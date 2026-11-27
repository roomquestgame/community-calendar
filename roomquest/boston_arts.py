"""Boston public arts, makers, independent bookshops and library programs.

Reuse TEC, iCalendar, BiblioEvents and IndieCommerce's native event facts. Full
descriptions are kept through the 12k publication contract; summaries never stand
in for missing detail. Slow bookshop hosts use durable, complete-only snapshots.
"""
from __future__ import annotations

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

from roomquest.event_description import description
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp

ZONE = 'America/New_York'
PAO = 'pao_arts_center_ma'
SOWA = 'sowa_boston_ma'
MILL = 'mill_forge_makerspace_ma'
ARMORY = 'arts_at_the_armory_ma'
TRIDENT = 'trident_booksellers_ma'
BROOKLINE = 'brookline_booksmith_ma'
HARVARD = 'harvard_book_store_ma'
PORTER = 'porter_square_books_ma'
BPL = 'boston_public_library_biblioevents_ma'
SOURCES = {
    PAO: ('https://www.paoartscenter.org/events', 'html', 'html'),
    SOWA: ('https://www.sowaboston.com/events/', 'html', 'html'),
    MILL: ('https://millforge.org/events/', 'html', 'html'),
    ARMORY: ('https://artsatthearmory.org/events.ics', 'html', 'html'),
    TRIDENT: ('https://tridentbookscafe.com/events', 'html', 'html'),
    BROOKLINE: ('https://brooklinebooksmith.com/upcoming-events', 'html', 'html'),
    HARVARD: ('https://www.harvard.com/upcoming-events', 'html', 'html'),
    PORTER: ('https://portersquarebooks.com/events', 'html', 'html'),
    BPL: ('https://bpl.bibliocommons.com/v2/events', 'html', 'html'),
}
LABELS = {
    PAO: 'Pao Arts Center', SOWA: 'SoWa Boston', MILL: 'Mill Forge Makerspace',
    ARMORY: 'Arts at the Armory', TRIDENT: 'Trident Booksellers & Cafe',
    BROOKLINE: 'Brookline Booksmith', HARVARD: 'Harvard Book Store',
    PORTER: 'Porter Square Books', BPL: 'Boston Public Library',
}
SOURCE_NOTES = {
    BPL: 'Complete rolling 7-day window of physical branch/offsite events; native gateway date filters are ignored upstream.',
    PAO: 'Permitted public HTML and full detail bodies; no robots-disallowed Squarespace JSON or ICS export.',
    ARMORY: 'Native ICS descriptions; reviewed Cafe/Performance Hall categories identify onsite rooms at 191 Highland Avenue.',
    SOWA: 'TEC First Friday calendar; Christmas Market lives on a separate seasonal page and is not inferred into this feed.',
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
ALLOWED_HOSTS[BPL] += ('gateway.bibliocommons.com',)
BOOKS = {TRIDENT, BROOKLINE, HARVARD, PORTER}
CHECKPOINT_KEYS = BOOKS | {PAO, BPL}
CHECKPOINT_EVENT_LIMITS = {BPL: 500}
BPL_PAGES_PER_CHUNK = 6
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
MAX_MANIFEST = 200
MAX_CHECKPOINT_BYTES = 900000
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|closed|closure|private (?:event|party)|members?[- ]only)\b', re.I)
REMOTE = re.compile(r'\b(?:virtual|webinar|online only)\b', re.I)
STREET = re.compile(r'^\d{1,6}(?:-\d{1,6})?\s+\S')
log = logging.getLogger(__name__)
HOLD_REASONS = {'boston_arts_description_missing', 'boston_arts_description_limit',
                'boston_arts_street_unresolved', 'boston_arts_schedule_unresolved', 'event_not_current'}


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
            source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('unregistered_boston_arts_source')
    return key


