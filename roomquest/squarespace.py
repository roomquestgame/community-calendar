"""The two owner-approved Squarespace JSON calendars; no HTML/detail requests."""
from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import urljoin, urlsplit
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
    paging = data.get('pagination') or {}
    if paging.get('nextPage'):
        # Squarespace's cursor here pages the separate past archive. Require
        # explicit evidence that it is a past record, never ignore an unknown
        # cursor or fetch the archive repeatedly as if it were future pages.
        cursor = paging.get('nextPageOffset')
        past = data.get('past')
        if (not isinstance(cursor, (int, float)) or not math.isfinite(cursor)
                or cursor >= datetime.now(timezone.utc).timestamp() * 1000
                or not isinstance(past, list)
                or not any(isinstance(e, dict) and e.get('publishOn') == cursor
                           and isinstance(e.get('endDate'), (int, float))
                           and e['endDate'] < datetime.now(timezone.utc).timestamp() * 1000
                           for e in past)):
            raise ValueError('pagination_requires_review')
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
