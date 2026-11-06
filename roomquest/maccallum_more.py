"""Dated public events linked by MacCallum More's ordinary homepage.

This is a limited catalog, not a museum-opening-hours feed. Every visible card
is accounted for; unknown pagination, caps and transport failures fail the run.
Held and non-activity cards are diagnostic omissions, never cancellations.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'maccallum_more_va'
CALENDAR = 'https://maccallummore.org/'
TIMEZONE = 'America/New_York'
MAX_DETAIL_PAGES = 10
MAX_SECONDS = 30
MAX_DESCRIPTION = 2000
MAX_FACT_TEXT = 50_000
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
_MONTHS = {name.lower(): n for n, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
_WEEKDAYS = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split()
_CLOCK = r'\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?'


class EventHold(ValueError):
    """A real card has insufficient or conflicting event facts."""


def _narrative(node):
    soup = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in soup.select('script, style, template, noscript'):
        tag.decompose()
    value = '\n'.join(x.strip() for x in soup.get_text('\n').splitlines() if x.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('maccallum_fact_text_limit')
    return value


def _note(diagnostics, disposition, identity, reason, url):
    diagnostics.setdefault(disposition, []).append({'id': identity, 'reason': reason, 'event_url': url})


def event_url(href):
    try:
        if not isinstance(href, str) or re.search(r'[\s\\<>]|%|(?:^|/)\.\.(?:/|$)', href):
            raise ValueError
        value = urljoin(CALENDAR, href)
        p = urlsplit(value)
        if (p.scheme != 'https' or p.netloc != 'maccallummore.org' or p.query or p.fragment
                or not re.fullmatch(r'/pages/[a-z0-9]+(?:-[a-z0-9]+)*/?', p.path)):
            raise ValueError
        return value.rstrip('/')
    except (TypeError, ValueError):
        raise ValueError('maccallum_event_url_unverified') from None


def discover(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    headings = [h for h in soup.select('h1, h2, h3')
                if plain(h.get_text()).casefold() == 'current exhibits & events']
    if len(headings) != 1:
        raise ValueError('maccallum_listing_structure_unverified')
    container = headings[0]
    for _ in range(4):
        if container.select('.multicolumn-card') or 'page-width' in container.get('class', []):
            break
        container = container.parent
        if container is None or container.name in ('html', 'body'):
            raise ValueError('maccallum_listing_structure_unverified')
    cards = container.select('.multicolumn-card')
    if len(cards) > MAX_DETAIL_PAGES:
        raise ValueError('maccallum_detail_page_limit')
    if not cards:
        if re.search(r'\bno (?:upcoming )?events\b', container.get_text(' ', strip=True), re.I):
            return []
        raise ValueError('maccallum_listing_empty_unverified')
    if container.select('[rel~=next], .pagination, [data-next-page]'):
        raise ValueError('maccallum_pagination_requires_review')
    found = {}
    for card in cards:
        heading = card.select_one('h3')
        anchors = card.select('a[href]')
        urls = {event_url(a['href']) for a in anchors}
        if heading is None or not plain(heading.get_text()) or len(urls) != 1:
            raise ValueError('maccallum_card_identity_missing')
        url = urls.pop()
        images = {urljoin(CALENDAR, image.get('src', '')) for image in card.select('img[src]')
                  if image.get('src')}
        item = {'url': url, 'title': plain(heading.get_text()),
                'image': next(iter(images)) if len(images) == 1 else None}
        if url in found and found[url] != item:
            raise ValueError('maccallum_conflicting_listing_card')
        found[url] = item
    return list(found.values())


def _title(value):
    value = re.sub(r'^\s*(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', plain(value), flags=re.I)
    return value


def _same_title(a, b):
    key = lambda x: re.sub(r'[^a-z0-9]', '', re.sub(r'\b20\d{2}\b', '', _title(x)).lower())
    return key(a) == key(b)


def _day(value):
    match = re.fullmatch(
        r'(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?'
        r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})', plain(value), re.I)
    try:
        if not match or match[2].lower() not in _MONTHS:
            raise ValueError
        day = date(int(match[4]), _MONTHS[match[2].lower()], int(match[3]))
        if match[1] and _WEEKDAYS[day.weekday()].casefold() != match[1].casefold():
            raise ValueError
        return day
    except ValueError:
        raise EventHold('publisher_date_unresolved') from None


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


def _details(body):
    headings = [h for h in body.select('h2, h3, h4')
                if plain(h.get_text()).casefold() == 'event details']
    if len(headings) != 1:
        raise EventHold('event_details_missing')
    table = headings[0].find_next_sibling()
    if table is None or table.name not in ('ul', 'ol', 'dl'):
        raise EventHold('event_details_missing')
    fields = {}
    for node in table.select('li'):
        match = re.fullmatch(r'([A-Za-z ]{2,40}):\s*(.+)', plain(node.get_text(' ', strip=True)))
        if match:
            key, value = match[1].casefold(), match[2]
            if key in fields and fields[key] != value:
                raise EventHold('publisher_detail_conflict')
            fields[key] = value
    return fields


def _status(raw_title, fields, narrative):
    choices = {fields['status'].lower().replace('canceled', 'cancelled')} if fields.get('status') else set()
    prefix = re.match(r'^\s*(cancelled|canceled|postponed)\s*[:–—-]', raw_title, re.I)
    if prefix:
        choices.add(prefix[1].lower().replace('canceled', 'cancelled'))
    choices.update(x.lower().replace('canceled', 'cancelled') for x in re.findall(
        r'^(?:Status:\s*)?(Cancelled|Canceled|Postponed|Scheduled)\s*$', narrative, re.I | re.M))
    if len(choices) > 1:
        raise EventHold('publisher_status_conflict')
    if choices:
        value = choices.pop()
        if value not in ('scheduled', 'cancelled', 'postponed'):
            raise EventHold('publisher_status_unresolved')
        return value
    if re.search(r'\b(?:cancelled|canceled|postponed)\b', narrative, re.I):
        raise EventHold('publisher_status_unresolved')
    return None


def _consistent_schedule(title, card_title, body, day, start):
    for value in (title, card_title):
        years = {int(x) for x in re.findall(r'\b20\d{2}\b', value)}
        if years and years != {day.year}:
            raise EventHold('publisher_schedule_conflict')
    # Only an explicit same-event "on <full date> at <time>" statement
    # competes with the detail table. Registration and sales deadlines do not.
    name = re.sub(r'[^a-z0-9]+', ' ', re.sub(r'\b20\d{2}\b', '', _title(title)).casefold()).strip()
    pattern = re.compile(
        r'\bon\s+((?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?'
        r'[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2}),?\s+at\s+'
        rf'({_CLOCK})', re.I)
    for p in body.select('p'):
        text = plain(p.get_text(' ', strip=True))
        key = re.sub(r'[^a-z0-9]+', ' ', text.casefold())
        if not name or (' ' + name + ' ') not in (' ' + key + ' '):
            continue
        for match in pattern.finditer(text):
            stated_day = _day(match[1])
            stated_start, _ = _times(stated_day, match[2])
            if stated_day != day or stated_start != start:
                raise EventHold('publisher_schedule_conflict')


def _exhibition(soup, card, current, diagnostics, page_id, url):
    """Recognize the observed exhibition page, without turning hours into events."""
    headings = soup.select('h2.image-with-text__heading')
    main = soup.find('main')
    if (len(headings) != 1 or main is None
            or 'juried art show' not in plain(headings[0].get_text()).casefold()
            or 'juried art show' not in card['title'].casefold()
            or not any(plain(h.get_text()).casefold() == 'awards reception and exhibit dates'
                       for h in main.select('h2'))):
        raise ValueError('maccallum_detail_structure_unverified')
    text = plain(_narrative(main))
    reception = re.search(
        r'\bAwards Reception\s+on\s+((?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?'
        r'[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2}),?\s+from\b', text, re.I)
    try:
        if not reception:
            raise EventHold('exhibition_reception_schedule_requires_review')
        day = _day(reception[1])
        years = {int(x) for x in re.findall(r'\b20\d{2}\b', headings[0].get_text())}
        if years != {day.year}:
            raise EventHold('publisher_schedule_conflict')
        if day >= current.astimezone(timestamp(day.isoformat(), TIMEZONE).tzinfo).date():
            raise EventHold('future_exhibition_reception_requires_review')
        _note(diagnostics, 'excluded', page_id, 'exhibition_without_future_timed_event', url)
    except EventHold as exc:
        _note(diagnostics, 'held', page_id, str(exc), url)
    return None


def _status_row(title, start, end, venue, address, city, url, identity, category):
    return {'id': identity, 'title': title[:180],
            'starts_at': start.astimezone(timezone.utc).isoformat(),
            'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
            'venue_name': venue[:400], 'venue_address': address[:400], 'venue_city': city[:120],
            'lat': None, 'lng': None, 'event_url': url, 'category': category[:80],
            'reason': 'missing_verified_venue_geo'}


def parse_event(payload, card, *, now=None, diagnostics=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('maccallum_now_timezone_missing')
    diagnostics = diagnostics if diagnostics is not None else {}
    url = event_url(card['url'])
    page_id = 'maccallum_more:' + sha256(url.encode()).hexdigest()[:32]
    soup = BeautifulSoup(payload, 'html.parser')
    titles = soup.select('h1.main-page-title')
    if len(titles) != 1:
        return _exhibition(soup, card, current, diagnostics, page_id, url)
    body = titles[0].find_next_sibling('div', class_='rte')
    if body is None:
        raise ValueError('maccallum_detail_structure_unverified')
    title, narrative = _title(titles[0].get_text()), _narrative(body)
    if not _same_title(title, card['title']):
        raise ValueError('maccallum_event_identity_conflict')
    try:
        try:
            fields = _details(body)
        except EventHold:
            if (re.search(r'\braffle\b', title, re.I) and re.search(r'\btickets?\b', narrative, re.I)
                    and any(plain(h.get_text()).casefold() == 'raffle details' for h in body.select('h2, h3'))):
                _note(diagnostics, 'excluded', page_id, 'fundraising_offer_without_public_gathering', url)
                return None
            raise
        day = _day(fields.get('date', ''))
        start, end = _times(day, fields.get('time', ''))
        _consistent_schedule(title, card['title'], body, day, start)
        # A recurring annual page is a different occurrence in a new year.
        identity = 'maccallum_more:' + sha256((url + '\n' + str(day.year)).encode()).hexdigest()[:32]
        page_id = identity
        status = _status(titles[0].get_text(), fields, narrative)
        terminal_status = status in ('cancelled', 'postponed')
        if (start > current + timedelta(days=LOOKAHEAD_DAYS)
                or (terminal_status and start < current - timedelta(days=STATUS_LOOKBACK_DAYS))
                or (not terminal_status and (end or start + timedelta(hours=3)) <= current)):
            return None
        if not terminal_status and re.search(r'\b(?:members?[ -]+only|private (?:party|event)|invitation[ -]+only)\b', narrative, re.I):
            _note(diagnostics, 'excluded', identity, 'nonpublic_event', url)
            return None
        address, venue = fields.get('address', ''), fields.get('location', '')
        city = re.fullmatch(r'\d{1,6}\s+[^,]+,\s*([^,]+),\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?', address)
        if not venue or not city:
            if not terminal_status:
                raise EventHold('event_venue_unreviewed')
            venue = address = ''
        row = (_status_row(title, start, end, venue, address, city[1].strip() if city else '', url,
                           identity, fields.get('category', '')) if terminal_status else
               record(title, start.isoformat(), end.isoformat() if end else None,
                      venue, address, city[1].strip() if city else '', url, identity,
                      fields.get('category', ''), tz=TIMEZONE, retain_until_end=True))
        if row is None:
            return None
        row.update(timezone=TIMEZONE, description=narrative[:MAX_DESCRIPTION],
                   location_provenance=('publisher_event_address_pending_geocode' if address else
                                        'publisher_explicit_status_without_current_venue'),
                   publisher_categories=[fields['category']] if fields.get('category') else [])
        if status:
            row['publisher_status'] = 'cancelled' if status == 'canceled' else status
        facts = {}
        if value := fields.get('admission') or fields.get('cost'):
            facts['cost'] = value[:400]
        if value := fields.get('registration'):
            facts['registration'] = value[:400]
        if re.search(r'\beveryone is welcome\b', narrative, re.I):
            facts['audience'] = 'Everyone is welcome.'
        return attach(row, SOURCE_KEY, facts=facts, candidate=card.get('image'), evidence_url=CALENDAR)
    except EventHold as exc:
        _note(diagnostics, 'held', page_id, str(exc), url)
        return None


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_maccallum_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    def get(url):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        value = fetch(url, 'text/html')
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        return value
    cards = discover(get(CALENDAR))
    diagnostics, rows, seen = {}, [], set()
    for card in cards:
        row = parse_event(get(card['url']), card, now=now, diagnostics=diagnostics)
        if row:
            if row['id'] in seen:
                raise ValueError('maccallum_conflicting_occurrence')
            seen.add(row['id'])
            rows.append(row)
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
    print(json.dumps({'event': 'maccallum_normalized', 'source_key': SOURCE_KEY,
                      'linked_cards': len(cards), 'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('maccallum_event_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
