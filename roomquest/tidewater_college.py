"""Read dated public programs from Tidewater Community College's Norfolk calendar."""
from datetime import datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.lynnhaven_river import CLOCK, _clock
from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = 'municipal_1e4397337c81260b0712c2df'
HOST = 'www.tcc.edu'
CALENDAR = f'https://{HOST}/college-events/norfolk-campus/'
ZONE = 'America/New_York'
EVENT_PATH = re.compile(r'/event/[a-z0-9][a-z0-9-]*/')
EVENT_TIME = re.compile(r'([A-Za-z]+ [A-Za-z]+ \d{1,2})(?:st|nd|rd|th),\s*(.+)', re.I)
RESTRICTED = re.compile(r'\b(?:cancell?ed|postponed|private event|student art night|(?:staff|students) only)\b', re.I)


def _labeled(node):
    label = node.find('strong', recursive=False)
    if label is None:
        return '', ''
    name = label.get_text(' ', strip=True).rstrip(':').lower()
    label.decompose()
    return name, node.get_text(' ', strip=True)


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE):
        raise ValueError('unregistered_tidewater_college')
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    upcoming = {}
    for offset in range(61):
        day = today + timedelta(days=offset)
        upcoming[f'{day:%A %B} {day.day}'.casefold()] = day
    page = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    listing = page.select_one('#tcc-events-search[data-cat="norfolk-campus"]')
    if listing is None or listing.get('data-max-pages') not in ('0', '1'):
        raise ValueError('incomplete_tidewater_college_calendar')
    events = listing.select('table.event')
    if len(events) > 60 or listing.get('data-total') != str(len(events)):
        raise ValueError('invalid_tidewater_college_calendar')

    rows = []
    seen = set()
    for event in events:
        label = event.select_one('label.title')
        clock = event.select_one('.meta.date-time')
        link = label.find_parent('a', href=True) if label else None
        if not all((link, clock)):
            raise ValueError('invalid_tidewater_college_event')
        title = plain(label.get_text())
        if not title or RESTRICTED.search(title):
            continue
        _, time_text = _labeled(clock)
        match = EVENT_TIME.fullmatch(time_text)
        if not match or (day := upcoming.get(match[1].casefold())) is None:
            continue
        hours = re.split(r'\s*[-–—]\s*', match[2], maxsplit=1)
        start = _clock(hours[0])
        end = _clock(hours[1]) if len(hours) == 2 else None
        if start is None and end and (suffix := CLOCK.fullmatch(hours[1].strip())):
            inferred = _clock(f'{hours[0]} {suffix[3]}m')
            if inferred is not None and inferred < end:
                start = inferred
        if start is None:
            continue
        fields = dict(_labeled(n) for n in event.select('.meta.location-address, .meta.desc'))
        street = fields.get('address', '')
        if not re.fullmatch(r'[1-9][0-9]{0,5}\s+[^,]+,\s*Norfolk,\s*VA\s+[0-9]{5}', street, re.I):
            continue
        url = urljoin(CALENDAR, link['href'])
        target = urlsplit(url)
        if (target.scheme != 'https' or target.netloc != HOST or target.query or target.fragment
                or not EVENT_PATH.fullmatch(target.path)):
            raise ValueError('invalid_tidewater_college_event_link')
        begins = datetime(day.year, day.month, day.day, *start)
        ends = datetime(day.year, day.month, day.day, *end) if end else None
        if (url, begins) in seen:
            raise ValueError('duplicate_tidewater_college_event')
        seen.add((url, begins))
        row = record(title, begins.isoformat(), ends.isoformat() if ends and ends > begins else None,
                     fields.get('where'), street, 'Norfolk', url, target.path, tz=ZONE)
        if row:
            row['description'] = plain(fields.get('description'))[:2000]
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
