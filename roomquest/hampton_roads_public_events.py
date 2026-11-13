"""Collect published bookstore events and Sandler Center performances."""
from datetime import datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.jsonld_adapter import Blocks
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = ZoneInfo('America/New_York')
PRINCE = 'municipal_23d62d2d858c7e93630fe5e3'
FLOURISH = 'municipal_a9fd322416e6536699a69f66'
SANDLER = 'municipal_12c58b8068db81adc4284433'
SOURCES = {
    PRINCE: ('https://prince-books.com/upcoming-events', '.event-list__title a', r'/event/\d{4}-\d{2}-\d{2}/[a-z0-9-]+/?'),
    FLOURISH: ('https://flourishbookstore.com/events/', '.flourish-schedule-row', r'/events/[a-z0-9-]+/?'),
    SANDLER: ('https://www.sandlercenter.org/events', '.eventItem h3.title a', r'/events/detail/[a-z0-9-]+/?'),
}
UNAVAILABLE = re.compile(r'\b(?:cancelled|canceled|postponed)\b', re.I)


def _book_event(fetch, key, url):
    raw = fetch(url, 'text/html')
    reader = Blocks()
    reader.feed(raw)
    reader.close()
    events = [event for block in reader.blocks if isinstance(block, dict)
              for event in block.get('@graph', []) if event.get('@type') == 'Event'
              and event.get('url', '').rstrip('/') == url.rstrip('/')]
    if len(events) != 1:
        raise ValueError('bookstore_event_schema_missing')
    event = events[0]
    if str(event.get('eventStatus', '')).endswith(('EventCancelled', 'EventPostponed', 'EventMovedOnline')):
        return None
    place = event.get('location') or {}
    if not isinstance(place, dict) or place.get('@type') == 'VirtualLocation':
        return None
    postal = place.get('address') or {}
    street = plain(postal.get('streetAddress'))
    city = plain(postal.get('addressLocality'))
    state = plain(postal.get('addressRegion'))
    name = plain(place.get('name'))
    zipcode = plain(postal.get('postalCode'))
    if key == PRINCE:
        # The site repeats the street inside addressLocality on in-store events.
        if re.fullmatch(r'109 e\.? main (?:st\.?|street)', street, re.I):
            name, city, state = 'Prince Books', 'Norfolk', 'VA'
            zipcode = zipcode or '23510'
        elif not street:
            content = BeautifulSoup(raw, 'html.parser').find('main')
            copy = plain(content.get_text(' ', strip=True)) if content else ''
            if re.search(r'\b(?:at prince books|the store will be filled)\b', copy, re.I):
                name, street, city, state = 'Prince Books', '109 E. Main Street', 'Norfolk', 'VA'
                zipcode = '23510'
    if not re.match(r'^\d+\s', street) or not city or state != 'VA':
        return None
    if not re.search(r',\s*VA(?:\s|$)', street):
        street = ', '.join((street, city, ('VA ' + zipcode).strip()))
    return (plain(event.get('name')), event.get('startDate'), event.get('endDate'),
            name or street, street, city, description(event.get('description')))


def _sandler_time(day, clock):
    date = plain(day.get_text(' ', strip=True)).replace('/', ' ')
    return datetime.strptime(' '.join(f'{date} {clock}'.split()), '%b %d %Y %I:%M %p').isoformat()


def description_from_detail(payload, row):
    """Return Sandler's prose from the exact linked, title-matched event page."""
    url = row.get('event_url', '')
    target = urlsplit(url)
    if (target.scheme != 'https' or target.netloc != 'www.sandlercenter.org'
            or target.query or target.fragment or not re.fullmatch(SOURCES[SANDLER][2], target.path)):
        raise ValueError('invalid_sandler_detail_identity')
    page = BeautifulSoup(payload, 'html.parser')
    identities = [node.get('href') for node in page.select('link[rel~=canonical]')]
    identities.extend(node.get('content') for node in page.select('meta[property="og:url"]'))
    primary = page.select('#content[role="main"] .event_detail')
    if not identities or any(identity != url for identity in identities) or len(primary) != 1:
        raise ValueError('invalid_sandler_detail_identity')
    # The live template repeats the same h1 for its two responsive headings.
    headings = primary[0].select('h1.title')
    title = plain(row.get('title')).casefold()
    if not title or not headings or any(
            plain(heading.get_text(' ', strip=True))[:180].strip().casefold() != title for heading in headings):
        raise ValueError('invalid_sandler_detail_identity')
    columns = primary[0].select('#column_1 .leftColumn')
    if len(columns) != 1:
        raise ValueError('invalid_sandler_detail_content')
    narratives = columns[0].find_all(class_='event_description', recursive=False)
    if len(narratives) > 1:
        raise ValueError('invalid_sandler_detail_content')
    return description(str(narratives[0])) if narratives else ''


