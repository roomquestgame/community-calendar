"""Read timed public performances from Virginia Beach Cultural Affairs."""
from datetime import datetime, timedelta
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

SOURCE_KEY = 'municipal_2c72672bcb8c47b895b8cb3e'
HOST = 'culture.virginiabeach.gov'
CALENDAR = f'https://{HOST}/events'
API = f'https://{HOST}/api/products/productionseasons'
ZONE = ZoneInfo('America/New_York')
DETAIL_PATH = re.compile(r'/[1-9][0-9]{0,9}/([1-9][0-9]{0,9})')
UNAVAILABLE = re.compile(r'\b(?:cancell?ed|postponed|sold out)\b', re.I)
VENUES = (
    ('lynnhaven house colonial education center', '4409 wishart rd',
     'Lynnhaven House Colonial Education Center', '4409 Wishart Road, Virginia Beach, VA 23455'),
    ('francis land house', '3131 virginia beach blvd',
     'Francis Land House', '3131 Virginia Beach Boulevard, Virginia Beach, VA 23462'),
)


def collect(source, fetch, *, deadline_at=None, render_calendar, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE.key):
        raise ValueError('unregistered_virginia_beach_cultural')
    now = now or datetime.now(ZONE)
    before = now + timedelta(days=60)
    payload = json.loads(render_calendar())
    productions = payload.get('productions') if isinstance(payload, dict) else None
    if not isinstance(productions, list) or len(productions) > 50:
        raise ValueError('invalid_virginia_beach_cultural_calendar')

    candidates = {}
    for series in productions:
        performances = series.get('performances') if isinstance(series, dict) else None
        if not isinstance(performances, list) or len(performances) > 200:
            raise ValueError('invalid_virginia_beach_cultural_performances')
        for performance in performances:
            if not isinstance(performance, dict):
                raise ValueError('invalid_virginia_beach_cultural_performances')
            title = plain(performance.get('performanceTitle'))
            display_clock = performance.get('displayTime')
            status = plain(performance.get('performanceStatusMessage'))
            if (not title or not display_clock or performance.get('isPerformanceVisible') is not True
                    or UNAVAILABLE.search(title) or UNAVAILABLE.search(status)):
                continue
            starts = datetime.fromisoformat(performance['performanceDate'])
            if starts.tzinfo is None:
                raise ValueError('virginia_beach_cultural_clock_conflict')
            starts = starts.astimezone(ZONE)
            day = f'{starts:%B} {starts.day}, {starts.year}'
            if (day != performance.get('displayDate')
                    or starts.strftime('%I:%M%p').lstrip('0') != display_clock.replace(' ', '').upper()):
                raise ValueError('virginia_beach_cultural_clock_conflict')
            if not now <= starts < before:
                continue
            url = performance['actionUrl']
            target = urlsplit(url)
            identity = str(performance['id'])
            match = DETAIL_PATH.fullmatch(target.path)
            if (target.scheme != 'https' or target.netloc != HOST or target.query or target.fragment
                    or not match or match[1] != identity or identity in candidates):
                raise ValueError('invalid_virginia_beach_cultural_event_link')
            candidates[identity] = (title, starts, url, series.get('description'))
            if len(candidates) > 12:
                raise ValueError('source_record_limit')

    rows = []
    for identity, (title, starts, url, description) in candidates.items():
        page = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        publisher_text = ' '.join(' '.join(page.stripped_strings).split()).casefold()
        locations = [(venue, address) for name, street, venue, address in VENUES
                     if name in publisher_text and street in publisher_text]
        if len(locations) != 1:
            continue
        venue, address = locations[0]
        row = record(title, starts.isoformat(), None, venue, address, 'Virginia Beach', url, identity,
                     tz=ZONE.key)
        if row:
            row['description'] = plain(description)[:2000]
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
