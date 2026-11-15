"""Publisher-native Jalopy and Brooklyn Art Haus public performance calendars.

All network requests use the supplied guarded publisher transport. Complete
descriptions, dated occurrences and actual venues are verified before a bounded
checkpoint exposes any records. Inert page JSON is decoded, never executed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_cardboard_arena import _walk, _deref
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
JALOPY = 'jalopy_theatre_brooklyn_ny'
ART_HAUS = 'brooklyn_art_haus_brooklyn_ny'
SOURCES = {
    JALOPY: ('https://www.viewcy.com/api/o/jalopytheatre/courses', 'html', 'html'),
    ART_HAUS: ('https://www.eventbrite.com/o/brooklyn-art-haus-65148790433', 'html', 'html'),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900000
MAX_DETAILS = 2
CHECKPOINT_MANIFEST_LIMITS = {key: MAX_RECORDS for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: MAX_RECORDS for key in SOURCES}
ART_ORGANIZER = '65148790433'
ART_ORGANIZATION = '1528945046803'
ART_PAGE_SIZE = 12
JALOPY_OWNER = 'c19f3d74-97a7-4045-b785-c8f1aae1d07d'
UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'

# Native publisher event-specific address/geometry, corroborated against exact
# NYC PAD house/street/borough/ZIP points. The venue is not inferred from the
# organizer: Jalopy's offsite anniversary is explicitly at Gottscheer Hall.
VENUES = {
    'jalopy': ('Jalopy Theatre', '315 Columbia Street, Brooklyn, NY 11231',
               'Brooklyn', 40.68136, -74.00432),
    'jalopy_mic': ('Jalopy Theatre / Tavern (approximate meeting point)',
                   '315 Columbia Street, Brooklyn, NY 11231', 'Brooklyn', 40.68136, -74.00432),
    'jalopy_estimated': ('Jalopy Theatre (approximate venue address)',
                         '315 Columbia Street, Brooklyn, NY 11231', 'Brooklyn', 40.68136, -74.00432),
    'gottscheer': ('Gottscheer Hall', '6-57 Fairview Avenue, Ridgewood, NY 11385',
                  'Ridgewood', 40.706827, -73.9054957),
    'art_haus': ('Brooklyn Art Haus', '24 Marcy Avenue, Brooklyn, NY 11211',
                 'Brooklyn', 40.7134273, -73.9549377),
}
NONPUBLIC = re.compile(r'\b(?:cancell?ed|postponed|members[ -]only|private (?:event|lesson))\b', re.I)
HOLD_REASONS = {'event_not_public', 'event_not_current', 'description_missing',
                'description_limit', 'description_shape_changed', 'venue_unreviewed',
                'schedule_unresolved', 'schedule_not_finite', 'recurring_occurrences_unresolved'}
ERROR_CODES = {'nyc_performance_' + suffix for suffix in (
    'source_unregistered', 'identity_changed', 'schedule_changed', 'listing_changed',
    'manifest_incomplete', 'manifest_limit', 'record_limit', 'checkpoint_invalid',
    'checkpoint_size_limit', 'detail_changed', 'conflicting_occurrence',
)} | {'collection_deadline', 'publisher_checkpoint_required'}


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('nyc_performance_source_unregistered')
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        pattern = (r'/event/[a-z0-9_]{1,100}' if key == JALOPY
                   else r'/e/[a-z0-9-]+-tickets-[1-9]\d{9,15}')
        return (p.scheme == 'https' and p.netloc == ALLOWED_HOSTS[key][0]
                and not p.query and not p.fragment and re.fullmatch(pattern, p.path) is not None)
    except ValueError:
        return False


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError('description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('description_limit')
    return text


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _time(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value)):
        raise ValueError('nyc_performance_schedule_changed')
    result = timestamp(value)
    if result is None or result.tzinfo is None:
        raise ValueError('nyc_performance_schedule_changed')
    return result


def _within(start, end, now):
    return start < now + timedelta(days=60) and end > now


def _viewcy_models(payload):
    """The existing bounded Flight decoder with Viewcy's anonymous preload frame.

    Preserve UTF-8 byte-counted text frames, including full bodies and newlines.
    Only anonymous :HL JSON preload hints are additionally skipped; no JS runs.
    """
    if not isinstance(payload, str) or len(payload.encode()) > 2_000_000:
        raise ValueError('nyc_performance_detail_changed')
    decoder, chunks = json.JSONDecoder(), []
    for script in BeautifulSoup(payload, 'html.parser').find_all('script'):
        text = script.get_text()
        for match in re.finditer(r'self\.__next_f\.push\(', text):
            try:
                item, _ = decoder.raw_decode(text[match.end():])
            except (ValueError, TypeError):
                raise ValueError('nyc_performance_detail_changed') from None
            if isinstance(item, list) and len(item) == 2 and item[0] == 1 and isinstance(item[1], str):
                chunks.append(item[1])
    if not chunks:
        raise ValueError('nyc_performance_detail_changed')
    stream, models, cursor = ''.join(chunks).encode(), {}, 0
    try:
        while cursor < len(stream):
            if stream[cursor:cursor + 1] in (b'\n', b'\r'):
                cursor += 1
                continue
            if stream[cursor:cursor + 4] == b':HL[':
                remaining = stream[cursor + 3:].decode('utf-8', errors='strict')
                value, size = decoder.raw_decode(remaining)
                if not isinstance(value, list) or len(value) > 5:
                    raise ValueError
                cursor += 3 + len(remaining[:size].encode())
                continue
            marker = re.match(rb'([a-f0-9]+):', stream[cursor:])
            if not marker or len(models) > 10000:
                raise ValueError
            identity = marker[1].decode()
            cursor += marker.end()
            text_frame = re.match(rb'T([a-f0-9]+),', stream[cursor:])
            if text_frame:
                size = int(text_frame[1], 16)
                cursor += text_frame.end()
                if size > 2_000_000 or cursor + size > len(stream):
                    raise ValueError
                value = stream[cursor:cursor + size].decode('utf-8', errors='strict')
                cursor += size
            else:
                end = stream.find(b'\n', cursor)
                end = len(stream) if end < 0 else end
                line = stream[cursor:end]
                cursor = end + 1
                if not line[:1] or line[:1] not in b'{["ntf-0123456789':
                    continue
                value = json.loads(line)
            if identity in models and models[identity] != value:
                raise ValueError
            models[identity] = value
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('nyc_performance_detail_changed') from None
    return models


def _jalopy_manifest(payload, now):
    try:
        data = json.loads(payload)
        courses = data['data']
        if (data.get('object') != 'list' or data.get('has_more') is not False
                or type(data['total_count']) is not int or not isinstance(courses, list)
                or len(courses) != data['total_count'] or not 0 <= len(courses) <= MAX_RECORDS):
            raise ValueError
        queue, ids, urls = [], set(), set()
        for course in courses:
            identity, slug, url = course['id'], course['uuid'], course['url']
            title = plain(course['name'])
            if (type(identity) is not int or identity <= 0 or identity in ids or url in urls
                    or course.get('object') != 'course' or not event_url(JALOPY, url)
                    or url != 'https://www.viewcy.com/event/' + slug or course.get('timezone') != ZONE
                    or not title or len(title) > 180 or not isinstance(course['description'], str)
                    or not isinstance(course['events'], list) or len(course['events']) > 500):
                raise ValueError
            ids.add(identity); urls.add(url)
            occurrences, native_ids = [], set()
            for event in course['events']:
                native = event['uuid']
                start, end = _time(event['starts_at']), _time(event['ends_at'])
                if (not isinstance(native, str) or not re.fullmatch(UUID, native) or native in native_ids
                        or event.get('object') != 'event' or event.get('book_url') != url
                        or plain(event['name']) != title or end <= start):
                    raise ValueError
                native_ids.add(native)
                if _within(start, end, now) and end - start < timedelta(days=1):
                    occurrences.append(dict(id=native, starts_at=start.isoformat(), ends_at=end.isoformat()))
            if occurrences and not NONPUBLIC.search(title):
                queue.append(dict(id=str(identity), slug=slug, url=url, title=title,
                    body=course['description'], category_id=course['category_id'],
                    native_future_count=sum(_time(e['ends_at']) > now for e in course['events']),
                    occurrences=sorted(occurrences, key=lambda e: (e['starts_at'], e['id']))))
        return sorted(queue, key=lambda item: item['url']), data['total_count']
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('nyc_performance_manifest_incomplete') from None


def _jalopy_venue(native, item, body):
    location = native.get('location') or {}
    # This native page omits its structured location, but its full current
    # body explicitly names the Jalopy Theater in Brooklyn. The official
    # theatre's 315 Columbia address is a reviewed estimate, visibly marked.
    if (not location and item['slug'] == 'jay_braggs_christma'
            and sha256(body.encode()).hexdigest() == 'b5dee157092a9c21a64db8b7e878a1909a5204cc632e958738f5614ba497091a'):
        return 'jalopy_estimated'
    street = re.sub(r'[^a-z0-9-]', '', plain(location.get('address')).casefold())
    point = (location.get('latitude'), location.get('longitude'))
    common = (location.get('country') == 'US' and location.get('state') in {'New York', 'NY'})
    if (common and location.get('name') in {'Jalopy Theatre', 'The Jalopy Theatre & School of Music'}
            and street in {'315columbiast', '315columbiastreet'} and location.get('city') == 'Brooklyn'
            and location.get('zipcode') == '11231' and point == VENUES['jalopy'][3:]):
        if item['slug'] == 'jalopy_open_mic_eith':
            # The publisher itself lists this address but explicitly allows the
            # adjacent tavern. Never claim that its room is precisely known.
            expected = ('Signups at 6pm, begins at 6:30pm Names are drawn out of a hat at 6:30pm '
                        'and the performer is allowed one song or the total allotted time of four minutes. '
                        'If there is a conflicting performance in the theatre, the open mic will be held in the tavern.')
            if plain(body) != expected:
                raise ValueError('venue_unreviewed')
            return 'jalopy_mic'
        if re.search(r'\bOFFSITE\b', body, re.I):
            raise ValueError('venue_unreviewed')
        return 'jalopy'
    if (common and location.get('name') == 'Gottscheer Hall'
            and street in {'6-57fairviewave', '6-57fairviewavenue'}
            and location.get('city') == 'Ridgewood' and location.get('zipcode') == '11385'
            and point == VENUES['gottscheer'][3:]):
        return 'gottscheer'
    raise ValueError('venue_unreviewed')


def _row(key, item, native_id, start, end, body, place, labels):
    venue, street, city, lat, lng = VENUES[place]
    row = record(item['title'], start.isoformat(), end.isoformat(), venue, street,
                 city, item['url'], native_id, '; '.join(labels), lat, lng, ZONE,
                 publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                   publisher_native_id=native_id, publisher_categories=labels,
                   description_provenance='publisher_full_native_body',
                   location_provenance='publisher_event_venue_street_and_point')
        if place == 'jalopy_mic':
            row.update(location_is_approximate=True,
                       location_provenance='publisher_theatre_address_with_explicit_adjacent_tavern_option')
        elif place == 'jalopy_estimated':
            row.update(location_is_approximate=True,
                       location_provenance='reviewed_full_body_named_theatre_estimated_official_street_and_point')
    return row


def _jalopy_detail(item, payload, now):
    models = _viewcy_models(payload)
    matches = [value for value in _walk(models) if value.get('numericId') == int(item['id'])]
    if len(matches) != 1:
        raise ValueError('nyc_performance_identity_changed')
    native = matches[0]
    if (native.get('id') != item['slug'] or plain(native.get('name')) != item['title']
            or native.get('url') != '/event/' + item['slug']
            or (native.get('owner') or {}).get('id') != JALOPY_OWNER
            or (native.get('owner') or {}).get('username') != 'jalopytheatre'):
        raise ValueError('nyc_performance_identity_changed')
    if (native.get('published') is not True or native.get('status') != 'published'
            or native.get('canceled') is not False or native.get('visibility') != 'listed'
            or native.get('accessMode') != 'open' or native.get('hideAddressUntilPurchase') is not False
            or native.get('locationSetting') != 'physical'
            or native.get('attendanceModes') != ['in-person'] or NONPUBLIC.search(item['title'])):
        raise ValueError('event_not_public')
    body = _body(item['body'])
    try:
        native_body = _deref(native.get('description'), models)
    except ValueError:
        raise ValueError('nyc_performance_detail_changed') from None
    if _body(native_body) != body:
        raise ValueError('nyc_performance_detail_changed')
    begun = sum(_time(e['starts_at']) <= now for e in item['occurrences'])
    count = native.get('futureEventCount')
    if (native.get('timezone') != ZONE or type(count) is not int
            or not item['native_future_count'] - begun <= count <= item['native_future_count']):
        raise ValueError('nyc_performance_schedule_changed')
    next_event = native.get('nextEvent') or {}
    selected = {occurrence['id']: occurrence for occurrence in item['occurrences']}
    next_item = selected.get(next_event.get('id'))
    if next_item and (_time(next_event.get('startsAt')) != _time(next_item['starts_at'])
                      or _time(next_event.get('endsAt')) != _time(next_item['ends_at'])):
        raise ValueError('nyc_performance_schedule_changed')
    place = _jalopy_venue(native, item, body)
    labels = [plain(native.get('categoryName'))] if plain(native.get('categoryName')) else ['Live Music']
    rows = []
    for occurrence in item['occurrences']:
        start, end = _time(occurrence['starts_at']), _time(occurrence['ends_at'])
        if _within(start, end, now):
            row = _row(JALOPY, item, occurrence['id'], start, end, body, place, labels)
            if row:
                rows.append(row)
    return rows


def _art_page_url(page):
    if type(page) is not int or not 1 <= page <= 17:
        raise ValueError('nyc_performance_manifest_limit')
    return (SOURCES[ART_HAUS][0] if page == 1 else
            'https://www.eventbrite.com/organizer-profile/api/organizers/' + ART_ORGANIZER
            + '/events/?page=' + str(page) + '&pageSize=12')


def _art_page(payload, number):
    """The organizer's native Show more route, discovered in its linked JS."""
    try:
        if number == 1:
            soup = BeautifulSoup(payload, 'html.parser')
            data = json.loads(soup.select_one('script#__NEXT_DATA__').get_text())['props']['pageProps']
            organizer = data['organizer']
            if (organizer.get('id') != ART_ORGANIZER or organizer.get('name') != 'Brooklyn Art Haus'
                    or organizer.get('profilePageUrl') != SOURCES[ART_HAUS][0]
                    or data.get('upcomingEventsFailed') is not False):
                raise ValueError
            events, total, more = data['upcomingEvents'], data['upcomingEventsTotal'], data['hasMoreUpcoming']
        else:
            data = json.loads(payload)
            events, total, more = data['events'], data['total'], data['hasMore']
        expected = min(ART_PAGE_SIZE, max(0, total - (number - 1) * ART_PAGE_SIZE)) if type(total) is int else -1
        if (type(total) is not int or not 0 <= total <= MAX_RECORDS or type(more) is not bool
                or not isinstance(events, list) or len(events) != expected
                or more != (number * ART_PAGE_SIZE < total)):
            raise ValueError
        queue = []
        for event in events:
            identity, url, title = event['id'], event['url'], plain(event['name'])
            start = timestamp(event['start_date'] + 'T' + event['start_time'], ZONE)
            sessions = event['additionalSessionsCount']
            if (not isinstance(identity, str) or not re.fullmatch(r'[1-9]\d{9,15}', identity)
                    or not event_url(ART_HAUS, url) or not url.endswith('-' + identity)
                    or event.get('primary_organizer_id') != ART_ORGANIZER or event.get('timezone') != ZONE
                    or not start or not title or len(title) > 180
                    or type(sessions) is not int or not 0 <= sessions < MAX_RECORDS):
                raise ValueError
            unavailable = (event.get('is_online_event') is not False
                or event.get('is_cancelled') is not False or event.get('is_protected_event') is not False
                or event.get('hide_start_date') is not False or event.get('hide_end_date') is not False
                or ((event.get('ticket_availability') or {}).get('is_sold_out') is True and sessions == 0))
            queue.append(dict(id=identity, url=url, title=title, starts_at=start.isoformat(),
                              additional_sessions=sessions, unavailable=unavailable))
        if len({item['id'] for item in queue}) != len(queue):
            raise ValueError
        return queue, total, more
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('nyc_performance_manifest_incomplete') from None


