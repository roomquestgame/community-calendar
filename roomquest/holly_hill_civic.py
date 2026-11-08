"""Reviewed Holly Hill-area public calendars, with explicit source contracts.

The caller supplies the existing bounded, robots-aware publisher transport.
This module never opens a socket, follows an arbitrary API next link, invents
an event time, or uses a town/source-center coordinate as an event location.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.jsonld_adapter import Blocks, types
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import DETAILS_VERSION, IMAGE_VERSION

ZONE = 'America/New_York'
SANTEE = 'santee_cooper_country_sc'
BEIDLER = 'beidler_forest_sc'
SC250 = 'south_carolina_250_sc'
SC250_API = 'https://southcarolina250.com/wp-json/tribe/events/v1/events'
EUTAWVILLE = 'town_of_eutawville_sc'
ELLOREE = 'elloree_town_calendar_sc'
BEIDLER_ROOT = 'https://www.audubon.org/beidler-forest/explore/seasonal-highlights/'
BEIDLER_PAGES = {
    BEIDLER_ROOT + 'night-exploration': 'Night Exploration',
    BEIDLER_ROOT + 'nocturnal-family-forays': 'Nocturnal Family Forays',
    BEIDLER_ROOT + 'boo-swamp': 'Boo in the Swamp',
}
ELLOREE_API = 'https://connect.elloreesc.com/api/functions/getPublicCalendarEvents'
SOURCES = {
    SANTEE: {'url': 'https://www.santeecoopercountry.org/daily-events-calendar/',
             'kind': 'json', 'adapter': 'jsonld', 'hosts': ('www.santeecoopercountry.org',)},
    BEIDLER: {'url': BEIDLER_ROOT + 'night-exploration', 'kind': 'html',
              'adapter': 'html', 'hosts': ('www.audubon.org',)},
    SC250: {'url': 'https://southcarolina250.com/events/?ical=1',
            'kind': 'ical', 'adapter': 'ical', 'hosts': ('southcarolina250.com',)},
    EUTAWVILLE: {'url': 'https://townofeutawville.gov/wp-json/tribe/events/v1/events',
                'kind': 'json', 'adapter': 'wordpress', 'hosts': ('townofeutawville.gov',)},
    ELLOREE: {'url': 'https://elloreesc.com/elloree-town-calendar/', 'kind': 'html',
              'adapter': 'html', 'hosts': ('elloreesc.com', 'connect.elloreesc.com')},
}
# Retain discovery even where no current collection contract exists. These
# are inventory/hold reasons, not parsers that silently manufacture empty feeds.
PENDING_SOURCES = {
    'world_grits_festival_sc': ('https://w.worldgritsfestival.com/index.html',
                              'future_annual_dates_outside_window_no_clock_times'),
    'old_santee_canal_park_sc': ('https://oldsanteecanal.recdesk.com/Community/Program',
                               'recdesk_public_post_adapter_required'),
    'elloree_heritage_museum_sc': ('https://www.elloreemuseum.org/events',
                                 'no_current_dated_events'),
    'town_of_harleyville_sc': ('https://harleyvillesc.gov/town-events',
                             'no_current_dated_events'),
    'branchville_raylrode_daze_sc': ('https://www.raylrodedazefestivul.com/',
                                   'publisher_timeout_future_annual_schedule_unverified'),
    'town_of_holly_hill_sc': ('https://hollyhill.sc.gov/', 'dated_calendar_not_verified'),
    'santee_national_wildlife_refuge_sc': ('https://www.fws.gov/refuge/santee/visit-us/activities',
                                         'activities_page_without_dated_events'),
}
MAX_RECORDS = 500
MAX_PAGES = 5
MAX_DESCRIPTION = 2000
_LOG = logging.getLogger(__name__)
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|members?[- ]only|invitation[- ]only|private (?:event|party|function))\b', re.I)
MONTHS = {name: index for index, name in enumerate(
    ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
     'September', 'October', 'November', 'December'), 1)}
# The full publisher detail says Saturday November 15, while its 2026 schema
# date is Sunday. The listing truncates that conflicting sentence, so retain
# the exact reviewed hold until the publisher's occurrence is re-reviewed.
SANTEE_REVIEW_HOLDS = {
    'https://www.santeecoopercountry.org/daily-events-calendar/e/crosswind-farm-turns-10-years-old-6acabda632e45a0cfecc693e/':
        'publisher_weekday_date_conflict',
}


class EventHold(ValueError):
    """A real publisher record lacks sufficient evidence to publish safely."""


def require_source(source, key):
    spec = SOURCES.get(key)
    if (not spec or source.get('source_key') != key
            or source.get('feed_url') != spec['url']
            or source.get('kind') != spec['kind']
            or source.get('platform_adapter') != spec['adapter']
            or source.get('timezone', ZONE) != ZONE):
        raise ValueError('unregistered_holly_hill_civic_source')


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
                or p.netloc != p.hostname or p.fragment
                or '..' in p.path.split('/')
                or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)):
            return None
        return p
    except ValueError:
        return None


def event_url(key, value):
    p = _safe_url(value)
    if not p or p.query:
        return False
    if key == SANTEE:
        return (p.hostname == 'www.santeecoopercountry.org'
                and bool(re.fullmatch(r'/daily-events-calendar/e/[a-z0-9-]+/', p.path)))
    if key == BEIDLER:
        return value in BEIDLER_PAGES
    if key in (SC250, EUTAWVILLE):
        return (p.hostname == SOURCES[key]['hosts'][0]
                and bool(re.fullmatch(r'/event/[a-z0-9%_-]+/(?:20\d{2}-\d{2}-\d{2}/)?', p.path)))
    if key == ELLOREE:
        # This public service supplies stable IDs but no individual detail URL.
        return value == SOURCES[ELLOREE]['url']
    return False


def image_url(key, value):
    p = _safe_url(value)
    if not p or p.query or not re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I):
        return None
    if re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', p.path, re.I):
        return None
    if key == SANTEE:
        ok = p.hostname == 'iti-images.s3.amazonaws.com' and bool(re.fullmatch(r'/events/[a-zA-Z0-9-]+\.(?:jpe?g|png|webp|gif)', p.path, re.I))
    elif key in (SC250, EUTAWVILLE):
        ok = p.hostname == SOURCES[key]['hosts'][0] and p.path.startswith('/wp-content/uploads/')
    elif key == ELLOREE:
        app = '6959455a632ee423176fe4c3'
        ok = ((p.hostname == 'elloreesc.com' and p.path.startswith('/wp-content/uploads/'))
              or (p.hostname == 'media.base44.com' and p.path.startswith('/images/public/' + app + '/'))
              or (p.hostname == 'base44.app' and p.path.startswith('/api/apps/' + app + '/files/mp/public/' + app + '/')))
    else:
        # Beidler's scenic hero image is not an occurrence-specific event image.
        ok = False
    return value if ok else None


def narrative(value):
    if value is not None and not isinstance(value, str):
        raise ValueError('invalid_publisher_description')
    soup = BeautifulSoup(value or '', 'html.parser')
    for tag in soup.select('script,style,template,noscript,form'):
        tag.decompose()
    return '\n'.join(line.strip() for line in soup.get_text('\n').splitlines() if line.strip())[:MAX_DESCRIPTION]


def _evidence(row, key, *, facts=None, candidate=None):
    if not event_url(key, row['event_url']):
        raise ValueError('publisher_evidence_identity_mismatch')
    row.update(details_extractor_version=DETAILS_VERSION,
               details_evidence_url=row['event_url'],
               publisher_details={k: v for k, v in (facts or {}).items() if v},
               image_extractor_version=IMAGE_VERSION)
    candidate = image_url(key, candidate)
    if candidate:
        row.update(image_url=candidate, image_provenance=IMAGE_VERSION,
                   image_evidence_url=row['event_url'])
    return row


def _hold(key, identity, reason):
    _LOG.warning('civic_event_held source=%s id=%s reason=%s', key, str(identity)[-180:], reason)


def _finish(rows, held):
    unique = {}
    for row in rows:
        identity = (row['id'], row['starts_at'])
        if identity in unique and unique[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        unique[identity] = row
    if not unique and held:
        raise ValueError('publisher_event_evidence_unavailable')
    return sorted(unique.values(), key=lambda row: (row['starts_at'], row['id']))


def _now(value):
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError('source_timezone_required')
    return result


def _check_deadline(deadline):
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _window(start, end, now):
    return start < now + timedelta(days=60) and (start >= now or (end is not None and end > now))


def _schedule(start, end, *, zone=None):
    if not isinstance(start, str) or not re.search(r'T\d{2}:\d{2}| \d{2}:\d{2}', start):
        raise EventHold('event_time_missing')
    try:
        begins = timestamp(start, zone)
        ends = timestamp(end, zone) if end else None
    except (TypeError, ValueError, KeyError) as exc:
        raise EventHold('publisher_timezone_or_time_unresolved') from exc
    if ends is not None and ends <= begins:
        raise EventHold('invalid_event_end')
    local = begins.astimezone(ZoneInfo(ZONE))
    if local.time().replace(tzinfo=None) == datetime.min.time():
        raise EventHold('placeholder_midnight_time')
    return begins, ends


def _address(value):
    if not isinstance(value, dict):
        raise EventHold('event_venue_unreviewed')
    street = plain(value.get('streetAddress') or value.get('address'))
    city = plain(value.get('addressLocality') or value.get('city'))
    state = plain(value.get('addressRegion') or value.get('state') or value.get('stateprovince'))
    postal = plain(value.get('postalCode') or value.get('zip'))
    state = 'SC' if state == 'South Carolina' else state
    if (not re.match(r'^\d{1,6}[A-Za-z]?(?:[-/]\d+)?\s+[A-Za-z]', street)
            or not city or not re.fullmatch(r'[A-Z]{2}', state)):
        raise EventHold('event_venue_unreviewed')
    street = re.sub(r',?\s*(?:United States|USA|US)\s*$', '', street, flags=re.I)
    # SCC often puts the complete address in streetAddress as well as the
    # structured locality fields. Do not duplicate city/state/ZIP in that case.
    suffix = r',\s*' + re.escape(city) + r',\s*' + re.escape(state) + r'(?:\s+\d{5}(?:-\d{4})?)?\s*$'
    if re.search(suffix, street, re.I):
        return street, city
    return f'{street}, {city}, {state}' + (f' {postal}' if postal else ''), city


def _geo(value):
    if not isinstance(value, dict):
        return None, None
    try:
        lat, lng = value.get('latitude'), value.get('longitude')
        if isinstance(lat, bool) or isinstance(lng, bool):
            return None, None
        lat, lng = float(lat), float(lng)
        if math.isfinite(lat) and math.isfinite(lng) and 32 <= lat <= 35.3 and -83.5 <= lng <= -78.2:
            return lat, lng
    except (TypeError, ValueError):
        pass
    return None, None


def _row(key, identity, title, starts, ends, venue, address, city, url, body,
         *, categories=None, geo=(None, None), facts=None, candidate=None):
    if not event_url(key, url) or not title or not identity or not venue:
        raise ValueError('publisher_event_identity_changed')
    labels = [plain(v)[:100] for v in (categories or []) if plain(v)][:20]
    row = record(title, starts.isoformat(), ends.isoformat() if ends else None,
                 venue, address, city, url, identity, ', '.join(labels), *geo,
                 tz=ZONE, publisher_geo=geo[0] is not None, retain_until_end=True)
    if row:
        row.update(timezone=ZONE, description=body[:MAX_DESCRIPTION], publisher_categories=labels,
                   location_provenance=('publisher_event_address_and_geo' if geo[0] is not None
                                        else 'publisher_event_address_pending_geocode'))
        _evidence(row, key, facts=facts, candidate=candidate)
    return row


def _weekday_check(body, starts):
    local = starts.astimezone(ZoneInfo(ZONE))
    for weekday, month, day in re.findall(
            r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+'
            r'(\d{1,2})(?:st|nd|rd|th)?\b', body, re.I):
        if (MONTHS[month.title()], int(day)) == (local.month, local.day) and weekday.lower() != local.strftime('%A').lower():
            raise EventHold('publisher_weekday_date_conflict')


def parse_santee(payload, *, now=None):
    now = _now(now)
    reader = Blocks()
    reader.feed(payload)
    reader.close()
    if reader.active:
        raise ValueError('invalid_jsonld_block')
    lists = []
    def visit(node, depth=0):
        if depth > 20:
            raise ValueError('source_record_limit')
        if isinstance(node, dict):
            if 'ItemList' in types(node):
                lists.append(node)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
    visit(reader.blocks)
    if len(lists) != 1:
        raise ValueError('unsupported_santee_calendar_shape')
    listing = lists[0]
    items, count = listing.get('itemListElement'), listing.get('numberOfItems')
    if (not isinstance(items, list) or type(count) is not int or count < 0
            or count != len(items) or count > MAX_RECORDS):
        raise ValueError('incomplete_santee_calendar')
    rows, held = [], 0
    for pos, wrapper in enumerate(items, 1):
        if (not isinstance(wrapper, dict) or wrapper.get('@type') != 'ListItem'
                or wrapper.get('position') != pos or not isinstance(wrapper.get('item'), dict)):
            raise ValueError('unsupported_santee_calendar_shape')
        item = wrapper['item']
        url, title = item.get('url'), plain(item.get('name'))
        if item.get('@type') != 'Event' or not event_url(SANTEE, url) or not title or wrapper.get('url') != url:
            raise ValueError('publisher_event_identity_changed')
        if (str(item.get('eventStatus', '')).endswith(('EventCancelled', 'EventPostponed'))
                or str(item.get('eventAttendanceMode', '')).endswith('OnlineEventAttendanceMode')
                or NONPUBLIC.search(title)):
            continue
        try:
            starts, ends = _schedule(item.get('startDate'), item.get('endDate'))
            if not _window(starts, ends, now):
                continue
            if url in SANTEE_REVIEW_HOLDS:
                raise EventHold(SANTEE_REVIEW_HOLDS[url])
            body = narrative(item.get('description'))
            _weekday_check(body, starts)
            venue = item.get('location')
            if not isinstance(venue, dict) or venue.get('@type') == 'VirtualLocation' or not plain(venue.get('name')):
                raise EventHold('event_venue_unreviewed')
            address, city = _address(venue.get('address'))
            categories = item.get('keywords') or []
            if isinstance(categories, str):
                categories = [v.strip() for v in categories.split(',') if v.strip()]
            if not isinstance(categories, list):
                raise ValueError('invalid_publisher_categories')
            offers = item.get('offers') or {}
            facts = {}
            if isinstance(offers, dict) and offers.get('price') is not None:
                facts['cost'] = plain(str(offers['price']) + ' ' + str(offers.get('priceCurrency') or ''))[:400]
            published_id = re.search(r'-([a-f0-9]{24})/$', url)
            identity = ('santee:' + published_id[1] if published_id else
                        'santee:' + sha256(url.encode()).hexdigest()[:32])
            row = _row(SANTEE, identity, title, starts, ends, plain(venue['name']),
                       address, city, url, body, categories=categories, geo=_geo(venue.get('geo')),
                       facts=facts, candidate=item.get('image'))
            if row:
                rows.append(row)
        except EventHold as exc:
            held += 1
            _hold(SANTEE, url, str(exc))
    return _finish(rows, held)


def collect_santee(source, fetch, *, deadline_at=None, now=None):
    require_source(source, SANTEE)
    deadline = min(monotonic() + 30, deadline_at or float('inf'))
    _check_deadline(deadline)
    payload = fetch(SOURCES[SANTEE]['url'], 'text/html')
    _check_deadline(deadline)
    return parse_santee(payload, now=now)


def _local_occurrence(year, month, day, weekday, start, end):
    try:
        date = datetime(year, MONTHS[month.title()], int(day))
        if weekday.lower() != date.strftime('%A').lower():
            raise EventHold('publisher_weekday_date_conflict')
        begins = datetime.combine(date, datetime.strptime(start.upper(), '%I:%M %p').time())
        finishes = datetime.combine(date, datetime.strptime(end.upper(), '%I:%M %p').time())
        return _schedule(begins.isoformat(), finishes.isoformat(), zone=ZONE)
    except (ValueError, KeyError) as exc:
        if isinstance(exc, EventHold):
            raise
        raise ValueError('invalid_beidler_schedule') from exc


def parse_beidler(payload, url, *, now=None):
    now = _now(now)
    if url not in BEIDLER_PAGES:
        raise ValueError('unregistered_beidler_page')
    soup = BeautifulSoup(payload, 'html.parser')
    canonical, heading = soup.select_one('link[rel=canonical]'), soup.select_one('h1')
    content = soup.select('section.nas_full_width_text')
    if (canonical is None or canonical.get('href') != url or heading is None
            or plain(heading.get_text()) != BEIDLER_PAGES[url] or not content
            or soup.select_one('a[href="/beidler-forest"]') is None):
        raise ValueError('beidler_page_structure_changed')
    body_html = ''.join(str(node) for node in content)
    text = plain(' '.join(node.get_text(' ', strip=True) for node in content))
    if not re.search(r'\b(?:swamp|boardwalk)\b', text, re.I):
        raise ValueError('beidler_event_location_changed')
    body = narrative(body_html)
    rows, held, schedule = [], 0, []
    if url.endswith('/boo-swamp'):
        match = re.search(r'Boo in the Swamp (20\d{2}) is on (\w+), (\w+) (\d{1,2})(?:st|nd|rd|th)?, from (\d{1,2}:\d{2}) to (\d{1,2}:\d{2}) (AM|PM)\b', text, re.I)
        if not match:
            raise ValueError('beidler_schedule_missing')
        year, weekday, month, day, start, end, meridiem = match.groups()
        schedule.append((int(year), month, day, weekday, start + ' ' + meridiem, end + ' ' + meridiem))
    else:
        headings = [node for block in content for node in block.select('h2,h3,h4')
                    if re.search(r'Schedule for 20\d{2}\b', node.get_text())]
        if len(headings) != 1:
            raise ValueError('beidler_schedule_missing')
        year = int(re.search(r'Schedule for (20\d{2})\b', headings[0].get_text())[1])
        listing = headings[0].find_next_sibling('ul')
        if listing is None or not listing.select('li') or len(listing.select('li')) > 100:
            raise ValueError('beidler_schedule_missing')
        pattern = r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),? (\w+) (\d{1,2})(?:st|nd|rd|th)?, (\d{1,2}:\d{2} (?:AM|PM)) to (\d{1,2}:\d{2} (?:AM|PM))'
        for node in listing.select('li'):
            value = plain(node.get_text())
            if NONPUBLIC.search(value):
                continue
            match = re.fullmatch(pattern, value, re.I)
            if not match:
                raise ValueError('invalid_beidler_schedule')
            weekday, month, day, start, end = match.groups()
            schedule.append((year, month, day, weekday, start, end))
    for args in schedule:
        try:
            starts, ends = _local_occurrence(*args)
            if not _window(starts, ends, now):
                continue
            facts = {}
            if url.endswith('/night-exploration'):
                cost = re.search(r'All Night Explorations are \$[0-9.]+ per person\.', text)
                if cost:
                    facts['cost'] = cost[0]
                if 'Reservations are required' in text:
                    facts['registration'] = 'Reservations are required; online reservations only; no walk-ins.'
                audience = re.search(r'This walk is NOT recommended for children under \d+\.', text)
                if audience:
                    facts['audience'] = audience[0]
            elif url.endswith('/nocturnal-family-forays'):
                cost = re.search(r'Adults: \$[0-9.]+ per person\. Children \(12 and under\): \$[0-9.]+ per person\.', text)
                if cost:
                    facts['cost'] = cost[0]
            identity = 'beidler:' + url.rsplit('/', 1)[-1] + ':' + starts.astimezone(ZoneInfo(ZONE)).date().isoformat()
            row = _row(BEIDLER, identity, BEIDLER_PAGES[url], starts, ends,
                       'Audubon Center at Beidler Forest', '336 Sanctuary Road, Harleyville, SC 29448',
                       'Harleyville', url, body, facts=facts)
            if row:
                rows.append(row)
        except EventHold as exc:
            held += 1
            _hold(BEIDLER, url, str(exc))
    return _finish(rows, held)


def collect_beidler(source, fetch, *, deadline_at=None, now=None):
    require_source(source, BEIDLER)
    deadline = min(monotonic() + 35, deadline_at or float('inf'))
    rows = []
    for url in BEIDLER_PAGES:
        _check_deadline(deadline)
        rows.extend(parse_beidler(fetch(url, 'text/html'), url, now=now))
    _check_deadline(deadline)
    return _finish(rows, 0)


def _parse_tec(items, key, now):
    rows, held = [], 0
    flags = (True, 1, '1', 'true')
    for item in items:
        title, url = plain(item.get('title')), item.get('url')
        if (item.get('status') != 'publish' or NONPUBLIC.search(title)
                or item.get('event_status') in ('cancelled', 'canceled', 'postponed')
                or any(item.get(k) in flags for k in ('all_day', 'hide_from_listings', 'is_virtual', 'virtual'))):
            continue
        if not title or not event_url(key, url):
            raise ValueError('publisher_event_identity_changed')
        venue = item.get('venue')
        if isinstance(venue, dict) and re.search(r'\b(?:virtual|online|zoom)\b', plain(venue.get('venue')), re.I):
            continue
        try:
            if item.get('timezone') != ZONE:
                raise EventHold('publisher_timezone_review_required')
            starts, ends = _schedule(item.get('start_date'), item.get('end_date'), zone=ZONE)
            if not _window(starts, ends, now):
                continue
            if starts != timestamp(item.get('utc_start_date'), 'UTC') or (ends and ends != timestamp(item.get('utc_end_date'), 'UTC')):
                raise EventHold('publisher_schedule_conflict')
            if not isinstance(venue, dict) or not plain(venue.get('venue')):
                raise EventHold('event_venue_unreviewed')
            address, city = _address(venue)
            body = narrative(item.get('description'))
            _weekday_check(body, starts)
            categories = item.get('categories') or []
            if not isinstance(categories, list) or any(not isinstance(x, dict) for x in categories):
                raise ValueError('invalid_publisher_categories')
            image = item.get('image') or {}
            row = _row(key, str(item['id']), title, starts, ends, plain(venue['venue']), address, city,
                       url, body, categories=[x.get('name') for x in categories],
                       facts={'cost': plain(item.get('cost'))[:400]},
                       candidate=image.get('url') if isinstance(image, dict) else None)
            if row:
                rows.append(row)
        except EventHold as exc:
            held += 1
            _hold(key, item.get('id'), str(exc))
    return _finish(rows, held)


def collect_tec(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if key != EUTAWVILLE:
        raise ValueError('unregistered_holly_hill_civic_source')
    require_source(source, key)
    now = _now(now)
    today = now.astimezone(ZoneInfo(ZONE)).date()
    deadline = min(monotonic() + 35, deadline_at or float('inf'))
    events, seen = [], set()
    expected = None
    for page in range(1, MAX_PAGES + 1):
        _check_deadline(deadline)
        params = {'per_page': 100, 'start_date': today.isoformat(),
                  'end_date': (today + timedelta(days=60)).isoformat(), 'page': page}
        payload = json.loads(fetch(SOURCES[key]['url'] + '?' + urlencode(params), 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
            raise ValueError('unsupported_wordpress_payload')
        total, pages = payload.get('total'), payload.get('total_pages')
        if (type(total) is not int or type(pages) is not int or total < 0 or pages < 0
                or (total == 0) != (pages == 0) or len(payload['events']) > 100):
            raise ValueError('invalid_wordpress_pagination')
        if total > MAX_RECORDS or pages > MAX_PAGES:
            raise ValueError('pagination_limit')
        if expected is None:
            expected = (total, pages)
        if expected != (total, pages):
            raise ValueError('wordpress_snapshot_changed')
        for item in payload['events']:
            identity = item.get('id') if isinstance(item, dict) else None
            if type(identity) is not int or identity <= 0 or identity in seen:
                raise ValueError('publisher_event_identity_changed')
            seen.add(identity)
            events.append(item)
        if page >= pages:
            if len(seen) != total or payload.get('next_rest_url'):
                raise ValueError('wordpress_snapshot_changed')
            break
    _check_deadline(deadline)
    return _parse_tec(events, key, now)


def _ics_stamp(event):
    from datetime import date
    value = event.decoded('DTSTART') if event.get('DTSTART') else None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError('publisher_timezone_review_required')
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        # Sorting a date-only publisher entry is not publishing a clock time.
        return datetime.combine(value, datetime.min.time(), ZoneInfo(ZONE)).astimezone(timezone.utc)
    raise ValueError('event_time_missing')


def _ics_signature(event):
    return tuple(str(event.get(key, '')) for key in
                 ('UID', 'SUMMARY', 'DTSTART', 'DTEND', 'LOCATION', 'URL', 'STATUS'))


def _ics_location(value):
    parts = [part.strip() for part in plain(value).split(',') if part.strip()]
    if parts and parts[-1].casefold() in ('united states', 'us', 'usa'):
        parts.pop()
    states = [i for i, part in enumerate(parts) if re.fullmatch(r'[A-Z]{2}', part)]
    if len(states) != 1 or states[0] < 3:
        raise EventHold('event_venue_unreviewed')
    state_index = states[0]
    if len(parts) not in (state_index + 1, state_index + 2):
        raise EventHold('event_venue_unreviewed')
    postal = parts[-1] if len(parts) == state_index + 2 else ''
    if postal and not re.fullmatch(r'\d{5}(?:-\d{4})?', postal):
        raise EventHold('event_venue_unreviewed')
    street_indexes = [i for i in range(1, state_index - 1)
                      if re.match(r'^\d{1,6}[A-Za-z]?(?:[-/]\d+)?\s+[A-Za-z]', parts[i])]
    if len(street_indexes) != 1:
        raise EventHold('event_venue_unreviewed')
    street_index = street_indexes[0]
    address, city = _address({'streetAddress': ', '.join(parts[street_index:state_index - 1]),
                             'addressLocality': parts[state_index - 1],
                             'addressRegion': parts[state_index], 'postalCode': postal})
    return ', '.join(parts[:street_index]), address, city


def _ics_public_facts(body):
    facts = {}
    for line in body.splitlines():
        if re.search(r'\b(?:free (?:admission|entry)|(?:event is|event will be) free|free and open to the public)\b', line, re.I):
            facts.setdefault('cost', line[:400])
        if re.search(r'\b(?:RSVP|registration)\b.{0,80}\brequired\b', line, re.I):
            facts.setdefault('registration', line[:400])
    return facts


def _sc250_series_month_check(url, body, starts):
    """The reviewed recurring film page explicitly limits itself to Apr/May.

    November-January ICS occurrences alone cannot resolve that conflict. Allow
    the source to recover only when its own text no longer contradicts the
    occurrence, without inventing a replacement date or changing the narrative.
    """
    if not url.startswith('https://southcarolina250.com/event/screening-ken-burns-the-revolutionary-war/'):
        return
    match = re.search(r'\bthroughout the months? of ([A-Za-z ,]+?)(?= for\b|[.\n])', body, re.I)
    if not match:
        return
    months = {MONTHS[word.title()] for word in re.findall(r'[A-Za-z]+', match[1])
              if word.title() in MONTHS}
    if months and starts.astimezone(ZoneInfo(ZONE)).month not in months:
        raise EventHold('publisher_series_month_conflict')


def collect_sc250_ics(source, fetch, *, deadline_at=None, now=None):
    """Read overlapping public exports until their ordered window is complete.

    SC250's TEC API advertises 41 occurrences but collapses recurring posts
    within each JSON page (33 objects at per_page=100 in the reviewed capture).
    The official ICS exports retain occurrence UIDs. The public list has 12
    entries per HTML page, while each export contains 30. Exact overlap proves
    progression without treating a capped first export as a complete calendar.
    """
    from icalendar import Calendar
    from roomquest.ics_adapter import parse as parse_ics

    require_source(source, SC250)
    now = _now(now)
    deadline = min(monotonic() + 35, deadline_at or float('inf'))
    previous = None
    found = {}
    complete = False
    for page in range(1, MAX_PAGES + 1):
        _check_deadline(deadline)
        url = (SOURCES[SC250]['url'] if page == 1 else
               f'https://southcarolina250.com/events/list/page/{page}/?ical=1')
        raw = fetch(url, 'text/calendar')
        if not raw.lstrip('\ufeff \r\n').startswith('BEGIN:VCALENDAR') or 'END:VCALENDAR' not in raw:
            raise ValueError('invalid_calendar_payload')
        calendar = Calendar.from_ical(raw)
        events = calendar.walk('VEVENT')
        if len(events) > 30:
            raise ValueError('sc250_ical_page_shape_changed')
        signatures, dates = [], []
        for event in events:
            if event.errors or any(event.get(key) for key in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID')):
                raise ValueError('sc250_ical_occurrence_shape_changed')
            uid = str(event.get('UID', ''))
            if not re.fullmatch(r'\d+-\d+-\d+@southcarolina250\.com', uid):
                raise ValueError('publisher_event_identity_changed')
            if not event_url(SC250, str(event.get('URL', ''))):
                raise ValueError('publisher_event_identity_changed')
            signature = _ics_signature(event)
            if uid in found and _ics_signature(found[uid]) != signature:
                raise ValueError('conflicting_event_occurrence')
            found[uid] = event
            signatures.append(signature)
            dates.append(_ics_stamp(event))
        if dates != sorted(dates) or len(signatures) != len(set(signatures)):
            raise ValueError('sc250_ical_order_changed')
        if previous is not None:
            overlap = previous[12:]
            if len(events) < len(overlap) or signatures[:len(overlap)] != overlap:
                raise ValueError('sc250_ical_pagination_changed')
        if len(events) < 30 or (dates and dates[-1] >= now + timedelta(days=60)):
            complete = True
            break
        previous = signatures
    if not complete:
        raise ValueError('pagination_limit')
    _check_deadline(deadline)
    public = Calendar()
    public.add('version', '2.0')
    public.add('prodid', '-//EventQuest reviewed public calendar normalization//EN')
    eligible, held = [], 0
    for event in found.values():
        title = plain(event.get('SUMMARY'))
        venue = plain(event.get('LOCATION'))
        if (str(event.get('STATUS', '')).upper() in ('CANCELLED', 'CANCELED')
                or NONPUBLIC.search(title)
                or re.search(r'\b(?:virtual|online|zoom)\b', venue, re.I)):
            continue
        raw_start = event.decoded('DTSTART')
        if not isinstance(raw_start, datetime):
            continue  # Date-only publisher events do not have a public start time.
        raw_end = event.decoded('DTEND') if event.get('DTEND') else None
        if raw_end is not None and not isinstance(raw_end, datetime):
            raise ValueError('invalid_event_end')
        try:
            starts, ends = _schedule(raw_start.isoformat(), raw_end.isoformat() if raw_end else None)
            if not _window(starts, ends, now):
                continue
            public.add_component(event)
            eligible.append((event, starts, ends))
        except EventHold as exc:
            held += 1
            _hold(SC250, event.get('UID'), str(exc))
    # Reuse the shared ICS validator/normalizer, including its bounded-calendar
    # and timezone checks. The common record helper below additionally retains
    # explicitly ongoing exhibits until their publisher's advertised end.
    parse_ics(public.to_ical().decode(), {'url': SOURCES[SC250]['url'], 'source_key': SC250},
              include_description=True)
    rows = []
    for event, starts, ends in eligible:
        try:
            venue, address, city = _ics_location(str(event.get('LOCATION', '')))
            body = narrative(str(event.get('DESCRIPTION', '')))
            _weekday_check(body, starts)
            _sc250_series_month_check(str(event['URL']), body, starts)
            categories = event.get('CATEGORIES')
            if not isinstance(categories, list):
                categories = [categories]
            labels = [str(label) for value in categories for label in getattr(value, 'cats', [])]
            attachments = event.get('ATTACH') or []
            if not isinstance(attachments, list):
                attachments = [attachments]
            candidates = {value for item in attachments if (value := image_url(SC250, str(item)))}
            row = _row(SC250, str(event['UID']), plain(event.get('SUMMARY')), starts, ends,
                       venue, address, city, str(event['URL']), body, categories=labels,
                       facts=_ics_public_facts(body),
                       candidate=next(iter(candidates)) if len(candidates) == 1 else None)
            if row:
                rows.append(row)
        except EventHold as exc:
            held += 1
            _hold(SC250, event.get('UID'), str(exc))
    return _finish(rows, held)


def parse_elloree(payload, source, *, now=None):
    require_source(source, ELLOREE)
    now = _now(now)
    data = json.loads(payload)
    if isinstance(data, dict) and not data.get('next') and not data.get('cursor'):
        data = data.get('data')
    if not isinstance(data, list):
        raise ValueError('unsupported_elloree_calendar_shape')
    items = data
    if len(items) > 100:
        raise ValueError('source_record_limit')
    rows, seen, held = [], set(), 0
    for item in items:
        identity = item.get('id') if isinstance(item, dict) else None
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{24}', identity) or identity in seen:
            raise ValueError('publisher_event_identity_changed')
        seen.add(identity)
        title = plain(item.get('title'))
        if not title:
            raise ValueError('publisher_event_identity_changed')
        if (item.get('is_sample') is True or item.get('all_day') is True
                or item.get('event_type') == 'Town Hall Closed'
                or NONPUBLIC.search(title) or re.search(r'\bclosed\b', title, re.I)):
            continue
        try:
            starts, ends = _schedule(item.get('start_date'), item.get('end_date'), zone=ZONE)
            if not _window(starts, ends, now):
                continue
            # Exact published venue label, not a publisher-wide fallback.
            if plain(item.get('location')).casefold() != 'elloree town hall':
                raise EventHold('event_venue_unreviewed')
            body = narrative(item.get('description'))
            _weekday_check(body, starts)
            row = _row(ELLOREE, identity, title, starts, ends, 'Elloree Town Hall',
                       '2719 West Cleveland Street, Elloree, SC 29047', 'Elloree',
                       SOURCES[ELLOREE]['url'], body, categories=[item.get('event_type')],
                       candidate=item.get('image_url'))
            if row:
                rows.append(row)
        except EventHold as exc:
            held += 1
            _hold(ELLOREE, identity, str(exc))
    return _finish(rows, held)


def collect_elloree(source, fetch, *, fetch_json=None, deadline_at=None, now=None):
    """fetch_json() is the caller's exact, bounded public POST `{}` wrapper."""
    require_source(source, ELLOREE)
    if fetch_json is None:
        raise ValueError('elloree_public_post_transport_required')
    deadline = min(monotonic() + 30, deadline_at or float('inf'))
    _check_deadline(deadline)
    page = fetch(SOURCES[ELLOREE]['url'], 'text/html')
    if ELLOREE_API not in page or 'getPublicCalendarEvents' not in page:
        raise ValueError('elloree_calendar_endpoint_changed')
    _check_deadline(deadline)
    payload = fetch_json()
    _check_deadline(deadline)
    return parse_elloree(payload, source, now=now)
