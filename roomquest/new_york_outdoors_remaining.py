"""Remaining NYC municipal and volunteer calendars with explicit coverage.

City Parks' native TEC descriptions are complete (checked against all current
detail pages); reviewed park mappings supply the street locations missing from
its borough-only venue objects. NYC Aging uses all dated physical occurrences
in a rolling 21-day query. The Parks dataset is a separately named complete
Staten Island Urban Park Rangers subset, never a replacement for the unresolved
citywide calendar. All requests use the caller's existing guarded transport.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
CITY = 'municipal_mapsee_a5f8d3546bd7cb625105dccf'
OLDER = 'municipal_mapsee_fa65937887b2c538c7ce242f'
RANGERS = 'nyc_parks_staten_island_urban_park_rangers_ny'
SOURCES = {
    CITY: ('https://cityparksfoundation.org/calendar/', 'html', 'html'),
    OLDER: ('https://data.cityofnewyork.us/Social-Services/Older-Adult-Center-OAC-Activities/fzy4-e84j', 'html', 'html'),
    RANGERS: ('https://data.cityofnewyork.us/City-Government/NYC-Parks-Public-Events-Upcoming-14-Days/w3wp-dpdi', 'html', 'html'),
}
ALLOWED_HOSTS = {
    CITY: ('cityparksfoundation.org',),
    OLDER: ('data.cityofnewyork.us',),
    RANGERS: ('data.cityofnewyork.us', 'www.nycgovparks.org'),
}
CHECKPOINT_KEYS = set()
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
MAX_PAGES = 10
OLDER_HORIZON_DAYS = 21
CITY_API = 'https://cityparksfoundation.org/wp-json/tribe/events/v1/events'
SODA_ROOT = 'https://data.cityofnewyork.us/resource/'
ERROR_CODES = {
    'unregistered_new_york_outdoors_remaining_source', 'ny_outdoors_remaining_deadline',
    'ny_outdoors_remaining_feed_changed', 'ny_outdoors_remaining_pagination_incomplete',
    'ny_outdoors_remaining_record_limit', 'ny_outdoors_remaining_description_missing',
    'ny_outdoors_remaining_description_limit', 'ny_outdoors_remaining_time_unverified',
    'ny_outdoors_remaining_location_unresolved', 'ny_outdoors_remaining_schedule_conflict',
    'ny_outdoors_remaining_not_public', 'ny_outdoors_remaining_link_unresolved',
    'ny_outdoors_remaining_cancellation_unresolved',
}
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|closed|private event|invitation.only)\b', re.I)


def _name(value):
    return plain(value).replace('’', "'").casefold()


def _city_place(park, borough, street, city, zipcode, lat, lng, identity, meeting, provenance):
    return dict(source_key=CITY, park=park, borough=borough,
                venue_name=park + ' (approximate meeting point)',
                venue_address=f'{street}, {city}, NY {zipcode}', venue_city=city,
                lat=lat, lng=lng, meeting=meeting, approximate=True,
                evidence_url='https://cityparksfoundation.org/events/' + identity + '/',
                provenance=provenance)


# All are actual named parks. No organization headquarters or city centroids.
# Points come from the NYC Planning PAD geocoder or the NYC Parks event dataset.
# Native descriptions retain the exact interior meeting directions.
CITY_PLACES = [
    _city_place('Seth Low Playground/ Bealin Square', 'Brooklyn',
        'West 12th Street & Avenue P', 'Brooklyn', '11204', 40.60818, -73.98629,
        'its-my-park-at-seth-low-playground-bealin-square-48', 'Seth Low',
        'Publisher gives West 12th between Bay Parkway/Avenue P. Named-playground PAD point; '
        'Avenue P access is an approximate entry for the interior park-house meeting.'),
    _city_place('Fort Hill Park', 'Staten Island', 'Sherman Avenue & Hendricks Avenue',
        'Staten Island', '10301', 40.640994808667, -74.081677938312,
        'its-my-park-at-fort-hill-park-7', 'Fort Hill Park',
        'Publisher street bounds plus NYC Parks native Fort Hill event point. '
        'Street access approximates the top-of-hill meeting described in full prose.'),
    _city_place('Tompkins Square Park', 'Manhattan', 'East 9th Street & Avenue A',
        'New York', '10009', 40.72645, -73.98171,
        'its-my-park-at-tompkins-square-park-28', 'Field House near the 9th St entrance',
        'Publisher names 9th Street entrance/Field House. Named-park PAD point is a '
        'park access approximation; interior Field House directions remain unchanged.'),
    _city_place('Westerleigh Park', 'Staten Island', 'Willard Avenue & Maine Avenue',
        'Staten Island', '10314', 40.61983, -74.13446,
        'its-my-park-at-westerleigh-park-39', 'Westerleigh Park',
        'Publisher lists four surrounding streets and the bandstand; named-park PAD point '
        'and a boundary intersection provide approximate street access.'),
    _city_place('Brigadier General Charles Young Playground', 'Manhattan',
        'Malcolm X Boulevard & West 144th Street', 'New York', '10037',
        40.8193277731, -73.9356595126,
        'its-my-park-at-brigadier-general-charles-young-playground-3', 'West 144th Street',
        'Publisher explicitly gives this restroom entrance; NYC Parks native volunteer '
        'event point locates the playground, with approximate restroom precision.'),
    _city_place('Corlears Hook Park', 'Manhattan', 'Jackson Street & Cherry Street',
        'New York', '10002', 40.711748, -73.979789,
        'its-my-park-at-corlears-hook-park-3', 'Corlears Hook Park',
        'Publisher supplies street bounds and a whole-park meeting. Named comfort-station '
        'PAD point is an approximate gathering location inside the correct park.'),
    _city_place('Andrew Haswell Green Park', 'Manhattan', 'East 60th Street at East River',
        'New York', '10065', 40.75951, -73.95762,
        'its-my-park-at-andrew-haswell-green-park-42', 'Alice Aycock Pavilion',
        'Publisher names East 60th Street pavilion and East River park; named-park PAD '
        'point/ZIP approximate that riverfront access, not an exact pavilion pin.'),
    _city_place('Ewen Park', 'Bronx', 'Johnson Avenue & West 232nd Street',
        'Bronx', '10463', 40.88219, -73.91002,
        'its-my-park-at-ewen-park-30', 'Ewen Park',
        'Publisher park street bounds and named-park PAD point. Interior toolbox/dog-run '
        'meeting remains in the full description; street entry is approximate.'),
    _city_place('Brower Park', 'Brooklyn', 'Brooklyn Avenue & Park Place',
        'Brooklyn', '11213', 40.67349, -73.9432,
        'its-my-park-at-brower-park-30', 'Butterfly Garden',
        'Publisher gives park bounds and Butterfly Garden meeting; named-park PAD point '
        'is an approximate interior location, with complete garden directions retained.'),
    _city_place('Matthews Muliner Playground', 'Bronx', 'Matthews Avenue & Rhinelander Avenue',
        'Bronx', '10462', 40.8469653025, -73.8615364187,
        'its-my-park-at-matthews-muliner-playground', 'Matthews Ave',
        'Publisher names Matthews Avenue restroom entrance; street spelling corrected from '
        'header Mathews using body and NYC Parks. Native Parks play-area point is approximate.'),
    _city_place('Brookville Park', 'Queens', 'South Conduit Avenue & 232nd Street',
        'Queens', '11422', 40.66284, -73.743,
        'its-my-park-at-brookville-park-4', 'Brookville (?:Park )?Playground|playground area',
        'Publisher explicitly meets at Brookville Playground/park house. The specific '
        'PAD playground point and ZIP are used instead of the much larger park centroid.'),
    _city_place('Stuyvesant Square', 'Manhattan', 'Nathan D. Perlman Place & East 16th Street',
        'New York', '10003', 40.73383, -73.98443,
        'its-my-park-at-stuyvesant-square-64', 'east park planted areas',
        'Publisher identifies east-square plantings and surrounding streets. Named-square '
        'PAD point is approximate; east-side entrance follows the explicit meeting side.'),
    _city_place('Sara D. Roosevelt Park', 'Manhattan', 'Hester Street & Chrystie Street',
        'New York', '10002', 40.716780922314, -73.994062882493,
        'its-my-park-at-sara-d-roosevelt-park-6', 'Hester Street Playground',
        'Publisher meets at Hester Street Playground. NYC Parks native Hester Street Park '
        'House point is a nearby meeting proxy, not the distant whole-park midpoint.'),
    _city_place('Ralph Bunche Park', 'Manhattan', 'First Avenue & East 43rd Street',
        'New York', '10017', 40.74928, -73.96982,
        'its-my-park-at-ralph-bunche-park-34', 'Ralph Bunche Park',
        'Publisher gives First Avenue/42nd-43rd bounds and whole-park plantings. '
        'Named-park PAD point and boundary street access are approximate.'),
    _city_place('Sunset Park', 'Brooklyn', '41st Street & Seventh Avenue',
        'Brooklyn', '11232', 40.64798, -74.00374,
        'its-my-park-at-sunset-park-126', '41st & 7th Ave',
        'Publisher explicitly names this corner and metal-container directions. Named-park '
        'PAD point is approximate; a contradictory off-park municipal point was rejected.'),
    _city_place('Roberto Clemente Ballfield', 'Brooklyn', 'Division Avenue & Wythe Avenue',
        'Brooklyn', '11249', 40.70643, -73.96771,
        'its-my-park-at-roberto-clemente-ballfield', 'Roberto Clemente Ballfield',
        'Publisher gives Division/Wythe/Kent boundary and whole-ballfield cleanup. '
        'PAD exact named-ballfield point and current 11249 ZIP replace historical header 11211.'),
    _city_place('Cottages Hill New Brighton Park', 'Staten Island', 'Arnold Street & Harvard Avenue',
        'Staten Island', '10301', 40.6394356283, -74.0896636019,
        'its-my-park-at-cottages-hill-new-brighton-park-8', 'garden',
        'Publisher park street bounds plus NYC Parks native Skyline Playground Garden '
        'event point. Boundary access is approximate; actual garden directions retained.'),
    _city_place('Alice Kornegay Triangle', 'Manhattan', 'Lexington Avenue & East 128th Street',
        'New York', '10035', 40.806548, -73.935583,
        'its-my-park-at-alice-kornegay-triangle-4', 'Alice Kornegay Triangle',
        'Publisher gives Lexington/128th-129th bounds and outside tree pits. Named-triangle '
        'PAD point is an approximate access location for work around the park.'),
    _city_place('Henry Hudson Park', 'Bronx', 'Independence Avenue & Kappock Street',
        'Bronx', '10463', 40.8809, -73.9209,
        'its-my-park-at-henry-hudson-park-30', 'Henry Hudson Park',
        'Publisher lists park bounds and upper/lower work areas. Named-park PAD point '
        'provides approximate access; no claim of one exact interior work site.'),
    _city_place('Bloomingdale Playground', 'Manhattan', 'Amsterdam Avenue & West 104th Street',
        'New York', '10025', 40.79911, -73.96563,
        'its-my-park-at-bloomingdale-playground-2', 'Bloomingdale Playground',
        'Publisher playground street bounds and exact named-playground PAD point; '
        'street entrance is approximate for the playground-wide gardening activity.'),
    _city_place('Rainbow Playground', 'Brooklyn', 'Sixth Avenue & 55th Street',
        'Brooklyn', '11220', 40.64054, -74.01106,
        'its-my-park-at-rainbow-playground-5', 'Rainbow Playground',
        'Publisher gives Sixth Avenue/55th-56th bounds. Named-playground PAD point '
        'and boundary intersection are approximate access for a park-wide meeting.'),
    _city_place('Little Bay Park', 'Queens', '14-18 Utopia Parkway',
        'Whitestone', '11357', 40.789382, -73.794252,
        'its-my-park-at-little-bay-park-4', '14-18 Utopia Pkwy',
        'Publisher explicitly supplies 14-18 Utopia Parkway for directions, overriding '
        'its broad park ZIPs. Nearby PAD 14-14 Utopia point is a visible approximation; '
        'the full prose retains both stated shoreline approach descriptions.'),
    _city_place('Jacob H. Schiff Playground', 'Manhattan', 'Amsterdam Avenue & West 136th Street',
        'New York', '10031', 40.82051, -73.95202,
        'its-my-park-at-jacob-h-schiff-playground-2', 'Jacob H. Schiff Playground',
        'Publisher gives Amsterdam/136th-138th bounds. Named-playground PAD point '
        'and boundary entry are approximate for a park-wide meeting.'),
    _city_place('Glenwood Landing', 'Queens', 'Glenwood Street & 39th Road',
        'Little Neck', '11363', 40.775069896346, -73.739911039084,
        'its-my-park-at-glenwood-landing-3', 'Glenwood Landing',
        'Publisher venue header says 39th Road while narrative says 39th Avenue. '
        'NYC Parks native Glenwood Landing Garden point and PAD exact named-park match '
        'support approximate access at the header street; narrative is retained unchanged.'),
    _city_place("Wolfe's Pond Park", 'Staten Island', '475 Cornelia Avenue',
        'Staten Island', '10312', 40.51806, -74.19006,
        'its-my-park-at-wolfes-pond-park-15', '475 Cornelia Ave',
        'Publisher explicitly supplies maintenance-shop meeting address at 475 Cornelia. '
        'Named-park PAD point is approximate for the main-parking-lot shop, not an exact building pin.'),
    _city_place('Moore Homestead Playground', 'Queens', 'Broadway & 45th Avenue',
        'Elmhurst', '11373', 40.742321270198, -73.882089495659,
        'its-my-park-at-moore-homestead-playground-3', 'Broadway & 45th Ave',
        'Publisher gives Broadway/45th/82nd meeting. Native NYC Parks comfort-station '
        'point is an approximate meeting proxy within that small playground.'),
    _city_place('Fraser Square', 'Brooklyn', 'Kings Highway & Avenue M',
        'Brooklyn', '11234', 40.61997, -73.94123,
        'its-my-park-at-fraser-square-13', 'Fraser Square',
        'Publisher gives Kings Highway/Avenue M bounds and all four planting areas. '
        'Named-square PAD point represents approximate access, not one exclusive meeting spot.'),
]
_CITY_BY_NAME = {_name(p['park']): p for p in CITY_PLACES}


def _ranger_place(native, name, street, zipcode, lat, lng, evidence, provenance):
    return dict(source_key=RANGERS, native_location=native, venue_name=name,
                venue_address=f'{street}, Staten Island, NY {zipcode}', venue_city='Staten Island',
                lat=lat, lng=lng, approximate=False, evidence_url=evidence, provenance=provenance)


RANGER_PLACES = [
    _ranger_place('Forest Avenue and Silver Lake Park Road (in Silver Lake Park)',
        'Silver Lake Park — Forest Avenue entrance', 'Forest Avenue & Silver Lake Park Road',
        '10301', 40.63159291279, -74.095857262611, SOURCES[RANGERS][0],
        'Native NYC Parks named intersection and event coordinates; official NYC street finder confirms park ZIP.'),
    _ranger_place('Prospect Avenue and Brentwood Avenue (in Allison Pond Park)',
        'Allison Pond Park — Prospect Avenue entrance', 'Prospect Avenue & Brentwood Avenue',
        '10301', 40.638315348643, -74.102748195445, SOURCES[RANGERS][0],
        'Native NYC Parks named intersection and exact event coordinates; PAD named park confirms ZIP.'),
    _ranger_place('Blue Heron Nature Center (in Blue Heron Park)', 'Blue Heron Nature Center',
        '222 Poillon Avenue', '10312', 40.530857179196, -74.177863717079,
        'https://www.nyc.gov/mayors-office/news/2022/07/mayor-adams-further-expands-city-s-network-at-home-test-distribution-sites-nyc-parks',
        'Official NYC Nature Center address; native NYC Parks event point at the named center.'),
    _ranger_place('Arthur Kill Road and Brookfield Avenue (in Brookfield Park)',
        'Brookfield Park — Arthur Kill Road entrance', 'Arthur Kill Road & Brookfield Avenue',
        '10308', 40.561667478494, -74.15999635582, SOURCES[RANGERS][0],
        'Native NYC Parks named intersection and event coordinates; official PAD named park and street finder confirm ZIP.'),
    _ranger_place('Nevada Avenue Parking Lot (in High Rock Park)', 'High Rock Park — Nevada Avenue parking lot',
        '200 Nevada Avenue', '10306', 40.584556817034, -74.124981164932,
        'https://comptroller.nyc.gov/wp-content/uploads/documents/MD10_072A.pdf',
        'Official City address for High Rock Park entrance; native event point locates the Nevada Avenue parking lot.'),
]
_RANGER_BY_LOCATION = {p['native_location']: p for p in RANGER_PLACES}

# Native provider IDs bind each reviewed physical center to its street/ZIP/point.
# New or changed sites are held for review rather than inheriting another center.
OLDER_SITES = {
    'C2501': ('Florence E Smith OAC', '102-19 34 Avenue', 'Corona', '11368', 40.755742, -73.865988),
    'C3701': ('Grand St Settlement Grand Coalition of Older Adults OAC', '175 Delancey Street 4th Floor', 'New York', '10002', 40.717466, -73.985004),
    'C8901': ('Washington Heights Neighborhood Senior Center (STAR OAC)', '650 West 187th Street', 'New York', '10033', 40.853679, -73.932494),
    'C7501': ('ST NICKS ALLIANCE COOPER PARK SOCIAL 2', '211 Ainslie Street', 'Brooklyn', '11211', 40.712972, -73.945453),
    'C1001': ('Bronx House Weinberg Neighborhood Senior Center', '990 Pelham Parkway South', 'Bronx', '10461', 40.856804, -73.860354),
    'C7205': ('Times Plaza Center OAC', '460 Atlantic Avenue', 'Brooklyn', '11217', 40.686296, -73.983223),
    'C4702': ('JCCGCI Haber House Older Adult Center', '3001 West 37th Street', 'Brooklyn', '11224', 40.573177, -74.002509),
    'W2104': ('Selfhelp Latimer', '34-30 137th Street', 'Flushing', '11354', 40.766044, -73.829935),
    'C9701': ('New Beginnings (Riverdale Y)', '5625 Arlington Avenue', 'Bronx', '10471', 40.905009, -73.907133),
    'C7502': ('ST NICKS ALLIANCE SWINGING SIXTIES OAC 2', '120 Jackson Street', 'Brooklyn', '11211', 40.71645, -73.946734),
    'C1711': ('CCNS Pete McGuinness Older Adult Center', '715 Leonard Street', 'Brooklyn', '11222', 40.729007, -73.95276),
    'C4501': ('ITALIAN SENIOR CITIZENS CENTER', '83-20 Queens Boulevard', 'Elmhurst', '11373', 40.737205, -73.879686),
    'W2101': ('SELFHELP AUSTIN ST', '106-06 Queens Boulevard', 'Forest Hills', '11375', 40.72212, -73.847335),
}
# St Nicks publishes activities at its other center with the originating
# provider ID. Native occurrence street/ZIP/point identify the actual site.
OLDER_OFFSITE_PAIRS = {'C7501': ('C7502',), 'C7502': ('C7501',)}
REVIEWED_LOCATIONS = CITY_PLACES + RANGER_PLACES
REVIEWED_INTERSECTIONS = [p for p in REVIEWED_LOCATIONS
                          if not re.match(r'^\d{1,6}(?:-\d{1,6})?\s', p['venue_address'])]
_LOCATIONS = {(p['source_key'], p['venue_name'], p['venue_address']): p for p in REVIEWED_LOCATIONS}


def reviewed_venue_location(key, name, address):
    place = _LOCATIONS.get((key, name, address))
    return {'lat': place['lat'], 'lng': place['lng']} if place else None


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.netloc not in ALLOWED_HOSTS[key]
                or p.query or p.fragment or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)):
            return False
        if key == OLDER:
            return value == SOURCES[key][0]
        pattern = r'/events/[a-z0-9-]+/' if key == CITY else r'/events/20\d{2}/\d{2}/\d{2}/[a-z0-9-]+'
        return bool(re.fullmatch(pattern, p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if key != CITY or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        return value if (p.scheme == 'https' and p.netloc == 'cityparksfoundation.org'
                         and not p.query and not p.fragment
                         and re.fullmatch(r'/wp-content/uploads/20\d{2}/\d{2}/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)', p.path, re.I)) else None
    except ValueError:
        return None


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('unregistered_new_york_outdoors_remaining_source')
    return key


def _budget(deadline_at):
    if deadline_at is not None and monotonic() + 10 >= deadline_at:
        raise ValueError('ny_outdoors_remaining_deadline')


def _body(value):
    if not isinstance(value, str):
        raise ValueError('ny_outdoors_remaining_description_missing')
    text = description(value, limit=max(len(value), MAX_DESCRIPTION + 1))
    if not text:
        raise ValueError('ny_outdoors_remaining_description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('ny_outdoors_remaining_description_limit')
    return text


def _point(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
        if math.isfinite(lat) and math.isfinite(lng) and 40.48 < lat < 40.94 and -74.27 < lng < -73.68:
            return lat, lng
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _times(item, start_field, end_field):
    start = timestamp(item.get(start_field), ZONE)
    end = timestamp(item.get(end_field), ZONE)
    if start is None or end is None or end <= start:
        raise ValueError('ny_outdoors_remaining_time_unverified')
    return start, end


def _hold(diagnostics, item, reason):
    diagnostics.append(dict(id=str(item.get('id') or item.get('guid') or item.get('dfta_id') or ''),
                            title=plain(item.get('title') or item.get('eventname')),
                            starts_at=item.get('start_date') or item.get('starttime'), reason=reason))


def _content_venue(**values):
    """Keep publisher event venue facts separate from reviewed map enrichment."""
    allowed = {'venue_name', 'venue_address', 'venue_city', 'venue_region',
               'venue_postal_code', 'venue_country'}
    result = {}
    for name, value in values.items():
        if name not in allowed:
            raise ValueError('ny_outdoors_remaining_feed_changed')
        if value in (None, ''):
            continue
        if not isinstance(value, (str, int)) or len(str(value)) > 500:
            raise ValueError('ny_outdoors_remaining_feed_changed')
        result[name] = plain(str(value))
    return result


def _attach_content(row, body, *, content_venue=None, image=None, labels=(),
                    provider_venue_id=None, source_coordinates=None, audience=(),
                    registration_text=None, native_options=None):
    """Retain event-owned facts before reviewed addresses and points are applied."""
    start, end = timestamp(row.get('starts_at')), timestamp(row.get('ends_at'))
    if start is None or start.tzinfo is None or end is not None and end.tzinfo is None:
        raise ValueError('ny_outdoors_remaining_time_unverified')
    facts = {
        'title': row['title'],
        'description': body,
        'is_all_day': False,
        'starts_at_utc': start.astimezone(timezone.utc).isoformat(),
        'ends_at_utc': end.astimezone(timezone.utc).isoformat() if end else None,
        'source_timezone': ZONE,
        'event_url': row['event_url'],
        'provider_venue_id': str(provider_venue_id) if provider_venue_id else None,
        'source_image_url': image,
        'publisher_categories': sorted({plain(value) for value in labels if plain(value)}),
        'audience': sorted({plain(value) for value in audience if plain(value)}),
        'attendance_mode': 'in_person',
        'registration_text': plain(registration_text),
        'native_options': native_options if native_options else None,
        **(content_venue or {}),
    }
    if source_coordinates is not None:
        try:
            lat, lng = map(float, source_coordinates)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('ny_outdoors_remaining_location_unresolved') from None
        if not (math.isfinite(lat) and math.isfinite(lng)
                and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError('ny_outdoors_remaining_location_unresolved')
        facts.update(source_latitude=lat, source_longitude=lng)
    facts = {name: value for name, value in facts.items()
             if value is not None and value != '' and value != [] and value != {}}
    row['collector_event_content_v1'] = {
        'version': 1,
        'event_id': row['id'],
        'facts': facts,
    }
    return row


def _row(key, item, title, body, place, start, end, url, identity, category, *,
         content_venue=None, image=None, labels=(), provider_venue_id=None,
         source_coordinates=None, audience=(), registration_text=None,
         native_options=None):
    if not event_url(key, url):
        raise ValueError('ny_outdoors_remaining_link_unresolved')
    if not title or len(title) > 180 or NONPUBLIC.search(title):
        raise ValueError('ny_outdoors_remaining_not_public')
    row = record(title, start, end, place['venue_name'], place['venue_address'], place['venue_city'],
                 url, identity, category=category, lat=place['lat'], lng=place['lng'],
                 tz=ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                   location_provenance=place['provenance'], location_evidence_url=place['evidence_url'])
        photo = photo_url(key, image)
        if photo:
            row['image_url'] = photo
        _attach_content(row, body, content_venue=content_venue, image=photo,
                        labels=labels, provider_venue_id=provider_venue_id,
                        source_coordinates=source_coordinates, audience=audience,
                        registration_text=registration_text,
                        native_options=native_options)
    return row


def _visible_cancellation_days(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if soup.select_one('.tribe-events, [data-elementor-type="wp-page"], [data-elementor-type="archive"]') is None:
        raise ValueError('ny_outdoors_remaining_feed_changed')
    for node in soup.select('script, style, [hidden], [aria-hidden="true"], '
                            '.elementor-hidden-desktop.elementor-hidden-tablet.elementor-hidden-mobile'):
        node.decompose()
    for node in soup.select('[style]'):
        if re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', node.get('style', ''), re.I):
            node.decompose()
    visible = plain(soup.get_text(' '))
    match = re.search(r'(.{0,180}(?:all|this weekend).{0,100}It[’\x27]s My Park.{0,200}cancell?ed.{0,120})', visible, re.I)
    if match is None:
        return set()
    if 'this weekend' not in match[0].casefold():
        raise ValueError('ny_outdoors_remaining_cancellation_unresolved')
    day = now.astimezone(ZoneInfo(ZONE)).date()
    saturday = day + timedelta(days=5 - day.weekday())
    return {saturday, saturday + timedelta(days=1)}


def _city_manifest(fetch, now, deadline_at):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    query = {'start_date': day.isoformat(), 'end_date': (day + timedelta(days=60)).isoformat(),
             'per_page': 100, 'page': 1}
    items, seen, total, pages = [], set(), None, None
    for page in range(1, MAX_PAGES + 1):
        _budget(deadline_at)
        query['page'] = page
        data = json.loads(fetch(CITY_API + '?' + urlencode(query), 'application/json'))
        if (not isinstance(data, dict) or not isinstance(data.get('events'), list)
                or type(data.get('total')) is not int or type(data.get('total_pages')) is not int):
            raise ValueError('ny_outdoors_remaining_feed_changed')
        if total is None:
            total, pages = data['total'], data['total_pages']
            if not 0 <= total <= MAX_RECORDS or not 0 <= pages <= MAX_PAGES:
                raise ValueError('ny_outdoors_remaining_record_limit')
        if total != data['total'] or pages != data['total_pages']:
            raise ValueError('ny_outdoors_remaining_pagination_incomplete')
        for item in data['events']:
            if not isinstance(item, dict) or not item.get('id') or item['id'] in seen:
                raise ValueError('ny_outdoors_remaining_pagination_incomplete')
            seen.add(item['id'])
            items.append(item)
        if page >= pages:
            break
    if len(items) != total:
        raise ValueError('ny_outdoors_remaining_pagination_incomplete')
    return items


def _city_row(item, now, cancelled):
    start, end = _times(item, 'start_date', 'end_date')
    if end <= now or start >= now + timedelta(days=60):
        return None
    if item.get('timezone') != ZONE or item.get('all_day'):
        raise ValueError('ny_outdoors_remaining_time_unverified')
    if start.astimezone(ZoneInfo(ZONE)).date() in cancelled:
        raise ValueError('ny_outdoors_remaining_not_public')
    title, body = plain(item.get('title')), _body(item.get('description'))
    match = re.fullmatch(r"it['’]s my park at (.+)", title, re.I)
    place = _CITY_BY_NAME.get(_name(match[1])) if match else None
    if place is None:
        raise ValueError('ny_outdoors_remaining_location_unresolved')
    venue = item.get('venue')
    if (not isinstance(venue, dict) or _name(venue.get('venue')) != _name(place['borough'])
            or not re.search(place['meeting'], body, re.I)):
        raise ValueError('ny_outdoors_remaining_location_unresolved')
    if _name(place['park']) == 'mckinley park' or re.search(r'Leif Ericson Park', body, re.I):
        raise ValueError('ny_outdoors_remaining_schedule_conflict')
    labels = [plain(c.get('name')) for c in item.get('categories', []) if isinstance(c, dict)]
    image = (item.get('image') or {}).get('url') if isinstance(item.get('image'), dict) else None
    return _row(CITY, item, title, body, place, start, end, item.get('url'), str(item['id']),
                ', '.join(labels), content_venue=_content_venue(venue_name=venue.get('venue')),
                image=image, labels=labels)


def _soda_query(key, now):
    local = now.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None, microsecond=0)
    horizon = now + timedelta(days=OLDER_HORIZON_DAYS if key == OLDER else 14)
    end = horizon.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None, microsecond=0)
    where = f"endtime > '{local.isoformat()}' AND starttime < '{end.isoformat()}'"
    if key == RANGERS:
        where += " AND parkids like 'R%' AND categories like '%Urban Park Rangers%'"
    query = {'$where': where, '$limit': MAX_RECORDS + 1,
             '$order': 'starttime,dfta_id,eventname,endtime' if key == OLDER else 'starttime,guid'}
    return SODA_ROOT + ('fzy4-e84j' if key == OLDER else 'w3wp-dpdi') + '.json?' + urlencode(query)


def _street_token(value):
    value = re.sub(r'\b(st|ave|blvd)\b', lambda m: {'st': 'street', 'ave': 'avenue', 'blvd': 'boulevard'}[m[0]], _name(value))
    return re.sub(r'[^a-z0-9-]', '', value)


def _older_row(item, now):
    start, end = _times(item, 'starttime', 'endtime')
    if end <= now or start >= now + timedelta(days=OLDER_HORIZON_DAYS):
        return None
    if item.get('islive') != 'Yes' or item.get('isvirtual') != 'No':
        raise ValueError('ny_outdoors_remaining_not_public')
    provider = OLDER_SITES.get(item.get('dfta_id'))
    point = _point(item.get('latitude'), item.get('longitude'))
    if (provider is None or _name(item.get('providername')) != _name(provider[0])
            or _name(item.get('state')) != 'ny' or point is None):
        raise ValueError('ny_outdoors_remaining_location_unresolved')
    eligible_sites = [provider] + [OLDER_SITES[site_id] for site_id in OLDER_OFFSITE_PAIRS.get(item['dfta_id'], ())]
    matches = [site for site in eligible_sites
               if _street_token(item.get('eventlocation')) == _street_token(site[1])
               and item.get('zipcode') == site[3]
               and all(abs(point[i] - site[4 + i]) <= 1e-7 for i in range(2))]
    if len(matches) != 1:
        raise ValueError('ny_outdoors_remaining_location_unresolved')
    site = matches[0]
    place = dict(venue_name=site[0], venue_address=f'{site[1]}, {site[2]}, NY {site[3]}',
                 venue_city=site[2], lat=point[0], lng=point[1], evidence_url=SOURCES[OLDER][0],
                 provenance='Publisher dated occurrence street, provider ID and native center coordinates. '
                 'Native street/point select the actual center for reviewed St Nicks cross-site activities. '
                 'Street abbreviations/case normalized; Queens neighborhoods corrected using publisher ZIP.')
    title, body = plain(item.get('eventname')), _body(item.get('description'))
    identity = 'nyc-oac:' + sha256(json.dumps([item.get('dfta_id'), title, start.isoformat(),
                end.isoformat(), place['venue_address']], separators=(',', ':')).encode()).hexdigest()
    labels = [plain(item.get('eventtype'))]
    labels.extend(plain(value) for value in str(item.get('topics') or '').split(';'))
    row = _row(
        OLDER, item, title, body, place, start, end, SOURCES[OLDER][0], identity,
        ', '.join(value for value in labels if value),
        content_venue=_content_venue(
            venue_address=item.get('eventlocation'), venue_city=item.get('city'),
            venue_region=item.get('state'), venue_postal_code=item.get('zipcode'),
            venue_country='US'),
        labels=labels, provider_venue_id=item.get('dfta_id'), source_coordinates=point,
        audience=['Adults 60+'],
        native_options={
            'accessibility': plain(item.get('eventaccessibility')),
            'is_recurring': plain(item.get('isrecurring')),
        },
    )
    if row:
        row.update(age_min=60, audience='Adults 60+', accessibility=plain(item.get('eventaccessibility')),
                   native_provider_id=item.get('dfta_id'), native_is_recurring=item.get('isrecurring'),
                   participation_evidence_url='https://www.nyc.gov/site/dfta/services/older-adult-center.page')
    return row


def _parks_link(value):
    url = value.get('url') if isinstance(value, dict) else value
    # The official SODA URL-typed field still uses HTTP. Only this exact official
    # event host/path is upgraded; no insecure request or arbitrary rewrite.
    if isinstance(url, str) and re.fullmatch(r'http://www\.nycgovparks\.org/events/20\d{2}/\d{2}/\d{2}/[a-z0-9-]+', url):
        url = 'https://' + url[len('http://'):]
    return url if event_url(RANGERS, url) else None


def _ranger_row(item, now):
    if (not str(item.get('parkids', '')).startswith('R')
            or 'Urban Park Rangers' not in [v.strip() for v in str(item.get('categories', '')).split('|')]):
        raise ValueError('ny_outdoors_remaining_feed_changed')
    start, end = _times(item, 'starttime', 'endtime')
    if end <= now or start >= now + timedelta(days=14):
        return None
    if re.search(r'\b(?:closed|cancelled|canceled|sold out|full)\b', plain(item.get('registration_description')), re.I):
        raise ValueError('ny_outdoors_remaining_not_public')
    place = _RANGER_BY_LOCATION.get(plain(item.get('location')))
    bits = str(item.get('coordinates', '')).split(',')
    point = _point(*bits) if len(bits) == 2 else None
    if (place is None or point is None or any(abs(point[i] - place[field]) > 1e-7
                                             for i, field in enumerate(('lat', 'lng')))):
        raise ValueError('ny_outdoors_remaining_location_unresolved')
    if not re.fullmatch(r'\d+', str(item.get('guid', ''))):
        raise ValueError('ny_outdoors_remaining_feed_changed')
    labels = [plain(value) for value in str(item.get('categories') or '').split('|')]
    row = _row(
        RANGERS, item, plain(item.get('title')), _body(item.get('description')), place,
        start, end, _parks_link(item.get('link')), str(item['guid']), plain(item.get('categories')),
        content_venue=_content_venue(venue_name=item.get('location')),
        labels=labels, source_coordinates=point,
        registration_text=item.get('registration_description'),
    )
    if row:
        row.update(native_location=plain(item.get('location')),
                   registration_description=plain(item.get('registration_description')))
    return row


def collect_with_diagnostics(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('ny_outdoors_remaining_time_unverified')
    _budget(deadline_at)
    cancelled = set()
    if key == CITY:
        cancelled = _visible_cancellation_days(fetch(SOURCES[key][0], 'text/html'), now)
        items = _city_manifest(fetch, now, deadline_at)
    else:
        items = json.loads(fetch(_soda_query(key, now), 'application/json'))
        if not isinstance(items, list) or any(not isinstance(v, dict) for v in items):
            raise ValueError('ny_outdoors_remaining_feed_changed')
        # 501 is a sentinel. Never mistake a capped API response for completeness.
        if len(items) > MAX_RECORDS:
            raise ValueError('ny_outdoors_remaining_record_limit')
    result, diagnostics, identities, native_items, conflicts = [], [], {}, {}, set()
    for item in items:
        try:
            row = (_city_row(item, now, cancelled) if key == CITY else
                   _older_row(item, now) if key == OLDER else _ranger_row(item, now))
        except ValueError as exc:
            if str(exc) not in ERROR_CODES or str(exc) == 'ny_outdoors_remaining_feed_changed':
                raise
            _hold(diagnostics, item, str(exc))
            continue
        if row:
            identity = (row['id'], row['starts_at'])
            if identity in conflicts:
                _hold(diagnostics, item, 'ny_outdoors_remaining_schedule_conflict')
                continue
            if identity in identities and identities[identity] != row:
                # The OAC export can repeat the same provider/title/time/street
                # occurrence with disagreeing prose and no native occurrence ID.
                # Hold both originals; choosing whichever arrived first would
                # make the published full description depend on API sort ties.
                if key != OLDER:
                    raise ValueError('ny_outdoors_remaining_feed_changed')
                conflicts.add(identity)
                _hold(diagnostics, native_items[identity], 'ny_outdoors_remaining_schedule_conflict')
                _hold(diagnostics, item, 'ny_outdoors_remaining_schedule_conflict')
                continue
            if identity not in identities:
                identities[identity] = row
                native_items[identity] = item
                result.append(row)
    result = [row for row in result if (row['id'], row['starts_at']) not in conflicts]
    return sorted(result, key=lambda r: (r['starts_at'], r['id'])), diagnostics


def collect(source, fetch, *, deadline_at=None, now=None):
    return collect_with_diagnostics(source, fetch, deadline_at=deadline_at, now=now)[0]