def _art_body(context):
    structured = context.get('structuredContent')
    if (not isinstance(structured, dict) or not isinstance(structured.get('modules'), list)
            or not isinstance(structured.get('widgets'), dict)):
        raise ValueError('description_shape_changed')
    modules, widgets = structured['modules'], structured['widgets']
    if (any(not isinstance(module, dict) or module.get('type') != 'text'
            or not isinstance(module.get('text'), str) for module in modules)
            or set(widgets) - {'faqs', 'nativeVideo', 'parking', 'agenda', 'lineup'}
            or any(value for name, value in widgets.items() if name != 'parking')):
        raise ValueError('description_shape_changed')
    parking = widgets.get('parking')
    if parking is not None and parking != {'availability': 'free'}:
        raise ValueError('description_shape_changed')
    summary = str(context['basicInfo'].get('summary') or '')
    raw = '<p>' + summary + '</p>\n' + '\n'.join(module['text'] for module in modules)
    if parking:
        raw += '\n<p>Parking: free.</p>'
    body = _body(raw)
    if body.casefold() == context['basicInfo']['name'].casefold() or not modules and re.search(r'(?:\.\.\.|…)$', body):
        raise ValueError('description_missing')
    return body


def _art_context(item, payload):
    try:
        soup = BeautifulSoup(payload, 'html.parser')
        data = json.loads(soup.select_one('script#__NEXT_DATA__').get_text())['props']['pageProps']
        context, basic = data['context'], data['context']['basicInfo']
        if (data.get('error') or data.get('canonicalUrl') != item['url']
                or basic.get('id') != item['id'] or basic.get('url') != item['url']
                or plain(basic.get('name')) != item['title']
                or (basic.get('organizer') or {}).get('id') != ART_ORGANIZER
                or basic.get('organizationId') != ART_ORGANIZATION):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('nyc_performance_identity_changed') from None
    if (basic.get('status') not in {'live', 'started'} or basic.get('isOnline') is not False
            or basic.get('isProtected') is not False or basic.get('isListed') is not True
            or NONPUBLIC.search(item['title'])):
        raise ValueError('event_not_public')
    venue, address = basic.get('venue') or {}, (basic.get('venue') or {}).get('address') or {}
    lines = address.get('localizedMultiLineAddressDisplay')
    if (venue.get('name') != 'Brooklyn Art Haus' or not isinstance(lines, list) or len(lines) != 2
            or re.sub(r'[^a-z0-9]', '', plain(lines[0]).casefold()) not in {'24marcyave', '24marcyavenue'}
            or lines[1] != 'Brooklyn, NY 11211' or address.get('country') != 'US'
            or address.get('city') != 'Brooklyn' or address.get('region') != 'NY'):
        raise ValueError('venue_unreviewed')
    try:
        point = (float(address['latitude']), float(address['longitude']))
    except (ValueError, TypeError, KeyError):
        raise ValueError('venue_unreviewed') from None
    if point != VENUES['art_haus'][3:]:
        raise ValueError('venue_unreviewed')
    return context


