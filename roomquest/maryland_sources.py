"""Reviewed Maryland calendars using the existing community source pipeline."""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
PG_PARKS = 'municipal_mapsee_d99dc674be18efff44a15ab4'
PG_ROOT = 'https://www.pgparks.com'
DNR = 'maryland_state_parks_activecalendar'
DNR_FEED = 'https://go.activecalendar.com/doit-md/page/ical/?duration=3months'
ARTS = 'howard_county_arts_md'
ARTS_FEED = 'https://www.hocoarts.org/wp-json/tribe/events/v1/events'
SAVAGE = 'savage_mill_md'
HISTORY = 'howard_county_history_md'
HTML = {
    SAVAGE: 'https://www.savagemill.com/events/list/',
    HISTORY: 'https://www.hchsmd.org/calendar',
}
LIBRARIES = {
    'howard_library_' + branch + '_md':
    f'https://howardcounty.librarycalendar.com/events/feed/ical?branches%5B{id}%5D={id}'
    for branch, id in {
        'central': 97, 'east_columbia': 99, 'elkridge': 100, 'glenwood': 101,
        'miller': 102, 'savage': 103,
    }.items()
} | {
    'anne_arundel_library_' + branch + '_md':
    f'https://www.aacpl.net/events/feed/ical?branches%5B{id}%5D={id}'
    for branch, id in {'crofton': 194, 'odenton': 203, 'severn': 205, 'annapolis': 191}.items()
}
ICS = LIBRARIES | {DNR: DNR_FEED}
EVENT_URLS = {
    PG_PARKS: r'https://www[.]pgparks[.]com/event_list/[a-z0-9-]+(?:/20\d{2}-\d{2}-\d{2})?/?',
    ARTS: r'https://www[.]hocoarts[.]org/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?',
    SAVAGE: r'https://www[.]savagemill[.]com/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?',
    HISTORY: r'https://www[.]hchsmd[.]org/calendar/[a-z0-9-]+/?',
    DNR: r'https://go[.]activecalendar[.]com/doit-md/event/[a-z0-9-]+/?',
}
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|members?[- ]only|invitation[- ]only|private (?:event|party))\b', re.I)
STREET = re.compile(r'^\d{1,6}(?:[-/]\d+)?\s+[A-Za-z]')
STATE = re.compile(r'^MD(?:\s+\d{5}(?:-\d{4})?)?$')


def require_source(source, url, kind, adapter):
    if (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'), source.get('timezone')) != (
            url, kind, adapter, ZONE):
        raise ValueError('unregistered_maryland_source')


def md_address(value):
    parts = [part.strip() for part in plain(value).split(',') if part.strip()]
    if parts and parts[-1].casefold() in {'us', 'usa', 'united states'}:
        parts.pop()
    if len(parts) >= 4 and re.fullmatch(r'\d{5}(?:-\d{4})?', parts[-1]):
        parts[-2:] = [' '.join(parts[-2:])]
    if len(parts) != 3 or not STREET.match(parts[0]) or not STATE.fullmatch(parts[2]):
        return None
    return ', '.join(parts), parts[1]


def library_venue(value):
    # The feed supplies a branch label before the street for Howard County.
    # An offsite/online event never inherits the branch's mailing address.
    label, separator, rest = plain(value).partition(',')
    direct = md_address(value)
    if direct:
        return label, direct
    if separator and (address := md_address(rest)):
        return label, address
    return None


