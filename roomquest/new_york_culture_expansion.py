"""Remaining Astor Center classes and Green-Wood public programs.

The supplied publisher transport owns robots, DNS, pacing and redirects. Native
monthly HTML manifests are hydrated with complete event pages; no WordPress API
or restricted Astor controls route is used. Partial descriptions stay private
until every manifest item is resolved and the full manifest is revalidated.
"""
from __future__ import annotations

from copy import deepcopy
from calendar import Calendar
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
ASTOR = 'astor_center_new_york_ny'
GREENWOOD = 'green_wood_cemetery_brooklyn_ny'
SOURCES = {
    ASTOR: ('https://www.astorcenternyc.com/calendar.aspx', 'html', 'html'),
    GREENWOOD: ('https://www.green-wood.com/calendar/month/', 'html', 'html'),
}
ASTOR_CATALOG = 'https://www.astorcenternyc.com/courses.ac?rel=nav'
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
MAX_DESCRIPTION = 12000
MAX_RECORDS = 200
MAX_CHECKPOINT_BYTES = 900000
MAX_DETAILS = 3
CHECKPOINT_MANIFEST_LIMITS = {key: MAX_RECORDS for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: MAX_RECORDS for key in SOURCES}

# Actual attendee streets from the publishers' directions/event bodies, paired
# with exact NYC Planning PAD house/street/borough/ZIP matches (2026-11-15).
# PAD identifies an address point, not an interior architectural feature.
VENUES = {
    'astor': ('Astor Center', '23 East 4th Street, New York, NY 10003',
              'New York', 40.727811, -73.992568),
    'main': ('Green-Wood Cemetery — Main Entrance', '500 25th Street, Brooklyn, NY 11232',
             'Brooklyn', 40.658098, -73.994843),
    'arch': ('Green-Wood Cemetery — Gothic Arch (approximate meeting point)',
             '500 25th Street, Brooklyn, NY 11232', 'Brooklyn', 40.658098, -73.994843),
    'house': ('Green-Wood — The Green-House', '750 Fifth Avenue, Brooklyn, NY 11232',
              'Brooklyn', 40.659118, -73.996097),
    # LPC designation LP-01233 identifies Historic Chapel BIN 3395903. NYC
    # OTI's BUILDING_P feature supplies its centroid, not an entrance point.
    'historic_chapel': ('Green-Wood Cemetery — Historic Chapel (approximate meeting point)',
                       '500 25th Street, Brooklyn, NY 11232', 'Brooklyn', 40.656346, -73.995307),
    # The native program explicitly locates the Modern Chapel near the Main
    # Entrance at 500 25th Street. Its exact doorway is not geocoded; retain
    # the verified nearby PAD address point and identify it as approximate.
    'modern_chapel': ('Green-Wood Cemetery — Modern Chapel (approximate meeting point)',
                     '500 25th Street, Brooklyn, NY 11232', 'Brooklyn', 40.658098, -73.994843),
}
# Two pages retain a different canonical slug. Their native Event
# URL, title, occurrence clocks and visible full body identify the requested
# occurrence. This exact alias does not permit a redirect or another hostname.
GREENWOOD_CANONICAL_ALIASES = {
    'https://www.green-wood.com/event/rest-in-pace-green-house-2/2026-11-15/':
        'https://www.green-wood.com/event/rest-in-pace-green-house/2026-11-15/',
    'https://www.green-wood.com/event/conifers/':
        'https://www.green-wood.com/event/conifers/2026-12-06/',
}
# These two November After Hours pages omit check-in. The publisher's same
# 2026 tour series explicitly meets at the Gothic Arch (500 25th Street):
# https://www.green-wood.com/event/green-wood-after-hours-47/2026-08-01/
# The estimate is bound to the reviewed current full body and exact event URLs;
# a changed body or newly scheduled tour must provide its own reviewed location.
AFTER_HOURS_ESTIMATES = {
    'https://www.green-wood.com/event/green-wood-after-hours-60/':
        '0351897371f2e3b0613704cef661ae93724b1b1a94c2b4f7da2e24a87b32ad05',
    'https://www.green-wood.com/event/green-wood-after-hours-61/':
        '0351897371f2e3b0613704cef661ae93724b1b1a94c2b4f7da2e24a87b32ad05',
}
NONPUBLIC = re.compile(r'\b(?:cancelled|canceled|postponed|members[ -]only|private event|sold out|fully booked)\b', re.I)
VISITING = re.compile(r'^(?:general admission|(?:museum|cemetery|opening|visiting) hours)\b', re.I)
HOLD_REASONS = {'event_not_current', 'event_not_public', 'description_missing',
                'description_limit', 'venue_unreviewed', 'schedule_unresolved'}
