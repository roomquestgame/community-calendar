"""Ocean City library and New Day FSC through existing guarded transport.

BiblioCommons' public gateway is advertised by the native events page and uses
the same entities/definitions contract as scrapers.lib.bibliocommons. It carries
complete descriptions, so no truncated listing excerpts or detail crawl is
needed. Pagination must certify a complete snapshot before anything is returned.

New Day's visual date grid is bound to the reviewed November PDF hash. Complete
program paragraphs are extracted again from that current publisher document.
Changed editions fail for review; they never authorize speculative recurrence.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_pdf_programs import _pages
from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import plain, record, timestamp

LOG = logging.getLogger(__name__)
ZONE = 'America/New_York'
LIBRARY = 'ocean_city_public_library_nj'
NEWDAY = 'new_day_family_success_nj'
SOURCES = {
    LIBRARY: ('https://oceancity.bibliocommons.com/v2/events', 'html', 'html'),
    NEWDAY: ('https://www.centerffs.org/our-services/community-connections/newday-fsc', 'html', 'html'),
}
ALLOWED_HOSTS = {
    LIBRARY: ('gateway.bibliocommons.com',),
    NEWDAY: ('www.centerffs.org',),
}
CHECKPOINT_KEYS = frozenset()
LIBRARY_API = 'https://gateway.bibliocommons.com/v2/libraries/oceancity/events'
MAX_EVENTS = 200
PAGE_SIZE = 100
MAX_DESCRIPTION = 12000
NEWDAY_DOCUMENT = ('https://www.centerffs.org/sites/default/files/2026-10/'
    'New%20Day%20November%202026%20Caendar%20English%20UPDATED%20%281%29.pdf')
NEWDAY_SHA256 = '55455b365d4e13a8c9fcbc594d769d9bdce4e8873a5046af2a39754e747c17e2'
LIBRARY_VENUE = ('Ocean City Free Public Library', '1735 Simpson Ave, Ocean City, NJ 08226', 'Ocean City')
NEWDAY_VENUE = ('New Day Family Success Center', '18 Martin Luther King Jr Avenue, Pleasantville, NJ 08232', 'Pleasantville')
# Exact named library branch map point in its native public entities.locations
# record, independently checked against the 1735 Simpson facility street.
LIBRARY_POINT = (39.2714578, -74.59008039999999)
# NJ Office of GIS score100 PointAddress for the exact publisher street/city/ZIP.
NEWDAY_POINT = (39.393297000003, -74.522038500001)
NEWDAY_PROGRAMS = (
    ('toddler-thanksgiving', 'Thanksgiving Celebration Toddler Time with Maria',
     '2026-11-16', '13:00', '14:00', 'Join Maria for a fun-', 'learning, and social connection.'),
    # The PDF and the organizer's indexed registration listing agree on 5pm but
    # differ on 6pm/6:30pm. Preserve the known start and leave the end unverified.
    ('real-talk-with-men', 'Real Talk with Men', '2026-11-19', '17:00', None,
     'Real Talk with Men is a judgment-free space', 'Please register on Eventbrite.'),
    ('kintsugi-day-of-thanks', 'Kintsugi Workshop with Gateway and Day of Thanks',
     '2026-11-23', '16:00', '18:30', 'Join Michael for a meaningful Kintsugi workshop', 'reflection, and connection!'),
    ('employment-one-stop', 'Employment Assistance with One Stop Career Center',
     '2026-11-30', '13:00', '14:00', 'Are you looking for a job or a career change?', 'Please register for an appointment!'),
)
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|private event|members?[- ]only|sold[- ]out)\b', re.I)


def _check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _source(source):
    key = source.get('source_key')
    if (key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter')) != SOURCES[key] or source.get('timezone') != ZONE):
        raise ValueError('unregistered_atlantic_local_community_source')
    return key


def event_url(key, value):
    if key == NEWDAY:
        return value == SOURCES[NEWDAY][0]
    if key != LIBRARY or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == 'https' and p.netloc == 'oceancity.bibliocommons.com'
                and not p.query and not p.fragment
                and re.fullmatch(r'/v2/events/[a-f0-9]{24}', p.path) is not None)
    except ValueError:
        return False


def _held(key, identity, reason):
    LOG.warning('atlantic_local_community_withheld source=%s id=%s reason=%s', key, identity, reason)


def _prose(raw):
    if not isinstance(raw, str):
        raise ValueError('atlantic_local_community_description_invalid')
    return narrative(raw)


def _row(key, identity, title, start, end, body, venue, point, url, now, categories=''):
    if not title or len(title) > 180 or not event_url(key, url):
        raise ValueError('atlantic_local_community_identity_changed')
    if (not start or (end and (end <= start or end > start + timedelta(hours=16)))):
        raise ValueError('atlantic_local_community_time_changed')
    if start >= now + timedelta(days=60) or (end or start + timedelta(hours=3)) <= now:
        return None
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_DESCRIPTION:
        raise ValueError('atlantic_local_community_description_invalid')
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 *venue[:2], venue[2], url, identity, categories, *point,
                 tz=ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                   location_provenance=('reviewed_publisher_library_branch_point' if key == LIBRARY
                                        else 'reviewed_nj_ogis_point_address'))
    return row


def _library_location(entities):
    loc = entities.get('locations', {}).get('MAIN')
    if not isinstance(loc, dict) or loc.get('name') != LIBRARY_VENUE[0] or loc.get('isHidden') is True:
        raise ValueError('ocean_library_venue_changed')
    address = loc.get('address') or {}
    if tuple(address.get(k) for k in ('number', 'street', 'city', 'state', 'zip', 'country')) != (
            '1735', 'Simpson Ave', 'Ocean City', 'New Jersey', '08226', 'US'):
        raise ValueError('ocean_library_venue_changed')
    geo = loc.get('mapLocation') or {}
    point = geo.get('centrePoint') or {}
    if (geo.get('timeZone') != ZONE or
            any(type(point.get(k)) not in (int, float) or not math.isfinite(point[k])
                or abs(point[k] - value) > 0.00001 for k, value in zip(('lat', 'lng'), LIBRARY_POINT))):
        raise ValueError('ocean_library_venue_changed')
    return loc


def _library_item(identity, item, entities, now):
    if not re.fullmatch(r'[a-f0-9]{24}', identity or '') or not isinstance(item, dict) or item.get('id') != identity:
        raise ValueError('ocean_library_event_identity_changed')
    d = item.get('definition')
    if not isinstance(d, dict):
        raise ValueError('ocean_library_payload_changed')
    title = plain(d.get('title'))
    start, end = timestamp(item.get('indexStart')), timestamp(item.get('indexEnd'))
    if start != timestamp(d.get('start'), ZONE) or end != timestamp(d.get('end'), ZONE):
        raise ValueError('ocean_library_clock_mismatch')
    if not start or (start >= now + timedelta(days=60)) or (end or start + timedelta(hours=3)) <= now:
        return None
    registration = d.get('registrationInfo') or {}
    reason = None
    if d.get('isVirtual') is True or d.get('branchLocationId') in (None, 'BC_VIRTUAL'):
        reason = 'virtual_or_no_physical_venue'
    elif d.get('branchLocationId') != 'MAIN' or d.get('nonBranchLocationId'):
        reason = 'unreviewed_physical_venue'
    elif d.get('isCancelled') is True or item.get('isFull') is True or registration.get('isFull') is True:
        reason = 'cancelled_or_full'
    elif item.get('registrationClosed') is True:
        reason = 'registration_closed'
    elif NONPUBLIC.search(title):
        reason = 'nonpublic_or_cancelled'
    if reason:
        _held(LIBRARY, identity, reason)
        return None
    loc = _library_location(entities)
    local_day = start.astimezone(ZoneInfo(ZONE)).date()
    for special_id in loc.get('specialHoursIds', []):
        special = entities.get('specialHours', {}).get(special_id)
        if not isinstance(special, dict):
            raise ValueError('ocean_library_closure_metadata_changed')
        if date.fromisoformat(special['startDate']) <= local_day <= date.fromisoformat(special['endDate']):
            close = special.get('closeTime')
            if (not special.get('openTime') and not close) or (close and
                    (start >= timestamp(str(local_day) + close, ZONE)
                     or end and end > timestamp(str(local_day) + close, ZONE))):
                _held(LIBRARY, identity, 'publisher_holiday_closure')
                return None
    raw_body = d.get('description')
    if not raw_body or not BeautifulSoup(str(raw_body), 'html.parser').get_text(' ', strip=True):
        _held(LIBRARY, identity, 'publisher_description_missing')
        return None
    body = _prose(raw_body)
    # These two current screenings carry their actual information only in an
    # unreviewed inline poster. A generic series heading (and the next film's
    # date) is not a description of the advertised screening. New publisher
    # prose can qualify normally; no arbitrary minimum text length is imposed.
    if (identity in ('695ff9e1c967cb412080c6d5', '695ff9e1c967cb412080c6d6')
            and body in ('2026 Movie Monday',
                         '2026 Movie Monday\nDecember 12/28 – The Holiday')):
        _held(LIBRARY, identity, 'poster_only_screening_description')
        return None
    # Registration instructions can contain additional native participation
    # requirements. Keep them in full when not already in the description.
    for key in ('instructions', 'instructionsToAttend', 'onlineInstructions'):
        extra = registration.get(key)
        if extra:
            text = _prose(extra)
            if plain(text) not in plain(body):
                body += '\n\n' + text
    if len(body) > MAX_DESCRIPTION:
        raise ValueError('atlantic_city_description_limit')
    room = plain(d.get('locationDetails'))
    venue = (LIBRARY_VENUE[0] + (' — ' + room if room else ''), *LIBRARY_VENUE[1:])
    categories = ', '.join(plain(entities.get('eventTypes', {}).get(t, {}).get('name'))
                           for t in d.get('typeIds', []))
    row = _row(LIBRARY, 'ocean-library:' + identity, title, start, end, body,
               venue, LIBRARY_POINT, SOURCES[LIBRARY][0] + '/' + identity, now, categories)
    if row:
        photo = entities.get('images', {}).get(d.get('featuredImageId'), {}).get('url')
        if isinstance(photo, str) and re.fullmatch(
                r'https://oceancity\.bibliocommons\.com/events/uploads/images/(?:full|large)/[a-f0-9]{32}/[^/?#\\<>\s]+', photo):
            row['image_url'] = photo
    return row


def collect_library(fetch, *, deadline_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    seen, rows = set(), []
    expected_count = expected_pages = None
    for page in range(1, 3):
        _check(deadline_at)
        url = LIBRARY_API + '?' + urlencode({'limit': PAGE_SIZE, 'page': page})
        raw = fetch(url, 'application/json')
        if not isinstance(raw, str) or len(raw) > 2_800_000:
            raise ValueError('ocean_library_payload_changed')
        data = json.loads(raw)
        events, entities = data.get('events'), data.get('entities')
        if not isinstance(events, dict) or not isinstance(entities, dict):
            raise ValueError('ocean_library_payload_changed')
        p, items = events.get('pagination'), events.get('items')
        if (not isinstance(p, dict) or not isinstance(items, list)
                or any(type(p.get(k)) is not int for k in ('count', 'pages', 'page', 'limit'))
                or p['page'] != page or p['limit'] != PAGE_SIZE
                or not 0 <= p['count'] <= MAX_EVENTS
                or p['pages'] != max(1, math.ceil(p['count'] / PAGE_SIZE))):
            raise ValueError('ocean_library_manifest_incomplete')
        if expected_count is None:
            expected_count, expected_pages = p['count'], p['pages']
        if (p['count'], p['pages']) != (expected_count, expected_pages):
            raise ValueError('ocean_library_manifest_changed')
        if len(items) != min(PAGE_SIZE, expected_count - (page - 1) * PAGE_SIZE):
            raise ValueError('ocean_library_manifest_incomplete')
        for identity in items:
            _check(deadline_at)
            if not isinstance(identity, str) or identity in seen:
                raise ValueError('ocean_library_duplicate_identity')
            seen.add(identity)
            row = _library_item(identity, entities.get('events', {}).get(identity), entities, now)
            if row:
                rows.append(row)
        if page == expected_pages:
            if len(seen) != expected_count:
                raise ValueError('ocean_library_manifest_incomplete')
            return rows
    raise ValueError('ocean_library_manifest_incomplete')


def discover_newday(payload):
    if not isinstance(payload, str) or len(payload) > 500_000:
        raise ValueError('newday_listing_changed')
    soup = BeautifulSoup(payload, 'html.parser')
    candidates = {urljoin(SOURCES[NEWDAY][0], a['href']) for a in soup.select('a[href]')
                  if 'calendar' in a.get_text(' ', strip=True).lower()
                  and 'english' in a.get_text(' ', strip=True).lower()}
    if candidates != {NEWDAY_DOCUMENT}:
        raise ValueError('newday_calendar_edition_unreviewed')
    return NEWDAY_DOCUMENT


def parse_newday(payload, *, now=None, deadline_at=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, bytes) or sha256(payload).hexdigest() != NEWDAY_SHA256:
        raise ValueError('newday_calendar_edition_unreviewed')
    pages = _pages(payload, max_pages=2, max_bytes=1_000_000, deadline_at=deadline_at)
    if (len(pages) != 2 or '18 Martin Luther King Jr. Ave Pleasantville NJ 08232' not in pages[0]
            or 'November 2026' not in pages[1]
            or '**Please register on Eventbrite for All Events!!**' not in pages[1]):
        raise ValueError('newday_calendar_identity_changed')
    rows = []
    for identity, title, day, begins, ends, first, last in NEWDAY_PROGRAMS:
        _check(deadline_at)
        matches = list(re.finditer(re.escape(first) + r'.*?' + re.escape(last), pages[1]))
        if len(matches) != 1:
            raise ValueError('newday_description_changed')
        body = matches[0][0] + '\n\nFree and Open to All of Atlantic County\n**Please register on Eventbrite for All Events!!**'
        start = timestamp(day + 'T' + begins, ZONE)
        end = timestamp(day + 'T' + ends, ZONE) if ends else None
        row = _row(NEWDAY, f'new-day:{identity}:{day}', title, start, end, body,
                   NEWDAY_VENUE, NEWDAY_POINT, SOURCES[NEWDAY][0], now)
        if row:
            rows.append(row)
    # The current grid prints HeadStart at 10:30PM; no AM is invented.
    # Caregiver Appreciation has a paragraph but no dated cell in this edition.
    return rows


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    _check(deadline_at)
    if key == LIBRARY:
        return collect_library(fetch, deadline_at=deadline_at, now=now)
    document = discover_newday(fetch(SOURCES[NEWDAY][0], 'text/html'))
    _check(deadline_at)
    return parse_newday(fetch(document, 'application/pdf'), now=now, deadline_at=deadline_at)
