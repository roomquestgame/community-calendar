"""Read VisitNorfolk's dated event pages discovered in its publisher RSS feed."""
from datetime import datetime
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record

KEY = 'municipal_3370957815b2ab3827be1e90'
HOST = 'www.visitnorfolk.com'
URL = f'https://{HOST}/event/feed/'
ZONE = 'America/New_York'
DETAIL = re.compile(r'/event/[a-z0-9][a-z0-9-]*/?')
CLOCK = re.compile(r'([1-9]|1[0-2])(?::([0-5][0-9]))?\s*([ap])\.?\s*m\.?', re.I)
STREET = re.compile(r'^\d{1,6}\s+[A-Za-z].+')


def _clock(value):
    match = CLOCK.fullmatch(value.strip())
    if not match:
        return None
    hour, minute, meridiem = match.groups()
    return int(hour) % 12 + 12 * (meridiem.casefold() == 'p'), int(minute or 0)


def collect(source, fetch):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            KEY, URL, 'rss', 'wordpress', ZONE):
        raise ValueError('unregistered_visit_norfolk_source')
    try:
        root = ElementTree.fromstring(fetch(URL, 'application/rss+xml,application/xml'))
    except ElementTree.ParseError as exc:
        raise ValueError('invalid_visit_norfolk_rss') from exc
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None:
        raise ValueError('invalid_visit_norfolk_rss')
    items = channel.findall('item')
    if len(items) > 24:
        raise ValueError('source_record_limit')
    rows = []
    seen = set()
    for item in items:
        link = (item.findtext('link') or '').strip()
        target = urlsplit(link)
        if (target.scheme != 'https' or target.netloc != HOST or not DETAIL.fullmatch(target.path)
                or target.query or target.fragment):
            raise ValueError('invalid_visit_norfolk_event_link')
        if link in seen:
            continue
        seen.add(link)
        soup = BeautifulSoup(fetch(link, 'text/html'), 'html.parser')
        block = soup.select_one('.listing-info')
        if block is None or block.select_one('.dates') is None:
            raise ValueError('invalid_visit_norfolk_event_page')
        title = plain(item.findtext('title'))
        if re.search(r'\b(?:cancell?ed|postponed)\b', title, re.I):
            continue
        when = block.select_one('.dates').get_text(' ', strip=True)
        try:
            day = datetime.strptime(when, '%B %d %Y')
        except ValueError:
            # A date range on the publisher page does not certify occurrences.
            continue
        time = block.select_one('.time')
        hours = re.split(r'\s*[-–]\s*', time.get_text(' ', strip=True) if time else '', maxsplit=1)
        start = _clock(hours[0])
        if start is None:
            continue
        end = _clock(hours[1]) if len(hours) == 2 else None
        begins = day.replace(hour=start[0], minute=start[1])
        ends = day.replace(hour=end[0], minute=end[1]) if end else None
        venue_element = block.select_one('.location')
        address_element = block.select_one('.addr')
        venue = venue_element.get_text(' ', strip=True) if venue_element else ''
        address = address_element.get_text(' ', strip=True).rstrip(',') if address_element else ''
        if not STREET.match(address):
            address = '333 Waterside Drive, Norfolk, VA 23510' if venue == 'Waterside District' else ''
        row = record(title, begins.isoformat(), ends.isoformat() if ends and ends > begins else None,
                     venue, address, '', link, target.path.rstrip('/'), tz=ZONE)
        if row:
            row['description'] = plain(item.findtext('description'))[:2000]
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
