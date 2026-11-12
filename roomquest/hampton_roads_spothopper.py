"""Read public event cards from three Hampton Roads brewery calendars."""

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

ZONE = ZoneInfo('America/New_York')
SMARTMOUTH = 'municipal_c95c95a5b06056f26da007e7'
VIBRANT = 'municipal_8f59bd98f751e3f218ee5ce1'
AFTERGLOW = 'municipal_cdbebcd2be97bebce865a8fb'
SOURCES = {
    SMARTMOUTH: ('https://smartmouthbrewing.com/events/', 'Smartmouth Brewing Pilot House',
                 '313 32nd Street, Virginia Beach, VA 23451', 'Virginia Beach'),
    VIBRANT: ('https://vibrantshorebrewingcompany.com/virginia-beach-vibe-creative-district-vibrant-shore-brewing-company-events',
              'Vibrant Shore Brewing Company', '505 18th Street, Virginia Beach, VA 23451', 'Virginia Beach'),
    AFTERGLOW: ('https://afterglowbrewing.com/norfolk-rail-yard-of-norfolk-afterglow-brewing-events',
                'Afterglow Brewing', '2330 Bowdens Ferry Road, Norfolk, VA 23508', 'Norfolk'),
}
DAY = re.compile(r'([A-Za-z]+) ([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)')
CLOCK = re.compile(r'(\d{1,2}:\d{2} [AP]M)(?:\s*-\s*(\d{1,2}:\d{2} [AP]M)?)?')
PROMOTIONS = {'boxcar pizza delivery', 'moontide sundries', 'pups, pedals + pints',
              'service industry happy hour!', 'christmas', "new year's eve", "new year's day"}
UNAVAILABLE = re.compile(r'\b(?:cancelled|canceled|postponed)\b', re.I)


def _field(card, selector):
    node = card.select_one(selector)
    return plain(node.get_text(' ', strip=True)) if node else ''


def _times(day, clock, now, stop):
    value = DAY.fullmatch(day)
    times = CLOCK.fullmatch(clock)
    if not value or not times:
        return None, None
    weekday, month, number = value.groups()
    for year in range(now.year, stop.year + 1):
        try:
            start = datetime.strptime(f'{month} {number} {year} {times[1]}', '%B %d %Y %I:%M %p').replace(tzinfo=ZONE)
        except ValueError:
            continue
        if start.strftime('%A') != weekday or not now <= start < stop:
            continue
        if not times[2]:
            return start, None
        end = datetime.combine(start.date(), datetime.strptime(times[2], '%I:%M %p').time(), ZONE)
        if end == start:
            return start, None
        return start, end if end > start else end + timedelta(days=1)
    return None, None


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    url, venue, address, city = SOURCES[key]
    if tuple(source.get(k) for k in ('feed_url', 'kind', 'platform_adapter', 'timezone')) != (
        url, 'html', 'html', ZONE.key,
    ):
        raise ValueError('unregistered_hampton_roads_brewery')
    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    stop = now + timedelta(days=60)
    page = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
    cards = page.select('.event-text-holder')
    if not cards:
        raise ValueError('publisher_event_listing_missing')
    if len(cards) > 100:
        raise ValueError('source_record_limit')
    rows = {}
    for card in cards:
        title = _field(card, 'h2')
        details = _field(card, '.event-info-text')
        if not title or title.casefold() in PROMOTIONS or UNAVAILABLE.search(title):
            continue
        if key == SMARTMOUTH and not re.search(r'\bPilot House\b|\b313 32nd\b', details, re.I):
            continue
        event = card.select_one('[data-event-id]')
        if not event or not re.fullmatch(r'[0-9]{1,12}', event['data-event-id']):
            continue
        day = _field(card, '.event-day, h3:not(.event-time)')
        start, end = _times(day, _field(card, '.event-time'), now, stop)
        if not start:
            continue
        date = _field(card, '.atc_date_start')
        if date and date != start.strftime('%Y-%m-%d %H:%M:%S'):
            continue
        identity = event['data-event-id']
        row = record(title, start.isoformat(), end.isoformat() if end else None,
                     venue, address, city, url, identity, tz=ZONE.key)
        if row:
            rows[identity] = row
    return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
