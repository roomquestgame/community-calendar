"""Read upcoming, timed programs from Lynnhaven River NOW's public calendar."""
from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = 'municipal_38cad94cfdc8628a8ce8ee90'
HOST = 'www.lynnhavenrivernow.org'
CALENDAR = f'https://{HOST}/events/'
ZONE = 'America/New_York'
EVENT_PATH = re.compile(r'/events/[a-z0-9][a-z0-9-]*/')
UNAVAILABLE = re.compile(r'\b(?:sold out|cancell?ed|postponed|private event)\b', re.I)
CLOCK = re.compile(r'(1[0-2]|[1-9])(?::([0-5][0-9]))?\s*([ap])\.?\s*m\.?', re.I)
STREET = re.compile(r'\b[1-9][0-9]{0,5}\s+[A-Za-z].+')
LOCALITY = re.compile(r'[A-Za-z .-]+,\s*VA\s+\d{5}', re.I)


def _clock(value):
    value = value.strip().casefold()
    if value == 'noon':
        return 12, 0
    if match := CLOCK.fullmatch(value):
        hour, minute, meridiem = match.groups()
        return int(hour) % 12 + 12 * (meridiem == 'p'), int(minute or 0)
    return None


def _field(meta, selector):
    field = meta.select_one(selector)
    if field is None:
        return ''
    label = field.find('span', recursive=False)
    if label is not None:
        label.decompose()
    return field.get_text('\n', strip=True)


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE):
        raise ValueError('unregistered_lynnhaven_river')
    local_day = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    upcoming_days = {(local_day + timedelta(days=offset)).strftime('%B %d, %A'):
                     local_day + timedelta(days=offset) for offset in range(61)}
    page = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    cards = page.select('a.blog-tile[href]')
    if not cards or len(cards) > 20:
        raise ValueError('invalid_lynnhaven_river_calendar')
    rows = []
    seen = set()
    for card in cards:
        listed_day = card.select_one('.tile-date')
        if listed_day is None:
            raise ValueError('lynnhaven_river_date_missing')
        date_text = listed_day.get_text(' ', strip=True)
        day = upcoming_days.get(date_text)
        if day is None:
            continue
        url = card['href']
        target = urlsplit(url)
        if (target.scheme != 'https' or target.netloc != HOST or target.query
                or target.fragment or not EVENT_PATH.fullmatch(target.path)):
            raise ValueError('invalid_lynnhaven_river_event_link')
        if url in seen:
            raise ValueError('duplicate_lynnhaven_river_event_link')
        seen.add(url)
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        meta = detail.select_one('.single-meta')
        if meta is None or _field(meta, '.s-date') != date_text:
            raise ValueError('lynnhaven_river_date_conflict')
        title = plain(_field(meta, '.s-title'))
        if not title or UNAVAILABLE.search(title):
            continue
        hours = re.split(r'\s+(?:to|[-–—])\s+', _field(meta, '.s-time'), maxsplit=1, flags=re.I)
        start = _clock(hours[0])
        end = _clock(hours[1]) if len(hours) == 2 else None
        if start is None and end and (suffix := CLOCK.fullmatch(hours[1].strip())):
            # The publisher puts one meridiem at the end of same-period ranges.
            inferred = _clock(f'{hours[0]} {suffix[3]}m')
            if inferred is not None and inferred < end:
                start = inferred
        if start is None:
            continue
        street_lines = [plain(part) for part in _field(meta, '.s-geo').splitlines() if plain(part)]
        street_index = next((i for i, part in enumerate(street_lines) if STREET.fullmatch(part)), None)
        if street_index is None or street_index + 1 >= len(street_lines):
            continue
        locality = street_lines[street_index + 1]
        if not LOCALITY.fullmatch(locality):
            continue
        venue = street_lines[0] if street_index else ''
        street = f'{street_lines[street_index]}, {locality}'
        begins = datetime(day.year, day.month, day.day, *start)
        ends = datetime(day.year, day.month, day.day, *end) if end else None
        row = record(title, begins.isoformat(), ends.isoformat() if ends and ends > begins else None,
                     venue, street, locality.split(',', 1)[0], url, target.path, tz=ZONE)
        if row:
            narrative = detail.select_one('.single-content')
            if narrative:
                from roomquest.event_description import description
                row['description'] = description(str(narrative))
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