ERROR_CODES = {'nyc_culture_' + suffix for suffix in (
    'source_unregistered', 'identity_changed', 'schedule_changed', 'listing_changed',
    'manifest_incomplete', 'manifest_limit', 'record_limit', 'checkpoint_invalid',
    'checkpoint_size_limit', 'detail_changed', 'conflicting_occurrence',
)} | {'collection_deadline', 'publisher_checkpoint_required'}


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('nyc_culture_source_unregistered')
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        parsed = urlsplit(value)
        pattern = (r'/class-[a-z0-9-]+\.ac' if key == ASTOR else
                   r'/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/(?:[1-9][0-9]?/)?)?')
        return (parsed.scheme == 'https' and parsed.netloc == ALLOWED_HOSTS[key][0]
                and not parsed.query and not parsed.fragment
                and re.fullmatch(pattern, parsed.path) is not None)
    except ValueError:
        return False


def _check(deadline):
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError('description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('description_limit')
    return text


def _digest(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _row_key(row):
    return row['id'] + '|' + row['starts_at']


def _json_events(soup):
    result = []
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            raise ValueError('nyc_culture_listing_changed') from None
        nodes = data if isinstance(data, list) else data.get('@graph', [data]) if isinstance(data, dict) else []
        for node in nodes:
            if isinstance(node, dict) and node.get('@type') == 'Event':
                result.append(node)
    return result


def _aware(value):
    result = timestamp(value)
    if (not result or result.tzinfo is None
            or result.utcoffset() != result.astimezone(ZoneInfo(ZONE)).utcoffset()):
        raise ValueError('nyc_culture_schedule_changed')
    return result


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _astor_manifest(fetch, deadline, now):
    _check(deadline)
    soup = BeautifulSoup(fetch(SOURCES[ASTOR][0], 'text/html'), 'html.parser')
    if not soup.select_one('.calendar-month-day') or not soup.select_one('a.date-title'):
        raise ValueError('nyc_culture_listing_changed')
    months = soup.select('a.date-title')
    years = soup.select('span.year')
    if len(months) != 1 or len(years) != 1:
        raise ValueError('nyc_culture_listing_changed')
    try:
        month = datetime.strptime(plain(months[0].get_text()) + ' ' + plain(years[0].get_text()), '%B %Y')
    except ValueError:
        raise ValueError('nyc_culture_listing_changed') from None
    queue = {}
    for cell in soup.select('.calendar-month-day'):
        for link in cell.select('a[href]'):
            url = urljoin(SOURCES[ASTOR][0], link['href'])
            if not event_url(ASTOR, url):
                raise ValueError('nyc_culture_identity_changed')
            try:
                day = month.replace(day=int(cell.select_one('span.day').get_text(strip=True))).date()
            except (AttributeError, ValueError):
                raise ValueError('nyc_culture_listing_changed') from None
            if not now.astimezone(ZoneInfo(ZONE)).date() <= day <= (now + timedelta(days=60)).date():
                continue
            title = plain(link.get_text())
            item = {'id': urlsplit(url).path[1:-3], 'url': url, 'title': title, 'dates': [day.isoformat()]}
            if not title:
                raise ValueError('nyc_culture_identity_changed')
            if url in queue:
                if queue[url]['title'] != title:
                    raise ValueError('nyc_culture_identity_changed')
                queue[url]['dates'] = sorted(set(queue[url]['dates'] + item['dates']))
            else:
                queue[url] = item
    # The month view omits later published months. The site's linked 'View All'
    # catalog is the complete class list; each detail supplies its own dated
    # occurrences, including later dates of a class already on this calendar.
    if not any(urljoin(SOURCES[ASTOR][0], a.get('href', '')) == ASTOR_CATALOG for a in soup.select('a[href]')):
        raise ValueError('nyc_culture_manifest_incomplete')
    _check(deadline)
    catalog = BeautifulSoup(fetch(ASTOR_CATALOG, 'text/html'), 'html.parser')
    listing = catalog.select_one('ul.event-teaser-list-md')
    heading = catalog.find('h1')
    if not listing or not heading or plain(heading.get_text()) != 'All Astor Center Events' or catalog.select('a[rel~=next]'):
        raise ValueError('nyc_culture_listing_changed')
    complete = {}
    for card in listing.select(':scope > li'):
        link, title_node = card.select_one('a[href]'), card.select_one('.event-title')
        url = urljoin(ASTOR_CATALOG, link['href']) if link else None
        title = plain(title_node.get_text()) if title_node else ''
        if not event_url(ASTOR, url) or not title or url in complete:
            raise ValueError('nyc_culture_identity_changed')
        if url in queue and queue[url]['title'] != title:
            raise ValueError('nyc_culture_identity_changed')
        complete[url] = {'id': urlsplit(url).path[1:-3], 'url': url, 'title': title,
                         'dates': queue[url]['dates'] if url in queue else []}
    if not set(queue).issubset(complete):
        raise ValueError('nyc_culture_manifest_incomplete')
    if len(complete) > MAX_RECORDS:
        raise ValueError('nyc_culture_manifest_limit')
    return sorted(complete.values(), key=lambda item: item['url'])


def _greenwood_page(payload, expected_month, now):
    soup = BeautifulSoup(payload, 'html.parser')
    month = soup.select_one('time.tribe-events-c-top-bar__datepicker-time')
    if not month or month.get('datetime') != expected_month:
        raise ValueError('nyc_culture_listing_changed')
    events = {}
    for event in _json_events(soup):
        url, title = event.get('url'), plain(event.get('name'))
        if not event_url(GREENWOOD, url) or not title:
            raise ValueError('nyc_culture_identity_changed')
        start, end = _aware(event.get('startDate')), _aware(event.get('endDate'))
        if end <= start:
            raise ValueError('nyc_culture_schedule_changed')
        item = {'id': 'greenwood-' + sha256(url.encode()).hexdigest()[:24],
                'url': url, 'title': title, 'starts_at': start.isoformat(), 'ends_at': end.isoformat()}
        if url in events and events[url] != item:
            raise ValueError('nyc_culture_schedule_changed')
        events[url] = item
    # The desktop calendar renders only three cards per day. Its JSON-LD must
    # account for the complete advertised per-day total, including '+ N More'.
    days = soup.select('.tribe-events-calendar-month__day-cell--desktop')
    if not days:
        raise ValueError('nyc_culture_manifest_incomplete')
    seen_days = set()
    for cell in days:
        day_node = cell.select_one('time.tribe-events-calendar-month__day-date-daynum')
        total_node = cell.select_one('.tribe-common-a11y-visual-hide')
        day = day_node.get('datetime') if day_node else None
        total = re.fullmatch(r'(\d+) events?,?', plain(total_node.get_text()) if total_node else '')
        if not day or not total or day in seen_days:
            raise ValueError('nyc_culture_manifest_incomplete')
        seen_days.add(day)
        dated = [item for item in events.values() if timestamp(item['starts_at']).date().isoformat() == day]
        count = len(dated)
        # The publisher retains an extra already-ended related event in its
        # JSON-LD on some past days. It cannot hide a missing current item or
        # enter the future queue; future daily totals must still match exactly.
        ended_extra = count > int(total[1]) and all(timestamp(item['ends_at']) <= now for item in dated)
        if count != int(total[1]) and not ended_extra:
            raise ValueError('nyc_culture_manifest_incomplete')
    target = datetime.strptime(expected_month, '%Y-%m').date()
    expected_days = {day.isoformat() for day in Calendar(firstweekday=6).itermonthdates(target.year, target.month)}
    if seen_days != expected_days:
        raise ValueError('nyc_culture_manifest_incomplete')
    links = {a.get('href') for a in soup.select('a[rel~=next]')}
    if len(links) > 1:
        raise ValueError('nyc_culture_manifest_incomplete')
    return list(events.values()), next(iter(links), None)


def _greenwood_manifest(fetch, deadline, now):
    month = now.astimezone(ZoneInfo(ZONE)).date().replace(day=1)
    end_month = (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date().replace(day=1)
    url, queue = SOURCES[GREENWOOD][0], {}
    for _ in range(3):
        _check(deadline)
        items, next_url = _greenwood_page(fetch(url, 'text/html'), month.strftime('%Y-%m'), now)
        for item in items:
            if not _within(timestamp(item['starts_at']), timestamp(item['ends_at']), now):
                continue
            if item['url'] in queue and queue[item['url']] != item:
                raise ValueError('nyc_culture_schedule_changed')
            queue[item['url']] = item
        if len(queue) > MAX_RECORDS:
            raise ValueError('nyc_culture_manifest_limit')
        if not next_url or month >= end_month:
            break
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        expected = 'https://www.green-wood.com/calendar/month/' + month.strftime('%Y-%m') + '/'
        if next_url != expected:
            raise ValueError('nyc_culture_manifest_incomplete')
        url = next_url
    else:
        raise ValueError('nyc_culture_manifest_incomplete')
    return sorted(queue.values(), key=lambda item: (item['starts_at'], item['url']))


def _manifest(key, fetch, deadline, now):
    return (_astor_manifest if key == ASTOR else _greenwood_manifest)(fetch, deadline, now)


def _row(key, item, start, end, body, place, labels):
    name, street, city, lat, lng = VENUES[place]
    identity = item['id'] + ':' + start.isoformat() if key == ASTOR else item['id']
    row = record(item['title'], start.isoformat(), end.isoformat() if end else None,
                 name, street, city, item['url'], identity, ', '.join(labels), lat, lng,
                 ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        provenance = {
            'arch': 'publisher_named_arch_approximate_PAD_meeting_point',
            'historic_chapel': 'publisher_named_chapel_and_official_NYC_building_centroid',
            'modern_chapel': 'publisher_named_chapel_near_entrance_approximate_PAD_meeting_point',
        }
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                   publisher_categories=labels, location_provenance=provenance.get(
                       place, 'publisher_attendee_street_and_exact_NYC_PAD_address_point'))
        if place in {'arch', 'historic_chapel', 'modern_chapel'}:
            row['location_is_approximate'] = True
    return row


def _astor_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    heading = soup.find('h1')
    nodes = _json_events(soup)
    if not 0 < len(nodes) <= 60 or not heading or plain(heading.get_text()) != item['title'] or any(plain(node.get('name')) != item['title'] for node in nodes):
        raise ValueError('nyc_culture_identity_changed')
    container = soup.select_one('.event-description')
    if not container:
        raise ValueError('description_missing')
    body = _body(str(container))
    # Astor's full native JSON-LD body should agree with its visible full body.
    native_starts = []
    for event in nodes:
        venue = event.get('location', {})
        if (not isinstance(venue, dict) or plain(venue.get('name')) != 'Astor Center'
                or plain(venue.get('address')) not in {'399 Lafayette Street, New York, NY 10003',
                                                      '23 East 4th Street, New York, NY 10003'}):
            raise ValueError('venue_unreviewed')
        if _body(event.get('description')) != body:
            raise ValueError('nyc_culture_detail_changed')
        try:
            native_starts.append(timestamp(datetime.strptime(event['startDate'], '%m/%d/%Y %I:%M:%S %p').isoformat(), ZONE))
        except (KeyError, TypeError, ValueError):
            raise ValueError('schedule_unresolved') from None
    if len(set(native_starts)) != len(native_starts):
        raise ValueError('nyc_culture_schedule_changed')
    options = soup.select('.event__date__cta__row')
    if not options:
        raise ValueError('schedule_unresolved')
    listed_dates = {datetime.fromisoformat(day).date() for day in item['dates']}
    dates = {value.date() for value in native_starts}
    if not listed_dates.issubset(dates):
        raise ValueError('nyc_culture_schedule_changed')
    starts, scheduled, seen = [], [], set()
    for option in options:
        value = option.select_one('.event__date')
        if not value:
            raise ValueError('nyc_culture_detail_changed')
        try:
            partial = datetime.strptime(plain(value.get_text()), '%A, %b %d %I:%M %p')
        except ValueError:
            raise ValueError('schedule_unresolved') from None
        matches = [day for day in dates if (day.month, day.day) == (partial.month, partial.day)]
        if len(matches) != 1 or matches[0] in seen:
            raise ValueError('nyc_culture_schedule_changed')
        seen.add(matches[0])
        start = timestamp(partial.replace(year=matches[0].year).isoformat(), ZONE)
        scheduled.append(start)
        if not NONPUBLIC.search(plain(option.get_text())):
            starts.append(start)
    if seen != dates or set(native_starts) != set(scheduled):
        raise ValueError('nyc_culture_schedule_changed')
    duration = re.search(r'\b(?:class is|classes are) (\d+(?:\.\d+)?) hours? long\b', body, re.I)
    hours = float(duration[1]) if duration else None
    if hours is not None and not 0 < hours <= 8:
        raise ValueError('schedule_unresolved')
    rows = []
    for start in starts:
        end = start + timedelta(hours=hours) if hours is not None else None
        if _within(start, end, now):
            row = _row(ASTOR, item, start, end, body, 'astor', ['Classes & Tastings'])
            if row:
                rows.append(row)
    return rows


def _greenwood_venue(body):
    found = re.search(r'Where\s+To\s+Go\s*:\s*(.+?)(?=Accessibility|Refunds:|Inclement Weather|$)', plain(body), re.I)
    meeting = found[1] if found else ''
    if re.search(r'Green[ -]House', meeting, re.I) and re.search(r'750\s+(?:Fifth|5th)\s+Avenue', meeting, re.I):
        return 'house'
    if (re.search(r'500\s+25th\s+Street', meeting, re.I)
            or re.search(r'(?:Fifth|5th)\s+Avenue', meeting, re.I) and re.search(r'25th\s+Street', meeting, re.I)):
        if re.search(r'Historic Chapel', meeting, re.I):
            return 'historic_chapel'
        if re.search(r'Modern Chapel', meeting, re.I) and re.search(r'Main Entrance', meeting, re.I):
            return 'modern_chapel'
        if re.search(r'Gothic Arch', meeting, re.I):
            return 'arch'
        if re.search(r'Main Entrance', meeting, re.I):
            return 'main'
    raise ValueError('venue_unreviewed')


def _greenwood_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    canonical = soup.select_one('link[rel=canonical]')
    heading = soup.select_one('.tribe-events-single-event-title')
    canonical_urls = {item['url']}
    if alias := GREENWOOD_CANONICAL_ALIASES.get(item['url']):
        canonical_urls.add(alias)
    if not canonical or canonical.get('href') not in canonical_urls or not heading:
        raise ValueError('nyc_culture_identity_changed')
    if NONPUBLIC.search(plain(heading.get_text())):
        raise ValueError('event_not_public')
    if plain(heading.get_text()) != item['title']:
        raise ValueError('nyc_culture_identity_changed')
    nodes = [node for node in _json_events(soup) if node.get('url') == item['url']]
    if len(nodes) != 1 or plain(nodes[0].get('name')) != item['title']:
        raise ValueError('nyc_culture_identity_changed')
    event = nodes[0]
    start, end = _aware(event.get('startDate')), _aware(event.get('endDate'))
    if start != timestamp(item['starts_at']) or end != timestamp(item['ends_at']):
        raise ValueError('nyc_culture_schedule_changed')
    if (event.get('eventStatus') != 'https://schema.org/EventScheduled'
            or event.get('eventAttendanceMode') != 'https://schema.org/OfflineEventAttendanceMode'):
        raise ValueError('event_not_public')
    container = soup.select_one('#tribe-events-content > div[id^=post-].tribe_events')
    if not container:
        raise ValueError('description_missing')
    # Preserve all narrative, fees, access instructions, age limits and weather
    # terms. Remove only the date/series/calendar controls around that content.
    for control in container.select('.tribe-events-series-relationship-single-marker, .tribe-events-schedule, .tribe-block__events-link'):
        control.decompose()
    body = _body(str(container))
    estimated = False
    try:
        place = _greenwood_venue(body)
    except ValueError:
        if (item['title'] != 'Green-Wood After Hours'
                or AFTER_HOURS_ESTIMATES.get(item['url']) != sha256(body.encode()).hexdigest()):
            raise
        place, estimated = 'arch', True
    if not _within(start, end, now):
        return []
    labels = [name.removeprefix('tribe_events_cat-').replace('-', ' ') for name in container.get('class', []) if name.startswith('tribe_events_cat-')]
    row = _row(GREENWOOD, item, start, end, body, place, labels or ['Public Programs'])
    if row and estimated:
        row['location_provenance'] = 'reviewed_same_tour_series_estimated_checkin_and_PAD_address_point'
        row['location_is_approximate'] = True
    return [row] if row else []


def _unique(rows):
    result = {}
    for row in rows:
        identity = (row['id'], row['starts_at'])
        if identity in result and result[identity] != row:
            raise ValueError('nyc_culture_conflicting_occurrence')
        result[identity] = row
    if len(result) > MAX_RECORDS:
        raise ValueError('nyc_culture_record_limit')
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))


def _new_state(key, queue, now):
    return dict(version=1, source_key=key, started_at=now.isoformat(),
                window_start=now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                manifest_hash=_digest(queue), manifest_count=len(queue), cursor=0,
                queue=queue, events=[], row_hashes={}, diagnostics=[], manifest_verified=not queue)


def _checkpoint(key, value, now):
    if value is None:
        return None
    try:
        if (not isinstance(value, dict) or type(value['version']) is not int or value['version'] != 1
                or value['source_key'] != key or type(value['cursor']) is not int
                or type(value['manifest_count']) is not int
                or not 0 <= value['cursor'] <= value['manifest_count'] <= MAX_RECORDS
                or not isinstance(value['queue'], list) or len(value['queue']) != value['manifest_count']
                or not isinstance(value['events'], list) or len(value['events']) > MAX_RECORDS
                or not isinstance(value['row_hashes'], dict) or len(value['row_hashes']) != len(value['events'])
                or not isinstance(value['diagnostics'], list) or len(value['diagnostics']) != value['cursor']
                or type(value['manifest_verified']) is not bool
                or value['manifest_verified'] and value['cursor'] != value['manifest_count']
                or not isinstance(value['started_at'], str)
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value['started_at'])
                or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
            raise ValueError
        started = timestamp(value['started_at'])
        if value['window_start'] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        if not started <= now <= started + timedelta(hours=4):
            return None
        queue = value['queue']
        for item in queue:
            fields = {'id', 'url', 'title', 'dates'} if key == ASTOR else {'id', 'url', 'title', 'starts_at', 'ends_at'}
            if (not isinstance(item, dict) or set(item) != fields or not event_url(key, item['url'])
                    or not isinstance(item['id'], str) or not item['id']
                    or not isinstance(item['title'], str) or not item['title'].strip()):
                raise ValueError
            if key == ASTOR:
                if (not isinstance(item['dates'], list) or not 0 <= len(item['dates']) <= 60
                        or len(set(item['dates'])) != len(item['dates'])
                        or any(not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', day) for day in item['dates'])):
                    raise ValueError
            elif _aware(item['ends_at']) <= _aware(item['starts_at']):
                raise ValueError
        if len({item['url'] for item in queue}) != len(queue) or value['manifest_hash'] != _digest(queue):
            raise ValueError
        processed = {item['url']: item for item in queue[:value['cursor']]}
        decisions = {}
        for decision in value['diagnostics']:
            if (not isinstance(decision, dict) or decision.get('event_url') not in processed
                    or decision['event_url'] in decisions or decision.get('disposition') not in {'held', 'accepted'}
                    or type(decision.get('event_count')) is not int or decision['event_count'] < 0
                    or decision['disposition'] == 'held' and decision.get('reason') not in HOLD_REASONS):
                raise ValueError
            decisions[decision['event_url']] = decision
        counts = {url: 0 for url in processed}
        venues = {VENUES['astor']} if key == ASTOR else {value for name, value in VENUES.items() if name != 'astor'}
        row_keys = set()
        for row in value['events']:
            item = processed.get(row.get('event_url')) if isinstance(row, dict) else None
            if (not item or row.get('title') != item['title']
                    or not isinstance(row.get('description'), str) or not 0 < len(row['description']) <= MAX_DESCRIPTION
                    or not row['description'].strip() or row.get('timezone') != ZONE
                    or row.get('attendance_mode') != 'in_person'
                    or tuple(row.get(field) for field in ('venue_name', 'venue_address', 'venue_city', 'lat', 'lng')) not in venues):
                raise ValueError
            marker = _row_key(row)
            if value['row_hashes'].get(marker) != _digest(row):
                raise ValueError
            row_keys.add(marker)
            start = timestamp(row.get('starts_at'))
            end = timestamp(row.get('ends_at'))
            if not start or not start.tzinfo or end and (not end.tzinfo or end <= start):
                raise ValueError
            if not _within(start, end, started):
                raise ValueError
            if key == ASTOR:
                if row.get('id') != item['id'] + ':' + start.astimezone(ZoneInfo(ZONE)).isoformat():
                    raise ValueError
            elif (row.get('id') != item['id'] or start != timestamp(item['starts_at']) or end != timestamp(item['ends_at'])):
                raise ValueError
            counts[item['url']] += 1
        if (any(counts[url] != decisions[url]['event_count']
                or (counts[url] > 0) != (decisions[url]['disposition'] == 'accepted') for url in processed)
                or len(_unique(value['events'])) != len(value['events'])
                or set(value['row_hashes']) != row_keys):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError('nyc_culture_checkpoint_invalid') from None
    return deepcopy(value)


def _bounded_pause(error):
    from roomquest.preview_worker import PreviewError
    return (isinstance(error, PreviewError) and str(error) in {'publisher_pacing_deferred', 'source_fetch_deadline'}
            or type(error) is ValueError and str(error) == 'collection_deadline')


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source)
    raise ValueError('publisher_checkpoint_required')


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS):
    key = _source(source)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = _checkpoint(key, checkpoint, current)
    if state and state['manifest_verified']:
        return dict(complete=True, events=_unique(deepcopy(state['events'])), checkpoint=state)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    started = timestamp(state['started_at']) if state else current
    if state is None:
        state = _new_state(key, _manifest(key, fetch, deadline, started), started)
    queue = state['queue']
    prior, paused = state['cursor'], False
    detail = _astor_detail if key == ASTOR else _greenwood_detail
    while state['cursor'] < len(queue) and state['cursor'] - prior < min(MAX_DETAILS, max(1, int(max_details))):
        if monotonic() + 12 >= deadline:
            break
        item, reason = queue[state['cursor']], 'event_not_current'
        try:
            if NONPUBLIC.search(item['title']) or VISITING.search(item['title']):
                raise ValueError('event_not_public')
            rows = _unique(detail(item, fetch(item['url'], 'text/html'), started))
        except ValueError as error:
            if _bounded_pause(error):
                paused = True
                break
            if str(error) not in HOLD_REASONS:
                raise
            rows, reason = [], str(error)
        state['events'].extend(rows)
        state['row_hashes'].update({_row_key(row): _digest(row) for row in rows})
        state['diagnostics'].append(dict(event_url=item['url'], disposition='accepted' if rows else 'held',
                                         event_count=len(rows), reason=None if rows else reason))
        state['cursor'] += 1
    if not paused and state['cursor'] == len(queue) and not state['manifest_verified'] and monotonic() + 20 < deadline:
        try:
            latest = _manifest(key, fetch, deadline, started)
        except ValueError as error:
            if not _bounded_pause(error):
                raise
        else:
            if _digest(latest) == state['manifest_hash']:
                state['manifest_verified'] = True
            else:
                state = _new_state(key, latest, started)
    if len(state['events']) > MAX_RECORDS or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('nyc_culture_checkpoint_size_limit')
    complete = state['manifest_verified']
    return dict(complete=complete, events=_unique(deepcopy(state['events'])) if complete else [], checkpoint=state)
