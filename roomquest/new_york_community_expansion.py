"""New public programs from Prospect Park Alliance and Snug Harbor.

The existing TEC parser supplies Prospect Park records. Snug Harbor's public
calendar uses its own documented-in-page slots JSON; each finite slot is paired
with its complete publisher HTML narrative. Every request uses the supplied
guarded transport. Partial checkpoints emit no public events.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp

ZONE = 'America/New_York'
PROSPECT = 'prospect_park_alliance_brooklyn_ny'
SNUG = 'snug_harbor_staten_island_ny'
SOURCES = {
    PROSPECT: ('https://www.prospectpark.org/events/', 'html', 'html'),
    SNUG: ('https://snug-harbor.org/events-calendar/', 'html', 'html'),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {key: 200 for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: 200 for key in SOURCES}
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900000
MAX_DETAILS = 6
PROSPECT_API = 'https://www.prospectpark.org/wp-json/tribe/events/v1/events'
SNUG_API = 'https://snug-harbor.org/wp-json/dod/v1/slot'

# Each tuple is a reviewed actual program location, not the Alliance's office
# or a generic city point. Provenance is stored separately and emitted per row.
VENUES = {'prospect_audubon': ('Prospect Park — Audubon Center',
                      '101 East Drive, Brooklyn, NY 11225',
                      'Brooklyn',
                      40.660822263911,
                      -73.965244889259),
 'prospect_bartel': ('Prospect Park — Bartel-Pritchard Square',
                     'Prospect Park West and 15th Street, Brooklyn, NY 11215',
                     'Brooklyn',
                     40.660939003015,
                     -73.979789838195),
 'prospect_carousel': ('Prospect Park — Carousel',
                       '452 Flatbush Avenue, Brooklyn, NY 11225',
                       'Brooklyn',
                       40.663831727656,
                       -73.964218273759),
 'prospect_concert': ('Prospect Park — Concert Grove (approximate street reference)',
                      'East Drive near Lincoln Road, Brooklyn, NY 11225',
                      'Brooklyn',
                      40.658993324617,
                      -73.964452967048),
 'prospect_parkside': ('Prospect Park — Parkside and Ocean Avenue Entrance',
                       'Parkside Avenue and Ocean Avenue, Brooklyn, NY 11226',
                       'Brooklyn',
                       40.654873286887,
                       -73.961908742822),
 'prospect_grand_army': ('Prospect Park — Grand Army Plaza',
                         'Grand Army Plaza, Brooklyn, NY 11238',
                         'Brooklyn',
                         40.67387886364,
                         -73.970105051994),
 'prospect_lefferts': ('Prospect Park — Lefferts Historic House (approximate street reference)',
                       '452 Flatbush Avenue, Brooklyn, NY 11225',
                       'Brooklyn',
                       40.664370125806,
                       -73.963795825839),
 'prospect_bandshell': ('Prospect Park — Lena Horne Bandshell (approximate street reference)',
                        'Prospect Park West and 9th Street, Brooklyn, NY 11215',
                        'Brooklyn',
                        40.66383325359,
                        -73.976445794106),
 'prospect_picnic': ('Prospect Park — Picnic House (approximate street reference)',
                     'West Drive near 5th Street, Brooklyn, NY 11215',
                     'Brooklyn',
                     40.665404183941,
                     -73.972320556641),
 'prospect_vanderbilt': ('Prospect Park — Vanderbilt Playground',
                         'Prospect Park Southwest and Vanderbilt Street, Brooklyn, NY 11218',
                         'Brooklyn',
                         40.655103323702,
                         -73.973048776388),
 'prospect_third_street': ('Prospect Park — 3rd Street Entrance',
                           'Prospect Park West and 3rd Street, Brooklyn, NY 11215',
                           'Brooklyn',
                           40.668239100851,
                           -73.973854482247),
 'prospect_willink': ('Prospect Park — Willink Plaza Entrance',
                      'Flatbush Avenue and Ocean Avenue, Brooklyn, NY 11225',
                      'Brooklyn',
                      40.663767412146,
                      -73.962858766226),
 'prospect_picnic_south': ('Prospect Park — lawn south of Picnic House (approximate meeting point)',
                           'West Drive near 5th Street, Brooklyn, NY 11215',
                           'Brooklyn',
                           40.6651,
                           -73.97232),
 'snug_c': ('Snug Harbor — Newhouse Main Hall Gallery, Building C',
            '1000 Richmond Terrace Building C, Staten Island, NY 10301',
            'Staten Island',
            40.644406529139,
            -74.102115103537),
 'snug_g': ('Snug Harbor — Newhouse Gallery 1, Building G',
            '1000 Richmond Terrace Building G, Staten Island, NY 10301',
            'Staten Island',
            40.643922942671,
            -74.102296149201),
 'snug_p': ('Snug Harbor — Community Hall, Building P',
            '1000 Richmond Terrace Building P, Staten Island, NY 10301',
            'Staten Island',
            40.641892080018,
            -74.101928515261),
 'snug_booth': ('Snug Harbor — Visitor Info Booth at Chapel Road and Gazebo Road (approximate meeting point)',
                '1000 Richmond Terrace at Chapel Road and Gazebo Road, Staten Island, NY 10301',
                'Staten Island',
                40.6436,
                -74.1033),
 'snug_lantern': ('Snug Harbor — Winter Lantern Festival entrance at Cottage Row and Chapel Road '
                  '(approximate meeting point)',
                  '1000 Richmond Terrace at Cottage Row and Chapel Road, Staten Island, NY 10301',
                  'Staten Island',
                  40.6437,
                  -74.1044),
 'snug_cottage_d': ('Snug Harbor — Emma’s Place, Cottage D (approximate meeting point)',
                    '1000 Richmond Terrace Cottage D, Staten Island, NY 10301',
                    'Staten Island',
                    40.6432,
                    -74.1048),
 'snug_compost': ('Snug Harbor — Sustainability Center, former Compost Demonstration Site (approximate '
                  'meeting point)',
                  '1000 Richmond Terrace Sustainability Center, Staten Island, NY 10301',
                  'Staten Island',
                  40.6417,
                  -74.1011),
 'snug_farm': ('Snug Harbor — Heritage Farm (approximate meeting point)',
               '1000 Richmond Terrace Heritage Farm, Staten Island, NY 10301',
               'Staten Island',
               40.6414,
               -74.102),
 'snug_y': ('Snug Harbor — Carpenter’s Shop, Building Y (approximate meeting point)',
            '1000 Richmond Terrace Building Y, Staten Island, NY 10301',
            'Staten Island',
            40.6437,
            -74.1024)}
LOCATION_PROVENANCE = {'prospect_audubon': 'publisher_named_venue_native_map_point_and_linked_street',
 'prospect_bartel': 'publisher_named_market_entrance_and_native_map_point',
 'prospect_carousel': 'publisher_named_venue_native_map_point_and_reviewed_entrance_street',
 'prospect_concert': 'publisher_named_venue_native_map_point_with_estimated_park_street_reference',
 'prospect_parkside': 'publisher_named_intersection_and_native_map_point_with_estimated_zip',
 'prospect_grand_army': 'publisher_named_plaza_and_native_map_point_with_reviewed_postal_context',
 'prospect_lefferts': 'publisher_named_venue_native_map_point_with_estimated_shared_entrance_street',
 'prospect_bandshell': 'publisher_named_venue_native_map_point_with_estimated_entrance_street',
 'prospect_picnic': 'publisher_named_venue_native_map_point_with_estimated_park_street_reference',
 'prospect_vanderbilt': 'publisher_named_venue_native_map_point_with_reviewed_park_street_reference',
 'prospect_third_street': 'publisher_dated_volunteer_registration_and_native_entrance_map_point',
 'prospect_willink': 'publisher_dated_volunteer_registration_and_native_entrance_map_point',
 'prospect_picnic_south': 'publisher_body_named_south_lawn_with_estimated_point_south_of_native_picnic_house_anchor',
 'snug_c': 'publisher_named_gallery_with_official_nyc_lpc_bin_and_oti_building_point',
 'snug_g': 'publisher_named_gallery_current_site_map_and_city_suffix_bin_building_point_zip_discrepancy_disclosed',
 'snug_p': 'publisher_named_building_current_site_map_and_city_suffix_bin_building_point_zip_discrepancy_disclosed',
 'snug_booth': 'publisher_body_named_location_with_estimated_point_from_current_official_site_map_and_city_building_anchors',
 'snug_lantern': 'publisher_body_named_location_with_estimated_point_from_current_official_site_map_and_city_building_anchors',
 'snug_cottage_d': 'publisher_body_named_location_with_estimated_point_from_current_official_site_map_and_city_building_anchors',
 'snug_compost': 'publisher_body_named_location_with_estimated_point_from_current_official_site_map_and_city_building_anchors',
 'snug_farm': 'publisher_body_named_location_with_estimated_point_from_current_official_site_map_and_city_building_anchors',
 'snug_y': 'publisher_body_named_location_with_estimated_point_from_current_official_site_map_and_city_building_anchors'}
PROSPECT_LOCATIONS = {('audubon center', 'https://www.prospectpark.org/location/audubon-center/'): 'prospect_audubon',
 ('bartel-pritchard square', 'https://www.prospectpark.org/location/bartel-pritchard-square/'): 'prospect_bartel',
 ('carousel', 'https://www.prospectpark.org/location/carousel/'): 'prospect_carousel',
 ('concert grove', 'https://www.prospectpark.org/location/concert-grove/'): 'prospect_concert',
 ('entrance—parkside + ocean avenues', 'https://www.prospectpark.org/location/entrance-parkside-ocean-avenues/'): 'prospect_parkside',
 ('grand army plaza', 'https://www.prospectpark.org/location/grand-army-plaza/'): 'prospect_grand_army',
 ('lefferts historic house', 'https://www.prospectpark.org/location/lefferts-historic-house/'): 'prospect_lefferts',
 ('lena horne bandshell', 'https://www.prospectpark.org/location/lena-horne-bandshell/'): 'prospect_bandshell',
 ('picnic house', 'https://www.prospectpark.org/location/picnic-house/'): 'prospect_picnic',
 ('vanderbilt playground', 'https://www.prospectpark.org/location/vanderbilt-playground/'): 'prospect_vanderbilt'}
REVIEWED_INTERSECTIONS = tuple(dict(source_key=PROSPECT, venue_name=v[0], venue_address=v[1], lat=v[3], lng=v[4])
    for name, v in VENUES.items() if name.startswith('prospect_') and not re.match(r'^\d+\s', v[1]))

# Dated publisher registration pages resolve these otherwise variable meetups.
PROSPECT_DATED_MEETUPS = {('10024597', 'https://www.prospectpark.org/event/park-pitch-in-fall-leaf-raking/2026-11-21/', '2026-11-21T16:00:00+00:00', '2026-11-21T19:00:00+00:00', 'ef791f2db54271707a0ec4f65bbe4719c05c2eccb8055841612a5c7dd4114956'): 'prospect_third_street',
 ('10024598', 'https://www.prospectpark.org/event/park-pitch-in-fall-leaf-raking/2026-11-22/', '2026-11-22T16:00:00+00:00', '2026-11-22T19:00:00+00:00', 'ef791f2db54271707a0ec4f65bbe4719c05c2eccb8055841612a5c7dd4114956'): 'prospect_willink'}

# Exact native occurrence identities found already public in production.
# Bounds prevent a different date or newly scheduled program being suppressed.
EXISTING_PUBLIC_OCCURRENCES = {
    (PROSPECT, '38564', '2026-11-15T13:00:00+00:00'): ('Pre-Thanksgiving Birding in Prospect Park', 'municipal_mapsee_2502a399a309ece2cb1a9925', 'https://brooklynbirdclub.org/event/pre-thanksgiving-birding-in-prospect-park/'),
    (PROSPECT, '38466', '2026-11-22T20:00:00+00:00'): ('Urban Park Rangers | Freedom Seekers: Stories by the Fire', 'nyc_parks_public', 'https://www.nycgovparks.org/events/2026/11/22/freedom-seekers-stories-by-the-fire'),
    (PROSPECT, '38469', '2026-11-27T17:00:00+00:00'): ('Urban Park Rangers | Post-Thanksgiving Day Super Hike', 'municipal_mapsee_0e46855a44eb788f36a2c0ab', 'https://www.nycgovparks.org/events/2026/11/27/postthanksgiving-day-super-hike'),
    (SNUG, '25578', '2026-11-15T21:00:00+00:00'): ("Staten Island Children's Museum: Crazy Science: Dry Ice Discovery", 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/crazy-science-dry-ice-discovery-4/2026-11-15/'),
    (SNUG, '24346', '2026-11-20T17:00:00+00:00'): ('Proximity Exhibition', 'municipal_mapsee_0e46855a44eb788f36a2c0ab', 'https://www.nycgovparks.org/events/2026/11/20/proximity-exhibition'),
    (SNUG, '24347', '2026-11-21T17:00:00+00:00'): ('Proximity Exhibition', 'municipal_mapsee_0e46855a44eb788f36a2c0ab', 'https://www.nycgovparks.org/events/2026/11/21/proximity-exhibition'),
    (SNUG, '25579', '2026-11-21T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: DJ Got Me Fit Dance Party', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/dj-got-me-fit-dance-party-8/2026-11-21/'),
    (SNUG, '25580', '2026-11-22T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: DJ Got Me Fit Dance Party', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/dj-got-me-fit-dance-party-8/2026-11-22/'),
    (SNUG, '25584', '2026-11-22T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: DJ Got Me Fit Dance Party', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/dj-got-me-fit-dance-party-8/2026-11-22/'),
    (SNUG, '24348', '2026-11-27T17:00:00+00:00'): ('Proximity Exhibition', 'municipal_mapsee_0e46855a44eb788f36a2c0ab', 'https://www.nycgovparks.org/events/2026/11/27/proximity-exhibition'),
    (SNUG, '25581', '2026-11-28T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Bilingual Birdies', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/bilingual-birdies-brings-music-and-dance-to-the-museum-experience-this-fun-filled-latin-adventure-4/2026-11-28/'),
    (SNUG, '25583', '2026-11-29T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Silly Billy', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/silly-billy-3/2026-11-29/'),
    (SNUG, '25585', '2026-12-05T17:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Museum Movers and Shakers', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/museum-movers-and-shakers-10/2026-12-05/'),
    (SNUG, '25586', '2026-12-06T17:00:00+00:00'): ('Staten Island Children&#8217;s Museum: ShopRite Kidz Cook: Holiday Cookies', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/shoprite-kidz-cook-holiday-cookies-2/'),
    (SNUG, '25600', '2026-12-12T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Crazy Science: Liquid Nitrogen', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/crazy-science-liquid-nitrogen-4/2026-12-12/'),
    (SNUG, '25601', '2026-12-13T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Crazy Science: Liquid Nitrogen', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/crazy-science-liquid-nitrogen-4/2026-12-13/'),
    (SNUG, '25599', '2026-12-19T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Zumba Kids', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/zumba-kids-5/2026-12-19/'),
    (SNUG, '25597', '2026-12-20T19:30:00+00:00'): ('Staten Island Children&#8217;s Museum: Mighty String Demons', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/mighty-string-demons-3/'),
    (SNUG, '25598', '2026-12-20T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Zumba Kids', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/zumba-kids-5/2026-12-20/'),
    (SNUG, '25603', '2026-12-26T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Silly Billy', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/silly-billy-3/2026-12-26/'),
    (SNUG, '25604', '2026-12-27T19:30:00+00:00'): ('Staten Island Children&#8217;s Museum: A Very GRACE-ful Winter’s Tale', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/a-very-grace-ful-winters-tale-2/'),
    (SNUG, '25602', '2026-12-28T21:00:00+00:00'): ('Staten Island Children&#8217;s Museum: Bilingual Birdies', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/bilingual-birdies-brings-music-and-dance-to-the-museum-experience-this-fun-filled-latin-adventure-4/2026-12-28/'),
    (SNUG, '25605', '2026-12-29T21:00:00+00:00'): ('Staten island Children&#8217;s Museum: Binx the Reptile Guy – Dino Scales &amp; Tails', 'municipal_mapsee_ff1f81293a6a6ae75a21a2d8', 'https://sichildrensmuseum.org/event/binx-the-reptile-guy-dino-scales-tails-5/2026-12-29/'),
}

NONPUBLIC = re.compile(r'\b(?:cancelled|canceled|postponed|members[ -]only|private (?:event|rental)|private wedding)\b', re.I)
REMOTE = re.compile(r'\b(?:virtual session|online only|webinar|zoom)\b', re.I)
VISITING = re.compile(r'^(?:general admission|(?:garden|museum|park|opening|visiting) hours)\b', re.I)
HOLD_REASONS = {'event_not_current', 'event_not_public', 'remote_event',
                'description_missing', 'description_limit', 'venue_unreviewed',
                'already_published_partner_occurrence', 'working_partner_source', 'schedule_unresolved'}
ERROR_CODES = {'nyc_community_' + suffix for suffix in (
    'source_unregistered', 'identity_changed', 'schedule_changed', 'listing_changed',
    'pagination_incomplete', 'manifest_limit', 'record_limit', 'checkpoint_invalid',
    'checkpoint_size_limit', 'detail_changed', 'conflicting_occurrence',
)} | {'collection_deadline', 'publisher_checkpoint_required'}


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('nyc_community_source_unregistered')
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.netloc != ALLOWED_HOSTS[key][0] or p.fragment:
            return False
        if key == PROSPECT:
            return not p.query and re.fullmatch(r'/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?', p.path) is not None
        return (re.fullmatch(r'/(?:event|class|exhibition)/[a-z0-9-]+/', p.path) is not None
                and re.fullmatch(r'slot_id=[1-9][0-9]{0,8}', p.query) is not None)
    except ValueError:
        return False


def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme == 'https' and p.netloc == ALLOWED_HOSTS[key][0]
                and p.path.startswith('/wp-content/uploads/') and not p.fragment
                and not p.query and '%' not in p.path and '..' not in p.path
                and re.search(r'\.(?:jpe?g|png|webp)$', p.path, re.I)):
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    if key not in SOURCES:
        return None
    return next((place[3:] for name, place in VENUES.items()
                 if name.startswith('prospect_') == (key == PROSPECT)
                 and place[:2] == (venue, address)), None)


def _label(value):
    return plain(value).replace('’', "'").replace('‘', "'").casefold()


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError('description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('description_limit')
    return text


def _narrative_identity(value):
    # The ordinary HTML page replaces visible email addresses with Cloudflare's
    # public placeholder while its native TEC feed preserves the full prose.
    # Compare the surrounding complete narrative without decoding protection
    # tokens, then publish the untouched complete native feed description.
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '<email>', value)
    text = text.replace('[email\xa0protected]', '<email>').replace('[email protected]', '<email>')
    return ''.join(text.split())


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _budget(deadline):
    if monotonic() + 12 >= deadline:
        raise ValueError('collection_deadline')


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _api_url(key, now, page=1):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    if key == PROSPECT:
        return PROSPECT_API + '?' + urlencode({'per_page': 50, 'start_date': str(day),
            'end_date': str(day + timedelta(days=60)), 'page': page})
    return SNUG_API + '?' + urlencode({'date_from': str(day),
        'date_to': str(day + timedelta(days=60)), 'include_expired': 'true', 'per_page': 500})


def _times(start, end):
    begins, ends = timestamp(start, ZONE), timestamp(end, ZONE)
    if not begins or not begins.tzinfo or ends and (not ends.tzinfo or not begins < ends):
        raise ValueError('nyc_community_schedule_changed')
    if ends and ends - begins > timedelta(hours=24):
        raise ValueError('schedule_unresolved')
    return begins, ends


def _held_identity(key, item):
    prior = EXISTING_PUBLIC_OCCURRENCES.get((key, item['id'], item['starts_at']))
    return bool(prior and _label(prior[0]) == _label(item['title']))


def _prospect_item(event, now):
    if (not isinstance(event, dict) or type(event.get('id')) is not int
            or not event_url(PROSPECT, event.get('url')) or not plain(event.get('title'))):
        raise ValueError('nyc_community_identity_changed')
    if event.get('timezone') != ZONE:
        raise ValueError('nyc_community_schedule_changed')
    unknown_end = event.get('end_date') == event.get('start_date')
    start, end = _times(event.get('start_date'), None if unknown_end else event.get('end_date'))
    if (timestamp(event.get('utc_start_date'), 'UTC') != start
            or timestamp(event.get('utc_end_date'), 'UTC') != (start if unknown_end else end)):
        raise ValueError('nyc_community_schedule_changed')
    if not _within(start, end, now):
        return None
    title = plain(event['title'])
    held = None
    if (event.get('status') != 'publish' or event.get('hide_from_listings')
            or event.get('all_day') or NONPUBLIC.search(title) or VISITING.search(title)):
        held = 'event_not_public'
    elif event.get('is_virtual') or REMOTE.search(title):
        held = 'remote_event'
    body = event.get('description')
    if not isinstance(body, str):
        raise ValueError('nyc_community_listing_changed')
    image = event.get('image') or {}
    item = dict(id=str(event['id']), url=event['url'], title=title,
                starts_at=start.astimezone(timezone.utc).isoformat(),
                ends_at=end.astimezone(timezone.utc).isoformat() if end else None, body=body,
                categories=[plain(v['name']) for v in event.get('categories', []) if isinstance(v, dict) and v.get('name')],
                image=photo_url(PROSPECT, image.get('url')) if isinstance(image, dict) else None,
                held=held)
    if _held_identity(PROSPECT, item):
        item['held'] = 'already_published_partner_occurrence'
    return item


def _snug_item(event, now):
    if (not isinstance(event, dict) or type(event.get('id')) is not int
            or type(event.get('post_id')) is not int or not event_url(SNUG, event.get('post_permalink'))
            or parse_qs(urlsplit(event['post_permalink']).query)['slot_id'] != [str(event['id'])]
            or event.get('type') not in {'event', 'class'} or not plain(event.get('name'))
            or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', event.get('date', ''))
            or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', event.get('time_start', ''))
            or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', event.get('time_end', ''))):
        raise ValueError('nyc_community_identity_changed')
    start, end = _times(event['date'] + 'T' + event['time_start'], event['date'] + 'T' + event['time_end'])
    if not _within(start, end, now):
        return None
    title = plain(event['name'])
    held = None
    if event.get('status') != 'Active' or NONPUBLIC.search(title) or VISITING.search(title):
        held = 'event_not_public'
    elif REMOTE.search(title):
        held = 'remote_event'
    details = event.get('details') if isinstance(event.get('details'), dict) else {}
    ticket = details.get('ticket_link') if isinstance(details.get('ticket_link'), dict) else {}
    ticket_url = ticket.get('url')
    # This independently published, healthy museum calendar already owns its
    # programs. Bind the exclusion to both publisher label and official ticket
    # hostname, so future mirrored dates also stay with the working source.
    if (title.casefold().replace('’', "'").startswith("staten island children's museum:")
            and isinstance(ticket_url, str)
            and urlsplit(ticket_url).scheme == 'https'
            and urlsplit(ticket_url).netloc in {'sichildrensmuseum.org', 'www.sichildrensmuseum.org'}):
        held = 'working_partner_source'
    item = dict(id=str(event['id']), post_id=event['post_id'], type=event['type'],
                url=event['post_permalink'], title=title,
                starts_at=start.astimezone(timezone.utc).isoformat(),
                ends_at=end.astimezone(timezone.utc).isoformat(),
                image=photo_url(SNUG, event.get('image_url')), ticket_url=ticket_url, held=held)
    if _held_identity(SNUG, item):
        item['held'] = 'already_published_partner_occurrence'
    return item


def _manifest(key, fetch, deadline, now):
    result, seen, total, pages = [], set(), None, None
    if key == SNUG:
        _budget(deadline)
        data = json.loads(fetch(_api_url(key, now), 'application/json'))
        # The native calendar requests 500 slots for its selected date range.
        # A full page cannot establish completeness and is rejected.
        if not isinstance(data, dict) or data.get('success') is not True or not isinstance(data.get('data'), list):
            raise ValueError('nyc_community_listing_changed')
        if len(data['data']) >= 500:
            raise ValueError('nyc_community_pagination_incomplete')
        native = data['data']
    else:
        native = []
        for page in range(1, 5):
            _budget(deadline)
            data = json.loads(fetch(_api_url(key, now, page), 'application/json'))
            if not isinstance(data, dict) or not isinstance(data.get('events'), list) or len(data['events']) > 50:
                raise ValueError('nyc_community_listing_changed')
            if total is None:
                total, pages = data.get('total'), data.get('total_pages')
                if type(total) is not int or type(pages) is not int or not 0 <= total <= MAX_RECORDS or not 0 <= pages <= 4:
                    raise ValueError('nyc_community_manifest_limit')
            if data.get('total') != total or data.get('total_pages') != pages:
                raise ValueError('nyc_community_pagination_incomplete')
            native.extend(data['events'])
            if page >= pages:
                if data.get('next_rest_url'):
                    raise ValueError('nyc_community_pagination_incomplete')
                break
        if len(native) != total:
            raise ValueError('nyc_community_pagination_incomplete')
    for value in native:
        if not isinstance(value, dict) or type(value.get('id')) is not int or value['id'] in seen:
            raise ValueError('nyc_community_pagination_incomplete')
        seen.add(value['id'])
        item = (_prospect_item if key == PROSPECT else _snug_item)(value, now)
        if item:
            result.append(item)
    if len(result) > MAX_RECORDS:
        raise ValueError('nyc_community_manifest_limit')
    if len({v['url'] for v in result}) != len(result):
        raise ValueError('nyc_community_identity_changed')
    return sorted(result, key=lambda v: (v['starts_at'], v['id']))


def _prospect_place(item, soup, body):
    dated = PROSPECT_DATED_MEETUPS.get((item['id'], item['url'], item['starts_at'], item['ends_at'], _digest(body)))
    if dated:
        return dated
    label = soup.select_one('.sidebar-location .sidebar-text')
    link = soup.select_one('.sidebar-mapit a[href]')
    if label and link:
        native = (_label(label.get_text(' ')), link.get('href'))
        if native in PROSPECT_LOCATIONS:
            place = PROSPECT_LOCATIONS[native]
            if place == 'prospect_picnic' and item['title'] == 'FIDO Coffee Bark':
                if 'just south of the Picnic House' not in body:
                    raise ValueError('venue_unreviewed')
                return 'prospect_picnic_south'
            return place
    if (item['title'] == 'Sunday Greenmarket at Bartel-Pritchard Square'
            and 'southwest corner' in body and not label and not link):
        return 'prospect_bartel'
    raise ValueError('venue_unreviewed')


def _snug_place(item, body):
    match = re.search(r'\bwhere\s*:(.*?)(?:\badmission\b|$)', body, re.I | re.S)
    where = _label(match[1]) if match else ''
    where = where.replace('ne whouse', 'newhouse').replace('b uilding', 'building')
    choices = (
        ('visitor info booth', 'snug_booth'),
        ('visitor services booth', 'snug_booth'),
        ('corner of cottage row and chapel road', 'snug_lantern'),
        ('building p lobby', 'snug_p'),
        ('building p at snug harbor', 'snug_p'),
        ('sustainability center', 'snug_compost'),
        ('compost demonstration site', 'snug_compost'),
        ('compost demo site', 'snug_compost'),
        ('heritage farm', 'snug_farm'),
        ("carpenter's shop", 'snug_y'),
        ('cottage d', 'snug_cottage_d'),
        ('main hall gallery, building c', 'snug_c'),
        ('building g, gallery 1', 'snug_g'),
        ('music hall', 'snug_t'),
        ('great hall', 'snug_r'),
    )
    places = {place for needle, place in choices if needle in where}
    if len(places) == 1 and next(iter(places)) in VENUES:
        return next(iter(places))
    raise ValueError('venue_unreviewed')


def _row(key, item, body, place):
    venue = VENUES[place]
    if key == PROSPECT:
        street, city, point = venue[1], venue[2], venue[3:]
        parsed = parse_tribe({'events': [dict(id=item['id'], title=item['title'],
            url=item['url'], status='publish', timezone=ZONE,
            utc_start_date=item['starts_at'], utc_end_date=item['ends_at'],
            categories=[{'name': name} for name in item['categories']],
            venue=dict(venue=venue[0], address=street, city=city, state='NY',
                       geo_lat=point[0], geo_lng=point[1]))]}, strict_public=True, retain_description=False)
        if len(parsed) != 1:
            raise ValueError('nyc_community_detail_changed')
        row = parsed[0]
        row['venue_address'] = street
    else:
        row = record(item['title'], item['starts_at'], item['ends_at'], venue[0],
                     venue[1], venue[2], item['url'], item['id'],
                     'Community Classes' if item['type'] == 'class' else 'Public Programs',
                     venue[3], venue[4], ZONE, publisher_geo=True)
        if not row:
            raise ValueError('nyc_community_detail_changed')
    row.update(description=body, timezone=ZONE, attendance_mode='in_person',
               location_provenance=LOCATION_PROVENANCE[place])
    if '(approximate' in venue[0] or 'estimate' in LOCATION_PROVENANCE[place] or 'approximate' in LOCATION_PROVENANCE[place]:
        row['location_is_approximate'] = True
    if item.get('image'):
        row['image_url'] = item['image']
    return row


def _detail(key, item, payload):
    soup = BeautifulSoup(payload, 'html.parser')
    heading = soup.select_one('h1.page-title' if key == PROSPECT else 'h1.o-hero-3__title')
    if not heading or _label(heading.get_text(' ')) != _label(item['title']):
        raise ValueError('nyc_community_detail_changed')
    if key == PROSPECT:
        nodes = soup.select('.tribe-events-single-event-description')
        if len(nodes) != 1:
            raise ValueError('nyc_community_detail_changed')
        rendered = _body(str(nodes[0]))
        body = _body(item['body'])
        if _narrative_identity(rendered) != _narrative_identity(body):
            raise ValueError('nyc_community_detail_changed')
        events = []
        for script in soup.select('script[type="application/ld+json"]'):
            data = json.loads(script.string or script.get_text())
            values = data if isinstance(data, list) else data.get('@graph', [data]) if isinstance(data, dict) else []
            events.extend(v for v in values if isinstance(v, dict) and v.get('@type') == 'Event')
        selected = [e for e in events if e.get('url') == item['url']]
        if (len(selected) != 1 or _label(selected[0].get('name')) != _label(item['title'])
                or timestamp(selected[0].get('startDate')) != timestamp(item['starts_at'])
                or timestamp(selected[0].get('endDate')) != timestamp(item['ends_at'] or item['starts_at'])
                or selected[0].get('eventStatus') != 'https://schema.org/EventScheduled'
                or selected[0].get('eventAttendanceMode') != 'https://schema.org/OfflineEventAttendanceMode'):
            raise ValueError('nyc_community_schedule_changed')
        place = _prospect_place(item, soup, body)
    else:
        nodes = soup.select('main .o-g-text-a-1__text')
        if not nodes:
            raise ValueError('description_missing')
        body = _body('\n'.join(str(v) for v in nodes))
        # A publisher may combine several sessions into one calendar slot.
        # Do not turn that enclosing span into one continuous timed event.
        if re.search(r'\bsession\s*1\s*:', body, re.I) and re.search(r'\bsession\s*2\s*:', body, re.I):
            raise ValueError('schedule_unresolved')
        # Native SEO dates describe the entire series, and calendar-export
        # controls can select its next date even for a historical slot. The
        # reviewed slots API owns occurrence clocks. Check the visible selected
        # date/start when this event layout supplies them; exhibitions omit it.
        day = soup.select_one('.o-hero-3__board-date-day')
        clock = soup.select_one('.o-hero-3__time')
        start = timestamp(item['starts_at']).astimezone(ZoneInfo(ZONE))
        if day and plain(day.get_text(' ')) != start.strftime('%b %d, %Y').replace(' 0', ' '):
            # Publishers commonly zero-pad the day; both render the same date.
            try:
                visible = datetime.strptime(plain(day.get_text(' ')), '%b %d, %Y').date()
            except ValueError:
                raise ValueError('nyc_community_schedule_changed') from None
            if visible != start.date():
                raise ValueError('nyc_community_schedule_changed')
        if clock:
            try:
                visible_clock = datetime.strptime(plain(clock.get_text(' ')), '%I:%M %p').time()
            except ValueError:
                raise ValueError('nyc_community_schedule_changed') from None
            if visible_clock != start.time().replace(tzinfo=None):
                raise ValueError('nyc_community_schedule_changed')
        place = _snug_place(item, body)
    return _row(key, item, body, place)


def _new_state(key, queue, now):
    return dict(version=1, source_key=key, started_at=now.isoformat(),
                window_start=now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                manifest_hash=_digest(queue), manifest_count=len(queue), cursor=0,
                queue=queue, events=[], row_hashes={}, diagnostics=[], manifest_verified=not queue)


def _checkpoint(key, value, now):
    if value is None:
        return None
    try:
        if (not isinstance(value, dict) or type(value['version']) is not int or value['version'] != 1
                or value['source_key'] != key or type(value['cursor']) is not int
                or type(value['manifest_count']) is not int
                or not 0 <= value['cursor'] <= value['manifest_count'] <= MAX_RECORDS
                or not isinstance(value['queue'], list) or len(value['queue']) != value['manifest_count']
                or value['manifest_hash'] != _digest(value['queue'])
                or not isinstance(value['events'], list) or len(value['events']) > MAX_RECORDS
                or not isinstance(value['row_hashes'], dict) or len(value['row_hashes']) != len(value['events'])
                or not isinstance(value['diagnostics'], list) or len(value['diagnostics']) != value['cursor']
                or type(value['manifest_verified']) is not bool
                or value['manifest_verified'] and value['cursor'] != value['manifest_count']
                or not isinstance(value['started_at'], str)
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value['started_at'])
                or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
            raise ValueError
        started = timestamp(value['started_at'])
        if value['window_start'] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        if not started <= now <= started + timedelta(hours=4):
            return None
        queue = value['queue']
        for item in queue:
            if (not isinstance(item, dict) or not re.fullmatch(r'[1-9][0-9]{0,9}', item['id'])
                    or not event_url(key, item['url']) or not item['title'].strip()
                    or item.get('held') not in HOLD_REASONS | {None}
                    or not _within(*_times(item['starts_at'], item['ends_at']), started)):
                raise ValueError
        if len({v['id'] for v in queue}) != len(queue) or len({v['url'] for v in queue}) != len(queue):
            raise ValueError
        processed = {v['url']: v for v in queue[:value['cursor']]}
        decisions = {}
        for decision in value['diagnostics']:
            if (not isinstance(decision, dict) or decision.get('event_url') not in processed
                    or decision['event_url'] in decisions or decision.get('disposition') not in {'held', 'accepted'}
                    or decision.get('disposition') == 'held' and decision.get('reason') not in HOLD_REASONS):
                raise ValueError
            decisions[decision['event_url']] = decision
        seen = set()
        for row in value['events']:
            item = processed.get(row.get('event_url')) if isinstance(row, dict) else None
            if (not item or item.get('held') or str(row.get('id')) != item['id']
                    or row['id'] in seen or row.get('title') != item['title']
                    or timestamp(row.get('starts_at')) != timestamp(item['starts_at'])
                    or timestamp(row.get('ends_at')) != timestamp(item['ends_at'])
                    or row.get('timezone') != ZONE or row.get('attendance_mode') != 'in_person'
                    or _body(row.get('description')) != row.get('description')
                    or (row.get('lat'), row.get('lng')) != reviewed_venue_location(key, row.get('venue_name'), row.get('venue_address'))
                    or row.get('location_provenance') != next((LOCATION_PROVENANCE[name] for name, place in VENUES.items() if place[:2] == (row.get('venue_name'), row.get('venue_address'))), None)
                    or value['row_hashes'].get(row['id']) != _digest(row)
                    or decisions[row['event_url']]['disposition'] != 'accepted'
                    or key == PROSPECT and _body(item['body']) != row['description']
                    or row.get('image_url') is not None and photo_url(key, row['image_url']) is None):
                raise ValueError
            seen.add(row['id'])
        if set(value['row_hashes']) != seen or len(seen) != sum(v['disposition'] == 'accepted' for v in decisions.values()):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError('nyc_community_checkpoint_invalid') from None
    return deepcopy(value)


def _bounded_pause(error):
    from roomquest.preview_worker import PreviewError
    return (isinstance(error, PreviewError) and str(error) in {'publisher_pacing_deferred', 'source_fetch_deadline'}
            or type(error) is ValueError and str(error) == 'collection_deadline')


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source)
    raise ValueError('publisher_checkpoint_required')


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('nyc_community_checkpoint_invalid')
    current = current.astimezone(timezone.utc)
    state = _checkpoint(key, checkpoint, current)
    if state and state['manifest_verified']:
        return dict(complete=True, events=deepcopy(state['events']), checkpoint=state)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    started = timestamp(state['started_at']) if state else current
    if state is None:
        state = _new_state(key, _manifest(key, fetch, deadline, started), started)
    queue = state['queue']
    fetched, paused = 0, False
    while state['cursor'] < len(queue):
        item = queue[state['cursor']]
        if not item.get('held') and (fetched >= min(MAX_DETAILS, max(1, int(max_details))) or monotonic() + 12 >= deadline):
            break
        try:
            if item.get('held'):
                raise ValueError(item['held'])
            payload = fetch(item['url'], 'text/html')
            fetched += 1
            row = _detail(key, item, payload)
        except ValueError as error:
            if _bounded_pause(error):
                paused = True
                break
            if str(error) not in HOLD_REASONS:
                raise
            state['diagnostics'].append(dict(event_url=item['url'], disposition='held', reason=str(error)))
        else:
            state['events'].append(row)
            state['row_hashes'][row['id']] = _digest(row)
            state['diagnostics'].append(dict(event_url=item['url'], disposition='accepted', reason=None))
        state['cursor'] += 1
    if not paused and state['cursor'] == len(queue) and not state['manifest_verified'] and monotonic() + 24 < deadline:
        try:
            latest = _manifest(key, fetch, deadline, started)
        except ValueError as error:
            if not _bounded_pause(error):
                raise
        else:
            if latest == queue and _digest(latest) == state['manifest_hash']:
                state['manifest_verified'] = True
            else:
                state = _new_state(key, latest, started)
    if len(state['events']) > MAX_RECORDS or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('nyc_community_checkpoint_size_limit')
    complete = state['manifest_verified']
    rows = sorted(state['events'], key=lambda v: (v['starts_at'], v['id']))
    if len({v['id'] for v in rows}) != len(rows):
        raise ValueError('nyc_community_conflicting_occurrence')
    return dict(complete=complete, events=deepcopy(rows) if complete else [], checkpoint=state)