def collect_ics(source, fetch):
    from roomquest.ics_adapter import parse

    key = source['source_key']
    require_source(source, ICS[key], 'ical', 'ical')
    raw = fetch(ICS[key], 'text/calendar')
    calendar = Calendar.from_ical(raw)
    if len(calendar.walk('VEVENT')) > 1000:
        raise ValueError('source_record_limit')
    if key == DNR:
        # The state portal publishes other departments too. Admit a physical
        # State Park venue with its own street and detail URL, never title alone.
        for event in calendar.walk('VEVENT'):
            location = str(event.get('LOCATION', ''))
            found = re.search(r'\b(https://go[.]activecalendar[.]com/doit-md/event/[a-z0-9-]+/?)',
                              str(event.get('DESCRIPTION', '')))
            address = re.search(r'(\d{1,6}\s+[A-Za-z][^,]*,\s*[^,]+,\s*MD(?:\s+\d{5})?)\s*$', location)
            if not found or not address or not re.search(r'\bState Park\b', location, re.I):
                calendar.subcomponents.remove(event)
                continue
            event['LOCATION'] = type(event['LOCATION'])(location[:address.start()].strip(' ,').replace(',', ' / ') + ', ' + address[1])
            event.add('URL', found[1])
        raw = calendar.to_ical().decode()
    rows = parse(raw, {'url': ICS[key], 'source_key': key}, legacy=False, include_description=True)
    events = {str(event.get('UID', '')): event for event in calendar.walk('VEVENT')
              if not event.get('RECURRENCE-ID')}
    result = []
    for row in rows:
        event = events.get(row['id'].split('__', 1)[0])
        # The normalizer keeps the occurrence's own location; recover the raw
        # VEVENT label for nonrecurring feeds without imposing a branch default.
        value = row.get('venue_address') or row.get('venue_name') or ''
        if event is not None and not event.get('RRULE'):
            value = str(event.get('LOCATION', ''))
        location = library_venue(value)
        url = urlsplit(row['event_url'])
        expected = urlsplit(ICS[key])
        valid_path = (re.fullmatch(EVENT_URLS[DNR], row['event_url']) if key == DNR
                      else re.fullmatch(r'/event/[a-z0-9-]+-[1-9]\d*/?', url.path))
        if (not location or not valid_path or url.scheme != 'https' or url.netloc != expected.netloc
                or url.query or url.fragment or NONPUBLIC.search(row['title'])):
            continue
        venue, (address, city) = location
        row.update(venue_name=venue, venue_address=address, venue_city=city, lat=None, lng=None,
                   reason='missing_verified_venue_geo', description=row.get('description', '')[:2000])
        result.append(row)
    if rows and not result:
        raise ValueError('venue_extraction_unavailable')
    return result


def _wp_pages(root, fetch, *, today, days, category=None):
    start, end = today.isoformat(), (today + timedelta(days=days)).isoformat()
    total = pages = None
    seen = set()
    for page in range(1, 6):
        query = {'per_page': 50, 'start_date': start, 'end_date': end, 'page': page}
        if category:
            query['categories'] = category
        payload = json.loads(fetch(root + '?' + urlencode(query), 'application/json'))
        if not isinstance(payload, dict):
            raise ValueError('unsupported_wordpress_payload')
        events = payload.get('events')
        reported_total, reported_pages = payload.get('total'), payload.get('total_pages')
        if (not isinstance(events, list) or len(events) > 50
                or type(reported_total) is not int or reported_total < 0
                or type(reported_pages) is not int or reported_pages < 0):
            raise ValueError('invalid_wordpress_pagination')
        if reported_pages > 5 or reported_total > 250:
            raise ValueError('pagination_limit')
        if total is None:
            total, pages = reported_total, reported_pages
        if (total, pages) != (reported_total, reported_pages):
            raise ValueError('wordpress_snapshot_changed')
        for item in events:
            identity = item.get('id') if isinstance(item, dict) else None
            if type(identity) is not int or identity <= 0 or identity in seen:
                raise ValueError('publisher_event_identity_changed')
            seen.add(identity)
            yield item
        if page >= pages:
            if len(seen) != total or payload.get('next_rest_url'):
                raise ValueError('wordpress_snapshot_changed')
            return


