"""Explicit performance dates in McGregor Hall's official show listing.

The listing supplies the year and separately lists every performance. A show
count, season heading, ticket link, or historical audition page never creates
an occurrence. The named hall address was reviewed on the publisher's own
/location-parking-and-directions page on 2026-11-10. Offsite notices are held.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach, optional_description

SOURCE_KEY = 'mcgregor_hall_henderson_nc'
CALENDAR = FEED_URL = 'https://www.mcgregorhall.org/shows-events'
TIMEZONE = 'America/New_York'
VENUE = 'McGregor Hall Performing Arts Center'
ADDRESS = '201 Breckenridge Street, Henderson, NC 27536'
MAX_DOCUMENT = 2_000_000
MAX_CARDS = 30
MAX_OCCURRENCES = 200
MAX_SECONDS = 20
LOOKAHEAD_DAYS = 60
_EVENT = re.compile(r'https://www\.mcgregorhall\.org/[a-z0-9][a-z0-9-]{0,140}')
_PHOTO = re.compile(
    r'https://irp\.cdn-website\.com/34057905/dms3rep/multi/'
    r'(?:[A-Za-z0-9_.()+-]|%20|%28|%29|%2[Bb]){1,180}\.(?:jpe?g|png|webp)', re.I)
_MONTHS = {name.casefold(): number for number, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
_WEEKDAYS = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split()
_DAY_PREFIX = re.compile(
    r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|'
    r'^[A-Za-z]{3,9}\.?\s+\d{1,2}\b|^\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}', re.I)
_SCHEDULE = re.compile(
    r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
    r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\s+'
    r'((?:[1-9]|1[0-2])(?::[0-5]\d)?\s*[ap]\.?m\.?)', re.I)
_PRIVATE = re.compile(r'\b(?:private (?:event|party|function)|members?[ -]+only|invitation[ -]+only)\b', re.I)
_OFFSITE = re.compile(r'\b(?:off[ -]site|relocated|moved to|new location|online[ -]only|virtual event|via Zoom)\b|\b(?:Location|Venue):', re.I)


class EventHold(ValueError):
    pass


def event_url(value):
    return value if isinstance(value, str) and _EVENT.fullmatch(value) and value != CALENDAR else None


def photo_url(value):
    # These are publisher-selected show artworks, including actual musical
    # logos. A blanket "logo" filename rule would discard Frozen's poster.
    return value if isinstance(value, str) and '..' not in value and _PHOTO.fullmatch(value) else None


def _text(tag):
    return plain(tag.get_text(' ', strip=True)).replace('\ufeff', '').strip()


def _audition_cta(paragraph):
    """Exclude only a standalone link to a separate audition information page."""
    links = paragraph.select('a[href]')
    return (len(links) == 1 and _text(paragraph) == _text(links[0])
            and re.fullmatch(r'Audition information is available here!', _text(links[0]), re.I)
            and re.fullmatch(r'https://www\.mcgregorhall\.org/[a-z0-9-]+-auditions-and-information',
                             urljoin(CALENDAR, links[0]['href'])) is not None)


def _note(diagnostics, disposition, identity, reason, url):
    diagnostics.setdefault(disposition, []).append(
        {'id': identity, 'reason': reason, 'event_url': url, 'disposition': disposition})


def _start(value):
    match = _SCHEDULE.fullmatch(value)
    if not match or match[2].casefold() not in _MONTHS:
        raise EventHold('publisher_schedule_unresolved')
    weekday, month, day, year, clock = match.groups()
    try:
        wall_day = datetime(int(year), _MONTHS[month.casefold()], int(day)).date()
        if _WEEKDAYS[wall_day.weekday()].casefold() != weekday.casefold():
            raise EventHold('publisher_date_weekday_conflict')
        clock = re.sub(r'[\s.]', '', clock).upper()
        wall_clock = datetime.strptime(clock, '%I:%M%p' if ':' in clock else '%I%p').time()
        return timestamp(datetime.combine(wall_day, wall_clock).isoformat(), TIMEZONE)
    except (ValueError, OverflowError) as error:
        if isinstance(error, EventHold):
            raise
        raise EventHold('publisher_schedule_unresolved') from error


def parse(payload, *, now=None, diagnostics=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('mcgregor_now_timezone_missing')
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('mcgregor_document_limit')
    diagnostics = diagnostics if diagnostics is not None else {}
    soup = BeautifulSoup(payload, 'html.parser')
    canonical, main = soup.select_one('link[rel=canonical]'), soup.select_one('#dm_content')
    if (not canonical or canonical.get('href') != CALENDAR or not main
            or not any(_text(h) == 'Shows & Events' for h in main.select('h1'))
            or not any(_text(h) == 'Upcoming performances at McGregor Hall' for h in main.select('h2'))):
        raise ValueError('mcgregor_listing_structure_unverified')
    if main.select('[rel~=next], .pagination, [data-next-page]'):
        raise ValueError('mcgregor_pagination_requires_review')
    links = [a for a in main.select('a[href]') if _text(a).casefold() == 'view event']
    if not 1 <= len(links) <= MAX_CARDS:
        raise ValueError('mcgregor_listing_count_unverified')
    diagnostics['cards'] = len(links)
    rows, seen_urls, seen_occurrences = [], set(), set()
    occurrence_count = 0
    for link in links:
        url = event_url(urljoin(CALENDAR, link['href']))
        card = link.find_parent('section')
        if (not url or not card or url in seen_urls
                or len([a for a in card.select('a[href]') if _text(a).casefold() == 'view event']) != 1):
            raise ValueError('mcgregor_event_identity_unverified')
        seen_urls.add(url)
        identity = 'mcgregor_hall:' + url.rsplit('/', 1)[1]
        try:
            headings = card.select('h3')
            if not headings or not _text(headings[0]):
                raise EventHold('publisher_title_missing')
            raw_title = _text(headings[0])
            title = re.sub(r'^(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', raw_title, flags=re.I)
            card_text = _text(card)
            if len(card_text) > 30_000:
                raise EventHold('publisher_card_text_limit')
            if _PRIVATE.search(card_text):
                _note(diagnostics, 'excluded', identity, 'nonpublic_event', url)
                continue
            if _OFFSITE.search(card_text):
                raise EventHold('event_venue_unreviewed')
            paragraphs = card.select('.dmNewParagraph p, .dmNewParagraph li')
            dated = []
            for group in card.select('.dmNewParagraph'):
                lines = group.select('p, li')
                if not any(_DAY_PREFIX.match(_text(node)) or re.fullmatch(
                        r'(?:[A-Za-z]+|\d+) Performances?:', _text(node), re.I) for node in lines):
                    continue
                # Once a paragraph widget is identified as the schedule, every
                # printed child must parse. Abbreviated/new date formats, TBD
                # entries or a second unknown line cannot silently disappear.
                dated.extend(_text(node) for node in lines if _text(node) and not re.fullmatch(
                    r'(?:[A-Za-z]+|\d+) Performances?:', _text(node), re.I))
            if not dated:
                raise EventHold('publisher_schedule_unresolved')
            # Account for every printed schedule line before emitting any row.
            starts = [_start(value) for value in dated]
            occurrence_count += len(starts)
            if occurrence_count > MAX_OCCURRENCES:
                raise ValueError('mcgregor_occurrence_limit')
            if len(set(starts)) != len(starts):
                raise ValueError('mcgregor_duplicate_occurrence')
            narrative = '\n\n'.join(_text(node) for node in paragraphs
                if node.name == 'p' and _text(node)
                and not _DAY_PREFIX.match(_text(node))
                and not _audition_cta(node)
                and not re.fullmatch(r'(?:[A-Za-z]+|\d+) Performances?:', _text(node), re.I))[:2000]
            images = {photo_url(image.get('data-dm-image-path')) for image in card.select('img')}
            images.discard(None)
            candidate = next(iter(images)) if len(images) == 1 else None
            status = re.match(r'^(cancelled|canceled|postponed)\s*[:–—-]', raw_title, re.I)
            for start in starts:
                occurrence = identity + ':' + start.strftime('%Y-%m-%dT%H:%M')
                if occurrence in seen_occurrences:
                    raise ValueError('mcgregor_duplicate_occurrence')
                seen_occurrences.add(occurrence)
                if start > now + timedelta(days=LOOKAHEAD_DAYS) or start + timedelta(hours=3) <= now:
                    _note(diagnostics, 'excluded', occurrence, 'outside_window', url)
                    continue
                row = record(title, start.isoformat(), None, VENUE, ADDRESS, 'Henderson',
                             url, occurrence, tz=TIMEZONE, retain_until_end=True)
                if row is None:
                    continue
                row.update(timezone=TIMEZONE,
                           description=optional_description(SOURCE_KEY, occurrence, narrative),
                           location_provenance='publisher_reviewed_named_venue_and_address',
                           publisher_categories=[])
                if status:
                    row['publisher_status'] = status[1].casefold().replace('canceled', 'cancelled')
                attach(row, SOURCE_KEY, candidate=candidate, evidence_url=CALENDAR)
                row['details_evidence_url'] = CALENDAR
                rows.append(row)
        except EventHold as error:
            _note(diagnostics, 'held', identity, str(error), url)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', TIMEZONE):
        raise ValueError('unregistered_mcgregor_source')
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
            print(json.dumps({'event': 'mcgregor_' + disposition, 'source_key': SOURCE_KEY, **item}), file=sys.stderr)
    print(json.dumps({'event': 'mcgregor_normalized', 'source_key': SOURCE_KEY,
                      'cards': diagnostics.get('cards', 0), 'records': len(rows),
                      'held': len(diagnostics.get('held', [])),
                      'excluded': len(diagnostics.get('excluded', []))}), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('mcgregor_event_evidence_unavailable')
    return rows
