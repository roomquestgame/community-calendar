"""Generate bounded occurrences from the three Hampton Roads market schedules."""
from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record

ZONE = 'America/New_York'
SOURCES = {
    'municipal_ae345229f73806e1a26d20ac': (
        'https://www.shoredrivefarmarket.com/', 'Shore Drive Farm Market',
        'Shore Drive Farm Market', '2945 Shore Drive, Virginia Beach, VA 23451', 'Virginia Beach'),
    'municipal_fbeab18ea945d530eccf2189': (
        'https://www.oldbeachfarmersmarket.com/market-days', 'Old Beach Farmers Market',
        'Old Beach Farmers Market', '611 18th Street, Virginia Beach, VA 23451', 'Virginia Beach'),
    'municipal_cafd15041a039d27e1a37fc3': (
        'https://www.tidewaterfarmersmarkets.com/east-beach', 'East Beach/EOV Farmers Market',
        'Bay Oaks Park', '2413 E Ocean View Ave., Norfolk, VA 23518', 'Norfolk'),
}


def _shore(text, days):
    if ('year-round market' not in text
            or 'located at 2945 shore drive, virginia beach, va 23451 – saturdays, 9 am–12 pm.' not in text):
        raise ValueError('shore_drive_schedule_changed')
    return days


def _old_beach(text, days):
    year = re.search(r'\b(20[0-9]{2}) market schedule\b', text)
    if (year is None or 'winter markets: november through march 1st & 3rd saturdays 9-12 pm' not in text
            or 'regular market season: april through october every saturday from 9-12 pm' not in text
            or '611 18th street' not in text):
        raise ValueError('old_beach_schedule_changed')
    return [day for day in days if day.year == int(year[1])
            and (4 <= day.month <= 10 or (day.day - 1) // 7 in (0, 2))]


def _east_beach(text, days):
    year = re.search(r'\b(20[0-9]{2}) vendor lineup\b', text)
    season = re.search(r'saturdays 9am to noon ([a-z]+ \d{1,2}) through ([a-z]+ \d{1,2})', text)
    if (year is None or season is None
            or 'bay oaks park 2413 e ocean view ave., norfolk, va 23518' not in text):
        raise ValueError('east_beach_schedule_changed')
    first, last = (datetime.strptime(f'{value} {year[1]}', '%B %d %Y').date() for value in season.groups())
    if first > last or first.weekday() != 5 or last.weekday() != 5:
        raise ValueError('east_beach_schedule_changed')
    return [day for day in days if first <= day <= last]


SCHEDULES = dict(zip(SOURCES, (_shore, _old_beach, _east_beach)))
# The organizer places this market on 18th between Cypress and Mediterranean.
# Street midpoint from the City of Virginia Beach GIS street segment 13090.
OLD_BEACH_PIN = (36.844967, -75.982314)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if key not in SOURCES:
        raise ValueError('unregistered_hampton_roads_market')
    url, title, venue, street, city = SOURCES[key]
    if tuple(source.get(k) for k in ('feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            url, 'html', 'html', ZONE):
        raise ValueError('unregistered_hampton_roads_market')
    today = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    first_saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    days = [first_saturday + timedelta(weeks=week) for week in range(9)
            if (first_saturday + timedelta(weeks=week) - today).days <= 60]
    page = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
    for hidden in page.select('script, style, noscript, template'):
        hidden.decompose()
    text = ' '.join(' '.join(page.stripped_strings).split()).casefold()
    selected = SCHEDULES[key](text, days)
    lat, lng = OLD_BEACH_PIN if key == 'municipal_fbeab18ea945d530eccf2189' else (None, None)
    rows = []
    for day in selected:
        starts = datetime(day.year, day.month, day.day, 9)
        ends = datetime(day.year, day.month, day.day, 12)
        row = record(title, starts.isoformat(), ends.isoformat(), venue, street, city,
                     url, f'{urlsplit(url).path}:{day.isoformat()}', 'Market', lat=lat, lng=lng, tz=ZONE)
        if row:
            rows.append(row)
    return rows