def _check(deadline):
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text or re.fullmatch(r'(?:details?|information)\s+(?:TBA|coming soon)[.!]?', text, re.I):
        raise ValueError('boston_arts_description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('boston_arts_description_limit')
    return text


def _address(street, city, state, postal):
    street = re.sub(r'\s*,\s*', ' ', plain(street)).strip()
    state = 'MA' if plain(state) in ('MA', 'Massachusetts') else plain(state)
    if not STREET.match(street) or not city or state != 'MA' or not re.fullmatch(r'\d{5}(?:-\d{4})?', str(postal or '')):
        raise ValueError('boston_arts_street_unresolved')
    return f'{street}, {plain(city)}, MA {postal}'


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.netloc != ALLOWED_HOSTS[key][0] or p.query or p.fragment
                or '..' in p.path.split('/') or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)):
            return False
        pattern = (r'/v2/events/[a-f0-9]{24}' if key == BPL else
                   r'/events/20\d{2}/[a-z0-9-]+' if key == PAO else
                   r'/event/(?:20\d{2}-\d{2}-\d{2}/)?[a-z0-9-]+/?' if key in BOOKS else
                   r'/events/[a-z0-9-]+/?' if key == ARMORY else
                   r'/event/[a-z0-9-]+(?:/20\d{2}-\d{2}-\d{2})?/?')
        return bool(re.fullmatch(pattern, p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.username or p.password or p.fragment or '..' in p.path.split('/'):
            return None
        if not re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I):
            return None
        if key == PAO:
            ok = p.netloc == 'images.squarespace-cdn.com' and p.path.startswith('/content/v1/5f1ee9f02f0eca0267084513/') and not p.query
        elif key in BOOKS:
            ok = p.netloc == ALLOWED_HOSTS[key][0] and p.path.startswith('/sites/default/files/') and set(parse_qs(p.query)) <= {'itok'}
        else:
            ok = p.netloc == ALLOWED_HOSTS[key][0] and p.path.startswith('/wp-content/uploads/') and not p.query
        return value if ok else None
    except ValueError:
        return None


def _within(start, end, now, days=60):
    return start < now + timedelta(days=days) and (end or start + timedelta(hours=3)) > now


def _finish(key, row, body, labels=(), image=None):
    if row is None:
        return None
    if not event_url(key, row.get('event_url')):
        raise ValueError('boston_arts_identity_changed')
    row.update(description=body, timezone=ZONE, attendance_mode='in_person',
               location_provenance='publisher_event_street_pending_geocode')
    if row.get('lat') is not None and row.get('lng') is not None:
        row['location_provenance'] = 'publisher_venue_coordinates'
    if labels:
        row['publisher_categories'] = list(dict.fromkeys(labels))
    native_image = photo_url(key, image)
    if native_image:
        row['image_url'] = native_image
    categories = sorted({plain(value) for value in labels if plain(value)}, key=str.casefold)
    return _attach_content(
        row, body=body, image=native_image,
        native_options={'publisher_categories': categories} if categories else None)


def _attach_content(row, *, body, image=None, native_options=None):
    """Retain event-owned publisher facts for the shared SQL fingerprint."""
    if row is None:
        return None
    start, end = timestamp(row.get('starts_at')), timestamp(row.get('ends_at'))
    facts = {
        'title': row.get('title'),
        'description': body,
        'is_all_day': False,
        'starts_at_utc': start.astimezone(timezone.utc).isoformat(),
        'ends_at_utc': end.astimezone(timezone.utc).isoformat() if end else None,
        'event_url': row.get('event_url'),
        'venue_name': row.get('venue_name'),
        'venue_address': row.get('venue_address'),
        'venue_city': row.get('venue_city'),
        'source_image_url': image,
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
    start, end = timestamp(row.get('starts_at')), timestamp(row.get('ends_at'))
    expected = {
        'title': row.get('title'),
        'description': row.get('description'),
        'is_all_day': False,
        'starts_at_utc': start.astimezone(timezone.utc).isoformat(),
        'event_url': row.get('event_url'),
    }
    if end is not None:
        expected['ends_at_utc'] = end.astimezone(timezone.utc).isoformat()
    return all(facts.get(name) == value for name, value in expected.items())


def _held(key, identity, reason):
    log.warning('boston_arts_event_held source=%s id=%s reason=%s', key, identity, reason)


def _unique(rows):
    unique = {}
    for row in rows:
        key = (row['id'], row['starts_at'])
        if key in unique and unique[key] != row:
            raise ValueError('boston_arts_conflicting_occurrence')
        unique[key] = row
    if len(unique) > MAX_RECORDS:
        raise ValueError('boston_arts_record_limit')
    return sorted(unique.values(), key=lambda row: (row['starts_at'], row['id']))


def _tribe(key, fetch, deadline, now):
    rows = []
    for page in range(1, 6):
        _check(deadline)
        query = urlencode(dict(per_page=100, page=page, start_date=now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                               end_date=(now + timedelta(days=60)).date().isoformat()))
        api = 'https://' + ALLOWED_HOSTS[key][0] + '/wp-json/tribe/events/v1/events?'
        data = json.loads(fetch(api + query, 'application/json'))
        if not isinstance(data, dict) or not isinstance(data.get('events'), list) or len(data['events']) > 100:
            raise ValueError('boston_arts_payload_changed')
        for native in data['events']:
            title = plain(native.get('title'))
            if (native.get('status') != 'publish' or native.get('all_day') or NONPUBLIC.search(title)
                    or REMOTE.search(title) or title == 'Pitch Us A Class!'):
                continue
            if native.get('timezone') != ZONE or not event_url(key, native.get('url')):
                raise ValueError('boston_arts_identity_changed')
            start, end = timestamp(native.get('start_date'), ZONE), timestamp(native.get('end_date'), ZONE)
            if not start or not end or end <= start:
                raise ValueError('boston_arts_schedule_unresolved')
            if start != timestamp(native.get('utc_start_date'), 'UTC') or end != timestamp(native.get('utc_end_date'), 'UTC'):
                raise ValueError('boston_arts_schedule_conflict')
            if not _within(start, end, now):
                continue
            try:
                body = _body(native.get('description'))
                venue = dict(native['venue']) if isinstance(native.get('venue'), dict) else {}
                if key == SOWA and not venue and title == 'First Friday':
                    # Official First Friday page links the SoWa artist studios;
                    # 450 Harrison is their published visitor entrance, not an office.
                    venue = dict(venue='SoWa Art + Design District (artist studios entrance)', address='450 Harrison Avenue',
                                 city='Boston', state='MA', zip='02118')
                complete = _address(venue.get('address'), venue.get('city'), venue.get('state') or venue.get('stateprovince'), venue.get('zip'))
                parsed = parse_tribe({'events': [dict(native, venue=venue)]}, strict_public=True)
                if not parsed:
                    continue
                row = parsed[0]
                row['venue_address'] = complete
                labels = [plain(c.get('name')) for c in native.get('categories', []) if isinstance(c, dict)]
                image = native.get('image') or {}
                rows.append(_finish(key, row, body, labels, image.get('url') if isinstance(image, dict) else None))
            except ValueError as exc:
                if str(exc) not in HOLD_REASONS:
                    raise
                _held(key, native.get('id'), str(exc))
        total = data.get('total_pages')
        if type(total) is not int or total < 0:
            raise ValueError('boston_arts_pagination_invalid')
        if page >= total and not data.get('next_rest_url'):
            return _unique(rows)
    raise ValueError('boston_arts_pagination_limit')


ARMORY_TRACKER = re.compile(r"\$\('#getTixButton'\)\.click\(function\(\)\s*\{\s*fbq\('track',\s*'Purchase',\s*\{currency:\s*\"USD\",\s*value:\s*0\.00\}\);\s*\}\);", re.S)


def _armory(payload, now):
    events = Calendar.from_ical(payload).walk('VEVENT')
    if len(events) > 500:
        raise ValueError('boston_arts_record_limit')
    rows = []
    for event in events:
        title, link, identity = plain(event.get('SUMMARY')), str(event.get('URL', '')), str(event.get('UID', ''))
        if NONPUBLIC.search(title) or REMOTE.search(title) or str(event.get('STATUS', '')).upper() == 'CANCELLED':
            continue
        if not event_url(ARMORY, link) or not re.fullmatch(r'\d+@artsatthearmory[.]org', identity):
            raise ValueError('boston_arts_identity_changed')
        if 'RRULE' in event or 'RDATE' in event or 'RECURRENCE-ID' in event:
            raise ValueError('boston_arts_ics_recurrence_changed')
        start = event.decoded('DTSTART')
        end = event.decoded('DTEND', None)
        if not isinstance(start, datetime) or start.tzinfo is None or not isinstance(end, datetime) or end.tzinfo is None or end < start:
            raise ValueError('boston_arts_schedule_unresolved')
        if end == start:
            end = None  # Publisher has supplied only a start, not a duration.
        if not _within(start, end, now):
            continue
        labels = [str(c) for c in event.get('CATEGORIES').cats] if event.get('CATEGORIES') else []
        rooms = set(labels) & {'Cafe', 'Performance Hall'}
        if len(rooms) != 1 or event.get('LOCATION'):
            _held(ARMORY, identity, 'boston_arts_street_unresolved')
            continue
        raw = ARMORY_TRACKER.sub('', str(event.get('DESCRIPTION', '')))
        if re.search(r'\$\(|\bfunction\s*\(|\bdocument\.', raw):
            raise ValueError('boston_arts_ics_description_changed')
        try:
            body = _body(raw)
        except ValueError as exc:
            _held(ARMORY, identity, str(exc))
            continue
        room = 'ROOTED Armory Cafe' if 'Cafe' in rooms else 'Arts at the Armory Performance Hall'
        row = record(title, start.isoformat(), end.isoformat() if end else None, room, '191 Highland Avenue, Somerville, MA 02143',
                     'Somerville', link, identity, tz=ZONE, retain_until_end=True)
        attachment = event.get('ATTACH')
        if isinstance(attachment, list):
            attachment = attachment[0] if attachment else None
        row = _finish(ARMORY, row, body, labels, str(attachment) if attachment else None)
        if row:
            rows.append(row)
    return _unique(rows)


def _bpl_page(payload, now):
    """Map one native gateway page, retaining every eligible full description."""
    from roomquest.biblioevents import page_rows
    data = json.loads(payload)
    parsed = page_rows(payload, ZONE)
    rows, diagnostics = [], []
    types = data.get('entities', {}).get('eventTypes', {})
    for identity, item, definition, locations, start in parsed:
        end = timestamp(item.get('indexEnd') or definition.get('end'), ZONE)
        if not _within(start, end, now, days=7) or definition.get('isCancelled') is True:
            continue
        title = plain(definition.get('title'))
        if NONPUBLIC.search(title) or REMOTE.search(title) or str(definition.get('attendanceMode', '')).lower() in ('online', 'virtual'):
            continue
        location = locations.get(definition.get('nonBranchLocationId') or definition.get('branchLocationId'))
        if not isinstance(location, dict):
            continue  # Virtual listings have no physical location.
        link = SOURCES[BPL][0] + '/' + identity
        try:
            address = location.get('address') or {}
            street = plain(address.get('street'))
            # Chinatown puts its branch name in `number` and a complete street
            # in `street`. Do not prepend that label to 2 Boylston Street.
            if not STREET.match(street):
                street = ' '.join(plain(address.get(k)) for k in ('number', 'street') if address.get(k))
            complete = _address(street, address.get('city'), address.get('state'), address.get('zip'))
            body = _body(definition.get('description'))
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            diagnostics.append(dict(event_url=link, disposition='held', reason=str(exc)))
            continue
        venue = plain(location.get('name'))
        point = (location.get('mapLocation') or {}).get('centrePoint') or {}
        lat, lng = point.get('lat'), point.get('lng')
        if not (isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and 41.9 < lat < 42.6 and -71.5 < lng < -70.7):
            lat = lng = None
        row = record(title, start.isoformat(), end.isoformat() if end else None, venue, complete, address.get('city'),
                     link, identity, lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
        labels = [plain(types[k].get('name')) for k in definition.get('typeIds', []) if isinstance(types.get(k), dict)]
        row = _finish(BPL, row, body, labels)
        if row:
            rows.append(row)
    return rows, diagnostics, data['events'].get('pagination', {})


def _bpl_url(page):
    # The publisher's own getCalloutFeaturedEvent/getEvents client uses this
    # exact sort. The unqualified collection has unstable shard ordering and
    # can repeat some IDs while omitting others across a complete page walk.
    return 'https://gateway.bibliocommons.com/v2/libraries/bpl/events?' + urlencode(
        dict(limit=100, page=page, sort='definition.start asc'))


def _bpl_checkpoint(value, now):
    if value is None:
        return None
    try:
        started = timestamp(value['started_at'])
        queue = value['queue']
        native_ids = value['seen_ids']
        valid = (type(value['version']) is int and value['version'] == 1 and value['source_key'] == BPL
                 and type(value['cursor']) is int and type(value['manifest_count']) is int
                 and 0 <= value['cursor'] <= value['manifest_count'] <= 100
                 and isinstance(queue, list) and len(queue) == value['manifest_count']
                 and queue == [dict(page=i, url=_bpl_url(i)) for i in range(1, len(queue) + 1)]
                 and value['manifest_hash'] == _hash(queue)
                 and type(value['native_count']) is int and 0 <= value['native_count'] <= 10000
                 and isinstance(native_ids, list) and len(native_ids) <= value['native_count']
                 and len(native_ids) == len(set(native_ids))
                 and all(isinstance(identity, str) and re.fullmatch(r'[a-f0-9]{24}', identity) for identity in native_ids)
                 and (value['cursor'] != value['manifest_count'] or len(native_ids) == value['native_count'])
                 and isinstance(value['events'], list) and len(value['events']) <= MAX_RECORDS
                 and isinstance(value['diagnostics'], list) and len(value['diagnostics']) <= 400
                 and value['window_start'] == started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                 and started.tzinfo is not None and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        seen = set()
        for row in value['events']:
            start, end = timestamp(row['starts_at']), timestamp(row.get('ends_at'))
            valid = (valid and re.fullmatch(r'[a-f0-9]{24}', row['id']) is not None
                     and row['id'] not in seen and row['id'] in native_ids
                     and row['event_url'] == SOURCES[BPL][0] + '/' + row['id']
                     and isinstance(row['description'], str) and 0 < len(row['description']) <= MAX_DESCRIPTION
                     and bool(row.get('venue_name')) and bool(STREET.match(row.get('venue_address', '')))
                     and re.search(r', MA \d{5}(?:-\d{4})?$', row['venue_address']) is not None
                     and start.tzinfo is not None and (end is None or end.tzinfo is not None and end >= start)
                     and _within(start, end, started, days=7)
                     and row.get('timezone') == ZONE and row.get('attendance_mode') == 'in_person'
                     and _content_envelope_valid(row))
            seen.add(row['id'])
        for item in value['diagnostics']:
            valid = valid and event_url(BPL, item['event_url']) and item['disposition'] == 'held' and item['reason'] in HOLD_REASONS
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('boston_arts_checkpoint_invalid')
    if not started <= now <= started + timedelta(hours=4):
        return None
    return deepcopy(value)


def _bpl_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None):
    current = now or datetime.now(timezone.utc)
    state = _bpl_checkpoint(checkpoint, current)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    if state and state['cursor'] == state['manifest_count']:
        return dict(complete=True, events=_unique(deepcopy(state['events'])), checkpoint=state)
    if state is None:
        state = dict(version=1, source_key=BPL, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=_hash([]), manifest_count=0, cursor=0, queue=[], events=[], diagnostics=[],
                     native_count=None, seen_ids=[])
    prior = state['cursor']
    legacy_prefix = bool(state['events'] and
                         any('collector_event_content_v1' not in row for row in state['events']))
    # A source-specific ceiling, within the existing transport deadline and
    # twelve-second reserve. Native cardinality still gates the final snapshot.
    for _ in range(BPL_PAGES_PER_CHUNK):
        if monotonic() + 12 >= deadline:
            break
        page = state['cursor'] + 1
        payload = fetch(_bpl_url(page), 'application/json')
        rows, diagnostics, paging = _bpl_page(payload, timestamp(state['started_at']))
        if legacy_prefix:
            for row in rows:
                row.pop('collector_event_content_v1', None)
        native_ids = json.loads(payload)['events']['items']
        pages = paging.get('pages')
        count = paging.get('count')
        if (paging.get('page') != page or type(pages) is not int or not 1 <= pages <= 100
                or type(count) is not int or not 0 <= count <= 10000):
            raise ValueError('boston_arts_pagination_invalid')
        if state['manifest_count'] and (pages != state['manifest_count'] or count != state['native_count']):
            raise ValueError('boston_arts_manifest_changed')
        if not state['manifest_count']:
            state['queue'] = [dict(page=i, url=_bpl_url(i)) for i in range(1, pages + 1)]
            state['manifest_hash'], state['manifest_count'] = _hash(state['queue']), pages
            state['native_count'] = count
        seen = set(state['seen_ids'])
        if len(native_ids) != len(set(native_ids)) or seen.intersection(native_ids):
            raise ValueError('boston_arts_pagination_invalid')
        state['seen_ids'].extend(native_ids)
        if len(state['seen_ids']) > count or page == pages and len(state['seen_ids']) != count:
            raise ValueError('boston_arts_pagination_invalid')
        state['events'] = _unique(state['events'] + rows)
        state['diagnostics'].extend(diagnostics)
        state['cursor'] = page
        if page == pages:
            break
    if prior == state['cursor']:
        raise ValueError('collection_deadline')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('boston_arts_checkpoint_size_limit')
    complete = state['cursor'] == state['manifest_count']
    return dict(complete=complete, events=deepcopy(state['events']) if complete else [], checkpoint=state)


def _book_place(soup, key):
    location = soup.select_one('.event-details__location--location')
    rich = location.select_one('p.address') if location else None
    if rich:
        def part(cls):
            node = rich.select_one('.' + cls)
            return plain(node.get_text(' ')) if node else ''
        lines = [part('address-line1'), part('address-line2')]
        city, state, postal = part('locality'), part('administrative-area'), part('postal-code')
        index = next((i for i, value in enumerate(lines) if STREET.match(value)), None)
        if index is None:
            raise ValueError('boston_arts_street_unresolved')
        venue = ' '.join(lines[:index]) or LABELS[key]
        street = ' '.join(lines[index:]).strip()
    else:
        address = location.select_one('address') if location else None
        lines = [plain(line) for line in address.stripped_strings] if address else []
        index = next((i for i, value in enumerate(lines) if STREET.match(value)), None)
        cityline = next((re.fullmatch(r'([^,]+),\s*(MA|Massachusetts)\s+(\d{5}(?:-\d{4})?)', value) for value in reversed(lines)
                         if re.fullmatch(r'([^,]+),\s*(MA|Massachusetts)\s+(\d{5}(?:-\d{4})?)', value)), None)
        if index is None or cityline is None:
            raise ValueError('boston_arts_street_unresolved')
        venue, street = ' '.join(lines[:index]) or LABELS[key], lines[index]
        city, state, postal = cityline.groups()
    return dict(venue_name=venue, venue_address=_address(street, city, state, postal), venue_city=city)


def _book_listing(key, payload, page, now):
    soup = BeautifulSoup(payload, 'html.parser')
    view = soup.select_one('.view-indiecommerce-event-list')
    if not view:
        raise ValueError('boston_arts_listing_changed')
    queue = []
    for card in view.select('article.event-list'):
        link = card.select_one('.event-list__title a[href]')
        if not link or not re.fullmatch(r'event-\d+', card.get('id', '')):
            raise ValueError('boston_arts_identity_changed')
        url, title = urljoin(page, link['href']), plain(link.get_text(' '))
        if not event_url(key, url):
            raise ValueError('boston_arts_identity_changed')
        if NONPUBLIC.search(title) or REMOTE.search(title):
            continue
        dates = [plain(node.parent.get_text(' ')) for node in card.select('.event-list__details--label') if plain(node.get_text()).rstrip(':') == 'Date']
        if len(dates) != 1:
            raise ValueError('boston_arts_schedule_unresolved')
        days = re.findall(r'\b\d{1,2}/\d{1,2}/20\d{2}\b', dates[0])
        if len(days) != 1:
            _held(key, url, 'boston_arts_schedule_unresolved')
            continue
        day = datetime.strptime(days[0], '%m/%d/%Y').date()
        if not now.astimezone(ZoneInfo(ZONE)).date() <= day < (now + timedelta(days=60)).date():
            continue
        queue.append(dict(url=url, title=title, id=card['id'][6:], day=day.isoformat()))
    links = [urljoin(page, a['href']) for a in view.select('.pager a[rel~=next][href]')]
    if key in (TRIDENT, PORTER):
        links += [urljoin(page, a['href']) for a in soup.select('a[href]') if plain(a.get_text()).lower() == 'next month']
    links = list(dict.fromkeys(links))
    if len(links) > 1:
        raise ValueError('boston_arts_pagination_invalid')
    next_page = links[0] if links else None
    if next_page and key in (TRIDENT, PORTER):
        m = re.fullmatch(r'/events/(20\d{2})/(\d{1,2})', urlsplit(next_page).path)
        if not m:
            raise ValueError('boston_arts_pagination_invalid')
        if date(int(m[1]), int(m[2]), 1) >= (now + timedelta(days=60)).date():
            next_page = None
    if next_page and not _listing_url(key, next_page):
        raise ValueError('boston_arts_pagination_invalid')
    return queue, next_page


def _book_detail(key, item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    events = []
    for tag in soup.select('script[type="application/ld+json"]'):
        value = json.loads(tag.get_text())
        nodes = value.get('@graph', [value]) if isinstance(value, dict) else value
        events += [node for node in nodes if isinstance(node, dict) and node.get('@type') == 'Event']
    heading, contents = soup.select_one('h1.event-details__info--title'), soup.select('.event-details__info--body')
    if (len(events) != 1 or not heading or len(contents) != 1 or events[0].get('url') != item['url']
            or plain(events[0].get('name')) != item['title'] or plain(heading.get_text()) != item['title']):
        raise ValueError('boston_arts_identity_changed')
    native = events[0]
    if native.get('eventStatus') != 'https://schema.org/EventScheduled' or native.get('eventAttendanceMode') == 'https://schema.org/OnlineEventAttendanceMode':
        return None
    start, end = timestamp(native.get('startDate')), timestamp(native.get('endDate'))
    if not start or start.tzinfo is None or (end and (end.tzinfo is None or end <= start)):
        raise ValueError('boston_arts_schedule_unresolved')
    if start.astimezone(ZoneInfo(ZONE)).date().isoformat() != item['day']:
        raise ValueError('boston_arts_schedule_conflict')
    if not _within(start, end, now):
        return None
    place = _book_place(soup, key)
    body = _body(str(contents[0]))
    image = soup.select_one('.event-details__image img[src]')
    labels = [plain(a.get_text()) for a in soup.select('.event-details__info--tags .event-tag__term')]
    row = record(item['title'], start.isoformat(), end.isoformat() if end else None, place['venue_name'],
                 place['venue_address'], place['venue_city'], item['url'], item['id'], tz=ZONE, retain_until_end=True)
    return _finish(key, row, body, labels, urljoin(item['url'], image['src']) if image else None)


def _pao_schedule(node, prefix):
    link = node.select_one('.' + prefix + '-meta-export-google[href]')
    if not link:
        raise ValueError('boston_arts_schedule_unresolved')
    url = urlsplit(link['href'])
    values = parse_qs(url.query)
    if url.hostname != 'www.google.com' or values.get('action') != ['TEMPLATE']:
        raise ValueError('boston_arts_schedule_unresolved')
    try:
        start, end = [datetime.strptime(v, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc) for v in values['dates'][0].split('/')]
    except (KeyError, ValueError):
        raise ValueError('boston_arts_schedule_unresolved') from None
    if end <= start:
        raise ValueError('boston_arts_schedule_unresolved')
    return start, end


def _pao_listing(payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    cards = soup.select('article.eventlist-event')
    if not cards:
        raise ValueError('boston_arts_listing_changed')
    queue = []
    for card in cards:
        start, end = _pao_schedule(card, 'eventlist')
        if not _within(start, end, now):
            continue
        link = card.select_one('.eventlist-title-link[href]')
        if not link:
            raise ValueError('boston_arts_identity_changed')
        url, title = urljoin(SOURCES[PAO][0], link['href']), plain(link.get_text())
        if not event_url(PAO, url):
            raise ValueError('boston_arts_identity_changed')
        if NONPUBLIC.search(title) or REMOTE.search(title):
            continue
        queue.append(dict(url=url, title=title, id=urlsplit(url).path, day=start.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                          start=start.isoformat(), end=end.isoformat()))
    return queue, None


def _pao_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    title = soup.select_one('.eventitem-title')
    content = soup.select('.sqs-layout[id^="item-"]')
    canonical = soup.select_one('link[rel="canonical"][href]')
    if not title or plain(title.get_text()) != item['title'] or len(content) != 1 or not canonical or canonical['href'] != item['url']:
        raise ValueError('boston_arts_identity_changed')
    start, end = _pao_schedule(soup, 'eventitem')
    if start.isoformat() != item['start'] or end.isoformat() != item['end']:
        raise ValueError('boston_arts_schedule_conflict')
    if not _within(start, end, now):
        return None
    location = soup.select_one('.eventitem-meta-address')
    text = plain(location.get_text(' ')) if location else ''
    if not all(value in text for value in ('Pao Arts Center', '99 Albany Street', 'Boston', '02111')):
        raise ValueError('boston_arts_street_unresolved')
    body = _body(str(content[0]))
    row = record(item['title'], start.isoformat(), end.isoformat(), 'Pao Arts Center', '99 Albany Street, Boston, MA 02111',
                 'Boston', item['url'], item['id'], lat=42.3498258, lng=-71.0601878, tz=ZONE, retain_until_end=True)
    # Publisher's event location marker coordinates, checked against 99 Albany.
    image = content[0].select_one('img[data-src],img[src]')
    labels = [plain(n.get_text()) for n in soup.select('.eventitem-cats a')]
    return _finish(PAO, row, body, labels, (image.get('data-src') or image.get('src')) if image else None)


def _listing_url(key, value):
    if not isinstance(value, str):
        return False
    p, base = urlsplit(value), urlsplit(SOURCES[key][0])
    if p.scheme != 'https' or p.netloc != base.netloc or p.fragment:
        return False
    if value == SOURCES[key][0]:
        return True
    if key in (TRIDENT, PORTER):
        return not p.query and bool(re.fullmatch(r'/events/20\d{2}/(?:0?[1-9]|1[0-2])', p.path))
    return key in BOOKS and p.path == base.path and bool(re.fullmatch(r'page=[0-4]', p.query))


def _hash(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        valid = (isinstance(value, dict) and value['version'] == 1 and type(value['version']) is int
                 and value['source_key'] == key and type(value['cursor']) is int
                 and type(value['manifest_count']) is int and 0 <= value['cursor'] <= value['manifest_count'] <= MAX_MANIFEST
                 and isinstance(value['queue'], list) and len(value['queue']) == value['manifest_count']
                 and isinstance(value['events'], list) and isinstance(value['diagnostics'], list)
                 and len(value['events']) + len(value['diagnostics']) == value['cursor']
                 and type(value['listing_complete']) is bool and isinstance(value['listed_pages'], list)
                 and len(value['listed_pages']) <= 5 and len(set(value['listed_pages'])) == len(value['listed_pages'])
                 and all(_listing_url(key, url) for url in value['listed_pages'])
                 and (value['next_page'] is None if value['listing_complete'] else _listing_url(key, value['next_page']))
                 and value['manifest_hash'] == _hash(value['queue'])
                 and len({item['url'] for item in value['queue']}) == len(value['queue'])
                 and all(event_url(key, item['url']) and isinstance(item['title'], str) and item['title'].strip()
                         and isinstance(item['id'], str) and re.fullmatch(r'20\d{2}-\d{2}-\d{2}', item['day']) for item in value['queue'])
                 and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        started = timestamp(value['started_at'])
        valid = valid and started.tzinfo is not None and value['window_start'] == started.astimezone(ZoneInfo(ZONE)).date().isoformat()
        processed = {item['url']: item for item in value['queue'][:value['cursor']]}
        seen = set()
        for row in value['events']:
            item = processed.get(row.get('event_url'))
            valid = valid and bool(item) and row['event_url'] not in seen
            valid = valid and row.get('title') == item['title'] and row.get('id') == item['id']
            valid = valid and isinstance(row.get('description'), str) and 0 < len(row['description']) <= MAX_DESCRIPTION
            valid = valid and bool(STREET.match(row.get('venue_address', ''))) and bool(re.search(r', MA \d{5}(?:-\d{4})?$', row.get('venue_address', '')))
            valid = valid and row.get('timezone') == ZONE and row.get('attendance_mode') == 'in_person'
            valid = valid and (row.get('image_url') is None or photo_url(key, row['image_url']) is not None)
            valid = valid and _content_envelope_valid(row)
            seen.add(row['event_url'])
        for diagnostic in value['diagnostics']:
            url = diagnostic['event_url']
            valid = valid and url in processed and url not in seen and diagnostic['disposition'] == 'held' and diagnostic['reason'] in HOLD_REASONS
            seen.add(url)
        valid = valid and seen == set(processed)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('boston_arts_checkpoint_invalid')
    if not started <= now <= started + timedelta(hours=4):
        return None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=2):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError('publisher_checkpoint_required')
    current = now or datetime.now(timezone.utc)
    if key == BPL:
        return _bpl_chunk(source, fetch, checkpoint=checkpoint, deadline_at=deadline_at, now=current)
    state = _checkpoint(checkpoint, key, current)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    if state is None:
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=_hash([]), manifest_count=0, cursor=0, queue=[], events=[], diagnostics=[],
                     listing_complete=False, next_page=SOURCES[key][0], listed_pages=[])
    anchor = timestamp(state['started_at'])
    if not state['listing_complete']:
        _check(deadline)
        page = state['next_page']
        if page in state['listed_pages'] or len(state['listed_pages']) >= 5:
            raise ValueError('boston_arts_pagination_limit')
        payload = fetch(page, 'text/html')
        queue, next_page = _pao_listing(payload, anchor) if key == PAO else _book_listing(key, payload, page, anchor)
        existing = {item['url']: item for item in state['queue']}
        for item in queue:
            if item['url'] in existing and existing[item['url']] != item:
                raise ValueError('boston_arts_manifest_changed')
            existing[item['url']] = item
        state['queue'] = sorted(existing.values(), key=lambda item: (item['day'], item['url']))
        state['manifest_count'] = len(state['queue'])
        state['manifest_hash'] = _hash(state['queue'])
        state['listed_pages'].append(page)
        state['next_page'], state['listing_complete'] = next_page, next_page is None
        if state['manifest_count'] > MAX_MANIFEST:
            raise ValueError('boston_arts_manifest_limit')
        # A separate durable listing phase honors the bookshops' ten-second
        # crawl delay; snapshots never publish before every page is accounted for.
        return dict(complete=False, events=[], checkpoint=state)
    if state['cursor'] == state['manifest_count']:
        return dict(complete=True, events=_unique(deepcopy(state['events'])), checkpoint=state)
    prior = state['cursor']
    legacy_prefix = bool(state['events'] and
                         any('collector_event_content_v1' not in row for row in state['events']))
    maximum = min(2, max(1, int(max_details)))
    while state['cursor'] < state['manifest_count'] and state['cursor'] - prior < maximum:
        if monotonic() + 12 >= deadline:
            break
        item = state['queue'][state['cursor']]
        reason = 'event_not_current'
        try:
            payload = fetch(item['url'], 'text/html')
            row = _pao_detail(item, payload, anchor) if key == PAO else _book_detail(key, item, payload, anchor)
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            row, reason = None, str(exc)
        if row:
            if legacy_prefix:
                row.pop('collector_event_content_v1', None)
            state['events'].append(row)
        else:
            state['diagnostics'].append(dict(event_url=item['url'], disposition='held', reason=reason))
        state['cursor'] += 1
    if state['cursor'] == prior:
        raise ValueError('collection_deadline')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('boston_arts_checkpoint_size_limit')
    complete = state['cursor'] == state['manifest_count']
    return dict(complete=complete, events=_unique(deepcopy(state['events'])) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    if key in CHECKPOINT_KEYS:
        raise ValueError('publisher_checkpoint_required')
    current = now or datetime.now(timezone.utc)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    if key in (SOWA, MILL):
        return _tribe(key, fetch, deadline, current)
    if key == ARMORY:
        return _armory(fetch(SOURCES[key][0], 'text/calendar'), current)
    raise ValueError('unregistered_boston_arts_source')


ERROR_CODES = HOLD_REASONS | {
    'unregistered_boston_arts_source', 'boston_arts_identity_changed', 'boston_arts_payload_changed',
    'boston_arts_schedule_conflict', 'boston_arts_conflicting_occurrence', 'boston_arts_record_limit',
    'boston_arts_pagination_invalid', 'boston_arts_pagination_limit', 'boston_arts_ics_recurrence_changed',
    'boston_arts_ics_description_changed', 'boston_arts_listing_changed', 'boston_arts_checkpoint_invalid',
    'boston_arts_checkpoint_size_limit', 'boston_arts_manifest_limit', 'boston_arts_manifest_changed',
    'publisher_checkpoint_required', 'collection_deadline',
}
