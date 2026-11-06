"""Public performance cards and same-production year/venue evidence.

Only the two permitted ordinary publisher pages are fetched. The separate
Google calendar and Ludus ticket destination are never collection endpoints.
Missing years, changed venue evidence and unsupported cards stay held; no
current-year or publisher-headquarters default is introduced.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'clarksville_community_players_va'
CALENDAR = 'https://clarksvilleplayers.org/'
AUDITIONS = 'https://clarksvilleplayers.org/auditions'
TIMEZONE = 'America/New_York'
MAX_CARDS = 30
MAX_OCCURRENCES = 100
MAX_SECONDS = 20
MAX_DESCRIPTION = 2000
MAX_FACT_TEXT = 50_000
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
THEATER_ADDRESS = '914 Virginia Avenue, Clarksville, VA 23927'
_MONTHS = {name.lower(): n for n, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
_MONTH = '(?:' + '|'.join(_MONTHS) + ')'
_WEEKDAYS = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split()
_CLOCK = r'\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?'
_OCCURRENCE = re.compile(
    rf'(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?'
    rf'({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d{{2}}))?\s*(?:@|at)\s*'
    rf'({_CLOCK})(?:\s*[-–—]\s*({_CLOCK}))?', re.I)
_ARTICLE_DATES = re.compile(
    rf'\b({_MONTH})\s+(\d{{1,2}}(?:(?:\s*,\s*|\s*&\s*|\s+and\s+|\s*[-–—]\s*)\d{{1,2}})*)'
    r'(?:,\s*|\s+)(20\d{2})\b', re.I)


class EventHold(ValueError):
    """An identified occurrence needs publisher evidence, not guessed facts."""


def _narrative(node):
    soup = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in soup.select('script, style, template, noscript'):
        tag.decompose()
    value = '\n'.join(x.strip() for x in soup.get_text('\n').splitlines() if x.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('players_fact_text_limit')
    return value


def _title(value):
    return re.sub(r'^\s*(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', plain(value), flags=re.I)


def _key(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value).casefold()).strip()


def _contains_title(text, title):
    title = _key(_title(title))
    return len(title) >= 4 and (' ' + title + ' ') in (' ' + _key(text) + ' ')


def _identity(title, value):
    return 'clarksville_players:' + sha256((_key(_title(title)) + '\n' + value).encode()).hexdigest()[:32]


def _note(diagnostics, disposition, identity, reason):
    diagnostics.setdefault(disposition, []).append({'id': identity, 'reason': reason, 'event_url': CALENDAR})


def _business(soup):
    matches = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            raise ValueError('players_publisher_identity_unverified') from None
        if isinstance(value, dict) and value.get('@type') == 'LocalBusiness':
            if value.get('name') == 'Clarksville Community Players':
                matches.append(value)
    if len(matches) != 1:
        raise ValueError('players_publisher_identity_unverified')
    address = matches[0].get('address') or {}
    # Deliberately ignore the publisher-wide LocalBusiness geo coordinates.
    # Loss of a venue must not erase an exact dated cancellation. Normal rows
    # may use this reviewed theater only with matching production evidence.
    return (isinstance(address, dict)
            and _key(address.get('streetAddress', '')).replace('avenue', 'ave') == '914 virginia ave'
            and address.get('addressLocality') == 'Clarksville'
            and address.get('addressRegion') == 'VA' and str(address.get('postalCode')) == '23927')


def _article_evidence(payload, title):
    soup = BeautifulSoup(payload, 'html.parser')
    for tag in soup.select('script, style, template, noscript'):
        tag.decompose()
    paragraphs = [plain(p.get_text(' ', strip=True)) for p in soup.select('p')
                  if _contains_title(p.get_text(' ', strip=True), title)]
    if sum(map(len, paragraphs)) > MAX_FACT_TEXT:
        raise ValueError('players_fact_text_limit')
    years = {}
    dated_paragraphs = []
    for paragraph in paragraphs:
        for match in _ARTICLE_DATES.finditer(paragraph):
            day_text = match[2]
            numbers = [int(x) for x in re.findall(r'\d+', day_text)]
            if re.search(r'[-–—]', day_text):
                if len(numbers) != 2 or not 0 <= numbers[1] - numbers[0] <= 14:
                    raise EventHold('publisher_date_range_unresolved')
                numbers = list(range(numbers[0], numbers[1] + 1))
            month, year = _MONTHS[match[1].lower()], int(match[3])
            for day in numbers:
                try:
                    date(year, month, day)
                except ValueError:
                    raise EventHold('publisher_date_unresolved') from None
                years.setdefault((month, day), set()).add(year)
            dated_paragraphs.append(paragraph)
    return years, paragraphs, '\n'.join(dict.fromkeys(dated_paragraphs))


def _venue(description, matching_paragraphs):
    # Explicit event-location lines can support future off-site productions.
    for line in description.splitlines():
        match = re.fullmatch(
            r'(?:Venue|Location):\s*(.+?)[;|]\s*(\d{1,6}\s+[^,]+,\s*([^,]+),\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)',
            line, re.I)
        if match:
            return match[1].strip(), match[2].strip(), match[3].strip(), 'publisher_event_address_pending_geocode'
    # This is a reviewed named-theater binding, additionally requiring a
    # paragraph that names this production and the theater's street address.
    venue = re.compile(
        r'Clarksville Fine Arts Center\s*\(\s*914\s+Virginia\s+Ave(?:nue)?\.?\s*,?\s*'
        r'Clarksville\s*,\s*VA(?:\s+23927)?\s*\)', re.I)
    if any(venue.search(p) for p in matching_paragraphs):
        return ('Clarksville Fine Arts Center', THEATER_ADDRESS, 'Clarksville',
                'publisher_matched_production_and_reviewed_theater_address')
    raise EventHold('event_venue_unreviewed')


def _clock(day, value):
    text = re.sub(r'[\s.]', '', value).upper()
    try:
        wall = datetime.strptime(text, '%I:%M%p' if ':' in text else '%I%p').time()
        return timestamp(datetime.combine(day, wall).isoformat(), TIMEZONE)
    except ValueError:
        raise EventHold('publisher_time_unresolved') from None


def _status(raw_title, description):
    prefix = re.match(r'^\s*(cancelled|canceled|postponed)\s*[:–—-]', raw_title, re.I)
    statements = re.findall(r'^(?:Status:\s*)?(Cancelled|Canceled|Postponed|Scheduled)\s*$', description, re.I | re.M)
    choices = {x.lower().replace('canceled', 'cancelled') for x in statements}
    if prefix:
        choices.add(prefix[1].lower().replace('canceled', 'cancelled'))
    if len(choices) > 1:
        raise EventHold('publisher_status_conflict')
    if choices:
        return choices.pop()
    if re.search(r'\b(?:cancelled|canceled|postponed)\b', description, re.I):
        raise EventHold('publisher_status_unresolved')
    return None


def _status_row(title, start, end, venue, address, city, identity):
    return {'id': identity, 'title': title[:180],
            'starts_at': start.astimezone(timezone.utc).isoformat(),
            'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
            'venue_name': venue[:400], 'venue_address': address[:400], 'venue_city': city[:120],
            'lat': None, 'lng': None, 'event_url': CALENDAR, 'category': '',
            'reason': 'missing_verified_venue_geo'}


def parse(payload, article_payload, *, now=None, diagnostics=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('players_now_timezone_missing')
    diagnostics = diagnostics if diagnostics is not None else {}
    soup = BeautifulSoup(payload, 'html.parser')
    reviewed_theater = _business(soup)
    headings = [h for h in soup.select('h1, h2, h3') if plain(h.get_text()).casefold() == 'upcoming shows']
    if len(headings) != 1:
        raise ValueError('players_listing_structure_unverified')
    section = headings[0].find_parent('section')
    if section is None:
        raise ValueError('players_listing_structure_unverified')
    if section.select('[rel~=next], .pagination, [data-next-page]'):
        raise ValueError('players_pagination_requires_review')
    cards = section.select('[data-ux="ContentCard"]')
    if len(cards) > MAX_CARDS:
        raise ValueError('players_source_record_limit')
    if not cards and not re.search(r'\bno (?:upcoming )?shows\b', section.get_text(' ', strip=True), re.I):
        raise ValueError('players_listing_empty_unverified')
    rows, seen = [], {}
    count = 0
    for card in cards:
        heading = card.select_one('[data-aid^="CONTENT_HEADLINE"][data-aid$="_RENDERED"]')
        content = card.select_one('[data-aid^="CONTENT_DESCRIPTION"][data-aid$="_RENDERED"]')
        if heading is None or content is None or not plain(heading.get_text()):
            raise ValueError('players_card_structure_unverified')
        raw_title = plain(heading.get_text())
        title, description = _title(raw_title), _narrative(content)
        card_id = _identity(title, 'card')
        try:
            status = _status(raw_title, description)
        except EventHold as exc:
            _note(diagnostics, 'held', card_id, str(exc))
            continue
        terminal_status = status in ('cancelled', 'postponed')
        if not terminal_status and re.search(r'\b(?:private (?:event|party)|members?[ -]+only|invitation[ -]+only)\b', description, re.I):
            _note(diagnostics, 'excluded', card_id, 'nonpublic_event')
            continue
        occurrences = list(_OCCURRENCE.finditer(description))
        count += len(occurrences)
        if count > MAX_OCCURRENCES:
            raise ValueError('players_source_record_limit')
        if not occurrences:
            _note(diagnostics, 'held', card_id, 'publisher_time_unresolved')
            continue
        try:
            years, paragraphs, article_description = _article_evidence(article_payload, title)
        except EventHold as exc:
            _note(diagnostics, 'held', card_id, str(exc))
            continue
        images = {urljoin(CALENDAR, image.get('src', '')) for image in card.select('img[src]') if image.get('src')}
        candidate = next(iter(images)) if len(images) == 1 else None
        for occurrence in occurrences:
            identity = _identity(title, occurrence[0])
            try:
                weekday, month_text, day_text, explicit_year, clock, end_clock = occurrence.groups()
                month, day = _MONTHS[month_text.lower()], int(day_text)
                evidence = years.get((month, day), set())
                if explicit_year:
                    year = int(explicit_year)
                    if evidence and evidence != {year}:
                        raise EventHold('publisher_schedule_conflict')
                elif len(evidence) == 1:
                    year = next(iter(evidence))
                else:
                    raise EventHold('publisher_year_unresolved')
                try:
                    local_day = date(year, month, day)
                except ValueError:
                    raise EventHold('publisher_date_unresolved') from None
                if weekday and _WEEKDAYS[local_day.weekday()].casefold() != weekday.casefold():
                    raise EventHold('publisher_schedule_conflict')
                start = _clock(local_day, clock)
                end = _clock(local_day, end_clock) if end_clock else None
                identity = _identity(title, start.isoformat())
                if end is not None and end <= start:
                    raise EventHold('publisher_time_conflict')
                if (start > current + timedelta(days=LOOKAHEAD_DAYS)
                        or (terminal_status and start < current - timedelta(days=STATUS_LOOKBACK_DAYS))
                        or (not terminal_status and (end or start + timedelta(hours=3)) <= current)):
                    continue
                # A previous year's article cannot locate a newly dated show.
                # Explicit card addresses remain independently usable.
                matching_venue = paragraphs if reviewed_theater and evidence == {year} else []
                try:
                    venue, address, city, venue_provenance = _venue(description, matching_venue)
                except EventHold:
                    if not terminal_status:
                        raise
                    venue = address = city = ''
                    venue_provenance = 'publisher_explicit_status_without_current_venue'
                row = (_status_row(title, start, end, venue, address, city, identity) if terminal_status else
                       record(title, start.isoformat(), end.isoformat() if end else None,
                              venue, address, city, CALENDAR, identity, tz=TIMEZONE, retain_until_end=True))
                if row is None:
                    continue
                row.update(timezone=TIMEZONE,
                           description=(description + ('\n\n' + article_description if article_description else ''))[:MAX_DESCRIPTION],
                           location_provenance=venue_provenance, publisher_categories=[])
                if status:
                    row['publisher_status'] = status
                facts = {}
                ticket = soup.find('a', href='https://clarksvilleplayers.ludus.com/')
                if ticket:
                    facts['registration'] = 'Ticket information: https://clarksvilleplayers.ludus.com/'
                attach(row, SOURCE_KEY, facts=facts, candidate=candidate, evidence_url=CALENDAR)
                if identity in seen:
                    if seen[identity] != row:
                        raise ValueError('players_conflicting_occurrence')
                    continue
                seen[identity] = row
                rows.append(row)
            except EventHold as exc:
                _note(diagnostics, 'held', identity, str(exc))
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_players_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    def get(url):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        value = fetch(url, 'text/html')
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        return value
    homepage, article = get(CALENDAR), get(AUDITIONS)
    diagnostics = {}
    rows = parse(homepage, article, now=now, diagnostics=diagnostics)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    print(json.dumps({'event': 'players_normalized', 'source_key': SOURCE_KEY,
                      'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('players_event_evidence_unavailable')
    return rows
