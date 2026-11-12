"""Read announced Virginia Beach public meetings and their posted venues."""

from datetime import datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.jsonld_adapter import Blocks
from roomquest.mapsee_adapter import plain, record, timestamp

HOST = 'virginiabeach.gov'
CALENDAR = f'https://{HOST}/connect/events?calendar=public-meetings'
SOURCE = 'municipal_376911a33eeef7ed0d9df1a0'
ZONE = ZoneInfo('America/New_York')
DETAIL = re.compile(r'/connect/events/[a-z0-9-]+(?:/\d{4}-\d{2}-\d{2})?/?')
LOCATION = re.compile(r'^(\d+ [^,]+)(?:, [^,]+)*, Virginia Beach, (?:Virginia|VA) (\d{5})$', re.I)


def _meeting(fetch, url):
    raw = fetch(url, 'text/html')
    reader = Blocks()
    reader.feed(raw)
    reader.close()
    events = [event for graph in reader.blocks if isinstance(graph, dict)
              for event in graph.get('@graph', []) if event.get('@type') == 'Event']
    if len(events) != 1:
        return None
    event = events[0]
    if (not str(event.get('eventStatus', '')).endswith('EventScheduled')
            or not str(event.get('eventAttendanceMode', '')).endswith('OfflineEventAttendanceMode')
            or re.search(r'\b(cancelled|canceled|postponed|virtual)\b', plain(event.get('name')), re.I)):
        return None
    addresses = {}
    page = BeautifulSoup(raw, 'html.parser')
    for node in page.select('main .row > p.mt-s6'):
        parts = [plain(s) for s in node.stripped_strings]
        if not parts:
            continue
        match = LOCATION.fullmatch(parts[-1])
        if match:
            street, zipcode = match.groups()
            address = f'{street}, Virginia Beach, VA {zipcode}'
            addresses[address] = parts[0] if len(parts) > 1 else street
    if len(addresses) != 1:
        return None
    address, name = next(iter(addresses.items()))
    return event, name, address


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
        SOURCE, CALENDAR, 'html', 'html', ZONE.key,
    ):
        raise ValueError('unregistered_virginia_beach_public_meetings')
    today = (now or datetime.now(ZONE)).astimezone(ZONE)
    stop = today + timedelta(days=60)
    page = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    links = page.select('main a[title][href^="/connect/events/"]')
    if not links:
        raise ValueError('publisher_event_listing_missing')
    candidates = {}
    for link in links:
        date = re.search(r' - (\d{4}/\d{2}/\d{2})$', link['title'])
        if not date:
            continue
        day = datetime.strptime(date[1], '%Y/%m/%d').date()
        if not today.date() <= day <= stop.date():
            continue
        url = urljoin(CALENDAR, link['href'])
        target = urlsplit(url)
        if (target.scheme == 'https' and target.netloc == HOST and not target.query
                and not target.fragment and DETAIL.fullmatch(target.path)):
            candidates[url] = day
    rows = []
    for url, day in sorted(candidates.items(), key=lambda item: item[1])[:14]:
        value = _meeting(fetch, url)
        if not value:
            continue
        event, venue, address = value
        starts = timestamp(event.get('startDate'), ZONE.key)
        if not starts or not today <= starts < stop or starts.astimezone(ZONE).date() != day:
            continue
        row = record(event.get('name'), event['startDate'], event.get('endDate'), venue, address,
                     'Virginia Beach', url, url, 'civic', tz=ZONE.key)
        if row:
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
