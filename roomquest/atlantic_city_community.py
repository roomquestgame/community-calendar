"""Official Atlantic City arts and library calendars, using shared normalizers.

Squarespace's public HTML is used because these publishers disallow their
JSON/iCalendar exports.  The city library's public StyledCalendar widget is
converted to iCalendar so recurrence expansion stays on the existing path.
The municipal AlphaDog calendar supplies its own public detail API. Larger
HTML/detail calendars use the worker's durable snapshot checkpoint contract.
Descriptions are complete publisher text; missing/oversized text is held,
never manufactured or shortened to make a record publishable.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar, Event, vRecur, vText

from roomquest.event_description import description
from roomquest.ics_adapter import parse as parse_ics
from roomquest.mapsee_adapter import plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = 'America/New_York'
COUNTY = 'atlantic_county_library_nj'
NOYES = 'noyes_arts_atlantic_city_nj'
ARTS = 'atlantic_city_arts_foundation_nj'
CITY_LIBRARY = 'atlantic_city_public_library_nj'
CITY = 'atlantic_city_municipal_nj'
SOURCES = {
    COUNTY: ('https://atlanticcounty.librarycalendar.com/events/feed/ical', 'ical', 'ical'),
    NOYES: ('https://noyesmuseum.org/all-noyes-events', 'html', 'html'),
    ARTS: ('https://atlanticcityartsfoundation.org/calendar', 'html', 'html'),
    CITY_LIBRARY: ('https://acfpl.org/events-menu/library-event-calendar-menu.html', 'html', 'html'),
    CITY: ('https://www.acnj.gov/calendar', 'html', 'html'),
}
LIBRARY_WIDGET_ID = '0u1npdLcaal07bbJ2llk'
LIBRARY_WIDGET = ('https://embed.styledcalendar.com/api/get-styled-calendar-events-data/'
                  '?styledCalendarId=' + LIBRARY_WIDGET_ID)
ALLOWED_HOSTS = {
    key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()
}
ALLOWED_HOSTS[CITY_LIBRARY] = ('acfpl.org', 'embed.styledcalendar.com')
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|private (?:event|party)|invitation[- ]only|staff[- ]only)\b', re.I)
MAX_DESCRIPTION = 12000
MAX_DETAILS = 80
MAX_DETAILS_PER_CHUNK = 6
MIN_DETAIL_SECONDS = 18
MAX_CHECKPOINT_BYTES = 900_000
MAX_CHECKPOINT_AGE = timedelta(hours=4)
VENUE_POINT_CONTRACT_VERSION = 2

# Addresses reviewed against the publisher's own branch directory (2026-11-14).
# Match the street supplied by the event, rather than inheriting a system HQ.
# https://atlanticcounty.librarycalendar.com/events/upcoming
COUNTY_BRANCHES = {
    'absecon': ('Absecon Branch Library', '305 New Jersey Avenue, Absecon, NJ 08201'),
    'brigantine': ('Brigantine Branch Library', '201 15th Street South, Brigantine, NJ 08203'),
    'buena': ('Buena Community Reading Center', '125 Weymouth-Malaga Road, Buena, NJ 08310'),
    'egg harbor city': ('Egg Harbor City Branch Library', '134 Philadelphia Avenue, Egg Harbor City, NJ 08215'),
    'egg harbor township': ('Egg Harbor Township Branch Library', '1 Swift Avenue, Egg Harbor Township, NJ 08234'),
    'galloway': ('Galloway Township Branch Library', '306 East Jimmie Leeds Road, Galloway, NJ 08205'),
    'galloway township': ('Galloway Township Branch Library', '306 East Jimmie Leeds Road, Galloway, NJ 08205'),
    'hammonton': ('Hammonton Branch Library', '451 South Egg Harbor Road, Hammonton, NJ 08037'),
    'mays landing': ('Mays Landing Branch Library', '40 Farragut Avenue, Mays Landing, NJ 08330'),
    'pleasantville': ('Pleasantville Branch Library', '33 Martin Luther King Jr. Avenue, Pleasantville, NJ 08232'),
    'somers point': ('Somers Point Branch Library', '801 Shore Road, Somers Point, NJ 08244'),
    'ventnor': ('Ventnor Branch Library', '6500 Atlantic Avenue, Ventnor, NJ 08406'),
}
MAIN_LIBRARY = ('Atlantic City Free Public Library — Main Library',
                '1 North Tennessee Avenue, Atlantic City, NJ 08401', 'Atlantic City')
RICHMOND_LIBRARY = ('Atlantic City Free Public Library — Richmond Branch',
                    '4115 Ventnor Avenue, Atlantic City, NJ 08401', 'Atlantic City')
MARMORA_BLOCK = ('1800 Block of Marmora Avenue (approximate map location)',
                 '1800 Marmora Avenue, Atlantic City, NJ 08401', 'Atlantic City')

# Exact venue associations, reviewed 2026-11-14. These are destination points
# published for the named buildings, never source-coverage centers. Each tuple
# includes the venue name AND full street so relocation cannot inherit a pin.
REVIEWED_VENUE_POINTS = {
    # Official ACAF event metadata identifies this exact Main Library address;
    # the library's current hours/locations page independently confirms it.
    # https://atlanticcityartsfoundation.org/calendar/community-meeting-may-mkbs2
    # https://acfpl.org/about-us-new/hours-locations-menu.html
    (CITY_LIBRARY, MAIN_LIBRARY[0], MAIN_LIBRARY[1]): (39.3625922, -74.4281244),
    # Current county ICS supplies this point for Bored? Games! at the Senior
    # Center. Independent Noyes/Somers Point Arts Commission event metadata
    # places the same named building about 6.5 metres away, and the city venue
    # directory confirms the exact street. Preserve existing native ICS GPS.
    # https://atlanticcounty.librarycalendar.com/event/copy-bored-games-40570
    # https://visitsomerspoint.com/venue/somers-point-senior-center/
    # https://noyesmuseum.org/all-noyes-events/2025/10/8/access-to-art-senior-art-class-with-the-somers-point-arts-commission-rkg6k
    (COUNTY, 'Somers Point Senior Center',
     '22 North Ambler Road, Somers Point, NJ 08244'): (39.3252475, -74.6081318),
    # Episcopal Asset Map publishes both the street and GeoCoordinates for
    # this church; its directions link contains the same destination point.
    # https://www.episcopalassetmap.org/dioceses/diocese-new-jersey/list/st-augustines-church
    (CITY, 'St. Augustine’s Episcopal Church',
     '1709 Arctic Ave., Atlantic City, NJ 08401'): (39.361884, -74.433525),
    # The city supplies the numbered block, not a building. NJ Office of GIS
    # returns a score-100 StreetAddress match on its 1800–1832 road segment.
    # Keep the visible approximate-location qualifier; this is neither a roof
    # point nor a claim about the exact shredding truck position.
    # https://www.acnj.gov/Calendar/ViewEvent/2078
    # https://geo.nj.gov/arcgis/rest/services/Tasks/NJ_Geocode/GeocodeServer/findAddressCandidates
    # SingleLine=1800 Marmora Avenue, Atlantic City, NJ 08401; outSR=4326.
    (CITY, MARMORA_BLOCK[0], MARMORA_BLOCK[1]): (39.369920418545, -74.440134563461),
}


def _apply_reviewed_venue_point(row, source_key):
    if row.get('lat') is not None or row.get('lng') is not None:
        return
    point = REVIEWED_VENUE_POINTS.get((source_key, row.get('venue_name'), row.get('venue_address')))
    if point is not None:
        row['lat'], row['lng'] = point
        if row.get('reason') == 'missing_verified_venue_geo':
            row['reason'] = None


def event_url(source_key, value):
    if not isinstance(value, str):
        return False
    p = urlsplit(value)
    if p.scheme != 'https' or p.query or p.fragment or p.username or p.password or p.port not in (None, 443):
        return False
    if source_key == CITY_LIBRARY:
        return value == SOURCES[CITY_LIBRARY][0]
    if source_key == CITY:
        return p.netloc == 'www.acnj.gov' and bool(re.fullmatch(r'/Calendar/View(?:Event|Meeting)/[1-9][0-9]{0,8}', p.path))
    profile = SOURCES.get(source_key)
    if not profile or p.netloc != urlsplit(profile[0]).netloc:
        return False
    prefix = '/event/' if source_key == COUNTY else urlsplit(profile[0]).path + '/'
    return bool(p.path.startswith(prefix) and re.fullmatch(r'[A-Za-z0-9/_%-]+', p.path)
                and len(p.path) > len(prefix))


def _full_description(value):
    if not isinstance(value, str):
        return ''
    # Passing the input length removes the shared 2,000-character display cap.
    text = description(value, limit=max(len(value), MAX_DESCRIPTION + 1))
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('publisher_description_limit')
    return text


def _hold(key, identity, reason):
    log.warning('atlantic_city_record_held source=%s id=%s reason=%s', key, identity, reason)


def _nj_address(value):
    text = plain(value)
    text = re.sub(r',?\s*(?:United States(?: of America)?|USA|US)\s*$', '', text, flags=re.I)
    text = re.sub(r',\s*New Jersey\b', ', NJ', text, flags=re.I)
    text = re.sub(r',\s*NJ\s*,\s*(\d{5}(?:-\d{4})?)$', r', NJ \1', text)
    match = re.fullmatch(r'(\d{1,6}(?:-\d+)?\s+[^,]+(?:,\s*(?:Suite|Ste|Unit)\s+[^,]+)?),\s*([^,]+),\s*NJ(?:\s+(\d{5}(?:-\d{4})?))?', text, re.I)
    if not match:
        return None
    street, city, postal = match.groups()
    # The shared structured-address parser expects a single street field.
    # Preserve the unit identifier without adding a fourth comma component.
    street = re.sub(r',\s*((?:Suite|Ste|Unit)\s+)', r' \1', street, flags=re.I)
    city = city.strip()
    return f'{street.strip()}, {city}, NJ' + (f' {postal}' if postal else ''), city


def _county_location(value, narrative):
    raw = plain(value)
    # The feed contains a repeated city in this explicitly offsite address.
    # The city's own venue page confirms 22 North Ambler Road:
    # https://visitsomerspoint.com/venue/somers-point-senior-center/
    if (re.match(r'^22-98 N\.? Ambler Rd\.?\b', raw, re.I)
            and 'Somers Point Senior Center' in narrative):
        return 'Somers Point Senior Center', '22 North Ambler Road, Somers Point, NJ 08244', 'Somers Point'
    location = _nj_address(raw)
    if not location:
        return None
    address, city = location
    branch = COUNTY_BRANCHES.get(city.casefold())
    if branch:
        # An event at another numbered street in the same city remains offsite.
        advertised_number = address.split(' ', 1)[0]
        branch_number = branch[1].split(' ', 1)[0]
        if advertised_number == branch_number:
            return branch[0], branch[1], branch[1].split(', ')[1]
    if address.startswith('535 London Avenue, Egg Harbor City,'):
        return 'Egg Harbor City Historical Society Roundhouse Museum', address, city
    return address.split(',', 1)[0], address, city


def _normalize_ics(raw, source_key, *, locations=None, closures=(), already_normalized=False):
    cal = Calendar.from_ical(raw)
    events = cal.walk('VEVENT')
    if len(events) > 1000:
        raise ValueError('source_record_limit')
    for event in events:
        # Preserve the shared parser's malformed-component rejection before
        # serialization could discard the original parser error metadata.
        if event.errors:
            if any(str(error[0]).upper() in {'RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID'}
                   for error in event.errors):
                raise ValueError('recurrence_invalid')
            raise ValueError('invalid_ical_component')
        # The shared parser caps raw DESCRIPTION at 12,000 characters. Strip
        # markup first, so a long HTML attribute cannot clip valid prose that
        # fits the actual description limit. Normalize every component,
        # including recurrence overrides, before the existing expansion path.
        text = str(event.get('DESCRIPTION', ''))
        if not already_normalized:
            text = _full_description(text)
        if len(text) > MAX_DESCRIPTION:
            raise ValueError('publisher_description_limit')
        event['DESCRIPTION'] = vText(text)
    raw = cal.to_ical().decode('utf-8')
    by_id = {str(event.get('UID', '')): event for event in events if not event.get('RECURRENCE-ID')}
    rows = parse_ics(raw, {'url': SOURCES[source_key][0], 'source_key': source_key},
                     legacy=False, include_description=True)
    result = []
    for row in rows:
        identity = row['id'].split('__', 1)[0]
        original = by_id.get(identity)
        # Already normalized before expansion; parsing it as HTML again would
        # erase escaped literal text such as the publisher's "<bring ID>".
        text = row.get('description', '')
        if not isinstance(text, str) or len(text) > MAX_DESCRIPTION:
            raise ValueError('publisher_description_limit')
        if not text.strip() or NONPUBLIC.search(row['title']):
            _hold(source_key, row['id'], 'description_unavailable_or_nonpublic')
            continue
        if not event_url(source_key, row.get('event_url')):
            raise ValueError('publisher_event_identity_changed')
        if source_key == COUNTY:
            location = _county_location(str(original.get('LOCATION', '')) if original else
                                        row.get('venue_address', ''), text)
        else:
            location = (locations or {}).get(identity)
        if not location:
            _hold(source_key, row['id'], 'venue_street_unresolved')
            continue
        start = timestamp(row['starts_at'])
        end = timestamp(row.get('ends_at')) or start + timedelta(hours=3)
        if any(start < closed_end and end > closed_start for closed_start, closed_end in closures):
            _hold(source_key, row['id'], 'publisher_library_closure')
            continue
        row.update(venue_name=location[0], venue_address=location[1], venue_city=location[2],
                   description=text, timezone=ZONE)
        _apply_reviewed_venue_point(row, source_key)
        if original is not None and original.get('IMAGE'):
            row['image_url'] = str(original['IMAGE'])
        result.append(row)
    if len(result) > 500:
        raise ValueError('source_record_limit')
    return sorted(result, key=lambda row: (row['starts_at'], row['id']))


def _google_times(node):
    links = [a for a in node.select('a[href]')
             if urlsplit(a['href']).hostname == 'www.google.com'
             and urlsplit(a['href']).path == '/calendar/event']
    if len(links) != 1:
        raise ValueError('publisher_calendar_link_changed')
    query = parse_qs(urlsplit(links[0]['href']).query)
    dates = query.get('dates') or []
    if query.get('action') != ['TEMPLATE'] or len(dates) != 1:
        raise ValueError('publisher_calendar_link_changed')
    if re.fullmatch(r'\d{8}/\d{8}', dates[0]):
        return None, None, query
    if not re.fullmatch(r'\d{8}T\d{6}Z/\d{8}T\d{6}Z', dates[0]):
        raise ValueError('publisher_event_time_changed')
    start, end = [datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                  for value in dates[0].split('/')]
    if end < start:
        raise ValueError('invalid_event_end')
    return start, end if end > start else None, query


def _squarespace_venue_point(soup, main, link, published_location):
    """Accept only this event's destination metadata tied to its own street.

    Squarespace also emits a generic Manhattan point on location-less pages.
    That value must not become event GPS. The reviewed southern New Jersey
    bounds include these publishers' current venues; points outside them are
    left to ordinary address resolution, without discarding the event.
    """
    canonical = soup.select('meta[property="og:url"]')
    latitude = soup.select('meta[property="og:latitude"]')
    longitude = soup.select('meta[property="og:longitude"]')
    maps = main.select('.eventitem-meta-address-maplink[href]')
    if (len(canonical) != 1 or canonical[0].get('content') != link
            or len(latitude) != 1 or len(longitude) != 1 or len(maps) != 1
            or not _nj_address(published_location)):
        return None
    target = urlsplit(maps[0]['href'])
    query = parse_qs(target.query).get('q')
    if (target.scheme not in ('http', 'https') or target.hostname not in ('maps.google.com', 'www.google.com')
            or target.path not in ('', '/', '/maps') or not query or len(query) != 1):
        return None
    # Squarespace omits commas in the map link while retaining them in its
    # calendar-export location. Require all actual address characters to agree.
    fingerprint = lambda value: re.sub(r'[^a-z0-9]', '', plain(value).casefold())
    if fingerprint(query[0]) != fingerprint(published_location):
        return None
    lines = main.select('.eventitem-meta-address-line:not(.eventitem-meta-address-line--title)')
    visible_address = ' '.join(node.get_text(' ', strip=True) for node in lines)
    if not lines or fingerprint(visible_address) != fingerprint(published_location):
        return None
    try:
        lat, lng = float(latitude[0]['content']), float(longitude[0]['content'])
    except (KeyError, TypeError, ValueError):
        return None
    if (not math.isfinite(lat) or not math.isfinite(lng)
            or not 39.0 <= lat <= 39.85 or not -75.2 <= lng <= -74.2):
        return None
    return lat, lng


def _squarespace_detail(key, link, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('.eventitem') or soup
    title_node = main.select_one('.eventitem-title')
    body = main.select_one('.eventitem-column-content .sqs-layout')
    if title_node is None or body is None:
        raise ValueError('publisher_event_detail_changed')
    title = plain(title_node.get_text())
    start, end, facts = _google_times(main)
    later = soup.select_one('.eventitem-pager-newer a[href], a.eventitem-pager-newer[href]')
    if later is None:
        later = next((a for a in soup.select('a[href]') if 'Later Event:' in a.get_text()), None)
    next_url = urljoin(link, later['href']) if later else None
    if next_url and not event_url(key, next_url):
        raise ValueError('publisher_next_event_changed')
    if start is None:
        _hold(key, link, 'date_only_event')
        return None, next_url, None
    if (NONPUBLIC.search(title) or start >= now + timedelta(days=60)
            or (end or start + timedelta(hours=3)) <= now):
        return None, next_url, start
    if plain((facts.get('text') or [''])[0]) != title:
        raise ValueError('publisher_event_identity_changed')
    text = _full_description(str(body))
    published_location = (facts.get('location') or [''])[0]
    location = _nj_address(published_location)
    # One Noyes film listing prints 08240 for Stockton's Galloway campus.
    # Stockton's own address is 101 Vera King Farris Drive, Galloway NJ 08205.
    # https://stockton.edu/maps/
    if (key == NOYES and location
            and re.fullmatch(r'101 Vera King Farris Dr[.]?, Galloway, NJ 08240', location[0])):
        location = (location[0].removesuffix('08240') + '08205', location[1])
    address_node = main.select_one('.eventitem-meta-address')
    if not text or not location or address_node is None:
        _hold(key, link, 'description_or_street_unavailable')
        return None, next_url, start
    # Map links duplicate the visible address; remove only the map label.
    venue_node = BeautifulSoup(str(address_node), 'html.parser')
    for anchor in venue_node.select('a'):
        anchor.decompose()
    venue_text = plain(venue_node.get_text())
    numbered = re.search(r'\b\d{1,6}\s', venue_text)
    venue = venue_text[:numbered.start()].strip(' ,') if numbered else venue_text
    point = _squarespace_venue_point(soup, main, link, published_location)
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue or location[0].split(',')[0], location[0], location[1], link,
                 sha256(urlsplit(link).path.encode()).hexdigest(),
                 lat=point[0] if point else None, lng=point[1] if point else None,
                 tz=ZONE, retain_until_end=True)
    if row:
        row['description'] = text
        row['timezone'] = ZONE
        candidate = body.select_one('img[data-src], img[src]')
        if candidate:
            row['image_url'] = candidate.get('data-src') or candidate.get('src')
    return row, next_url, start


def _squarespace_links(key, payload, now):
    listing = SOURCES[key][0]
    soup = BeautifulSoup(payload, 'html.parser')
    links = {}
    if key == ARTS:
        if soup.select_one('.eventlist') is None:
            raise ValueError('publisher_calendar_identity_changed')
        for card in soup.select('article.eventlist-event--upcoming'):
            anchor = card.select_one('.eventlist-title-link[href]')
            if anchor is not None:
                links[urljoin(listing, anchor['href'])] = None
    else:
        cards = soup.select('noscript > ul > li')
        if not cards or len(cards) > 150:
            raise ValueError('publisher_calendar_identity_changed')
        for card in cards:
            anchor = card.select_one('h1 a[href]')
            if anchor is None:
                continue
            dates = re.findall(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) \d{1,2}, \d{4}',
                               plain(card.get_text(' ', strip=True)))
            if not dates:
                raise ValueError('publisher_calendar_date_missing')
            days = []
            for value in dates:
                try:
                    days.append(datetime.strptime(value, '%B %d, %Y').date())
                except ValueError:
                    days.append(datetime.strptime(value, '%b %d, %Y').date())
            if max(days) < now.astimezone(ZoneInfo(ZONE)).date():
                continue
            links[urljoin(listing, anchor['href'])] = max(days)
    if len(links) > MAX_DETAILS or any(not event_url(key, link) for link in links):
        raise ValueError('publisher_detail_limit')
    return links


def _squarespace(key, fetch, now):
    links = _squarespace_links(key, fetch(SOURCES[key][0], 'text/html'), now)
    outcomes = {}
    # Shared transport still enforces publisher robots, pacing, redirect hosts,
    # response size and the source deadline for each of these bounded requests.
    def detail(link):
        return link, _squarespace_detail(key, link, fetch(link, 'text/html'), now)
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(copy_context().run, detail, link) for link in links]
        outcomes.update(task.result() for task in tasks)
    if key == NOYES and outcomes:
        # The default calendar HTML lists the current month. Follow its actual
        # forward event navigation to discover following-month events too.
        # Never request the site's robots-disallowed month/view/export URLs.
        latest = max(outcomes, key=lambda link: outcomes[link][2] or datetime.min.replace(tzinfo=timezone.utc))
        while outcomes[latest][1]:
            upcoming = outcomes[latest][1]
            if upcoming in outcomes:
                raise ValueError('publisher_next_event_cycle')
            if len(outcomes) >= MAX_DETAILS:
                raise ValueError('publisher_detail_limit')
            _, outcome = detail(upcoming)
            if outcome[2] and outcomes[latest][2] and outcome[2] < outcomes[latest][2]:
                raise ValueError('publisher_event_order_changed')
            outcomes[upcoming] = outcome
            latest = upcoming
            if outcome[2] and outcome[2] >= now + timedelta(days=60):
                break
    rows = [outcome[0] for outcome in outcomes.values() if outcome[0] is not None]
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def _community_checkpoint(value, now, key=NOYES):
    invalid = 'noyes_checkpoint_invalid' if key == NOYES else 'municipal_checkpoint_invalid'
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('version')) is not int
            or value.get('version') != 1 or value.get('source_key') != key
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES
            or type(value.get('cursor')) is not int
            or type(value.get('manifest_count')) is not int
            or not 0 <= value['cursor'] <= value['manifest_count'] <= MAX_DETAILS
            or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('manifest_hash', '')))
            or not isinstance(value.get('base_urls'), list)
            or not isinstance(value.get('queue'), list)
            or len(value['queue']) != value['manifest_count']
            or any(not event_url(key, url) for url in value['queue'])
            or len(set(value['queue'])) != len(value['queue'])
            or value['queue'][:len(value['base_urls'])] != value['base_urls']
            or not isinstance(value.get('events'), list) or len(value['events']) > MAX_DETAILS
            or not isinstance(value.get('diagnostics'), list) or len(value['diagnostics']) > MAX_DETAILS
            or not isinstance(value.get('edges'), list) or len(value['edges']) != value['cursor']):
        raise ValueError(invalid)
    try:
        start = datetime.fromisoformat(value['started_at'])
        anchor = date.fromisoformat(value['window_start'])
        if start.tzinfo is None or anchor != start.astimezone(ZoneInfo(ZONE)).date():
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError(invalid) from None
    if now < start or now - start > MAX_CHECKPOINT_AGE:
        return None
    prefix = value['queue'][:value['cursor']]
    accepted, held, linked = set(), set(), set()
    for row in value['events']:
        if (not isinstance(row, dict) or row.get('event_url') not in prefix
                or row['event_url'] in accepted
                or row.get('id') != sha256(urlsplit(row['event_url']).path.encode()).hexdigest()
                or not _full_description(row.get('description'))
                or not _nj_address(row.get('venue_address'))
                or not timestamp(row.get('starts_at'))):
            raise ValueError(invalid)
        accepted.add(row['event_url'])
    for item in value['diagnostics']:
        if (not isinstance(item, dict) or item.get('event_url') not in prefix
                or item['event_url'] in accepted | held or item.get('disposition') != 'held'
                or item.get('reason') != 'publisher_record_not_eligible'):
            raise ValueError(invalid)
        held.add(item['event_url'])
    for index, edge in enumerate(value['edges']):
        if (not isinstance(edge, dict) or edge.get('from') != prefix[index]
                or (edge.get('next') is not None and not event_url(key, edge['next']))):
            raise ValueError(invalid)
        if edge.get('next'):
            linked.add(edge['next'])
    if (accepted | held != set(prefix)
            or not set(value['queue'][len(value['base_urls']):]) <= linked):
        raise ValueError(invalid)
    return deepcopy(value)


def _noyes_manifest_digest(links, ordered):
    encoded = {'venue_point_contract_version': VENUE_POINT_CONTRACT_VERSION,
               'events': [[url, links[url].isoformat()] for url in ordered]}
    return sha256(json.dumps(encoded, separators=(',', ':')).encode()).hexdigest()


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    """Read Noyes or municipal details in durable, complete-window chunks.

    The allowed default page contains the current month. Each fetched detail's
    real forward link extends the queue before its cursor advances. Thus a
    checkpoint cannot claim completion before following the next month too.
    The worker owns revision checks, guarded transport and durable persistence.
    """
    if source.get('source_key') == CITY:
        return _municipal_chunk(source, fetch, checkpoint=checkpoint, deadline_at=deadline_at,
                                now=now, max_details=max_details)
    if ((source.get('source_key'), source.get('feed_url'), source.get('kind'),
         source.get('platform_adapter'), source.get('timezone')) !=
            (NOYES, *SOURCES[NOYES], ZONE)):
        raise ValueError('unregistered_atlantic_city_community_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('noyes_checkpoint_invalid')
    current = current.astimezone(timezone.utc)
    state = _community_checkpoint(checkpoint, current)
    anchor = datetime.fromisoformat(state['started_at']) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    payload = fetch(SOURCES[NOYES][0], 'text/html')
    links = _squarespace_links(NOYES, payload, anchor)
    base = sorted(links, key=lambda url: (links[url], url))
    digest = _noyes_manifest_digest(links, base)
    if state is None or state['manifest_hash'] != digest or state['base_urls'] != base:
        anchor = current
        links = _squarespace_links(NOYES, payload, anchor)
        base = sorted(links, key=lambda url: (links[url], url))
        digest = _noyes_manifest_digest(links, base)
        state = {'version': 1, 'source_key': NOYES, 'started_at': current.isoformat(),
                 'window_start': current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 'manifest_hash': digest, 'manifest_count': len(base), 'cursor': 0,
                 'base_urls': base, 'queue': list(base), 'edges': [], 'events': [], 'diagnostics': []}
    previous = state['cursor']
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state['cursor'] < len(state['queue']) and state['cursor'] - previous < limit:
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        url = state['queue'][state['cursor']]
        row, next_url, start = _squarespace_detail(NOYES, url, fetch(url, 'text/html'), anchor)
        if row is not None:
            state['events'].append(row)
        else:
            state['diagnostics'].append({'event_url': url, 'disposition': 'held',
                                         'reason': 'publisher_record_not_eligible'})
        state['edges'].append({'from': url, 'next': next_url})
        if next_url and (start is None or start < anchor + timedelta(days=60)):
            if next_url not in state['queue']:
                if len(state['queue']) >= MAX_DETAILS:
                    raise ValueError('publisher_detail_limit')
                state['queue'].append(next_url)
            elif (state['cursor'] >= len(base)
                  and next_url in state['queue'][:state['cursor'] + 1]):
                raise ValueError('publisher_next_event_cycle')
        state['cursor'] += 1
        state['manifest_count'] = len(state['queue'])
    if state['cursor'] == previous < len(state['queue']):
        raise ValueError('collection_deadline')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('noyes_checkpoint_size_limit')
    complete = state['cursor'] == state['manifest_count']
    rows = sorted(state['events'], key=lambda row: (row['starts_at'], row['id'])) if complete else []
    return {'complete': complete, 'events': deepcopy(rows), 'checkpoint': state}


def _municipal_manifest(payload):
    items = json.loads(payload)
    if not isinstance(items, list) or len(items) > MAX_DETAILS:
        raise ValueError('municipal_calendar_limit')
    result = {}
    for item in items:
        if (not isinstance(item, dict) or item.get('className') not in ('Event', 'Meeting')
                or not re.fullmatch(r'[1-9][0-9]{0,8}', str(item.get('id', '')))
                or type(item.get('allDay')) is not bool or not plain(item.get('title'))
                or not timestamp(item.get('start'), ZONE)):
            raise ValueError('municipal_calendar_identity_changed')
        url = 'https://www.acnj.gov/Calendar/View' + item['className'] + '/' + str(item['id'])
        if url in result:
            raise ValueError('municipal_calendar_identity_changed')
        result[url] = {field: item.get(field) for field in ('id', 'title', 'className', 'allDay', 'start', 'end')}
    return result


def _municipal_location(value, title):
    raw = plain(value)
    # Actual council-chambers venue, not a municipal-source default. The city
    # confirms Room 206 and this street in its 2026 Planning Board notice:
    # https://www.acnj.gov/News/View/2662/notice-of-cancellation-of-planning-board-meeting
    if (raw == 'City Council Chambers, 2nd Floor, Room 206'
            or re.fullmatch(r'\(?Council Chambers\)?[,]?\s+City Hall\s*[-–]\s*1301 Bacharach Blvd', raw)):
        return 'Atlantic City Hall — Council Chambers', '1301 Bacharach Boulevard, Atlantic City, NJ 08401', 'Atlantic City'
    # The event names these specific courts but omits its location. Official
    # August 2026 funding news identifies the courts at 1510 Adriatic Avenue:
    # https://www.acnj.gov/News/View/2628/grant-will-support-improvements-to-tennis-courts-at-all-wars-memorial-building
    if not raw and title == 'All Wars Tennis Courts Ribbon Cutting':
        return 'All Wars Memorial Building Tennis Courts', '1510 Adriatic Avenue, Atlantic City, NJ 08401', 'Atlantic City'
    # The publisher gives a numbered block. Use that block's starting number
    # as a street-level location estimate, retaining "Block" in the venue so
    # it is not represented as a named building. This is not a parade default.
    if raw == '1800 Block of Marmora Ave., Atlantic City':
        return MARMORA_BLOCK
    number = re.search(r'\b[0-9]{1,6}\s', raw)
    if not number:
        return None
    venue = raw[:number.start()].strip(' ,–-')
    street = raw[number.start():]
    # Other block locations, entire streets and parade routes need individual
    # review before assigning a structured numbered street.
    if re.search(r'\bBlock\b', street, re.I):
        return None
    if re.search(r',\s*Atlantic City$', street, re.I):
        street += ', NJ 08401'
    elif re.search(r',\s*Atlantic City,\s*NJ$', street, re.I):
        street += ' 08401'
    location = _nj_address(street)
    if not location:
        return None
    return venue or location[0].split(',')[0], location[0], location[1]


def _municipal_detail(url, manifest, payload):
    item = json.loads(payload)
    kind = manifest['className']
    if (not isinstance(item, dict) or str(item.get(kind + '_ID')) != str(manifest['id'])
            or type(item.get(kind + '_IsCanceled')) is not bool):
        raise ValueError('municipal_event_identity_changed')
    title = plain(item.get(kind + '_Title') or item.get('Meeting_Type'))
    start_text = item.get('Meeting_DateTime') if kind == 'Meeting' else item.get('Event_StartDateTime')
    end_text = None if kind == 'Meeting' else item.get('Event_EndDateTime')
    start, end = timestamp(start_text, ZONE), timestamp(end_text, ZONE)
    if (title != plain(manifest['title']) or start is None
            or start != timestamp(manifest['start'], ZONE)
            or (kind == 'Event' and (item.get('Event_IsAllDay') is not manifest['allDay']
                                    or end != timestamp(manifest['end'], ZONE)))):
        raise ValueError('municipal_event_schedule_changed')
    if item[kind + '_IsCanceled'] or manifest['allDay'] or NONPUBLIC.search(title):
        return None
    if end is not None and end < start:
        raise ValueError('invalid_event_end')
    if end == start:
        end = None
    narrative = _full_description(item.get(kind + '_Description'))
    location = _municipal_location(item.get(kind + '_Location'), title)
    if not narrative or not location:
        _hold(CITY, url, 'description_or_street_unavailable')
        return None
    row = record(title, start, end, location[0], location[1], location[2], url,
                 sha256(urlsplit(url).path.encode()).hexdigest(), tz=ZONE, retain_until_end=True)
    if row:
        row.update(description=narrative, timezone=ZONE)
        _apply_reviewed_venue_point(row, CITY)
    return row


def _municipal_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                     max_details=MAX_DETAILS_PER_CHUNK):
    if ((source.get('source_key'), source.get('feed_url'), source.get('kind'),
         source.get('platform_adapter'), source.get('timezone')) !=
            (CITY, *SOURCES[CITY], ZONE)):
        raise ValueError('unregistered_atlantic_city_community_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('municipal_checkpoint_invalid')
    current = current.astimezone(timezone.utc)
    state = _community_checkpoint(checkpoint, current, CITY)
    anchor = date.fromisoformat(state['window_start']) if state else current.astimezone(ZoneInfo(ZONE)).date()
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    listing = 'https://www.acnj.gov/api/data/GetCalendarData?' + urlencode({
        'start': anchor.isoformat(), 'end': (anchor + timedelta(days=61)).isoformat()})
    manifest = _municipal_manifest(fetch(listing, 'application/json'))
    base = sorted(manifest, key=lambda url: (manifest[url]['start'], url))
    encoded = {'venue_point_contract_version': VENUE_POINT_CONTRACT_VERSION,
               'events': [[url, manifest[url]] for url in base]}
    digest = sha256(json.dumps(encoded, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    if state is None or state['manifest_hash'] != digest or state['base_urls'] != base:
        state = {'version': 1, 'source_key': CITY, 'started_at': current.isoformat(),
                 'window_start': current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 'manifest_hash': digest, 'manifest_count': len(base), 'cursor': 0,
                 'base_urls': base, 'queue': list(base), 'edges': [], 'events': [], 'diagnostics': []}
    if state['queue'] != base:
        raise ValueError('municipal_checkpoint_invalid')
    previous = state['cursor']
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state['cursor'] < len(base) and state['cursor'] - previous < limit:
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        url = base[state['cursor']]
        card = manifest[url]
        detail_url = 'https://www.acnj.gov/api/data/Get' + card['className'] + '?id=' + str(card['id'])
        row = _municipal_detail(url, card, fetch(detail_url, 'application/json'))
        if row is not None:
            state['events'].append(row)
        else:
            state['diagnostics'].append({'event_url': url, 'disposition': 'held',
                                         'reason': 'publisher_record_not_eligible'})
        state['edges'].append({'from': url, 'next': None})
        state['cursor'] += 1
    if state['cursor'] == previous < len(base):
        raise ValueError('collection_deadline')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('municipal_checkpoint_size_limit')
    complete = state['cursor'] == state['manifest_count']
    rows = sorted(state['events'], key=lambda row: (row['starts_at'], row['id'])) if complete else []
    return {'complete': complete, 'events': deepcopy(rows), 'checkpoint': state}


def _city_library_location(value):
    text = plain(value)
    if re.search(r'\b(?:virtual|online|zoom)\b', text, re.I):
        return None
    if re.search(r'\b(?:Richmond|4115\s+Ventnor)\b', text, re.I):
        return RICHMOND_LIBRARY
    if (text.casefold() in {'atlantic city free public library', 'main library'}
            or re.search(r'\b1\s+(?:N\.?|North)\s+Tennessee\b', text, re.I)):
        return MAIN_LIBRARY
    # Empty publisher venue fields remain held. The office location is never
    # substituted for online, offsite or unspecified library programs.
    return None


def _styled_ical(payload, *, now=None):
    from lzstring import _decompress
    from dateutil.rrule import rrulestr

    now = now or datetime.now(timezone.utc)
    data = json.loads(payload)
    groups = data.get('compressedEventsAndIds') if isinstance(data, dict) else None
    if not isinstance(groups, list) or not 1 <= len(groups) <= 25:
        raise ValueError('publisher_calendar_identity_changed')
    calendar = Calendar()
    calendar.add('VERSION', '2.0')
    calendar.add('PRODID', '-//EventQuest//Atlantic City public library widget//EN')
    calendar.add('X-WR-TIMEZONE', ZONE)
    locations, closures = {}, []
    raw_count = 0
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('publisher_calendar_identity_changed')
        calendar_id, compressed = group.get('sourceCalendarGoogleId'), group.get('compressedEvents')
        if (not isinstance(calendar_id, str) or not calendar_id.endswith('@group.calendar.google.com')
                or not isinstance(compressed, str) or len(compressed) > 150000):
            raise ValueError('publisher_calendar_identity_changed')
        # lzstring 1.0.4's Python-3 UTF16 wrapper omits ord(). Its underlying
        # decoder accepts the correct character accessor for this exact format.
        decoded = _decompress(len(compressed), 16384, lambda index: ord(compressed[index]) - 32)
        if not isinstance(decoded, str) or len(decoded) > 2_000_000:
            raise ValueError('publisher_record_limit')
        # JavaScript compression uses UTF-16 code units, including emoji pairs.
        decoded = decoded.encode('utf-16', 'surrogatepass').decode('utf-16')
        items = json.loads(decoded)
        if not isinstance(items, list):
            raise ValueError('publisher_calendar_identity_changed')
        raw_count += len(items)
        if raw_count > 1000:
            raise ValueError('publisher_record_limit')
        for item in items:
            if not isinstance(item, dict) or item.get('timeZone') != ZONE:
                raise ValueError('publisher_timezone_changed')
            title = plain(item.get('title'))
            identity = item.get('id')
            if not isinstance(identity, str) or not identity or len(identity) > 250:
                raise ValueError('publisher_event_identity_changed')
            if item.get('allDay') is True:
                if re.search(r'\bLIBRARY CLOSED\b', title, re.I):
                    start = datetime.combine(date.fromisoformat(item['start']), datetime.min.time(), ZoneInfo(ZONE))
                    end = datetime.combine(date.fromisoformat(item['end']), datetime.min.time(), ZoneInfo(ZONE))
                    closures.append((start, end))
                continue
            if NONPUBLIC.search(title):
                continue
            start, end = timestamp(item.get('start')), timestamp(item.get('end'))
            if not start or not end or end <= start:
                raise ValueError('publisher_event_time_changed')
            recurrence = item.get('recurrence') or []
            if not isinstance(recurrence, list) or len(recurrence) > 1:
                raise ValueError('recurrence_requires_review')
            for rule in recurrence:
                if not isinstance(rule, str) or not rule.startswith('RRULE:'):
                    raise ValueError('recurrence_requires_review')
                recur = vRecur.from_ical(rule.removeprefix('RRULE:'))
                if (recur.get('FREQ') or [''])[0] not in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}:
                    raise ValueError('unsupported_dense_recurrence')
                # Prune only series with no occurrence in this window. This
                # avoids counting expired historical rules toward the shared
                # normalizer's 50-active-series safety ceiling.
                candidate = rrulestr(rule.removeprefix('RRULE:'),
                                     dtstart=start.astimezone(ZoneInfo(ZONE))).after(now - (end - start), inc=True)
                if candidate is None or candidate >= now + timedelta(days=60):
                    break
            else:
                candidate = start if not recurrence else candidate
            if recurrence and (candidate is None or candidate >= now + timedelta(days=60)):
                continue
            if not recurrence and (end <= now or start >= now + timedelta(days=60)):
                continue
            props = item.get('extendedProps') or {}
            location = _city_library_location(props.get('location', ''))
            text = _full_description(props.get('description', ''))
            if not location or not text:
                _hold(CITY_LIBRARY, identity, 'description_or_street_unavailable')
                continue
            event = Event()
            uid = sha256((calendar_id + ':' + identity).encode()).hexdigest()
            event.add('UID', uid)
            event.add('SUMMARY', title)
            event.add('DTSTART', start.astimezone(ZoneInfo(ZONE)))
            event.add('DTEND', end.astimezone(ZoneInfo(ZONE)))
            event.add('DESCRIPTION', text)
            event.add('LOCATION', location[1])
            event.add('URL', SOURCES[CITY_LIBRARY][0])
            for rule in recurrence:
                event.add('RRULE', vRecur.from_ical(rule.removeprefix('RRULE:')))
            exdates = item.get('exdate') or []
            if not isinstance(exdates, list) or len(exdates) > 200:
                raise ValueError('recurrence_requires_review')
            if exdates:
                event.add('EXDATE', [timestamp(value).astimezone(ZoneInfo(ZONE)) for value in exdates])
            locations[uid] = location
            calendar.add_component(event)
    return calendar.to_ical().decode(), locations, closures


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if profile is None or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'), source.get('timezone')) != (*profile, ZONE):
        raise ValueError('unregistered_atlantic_city_community_source')
    now = now or datetime.now(timezone.utc)
    if key == COUNTY:
        return _normalize_ics(fetch(profile[0], 'text/calendar'), key)
    if key == CITY:
        raise ValueError('publisher_checkpoint_required')
    if key == CITY_LIBRARY:
        page = BeautifulSoup(fetch(profile[0], 'text/html'), 'html.parser')
        frames = page.select('iframe[src]')
        if not any(frame['src'] == 'https://embed.styledcalendar.com/#' + LIBRARY_WIDGET_ID for frame in frames):
            raise ValueError('publisher_widget_identity_changed')
        raw, locations, closures = _styled_ical(fetch(LIBRARY_WIDGET, 'application/json'), now=now)
        return _normalize_ics(raw, key, locations=locations, closures=closures,
                              already_normalized=True)
    return _squarespace(key, fetch, now)