def _pg_location(html, url, start, end):
    page = BeautifulSoup(html, 'html.parser')
    canonical = page.select_one('link[rel=canonical]')
    calendar = page.select_one('.addeventatc')
    locations = page.select('.event-location')
    if canonical is None or canonical.get('href') != url or calendar is None or len(locations) != 1:
        return None
    for selector, fmt, expected in (
            ('.start', '%A, %B %d, %Y %I:%M %p', start),
            ('.end', '%m/%d/%Y %I:%M %p', end)):
        node = calendar.select_one(selector)
        try:
            if node is None or datetime.strptime(plain(node.get_text()), fmt) != expected.replace(tzinfo=None):
                return None
        except ValueError:
            return None
    node = locations[0]
    venue = node.select_one('p a[href]')
    maps = [a for a in node.select('a[href]') if urlsplit(a['href']).hostname == 'maps.google.com']
    if venue is None or len(maps) != 1:
        return None
    # The publisher's map URL carries the event's explicit street/city/state.
    # It is parsed locally and is never requested.
    query = parse_qs(urlsplit(maps[0]['href']).query).get('q', [])
    address = library_venue(query[0]) if len(query) == 1 else None
    if not address or not plain(venue.get_text()):
        return None
    return plain(venue.get_text()), address[1]


def collect_wordpress(source, fetch, *, now=None):
    from roomquest.mapsee_adapter import parse_tribe
    from roomquest.publisher_evidence import attach

    key = source['source_key']
    parks = key == PG_PARKS
    require_source(source, PG_ROOT if parks else ARTS_FEED, 'json', 'wordpress')
    root = PG_ROOT + '/wp-json/tribe/events/v1/events' if parks else ARTS_FEED
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(ZONE)).date()
    # PG's complete county calendar needs eight pages and its API omits
    # addresses. Review its public Special Event category with a detail budget.
    # The Arts API advertises a 10-second crawl delay. Use a bounded fortnight.
    items = list(_wp_pages(root, fetch, today=today, days=60 if parks else 14,
                           category=540 if parks else None))
    if parks and len(items) > 16:
        raise ValueError('publisher_detail_limit')
    result = []
    held = 0
    for item in items:
        title, url = plain(item.get('title')), item.get('url') or ''
        if (item.get('status') != 'publish' or any(item.get(k) for k in
                ('all_day', 'is_virtual', 'hide_from_listings'))
                or item.get('event_status') in {'canceled', 'cancelled', 'postponed'}
                or NONPUBLIC.search(title)):
            continue
        if not re.fullmatch(EVENT_URLS[key], url):
            raise ValueError('publisher_event_identity_changed')
        starts, ends = (timestamp(item.get(k), ZONE) for k in ('start_date', 'end_date'))
        if (not starts or not ends or ends <= starts
                or starts != timestamp(item.get('utc_start_date'), 'UTC')
                or ends != timestamp(item.get('utc_end_date'), 'UTC')):
            held += 1
            continue
        if ends <= now:
            continue
        row = parse_tribe({'events': [item]}, strict_public=True, retain_description=True)
        if not row:
            continue
        row = row[0]
        if parks:
            location = _pg_location(fetch(url, 'text/html'), url, starts, ends)
        else:
            address = md_address(row.get('venue_address'))
            location = (row['venue_name'], address) if address and row.get('venue_name') else None
        if not location:
            held += 1
            continue
        venue, (address, city) = location
        row.update(venue_name=venue, venue_address=address, venue_city=city,
                   timezone=ZONE, lat=None, lng=None, reason='missing_verified_venue_geo',
                   publisher_categories=[plain(c.get('name'))[:100] for c in item.get('categories', [])
                                         if isinstance(c, dict) and plain(c.get('name'))][:20])
        image = item.get('image')
        result.append(attach(row, key, candidate=image.get('url') if isinstance(image, dict) else None,
                             facts={'cost': plain(item.get('cost'))[:400]}))
    if held and not result:
        raise ValueError('venue_extraction_unavailable')
    return result


