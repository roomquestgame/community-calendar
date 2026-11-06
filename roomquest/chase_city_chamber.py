"""One allowed, public Chase City calendar page; no JSON/ICS export requests.

Event dates come from the publisher's calendar links and must agree with the
visible schedule. All list cards are accounted for. Unknown pagination fails
into review, and unresolved event venues are held without a publisher-office pin.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach, image_url

SOURCE_KEY = 'chase_city_chamber_va'
CALENDAR = 'https://chasecitychamber.com/upcoming-events'
TIMEZONE = 'America/New_York'
MAX_CARDS = 100
MAX_SECONDS = 20
MAX_DESCRIPTION = 2000
LOOKAHEAD_DAYS = 60

# Reviewed from this exact event's flyer, not from the organization's address.
# The HTML footer separately identifies the named Estes Center's street address.
# All bindings must still match; this is not a reusable default venue.
AWARDS_URL = CALENDAR + '/chase-city-chamber-of-commerce-awards-cocktail-party'
AWARDS_TITLE = 'Chase City Chamber of Commerce Awards Cocktail Party'
AWARDS_IMAGE = ('https://images.squarespace-cdn.com/content/v1/64921bef4a756810ab11ec54/'
                '4760210d-377d-4a14-b2b2-254836e42004/'
                'Chamber+Cocktail+Party+%285.4+x+4.2+in%29+%281%29.png')
AWARDS_START = '2026-11-06T23:00:00+00:00'
AWARDS_END = '2026-11-07T00:30:00+00:00'
AWARDS_DESCRIPTION = ("Estes Center Banquet Room.\n"
                      "Heavy hors d'oeuvres and beverages included.\n"
                      "Please RSVP by October 30.\n$25 per person.")


class EventHold(ValueError):
    """An identified event needs review; no replacement facts are guessed."""


def _log(kind, **fields):
    print(json.dumps({'event': 'chase_city_' + kind, 'source_key': SOURCE_KEY,
                      **fields}, sort_keys=True), file=sys.stderr)


def _narrative(element):
    soup = BeautifulSoup(str(element or ''), 'html.parser')
    for tag in soup.select('script, style, template, noscript'):
        tag.decompose()
    return '\n'.join(line.strip() for line in soup.get_text('\n').splitlines()
                     if line.strip())[:MAX_DESCRIPTION]


def _context(soup):
    matches = []
    for script in soup.select('script'):
        text = script.get_text()
        match = re.search(r'\bStatic\.SQUARESPACE_CONTEXT\s*=\s*', text)
        if match:
            matches.append(json.JSONDecoder().raw_decode(text[match.end():])[0])
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError('unsupported_chase_city_payload')
    data = matches[0]
    collection = data.get('collection') or {}
    if ((data.get('website') or {}).get('timeZone') != TIMEZONE
            or collection.get('id') != '6492254218db692df7b9aa7a'
            or collection.get('fullUrl') != '/upcoming-events'
            or collection.get('permissionType') != 1):
        raise ValueError('chase_city_calendar_identity_changed')


def _times(card):
    export = card.select_one('a.eventlist-meta-export-google[href]')
    if export is None:
        raise ValueError('event_time_missing')
    parsed = urlsplit(export['href'])
    query = parse_qs(parsed.query)
    if (parsed.scheme not in ('https', 'http') or parsed.hostname != 'www.google.com'
            or parsed.path != '/calendar/event' or query.get('action') != ['TEMPLATE']
            or len(query.get('dates', [])) != 1):
        raise ValueError('publisher_calendar_link_changed')
    dates = query['dates'][0]
    if re.fullmatch(r'\d{8}/\d{8}', dates):
        return None, None, query  # Explicit all-day event; no invented hours.
    if not re.fullmatch(r'\d{8}T\d{6}Z/\d{8}T\d{6}Z', dates):
        raise ValueError('event_time_missing')
    start, end = [datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                  for value in dates.split('/')]
    if end <= start:
        raise EventHold('invalid_event_end')
    return start, end, query


def _check_visible_times(card, start, end):
    for label, value in (('start', start), ('end', end)):
        node = card.select_one('time.event-time-localized-' + label)
        try:
            local = value.astimezone(ZoneInfo(TIMEZONE))
            shown = datetime.strptime(' '.join(node.get_text().split()), '%I:%M %p').time()
            if node.get('datetime') != local.date().isoformat() or shown != local.time():
                raise ValueError()
        except (AttributeError, TypeError, ValueError):
            raise EventHold('publisher_schedule_conflict') from None


def _image(card):
    candidates = set()
    for tag in card.select('.eventlist-description img, .eventlist-column-thumbnail img'):
        raw = tag.get('data-src') or tag.get('src')
        if candidate := image_url(raw, 'chase_city_chamber'):
            candidates.add(candidate)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _venue(card, query, *, url, title, start, end, candidate, page_text):
    node = card.select_one('.eventlist-meta-address')
    venue = re.sub(r'\s*\(map\)\s*$', '', node.get_text(' ', strip=True)).strip() if node else ''
    locations = query.get('location', [])
    if len(locations) > 1:
        raise EventHold('conflicting_event_venue')
    address = plain(locations[0]) if locations else ''
    reviewed = (url == AWARDS_URL and title == AWARDS_TITLE and candidate == AWARDS_IMAGE
                and start.isoformat() == AWARDS_START and end.isoformat() == AWARDS_END)
    if reviewed:
        if ((venue and venue != 'Estes Center Banquet Room')
                or (address and address != '316 N Main St, Chase City, VA')):
            raise EventHold('conflicting_event_venue')
        if ('316 N Main St, Chase City, VA' not in page_text
                or '(inside the Estes Community Center)' not in page_text):
            raise EventHold('reviewed_event_venue_evidence_changed')
        return ('Estes Center Banquet Room', '316 N Main St, Chase City, VA', 'Chase City',
                'reviewed_event_flyer_and_matched_venue_address', True)
    locality = re.search(r',\s*([^,]+),\s*([A-Z]{2})\b', address)
    if (not venue or not re.search(r'\b\d{1,6}\s+[A-Za-z]', address) or not locality):
        raise EventHold('event_venue_unreviewed')
    return venue, address, locality[1].strip(), 'publisher_event_address_pending_geocode', False


def parse(payload, *, now=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('chase_city_now_timezone_missing')
    soup = BeautifulSoup(payload, 'html.parser')
    _context(soup)
    for anchor in soup.select('a[href]'):
        link = urlsplit(urljoin(CALENDAR, anchor['href']))
        if (link.hostname == 'chasecitychamber.com' and link.path == '/upcoming-events'
                and any(key in parse_qs(link.query) for key in ('offset', 'page', 'reversePaginate'))):
            raise ValueError('pagination_requires_review')
    cards = soup.select('article.eventlist-event')
    if len(cards) > MAX_CARDS:
        raise ValueError('source_record_limit')
    if not cards and not soup.select_one('.eventlist'):
        raise ValueError('unsupported_chase_city_payload')
    page_text = soup.get_text(' ', strip=True)
    records, seen, held, excluded = [], {}, 0, 0
    for card in cards:
        link = card.select_one('a.eventlist-title-link[href]')
        if link is None:
            raise ValueError('event_identity_missing')
        title = plain(link.get_text())
        url = urljoin(CALENDAR, link['href'])
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'chasecitychamber.com'
                or not re.fullmatch(r'/upcoming-events/[a-z0-9-]+/?', parsed.path)
                or parsed.query or parsed.fragment):
            raise ValueError('invalid_event_link')
        identity = 'chase_city:' + sha256(url.encode()).hexdigest()[:32]
        narrative = _narrative(card.select_one('.eventlist-description'))
        if re.search(r'\b(?:cancelled|canceled|postponed|closed|closure|members?[\s-]+only|'
                     r'private\s+(?:event|party|function)|invitation[\s-]+only)\b',
                     title + ' ' + narrative, re.I):
            excluded += 1
            continue
        try:
            start, end, query = _times(card)
            if start is None or start > current + timedelta(days=LOOKAHEAD_DAYS) or end <= current:
                continue
            if not title or title == 'Untitled Event' or query.get('text') != [title]:
                raise EventHold('publisher_event_identity_conflict')
            _check_visible_times(card, start, end)
            candidate = _image(card)
            venue, address, city, provenance, reviewed = _venue(
                card, query, url=url, title=title, start=start, end=end,
                candidate=candidate, page_text=page_text)
            row = record(title, start.isoformat(), end.isoformat(), venue, address,
                         city, url, identity, tz=TIMEZONE, retain_until_end=True)
            if row is None:
                continue
            row['timezone'] = TIMEZONE
            row['description'] = narrative or (AWARDS_DESCRIPTION if reviewed else '')
            row['location_provenance'] = provenance
            row['publisher_categories'] = []
            facts = {'cost': '$25 per person'} if reviewed else {}
            attach(row, SOURCE_KEY, facts=facts, candidate=candidate, evidence_url=CALENDAR)
            key = (identity, row['starts_at'])
            if key in seen:
                if seen[key] != row:
                    raise ValueError('conflicting_event_occurrence')
                continue
            seen[key] = row
            records.append(row)
        except EventHold as exc:
            held += 1
            _log('event_held', identity=identity, reason=str(exc))
    _log('normalized', upstream_cards=len(cards), held=held, excluded=excluded, records=len(records))
    if not records and held:
        raise ValueError('chase_city_event_evidence_unavailable')
    return sorted(records, key=lambda item: (item['starts_at'], item['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'):
        raise ValueError('unregistered_chase_city_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    payload = fetch(CALENDAR, 'text/html')
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    rows = parse(payload, now=now)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    return rows
