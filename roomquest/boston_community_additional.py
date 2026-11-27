"""Additional Boston outdoor/fitness calendars through ordinary publisher reads.

Native ICS, Squarespace, Shopify, WordPress, Eventbrite and Capitan descriptions
are retained in full. Detailed calendars use the existing complete-only durable
snapshot protocol. This module performs no network access of its own.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.atlantic_city_community import _google_times
from roomquest.boston_community import _detail_point, _point, LOCALITIES
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = 'America/New_York'
ARBORETUM = 'arnold_arboretum_ma'
PARKOUR = 'parkour_generations_boston_ma'
TRACKSMITH = 'tracksmith_trackhouse_boston_ma'
TRUSTEES = 'trustees_metro_boston_ma'
CENTRAL = 'central_rock_cambridge_ma'
ROCKSPOT = 'rock_spot_south_boston_ma'
HARBOR = 'boston_harbor_now_ma'
SOURCES = {
    ARBORETUM: ('https://arboretum.harvard.edu/events/?ical=1', 'html', 'html'),
    PARKOUR: ('https://pkgenboston.com/local-events', 'html', 'html'),
    TRACKSMITH: ('https://www.tracksmith.com/pages/trackhouse', 'html', 'html'),
    TRUSTEES: ('https://thetrustees.org/program/metro-boston-programs/', 'html', 'html'),
    CENTRAL: ('https://centralrockgym.com/cambridge/events/bipoc-climbers-meetup/', 'html', 'html'),
    ROCKSPOT: ('https://climber.hellocapitan.com/rockspot/schedule/events/95/', 'html', 'html'),
    HARBOR: ('https://www.bostonharbornow.org/events/', 'html', 'html'),
}
LABELS = {
    ARBORETUM: 'Arnold Arboretum Public Programs',
    PARKOUR: 'Parkour Generations Boston',
    TRACKSMITH: 'Tracksmith Trackhouse Boston',
    TRUSTEES: 'The Trustees — Metro Boston Programs',
    CENTRAL: 'Central Rock Gym Cambridge — BIPOC Climbers Meetup',
    ROCKSPOT: 'Rock Spot Climbing South Boston',
    HARBOR: 'Boston Harbor Now and Friends of the Harborwalk',
}
SOURCE_NOTES = {
    ARBORETUM: 'Official permitted ICS with complete native descriptions, compared with current calendar; exact publisher meeting sites, including reviewed Flora Way gate intersection.',
    PARKOUR: 'Official Squarespace dated HTML and exact linked public ZenPlanner sessions; complete narratives and event-specific streets. Explicit individual-day clinic signup permits the dated daily sessions. ICS lacks descriptions and is not used as a prose fallback.',
    TRACKSMITH: 'Official current Trackhouse listing and complete event details; dated JSON-LD reconciled with visible start clocks. Partner hotel runs retain their actual meeting venue.',
    TRUSTEES: 'Metro Boston program listing only; complete native detail prose, exact dates and actual garden streets. Statewide deCordova programming is a separate source.',
    CENTRAL: 'Publisher explicitly states the third Thursday monthly at 7–9pm. Bounded 60-day recurrence is checked against the current named edition and native post freshness. Exact Cambridge venue point comes from the publisher location page Get Directions link.',
    ROCKSPOT: 'Official public Capitan scheduler, next 60 days; complete native descriptions and explicitly dated public bookable classes/meetups. Private appointments, rentals and closed course parts excluded. Exact South Boston facility point comes from its publisher venue map marker.',
    HARBOR: 'Official calendar links organizer Eventbrite details; full native description, native date and meeting point. Exact bocce street disagreement resolved from structured publisher point and municipal park context.',
}
ALLOWED_HOSTS = {k: (urlsplit(v[0]).hostname,) for k, v in SOURCES.items()}
ALLOWED_HOSTS[HARBOR] = ('www.bostonharbornow.org', 'www.eventbrite.com')
ALLOWED_HOSTS[PARKOUR] = ('pkgenboston.com', 'pkgenboston.sites.zenplanner.com')
HOLIDAY_PARENT = 'https://pkgenboston.com/local-events/2026/holiday-challenge'
HOLIDAY_SESSIONS = {
    'F627675C-0625-4AC6-9410-A2DA10FF3F5C': ('PKGB Holiday Challenge - ADULT/TEEN 2026', '9am - 12pm Adult / Teen Signup'),
    'AD58D198-525D-43BA-8F2F-1967B02668FD': ('PKGB Holiday Challenge - YOUTH 2026', '1pm - 3pm Youth Signup'),
}
CHECKPOINT_KEYS = {PARKOUR, TRACKSMITH, TRUSTEES, ROCKSPOT, HARBOR}
MAX_MANIFEST = 200
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900000
DETAILS_PER_CHUNK = 8
REVIEWED_INTERSECTIONS = ({
    'source_key': ARBORETUM,
    'venue_name': 'Flora Way Gate (Formerly Bussey St Gate)',
    'venue_address': 'Flora Way & Hemlock Hill Road, Boston, MA 02131',
    'lat': 42.2964125, 'lng': -71.1280781,
},)
GATE_EVIDENCE = 'https://arboretum.harvard.edu/venue/bussey-street-gate/'
GATE_PROVENANCE = ('Exact publisher Flora Way Gate point and directions place the meeting at the end of Hemlock Hill Road on Flora Way; '
    'street intersection supplied for the unnumbered gate. ZIP 02131 is a reviewed Roslindale street-context resolution, corroborated by City of Boston Flora Way park records; no headquarters or invented house number.')
HARBOR_BOCCE_PROVENANCE = ('Publisher structured venue/address and its event-specific point identify the bocce courts at523 Commercial Street. '
    'The narrative says423; Boston parks records place these courts between Puopolo517 and Langone529–543 Commercial Street, supporting523. '
    'Native narrative retained unchanged; reviewed physical meeting-site resolution, not a claim that the conflicting prose agrees.')
HARBOR_BOCCE_EVIDENCE = 'https://www.boston.gov/departments/parks-and-recreation/improvements-langone-park-and-puopolo-playground'
DOJO_POINT = (42.382388, -71.105441)
DOJO_EVIDENCE = 'https://www.somervillema.gov/events/2023/10/30/annual-candlelight-vigil-honor-domestic-violence-awareness-month'
DOJO_PROVENANCE = ('City of Somerville named-event map feature 50785 identifies The Dojo at Somernova at 15 Properzi Way with this point; '
    'the current venue website confirms the identical street. Conflicting publisher event pins replaced by this reviewed building/site point, '
    'not a claimed exact classroom or door.')
REVIEWED_VENUE_POINTS = {
    (CENTRAL, 'Central Rock Gym Cambridge', '170 Alewife Brook Parkway, Cambridge, MA 02138'): {
        'point': (42.390776, -71.142459),
        'evidence': 'https://centralrockgym.com/cambridge/',
        'provenance': ('Publisher Cambridge location page pairs 170 Alewife Brook Pkwy, Cambridge 02138 with '
            'Get Directions https://www.google.com/maps?q=42.390776,-71.142459. '
            'Reviewed 2026-11-15; exact source, venue name and street only. The event explicitly identifies this Cambridge facility.'),
    },
    (ROCKSPOT, 'Rock Spot Climbing South Boston', '30 Old Colony Avenue, South Boston, MA 02127'): {
        'point': (42.3372967, -71.0561203),
        'evidence': 'https://rockspotclimbing.com/locations/ma/southboston/',
        'provenance': ('Publisher South Boston location map marker 0 names Rock Spot Climbing: South Boston '
            'at 30 Old Colony Avenue, Boston MA 02127 and supplies 42.3372967,-71.0561203. '
            'Reviewed 2026-11-15; exact source, venue name and street only. Separate parking marker 1 is excluded.'),
    },
    (TRUSTEES, 'City Natives', '30 Edgewater Drive, Mattapan, MA 02126'): {
        'point': (42.2660524, -71.0955048),
        'evidence': 'https://thetrustees.org/place/city-natives/',
        'provenance': ('Publisher City Natives location page pairs 30 Edgewater Drive, Mattapan MA 02126 '
            'with a Google directions destination !1d-71.0955048!2d42.2660524. '
            'Reviewed 2026-11-15; exact source, venue name and street only. The map viewport longitude is excluded.'),
    },
}
ERROR_CODES = {'unregistered_boston_additional_source', 'boston_additional_calendar_changed',
    'boston_additional_detail_changed', 'boston_additional_description_missing',
    'boston_additional_description_limit', 'boston_additional_street_unresolved',
    'boston_additional_time_conflict', 'boston_additional_outside_window',
    'boston_additional_not_public', 'boston_additional_record_limit',
    'boston_additional_checkpoint_invalid', 'boston_additional_checkpoint_limit',
    'boston_additional_deadline', 'boston_additional_feed_changed',
    'boston_additional_schedule_changed', 'boston_additional_location_conflict',
    'boston_additional_pagination_incomplete', 'boston_additional_existing_public_overlap'}


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('unregistered_boston_additional_source')
    return key


def _full(value):
    value = description(value, limit=MAX_DESCRIPTION + 1)
    if len(value) > MAX_DESCRIPTION:
        raise ValueError('boston_additional_description_limit')
    return value


def _budget(deadline_at, reserve=8):
    if deadline_at is not None and monotonic() + reserve >= deadline_at:
        raise ValueError('boston_additional_deadline')


def _hold(key, identity, reason, diagnostics):
    log.warning('boston_additional_record_held source=%s id=%s reason=%s', key, identity, reason)
    diagnostics.append({'id': str(identity), 'reason': reason})


def _within(start, end, now):
    window_start = calendar_anchor(now)
    return bool(start and start < window_start + timedelta(days=60) and (end or start + timedelta(hours=3)) > window_start)


def _offset(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt if dt.tzinfo is not None else None
    except ValueError:
        return None


def _street(value):
    match = re.fullmatch(r'(\d{1,6}(?:[A-Za-z]|-\d{1,6})?\s+.+?),\s*([^,]+),\s*(?:MA|Massachusetts),?\s*'
        r'(\d{5}(?:-\d{4})?)(?:,\s*(?:USA|United States))?', plain(value), re.I)
    if not match or match[2] not in LOCALITIES | {'Jamaica Plain', 'Roslindale'}:
        return None
    return f'{match[1]}, {match[2]}, MA {match[3]}', match[2]


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        patterns = {
            ARBORETUM: r'/event/[a-z0-9_-]+/',
            PARKOUR: r'/local-events/[a-zA-Z0-9_/-]+',
            TRACKSMITH: r'/events/[a-z0-9_-]+',
            TRUSTEES: r'/event/[1-9][0-9]*/',
            CENTRAL: r'/cambridge/events/bipoc-climbers-meetup/',
            ROCKSPOT: r'/rockspot/schedule/event/[1-9][0-9]*/select-num-participants/',
            HARBOR: r'/e/[a-z0-9-]+-tickets-[1-9][0-9]*',
        }
        if key == PARKOUR and p.netloc == 'pkgenboston.sites.zenplanner.com':
            query = parse_qs(p.query)
            return bool(p.scheme == 'https' and p.path == '/event.cfm' and not p.fragment
                and set(query) == {'eventId'} and len(query['eventId']) == 1
                and query['eventId'][0] in HOLIDAY_SESSIONS
                and p.query == 'eventId=' + query['eventId'][0])
        host = 'www.eventbrite.com' if key == HARBOR else ALLOWED_HOSTS[key][0]
        return bool(p.scheme == 'https' and p.netloc == host and not (p.query or p.fragment)
            and re.fullmatch(patterns[key], p.path) and '..' not in p.path.split('/'))
    except ValueError:
        return False


def _clock(day, value):
    value = plain(value).lower().replace('.', '')
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', value)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError('boston_additional_time_conflict')
    hour = int(match[1]) % 12 + (12 if match[3] == 'pm' else 0)
    return timestamp(f'{day}T{hour:02}:{int(match[2] or 0):02}:00', ZONE)


def _range(day, value):
    parts = re.split(r'\s*[-–—]\s*', plain(value))
    if len(parts) != 2:
        raise ValueError('boston_additional_time_conflict')
    if not re.search(r'[ap]\.?m\.?$', parts[0], re.I):
        meridiem = re.search(r'([ap]\.?m\.?)$', parts[1], re.I)
        if meridiem:
            parts[0] += meridiem[1]
    start, end = _clock(day, parts[0]), _clock(day, parts[1])
    if end <= start:
        raise ValueError('boston_additional_time_conflict')
    return start, end


def _row(key, title, start, end, url, identity, body, venue, street, city, *, point=None,
         categories=(), evidence=None, provenance='Publisher event-specific full street address.',
         native_venue_name=None, native_venue_address=None, native_venue_city=None,
         native_options=None):
    if not body or not body.strip() or plain(body).casefold() == plain(title).casefold():
        raise ValueError('boston_additional_description_missing')
    if len(body) > MAX_DESCRIPTION:
        raise ValueError('boston_additional_description_limit')
    if not event_url(key, url):
        raise ValueError('boston_additional_detail_changed')
    reviewed = REVIEWED_VENUE_POINTS.get((key, venue, street))
    if reviewed:
        point, evidence, provenance = reviewed['point'], reviewed['evidence'], reviewed['provenance']
    row = record(title, start.isoformat(), end.isoformat() if end else None, venue, street, city,
        url, identity, '', lat=point[0] if point else None, lng=point[1] if point else None,
        tz=ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
            publisher_categories=list(categories), location_evidence_url=evidence or url,
            location_provenance=provenance)
    options = dict(native_options or {})
    native_categories = sorted({plain(value) for value in categories if plain(value)}, key=str.casefold)
    if native_categories:
        options['publisher_categories'] = native_categories
    return _attach_content(
        row, title=title, body=body, start=start, end=end, url=url,
        venue_name=venue if native_venue_name is None else native_venue_name,
        venue_address=street if native_venue_address is None else native_venue_address,
        venue_city=city if native_venue_city is None else native_venue_city,
        native_options=options)


def _attach_content(row, *, title, body, start, end, url, venue_name=None,
                    venue_address=None, venue_city=None, venue_region=None,
                    venue_postal_code=None, venue_country=None, photo=None,
                    native_options=None):
    """Retain event-owned publisher facts for the shared SQL fingerprint."""
    if row is None:
        return None
    facts = {
        'title': title,
        'description': body,
        'is_all_day': False,
        'starts_at_utc': start.astimezone(timezone.utc).isoformat(),
        'ends_at_utc': end.astimezone(timezone.utc).isoformat() if end else None,
        'event_url': url,
        'venue_name': venue_name,
        'venue_address': venue_address,
        'venue_city': venue_city,
        'venue_region': venue_region,
        'venue_postal_code': venue_postal_code,
        'venue_country': venue_country,
        'source_image_url': photo,
        'native_options': native_options,
    }
    facts = {name: value for name, value in facts.items()
             if value is not None and value != '' and value != {}}
    row['collector_event_content_v1'] = {
        'version': 1,
        'event_id': row['id'],
        'facts': facts,
    }
    return row


def _content_envelope_valid(row):
    evidence = row.get('collector_event_content_v1')
    if evidence is None:
        return True
    if (not isinstance(evidence, dict)
            or set(evidence) != {'version', 'event_id', 'facts'}
            or evidence.get('version') != 1
            or evidence.get('event_id') != row.get('id')
            or not isinstance(evidence.get('facts'), dict)):
        return False
    facts = evidence['facts']
    allowed = {
        'title', 'description', 'is_all_day', 'starts_at_utc', 'ends_at_utc',
        'event_url', 'venue_name', 'venue_address', 'venue_city', 'venue_region',
        'venue_postal_code', 'venue_country', 'source_image_url', 'native_options',
    }
    if not set(facts) <= allowed:
        return False
    expected = {
        'title': row.get('title'),
        'description': row.get('description'),
        'is_all_day': False,
        'starts_at_utc': timestamp(row.get('starts_at')).astimezone(timezone.utc).isoformat(),
        'event_url': row.get('event_url'),
    }
    end = timestamp(row.get('ends_at'))
    if end is not None:
        expected['ends_at_utc'] = end.astimezone(timezone.utc).isoformat()
    return all(facts.get(name) == value for name, value in expected.items())


def _schemas(soup):
    result = []
    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if str(value.get('@type', '')).endswith('Event'):
                result.append(value)
            if '@graph' in value:
                visit(value['@graph'])
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            raise ValueError('boston_additional_detail_changed')
    return result


def _arboretum(fetch, now, deadline_at, diagnostics):
    _budget(deadline_at)
    listing = BeautifulSoup(fetch('https://arboretum.harvard.edu/events/', 'text/html'), 'html.parser')
    # This official public export currently contains the entire upcoming list.
    # A later paginated calendar must fail visibly, not silently publish page1.
    if listing.select('a.tribe-events-c-nav__next[href], a.tribe-events-nav-next[href]'):
        raise ValueError('boston_additional_pagination_incomplete')
    listed = _schemas(listing)
    if not listed and not listing.select_one('.tribe-events'):
        raise ValueError('boston_additional_calendar_changed')
    _budget(deadline_at)
    payload = fetch(SOURCES[ARBORETUM][0], 'text/calendar')
    if not isinstance(payload, str) or not payload.lstrip().startswith('BEGIN:VCALENDAR'):
        raise ValueError('boston_additional_feed_changed')
    cal = Calendar.from_ical(payload)
    events = cal.walk('VEVENT')
    if len(events) > MAX_RECORDS:
        raise ValueError('boston_additional_record_limit')
    listed_urls = {e.get('url') for e in listed if _within(timestamp(e.get('startDate')),
        timestamp(e.get('endDate')), now)}
    feed_urls = {str(e.get('URL', '')) for e in events}
    if not listed_urls <= feed_urls:
        raise ValueError('boston_additional_pagination_incomplete')
    out, seen = [], set()
    for item in events:
        url = str(item.get('URL', ''))
        if item.errors or any(item.get(k) for k in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID')):
            raise ValueError('boston_additional_feed_changed')
        if str(item.get('STATUS', '')).upper() in {'CANCELED', 'CANCELLED'}:
            continue
        start = item.decoded('DTSTART') if item.get('DTSTART') else None
        end = item.decoded('DTEND') if item.get('DTEND') else None
        if (not isinstance(start, datetime) or start.tzinfo is None
                or (end and (not isinstance(end, datetime) or end.tzinfo is None or end <= start))):
            _hold(ARBORETUM, url, 'boston_additional_time_conflict', diagnostics)
            continue
        if not _within(start, end, now):
            continue
        title, body = plain(item.get('SUMMARY')), _full(str(item.get('DESCRIPTION', '')))
        native_location = plain(str(item.get('LOCATION', '')))
        uid = str(item.get('UID', ''))
        if not uid or uid in seen or not event_url(ARBORETUM, url):
            raise ValueError('boston_additional_feed_changed')
        seen.add(uid)
        geo = item.get('GEO')
        point = _point(getattr(geo, 'latitude', None), getattr(geo, 'longitude', None))
        evidence, provenance = url, 'Native ICS event street and GEO identify this exact meeting venue.'
        if native_location == 'Flora Way Gate (Formerly Bussey St Gate), Bussey Street Gate, Boston, MA, United States':
            place = REVIEWED_INTERSECTIONS[0]
            if point != (place['lat'], place['lng']):
                _hold(ARBORETUM, url, 'boston_additional_location_conflict', diagnostics)
                continue
            venue, street, city = place['venue_name'], place['venue_address'], 'Boston'
            evidence, provenance = GATE_EVIDENCE, GATE_PROVENANCE
        else:
            split = re.search(r',\s*(?=\d{1,6}\s)', native_location)
            address = _street(native_location[split.end():]) if split else None
            if not address:
                _hold(ARBORETUM, url, 'boston_additional_street_unresolved', diagnostics)
                continue
            venue, (street, city) = native_location[:split.start()], address
        if not body:
            _hold(ARBORETUM, url, 'boston_additional_description_missing', diagnostics)
            continue
        categories = item.get('CATEGORIES')
        categories = [str(c) for c in getattr(categories, 'cats', [])]
        row = _row(ARBORETUM, title, start, end, url, 'arboretum:' + uid, body, venue,
            street, city, point=point, categories=categories, evidence=evidence, provenance=provenance,
            native_venue_name='', native_venue_address='', native_venue_city='',
            native_options={'native_location': native_location})
        if row:
            out.append(row)
    return out


def _parkour_manifest(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if not soup.select_one('.eventlist'):
        raise ValueError('boston_additional_calendar_changed')
    out = []
    for card in soup.select('article.eventlist-event--upcoming'):
        link = card.select_one('.eventlist-title-link[href]')
        if link is None:
            raise ValueError('boston_additional_calendar_changed')
        url = urljoin(SOURCES[PARKOUR][0], link['href'])
        title = plain(link.get_text())
        start, end, facts = _google_times(card)
        if not event_url(PARKOUR, url) or not start or plain((facts.get('text') or [''])[0]) != title:
            raise ValueError('boston_additional_calendar_changed')
        if not _within(start, end, now):
            continue
        venue = card.select_one('.eventlist-meta-address')
        venue = BeautifulSoup(str(venue), 'html.parser') if venue else None
        if venue:
            for a in venue.select('a'):
                a.decompose()
        out.append({'url': url, 'title': title, 'start': start.isoformat(),
            'end': end.isoformat() if end else None,
            'location': plain((facts.get('location') or [''])[0]),
            'venue': plain(venue.get_text()) if venue else ''})
    return out


def _parkour_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('.eventitem')
    title = main.select_one('.eventitem-title') if main else None
    content = main.select_one('.eventitem-column-content .sqs-layout') if main else None
    canonical = soup.select_one('meta[property="og:url"]')
    if title is None or content is None or canonical is None or canonical.get('content') != card['url']:
        raise ValueError('boston_additional_detail_changed')
    start, end, facts = _google_times(main)
    venue = main.select_one('.eventitem-meta-address-line--title')
    venue = plain(venue.get_text()) if venue else ''
    location = plain((facts.get('location') or [''])[0])
    if (plain(title.get_text()) != card['title'] or not start or start.isoformat() != card['start']
            or (end.isoformat() if end else None) != card['end'] or venue != card['venue']
            or location != card['location']):
        raise ValueError('boston_additional_detail_changed')
    body, address = _full(str(content)), _street(location)
    if not body or not venue or not address:
        _hold(PARKOUR, card['url'], 'boston_additional_description_missing' if not body
            else 'boston_additional_street_unresolved', diagnostics)
        return []
    sessions = _parkour_sessions(card, body)
    if not sessions:
        _hold(PARKOUR, card['url'], 'boston_additional_time_conflict', diagnostics)
        return []
    point = _detail_point(soup, main, location)
    provenance = 'Publisher event-specific full street; coordinates accepted only when event export, visible address and map destination agree.'
    evidence = card['url']
    if (venue, address[0]) == ('The Dojo @ Somernova', '15 Properzi Way, Somerville, MA 02143'):
        point, evidence, provenance = DOJO_POINT, DOJO_EVIDENCE, DOJO_PROVENANCE
    out = []
    for begins, ends in sessions:
        identity = 'parkour:' + sha256(urlsplit(card['url']).path.encode()).hexdigest()
        if len(sessions) > 1:
            identity += ':' + begins.date().isoformat()
        row = _row(PARKOUR, card['title'], begins, ends, card['url'], identity, body,
            venue, address[0], address[1], point=point,
            categories=[plain(a.get_text()) for a in main.select('.eventitem-meta-cats a, .eventitem-meta-tags a')],
            evidence=evidence, provenance=provenance)
        if row:
            if len(sessions) > 1:
                row['publisher_schedule_rule'] = 'Each explicitly advertised day, 10 am–3 pm; publisher offers individual-day signup for the dated clinic range.'
            out.append(row)
    return out


def _parkour_sessions(card, body):
    start, end = _offset(card['start']), _offset(card['end'])
    if not start or not end:
        return []
    start, end = start.astimezone(ZoneInfo(ZONE)), end.astimezone(ZoneInfo(ZONE))
    if start.date() == end.date():
        return [(start, end)]
    total = (end.date() - start.date()).days + 1
    text = plain(body)
    single = re.search(r'1-day and (\d+)-day signup options', text, re.I)
    span = re.search(r'TIME / LOCATION (\d{1,2}(?::\d{2})?\s*[ap]m)\s*[-–]\s*(\d{1,2}(?::\d{2})?\s*[ap]m) at The Dojo', text, re.I)
    dates = re.search(r'DATES [A-Z]{3} (\d{1,2})/(\d{1,2})\s*[-–]\s*[A-Z]{3} (\d{1,2})/(\d{1,2})', text)
    if (not card['title'].startswith('Parkour Explorer School Break Clinic') or not 2 <= total <= 10
            or not single or int(single[1]) != total or not span or not dates
            or (int(dates[1]), int(dates[2])) != (start.month, start.day)
            or (int(dates[3]), int(dates[4])) != (end.month, end.day)):
        return []
    times = [_range(start.date() + timedelta(days=i), span[1] + '-' + span[2]) for i in range(total)]
    return times if times[0][0] == start and times[-1][1] == end else []


def _parkour_linked_sessions(card, payload):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('.eventitem')
    title = main.select_one('.eventitem-title') if main else None
    body = main.select_one('.eventitem-column-content .sqs-layout') if main else None
    canonical = soup.select_one('meta[property="og:url"]')
    venue = main.select_one('.eventitem-meta-address-line--title') if main else None
    if (title is None or body is None or plain(title.get_text()) != card['title']
            or card['url'] != HOLIDAY_PARENT or canonical is None or canonical.get('content') != card['url']
            or venue is None or plain(venue.get_text()) != card['venue']):
        raise ValueError('boston_additional_detail_changed')
    start, end, facts = _google_times(main)
    if (not start or not end or start.isoformat() != card['start'] or end.isoformat() != card['end']
            or plain((facts.get('location') or [''])[0]) != card['location']):
        raise ValueError('boston_additional_time_conflict')
    day = start.astimezone(ZoneInfo(ZONE)).date()
    if day != date(2026, 12, 5):
        raise ValueError('boston_additional_schedule_changed')
    out = []
    for native_id, (native_title, label) in HOLIDAY_SESSIONS.items():
        url = 'https://pkgenboston.sites.zenplanner.com/event.cfm?eventId=' + native_id
        anchors = [a for a in body.select('a[href]') if a['href'] == url and plain(a.get_text()) == label]
        if len(anchors) != 1:
            raise ValueError('boston_additional_schedule_changed')
        match = re.match(r'^(\d{1,2}[ap]m) - (\d{1,2}[ap]m)', label)
        begins, ends = _range(day, match[1] + '-' + match[2])
        out.append({'url': url, 'title': native_title, 'kind': 'zenplanner', 'parent_url': card['url'],
            'native_id': native_id, 'start': begins.isoformat(), 'end': ends.isoformat(),
            'venue': card['venue'], 'location': card['location']})
    return out


def _parkour_zen_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    field = soup.select_one('fieldset')
    title = field.select_one('legend') if field else None
    if title is None or plain(title.get_text()) != card['title']:
        raise ValueError('boston_additional_detail_changed')
    labels = {plain(n.get_text()): n for n in field.select('strong')}
    if not {'Date:', 'Time:', 'Location:'} <= set(labels):
        raise ValueError('boston_additional_detail_changed')
    try:
        day = datetime.strptime(plain(labels['Date:'].next_sibling), '%B %d, %Y').date()
    except ValueError:
        raise ValueError('boston_additional_time_conflict')
    clocks = plain(labels['Time:'].parent.get_text()).removeprefix('Time:').strip().replace(' to ', '-')
    start, end = _range(day, clocks)
    if start != _offset(card['start']) or end != _offset(card['end']):
        raise ValueError('boston_additional_time_conflict')
    adr = field.select_one('.adr')
    parts = [plain(adr.select_one(c).get_text()) if adr and adr.select_one(c) else ''
        for c in ('.street-address', '.locality', '.region', '.postal-code')]
    address = _street(parts[0] + ', ' + parts[1] + ', ' + parts[2] + ' ' + parts[3])
    location_label = plain(labels['Location:'].parent.get_text()).removeprefix('Location:').strip()
    if (not address or address != _street(card['location'])
            or location_label != 'The Dojo @ Somernova SOM' or card['venue'] != 'The Dojo @ Somernova'):
        raise ValueError('boston_additional_location_conflict')
    # The current public template has one paragraph containing multiple native
    # blocks. Retain every narrative sibling before its Date facts, including
    # later paragraphs/lists if the publisher expands that same content area.
    narrative = []
    for sibling in title.next_siblings:
        if sibling is labels['Date:'] or (getattr(sibling, 'name', None)
                and labels['Date:'] in sibling.descendants):
            break
        narrative.append(str(sibling))
    body = _full(''.join(narrative))
    if not body:
        _hold(PARKOUR, card['url'], 'boston_additional_description_missing', diagnostics)
        return []
    row = _row(PARKOUR, card['title'], start, end, card['url'], 'parkour:zenplanner:' + card['native_id'],
        body, card['venue'], address[0], address[1], point=DOJO_POINT,
        evidence=DOJO_EVIDENCE, provenance=DOJO_PROVENANCE)
    if row:
        row['publisher_schedule_rule'] = 'Separate native registration session reconciles the aggregate Squarespace header; date and start/end verified against the current linked booking detail.'
    return [row] if row else []


def _tracksmith_manifest(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    cards = soup.select('a.EventCard.events-carousel__card')
    if not cards and not re.search(r'UPCOMING EVENTS', soup.get_text(), re.I):
        raise ValueError('boston_additional_calendar_changed')
    out = []
    for card in cards:
        url = urljoin(SOURCES[TRACKSMITH][0], card.get('href', ''))
        selectors = ['.EventCard__title', '.EventCard__date', '.EventCard__time', '.EventCard__locAbbr']
        title, day, clock, loc = [plain(card.select_one(s).get_text()) if card.select_one(s) else '' for s in selectors]
        if loc != 'Bos':
            raise ValueError('boston_additional_calendar_changed')
        if not event_url(TRACKSMITH, url) or not title or not day or not clock:
            raise ValueError('boston_additional_calendar_changed')
        out.append({'url': url, 'title': title, 'day_label': day, 'clock': clock})
    return out


def _tracksmith_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    schemas = _schemas(soup)
    content = soup.select_one('.event-page__content')
    h1 = soup.select_one('h1.event-page__title')
    canonical = soup.select_one('link[rel="canonical"]')
    if (len(schemas) != 1 or content is None or h1 is None
            or canonical is None or canonical.get('href') != card['url']):
        raise ValueError('boston_additional_detail_changed')
    item = schemas[0]
    if plain(item.get('name')) != card['title'] or plain(h1.get_text()) != card['title']:
        raise ValueError('boston_additional_detail_changed')
    if item.get('eventStatus', '').endswith(('EventCancelled', 'EventPostponed')):
        _hold(TRACKSMITH, card['url'], 'boston_additional_not_public', diagnostics)
        return []
    try:
        day = date.fromisoformat(item['startDate'])
    except (ValueError, TypeError, KeyError):
        raise ValueError('boston_additional_time_conflict')
    if item.get('endDate') != item['startDate'] or day.strftime('%-d %b') != card['day_label']:
        raise ValueError('boston_additional_time_conflict')
    start, end = _clock(day, card['clock']), None
    native_summary = plain(item.get('description'))
    span = re.search(r'(?:class running from|from)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[-–]\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))', native_summary, re.I)
    if span:
        began, end = _range(day, span[1] + '-' + span[2])
        if began != start:
            raise ValueError('boston_additional_time_conflict')
    elif match := re.search(r'will run (?:to|until)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))', native_summary, re.I):
        end = _clock(day, match[1])
        if end <= start:
            raise ValueError('boston_additional_time_conflict')
    if not _within(start, end, now):
        _hold(TRACKSMITH, card['url'], 'boston_additional_outside_window', diagnostics)
        return []
    location = item.get('location') or {}
    venue = plain(location.get('name'))
    native = plain((location.get('address') or {}).get('name'))
    if (venue, native) in {
            ('The Trackhouse', '285 Newbury Street, Boston, MA'),
            ('The Trackhouse', '285 Newbury Street, Boston, MA 02115'),
            ('The Boston Trackhouse', '285 Newbury St, Boston MA 02115'),
            ('The Boston Trackhouse', '285 Newbury St, Boston, MA 02115')}:
        street, city = '285 Newbury Street, Boston, MA 02115', 'Boston'
        provenance = 'Exact event Trackhouse street; postal ZIP supplied by the publisher Trackhouse venue page.'
        evidence = SOURCES[TRACKSMITH][0]
    elif (venue, native) == ('The Newbury Boston', '1 Newbury St, Boston, MA 02116'):
        street, city = native, 'Boston'
        provenance = 'Native partner run event explicitly meets in The Newbury hotel lobby at its own full street, not the Trackhouse.'
        evidence = card['url']
    else:
        address = _street(native)
        if not address or not venue:
            _hold(TRACKSMITH, card['url'], 'boston_additional_street_unresolved', diagnostics)
            return []
        street, city = address
        provenance, evidence = 'Native event-specific full street.', card['url']
    body = _full(str(content))
    if not body:
        _hold(TRACKSMITH, card['url'], 'boston_additional_description_missing', diagnostics)
        return []
    row = _row(TRACKSMITH, card['title'], start, end, card['url'],
        'tracksmith:' + urlsplit(card['url']).path.split('/')[-1], body, venue, street, city,
        evidence=evidence, provenance=provenance, native_venue_name=venue,
        native_venue_address=native)
    return [row] if row else []


def _trustees_manifest(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    cards = soup.select('article.teaser-event')
    if not cards and 'Metro Boston Programs' not in soup.get_text():
        raise ValueError('boston_additional_calendar_changed')
    out = []
    for card in cards:
        anchor, heading = card.select_one('a[href]'), card.select_one('.teaser-event__title')
        if anchor is None or heading is None:
            raise ValueError('boston_additional_calendar_changed')
        url = urljoin(SOURCES[TRUSTEES][0], anchor['href'])
        if not event_url(TRUSTEES, url):
            raise ValueError('boston_additional_calendar_changed')
        out.append({'url': url, 'title': plain(heading.get_text())})
    return out


def _trustees_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    body = soup.select_one('.event-text__column-right.wysiwyg')
    when = soup.select_one('.event-text__when p')
    location = soup.select_one('.event-text__location > p')
    if body is None or when is None or location is None:
        raise ValueError('boston_additional_detail_changed')
    title = body.select_one('h4')
    if title is None or plain(title.get_text()) != 'About ' + card['title']:
        raise ValueError('boston_additional_detail_changed')
    title.decompose()
    for child in body.select('.event-text__social'):
        child.decompose()
    parts = [plain(x) for x in when.stripped_strings if plain(x)]
    if len(parts) != 2:
        raise ValueError('boston_additional_time_conflict')
    try:
        day = datetime.strptime(parts[0], '%A, %B %d, %Y').date()
    except ValueError:
        raise ValueError('boston_additional_time_conflict')
    start, end = _range(day, parts[1])
    if not _within(start, end, now):
        _hold(TRUSTEES, card['url'], 'boston_additional_outside_window', diagnostics)
        return []
    # Root's production audit verified this exact cohosted occurrence is already
    # public through Boston Food Forest Coalition. Preserve that working event.
    if (card['url'] == 'https://thetrustees.org/event/450287/'
            and start.isoformat() == '2026-12-19T14:30:00-05:00'
            and end.isoformat() == '2026-12-19T16:00:00-05:00'):
        _hold(TRUSTEES, card['url'], 'boston_additional_existing_public_overlap', diagnostics)
        return []
    loc = [plain(x) for x in location.stripped_strings if plain(x)]
    if len(loc) != 3:
        _hold(TRUSTEES, card['url'], 'boston_additional_street_unresolved', diagnostics)
        return []
    venue, streetline, locality = loc
    streetline = streetline.replace('–', '-')
    address = _street(streetline + ', ' + locality)
    text = _full(str(body))
    if not address or not text:
        _hold(TRUSTEES, card['url'], 'boston_additional_street_unresolved' if not address
            else 'boston_additional_description_missing', diagnostics)
        return []
    street, city = address
    provenance, evidence = 'Native event venue and full postal street.', card['url']
    if venue == 'Leland St Cooperative Garden' and street == '2-6 Leland St, Jamaica Plain, MA 02130':
        # The event's exact4Leland entrance lies within its own2–6 site range.
        # Preserve the publisher range rather than replace it with another venue.
        provenance = 'Native garden address range 2–6 Leland Street contains the narrative 4 Leland entrance; exact actual garden retained.'
    row = _row(TRUSTEES, card['title'], start, end, card['url'],
        'trustees:' + urlsplit(card['url']).path.strip('/').split('/')[-1], text,
        venue, street, city, evidence=evidence, provenance=provenance,
        native_venue_name=venue, native_venue_address=streetline + ', ' + locality)
    return [row] if row else []


def _central(fetch, now, deadline_at, diagnostics):
    _budget(deadline_at)
    soup = BeautifulSoup(fetch(SOURCES[CENTRAL][0], 'text/html'), 'html.parser')
    heading = soup.select_one('h1')
    blocks = soup.select('.white-content')
    if heading is None or len(blocks) != 2:
        raise ValueError('boston_additional_detail_changed')
    body = _full('\n'.join(str(n) for n in blocks))
    if not body:
        raise ValueError('boston_additional_description_missing')
    if (not re.search(r'third Thursday of the month', body, re.I)
            or not re.search(r'officially from 7\s*[-–]\s*9\s*pm', body, re.I)
            or not re.search(r'Cambridge location at\s*170 Alewife Brook Pkwy', body)):
        raise ValueError('boston_additional_schedule_changed')
    _budget(deadline_at)
    post = json.loads(fetch('https://centralrockgym.com/cambridge/wp-json/wp/v2/events/492', 'application/json'))
    modified = timestamp(post.get('modified_gmt'), 'UTC')
    if (post.get('id') != 492 or post.get('link') != SOURCES[CENTRAL][0]
            or post.get('status') != 'publish' or not modified
            or not timedelta(days=-1) <= now - modified <= timedelta(days=90)):
        raise ValueError('boston_additional_schedule_changed')
    edition = re.search(r'this time on Thursday,\s*([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)', body)
    if not edition:
        raise ValueError('boston_additional_schedule_changed')
    named = datetime.strptime(f'{edition[1]} {edition[2]} {modified.year}', '%B %d %Y').date()
    if named.weekday() != 3 or not 15 <= named.day <= 21:
        raise ValueError('boston_additional_schedule_changed')
    first = calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date()
    if not first - timedelta(days=35) <= named <= first + timedelta(days=60):
        raise ValueError('boston_additional_schedule_changed')
    out = []
    for offset in range(61):
        day = first + timedelta(days=offset)
        if day.weekday() != 3 or not 15 <= day.day <= 21:
            continue
        start, end = _range(day, '7pm-9pm')
        if not _within(start, end, now):
            continue
        row = _row(CENTRAL, plain(heading.get_text()), start, end, SOURCES[CENTRAL][0],
            'centralrock:492:' + day.isoformat(), body, 'Central Rock Gym Cambridge',
            '170 Alewife Brook Parkway, Cambridge, MA 02138', 'Cambridge',
            evidence='https://centralrockgym.com/locations/',
            provenance='Exact native Cambridge gym street; complete postal form verified against the official location directory.',
            native_options={'publisher_schedule_rule': 'third_thursday_19:00-21:00_America/New_York'})
        if row:
            row['publisher_schedule_rule'] = 'Third Thursday of every month,19:00–21:00 America/New_York;60-day expansion of explicit current publisher rule.'
            out.append(row)
    return out


def _rock_manifest(now):
    first = calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date()
    return [{'url': SOURCES[ROCKSPOT][0] + '?' + urlencode({'day': (first + timedelta(days=d)).isoformat()}),
        'title': 'Rock Spot South Boston public schedule', 'day': (first + timedelta(days=d)).isoformat()}
        for d in range(0, 60, 7)]


def _rock_page(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    selected = soup.select_one('#location-select option[selected]')
    day_input = soup.select_one('form[method="get"] input[name="day"]')
    if (selected is None or selected.get('value') != '95' or plain(selected.get_text()) != 'South Boston, MA'
            or day_input is None or day_input.get('value') != card['day']):
        raise ValueError('boston_additional_calendar_changed')
    first, out = date.fromisoformat(card['day']), []
    for block in soup.select('div.card.capitan-card'):
        heading = block.select_one(':scope > .card-header')
        content = block.select_one(':scope > .card-body')
        if heading is None or content is None:
            continue
        try:
            day = datetime.strptime(plain(heading.get_text()), '%A, %B %d, %Y').date()
        except ValueError:
            continue
        if not first <= day < first + timedelta(days=7):
            raise ValueError('boston_additional_calendar_changed')
        chunks, current = [], []
        for child in content.children:
            if getattr(child, 'name', None) == 'hr':
                chunks.append(current); current = []
            else:
                current.append(str(child))
        chunks.append(current)
        for chunk in chunks:
            item = BeautifulSoup(''.join(chunk), 'html.parser')
            spans = item.find_all('span', class_='d-block', recursive=False)
            if not spans:
                continue
            if len(spans) != 2:
                raise ValueError('boston_additional_calendar_changed')
            title, clocks = [plain(s.get_text()) for s in spans]
            # Capitan displays bookable private inventory beside public events.
            # A class without an open public Book link is a closed cohort/slot.
            if re.search(r'\b(?:rental|birthday|party deposit|overnight|private|group visit|scout)\b', title, re.I):
                continue
            installment = re.search(r'\(Part (\d+) of (\d+)\)', title)
            if installment and int(installment[1]) > 1:
                # Later course installments are not standalone admission even
                # while the parent course's registration link remains open.
                continue
            book = item.select_one('a[href*="/select-num-participants/"]')
            details = item.select_one('div[id^="event-details-"] > div.mt-2')
            identifier = item.select_one('a.show-event-details[data-eventpartid]')
            if book is None:
                continue
            if details is None or identifier is None:
                raise ValueError('boston_additional_detail_changed')
            url = urljoin(SOURCES[ROCKSPOT][0], book['href'])
            if not event_url(ROCKSPOT, url) or not re.fullmatch(r'[1-9][0-9]*', identifier['data-eventpartid']):
                raise ValueError('boston_additional_detail_changed')
            start, end = _range(day, clocks)
            if not _within(start, end, now):
                continue
            body = _full(str(details))
            if not body:
                _hold(ROCKSPOT, card['url'], 'boston_additional_description_missing', diagnostics)
                continue
            native_id = urlsplit(url).path.split('/')[-3]
            row = _row(ROCKSPOT, title, start, end, url,
                'rockspot:' + native_id + ':' + identifier['data-eventpartid'], body,
                'Rock Spot Climbing South Boston', '30 Old Colony Avenue, South Boston, MA 02127', 'South Boston',
                evidence='https://rockspotclimbing.com/locations/ma/southboston/',
                provenance='Scheduler location95 explicitly selects South Boston; full street verified against the gym’s official location page. Other chain locations are not mapped here.',
                native_venue_name='South Boston, MA', native_venue_address='', native_venue_city='',
                native_options={'scheduler_location_id': '95'})
            if row:
                row['publisher_schedule_page'] = card['url']
                out.append(row)
    return out


def _harbor_manifest(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if 'Upcoming Events' not in soup.get_text():
        raise ValueError('boston_additional_calendar_changed')
    urls = []
    for a in soup.select('a[href]'):
        url = a['href'].split('?')[0]
        if event_url(HARBOR, url) and url not in urls:
            urls.append(url)
    return [{'url': url, 'title': 'Boston Harbor Now official calendar event'} for url in urls]


def _harbor_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    schemas = [s for s in _schemas(soup) if s.get('url') == card['url']]
    context_script = soup.select_one('script#__NEXT_DATA__')
    if len(schemas) != 1 or context_script is None:
        raise ValueError('boston_additional_detail_changed')
    item = schemas[0]
    if not (item.get('organizer') or {}).get('url', '').endswith('-11882374432'):
        raise ValueError('boston_additional_detail_changed')
    if item.get('eventStatus', '').endswith(('EventCancelled', 'EventPostponed')):
        _hold(HARBOR, card['url'], 'boston_additional_not_public', diagnostics)
        return []
    start, end = _offset(item.get('startDate')), _offset(item.get('endDate'))
    if not start or not end or end <= start:
        raise ValueError('boston_additional_time_conflict')
    if not _within(start, end, now):
        _hold(HARBOR, card['url'], 'boston_additional_outside_window', diagnostics)
        return []
    # The schema description is only a teaser; this is the complete visible
    # organizer overview, including the itinerary and access instructions.
    overview = soup.select('[class*="Overview-module"][class*="__summary"]')
    overview = [n for n in overview if '__summaryWrapper' not in ' '.join(n.get('class', []))]
    if len(overview) != 1:
        raise ValueError('boston_additional_detail_changed')
    body = _full(str(overview[0]))
    if not body:
        _hold(HARBOR, card['url'], 'boston_additional_description_missing', diagnostics)
        return []
    try:
        context = json.loads(context_script.string or context_script.get_text())['props']['pageProps']['context']
        basic = context['basicInfo']
    except (KeyError, TypeError, ValueError):
        raise ValueError('boston_additional_detail_changed')
    if basic.get('url') != card['url'] or str(basic.get('id')) != card['url'].rsplit('-', 1)[-1]:
        raise ValueError('boston_additional_detail_changed')
    if (basic.get('isProtected') is not False or basic.get('isListed') is not True
            or basic.get('isOnline') is not False or basic.get('status') != 'live'
            or basic.get('hideStartDate') is not False or basic.get('hideEndDate') is not False
            or basic.get('isParentEvent') is not False or basic.get('isSeries') is not False):
        _hold(HARBOR, card['url'], 'boston_additional_not_public', diagnostics)
        return []
    if (_offset((basic.get('startDate') or {}).get('utc')) != start
            or _offset((basic.get('endDate') or {}).get('utc')) != end):
        raise ValueError('boston_additional_time_conflict')
    location = item.get('location') or {}
    venue = plain(location.get('name'))
    address = location.get('address') or {}
    native_street = plain(address.get('streetAddress'))
    lat = soup.select_one('meta[property="event:location:latitude"]')
    lng = soup.select_one('meta[property="event:location:longitude"]')
    point = _point(lat.get('content') if lat else None, lng.get('content') if lng else None)
    provenance, evidence = 'Native organizer event-specific street and matching location point.', card['url']
    if (venue, native_street) == ('Bocce Ball Courts', '523 Commercial Street, Boston, MA 02109'):
        street, city = native_street, 'Boston'
        if '423 Commercial Street' in body:
            if not ('Langone' in body and 'Puopolo' in body) or point != (42.3686156, -71.0554974):
                raise ValueError('boston_additional_location_conflict')
            provenance, evidence = HARBOR_BOCCE_PROVENANCE, HARBOR_BOCCE_EVIDENCE
    elif (venue == 'Boston Harbor Islands Pavilion' and native_street ==
            '191 W Atlantic Avenue, Rose Kennedy Greenway btw Faneuil Hall Marketplace and Christopher Columbus Park, Boston, MA 02110'):
        street, city = '191 W Atlantic Avenue, Boston, MA 02110', 'Boston'
        provenance = 'Native full postal street normalized by removing the inserted landmark directions; exact191WAtlantic venue confirmed by Boston Harbor Islands and NPS. Native pavilion point retained.'
        evidence = 'https://www.bostonharborislands.org/access-hours/'
    else:
        parsed = _street(native_street)
        if not parsed:
            _hold(HARBOR, card['url'], 'boston_additional_street_unresolved', diagnostics)
            return []
        street, city = parsed
    # Bind event OG coordinates to the same venue’s own serialized location,
    # never a map viewport or an unrelated recommended event.
    if not _eventbrite_location_matches(context, venue, point):
        point = None
    row = _row(HARBOR, plain(item.get('name')), start, end, card['url'],
        'harbor:' + card['url'].rsplit('-', 1)[-1], body, venue, street, city,
        point=point, evidence=evidence, provenance=provenance,
        native_venue_name=venue, native_venue_address=native_street)
    return [row] if row else []


def _eventbrite_location_matches(context, venue, point):
    if not point:
        return False
    # Reviewed public Next payload nests location under basicInfo in some
    # releases. Only an object with this exact venue and its own address counts.
    def visit(value):
        if isinstance(value, dict):
            address = value.get('address')
            if plain(value.get('name')) == venue and isinstance(address, dict):
                if _point(address.get('latitude'), address.get('longitude')) == point:
                    return True
            return any(visit(v) for v in value.values() if isinstance(v, (dict, list)))
        if isinstance(value, list):
            return any(visit(v) for v in value)
        return False
    return visit(context.get('basicInfo', context))


def _manifest(key, fetch, now, deadline_at):
    if key == ROCKSPOT:
        return _rock_manifest(now)
    _budget(deadline_at)
    payload = fetch(SOURCES[key][0], 'text/html')
    fn = {PARKOUR: _parkour_manifest, TRACKSMITH: _tracksmith_manifest,
          TRUSTEES: _trustees_manifest, HARBOR: _harbor_manifest}[key]
    manifest = fn(payload, now)
    if key == PARKOUR:
        expanded = []
        for card in manifest:
            if card['url'] == HOLIDAY_PARENT:
                _budget(deadline_at, 18)
                expanded.extend(_parkour_linked_sessions(card, fetch(card['url'], 'text/html')))
            else:
                expanded.append(card)
        return expanded
    return manifest


def _detail(key, card, payload, now, diagnostics):
    if key == PARKOUR and card.get('kind') == 'zenplanner':
        return _parkour_zen_detail(card, payload, now, diagnostics)
    fn = {PARKOUR: _parkour_detail, TRACKSMITH: _tracksmith_detail,
          TRUSTEES: _trustees_detail, ROCKSPOT: _rock_page, HARBOR: _harbor_detail}[key]
    return fn(card, payload, now, diagnostics)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _card_valid(key, card, started):
    if not isinstance(card, dict) or not isinstance(card.get('title'), str) or not card['title'].strip():
        return False
    if key == ROCKSPOT:
        try:
            day = date.fromisoformat(card['day'])
            first = calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date()
            return bool(0 <= (day - first).days < 60 and (day - first).days % 7 == 0
                and card['url'] == SOURCES[key][0] + '?' + urlencode({'day': card['day']}))
        except (TypeError, ValueError, KeyError):
            return False
    if not event_url(key, card.get('url')):
        return False
    if key == PARKOUR:
        if card.get('kind') == 'zenplanner':
            if (card.get('native_id') not in HOLIDAY_SESSIONS or card.get('parent_url') != HOLIDAY_PARENT
                    or card['url'] != 'https://pkgenboston.sites.zenplanner.com/event.cfm?eventId=' + card['native_id']
                    or card['title'] != HOLIDAY_SESSIONS[card['native_id']][0]):
                return False
            label = HOLIDAY_SESSIONS[card['native_id']][1]
            clocks = re.match(r'^(\d{1,2}[ap]m) - (\d{1,2}[ap]m)', label)
            expected = _range(date(2026, 12, 5), clocks[1] + '-' + clocks[2])
            if ((_offset(card.get('start')), _offset(card.get('end'))) != expected
                    or card.get('venue') != 'The Dojo @ Somernova'
                    or _street(card.get('location')) != ('15 Properzi Way, Somerville, MA 02143', 'Somerville')):
                return False
        elif urlsplit(card['url']).hostname != 'pkgenboston.com' or card['url'] == HOLIDAY_PARENT:
            # A deployed older manifest may still contain the contradictory
            # aggregate holiday header. It must be rediscovered as the two
            # verified registration sessions before any prefix can publish.
            return False
        return bool(_offset(card.get('start')) and (card.get('end') is None or _offset(card['end']))
            and isinstance(card.get('location'), str) and isinstance(card.get('venue'), str))
    if key == TRACKSMITH:
        return bool(isinstance(card.get('day_label'), str) and re.fullmatch(r'\d{1,2} [A-Z][a-z]{2}', card['day_label'])
            and isinstance(card.get('clock'), str))
    return True


def _row_valid(key, row, card, started):
    if not isinstance(row, dict) or not event_url(key, row.get('event_url')):
        return False
    if (row.get('timezone') != ZONE or row.get('attendance_mode') != 'in_person'
            or not _content_envelope_valid(row)
            or not isinstance(row.get('description'), str) or not row['description'].strip()
            or plain(row['description']).casefold() == plain(row.get('title')).casefold()
            or len(row['description']) > MAX_DESCRIPTION or not row.get('venue_name')
            or not _street(row.get('venue_address')) or not row.get('location_provenance')
            or not row.get('location_evidence_url')):
        return False
    point = _point(row.get('lat'), row.get('lng'))
    if (row.get('lat') is not None or row.get('lng') is not None) and not point:
        return False
    reviewed = REVIEWED_VENUE_POINTS.get((key, row['venue_name'], row['venue_address']))
    if reviewed and (point != reviewed['point'] or row['location_evidence_url'] != reviewed['evidence']
            or row['location_provenance'] != reviewed['provenance']):
        return False
    start, end = _offset(row.get('starts_at')), _offset(row.get('ends_at')) if row.get('ends_at') else None
    if not start or (row.get('ends_at') and not end) or (end and end <= start) or not _within(start, end, started):
        return False
    if key != ROCKSPOT and row['event_url'] != card['url']:
        return False
    if key in {PARKOUR, TRACKSMITH, TRUSTEES} and row.get('title') != card['title']:
        return False
    if key == PARKOUR:
        address = _street(card['location'])
        if not address or row['venue_name'] != card['venue'] or row['venue_address'] != address[0]:
            return False
        if card.get('kind') == 'zenplanner':
            if start != _offset(card['start']) or end != _offset(card['end']):
                return False
            identity = 'parkour:zenplanner:' + card['native_id']
        else:
            sessions = _parkour_sessions(card, row['description'])
            if (start, end) not in sessions:
                return False
            identity = 'parkour:' + sha256(urlsplit(card['url']).path.encode()).hexdigest()
            if len(sessions) > 1:
                identity += ':' + start.astimezone(ZoneInfo(ZONE)).date().isoformat()
        if (row['venue_name'], row['venue_address']) == ('The Dojo @ Somernova', '15 Properzi Way, Somerville, MA 02143'):
            if (point != DOJO_POINT or row['location_evidence_url'] != DOJO_EVIDENCE
                    or row['location_provenance'] != DOJO_PROVENANCE):
                return False
    elif key == TRACKSMITH:
        local = start.astimezone(ZoneInfo(ZONE))
        if local.strftime('%-d %b') != card['day_label'] or _clock(local.date(), card['clock']) != start:
            return False
        identity = 'tracksmith:' + urlsplit(card['url']).path.split('/')[-1]
    elif key == TRUSTEES:
        identity = 'trustees:' + urlsplit(card['url']).path.strip('/').split('/')[-1]
    elif key == HARBOR:
        identity = 'harbor:' + card['url'].rsplit('-', 1)[-1]
        if row['venue_name'] == 'Bocce Ball Courts' and '423 Commercial Street' in row['description']:
            if (row['venue_address'] != '523 Commercial Street, Boston, MA 02109'
                    or point != (42.3686156, -71.0554974)
                    or row['location_provenance'] != HARBOR_BOCCE_PROVENANCE
                    or row['location_evidence_url'] != HARBOR_BOCCE_EVIDENCE):
                return False
    else:
        title = row.get('title', '')
        installment = re.search(r'\(Part (\d+) of (\d+)\)', title)
        if (re.search(r'\b(?:rental|birthday|party deposit|overnight|private|group visit|scout)\b', title, re.I)
                or installment and int(installment[1]) > 1):
            # Reject old durable prefixes collected before the public-course
            # eligibility correction, even if their stored hash is intact.
            return False
        if (row.get('publisher_schedule_page') != card['url']
                or row['venue_name'] != 'Rock Spot Climbing South Boston'
                or row['venue_address'] != '30 Old Colony Avenue, South Boston, MA 02127'
                or not date.fromisoformat(card['day']) <= start.astimezone(ZoneInfo(ZONE)).date()
                    < date.fromisoformat(card['day']) + timedelta(days=7)):
            return False
        native = urlsplit(row['event_url']).path.split('/')[-3]
        return bool(re.fullmatch('rockspot:' + native + r':[1-9][0-9]*', str(row.get('id', ''))))
    return row.get('id') == identity


def _checkpoint_valid(key, state, now):
    try:
        started = _offset(state['started_at'])
        manifest = state['manifest']
        if (type(state['version']) is not int or state['version'] != 1 or state['source_key'] != key or not started
                or started.utcoffset() != timedelta(0) or not -60 <= (now - started).total_seconds() <= 14400
                or state['window_start'] != calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date().isoformat()
                or type(state['cursor']) is not int or type(state['manifest_count']) is not int
                or not isinstance(manifest, list) or not 0 <= state['cursor'] <= len(manifest) <= MAX_MANIFEST
                or state['manifest_count'] != len(manifest) or state['manifest_hash'] != _digest(manifest)
                or not all(_card_valid(key, card, started) for card in manifest)
                or len({c['url'] for c in manifest}) != len(manifest)
                or not isinstance(state['events'], list) or len(state['events']) > MAX_RECORDS
                or not isinstance(state['diagnostics'], list) or len(state['diagnostics']) > 400
                or not isinstance(state['outcomes'], list) or len(state['outcomes']) != state['cursor']):
            return False
        if key == ROCKSPOT and manifest != _rock_manifest(started):
            return False
        prefix = {c['url']: c for c in manifest[:state['cursor']]}
        by_url = {u: [] for u in prefix}
        identities = set()
        for row in state['events']:
            url = row.get('publisher_schedule_page') if key == ROCKSPOT else row.get('event_url')
            if url not in prefix or not _row_valid(key, row, prefix[url], started):
                return False
            identity = (row['id'], row['starts_at'])
            if identity in identities:
                return False
            identities.add(identity)
            by_url[url].append(row)
        for index, outcome in enumerate(state['outcomes']):
            url = manifest[index]['url']
            if (not isinstance(outcome, dict) or outcome.get('url') != url
                    or outcome.get('rows_hash') != _digest(by_url[url])):
                return False
        for diag in state['diagnostics']:
            if not isinstance(diag, dict) or diag.get('id') not in prefix or diag.get('reason') not in ERROR_CODES:
                return False
        return len(json.dumps(state).encode()) <= MAX_CHECKPOINT_BYTES
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return False


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError('unregistered_boston_additional_source')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('boston_additional_checkpoint_invalid')
    now = now.astimezone(timezone.utc)
    state = deepcopy(checkpoint) if checkpoint is not None else None
    if state is not None and not _checkpoint_valid(key, state, now):
        raise ValueError('boston_additional_checkpoint_invalid')
    if state is None:
        manifest = _manifest(key, fetch, now, deadline_at)
        if len(manifest) > MAX_MANIFEST or len({c['url'] for c in manifest}) != len(manifest):
            raise ValueError('boston_additional_record_limit')
        state = {'version': 1, 'source_key': key, 'started_at': now.isoformat(),
            'window_start': calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date().isoformat(),
            'manifest': manifest, 'manifest_hash': _digest(manifest), 'manifest_count': len(manifest),
            'cursor': 0, 'events': [], 'diagnostics': [], 'outcomes': []}
    frozen_now = _offset(state['started_at'])
    legacy_prefix = bool(state['events'] and
                         any('collector_event_content_v1' not in row for row in state['events']))
    for index in range(state['cursor'], min(len(state['manifest']), state['cursor'] + DETAILS_PER_CHUNK)):
        if deadline_at is not None and monotonic() + 18 >= deadline_at:
            break
        card = state['manifest'][index]
        rows = _detail(key, card, fetch(card['url'], 'text/html'), frozen_now, state['diagnostics'])
        if legacy_prefix:
            for row in rows:
                row.pop('collector_event_content_v1', None)
        if not rows and not any(d['id'] == card['url'] for d in state['diagnostics']):
            _hold(key, card['url'], 'boston_additional_outside_window', state['diagnostics'])
        state['events'].extend(rows)
        state['outcomes'].append({'url': card['url'], 'rows_hash': _digest(rows)})
        state['cursor'] = index + 1
        if len(state['events']) > MAX_RECORDS:
            raise ValueError('boston_additional_record_limit')
    if len(json.dumps(state).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('boston_additional_checkpoint_limit')
    if not _checkpoint_valid(key, state, now):
        raise ValueError('boston_additional_checkpoint_invalid')
    complete = state['cursor'] == len(state['manifest'])
    return {'complete': complete, 'events': deepcopy(state['events']) if complete else [],
        'checkpoint': state, 'diagnostics': deepcopy(state['diagnostics'])}


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)
    if key in CHECKPOINT_KEYS:
        state = None
        for _ in range(MAX_MANIFEST + 1):
            _budget(deadline_at)
            result = collect_chunk(source, fetch, checkpoint=state, deadline_at=deadline_at, now=now)
            if result['complete']:
                return result['events']
            state = result['checkpoint']
        raise ValueError('boston_additional_record_limit')
    diagnostics = []
    return (_arboretum if key == ARBORETUM else _central)(fetch, now, deadline_at, diagnostics)