def _art_detail(item, payload, now, fetch):
    context = _art_context(item, payload)
    basic = context['basicInfo']
    body = _art_body(context)
    if basic.get('isParentEvent') is True:
        # Parent start/end describe the full series range. A public finite
        # occurrence is required; the range must never be published as one.
        raise ValueError('recurring_occurrences_unresolved')
    try:
        start_data, end_data = basic['startDate'], basic['endDate']
        start, end = timestamp(start_data['local'], ZONE), timestamp(end_data['local'], ZONE)
        if (start_data.get('timezone') != ZONE or end_data.get('timezone') != ZONE
                or not start or not end or end <= start or end - start >= timedelta(days=1)
                or start != _time(item['starts_at']) or _time(start_data['utc']) != start
                or _time(end_data['utc']) != end or basic.get('hideStartDate') is not False
                or basic.get('hideEndDate') is not False or type(basic.get('isParentEvent')) is not bool):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError('schedule_unresolved') from None
    if not _within(start, end, now):
        return []
    labels = [label for label in (context.get('taxonomies') or {}).values() if isinstance(label, str)]
    row = _row(ART_HAUS, item, item['id'], start, end, body, 'art_haus', labels or ['Performing Arts'])
    if row:
        row.update(publisher_organizer_id=ART_ORGANIZER,
                   description_provenance='publisher_overview_all_structured_text_modules_and_parking')
    return [row] if row else []


