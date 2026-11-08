"""Exact Maryland publisher calendars with occurrence-level time and venue evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.maryland_sources import NONPUBLIC, ZONE, md_address, require_source

TZ = ZoneInfo(ZONE)
BOWIE = 'bowie_performing_arts_md'
HOWARD = 'howard_recreation_parks_md'
ANNE = 'anne_arundel_parks_md'
MONTGOMERY = 'montgomery_parks_md'
UMD = 'university_maryland_public_md'
SOURCES = {
    BOWIE: 'https://bowiecenter.org/events/',
    HOWARD: 'https://www.howardcountymd.gov/events?department%5B17%5D=17',
    ANNE: 'https://www.aacounty.org/recreation-parks/parks/parks-calendar',
    MONTGOMERY: 'https://montgomeryparks.org/events/',
    UMD: 'https://calendar.umd.edu/category/arts-entertainment-and-culture',
}
UMD_COMMUNITY = 'https://calendar.umd.edu/category/community-engagement'
PRIVATE = re.compile(r'\b(?:student[s]? only|faculty only|staff only|campus community only|invite only)\b', re.I)



def words(node):
    return node.get_text(' ', strip=True) if node else ''


def make_row(title, start, end, venue, address, url, now):
    if (not start or not title or not venue or not address or NONPUBLIC.search(title)
            or PRIVATE.search(title) or start >= now + timedelta(days=60)
            or (end or start + timedelta(hours=3)) <= now or (end and end <= start)):
        return None
    return record(title, start.isoformat(), end.isoformat() if end else None,
                  venue, address[0], address[1], url, f"{urlsplit(url).path}:{start.isoformat()}:{title}",
                  tz=ZONE, retain_until_end=True)


def street_line(parts):
    if len(parts) == 2:
        return md_address(', '.join(parts))
    if len(parts) == 3 and re.fullmatch(r'[A-Za-z .\'-]+', parts[1]):
        return md_address(', '.join(parts))
    return None


def _allowed_link(base, value, pattern):
    url = urljoin(base, value)
    origin, target = urlsplit(base), urlsplit(url)
    if (target.scheme, target.netloc) != ('https', origin.netloc) or target.query or target.fragment:
        return None
    return url if re.fullmatch(pattern, target.path) else None


def _clock(value):
    return datetime.strptime(re.sub(r'[.\s]+', '', value).upper(), '%I:%M%p').time()


def _event_schema(soup, *, permissive=False):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(), strict=not permissive)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        for item in data.get('@graph', [data]):
            if isinstance(item, dict) and item.get('@type') == 'Event':
                return item
    return {}


def _bowie(soup, url, now):
    event = _event_schema(soup, permissive=True)
    venue = 'Bowie Center for the Performing Arts'
    address_node = soup.select_one('.gt-item.gt-address')
    address_text = words(address_node)
    if not re.fullmatch(r'15200 Annapolis Rd\.? Bowie, MD 20715(?: USA)?', address_text):
        return []
    if event.get('eventStatus', '').rsplit('/', 1)[-1] != 'EventScheduled':
        return []
    title = event.get('name', '')
    address = md_address('15200 Annapolis Rd, Bowie, MD 20715')
    rows = []
    for date in soup.select('.gt-content > .gt-date'):
        label = words(date.parent)[len(words(date)):].strip()
        if not re.search(r'\b(?:show|concert|film|performance|matinee|evening)\b', label, re.I):
            continue
        if re.search(r'\b(?:doors|reception|cancelled|canceled|postponed)\b', label, re.I):
            continue
        start = datetime.strptime(re.sub(r'\b([ap])\.m\.', r'\1m', words(date), flags=re.I),
                                  '%B %d, %Y %I:%M %p').replace(tzinfo=TZ)
        row = make_row(title, start, None, venue, address, url, now)
        if row:
            rows.append(row)
    return rows


def _howard(soup, url, now):
    hero = soup.select_one('.hero--event')
    if not hero:
        return []
    title = words(hero.select_one('h1') or soup.select_one('h1'))
    day = words(hero.select_one('.hero__date'))
    times = re.split(r'\s*[-–]\s*', words(soup.select_one('.node-split--event .node-split__sidebar-item-content .time')))
    location = soup.select_one('.node--location--department-header-component')
    if not location or not day or not times[0]:
        return []
    labels = [words(location.select_one('.' + cls)) for cls in
              ('address-line1', 'locality', 'administrative-area', 'postal-code')]
    street, city, state, zip_code = labels
    address = md_address(f'{street}, {city}, {state} {zip_code}')
    venue = words(location.select_one('h2,h3,h4,[class*="title"]'))
    if not venue:
        venue = words(location).split(street)[0].strip() if street else ''
    date = datetime.strptime(day, '%m/%d/%Y').date()
    start = datetime.combine(date, _clock(times[0]), TZ)
    end = datetime.combine(date, _clock(times[1]), TZ) if len(times) == 2 and times[1] else None
    return [r for r in [make_row(title, start, end, venue, address, url, now)] if r]


def _anne(soup, base, now):
    rows = []
    cards = soup.select('.zn-event-w-date')
    if not cards:
        raise ValueError('publisher_calendar_structure_changed')
    for card in cards:
        link = card.select_one('h2 a[href]')
        place = card.select_one('.zn-event-location > div')
        venue = place.select_one('.zn-location-name') if place else None
        times = [timestamp(t['datetime']) for t in card.select('.zn-event-time time[datetime]')]
        if not link or not venue or not times:
            continue
        url = _allowed_link(base, link['href'], r'/[a-z0-9/-]+')
        address = street_line(list(place.stripped_strings)[1:])
        if not address:
            match = re.fullmatch(r'(\d{1,6} [^,]+),\s*([A-Za-z .\'-]+),\s*(MD \d{5})', ' '.join(list(place.stripped_strings)[1:]))
            address = md_address(', '.join(match.groups())) if match else None
        if url:
            row = make_row(words(link), times[0], times[1] if len(times) == 2 else None,
                           words(venue), address, url, now)
            if row:
                rows.append(row)
    return rows


def _umd(soup, url, now):
    event = _event_schema(soup)
    if (event.get('eventStatus', '').rsplit('/', 1)[-1] != 'EventScheduled'
            or event.get('eventAttendanceMode', '').rsplit('/', 1)[-1] != 'OfflineEventAttendanceMode'
            or PRIVATE.search(event.get('description') or '')):
        return []
    audiences = {words(link) for link in soup.select('umd-event-tags a[href]')}
    if not audiences.intersection({'General Public', 'Public', 'Alumni', 'Friends', 'Parents & Families', 'Faculty and Staff'}):
        return []
    place = soup.select_one('umd-event-location')
    if not place:
        return []
    street = place.select_one('address')
    address = street_line(list(street.stripped_strings)) if street else None
    row = make_row(event.get('name', ''), timestamp(event.get('startDate'), ZONE),
                   timestamp(event.get('endDate'), ZONE), words(place.select_one('.address-title')),
                   address, url, now)
    return [row] if row else []


def _montgomery(soup, url, now):
    main = soup.select_one('main')
    if not main:
        return []
    when = main.select_one('.content > .date')
    times = when.parent.select_one('.time') if when else None
    location = next((block for block in main.select('.content')
                     if block.select_one('strong') and words(block.select_one('strong')) == 'Location:'), None)
    if not when or not times or not location:
        return []
    lines = [line.strip().strip(',') for part in list(location.stripped_strings)[1:]
             for line in part.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    address = street_line(lines[1:])
    date = datetime.strptime(words(when), '%A, %B %d, %Y').date()
    start_text, end_text = re.split(r'\s*[-–]\s*', words(times))
    row = make_row(words(main.select_one('h1')), datetime.combine(date, _clock(start_text), TZ),
                   datetime.combine(date, _clock(end_text), TZ), lines[0], address, url, now)
    return [row] if row else []


def _details(soup, base, key, now):
    selector, pattern = {
        BOWIE: ('.gt-event-style-1 .gt-title a[href]', r'/event/[a-z0-9-]+/'),
        HOWARD: ('.node--event--upcoming__title a[href]', r'/[a-zA-Z0-9/-]+'),
        UMD: ('umd-element-event[data-display="list"] [slot="headline"] a[href]', r'/[a-z0-9-]+'),
        MONTGOMERY: ('a.event-block[href]', r'/events/[a-z0-9-]+/'),
    }[key]
    anchors = soup.select(selector)
    if not anchors:
        raise ValueError('publisher_calendar_structure_changed')
    links = {}
    for anchor in anchors:
        value = anchor['href']
        expected = None
        if key == UMD:
            occurrence = re.fullmatch(r'([^?]+)\?start=(\d{4}-\d{2}-\d{2})', value)
            if not occurrence or PRIVATE.search(words(anchor)):
                continue
            value, expected = occurrence.groups()
            listed = anchor.find_parent('umd-element-event')
            if listed.get('data-visual-time') == 'false':
                continue
            start = timestamp(words(listed.select_one('[slot="start-date-iso"]')), ZONE)
            if not start or start <= now or start >= now + timedelta(days=60):
                continue
            expected = start
        url = _allowed_link(base, value, pattern)
        if url:
            links.setdefault(url, expected)
    if len(links) > 24:
        raise ValueError('source_record_limit')
    return links


def collect(source, fetch, *, deadline_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    key = source['source_key']
    base = SOURCES[key]
    require_source(source, base, 'html', 'html')
    soup = BeautifulSoup(fetch(base, 'text/html'), 'html.parser')
    if key == ANNE:
        return _anne(soup, base, now)
    links = _details(soup, base, key, now)
    if key == UMD:
        community = BeautifulSoup(fetch(UMD_COMMUNITY, 'text/html'), 'html.parser')
        for url, start in _details(community, UMD_COMMUNITY, key, now).items():
            links.setdefault(url, start)
    parser = {BOWIE: _bowie, HOWARD: _howard, UMD: _umd, MONTGOMERY: _montgomery}[key]

    def read(item):
        url, expected = item
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('source_fetch_deadline')
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        try:
            rows = parser(detail, url, now)
        except (TypeError, ValueError, OverflowError):
            return []
        if expected is not None:
            return [r for r in rows if timestamp(r['starts_at']) == expected]
        return rows

    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for batch in pool.map(read, links.items()) for row in batch]
