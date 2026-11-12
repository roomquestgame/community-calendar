"""Collect timed Chesapeake Public Library programs from the city's public calendar."""
from datetime import datetime, timedelta
import json
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record, timestamp

KEY = 'municipal_14cf2462473c7970657e86f4'
HOST = 'www.cityofchesapeake.net'
URL = f'https://{HOST}/m/Calendar'
MONTH_URL = f'https://{HOST}/m/Calendar/Home/MonthEvents'
ZONE = 'America/New_York'
BRANCHES = {
    'Central Library': '298 Cedar Road, Chesapeake, VA 23322',
    'Dr. Clarence V. Cuffee Library': '2726 Border Road, Chesapeake, VA 23324',
    'Greenbrier Library': '1214 Volvo Parkway, Chesapeake, VA 23320',
    'Indian River Library': '2320 Old Greenbrier Road, Chesapeake, VA 23325',
    'Major Hillard Library': '824 Old George Washington Highway N, Chesapeake, VA 23323',
    'Russell Memorial Library': '2808 Taylor Road, Chesapeake, VA 23321',
    'South Norfolk Memorial Library': '801 Poindexter Street, Chesapeake, VA 23324',
}
DISPLAY_TIME = re.compile(r'(\d{1,2})(?::(\d{2}))?([ap])')


def _display_clock(value):
    match = DISPLAY_TIME.fullmatch(value.strip().casefold())
    if not match:
        return None
    hour, minute, meridiem = match.groups()
    if not 1 <= int(hour) <= 12 or int(minute or 0) > 59:
        return None
    return int(hour) % 12 + 12 * (meridiem == 'p'), int(minute or 0)


def _end(start, item, props):
    if item.get('end'):
        return timestamp(item['end'], ZONE)
    clocks = props.get('time', '').split(' - ', 1)
    if len(clocks) != 2 or _display_clock(clocks[0]) != (start.hour, start.minute):
        return None
    finish = _display_clock(clocks[1])
    if finish is None:
        return None
    end = start.replace(hour=finish[0], minute=finish[1])
    return end if end > start else None


def collect(source, fetch, *, today=None):
    expected = (KEY, URL, 'html', 'html', ZONE)
    if tuple(source.get(key) for key in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != expected:
        raise ValueError('unregistered_chesapeake_library_source')
    today = today or datetime.now(ZoneInfo(ZONE)).date()
    before = today + timedelta(days=60)
    # The calendar's date filter supports the full window in one public request.
    # This keeps the city’s advertised crawl delay within the worker budget.
    query = urlencode({'startDate': today.isoformat(), 'endDate': (before - timedelta(days=1)).isoformat(), 'cat': 43})
    items = json.loads(fetch(f'{MONTH_URL}?{query}', 'application/json'))
    if not isinstance(items, list) or len(items) > 500:
        raise ValueError('invalid_chesapeake_library_date_range')
    rows = {}
    for item in items:
        props = item.get('extendedProps') if isinstance(item, dict) else None
        if not isinstance(props, dict) or props.get('category') != 'Chesapeake Public Library':
            raise ValueError('invalid_chesapeake_library_event')
        # All-day programs do not have a timed occurrence in this feed.
        if item.get('allDay') is not False:
            continue
        venue = plain(props.get('location'))
        address = BRANCHES.get(venue.partition(' -')[0])
        if not address:
            continue
        identity = item.get('id')
        raw_start = item.get('start')
        if not isinstance(identity, str) or not identity.isdigit() or not isinstance(raw_start, str) or 'T' not in raw_start:
            raise ValueError('invalid_chesapeake_library_occurrence')
        start = timestamp(raw_start, ZONE)
        local_day = start.astimezone(ZoneInfo(ZONE)).date()
        if not today <= local_day < before:
            continue
        if props.get('date') != local_day.isoformat():
            raise ValueError('chesapeake_library_date_conflict')
        finish = _end(start, item, props)
        navigation = f'/m/calendar/event/detail/{identity}'
        event_url = f'https://{HOST}{navigation}' if props.get('isActionable') is True and props.get('navigationUrl') == navigation else URL
        row = record(item.get('title'), start.isoformat(), finish.isoformat() if finish else None,
                     venue, address, 'Chesapeake', event_url, identity, 'Library', tz=ZONE,
                     retain_until_end=True)
        if row:
            row['description'] = plain(props.get('description'))[:2000]
            key = (identity, row['starts_at'])
            if key in rows and rows[key] != row:
                raise ValueError('conflicting_chesapeake_library_occurrence')
            rows[key] = row
    return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
