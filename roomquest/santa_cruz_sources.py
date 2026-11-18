"""Santa Cruz, CA publisher-primary Events Calendar REST adapters.

Only reviewed first-party endpoints. Hold missing/ambiguous event details, never
supply a default venue address or coordinates. Publisher photo URLs are only
candidates for the backend's rights/size checks. No HTML scraping or extra fetch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import math
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo
import json

from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = 'America/Los_Angeles'
UCSC = 'uc_santa_cruz_primary_ca'
KUUMBWA = 'kuumbwa_jazz_santa_cruz_ca'
NATURAL_HISTORY = 'santa_cruz_museum_natural_history_ca'
VISIT_SANTA_CRUZ = 'visit_santa_cruz_county_ca'
FIRST_FRIDAY = 'first_friday_santa_cruz_ca'
CAPITOLA_VILLAGE = 'capitola_village_events_ca'
API = '/wp-json/tribe/events/v1/events'
SOURCES = {
    UCSC: ('https://events.ucsc.edu' + API, 'json', 'wordpress'),
    KUUMBWA: ('https://www.kuumbwajazz.org' + API, 'json', 'wordpress'),
    NATURAL_HISTORY: ('https://santacruzmuseum.org' + API, 'json', 'wordpress'),
    VISIT_SANTA_CRUZ: ('https://www.santacruz.org' + API, 'json', 'wordpress'),
    FIRST_FRIDAY: ('https://firstfridaysantacruz.com' + API, 'json', 'wordpress'),
    CAPITOLA_VILLAGE: ('https://capitolavillage.com' + API, 'json', 'wordpress'),
}
ALLOWED_HOSTS = {key: (urlsplit(va¶»§q«^