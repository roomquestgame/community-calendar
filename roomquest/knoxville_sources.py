"""Knoxville, Tennessee primary publisher calendars on the shared lanes.

Three Events Calendar (TEC) REST calendars and one iCalendar feed, each an
organizer's own calendar. Only the exact registered endpoint is read; response
"next" links are never followed. Descriptions are the complete publisher text:
blank or oversized text is held, never manufactured or shortened. Each event
keeps its own published venue street. A missing or number-less street is held
for review; it is never replaced by a source-wide pin or a guessed number. One
reviewed venue street is used only for an exact venue name whose own record
leaves the street blank. All-day entries have no published clock and are held.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)

ZONE = 'America/New_York'
WDVX = 'wdvx_knoxville_tn'
HISTORY = 'east_tn_history_center_tn'
CHAMBER = 'knoxville_chamber_tn'
MAKERS = 'knox_makers_tn'

TRIBE_PATH = '/wp-json/tribe/events/v1/events'
SOURCES = {
    WDVX: ('https://wdvx.com' + TRIBE_PATH, 'json', 'wordpress'),
    HISTORY: ('https://www.easttnhistory.org' + TRIBE_PATH, 'json', 'wordpress'),
    CHAMBER: ('https://www.knoxvillechamber.com' + TRIBE_PATH, 'json', 'wordpress'),
    MAKERS: ('https://events.knoxmakers.org/calendar.ics', 'ical', 'ical'),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
# Each calendar lists under 50 dated occurrences in 60 days (one page).
MAX_PAGES = {WDVX: 2, HISTORY: 2, CHAMBER: 2}
MAX_RECORDS = 600
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
MIN_IMAGE_WIDTH = 600

_SLUG = r'[a-z0-9]+(?:-[a-z0-9]+)*'
_DATE = r'20[0-9]{2}-[0-9]{2}-[0-9]{2}'
EVENT_URLS = {
    WDVX: re.compile(rf'https://wdvx\.com/event/{_SLUG}/(?:{_DATE}/)?'),
    HISTORY: re.compile(rf'https://www\.easttnhistory\.org/event/{_SLUG}/(?:{_DATE}/)?'),
    CHAMBER: re.compile(rf'https://www\.knoxvillechamber\.com/community-calendar/{_SLUG}/(?:{_DATE}/)?'),
    MAKERS: re.compile(rf'https://events\.knoxmakers\.org/event/{_SLUG}'),
}
# Full-size featured media from each publisher's own WordPress upload library.
PHOTO_URLS = {
    WDVX: re.compile(r'https://wdvx\.com/site/wp-content/uploads/20[0-9]{2}/[01][0-9]/[^/?#\s]+\.(?:jpe?g|png|webp)', re.I),
    HISTORY: re.compile(r'https://www\.easttnhistory\.org/wp-content/uploads/20[0-9]{2}/[01][0-9]/[^/?#\s]+\.(?:jpe?g|png|webp)', re.I),
    CHAMBER: re.compile(r'https://www\.knoxvillechamber\.com/wp-content/uploads/20[0-9]{2}/[01][0-9]/[^/?#\s]+\.(?:jpe?g|png|webp)', re.I),
}
_NOT_PHOTO = re.compile(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel|placeholder|icon)(?:[-_.]|$)', re.I)
# Publisher label for closure notices, not attendable events.
CLOSURE_LABELS = {'museum closures', 'closures', 'closed'}
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|private (?:event|party)|invitation[- ]only|staff[- ]only|members[- ]only)\b', re.I)
VIRTUAL = re.compile(r'\b(?:online|virtual|zoom|webinar|livestream)\b', re.I)
# Mirrors the backend street parser (rq_curator_private.udell_address_v1),
# including this batch's reviewed "Pike" suffix used across Knox County.
STREET = re.compile(
    r'^[0-9]{1,6}[A-Za-z]?\s+[^,]*\b(?:street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|'
    r'court|ct|way|parkway|pkwy|place|pl|plaza|plz|circle|cir|highway|hwy|terrace|ter|loop|trail|trl|'
    r'pike)\b\.?(?:\s+(?:n|s|e|w|ne|nw|se|sw))?$', re.I)
# Exact venue whose publisher record leaves the street blank. Street verified
# on the venue's official site (https://www.tennesseetheatre.com/, footer,
# 2026-11-17) and in WDVX's own venue record for the same theatre.
REVIEWED_VENUES = {
    'tennessee theatre': ('Tennessee Theatre', '604 South Gay Street, Knoxville, TN 37902'),
}
STATES = {'tennessee': 'TN', 'tn': 'TN'}


def event_url(source_key, value):
    pattern = EVENT_URLS.get(source_key)
    return bool(pattern and isinstance(value, str) and pattern.fullmatch(value))


def photo_url(source_key, value):
    pattern = PHOTO_URLS.get(source_key)
    if not pattern or not isinstance(value, str) or len(value) > 2000:
        return None
    if not pattern.fullmatch(value) or _NOT_PHOTO.search(urlsplit(value).path):
        return None
    return value


def _hold(source_key, identity, reason):
    log.warning('knoxville_record_held source=%s id=%s reason=%s', source_key, str(identity)[:180], reason)


def _full_description(value):
    """Complete sanitized publisher narrative; None when it exceeds the limit."""
    from roomquest.event_description import description
    if not isinstance(value, str):
        return ''
    # Passing the input length removes the shared 2,000-character display cap.
    text = description(value, limit=max(len(value), MAX_DESCRIPTION + 1))
    # The publisher's encoder replaced apostrophes in contractions with U+FFFD.
    text = re.sub(r'(?<=[A-Za-z])�(?=(?:s|t|re|ve|ll|d|m)\b)', '’', text)
    return None if len(text) > MAX_DESCRIPTION else text


def tn_street(street, city, state, postal):
    """Return "number street, City, TN ZIP" from the event's own venue fields."""
    street = plain(street).strip(' ,')
    # "1050 Worlds Fair Park, DR": a suffix split into its own field.
    street = re.sub(r',\s*(dr|st|ave|rd|blvd|ln|ct|pkwy|hwy|way|pike)\.?$', r' \1', street, flags=re.I)
    city = plain(city).strip(' ,')
    region = plain(state).strip(' ,')
    postal = plain(postal).strip(' ,')
    region = STATES.get(region.casefold(), region.upper() if len(region) == 2 else '')
    # A blank region is Tennessee only when the event's own ZIP is a TN ZIP.
    if not region and re.fullmatch(r'3(?:7[0-9]|8[0-5])[0-9]{2}(?:-[0-9]{4})?', postal):
        region = 'TN'
    if not (street and city and region) or not STREET.match(street):
        return None
    if postal and not re.fullmatch(r'[0-9]{5}(?:-[0-9]{4})?', postal):
        postal = ''
    return f'{street}, {city}, {region}' + (f' {postal}' if postal else '')


