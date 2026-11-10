"""Victoria's dated cards, with disclosed owner-authorized venue associations.

Explicit occurrence locations take precedence. Ben authorized educated venue
associations on 2026-11-10: the three reviewed council/skating occurrences below
can use official venue evidence, labeled as inferred rather than printed on the
event card. No generic town-office default or future recurrence is generated.
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

SOURCE_KEY = 'victoria_town_calendar_va'
CALENDAR = FEED_URL = 'https://victoriava.net/calendar-of-events'
TIMEZONE = 'America/New_York'
MAX_DOCUMENT = 1_000_000
MAX_CARDS = 100
MAX_SECONDS = 20
LOOKAHEAD_DAYS = 60
_DATE_TIME = re.compile(r'\d{1,2}/\d{1,2}/20\d{2} - (?:[1-9]|1[0-2]):[0-5]\d [AP]M', re.I)
_LOCATION = re.compile(
    r'Location:\s*(?:(?P<name>[^,\n]{1,120}),\s*)?'
    r'(?P<street>[1-9]\d{0,5}\s+[^,\n]{3,120}),\s*'
    r'(?P<city>[A-Za-z][A-Za-z .\'-]{1,70}),\s*VA'
    r'(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?', re.I)
_PRIVATE = re.compile(r'\b(?:private (?:event|party|function)|members?[ -]+only|invitation[ -]+only)\b', re.I)
ASSOCIATION_METHOD = 'owner_authorized_inferred_venue_association'

# Reviewed 2026-11-10. Dates and clocks remain mandatory facts from the current
# calendar response. These values only fence which already-listed occurrences
# may receive an educated association; they never create an event themselves.
_ASSOCIATION_OCCURRENCES = {
    'victoria_calendar:32309': ('Town Council Meeting', '2026-11-10', '19:00', '20:00', 'council'),
    'victoria_calendar:32320': ('Town Council Meeting', '2026-12-08', '19:00', '20:00', 'council'),
    'victoria_calendar:36080': ('Skate Night', '2026-11-20', '18:00', '21:30', 'skating'),
}
_ASSOCIATION_VENUES = {
    'council': {
        'venue_name': 'Victoria Municipal Building',
        'venue_address': '1809 Main Street, Victoria, VA 23974',
        'evidence_urls': [
            'https://www.victoriava.net/documents/290/Agenda-October_2026.pdf',
            'https://victoriava.net/documents/290/Town_of_Victoria_2024_CCR_06.20.25.pdf',
        ],
        'disclosure': "Venue inferred from the town's regular council meeting location; "
                      'the current calendar entry does not specify a venue.',
    },
    'skating': {
        'venue_name': 'Victoria-Lunenburg Community Centre',
        'venue_address': '1421 6th Street, Victoria, VA 23974',
        'evidence_urls': [
            'https://victoriava.net/community-centers',
            'https://www.victoriava.net/news-detail?item_id=34448',
        ],
        'disclosure': "Venue inferred from the town's official directory and a previous Skate Night announcement; "
                      'the current calendar entry does not specify a venue.',
    },
}


class EventHold(ValueError):
    pass


def _text(tag):
    return plain(tag.get_text(' ', strip=True))


def _note(diagnostics, disposition, identity, reason, **facts):
    diagnostics.setdefault(disposition, []).append(
        {'id': identity, 'reason': reason, 'event_url': CALENDAR,
         'disposition': disposition, **facts})


def _instant(value):
    if not _DATE_TIME.fullmatch(value):
        raise EventHold('publisher_schedule_unresolved')
    try:
        wall = datetime.strptime(value.upper(), '%m/%d/%Y - %I:%M %p')
        return timestamp(wall.isoformat(), TIMEZONE)
    except (ValueError, OverflowError) as error:
        raise EventHold('publisher_schedule_unresolved') from error


def _venue(card, *, identity, title, start, end, allow_inferred_venues):
    # A narrowly labeled, complete address in this actual occurrence card can
    # support future cards. General source contact data is never consulted.
    labels = [_text(tag) for tag in card.select('p, address')
              if _text(tag).casefold().startswith('location:')]
    if labels:
        if len(labels) != 1 or not (match := _LOCATION.fullmatch(labels[0])):
            raise EventHold('event_venue_unreviewed')
        name, street, city, zipcode = (match.group(key) for key in ('name', 'street', 'city', 'zip'))
        address = f'{street}, {city}, VA' + (' ' + zipcode if zipcode else '')
        return name or street, address, city, None, None
    expected = _ASSOCIATION_OCCURRENCES.get(identity) if allow_inferred_venues is True else None
    if (expected is None or (title, start.date().isoformat(), start.strftime('%H:%M'), end.strftime('%H:%M')) != expected[:4]
            or end.date() != start.date()
            or re.search(r'\b(?:Location|Venue)\s*:|\b(?:moved to|relocated|new location|off[ -]site)\b',
                         _text(card), re.I)):
        raise EventHold('event_venue_unreviewed')
    reviewed = _ASSOCIATION_VENUES[expected[4]]
    association = {
        'method': ASSOCIATION_METHOD, 'evidence_urls': list(reviewed['evidence_urls']),
        'matched_activity': title, 'venue_name': reviewed['venue_name'],
        'venue_address': reviewed['venue_address'],
    }
    return (reviewed['venue_name'], reviewed['venue_address'], 'Victoria',
            association, reviewed['disclosure'])


def parse(payload, *, now=None, diagnostics=None, allow_inferred_venues=False):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('victoria_now_timezone_missing')
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('victoria_document_limit')
    diagnostics = diagnostics if diagnostics is not None else {}
    soup = BeautifulSoup(payload, 'html.parser')
    canonical, main = soup.select_one('link[rel=canonical]'), soup.select_one('main#site_main')
    listing = main.select_one('#events_listing') if main else None
    if (not canonical or canonical.get('href') != CALENDAR or not main or not listing
            or [_text(h) for h in main.select('h1')] != ['Calendar of Events']
            or [_text(h) for h in listing.select('h2')] != ['Upcoming Events']):
        raise ValueError('victoria_listing_structure_unverified')
    if listing.select('[rel~=next], .pagination, [data-next-page]'):
        raise ValueError('victoria_pagination_requires_review')
    cards = listing.find_all('div', class_='item', recursive=False)
    if len(cards) > MAX_CARDS or len(cards) != len(listing.select('.item')):
        raise ValueError('victoria_listing_count_unverified')
    if not cards and not re.search(r'\bno (?:upcoming )?events\b', _text(listing), re.I):
        raise ValueError('victoria_listing_empty_unverified')
    diagnostics['cards'] = len(cards)
    rows, seen = [], set()
    for card in cards:
        source_id = card.get('id', '')
        if not re.fullmatch(r'item_[1-9]\d{0,11}', source_id) or source_id in seen:
            raise ValueError('victoria_event_identity_unverified')
        seen.add(source_id)
        identity = 'victoria_calendar:' + source_id.removeprefix('item_')
        facts = {}
        try:
            titles, schedules = card.select('h3'), card.select('p.small')
            if len(titles) != 1 or len(schedules) != 1 or not _text(titles[0]):
                raise EventHold('publisher_card_structure_unverified')
            raw_title = _text(titles[0])
            schedule = _text(schedules[0])
            match = re.fullmatch(r'Begins:\s*(.+?)\s+Ends:\s*(.+)', schedule)
            if not match:
                raise EventHold('publisher_schedule_unresolved')
            start, end = _instant(match[1]), _instant(match[2])
            if not start < end <= start + timedelta(days=7):
                raise EventHold('publisher_time_conflict')
            facts = {'starts_at': start.isoformat(), 'ends_at': end.isoformat()}
            if start > now + timedelta(days=LOOKAHEAD_DAYS) or end <= now:
                _note(diagnostics, 'excluded', identity, 'outside_window', **facts)
                continue
            text = _text(card)
            if len(text) > 30_000:
                raise EventHold('publisher_card_text_limit')
            if _PRIVATE.search(text):
                _note(diagnostics, 'excluded', identity, 'nonpublic_event', **facts)
                continue
            if re.search(r'\b(?:online[ -]only|virtual meeting|via Zoom)\b', text, re.I):
                _note(diagnostics, 'excluded', identity, 'virtual_event', **facts)
                continue
            title = re.sub(r'^(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', raw_title, flags=re.I)
            venue, address, city, association, disclosure = _venue(
                card, identity=identity, title=title, start=start, end=end,
                allow_inferred_venues=allow_inferred_venues)
            narrative = '\n\n'.join(_text(tag) for tag in card.find_all('p', recursive=False)
                                      if tag not in schedules and not _text(tag).casefold().startswith('location:'))[:2000]
            if association is not None:
                # Keep the disclosure visible even when the source has no prose.
                narrative = disclosure + ('\n\n' + narrative[:2000 - len(disclosure) - 2] if narrative else '')
            row = record(title, start.isoformat(), end.isoformat(), venue, address, city,
                         CALENDAR, identity, tz=TIMEZONE, retain_until_end=True)
            if row:
                row.update(timezone=TIMEZONE,
                           description=optional_description(SOURCE_KEY, identity, narrative),
                           location_provenance=ASSOCIATION_METHOD if association is not None else 'publisher_event_address_pending_geocode',
                           publisher_categories=[])
                if association is not None:
                    row['venue_association'] = association
                    _note(diagnostics, 'inferred', identity, ASSOCIATION_METHOD, **facts)
                if status := re.match(r'^(cancelled|canceled|postponed)\s*[:–—-]', raw_title, re.I):
                    row['publisher_status'] = status[1].casefold().replace('canceled', 'cancelled')
                attach(row, SOURCE_KEY)
                rows.append(row)
        except EventHold as error:
            _note(diagnostics, 'held', identity, str(error), **facts)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', TIMEZONE):
        raise ValueError('unregistered_victoria_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    payload = fetch(CALENDAR, 'text/html')
    diagnostics = {}
    version = source.get('venue_association_contract_version')
    rows = parse(payload, now=now, diagnostics=diagnostics,
                 allow_inferred_venues=type(version) is int and version == 1)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    for disposition in ('held', 'excluded', 'inferred'):
        for item in diagnostics.get(disposition, []):
            print(json.dumps({'event': 'victoria_' + disposition, 'source_key': SOURCE_KEY, **item}), file=sys.stderr)
    print(json.dumps({'event': 'victoria_normalized', 'source_key': SOURCE_KEY,
                      'cards': diagnostics.get('cards', 0), 'records': len(rows),
                      'held': len(diagnostics.get('held', [])),
                      'inferred': len(diagnostics.get('inferred', [])),
                      'excluded': len(diagnostics.get('excluded', []))}), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('victoria_event_venue_unreviewed')
    return rows
