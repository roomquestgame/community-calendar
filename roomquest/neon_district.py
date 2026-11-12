"""Read the public calendar cards published by Norfolk's NEON District."""
from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = 'municipal_749460d8567ccf71cade6771'
HOST = 'neonnfk.com'
CALENDAR = f'https://{HOST}/events/'
ZONE = 'America/New_York'
DETAIL = re.compile(r'/events/[a-z0-9][a-z0-9-]*/')
STREET = re.compile(r'^[1-9][0-9]{0,5}\s+[A-Za-z].+')


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE):
        raise ValueError('unregistered_neon_district')
    local_day = (now or datetime.now(ZoneInfo(ZONE))).astimezone(ZoneInfo(ZONE)).date()
    page = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    calendar = page.select_one('section.cards')
    if calendar is None or calendar.select_one('.pagination-container a[href]'):
        raise ValueError('invalid_neon_district_calendar')
    cards = calendar.select('.card-info')
    if len(cards) > 50:
        raise ValueError('source_record_limit')
    rows = []
    seen = set()
    for card in cards:
        header = card.select_one('.card-header')
        title_node = card.select_one('h3')
        link = card.select_one('a.btn[href]')
        if not all((header, title_node, link)):
            raise ValueError('invalid_neon_district_calendar')
        day_text = header.get_text(' ', strip=True).partition('//')[0].strip()
        if not re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{2}', day_text):
            continue
        day = datetime.strptime(day_text, '%m.%d.%y').date()
        title = plain(title_node.get_text())
        if not local_day <= day <= local_day + timedelta(days=60):
            continue
        if not title or re.search(r'\b(?:cancell?ed|postponed|private event)\b', title, re.I):
            continue
        clock, venue, street = (card.select_one(c) for c in ('.event-time', '.event-location', '.event-address'))
        if not all((clock, venue, street)):
            continue
        clock_text = clock.get_text(' ', strip=True)
        if not re.fullmatch(r'\d{1,2}:\d{2}\s+[ap]m\s*[-–]\s*\d{1,2}:\d{2}\s+[ap]m', clock_text, re.I):
            continue
        starts, ends = [datetime.combine(day, datetime.strptime(part.strip().upper(), '%I:%M %p').time())
                        for part in re.split(r'\s*[-–]\s*', clock_text, maxsplit=1)]
        address = plain(street.get_text())
        if not STREET.fullmatch(address):
            continue
        url = link['href']
        target = urlsplit(url)
        if (target.scheme != 'https' or target.netloc != HOST or target.query
                or target.fragment or not DETAIL.fullmatch(target.path)):
            raise ValueError('invalid_neon_district_event_link')
        if (url, starts) in seen:
            raise ValueError('duplicate_neon_district_event')
        seen.add((url, starts))
        if not re.search(r'\bNorfolk\b', address, re.I):
            address += ', Norfolk, VA'
        row = record(title, starts.isoformat(), ends.isoformat() if ends > starts else None,
                     plain(venue.get_text()), address, 'Norfolk', url, target.path, tz=ZONE)
        if row:
            description = card.select_one('p')
            if description:
                row['description'] = plain(description.get_text(' ', strip=True))[:2000]
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