def _savage_events(fetch, now):
    from roomquest.publisher_evidence import attach

    base = HTML[SAVAGE]
    for page in range(1, 9):
        url = base if page == 1 else f'{base}page/{page}/'
        soup = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        data = soup.select_one('script[data-js="tribe-events-view-data"]')
        if data is None:
            raise ValueError('publisher_calendar_identity_changed')
        listing = json.loads(data.get_text())
        blocks = []
        for node in soup.select('script[type="application/ld+json"]'):
            value = json.loads(node.get_text())
            if isinstance(value, list):
                blocks.extend(x for x in value if isinstance(x, dict) and x.get('@type') == 'Event')
        if not isinstance(listing.get('events'), list) or len(listing['events']) != len(blocks) or len(blocks) > 20:
            raise ValueError('wordpress_snapshot_changed')
        for item in blocks:
            url = item.get('url') or ''
            if not re.fullmatch(EVENT_URLS[SAVAGE], url):
                raise ValueError('publisher_event_identity_changed')
            if (item.get('eventStatus') != 'https://schema.org/EventScheduled'
                    or NONPUBLIC.search(plain(item.get('name')))):
                continue
            start = timestamp(item.get('startDate'))
            end = timestamp(item.get('endDate'))
            if not start or not end or end <= start:
                continue
            if start >= now + timedelta(days=60):
                return
            place = item.get('location') or {}
            postal = place.get('address') or {}
            address = md_address(', '.join(plain(postal.get(k)) for k in
                                            ('streetAddress', 'addressLocality', 'addressRegion', 'postalCode')))
            if not address:
                continue
            row = record(item.get('name'), start.isoformat(), end.isoformat(), place.get('name'),
                         address[0], address[1], url, urlsplit(url).path.strip('/'), tz=ZONE)
            if row:
                row['description'] = plain(item.get('description'))[:2000]
                image = item.get('image')
                yield attach(row, SAVAGE, candidate=image if isinstance(image, str) else None)
        expected = f'{base}page/{page + 1}/'
        next_url = listing.get('next_url')
        if not next_url:
            return
        if next_url != expected:
            raise ValueError('pagination_requires_review')
    raise ValueError('pagination_limit')


def _history_events(payload, now):
    from roomquest.chase_city_chamber import _times
    from roomquest.publisher_evidence import attach

    soup = BeautifulSoup(payload, 'html.parser')
    listing = soup.select_one('.eventlist--upcoming')
    if listing is None:
        raise ValueError('publisher_calendar_identity_changed')
    cards = listing.select('article.eventlist-event')
    if len(cards) > 40:
        raise ValueError('source_record_limit')
    for card in cards:
        title_node = card.select_one('.eventlist-title-link[href]')
        if title_node is None:
            raise ValueError('publisher_event_identity_changed')
        title = plain(title_node.get_text())
        url = urljoin(HTML[HISTORY], title_node['href'])
        if not re.fullmatch(EVENT_URLS[HISTORY], url):
            raise ValueError('publisher_event_identity_changed')
        if NONPUBLIC.search(title):
            continue
        start, end, facts = _times(card)
        if start is None or end is None or start >= now + timedelta(days=60) or end <= now:
            continue
        if plain((facts.get('text') or [''])[0]) != title:
            raise ValueError('publisher_event_identity_changed')
        description = card.select_one('.eventlist-description')
        body = plain(description.get_text(' ', strip=True)) if description else ''
        location = (facts.get('location') or [''])[0]
        address = library_venue(location)
        if not address:
            # Two cards explicitly print a street/city/state in the narrative.
            matches = re.findall(r'(\d{1,6}\s+[A-Za-z][^,]{2,75},\s*[A-Za-z][^,]{1,45},\s*MD\s+\d{5})\b', body)
            if len(matches) == 1 and (parsed := md_address(matches[0])) and not re.match(r'(\w+) \1\b', parsed[1], re.I):
                address = parsed[0].split(',')[0], parsed
        if not address:
            continue
        venue, (street, city) = address
        row = record(title, start.isoformat(), end.isoformat(), venue, street, city, url,
                     urlsplit(url).path.strip('/'), tz=ZONE)
        if row:
            row['description'] = body[:2000]
            image = card.select_one('.eventlist-column-thumbnail img')
            yield attach(row, HISTORY, candidate=(image.get('data-src') or image.get('src')) if image else None,
                         evidence_url=HTML[HISTORY])


def collect_html(source, fetch, *, deadline_at=None, now=None):
    key = source['source_key']
    require_source(source, HTML[key], 'html', 'html')
    now = now or datetime.now(timezone.utc)
    records = (_savage_events(fetch, now) if key == SAVAGE
               else _history_events(fetch(HTML[key], 'text/html'), now))
    rows = {}
    for row in records:
        identity = row['id'], row['starts_at']
        if identity in rows and rows[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        rows[identity] = row
    return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
