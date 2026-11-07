"""Pair Visit Farmville's occurrence rows with the publisher's venue details."""
from datetime import datetime, timezone
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'visit_farmville_va'
SOURCE_URL = 'https://visitfarmville.com/events/'
TIMEZONE = 'America/New_York'
MAX_DETAIL_PAGES = 12
_DATE = r'[A-Za-z]+ [0-9]{1,2}, 20[0-9]{2}'
_TIME = r'[0-9]{1,2}:[0-9]{2} [ap]m'


def event_url(url):
    if not isinstance(url, str):
        return False
    return re.fullmatch(r'https://visitfarmville\.com/events/[a-z0-9]+(?:-[a-z0-9]+)*/', url) is not None


def photo_url(url):
    if not isinstance(url, str) or len(url) > 2000:
        return None
    return url if re.fullmatch(
        r'https://visitfarmville\.com/wp-content/uploads/20[0-9]{2}/[01][0-9]/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)', url
    ) else None


def date_value(text):
    return datetime.strptime(text, '%B %d, %Y').date()


def local_time(day, value):
    clock = datetime.strptime(value.upper(), '%I:%M %p').time()
    return timestamp(datetime.combine(day, clock), TIMEZONE)


def occurrences(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    calendar = soup.select_one('.em-events-list table')
    if not calendar:
        raise ValueError('farmville_calendar_table_missing')
    if soup.select_one('[rel=next], .em-pagination a[href], .em-pagination button, .page-numbers.next'):
        raise ValueError('pagination_requires_review')
    rows = []
    for tr in calendar.select('tr'):
        if tr.find('th'):
            continue
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 3:
            raise ValueError('farmville_calendar_row_invalid')
        a = cells[1].select_one('a[href]')
        img = cells[2].select_one('img')
        url = urljoin(SOURCE_URL, a['href']) if a else ''
        title = a.get_text(' ', strip=True) if a else ''
        match = re.fullmatch(rf'({_DATE}) ({_TIME}) - ({_TIME})', cells[0].get_text(' ', strip=True), re.I)
        if not (match and event_url(url) and title):
            raise ValueError('farmville_calendar_schedule_unverified')
        day = date_value(match[1])
        start, end = local_time(day, match[2]), local_time(day, match[3])
        if end <= start:
            raise ValueError('farmville_calendar_schedule_unverified')
        image = (img.get('data-src-img') or img.get('src')) if img else None
        rows.append((url, title, day, start, end, image))
    if not rows:
        raise ValueError('farmville_calendar_rows_missing')
    return rows


def detail(payload, url):
    soup = BeautifulSoup(payload, 'html.parser')
    event = soup.select_one('.entry-content .em-event-single')
    if not event or not event_url(url):
        raise ValueError('farmville_event_detail_missing')
    fields = {}
    description = []
    for child in event.find_all(recursive=False):
        label = child.find('strong', recursive=False)
        key = label.get_text(' ', strip=True) if label else None
        if key in ('Date/Time', 'Location', 'Categories'):
            fields[key] = child
        elif not child.select_one('.em-location-map-container'):
            description.append(child.get_text(' ', strip=True))
    schedule = fields.get('Date/Time')
    location = fields.get('Location')
    if schedule is None or location is None:
        raise ValueError('farmville_event_detail_fields_missing')
    venue = location.select_one('a[href]')
    balloon = event.select_one('.em-map-balloon-content')
    street_line = plain(' '.join(balloon.find_all(string=True, recursive=False))) if balloon else ''
    place = re.fullmatch(r'(\d{1,6} [^\r\n]+) - (Farmville)(?:, VA)?', street_line)
    span = re.fullmatch(
        rf'Date/Time Date\(s\) - ({_DATE})(?: - ({_DATE}))? ({_TIME}) - ({_TIME})',
        schedule.get_text(' ', strip=True), re.I)
    if not (venue and place and span):
        raise ValueError('farmville_event_venue_or_schedule_unverified')
    category_node = fields.get('Categories')
    categories = [a.get_text(' ', strip=True) for a in category_node.select('a')] if category_node else []
    return {
        'venue': venue.get_text(' ', strip=True), 'address': f'{place[1]}, {place[2]}, VA',
        'first': date_value(span[1]), 'last': date_value(span[2] or span[1]),
        'start': span[3], 'end': span[4], 'description': plain(' '.join(description)),
        'categories': categories,
    }


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != SOURCE_URL
            or source.get('timezone') != TIMEZONE or source.get('kind') != 'html'
            or source.get('platform_adapter') != 'html'):
        raise ValueError('unregistered_visit_farmville_calendar')
    now = datetime.now(timezone.utc)
    rows = [row for row in occurrences(fetch(SOURCE_URL, 'text/html')) if row[4] > now]
    if len({row[0] for row in rows}) > MAX_DETAIL_PAGES:
        raise ValueError('farmville_calendar_detail_limit')
    locations = {}
    result = {}
    for url, title, day, start, end, image in rows:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if url not in locations:
            locations[url] = detail(fetch(url, 'text/html'), url)
        event = locations[url]
        if (not event['first'] <= day <= event['last'] or start != local_time(day, event['start'])
                or end != local_time(day, event['end'])):
            raise ValueError('farmville_listing_detail_schedule_conflict')
        item = record(title, start, end, event['venue'], event['address'], 'Farmville', url,
                      url, ', '.join(event['categories']), retain_until_end=True)
        if item:
            item['description'] = event['description'][:12000]
            item['publisher_categories'] = event['categories']
            result[(url, start)] = attach(item, SOURCE_KEY, candidate=image, evidence_url=SOURCE_URL)
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))
