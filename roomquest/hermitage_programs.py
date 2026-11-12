"""Read the Hermitage Museum's listed concerts, museum tours and Winter Twilight."""
from datetime import datetime, timedelta
import re
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.lynnhaven_river import _clock
from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = 'municipal_e1e032feac65ae6f1c75b39f'
HOST = 'thehermitagemuseum.org'
CALENDAR = f'https://{HOST}/public-programs/'
ZONE = ZoneInfo('America/New_York')
VENUE = 'Hermitage Museum & Gardens'
ADDRESS = '7637 North Shore Road, Norfolk, VA 23505'
DETAILS = {
    '/tours-and-field-trips/': 'tour',
    '/livefromthemusicroom/': 'concert',
    '/wintertwilight/': 'twilight',
}
WEEKDAY = re.compile(r'([A-Za-z]+),\s*([0-9]{1,2})/([0-9]{1,2})\b')
CONCERT = re.compile(r'([A-Za-z]+),\s*([A-Za-z]+)\s+([0-9]{1,2}):')


def _concert(page, day):
    text = ' '.join(page.stripped_strings)
    clock = re.search(r'Performances begin at ([0-9:\sapm]+)\s+and', text, re.I)
    if not clock:
        return None
    for header in page.select('h4'):
        match = CONCERT.fullmatch(header.get_text(' ', strip=True))
        if not match or (match[1].casefold(), match[2].casefold(), int(match[3])) != (
                day.strftime('%A').casefold(), day.strftime('%B').casefold(), day.day):
            continue
        performer = header.find_next_sibling('h3')
        start = _clock(clock[1])
        if performer and start:
            return f'Live from the Music Room: {plain(performer.get_text())}', start, None
    return None


def _tour(page, day):
    text = ' '.join(page.stripped_strings)
    clock = re.search(r'tours begin at ([0-9:\sapm]+) and last ([1-9]) hours?', text, re.I)
    listing = next((n.get_text(' ', strip=True) for n in page.select('p')
                    if n.get_text(' ', strip=True).startswith('TOUR DATES:')), '')
    if not clock or not re.search(rf'\b{day:%B} {day.day}(?:st|nd|rd|th)\b', listing, re.I):
        return None
    start = _clock(clock[1])
    if start and start[0] + int(clock[2]) < 24:
        return 'Secrets of the Hermitage Tour', start, (start[0] + int(clock[2]), start[1])
    return None


def _twilight(page, day):
    for header in page.select('h3'):
        text = header.get_text(' ', strip=True)
        match = re.fullmatch(r'([A-Za-z]+),\s*([A-Za-z]+)\s+([0-9]{1,2})\s*(?:st|nd|rd|th)'
                             r'\s*\|\s*(.*?)\s+to\s+(.*)', text, re.I)
        if not match or (match[1].casefold(), match[2].casefold(), int(match[3])) != (
                day.strftime('%A').casefold(), day.strftime('%B').casefold(), day.day):
            continue
        start, end = (_clock(re.sub(r'\s+', '', value)) for value in (match[4], match[5]))
        if start and end and start < end:
            return 'Winter Twilight', start, end
    return None


PARSERS = {'concert': _concert, 'tour': _tour, 'twilight': _twilight}


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE.key):
        raise ValueError('unregistered_hermitage_programs')
    today = (now or datetime.now(ZONE)).astimezone(ZONE).date()
    days = {}
    for offset in range(61):
        day = today + timedelta(days=offset)
        days[(day.month, day.day)] = day
    root = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    if not any(re.fullmatch(r'20[0-9]{2} Programs & Events', n.get_text(' ', strip=True))
               for n in root.select('.main-content h2')):
        raise ValueError('invalid_hermitage_programs')
    pages = {}
    records = {}
    for heading in root.select('.main-content h4'):
        text = heading.get_text(' ', strip=True)
        match = WEEKDAY.match(text)
        anchor = heading.select_one('a[href]')
        if not match or anchor is None:
            continue
        day = days.get((int(match[2]), int(match[3])))
        url = urljoin(CALENDAR, anchor['href'])
        path = url.removeprefix(f'https://{HOST}')
        family = DETAILS.get(path)
        if day is None or family is None:
            continue
        if family != 'twilight' and day.strftime('%A').casefold() != match[1].casefold():
            continue
        if path not in pages:
            pages[path] = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        found = PARSERS[family](pages[path], day)
        if found is None:
            continue
        title, start, end = found
        starts = datetime(day.year, day.month, day.day, *start)
        ends = datetime(day.year, day.month, day.day, *end) if end else None
        row = record(title, starts.isoformat(), ends.isoformat() if ends else None, VENUE,
                     ADDRESS, 'Norfolk', url, f'{path}:{day.isoformat()}', tz=ZONE.key)
        if row:
            records[(path, day)] = row
    return sorted(records.values(), key=lambda row: (row['starts_at'], row['id']))
