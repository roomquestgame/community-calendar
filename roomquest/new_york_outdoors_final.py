"""Reviewed NYC public calendars that remained after the first two batches.

All traffic uses the supplied guarded GET transport. Native descriptions are
preserved in full; listing and JSON-LD excerpts never substitute for full page
bodies. Park access estimates are named and evidenced as approximate locations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
FORDHAM = 'fordham_university_ny'
BRONX = 'bronx_river_alliance_ny'
WAVE = 'wave_hill_ny'
BRIDGE = 'brooklyn_bridge_park_ny'
BKUP = 'bkup_brooklyn_ny'
NYRR = 'nyrr_open_run_ny'
CB6 = 'brooklyn_community_board_6_ny'
TRANSALT = 'transportation_alternatives_ny'
PARKS = 'municipal_mapsee_0e46855a44eb788f36a2c0ab'
SOURCES = {
    FORDHAM: ('https://calendar.fordham.edu/', 'html', 'html'),
    BRONX: ('https://bronxriver.org/visit-the-river/calendar', 'html', 'html'),
    WAVE: ('https://www.wavehill.org/calendar', 'html', 'html'),
    BRIDGE: ('https://brooklynbridgepark.org/events/', 'html', 'html'),
    BKUP: ('https://www.bkup.nyc/events', 'html', 'html'),
    NYRR: ('https://prod.nyrr.org/open-run', 'html', 'html'),
    CB6: ('https://brooklyncb6.cityofnewyork.us/events/', 'html', 'html'),
    TRANSALT: ('https://transalt.org/events', 'html', 'html'),
    PARKS: ('https://data.cityofnewyork.us/resource/w3wp-dpdi.json', 'html', 'html'),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
ALLOWED_HOSTS[PARKS] = ('data.cityofnewyork.us', 'www.nycgovparks.org')
ALLOWED_HOSTS[TRANSALT] = ('transalt.org', 'api.mobilize.us', 'www.mobilize.us')
CHECKPOINT_KEYS = {BRONX, WAVE, BKUP, NYRR}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
MAX_MANIFEST = 200
MAX_CHECKPOINT_BYTES = 900000
MAX_DETAILS = 3
NONPUBLIC = re.compile(r'\b(?:cancelled|canceled|postponed|private event|invitation.only|members.only|sold out|fully booked)\b', re.I)
REMOTE = re.compile(r'^(?:virtual|online|zoom)(?:\b|/)', re.I)
HOLD_REASONS = {
    'event_not_current', 'event_not_public', 'all_day_without_hours', 'description_missing',
    'description_limit', 'time_unverified', 'street_unresolved', 'venue_conflict',
    'point_unresolved', 'schedule_conflict', 'event_link_unresolved', 'other_source_owns_event',
    'publisher_body_link_only', 'registration_closed', 'venue_not_reviewed',
}
ERROR_CODES = {'nyc_final_' + x for x in (
    'source_unregistered', 'payload_changed', 'pagination_incomplete', 'record_limit',
    'manifest_limit', 'checkpoint_invalid', 'checkpoint_size_limit', 'checkpoint_required',
    'listing_changed', 'detail_changed',
)} | {'collection_deadline'}

# Explicitly reviewed source/venue/street/point tuples; no organizer fallback.
PLACES = [{'source_key': 'fordham_university_ny',
  'native_identity': 'Pope Auditorium',
  'venue_name': 'Pope Auditorium',
  'venue_address': '113 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.770616,
  'lng': -73.985259,
  'evidence_url': 'https://calendar.fordham.edu/event/fordham-theatre-mainstage-measure-for-measure',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lowenstein Center, Lincoln Center Campus, 113 W 60th St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'McMahon Hall',
  'venue_name': 'McMahon Hall',
  'venue_address': '155 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.770988,
  'lng': -73.986305,
  'evidence_url': 'https://calendar.fordham.edu/event/lecture-no-logos-exilic-theory-of-talmud-by-elad-lapidot',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lincoln Center Campus, 155 W 60th St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Freeman Hall',
  'venue_name': 'Freeman Hall (approximate meeting point)',
  'venue_address': '441 East Fordham Road, Bronx, NY 10458',
  'venue_city': 'Bronx',
  'lat': 40.860462,
  'lng': -73.885585,
  'evidence_url': 'https://calendar.fordham.edu/event/department-of-physics-applied-physics-lecture',
  'provenance': 'publisher_visible_venue_address_with_NYC_PAD_named_building_point',
  'approximate': True,
  'native_address': 'Fordham University, Rose Hill Campus'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'University Church',
  'venue_name': 'University Church (approximate meeting point)',
  'venue_address': '441 East Fordham Road, Bronx, NY 10458',
  'venue_city': 'Bronx',
  'lat': 40.863609,
  'lng': -73.886429,
  'evidence_url': 'https://calendar.fordham.edu/event/uca-martyrs-commemoration',
  'provenance': 'publisher_visible_venue_address_with_NYC_PAD_named_building_point',
  'approximate': True,
  'native_address': 'Rose Hill Campus, Fordham University, Bronx, NY 10458'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'McNally Amphitheatre',
  'venue_name': 'McNally Amphitheatre',
  'venue_address': '140 West 62nd Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.771115,
  'lng': -73.98444,
  'evidence_url': 'https://calendar.fordham.edu/event/christmas-movie-screening-merchants-of-joy',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lincoln Center Campus, 140 West 62nd St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Lowenstein Center',
  'venue_name': 'Lowenstein Center',
  'venue_address': '113 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.770616,
  'lng': -73.985259,
  'evidence_url': 'https://calendar.fordham.edu/event/muffins-with-abigail',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lincoln Center Campus, 113 W 60th St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Lowenstein Lobby',
  'venue_name': 'Lowenstein Lobby',
  'venue_address': '113 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.770616,
  'lng': -73.985259,
  'evidence_url': 'https://calendar.fordham.edu/event/thanksgiving-meal-distribution',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lincoln Center Campus, 113 W 60th St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': "Slattery's Midtown Pub",
  'venue_name': "Slattery's Midtown Pub",
  'venue_address': '8 East 36th Street, New York, NY 10016',
  'venue_city': 'New York',
  'lat': 40.749241,
  'lng': -73.983008,
  'evidence_url': 'https://calendar.fordham.edu/event/fordham-track-field-spiked-shoe-club-meet-up',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': '8 East 36th Street | New York, NY 10016'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Fatima Hall - Our Lady of Mt. Carmel',
  'venue_name': 'Fatima Hall - Our Lady of Mt. Carmel',
  'venue_address': '627 East 187th Street, Bronx, NY 10458',
  'venue_city': 'Bronx',
  'lat': 40.855223,
  'lng': -73.886391,
  'evidence_url': 'https://calendar.fordham.edu/event/holiday-market',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': '627 E 187th St'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Costantino Room, Fordham Law School',
  'venue_name': 'Costantino Room, Fordham Law School',
  'venue_address': '150 West 62nd Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.771578,
  'lng': -73.984855,
  'evidence_url': 'https://calendar.fordham.edu/event/8th-annual-one-girl-women-in-charge-summit',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': '150 West 62nd St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'McMahon Hall|room:109',
  'venue_name': 'McMahon Hall, 109',
  'venue_address': '155 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.770988,
  'lng': -73.986305,
  'evidence_url': 'https://calendar.fordham.edu/event/lecture-no-logos-exilic-theory-of-talmud-by-elad-lapidot',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lincoln Center Campus, 155 W 60th St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Freeman Hall|room:103',
  'venue_name': 'Freeman Hall, 103 (approximate meeting point)',
  'venue_address': '441 East Fordham Road, Bronx, NY 10458',
  'venue_city': 'Bronx',
  'lat': 40.860462,
  'lng': -73.885585,
  'evidence_url': 'https://calendar.fordham.edu/event/department-of-physics-applied-physics-lecture',
  'provenance': 'publisher_visible_venue_address_with_NYC_PAD_named_building_point',
  'approximate': True,
  'native_address': 'Fordham University, Rose Hill Campus'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'Lowenstein Center|room:LL 914',
  'venue_name': 'Lowenstein Center, LL 914',
  'venue_address': '113 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.770616,
  'lng': -73.985259,
  'evidence_url': 'https://calendar.fordham.edu/event/becoming-in-the-african-megacity-housing-mobility-and-the-unmaking-of-the-apartheid-city',
  'provenance': 'publisher_visible_street_and_exact_NYC_PAD_or_native_geo',
  'approximate': False,
  'native_address': 'Lincoln Center Campus, 113 W 60th St., New York, NY 10023'},
 {'source_key': 'fordham_university_ny',
  'native_identity': 'University Church|room:Ignatius Loyola Room',
  'venue_name': 'University Church, Ignatius Loyola Room (approximate meeting point)',
  'venue_address': '441 East Fordham Road, Bronx, NY 10458',
  'venue_city': 'Bronx',
  'lat': 40.863609,
  'lng': -73.886429,
  'evidence_url': 'https://calendar.fordham.edu/event/uca-martyrs-commemoration',
  'provenance': 'publisher_visible_venue_address_with_NYC_PAD_named_building_point',
  'approximate': True,
  'native_address': 'Rose Hill Campus, Fordham University, Bronx, NY 10458'},
 {'source_key': 'bronx_river_alliance_ny',
  'native_identity': 'Concrete Plant Park (1370 Westchester Ave)',
  'venue_name': 'Concrete Plant Park (approximate meeting point)',
  'venue_address': '1370 Westchester Avenue, Bronx, NY 10472',
  'venue_city': 'Bronx',
  'lat': 40.826900482177734,
  'lng': -73.88480377197266,
  'evidence_url': 'https://bronxriver.org/visit-the-river/calendar',
  'provenance': 'publisher_meeting_directions_with_official_Parks_native_point',
  'approximate': True},
 {'source_key': 'bronx_river_alliance_ny',
  'native_identity': 'Muskrat Cove Park',
  'venue_name': 'Muskrat Cove Park — Woodlawn station entrance (approximate meeting point)',
  'venue_address': 'Webster Avenue & East 233rd Street, Bronx, NY 10470',
  'venue_city': 'Bronx',
  'lat': 40.89630126953125,
  'lng': -73.86299896240234,
  'evidence_url': 'https://bronxriver.org/event/november-project-waste',
  'provenance': 'publisher_meeting_directions_with_official_Parks_native_point',
  'approximate': True},
 {'source_key': 'bronx_river_alliance_ny',
  'native_identity': 'The Bronx River Forest (Burke Ave Bridge)',
  'venue_name': 'Bronx River Forest — Burke Avenue Bridge (approximate meeting point)',
  'venue_address': 'Burke Avenue & Bronx Boulevard, Bronx, NY 10467',
  'venue_city': 'Bronx',
  'lat': 40.871585845947266,
  'lng': -73.87255096435547,
  'evidence_url': 'https://bronxriver.org/place/bronx-river-forest-boat',
  'provenance': 'publisher_meeting_directions_with_official_Parks_native_point',
  'approximate': True},
 {'source_key': 'bronx_river_alliance_ny',
  'native_identity': 'Bronx River House (1490 Sheridan Blvd)',
  'venue_name': 'Bronx River House',
  'venue_address': '1490 Sheridan Boulevard, Bronx, NY 10459',
  'venue_city': 'Bronx',
  'lat': 40.832826,
  'lng': -73.882878,
  'evidence_url': 'https://bronxriver.org/visit-the-river/calendar',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False},
 {'source_key': 'bronx_river_alliance_ny',
  'native_identity': '1490 Sheridan Boulevard, Bronx, NY 10459',
  'venue_name': 'Bronx River House',
  'venue_address': '1490 Sheridan Boulevard, Bronx, NY 10459',
  'venue_city': 'Bronx',
  'lat': 40.832826,
  'lng': -73.882878,
  'evidence_url': 'https://bronxriver.org/visit-the-river/calendar',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Across the Grounds',
  'venue_name': 'Wave Hill — Across the Grounds (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Armor Hall',
  'venue_name': 'Wave Hill — Armor Hall (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Glyndor Gallery',
  'venue_name': 'Wave Hill — Glyndor Gallery (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Great Lawn',
  'venue_name': 'Wave Hill — Great Lawn (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Grounds, Armor Hall',
  'venue_name': 'Wave Hill — Grounds, Armor Hall (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Grounds; Armor Hall',
  'venue_name': 'Wave Hill — Grounds; Armor Hall (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Lower Lawn',
  'venue_name': 'Wave Hill — Lower Lawn (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Mark Twain Room, Wave Hill House',
  'venue_name': 'Wave Hill — Mark Twain Room, Wave Hill House (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Meet at Glyndor Gallery',
  'venue_name': 'Wave Hill — Meet at Glyndor Gallery (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Meet at Perkins Visitor Center',
  'venue_name': 'Wave Hill — Meet at Perkins Visitor Center (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Meet at Wave Hill House',
  'venue_name': 'Wave Hill — Meet at Wave Hill House (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'On the grounds',
  'venue_name': 'Wave Hill — On the grounds (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'On the grounds, Wave Hill House',
  'venue_name': 'Wave Hill — On the grounds, Wave Hill House (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Wave Hill',
  'venue_name': 'Wave Hill — Wave Hill (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Wave Hill House Café',
  'venue_name': 'Wave Hill — Wave Hill House Café (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Wave Hill House and Glyndor Gallery',
  'venue_name': 'Wave Hill — Wave Hill House and Glyndor Gallery (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Wave Hill House, Armor Hall',
  'venue_name': 'Wave Hill — Wave Hill House, Armor Hall (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'wave_hill_ny',
  'native_identity': 'Wave Hill House, Mark Twain Room',
  'venue_name': 'Wave Hill — Wave Hill House, Mark Twain Room (approximate meeting point)',
  'venue_address': '4900 Independence Avenue, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.89889,
  'lng': -73.91244,
  'evidence_url': 'https://www.wavehill.org/visit/getting-here',
  'provenance': 'publisher_property_address_and_NYC_PAD_point_interior_meeting_retained',
  'approximate': True},
 {'source_key': 'bkup_brooklyn_ny',
  'native_identity': 'Brooklyn Uprising',
  'venue_name': 'Brooklyn Uprising',
  'venue_address': '20 John Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.704144,
  'lng': -73.987996,
  'evidence_url': 'https://www.bkup.nyc/events',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False},
 {'source_key': 'bkup_brooklyn_ny',
  'native_identity': 'Ritual Moves - Yoga Room',
  'venue_name': 'Ritual Moves - Yoga Room',
  'venue_address': '32 Pearl Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.704144,
  'lng': -73.987996,
  'evidence_url': 'https://www.bkup.nyc/events/edc96bc7-60f0-4dbc-bda1-8fac7a005bc7',
  'provenance': 'publisher_event_specific_yoga_room_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=32+Pearl+Street+Brooklyn+NY11201&size=5'},
 {'source_key': 'brooklyn_bridge_park_ny',
  'native_identity': '18837',
  'venue_name': 'Visitor Center at the Boathouse (approximate meeting point)',
  'venue_address': '10 Montague Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.69580233,
  'lng': -73.99928481,
  'evidence_url': 'https://www.bargemusic.org/about-bargemusic/',
  'provenance': 'publisher_specific_map_location_point_and_official_venue_street',
  'approximate': True,
  'native_lat': '40.69580233',
  'native_lng': '-73.99928481'},
 {'source_key': 'brooklyn_bridge_park_ny',
  'native_identity': '18747',
  'venue_name': 'Environmental Education Center',
  'venue_address': '99 Plymouth Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.7041854,
  'lng': -73.98931477,
  'evidence_url': 'https://brooklynbridgepark.org/places-to-see/environmental-education-center/',
  'provenance': 'publisher_specific_map_location_point_and_official_venue_street',
  'approximate': False,
  'native_lat': '40.7041854',
  'native_lng': '-73.98931477'},
 {'source_key': 'brooklyn_bridge_park_ny',
  'native_identity': '18675',
  'venue_name': 'Emily Warren Roebling Plaza (approximate meeting point)',
  'venue_address': 'Water Street & New Dock Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.70400855,
  'lng': -73.99417998,
  'evidence_url': 'https://brooklynbridgepark.org/places-to-see/emily-warren-roebling-plaza/',
  'provenance': 'publisher_specific_map_location_point_and_official_venue_street',
  'approximate': True,
  'native_lat': '40.70400855',
  'native_lng': '-73.99417998'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Inwood Hill Park',
  'venue_name': 'Inwood Hill Park Open Run (approximate meeting point)',
  'venue_address': 'Isham Street & Seaman Avenue, New York, NY 10034',
  'venue_city': 'New York',
  'lat': 40.87001,
  'lng': -73.92093,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/inwood-hill-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Park entrance at the intersection of Isham Street and Seaman Avenue',
  'native_direction': '40.87001,-73.92093'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': "St. Mary's Park",
  'venue_name': "St. Mary's Park Open Run (approximate meeting point)",
  'venue_address': 'East 149th Street & St. Anns Avenue, Bronx, NY 10455',
  'venue_city': 'Bronx',
  'lat': 40.81315982180905,
  'lng': -73.91369641349353,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/st-marys-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Park Entrance at E 149th Street (Between St. Ann’s Ave and Eagle Ave)',
  'native_direction': '40.81315982180905,-73.91369641349353'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Highland Park',
  'venue_name': 'Highland Park Open Run (approximate meeting point)',
  'venue_address': 'Elton Street & Jamaica Avenue, Brooklyn, NY 11208',
  'venue_city': 'Brooklyn',
  'lat': 40.68386,
  'lng': -73.88575,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/highland-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Park entrance at the intersection of Elton Street and Jamaica Avenue',
  'native_direction': '40.68386,-73.88575'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Morningside Park',
  'venue_name': 'Morningside Park Open Run (approximate meeting point)',
  'venue_address': 'West 110th Street & Manhattan Avenue, New York, NY 10026',
  'venue_city': 'New York',
  'lat': 40.80197,
  'lng': -73.95958,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/morningside-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Park entrance at West 110th Street and Manhattan Avenue (down the stairs)',
  'native_direction': '40.80197,-73.95958'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Cunningham Park',
  'venue_name': 'Cunningham Park Open Run (approximate meeting point)',
  'venue_address': 'Union Turnpike & 196th Street, Queens, NY 11366',
  'venue_city': 'Queens',
  'lat': 40.72948,
  'lng': -73.77369,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/cunningham-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Off Union Turnpike at the comfort station between the tennis courts and baseball fields',
  'native_direction': '40.72948,-73.77369'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Brooklyn Bridge Park',
  'venue_name': 'Brooklyn Bridge Park Open Run (approximate meeting point)',
  'venue_address': 'Atlantic Avenue & Furman Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.69247,
  'lng': -74.00172,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/brooklyn-bridge-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Meet on the south side of Fornino on Pier 6',
  'native_direction': '40.69247,-74.00172'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Shore Road Park',
  'venue_name': 'Shore Road Park Open Run (approximate meeting point)',
  'venue_address': '79th Street & Shore Road, Brooklyn, NY 11209',
  'venue_city': 'Brooklyn',
  'lat': 40.63146,
  'lng': -74.03915,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/shore-road-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Park entrance at 79th Street and Shore Road',
  'native_direction': '40.63146,-74.03915'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Marine Park',
  'venue_name': 'Marine Park Open Run (approximate meeting point)',
  'venue_address': '3000 Fillmore Avenue, Brooklyn, NY 11234',
  'venue_city': 'Brooklyn',
  'lat': 40.6078,
  'lng': -73.93653,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/marine-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Behind the Carmine Carro Community Center on Fillmore Avenue',
  'native_direction': '40.6078,-73.93653'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Crocheron Park',
  'venue_name': 'Crocheron Park Open Run (approximate meeting point)',
  'venue_address': '33rd Road & 215th Place, Queens, NY 11361',
  'venue_city': 'Queens',
  'lat': 40.77219,
  'lng': -73.76949,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/crocheron-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'The comfort station at 33 Road and 215th Place.',
  'native_direction': '40.77219,-73.76949'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Astoria Park',
  'venue_name': 'Astoria Park Open Run (approximate meeting point)',
  'venue_address': 'Hoyt Avenue North & 19th Street, Queens, NY 11102',
  'venue_city': 'Queens',
  'lat': 40.77757,
  'lng': -73.92287,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/astoria-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Next to the track by the comfort station',
  'native_direction': '40.77757,-73.92287'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Conference House Park',
  'venue_name': 'Conference House Park Open Run (approximate meeting point)',
  'venue_address': 'Hylan Boulevard & Satterlee Street, Staten Island, NY 10307',
  'venue_city': 'Staten Island',
  'lat': 40.50275,
  'lng': -74.25207,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/conference-house-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Off Hylan Boulevard, next to parking lot on path leading to the water',
  'native_direction': '40.50275,-74.25207'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Canarsie Park',
  'venue_name': 'Canarsie Park Open Run (approximate meeting point)',
  'venue_address': 'East 88th Street & Seaview Avenue, Brooklyn, NY 11236',
  'venue_city': 'Brooklyn',
  'lat': 40.62911,
  'lng': -73.89616,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/canarsie-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Canarsie Park office on 88th Street and Seaview Avenue (by the flagpole)',
  'native_direction': '40.62911,-73.89616'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Baisley Pond Park',
  'venue_name': 'Baisley Pond Park Open Run (approximate meeting point)',
  'venue_address': 'Baisley Boulevard & 154th Street, Queens, NY 11434',
  'venue_city': 'Queens',
  'lat': 40.67296,
  'lng': -73.78585,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/baisley-pond-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'The cricket field at the intersection of Baisley Pond Blvd and 154th Street',
  'native_direction': '40.67296,-73.78585'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Flushing Meadows Corona Park',
  'venue_name': 'Flushing Meadows Corona Park Open Run (approximate meeting point)',
  'venue_address': '111th Street & 55th Avenue, Queens, NY 11368',
  'venue_city': 'Queens',
  'lat': 40.74271,
  'lng': -73.85008,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/flushing-meadows-corona-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'UN Ave S at 111th St & 55th Ave',
  'native_direction': '40.74271,-73.85008'},
 {'source_key': 'nyrr_open_run_ny',
  'native_identity': 'Soundview Park',
  'venue_name': 'Soundview Park Open Run (approximate meeting point)',
  'venue_address': 'Morrison Avenue & Lafayette Avenue, Bronx, NY 10473',
  'venue_city': 'Bronx',
  'lat': 40.82001,
  'lng': -73.87241,
  'evidence_url': 'https://prod.nyrr.org/races-and-events/2026/soundview-park',
  'provenance': 'publisher_specific_meeting_coordinate_and_named_street_access_with_official_NYC_ZIP',
  'approximate': True,
  'native_meeting': 'Park entrance at the intersection of Morrison Avenue and Lafayette Avenue',
  'native_direction': '40.82001,-73.87241'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '783377',
  'venue_name': '34th Avenue Open Street (approximate meeting point)',
  'venue_address': '34th Avenue & 93rd Street, Queens, NY 11372',
  'venue_city': 'Queens',
  'lat': 40.7547728,
  'lng': -73.8748084,
  'evidence_url': 'https://www.mobilize.us/transalt/event/783377/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': True,
  'native_address_lines': ['34th Avenue & 93rd Street', ''],
  'native_geo': {'latitude': 40.7547728, 'longitude': -73.8748084},
  'native_postal_code': '11372'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '783426',
  'venue_name': '152 E 118th St',
  'venue_address': '152 East 118th Street, New York, NY 10035',
  'venue_city': 'New York',
  'lat': 40.7996662,
  'lng': -73.9402926,
  'evidence_url': 'https://www.mobilize.us/transalt/event/783426/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': False,
  'native_address_lines': ['152 E 118th St', ''],
  'native_geo': {'latitude': 40.7996662, 'longitude': -73.9402926},
  'native_postal_code': '10035'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '783479',
  'venue_name': 'Transportation Alternatives',
  'venue_address': '111 John Street Suite 260, New York, NY 10038',
  'venue_city': 'New York',
  'lat': 40.7078064,
  'lng': -74.0057587,
  'evidence_url': 'https://www.mobilize.us/transalt/event/783479/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': False,
  'native_address_lines': ['111 John St 260', ''],
  'native_geo': {'latitude': 40.7078064, 'longitude': -74.0057587},
  'native_postal_code': '10038'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '878413',
  'venue_name': 'West 125th Street & Adam Clayton Powell Junior Boulevard (approximate meeting point)',
  'venue_address': 'West 125th Street & Adam Clayton Powell Jr Boulevard, New York, NY 10027',
  'venue_city': 'New York',
  'lat': 40.8090181,
  'lng': -73.9484236,
  'evidence_url': 'https://www.mobilize.us/transalt/event/878413/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': True,
  'native_address_lines': ['West 125th Street & Adam Clayton Powell Junior Boulevard', ''],
  'native_geo': {'latitude': 40.8090181, 'longitude': -73.9484236},
  'native_postal_code': '10027'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '1036822',
  'venue_name': 'Say Coffee',
  'venue_address': '346 East 59th Street, New York, NY 10022',
  'venue_city': 'New York',
  'lat': 40.7596217,
  'lng': -73.962299,
  'evidence_url': 'https://www.mobilize.us/transalt/event/1036822/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': False,
  'native_address_lines': ['346 E 59th St', ''],
  'native_geo': {'latitude': 40.7596217, 'longitude': -73.962299},
  'native_postal_code': '10022'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '1075913',
  'venue_name': 'Charles A. Dana Discovery Center (approximate meeting point)',
  'venue_address': 'Central Park North & Fifth Avenue, New York, NY 10029',
  'venue_city': 'New York',
  'lat': 40.7979019,
  'lng': -73.9516428,
  'evidence_url': 'https://www.mobilize.us/transalt/event/1075913/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': True,
  'native_address_lines': ['Central Pk N', ''],
  'native_geo': {'latitude': 40.7979019, 'longitude': -73.9516428},
  'native_postal_code': '10029'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '1080912',
  'venue_name': 'West 116th Street & Riverside Drive (approximate meeting point)',
  'venue_address': 'West 116th Street & Riverside Drive, New York, NY 10027',
  'venue_city': 'New York',
  'lat': 40.8088248,
  'lng': -73.9658006,
  'evidence_url': 'https://www.mobilize.us/transalt/event/1080912/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': True,
  'native_address_lines': ['West 116th Street & Riverside Drive', ''],
  'native_geo': {'latitude': 40.8088248, 'longitude': -73.9658006},
  'native_postal_code': '10027'},
 {'source_key': 'transportation_alternatives_ny',
  'native_identity': '1081297',
  'venue_name': 'Transportation Alternatives',
  'venue_address': '111 John Street, New York, NY 10038',
  'venue_city': 'New York',
  'lat': 40.7074554,
  'lng': -74.0056642,
  'evidence_url': 'https://www.mobilize.us/transalt/event/1081297/',
  'provenance': 'publisher_public_location_address_and_event_specific_point',
  'approximate': False,
  'native_address_lines': ['111 John St', ''],
  'native_geo': {'latitude': 40.7074554, 'longitude': -74.0056642},
  'native_postal_code': '10038'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '9302',
  'venue_name': 'Nitehawk Cinema Prospect Park',
  'venue_address': '188 Prospect Park West, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.661628,
  'lng': -73.979854,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/nitehawk-cinema-prospect-park/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Nitehawk Cinema Prospect Park',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=188+Prospect+Park+West%2C+Brooklyn%2C+NY+11215'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '9700',
  'venue_name': 'Gerritsen Beach Library',
  'venue_address': '2808 Gerritsen Ave, Brooklyn, NY 11229',
  'venue_city': 'Brooklyn',
  'lat': 40.591418,
  'lng': -73.92401,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/gerritsen-beach-library/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Gerritsen Beach Library',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=2808+Gerritsen+Ave%2C+Brooklyn%2C+NY+11229'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '1889',
  'venue_name': 'Principles GI Coffee House',
  'venue_address': '139 9th St, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.672485,
  'lng': -73.992615,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/principles-gi-coffee-house/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Principles GI Coffee House',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=139+9th+St%2C+Brooklyn%2C+NY+11215'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '1665',
  'venue_name': 'P.S. 372 – The Children’s School Gymnasium',
  'venue_address': '215 1st Street, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.675943,
  'lng': -73.985563,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/p-s-372-the-childrens-school-gymnasium/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'P.S. 372 – The Children’s School Gymnasium',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=215+1st+Street%2C+Brooklyn%2C+NY+11215'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '2513',
  'venue_name': 'Christ Church',
  'venue_address': '326 Clinton Street, Brooklyn, NY 11231',
  'venue_city': 'Brooklyn',
  'lat': 40.685805,
  'lng': -73.99675,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/christ-church/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Christ Church',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=326+Clinton+Street%2C+Brooklyn%2C+NY+11231'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '1031',
  'venue_name': 'Van Alen Institute',
  'venue_address': '303 Bond Street, Brooklyn, NY 11231',
  'venue_city': 'Brooklyn',
  'lat': 40.680056,
  'lng': -73.989233,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/van-alen-institute/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Van Alen Institute',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=303+Bond+Street%2C+Brooklyn%2C+NY+11231'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '1794',
  'venue_name': 'PS 15',
  'venue_address': '71 Sullivan Street, Brooklyn, NY 11231',
  'venue_city': 'Brooklyn',
  'lat': 40.676944,
  'lng': -74.011958,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/ps-15/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'PS 15',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=71+Sullivan+Street%2C+Brooklyn%2C+NY+11231'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '9702',
  'venue_name': 'Brooklyn Creative Reuse',
  'venue_address': '254 36th Street Space C244 (Industry City), Brooklyn, NY 11232',
  'venue_city': 'Brooklyn',
  'lat': 40.65623,
  'lng': -74.007951,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/brooklyn-creative-reuse/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Brooklyn Creative Reuse',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=254+36th+Street%2C+Brooklyn%2C+NY+11232'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '1747',
  'venue_name': '78th Precinct',
  'venue_address': '65 6th Avenue, Brooklyn, NY 11217',
  'venue_city': 'Brooklyn',
  'lat': 40.680901,
  'lng': -73.974145,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/78th-precinct/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': '78th Precinct',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=65+6th+Avenue%2C+Brooklyn%2C+NY+11217'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '2505',
  'venue_name': 'Brooklyn Public Library – Red Hook Interim Branch',
  'venue_address': '362 Van Brunt Street, Brooklyn, NY 11231',
  'venue_city': 'Brooklyn',
  'lat': 40.677697,
  'lng': -74.012817,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/brooklyn-public-library-red-hook/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Brooklyn Public Library – Red Hook Interim Branch',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=362+Van+Brunt+Street%2C+Brooklyn%2C+NY+11231'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '2020',
  'venue_name': '250 Baltic Street- Cobble Hill Community Room/ Carroll Gardens Pop-Up Library',
  'venue_address': '250 Baltic Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.686131,
  'lng': -73.994761,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/cobble-hill-community-room/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': '250 Baltic Street- Cobble Hill Community Room/ Carroll Gardens Pop-Up Library',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=250+Baltic+Street%2C+Brooklyn%2C+NY+11201'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '1991',
  'venue_name': 'Brooklyn Borough Hall',
  'venue_address': '209 Joralemon St, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.692768,
  'lng': -73.990298,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/brooklyn-borough-hall/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Brooklyn Borough Hall',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=209+Joralemon+St%2C+Brooklyn%2C+NY+11201'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '9689',
  'venue_name': '240 3rd Avenue',
  'venue_address': '240 3rd Avenue, Brooklyn, NY 11217',
  'venue_city': 'Brooklyn',
  'lat': 40.67879,
  'lng': -73.98565,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/240-3rd-avenue/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': '240 3rd Avenue',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=240+3rd+Avenue%2C+Brooklyn%2C+NY+11217'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '9276',
  'venue_name': 'Hook Studios',
  'venue_address': '161 Dikeman Street, Brooklyn, NY 11231',
  'venue_city': 'Brooklyn',
  'lat': 40.677858,
  'lng': -74.015531,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/hook-studios/',
  'provenance': 'publisher_full_street_and_exact_NYC_PAD_point',
  'approximate': False,
  'native_venue': 'Hook Studios',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=161+Dikeman+Street%2C+Brooklyn%2C+NY+11231'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': 'title:Old Stone House',
  'venue_name': 'Old Stone House',
  'venue_address': '336 3rd Street, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.673008,
  'lng': -73.98462,
  'evidence_url': 'https://theoldstonehouse.org/visit/',
  'provenance': 'publisher_exact_named_venue_with_official_full_street_and_exact_NYC_PAD',
  'approximate': False,
  'native_venue': 'Old Stone House',
  'geocode_evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=336+3rd+Street+Brooklyn+NY+11215&size=4'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': 'title:Grown-Up Bike Bus',
  'venue_name': 'Principles GI Coffee House — ride (approximate meeting point)',
  'venue_address': '139 9th Street, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.672485,
  'lng': -73.992615,
  'evidence_url': 'https://principlesbk.nyc/contact-1',
  'provenance': 'native_title_Thursday8AM_linked_organizer_with_primary_current_street_and_exact_PAD_approximate_ride_meeting',
  'approximate': True,
  'native_venue': 'Principles GI Coffee House'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '2037',
  'venue_name': 'Cobble Hill Park (approximate meeting point)',
  'venue_address': 'Clinton Street & Congress Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.6882115536,
  'lng': -73.9960138019,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/cobble-hill-park/',
  'provenance': 'publisher_named_intersection_and_official_Parks_property_or_NYC_PAD_corner_point',
  'approximate': True,
  'native_venue': 'Cobble Hill Park'},
 {'source_key': 'brooklyn_community_board_6_ny',
  'native_identity': '9687',
  'venue_name': '4th Street Plaza at 5th Avenue (approximate meeting point)',
  'venue_address': '4th Street & 5th Avenue, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.672191,
  'lng': -73.984456,
  'evidence_url': 'https://brooklyncb6.cityofnewyork.us/venue/4th-street-plaza-at-5th-avenue/',
  'provenance': 'publisher_named_intersection_and_official_Parks_property_or_NYC_PAD_corner_point',
  'approximate': True,
  'native_venue': '4th Street Plaza at 5th Avenue'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Newhouse Center for Contemporary Art (Building C) (in Snug Harbor Cultural '
                     'Center)|40.6423952181,-74.1030524026|R116',
  'venue_name': 'Newhouse Center for Contemporary Art (Building C) (in Snug Harbor Cultural Center) (approximate '
                'meeting point)',
  'venue_address': '1000 Richmond Terrace, Staten Island, NY 10301',
  'venue_city': 'Staten Island',
  'lat': 40.6423952181,
  'lng': -74.1030524026,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/14/proximity-exhibition',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Newhouse Center for Contemporary Art (Building C) (in Snug Harbor Cultural Center)',
  'native_point': [40.6423952181, -74.1030524026],
  'native_park_id': 'R116'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Wagner College Pool - Spiro Sports Center|40.614960443787,-74.095867991448|',
  'venue_name': 'Wagner College Pool - Spiro Sports Center (approximate meeting point)',
  'venue_address': '1 Campus Road, Staten Island, NY 10301',
  'venue_city': 'Staten Island',
  'lat': 40.614960443787,
  'lng': -74.095867991448,
  'evidence_url': 'https://wagner.edu/public-safety/files/2018/02/PS-18_PublicSafetyMap-CallBoxes_V1.pdf',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Wagner College Pool - Spiro Sports Center',
  'native_point': [40.614960443787, -74.095867991448],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Conference House Park|40.502601623535,-74.251800537109|R006',
  'venue_name': 'Conference House Park (approximate meeting point)',
  'venue_address': '298 Satterlee Street, Staten Island, NY 10307',
  'venue_city': 'Staten Island',
  'lat': 40.502601623535,
  'lng': -74.251800537109,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Conference House Park',
  'native_point': [40.502601623535, -74.251800537109],
  'native_park_id': 'R006'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Carmine Carro Community Center (in Marine Park)|40.607943945573,-73.937465012074|B057',
  'venue_name': 'Carmine Carro Community Center (in Marine Park)',
  'venue_address': '3000 Fillmore Avenue, Brooklyn, NY 11234',
  'venue_city': 'Brooklyn',
  'lat': 40.607943945573,
  'lng': -73.937465012074,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Carmine Carro Community Center (in Marine Park)',
  'native_point': [40.607943945573, -73.937465012074],
  'native_park_id': 'B057'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Cunningham Park Parking Lot (in Cunningham Park)|40.730899810791016,-73.77400207519531|Q021',
  'venue_name': 'Cunningham Park Parking Lot (in Cunningham Park) (approximate meeting point)',
  'venue_address': 'Union Turnpike & 197th Street, Queens, NY 11366',
  'venue_city': 'Queens',
  'lat': 40.730899810791016,
  'lng': -73.77400207519531,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Cunningham Park Parking Lot (in Cunningham Park)',
  'native_point': [40.730899810791016, -73.77400207519531],
  'native_park_id': 'Q021'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': "Dance Room (in St. John's Park)|40.67350006,-73.93479919|B245",
  'venue_name': "Dance Room (in St. John's Park)",
  'venue_address': '1251 Prospect Place, Brooklyn, NY 11213',
  'venue_city': 'Brooklyn',
  'lat': 40.67350006,
  'lng': -73.93479919,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': "Dance Room (in St. John's Park)",
  'native_point': [40.67350006, -73.93479919],
  'native_park_id': 'B245'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Margaret Corbin Circle (in Fort Tryon Park)|40.859411944915,-73.934134840965|M029',
  'venue_name': 'Margaret Corbin Circle (in Fort Tryon Park) (approximate meeting point)',
  'venue_address': 'Fort Washington Avenue & Margaret Corbin Circle, New York, NY 10040',
  'venue_city': 'New York',
  'lat': 40.859411944915,
  'lng': -73.934134840965,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Margaret Corbin Circle (in Fort Tryon Park)',
  'native_point': [40.859411944915, -73.934134840965],
  'native_park_id': 'M029'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Gatehouse Garden|40.8084977,-73.9596083|',
  'venue_name': 'Gatehouse Garden',
  'venue_address': '1195 Amsterdam Avenue, New York, NY 10027',
  'venue_city': 'New York',
  'lat': 40.8084977,
  'lng': -73.9596083,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Gatehouse Garden',
  'native_point': [40.8084977, -73.9596083],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Harlem Valley Garden|40.81460189819336,-73.94349670410156|',
  'venue_name': 'Harlem Valley Garden',
  'venue_address': '197 West 134th Street, New York, NY 10030',
  'venue_city': 'New York',
  'lat': 40.81460189819336,
  'lng': -73.94349670410156,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Harlem Valley Garden',
  'native_point': [40.81460189819336, -73.94349670410156],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': "Urban Farm (in Randall's Island Park)|40.784213892023,-73.925898551941|M104",
  'venue_name': "Urban Farm (in Randall's Island Park)",
  'venue_address': '11 Wards Meadow Loop, New York, NY 10035',
  'venue_city': 'New York',
  'lat': 40.784213892023,
  'lng': -73.925898551941,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/15/winter-composting-with-big-reuse',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': "Urban Farm (in Randall's Island Park)",
  'native_point': [40.784213892023, -73.925898551941],
  'native_park_id': 'M104'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Greenbelt Nature Center (in Blood Root Valley)|40.588401794434,-74.139099121094|R129',
  'venue_name': 'Greenbelt Nature Center (in Blood Root Valley)',
  'venue_address': '700 Rockland Avenue, Staten Island, NY 10314',
  'venue_city': 'Staten Island',
  'lat': 40.588401794434,
  'lng': -74.139099121094,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Greenbelt Nature Center (in Blood Root Valley)',
  'native_point': [40.588401794434, -74.139099121094],
  'native_park_id': 'R129'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'H.H. Biddle House (in Conference House Park)|40.505546147538,-74.254193782807|R006',
  'venue_name': 'H.H. Biddle House (in Conference House Park)',
  'venue_address': '70 Satterlee Street, Staten Island, NY 10307',
  'venue_city': 'Staten Island',
  'lat': 40.505546147538,
  'lng': -74.254193782807,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'H.H. Biddle House (in Conference House Park)',
  'native_point': [40.505546147538, -74.254193782807],
  'native_park_id': 'R006'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': "Gymnasium (in St. John's Park)|40.67350006,-73.93479919|B245",
  'venue_name': "Gymnasium (in St. John's Park)",
  'venue_address': '1251 Prospect Place, Brooklyn, NY 11213',
  'venue_city': 'Brooklyn',
  'lat': 40.67350006,
  'lng': -73.93479919,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': "Gymnasium (in St. John's Park)",
  'native_point': [40.67350006, -73.93479919],
  'native_park_id': 'B245'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brower Park Lawn (in Brower Park)|40.673487329365,-73.942834436893|B012',
  'venue_name': 'Brower Park Lawn (in Brower Park) (approximate meeting point)',
  'venue_address': '195 Brooklyn Avenue, Brooklyn, NY 11213',
  'venue_city': 'Brooklyn',
  'lat': 40.673487329365,
  'lng': -73.942834436893,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Brower Park Lawn (in Brower Park)',
  'native_point': [40.673487329365, -73.942834436893],
  'native_park_id': 'B012'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'T & T Vernon Block Association Garden|40.694994,-73.94386|',
  'venue_name': 'T & T Vernon Block Association Garden',
  'venue_address': '200 Vernon Avenue, Brooklyn, NY 11206',
  'venue_city': 'Brooklyn',
  'lat': 40.694994,
  'lng': -73.94386,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'T & T Vernon Block Association Garden',
  'native_point': [40.694994, -73.94386],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'North Picnic Area (in Pelham Bay Park)|40.871167346548,-73.790476083755|X039',
  'venue_name': 'North Picnic Area (in Pelham Bay Park) (approximate meeting point)',
  'venue_address': 'Park Drive & Orchard Beach Road, Bronx, NY 10464',
  'venue_city': 'Bronx',
  'lat': 40.871167346548,
  'lng': -73.790476083755,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'North Picnic Area (in Pelham Bay Park)',
  'native_point': [40.871167346548, -73.790476083755],
  'native_park_id': 'X039'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Fort Totten Park Visitors Center (in Fort Totten Park)|40.795606825398,-73.778019666672|Q458',
  'venue_name': 'Fort Totten Park Visitors Center (in Fort Totten Park) (approximate meeting point)',
  'venue_address': '212th Street & Bell Boulevard, Queens, NY 11359',
  'venue_city': 'Queens',
  'lat': 40.795606825398,
  'lng': -73.778019666672,
  'evidence_url': 'https://www.nyc.gov/mayors-office/news/2022/07/mayor-adams-further-expands-city-s-network-at-home-test-distribution-sites-nyc-parks',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Fort Totten Park Visitors Center (in Fort Totten Park)',
  'native_point': [40.795606825398, -73.778019666672],
  'native_park_id': 'Q458'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room (in Williamsbridge Oval)|40.876733907,-73.878591092031|X104',
  'venue_name': 'Multi-Use Room (in Williamsbridge Oval)',
  'venue_address': '3225 Reservoir Oval East, Bronx, NY 10467',
  'venue_city': 'Bronx',
  'lat': 40.876733907,
  'lng': -73.878591092031,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room (in Williamsbridge Oval)',
  'native_point': [40.876733907, -73.878591092031],
  'native_park_id': 'X104'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Seth Low Playground (in Seth Low Playground/ Bealin '
                     'Square)|40.608200073242,-73.986503601074|B100',
  'venue_name': 'Seth Low Playground (in Seth Low Playground/ Bealin Square) (approximate meeting point)',
  'venue_address': '7217 Bay Parkway, Brooklyn, NY 11204',
  'venue_city': 'Brooklyn',
  'lat': 40.608200073242,
  'lng': -73.986503601074,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Seth Low Playground (in Seth Low Playground/ Bealin Square)',
  'native_point': [40.608200073242, -73.986503601074],
  'native_park_id': 'B100'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Conference House Museum (in Conference House Park)|40.50199890136719,-74.25140380859375|R006',
  'venue_name': 'Conference House Museum (in Conference House Park)',
  'venue_address': '298 Satterlee Street, Staten Island, NY 10307',
  'venue_city': 'Staten Island',
  'lat': 40.50199890136719,
  'lng': -74.25140380859375,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Conference House Museum (in Conference House Park)',
  'native_point': [40.50199890136719, -74.25140380859375],
  'native_park_id': 'R006'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Old Stone House (in Washington Park)|40.672939300537,-73.984603881836|B111',
  'venue_name': 'Old Stone House (in Washington Park)',
  'venue_address': '336 Third Street, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.672939300537,
  'lng': -73.984603881836,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Old Stone House (in Washington Park)',
  'native_point': [40.672939300537, -73.984603881836],
  'native_park_id': 'B111'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Fort Greene Park Visitor Center (in Fort Greene Park)|40.69219970703125,-73.97480010986328|B032',
  'venue_name': 'Fort Greene Park Visitor Center (in Fort Greene Park) (approximate meeting point)',
  'venue_address': 'Myrtle Avenue & Washington Park, Brooklyn, NY 11205',
  'venue_city': 'Brooklyn',
  'lat': 40.69219970703125,
  'lng': -73.97480010986328,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/15/historic-new-york-prison-ship-martyrs-monument',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Fort Greene Park Visitor Center (in Fort Greene Park)',
  'native_point': [40.69219970703125, -73.97480010986328],
  'native_park_id': 'B032'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Eton Place Parking Lot (in Willowbrook Park)|40.604227074067,-74.159055948257|R030',
  'venue_name': 'Eton Place Parking Lot (in Willowbrook Park) (approximate meeting point)',
  'venue_address': 'Richmond Avenue & Eton Place, Staten Island, NY 10314',
  'venue_city': 'Staten Island',
  'lat': 40.604227074067,
  'lng': -74.159055948257,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Eton Place Parking Lot (in Willowbrook Park)',
  'native_point': [40.604227074067, -74.159055948257],
  'native_park_id': 'R030'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Inwood Hill Nature Center (in Inwood Hill Park)|40.874000549316406,-73.92009735107422|M042',
  'venue_name': 'Inwood Hill Nature Center (in Inwood Hill Park) (approximate meeting point)',
  'venue_address': 'West 218th Street & Indian Road, New York, NY 10034',
  'venue_city': 'New York',
  'lat': 40.874000549316406,
  'lng': -73.92009735107422,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/15/inwood-interplay-arts-and-science-weekend',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Inwood Hill Nature Center (in Inwood Hill Park)',
  'native_point': [40.874000549316406, -73.92009735107422],
  'native_park_id': 'M042'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Cafe Lawn (in Fort Tryon Park)|40.860198974609375,-73.93309783935547|M029',
  'venue_name': 'Cafe Lawn (in Fort Tryon Park) (approximate meeting point)',
  'venue_address': '1 Margaret Corbin Drive, New York, NY 10040',
  'venue_city': 'New York',
  'lat': 40.860198974609375,
  'lng': -73.93309783935547,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/15/battle-of-fort-washington',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Cafe Lawn (in Fort Tryon Park)',
  'native_point': [40.860198974609375, -73.93309783935547],
  'native_park_id': 'M029'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'West 218th Street and Indian Road (in Inwood Hill Park)|40.873013267738,-73.918452858924|M042',
  'venue_name': 'West 218th Street and Indian Road (in Inwood Hill Park)',
  'venue_address': 'West 218th Street & Indian Road, New York, NY 10034',
  'venue_city': 'New York',
  'lat': 40.873013267738,
  'lng': -73.918452858924,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'West 218th Street and Indian Road (in Inwood Hill Park)',
  'native_point': [40.873013267738, -73.918452858924],
  'native_park_id': 'M042'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Public Restroom Building - 164th St and Lithonia Ave (in Kissena '
                     'Park)|40.749037767722,-73.803719761346|Q024',
  'venue_name': 'Public Restroom Building - 164th St and Lithonia Ave (in Kissena Park)',
  'venue_address': '164th Street & Lithonia Avenue, Queens, NY 11358',
  'venue_city': 'Queens',
  'lat': 40.749037767722,
  'lng': -73.803719761346,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/15/natures-workshop-bird-friendly-windows',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Public Restroom Building - 164th St and Lithonia Ave (in Kissena Park)',
  'native_point': [40.749037767722, -73.803719761346],
  'native_park_id': 'q024'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Crotona Nature Center (in Crotona Park)|40.837001800537,-73.893402099609|X010',
  'venue_name': 'Crotona Nature Center (in Crotona Park) (approximate meeting point)',
  'venue_address': 'Crotona Park East & Charlotte Street, Bronx, NY 10460',
  'venue_city': 'Bronx',
  'lat': 40.837001800537,
  'lng': -73.893402099609,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Crotona Nature Center (in Crotona Park)',
  'native_point': [40.837001800537, -73.893402099609],
  'native_park_id': 'X010'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Hester Street Park House (in Sara D. Roosevelt Park)|40.716780922314,-73.994062882493|M105',
  'venue_name': 'Hester Street Park House (in Sara D. Roosevelt Park) (approximate meeting point)',
  'venue_address': 'Hester Street & Chrystie Street, New York, NY 10002',
  'venue_city': 'New York',
  'lat': 40.716780922314,
  'lng': -73.994062882493,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/15/its-my-park-at-sara-d-roosevelt-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Hester Street Park House (in Sara D. Roosevelt Park)',
  'native_point': [40.716780922314, -73.994062882493],
  'native_park_id': 'M105'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Bountiful Bliss Community Garden|40.628515,-73.934395|',
  'venue_name': 'Bountiful Bliss Community Garden',
  'venue_address': '1087 East 43rd Street, Brooklyn, NY 11210',
  'venue_city': 'Brooklyn',
  'lat': 40.628515,
  'lng': -73.934395,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Bountiful Bliss Community Garden',
  'native_point': [40.628515, -73.934395],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': "Merchant's House Museum|40.727699279785156,-73.99230194091797|M318",
  'venue_name': "Merchant's House Museum",
  'venue_address': '29 East 4th Street, New York, NY 10003',
  'venue_city': 'New York',
  'lat': 40.727699279785156,
  'lng': -73.99230194091797,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': "Merchant's House Museum",
  'native_point': [40.727699279785156, -73.99230194091797],
  'native_park_id': 'M318'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Bayside Historical Society (in Fort Totten Park)|40.792235644025,-73.77775144577|Q458',
  'venue_name': 'Bayside Historical Society (in Fort Totten Park)',
  'venue_address': '208 Totten Avenue, Queens, NY 11359',
  'venue_city': 'Queens',
  'lat': 40.792235644025,
  'lng': -73.77775144577,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Bayside Historical Society (in Fort Totten Park)',
  'native_point': [40.792235644025, -73.77775144577],
  'native_park_id': 'Q458'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Athletic Courts (in Torsney Playground)|40.747336617996,-73.921119214382|Q340',
  'venue_name': 'Athletic Courts (in Torsney Playground) (approximate meeting point)',
  'venue_address': '41-15 Skillman Avenue, Queens, NY 11104',
  'venue_city': 'Queens',
  'lat': 40.747336617996,
  'lng': -73.921119214382,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Athletic Courts (in Torsney Playground)',
  'native_point': [40.747336617996, -73.921119214382],
  'native_park_id': 'Q340'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'New York Public Library - Morningside Heights Branch|40.806144714355,-73.964828491211|',
  'venue_name': 'New York Public Library - Morningside Heights Branch',
  'venue_address': '2900 Broadway, New York, NY 10025',
  'venue_city': 'New York',
  'lat': 40.806144714355,
  'lng': -73.964828491211,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'New York Public Library - Morningside Heights Branch',
  'native_point': [40.806144714355, -73.964828491211],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Jacob H. Schiff Play Area (in Jacob H. Schiff Playground)|40.820499420166,-73.952003479004|M223',
  'venue_name': 'Jacob H. Schiff Play Area (in Jacob H. Schiff Playground) (approximate meeting point)',
  'venue_address': '1540 Amsterdam Avenue, New York, NY 10031',
  'venue_city': 'New York',
  'lat': 40.820499420166,
  'lng': -73.952003479004,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Jacob H. Schiff Play Area (in Jacob H. Schiff Playground)',
  'native_point': [40.820499420166, -73.952003479004],
  'native_park_id': 'M223'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': '102nd Street Field House (in Riverside Park)|40.800691692826,-73.973306179047|M072',
  'venue_name': '102nd Street Field House (in Riverside Park) (approximate meeting point)',
  'venue_address': 'Riverside Drive & West 102nd Street, New York, NY 10025',
  'venue_city': 'New York',
  'lat': 40.800691692826,
  'lng': -73.973306179047,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/16/riverside-field-house-fall-bodyroll',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': '102nd Street Field House (in Riverside Park)',
  'native_point': [40.800691692826, -73.973306179047],
  'native_park_id': 'M072'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Sunnyside Community Services|40.7451662,-73.9256081|',
  'venue_name': 'Sunnyside Community Services',
  'venue_address': '43-31 39th Street, Queens, NY 11104',
  'venue_city': 'Queens',
  'lat': 40.7451662,
  'lng': -73.9256081,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Sunnyside Community Services',
  'native_point': [40.7451662, -73.9256081],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Le Carrousel (in Bryant Park)|40.753299713135,-73.984001159668|M008',
  'venue_name': 'Le Carrousel (in Bryant Park) (approximate meeting point)',
  'venue_address': 'West 40th Street & Sixth Avenue, New York, NY 10018',
  'venue_city': 'New York',
  'lat': 40.753299713135,
  'lng': -73.984001159668,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Le Carrousel (in Bryant Park)',
  'native_point': [40.753299713135, -73.984001159668],
  'native_park_id': 'M008'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library- Gerritsen Beach|40.5913411,-73.9240055|',
  'venue_name': 'Brooklyn Public Library- Gerritsen Beach',
  'venue_address': '2808 Gerritsen Avenue, Brooklyn, NY 11229',
  'venue_city': 'Brooklyn',
  'lat': 40.5913411,
  'lng': -73.9240055,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library- Gerritsen Beach',
  'native_point': [40.5913411, -73.9240055],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Bayside|40.7601617,-73.7683806|',
  'venue_name': 'Queens Public Library - Bayside',
  'venue_address': '214-20 Northern Boulevard, Queens, NY 11361',
  'venue_city': 'Queens',
  'lat': 40.7601617,
  'lng': -73.7683806,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Bayside',
  'native_point': [40.7601617, -73.7683806],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Abib Newborn Garden|40.659581894292,-73.906001950262|',
  'venue_name': 'Abib Newborn Garden',
  'venue_address': '495 Osborn Street, Brooklyn, NY 11212',
  'venue_city': 'Brooklyn',
  'lat': 40.659581894292,
  'lng': -73.906001950262,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Abib Newborn Garden',
  'native_point': [40.659581894292, -73.906001950262],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Dance Room (in Chelsea Recreation Center)|40.74829865,-74.00219727|M260',
  'venue_name': 'Dance Room (in Chelsea Recreation Center)',
  'venue_address': '430 West 25th Street, New York, NY 10001',
  'venue_city': 'New York',
  'lat': 40.74829865,
  'lng': -74.00219727,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Dance Room (in Chelsea Recreation Center)',
  'native_point': [40.74829865, -74.00219727],
  'native_park_id': 'M260'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'MVMNT Fitness and Health Studio|40.661722130567,-73.96136879921|',
  'venue_name': 'MVMNT Fitness and Health Studio',
  'venue_address': '510 Flatbush Avenue, Brooklyn, NY 11225',
  'venue_city': 'Brooklyn',
  'lat': 40.661722130567,
  'lng': -73.96136879921,
  'evidence_url': 'https://nycgovparks.org/events/2026/11/02/bodyweight-circuit-training',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'MVMNT Fitness and Health Studio',
  'native_point': [40.661722130567, -73.96136879921],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Our Lady of Grace Roman Catholic Church|40.660504936375,-73.832638487255|',
  'venue_name': 'Our Lady of Grace Roman Catholic Church',
  'venue_address': '100-05 159th Avenue, Queens, NY 11414',
  'venue_city': 'Queens',
  'lat': 40.660504936375,
  'lng': -73.832638487255,
  'evidence_url': 'https://data.cityofnewyork.us/api/views/hyur-qpyf/rows.pdf',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Our Lady of Grace Roman Catholic Church',
  'native_point': [40.660504936375, -73.832638487255],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brownsville Neighborhood Health Action Center|40.6646618,-73.9111354|',
  'venue_name': 'Brownsville Neighborhood Health Action Center',
  'venue_address': '259 Bristol Street, Brooklyn, NY 11212',
  'venue_city': 'Brooklyn',
  'lat': 40.6646618,
  'lng': -73.9111354,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brownsville Neighborhood Health Action Center',
  'native_point': [40.6646618, -73.9111354],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room C (in McCarren Park)|40.7201004,-73.94999695|B058',
  'venue_name': 'Multi-Use Room C (in McCarren Park)',
  'venue_address': '776 Lorimer Street, Brooklyn, NY 11222',
  'venue_city': 'Brooklyn',
  'lat': 40.7201004,
  'lng': -73.94999695,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room C (in McCarren Park)',
  'native_point': [40.7201004, -73.94999695],
  'native_park_id': 'B058'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room (in Asser Levy Playground)|40.73609924,-73.97570038|M164',
  'venue_name': 'Multi-Use Room (in Asser Levy Playground)',
  'venue_address': '392 Asser Levy Place, New York, NY 10010',
  'venue_city': 'New York',
  'lat': 40.73609924,
  'lng': -73.97570038,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Multi-Use Room (in Asser Levy Playground)',
  'native_point': [40.73609924, -73.97570038],
  'native_park_id': 'M164'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Ryan Health- Chelsea Clinton Community Health Center|40.762044859544,-73.993928864383|',
  'venue_name': 'Ryan Health- Chelsea Clinton Community Health Center',
  'venue_address': '645 Tenth Avenue, New York, NY 10036',
  'venue_city': 'New York',
  'lat': 40.762044859544,
  'lng': -73.993928864383,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Ryan Health- Chelsea Clinton Community Health Center',
  'native_point': [40.762044859544, -73.993928864383],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Fort Totten Park-Building 422 - NE Queens Headquarters (in Fort Totten '
                     'Park)|40.792996979067,-73.776700019836|Q458',
  'venue_name': 'Fort Totten Park-Building 422 - NE Queens Headquarters (in Fort Totten Park)',
  'venue_address': '422 Weaver Avenue, Queens, NY 11359',
  'venue_city': 'Queens',
  'lat': 40.792996979067,
  'lng': -73.776700019836,
  'evidence_url': 'https://nycgovparks.org/events/2026/11/02/yoga',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Fort Totten Park-Building 422 - NE Queens Headquarters (in Fort Totten Park)',
  'native_point': [40.792996979067, -73.776700019836],
  'native_park_id': 'Q458'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Bartow Community Center - Room 31|40.8704537,-73.8291111|',
  'venue_name': 'Bartow Community Center - Room 31',
  'venue_address': '2049 Bartow Avenue, Bronx, NY 10475',
  'venue_city': 'Bronx',
  'lat': 40.8704537,
  'lng': -73.8291111,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Bartow Community Center - Room 31',
  'native_point': [40.8704537, -73.8291111],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room - Cellar (in Sorrentino Recreation Center)|40.60240173,-73.76249695|Q446',
  'venue_name': 'Multi-Use Room - Cellar (in Sorrentino Recreation Center) (approximate meeting point)',
  'venue_address': '18-48 Cornaga Avenue, Queens, NY 11691',
  'venue_city': 'Queens',
  'lat': 40.602443,
  'lng': -73.751375,
  'evidence_url': 'https://www.nyc.gov/site/queenscb14/resources/youth-services.page',
  'provenance': 'exact_named_facility_street_and_NYC_PAD_point_correct_native_pin_about950m_west',
  'approximate': True,
  'native_name': 'Multi-Use Room - Cellar (in Sorrentino Recreation Center)',
  'native_point': [40.60240173, -73.76249695],
  'native_park_id': 'Q446'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Marcus Garvey Park|40.804508209229,-73.943664550781|M058',
  'venue_name': 'Marcus Garvey Park (approximate meeting point)',
  'venue_address': '18 Mount Morris Park West, New York, NY 10027',
  'venue_city': 'New York',
  'lat': 40.804508209229,
  'lng': -73.943664550781,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Marcus Garvey Park',
  'native_point': [40.804508209229, -73.943664550781],
  'native_park_id': 'M058'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Dance Room (in Constance Baker Motley Recreation Center)|40.75646973,-73.9651413|M130',
  'venue_name': 'Dance Room (in Constance Baker Motley Recreation Center)',
  'venue_address': '348 East 54th Street, New York, NY 10022',
  'venue_city': 'New York',
  'lat': 40.75646973,
  'lng': -73.9651413,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Dance Room (in Constance Baker Motley Recreation Center)',
  'native_point': [40.75646973, -73.9651413],
  'native_park_id': 'M130'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Dance Room (in Highbridge Park)|40.84260178,-73.93430328|M037',
  'venue_name': 'Dance Room (in Highbridge Park)',
  'venue_address': '2301 Amsterdam Avenue, New York, NY 10032',
  'venue_city': 'New York',
  'lat': 40.84260178,
  'lng': -73.93430328,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Dance Room (in Highbridge Park)',
  'native_point': [40.84260178, -73.93430328],
  'native_park_id': 'M037'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Concrete Plant Park|40.826900482177734,-73.88480377197266|X305',
  'venue_name': 'Concrete Plant Park (approximate meeting point)',
  'venue_address': '1370 Westchester Avenue, Bronx, NY 10472',
  'venue_city': 'Bronx',
  'lat': 40.826900482177734,
  'lng': -73.88480377197266,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/17/tuesday-stewardship-at-the-foodway',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Concrete Plant Park',
  'native_point': [40.826900482177734, -73.88480377197266],
  'native_park_id': 'X305'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Bowne Park Field House (in Bowne Park)|40.770500183105,-73.80729675293|Q006',
  'venue_name': 'Bowne Park Field House (in Bowne Park) (approximate meeting point)',
  'venue_address': '155-01 32nd Avenue, Queens, NY 11354',
  'venue_city': 'Queens',
  'lat': 40.770500183105,
  'lng': -73.80729675293,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Bowne Park Field House (in Bowne Park)',
  'native_point': [40.770500183105, -73.80729675293],
  'native_park_id': 'Q006'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Rutan-Becket House (in Conference House Park)|40.504737562051,-74.254861831665|R006',
  'venue_name': 'Rutan-Becket House (in Conference House Park)',
  'venue_address': '6 Shore Road, Staten Island, NY 10307',
  'venue_city': 'Staten Island',
  'lat': 40.504737562051,
  'lng': -74.254861831665,
  'evidence_url': 'https://nycgovparks.org/events/2026/11/13/ongoing-museum-exhibit-still-waters-reflections-of-a-maritime-community',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Rutan-Becket House (in Conference House Park)',
  'native_point': [40.504737562051, -74.254861831665],
  'native_park_id': 'R006'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queensbridge Park House (in Queensbridge Park)|40.755045994592,-73.949578225613|Q104',
  'venue_name': 'Queensbridge Park House (in Queensbridge Park) (approximate meeting point)',
  'venue_address': '40-50 Vernon Boulevard, Queens, NY 11101',
  'venue_city': 'Queens',
  'lat': 40.755045994592,
  'lng': -73.949578225613,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Queensbridge Park House (in Queensbridge Park)',
  'native_point': [40.755045994592, -73.949578225613],
  'native_park_id': 'Q104'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Sonia Sotomayor Community Center|40.825536,-73.867359|',
  'venue_name': 'Sonia Sotomayor Community Center',
  'venue_address': '1000 Rosedale Avenue, Bronx, NY 10472',
  'venue_city': 'Bronx',
  'lat': 40.825536,
  'lng': -73.867359,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Sonia Sotomayor Community Center',
  'native_point': [40.825536, -73.867359],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Gymnasium (in Gertrude Ederle Recreation Center)|40.77149963,-73.9885025|M063',
  'venue_name': 'Gymnasium (in Gertrude Ederle Recreation Center)',
  'venue_address': '232 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.77149963,
  'lng': -73.9885025,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Gymnasium (in Gertrude Ederle Recreation Center)',
  'native_point': [40.77149963, -73.9885025],
  'native_park_id': 'M063'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Dance Room (in Jackie Robinson Park)|40.82419968,-73.94249725|M014',
  'venue_name': 'Dance Room (in Jackie Robinson Park)',
  'venue_address': '85 Bradhurst Avenue, New York, NY 10039',
  'venue_city': 'New York',
  'lat': 40.82419968,
  'lng': -73.94249725,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Dance Room (in Jackie Robinson Park)',
  'native_point': [40.82419968, -73.94249725],
  'native_park_id': 'M014'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Corona|40.751004375974,-73.861925057672|',
  'venue_name': 'Queens Public Library - Corona',
  'venue_address': '38-23 104th Street, Queens, NY 11368',
  'venue_city': 'Queens',
  'lat': 40.751004375974,
  'lng': -73.861925057672,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Corona',
  'native_point': [40.751004375974, -73.861925057672],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Seaside|40.5794149,-73.8377884|',
  'venue_name': 'Queens Public Library - Seaside',
  'venue_address': '116-15 Rockaway Beach Boulevard, Queens, NY 11694',
  'venue_city': 'Queens',
  'lat': 40.5794149,
  'lng': -73.8377884,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Seaside',
  'native_point': [40.5794149, -73.8377884],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYPL- Bloomingdale Library|40.795944213867,-73.967864990234|',
  'venue_name': 'NYPL- Bloomingdale Library',
  'venue_address': '150 West 100th Street, New York, NY 10025',
  'venue_city': 'New York',
  'lat': 40.795944213867,
  'lng': -73.967864990234,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYPL- Bloomingdale Library',
  'native_point': [40.795944213867, -73.967864990234],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Flatbush|40.65189722298,-73.958265781403|',
  'venue_name': 'Brooklyn Public Library - Flatbush',
  'venue_address': '22 Linden Boulevard, Brooklyn, NY 11226',
  'venue_city': 'Brooklyn',
  'lat': 40.65189722298,
  'lng': -73.958265781403,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Flatbush',
  'native_point': [40.65189722298, -73.958265781403],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYC Department of Health and Mental Hygiene- Bedford-Stuyvesant Center|40.6855549,-73.9411715|',
  'venue_name': 'NYC Department of Health and Mental Hygiene- Bedford-Stuyvesant Center',
  'venue_address': '485 Throop Avenue, Brooklyn, NY 11221',
  'venue_city': 'Brooklyn',
  'lat': 40.6855549,
  'lng': -73.9411715,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYC Department of Health and Mental Hygiene- Bedford-Stuyvesant Center',
  'native_point': [40.6855549, -73.9411715],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'P.S. 361 Beacon - Woodside on the Move|40.747644,-73.9056932|',
  'venue_name': 'P.S. 361 Beacon - Woodside on the Move',
  'venue_address': '39-07 57th Street, Queens, NY 11377',
  'venue_city': 'Queens',
  'lat': 40.747644,
  'lng': -73.9056932,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'P.S. 361 Beacon - Woodside on the Move',
  'native_point': [40.747644, -73.9056932],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Central Park Gardens - Community Room|40.7928133,-73.9657847|',
  'venue_name': 'Central Park Gardens - Community Room',
  'venue_address': '50 West 97th Street, New York, NY 10025',
  'venue_city': 'New York',
  'lat': 40.7928133,
  'lng': -73.9657847,
  'evidence_url': 'https://nycgovparks.org/events/2026/11/03/tone-up-tuesday',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Central Park Gardens - Community Room',
  'native_point': [40.7928133, -73.9657847],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'East Flatbush Village, Inc|40.648339760454,-73.929733514786|',
  'venue_name': 'East Flatbush Village, Inc',
  'venue_address': '1011 Utica Avenue, Brooklyn, NY 11203',
  'venue_city': 'Brooklyn',
  'lat': 40.648339760454,
  'lng': -73.929733514786,
  'evidence_url': 'https://eastflatbushvillage.org/contact-us/',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'East Flatbush Village, Inc',
  'native_point': [40.648339760454, -73.929733514786],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Pier 6 (in Brooklyn Bridge Park)|40.692914780123,-74.00262928009|B431',
  'venue_name': 'Pier 6 (in Brooklyn Bridge Park) (approximate meeting point)',
  'venue_address': 'Atlantic Avenue & Furman Street, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.692914780123,
  'lng': -74.00262928009,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/17/nyrr-open-run-brooklyn-bridge-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Pier 6 (in Brooklyn Bridge Park)',
  'native_point': [40.692914780123, -74.00262928009],
  'native_park_id': 'B431'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Golden Age Classroom B (in Brownsville Playground)|40.65660095,-73.90200043|B270',
  'venue_name': 'Golden Age Classroom B (in Brownsville Playground)',
  'venue_address': '1555 Linden Boulevard, Brooklyn, NY 11212',
  'venue_city': 'Brooklyn',
  'lat': 40.65660095,
  'lng': -73.90200043,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Golden Age Classroom B (in Brownsville Playground)',
  'native_point': [40.65660095, -73.90200043],
  'native_park_id': 'B270'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Woodlawn Playground (in Van Cortlandt Park)|40.900284167492,-73.872265726328|X092',
  'venue_name': 'Woodlawn Playground (in Van Cortlandt Park) (approximate meeting point)',
  'venue_address': 'Van Cortlandt Park East & Kepler Avenue, Bronx, NY 10470',
  'venue_city': 'Bronx',
  'lat': 40.900284167492,
  'lng': -73.872265726328,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Woodlawn Playground (in Van Cortlandt Park)',
  'native_point': [40.900284167492, -73.872265726328],
  'native_park_id': 'X092'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Crotona Tennis House (in Crotona Park)|40.840147765856,-73.895328640938|X010',
  'venue_name': 'Crotona Tennis House (in Crotona Park)',
  'venue_address': '1700 Crotona Avenue, Bronx, NY 10457',
  'venue_city': 'Bronx',
  'lat': 40.840147765856,
  'lng': -73.895328640938,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Crotona Tennis House (in Crotona Park)',
  'native_point': [40.840147765856, -73.895328640938],
  'native_park_id': 'X010'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'New Settlement Community Center|40.84238815307617,-73.91618347167969|',
  'venue_name': 'New Settlement Community Center',
  'venue_address': '1501 Jerome Avenue, Bronx, NY 10452',
  'venue_city': 'Bronx',
  'lat': 40.84238815307617,
  'lng': -73.91618347167969,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'New Settlement Community Center',
  'native_point': [40.84238815307617, -73.91618347167969],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room A (in Detective Keith L Williams Park)|40.701840811682,-73.783516763806|Q121',
  'venue_name': 'Multi-Use Room A (in Detective Keith L Williams Park)',
  'venue_address': '106-16 173rd Street, Queens, NY 11433',
  'venue_city': 'Queens',
  'lat': 40.701840811682,
  'lng': -73.783516763806,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room A (in Detective Keith L Williams Park)',
  'native_point': [40.701840811682, -73.783516763806],
  'native_park_id': 'Q121'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Kings Highway Branch|40.610279539608,-73.953201770783|',
  'venue_name': 'Brooklyn Public Library - Kings Highway Branch',
  'venue_address': '2115 Ocean Avenue, Brooklyn, NY 11229',
  'venue_city': 'Brooklyn',
  'lat': 40.610279539608,
  'lng': -73.953201770783,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Kings Highway Branch',
  'native_point': [40.610279539608, -73.953201770783],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Fantasy Garden|40.664391839814,-73.916898299372|',
  'venue_name': 'Fantasy Garden',
  'venue_address': '181 Legion Street, Brooklyn, NY 11212',
  'venue_city': 'Brooklyn',
  'lat': 40.664391839814,
  'lng': -73.916898299372,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Fantasy Garden',
  'native_point': [40.664391839814, -73.916898299372],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Arts and Crafts Room (in Blood Root Valley)|40.5919826,-74.13947248|R129',
  'venue_name': 'Arts and Crafts Room (in Blood Root Valley)',
  'venue_address': '501 Brielle Avenue, Staten Island, NY 10314',
  'venue_city': 'Staten Island',
  'lat': 40.5919826,
  'lng': -74.13947248,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Arts and Crafts Room (in Blood Root Valley)',
  'native_point': [40.5919826, -74.13947248],
  'native_park_id': 'R129'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYPL - George Bruce|40.813846588135,-73.956886291504|',
  'venue_name': 'NYPL - George Bruce',
  'venue_address': '518 West 125th Street, New York, NY 10027',
  'venue_city': 'New York',
  'lat': 40.813846588135,
  'lng': -73.956886291504,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYPL - George Bruce',
  'native_point': [40.813846588135, -73.956886291504],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYC Department of Health and Mental Hygiene- East Harlem Neighborhood Health Action '
                     'Center|40.797615,-73.9419066|',
  'venue_name': 'NYC Department of Health and Mental Hygiene- East Harlem Neighborhood Health Action Center',
  'venue_address': '158 East 115th Street, New York, NY 10029',
  'venue_city': 'New York',
  'lat': 40.797615,
  'lng': -73.9419066,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYC Department of Health and Mental Hygiene- East Harlem Neighborhood Health Action Center',
  'native_point': [40.797615, -73.9419066],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room A (in McCarren Park)|40.7201004,-73.94999695|B058',
  'venue_name': 'Multi-Use Room A (in McCarren Park)',
  'venue_address': '776 Lorimer Street, Brooklyn, NY 11222',
  'venue_city': 'Brooklyn',
  'lat': 40.7201004,
  'lng': -73.94999695,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room A (in McCarren Park)',
  'native_point': [40.7201004, -73.94999695],
  'native_park_id': 'B058'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Hudson Guild Fulton Community Center|40.74329634805,-74.004046916962|',
  'venue_name': 'Hudson Guild Fulton Community Center',
  'venue_address': '119 Ninth Avenue, New York, NY 10011',
  'venue_city': 'New York',
  'lat': 40.74329634805,
  'lng': -74.004046916962,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Hudson Guild Fulton Community Center',
  'native_point': [40.74329634805, -74.004046916962],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Gymnasium (in Highbridge Park)|40.84260178,-73.93430328|M037',
  'venue_name': 'Gymnasium (in Highbridge Park)',
  'venue_address': '2301 Amsterdam Avenue, New York, NY 10032',
  'venue_city': 'New York',
  'lat': 40.84260178,
  'lng': -73.93430328,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Gymnasium (in Highbridge Park)',
  'native_point': [40.84260178, -73.93430328],
  'native_park_id': 'M037'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Astoria Love Family Enrichment Center|40.764049476746,-73.924003243447|',
  'venue_name': 'Astoria Love Family Enrichment Center',
  'venue_address': '31-16 31st Street, Queens, NY 11106',
  'venue_city': 'Queens',
  'lat': 40.764049476746,
  'lng': -73.924003243447,
  'evidence_url': 'https://astorialove.org/',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Astoria Love Family Enrichment Center',
  'native_point': [40.764049476746, -73.924003243447],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Dance Room (in Thomas Jefferson Park)|40.79349899,-73.93669891|M047',
  'venue_name': 'Dance Room (in Thomas Jefferson Park)',
  'venue_address': '2180 First Avenue, New York, NY 10029',
  'venue_city': 'New York',
  'lat': 40.79349899,
  'lng': -73.93669891,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Dance Room (in Thomas Jefferson Park)',
  'native_point': [40.79349899, -73.93669891],
  'native_park_id': 'M047'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room - Full (in A.R.R.O.W. Field House)|40.755894029168,-73.926240560102|Q470',
  'venue_name': 'Multi-Use Room - Full (in A.R.R.O.W. Field House)',
  'venue_address': '35-30 35th Street, Queens, NY 11106',
  'venue_city': 'Queens',
  'lat': 40.755894029168,
  'lng': -73.926240560102,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room - Full (in A.R.R.O.W. Field House)',
  'native_point': [40.755894029168, -73.926240560102],
  'native_park_id': 'Q470'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'VCPA Learning Garden (in Van Cortlandt Park)|40.886100769043,-73.897499084473|X092',
  'venue_name': 'VCPA Learning Garden (in Van Cortlandt Park) (approximate meeting point)',
  'venue_address': 'Broadway & Van Cortlandt Park South, Bronx, NY 10463',
  'venue_city': 'Bronx',
  'lat': 40.886100769043,
  'lng': -73.897499084473,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/19/trail-work-thursdays-volunteer-trail-care-at-van-cortlandt-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'VCPA Learning Garden (in Van Cortlandt Park)',
  'native_point': [40.886100769043, -73.897499084473],
  'native_park_id': 'X092'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Buddy Monument (in Forest Park)|40.70133568698,-73.841577112675|Q015',
  'venue_name': 'Buddy Monument (in Forest Park) (approximate meeting point)',
  'venue_address': 'Park Lane South & Myrtle Avenue, Queens, NY 11418',
  'venue_city': 'Queens',
  'lat': 40.70133568698,
  'lng': -73.841577112675,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Buddy Monument (in Forest Park)',
  'native_point': [40.70133568698, -73.841577112675],
  'native_park_id': 'Q015'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Park Slope|40.6682174,-73.9834162|',
  'venue_name': 'Brooklyn Public Library - Park Slope',
  'venue_address': '431 Sixth Avenue, Brooklyn, NY 11215',
  'venue_city': 'Brooklyn',
  'lat': 40.6682174,
  'lng': -73.9834162,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Park Slope',
  'native_point': [40.6682174, -73.9834162],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'High Rock Gate (in High Rock Park)|40.58380126953125,-74.12329864501953|R088',
  'venue_name': 'High Rock Gate (in High Rock Park) (approximate meeting point)',
  'venue_address': '200 Nevada Avenue, Staten Island, NY 10306',
  'venue_city': 'Staten Island',
  'lat': 40.58380126953125,
  'lng': -74.12329864501953,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'High Rock Gate (in High Rock Park)',
  'native_point': [40.58380126953125, -74.12329864501953],
  'native_park_id': 'R088'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room B (in Detective Keith L Williams Park)|40.701861403994,-73.783501005828|Q121',
  'venue_name': 'Multi-Use Room B (in Detective Keith L Williams Park)',
  'venue_address': '106-16 173rd Street, Queens, NY 11433',
  'venue_city': 'Queens',
  'lat': 40.701861403994,
  'lng': -73.783501005828,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room B (in Detective Keith L Williams Park)',
  'native_point': [40.701861403994, -73.783501005828],
  'native_park_id': 'Q121'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Success Garden - East New York|40.6648739,-73.8975101|',
  'venue_name': 'Success Garden - East New York',
  'venue_address': '461 Williams Avenue, Brooklyn, NY 11207',
  'venue_city': 'Brooklyn',
  'lat': 40.6648739,
  'lng': -73.8975101,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Success Garden - East New York',
  'native_point': [40.6648739, -73.8975101],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYPL - Spuyten Duyvil|40.886241912842,-73.91463470459|',
  'venue_name': 'NYPL - Spuyten Duyvil',
  'venue_address': '650 West 235th Street, Bronx, NY 10463',
  'venue_city': 'Bronx',
  'lat': 40.886241912842,
  'lng': -73.91463470459,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYPL - Spuyten Duyvil',
  'native_point': [40.886241912842, -73.91463470459],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'P.S./I.S. 109|40.636395,-73.9333185|',
  'venue_name': 'P.S./I.S. 109',
  'venue_address': '1001 East 45th Street, Brooklyn, NY 11203',
  'venue_city': 'Brooklyn',
  'lat': 40.636395,
  'lng': -73.9333185,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'P.S./I.S. 109',
  'native_point': [40.636395, -73.9333185],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Richmond Hill|40.70080998243,-73.831687512611|',
  'venue_name': 'Queens Public Library - Richmond Hill',
  'venue_address': '118-14 Hillside Avenue, Queens, NY 11418',
  'venue_city': 'Queens',
  'lat': 40.70080998243,
  'lng': -73.831687512611,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Richmond Hill',
  'native_point': [40.70080998243, -73.831687512611],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Rochdale Village Community Center|40.675350789075,-73.769889950752|',
  'venue_name': 'Rochdale Village Community Center (approximate meeting point)',
  'venue_address': '169-65 137th Avenue, Queens, NY 11434',
  'venue_city': 'Queens',
  'lat': 40.675350789075,
  'lng': -73.769889950752,
  'evidence_url': 'https://www.nysenate.gov/calendar/events/james-sanders/september-26-2019/community-development-day?page=3',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Rochdale Village Community Center',
  'native_point': [40.675350789075, -73.769889950752],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - New Utrecht|40.607961671271,-74.003469103657|',
  'venue_name': 'Brooklyn Public Library - New Utrecht',
  'venue_address': '1743 86th Street, Brooklyn, NY 11214',
  'venue_city': 'Brooklyn',
  'lat': 40.607961671271,
  'lng': -74.003469103657,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - New Utrecht',
  'native_point': [40.607961671271, -74.003469103657],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Sheepshead Bay Cornerstone Community Center|40.594135680862,-73.940373398022|',
  'venue_name': 'Sheepshead Bay Cornerstone Community Center',
  'venue_address': '3679 Nostrand Avenue, Brooklyn, NY 11229',
  'venue_city': 'Brooklyn',
  'lat': 40.594135680862,
  'lng': -73.940373398022,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Sheepshead Bay Cornerstone Community Center',
  'native_point': [40.594135680862, -73.940373398022],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Sunnyside|40.740872057552,-73.921704828739|',
  'venue_name': 'Queens Public Library - Sunnyside',
  'venue_address': '43-06 Greenpoint Avenue, Queens, NY 11104',
  'venue_city': 'Queens',
  'lat': 40.740872057552,
  'lng': -73.921704828739,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Sunnyside',
  'native_point': [40.740872057552, -73.921704828739],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Broadway|40.758652425135,-73.918559074402|',
  'venue_name': 'Queens Public Library - Broadway',
  'venue_address': '40-20 Broadway, Queens, NY 11103',
  'venue_city': 'Queens',
  'lat': 40.758652425135,
  'lng': -73.918559074402,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Broadway',
  'native_point': [40.758652425135, -73.918559074402],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - East Elmhurst|40.762548,-73.873869|',
  'venue_name': 'Queens Public Library - East Elmhurst',
  'venue_address': '95-06 Astoria Boulevard, Queens, NY 11369',
  'venue_city': 'Queens',
  'lat': 40.762548,
  'lng': -73.873869,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - East Elmhurst',
  'native_point': [40.762548, -73.873869],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Ulmer Park|40.592903657654,-73.988698124885|',
  'venue_name': 'Brooklyn Public Library - Ulmer Park',
  'venue_address': '2602 Bath Avenue, Brooklyn, NY 11214',
  'venue_city': 'Brooklyn',
  'lat': 40.592903657654,
  'lng': -73.988698124885,
  'evidence_url': 'https://www.bklynlibrary.org/locations/ulmer-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Ulmer Park',
  'native_point': [40.592903657654, -73.988698124885],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Gymnasium (in Julio Carballo Fields)|40.814910128999,-73.889116707316|X260',
  'venue_name': 'Gymnasium (in Julio Carballo Fields)',
  'venue_address': '765 Manida Street, Bronx, NY 10474',
  'venue_city': 'Bronx',
  'lat': 40.814910128999,
  'lng': -73.889116707316,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Gymnasium (in Julio Carballo Fields)',
  'native_point': [40.814910128999, -73.889116707316],
  'native_park_id': 'X260'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - St. Albans|40.692450303937,-73.760227560997|',
  'venue_name': 'Queens Public Library - St. Albans',
  'venue_address': '191-05 Linden Boulevard, Queens, NY 11412',
  'venue_city': 'Queens',
  'lat': 40.692450303937,
  'lng': -73.760227560997,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - St. Albans',
  'native_point': [40.692450303937, -73.760227560997],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'United Nations Ave South Entrance (in Flushing Meadows Corona '
                     'Park)|40.742657289192,-73.849996328354|Q099',
  'venue_name': 'United Nations Ave South Entrance (in Flushing Meadows Corona Park) (approximate meeting point)',
  'venue_address': '111th Street & 55th Avenue, Queens, NY 11368',
  'venue_city': 'Queens',
  'lat': 40.742657289192,
  'lng': -73.849996328354,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/19/nyrr-open-run-flushing-meadows-corona-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'United Nations Ave South Entrance (in Flushing Meadows Corona Park)',
  'native_point': [40.742657289192, -73.849996328354],
  'native_park_id': 'Q099'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Fraser Square Park (in Fraser Square)|40.619970278,-73.9412285575|B173',
  'venue_name': 'Fraser Square Park (in Fraser Square) (approximate meeting point)',
  'venue_address': 'Avenue M & East 34th Street, Brooklyn, NY 11234',
  'venue_city': 'Brooklyn',
  'lat': 40.619970278,
  'lng': -73.9412285575,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Fraser Square Park (in Fraser Square)',
  'native_point': [40.619970278, -73.9412285575],
  'native_park_id': 'B173'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Van Cortlandt Golf House (in Van Cortlandt Park)|40.8890380859375,-73.89234161376953|X092',
  'venue_name': 'Van Cortlandt Golf House (in Van Cortlandt Park) (approximate meeting point)',
  'venue_address': 'Bailey Avenue & Van Cortlandt Park South, Bronx, NY 10463',
  'venue_city': 'Bronx',
  'lat': 40.8890380859375,
  'lng': -73.89234161376953,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/20/floodplain-forest-fridays-volunteer-tree-planting-at-van-cortlandt-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Van Cortlandt Golf House (in Van Cortlandt Park)',
  'native_point': [40.8890380859375, -73.89234161376953],
  'native_park_id': 'X092'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': '12th St & 31st Ave, Queens, NY (in Astoria Park)|40.768847223036,-73.933396100998|Q004',
  'venue_name': '12th St & 31st Ave, Queens, NY (in Astoria Park)',
  'venue_address': '12th Street & 31st Avenue, Queens, NY 11106',
  'venue_city': 'Queens',
  'lat': 40.768847223036,
  'lng': -73.933396100998,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/20/astoria-street-tree-care',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': '12th St & 31st Ave, Queens, NY (in Astoria Park)',
  'native_point': [40.768847223036, -73.933396100998],
  'native_park_id': 'Q004'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brigadier General Charles Young Playground|40.8193277731,-73.9356595126|M186',
  'venue_name': 'Brigadier General Charles Young Playground (approximate meeting point)',
  'venue_address': '680 Lenox Avenue, New York, NY 10037',
  'venue_city': 'New York',
  'lat': 40.8193277731,
  'lng': -73.9356595126,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Brigadier General Charles Young Playground',
  'native_point': [40.8193277731, -73.9356595126],
  'native_park_id': 'M186'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Andrew Haswell Green Park|40.759700775146484,-73.95760345458984|M108Q1',
  'venue_name': 'Andrew Haswell Green Park (approximate meeting point)',
  'venue_address': '555 East 60th Street, New York, NY 10022',
  'venue_city': 'New York',
  'lat': 40.759700775146484,
  'lng': -73.95760345458984,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Andrew Haswell Green Park',
  'native_point': [40.759700775146484, -73.95760345458984],
  'native_park_id': 'M108Q1'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Ecology Park|40.6240524,-73.9059049|',
  'venue_name': 'Ecology Park (approximate meeting point)',
  'venue_address': 'Bergen Avenue & Avenue T, Brooklyn, NY 11234',
  'venue_city': 'Brooklyn',
  'lat': 40.6240524,
  'lng': -73.9059049,
  'evidence_url': 'https://www.nyc.gov/assets/brooklyncb18/downloads/pdf/2024/Ecology-Park-Summer-Series-7-28-24.pdf',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Ecology Park',
  'native_point': [40.6240524, -73.9059049],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Vermont Place Parking Lot (in Highland Park)|40.686199188232,-73.889801025391|Q020',
  'venue_name': 'Vermont Place Parking Lot (in Highland Park) (approximate meeting point)',
  'venue_address': 'Vermont Place & Highland Boulevard, Brooklyn, NY 11207',
  'venue_city': 'Brooklyn',
  'lat': 40.686199188232,
  'lng': -73.889801025391,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Vermont Place Parking Lot (in Highland Park)',
  'native_point': [40.686199188232, -73.889801025391],
  'native_park_id': 'Q020'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Broadway and 251st Street (in Van Cortlandt Park)|40.8958854675293,-73.8964614868164|X092',
  'venue_name': 'Broadway and 251st Street (in Van Cortlandt Park)',
  'venue_address': 'Broadway & West 251st Street, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.8958854675293,
  'lng': -73.8964614868164,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/20/running-group',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Broadway and 251st Street (in Van Cortlandt Park)',
  'native_point': [40.8958854675293, -73.8964614868164],
  'native_park_id': 'X092'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Tilden Senior Center|40.663341435816,-73.905597686768|',
  'venue_name': 'Tilden Senior Center',
  'venue_address': '630 Mother Gaston Boulevard, Brooklyn, NY 11212',
  'venue_city': 'Brooklyn',
  'lat': 40.663341435816,
  'lng': -73.905597686768,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Tilden Senior Center',
  'native_point': [40.663341435816, -73.905597686768],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Sheepshead Bay|40.586986323027,-73.955437708298|',
  'venue_name': 'Brooklyn Public Library - Sheepshead Bay',
  'venue_address': '2636 East 14th Street, Brooklyn, NY 11235',
  'venue_city': 'Brooklyn',
  'lat': 40.586986323027,
  'lng': -73.955437708298,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Sheepshead Bay',
  'native_point': [40.586986323027, -73.955437708298],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Fit4Dance NYC|40.6487517,-73.9572669|',
  'venue_name': 'Fit4Dance NYC',
  'venue_address': '21 Snyder Avenue, Brooklyn, NY 11226',
  'venue_city': 'Brooklyn',
  'lat': 40.6487517,
  'lng': -73.9572669,
  'evidence_url': 'https://fit4dancenyc.com/contact',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Fit4Dance NYC',
  'native_point': [40.6487517, -73.9572669],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'River Run Playground (in Riverside Park)|40.7869987487793,-73.9822006225586|M071',
  'venue_name': 'River Run Playground (in Riverside Park) (approximate meeting point)',
  'venue_address': 'Riverside Drive & West 83rd Street, New York, NY 10024',
  'venue_city': 'New York',
  'lat': 40.7869987487793,
  'lng': -73.9822006225586,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'River Run Playground (in Riverside Park)',
  'native_point': [40.7869987487793, -73.9822006225586],
  'native_park_id': 'M071'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Canarsie Park House (in Canarsie Park)|40.628942896777,-73.895997524261|B018',
  'venue_name': 'Canarsie Park House (in Canarsie Park) (approximate meeting point)',
  'venue_address': 'East 88th Street & Seaview Avenue, Brooklyn, NY 11236',
  'venue_city': 'Brooklyn',
  'lat': 40.628942896777,
  'lng': -73.895997524261,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/nyrr-open-run-canarsie-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Canarsie Park House (in Canarsie Park)',
  'native_point': [40.628942896777, -73.895997524261],
  'native_park_id': 'B018'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': "St. Mary's Annual 5K Start|40.813804626464844,-73.91180419921875|",
  'venue_name': "St. Mary's Annual 5K Start",
  'venue_address': 'East 149th Street & Eagle Avenue, Bronx, NY 10455',
  'venue_city': 'Bronx',
  'lat': 40.813804626464844,
  'lng': -73.91180419921875,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': "St. Mary's Annual 5K Start",
  'native_point': [40.813804626464844, -73.91180419921875],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Seaman Avenue and Isham Street Entrance (in Inwood Hill '
                     'Park)|40.869998931884766,-73.92109680175781|M042',
  'venue_name': 'Seaman Avenue and Isham Street Entrance (in Inwood Hill Park)',
  'venue_address': 'Seaman Avenue & Isham Street, New York, NY 10034',
  'venue_city': 'New York',
  'lat': 40.869998931884766,
  'lng': -73.92109680175781,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/nyrr-open-run-inwood-hill-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Seaman Avenue and Isham Street Entrance (in Inwood Hill Park)',
  'native_point': [40.869998931884766, -73.92109680175781],
  'native_park_id': 'M042'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Astoria Park|40.779102012899,-73.922377586365|Q004',
  'venue_name': 'Astoria Park (approximate meeting point)',
  'venue_address': '24-02 19th Street, Queens, NY 11102',
  'venue_city': 'Queens',
  'lat': 40.779102012899,
  'lng': -73.922377586365,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Astoria Park',
  'native_point': [40.779102012899, -73.922377586365],
  'native_park_id': 'Q004'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Baisley Pond Park House (in Baisley Pond Park)|40.67300033569336,-73.78669738769531|Q005',
  'venue_name': 'Baisley Pond Park House (in Baisley Pond Park) (approximate meeting point)',
  'venue_address': 'Baisley Boulevard & 154th Street, Queens, NY 11434',
  'venue_city': 'Queens',
  'lat': 40.67300033569336,
  'lng': -73.78669738769531,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/nyrr-open-run-baisley-pond-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Baisley Pond Park House (in Baisley Pond Park)',
  'native_point': [40.67300033569336, -73.78669738769531],
  'native_park_id': 'Q005'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Elton Street and Jamaica Avenue (in Highland Park)|40.68360137939453,-73.88569641113281|Q020',
  'venue_name': 'Elton Street and Jamaica Avenue (in Highland Park)',
  'venue_address': 'Elton Street & Jamaica Avenue, Brooklyn, NY 11208',
  'venue_city': 'Brooklyn',
  'lat': 40.68360137939453,
  'lng': -73.88569641113281,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/nyrr-open-run-highland-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Elton Street and Jamaica Avenue (in Highland Park)',
  'native_point': [40.68360137939453, -73.88569641113281],
  'native_park_id': 'Q020'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Lawn Near 79th Street Entrance (in Shore Park and Parkway)|40.63140850518,-74.039070755243|B082',
  'venue_name': 'Lawn Near 79th Street Entrance (in Shore Park and Parkway) (approximate meeting point)',
  'venue_address': '79th Street & Shore Road, Brooklyn, NY 11209',
  'venue_city': 'Brooklyn',
  'lat': 40.63140850518,
  'lng': -74.039070755243,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/nyrr-open-run-shore-road-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Lawn Near 79th Street Entrance (in Shore Park and Parkway)',
  'native_point': [40.63140850518, -74.039070755243],
  'native_park_id': 'B082'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Entrance - Lafayette Avenue and Morrison Avenue (in Soundview '
                     'Park)|40.820098876953,-73.872398376465|X118',
  'venue_name': 'Entrance - Lafayette Avenue and Morrison Avenue (in Soundview Park)',
  'venue_address': 'Lafayette Avenue & Morrison Avenue, Bronx, NY 10473',
  'venue_city': 'Bronx',
  'lat': 40.820098876953,
  'lng': -73.872398376465,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/nyrr-open-run-soundview-park',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Entrance - Lafayette Avenue and Morrison Avenue (in Soundview Park)',
  'native_point': [40.820098876953, -73.872398376465],
  'native_park_id': 'X118'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Alley Pond Park|40.745929465324,-73.741154670716|Q001',
  'venue_name': 'Alley Pond Park (approximate meeting point)',
  'venue_address': 'Winchester Boulevard & Union Turnpike, Queens, NY 11364',
  'venue_city': 'Queens',
  'lat': 40.745929465324,
  'lng': -73.741154670716,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/alley-pond-park-tree-and-shrub-planting',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Alley Pond Park',
  'native_point': [40.745929465324, -73.741154670716],
  'native_park_id': 'Q001'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Gymnasium (Court) (in Flushing Meadows Corona Park)|40.75149918,-73.83439636|Q099',
  'venue_name': 'Gymnasium (Court) (in Flushing Meadows Corona Park)',
  'venue_address': '131-40 Fowler Avenue, Queens, NY 11355',
  'venue_city': 'Queens',
  'lat': 40.75149918,
  'lng': -73.83439636,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Gymnasium (Court) (in Flushing Meadows Corona Park)',
  'native_point': [40.75149918, -73.83439636],
  'native_park_id': 'Q099'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Westerleigh Park|40.619800567627,-74.134498596191|R029',
  'venue_name': 'Westerleigh Park (approximate meeting point)',
  'venue_address': 'Willard Avenue & Maine Avenue, Staten Island, NY 10314',
  'venue_city': 'Staten Island',
  'lat': 40.619800567627,
  'lng': -74.134498596191,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Westerleigh Park',
  'native_point': [40.619800567627, -74.134498596191],
  'native_park_id': 'R029'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Moore Homestead Playground Comfort Station (in Moore Homestead '
                     'Playground)|40.742321270198,-73.882089495659|Q361',
  'venue_name': 'Moore Homestead Playground Comfort Station (in Moore Homestead Playground) (approximate meeting '
                'point)',
  'venue_address': '82-02 Broadway, Queens, NY 11373',
  'venue_city': 'Queens',
  'lat': 40.742321270198,
  'lng': -73.882089495659,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Moore Homestead Playground Comfort Station (in Moore Homestead Playground)',
  'native_point': [40.742321270198, -73.882089495659],
  'native_park_id': 'Q361'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Glenwood Landing Garden (in Glenwood Landing)|40.775069896346,-73.739911039084|Q222',
  'venue_name': 'Glenwood Landing Garden (in Glenwood Landing) (approximate meeting point)',
  'venue_address': 'Glenwood Street & 39th Road, Queens, NY 11363',
  'venue_city': 'Queens',
  'lat': 40.775069896346,
  'lng': -73.739911039084,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Glenwood Landing Garden (in Glenwood Landing)',
  'native_point': [40.775069896346, -73.739911039084],
  'native_park_id': 'Q222'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Joe Holzka Community Garden|40.634498596191,-74.121696472168|',
  'venue_name': 'Joe Holzka Community Garden (approximate meeting point)',
  'venue_address': 'Castleton Avenue & Barker Street, Staten Island, NY 10310',
  'venue_city': 'Staten Island',
  'lat': 40.634498596191,
  'lng': -74.121696472168,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Joe Holzka Community Garden',
  'native_point': [40.634498596191, -74.121696472168],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'George Washington Carver High School for the Sciences|40.671126130186,-73.757764781531|',
  'venue_name': 'George Washington Carver High School for the Sciences (approximate meeting point)',
  'venue_address': '143-10 Springfield Boulevard, Queens, NY 11413',
  'venue_city': 'Queens',
  'lat': 40.6680862551,
  'lng': -73.757868374,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'exact_named_current_DOE_facility_point_correct_native_pin_about340m_north',
  'approximate': True,
  'native_name': 'George Washington Carver High School for the Sciences',
  'native_point': [40.671126130186, -73.757764781531],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Mural Bridge (in Forest Park)|40.703765462949,-73.839664936066|Q015',
  'venue_name': 'Mural Bridge (in Forest Park) (approximate meeting point)',
  'venue_address': 'Park Lane South & Myrtle Avenue, Queens, NY 11418',
  'venue_city': 'Queens',
  'lat': 40.703765462949,
  'lng': -73.839664936066,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Mural Bridge (in Forest Park)',
  'native_point': [40.703765462949, -73.839664936066],
  'native_park_id': 'Q015'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Community House Beacon @ PS 149|40.7552247,-73.874204|',
  'venue_name': 'Queens Community House Beacon @ PS 149',
  'venue_address': '93-11 34th Avenue, Queens, NY 11372',
  'venue_city': 'Queens',
  'lat': 40.7552247,
  'lng': -73.874204,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Community House Beacon @ PS 149',
  'native_point': [40.7552247, -73.874204],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Pier 35 (in East River Waterfront Esplanade)|40.709649444767,-73.988022970886|M391',
  'venue_name': 'Pier 35 (in East River Waterfront Esplanade) (approximate meeting point)',
  'venue_address': 'South Street & Rutgers Slip, New York, NY 10002',
  'venue_city': 'New York',
  'lat': 40.709649444767,
  'lng': -73.988022970886,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Pier 35 (in East River Waterfront Esplanade)',
  'native_point': [40.709649444767, -73.988022970886],
  'native_park_id': 'm391'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Play Area (in Brigadier General Charles Young Playground)|40.819519519731,-73.936442434788|M186',
  'venue_name': 'Play Area (in Brigadier General Charles Young Playground) (approximate meeting point)',
  'venue_address': '680 Lenox Avenue, New York, NY 10037',
  'venue_city': 'New York',
  'lat': 40.819519519731,
  'lng': -73.936442434788,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Play Area (in Brigadier General Charles Young Playground)',
  'native_point': [40.819519519731, -73.936442434788],
  'native_park_id': 'M186'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'West 159th Street and Amsterdam Avenue (in Roger Morris '
                     'Park)|40.834143744992,-73.941024231774|M073',
  'venue_name': 'West 159th Street and Amsterdam Avenue (in Roger Morris Park)',
  'venue_address': 'West 159th Street & Amsterdam Avenue, New York, NY 10032',
  'venue_city': 'New York',
  'lat': 40.834143744992,
  'lng': -73.941024231774,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/washington-heights-street-tree-care',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'West 159th Street and Amsterdam Avenue (in Roger Morris Park)',
  'native_point': [40.834143744992, -73.941024231774],
  'native_park_id': 'M073'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Butler Terrace and Brighton Aveune (in Jones Woods Park)|40.636559843448,-74.088993982031|R048',
  'venue_name': 'Butler Terrace and Brighton Aveune (in Jones Woods Park)',
  'venue_address': 'Butler Terrace & Brighton Avenue, Staten Island, NY 10301',
  'venue_city': 'Staten Island',
  'lat': 40.636559843448,
  'lng': -74.088993982031,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/jones-woods-park-forest-restoration',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Butler Terrace and Brighton Aveune (in Jones Woods Park)',
  'native_point': [40.636559843448, -74.088993982031],
  'native_park_id': 'R048'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Tilden Playground|40.647598266602,-73.931396484375|B234',
  'venue_name': 'Tilden Playground (approximate meeting point)',
  'venue_address': '4802 Tilden Avenue, Brooklyn, NY 11203',
  'venue_city': 'Brooklyn',
  'lat': 40.647598266602,
  'lng': -73.931396484375,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Tilden Playground',
  'native_point': [40.647598266602, -73.931396484375],
  'native_park_id': 'B234'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Play Area (in Matthews Muliner Playground)|40.8469653025,-73.8615364187|X178',
  'venue_name': 'Play Area (in Matthews Muliner Playground) (approximate meeting point)',
  'venue_address': 'Matthews Avenue & Morris Park Avenue, Bronx, NY 10462',
  'venue_city': 'Bronx',
  'lat': 40.8469653025,
  'lng': -73.8615364187,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Play Area (in Matthews Muliner Playground)',
  'native_point': [40.8469653025, -73.8615364187],
  'native_park_id': 'X178'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Cambria Heights|40.69569984134,-73.741208053924|',
  'venue_name': 'Queens Public Library - Cambria Heights',
  'venue_address': '218-13 Linden Boulevard, Queens, NY 11411',
  'venue_city': 'Queens',
  'lat': 40.69569984134,
  'lng': -73.741208053924,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Cambria Heights',
  'native_point': [40.69569984134, -73.741208053924],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Brooklyn Heights|40.695695481907,-73.991195976734|',
  'venue_name': 'Brooklyn Public Library - Brooklyn Heights',
  'venue_address': '286 Cadman Plaza West, Brooklyn, NY 11201',
  'venue_city': 'Brooklyn',
  'lat': 40.695695481907,
  'lng': -73.991195976734,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Brooklyn Heights',
  'native_point': [40.695695481907, -73.991195976734],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Rock Climbing Wall Room (in Gertrude Ederle Recreation Center)|40.77149963,-73.9885025|M063',
  'venue_name': 'Rock Climbing Wall Room (in Gertrude Ederle Recreation Center)',
  'venue_address': '232 West 60th Street, New York, NY 10023',
  'venue_city': 'New York',
  'lat': 40.77149963,
  'lng': -73.9885025,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Rock Climbing Wall Room (in Gertrude Ederle Recreation Center)',
  'native_point': [40.77149963, -73.9885025],
  'native_park_id': 'M063'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'BPL- Macon Library|40.6830369,-73.9348376|',
  'venue_name': 'BPL- Macon Library',
  'venue_address': '361 Lewis Avenue, Brooklyn, NY 11233',
  'venue_city': 'Brooklyn',
  'lat': 40.6830369,
  'lng': -73.9348376,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'BPL- Macon Library',
  'native_point': [40.6830369, -73.9348376],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Thomas Jefferson Recreation Center (in Thomas Jefferson '
                     'Park)|40.79349899291992,-73.93669891357422|M047',
  'venue_name': 'Thomas Jefferson Recreation Center (in Thomas Jefferson Park)',
  'venue_address': '2180 First Avenue, New York, NY 10029',
  'venue_city': 'New York',
  'lat': 40.79349899291992,
  'lng': -73.93669891357422,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Thomas Jefferson Recreation Center (in Thomas Jefferson Park)',
  'native_point': [40.79349899291992, -73.93669891357422],
  'native_park_id': 'M047'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'George Washington Carver Community Garden|40.702751,-73.947952|',
  'venue_name': 'George Washington Carver Community Garden',
  'venue_address': '110 Walton Street, Brooklyn, NY 11206',
  'venue_city': 'Brooklyn',
  'lat': 40.702751,
  'lng': -73.947952,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'George Washington Carver Community Garden',
  'native_point': [40.702751, -73.947952],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYPL - Tompkins Square Library|40.7273154,-73.9803838|',
  'venue_name': 'NYPL - Tompkins Square Library',
  'venue_address': '331 East 10th Street, New York, NY 10009',
  'venue_city': 'New York',
  'lat': 40.7273154,
  'lng': -73.9803838,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYPL - Tompkins Square Library',
  'native_point': [40.7273154, -73.9803838],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'The Overlook (in Forest Park)|40.710895558585,-73.835624933243|Q015',
  'venue_name': 'The Overlook (in Forest Park)',
  'venue_address': '80-30 Park Lane, Queens, NY 11415',
  'venue_city': 'Queens',
  'lat': 40.710895558585,
  'lng': -73.835624933243,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP',
  'approximate': False,
  'native_name': 'The Overlook (in Forest Park)',
  'native_point': [40.710895558585, -73.835624933243],
  'native_park_id': 'Q015'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'NYPL - Eastchester Library|40.869995298193,-73.844834804535|',
  'venue_name': 'NYPL - Eastchester Library',
  'venue_address': '1385 East Gun Hill Road, Bronx, NY 10469',
  'venue_city': 'Bronx',
  'lat': 40.869995298193,
  'lng': -73.844834804535,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'NYPL - Eastchester Library',
  'native_point': [40.869995298193, -73.844834804535],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Prospect Avenue and Brentwood Avenue (in Allison Pond '
                     'Park)|40.638315348643,-74.102748195445|R052',
  'venue_name': 'Prospect Avenue and Brentwood Avenue (in Allison Pond Park)',
  'venue_address': 'Prospect Avenue & Brentwood Avenue, Staten Island, NY 10301',
  'venue_city': 'Staten Island',
  'lat': 40.638315348643,
  'lng': -74.102748195445,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/introduction-to-fly-fishing',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Prospect Avenue and Brentwood Avenue (in Allison Pond Park)',
  'native_point': [40.638315348643, -74.102748195445],
  'native_park_id': 'R052'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Burke Bridge (in Bronx Park)|40.871585845947266,-73.87255096435547|X002',
  'venue_name': 'Burke Bridge (in Bronx Park) (approximate meeting point)',
  'venue_address': 'Burke Avenue & Bronx Boulevard, Bronx, NY 10467',
  'venue_city': 'Bronx',
  'lat': 40.871585845947266,
  'lng': -73.87255096435547,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/outdoor-skills-workshop-hiking-basics',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Burke Bridge (in Bronx Park)',
  'native_point': [40.871585845947266, -73.87255096435547],
  'native_park_id': 'X002'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Orchard Beach Pavilion (in Pelham Bay Park)|40.8661994934082,-73.7947998046875|X039',
  'venue_name': 'Orchard Beach Pavilion (in Pelham Bay Park) (approximate meeting point)',
  'venue_address': 'Park Drive & Orchard Beach Road, Bronx, NY 10464',
  'venue_city': 'Bronx',
  'lat': 40.8661994934082,
  'lng': -73.7947998046875,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Orchard Beach Pavilion (in Pelham Bay Park)',
  'native_point': [40.8661994934082, -73.7947998046875],
  'native_park_id': 'X039'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Queens Public Library - Far Rockaway|40.604347148912,-73.752398192883|',
  'venue_name': 'Queens Public Library - Far Rockaway',
  'venue_address': '16-37 Central Avenue, Queens, NY 11691',
  'venue_city': 'Queens',
  'lat': 40.604347148912,
  'lng': -73.752398192883,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Queens Public Library - Far Rockaway',
  'native_point': [40.604347148912, -73.752398192883],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Paradise Community Garden NY|40.6907019,-73.8037744|',
  'venue_name': 'Paradise Community Garden NY',
  'venue_address': '107-29 Inwood Street, Queens, NY 11435',
  'venue_city': 'Queens',
  'lat': 40.6907019,
  'lng': -73.8037744,
  'evidence_url': 'https://data.cityofnewyork.us/dataset/GreenThumb-Garden-Info/p78i-pat6',
  'provenance': 'publisher_native_event_point_with_reviewed_current_GreenThumb_named_garden_address',
  'approximate': False,
  'native_name': 'Paradise Community Garden NY',
  'native_point': [40.6907019, -73.8037744],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Classroom B - Large (in Lost Battalion Hall Recreation '
                     'Center)|40.731716602397,-73.865442993229|Q401',
  'venue_name': 'Classroom B - Large (in Lost Battalion Hall Recreation Center)',
  'venue_address': '93-29 Queens Boulevard, Queens, NY 11374',
  'venue_city': 'Queens',
  'lat': 40.731716602397,
  'lng': -73.865442993229,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Classroom B - Large (in Lost Battalion Hall Recreation Center)',
  'native_point': [40.731716602397, -73.865442993229],
  'native_park_id': 'Q401'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'BronxWorks - Betances Community Center|40.8126634,-73.9146281|',
  'venue_name': 'BronxWorks - Betances Community Center',
  'venue_address': '547 East 146th Street, Bronx, NY 10455',
  'venue_city': 'Bronx',
  'lat': 40.8126634,
  'lng': -73.9146281,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'BronxWorks - Betances Community Center',
  'native_point': [40.8126634, -73.9146281],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Ballroom (in John J Carty Park)|40.61333466,-74.02997589|B210W',
  'venue_name': 'Ballroom (in John J Carty Park)',
  'venue_address': '9941 Fort Hamilton Parkway, Brooklyn, NY 11209',
  'venue_city': 'Brooklyn',
  'lat': 40.61333466,
  'lng': -74.02997589,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Ballroom (in John J Carty Park)',
  'native_point': [40.61333466, -74.02997589],
  'native_park_id': 'B210W'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Marcy|40.691628,-73.9512743|',
  'venue_name': 'Brooklyn Public Library - Marcy',
  'venue_address': '617 DeKalb Avenue, Brooklyn, NY 11216',
  'venue_city': 'Brooklyn',
  'lat': 40.691628,
  'lng': -73.9512743,
  'evidence_url': 'https://www.bklynlibrary.org/locations/marcy',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Marcy',
  'native_point': [40.691628, -73.9512743],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'J. Hood Wright Recreation Center (in J. Hood Wright Park)|40.846576301764,-73.940825939178|M099',
  'venue_name': 'J. Hood Wright Recreation Center (in J. Hood Wright Park)',
  'venue_address': '351 Fort Washington Avenue, New York, NY 10033',
  'venue_city': 'New York',
  'lat': 40.846576301764,
  'lng': -73.940825939178,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'J. Hood Wright Recreation Center (in J. Hood Wright Park)',
  'native_point': [40.846576301764, -73.940825939178],
  'native_park_id': 'M099'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brooklyn Public Library - Bay Ridge|40.6336068,-74.0295073|',
  'venue_name': 'Brooklyn Public Library - Bay Ridge',
  'venue_address': '7223 Ridge Boulevard, Brooklyn, NY 11209',
  'venue_city': 'Brooklyn',
  'lat': 40.6336068,
  'lng': -74.0295073,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Brooklyn Public Library - Bay Ridge',
  'native_point': [40.6336068, -74.0295073],
  'native_park_id': None},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Lawn Area - Monitor Street and Driggs Avenue (in Msgr. McGolrick '
                     'Park)|40.723712045724,-73.942661046981|B114',
  'venue_name': 'Lawn Area - Monitor Street and Driggs Avenue (in Msgr. McGolrick Park) (approximate meeting point)',
  'venue_address': 'Monitor Street & Driggs Avenue, Brooklyn, NY 11222',
  'venue_city': 'Brooklyn',
  'lat': 40.723712045724,
  'lng': -73.942661046981,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Lawn Area - Monitor Street and Driggs Avenue (in Msgr. McGolrick Park)',
  'native_point': [40.723712045724, -73.942661046981],
  'native_park_id': 'B114'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room (in St. James Park)|40.864771281824,-73.899219214916|X044',
  'venue_name': 'Multi-Use Room (in St. James Park)',
  'venue_address': '2530 Jerome Avenue, Bronx, NY 10468',
  'venue_city': 'Bronx',
  'lat': 40.864771281824,
  'lng': -73.899219214916,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Multi-Use Room (in St. James Park)',
  'native_point': [40.864771281824, -73.899219214916],
  'native_park_id': 'X044'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'West 81st Street and Central Park West (in Central Park)|40.781804280189,-73.971595048905|M010',
  'venue_name': 'West 81st Street and Central Park West (in Central Park)',
  'venue_address': 'West 81st Street & Central Park West, New York, NY 10024',
  'venue_city': 'New York',
  'lat': 40.781804280189,
  'lng': -73.971595048905,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/falling-for-nature-hike',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'West 81st Street and Central Park West (in Central Park)',
  'native_point': [40.781804280189, -73.971595048905],
  'native_park_id': 'M010'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Entrance - Mt. Eden Parkway and Morris Avenue (in Claremont '
                     'Park)|40.842700958252,-73.90950012207|X008',
  'venue_name': 'Entrance - Mt. Eden Parkway and Morris Avenue (in Claremont Park)',
  'venue_address': 'Mount Eden Parkway & Morris Avenue, Bronx, NY 10457',
  'venue_city': 'Bronx',
  'lat': 40.842700958252,
  'lng': -73.90950012207,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/living-with-urban-coyotes',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Entrance - Mt. Eden Parkway and Morris Avenue (in Claremont Park)',
  'native_point': [40.842700958252, -73.90950012207],
  'native_park_id': 'X008'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Entrance - Baisley Blvd. & 157th Street (in Baisley Pond '
                     'Park)|40.675882000605,-73.78319811821|Q005',
  'venue_name': 'Entrance - Baisley Blvd. & 157th Street (in Baisley Pond Park)',
  'venue_address': 'Baisley Boulevard & 157th Street, Queens, NY 11434',
  'venue_city': 'Queens',
  'lat': 40.675882000605,
  'lng': -73.78319811821,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/21/beginner-fishing',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Entrance - Baisley Blvd. & 157th Street (in Baisley Pond Park)',
  'native_point': [40.675882000605, -73.78319811821],
  'native_park_id': 'Q005'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Multi-Use Room B (in Marcus Garvey Park)|40.80502319,-73.94498444|M058',
  'venue_name': 'Multi-Use Room B (in Marcus Garvey Park)',
  'venue_address': '18 Mount Morris Park West, New York, NY 10027',
  'venue_city': 'New York',
  'lat': 40.80502319,
  'lng': -73.94498444,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP',
  'approximate': False,
  'native_name': 'Multi-Use Room B (in Marcus Garvey Park)',
  'native_point': [40.80502319, -73.94498444],
  'native_park_id': 'M058'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Blue Heron Nature Center (in Blue Heron Park)|40.530857179196,-74.177863717079|R119',
  'venue_name': 'Blue Heron Nature Center (in Blue Heron Park)',
  'venue_address': '222 Poillon Avenue, Staten Island, NY 10312',
  'venue_city': 'Staten Island',
  'lat': 40.530857179196,
  'lng': -74.177863717079,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/Facilities-Database/ji82-xba5',
  'provenance': 'publisher_native_event_point_with_reviewed_current_NYC_FacDB_venue_address',
  'approximate': False,
  'native_name': 'Blue Heron Nature Center (in Blue Heron Park)',
  'native_point': [40.530857179196, -74.177863717079],
  'native_park_id': 'R119'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Broadway Promenade at Bennett Ave (in Fort Tryon Park)|40.859676061388,-73.931570407425|M029',
  'venue_name': 'Broadway Promenade at Bennett Ave (in Fort Tryon Park)',
  'venue_address': 'Broadway & Bennett Avenue, New York, NY 10040',
  'venue_city': 'New York',
  'lat': 40.859676061388,
  'lng': -73.931570407425,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/22/bulb-planting',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Broadway Promenade at Bennett Ave (in Fort Tryon Park)',
  'native_point': [40.859676061388, -73.931570407425],
  'native_park_id': 'M029'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Corlears Hook Park|40.711799621582,-73.979301452637|M017',
  'venue_name': 'Corlears Hook Park (approximate meeting point)',
  'venue_address': 'Jackson Street & Cherry Street, New York, NY 10002',
  'venue_city': 'New York',
  'lat': 40.711799621582,
  'lng': -73.979301452637,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Corlears Hook Park',
  'native_point': [40.711799621582, -73.979301452637],
  'native_park_id': 'M017'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': "Lawn Area (in Owl's Head Park)|40.640098571777,-74.032402038574|B066",
  'venue_name': "Lawn Area (in Owl's Head Park) (approximate meeting point)",
  'venue_address': '68th Street & Colonial Road, Brooklyn, NY 11220',
  'venue_city': 'Brooklyn',
  'lat': 40.640098571777,
  'lng': -74.032402038574,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': "Lawn Area (in Owl's Head Park)",
  'native_point': [40.640098571777, -74.032402038574],
  'native_park_id': 'B066'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Van Cortlandt Nature Center (in Van Cortlandt Park)|40.891101837158,-73.893997192383|X092',
  'venue_name': 'Van Cortlandt Nature Center (in Van Cortlandt Park) (approximate meeting point)',
  'venue_address': 'Broadway & West 246th Street, Bronx, NY 10471',
  'venue_city': 'Bronx',
  'lat': 40.891101837158,
  'lng': -73.893997192383,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/22/autumn-mushroom-id-hike',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Van Cortlandt Nature Center (in Van Cortlandt Park)',
  'native_point': [40.891101837158, -73.893997192383],
  'native_park_id': 'X092'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Arthur Kill Road and Brookfield Avenue (in Brookfield Park)|40.561667478494,-74.15999635582|R172',
  'venue_name': 'Arthur Kill Road and Brookfield Avenue (in Brookfield Park)',
  'venue_address': 'Arthur Kill Road & Brookfield Avenue, Staten Island, NY 10308',
  'venue_city': 'Staten Island',
  'lat': 40.561667478494,
  'lng': -74.15999635582,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/22/nature-sketching',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Arthur Kill Road and Brookfield Avenue (in Brookfield Park)',
  'native_point': [40.561667478494, -74.15999635582],
  'native_park_id': 'R172'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Entrance - 34th Avenue between 77th and 78th Streets (in Travers '
                     'Park)|40.753513336182,-73.889167785645|Q303',
  'venue_name': 'Entrance - 34th Avenue between 77th and 78th Streets (in Travers Park) (approximate meeting point)',
  'venue_address': '34th Avenue & 78th Street, Queens, NY 11372',
  'venue_city': 'Queens',
  'lat': 40.753513336182,
  'lng': -73.889167785645,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Entrance - 34th Avenue between 77th and 78th Streets (in Travers Park)',
  'native_point': [40.753513336182, -73.889167785645],
  'native_park_id': 'Q303'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Rainbow Playground|40.64055758465,-74.01117895632|B265',
  'venue_name': 'Rainbow Playground (approximate meeting point)',
  'venue_address': '5523 Sixth Avenue, Brooklyn, NY 11220',
  'venue_city': 'Brooklyn',
  'lat': 40.64055758465,
  'lng': -74.01117895632,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Rainbow Playground',
  'native_point': [40.64055758465, -74.01117895632],
  'native_park_id': 'B265'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Union Turnpike and 196th Street (in Cunningham Park)|40.730712281998,-73.774853669312|Q021',
  'venue_name': 'Union Turnpike and 196th Street (in Cunningham Park)',
  'venue_address': 'Union Turnpike & 196th Street, Queens, NY 11366',
  'venue_city': 'Queens',
  'lat': 40.730712281998,
  'lng': -73.774853669312,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Union Turnpike and 196th Street (in Cunningham Park)',
  'native_point': [40.730712281998, -73.774853669312],
  'native_park_id': 'Q021'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Seaman Avenue and Isham Street (in Inwood Hill Park)|40.869701385498,-73.920600891113|M042',
  'venue_name': 'Seaman Avenue and Isham Street (in Inwood Hill Park)',
  'venue_address': 'Seaman Avenue & Isham Street, New York, NY 10034',
  'venue_city': 'New York',
  'lat': 40.869701385498,
  'lng': -73.920600891113,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/22/native-american-heritage-month-walking-lenapehoking',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Seaman Avenue and Isham Street (in Inwood Hill Park)',
  'native_point': [40.869701385498, -73.920600891113],
  'native_park_id': 'M042'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Brower Park Butterfly Garden (in Brower Park)|40.67375339583,-73.943148255348|B012',
  'venue_name': 'Brower Park Butterfly Garden (in Brower Park) (approximate meeting point)',
  'venue_address': '195 Brooklyn Avenue, Brooklyn, NY 11213',
  'venue_city': 'Brooklyn',
  'lat': 40.67375339583,
  'lng': -73.943148255348,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Brower Park Butterfly Garden (in Brower Park)',
  'native_point': [40.67375339583, -73.943148255348],
  'native_park_id': 'B012'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Orchard Beach Nature Center (in Pelham Bay Park)|40.870487367202,-73.786619067192|X039',
  'venue_name': 'Orchard Beach Nature Center (in Pelham Bay Park) (approximate meeting point)',
  'venue_address': 'Park Drive & Orchard Beach Road, Bronx, NY 10464',
  'venue_city': 'Bronx',
  'lat': 40.870487367202,
  'lng': -73.786619067192,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Orchard Beach Nature Center (in Pelham Bay Park)',
  'native_point': [40.870487367202, -73.786619067192],
  'native_park_id': 'X039'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Parkside Avenue and South Lake Drive (in Prospect Park)|40.651412963867,-73.971786499023|B073',
  'venue_name': 'Parkside Avenue and South Lake Drive (in Prospect Park)',
  'venue_address': 'Parkside Avenue & South Lake Drive, Brooklyn, NY 11226',
  'venue_city': 'Brooklyn',
  'lat': 40.651412963867,
  'lng': -73.971786499023,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/22/freedom-seekers-stories-by-the-fire',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance',
  'approximate': False,
  'native_name': 'Parkside Avenue and South Lake Drive (in Prospect Park)',
  'native_point': [40.651412963867, -73.971786499023],
  'native_park_id': 'B073'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Ralph Bunche Park|40.7493242373,-73.9697516846|M203B',
  'venue_name': 'Ralph Bunche Park (approximate meeting point)',
  'venue_address': '741 First Avenue, New York, NY 10017',
  'venue_city': 'New York',
  'lat': 40.7493242373,
  'lng': -73.9697516846,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Ralph Bunche Park',
  'native_point': [40.7493242373, -73.9697516846],
  'native_park_id': 'M203B'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Kissena Park|40.745800958,-73.808508147|Q024',
  'venue_name': 'Kissena Park (approximate meeting point)',
  'venue_address': 'Kissena Boulevard & Booth Memorial Avenue, Queens, NY 11355',
  'venue_city': 'Queens',
  'lat': 40.745800958,
  'lng': -73.808508147,
  'evidence_url': 'https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve',
  'provenance': 'publisher_native_event_point_with_reviewed_current_Parks_property_street_and_ZIP_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Kissena Park',
  'native_point': [40.745800958, -73.808508147],
  'native_park_id': 'Q024'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Nevada Avenue Parking Lot (in High Rock Park)|40.584556817034,-74.124981164932|R088',
  'venue_name': 'Nevada Avenue Parking Lot (in High Rock Park)',
  'venue_address': '200 Nevada Avenue, Staten Island, NY 10306',
  'venue_city': 'Staten Island',
  'lat': 40.584556817034,
  'lng': -74.124981164932,
  'evidence_url': 'https://data.cityofnewyork.us/City-Government/NYC-Parks-Events-Listing-Event-Locations/cpcm-i88g',
  'provenance': 'publisher_native_event_point_with_reviewed_exact_named_historical_Parks_address_corroborated_by_current_event',
  'approximate': False,
  'native_name': 'Nevada Avenue Parking Lot (in High Rock Park)',
  'native_point': [40.584556817034, -74.124981164932],
  'native_park_id': 'R088'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Alley Pond Adventure Course (in Alley Pond Park)|40.742768103299,-73.741125994751|Q001',
  'venue_name': 'Alley Pond Adventure Course (in Alley Pond Park) (approximate meeting point)',
  'venue_address': 'Winchester Boulevard & Union Turnpike, Queens, NY 11364',
  'venue_city': 'Queens',
  'lat': 40.742768103299,
  'lng': -73.741125994751,
  'evidence_url': 'https://www.nycgovparks.org/programs/rangers/adventure-course',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Alley Pond Adventure Course (in Alley Pond Park)',
  'native_point': [40.742768103299, -73.741125994751],
  'native_park_id': 'Q001'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'Audubon Center at the Boathouse (in Prospect Park)|40.660701751709,-73.965400695801|B073',
  'venue_name': 'Audubon Center at the Boathouse (in Prospect Park) (approximate meeting point)',
  'venue_address': 'Lincoln Road & Ocean Avenue, Brooklyn, NY 11225',
  'venue_city': 'Brooklyn',
  'lat': 40.660701751709,
  'lng': -73.965400695801,
  'evidence_url': 'https://www.nycgovparks.org/events/2026/11/27/postthanksgiving-day-super-hike',
  'provenance': 'publisher_native_event_point_with_reviewed_official_publisher_named_street_or_entrance_approximate_street_access_native_meeting_preserved',
  'approximate': True,
  'native_name': 'Audubon Center at the Boathouse (in Prospect Park)',
  'native_point': [40.660701751709, -73.965400695801],
  'native_park_id': 'B073'},
 {'source_key': 'municipal_mapsee_0e46855a44eb788f36a2c0ab',
  'native_identity': 'event:2315505',
  'venue_name': 'Rev. T. Wendell Foster Park — East 164th Street entrance (approximate meeting point)',
  'venue_address': '40 East 164th Street, Bronx, NY 10452',
  'venue_city': 'Bronx',
  'lat': 40.830809,
  'lng': -73.925479,
  'evidence_url': 'https://geosearch.planninglabs.nyc/v2/search?text=40+East+164th+Street+Bronx+NY+10452',
  'provenance': 'native_exact_entrance_directions_and_current_NYC_FacDB_with_exact_PAD_street_point',
  'approximate': True}]
REVIEWED_INTERSECTIONS = [p for p in PLACES if not re.match(r"^\d+[A-Za-z]?(?:-\d+)?\s", p["venue_address"])]


def reviewed_venue_location(key, name, address):
    for place in PLACES:
        if (key, name, address) == (place['source_key'], place['venue_name'], place['venue_address']):
            return {'lat': place['lat'], 'lng': place['lng']}
    return None


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS[key] and not parsed.username and not parsed.password and parsed.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


def photo_url(key, value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        extra = {'localist-images.azureedge.net', 'images.squarespace-cdn.com', 'mobilizeamerica.imgix.net'}
        if parsed.scheme == 'https' and parsed.hostname in set(ALLOWED_HOSTS.get(key, ())) | extra and not parsed.username and not parsed.password and parsed.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


def _source(source):
    key = source.get('source_key')
    expected = SOURCES.get(key)
    if expected is None or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != expected:
        raise ValueError('nyc_final_source_unregistered')
    return key


def _budget(deadline):
    if deadline is not None and monotonic() + 5 >= deadline:
        raise ValueError('collection_deadline')


def _body(value):
    text = description(value, limit=max(len(str(value or '')), MAX_DESCRIPTION + 1))
    if not text or not text.strip():
        raise ValueError('description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('description_limit')
    return text


def _point(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
        if math.isfinite(lat) and math.isfinite(lng) and 40.48 < lat < 40.94 and -74.27 < lng < -73.68:
            return lat, lng
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _times(start, end=None):
    try:
        start, end = timestamp(start, ZONE), timestamp(end, ZONE)
        if start is None or end is not None and end <= start:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError('time_unverified') from None
    return start, end


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _place(key, identity):
    return next((p for p in PLACES if p['source_key'] == key and p['native_identity'] == str(identity)), None)


def _id(key, native, start):
    return 'nyc-outdoors-final:' + sha256((key + '|' + str(native) + '|' + start.astimezone(timezone.utc).isoformat()).encode()).hexdigest()


def _row(key, native, title, start, end, body, place, url, now, category='', image=None):
    if not _within(start, end, now):
        raise ValueError('event_not_current')
    title = plain(title)
    if not title or len(title) > 180 or NONPUBLIC.search(title):
        raise ValueError('event_not_public')
    if event_url(key, url) is None:
        raise ValueError('event_link_unresolved')
    if not place:
        raise ValueError('venue_not_reviewed')
    body = _body(body)
    point = _point(place.get('lat'), place.get('lng'))
    if point is None:
        raise ValueError('point_unresolved')
    if not re.search(r', [^,]+, NY \d{5}(?:-\d{4})?$', place.get('venue_address', '')):
        raise ValueError('street_unresolved')
    result = record(title, start, end, place['venue_name'], place['venue_address'], place['venue_city'],
                    url, _id(key, native, start), category, *point, tz=ZONE,
                    publisher_geo=True, retain_until_end=True)
    if result:
        result.update(description=body, timezone=ZONE, attendance_mode='in_person',
                      publisher_native_id=str(native), location_provenance=place['provenance'],
                      location_evidence_url=place['evidence_url'])
        if photo_url(key, image):
            result['image_url'] = image
    return result


def _held(key, identity, title, reason, url=None):
    return {'source_key': key, 'id': str(identity), 'title': plain(title), 'event_url': url,
            'disposition': 'held', 'reason': reason}


def _fordham_manifest(fetch, now, deadline):
    result, total, pages = [], None, None
    day = now.astimezone(ZoneInfo(ZONE)).date()
    for page in range(1, 11):
        _budget(deadline)
        url = 'https://calendar.fordham.edu/api/2/events?' + urlencode({
            'start': day.isoformat(), 'end': (day + timedelta(days=60)).isoformat(), 'pp': 100, 'page': page})
        data = json.loads(fetch(url, 'application/json'))
        meta = data.get('page', {})
        if not isinstance(data.get('events'), list) or meta.get('current') != page:
            raise ValueError('nyc_final_payload_changed')
        if total is None:
            total, pages = meta.get('total_items'), meta.get('total')
            if type(total) is not int or type(pages) is not int or not 0 <= total <= MAX_RECORDS or not 0 <= pages <= 10:
                raise ValueError('nyc_final_record_limit')
        if meta.get('total_items') != total or meta.get('total') != pages:
            raise ValueError('nyc_final_pagination_incomplete')
        result.extend(data['events'])
        if page >= pages:
            break
    if len(result) != total:
        raise ValueError('nyc_final_pagination_incomplete')
    return result


def _fordham_rows(item, now):
    event = item.get('event')
    if not isinstance(event, dict):
        raise ValueError('nyc_final_payload_changed')
    if (event.get('private') or event.get('status') not in ('live', 'published')
            or event.get('publish_status') != 'published' or event.get('experience') != 'inperson'
            or not any(x.get('name') == 'Public' for x in event.get('filters', {}).get('event_audiences', []))):
        raise ValueError('event_not_public')
    if event.get('event_instances') and all(v.get('event_instance', {}).get('all_day') for v in event['event_instances']):
        raise ValueError('all_day_without_hours')
    place = _place(FORDHAM, event.get('location_name'))
    if place is None:
        raise ValueError('venue_not_reviewed')
    # Exact reviewed publisher address/geo signature prevents changed venue data
    # from inheriting a formerly appropriate campus entrance.
    if place.get('native_address') != plain(event.get('address')):
        raise ValueError('venue_conflict')
    venue = dict(place)
    room = plain(event.get('room_number'))
    if room:
        venue['venue_name'] = plain(venue['venue_name'].replace(' (approximate meeting point)', '') + ', ' + room)
        if place.get('approximate'):
            venue['venue_name'] += ' (approximate meeting point)'
    if len(venue['venue_name']) > 120:
        raise ValueError('venue_conflict')
    body = _body(event.get('description'))
    categories = ', '.join(plain(x.get('name')) for x in event.get('filters', {}).get('event_types', []))
    rows = []
    for wrapper in event.get('event_instances', []):
        occurrence = wrapper.get('event_instance', {})
        if occurrence.get('all_day'):
            raise ValueError('all_day_without_hours')
        start, end = _times(occurrence.get('start'), occurrence.get('end'))
        row = _row(FORDHAM, occurrence.get('id'), event.get('title'), start, end, body, venue,
                   event.get('localist_url'), now, categories, event.get('photo_url'))
        if row:
            rows.append(row)
    return rows


def _tribe_manifest(fetch, now, deadline):
    result, seen, total, pages = [], set(), None, None
    day = now.astimezone(ZoneInfo(ZONE)).date()
    for page in range(1, 11):
        _budget(deadline)
        url = 'https://brooklyncb6.cityofnewyork.us/wp-json/tribe/events/v1/events?' + urlencode({
            'per_page': 100, 'start_date': day.isoformat(),
            'end_date': (day + timedelta(days=60)).isoformat(), 'page': page})
        data = json.loads(fetch(url, 'application/json'))
        if not isinstance(data.get('events'), list):
            raise ValueError('nyc_final_payload_changed')
        if total is None:
            total, pages = data.get('total'), data.get('total_pages')
            if type(total) is not int or type(pages) is not int or not 0 <= total <= MAX_RECORDS or not 0 <= pages <= 10:
                raise ValueError('nyc_final_record_limit')
        if data.get('total') != total or data.get('total_pages') != pages:
            raise ValueError('nyc_final_pagination_incomplete')
        for event in data['events']:
            if event.get('id') in seen:
                raise ValueError('nyc_final_pagination_incomplete')
            seen.add(event.get('id'))
            result.append(event)
        if page >= pages:
            break
    if len(result) != total:
        raise ValueError('nyc_final_pagination_incomplete')
    return result


def _tribe_rows(event, now):
    native_venue = event.get('venue') if isinstance(event.get('venue'), dict) else {}
    if (event.get('status') != 'publish' or event.get('hide_from_listings') or event.get('is_virtual')
            or REMOTE.search(plain(native_venue.get('venue'))) or REMOTE.search(plain(event.get('title')))
            or re.search(r'\b(?:virtual info session|statewide webinar)\b', plain(event.get('description')), re.I)
            or NONPUBLIC.search(plain(event.get('description')))):
        raise ValueError('event_not_public')
    if event.get('all_day'):
        raise ValueError('all_day_without_hours')
    if event.get('timezone') != ZONE:
        raise ValueError('time_unverified')
    # TEC imports may omit the end by repeating the start. Preserve the verified
    # start and unknown end; no duration or narrative clock is inferred.
    native_end = None if event.get('end_date') == event.get('start_date') else event.get('end_date')
    start, end = _times(event.get('start_date'), native_end)
    body = _body(event.get('description'))
    if end is None:
        explicit = re.search(r'\bEnds (\d{1,2}:\d{2} [AP]M)\.', body)
        if explicit:
            clock = datetime.strptime(explicit[1], '%I:%M %p').time()
            end = datetime.combine(start.date(), clock, tzinfo=start.tzinfo)
            if end <= start:
                raise ValueError('time_unverified')
        elif plain(event.get('title')) == 'Park Slope Farmers Market' and '9AM–2PM' in body and (start.hour, start.minute) == (9, 0):
            end = start.replace(hour=14)
    node = BeautifulSoup(event.get('description') or '', 'html.parser')
    for anchor in node.select('a'):
        anchor.decompose()
    if not plain(node.get_text()):
        raise ValueError('publisher_body_link_only')
    native = event.get('venue') if isinstance(event.get('venue'), dict) else {}
    place = _place(CB6, native.get('id'))
    if not native and plain(event.get('title')).startswith('Old Stone House: '):
        place = _place(CB6, 'title:Old Stone House')
    if not native and plain(event.get('title')) == 'Park Slope Farmers Market' and 'Site host: Old Stone House.' in body:
        place = _place(CB6, '9687')
    if (not native and plain(event.get('title')) == 'Grown-Up Bike Bus'
            and str(event.get('website') or '').rstrip('/') in ('https://principlesbk.nyc/upcoming-events', 'https://principlesbk.nyc/upcoming-events-listing')
            and 'Weekly group ride from Gowanus to the Upper East Side.' in body and 'Thursdays 8:00 AM.' in body):
        if start.weekday() != 3 or (start.hour, start.minute) != (8, 0):
            raise ValueError('schedule_conflict')
        place = _place(CB6, 'title:Grown-Up Bike Bus')
    if (not native and str(event.get('id')) == '9086' and plain(event.get('title')) == '5th Avenue Tree Lighting — Small Business Saturday'
            and event.get('website') == 'https://parkslopefifthavenuebid.com/event/5th-avenue-tree-lighting-small-business-saturday/'):
        if start.strftime('%Y-%m-%d %H:%M') != '2026-11-28 16:30':
            raise ValueError('schedule_conflict')
        place = _place(CB6, '9687')
    if place is None:
        raise ValueError('venue_not_reviewed')
    if native and place.get('native_venue') != plain(native.get('venue')):
        raise ValueError('venue_conflict')
    return [r] if (r := _row(CB6, event.get('id'), event.get('title'), start, end, body, place,
                            event.get('url'), now,
                            ', '.join(plain(x.get('name')) for x in event.get('categories', [])),
                            (event.get('image') or {}).get('url') if isinstance(event.get('image'), dict) else None)) else []


def _jsonld(soup, wanted):
    found = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kinds = value.get('@type', [])
            if wanted in (kinds if isinstance(kinds, list) else [kinds]):
                found.append(value)
            if '@graph' in value:
                visit(value['@graph'])
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (TypeError, ValueError):
            raise ValueError('nyc_final_payload_changed') from None
    return found


def _simple_manifest(key, payload):
    soup = BeautifulSoup(payload, 'html.parser')
    if key == BRONX:
        links = [urljoin(SOURCES[key][0], a['href']) for a in soup.select('a[href]')
                 if re.search(r'^https://bronxriver\.org/event/[^/?#]+/?$', urljoin(SOURCES[key][0], a['href']))]
    elif key == BKUP:
        links = [urljoin(SOURCES[key][0], a['href']) for a in soup.select('.public-event-card h2 a[href]')
                 if re.fullmatch(r'/events/[a-f0-9-]{36}', a['href'])]
        if not soup.select('.public-event-card'):
            raise ValueError('nyc_final_listing_changed')
    elif key == NYRR:
        links = [urljoin(SOURCES[key][0], a['href']) for a in soup.select('a[href]')
                 if re.fullmatch(r'/races-and-events/20\d{2}/[a-z0-9-]+', a['href'])
                 and not a['href'].endswith('/open-run-volunteers')]
    else:
        raise ValueError('nyc_final_source_unregistered')
    links = sorted(set(links))
    if len(links) > MAX_MANIFEST:
        raise ValueError('nyc_final_manifest_limit')
    return [dict(url=url) for url in links]


def _wave_manifest(fetch, now, deadline):
    result, seen_pages, previous_dates = {}, set(), None
    url = SOURCES[WAVE][0]
    for page in range(1, 16):
        _budget(deadline)
        payload = fetch(url, 'text/html')
        soup = BeautifulSoup(payload, 'html.parser')
        cards = soup.select('.event-wrapper a[href]')
        if not cards:
            raise ValueError('nyc_final_listing_changed')
        fingerprint = sha256(''.join(str(x) for x in cards).encode()).hexdigest()
        if fingerprint in seen_pages:
            raise ValueError('nyc_final_pagination_incomplete')
        seen_pages.add(fingerprint)
        dated = []
        for card in cards:
            link = event_url(WAVE, card.get('href'))
            heading = card.select_one('.event__title')
            clocks = card.select('time[datetime]')
            if not link or not heading or not clocks:
                continue
            start, end = _times(clocks[0]['datetime'], clocks[1]['datetime'] if len(clocks) > 1 else None)
            dated.append(start)
            title = plain(heading.get_text())
            if not _within(start, end, now):
                continue
            identity = link + '|' + start.isoformat()
            item = result.setdefault(link, dict(url=link, title=title, occurrences=[]))
            if item['title'] != title:
                raise ValueError('nyc_final_listing_changed')
            occurrence = dict(start=start.isoformat(), end=end.isoformat() if end else None,
                              all_day=start.hour == start.minute == 0)
            if occurrence not in item['occurrences']:
                item['occurrences'].append(occurrence)
        # Pagination is chronological, but the recurring exhibition strip is
        # repeated on each page and is outside .event-wrapper.
        if dated and min(dated) >= now + timedelta(days=60):
            break
        next_path = '/calendar/page/' + str(page + 1) + '?date=all'
        next_link = next((a['href'] for a in soup.select('a[href]') if a['href'] == next_path), None)
        if next_link is None:
            break
        url = urljoin(SOURCES[WAVE][0], next_link)
    else:
        raise ValueError('nyc_final_pagination_incomplete')
    queue = sorted(result.values(), key=lambda x: x['url'])
    if len(queue) > MAX_MANIFEST or sum(len(x['occurrences']) for x in queue) > 200:
        raise ValueError('nyc_final_manifest_limit')
    return queue


def _bronx_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    fields = {}
    for line in soup.select('.jet-table tbody tr'):
        cells = line.select('td')
        if len(cells) == 2:
            fields[plain(cells[0].get_text())] = plain(cells[1].get_text())
    if set(fields) != {'Date', 'Location', 'Start Time', 'End Time'}:
        raise ValueError('nyc_final_detail_changed')
    if REMOTE.search(fields['Location']):
        raise ValueError('event_not_public')
    start, end = _times(fields['Date'] + 'T' + fields['Start Time'], fields['Date'] + 'T' + fields['End Time'])
    content = soup.select_one('.elementor-widget-theme-post-content')
    if content is None or soup.title is None:
        raise ValueError('nyc_final_detail_changed')
    title = plain(soup.title.get_text()).removesuffix(' - Bronx River Alliance')
    body = _body(str(content))
    place = _place(BRONX, fields['Location'])
    category = ', '.join(dict.fromkeys(plain(a.get_text()) for a in soup.select('a[rel="tag"]')))
    image = soup.select_one('meta[property="og:image"]')
    row = _row(BRONX, item['url'], title, start, end, body, place, item['url'], now,
               category, image.get('content') if image else None)
    return [row] if row else []


def _bkup_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    events = _jsonld(soup, 'Event')
    if len(events) != 1:
        raise ValueError('nyc_final_detail_changed')
    event = events[0]
    if event.get('url') != item['url']:
        raise ValueError('nyc_final_detail_changed')
    if (event.get('eventAttendanceMode') != 'https://schema.org/OfflineEventAttendanceMode'
            or event.get('eventStatus') != 'https://schema.org/EventScheduled'):
        raise ValueError('event_not_public')
    card = soup.select_one('.marketing-public-detail-card')
    if card is None:
        raise ValueError('nyc_final_detail_changed')
    # The JSON-LD and list descriptions are visibly shortened. Only this full
    # editorial body and the native participation/fee policies are ingested.
    title = plain(card.select_one('h1').get_text()) if card.select_one('h1') else ''
    if re.search(r'\b(?:physical therapy|private coaching|1:1 appointment|climbing rehab)\b', title, re.I):
        raise ValueError('event_not_public')
    content = card.select_one('.event-description-rich')
    if content is None:
        raise ValueError('description_missing')
    if re.search(r'\b(?:sold out|fully booked|0 spots left|event cancelled)\b', card.get_text(' ', strip=True), re.I):
        raise ValueError('registration_closed')
    native = event.get('location', {}).get('address', {})
    if (native.get('streetAddress'), native.get('addressLocality'), native.get('addressRegion'), native.get('postalCode')) == ('20 John St', 'Brooklyn', 'NY', '11201'):
        place = _place(BKUP, 'Brooklyn Uprising')
    elif native.get('streetAddress') == '32 Pearl St, Brooklyn, NY 11201' and event.get('location', {}).get('name') == 'Ritual Moves - Yoga Room':
        place = _place(BKUP, 'Ritual Moves - Yoga Room')
    else:
        raise ValueError('venue_conflict')
    parts = [str(content)]
    parts.extend(str(node) for node in card.find_all('div', recursive=False) if node.get_text(' ', strip=True).startswith('Location:'))
    for section in card.find_all('div', recursive=False):
        if section.get_text(' ', strip=True).startswith('Instructor '):
            parts.append(str(section))
    parts.extend(str(x) for x in card.select('.event-fee-policy-callout'))
    access = next((p for p in card.select('p') if 'Access to the gym via a pass or membership' in p.get_text()), None)
    if access is not None:
        parts.append(str(access))
    requirements = next((node for node in soup.select('.marketing-news-footer-top > div')
                         if node.get_text(' ', strip=True).startswith('Important Information')), None)
    if requirements is None:
        raise ValueError('nyc_final_detail_changed')
    parts.append(str(requirements))
    start, end = _times(event.get('startDate'), event.get('endDate'))
    title = plain(card.select_one('h1').get_text()) if card.select_one('h1') else ''
    type_node = card.select_one('div.mb-3')
    category = plain(type_node.get_text()) if type_node else ''
    if re.search(r'\b(?:physical therapy|private coaching|1:1 appointment)\b', title, re.I):
        raise ValueError('event_not_public')
    row = _row(BKUP, item['url'].rsplit('/', 1)[-1], title, start, end, '\n'.join(parts), place,
               item['url'], now, category)
    return [row] if row else []


def _wave_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    root = soup.select_one('.page__program')
    if root is None or root.select_one('h1') is None:
        raise ValueError('nyc_final_detail_changed')
    title = plain(root.select_one('h1').get_text())
    if title != item['title']:
        raise ValueError('nyc_final_detail_changed')
    if re.search(r'\b(?:closed|early close)\b', title, re.I):
        raise ValueError('event_not_public')
    details = {}
    for section in root.select('.page__detail'):
        label = section.select_one('.page__detail-subtitle')
        if label:
            details[plain(label.get_text())] = section
    where = details.get('Where')
    venue = plain(where.select_one('.page__detail-title').get_text()) if where and where.select_one('.page__detail-title') else ''
    if not venue or REMOTE.search(venue):
        raise ValueError('venue_not_reviewed')
    place = _place(WAVE, venue)
    entries = root.select('.page__entry--rich-text')
    if not entries:
        raise ValueError('description_missing')
    parts = [str(x) for x in entries]
    if 'Price' in details:
        parts.append(str(details['Price']))
    body = _body('\n'.join(parts))
    categories = ', '.join(plain(x.get_text()) for x in root.select('.page__categories-item'))
    image = root.select_one('.page__background img[src]')
    image_url = urljoin(item['url'], image['src']) if image else None
    rows = []
    for occurrence in item['occurrences']:
        if occurrence['all_day']:
            raise ValueError('all_day_without_hours')
        start, end = _times(occurrence['start'], occurrence['end'])
        row = _row(WAVE, item['url'], title, start, end, body, place, item['url'], now, categories, image_url)
        if row:
            rows.append(row)
    return rows


def _nyrr_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    events = _jsonld(soup, 'SportsEvent')
    if len(events) != 1:
        raise ValueError('nyc_final_detail_changed')
    event = events[0]
    if event.get('eventStatus') != 'https://schema.org/EventScheduled':
        raise ValueError('event_not_public')
    native = event.get('location', {})
    if native.get('address', {}).get('addressRegion') != 'New York':
        raise ValueError('venue_not_reviewed')
    main = soup.select_one('main')
    schedule = main.select_one('p._1jjn27a4') if main else None
    if not schedule:
        raise ValueError('nyc_final_detail_changed')
    match = re.match(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s at (\d{2}:\d{2} [AP]M),', schedule.get_text(' ', strip=True))
    if not match:
        raise ValueError('time_unverified')
    weekday = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].index(match[1])
    clock = datetime.strptime(match[2], '%I:%M %p').time()
    first, last = _times(event.get('startDate'), event.get('endDate'))
    first, last = first.astimezone(ZoneInfo(ZONE)), last.astimezone(ZoneInfo(ZONE))
    if (first.weekday() != weekday or last.weekday() != weekday
            or first.time().replace(tzinfo=None) != clock or last.time().replace(tzinfo=None) != clock
            or last - first > timedelta(days=370)):
        raise ValueError('schedule_conflict')
    place = _place(NYRR, event.get('name'))
    if place is None or native.get('name') != place.get('native_meeting'):
        raise ValueError('venue_not_reviewed')
    direction = next((a['href'] for a in schedule.select('a[href]') if 'google.com/maps/dir/Current+Location/' in a['href']), None)
    expected = 'https://www.google.com/maps/dir/Current+Location/' + place['native_direction']
    if direction != expected:
        raise ValueError('venue_conflict')
    summary = main.select_one('p._1jjn27a6')
    body_section = schedule.parent
    if summary is None:
        raise ValueError('description_missing')
    parts = [str(summary), str(schedule)]
    # Preserve the complete publisher narrative, including expanded paragraphs
    # and check-in/waiver/access rules. Remove only UI toggles and duplicate prose.
    for node in body_section.select('.x2jflr1'):
        parts.append(str(node))
    faq = next((h for h in main.select('h2,h3') if plain(h.get_text()) == 'FAQ'), None)
    if faq:
        parts.append(str(faq.parent))
    unique, seen = [], set()
    for part in parts:
        normalized = _body(part)
        if normalized not in seen:
            unique.append(part)
            seen.add(normalized)
    body = _body('\n'.join(unique))
    cursor = max(first.date(), now.astimezone(ZoneInfo(ZONE)).date())
    cursor += timedelta(days=(weekday - cursor.weekday()) % 7)
    until = min(last.date(), (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date())
    rows = []
    while cursor <= until:
        start = datetime.combine(cursor, clock, ZoneInfo(ZONE))
        if _within(start, None, now):
            row = _row(NYRR, item['url'], event.get('name') + ' Open Run', start, None, body, place,
                       item['url'], now, 'Community Run / Walk')
            if row:
                row.update(schedule_provenance='publisher_explicit_bounded_weekly_schedule',
                           recurrence_first=first.isoformat(), recurrence_last=last.isoformat())
                rows.append(row)
        cursor += timedelta(days=7)
    if not rows:
        raise ValueError('event_not_current')
    return rows


def _bridge_manifest(fetch, now, deadline):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    _budget(deadline)
    calendar_url = 'https://brooklynbridgepark.org/wp-admin/admin-ajax.php?' + urlencode({
        'action': 'get_calendar_events', 'start': day.isoformat(), 'end': (day + timedelta(days=60)).isoformat()})
    calendar = json.loads(fetch(calendar_url, 'application/json'))
    if not isinstance(calendar, list) or len(calendar) > 100:
        raise ValueError('nyc_final_record_limit')
    identifiers = [x.get('id') for x in calendar if isinstance(x, dict)]
    if len(identifiers) != len(calendar) or any(type(x) is not int for x in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('nyc_final_payload_changed')
    if not calendar:
        return []
    _budget(deadline)
    posts = json.loads(fetch('https://brooklynbridgepark.org/wp-json/wp/v2/events?' + urlencode({
        'include': ','.join(map(str, sorted(identifiers))), 'per_page': 100}), 'application/json'))
    if not isinstance(posts, list) or {x.get('id') for x in posts} != set(identifiers) or len(posts) != len(calendar):
        raise ValueError('nyc_final_pagination_incomplete')
    locations = sorted({v for p in posts for v in p.get('acf', {}).get('event_location', [])})
    if len(locations) > 100 or any(type(x) is not int for x in locations):
        raise ValueError('nyc_final_payload_changed')
    _budget(deadline)
    native_locations = json.loads(fetch('https://brooklynbridgepark.org/wp-json/wp/v2/maplocations?' + urlencode({
        'include': ','.join(map(str, locations)), 'per_page': 100}), 'application/json'))
    if not isinstance(native_locations, list) or {x.get('id') for x in native_locations} != set(locations):
        raise ValueError('nyc_final_pagination_incomplete')
    index = {x['id']: x for x in calendar}
    geo_index = {x['id']: x for x in native_locations}
    return [dict(post=p, calendar=index[p['id']], locations=geo_index) for p in posts]


def _bridge_rows(item, now):
    post, listing = item['post'], item['calendar']
    acf = post.get('acf', {})
    if post.get('status') != 'publish' or acf.get('status') != 'Scheduled':
        raise ValueError('event_not_public')
    if acf.get('multi-day') or acf.get('recurring_event'):
        raise ValueError('time_unverified')
    start, end = _times(listing.get('start'), listing.get('end'))
    try:
        day = datetime.strptime(acf.get('date', ''), '%Y%m%d').date()
        native_start = datetime.combine(day, datetime.strptime(acf.get('start_time', ''), '%I:%M %p').time(), ZoneInfo(ZONE))
        native_end = datetime.combine(day, datetime.strptime(acf.get('end_time', ''), '%I:%M %p').time(), ZoneInfo(ZONE))
    except (TypeError, ValueError):
        raise ValueError('time_unverified') from None
    if (start, end) != (native_start, native_end) or post.get('link') != listing.get('url'):
        raise ValueError('schedule_conflict')
    ids = acf.get('event_location')
    if not isinstance(ids, list) or len(ids) != 1:
        raise ValueError('venue_not_reviewed')
    place = _place(BRIDGE, ids[0])
    native = item['locations'].get(ids[0], {}).get('acf', {})
    if place is None or native.get('latitude') != place.get('native_lat') or native.get('longitude') != place.get('native_lng'):
        raise ValueError('venue_conflict')
    parts = [acf.get('description')]
    if plain(acf.get('time_notes')):
        parts.append(acf['time_notes'])
    if plain(acf.get('optional_cta')):
        parts.append(acf['optional_cta'])
    body = _body('\n'.join(str(x or '') for x in parts))
    photos = post.get('yoast_head_json', {}).get('og_image', [])
    photo = photos[0].get('url') if photos else None
    row = _row(BRIDGE, post['id'], post.get('title', {}).get('rendered'), start, end, body, place,
               post['link'], now, plain(listing.get('category')), photo)
    return [row] if row else []


def _transalt_manifest(fetch, now, deadline):
    url = 'https://api.mobilize.us/v1/organizations/35772/events?' + urlencode({'timeslot_end': 'gte_' + str(int(now.timestamp()))})
    result, seen = [], set()
    for _ in range(10):
        _budget(deadline)
        if not url.startswith('https://api.mobilize.us/v1/organizations/35772/events') or url in seen:
            raise ValueError('nyc_final_pagination_incomplete')
        seen.add(url)
        data = json.loads(fetch(url, 'application/json'))
        if not isinstance(data.get('data'), list):
            raise ValueError('nyc_final_payload_changed')
        result.extend(data['data'])
        if len(result) > MAX_RECORDS:
            raise ValueError('nyc_final_record_limit')
        url = data.get('next')
        if not url:
            break
    else:
        raise ValueError('nyc_final_pagination_incomplete')
    if len({e.get('id') for e in result}) != len(result):
        raise ValueError('nyc_final_pagination_incomplete')
    return result


def _transalt_rows(event, now):
    if (event.get('sponsor', {}).get('id') != 35772 or event.get('is_virtual') is not False
            or event.get('visibility') != 'PUBLIC' or event.get('address_visibility') != 'PUBLIC'
            or event.get('approval_status') != 'APPROVED'):
        raise ValueError('event_not_public')
    if event.get('timezone') != ZONE:
        raise ValueError('time_unverified')
    native = event.get('location') or {}
    place = _place(TRANSALT, event.get('id'))
    if (not place or native.get('address_lines') != place.get('native_address_lines')
            or native.get('location') != place.get('native_geo')
            or native.get('postal_code') != place.get('native_postal_code')):
        raise ValueError('venue_not_reviewed')
    parts = [event.get('description')]
    if event.get('accessibility_notes'):
        parts.append(event['accessibility_notes'])
    body = _body('\n'.join(str(x or '') for x in parts))
    rows = []
    for timeslot in event.get('timeslots', []):
        if timeslot.get('is_full'):
            continue
        try:
            start = datetime.fromtimestamp(timeslot['start_date'], timezone.utc)
            end = datetime.fromtimestamp(timeslot['end_date'], timezone.utc)
            if end <= start:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError('time_unverified') from None
        if not _within(start, end, now):
            continue
        row = _row(TRANSALT, str(event['id']) + ':' + str(timeslot['id']), event.get('title'), start, end,
                   body, place, event.get('browser_url'), now, event.get('event_type', ''), event.get('featured_image_url'))
        if row:
            rows.append(row)
    if not rows:
        raise ValueError('event_not_current')
    return rows


def _manifest(key, fetch, now, deadline):
    if key == WAVE:
        return _wave_manifest(fetch, now, deadline)
    _budget(deadline)
    return _simple_manifest(key, fetch(SOURCES[key][0], 'text/html'))


def _digest(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        valid = (isinstance(value, dict) and type(value.get('version')) is int and value['version'] == 1
                 and value.get('source_key') == key and type(value.get('cursor')) is int
                 and type(value.get('manifest_count')) is int
                 and 0 <= value['cursor'] <= value['manifest_count'] <= MAX_MANIFEST
                 and isinstance(value.get('queue'), list) and len(value['queue']) == value['manifest_count']
                 and isinstance(value.get('events'), list) and len(value['events']) <= 201
                 and isinstance(value.get('diagnostics'), list) and len(value['diagnostics']) <= MAX_MANIFEST
                 and value.get('manifest_hash') == _digest(value['queue'])
                 and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        if not valid:
            raise ValueError
        started = timestamp(value['started_at'])
        if (not re.fullmatch(r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:\+00:00|Z)', value['started_at'])
                or started is None or value['window_start'] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()):
            raise ValueError
        if not timedelta(0) <= now - started <= timedelta(hours=4):
            return None
        queue = value['queue']
        if (any(not isinstance(q, dict) or not event_url(key, q.get('url')) for q in queue)
                or len({q['url'] for q in queue}) != len(queue)):
            raise ValueError
        prefix = {q['url'] for q in queue[:value['cursor']]}
        represented, ids = set(), set()
        for row in value['events']:
            if not isinstance(row, dict) or row.get('event_url') not in prefix:
                raise ValueError
            start, end = _times(row.get('starts_at'), row.get('ends_at'))
            if (row.get('id') in ids or row.get('id') != _id(key, row.get('publisher_native_id'), start)
                    or row.get('timezone') != ZONE or row.get('attendance_mode') != 'in_person'
                    or not isinstance(row.get('description'), str) or _body(row['description']) != row['description']
                    or not row.get('venue_name') or not row.get('venue_address')
                    or _point(row.get('lat'), row.get('lng')) is None
                    or reviewed_venue_location(key, row['venue_name'], row['venue_address']) != {'lat': row['lat'], 'lng': row['lng']}
                    or row.get('image_url') is not None and not photo_url(key, row['image_url'])):
                raise ValueError
            represented.add(row['event_url'])
            ids.add(row['id'])
        for held in value['diagnostics']:
            if (not isinstance(held, dict) or held.get('source_key') != key or held.get('event_url') not in prefix
                    or held['event_url'] in represented or held.get('disposition') != 'held'
                    or held.get('reason') not in HOLD_REASONS):
                raise ValueError
            represented.add(held['event_url'])
        if represented != prefix:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('nyc_final_checkpoint_invalid') from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=None):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError('nyc_final_source_unregistered')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('nyc_final_checkpoint_invalid')
    state = _checkpoint(checkpoint, key, current)
    created = state is None
    if created:
        queue = _manifest(key, fetch, current, deadline_at)
        state = dict(version=1, source_key=key, started_at=current.astimezone(timezone.utc).isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(), manifest_hash=_digest(queue),
                     manifest_count=len(queue), queue=queue, cursor=0, events=[], diagnostics=[])
    anchor = timestamp(state['started_at'])
    queue, prior = state['queue'], state['cursor']
    # The four-hour manifest snapshot is immutable, including across midnight;
    # every detail is hydrated at its processing time. No stale listing excerpt
    # is ever staged, and a completed retry replays the identical completed wire.
    limit = MAX_DETAILS if max_details is None else min(MAX_DETAILS, max(1, int(max_details)))
    for item in queue[prior:prior + limit]:
        if deadline_at is not None and monotonic() + 18 >= deadline_at:
            break
        try:
            payload = fetch(item['url'], 'text/html')
            parser = {BRONX: _bronx_detail, BKUP: _bkup_detail, WAVE: _wave_detail, NYRR: _nyrr_detail}[key]
            rows = parser(item, payload, anchor)
            if not rows:
                raise ValueError('event_not_current')
            state['events'].extend(rows)
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            state['diagnostics'].append(_held(key, item['url'], item.get('title'), str(exc), item['url']))
        state['cursor'] += 1
        if len(state['events']) > 201:
            raise ValueError('nyc_final_record_limit')
    if state['cursor'] == prior < len(queue) and not created:
        raise ValueError('collection_deadline')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('nyc_final_checkpoint_size_limit')
    complete = state['cursor'] == len(queue)
    return dict(complete=complete, checkpoint=state, diagnostics=deepcopy(state['diagnostics']),
                events=deepcopy(sorted(state['events'], key=lambda x: (x['starts_at'], x['id']))) if complete else [])


def _parks_location_id(event):
    try:
        parts = [float(x.strip()) for x in str(event.get('coordinates') or '').split(',')]
        if len(parts) != 2 or _point(*parts) is None:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError('point_unresolved') from None
    return str(event.get('location') or '') + '|' + ','.join(str(x) for x in parts) + '|' + str(event.get('parkids') or '').upper()


def _parks_manifest(fetch, now, deadline):
    # w3wp-dpdi is the publisher's rolling two-week public events export.
    # Query the entire defined window; overflow fails, it never slices rows.
    _budget(deadline)
    local = now.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None, microsecond=0)
    until = local.date() + timedelta(days=14)
    url = SOURCES[PARKS][0] + '?' + urlencode({
        '$where': "endtime >= '" + local.isoformat() + "' AND starttime < '" + until.isoformat() + "T00:00:00'",
        '$order': 'starttime,guid', '$limit': MAX_RECORDS + 1})
    events = json.loads(fetch(url, 'application/json'))
    if not isinstance(events, list) or len(events) > MAX_RECORDS:
        raise ValueError('nyc_final_record_limit')
    if any(not isinstance(x, dict) for x in events) or len({x.get('guid') for x in events}) != len(events):
        raise ValueError('nyc_final_payload_changed')
    return events


def _parks_rows(event, now):
    title = plain(event.get('title'))
    native_name = str(event.get('location') or '')
    if NONPUBLIC.search(title) or REMOTE.search(native_name):
        raise ValueError('event_not_public')
    # Existing/direct publisher ownership is explicit; the citywide source is
    # still processed completely, with these exclusions recorded per native ID.
    categories = [v.strip() for v in str(event.get('categories') or '').split('|')]
    direct_greenbelt = {'2282507': '2003425962986', '2282245': '2003428843602', '2282504': '2003430102367'}
    registration = event.get('registration_url')
    registration = registration.get('url') if isinstance(registration, dict) else registration
    if str(event.get('guid')) in direct_greenbelt and isinstance(registration, str) and re.fullmatch(r'https://www\.eventbrite\.com/e/[^?#]*' + direct_greenbelt[str(event['guid'])] + r'(?:\?[^#]*)?', registration):
        raise ValueError('other_source_owns_event')
    if (re.match(r"^it['’]s my park\b", title, re.I)
            or re.match(r'^NYRR Open Run\b', title, re.I)
            or str(event.get('parkids') or '').upper().startswith('R') and 'Urban Park Rangers' in categories
            or native_name == 'Wave Hill'):
        raise ValueError('other_source_owns_event')
    start, end = _times(event.get('starttime'), event.get('endtime'))
    if not _within(start, end, now):
        raise ValueError('event_not_current')
    link = event.get('link')
    url = link.get('url') if isinstance(link, dict) else link
    if isinstance(url, str) and url.startswith('http://www.nycgovparks.org/'):
        url = 'https://' + url[len('http://'):]
    if not isinstance(url, str) or not re.fullmatch(r'https://www\.nycgovparks\.org/events/20\d{2}/\d{2}/\d{2}/[a-zA-Z0-9_-]+/?', url):
        raise ValueError('event_link_unresolved')
    if native_name == "Randall's Island Park" and re.search(r'notified after registration', str(event.get('description') or ''), re.I):
        raise ValueError('street_unresolved')
    if native_name == 'Oak Ridge (in Forest Park)':
        raise ValueError('venue_conflict')
    if str(event.get('guid')) == '2315505' and native_name == '' and re.search(r'Rev\.? T\.? Wendell Foster Park', title, re.I) and 'near the E.164 St. park entrance' in str(event.get('description') or ''):
        place = _place(PARKS, 'event:2315505')
    else:
        place = _place(PARKS, _parks_location_id(event))
    parts = [_body(event.get('description'))]
    for key, label in [('registration_description', 'Registration'), ('instructor', 'Instructor')]:
        if plain(event.get(key)):
            parts.append(label + ': ' + _body(event[key]))
    for key, label in [('registration_url', 'Registration link'), ('contact_phone', 'Contact phone')]:
        value = event.get(key)
        if isinstance(value, dict):
            value = value.get('url')
        if plain(value):
            parts.append(label + ': ' + plain(value))
    image = event.get('image')
    if isinstance(image, dict):
        image = image.get('url')
    if isinstance(image, str) and image.startswith('http://www.nycgovparks.org/'):
        image = image.replace('http://', 'https://', 1)
    row = _row(PARKS, event.get('guid'), title, start, end, '\n\n'.join(parts), place, url, now,
               ', '.join(categories), image)
    return [row] if row else []


def collect_with_diagnostics(source, fetch, *, deadline_at=None, now=None):
    key, now = _source(source), now or datetime.now(timezone.utc)
    if key in CHECKPOINT_KEYS:
        result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
        if not result['complete']:
            raise ValueError('nyc_final_checkpoint_required')
        return result['events'], result['diagnostics']
    loaders = {FORDHAM: (_fordham_manifest, _fordham_rows), CB6: (_tribe_manifest, _tribe_rows),
               BRIDGE: (_bridge_manifest, _bridge_rows), TRANSALT: (_transalt_manifest, _transalt_rows),
               PARKS: (_parks_manifest, _parks_rows)}
    loader, parser = loaders[key]
    native = loader(fetch, now, deadline_at)
    rows, diagnostics = [], []
    for item in native:
        identity = item.get('id', item.get('guid', item.get('event', {}).get('id', item.get('post', {}).get('id'))))
        title = item.get('title') or item.get('event', {}).get('title') or item.get('post', {}).get('title', {}).get('rendered')
        try:
            accepted = parser(item, now)
            if not accepted:
                raise ValueError('event_not_current')
            rows.extend(accepted)
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            diagnostics.append(_held(key, identity, title, str(exc)))
    if len(rows) > MAX_RECORDS or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('nyc_final_record_limit')
    return sorted(rows, key=lambda x: (x['starts_at'], x['id'])), diagnostics


def collect(source, fetch, *, deadline_at=None, now=None):
    return collect_with_diagnostics(source, fetch, deadline_at=deadline_at, now=now)[0]