def _sandler_events(fetch, link, url, *, listing_only=False):
    info = link.find_parent(class_='info')
    if not info or UNAVAILABLE.search(plain(info.get_text(' ', strip=True))):
        return []
    day = info.select_one('.m-date__singleDate')
    clock = info.select_one('.time .start')
    narrative = info.select_one('.event_description')
    if day and clock:
        starts = [_sandler_time(day, clock.get_text(' ', strip=True))]
    else:
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        narrative = detail.select_one('.event_description') or narrative
        starts = []
        for showing in detail.select('.event_showings li[id^="showing_"]'):
            if UNAVAILABLE.search(plain(showing.get_text(' ', strip=True))):
                continue
            day = showing.select_one('.showings_date .m-date__singleDate')
            clock = showing.select_one('.wrapper .time')
            time = re.fullmatch(r'[A-Za-z]+ at (\d{1,2}:\d{2})\s*(am|pm)',
                                clock.get_text(' ', strip=True), re.I) if clock else None
            if day and time:
                starts.append(_sandler_time(day, f'{time[1]} {time[2].upper()}'))
    title = plain(link.get_text(' ', strip=True))
    narrative = '' if listing_only else description(str(narrative) if narrative else None)
    return [(title, start, None, 'Sandler Center for the Performing Arts',
             '201 Market Street, Virginia Beach, VA 23462', 'Virginia Beach', narrative)
            for start in sorted(set(starts))]


def collect(source, fetch, *, deadline_at=None, now=None, listing_only=False):
    """Collect legacy facts, or Sandler facts for the exact-link checkpoint.

    Sandler single-show dates come from listing cards. Multi-show cards still
    require their existing detail fetch for times; the checkpoint caller can
    reuse that payload when it validates and extracts the same page's prose.
    """
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if not profile or tuple(source.get(k) for k in ('feed_url', 'kind', 'platform_adapter', 'timezone')) != (
        profile[0], 'html', 'html', ZONE.key,
    ):
        raise ValueError('unregistered_hampton_roads_public_events')
    if listing_only and key != SANDLER:
        raise ValueError('unregistered_sandler_listing_source')
    base, selector, path = profile
    page = BeautifulSoup(fetch(base, 'text/html'), 'html.parser')
    links = page.select(selector)
    if not links:
        raise ValueError('publisher_event_listing_missing')
    if len(links) > 45:
        raise ValueError('source_record_limit')

    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    stop = now + timedelta(days=60)
    seen_urls = set()
    rows = []
    for link in links:
        url = urljoin(base, link['href'])
        target = urlsplit(url)
        if (target.scheme != 'https' or target.netloc != urlsplit(base).netloc
                or target.query or target.fragment or not re.fullmatch(path, target.path)):
            raise ValueError('invalid_hampton_roads_event_link')
        if url in seen_urls:
            continue
        seen_urls.add(url)
        events = (_sandler_events(fetch, link, url, listing_only=listing_only)
                  if key == SANDLER else [_book_event(fetch, key, url)])
        for event in events:
            if not event:
                continue
            title, starts, ends, venue, street, city, narrative = event
            begins = timestamp(starts, ZONE.key)
            if not begins or not now <= begins < stop or UNAVAILABLE.search(title):
                continue
            row = record(title, starts, ends, venue, street, city, url, url, tz=ZONE.key)
            if row:
                row['description'] = narrative
                rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
