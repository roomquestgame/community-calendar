"""Read a complete seven-day window from Discover Halifax's event directory."""
from datetime import datetime, timedelta
import re
from time import monotonic
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach, optional_description
from roomquest.reviewed_chambers import STREET_SUFFIX

KEY = 'discover_halifax_va'
URL = 'https://gohalifaxva.com/events/'
ZONE = 'America/New_York'
EVENT_URL = re.compile(r'https://gohalifaxva[.]com/directory/[a-z0-9]+(?:-[a-z0-9]+)*/')
PHOTO_URL = re.compile(r'https://gohalifaxva[.]com/site/wp-content/uploads/20[0-9]{2}/[01][0-9]/[A-Za-z0-9_.-]+[.](?:jpe?g|png|webp)', re.I)
_ADDRESS = re.compile(
    r'(?P<venue>.+?),\s*(?P<number>[0-9]{1,6})[,]?\s+(?P<street>[^,]+),\s*'
    r'(?P<city>[A-Za-z][A-Za-z .\x27-]+),\s*(?:[^,]+ County,\s*)?'
    r'(?:Virginia|VA),?\s+(?P<zip>\d{5})(?:, United States)?', re.I)
MAX_DETAILS = 18


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def _date(value):
    return datetime.strptime(value, '%B %d, %Y').date()


def _start(day, value):
    clock = datetime.strptime(value.upper(), '%I:%M %p').time()
    return timestamp(datetime.combine(day, clock), ZONE)


def _directory(payload, today):
    page = BeautifulSoup(payload, 'html.parser')
    count = page.select_one('.directorist-header-found-title span')
    cards = page.select('article.directorist-listing-single')
    if (not count or not _text(count).isdigit() or int(_text(count)) != len(cards)
            or not 1 <= len(cards) <= 200
            or page.select_one('.directorist-pagination, [rel="next"]')):
        raise ValueError('halifax_directory_incomplete')
    found, seen = [], set()
    for card in cards:
        link = card.select_one('.directorist-listing-title a[href]')
        url = link['href'] if link else ''
        if not EVENT_URL.fullmatch(url) or url in seen:
            raise ValueError('halifax_directory_event_identity')
        seen.add(url)
        day = _date(_text(card.select_one('.directorist-listing-card-date')))
        if today <= day < today + timedelta(days=7):
            found.append((url, _text(link), day, _text(card.select_one('.directorist-listing-card-time'))))
    if len(found) > MAX_DETAILS:
        raise ValueError('halifax_directory_detail_limit')
    return found


def _detail(payload, url, title, day, clock):
    page = BeautifulSoup(payload, 'html.parser')
    canonical = page.select_one('link[rel="canonical"]')
    header = page.select_one('h1.directorist-listing-details__listing-title')
    if not canonical or canonical.get('href') != url or _text(header) != title:
        raise ValueError('halifax_directory_detail_identity')
    fields = {}
    for row in page.select('.directorist-single-info'):
        label = _text(row.select_one('.directorist-single-info__label__text'))
        value = _text(row.select_one('.directorist-single-info__value'))
        if label and value:
            if label in fields and fields[label] != value:
                raise ValueError('halifax_directory_detail_conflict')
            fields[label] = value
    if fields.get('Start Date') != day.strftime('%B %d, %Y').replace(' 0', ' '):
        return None
    if not clock or not fields.get('Start Time'):
        return None
    start = _start(day, clock)
    if _start(day, fields['Start Time']) != start:
        return None
    # The Chamber and tourism listings disagree on this event's public start.
    if url.endswith('/woodbine-christmas-market/') and day.isoformat() == '2026-11-15':
        return None
    address = _ADDRESS.fullmatch(fields.get('Address', ''))
    if (not address or address['city'].lower().endswith(' county')
            or not re.search(r'\b' + STREET_SUFFIX + r'\b', address['street'], re.I)):
        return None
    detail = page.select_one('.directorist-card-general-section')
    description = _text(detail).removeprefix('Description ').strip()
    if re.search(r'\b(cancelled|canceled|postponed|online only|virtual only)\b', title+' '+description, re.I):
        return None
    end = _start(_date(fields['End Date']) if fields.get('End Date') else day,
                 fields['End Time']) if fields.get('End Time') else None
    if end and not start < end <= start + timedelta(hours=24):
        end = None
    street = f"{address['number']} {address['street']}, {address['city']}, VA {address['zip']}"
    row = record(title, start, end, address['venue'], street, address['city'], url, url, retain_until_end=True)
    if row:
        row.update(description=optional_description(KEY, row['id'], description[:3000]),
                   attendance_mode='in_person')
        photos = {tag.get('content') for tag in page.select('meta[property="og:image"]')
                  if PHOTO_URL.fullmatch(tag.get('content', ''))}
        attach(row, KEY, candidate=next(iter(photos)) if len(photos) == 1 else None)
    return row


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone'),
        source.get('kind'), source.get('platform_adapter')) != (KEY, URL, ZONE, 'html', 'html'):
        raise ValueError('unregistered_discover_halifax')
    today = datetime.now(ZoneInfo(ZONE)).date()
    events = _directory(fetch(URL, 'text/html'), today)
    result = []
    for url, title, day, clock in events:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if row := _detail(fetch(url, 'text/html'), url, title, day, clock):
            result.append(row)
    return result
