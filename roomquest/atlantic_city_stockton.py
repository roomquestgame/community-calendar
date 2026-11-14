"""Stockton's public performances and community learning calendars.

The PAC's own HTML is the authoritative performance manifest. Its independently
published 25Live iCalendar export supplies complete additional event narratives
and named rooms. No requests go to the ticket site's robots-disallowed pages.
Department calendars expose complete HTML bodies in their dated event cards.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.atlantic_city_community import MAX_DESCRIPTION, _full_description, _nj_address
from roomquest.mapsee_adapter import plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = 'America/New_York'
PAC = 'stockton_performing_arts_nj'
HRC = 'stockton_holocaust_resource_nj'
SCOSA = 'stockton_center_successful_aging_nj'
SOURCES = {
    PAC: ('https://stockton.edu/pac/events-list.html', 'html', 'html'),
    HRC: ('https://stockton.edu/holocaust-resource/events/index.html', 'html', 'html'),
    SCOSA: ('https://www.stockton.edu/aging/events-workshops.html', 'html', 'html'),
}
PAC_ICAL = 'https://25livepub.collegenet.com/calendars/all-university-events-from-25live.ics'
ALLOWED_HOSTS = {
    PAC: ('stockton.edu', '25livepub.collegenet.com'),
    HRC: ('stockton.edu',),
    SCOSA: ('www.stockton.edu',),
}
MAX_CARDS = 500
MAX_ICAL = 199  # The export silently caps at 200: a capped result is not complete.
MAIN_STREET = '101 Vera King Farris Drive, Galloway, NJ 08205'
AC_STREET = '3711 Atlantic Avenue, Atlantic City, NJ 08401'
MAIN_VENUE = 'Stockton Performing Arts Center'
EXPERIMENTAL_VENUE = 'Stockton University Experimental Theatre'
GALLOWAY_CAMPUS = 'Stockton University — Galloway Campus'
# The venue's technical specifications explicitly identify these as its exact
# building GPS coordinates (load-in location, not a campus/map camera center).
# https://stockton.edu/pac/technical-specs.html
PAC_BUILDING_POINT = (39.4914722222, -74.5336388889)
# Exact destination placemark from Stockton's own public map. Its description
# explicitly identifies the Galloway campus; use only for a campus-level venue,
# never for L-112, the PAC, or an unverified room within the campus.
# https://stockton.edu/maps/index.html
# https://www.google.com/maps/d/kml?mid=1iZnWa0V3cETgS55Q6BmEHgXVHIU&forcekml=1
REVIEWED_VENUE_POINTS = {
    (PAC, GALLOWAY_CAMPUS, MAIN_STREET): (39.491192, -74.534683),
}
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|private event|invitation[- ]only|staff[- ]only|members[- ]only)\b', re.I)
MONTHS = {name.lower(): index for index, name in enumerate(
    ('January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'), 1)}
MONTH_PATTERN = '(?:' + '|'.join(MONTHS) + ')'
PAC_DATE = re.compile(
    r'(?P<month>' + MONTH_PATTERN + r')\s+(?P<day>\d{1,2})'
    r'(?:\s*[-–]\s*(?:(?P<end_month>' + MONTH_PATTERN + r')\s+)?(?P<end_day>\d{1,2}))?'
    r'(?:,\s*(?P<year>20\d{2}))?\s*@\s*', re.I)
CLOCK = re.compile(r'\b(\d{1,2})(?::([0-5]\d))?\s*([ap])m\b', re.I)

# Exact current program aliases, matched to the actual local date and public/
# educational program variant. New names can match exactly, but never through
# lossy substring matching that merges student and public performances.
PAC_ALIASES = {
    ('veteransdayconcert', False): {'freeveteransdayconcertbayatlanticsymphony'},
    ('amoreperfectunion', True): {'amoreperfectunionbypushcartplayers'},
    ('mikegoodwin', False): {'mikegoodwinthecomedyzone'},
    ('thenutcracker', False): {'thenutcrackerbyatlanticcityballetpublicperformance'},
    ('thenutcracker', True): {'thenutcrackereducationalperformancebyatlanticcityballet'},
    ('holidaycheer', False): {'holidaycheerbayatlanticsymphony'},
}
MAIN_ROOMS = {
    'Performing Arts Center, Main Theater, Performing Arts Center Green Room, M-Wing PAC Lower Lobby',
    'Performing Arts Center, Main Theater',
}
EXPERIMENTAL_ROOMS = {'Performing Arts Center Experimental Theater'}
PAC_ORGANIZATIONS = {
    'PERFORMING ARTS CENTER',
    'PERFORMING ARTS CENTER, ARTS & HUMANITIES, SCHOOL OF',
}

# These two public productions are missing from the PAC's native 25Live export.
# The Figuring's room is independently confirmed on the university's own page:
# https://stockton.edu/news/2026/the-figuring.html
# Charlie Brown's current PAC card verifies a university production but does
# not name a room; the verified Galloway campus address is retained without
# assigning the previous season's room or the PAC building's GPS point. Its
# destination is the official campus-level placemark, which matches its venue.
# Both use the official venue navigation address, not its administrative suite:
# https://stockton.edu/pac/directions-parking.html
REVIEWED_CARD_VENUES = {
    ('1853', 'thefiguring'): EXPERIMENTAL_VENUE,
    ('1859', 'acharliebrownchristmas'): GALLOWAY_CAMPUS,
}


def _key(value):
    return re.sub(r'[^a-z0-9]', '', plain(value).casefold())


def event_url(source_key, value):
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
                or p.fragment):
            return False
    except ValueError:
        return False
    if source_key == PAC:
        return (p.netloc == 'stockton.universitytickets.com' and p.path == '/w/event.aspx'
                and bool(re.fullmatch(r'id=[1-9][0-9]{0,8}', p.query)))
    return source_key in SOURCES and value == SOURCES[source_key][0]


def _hold(source_key, identity, reason):
    log.warning('stockton_record_held source=%s id=%s reason=%s', source_key, identity, reason)


def _time_text(value):
    return re.sub(r'\b([ap])\s*\.?\s*m\.?', r'\1m', plain(value), flags=re.I)


def _wall(day, hour, minute, meridiem):
    hour, minute = int(hour), int(minute or 0)
    if not 1 <= hour <= 12 or not 0 <= minute < 60:
        raise ValueError('stockton_event_time_changed')
    hour = hour % 12 + (12 if meridiem.lower() == 'p' else 0)
    return timestamp(datetime.combine(day, datetime.min.time()).replace(
        hour=hour, minute=minute).isoformat(), ZONE)


def _month_years(cards):
    result = {}
    for card in cards:
        line = card.select_one('.event-line1')
        for match in PAC_DATE.finditer(_time_text(str(line or ''))):
            if match['year']:
                for month in (match['month'], match['end_month']):
                    if month:
                        result.setdefault(month.lower(), set()).add(int(match['year']))
    return result


def _pac_starts(value, month_years):
    text = _time_text(value)
    matches = list(PAC_DATE.finditer(text))
    if not matches:
        raise ValueError('stockton_event_time_changed')
    result = []
    for index, match in enumerate(matches):
        years = {int(match['year'])} if match['year'] else month_years.get(match['month'].lower(), set())
        if len(years) != 1:
            raise ValueError('stockton_event_year_unresolved')
        year = next(iter(years))
        first = date(year, MONTHS[match['month'].lower()], int(match['day']))
        last = date(year, MONTHS[(match['end_month'] or match['month']).lower()],
                    int(match['end_day'] or match['day']))
        if not 0 <= (last - first).days <= 6:
            raise ValueError('stockton_event_time_changed')
        tail = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else None]
        clocks = list(CLOCK.finditer(tail))
        if not 1 <= len(clocks) <= 4:
            raise ValueError('stockton_event_time_changed')
        remainder = CLOCK.sub('', tail)
        remainder = re.sub(r'\b(?:and|sun(?:day)?|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?)\b', '', remainder, flags=re.I)
        if re.sub(r'[\s&|,–-]', '', remainder):
            raise ValueError('stockton_event_time_changed')
        for offset in range((last - first).days + 1):
            for clock in clocks:
                result.append(_wall(first + timedelta(days=offset), *clock.groups()))
    if len(result) != len(set(result)):
        raise ValueError('stockton_event_time_changed')
    return sorted(result)


def _card_times(node):
    day = datetime.strptime(node.get('data-day', ''), '%m/%d/%Y').date()
    text = _time_text(node.get_text(' ', strip=True))
    if text.count('|') != 1:
        raise ValueError('stockton_event_time_changed')
    value = text.split('|')[1].strip()
    match = re.fullmatch(r'(\d{1,2})(?::([0-5]\d))?\s*([ap])?m?'
                         r'(?:\s*[-–]\s*(\d{1,2})(?::([0-5]\d))?\s*([ap])m)?', value, re.I)
    if not match or not (match[3] or match[6]):
        raise ValueError('stockton_event_time_changed')
    start = _wall(day, match[1], match[2], match[3] or match[6])
    end = _wall(day, match[4], match[5], match[6]) if match[4] else None
    if end is not None and end <= start:
        raise ValueError('stockton_event_time_changed')
    return start, end


def _native_performances(payload):
    calendar = Calendar.from_ical(payload)
    events = calendar.walk('VEVENT')
    if len(events) > MAX_ICAL:
        raise ValueError('stockton_calendar_result_limit')
    result, duplicate_keys = [], {}
    for item in events:
        fields = item.get('X-TRUMBA-CUSTOMFIELD', [])
        if not isinstance(fields, list):
            fields = [fields]
        metadata = {str(field.params.get('NAME')): plain(str(field)) for field in fields}
        if (metadata.get('Event Type') != 'Performance'
                or metadata.get('Organization') not in PAC_ORGANIZATIONS):
            continue
        start = getattr(item.get('DTSTART'), 'dt', None)
        end = getattr(item.get('DTEND'), 'dt', None)
        if (not isinstance(start, datetime) or start.tzinfo is None
                or not isinstance(end, datetime) or end.tzinfo is None or end <= start
                or str(item.get('DTSTART').params.get('TZID')) != ZONE):
            raise ValueError('stockton_event_time_changed')
        title, location = plain(str(item.get('SUMMARY', ''))), plain(str(item.get('LOCATION', '')))
        raw = str(item.get('DESCRIPTION', ''))
        duplicate_key = (metadata.get('Event Locator'), title, start.isoformat(), location)
        signature = (raw, end.isoformat())
        if duplicate_key in duplicate_keys:
            if duplicate_keys[duplicate_key] != signature:
                raise ValueError('stockton_calendar_duplicate_conflict')
            continue
        duplicate_keys[duplicate_key] = signature
        soup = BeautifulSoup(raw, 'html.parser')
        # These nodes are a copied booking header (title/category/first-show
        # time), not event prose. Keep all remaining paragraphs, eligibility,
        # accessibility, and other event details without shortening them.
        for node in soup.select('#LiteralEventName, #ctl00_cphMainContent_divborderwrap'):
            node.decompose()
        narrative = _full_description(str(soup))
        result.append({'title': title, 'key': _key(title), 'start': start,
                       'end': end, 'location': location, 'description': narrative})
    return result


def _native_matches(title, subtitle, start, native):
    educational = 'student matinee' in subtitle.casefold()
    core = _key(title)
    names = PAC_ALIASES.get((core, educational), {core})
    local_day = start.astimezone(ZoneInfo(ZONE)).date()
    matches = [row for row in native if row['key'] in names
               and row['start'].astimezone(ZoneInfo(ZONE)).date() == local_day]
    exact = [row for row in matches if row['start'] == start]
    chosen = exact or matches
    if len({(row['description'], row['location']) for row in chosen}) > 1:
        raise ValueError('stockton_calendar_program_ambiguous')
    return chosen[0] if chosen else None, bool(exact)


def _pac(payload, native_payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    cards = soup.select('.pac-event-item')
    if not 1 <= len(cards) <= MAX_CARDS:
        raise ValueError('stockton_calendar_shape_changed')
    years, native = _month_years(cards), _native_performances(native_payload)
    output = []
    for card in cards:
        title_node, date_node, body = (card.select_one(s) for s in
                                       ('.event-title', '.event-line1', '.event-description'))
        if not title_node or not date_node:
            raise ValueError('stockton_calendar_shape_changed')
        title = plain(title_node.get_text(' ', strip=True))
        subtitle_node = card.select_one('.subtitle')
        subtitle = plain(subtitle_node.get_text(' ', strip=True)) if subtitle_node else ''
        link = title_node.find_parent('a', href=True)
        url = link.get('href') if link else ''
        if not event_url(PAC, url):
            raise ValueError('stockton_event_identity_changed')
        identifier = parse_qs(urlsplit(url).query)['id'][0]
        narrative = _full_description(str(body or ''))
        if not narrative or NONPUBLIC.search(title + ' ' + subtitle + ' ' + narrative):
            _hold(PAC, url, 'description_or_public_eligibility_unavailable')
            continue
        if re.search(r'\b(?:read more|continue reading)\b', narrative, re.I) or narrative.rstrip().endswith(('...', '…')):
            _hold(PAC, url, 'publisher_body_is_excerpt')
            continue
        for start in _pac_starts(date_node.get_text(' ', strip=True), years):
            if not now <= start < now + timedelta(days=60):
                continue
            match, exact_time = _native_matches(title, subtitle, start, native)
            venue, end, full = None, None, narrative
            if match:
                if match['location'] in MAIN_ROOMS:
                    venue = MAIN_VENUE
                elif match['location'] in EXPERIMENTAL_ROOMS:
                    venue = EXPERIMENTAL_VENUE
                if exact_time:
                    end = match['end']
                extra = match['description']
                if extra:
                    # Both inputs are already normalized publisher text. A
                    # second HTML parse would erase literal angle-bracket prose
                    # decoded from entities, including admission instructions.
                    full = (extra if ' '.join(narrative.split()) in ' '.join(extra.split())
                            else narrative + '\n' + extra)
                    if len(full) > MAX_DESCRIPTION:
                        raise ValueError('publisher_description_limit')
            if venue is None:
                venue = REVIEWED_CARD_VENUES.get((identifier, _key(title)))
            if 'student matinee' in subtitle.casefold():
                if not match or not re.search(r'home[- ]school(?:ed)? (?:children|students)', match['description'], re.I):
                    _hold(PAC, url, 'family_registration_eligibility_unavailable')
                    continue
            if re.search(r'\b(?:sold out|registration (?:is )?closed)\b', full, re.I):
                _hold(PAC, url, 'publisher_registration_closed')
                continue
            if not venue:
                _hold(PAC, url, 'event_room_unresolved')
                continue
            display_title = title + (' — ' + subtitle if subtitle else '')
            identity = sha256((url + '\n' + start.isoformat()).encode()).hexdigest()
            point = (PAC_BUILDING_POINT if venue in {MAIN_VENUE, EXPERIMENTAL_VENUE}
                     else REVIEWED_VENUE_POINTS.get((PAC, venue, MAIN_STREET), (None, None)))
            row = record(display_title, start, end, venue, MAIN_STREET, 'Galloway',
                         url, identity, lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
            if row:
                row.update(description=full, timezone=ZONE)
                image = card.select_one('.events-image img[src]')
                if image:
                    candidate = urljoin(SOURCES[PAC][0], image['src'])
                    if urlsplit(candidate).netloc == 'stockton.edu':
                        row['image_url'] = candidate
                output.append(row)
    return output


def _department_location(value):
    text = re.sub(r'^Location:\s*', '', plain(value))
    if re.search(r'\b(?:virtual|online|zoom)\b', text, re.I):
        return None
    if text == 'Stockton Atlantic City Campus':
        # https://stockton.edu/maps/ identifies this exact public campus.
        return 'Stockton University Atlantic City Campus', AC_STREET, 'Atlantic City'
    parts = [part.strip() for part in text.split('|') if part.strip()]
    if not parts:
        return None
    address = _nj_address(parts[-1])
    if not address or not re.search(r'\bNJ \d{5}\b', address[0]):
        return None
    return ' — '.join(parts[:-1]) or parts[-1], address[0], address[1]


def _department(source_key, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    cards = soup.select('.cal-block-item .event-details')
    if not 1 <= len(cards) <= MAX_CARDS:
        raise ValueError('stockton_calendar_shape_changed')
    output = []
    for card in cards:
        time_node = card.select_one('.date-time[data-day]')
        if not time_node:
            raise ValueError('stockton_calendar_shape_changed')
        day = datetime.strptime(time_node['data-day'], '%m/%d/%Y').date()
        if not now.astimezone(ZoneInfo(ZONE)).date() <= day <= (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date():
            continue
        start, end = _card_times(time_node)
        if (end or start) <= now or start >= now + timedelta(days=60):
            continue
        title_node, body, location_node = (card.select_one(s) for s in
                                           ('.event-title', '.event-description', '.location'))
        if not title_node:
            raise ValueError('stockton_calendar_shape_changed')
        title = plain(title_node.get_text(' ', strip=True))
        location_text = plain(location_node.get_text(' ', strip=True)) if location_node else ''
        if source_key == SCOSA and location_text == 'Location: Stockton PAC':
            _hold(source_key, title, 'covered_by_stockton_performing_arts_nj')
            continue
        narrative = _full_description(str(body or ''))
        if not narrative:
            _hold(source_key, title, 'description_unavailable')
            continue
        subtitle = card.select_one('.subtitle')
        if subtitle:
            narrative = _full_description(str(subtitle) + '\n' + str(body or ''))
        location = _department_location(location_text)
        eligible = source_key == SCOSA or bool(re.search(r'\bopen to (?:the public|educators)\b', narrative, re.I))
        if not narrative or not location or not eligible or NONPUBLIC.search(title + ' ' + narrative):
            _hold(source_key, title, 'description_street_or_public_eligibility_unavailable')
            continue
        url = SOURCES[source_key][0]
        identity = sha256((url + '\n' + title + '\n' + start.isoformat()).encode()).hexdigest()
        row = record(title, start, end, *location, url, identity, tz=ZONE, retain_until_end=True)
        if row:
            row.update(description=narrative, timezone=ZONE)
            if location == ('Stockton University Atlantic City Campus', AC_STREET, 'Atlantic City'):
                # Exact named campus placemark from the university's public map,
                # not the map viewport or an Atlantic City coverage center:
                # https://stockton.edu/maps/index.html
                # https://www.google.com/maps/d/kml?mid=1iZnWa0V3cETgS55Q6BmEHgXVHIU&forcekml=1
                row.update(lat=39.3497122, lng=-74.4546789)
                if row.get('reason') == 'missing_verified_venue_geo':
                    row['reason'] = None
            output.append(row)
    return output


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if profile is None or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'), source.get('timezone')) != (*profile, ZONE):
        raise ValueError('unregistered_atlantic_city_stockton_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('stockton_event_time_changed')
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    payload = fetch(profile[0], 'text/html')
    if key != PAC:
        return _department(key, payload, current)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    anchor = current.astimezone(ZoneInfo(ZONE)).date()
    export = PAC_ICAL + '?' + urlencode({
        'startdate': anchor.strftime('%Y%m%d'),
        'enddate': (anchor + timedelta(days=61)).strftime('%Y%m%d'),
        'previousweeks': 0, 'search': 'PERFORMING ARTS CENTER', 'customnotes': 0,
    })
    return _pac(payload, fetch(export, 'text/calendar'), current)