def _labels(item):
    out = []
    for value in item.get('categories') or []:
        if isinstance(value, dict) and isinstance(value.get('name'), str):
            label = plain(value['name'])[:100]
            if label and label not in out:
                out.append(label)
    return out[:20]


def _tribe_row(source_key, item):
    if not isinstance(item, dict) or item.get('id') in (None, ''):
        raise ValueError('unsupported_wordpress_payload')
    identity = item['id']
    if item.get('status') != 'publish' or item.get('hide_from_listings') in (True, 1, '1', 'true'):
        return None
    title = plain(item.get('title'))
    labels = _labels(item)
    if {label.casefold() for label in labels} & CLOSURE_LABELS:
        return None
    if NONPUBLIC.search(title):
        _hold(source_key, identity, 'not_public')
        return None
    if item.get('all_day') in (True, 1, '1', 'true'):
        # No published clock; a date-only boundary is not an event time.
        _hold(source_key, identity, 'all_day_without_time')
        return None
    if item.get('timezone') != ZONE:
        _hold(source_key, identity, 'publisher_timezone_review_required')
        return None
    start, end = timestamp(item.get('utc_start_date'), 'UTC'), timestamp(item.get('utc_end_date'), 'UTC')
    local_start = timestamp(item.get('start_date'), ZONE)
    if start is None or local_start != start:
        _hold(source_key, identity, 'publisher_schedule_conflict')
        return None
    if end is not None and end <= start:
        end = None
    venue = item.get('venue') if isinstance(item.get('venue'), dict) else {}
    name = plain(venue.get('venue'))
    if VIRTUAL.search(name):
        return None
    street = tn_street(venue.get('address'), venue.get('city'),
                       venue.get('state') or venue.get('stateprovince') or venue.get('province'), venue.get('zip'))
    if street is None and not plain(venue.get('address')):
        reviewed = REVIEWED_VENUES.get(name.casefold())
        if reviewed:
            name, street = reviewed
    if not name or street is None:
        _hold(source_key, identity, 'venue_street_unverified')
        return None
    narrative = _full_description(item.get('description'))
    if narrative is None:
        _hold(source_key, identity, 'publisher_description_limit')
        return None
    if not narrative.strip():
        _hold(source_key, identity, 'publisher_description_missing')
        return None
    link = item.get('url')
    if not event_url(source_key, link):
        _hold(source_key, identity, 'publisher_event_identity_mismatch')
        return None
    lat, lng = venue.get('geo_lat'), venue.get('geo_lng')
    try:
        lat, lng = (float(lat), float(lng)) if lat not in (None, '') and lng not in (None, '') else (None, None)
    except (TypeError, ValueError):
        lat = lng = None
    if lat is not None and not (34.5 <= lat <= 37.2 and -90.4 <= lng <= -81.5):
        lat = lng = None
    row = record(title, start.isoformat(), end.isoformat() if end else None, name, street,
                 plain(venue.get('city')), link, identity, ', '.join(labels), lat, lng, ZONE,
                 retain_until_end=True)
    if row is None:
        return None
    row['description'] = narrative
    row['timezone'] = ZONE
    row['publisher_categories'] = labels
    row['location_provenance'] = 'publisher_event_venue'
    from roomquest.publisher_evidence import attach
    cost = item.get('cost')
    facts = {'cost': plain(cost)[:400]} if isinstance(cost, str) and plain(cost) else {}
    featured = item.get('image') if isinstance(item.get('image'), dict) else {}
    candidate = featured.get('url')
    width = featured.get('width')
    if isinstance(width, int) and width < MIN_IMAGE_WIDTH:
        candidate = None
    return attach(row, source_key, facts=facts, candidate=candidate)


