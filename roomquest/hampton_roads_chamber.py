"""Read the Hampton Roads Chamber's public GrowthZone event listings."""
from datetime import datetime, timedelta
import re
from urllib.parse import parse_qsl, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import address, plain, record
from roomquest.south_hill_chamber import _event_json, _listing_time, _narrative

SOURCE_KEY = 'municipal_5effc448d9e900b8cdd14958'
HOST = 'business.hrchamber.com'
CALENDAR = f'https://{HOST}/event-calendar'
ZONE = 'America/New_York'
DETAIL = re.compile(r'/event-calendar/Details/[a-z0-9-]+-([1-9][0-9]{0,11})/?')
PRIVATE = re.compile(r'\b(?:members?[- ]only|private event|preview for Chamber members)\b', re.I)
UNAVAILABLE = re.compile(r'\b(?:sold out|cancell?ed|postponed)\b', re.I)


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')) != (
            SOURCE_KEY, CALENDAR, 'html', 'html', ZONE):
        raise ValueError('unregistered_hampton_roads_chamber')
    now = now or datetime.now(ZoneInfo(ZONE))
    end_of_window = now + timedelta(days=60)
    soup = BeautifulSoup(fetch(CALENDAR, 'text/html'), 'html.parser')
    listing = soup.select_one('.gz-events-listing')
    if listing is None:
        raise ValueError('invalid_hampton_roads_chamber_listing')
    counts = [match[1] for label in listing.select('.gz-subtitle')
              if (match := re.fullmatch(r'Results:\s*([0-9]+)', label.get_text(' ', strip=True)))]
    cards = listing.select('.gz-events-cards .gz-events-card')
    if len(counts) != 1 or int(counts[0]) != len(cards):
        raise ValueError('hampton_roads_chamber_listing_incomplete')

    events = {}
    for card in cards:
        title_link = card.select_one('a.gz-event-card-title[href]')
        start_tag = card.select_one('meta[itemprop="startDate"][content]')
        end_tag = card.select_one('meta[itemprop="endDate"][content]')
        if not all((title_link, start_tag, end_tag)):
            raise ValueError('hampton_roads_chamber_event_incomplete')
        begins = _listing_time(start_tag['content'])
        ends = _listing_time(end_tag['content'])
        title = plain(title_link.get_text())
        if not now <= begins <= end_of_window or UNAVAILABLE.search(title) or PRIVATE.search(title):
            continue
        url = urljoin(CALENDAR, title_link['href'])
        parts = urlsplit(url)
        match = DETAIL.fullmatch(parts.path)
        if (not match or parts.scheme != 'https' or parts.netloc != HOST or parts.fragment
                or parse_qsl(parts.query, keep_blank_values=True) not in ([], [('sourceTypeId', 'Website')])):
            raise ValueError('invalid_hampton_roads_chamber_event_link')
        if match[1] in events or len(events) >= 16:
            raise ValueError('hampton_roads_chamber_listing_limit')
        events[match[1]] = (url, title, begins, ends)

    records = []
    for identity, (url, title, begins, ends) in events.items():
        page = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        detail = _event_json(page)
        clock = page.select_one('.gz-event-time')
        visible = clock.get_text(' ', strip=True) if clock else ''
        if plain(detail.get('name')) != title or detail.get('startDate') != begins.date().isoformat():
            raise ValueError('hampton_roads_chamber_event_conflict')
        # The JSON-LD end date sometimes rolls over in UTC. Check the publisher's
        # visible local time independently before using the listing's timestamps.
        if begins.date() != ends.date() or ends <= begins:
            continue
        day = f'{begins:%A, %B} {begins.day}, {begins.year}'
        start_clock = begins.strftime('%I:%M %p').lstrip('0')
        end_clock = ends.strftime('%I:%M %p').lstrip('0')
        if f'{day} ({start_clock} - {end_clock})' not in visible:
            raise ValueError('hampton_roads_chamber_event_conflict')
        if not str(detail.get('eventStatus', '')).endswith('EventScheduled'):
            continue
        if str(detail.get('eventAttendanceMode', '')).endswith('OnlineEventAttendanceMode'):
            continue
        location = detail.get('location')
        if not isinstance(location, dict) or location.get('@type') != 'Place':
            continue
        place = location.get('address')
        if not isinstance(place, dict):
            continue
        if (location.get('name'), place.get('streetAddress'), place.get('addressLocality'),
                place.get('postalCode')) == ('Hampton Roads Chamber', '101 W Main Street Suite 800',
                                              'Norfolk', '23510') and not place.get('addressRegion'):
            place = {**place, 'addressRegion': 'VA'}
        if not all(place.get(k) for k in ('streetAddress', 'addressLocality', 'addressRegion')):
            continue
        description = _narrative(detail.get('description'))
        if PRIVATE.search(description):
            continue
        row = record(title, begins.isoformat(), ends.isoformat() if ends > begins else None,
                     location.get('name'), address(place), place['addressLocality'], url, identity, tz=ZONE)
        if row:
            row['description'] = description
            records.append(row)
    return sorted(records, key=lambda row: (row['starts_at'], row['id']))
