"""Victoria's explicitly dated municipal event cards, with event-scoped venues.

Current cards have publisher IDs and clocks but no locations. Those cards stay
held. Neither a Town Office footer, a previous meeting, an old skating article,
nor a parade registration address supplies a current occurrence's venue.
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


def _venue(card):
    # A narrowly labeled, complete address in this actual occurrence card can
    # support future cards. General source contact data is never consulted.
    labels = [_text(tag) for tag in card.select('p, address')
              if _text(tag).casefold().startswith('location:')]
    if len(labels) != 1 or not (match := _LOCATION.fullmatch(labels[0])):
        raise EventHold('event_venue_unreviewed')
    name, street, city, zipcode = (match.group(key) for key in ('name', 'street', 'city', 'zip'))
    address = f'{street}, {city}, VA' + (' ' + zipcode if zipcode else '')
    return name or street, address, city


def parse(payload, *, now=None, diagnostics=None):
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
            venue, address, city = _venue(card)
            title = re.sub(r'^(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', raw_title, flags=re.I)
            narrative = '\n\n'.join(_text(tag) for tag in card.find_all('p', recursive=False)
                                      if tag not in schedules and not _text(tag).casefold().startswith('location:'))[:2000]
            row = record(title, start.isoformat(), end.isoformat(), venue, address, city,
                         CALENDAR, identity, tz=TIMEZONE, retain_until_end=True)
            if row:
                row.update(timezone=TIMEZONE,
                           description=optional_description(SOURCE_KEY, identity, narrative),
                           location_provenance='publisher_event_address_pending_geocode',
                           publisher_categories=[])
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
    rows = parse(payload, now=now, diagnostics=diagnostics)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    for disposition in ('held', 'excluded'):
        for item in diagnostics.get(disposition, []):
            print(json.dumps({'event': 'victoria_' + disposition, 'source_key': SOURCE_KEY, **item}), file=sys.stderr)
    print(json.dumps({'event': 'victoria_normalized', 'source_key': SOURCE_KEY,
                      'cards': diagnostics.get('cards', 0), 'records': len(rows),
                      'held': len(diagnostics.get('held', [])),
                      'excluded': len(diagnostics.get('excluded', []))}), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('victoria_event_venue_unreviewed')
    return rows