def collect_tribe(source, fetch, *, deadline_at=None, now=None):
    source_key = source['source_key']
    url = SOURCES[source_key][0]
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE))
    params = {'per_page': 100, 'start_date': current.date().isoformat(),
              'end_date': (current + timedelta(days=WINDOW_DAYS)).date().isoformat()}
    deadline = min(monotonic() + 36, deadline_at or float('inf'))
    rows = {}
    for page in range(1, MAX_PAGES[source_key] + 1):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        payload = json.loads(fetch(f'{url}?{urlencode(dict(params, page=page))}', 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
            raise ValueError('unsupported_wordpress_payload')
        total_pages = payload.get('total_pages', 1)
        if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 0:
            raise ValueError('invalid_wordpress_pagination')
        if total_pages > MAX_PAGES[source_key]:
            raise ValueError('pagination_limit')
        if len(payload['events']) > 100:
            raise ValueError('source_record_limit')
        for item in payload['events']:
            row = _tribe_row(source_key, item)
            if row is None:
                continue
            key = (row['id'], row['starts_at'])
            if key in rows and rows[key] != row:
                raise ValueError('conflicting_event_occurrence')
            rows[key] = row
        if len(rows) > MAX_RECORDS:
            raise ValueError('source_record_limit')
        if page >= total_pages:
            break
    return sorted(rows.values(), key=lambda r: (r['starts_at'], r['title'], r['id']))


MAKERS_LOCATION = re.compile(
    r'^(?:(?P<room>[^,]{1,80}),\s*)?(?P<venue>Knox Makers)\s+-\s+'
    r'(?P<street>[0-9]{1,6}\s+[^,]+),\s*(?P<city>Knoxville),\s*(?P<state>TN)(?:\s+(?P<zip>[0-9]{5}))?$')


def collect_makers(source, fetch, *, deadline_at=None, now=None):
    from icalendar import Calendar, vText
    from roomquest.ics_adapter import parse as parse_ics
    url = SOURCES[MAKERS][0]
    raw = fetch(url, 'text/calendar')
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    cal = Calendar.from_ical(raw)
    events = cal.walk('VEVENT')
    if len(events) > 1000:
        raise ValueError('source_record_limit')
    held = set()
    for event in events:
        if event.errors:
            raise ValueError('invalid_ical_component')
        text = _full_description(str(event.get('DESCRIPTION', '')))
        if text is None:
            held.add(str(event.get('UID', '')))
            text = ''
        event['DESCRIPTION'] = vText(text)
    rows = parse_ics(cal.to_ical().decode('utf-8'), {'url': url, 'source_key': MAKERS},
                     legacy=False, include_description=True)
    result = []
    for row in rows:
        identity = row['id'].split('__', 1)[0]
        if identity in held:
            _hold(MAKERS, identity, 'publisher_description_limit')
            continue
        if NONPUBLIC.search(row['title']):
            _hold(MAKERS, identity, 'not_public')
            continue
        if not (row.get('description') or '').strip():
            _hold(MAKERS, identity, 'publisher_description_missing')
            continue
        if not event_url(MAKERS, row.get('event_url')):
            _hold(MAKERS, identity, 'publisher_event_identity_mismatch')
            continue
        location = MAKERS_LOCATION.fullmatch(plain(row.get('venue_name') or row.get('venue_address') or ''))
        if not location or not STREET.match(location['street']):
            _hold(MAKERS, identity, 'venue_street_unverified')
            continue
        room = location['room']
        row['venue_name'] = f"Knox Makers — {room}" if room else 'Knox Makers'
        row['venue_address'] = (f"{location['street']}, Knoxville, TN"
                                + (f" {location['zip']}" if location['zip'] else ''))
        row['venue_city'] = 'Knoxville'
        row['timezone'] = ZONE
        row['location_provenance'] = 'publisher_event_venue'
        result.append(row)
    if len(result) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    return sorted(result, key=lambda r: (r['starts_at'], r['title'], r['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if (not profile or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != profile
            or source.get('timezone') != ZONE):
        raise ValueError('unregistered_knoxville_source')
    if key == MAKERS:
        return collect_makers(source, fetch, deadline_at=deadline_at, now=now)
    return collect_tribe(source, fetch, deadline_at=deadline_at, now=now)
