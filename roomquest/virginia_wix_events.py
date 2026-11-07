"""Collect reviewed public Wix calendars through the shared HTML worker."""
from datetime import datetime
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import address, plain, record
from roomquest.publisher_evidence import attach
from scrapers.lib.jsonld import extract_events_from_blocks, extract_jsonld_blocks

SOURCES = {
    'north_street_press_club_va': ('https://www.northstreetpressclub.com/events', 'Farmville', '23901'),
    'berry_hill_resort_va': ('https://www.berryhillresort.com/upcoming-events', 'South Boston', '24592'),
}
MAX_DETAILS = 12
_DETAIL_PATH = re.compile(r'/event-details/[a-z0-9]+(?:-[a-z0-9]+)*/?')
_IMAGE_OWNERS = {'north_street_press_club_va': 'e3704b', 'berry_hill_resort_va': '56bd96'}


def event_url(source_key, url):
    if source_key not in SOURCES or not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return bool(parsed.scheme == 'https' and parsed.netloc == urlsplit(SOURCES[source_key][0]).netloc
                and _DETAIL_PATH.fullmatch(parsed.path) and not parsed.query and not parsed.fragment)


def listing_urls(payload, source_key):
    soup = BeautifulSoup(payload, 'html.parser')
    if soup.select_one('[data-hook="load-more-button"], [data-hook="pagination"]'):
        raise ValueError('pagination_requires_review')
    links = {}
    for card in soup.select('a[data-hook="title"][href]'):
        url = urljoin(SOURCES[source_key][0], card['href'])
        title = card.get_text(' ', strip=True)
        if not event_url(source_key, url) or not title or (url in links and links[url] != title):
            raise ValueError('wix_calendar_card_invalid')
        links[url] = title
    if not links:
        raise ValueError('wix_calendar_cards_missing')
    if len(links) > MAX_DETAILS:
        raise ValueError('wix_calendar_detail_limit')
    return links


def photo_url(source_key, url):
    """Accept only the publisher's own Wix event image account and public path."""
    if source_key not in _IMAGE_OWNERS or not isinstance(url, str) or len(url) > 2000:
        return None
    owner = _IMAGE_OWNERS[source_key]
    match = re.fullmatch(
        r'https://static\.wixstatic\.com/media/(' + owner +
        r'_[a-f0-9]{32}(?:~|%7E)mv2\.(?:jpe?g|png|webp))(?:/v1/fill/[A-Za-z0-9_,]+/\1)?',
        url, flags=re.I)
    return url if match else None


def event_detail(payload, source_key, url, expected_title):
    if not event_url(source_key, url):
        raise ValueError('publisher_evidence_identity_mismatch')
    events = extract_events_from_blocks(extract_jsonld_blocks(payload))
    if len(events) != 1 or not isinstance(events[0], dict):
        raise ValueError('wix_event_identity_missing')
    event = events[0]
    location = event.get('location')
    if not isinstance(location, dict):
        raise ValueError('wix_event_venue_missing')
    if (plain(event.get('name')).casefold() != plain(expected_title).casefold()
            or (event.get('url') or location.get('url')) != url):
        raise ValueError('wix_event_identity_mismatch')
    status = str(event.get('eventStatus', '')).rsplit('/', 1)[-1]
    if status in ('EventCancelled', 'EventPostponed'):
        return None
    if status not in ('EventScheduled', 'EventRescheduled'):
        raise ValueError('wix_event_status_unverified')
    attendance = str(event.get('eventAttendanceMode', '')).rsplit('/', 1)[-1]
    if attendance == 'OnlineEventAttendanceMode':
        return None
    if attendance != 'OfflineEventAttendanceMode':
        raise ValueError('wix_event_attendance_unverified')

    venue = plain(location.get('name'))
    street = address(location.get('address'))
    _, city, zip_code = SOURCES[source_key]
    if (not venue or not re.match(r'^\d{1,6}\s+[A-Za-z]', street)
            or not re.search(r',\s*' + re.escape(city) + r',\s*VA\s*' + zip_code + r'\b', street, re.I)):
        raise ValueError('wix_event_venue_unverified')
    begins = datetime.fromisoformat(event['startDate'])
    ends = datetime.fromisoformat(event['endDate']) if event.get('endDate') else None
    if begins.tzinfo is None or (ends is not None and (ends.tzinfo is None or ends <= begins)):
        raise ValueError('wix_event_schedule_unverified')
    row = record(expected_title, begins, ends, venue, street, city, url, url)
    if row is not None:
        row['description'] = plain(event.get('description'))[:12000]
        row['attendance_mode'] = 'in_person'
        image = event.get('image')
        attach(row, source_key, candidate=image.get('url') if isinstance(image, dict) else image)
    return row


def collect(source, fetch, *, deadline_at=None):
    key = source.get('source_key')
    config = SOURCES.get(key)
    if (not config or source.get('feed_url') != config[0] or source.get('timezone') != 'America/New_York'
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'):
        raise ValueError('unregistered_virginia_wix_calendar')
    links = listing_urls(fetch(config[0], 'text/html'), key)
    result = []
    for url, title in links.items():
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if row := event_detail(fetch(url, 'text/html'), key, url, title):
            result.append(row)
    return sorted(result, key=lambda row: (row['starts_at'], row['id']))
