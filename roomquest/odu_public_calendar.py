"""Collect the General Public view of Old Dominion University's calendar."""
from datetime import date, datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

HOST = 'www.odu.edu'
SOURCE_KEY = 'municipal_675453b56a7c6bd1a1458ce2'
CALENDAR = f'https://{HOST}/events/calendar'
ZONE = ZoneInfo('America/New_York')
EVENT_PATH = re.compile(r'/(?:[a-z0-9-]+/)*events/[a-z0-9-]+/?')
CLOCK = re.compile(r'([0-9]{1,2}:[0-9]{2} [ap]m)(?:\s*[-–]\s*([0-9]{1,2}:[0-9]{2} [ap]m))?', re.I)
UNAVAILABLE = re.compile(r'\b(?:cancelled|canceled|postponed)\b', re.I)

# Public locations from the university's campus GIS building point layer.
# https://www.odu.edu/map
VENUES = {
    'lê planetarium': ('4501 Elkhorn Avenue', 36.884722, -76.308382),
    'perry library': ('1286 W. 43rd Street', 36.883999, -76.305147),
    'batten arts & letters building': ('4401 Hampton Boulevard', 36.884425, -76.303480),
    'gordon art gallery': ('4509 Monarch Way', 36.885241, -76.300492),
    'goode theatre': ('4601 Monarch Way', 36.885831, -76.300810),
}


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(key) for key in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
        SOURCE_KEY, CALENDAR, 'html', 'html', ZONE.key,
    ):
        raise ValueError('unregistered_odu_public_calendar')

    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    stop = now + timedelta(days=60)
    month = now.date().replace(day=1)
    result = {}
    for _ in range(3):
        if month > stop.date():
            break
        page_url = f'{CALENDAR}/{month:%Y%m}?audience=6'
        page = BeautifulSoup(fetch(page_url, 'text/html'), 'html.parser')
        selected = page.select_one('select[name="audience"] option[selected][value="6"]')
        calendar = page.select_one('.calendar-calendar')
        if not selected or plain(selected.get_text(' ', strip=True)) != 'General Public' or not calendar:
            raise ValueError('odu_public_calendar_audience_missing')
        links = calendar.select('td[date-date] a.event-target-nid')
        if len(links) > 120:
            raise ValueError('source_record_limit')
        for link in links:
            day = date.fromisoformat(link.find_parent('td')['date-date'])
            if day.month != month.month or not now.date() <= day <= stop.date():
                continue
            row = _event(link, page_url, fetch, day, now, stop)
            if row:
                key = (row['id'], row['starts_at'])
                if key in result and result[key] != row:
                    raise ValueError('conflicting_event_occurrence')
                result[key] = row
        month = (month + timedelta(days=32)).replace(day=1)
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))


def _event(link, page_url, fetch, day, now, stop):
    title = plain(link.get_text(' ', strip=True))
    if not title or UNAVAILABLE.search(title):
        return None
    clock = link.parent.select_one('.event-time')
    location = link.parent.select_one('.event-location')
    times = CLOCK.fullmatch(' '.join(clock.stripped_strings)) if clock else None
    venue = plain(location.get_text(' ', strip=True)).removeprefix('Location: ').strip() if location else ''
    address = VENUES.get(venue.casefold())
    if not times or not address:
        return None

    start = datetime.combine(day, datetime.strptime(times[1], '%I:%M %p').time(), ZONE)
    if not now <= start < stop:
        return None
    end = datetime.combine(day, datetime.strptime(times[2], '%I:%M %p').time(), ZONE) if times[2] else None
    if end is not None and end < start:
        return None
    event_url = urljoin(page_url, link.get('href', ''))
    target = urlsplit(event_url)
    if (target.scheme != 'https' or target.netloc != HOST or not EVENT_PATH.fullmatch(target.path)
            or target.fragment or (target.query and not re.fullmatch(r'delta=[0-9]{1,3}', target.query))):
        raise ValueError('invalid_odu_public_calendar_link')
    if title.endswith(('…', '...')):
        page = BeautifulSoup(fetch(event_url, 'text/html'), 'html.parser')
        heading = page.select_one('h1')
        title = plain(heading.get_text(' ', strip=True)) if heading else ''
        if not title or UNAVAILABLE.search(title):
            return None
    street, lat, lng = address
    return record(title, start.isoformat(), end.isoformat() if end else None,
                  venue, f'{street}, Norfolk, VA 23508', 'Norfolk', event_url, event_url,
                  lat=lat, lng=lng, tz=ZONE.key)
