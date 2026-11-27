"""Additional Boston-area museum, cinema, art-school and maker calendars.

Only native dated occurrences are admitted. Detail-heavy calendars use a durable
complete-only snapshot; every HTTP operation is the injected guarded transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import base64
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest import boston_arts as shared
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = shared.ZONE
MOS = 'museum_science_boston_ma'
COOLIDGE = 'coolidge_corner_theatre_ma'
BAC = 'brookline_arts_center_ma'
ELIOT = 'eliot_school_ma'
HMSC = 'harvard_museums_science_culture_ma'
PEM = 'peabody_essex_museum_ma'
DECORDOVA = 'decordova_museum_ma'
AQUARIUM = 'new_england_aquarium_ma'
SOURCES = {
    MOS: ('https://www.mos.org/events', 'html', 'html'),
    COOLIDGE: ('https://coolidge.org/', 'html', 'html'),
    BAC: ('https://brooklineartscenter.org/workshops', 'html', 'html'),
    ELIOT: ('https://eliotschool.org/calendar', 'html', 'html'),
    HMSC: ('https://hmsc.harvard.edu/programs/upcoming-programs/', 'html', 'html'),
    PEM: ('https://www.pem.org/events', 'html', 'html'),
    DECORDOVA: ('https://thetrustees.org/things-to-do/?_event_related_place=1730', 'html', 'html'),
    AQUARIUM: ('https://www.neaq.org/engage/events-and-programs/', 'html', 'html'),
}
LABELS = {MOS: 'Museum of Science, Boston', COOLIDGE: 'Coolidge Corner Theatre',
          BAC: 'Brookline Arts Center', ELIOT: 'Eliot School of Fine & Applied Arts',
          HMSC: 'Harvard Museums of Science & Culture', PEM: 'Peabody Essex Museum',
          DECORDOVA: 'deCordova Sculpture Park and Museum', AQUARIUM: 'New England Aquarium'}
SOURCE_NOTES = {
    MOS: 'Native Drupal event-listing API discovered in permitted HTML; complete pagination and full detail bodies, rolling 60 days.',
    COOLIDGE: 'Native cinema listings and individual ticketed showtimes; full program/film descriptions, rolling 60 days.',
    BAC: 'Native workshop content blocks with complete program text and explicit session dates; conflicting weekday/date held.',
    ELIOT: 'Complete month calendars plus every native overflow-day link; exact ISO occurrences and class details. Native ten-record ICS export is not used.',
    HMSC: 'Complete Calendar Plus program listing and full detail bodies; exact per-event museum/venue street mapping.',
    PEM: 'Complete native CollectionPage Event manifest, all explicit detail occurrences and full prose; Salem within Boston metro scope.',
    DECORDOVA: 'Native FacetWP listing scoped to property 1730, verified total and full detail pages; Lincoln within Boston metro scope.',
    AQUARIUM: 'Native TEC REST with complete descriptions and structured venue; public calendar availability excludes sold-out and member-only events.',
}
ALLOWED_HOSTS = {key: (urlsplit(v[0]).hostname,) for key, v in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES) - {BAC, AQUARIUM}
CHECKPOINT_MANIFEST_LIMITS = {}
# Current capture has 179 showtimes; retain room for the cinema's next native
# release while preserving the global 500-record and 900KB checkpoint bounds.
CHECKPOINT_EVENT_LIMITS = {COOLIDGE: 500}
DAYS = 60
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900000
MAX_LIST_PAGES = 100
DETAILS_PER_CHUNK = 12
PAGES_PER_CHUNK = 4
UNAVAILABLE = re.compile(r'\b(?:sold[- ]out|waitlist(?:ed)?|cancel(?:l)?ed|postponed|members?[- ]only|private (?:event|party|studio)|closed|closure)\b', re.I)
REMOTE = re.compile(r'\b(?:online (?:workshop|lecture|only|event)|virtual (?:event|program|workshop)|webinar)\b', re.I)
PREFIX = 'boston_arts_additional_'
HOLD_REASONS = shared.HOLD_REASONS | {PREFIX + s for s in ('not_public', 'not_current', 'schedule_unresolved', 'street_unresolved', 'description_missing')}
ERROR_CODES = shared.ERROR_CODES | HOLD_REASONS | {PREFIX + s for s in ('source_unregistered', 'identity_changed', 'listing_changed', 'pagination_changed', 'manifest_changed', 'manifest_limit', 'record_limit', 'checkpoint_invalid', 'checkpoint_size_limit', 'payload_changed')}

# Primary publisher address evidence is recorded with the capture receipt. PEM's
# point is the exact native LocalBusiness.geo bound to 161 Essex St, not a viewport.
VENUES = {
    MOS: [('Museum of Science', '1 Science Park, Boston, MA 02114', 'Boston', None)],
    COOLIDGE: [('Coolidge Corner Theatre', '290 Harvard Street, Brookline, MA 02446', 'Brookline', None)],
    BAC: [('Brookline Arts Center', '86 Monmouth Street, Brookline, MA 02446', 'Brookline', None)],
    ELIOT: [('Eliot Schoolhouse', '24 Eliot Street, Jamaica Plain, MA 02130', 'Jamaica Plain', None),
            ('Eliot School Annex', '253 Amory Street, Jamaica Plain, MA 02130', 'Jamaica Plain', None),
            ('Boston Building Resources', '100 Terrace Street, Boston, MA 02120', 'Boston', None)],
    HMSC: [('Harvard Museum of Natural History', '26 Oxford Street, Cambridge, MA 02138', 'Cambridge', None),
           ('Peabody Museum of Archaeology & Ethnology', '11 Divinity Avenue, Cambridge, MA 02138', 'Cambridge', None),
           ('Harvard Museum of the Ancient Near East', '6 Divinity Avenue, Cambridge, MA 02138', 'Cambridge', None),
           ('Geological Lecture Hall', '24 Oxford Street, Cambridge, MA 02138', 'Cambridge', None),
           ('Collection of Historical Scientific Instruments', '1 Oxford Street, Cambridge, MA 02138', 'Cambridge', None)],
    PEM: [('Peabody Essex Museum', '161 Essex Street, Salem, MA 01970', 'Salem', (42.521442, -70.892372))],
    DECORDOVA: [('deCordova Sculpture Park and Museum', '51 Sandy Pond Road, Lincoln, MA 01773', 'Lincoln', None)],
    AQUARIUM: [('New England Aquarium', '1 Central Wharf, Boston, MA 02110', 'Boston', None)],
}

# The actual Eliot publication hold at this exact venue was verified against
# City of Boston SAM_ADDRESS_ID134497, a unitless address point (not a range).
ELIOT_BBR_EVIDENCE = ('https://gis.boston.gov/arcgis/rest/services/SAM/Live_SAM_Address/MapServer/1/query'
                      '?f=json&where=SAM_ADDRESS_ID%3D134497&outFields=*&outSR=4326&returnGeometry=true')


def _reviewed_municipal_point(key, venue, address):
    if (key, venue, address) == (ELIOT, 'Boston Building Resources',
                                  '100 Terrace Street, Boston, MA 02120'):
        return (42.328649, -71.097821)
    return None


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError(PREFIX + 'source_unregistered')
    return key


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _outcome(item, rows, reason):
    return dict(event_url=item['url'], reason=reason, rows=[dict(
        id=row['id'], starts_at=row['starts_at'], ends_at=row.get('ends_at'),
        description_sha256=sha256(row['description'].encode()).hexdigest(), row_sha256=_hash(row))
        for row in rows])


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.netloc != ALLOWED_HOSTS[key][0] or p.query or p.fragment or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I):
            return False
        patterns = {MOS: r'/events/[a-z0-9-]+', COOLIDGE: r'/(?:films|events)/[a-z0-9-]+',
                    BAC: r'/workshops', ELIOT: r'/classes/[a-z0-9-]+', HMSC: r'/calendar_event/[a-z0-9-]+/',
                    PEM: r'/events/[a-z0-9-]+', DECORDOVA: r'/event/\d+/', AQUARIUM: r'/event/[a-z0-9-]+/'}
        return bool(re.fullmatch(patterns[key], p.path))
    except ValueError:
        return False


def _listing_url(key, url):
    if url == SOURCES[key][0]:
        return True
    if not isinstance(url, str):
        return False
    if key == COOLIDGE:
        return url == 'https://coolidge.org/films-events/coming-soon' or bool(re.fullmatch(r'https://coolidge[.]org/films-events/welcome-coolidge-corner-theatre\?view_args=20\d{4}', url))
    if key == ELIOT:
        return bool(re.fullmatch(r'https://eliotschool[.]org/calendar/(?:month/20\d{2}-\d{2}|day/20\d{2}-\d{2}-\d{2})', url))
    if key == MOS:
        return bool(re.fullmatch(r'https://www[.]mos[.]org/api/v1/event-listing/event_detail/96\+101/all/all/all/all\?items_per_page=18&sort_by=date_asc(?:&page=\d{1,2})?', url))
    if key == DECORDOVA:
        return bool(re.fullmatch(r'https://thetrustees[.]org/things-to-do/\?_event_related_place=1730&_paged=\d{1,2}', url))
    return False


def _item(key, url, title, *, sessions=None):
    if not event_url(key, url) or not title:
        raise ValueError(PREFIX + 'identity_changed')
    return dict(url=url, title=plain(title), id=key + ':' + urlsplit(url).path.strip('/').replace('/', ':'), sessions=sessions or [])


def _merge(items):
    result = {}
    for item in items:
        if item['url'] in result:
            old = result[item['url']]
            if (old['id'], old['title']) != (item['id'], item['title']):
                raise ValueError(PREFIX + 'manifest_changed')
            old['sessions'] = sorted({json.dumps(v, sort_keys=True): v for v in old['sessions'] + item['sessions']}.values(), key=lambda v: json.dumps(v, sort_keys=True))
        else:
            result[item['url']] = deepcopy(item)
    return sorted(result.values(), key=lambda v: v['url'])


def _attach_content(row, item, body, start, end, *, title=None, native_options=None):
    if row is None:
        return None
    options = dict(item.get('native_options') or {})
    options.update(native_options or {})
    facts = {
        'title': title or item['title'],
        'description': body,
        'is_all_day': False,
        'starts_at_utc': start.astimezone(timezone.utc).isoformat(),
        'ends_at_utc': end.astimezone(timezone.utc).isoformat() if end else None,
        'event_url': item['url'],
        'native_options': options or None,
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
    if (not isinstance(evidence, dict) or set(evidence) != {'version', 'event_id', 'facts'}
            or evidence.get('version') != 1 or evidence.get('event_id') != row.get('id')
            or not isinstance(evidence.get('facts'), dict)):
        return False
    facts = evidence['facts']
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


def _row(key, item, body, start, end, *, venue_index=0, identity=None, title=None, room=None):
    if not start or start.tzinfo is None or end is not None and (end.tzinfo is None or end <= start):
        raise ValueError(PREFIX + 'schedule_unresolved')
    venue, address, city, point = VENUES[key][venue_index]
    if room:
        venue += ' — ' + room
    municipal_point = _reviewed_municipal_point(key, venue, address)
    point = municipal_point or point
    body = shared._body(body)
    rid = item['id'] + ':' + str(identity or start.isoformat())
    row = record(title or item['title'], start.isoformat(), end.isoformat() if end else None,
                 venue, address, city, item['url'], rid, lat=point[0] if point else None,
                 lng=point[1] if point else None, tz=ZONE, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                   location_provenance='publisher_venue_coordinates' if point else 'publisher_venue_street_pending_geocode')
        if key == ELIOT and venue_index in (0, 1):
            row['location_provenance'] = 'publisher_class_street_neighborhood_zip_resolution'
        if municipal_point:
            row.update(location_provenance='reviewed_municipal_exact_address_point',
                       location_evidence_url=ELIOT_BBR_EVIDENCE)
    return _attach_content(row, item, body, start, end, title=title,
                           native_options={'room': room} if room else None)


def _unique(rows):
    rows = shared._unique([r for r in rows if r])
    if len(rows) > 500:
        raise ValueError(PREFIX + 'record_limit')
    return rows


def _clock(value):
    v = re.sub(r'[.\s]', '', value).lower()
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(am|pm)', v)
    if not m or not 1 <= int(m[1]) <= 12 or int(m[2] or 0) > 59:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return int(m[1]) % 12 + (12 if m[3] == 'pm' else 0), int(m[2] or 0)


def _times(day, text):
    t = re.sub(r'\s+', '', text).lower().replace('–', '-').replace('—', '-')
    parts = t.split('-')
    if len(parts) not in (1, 2):
        raise ValueError(PREFIX + 'schedule_unresolved')
    if len(parts) == 2 and not re.search('[ap]m$', parts[0]):
        suffix = re.search('[ap]m$', parts[1])
        if not suffix:
            raise ValueError(PREFIX + 'schedule_unresolved')
        parts[0] += suffix[0]
        if _clock(parts[0]) >= _clock(parts[1]) and suffix[0] == 'pm':
            parts[0] = parts[0][:-2] + 'am'
    start = datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)).replace(hour=_clock(parts[0])[0], minute=_clock(parts[0])[1])
    end = None if len(parts) == 1 else datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)).replace(hour=_clock(parts[1])[0], minute=_clock(parts[1])[1])
    if end is not None and end <= start:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return start, end


def _day(text, year=None):
    m = re.search(r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})(?:[–-]\d{1,2})?(?:,?\s+(20\d{2}))?', text, re.I)
    if not m or not (m[3] or year):
        raise ValueError(PREFIX + 'schedule_unresolved')
    month = datetime.strptime(m[1][:3].title(), '%b').month
    day = date(int(m[3] or year), month, int(m[2]))
    weekday = re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b', text, re.I)
    if weekday and weekday[1].lower() != day.strftime('%a').lower():
        raise ValueError(PREFIX + 'schedule_unresolved')
    return day


def _ld(soup):
    out = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.get_text())
        except ValueError:
            raise ValueError(PREFIX + 'payload_changed')
        out.extend(value if isinstance(value, list) else [value])
    return out


def _hmsc_listing(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('main')
    if not main or 'Upcoming Programs' not in soup.get_text():
        raise ValueError(PREFIX + 'listing_changed')
    links = [a for a in main.select('a[href]') if '/calendar_event/' in a['href']]
    if not links or soup.select('.pagination a, .page-numbers.next'):
        raise ValueError(PREFIX + 'pagination_changed')
    return _merge([_item(HMSC, urljoin(SOURCES[HMSC][0], a['href']), a.get_text(' ', strip=True)) for a in links]), []


def _hmsc_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    content = soup.select_one('article.calendar_event .entry-content')
    title = soup.select_one('h1')
    if not content or not title or plain(title.get_text()) != item['title']:
        raise ValueError(PREFIX + 'identity_changed')
    body = shared._body(str(content))
    if REMOTE.search(body) or UNAVAILABLE.search(item['title']):
        raise ValueError(PREFIX + 'not_public')
    google = [a['href'] for a in soup.select('a[href]') if a['href'].startswith('https://calendar.google.com/calendar/r/eventedit?')]
    if len(google) != 1:
        raise ValueError(PREFIX + 'schedule_unresolved')
    q = parse_qs(urlsplit(google[0]).query)
    clocks = q.get('dates', [''])[0].split('/')
    if len(clocks) != 2 or not all(re.fullmatch(r'20\d{6}T\d{6}Z', v) for v in clocks):
        raise ValueError(PREFIX + 'schedule_unresolved')
    start, end = [datetime.strptime(v, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc) for v in clocks]
    if not shared._within(start, end, now, DAYS):
        return []
    location_nodes = content.find_all(string=re.compile('Location:'))
    location = body[:body.find('\n\n')+1000] if not location_nodes else location_nodes[0].parent.parent.get_text(' ', strip=True)
    match = [i for i, v in enumerate(VENUES[HMSC]) if re.search(r'\b' + re.escape(v[1].split(',')[0]).replace('Street', '(?:Street|St[.]?)').replace('Avenue', '(?:Avenue|Ave[.]?)') + r'\b', location, re.I)]
    if not match and 'Harvard Museum of Natural History' in location and 'Cambridge' in location:
        match = [0]  # Official museum visit page confirms26OxfordSt for this named classroom.
    if len(match) != 1:
        raise ValueError(PREFIX + 'street_unresolved')
    observed = dict(item, native_options={'location_text': plain(location)})
    return [_row(HMSC, observed, body, start, end, venue_index=match[0])]


def _pem_listing(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    groups = [v for v in _ld(soup) if v.get('@type') == 'CollectionPage']
    if len(groups) != 1:
        raise ValueError(PREFIX + 'listing_changed')
    native = groups[0].get('mainEntity', {}).get('itemListElement')
    if not isinstance(native, list) or not 0 < len(native) <= 500 or [v.get('position') for v in native] != list(range(1, len(native)+1)):
        raise ValueError(PREFIX + 'pagination_changed')
    items = []
    for wrapper in native:
        event = wrapper.get('item', {})
        start, end = timestamp(event.get('startDate')), timestamp(event.get('endDate'))
        if not start or start.tzinfo is None or not end or end.tzinfo is None or end <= start:
            raise ValueError(PREFIX + 'schedule_unresolved')
        if start >= now + timedelta(days=DAYS) or UNAVAILABLE.search(plain(event.get('name'))):
            continue
        if ((event.get('location') or {}).get('address', {}).get('streetAddress') != VENUES[PEM][0][1]
                or (event.get('offers') or {}).get('url') != event.get('url')):
            raise ValueError(PREFIX + 'identity_changed')
        if event.get('eventStatus') != 'https://schema.org/EventScheduled' or (event.get('offers') or {}).get('availability') in {'https://schema.org/SoldOut', 'https://schema.org/Discontinued'}:
            continue
        item = _item(PEM, event.get('url'), event.get('name'), sessions=[dict(start=event['startDate'], end=event.get('endDate'))])
        item['native_options'] = {'location_text': event['location']['address']['streetAddress']}
        items.append(item)
    # Keep ended siblings for native series-envelope detection and Markdown ICS
    # identity checks, but only fetch programs with an eligible occurrence.
    items = [item for item in _merge(items) if any(shared._within(timestamp(v['start']), timestamp(v.get('end')), now, DAYS) for v in item['sessions'])]
    return items, []


def _pem_occurrences(sessions):
    """Native PEM emits series envelopes alongside its individual sessions."""
    values = {(timestamp(v['start']), timestamp(v.get('end'))) for v in sessions}
    if any(a is None or a.tzinfo is None or b is None or b.tzinfo is None or b <= a for a, b in values):
        raise ValueError(PREFIX + 'schedule_unresolved')
    result = []
    for start, end in sorted(values):
        contained = [(a, b) for a, b in values if start <= a and b <= end and (a, b) != (start, end)]
        if (end-start > timedelta(days=1) and contained
                or len(contained) > 1 and any(a == start and b < end for a, b in contained)):
            continue
        result.append((start, end))
    return result


def _pem_markdown(item, payload, now):
    # The publisher serves native Markdown for selected records. Validate its
    # canonical identity and embedded calendar; use the full narrative, never
    # the short listing description. The listing supplies every explicit date.
    header = re.match(r'^---\s*\n(.*?)\n---\s*\n', payload, re.S)
    if not header:
        raise ValueError(PREFIX + 'identity_changed')
    fields = dict(re.findall(r'^([a-z_]+):\s*"?([^\n]*?)"?\s*$', header[1], re.M))
    if fields.get('canonical_url') != item['url'] or plain(fields.get('title')) != item['title']:
        raise ValueError(PREFIX + 'identity_changed')
    calendars = set(re.findall(r'data:text/calendar;charset=utf8;base64,([A-Za-z0-9+/=]+)', payload))
    if not calendars or len(calendars) > 100:
        raise ValueError(PREFIX + 'schedule_unresolved')
    native = []
    for encoded in calendars:
        try:
            entries = Calendar.from_ical(base64.b64decode(encoded, validate=True)).walk('VEVENT')
            if len(entries) != 1:
                raise ValueError()
            event = entries[0]
            if plain(str(event.get('SUMMARY'))) != item['title'] or str(event.get('LOCATION')) != '161 Essex St, Salem, MA 01970':
                raise ValueError()
            start, end = event.decoded('DTSTART'), event.decoded('DTEND')
            if not isinstance(start, datetime) or not isinstance(end, datetime) or start.tzinfo is None or end.tzinfo is None:
                raise ValueError()
            native.append((start, end))
        except Exception as exc:
            raise ValueError(PREFIX + 'schedule_unresolved') from exc
    occurrences = _pem_occurrences(item['sessions'])
    if not all(v in occurrences for v in native):
        raise ValueError(PREFIX + 'schedule_unresolved')
    narrative = payload.split('## Know before you go', 1)
    if len(narrative) != 2:
        raise ValueError(PREFIX + 'description_missing')
    body = re.split(r'(?:^|\n)(?:## )?Other events that may interest you|(?:^|\n)Stay up to date[.]', narrative[1], maxsplit=1)[0]
    body = re.sub(r'!\[[^]]*\]\([^)]*\)', '', body)
    body = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', body)
    body = shared._body(re.sub(r'(?m)^#{1,6}\s*', '', body))
    if UNAVAILABLE.search(item['title']) or REMOTE.search(body[:300]) or re.search(r'\bSOLD OUT\b', body, re.I):
        raise ValueError(PREFIX + 'not_public')
    return _unique([_row(PEM, item, body, start, end) for start, end in occurrences
                    if shared._within(start, end, now, DAYS)])


def _pem_detail(item, payload, now):
    if payload.startswith('---'):
        return _pem_markdown(item, payload, now)
    soup = BeautifulSoup(payload, 'html.parser')
    events = [v for v in _ld(soup) if v.get('@type') == 'Event']
    main = soup.select_one('main')
    if not events and item['sessions'] and all(timestamp(v.get('end') or v['start']) < now for v in item['sessions']):
        return []
    if not events or not main:
        raise ValueError(PREFIX + 'identity_changed')
    body_nodes = [n for n in main.find_all(recursive=False) if n.name == 'section' and not set(n.get('class', [])) & {'keepExploring', 'newsletter'}]
    body = shared._body('\n'.join(str(n) for n in body_nodes))
    if UNAVAILABLE.search(item['title']) or REMOTE.search(body[:300]):
        raise ValueError(PREFIX + 'not_public')
    rows = []
    occurrences = set(_pem_occurrences([dict(start=v.get('startDate'), end=v.get('endDate')) for v in events]))
    for event in events:
        link = (event.get('offers') or {}).get('url')
        if link != item['url'] or (event.get('location') or {}).get('address', {}).get('streetAddress') != '161 Essex Street, Salem, MA 01970':
            raise ValueError(PREFIX + 'identity_changed')
        if event.get('eventStatus') != 'https://schema.org/EventScheduled' or (event.get('offers') or {}).get('availability') in {'https://schema.org/SoldOut', 'https://schema.org/Discontinued'}:
            continue
        start, end = timestamp(event.get('startDate')), timestamp(event.get('endDate'))
        if (start, end) in occurrences and shared._within(start, end, now, DAYS):
            rows.append(_row(PEM, item, body, start, end, title=event['name']))
    return _unique(rows)


def _trust_listing(payload, url):
    soup = BeautifulSoup(payload, 'html.parser')
    scripts = [n.get_text().strip() for n in soup.select('script:not([src])') if 'window.FWP_JSON = ' in n.get_text()]
    if len(scripts) != 1:
        raise ValueError(PREFIX + 'listing_changed')
    config = json.loads(scripts[0].split('window.FWP_JSON = ', 1)[1].rstrip(';'))
    preload = config['preload_data']
    pager = preload['settings']['pager']
    number = int(parse_qs(urlsplit(url).query).get('_paged', ['1'])[0])
    cards = soup.select('.facetwp-template .event-cards .teaser-event')
    if (pager['page'] != number or pager['per_page'] != 16 or type(pager['total_rows']) is not int
            or not 0 <= pager['total_rows'] <= 500
            or pager['total_pages'] != max(1, (pager['total_rows']+15)//16)):
        raise ValueError(PREFIX + 'pagination_changed')
    expected = min(16, max(0, pager['total_rows'] - (number-1)*16))
    if len(cards) != expected:
        raise ValueError(PREFIX + 'pagination_changed')
    items = []
    for card in cards:
        a, title = card.select_one('a[href]'), card.select_one('.teaser-event__title')
        location = card.select_one('.teaser-event__location')
        if not a or not title or not location or plain(location.get_text()) != 'deCordova Sculpture Park and Museum | Lincoln':
            raise ValueError(PREFIX + 'identity_changed')
        item = _item(DECORDOVA, a['href'], title.get_text(' ', strip=True))
        item['native_options'] = {'location_text': plain(location.get_text(' ', strip=True))}
        items.append(item)
    following = [SOURCES[DECORDOVA][0] + '&_paged=' + str(number+1)] if number < pager['total_pages'] else []
    return _merge(items), following


def _native_page(key, payload, url):
    """Record all publisher IDs before horizon or eligibility filtering."""
    if key == MOS and '/api/' in url:
        data = json.loads(payload)
        pager = data['pager']
        ids = []
        for event in data['results']:
            card = BeautifulSoup(event['event_listing'], 'html.parser')
            ids.append(urljoin(SOURCES[MOS][0], card.select_one('.listing-item__title a[href]')['href']))
        return dict(page=pager['current_page'], total=pager['total_results'], size=18, ids=ids)
    if key == DECORDOVA:
        soup = BeautifulSoup(payload, 'html.parser')
        script = next(n.get_text().strip() for n in soup.select('script:not([src])') if 'window.FWP_JSON = ' in n.get_text())
        pager = json.loads(script.split('window.FWP_JSON = ', 1)[1].rstrip(';'))['preload_data']['settings']['pager']
        ids = [node.select_one('a[href]')['href'] for node in soup.select('.facetwp-template .event-cards .teaser-event')]
        return dict(page=pager['page']-1, total=pager['total_rows'], size=16, ids=ids)
    return None


def _record_native_page(state, key, payload, url):
    native = _native_page(key, payload, url)
    if native is None:
        return
    if (native['page'] != len(state['native_pages'])
            or state['native_total'] is not None and state['native_total'] != native['total']
            or len(set(native['ids'])) != len(native['ids'])
            or set(native['ids']) & set(state['native_seen'])
            or any(not event_url(key, value) for value in native['ids'])):
        raise ValueError(PREFIX + 'pagination_changed')
    state['native_total'] = native['total']
    state['native_seen'].extend(native['ids'])
    state['native_pages'].append(url)


def _trust_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    when = soup.select_one('.event-text__when')
    body_node = soup.select_one('.event-text__column-right.wysiwyg')
    location = soup.select_one('.event-text__location')
    title = soup.select_one('meta[property="og:title"]')
    canonical = soup.select_one('link[rel="canonical"]')
    detail_title = plain(title.get('content')) if title else ''
    detail_identity = detail_title.replace('–', '-').replace('—', '-')
    listing_identity = item['title'].replace('–', '-').replace('—', '-')
    if (not when or not body_node or not title or not canonical or canonical.get('href') != item['url']
            or not (detail_identity == listing_identity or listing_identity.endswith('...')
                    and detail_identity.startswith(listing_identity[:-3]))):
        raise ValueError(PREFIX + 'identity_changed')
    body = shared._body(str(body_node))
    if UNAVAILABLE.search(item['title']) or re.search(r'\bsold out\b', (soup.select_one('.event-text') or soup).get_text(' ', strip=True), re.I):
        raise ValueError(PREFIX + 'not_public')
    lines = list(when.stripped_strings)
    day = _day(' '.join(lines))
    if not now.astimezone(ZoneInfo(ZONE)).date() <= day < (now+timedelta(days=DAYS)).date():
        return []
    if not re.search(r'51 Sandy Pond Road\s+Lincoln,? MA 01773', (location or soup).get_text(' ', strip=True)):
        raise ValueError(PREFIX + 'street_unresolved')
    clock = next((v for v in lines if re.search(r'\d\s*(?:AM|PM)\b', v, re.I)), '')
    rows = []
    for segment in re.split(r'\s+and\s+', clock):
        label = re.search(r'\s*\(([^)]+)\)\s*$', segment)
        start, end = _times(day, segment[:label.start()] if label else segment)
        if shared._within(start, end, now, DAYS):
            rows.append(_row(DECORDOVA, item, body, start, end,
                             title=detail_title + (' — ' + label[1] if label else '')))
    return rows


def _mos_listing(payload, url, now):
    if '/api/' not in url:
        soup = BeautifulSoup(payload, 'html.parser')
        nodes = soup.select('#event-listing[data-api-url]')
        if len(nodes) != 1 or not _listing_url(MOS, nodes[0]['data-api-url']):
            raise ValueError(PREFIX + 'listing_changed')
        return [], [nodes[0]['data-api-url']]
    data = json.loads(payload)
    pager, native = data.get('pager', {}), data.get('results')
    page = int(parse_qs(urlsplit(url).query).get('page', ['0'])[0])
    if (not isinstance(native, list) or pager.get('current_page') != page or pager.get('items_per_page') != 18
            or type(pager.get('total_results')) is not int or not 0 <= pager['total_results'] <= 500
            or type(pager.get('total_pages')) is not int or not 0 <= pager['total_pages'] <= 28
            or len(native) != min(18, max(0, pager['total_results'] - page*18))
            or pager['total_pages'] != (pager['total_results']+17)//18):
        raise ValueError(PREFIX + 'pagination_changed')
    items = []
    for event in native:
        card = BeautifulSoup(event.get('event_listing', ''), 'html.parser')
        link = card.select_one('.listing-item__title a[href]')
        dates = card.select_one('.listing-item__date')
        if not link or not dates:
            raise ValueError(PREFIX + 'listing_changed')
        line = dates.get_text(' ', strip=True)
        try:
            day = _day(line)
        except ValueError:
            # A native multi-date listing still needs its complete detail;
            # do not silently discard it because the preview date is complex.
            day = None
        if day and not now.astimezone(ZoneInfo(ZONE)).date() <= day < (now + timedelta(days=DAYS)).date():
            continue
        items.append(_item(MOS, urljoin(SOURCES[MOS][0], link['href']), link.get_text(' ', strip=True)))
    next_url = re.sub(r'&page=\d+$', '', url) + '&page=' + str(page+1) if page+1 < pager['total_pages'] else None
    return _merge(items), [next_url] if next_url else []


def _mos_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    heading = soup.select_one('.event-show-header')
    title = soup.select_one('h1')
    details = soup.select_one('.event-details')
    if not heading or not title or plain(title.get_text()) != item['title'] or not details:
        raise ValueError(PREFIX + 'identity_changed')
    if re.search(r'\bMember Event\b', heading.get_text(' '), re.I) or UNAVAILABLE.search(heading.get_text(' ')):
        raise ValueError(PREFIX + 'not_public')
    dates = heading.select_one('.date-time')
    if not dates:
        raise ValueError(PREFIX + 'schedule_unresolved')
    line = dates.get_text(' ', strip=True)
    # The desktop and mobile copies are semantically identical; preserve one
    # complete narrative and all native speaker biographies, never the summary.
    desktop = details.select_one('.desktop-only')
    if desktop is None:
        raise ValueError(PREFIX + 'description_missing')
    if REMOTE.search(desktop.get_text(' ', strip=True)[:300]):
        raise ValueError(PREFIX + 'not_public')
    for node in desktop.select('button, .button, script, style'):
        node.decompose()
    speakers = soup.select('.speaker-listing')
    body = shared._body(str(desktop) + '\n' + '\n'.join(str(n) for n in speakers))
    schedules = _mos_schedule(line)
    sold_fireside = (item['url'] == 'https://www.mos.org/events/science-wellness-cody-rigsby'
                    and 'The Science of Wellness Fireside Chat is SOLD OUT!' in body)
    if re.search(r'\bsold out\b', body, re.I) and not sold_fireside:
        raise ValueError(PREFIX + 'not_public')
    rows = []
    for start, end, label in schedules:
        if sold_fireside and 'fireside chat' in label.lower():
            continue
        if shared._within(start, end, now, DAYS):
            rows.append(_row(MOS, item, body, start, end, title=item['title'] + (' — ' + label if label else '')))
    return _unique(rows)



def _mos_schedule(line):
    current_day = None
    days = []
    result = []
    for segment in line.split(';'):
        if '|' in segment:
            date_part, clocks = segment.split('|', 1)
            year = re.search(r'\b20\d{2}\b', date_part)
            current_day = _day(date_part, int(year[0]) if year else None)
            day_range = re.search(r'\b\d{1,2}[–-](\d{1,2}),?\s+20\d{2}', date_part)
            last = current_day.replace(day=int(day_range[1])) if day_range else current_day
            if not current_day <= last <= current_day+timedelta(days=7):
                raise ValueError(PREFIX + 'schedule_unresolved')
            days = [current_day+timedelta(days=i) for i in range((last-current_day).days+1)]
        else:
            clocks = segment
        if not current_day:
            raise ValueError(PREFIX + 'schedule_unresolved')
        clock_match = re.search(r'(?i)(\d{1,2}(?::\d{2})?\s*(?:[ap]m)?\s*[–-]\s*\d{1,2}(?::\d{2})?\s*[ap]m|\d{1,2}(?::\d{2})?\s*[ap]m(?:\s+and\s+\d{1,2}(?::\d{2})?\s*[ap]m)?)\s*$', clocks)
        if not clock_match:
            raise ValueError(PREFIX + 'schedule_unresolved')
        label = clocks[:clock_match.start()].strip(' –-')
        for day in days:
            for clock in re.split(r'\s+and\s+', clock_match[1], flags=re.I):
                start, end = _times(day, clock)
                result.append((start, end, label))
    return result


def _coolidge_listing(payload, url, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if not soup.select('.film-card'):
        raise ValueError(PREFIX + 'listing_changed')
    items = []
    for card in soup.select('.film-card'):
        title = card.select_one('.film-card__title a[href]') or card.select_one('h2 a[href], h3 a[href]')
        if not title:
            continue
        link = urljoin(url, title['href'])
        if not event_url(COOLIDGE, link):
            raise ValueError(PREFIX + 'identity_changed')
        items.append(_item(COOLIDGE, link, title.get_text(' ', strip=True)))
    if not items and url == SOURCES[COOLIDGE][0]:
        raise ValueError(PREFIX + 'pagination_changed')
    following = ['https://coolidge.org/films-events/coming-soon'] if url == SOURCES[COOLIDGE][0] else []
    for a in soup.select('.pager__item--next a[href]'):
        link = urljoin(url, a['href'])
        if not _listing_url(COOLIDGE, link):
            raise ValueError(PREFIX + 'pagination_changed')
        month = parse_qs(urlsplit(link).query).get('view_args', [''])[0]
        if month and datetime.strptime(month, '%Y%m').date() <= (now + timedelta(days=DAYS)).date():
            following.append(link)
    return _merge(items), following


def _coolidge_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    title = soup.select_one('h1')
    if not title or plain(title.get_text()) != item['title']:
        raise ValueError(PREFIX + 'identity_changed')
    if UNAVAILABLE.search(item['title']):
        raise ValueError(PREFIX + 'not_public')
    bodies = [n.select_one('.field__item') for n in soup.select('.field--name-body') if n.select_one('.field__label') and plain(n.select_one('.field__label').get_text()) == 'Body']
    if len(bodies) != 1:
        raise ValueError(PREFIX + 'description_missing')
    body = shared._body(str(bodies[0]))
    # The site presents month/day in its current showtime list. Resolve only a
    # unique occurrence in the anchored60-day window, preserving native weekday.
    rows = []
    for block in soup.select('.film-showtime-list'):
        day_text = block.select_one('.datepicker__date')
        weekday = block.select_one('.datepicker__day')
        if not day_text or not weekday or not re.fullmatch(r'\d{1,2}/\d{1,2}', day_text.get_text(strip=True)):
            raise ValueError(PREFIX + 'schedule_unresolved')
        month, day = map(int, day_text.get_text(strip=True).split('/'))
        possible = []
        for year in {now.astimezone(ZoneInfo(ZONE)).year, (now+timedelta(days=DAYS)).astimezone(ZoneInfo(ZONE)).year}:
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if now.astimezone(ZoneInfo(ZONE)).date() <= d < (now+timedelta(days=DAYS)).date() and d.strftime('%a').lower() == weekday.get_text(strip=True).lower():
                possible.append(d)
        if not possible:
            continue
        if len(possible) != 1:
            raise ValueError(PREFIX + 'schedule_unresolved')
        for a in block.select('a.showtime-ticket__button[href]'):
            classes = ' '.join(c for parent in [a, a.parent] for c in parent.get('class', []))
            if re.search(r'unavailable|sold-out|soldout|BeforeSales|AfterSales|AfterEvent', classes, re.I):
                continue
            time_node, room = a.select_one('.showtime-ticket__time'), a.select_one('.showtime-ticket__venue')
            parsed = urlsplit(a['href'])
            query = parse_qs(parsed.query)
            native = (query.get('evtinfo') or query.get('evtInfo') or [''])[0].split('~')[0]
            bundle = query.get('guid', [''])[0]
            is_bundle = (parsed.path.lower() == '/websales/pages/entrypoint.aspx' and 'availability--all' in classes
                         and bool(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', bundle)))
            if (parsed.scheme != 'https' or parsed.netloc != 'store.coolidge.org' or not time_node
                    or not (native.isdigit() and parsed.path.lower() == '/websales/pages/ticketsearchcriteria.aspx'
                            or is_bundle and parsed.path.lower() == '/websales/pages/entrypoint.aspx')):
                raise ValueError(PREFIX + 'identity_changed')
            start, _ = _times(possible[0], time_node.get_text(strip=True))
            if is_bundle:
                native = bundle + ':' + start.isoformat()
            if shared._within(start, None, now, DAYS):
                rows.append(_row(COOLIDGE, item, body, start, None, identity=native, room=room.get_text(strip=True) if room else None))
    return _unique(rows)


def _eliot_listing(payload, url, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if not soup.select_one('.calendar-calendar'):
        raise ValueError(PREFIX + 'listing_changed')
    following = []
    for a in soup.select('a[href]'):
        link = urljoin(url, a['href'])
        if '/calendar/day/' in link and a.get_text(' ', strip=True).startswith('See all'):
            day = date.fromisoformat(link.rsplit('/', 1)[1])
            if now.astimezone(ZoneInfo(ZONE)).date() <= day < (now+timedelta(days=DAYS)).date():
                following.append(link)
        elif '/calendar/month/' in link and ('»' in a.get_text()):
            month = date.fromisoformat(link.rsplit('/', 1)[1] + '-01')
            if now.astimezone(ZoneInfo(ZONE)).date().replace(day=1) < month <= (now+timedelta(days=DAYS)).date():
                following.append(link)
    items = []
    for card in soup.select('.calendar .contents'):
        a = card.select_one('a[href^="/classes/"]')
        start_node = card.select_one('.date-display-start[content], .date-display-single[content]')
        end_node = card.select_one('.date-display-end[content]')
        if not a:
            continue
        availability = card.select_one('.views-field-class-available')
        if UNAVAILABLE.search(card.get_text(' ', strip=True)) or availability and re.fullmatch(r'Full', availability.get_text(' ', strip=True)):
            continue
        if not start_node:
            raise ValueError(PREFIX + 'schedule_unresolved')
        start, end = timestamp(start_node['content']), timestamp(end_node['content']) if end_node else None
        if not start or start.tzinfo is None or end and end-start > timedelta(days=1):
            raise ValueError(PREFIX + 'schedule_unresolved')
        if not shared._within(start, end, now, DAYS):
            continue
        sessions = [dict(start=start.isoformat(), end=end.isoformat() if end else None)]
        items.append(_item(ELIOT, urljoin(url, a['href']), a.get_text(' ', strip=True), sessions=sessions))
    return _merge(items), sorted(set(following))


def _eliot_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    title = soup.select_one('h1')
    course = soup.select_one('.view-classes-courses-tabs-view.view-display-id-block_1')
    location = soup.select_one('.field-name-field-location .field-item')
    if not title or plain(title.get_text()) != item['title'] or not course:
        raise ValueError(PREFIX + 'identity_changed')
    if not location:
        raise ValueError(PREFIX + 'street_unresolved')
    location_text = location.get_text(' ', strip=True)
    if re.search(r'253 Amory St', location_text):
        venue = 1
    elif re.search(r'24 Eliot St', location_text):
        venue = 0
    elif re.search(r'Boston Building Resources, 100 Terrace St(?:reet)?, Boston, MA 02120', location_text):
        venue = 2
    else:
        raise ValueError(PREFIX + 'street_unresolved')
    materials = soup.select_one('.view-classes-courses-tabs-view.view-display-id-block_3')
    instructor = soup.select_one('.view-instructors.view-display-id-class_quicktab')
    body = shared._body('\n'.join(str(n) for n in (course, instructor, materials) if n))
    if REMOTE.search(location_text) or UNAVAILABLE.search(item['title']):
        raise ValueError(PREFIX + 'not_public')
    observed = dict(item, native_options={'location_text': plain(location_text)})
    return _unique([_row(ELIOT, observed, body, timestamp(v['start']), timestamp(v['end']), venue_index=venue)
                    for v in item['sessions'] if shared._within(timestamp(v['start']), timestamp(v['end']), now, DAYS)])


def _bac(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    if '86 Monmouth Street, Brookline, MA 02446' not in soup.get_text(' ', strip=True):
        raise ValueError(PREFIX + 'street_unresolved')
    captions = [n for n in soup.select('figcaption.caption') if n.select('.class-listing') and re.search(r'\bDate:', n.get_text())]
    if not captions:
        raise ValueError(PREFIX + 'listing_changed')
    years = sorted(set(int(v) for v in re.findall(r'\b20\d{2}\b', soup.get_text())))
    rows = []
    for n in captions:
        text = plain(n.get_text(' ', strip=True))
        title = re.split(r'\b(?:Ages|Date):', text, maxsplit=1)[0].strip()
        if not title or UNAVAILABLE.search(title):
            continue
        dates = re.search(r'\bDate:\s*(.*?)\s*Time:', text)
        times = re.search(r'\bTime:\s*(.*?)\s*(?:Ages:|Instructor:|Workshop Fee:)', text)
        registration = [a for a in n.select('a[href]') if a.get_text(' ', strip=True).startswith('Register')]
        if not dates or not times or not registration:
            shared._held(BAC, title, PREFIX + 'schedule_unresolved')
            continue
        for link in registration:
            q = parse_qs(urlsplit(link['href']).query)
            native_id = q.get('session', [''])[0]
            if not native_id.isdigit():
                raise ValueError(PREFIX + 'identity_changed')
            item = _item(BAC, SOURCES[BAC][0], title)
            item['id'] = BAC + ':session:' + native_id
            native_dates = link.get_text(' ', strip=True) if dates[1].startswith('Multiple') else dates[1]
            candidates = re.findall(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+[A-Za-z]+\s+\d{1,2}(?:,?\s+20\d{2})?|[A-Z][a-z]{2}\s+\d{1,2}(?:,?\s+20\d{2})?', native_dates)
            for value in candidates:
                try:
                    possible = [_day(value)] if re.search(r'\b20\d{2}\b', value) else [_day(value, y) for y in years if _day_without_weekday(value, y)]
                    possible = [d for d in possible if now.astimezone(ZoneInfo(ZONE)).date() <= d < (now+timedelta(days=DAYS)).date()]
                    if not possible:
                        continue
                    if len(possible) != 1:
                        raise ValueError(PREFIX + 'schedule_unresolved')
                    override = re.search(r'\((\d[^)]*[ap]m)\)', link.get_text(' ', strip=True))
                    start, end = _times(possible[0], override[1] if override else times[1])
                    if shared._within(start, end, now, DAYS):
                        rows.append(_row(BAC, item, str(n), start, end))
                except ValueError as exc:
                    if str(exc) not in HOLD_REASONS:
                        raise
                    shared._held(BAC, native_id, str(exc))
    return _unique(rows)


def _day_without_weekday(value, year):
    try:
        _day(value, year)
        return True
    except ValueError:
        return False


def _aquarium(fetch, now, deadline):
    # The native calendar redirects individual entries to the curated program
    # page. Availability is supplied there, not by TEC's minimal description.
    availability, visited = {}, set()
    url = SOURCES[AQUARIUM][0]
    while url:
        shared._check(deadline)
        if url in visited or len(visited) >= 5:
            raise ValueError(PREFIX + 'pagination_changed')
        visited.add(url)
        soup = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        if not soup.h1 or plain(soup.h1.get_text()) != 'Events and Programs':
            raise ValueError(PREFIX + 'listing_changed')
        for card in soup.select('.tribe-events-pro-photo__event, .tribe-events-calendar-list__event'):
            title = card.select_one('.tribe-events-pro-photo__event-title, .tribe-events-calendar-list__event-title')
            day = card.select_one('time[datetime]')
            if not title or not day or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', day['datetime']):
                raise ValueError(PREFIX + 'identity_changed')
            identity = (plain(title.get_text()), day['datetime'])
            status = not bool(re.search(r'\bSOLD OUT\b', card.get_text(' ', strip=True), re.I))
            if identity in availability and availability[identity] != status:
                raise ValueError(PREFIX + 'identity_changed')
            availability[identity] = status
        following = soup.select('a.tribe-events-c-nav__next[href]')
        if len(following) > 1:
            raise ValueError(PREFIX + 'pagination_changed')
        url = urljoin(url, following[0]['href']) if following else None
        if url:
            p = urlsplit(url)
            q = parse_qs(p.query)
            if (p.scheme != 'https' or p.netloc != ALLOWED_HOSTS[AQUARIUM][0] or p.fragment
                    or not re.fullmatch(r'/events/photo/(?:page/[2-5]/)?', p.path)
                    or q.get('pagename') != ['engage/events-and-programs']
                    or q.get('eventDisplay') == ['past']):
                raise ValueError(PREFIX + 'pagination_changed')
    rows = []
    for page in range(1, 6):
        shared._check(deadline)
        query = urlencode(dict(per_page=100, page=page, start_date=now.astimezone(ZoneInfo(ZONE)).date().isoformat(), end_date=(now+timedelta(days=DAYS)).date().isoformat()))
        data = json.loads(fetch('https://www.neaq.org/wp-json/tribe/events/v1/events?' + query, 'application/json'))
        events = data.get('events')
        if (not isinstance(events, list) or type(data.get('total')) is not int or not 0 <= data['total'] <= 500
                or type(data.get('total_pages')) is not int or data['total_pages'] != (data['total']+99)//100
                or len(events) != min(100, max(0, data['total']-(page-1)*100))):
            raise ValueError(PREFIX + 'pagination_changed')
        for event in events:
            title = plain(event.get('title'))
            categories = [plain(v.get('name')) for v in event.get('categories', [])]
            if (UNAVAILABLE.search(title) or title.startswith('Member ')
                    or any(v.lower() in {'members', 'members only', 'private events'} for v in categories)
                    or event.get('status') != 'publish'
                    or event.get('event_status') in ('cancelled', 'canceled', 'postponed')
                    or any(event.get(k) in (True, 1, '1', 'true') for k in ('hide_from_listings', 'is_virtual', 'virtual', 'all_day'))):
                continue
            calendar_identity = (title, (event.get('start_date') or '')[:10])
            if calendar_identity not in availability:
                raise ValueError(PREFIX + 'pagination_changed')
            if not availability[calendar_identity]:
                continue
            item = _item(AQUARIUM, event.get('url'), title)
            item['id'] = AQUARIUM + ':' + str(event['id'])
            start, end = timestamp(event.get('start_date'), ZONE), timestamp(event.get('end_date'), ZONE)
            if event.get('timezone') != ZONE or start != timestamp(event.get('utc_start_date'), 'UTC') or end != timestamp(event.get('utc_end_date'), 'UTC'):
                raise ValueError(PREFIX + 'schedule_unresolved')
            venue = event.get('venue') or {}
            if (venue.get('address'), venue.get('city'), venue.get('state'), venue.get('zip')) != ('1 Central Wharf', 'Boston', 'MA', '02110'):
                raise ValueError(PREFIX + 'street_unresolved')
            item['native_options'] = {'location_text': ', '.join(
                str(venue[name]) for name in ('address', 'city', 'state', 'zip'))}
            if shared._within(start, end, now, DAYS):
                rows.append(_row(AQUARIUM, item, event.get('description'), start, end))
        if page >= data['total_pages']:
            return _unique(rows)
    raise ValueError(PREFIX + 'pagination_changed')


def _checkpoint(value, key, now):
    if value is None:
        return None
    # The concurrent release used this same manifest/pagination schema before
    # result proofs existed. An unprocessed checkpoint has nothing to re-attest:
    # preserve its native listing progress, then run every normal validation.
    # Processed legacy rows must be cleared through the targeted deployment fix.
    if (isinstance(value, dict) and 'outcomes' not in value and 'outcome_hash' not in value
            and type(value.get('cursor')) is int and value['cursor'] == 0
            and value.get('events') == [] and value.get('diagnostics') == []):
        value = dict(deepcopy(value), outcomes=[], outcome_hash=_hash([]))
    try:
        started = timestamp(value['started_at'])
        queue = value['queue']
        valid = (value['version'] == 1 and type(value['version']) is int and value['source_key'] == key
                 and started.tzinfo is not None and value['window_start'] == started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                 and isinstance(queue, list) and len(queue) <= CHECKPOINT_MANIFEST_LIMITS.get(key, 200)
                 and type(value['manifest_count']) is int and value['manifest_count'] == len(queue) and value['manifest_hash'] == _hash(queue)
                 and type(value['cursor']) is int and 0 <= value['cursor'] <= len(queue)
                 and len({v['url'] for v in queue}) == len(queue)
                 and all(event_url(key, v['url']) and isinstance(v['title'], str) and 0 < len(v['title']) <= 500
                         and v['id'] == _item(key, v['url'], v['title'])['id'] and isinstance(v['sessions'], list) for v in queue)
                 and isinstance(value['pending_pages'], list) and len(value['pending_pages']) <= MAX_LIST_PAGES
                 and isinstance(value['listed_pages'], list) and len(value['listed_pages']) <= MAX_LIST_PAGES
                 and len(set(value['listed_pages'])) == len(value['listed_pages'])
                 and all(_listing_url(key, u) for u in value['pending_pages'] + value['listed_pages'])
                 and type(value['listing_complete']) is bool and value['listing_complete'] == (not value['pending_pages'])
                 and (value['listing_complete'] or value['cursor'] == 0 and not value['events'])
                 and isinstance(value['events'], list) and len(value['events']) <= CHECKPOINT_EVENT_LIMITS.get(key, 201)
                 and isinstance(value['diagnostics'], list) and len(value['diagnostics']) <= 400
                 and isinstance(value['outcomes'], list) and len(value['outcomes']) == value['cursor']
                 and value['outcome_hash'] == _hash(value['outcomes'])
                 and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        if key in {MOS, DECORDOVA}:
            native_pages = [u for u in value['listed_pages'] if key == DECORDOVA or '/api/' in u]
            total = value['native_total']
            valid = (valid and value['native_pages'] == native_pages
                     and isinstance(value['native_seen'], list) and len(value['native_seen']) <= 500
                     and len(set(value['native_seen'])) == len(value['native_seen'])
                     and all(event_url(key, u) for u in value['native_seen'])
                     and (total is None and not native_pages and not value['native_seen']
                          or type(total) is int and 0 <= total <= 500
                          and len(value['native_seen']) == min(total, len(native_pages)*(18 if key == MOS else 16)))
                     and (not value['listing_complete'] or type(total) is int and len(value['native_seen']) == total
                          and len(native_pages) == max(1, (total+(17 if key == MOS else 15))//(18 if key == MOS else 16))))
        else:
            valid = valid and value['native_total'] is None and value['native_seen'] == [] and value['native_pages'] == []
        for item in queue:
            for session in item['sessions']:
                a, b = timestamp(session['start']), timestamp(session.get('end'))
                valid = (valid and a.tzinfo is not None and (b is None or b.tzinfo is not None and b > a)
                         and (a < started+timedelta(days=DAYS) if key == PEM else shared._within(a, b, started, DAYS)))
        processed = {v['url']: v for v in queue[:value['cursor']]}
        proofs, expected_diagnostics = {}, []
        for item, outcome in zip(queue[:value['cursor']], value['outcomes']):
            valid = (valid and outcome['event_url'] == item['url'] and isinstance(outcome['rows'], list)
                     and (outcome['rows'] and outcome['reason'] is None
                          or not outcome['rows'] and outcome['reason'] in HOLD_REASONS))
            if outcome['reason'] is not None:
                expected_diagnostics.append(dict(event_url=item['url'], disposition='held', reason=outcome['reason']))
            for proof in outcome['rows']:
                identity = (proof['id'], proof['starts_at'])
                valid = valid and identity not in proofs
                proofs[identity] = (item['url'], proof)
        valid = valid and len(proofs) == len(value['events']) and expected_diagnostics == value['diagnostics']
        identities = set()
        for row in value['events']:
            item = processed.get(row['event_url'])
            identity = (row['id'], row['starts_at'])
            a, b = timestamp(row['starts_at']), timestamp(row.get('ends_at'))
            venues = [v for v in VENUES[key] if row['venue_address'] == v[1] and
                      (row['venue_name'] == v[0] or key == COOLIDGE and row['venue_name'].startswith(v[0] + ' — '))]
            municipal_point = _reviewed_municipal_point(key, row['venue_name'], row['venue_address'])
            expected_point = municipal_point or (venues[0][3] if len(venues) == 1 else None)
            bound = proofs.get(identity)
            valid = (valid and item is not None and row['id'].startswith(item['id'] + ':') and identity not in identities
                     and bound is not None and bound[0] == row['event_url']
                     and bound[1]['ends_at'] == row.get('ends_at')
                     and bound[1]['description_sha256'] == sha256(row['description'].encode()).hexdigest()
                     and bound[1]['row_sha256'] == _hash(row)
                     and isinstance(row['description'], str) and 0 < len(row['description']) <= MAX_DESCRIPTION
                     and _content_envelope_valid(row)
                     and len(venues) == 1 and row.get('timezone') == ZONE and row.get('attendance_mode') == 'in_person'
                     and (row.get('lat'), row.get('lng')) == (expected_point or (None, None))
                     and row.get('location_provenance') == ('reviewed_municipal_exact_address_point' if municipal_point else
                         'publisher_venue_coordinates' if expected_point else
                         'publisher_class_street_neighborhood_zip_resolution' if key == ELIOT and venues[0][2] == 'Jamaica Plain' else 'publisher_venue_street_pending_geocode')
                     and (not municipal_point or row.get('location_evidence_url') == ELIOT_BBR_EVIDENCE)
                     and a.tzinfo is not None and (b is None or b.tzinfo is not None and b > a)
                     and shared._within(a, b, started, DAYS))
            if item is not None:
                suffix = row['id'][len(item['id'])+1:]
                clocks = {a.isoformat(), a.astimezone(ZoneInfo(ZONE)).isoformat()}
                if key == COOLIDGE:
                    valid = valid and (suffix.isdigit() or any(re.fullmatch(
                        r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}:' + re.escape(clock), suffix)
                        for clock in clocks))
                else:
                    valid = valid and suffix in clocks
                if key in {HMSC, ELIOT}:
                    valid = valid and row['title'] == item['title']
            if key == ELIOT:
                valid = valid and any(timestamp(v['start']) == a and timestamp(v.get('end')) == b for v in item['sessions'])
            identities.add(identity)
        for d in value['diagnostics']:
            valid = valid and d['event_url'] in processed and d['disposition'] == 'held' and d['reason'] in HOLD_REASONS
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, IndexError):
        valid = False
    if not valid:
        raise ValueError(PREFIX + 'checkpoint_invalid')
    if not started <= now <= started + timedelta(hours=4):
        return None
    return deepcopy(value)


def _listing(key, payload, url, now):
    if key == MOS:
        return _mos_listing(payload, url, now)
    if key == COOLIDGE:
        return _coolidge_listing(payload, url, now)
    if key == ELIOT:
        return _eliot_listing(payload, url, now)
    if key == HMSC:
        return _hmsc_listing(payload)
    if key == PEM:
        return _pem_listing(payload, now)
    return _trust_listing(payload, url)


def _detail(key, item, payload, now):
    return {MOS: _mos_detail, COOLIDGE: _coolidge_detail, ELIOT: _eliot_detail,
            HMSC: _hmsc_detail, PEM: _pem_detail, DECORDOVA: _trust_detail}[key](item, payload, now)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=DETAILS_PER_CHUNK):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError('publisher_checkpoint_required')
    current = now or datetime.now(timezone.utc)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    state = _checkpoint(checkpoint, key, current)
    legacy_prefix = bool(state and state['events'] and
                         any('collector_event_content_v1' not in row for row in state['events']))
    if state is None:
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=_hash([]), manifest_count=0, cursor=0, queue=[], events=[], diagnostics=[],
                     pending_pages=[SOURCES[key][0]], listed_pages=[], listing_complete=False,
                     native_total=None, native_seen=[], native_pages=[], outcomes=[], outcome_hash=_hash([]))
    if not state['listing_complete']:
        before = len(state['listed_pages'])
        for _ in range(PAGES_PER_CHUNK):
            if not state['pending_pages'] or monotonic() + 12 >= deadline:
                break
            if len(state['listed_pages']) >= MAX_LIST_PAGES:
                raise ValueError(PREFIX + 'pagination_changed')
            url = state['pending_pages'][0]
            if not _listing_url(key, url) or url in state['listed_pages']:
                raise ValueError(PREFIX + 'pagination_changed')
            payload = fetch(url, 'application/json' if '/api/' in url else 'text/html')
            items, following = _listing(key, payload, url, timestamp(state['started_at']))
            _record_native_page(state, key, payload, url)
            if any(not _listing_url(key, u) for u in following):
                raise ValueError(PREFIX + 'pagination_changed')
            state['queue'] = _merge(state['queue'] + items)
            if len(state['queue']) > CHECKPOINT_MANIFEST_LIMITS.get(key, 200):
                raise ValueError(PREFIX + 'manifest_limit')
            state['listed_pages'].append(url)
            state['pending_pages'] = list(dict.fromkeys(state['pending_pages'][1:] + [u for u in following if u not in state['listed_pages']]))
            state['listing_complete'] = not state['pending_pages']
            if (state['listing_complete'] and key in {MOS, DECORDOVA}
                    and (state['native_total'] is None or len(state['native_seen']) != state['native_total'])):
                raise ValueError(PREFIX + 'pagination_changed')
            state['manifest_count'], state['manifest_hash'] = len(state['queue']), _hash(state['queue'])
            if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
                raise ValueError(PREFIX + 'checkpoint_size_limit')
        if len(state['listed_pages']) == before:
            raise ValueError('collection_deadline')
        return dict(complete=state['listing_complete'] and not state['queue'], events=[], checkpoint=state)
    if state['cursor'] == state['manifest_count']:
        return dict(complete=True, events=deepcopy(state['events']), checkpoint=state)
    before = state['cursor']
    for _ in range(min(max_details, DETAILS_PER_CHUNK)):
        if state['cursor'] == state['manifest_count'] or monotonic() + 12 >= deadline:
            break
        item = state['queue'][state['cursor']]
        payload = fetch(item['url'], 'text/html')
        rows, reason = [], None
        try:
            rows = _detail(key, item, payload, timestamp(state['started_at']))
            if legacy_prefix:
                for row in rows:
                    row.pop('collector_event_content_v1', None)
            state['events'] = _unique(state['events'] + rows)
            if len(state['events']) > CHECKPOINT_EVENT_LIMITS.get(key, 201):
                raise ValueError(PREFIX + 'record_limit')
            if not rows:
                reason = PREFIX + 'not_current'
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            reason = str(exc)
        if reason is not None:
            state['diagnostics'].append(dict(event_url=item['url'], disposition='held', reason=reason))
        state['outcomes'].append(_outcome(item, rows, reason))
        state['outcome_hash'] = _hash(state['outcomes'])
        state['cursor'] += 1
    if before == state['cursor']:
        raise ValueError('collection_deadline')
    if len(state['diagnostics']) > 400 or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError(PREFIX + 'checkpoint_size_limit')
    complete = state['cursor'] == state['manifest_count']
    return dict(complete=complete, events=deepcopy(state['events']) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    if key in CHECKPOINT_KEYS:
        raise ValueError('publisher_checkpoint_required')
    current = now or datetime.now(timezone.utc)
    deadline = deadline_at if deadline_at is not None else monotonic()+35
    if key == BAC:
        return _bac(fetch(SOURCES[key][0], 'text/html'), current)
    return _aquarium(fetch, current, deadline)
