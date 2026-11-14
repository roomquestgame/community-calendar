"""Reviewed NYC outdoor, fitness and community calendars.

The Events Calendar REST API supplies complete publisher narratives; its HTML
list excerpts do not. Squarespace sources use permitted listing/detail HTML,
never the exports their robots policy disallows. Larger HTML calendars resume
through the existing durable snapshot contract, emitting only a complete set.
All requests go through the caller's normal robots/SSRF guarded transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_community import _google_times
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = 'America/New_York'
QBG = 'queens_botanical_garden_ny'
VCP = 'van_cortlandt_park_alliance_ny'
FORT = 'fort_tryon_park_conservancy_ny'
LES = 'municipal_mapsee_6a0963906d4579496fa3659c'
RIVERSIDE = 'municipal_mapsee_a60c8290b2e794fcd00a52da'
RANDALLS = 'municipal_mapsee_accd81805a1bc1a57d12e24b'
DYCKMAN = 'dyckman_run_club_ny'
ASTORIA = 'astoria_park_alliance_ny'
SOURCES = {
    QBG: ('https://queensbotanical.org/calendar/', 'html', 'html'),
    VCP: ('https://vancortlandt.org/calendar-of-events/', 'html', 'html'),
    FORT: ('https://forttryonpark.org/events/', 'html', 'html'),
    LES: ('https://www.lesecologycenter.org/calendar/', 'html', 'html'),
    RIVERSIDE: ('https://riversideparknyc.org/events/', 'html', 'html'),
    RANDALLS: ('https://randallsisland.org/events/', 'html', 'html'),
    DYCKMAN: ('https://dyckmanrunclub.org/events', 'html', 'html'),
    ASTORIA: ('https://www.astoriaparkalliance.org/events', 'html', 'html'),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = {DYCKMAN, ASTORIA}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
MAX_PAGES = 10
MAX_MANIFEST = 200
DETAILS_PER_CHUNK = 3
CHECKPOINT_MAX_BYTES = 900_000
ERROR_CODES = {
    'unregistered_new_york_outdoors_source', 'ny_outdoors_description_limit',
    'ny_outdoors_feed_changed', 'ny_outdoors_pagination_incomplete',
    'ny_outdoors_record_limit', 'ny_outdoors_deadline',
    'ny_outdoors_calendar_changed', 'ny_outdoors_detail_changed',
    'ny_outdoors_checkpoint_invalid', 'ny_outdoors_checkpoint_limit',
    'ny_outdoors_description_or_location_missing', 'ny_outdoors_time_unverified',
    'ny_outdoors_schedule_conflict', 'ny_outdoors_not_public_event',
}
NON_EVENT_TITLE = re.compile(
    r'\b(?:cancell?ed|postponed|closed|private event|invitation.only)\b|^On this Day:', re.I)
REMOTE = re.compile(r'\b(?:online via zoom|online conversation|virtual event|off[- ]site event)\b', re.I)


def _place(key, name, address, lat, lng, evidence, provenance, approximate=False):
    return {'source_key': key, 'venue_name': name, 'venue_address': address,
            'lat': lat, 'lng': lng, 'evidence_url': evidence,
            'provenance': provenance, 'approximate': approximate}


# Exact tuple bindings prevent a changed event venue inheriting a source's pin.
# Intersections are real park entrances, retained as streets instead of inventing
# house numbers. Approximate entrance substitutions are visible in venue names.
REVIEWED_LOCATIONS = [
    _place(QBG, 'Queens Botanical Garden', '43-50 Main Street, Flushing, NY 11355',
           40.7512393, -73.8261905, 'https://queensbotanical.org/directions/',
           'Official garden entrance address and named-garden map destination.'),
    _place(VCP, 'Woodlawn Playground (approximate meeting point)',
           'East 239th Street & Van Cortlandt Park East, Bronx, NY 10470',
           40.90114, -73.87502,
           'https://vancortlandt.org/visit/things-to-see-and-do/',
           'Organizer names Woodlawn Playground/239th Street at the east edge of the park. '
           'NYC Planning PAD exact named-playground match supplies point/ZIP; east-side street prefix '
           'corrected from the directory typo. Point is playground, not the exact handball-court meeting tree.', True),
    _place(VCP, 'VCPA Learning Garden (approximate meeting point)',
           'Broadway & Mosholu Avenue, Bronx, NY 10471',
           40.901795, -73.894148,
           'https://vancortlandt.org/event/tune-up-tuesdays-garden-volunteer-days/2026-11-24/',
           'Organizer states Broadway/Mosholu entrance and garden across from Riverdale Stables. '
           'NYC Planning PAD physical Van Cortlandt Park Stables point is a nearby garden proxy; '
           'the duplicate PAD stable point outside the park was rejected.', True),
    _place(VCP, 'Van Cortlandt Golf House (approximate meeting point)',
           'Van Cortlandt Park South & Bailey Avenue, Bronx, NY 10471',
           40.889095, -73.89235,
           'https://www.bronxartsensemble.org/event/juneteenth2023/',
           'Park-event organizer gives Golf House access via Park South/Bailey; current VCPA event '
           'meets outside Golf House. NYC Planning PAD exact named Golf House point and ZIP preserved.', True),
    _place(VCP, 'Van Cortlandt Nature Center (approximate meeting point)',
           'Broadway & West 242nd Street, Bronx, NY 10471',
           40.891109, -73.893936,
           'https://www.eventbrite.com/e/van-cortlandt-nature-group-walk-tickets-2003371280429',
           'Current organizer registration gives Broadway/242nd entrance; NYC Planning PAD exact '
           'Nature Center building point and ZIP identify the actual destination inside the park.', True),
    _place(FORT, 'Heather Garden entrance (approximate meeting point)',
           'Margaret Corbin Circle & Fort Washington Avenue, New York, NY 10040',
           40.859646, -73.934613,
           'https://forttryonpark.org/event/medieval-festival/',
           'Official Margaret Corbin Circle drop-off at 741 Fort Washington Avenue; NYC Planning PAD '
           'point for that cottage is a nearby entrance proxy for Heather Garden.', True),
    _place(RIVERSIDE, '102nd Street Field House',
           'West 102nd Street & Riverside Drive, New York, NY 10025',
           40.800764397978, -73.973292973939,
           'https://riversideparknyc.org/event/field-house-mat-pilates-3/2026-11-19/',
           'Event describes this entrance and native TEC venue coordinates locate the Field House.'),
    _place(RIVERSIDE, '95th Street Compost Compound (approximate meeting point)',
           'West 95th Street & Riverside Drive, New York, NY 10025',
           40.7958470131, -73.9775633692,
           'https://riversideparknyc.org/event/volunteer-at-the-compost-compound-3-2/2026-11-16/',
           'Street access inferred from named 95th Street compound; native venue point preserved.', True),
    _place(RIVERSIDE, 'W 125th & Marginal Streets',
           'West 125th Street & Marginal Street, New York, NY 10027',
           40.818861, -73.961139,
           'https://riversideparknyc.org/event/holiday-on-the-hudson-4/',
           'Publisher supplies the intersection and native venue coordinates.'),
    _place(RIVERSIDE, 'River Run Playground (approximate meeting point)',
           'West 83rd Street & Riverside Drive, New York, NY 10024',
           40.78706, -73.98215,
           'https://riversideparknyc.org/event/moon-lit-forest-bathing/',
           'Named playground native point; street entrance inferred from local park layout.', True),
    _place(RANDALLS, 'Urban Farm', '11 Wards Meadow Loop, New York, NY 10035',
           40.783753, -73.925686,
           'https://randallsisland.org/programs/edible-education',
           'Official Urban Farm directions address plus native TEC venue point.'),
    _place(RANDALLS, 'Icahn Stadium', '10 Central Road, New York, NY 10035',
           40.792778, -73.924666,
           'https://randallsisland.org/visit/directions',
           'Official directions explicitly identify Icahn Stadium at this address; native venue point.'),
    _place(RANDALLS, 'Icahn Stadium Classroom', '10 Central Road, New York, NY 10035',
           40.792778, -73.924666,
           'https://randallsisland.org/visit/directions',
           'Event names classroom inside the stadium; official stadium address and native venue point.'),
    _place(DYCKMAN, 'Bronx Legends Boxing Academy', '1761 Walton Avenue, Bronx, NY 10453',
           40.8475541, -73.9104948, SOURCES[DYCKMAN][0],
           'Publisher event visible address, Google Calendar export, map link and own-event OG point agree.'),
    _place(DYCKMAN, 'Quisqueya Plaza', '247 Dyckman Street, New York, NY 10034',
           40.86530214917616, -73.92849124097778, SOURCES[DYCKMAN][0],
           'Organizer calendar states 247 Dyckman Street as Quisqueya Plaza meetup; named venue point.'),
    _place(ASTORIA, 'Astoria Park Field House (approximate meeting point)',
           'Hoyt Avenue North & 19th Street, Astoria, NY 11102',
           40.77757, -73.92287,
           'https://www.astoriaparkalliance.org/explore-astoria-park',
           'Alliance confirms street entrance; NYRR official Astoria Park track/comfort-station meeting point '
           '(https://prod.nyrr.org/races-and-events/2026/astoria-park) is a nearby proxy for the Field House.', True),
    _place(LES, 'Grand & Clinton', 'Grand Street & Clinton Street, New York, NY 10002',
           40.715881, -73.986773, SOURCES[LES][0],
           'Feed names both streets and publishes venue-specific coordinates.'),
    _place(LES, 'East Broadway', 'East Broadway & Rutgers Street, New York, NY 10002',
           40.7140636, -73.9901951, SOURCES[LES][0],
           'Native street intersection and venue coordinates; narrative locates drop-off inside Straus Square.'),
    _place(LES, 'Tompkins Square Greenmarket Compost Drop-off',
           'East 7th Street between Avenue A & Avenue B, New York, NY 10009',
           40.7275043, -73.9800645, SOURCES[LES][0],
           'Feed gives street segment, north-side directions and named venue coordinates.'),
    _place(LES, 'Tompkins Square Park Avenue A b/w 9th & 10th Sts',
           'Avenue A between East 9th Street & East 10th Street, New York, NY 10009',
           40.7264295, -73.9817841, SOURCES[LES][0],
           'Native street segment and park-specific coordinates; exact collection position is publisher-directed.'),
    _place(LES, 'Union Square Greenmarket (approximate meeting point)',
           'East 17th Street & Union Square East, New York, NY 10003',
           40.736394, -73.989271, SOURCES[LES][0],
           'Narrative locates grey barrels at eastern edge of Greenmarket; nearest street access inferred; '
           'native Greenmarket point retained.', True),
    _place(LES, 'Harlem Valley Garden', '197 West 134th Street, New York, NY 10030',
           40.81461, -73.94355,
           'https://www.lesecologycenter.org/calendar/central-harlem-street-tree-care-part-3-with-harlem-valley-community-garden/',
           'Publisher event street resolved to exact normalized street/number in NYC Planning PAD 26c.'),
    _place(LES, 'The Arts Center at Governors Island', '110 Andes Rd, New York, NY 10004',
           40.692764, -74.016335, SOURCES[LES][0],
           'Native event street resolved to exact normalized street/number in NYC Planning PAD 26c.'),
    _place(RIVERSIDE, 'Riverbank (Camel) Playground', '675 Riverside Dr, New York, NY 10031',
           40.82576, -73.95391, SOURCES[RIVERSIDE][0],
           'Native playground street resolved to exact normalized street/number in NYC Planning PAD 26c.'),
]
REVIEWED_INTERSECTIONS = [p for p in REVIEWED_LOCATIONS if '&' in p['venue_address']]
_LOCATIONS = {(p['source_key'], p['venue_name'], p['venue_address']): p for p in REVIEWED_LOCATIONS}


def reviewed_venue_location(key, venue, address):
    point = _LOCATIONS.get((key, venue, address))
    return {'lat': point['lat'], 'lng': point['lng']} if point else None


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        prefix = '/calendar/' if key == LES else ('/events/' if key in {RANDALLS, DYCKMAN, ASTORIA} else '/event/')
        return bool(p.scheme == 'https' and p.hostname in ALLOWED_HOSTS[key]
                    and p.port in (None, 443) and not (p.username or p.password or p.query or p.fragment)
                    and p.path.startswith(prefix) and len(p.path) > len(prefix)
                    and len(p.path) <= 700 and re.fullmatch(r'[A-Za-z0-9/_%-]+', p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or key not in SOURCES:
        return False
    try:
        p = urlsplit(value)
        hosts = set(ALLOWED_HOSTS[key])
        if key in CHECKPOINT_KEYS:
            hosts |= {'images.squarespace-cdn.com', 'static1.squarespace.com'}
        return bool(p.scheme == 'https' and p.hostname in hosts and p.port in (None, 443)
                    and not (p.username or p.password or p.fragment)
                    and (p.path.startswith('/wp-content/uploads/')
                         or (key in CHECKPOINT_KEYS and p.path.startswith('/content/'))))
    except ValueError:
        return False


def _full_description(value):
    if not isinstance(value, str):
        return ''
    text = description(value, limit=max(len(value), MAX_DESCRIPTION + 1))
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('ny_outdoors_description_limit')
    return text


def _hold(key, identity, reason, diagnostics=None):
    log.warning('new_york_outdoors_record_held source=%s id=%s reason=%s', key, identity, reason)
    if diagnostics is not None:
        diagnostics.append({'id': str(identity), 'reason': reason})


def _budget(deadline_at, reserve=8):
    if deadline_at is not None and monotonic() + reserve >= deadline_at:
        raise ValueError('ny_outdoors_deadline')


def _point(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
        if math.isfinite(lat) and math.isfinite(lng) and 40.48 <= lat <= 40.94 and -74.27 <= lng <= -73.68:
            return lat, lng
    except (ValueError, TypeError):
        pass
    return None


def _named(key, name):
    return next((p for p in REVIEWED_LOCATIONS if p['source_key'] == key and p['venue_name'] == name), None)


def _native_location(key, venue):
    if not isinstance(venue, dict):
        return None
    name, street = plain(venue.get('venue')), plain(venue.get('address'))
    city = plain(venue.get('city')).title()
    if city == 'New York City':
        city = 'New York'
    postal = str(venue.get('zip') or '').strip()
    state = plain(venue.get('state') or venue.get('province'))
    if state not in {'', 'NY', 'New York'}:
        return None
    if city not in {'New York', 'Brooklyn', 'Bronx', 'Staten Island', 'Queens', 'Astoria',
                    'Flushing', 'Bayside', 'Jamaica', 'Glen Oaks', 'Fresh Meadows'}:
        return None
    if not re.fullmatch(r'\d{5}(?:-\d{4})?', postal):
        return None
    # One native Queens venue has reversed street/number components.
    if name == 'Crocheron Park' and street == '34th Avenue 214-41':
        street = '214-41 34th Avenue'
    if name == 'Cunningham Park' and street == 'Union Turnpike 19600':
        street = '196-00 Union Turnpike'
    if name == 'Queens County Farm Museum' and street == '73-50 Little Neck Pkwy, Glen Oaks, NY':
        street = '73-50 Little Neck Parkway'
    if not name or not re.match(r'^\d{1,6}(?:-\d{1,6})?\s+\S', street):
        return None
    point = _point(venue.get('geo_lat'), venue.get('geo_lng'))
    address = f'{street}, {city}, NY {postal}'
    if point is None:
        reviewed = _LOCATIONS.get((key, name, address))
        if reviewed:
            return reviewed
    return _place(key, name, f'{street}, {city}, NY {postal}',
                  *(point or (None, None)), SOURCES[key][0], 'Native publisher venue street and coordinates.')


def _location(key, event, text, start):
    title = plain(event.get('title'))
    v = event.get('venue') or {}
    v = v if isinstance(v, dict) else {}
    name = plain(v.get('venue'))
    native = _native_location(key, v)
    if native:
        return native
    if key == QBG:
        # Onsite series reviewed against current full narratives. New titles or
        # explicitly offsite metadata are held for venue review.
        if (not name and not REMOTE.search(text)
                and re.match(r'^(?:AnkhLave Indigenous Mural|Math in Bloom:|Compost (?:Beautification|Build|Site Tour)|'
                             r'Farm (?:Community Volunteer Days|Stand|Open Hours|Cooking Workshop)|'
                             r'Rain Garden Stewardship|Winter Wonder)', title)):
            return _named(key, 'Queens Botanical Garden')
    elif key == VCP:
        for marker, place in (
            ('Woodlawn Playground', 'Woodlawn Playground (approximate meeting point)'),
            ('VCPA Learning Garden', 'VCPA Learning Garden (approximate meeting point)'),
            ('Golf House', 'Van Cortlandt Golf House (approximate meeting point)'),
            ('meet in front of the Nature Center', 'Van Cortlandt Nature Center (approximate meeting point)'),
        ):
            if marker.casefold() in text.casefold():
                return _named(key, place)
    elif key == FORT:
        if ('heather garden entrance' in text.casefold()
                or 'heather garden’s margaret corbin circle entrance' in text.casefold()):
            return _named(key, 'Heather Garden entrance (approximate meeting point)')
        if 'Broadway Greeting Garden at the Arden Street/Broadway entrance' in text:
            return _named(key, 'Broadway Greeting Garden (approximate meeting point)')
        if 'Meeting Location: Broadway/Bennett Entrance' in text:
            return _named(key, 'Broadway/Bennett entrance (approximate meeting point)')
        if 'Café Lawn' in text:
            return _named(key, 'Café Lawn (approximate meeting point)')
    elif key == RIVERSIDE:
        names = {'102nd Street Field House': '102nd Street Field House',
                 '95th Street Compost Compound': '95th Street Compost Compound (approximate meeting point)',
                 'W 125th & Marginal Streets': 'W 125th & Marginal Streets',
                 'River Run Playground': 'River Run Playground (approximate meeting point)'}
        if name in names:
            return _named(key, names[name])
    elif key == RANDALLS:
        if name == 'Urban Farm' and 'Urban Farm' in text:
            return _named(key, name)
        if name == 'Icahn Stadium' and 'Icahn Stadium' in text:
            return _named(key, 'Icahn Stadium Classroom' if 'Icahn Stadium Classroom' in text else name)
    elif key == LES:
        names = {'Grand & Clinton': 'Grand & Clinton', 'East Broadway': 'East Broadway',
                 'Tompkins Square Greenmarket Compost Drop-off': 'Tompkins Square Greenmarket Compost Drop-off',
                 'Tompkins Square Park Avenue A b/w 9th & 10th Sts': 'Tompkins Square Park Avenue A b/w 9th & 10th Sts',
                 'Union Square Greenmarket': 'Union Square Greenmarket (approximate meeting point)'}
        if name in names:
            return _named(key, names[name])
        if name == 'Delancey Street Bridge' and '540 Delancy St' in text:
            point = _point(v.get('geo_lat'), v.get('geo_lng'))
            return _place(key, name, '540 Delancey Street, New York, NY 10002',
                          *(point or (None, None)), event['url'],
                          'Full event narrative supplies 540 Delancy St; normalize street spelling; native bridge point.')
    return None


def _randalls_clocks(payload):
    """Visible NYC clocks corroborate the reviewed correction of UTC+0 export metadata."""
    soup = BeautifulSoup(payload, 'html.parser')
    out = {}
    for card in soup.select('.tribe-events-calendar-list__event-header'):
        anchor = card.select_one('.tribe-events-calendar-list__event-title-link[href]')
        stamp = card.select_one('time[datetime]')
        if not anchor or not stamp:
            continue
        times = re.findall(r'\b(\d{1,2}:\d{2})\s*(am|pm)\b', stamp.get_text(' ', strip=True), re.I)
        if len(times) != 2 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp['datetime']):
            continue
        values = [datetime.strptime(f'{t} {suffix}', '%I:%M %p').strftime('%H:%M:%S') for t, suffix in times]
        out[anchor['href']] = (stamp['datetime'], *values)
    return out


def _make_row(key, event, now, diagnostics, clocks=None):
    identity = str(event.get('id') or '')
    title, link = plain(event.get('title')), event.get('url')
    if not identity or not title or not event_url(key, link):
        raise ValueError('ny_outdoors_feed_changed')
    if (NON_EVENT_TITLE.search(title) or event.get('all_day') or event.get('status') in {'cancelled', 'canceled', 'postponed'}):
        _hold(key, identity, 'ny_outdoors_not_public_event', diagnostics)
        return None
    text = _full_description(event.get('description'))
    if not text or REMOTE.search(text):
        _hold(key, identity, 'ny_outdoors_description_or_location_missing', diagnostics)
        return None
    tz = event.get('timezone')
    if key == RANDALLS and tz == 'UTC+0':
        start_raw, end_raw = str(event.get('start_date') or ''), str(event.get('end_date') or '')
        visible = (clocks or {}).get(link)
        if (visible is None or start_raw != f'{visible[0]} {visible[1]}'
                or end_raw != f'{visible[0]} {visible[2]}'):
            _hold(key, identity, 'ny_outdoors_time_unverified', diagnostics)
            return None
        tz = ZONE
    if tz != ZONE:
        _hold(key, identity, 'ny_outdoors_time_unverified', diagnostics)
        return None
    start = timestamp(event.get('start_date'), tz)
    end = timestamp(event.get('end_date'), tz)
    if start is None or (end is not None and end <= start):
        _hold(key, identity, 'ny_outdoors_time_unverified', diagnostics)
        return None
    if start >= now + timedelta(days=60) or (end or start + timedelta(hours=3)) <= now:
        return None
    # Publisher-specific contradictions found in the current calendar. Keep
    # truthful full narrative rather than taking the header or body on faith.
    if ((key == FORT and title == 'Dog Run Santa Paws Photoshoot' and '11 AM to 2 PM' in text
         and start.astimezone(ZoneInfo(ZONE)).hour != 11)
            or (key == FORT and title == 'Broadway Beautification'
                and 'March to November' in text and start.astimezone(ZoneInfo(ZONE)).month not in range(3, 12))
            or (key == VCP and '3.5 hour walk' in text and end and end - start != timedelta(hours=3.5))):
        _hold(key, identity, 'ny_outdoors_schedule_conflict', diagnostics)
        return None
    place = _location(key, event, text, start)
    if place is None:
        _hold(key, identity, 'ny_outdoors_description_or_location_missing', diagnostics)
        return None
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 place['venue_name'], place['venue_address'], place['venue_address'].split(', ')[-2],
                 link, identity,
                 category=', '.join(plain(c.get('name')) for c in event.get('categories', []) if isinstance(c, dict)),
                 lat=place['lat'], lng=place['lng'], tz=ZONE,
                 publisher_geo=True, retain_until_end=True)
    if row:
        row['description'] = text
        row['timezone'] = ZONE
        row['location_provenance'] = place['provenance']
        row['location_evidence_url'] = place['evidence_url']
        candidate = event.get('image')
        if isinstance(candidate, dict) and photo_url(key, candidate.get('url')):
            row['image_url'] = candidate['url']
    return row


def _tribe(key, fetch, now, deadline_at=None):
    base = 'https://' + ALLOWED_HOSTS[key][0] + '/wp-json/tribe/events/v1/events'
    local_day = now.astimezone(ZoneInfo(ZONE)).date()
    query = {'start_date': local_day.isoformat(), 'end_date': (local_day + timedelta(days=60)).isoformat(),
             'per_page': 100, 'page': 1}
    events, seen, total, pages = [], set(), None, None
    for page in range(1, MAX_PAGES + 1):
        _budget(deadline_at)
        query['page'] = page
        data = json.loads(fetch(base + '?' + urlencode(query), 'application/json'))
        if not isinstance(data, dict) or not isinstance(data.get('events'), list):
            raise ValueError('ny_outdoors_feed_changed')
        if type(data.get('total')) is not int or type(data.get('total_pages')) is not int:
            raise ValueError('ny_outdoors_feed_changed')
        if total is None:
            total, pages = data['total'], data['total_pages']
            if not 0 <= total <= MAX_RECORDS or not 0 <= pages <= MAX_PAGES:
                raise ValueError('ny_outdoors_record_limit')
        if data['total'] != total or data['total_pages'] != pages:
            raise ValueError('ny_outdoors_pagination_incomplete')
        for event in data['events']:
            if not isinstance(event, dict) or not event.get('id') or event['id'] in seen:
                raise ValueError('ny_outdoors_pagination_incomplete')
            seen.add(event['id'])
            events.append(event)
        if page >= pages:
            break
    if len(events) != total:
        raise ValueError('ny_outdoors_pagination_incomplete')
    clocks = None
    if key == RANDALLS and any(e.get('timezone') == 'UTC+0' for e in events):
        _budget(deadline_at)
        clocks = _randalls_clocks(fetch(SOURCES[key][0], 'text/html'))
    out, diagnostics, fingerprints = [], [], set()
    for event in events:
        row = _make_row(key, event, now, diagnostics, clocks)
        if row:
            fp = (row['title'], row['starts_at'], row['venue_name'], row['venue_address'])
            if fp not in fingerprints:
                out.append(row)
                fingerprints.add(fp)
    return out, diagnostics


def _manifest(key, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if soup.select_one('.eventlist') is None:
        raise ValueError('ny_outdoors_calendar_changed')
    out = []
    for card in soup.select('article.eventlist-event--upcoming'):
        anchor = card.select_one('.eventlist-title-link[href]')
        if anchor is None:
            raise ValueError('ny_outdoors_calendar_changed')
        link = urljoin(SOURCES[key][0], anchor['href'])
        if not event_url(key, link):
            raise ValueError('ny_outdoors_calendar_changed')
        start, end, facts = _google_times(card)
        if start is None or start >= now + timedelta(days=60) or (end or start + timedelta(hours=3)) <= now:
            continue
        title = plain(anchor.get_text())
        if plain((facts.get('text') or [''])[0]).casefold() != title.casefold():
            raise ValueError('ny_outdoors_calendar_changed')
        excerpt = card.select_one('.eventlist-excerpt')
        out.append({'url': link, 'title': title, 'start': start.isoformat(),
                    'end': end.isoformat() if end else None,
                    'location': plain((facts.get('location') or [''])[0]),
                    'excerpt_hash': sha256(_full_description(str(excerpt or '')).encode()).hexdigest()})
    if len(out) > MAX_MANIFEST or len({c['url'] for c in out}) != len(out):
        raise ValueError('ny_outdoors_record_limit')
    return out


def _squarespace_detail(key, card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('.eventitem')
    title_node = main.select_one('.eventitem-title') if main else None
    body = main.select_one('.eventitem-column-content .sqs-layout') if main else None
    canonicals = soup.select('meta[property="og:url"]')
    canonical = canonicals[0].get('content') if len(canonicals) == 1 else None
    # This publisher's HTTPS page still prints its historical HTTP canonical.
    # Compare the exact reviewed host/path, without requesting any HTTP URL.
    if key == ASTORIA and isinstance(canonical, str) and canonical.startswith('http://www.astoriaparkalliance.org/'):
        canonical = 'https://' + canonical[len('http://'):]
    if (title_node is None or body is None or len(canonicals) != 1
            or canonical != card['url']):
        raise ValueError('ny_outdoors_detail_changed')
    title = plain(title_node.get_text())
    start, end, facts = _google_times(main)
    if (title.casefold() != card['title'].casefold() or start is None
            or start.isoformat() != card['start'] or (end.isoformat() if end else None) != card['end']
            or plain((facts.get('text') or [''])[0]).casefold() != title.casefold()
            or plain((facts.get('location') or [''])[0]) != card['location']):
        raise ValueError('ny_outdoors_detail_changed')
    text = _full_description(str(body))
    address = main.select_one('.eventitem-meta-address-line--title')
    venue = plain(address.get_text()) if address else ''
    if (NON_EVENT_TITLE.search(title) or title.casefold() in {'happy thanksgiving'}
            or re.search(r'\b(?:members.only|membership for full access)\b', text, re.I)):
        _hold(key, card['url'], 'ny_outdoors_not_public_event', diagnostics)
        return None
    place = None
    if key == DYCKMAN:
        if title.casefold() == 'drc medal party' and 'free public run' in text.casefold():
            _hold(key, card['url'], 'ny_outdoors_schedule_conflict', diagnostics)
            return None
        if (venue == 'Bronx Legends Boxing Academy' and '1761 Walton Avenue' in card['location']
                and '10453' in card['location']):
            place = _named(key, venue)
        elif (venue == 'Quisqueya Plaza' and title.casefold() == 'cardio thursdays'
              and 'free public run' in text.casefold()):
            place = _named(key, venue)
    elif (key == ASTORIA and venue == 'Astoria Park' and 'Field House near the Astoria Park track' in text):
        place = _named(key, 'Astoria Park Field House (approximate meeting point)')
    if not text or place is None:
        _hold(key, card['url'], 'ny_outdoors_description_or_location_missing', diagnostics)
        return None
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 place['venue_name'], place['venue_address'], place['venue_address'].split(', ')[-2],
                 card['url'], sha256(urlsplit(card['url']).path.encode()).hexdigest(),
                 category=', '.join(plain(a.get_text()) for a in main.select(
                     '.eventitem-meta-cats a, .eventitem-meta-tags a, a.eventitem-meta-category')),
                 lat=place['lat'], lng=place['lng'], tz=ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=text, timezone=ZONE, location_provenance=place['provenance'],
                   location_evidence_url=place['evidence_url'])
        candidate = body.select_one('img[data-src], img[src]')
        image = candidate.get('data-src') or candidate.get('src') if candidate else None
        if photo_url(key, image):
            row['image_url'] = image
    return row


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
                             source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('unregistered_new_york_outdoors_source')
    return key


def _checkpoint_rows_valid(key, state, manifest):
    """Only the already visited manifest prefix can supply persisted output."""
    prefix = {c['url']: c for c in manifest[:state['cursor']]}
    seen = set()
    for row in state['events']:
        if not isinstance(row, dict):
            return False
        url = row.get('event_url')
        card = prefix.get(url)
        place = _LOCATIONS.get((key, row.get('venue_name'), row.get('venue_address')))
        if (card is None or url in seen or place is None
                or row.get('id') != sha256(urlsplit(url).path.encode()).hexdigest()
                or plain(row.get('title')).casefold() != card['title'].casefold()
                or row.get('starts_at') != card['start'] or row.get('ends_at') != card['end']
                or row.get('timezone') != ZONE or row.get('lat') != place['lat'] or row.get('lng') != place['lng']
                or not isinstance(row.get('description'), str) or not row['description'].strip()
                or len(row['description']) > MAX_DESCRIPTION):
            return False
        seen.add(url)
    return True


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)
    if key not in CHECKPOINT_KEYS:
        raise ValueError('unregistered_new_york_outdoors_source')
    _budget(deadline_at)
    manifest = _manifest(key, fetch(SOURCES[key][0], 'text/html'), now)
    digest = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    state = deepcopy(checkpoint) if checkpoint else None
    if state is not None:
        try:
            valid = (state['version'] == 1 and state['source_key'] == key
                     and type(state['cursor']) is int and 0 <= state['cursor'] <= len(manifest)
                     and isinstance(state['events'], list) and len(state['events']) <= state['cursor']
                     and isinstance(state['diagnostics'], list)
                     and len(state['diagnostics']) <= MAX_MANIFEST
                     and now - datetime.fromisoformat(state['started_at']) <= timedelta(hours=4)
                     and datetime.fromisoformat(state['started_at']) <= now
                     and all(isinstance(e, dict) and event_url(key, e.get('event_url')) for e in state['events']))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError('ny_outdoors_checkpoint_invalid')
        if state.get('manifest_hash') != digest or state.get('manifest_count') != len(manifest):
            state = None
        elif not _checkpoint_rows_valid(key, state, manifest):
            raise ValueError('ny_outdoors_checkpoint_invalid')
    if state is None:
        state = {'version': 1, 'source_key': key, 'started_at': now.isoformat(),
                 'window_start': now.isoformat(), 'manifest_hash': digest,
                 'manifest_count': len(manifest), 'cursor': 0, 'events': [], 'diagnostics': []}
    stop = min(len(manifest), state['cursor'] + DETAILS_PER_CHUNK)
    for index in range(state['cursor'], stop):
        if deadline_at is not None and monotonic() + 18 >= deadline_at:
            break
        card = manifest[index]
        row = _squarespace_detail(key, card, fetch(card['url'], 'text/html'), now, state['diagnostics'])
        if row:
            state['events'].append(row)
        state['cursor'] = index + 1
    if len(json.dumps(state).encode()) > CHECKPOINT_MAX_BYTES:
        raise ValueError('ny_outdoors_checkpoint_limit')
    complete = state['cursor'] == len(manifest)
    return {'complete': complete, 'events': state['events'] if complete else [],
            'checkpoint': None if complete else state, 'diagnostics': state['diagnostics']}


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)
    if key not in CHECKPOINT_KEYS:
        return _tribe(key, fetch, now, deadline_at)[0]
    checkpoint = None
    for _ in range((MAX_MANIFEST + DETAILS_PER_CHUNK - 1) // DETAILS_PER_CHUNK + 1):
        part = collect_chunk(source, fetch, checkpoint=checkpoint, deadline_at=deadline_at, now=now)
        if part['complete']:
            return part['events']
        if checkpoint and part['checkpoint']['cursor'] == checkpoint['cursor']:
            raise ValueError('ny_outdoors_deadline')
        checkpoint = part['checkpoint']
    raise ValueError('ny_outdoors_record_limit')
