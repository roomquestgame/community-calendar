"""Shady Shack's explicitly listed SpotApps event cards.

Only this source has the owner's approved year rule: a yearless month/day uses
the venue's current year. An earlier month rolls into next year only when that
date is inside the ordinary 60-day New Year window. An explicit year always
wins, including on historical flyers. Every assumption is logged separately
from publisher facts; weekly labels never generate additional occurrences.

Markup was observed in the ordinary public browser page on 2026-11-10. All
collector network access still comes from the worker's guarded transport.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach, optional_description

SOURCE_KEY = 'shady_shack_bracey_va'
CALENDAR = 'https://shadyshackgrill.com/bracey-shady-shack-bar-and-grill-events'
FEED_URL = CALENDAR
TIMEZONE = 'America/New_York'
VENUE = 'Shady Shack Bar and Grill'
ADDRESS = '183 Hendricks Mill Rd, Bracey, VA 23919'
MAX_SECONDS = 20
MAX_DOCUMENT = 2_000_000
MAX_FACT_TEXT = 50_000
MAX_CARDS = 100
MAX_DESCRIPTION = 2000
LOOKAHEAD_DAYS = 60
YEAR_RULE = 'owner_authorized_current_year_with_bounded_new_year_rollover'
PHOTO_URL = re.compile(r'https://static\.spotapps\.co/spots/[0-9a-f]{2}/[0-9a-f]{30}/w926')
_MONTHS = {}
for _number, _name in enumerate('January February March April May June July August September October November December'.split(), 1):
    _MONTHS[_name.lower()] = _MONTHS[_name[:3].lower()] = _number
_WEEKDAYS = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split()
_DATE = re.compile(
    r'(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?'
    r'([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?', re.I)
_CLOCK = r'\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?'
_PRIVATE = re.compile(r'\b(?:private (?:event|party|function)|members?[ -]+only|invitation[ -]+only)\b', re.I)
_OFFSITE = re.compile(
    r'\b(?:Location|Venue):|\boff[ -]site\b|\brelocat(?:ed|ing|ion)\b|\bmoved? to\b|'
    r'\bnew location\b|\bonline[ -]only\b|\bvirtual event\b|\bvia Zoom\b', re.I)


class EventHold(ValueError):
    """An identified publisher card lacks a usable occurrence fact."""


def photo_url(value):
    """Only the observed event-image CDN shape; byte validation is separate."""
    return value if isinstance(value, str) and PHOTO_URL.fullmatch(value) else None


def _text(node):
    copy = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in copy.select('script, style, template, noscript, [hidden], [aria-hidden=true]'):
        tag.decompose()
    value = '\n'.join(line.strip() for line in copy.get_text('\n').splitlines() if line.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('shady_fact_text_limit')
    return value


def _note(diagnostics, disposition, identity, reason, **facts):
    diagnostics.setdefault(disposition, []).append(
        {'id': identity, 'reason': reason, 'event_url': CALENDAR, **facts})


def _day(value, current, diagnostics, identity):
    match = _DATE.fullmatch(plain(value))
    if not match or match[2].lower() not in _MONTHS:
        raise EventHold('publisher_date_unresolved')
    month = _MONTHS[match[2].lower()]
    local_today = current.astimezone(ZoneInfo(TIMEZONE)).date()
    inferred = match[4] is None
    year = int(match[4]) if not inferred else local_today.year
    try:
        day = date(year, month, int(match[3]))
        if inferred and month < local_today.month:
            next_year = date(local_today.year + 1, month, int(match[3]))
            if next_year <= local_today + timedelta(days=LOOKAHEAD_DAYS):
                day = next_year
                year = day.year
    except ValueError:
        raise EventHold('publisher_date_unresolved') from None
    if inferred:
        _note(diagnostics, 'year_assumptions', identity, YEAR_RULE,
              published_date=plain(value), assigned_year=year,
              reference_local_date=local_today.isoformat())
    if match[1] and _WEEKDAYS[day.weekday()].casefold() != match[1].casefold():
        if not inferred:
            raise EventHold('publisher_date_weekday_conflict')
        # The owner's year rule controls a yearless card. A printed weekday is
        # retained as a warning, never used to silently choose another year.
        _note(diagnostics, 'warnings', identity, 'weekday_differs_from_owner_assigned_year',
              published_weekday=match[1], assigned_date=day.isoformat())
    return day


def _times(day, value):
    match = re.fullmatch(rf'({_CLOCK})(?:\s*(?:[-–—]|to)\s*({_CLOCK}))?', plain(value), re.I)
    if not match:
        raise EventHold('publisher_time_unresolved')
    values = []
    for text in match.groups():
        if text is None:
            values.append(None)
            continue
        text = re.sub(r'[\s.]', '', text).upper()
        try:
            wall = datetime.strptime(text, '%I:%M%p' if ':' in text else '%I%p').time()
            values.append(timestamp(datetime.combine(day, wall).isoformat(), TIMEZONE))
        except ValueError:
            raise EventHold('publisher_time_unresolved') from None
    if values[1] is not None and values[1] <= values[0]:
        raise EventHold('publisher_time_conflict')
    return values


def _status(title, narrative):
    choices = set()
    prefix = re.match(r'^\s*(cancelled|canceled|postponed)\s*[:–—-]', title, re.I)
    if prefix:
        choices.add(prefix[1].lower().replace('canceled', 'cancelled'))
    choices.update(value.lower().replace('canceled', 'cancelled') for value in re.findall(
        r'^(?:Status:\s*)?(Scheduled|Cancelled|Canceled|Postponed)\s*$', narrative, re.I | re.M))
    if len(choices) > 1:
        raise EventHold('publisher_status_conflict')
    if choices:
        return choices.pop()
    if re.search(r'\b(?:cancelled|canceled|postponed)\b', narrative, re.I):
        raise EventHold('publisher_status_unresolved')
    return None


def _cards(payload):
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('shady_document_limit')
    soup = BeautifulSoup(payload, 'html.parser')
    mains = soup.select('main#content')
    if len(mains) != 1:
        raise ValueError('shady_listing_structure_unverified')
    headings = mains[0].select('h1')
    if len(headings) != 1 or plain(headings[0].get_text()).casefold() != 'events':
        raise ValueError('shady_listing_structure_unverified')
    container = headings[0].parent
    if container.name != 'div' or 'container' not in container.get('class', []):
        raise ValueError('shady_listing_structure_unverified')
    if mains[0].select('[rel~=next], .pagination, [data-next-page]'):
        raise ValueError('shady_pagination_requires_review')
    holders = container.find_all('div', class_='events-holder', recursive=False)
    if len(holders) > MAX_CARDS:
        raise ValueError('shady_source_record_limit')
    if not holders:
        if re.search(r'\bno (?:upcoming )?events\b', _text(container), re.I):
            return []
        raise ValueError('shady_listing_empty_unverified')
    cards = []
    for holder in holders:
        sections = holder.find_all('section', recursive=False)
        if len(sections) != 1 or not re.fullmatch(r'[1-9][0-9]{0,11}', sections[0].get('id', '')):
            raise ValueError('shady_card_identity_missing')
        cards.append(sections[0])
    if (len(mains[0].select('.events-holder')) != len(holders)
            or len(mains[0].select('.event-content')) != len(cards)):
        raise ValueError('shady_listing_structure_unverified')
    return cards


def parse(payload, *, now=None, diagnostics=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('shady_now_timezone_missing')
    diagnostics = diagnostics if diagnostics is not None else {}
    rows, seen = [], {}
    cards = _cards(payload)
    diagnostics['schedule_cards'] = len(cards)
    for card in cards:
        publisher_id = card['id']
        identity = 'shady_shack:' + publisher_id
        # Conflicting copies of one publisher ID cannot produce partial success.
        fingerprint = (str(card),)
        if publisher_id in seen:
            if seen[publisher_id] != fingerprint:
                raise ValueError('shady_conflicting_occurrence')
            continue
        seen[publisher_id] = fingerprint
        try:
            text_holders = card.select('.event-text-holder')
            if len(text_holders) != 1:
                raise EventHold('publisher_card_structure_unverified')
            text_holder = text_holders[0]
            headings = text_holder.select('h2')
            dates = text_holder.select('.event-day')
            clocks = text_holder.select('.event-time')
            infos = text_holder.select('.event-info-text')
            metadata = text_holder.select('[data-event-id]')
            if (len(headings) != 1 or len(dates) != 1 or len(clocks) != 1 or len(infos) != 1
                    or len(metadata) != 1 or metadata[0].get('data-event-id') != publisher_id):
                raise EventHold('publisher_card_structure_unverified')
            raw_title = plain(headings[0].get_text())
            title = re.sub(r'^\s*(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', raw_title, flags=re.I)
            if not title:
                raise EventHold('publisher_title_missing')
            narrative = _text(infos[0])
            card_text = _text(text_holder)
            status = _status(raw_title, narrative)
            if _PRIVATE.search(card_text):
                _note(diagnostics, 'excluded', identity, 'nonpublic_event')
                continue
            if _OFFSITE.search(card_text):
                raise EventHold('event_venue_unreviewed')
            day = _day(dates[0].get_text(' ', strip=True), current, diagnostics, identity)
            # SpotApps supplies an occurrence ID, not a series expansion rule.
            # Including its published/owner-resolved local day also prevents a
            # reused card ID from merging separately listed calendar dates.
            occurrence_id = f'{identity}:{day.isoformat()}'
            start, end = _times(day, clocks[0].get_text(' ', strip=True))
            if start > current + timedelta(days=LOOKAHEAD_DAYS) or (end or start + timedelta(hours=3)) <= current:
                diagnostics['outside_window'] = diagnostics.get('outside_window', 0) + 1
                continue
            row = record(title, start.isoformat(), end.isoformat() if end else None,
                         VENUE, ADDRESS, 'Bracey', CALENDAR, occurrence_id,
                         tz=TIMEZONE, retain_until_end=True)
            if row is None:
                continue
            row.update(timezone=TIMEZONE,
                       description=optional_description(SOURCE_KEY, occurrence_id, narrative[:MAX_DESCRIPTION]),
                       location_provenance='publisher_reviewed_named_venue_and_address',
                       publisher_categories=[])
            if status:
                row['publisher_status'] = status
            candidates = {urljoin(CALENDAR, image.get('src', ''))
                          for image in card.select('.event-image-holder img.event-image[src]') if image.get('src')}
            candidate = next(iter(candidates)) if len(candidates) == 1 else None
            if candidates and (len(candidates) != 1 or not photo_url(candidate)):
                _note(diagnostics, 'warnings', identity, 'event_image_candidate_unverified')
            attach(row, SOURCE_KEY, candidate=photo_url(candidate))
            rows.append(row)
        except EventHold as error:
            _note(diagnostics, 'held', identity, str(error))
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_shady_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    payload = fetch(CALENDAR, 'text/html')
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    diagnostics = {}
    rows = parse(payload, now=now, diagnostics=diagnostics)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    print(json.dumps({'event': 'shady_shack_normalized', 'source_key': SOURCE_KEY,
                      'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('shady_event_evidence_unavailable')
    return rows
