"""Vance Arts' public TEC cards and their linked event details.

Printed local dates/clocks are checked in both representations. The publisher's
concert currently labels the same wall clock UTC in JSON-LD; only a matching
visible schedule and complete North Carolina event venue justify local Eastern
time. Every other schedule discrepancy is held. Parade mailing/lineup addresses
are never interpreted as venue metadata.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach, optional_description

SOURCE_KEY = 'vance_county_arts_council_nc'
CALENDAR = FEED_URL = 'https://vanceartscouncil.com/events/'
TIMEZONE = 'America/New_York'
MAX_DOCUMENT = 2_000_000
MAX_CARDS = 20
MAX_SECONDS = 30
LOOKAHEAD_DAYS = 60
_EVENT = re.compile(r'https://vanceartscouncil\.com/event/[a-z0-9]+(?:-[a-z0-9]+)*/')
_PHOTO = re.compile(r'https://vanceartscouncil\.com/wp-content/uploads/20\d{2}/(?:0[1-9]|1[0-2])/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,180}\.(?:jpe?g|png|webp)', re.I)
_CLOCK = r'(?:[1-9]|1[0-2]):[0-5]\d\s*[ap]m'
_DAY_CLOCK = re.compile(r'([A-Za-z]+ \d{1,2}, 20\d{2})\s*@\s*(' + _CLOCK + ')', re.I)
_PRIVATE = re.compile(r'\b(?:private (?:event|party|function)|members?[ -]+only|invitation[ -]+only)\b', re.I)


class EventHold(ValueError):
    pass


def event_url(value):
    return value if isinstance(value, str) and _EVENT.fullmatch(value) else None


def photo_url(value):
    if not isinstance(value, str) or '..' in value or not _PHOTO.fullmatch(value):
        return None
    if re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', value, re.I):
        return None
    return value


def _text(tag):
    return plain(tag.get_text(' ', strip=True))


def _document(payload):
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('vance_document_limit')
    return BeautifulSoup(payload, 'html.parser')


def _json_events(soup):
    scripts = soup.select('script[type="application/ld+json"]')
    if not 1 <= len(scripts) <= 10:
        raise ValueError('vance_structured_events_unverified')
    events = {}
    for script in scripts:
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError) as error:
            raise ValueError('vance_structured_events_unverified') from error
        values = data if isinstance(data, list) else data.get('@graph', [data]) if isinstance(data, dict) else []
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError('vance_structured_events_unverified')
        for item in values:
            if not isinstance(item, dict) or item.get('@type') != 'Event':
                continue
            url = event_url(item.get('url'))
            if not url or url in events:
                raise ValueError('vance_event_identity_unverified')
            events[url] = item
    if len(events) > MAX_CARDS:
        raise ValueError('vance_source_record_limit')
    return events


def _schedule(container):
    starts = container.select('.tribe-event-date-start')
    end_dates = container.select('.tribe-event-date-end')
    end_clocks = container.select('.tribe-event-time')
    if len(starts) != 1 or len(end_dates) > 1 or len(end_clocks) > 1 or (end_dates and end_clocks):
        raise EventHold('publisher_schedule_unresolved')
    try:
        match = _DAY_CLOCK.fullmatch(_text(starts[0]))
        if not match:
            raise EventHold('publisher_schedule_unresolved')
        start_wall = datetime.strptime(match[1] + ' ' + match[2].upper(), '%B %d, %Y %I:%M %p')
        start = timestamp(start_wall.isoformat(), TIMEZONE)
        end = None
        if end_dates:
            match = _DAY_CLOCK.fullmatch(_text(end_dates[0]))
            if not match:
                raise EventHold('publisher_schedule_unresolved')
            end_wall = datetime.strptime(match[1] + ' ' + match[2].upper(), '%B %d, %Y %I:%M %p')
            end = timestamp(end_wall.isoformat(), TIMEZONE)
        elif end_clocks:
            text = _text(end_clocks[0])
            if not re.fullmatch(_CLOCK, text, re.I):
                raise EventHold('publisher_schedule_unresolved')
            clock = datetime.strptime(text.upper(), '%I:%M %p').time()
            end = timestamp(datetime.combine(start.date(), clock).isoformat(), TIMEZONE)
        if end is not None and not start < end <= start + timedelta(days=7):
            raise EventHold('publisher_time_conflict')
        return start, end
    except (ValueError, OverflowError) as error:
        if isinstance(error, EventHold):
            raise
        raise EventHold('publisher_schedule_unresolved') from error


def _structured_schedule(item, start, end):
    discrepancy = False
    for field, printed in (('startDate', start), ('endDate', end)):
        value = item.get(field)
        if printed is None and value in (None, ''):
            continue
        if printed is None or not isinstance(value, str):
            raise EventHold('publisher_schedule_conflict')
        try:
            structured = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as error:
            raise EventHold('publisher_schedule_conflict') from error
        if (structured.tzinfo is None or structured.utcoffset() is None
                or structured.replace(tzinfo=None) != printed.replace(tzinfo=None)):
            raise EventHold('publisher_schedule_conflict')
        if structured != printed:
            if structured.utcoffset() != timedelta(0):
                raise EventHold('publisher_schedule_conflict')
            discrepancy = True
    return discrepancy


def _listing(payload):
    soup = _document(payload)
    containers = soup.select('.tribe-events-view--list')
    if len(containers) != 1:
        raise ValueError('vance_listing_structure_unverified')
    container = containers[0]
    next_links = container.select('.tribe-events-c-nav__next')
    if len(next_links) != 1 or next_links[0].name != 'button' or not next_links[0].has_attr('disabled'):
        raise ValueError('vance_pagination_requires_review')
    cards = container.select('article.tribe-events-calendar-list__event')
    if len(cards) > MAX_CARDS:
        raise ValueError('vance_source_record_limit')
    if not cards:
        if re.search(r'\bno (?:upcoming )?events\b', _text(container), re.I):
            return []
        raise ValueError('vance_listing_empty_unverified')
    structured = _json_events(soup)
    manifest, urls, ids = [], set(), set()
    for card in cards:
        links = card.select('.tribe-events-calendar-list__event-title-link')
        identifiers = [value.removeprefix('post-') for value in card.get('class', [])
                       if re.fullmatch(r'post-[1-9]\d{0,11}', value)]
        if (len(links) != 1 or len(identifiers) != 1
                or 'status-publish' not in card.get('class', [])):
            raise ValueError('vance_event_identity_unverified')
        url, identity = event_url(links[0].get('href')), 'vance_arts:' + identifiers[0]
        if not url or url in urls or identity in ids or url not in structured:
            raise ValueError('vance_event_identity_unverified')
        urls.add(url)
        ids.add(identity)
        manifest.append((identity, url, _text(links[0]), card, structured[url]))
    if urls != set(structured):
        raise ValueError('vance_manifest_mismatch')
    return manifest


def _venue(container, item):
    groups = container.select('.tribe-events-meta-group-venue')
    if len(groups) != 1:
        raise EventHold('event_venue_unreviewed')
    def one(selector):
        found = groups[0].select(selector)
        return _text(found[0]) if len(found) == 1 else ''
    venue, street, city, region, zipcode = (one(selector) for selector in (
        '.tribe-venue', '.tribe-street-address', '.tribe-locality', '.tribe-region', '.tribe-postal-code'))
    if (not venue or not re.fullmatch(r'[1-9]\d{0,5}\s+.{3,120}', street)
            or not city or region != 'NC' or not re.fullmatch(r'\d{5}(?:-\d{4})?', zipcode)):
        raise EventHold('event_venue_unreviewed')
    location = item.get('location')
    address = location.get('address') if isinstance(location, dict) else None
    if not isinstance(address, dict) or plain(location.get('name')).casefold() != venue.casefold():
        raise EventHold('publisher_venue_conflict')
    for key, expected in (('streetAddress', street), ('addressLocality', city),
                          ('addressRegion', region), ('postalCode', zipcode)):
        if plain(address.get(key)).casefold() != expected.casefold():
            raise EventHold('publisher_venue_conflict')
    return venue, f'{street}, {city}, {region} {zipcode}', city


def _detail(payload, identity, url, title, expected_start, expected_end, listing_item):
    soup = _document(payload)
    content = soup.select_one('#tribe-events-content.tribe-events-single')
    headings = content.select('.tribe-events-single-event-title') if content else []
    canonical = soup.select_one('link[rel=canonical]')
    if (not content or not soup.body or 'postid-' + identity.split(':')[1] not in soup.body.get('class', [])
            or len(headings) != 1 or _text(headings[0]) != title
            or (canonical and canonical.get('href') != url)):
        raise ValueError('vance_event_detail_mismatch')
    events = _json_events(soup)
    if set(events) != {url} or plain(events[url].get('name')) != title:
        raise ValueError('vance_event_detail_mismatch')
    item = events[url]
    schedules = content.select('.tribe-events-schedule')
    if len(schedules) != 1:
        raise EventHold('publisher_schedule_unresolved')
    start, end = _schedule(schedules[0])
    if (start, end) != (expected_start, expected_end):
        raise EventHold('publisher_schedule_conflict')
    discrepancy = _structured_schedule(item, start, end)
    if item.get('eventAttendanceMode') not in ('https://schema.org/OfflineEventAttendanceMode',
                                             'https://schema.org/MixedEventAttendanceMode'):
        raise EventHold('nonphysical_event')
    statuses = {'https://schema.org/EventScheduled': 'scheduled',
                'https://schema.org/EventCancelled': 'cancelled',
                'https://schema.org/EventPostponed': 'postponed'}
    status = statuses.get(item.get('eventStatus'))
    if not status or listing_item.get('eventStatus') != item.get('eventStatus'):
        raise EventHold('publisher_status_conflict')
    descriptions = content.select('.tribe-events-single-event-description')
    if len(descriptions) > 1:
        raise EventHold('publisher_description_structure_unverified')
    narrative = _text(descriptions[0]) if descriptions else ''
    if len(narrative) > 30_000:
        raise EventHold('publisher_card_text_limit')
    if _PRIVATE.search(title + ' ' + narrative):
        raise EventHold('nonpublic_event')
    venue, address, city = _venue(content, item)
    # No costs are inferred from prose, parade entry fees, mailing instructions,
    # or an offer numeric zero. Use the event's visible Cost metadata only.
    costs = content.select('.tribe-events-event-cost')
    facts = {'cost': _text(costs[0])[:400]} if len(costs) == 1 and _text(costs[0]) else {}
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue, address, city, url, identity, tz=TIMEZONE, retain_until_end=True)
    if row:
        row.update(timezone=TIMEZONE,
                   description=optional_description(SOURCE_KEY, identity, narrative[:2000]),
                   location_provenance='publisher_event_address_pending_geocode',
                   publisher_status=status,
                   publisher_categories=[_text(a) for a in content.select('.tribe-events-event-categories a')][:5])
        candidate = item.get('image') if item.get('image') == listing_item.get('image') else None
        attach(row, SOURCE_KEY, facts=facts, candidate=photo_url(candidate))
    return row, discrepancy


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', TIMEZONE):
        raise ValueError('unregistered_vance_source')
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('vance_now_timezone_missing')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    def check():
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
    def note(disposition, identity, url, reason):
        print(json.dumps({'event': 'vance_' + disposition, 'source_key': SOURCE_KEY,
                          'id': identity, 'event_url': url, 'disposition': disposition,
                          'reason': reason}), file=sys.stderr)
    check()
    manifest = _listing(fetch(CALENDAR, 'text/html'))
    check()
    rows, held, excluded = [], 0, 0
    for identity, url, title, card, item in manifest:
        check()
        try:
            if not title or plain(item.get('name')) != title:
                raise EventHold('publisher_title_conflict')
            start, end = _schedule(card)
            dates = card.select('time.tribe-events-calendar-list__event-datetime')
            if len(dates) != 1 or dates[0].get('datetime') != start.date().isoformat():
                raise EventHold('publisher_schedule_conflict')
            discrepancy = _structured_schedule(item, start, end)
            if start > now + timedelta(days=LOOKAHEAD_DAYS) or (end or start + timedelta(hours=3)) <= now:
                excluded += 1
                note('excluded', identity, url, 'outside_window')
                continue
            row, detail_discrepancy = _detail(fetch(url, 'text/html'), identity, url, title, start, end, item)
            check()
            if row:
                if discrepancy or detail_discrepancy:
                    note('warning', identity, url, 'publisher_utc_default_visible_local_verified')
                rows.append(row)
        except EventHold as error:
            held += 1
            note('held', identity, url, str(error))
    print(json.dumps({'event': 'vance_normalized', 'source_key': SOURCE_KEY,
                      'cards': len(manifest), 'records': len(rows), 'held': held,
                      'excluded': excluded}), file=sys.stderr)
    if not rows and held:
        raise ValueError('vance_event_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
