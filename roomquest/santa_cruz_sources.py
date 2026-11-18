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
API = '/wp-json/tribe/events/v1/events'
SOURCES = {
    UCSC: ('https://events.ucsc.edu' + API, 'json', 'wordpress'),
    KUUMBWA: ('https://www.kuumbwajazz.org' + API, 'json', 'wordpress'),
    NATURAL_HISTORY: ('https://santacruzmuseum.org' + API, 'json', 'wordpress'),
    VISIT_SANTA_CRUZ: ('https://www.santacruz.org' + API, 'json', 'wordpress'),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
MAX_PAGES = {UCSC: 3, KUUMBWA: 1, NATURAL_HISTORY: 1, VISIT_SANTA_CRUZ: 4}
PAGE_SIZE = 100
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 30
SOURCE_WINDOW_DAYS = {VISIT_SANTA_CRUZ: 17}
CITY_WHITELIST = {
    'santa cruz', 'aptos', 'capitola', 'watsonville', 'scotts valley',
    'felton', 'soquel', 'ben lomond', 'boulder creek', 'live oak',
    'bonny doon', 'davenport', 'la selva beach', 'freedom',
}
STREET = re.compile(
    r'\b[0-9]{1,6}[a-z]?\s+(?![0-9]{1,6}\s|on\s|at\s|near\s|in\s|of\s)(?:[a-z0-9.#\x27-]+\s+){1,9}'
    r'(?:street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|'
    r'court|ct|way|parkway|pkwy|place|pl|plaza|circle|cir|highway|hwy|'
    r'terrace|ter|trail|trl)\b\.?', re.I)
IMAGE_HOST = {UCSC: 'events.ucsc.edu', KUUMBWA: 'www.kuumbwajazz.org',
              NATURAL_HISTORY: 'santacruzmuseum.org', VISIT_SANTA_CRUZ: 'www.santacruz.org'}
NO_IMAGE = re.compile(r'(?:^|[-_/])(?:logo|favicon|icon|avatar|placeholder|pixel)(?:[-_.]|$)', re.I)
SMALL_IMAGE = re.compile(r'-[1-5][0-9]{1,2}x[1-5][0-9]{1,2}\.(?:png|jpe?g|webp)$', re.I)
NONPUBLIC = re.compile(r'\b(?:cancelled|canceled|postponed|private event|members[- ]only|invite[- ]only)\b', re.I)


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str):
        return False
    url = urlsplit(value)
    path = ('/calendar/' if key == KUUMBWA else
            '/upcoming-event/' if key == VISIT_SANTA_CRUZ else '/event/')
    date_suffix = r'(?:20\d{2}-\d{2}-\d{2}/)?' if key in (NATURAL_HISTORY, VISIT_SANTA_CRUZ) else ''
    return bool(url.scheme == 'https' and url.hostname == ALLOWED_HOSTS[key][0]
                and not url.username and not url.password and url.port in (None, 443)
                and not url.query and not url.fragment
                and re.fullmatch(path + r'[a-z0-9]+(?:-[a-z0-9]+)*/' + date_suffix,
                                 url.path))


def photo_url(key, value):
    if key not in IMAGE_HOST or not isinstance(value, str) or len(value) > 2000:
        return None
    url = urlsplit(value)
    if (url.scheme != 'https' or url.hostname != IMAGE_HOST[key] or url.query or url.fragment
            or url.username or url.password or url.port not in (None, 443)
            or not re.fullmatch(r'/wp-content/uploads/20\d{2}/(?:0?[1-9]|1[0-2])/'
                                r'[^/?#\s]+\.(?:jpg|jpeg|png|webp)', url.path, re.I)
            or NO_IMAGE.search(url.path) or SMALL_IMAGE.search(url.path)):
        return None
    return value


def _full_description(value):
    """Sanitize complete publisher description, never silently truncate."""
    from roomquest.event_description import description
    if not isinstance(value, str):
        return None
    narrative = description(value, limit=max(len(value), MAX_DESCRIPTION + 1))
    return narrative if narrative and len(narrative) <= MAX_DESCRIPTION else None


def _street(venue):
    """Use only the occurrence's own physical number and street."""
    raw = plain(venue.get('address'))
    city = plain(venue.get('city'))
    state = plain(venue.get('state') or venue.get('stateprovince') or venue.get('province'))
    zipcode = plain(venue.get('zip'))
    if city.casefold() not in CITY_WHITELIST or state.casefold() not in ('', 'ca', 'california'):
        return None
    match = STREET.search(raw)
    if not match:
        return None
    street = match.group(0).strip(' .,')
    if zipcode and not re.fullmatch(r'\d{5}(?:-\d{4})?', zipcode):
        zipcode = ''
    return f'{street}, {city}, CA' + (f' {zipcode}' if zipcode else '')