def _unique(rows):
    result = {}
    for row in rows:
        marker = (row['id'], row['starts_at'])
        if marker in result and result[marker] != row:
            raise ValueError('nyc_performance_conflicting_occurrence')
        result[marker] = row
    if len(result) > MAX_RECORDS:
        raise ValueError('nyc_performance_record_limit')
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))


def _row_key(row):
    return row['id'] + '|' + row['starts_at']


def _seal(state):
    state.pop('integrity_hash', None)
    state['integrity_hash'] = _digest(state)
    return state


def _blank(key, now):
    return dict(version=1, source_key=key, started_at=now.isoformat(),
                window_start=now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                phase='manifest', queue=[], manifest_count=0, manifest_hash=_digest([]),
                catalog_total=None, next_page=1, page_hashes=[], verify_page=1,
                cursor=0, events=[], row_hashes={}, diagnostics=[], manifest_verified=False)


def _checkpoint(key, value, now):
    if value is None:
        return None
    try:
        if not isinstance(value, dict):
            raise ValueError
        state = deepcopy(value)
        seal = state.pop('integrity_hash')
        if seal != _digest(state):
            raise ValueError
        state['integrity_hash'] = seal
        if (type(state['version']) is not int or state['version'] != 1 or state['source_key'] != key
                or state['phase'] not in {'manifest', 'details', 'verify', 'complete'}
                or not isinstance(state['queue'], list) or type(state['manifest_count']) is not int
                or not 0 <= state['manifest_count'] == len(state['queue']) <= MAX_RECORDS
                or state['manifest_hash'] != _digest(state['queue'])
                or type(state['cursor']) is not int or not 0 <= state['cursor'] <= state['manifest_count']
                or type(state['next_page']) is not int or not 1 <= state['next_page'] <= 18
                or type(state['verify_page']) is not int or not 1 <= state['verify_page'] <= state['next_page']
                or not isinstance(state['page_hashes'], list) or len(state['page_hashes']) != state['next_page'] - 1
                or any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{64}', v) for v in state['page_hashes'])
                or (state['catalog_total'] is not None and
                    (type(state['catalog_total']) is not int or not 0 <= state['catalog_total'] <= MAX_RECORDS))
                or not isinstance(state['events'], list) or len(state['events']) > MAX_RECORDS
                or not isinstance(state['row_hashes'], dict) or len(state['row_hashes']) != len(state['events'])
                or not isinstance(state['diagnostics'], list) or len(state['diagnostics']) != state['cursor']
                or type(state['manifest_verified']) is not bool
                or state['manifest_verified'] != (state['phase'] == 'complete')
                or state['phase'] == 'manifest' and state['cursor'] != 0
                or state['phase'] in {'verify', 'complete'} and state['cursor'] != state['manifest_count']
                or state['phase'] == 'complete' and state['verify_page'] != state['next_page']
                or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
            raise ValueError
        started = _time(state['started_at'])
        if started.utcoffset() != timedelta(0) or state['window_start'] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        if not started <= now <= started + timedelta(hours=4):
            return None
        urls, identities = set(), set()
        for item in state['queue']:
            if (not isinstance(item, dict) or not isinstance(item['id'], str) or item['id'] in identities
                    or not event_url(key, item['url']) or item['url'] in urls
                    or not isinstance(item['title'], str) or not 0 < len(item['title']) <= 180):
                raise ValueError
            identities.add(item['id']); urls.add(item['url'])
            if key == JALOPY:
                if (not re.fullmatch(r'[1-9]\d{0,9}', item['id']) or not isinstance(item['body'], str)
                        or item['url'] != 'https://www.viewcy.com/event/' + item['slug']
                        or not isinstance(item['occurrences'], list) or not 1 <= len(item['occurrences']) <= MAX_RECORDS
                        or type(item['native_future_count']) is not int
                        or not len(item['occurrences']) <= item['native_future_count'] <= 500):
                    raise ValueError
                occurrence_ids = set()
                for occurrence in item['occurrences']:
                    start, end = _time(occurrence['starts_at']), _time(occurrence['ends_at'])
                    if (not re.fullmatch(UUID, occurrence['id']) or occurrence['id'] in occurrence_ids
                            or not timedelta(0) < end - start < timedelta(days=1) or not _within(start, end, started)):
                        raise ValueError
                    occurrence_ids.add(occurrence['id'])
            elif (not re.fullmatch(r'[1-9]\d{9,15}', item['id']) or not item['url'].endswith('-' + item['id'])
                    or type(item['additional_sessions']) is not int or not 0 <= item['additional_sessions'] < MAX_RECORDS
                    or type(item['unavailable']) is not bool or not _time(item['starts_at'])):
                raise ValueError
        if key == ART_HAUS and state['phase'] != 'manifest' and len(state['queue']) != state['catalog_total']:
            raise ValueError
        processed = {item['url']: item for item in state['queue'][:state['cursor']]}
        counts = {url: 0 for url in processed}
        valid_venues = {VENUES['art_haus']} if key == ART_HAUS else {v for k, v in VENUES.items() if k != 'art_haus'}
        hashes = {}
        for row in state['events']:
            item = processed.get(row.get('event_url')) if isinstance(row, dict) else None
            if (not item or row.get('title') != item['title'] or _body(row['description']) != row['description']
                    or row.get('timezone') != ZONE or row.get('attendance_mode') != 'in_person'
                    or row.get('id') != row.get('publisher_native_id')
                    or tuple(row.get(k) for k in ('venue_name', 'venue_address', 'venue_city', 'lat', 'lng')) not in valid_venues):
                raise ValueError
            start, end = _time(row['starts_at']), _time(row['ends_at'])
            if not timedelta(0) < end - start < timedelta(days=1) or not _within(start, end, started):
                raise ValueError
            if key == JALOPY and not any(o['id'] == row['id'] and _time(o['starts_at']) == start and _time(o['ends_at']) == end for o in item['occurrences']):
                raise ValueError
            if key == ART_HAUS and row.get('publisher_organizer_id') != ART_ORGANIZER:
                raise ValueError
            counts[item['url']] += 1
            hashes[_row_key(row)] = _digest(row)
        if hashes != state['row_hashes'] or len(_unique(state['events'])) != len(state['events']):
            raise ValueError
        decisions = set()
        for diagnostic in state['diagnostics']:
            url = diagnostic['event_url']
            if (url not in processed or url in decisions or type(diagnostic['event_count']) is not int
                    or diagnostic['event_count'] != counts[url]
                    or diagnostic['disposition'] != ('accepted' if counts[url] else 'held')
                    or not counts[url] and diagnostic['reason'] not in HOLD_REASONS):
                raise ValueError
            decisions.add(url)
        if decisions != set(processed):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError('nyc_performance_checkpoint_invalid') from None
    return state


def _result(state):
    if len(state['events']) > MAX_RECORDS:
        raise ValueError('nyc_performance_record_limit')
    _seal(state)
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('nyc_performance_checkpoint_size_limit')
    return dict(complete=state['manifest_verified'],
                events=deepcopy(_unique(state['events'])) if state['manifest_verified'] else [], checkpoint=state)


def _bounded(error):
    from roomquest.preview_worker import PreviewError
    return (isinstance(error, PreviewError) and str(error) in {'publisher_pacing_deferred', 'source_fetch_deadline'}
            or type(error) is ValueError and str(error) == 'collection_deadline')


def _check(deadline, reserve=12):
    if monotonic() + reserve >= deadline:
        raise ValueError('collection_deadline')


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source)
    raise ValueError('publisher_checkpoint_required')


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS):
    key = _source(source)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    if type(max_details) is not int or not 1 <= max_details <= MAX_DETAILS:
        raise ValueError('nyc_performance_record_limit')
    state = _checkpoint(key, checkpoint, current) or _blank(key, current)
    if state['manifest_verified']:
        return _result(state)
    started = _time(state['started_at'])
    try:
        if state['phase'] == 'manifest':
            _check(deadline)
            if key == JALOPY:
                queue, total = _jalopy_manifest(fetch(SOURCES[key][0], 'application/json'), started)
                state.update(queue=queue, catalog_total=total, next_page=2, page_hashes=[_digest(queue)], phase='details')
            else:
                page = state['next_page']
                queue, total, more = _art_page(fetch(_art_page_url(page), 'text/html' if page == 1 else 'application/json'), page)
                if state['catalog_total'] is not None and state['catalog_total'] != total:
                    return _result(_blank(key, current))
                if {i['id'] for i in queue}.intersection(i['id'] for i in state['queue']):
                    raise ValueError('nyc_performance_manifest_incomplete')
                state['queue'].extend(queue)
                state['page_hashes'].append(_digest(queue))
                state.update(catalog_total=total, next_page=page + 1, phase='manifest' if more else 'details')
            state.update(manifest_count=len(state['queue']), manifest_hash=_digest(state['queue']))
            return _result(state)
        if state['phase'] == 'verify':
            _check(deadline)
            page = state['verify_page']
            if key == JALOPY:
                queue, total = _jalopy_manifest(fetch(SOURCES[key][0], 'application/json'), started)
            else:
                queue, total, _ = _art_page(fetch(_art_page_url(page), 'text/html' if page == 1 else 'application/json'), page)
            if total != state['catalog_total'] or _digest(queue) != state['page_hashes'][page - 1]:
                return _result(_blank(key, current))
            state['verify_page'] += 1
            if state['verify_page'] == state['next_page']:
                state.update(phase='complete', manifest_verified=True)
            return _result(state)
        for _ in range(max_details):
            if state['cursor'] == len(state['queue']):
                break
            _check(deadline)
            item, reason = state['queue'][state['cursor']], 'event_not_current'
            try:
                if NONPUBLIC.search(item['title']) or key == ART_HAUS and item['unavailable']:
                    raise ValueError('event_not_public')
                if key == ART_HAUS and _time(item['starts_at']) >= started + timedelta(days=60):
                    raise ValueError('event_not_current')
                payload = fetch(item['url'], 'text/html')
                rows = _unique(_jalopy_detail(item, payload, current) if key == JALOPY else _art_detail(item, payload, current, fetch))
            except ValueError as error:
                if str(error) not in HOLD_REASONS:
                    raise
                rows, reason = [], str(error)
            state['events'].extend(rows)
            state['row_hashes'].update({_row_key(row): _digest(row) for row in rows})
            state['diagnostics'].append(dict(event_url=item['url'], event_count=len(rows),
                disposition='accepted' if rows else 'held', reason=None if rows else reason))
            state['cursor'] += 1
        if state['cursor'] == len(state['queue']):
            state['phase'] = 'verify'
    except ValueError as error:
        if not _bounded(error):
            raise
    return _result(state)
