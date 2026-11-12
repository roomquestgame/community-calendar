"""Read dated, timed cards from Downtown Norfolk's public community calendar."""
from datetime import datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.lynnhaven_river import _clock
from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = 'municipal_175e7cdf657e22645f5d5ef6'
HOST = 'www.downtownnorfolk.org'
CALENDAR = f'https://{HOST}/explore/calendar?d=next30'
ZONE = ZoneInfo('America/New_York')
DETAIL = re.compile(r'/event/[a-z0-9][a-z0-9-]*/?')
UNAVAILABLE = re.compile(r'\b(?:cancell?ed|postponed|private event|sold out)\b', re.I)
VENUES = {
    'virginia zoo': '3500 Granby Street, Norfolk, VA 23504',
    'macarthur memorial': '198 Bank Street, Norfolk, VA 23510',
    'macarthur memorial museum': '198 Bank Street, Norfolk, VA 23510',
    'wells theatre': '108 East Tazewell Street, Norfolk, VA 23510',
    'attucks theatre': '1010 Church Street, Norfolk, VA 23510',
    'waterside district': '333 Waterside Drive, Norfolk, VA 23510',
    'selden market': '208 East Main Street, Norfolk, VA 23510',
    'harrison opera house': '160 West Virginia Beach Boulevard, Norfolk, VA 23510',
    'tcc visual arts & design center': '260 Boush Street, Norfolk, VA 23510',
    'nauticus': '1 Waterside Drive, Norfolk, VA 23510',
}


def _value(card, selector):
    node = card.select_one(selector)
    return plain(node.get_text(' ', strip=True)) if node else ''


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE.key):
        raise ValueError('unregistered_downtown_norfolk')
    today = (now or datetime.now(ZONE)).astimezone(ZONE).date()
    local_days = {}
    for offset in range(31):
        day = today + timedelta(days=offset)
        local_days[(day.strftime('%a').casefold(), day.day, day.strftime('%b').casefold())] = day
    page = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    cards = page.select('a.pcrd[href]')
    if not cards or len(cards) > 140:
        raise ValueError('invalid_downtown_norfolk_calendar')

    records = {}
    for card in cards:
        day_text = _value(card, '.pcrd-date-day')
        if not day_text.isdecimal():
            continue
        day = local_days.get((_value(card, '.pcrd-date-dow').casefold(), int(day_text),
                              _value(card, '.pcrd-date-month').casefold()))
        venue = _value(card, '.pcrd-content-venue')
        address = VENUES.get(venue.casefold())
        title = _value(card, '.pcrd-content-headline')
        if day is None or not title or not address or UNAVAILABLE.search(title):
            continue
        hours = re.split(r'\s*[-–—]\s*', _value(card, '.pcrd-content-time'), maxsplit=1)
        start = _clock(hours[0])
        if start is None:
            continue
        end = _clock(hours[1]) if len(hours) == 2 else None
        url = urljoin(CALENDAR, card['href'])
        target = urlsplit(url)
        if (target.scheme != 'https' or target.netloc != HOST or target.query or target.fragment
                or not DETAIL.fullmatch(target.path)):
            raise ValueError('invalid_downtown_norfolk_event_link')
        begins = datetime(day.year, day.month, day.day, *start)
        ends = datetime(day.year, day.month, day.day, *end) if end else None
        row = record(title, begins.isoformat(), ends.isoformat() if ends and ends > begins else None,
                     venue, address, 'Norfolk', url, target.path.rstrip('/'), tz=ZONE.key)
        if row:
            key = (row['id'], row['starts_at'])
            if key in records and records[key] != row:
                raise ValueError('conflicting_downtown_norfolk_event')
            records[key] = row
    return sorted(records.values(), key=lambda row: (row['starts_at'], row['id']))
