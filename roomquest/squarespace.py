"""The two owner-approved Squarespace JSON calendars; no HTML/detail requests."""
from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, timestamp

SOURCES = {
    'https://fraziermuseum.org/calendar?format=json': {
        'timezone': 'America/Kentucky/Louisville', 'state': r'(?:KY|Kentucky)',
        'bounds': (36.4, 39.2, -89.7, -81.9),
    },
    'https://missiongarden.org/events?format=json': {
        'timezone': 'America/Phoenix', 'state': r'(?:AZ|Arizona)',
        'bounds': (31.3, 37.1, -114.9, -109.0),
    },
}


def check_pagination(data, *, upcoming):
    """Only a proven past-archive cursor can be omitted from a full snapshot."""
    paging = data.get('pagination') or {}
    if not isinstance(paging, dict):
        raise ValueError('invalid_squarespace_pagination')
    if not paging.get('nextPage'):
        return
    cursor = paging.get('nextPageOffset')
    past = data.get('past')
    now = datetime.now(timezone.utc).timestamp() * 1000
    if (not upcoming or isinstance(cursor, bool) or not isinstance(cursor, (int, float))
            or not math.isfinite(cursor) or cursor >= now or not isinstance(past, list)
            or not any(isinstance(e, dict) and e.get('publishOn') == cursor
                       and not isinstance(e.get('endDate'), bool)
                       and isinstance(e.get('endDate'), (int, float))
                       and math.isfinite(e['endDate']) and e['endDate'] < now
                       for e in past)):
        raise ValueError('pagination_requires_review')


def collect(source, fetch):
    """One JSON snapshot, shared by registered catalogs and curated sources.

    No archive crawl, per-event requests, location search or response next links.
    An ambiguous/incomplete snapshot fails instead of inventing removals.
    """
    base = source['feed_url']
    root = urlsplit(base)
    query = dict(parse_qsl(root.query, keep_blank_values=True))
    if query.get('format', 'json') != 'json' or 'offset' in query:
        raise ValueError('unsupported_squarespace_endpoint')
    query['format'] = 'json'
    url = urlunsplit((root.scheme, root.netloc, root.path, urlencode(query), ''))
    payload = fetch(url, 'application/json')
    if base in SOURCES:
        return parse(payload, source)  # Retain reviewed timezone/state/location checks.
    return parse_registered(json.loads(payload), base)


def parse_registered(data, base):
    """Preserve Mapsee factual identities and reuse shared record normalization."""
    from roomquest.mapsee_adapter import record
    if not isinstance(data, dict):
        raise ValueError('unsupported_squarespace_payload')
    if 'upcoming' in data and not isinstance(data['upcoming'], list):
        raise ValueError('unsupported_squarespace_payload')
    upcoming = isinstance(data.get('upcoming'), list)
    rows = data.get('upcoming') if upcoming else data.get('items')
    if not isinstance(rows, list):
        raise ValueError('unsupported_squarespace_payload')
    if len(rows) > 500:
        raise ValueError('source_record_limit')
    check_pagination(data, upcoming=upcoming)
    out = {}
    for e in rows:
        if not isinstance(e, dict):
            raise ValueError('invalid_calendar_record')
        if e.get('cancelled') is True or (e.get('workflowState') is not None and e['workflowState'] != 1):
            continue
        if e.get('allDay') or e.get('allDayEvent'):
            continue
        if not isinstance(e.get('id'), str) or not e['id'].strip():
            raise ValueError('event_identity_missing')
        for key in ('startDate', 'endDate'):
            value = e.get(key)
            if key == 'endDate' and value is None:
                continue  # Retain explicit missing end; never estimate an end.
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('event_time_missing')
        v = e.get('location') or {}
        if not isinstance(v, dict):
            raise ValueError('invalid_event_location')
        street = ', '.join(plain(v[k]) for k in ('addressLine1', 'addressLine2') if v.get(k))
        lat, lng = v.get('mapLat'), v.get('mapLng')
        marker = (v.get('markerLat'), v.get('markerLng'))
        if marker[0] is not None and marker[1] is not None:
            conflict = False
            if lat is not None and lng is not None:
                try:
                    conflict = not all(math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-7)
                                       for a, b in zip((lat, lng), marker))
                except (TypeError, ValueError, OverflowError):
                    conflict = True
            if conflict:
                lat = lng = None  # Conflicting evidence is held for location review.
            else:
                lat, lng = marker
        if isinstance(lat, bool) or isinstance(lng, bool):
            lat = lng = None
        path = e.get('fullUrl') or e.get('urlId')
        if not isinstance(path, str) or not path.strip():
            raise ValueError('event_link_missing')
        row = record(e.get('title'), e.get('startDate'), e.get('endDate'),
                     v.get('addressTitle'), street, '', urljoin(base, path), e['id'],
                     ', '.join(str(x) for x in e.get('categories', [])), lat, lng)
        if row:
            key = (row['id'], row['starts_at'])
            if key in out and out[key] != row:
                raise ValueError('conflicting_event_occurrence')
            out[key] = row
    result = sorted(out.values(), key=lambda e: (e['starts_at'], e['title']))
    if result and not any(e.get('venue_name') or e.get('venue_address') for e in result):
        raise ValueError('venue_extraction_unavailable')
    return result


