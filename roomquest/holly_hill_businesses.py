"""Two reviewed business calendars near Holly Hill, using injected transport.

D&G sells explicitly dated tower-hunt sessions as WooCommerce products. Its
product SKU is an inventory identifier, never an occurrence date. Outside Inn
publishes Event JSON-LD alongside guest-only and appointment-based activities;
only explicitly public, dated occurrences are eligible. Neither parser expands
prose recurrence, follows social accounts, fetches checkout URLs, or borrows a
publisher-wide map pin. All requests pass through the worker's guarded fetch.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import address, plain, record, timestamp
from roomquest.publisher_evidence import attach

TIMEZONE = 'America/New_York'
D_AND_G = 'd_and_g_outdoors_sc'
OUTSIDE_INN = 'outside_inn_campground_sc'
SOURCES = {
    D_AND_G: 'https://dandgoutdoors.com/hunt/',
    OUTSIDE_INN: 'https://outsideinncampground.com/upcoming-events/',
}
HOSTS = {key: (urlsplit(url).hostname,) for key, url in SOURCES.items()}
MAX_DOCUMENT = 2_000_000
MAX_RECORDS = 50
MAX_DETAILS = 16
MAX_SECONDS = 30
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
DG_ADDRESS = '3402 Bass Drive, Holly Hill, SC 29059'
_MONTHS = {name.lower(): index for index, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
_DATE = re.compile(r'([A-Za-z]+) (\d{1,2}), (20\d{2})\s*[-–—]\s*\d+ Birds(?: \([A-Za-z !]+\))?', re.I)
_PATH = re.compile(r'/hunt/([a-z]+)-(\d{1,2})-(20\d{2})-[a-z0-9-]+/')
_CLOCK = r'\d{1,2}:\d{2}\s*[ap]m'
_RANGE = re.compile(rf'\(({_CLOCK})\s*[-–—]\s*({_CLOCK})\)', re.I)
_NONPUBLIC = re.compile(r'\b(?:private (?:hunt|event|tour)|guests? only|members? only|by appointment|by reservation|for overnight guests|open to (?:all )?overnight guests)\b', re.I)
_PUBLIC = re.compile(r'\b(?:open to (?:the )?public|open to (?:both )?overnight guests and (?:the )?public|open to guests and the community|open to all(?!\s+(?:overnight\s+)?(?:guests|campers|members))|guests and non-guests)\b', re.I)
_OFFSITE = re.compile(r'\b(?:off[ -]site|relocat(?:ed|ion)|moved? to|new (?:location|venue))\b|\b(?:location|venue)\s*:', re.I)


class EventHold(ValueError):
    """An occurrence needs additional or corrected publisher evidence."""


def event_url(source_key, url):
    if not isinstance(url, str) or source_key not in SOURCES:
        return False
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != HOSTS[source_key][0]
                or parts.query or parts.fragment):
            return False
        return bool(_PATH.fullmatch(parts.path)) if source_key == D_AND_G else url == SOURCES[OUTSIDE_INN]
    except ValueError:
        return False


def _page(payload):
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('holly_hill_document_limit')
    return BeautifulSoup(payload, 'html.parser')


def _text(node):
    copy = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in copy.select('script,style,template,noscript'):
        tag.decompose()
    return plain(copy.get_text(' ', strip=True))


def _label(value):
    return re.sub(r'\s*[-–—]\s*', ' - ', plain(value)).casefold()


def _day(title):
    match = _DATE.fullmatch(plain(title))
    if not match:
        raise EventHold('publisher_date_unresolved')
    try:
        return date(int(match[3]), _MONTHS[match[1].lower()], int(match[2]))
    except (KeyError, ValueError):
        raise EventHold('publisher_date_unresolved') from None


def _note(diagnostics, disposition, identity, reason, url):
    diagnostics.setdefault(disposition, []).append({'id': identity, 'reason': reason, 'event_url': url})


def _status(text):
    statuses = {value.lower().replace('canceled', 'cancelled') for value in re.findall(
        r'(?:^|[.!;]\s+)(?:Status:\s*)?(Cancelled|Canceled|Postponed)(?=\s*[.!;]|\s*$)', text, re.I)}
    if len(statuses) > 1:
        raise EventHold('publisher_status_conflict')
    if not statuses and re.search(r'\b(?:cancelled|canceled|postponed)\b', text, re.I):
        raise EventHold('publisher_status_unresolved')
    return statuses.pop() if statuses else 'scheduled'


def _within(start, end, current, status):
    if start > current + timedelta(days=LOOKAHEAD_DAYS):
        return False
    if status in ('cancelled', 'postponed'):
        return start >= current - timedelta(days=STATUS_LOOKBACK_DAYS)
    return (end or start) > current


def _row(key, title, start, end, venue, street, city, url, identity, description,
         status='scheduled', facts=None, categories=None):
    if status in ('cancelled', 'postponed'):
        item = {'id': identity, 'title': title[:180], 'starts_at': start.astimezone(timezone.utc).isoformat(),
                'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
                'venue_name': venue, 'venue_address': street, 'venue_city': city,
                'lat': None, 'lng': None, 'event_url': url, 'category': '',
                'reason': 'missing_verified_venue_geo'}
    else:
        item = record(title, start.isoformat(), end.isoformat() if end else None,
                      venue, street, city, url, identity, tz=TIMEZONE, retain_until_end=True)
    if item:
        item.update(timezone=TIMEZONE, description=description[:2000], attendance_mode='in_person',
                    publisher_status=status, publisher_categories=categories or [],
                    location_provenance='publisher_event_address' if key == OUTSIDE_INN else
                                        'publisher_tower_hunt_and_current_address')
        attach(item, key, facts=facts)
    return item


def _dg_listing(payload, current, diagnostics):
    soup = _page(payload)
    main = soup.select_one('main#main')
    if not main or not soup.title or 'Pheasant Hunt' not in soup.title.get_text():
        raise ValueError('d_and_g_listing_structure_unverified')
    if main.select('[rel~=next], .woocommerce-pagination, [data-next-page]'):
        raise ValueError('d_and_g_pagination_requires_review')
    cards = main.select('ul.products > li.product')
    count = main.select_one('.woocommerce-result-count')
    declared = re.match(r'Showing all (\d+) results', _text(count))
    if not cards and re.search(r'No products were found', _text(main), re.I):
        return []
    if not declared or int(declared[1]) != len(cards) or not 1 <= len(cards) <= MAX_RECORDS:
        raise ValueError('d_and_g_catalogue_count_unverified')
    results, seen = [], set()
    for card in cards:
        link = card.select_one('.woocommerce-loop-product__title a[href]')
        ids = [c.removeprefix('post-') for c in card.get('class', []) if re.fullmatch(r'post-[1-9]\d*', c)]
        if (not link or len(ids) != 1 or ids[0] in seen or 'product_cat-hunts' not in card.get('class', [])
                or not event_url(D_AND_G, link.get('href'))):
            raise ValueError('d_and_g_product_identity_unverified')
        seen.add(ids[0])
        url, title = link['href'], _text(link)
        day = _day(title)
        slug = _PATH.fullmatch(urlsplit(url).path)
        if slug[1] not in _MONTHS or day != date(int(slug[3]), _MONTHS[slug[1]], int(slug[2])):
            raise ValueError('d_and_g_product_date_conflict')
        if not current.date() - timedelta(days=STATUS_LOOKBACK_DAYS) <= day <= (current + timedelta(days=LOOKAHEAD_DAYS)).date():
            diagnostics['outside_window'] = diagnostics.get('outside_window', 0) + 1
            continue
        results.append((ids[0], url, title, day))
    diagnostics['catalogue_products'] = len(cards)
    if len(results) > MAX_DETAILS:
        raise ValueError('d_and_g_detail_limit')
    return results


def _dg_detail(payload, product, current):
    identity, url, title, day = product
    soup = _page(payload)
    canonical = soup.select('link[rel=canonical]')
    body = soup.select_one(f'main #product-{identity}')
    heading = body.select_one('.summary h1.product_title') if body else None
    narrative = body.select_one('.woocommerce-product-details__short-description') if body else None
    if (len(canonical) != 1 or canonical[0].get('href') != url or not heading or not narrative
            or _label(_text(heading)) != _label(title)):
        raise ValueError('d_and_g_product_identity_unverified')
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.get_text())
        if isinstance(data, dict) and data.get('@type') == 'Product':
            products.append(data)
    if (len(products) != 1 or products[0].get('url') != url
            or _label(products[0].get('name')) != _label(title)):
        raise ValueError('d_and_g_product_schema_unverified')
    description = _text(narrative)
    status = _status(description)
    if _NONPUBLIC.search(description):
        return None
    ranges = set(_RANGE.findall(description))
    schema_ranges = set(_RANGE.findall(plain(products[0].get('description'))))
    if len(ranges) != 1 or ranges != schema_ranges:
        raise EventHold('publisher_time_unresolved')
    clocks = next(iter(ranges))
    try:
        start, end = [timestamp(datetime.combine(day, datetime.strptime(
            re.sub(r'\s+', '', clock).upper(), '%I:%M%p').time()).isoformat(), TIMEZONE) for clock in clocks]
    except ValueError:
        raise EventHold('publisher_time_unresolved') from None
    if end <= start or ('3-hours' in description and end - start != timedelta(hours=3)):
        raise EventHold('publisher_time_conflict')
    if ('(morning)' in title.lower() and start.hour >= 12) or ('(afternoon)' in title.lower() and start.hour < 12):
        raise EventHold('publisher_time_conflict')
    if not _within(start, end, current, status):
        return None
    footer = _text(soup.select_one('footer'))
    if (_OFFSITE.search(description) or not re.search(r'3402 Bass Drive\s+Holly Hill, SC 29059\b', footer)
            or 'D&G Outdoors offers bird tower hunting in Holly Hill' not in footer):
        raise EventHold('publisher_venue_unreviewed')
    price = body.select_one('.summary .price')
    amount = re.fullmatch(r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', _text(price))
    facts = {}
    if amount and 'Price is per station' in description:
        facts['cost'] = f'${amount[1]} per station.'
        if 'maximum of FOUR (4) shooters' in description:
            facts['cost'] += ' Each station accommodates a maximum of four shooters.'
    stock = body.select_one('.summary .stock')
    if stock and 'out-of-stock' in stock.get('class', []):
        facts['registration'] = 'Sold out on the publisher booking page.'
    return _row(D_AND_G, 'D&G Outdoors Pheasant Tower Hunt — ' + title, start, end,
                'D&G Outdoors', DG_ADDRESS, 'Holly Hill', url, 'd_and_g_outdoors:' + identity,
                description, status, facts, ['Tower Hunts'])


def parse_outside_inn(payload, *, now=None, diagnostics=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('holly_hill_now_timezone_missing')
    diagnostics = diagnostics if diagnostics is not None else {}
    soup = _page(payload)
    canonical = soup.select('link[rel=canonical]')
    main = soup.select_one('main')
    if (len(canonical) != 1 or canonical[0].get('href') != SOURCES[OUTSIDE_INN] or not main
            or "What's Happening at the Farm" not in _text(main)):
        raise ValueError('outside_inn_listing_structure_unverified')
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.get_text())
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data
        if not isinstance(nodes, list) or len(nodes) > 500:
            raise ValueError('outside_inn_schema_unverified')
        events.extend(node for node in nodes if isinstance(node, dict) and node.get('@type') == 'Event')
    if len(events) > MAX_RECORDS:
        raise ValueError('outside_inn_record_limit')
    if not events and not re.search(r'\bno upcoming events\b', _text(main), re.I):
        raise ValueError('outside_inn_empty_unverified')
    rows, seen = [], {}
    for event in events:
        title, description = plain(event.get('name')), plain(event.get('description'))
        raw_start = event.get('startDate')
        if not title or not isinstance(raw_start, str):
            raise ValueError('outside_inn_event_shape_unverified')
        identity = 'outside_inn:' + sha256((title + '\n' + raw_start).encode()).hexdigest()[:32]
        # Past date-only guest weekends can be ignored without inventing a time.
        try:
            day = date.fromisoformat(raw_start[:10])
        except ValueError:
            raise ValueError('outside_inn_event_date_unresolved') from None
        if day < current.date() - timedelta(days=STATUS_LOOKBACK_DAYS) or day > (current + timedelta(days=LOOKAHEAD_DAYS)).date():
            diagnostics['outside_window'] = diagnostics.get('outside_window', 0) + 1
            continue
        try:
            public = bool(_PUBLIC.search(description))
            if _NONPUBLIC.search(description) and not public:
                _note(diagnostics, 'excluded', identity, 'nonpublic_or_appointment_activity', SOURCES[OUTSIDE_INN])
                continue
            if not public:
                raise EventHold('publisher_public_access_unresolved')
            if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})', raw_start):
                raise EventHold('publisher_time_unresolved')
            start = timestamp(raw_start)
            end = timestamp(event.get('endDate'))
            if end and end <= start:
                raise EventHold('publisher_time_conflict')
            status_raw = str(event.get('eventStatus', ''))
            statuses = {'EventScheduled': 'scheduled', 'EventCancelled': 'cancelled', 'EventPostponed': 'postponed'}
            status = statuses.get(status_raw.rsplit('/', 1)[-1])
            if not status:
                raise EventHold('publisher_status_unresolved')
            if not _within(start, end, current, status):
                continue
            location = event.get('location')
            street = location.get('address') if isinstance(location, dict) else None
            if (not isinstance(street, dict) or location.get('name') != 'Outside Inn Campground'
                    or not all(street.get(k) == v for k, v in {
                        'streetAddress': '1074 Woolbright Rd', 'addressLocality': 'Santee',
                        'addressRegion': 'SC', 'postalCode': '29142'}.items())
                    or str(event.get('eventAttendanceMode', '')).rsplit('/', 1)[-1] != 'OfflineEventAttendanceMode'
                    or _OFFSITE.search(description)):
                raise EventHold('publisher_venue_unreviewed')
            if event.get('url') and not event_url(OUTSIDE_INN, event['url']):
                raise EventHold('publisher_event_link_unreviewed')
            facts = {}
            cost = re.search(r'\$\d+(?:\.\d{2})? per person', description)
            if cost:
                facts['cost'] = cost[0]
            row = _row(OUTSIDE_INN, title, start, end, location['name'], address(street), 'Santee',
                       SOURCES[OUTSIDE_INN], identity, description, status, facts)
            if row:
                if identity in seen and seen[identity] != row:
                    raise ValueError('outside_inn_conflicting_occurrence')
                seen[identity] = row
        except EventHold as exc:
            _note(diagnostics, 'held', identity, str(exc), SOURCES[OUTSIDE_INN])
    diagnostics['jsonld_events'] = len(events)
    rows.extend(seen.values())
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None, diagnostics=None):
    key = source.get('source_key')
    if (key not in SOURCES or source.get('feed_url') != SOURCES[key] or source.get('kind') != 'html'
            or source.get('platform_adapter') != 'html' or source.get('timezone') != TIMEZONE):
        raise ValueError('unregistered_holly_hill_business_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('holly_hill_now_timezone_missing')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    diagnostics = diagnostics if diagnostics is not None else {}

    def get(url):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        value = fetch(url, 'text/html')
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        return value

    payload = get(SOURCES[key])
    if key == D_AND_G:
        rows = []
        for product in _dg_listing(payload, current, diagnostics):
            try:
                row = _dg_detail(get(product[1]), product, current)
                if row:
                    rows.append(row)
            except EventHold as exc:
                _note(diagnostics, 'held', product[0], str(exc), product[1])
    else:
        rows = parse_outside_inn(payload, now=current, diagnostics=diagnostics)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    print(json.dumps({'event': 'holly_hill_business_normalized', 'source_key': key,
                      'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('holly_hill_business_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
