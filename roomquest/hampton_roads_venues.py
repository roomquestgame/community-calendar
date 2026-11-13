"""Public, timed events from Nauticus and SevenVenues."""

from datetime import datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record

ZONE = ZoneInfo('America/New_York')
NAUTICUS = 'municipal_34ba9ee0424a01d0551a9e69'
SEVEN = 'municipal_f1228683d362efb24e29c98c'
SOURCES = {
    NAUTICUS: ('https://nauticus.org/calendar/', '.events-list .event a.title', r'/events/[a-z0-9-]+/'),
    SEVEN: ('https://www.sevenvenues.com/events/all', '.eventItem h3.title a', r'/events/detail/[a-z0-9-]+/?'),
}
VENUES = {
    'attucks-theatre': ('Attucks Theatre', '1010 Church Street'),
    'chrysler-hall': ('Chrysler Hall', '215 Saint Pauls Boulevard'),
    'harbor-park': ('Harbor Park', '150 Park Avenue'),
    'harrison-opera-house': ('Harrison Opera House', '160 West Virginia Beach Boulevard'),
    'scope-arena': ('Scope Arena', '201 East Brambleton Avenue'),
    'wells-theatre': ('Wells Theatre', '110 East Tazewell Street'),
}
UNAVAILABLE = re.compile(r'\b(?:cancelled|canceled|postponed)\b', re.I)


def _nauticus(link, fetch, url):
    card = link.find_parent(class_='event')
    listing = card.select_one('.date')
    if not listing or not re.search(r'\|\s*\d', listing.get_text(' ', strip=True)):
        return None, []
    page = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
    detail = page.select_one('.post-date')
    if not detail:
        return None, []
    value = plain(detail.get_text(' ', strip=True))
    match = re.fullmatch(r'[A-Za-z]+, ([A-Za-z]+ \d{1,2}, \d{4})\s*\|\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)', value, re.I)
    if not match:
        return None, []
    day, hour, minute, period = match.groups()
    starts = datetime.strptime(f'{day} {hour}:{minute or "00"} {period.upper()}', '%B %d, %Y %I:%M %p')
    return ('Nauticus & Battleship Wisconsin', '1 Waterside Drive'), [starts]


def _seven(fetch, url):
    page = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
    venue = page.select_one('.sidebar_event_venue a[href]')
    location = VENUES.get(urlsplit(venue['href']).path.rstrip('/').rsplit('/', 1)[-1]) if venue else None
    if not location:
        return None, [], ''
    dates = []
    for occurrence in page.select('.event_showings [id^="showing_"]'):
        if UNAVAILABLE.search(plain(occurrence.get_text(' ', strip=True))):
            continue
        day = occurrence.select_one('.showings_date .m-date__singleDate')
        clock = occurrence.select_one('.first_wrapper .time')
        if day and clock:
            date = plain(day.get_text(' ', strip=True)).split(',', 1)[-1].replace(',', ' ').split()
            if len(date) != 3:
                continue
            month, day_number, year = date
            when = f'{month[:3]} {day_number} {year} {plain(clock.get_text(" ", strip=True))}'
            try:
                dates.append(datetime.strptime(when, '%b %d %Y %I:%M %p'))
            except ValueError:
                continue
    narrative = page.select_one('.event_description')
    return location, dates, description(str(narrative) if narrative else None)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    base, selector, path = SOURCES[key]
    if tuple(source.get(k) for k in ('feed_url', 'kind', 'platform_adapter', 'timezone')) != (
        base, 'html', 'html', ZONE.key,
    ):
        raise ValueError('unregistered_hampton_roads_venues')
    page = BeautifulSoup(fetch(base, 'text/html'), 'html.parser')
    links = page.select(selector)
    if not links:
        raise ValueError('publisher_event_listing_missing')
    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    stop = now + timedelta(days=60)
    seen = set()
    rows = []
    for link in links:
        url = urljoin(base, link['href'])
        target = urlsplit(url)
        if (target.scheme != 'https' or target.netloc != urlsplit(base).netloc
                or target.query or target.fragment or not re.fullmatch(path, target.path)):
            continue
        title = plain(link.get_text(' ', strip=True))
        if url in seen or UNAVAILABLE.search(title):
            continue
        seen.add(url)
        if len(seen) > 24:
            break
        if key == NAUTICUS:
            venue, dates = _nauticus(link, fetch, url)
            narrative = ''
        else:
            venue, dates, narrative = _seven(fetch, url)
        if not venue:
            continue
        name, street = venue
        for date in sorted(set(dates)):
            starts = date.replace(tzinfo=ZONE)
            if now <= starts < stop:
                row = record(title, starts.isoformat(), None, name, f'{street}, Norfolk, VA 23510',
                             'Norfolk', url, url, tz=ZONE.key)
                if row:
                    row['description'] = narrative
                    rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