def parse(payload, source):
    from roomquest.preview_worker import _preview
    base = source.get('feed_url')
    config = SOURCES.get(base)
    if not config:
        raise ValueError('unregistered_squarespace_source')
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get('upcoming'), list):
        raise ValueError('unsupported_squarespace_payload')
    if (data.get('website') or {}).get('timeZone') != config['timezone']:
        raise ValueError('publisher_timezone_changed')
    rows = data['upcoming']
    if len(rows) > 100:
        raise ValueError('source_record_limit')
    check_pagination(data, upcoming=True)
    out = {}
    for event in rows:
        if not isinstance(event, dict):
            raise ValueError('invalid_calendar_record')
        if event.get('workflowState') != 1 or event.get('cancelled') is True:
            continue
        if event.get('allDay') or event.get('allDayEvent'):
            continue
        identity = event.get('id')
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('event_identity_missing')
        if not plain(event.get('title')):
            raise ValueError('event_title_missing')
        times = [event.get(k) for k in ('startDate', 'endDate')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in times):
            raise ValueError('event_time_missing')
        start, end = (timestamp(v) for v in times)
        if end < start:
            raise ValueError('invalid_event_end')
        local = [v.astimezone(ZoneInfo(config['timezone'])) for v in (start, end)]
        if all(v.hour == v.minute == 0 for v in local):
            continue  # An undifferentiated all-day span is not a timed event.
        location = event.get('location') or {}
        if not isinstance(location, dict):
            raise ValueError('invalid_event_location')
        street = plain(location.get('addressLine1'))
        locality = plain(location.get('addressLine2'))
        address = ', '.join(v for v in (street, locality) if v)
        venue = plain(location.get('addressTitle'))
        city = locality.split(',')[0].strip() if ',' in locality else ''
        lat, lng = location.get('markerLat'), location.get('markerLng')
        south, north, west, east = config['bounds']
        valid_geo = (not isinstance(lat, bool) and not isinstance(lng, bool)
                     and isinstance(lat, (int, float)) and isinstance(lng, (int, float))
                     and south <= lat <= north and west <= lng <= east
                     and re.search(r'\b\d{1,6}\s+\w', street)
                     and re.search(r',\s*' + config['state'] + r'\b', locality))
        if not valid_geo:
            lat = lng = None  # Hold factual address; never substitute a default pin.
        path = event.get('fullUrl')
        if not isinstance(path, str) or not path.startswith(urlsplit(base).path.rstrip('/') + '/'):
            raise ValueError('invalid_event_link')
        link = urljoin(base, path)
        if urlsplit(link).netloc != urlsplit(base).netloc:
            raise ValueError('invalid_event_link')
        record = _preview(plain(event.get('title')), start, end, venue, lat, lng,
                          link, identity, ', '.join(str(v) for v in event.get('categories', [])),
                          address, city, allow_ongoing=True)
        if record:
            key = (identity, record['starts_at'])
            if key in out and out[key] != record:
                raise ValueError('conflicting_event_occurrence')
            out[key] = record
    return sorted(out.values(), key=lambda e: (e['starts_at'], e['id']))