def _point(venue):
    try:
        lat, lng = float(venue.get('geo_lat')), float(venue.get('geo_lng'))
        if math.isfinite(lat) and math.isfinite(lng) and 36.75 <= lat <= 37.3 and -122.4 <= lng <= -121.6:
            return lat, lng
    except (TypeError, ValueError, OverflowError):
        pass
    return None, None


def _labels(item):
    out = []
    for category in item.get('categories') or []:
        if isinstance(category, dict) and isinstance(category.get('name'), str):
            name = plain(category['name'])[:100]
            if name and name not in out:
                out.append(name)
    return out[:20]


def _row(key, event):
    if not isinstance(event, dict) or event.get('id') in (None, ''):
        raise ValueError('invalid_publisher_event')
    identity = str(event['id'])
    if event.get('status') != 'publish' or event.get('hide_from_listings') or event.get('all_day'):
        return None
    title = plain(event.get('title'))
    if not title or NONPUBLIC.search(title):
        return None
    if event.get('timezone') != ZONE:
        log.info('santa_cruz_hold source=%s id=%s reason=timezone', key, identity[:80])
        return None
    start = timestamp(event.get('utc_start_date'), 'UTC')
    wall_start = timestamp(event.get('start_date'), ZONE)
    end = timestamp(event.get('utc_end_date'), 'UTC')
    if start is None or wall_start != start or (end is not None and end < start):
        log.info('santa_cruz_hold source=%s id=%s reason=schedule', key, identity[:80])
        return None
    venue = event.get('venue') if isinstance(event.get('venue'), dict) else {}
    name = plain(venue.get('venue'))
    street = _street(venue)
    if not name or not street:
        log.info('santa_cruz_hold source=%s id=%s reason=street', key, identity[:80])
        return None
    narrative = _full_description(event.get('description'))
    if not narrative:
        log.info('santa_cruz_hold source=%s id=%s reason=description', key, identity[:80])
        return None
    link = event.get('url')
    if key == VISIT_SANTA_CRUZ and not re.fullmatch(r'.*/20[0-9]{2}-[0-9]{2}-[0-9]{2}/', str(link)):
        log.info('santa_cruz_hold source=%s id=%s reason=dated_occurrence',key,identity[:80])
        return None
    if not event_url(key, link):
        log.info('santa_cruz_hold source=%s id=%s reason=event_url', key, identity[:80])
        return None
    labels = _labels(event)
    lat, lng = _point(venue)
    item = record(title, start.isoformat(), end.isoformat() if end and end > start else None,
                  name, street, plain(venue.get('city')), link, identity,
                  ', '.join(labels), lat, lng, ZONE, retain_until_end=True)
    if item is None:
        return None
    item.update(description=narrative, timezone=ZONE, publisher_categories=labels,
                location_provenance='publisher_event_venue')
    from roomquest.publisher_evidence import attach
    picture = event.get('image') if isinstance(event.get('image'), dict) else {}
    candidate = picture.get('url')
    if key == VISIT_SANTA_CRUZ and re.search(r'(?:[_-]\d{2,4}x\d{2,4})\.',str(candidate),re.I):
        candidate = None
    try:
        if picture.get('width') is not None and float(picture['width']) < 600:
            candidate = None
    except (TypeError, ValueError):
        candidate = None
    details = {'cost': plain(event['cost'])[:400]} if isinstance(event.get('cost'), str) and plain(event['cost']) else {}
    return attach(item, key, facts=details, candidate=candidate)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if (key not in SOURCES or
            (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != SOURCES[key] or
            source.get('timezone') != ZONE):
        raise ValueError('unregistered_santa_cruz_source')
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE))
    deadline = min(monotonic() + 39, deadline_at or float('inf'))
    params = {'per_page': PAGE_SIZE, 'start_date': now.date().isoformat(),
              'end_date': (now + timedelta(days=SOURCE_WINDOW_DAYS.get(key, WINDOW_DAYS))).date().isoformat()}
    rows = {}
    for page in range(1, MAX_PAGES[key] + 1):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        url = SOURCES[key][0] + '?' + urlencode(dict(params, page=page))
        payload = json.loads(fetch(url, 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
            raise ValueError('invalid_wordpress_payload')
        pages = payload.get('total_pages', 1)
        if type(pages) is not int or pages < 1 or pages > MAX_PAGES[key] or len(payload['events']) > PAGE_SIZE:
            raise ValueError('pagination_limit')
        for event in payload['events']:
            item = _row(key, event)
            if item is None:
                continue
            ident = (item['id'], item['starts_at'])
            if ident in rows and rows[ident] != item:
                raise ValueError('conflicting_event_occurrence')
            rows[ident] = item
        if len(rows) > MAX_RECORDS:
            raise ValueError('source_record_limit')
        if page >= pages:
            break
    return sorted(rows.values(), key=lambda x: (x['starts_at'], x['title'], x['id']))
