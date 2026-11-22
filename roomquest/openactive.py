"""Reviewed OpenActive RPDE profiles, cursors and occurrence projection.

Transport, persistent storage and lease fencing belong to the worker. A page is
not an event collection: only an empty self-next page proves an RPDE tail. The
SessionSeries and ScheduledSession feeds remain joined by native identity.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import address, plain, record, timestamp
from roomquest.registration_formats import source_key

BETTER = 'https://better-admin.org.uk/api/openactive/better'
BOOKWHEN = 'https://bookwhen.com/api/openactive/'
ORIENTEERING = 'https://www.britishorienteering.org.uk/fullfixturesjson.php'
CYCLING = 'https://api.letsride.co.uk/public/v1/rides'
PROFILES = {
    'better': {'urls': (BETTER, BETTER + '/session-series', BETTER + '/scheduled-sessions'),
               'streams': (BETTER + '/session-series', BETTER + '/scheduled-sessions'),
               'event_hosts': ('bookings.better.org.uk',), 'sessions_only': True},
    'bookwhen': {'urls': (BOOKWHEN + 'sessionseries', BOOKWHEN + 'scheduledsessions'),
                 'streams': (BOOKWHEN + 'sessionseries', BOOKWHEN + 'scheduledsessions'),
                 'event_hosts': ('bookwhen.com',), 'sessions_only': True},
    'orienteering': {'urls': (ORIENTEERING,), 'streams': (ORIENTEERING,),
                    'event_hosts': ('www.britishorienteering.org.uk',), 'sessions_only': False},
    'cycling': {'urls': (CYCLING,), 'streams': (CYCLING,),
                'event_hosts': ('www.letsride.co.uk',), 'sessions_only': False},
}
URLS = tuple(url for spec in PROFILES.values() for url in spec['urls'])
ADAPTER = 'openactive_rpde_v1'
EXTRACTION = 'registered_openactive_rpde_v1'
MAX_ITEM_BYTES = 60_000
MAX_DESCRIPTION = 12000
MAX_RECORDS = 250_000
MAX_CAPTURE_AGE = timedelta(hours=4)
RESYNC_AFTER = timedelta(days=6)
LICENSES = frozenset(('https://creativecommons.org/licenses/by/4.0/',
                      'http://creativecommons.org/licenses/by/4.0/'))


def profile(url):
    return next((spec for spec in PROFILES.values() if url in spec['urls']), None)


def enabled(source):
    return (type(source.get('registered_openactive_version')) is int
            and source['registered_openactive_version'] == 1)


def validate_source(source, *, require_capability=True):
    if (not profile(source.get('feed_url'))
            or source.get('source_key') != source_key(source['feed_url'])
            or source.get('kind', 'json') != 'json'
            or source.get('platform_adapter', 'jsonld') != 'jsonld'
            or require_capability and not enabled(source)):
        raise ValueError('openactive_source_identity')


def allowed_hosts(url):
    spec = profile(url)
    if not spec:
        raise ValueError('openactive_source_identity')
    return tuple(sorted({urlsplit(stream).hostname for stream in spec['streams']}))


def page_url(value, stream):
    from roomquest.registered_native_content import native_url
    if not native_url(value):
        return False
    parts, base = urlsplit(value), urlsplit(stream)
    if (parts.scheme, parts.netloc, parts.path) != (base.scheme, base.netloc, base.path):
        return False
    fields = parse_qsl(parts.query, keep_blank_values=True)
    names = [k for k, _ in fields]
    return (len(names) == len(set(names)) and len(parts.query) <= 2000
            and set(names) <= {'afterTimestamp', 'afterId', 'afterChangeNumber', 'limit'}
            and all(v and len(v) <= 500 for _, v in fields)
            and ('afterTimestamp' in names) == ('afterId' in names)
            and not ('afterChangeNumber' in names and 'afterId' in names))


def evidence_url(source, value):
    spec = profile(source.get('feed_url'))
    return bool(spec and any(page_url(value, stream) for stream in spec['streams']))


def event_url(source, value):
    from roomquest.registered_native_content import native_url
    spec = profile(source.get('feed_url'))
    return bool(spec and native_url(value) and urlsplit(value).hostname in spec['event_hosts'])


def _scalar(value):
    return ((type(value) is int and value >= 0)
            or isinstance(value, str) and 0 < len(value) <= 500)


def _position(modified, identity):
    # The RPDE identifier retains its JSON number/string ordering. Cross-type
    # comparisons are rejected rather than guessing the publisher's collation.
    if not _scalar(modified) or not _scalar(identity):
        raise ValueError('openactive_position_invalid')
    return modified, identity


def _cursor(value):
    fields = dict(parse_qsl(urlsplit(value).query))
    raw = fields.get('afterTimestamp', fields.get('afterChangeNumber'))
    if raw is None:
        return None
    modified = int(raw) if re.fullmatch(r'[0-9]+', raw) else raw
    return modified, fields.get('afterId', '')


def _after(left, right):
    if right is None:
        return True
    try:
        return left > right
    except TypeError as exc:
        raise ValueError('openactive_position_invalid') from exc


def _projection_data(data, *, depth=0):
    """Retain all fields used in cards, not unrelated booking/cache payloads.

    Better can publish thousands of PartialSchedule entries on a single parent.
    Their types suffice to prove we must not extrapolate; actual occurrences
    come from the separate ScheduledSession stream. No narrative, venue,
    occurrence identity or status is truncated by this reduction.
    """
    if depth > 3:
        raise ValueError('openactive_item_size_limit')
    fields = ('@type', 'type', '@id', 'id', 'name', 'description', 'url', 'image',
              'startDate', 'endDate', 'date_start', 'date_end', 'session_url',
              'eventStatus', 'eventAttendanceMode', 'cancelled', 'duration')
    result = {key: deepcopy(data[key]) for key in fields if key in data}
    if 'superEvent' in data:
        parent = data['superEvent']
        result['superEvent'] = ({key: parent[key] for key in ('@id', 'id') if key in parent}
                                if isinstance(parent, dict) else parent)
    if isinstance(data.get('location'), dict):
        result['location'] = {key: deepcopy(data['location'][key]) for key in (
            '@type', 'type', '@id', 'id', 'name', 'address', 'geo', 'venue',
            'nearest_town', 'event_centre', 'postcode') if key in data['location']}
    if isinstance(data.get('activity'), list):
        result['activity'] = [{'prefLabel': value.get('prefLabel', '')}
                              for value in data['activity'] if isinstance(value, dict)]
    if 'eventSchedule' in data:
        schedules = data['eventSchedule'] if isinstance(data['eventSchedule'], list) else [data['eventSchedule']]
        result['eventSchedule'] = [dict({'@type': kind}, **({'scheduleTimezone': zone} if zone else {}))
                                  for kind, zone in sorted({(_type(item), str(item.get('scheduleTimezone') or ''))
                                  for item in schedules if isinstance(item, dict)})]
    if 'subEvent' in data:
        if (not isinstance(data['subEvent'], list) or len(data['subEvent']) > 500
                or any(not isinstance(child, dict) for child in data['subEvent'])):
            raise ValueError('openactive_item_invalid')
        result['subEvent'] = [_projection_data(child, depth=depth + 1)
                              for child in data['subEvent']]
    if isinstance(data.get('details'), dict):
        result['details'] = {'description': data['details'].get('description', '')}
    return result


def parse_page(payload, requested, stream, *, previous=None, license_url=None):
    if not page_url(requested, stream):
        raise ValueError('openactive_cursor_scope')
    try:
        data = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError('openactive_payload_invalid') from exc
    if (not isinstance(data, dict) or not isinstance(data.get('items'), list)
            or len(data['items']) > 500 or data.get('license') not in LICENSES
            or license_url is not None and data['license'] != license_url
            or not page_url(data.get('next'), stream)):
        raise ValueError('openactive_payload_invalid')
    result, position = [], previous
    for item in data['items']:
        if (not isinstance(item, dict) or item.get('state') not in ('updated', 'deleted')
                or not isinstance(item.get('kind'), str) or not 1 <= len(item['kind']) <= 100):
            raise ValueError('openactive_item_invalid')
        current = _position(item.get('modified'), item.get('id'))
        if not _after(current, position):
            raise ValueError('openactive_page_order_invalid')
        position = current
        key = hashlib.sha256((stream + '\n' + item['kind'] + '\n' + str(item['id'])).encode()).hexdigest()
        if item['state'] == 'deleted':
            result.append({'key': key, 'deleted': True})
            continue
        body = item.get('data')
        if not isinstance(body, dict):
            raise ValueError('openactive_item_invalid')
        identity = body.get('@id', body.get('id'))
        if identity is not None and (not isinstance(identity, str) or len(identity) > 1000):
            raise ValueError('openactive_item_invalid')
        row = {'key': key, 'feed_url': stream, 'kind': item['kind'], 'identity': identity,
               'data': _projection_data(body), 'evidence_url': requested}
        if len(json.dumps(row, ensure_ascii=False).encode()) > MAX_ITEM_BYTES:
            raise ValueError('openactive_item_size_limit')
        result.append(row)
    tail = not data['items'] and data['next'] == requested
    if data['items'] and data['next'] == requested:
        raise ValueError('openactive_cursor_stalled')
    outgoing = _cursor(data['next'])
    incoming = _cursor(requested)
    if data['items']:
        fields = dict(parse_qsl(urlsplit(data['next']).query))
        if (outgoing is None or str(outgoing[0]) != str(position[0])
                or 'afterId' in fields and fields['afterId'] != str(position[1])):
            raise ValueError('openactive_cursor_invalid')
    elif not tail and (outgoing is None or incoming is not None and not _after(outgoing, incoming)):
        raise ValueError('openactive_cursor_stalled')
    return {'items': result, 'next': data['next'], 'tail': tail,
            'license': data['license'], 'position': position}


def probe(source, fetch, *, body=None, deadline_at=None):
    validate_source(source, require_capability=False)
    spec = profile(source['feed_url'])
    if source['feed_url'] == BETTER:
        soup = BeautifulSoup(body if body is not None else fetch(BETTER, 'text/html'), 'html.parser')
        distributions = set()
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                dataset = json.loads(script.get_text())
            except ValueError:
                continue
            if isinstance(dataset, dict) and dataset.get('@type') == 'Dataset' and dataset.get('@id') == BETTER:
                distributions.update(v.get('contentUrl') for v in dataset.get('distribution', []) if isinstance(v, dict))
        if not set(spec['streams']) <= distributions:
            raise ValueError('openactive_dataset_identity')
    for stream in spec['streams']:
        payload = body if stream == source['feed_url'] and body is not None else fetch(stream, 'application/json')
        parse_page(payload, stream, stream)
    return True


def _utc(value):
    if not isinstance(value, str):
        raise ValueError('openactive_checkpoint_invalid')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError('openactive_checkpoint_invalid')
    return result


def new_checkpoint(source, *, now, previous=None):
    validate_source(source)
    reset = (previous is None or previous.get('last_complete_at') is None
             or now - _utc(previous['last_complete_at']) >= RESYNC_AFTER)
    streams = []
    for index, url in enumerate(profile(source['feed_url'])['streams']):
        old = previous['streams'][index] if previous and not reset else None
        streams.append({'url': url, 'next': old['next'] if old else url,
                        'complete': False, 'pages': 0, 'license': old['license'] if old else None,
                        'last_modified': old['last_modified'] if old else None,
                        'last_id': old['last_id'] if old else None})
    return ({'version': 1, 'adapter': ADAPTER, 'source_key': source['source_key'],
             'feed_url': source['feed_url'], 'started_at': now.isoformat(),
             'last_complete_at': previous['last_complete_at'] if previous else None,
             'phase': 'fetch', 'streams': streams, 'stage_after': None,
             'record_count': 0, 'venue_count': 0, 'held_count': 0, 'samples': []}, reset)


def validate_checkpoint(source, value, *, now):
    validate_source(source)
    try:
        if (not isinstance(value, dict) or set(value) != {
                'version', 'adapter', 'source_key', 'feed_url', 'started_at', 'last_complete_at',
                'phase', 'streams', 'stage_after', 'record_count', 'venue_count', 'held_count', 'samples'}
                or type(value['version']) is not int or value['version'] != 1 or value['adapter'] != ADAPTER
                or value['source_key'] != source['source_key'] or value['feed_url'] != source['feed_url']
                or value['phase'] not in ('fetch', 'stage', 'complete', 'ready')
                or any(type(value[k]) is not int or value[k] < 0 for k in ('record_count', 'venue_count', 'held_count'))
                or value['record_count'] > MAX_RECORDS or value['venue_count'] > value['record_count']
                or value['stage_after'] is not None and not re.fullmatch('[0-9a-f]{64}', value['stage_after'])
                or not isinstance(value['samples'], list) or len(value['samples']) > 8
                or len(json.dumps(value['samples'], ensure_ascii=False).encode('utf-8')) > 18000):
            raise ValueError
        if value['last_complete_at'] is not None:
            _utc(value['last_complete_at'])
        age = now - _utc(value['started_at'])
        if age < timedelta(seconds=-30):
            raise ValueError
        # Ready snapshots intentionally survive the 96-hour freshness window. An
        # in-progress capture has a bounded lifetime and restarts visibly.
        streams = value['streams']
        if not isinstance(streams, list) or [x['url'] for x in streams] != list(profile(source['feed_url'])['streams']):
            raise ValueError
        for item in streams:
            if (set(item) != {'url', 'next', 'complete', 'pages', 'license', 'last_modified', 'last_id'}
                    or not page_url(item['next'], item['url']) or type(item['complete']) is not bool
                    or type(item['pages']) is not int or not 0 <= item['pages'] <= 100000
                    or item['license'] is not None and item['license'] not in LICENSES
                    or (item['last_modified'] is None) != (item['last_id'] is None)):
                raise ValueError
            if item['last_modified'] is not None:
                _position(item['last_modified'], item['last_id'])
        if value['phase'] != 'fetch' and not all(x['complete'] for x in streams):
            raise ValueError
        if value['phase'] != 'ready' and age > MAX_CAPTURE_AGE:
            raise ValueError('openactive_checkpoint_expired')
    except (TypeError, KeyError, ValueError, OverflowError) as exc:
        if str(exc) == 'openactive_checkpoint_expired':
            raise
        raise ValueError('openactive_checkpoint_invalid') from exc
    return value


def parent_identity(item):
    parent = item['data'].get('superEvent')
    if isinstance(parent, dict):
        parent = parent.get('@id', parent.get('id'))
    return parent if isinstance(parent, str) else None


def validate_item(source, item):
    try:
        if (not isinstance(item, dict) or set(item) != {
                'key', 'feed_url', 'kind', 'identity', 'data', 'evidence_url'}
                or not isinstance(item['key'], str) or not re.fullmatch('[0-9a-f]{64}', item['key'])
                or item['feed_url'] not in profile(source['feed_url'])['streams']
                or not isinstance(item['kind'], str) or not 1 <= len(item['kind']) <= 100
                or not isinstance(item['data'], dict)
                or item['identity'] != item['data'].get('@id', item['data'].get('id'))
                or not page_url(item['evidence_url'], item['feed_url'])
                or len(json.dumps(item, ensure_ascii=False).encode()) > MAX_ITEM_BYTES):
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('openactive_retained_item_invalid') from exc


def _type(data):
    value = data.get('@type', data.get('type', ''))
    return str(value).rstrip('/').rsplit('/', 1)[-1].rsplit('#', 1)[-1]


def _cancelled(data):
    return str(data.get('eventStatus', '')).rsplit('/', 1)[-1] in (
        'EventCancelled', 'EventPostponed') or data.get('cancelled') is True


def _attach_native(row, source, item, narrative):
    from roomquest.registered_native_content import image_candidate, VERSION
    if not evidence_url(source, item.get('evidence_url')) or not event_url(source, row['event_url']):
        raise ValueError('openactive_native_evidence_invalid')
    image = image_candidate(item['data'].get('image'), item['evidence_url'])
    row['description'] = narrative
    row['image_extractor_version'] = VERSION
    row['registered_native_content'] = {
        'version': 1, 'source_key': source['source_key'], 'feed_url': source['feed_url'],
        'adapter': 'jsonld', 'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': 'description' if narrative else None,
        'image_field': 'image' if image else None, 'extraction': EXTRACTION,
        'evidence_url': item['evidence_url'],
    }
    if image:
        row.update(image_url=image, image_provenance=VERSION, image_evidence_url=item['evidence_url'])
    return row


def project(source, item, parents):
    """Map published occurrences; return (records, explicit hold count).

    PartialSchedule is descriptive only. Better/Bookwhen series are joined
    metadata, never invented occurrences. A deleted/missing parent cannot leave
    previously inherited venue/description facts in the current projection.
    """
    validate_item(source, item)
    data = item['data']
    kind = _type(data) or item['kind']
    if _cancelled(data):
        return [], 0
    spec = profile(source['feed_url'])
    if kind in ('SessionSeries', 'EventSeries', 'CourseInstance'):
        if spec['sessions_only']:
            return [], 0
        children = data.get('subEvent', [])
        if not isinstance(children, list):
            return [], 1
        # Only actual native child occurrences are accepted. Full Schedule
        # expansion is intentionally not needed by the reviewed live profiles.
        rows, held = [], 0
        for child in children:
            if not isinstance(child, dict) or not child.get('startDate'):
                held += 1
                continue
            combined = {key: value for key, value in data.items() if key not in (
                '@type', 'type', '@id', 'id', 'subEvent', 'superEvent', 'eventSchedule')}
            combined.update(child)
            combined['@type'] = _type(child) or 'ScheduledSession'
            subitem = dict(item, data=combined, kind=combined['@type'],
                           identity=combined.get('@id', combined.get('id')))
            result, skipped = project(source, subitem, {})
            rows.extend(result)
            held += skipped
        return rows, held + int(not children and bool(data.get('eventSchedule')))
    if spec['sessions_only'] and kind != 'ScheduledSession':
        return [], 1
    parent_ref = parent_identity(item)
    parent = parents.get(parent_ref) if parent_ref else None
    if parent_ref and parent is None:
        return [], 1
    if parent and _cancelled(parent['data']):
        return [], 0
    merged = dict(parent['data'] if parent else {}, **data)
    legacy = item['feed_url'] == ORIENTEERING
    start_value = merged.get('date_start') if legacy else merged.get('startDate')
    end_value = merged.get('date_end') if legacy else merged.get('endDate')
    if not isinstance(start_value, str) or not re.search(r'T\d\d:\d\d', start_value):
        return [], 1
    # Orienteering's legacy feed explicitly uses midnight/end-of-day when no
    # event clock exists. Those are date placeholders, never bookable sessions.
    if legacy and start_value.endswith('T00:00:00') and str(end_value).endswith('T23:59:59'):
        return [], 1
    try:
        start = timestamp(start_value, 'Europe/London' if legacy else None)
        end = timestamp(end_value, 'Europe/London' if legacy else None)
        if start.tzinfo is None or end and end.tzinfo is None:
            return [], 1
    except (ValueError, TypeError, OverflowError):
        return [], 1
    location = merged.get('location')
    if not isinstance(location, dict) or _type(location) == 'VirtualLocation':
        return [], 1
    if str(merged.get('eventAttendanceMode', '')).endswith('OnlineEventAttendanceMode'):
        return [], 0
    place = plain(location.get('name') or location.get('venue'))
    postal = location.get('address') or {}
    street = address(postal)
    city = plain(postal.get('addressLocality')) if isinstance(postal, dict) else ''
    if legacy:
        city = plain(location.get('nearest_town'))
        street = ', '.join(v for v in (plain(location.get('event_centre')), city, plain(location.get('postcode'))) if v)
    geo = location.get('geo') or {}
    lat, lng = geo.get('latitude'), geo.get('longitude')
    if not place or not street:
        return [], 1
    url = merged.get('session_url') if legacy else merged.get('url')
    if not event_url(source, url):
        return [], 1
    descriptive_item = item if data.get('description') else parent or item
    narrative_value = descriptive_item['data'].get('description')
    if legacy:
        narrative_value = (data.get('details') or {}).get('description')
    narrative = description(narrative_value, limit=MAX_DESCRIPTION + 1)
    if len(narrative) > MAX_DESCRIPTION:
        raise ValueError('registered_native_description_too_long')
    if not narrative:
        return [], 1
    native_id = data.get('@id', data.get('id'))
    occurrence = str(native_id or item['key']) + '\n' + start.astimezone(timezone.utc).isoformat()
    identity = 'openactive:' + hashlib.sha256(occurrence.encode()).hexdigest()[:40]
    activity = merged.get('activity') or []
    category = ', '.join(plain(v.get('prefLabel', '')) for v in activity if isinstance(v, dict))
    try:
        row = record(merged.get('name'), start, end, place, street, city, url, identity,
                     category, lat, lng, publisher_geo=True)
    except (ValueError, TypeError, OverflowError):
        return [], 1
    if row is None:
        return [], 0
    zones = {s.get('scheduleTimezone') for s in merged.get('eventSchedule', [])
             if isinstance(s, dict) and s.get('scheduleTimezone')}
    country = postal.get('addressCountry') if isinstance(postal, dict) else None
    if isinstance(country, dict):
        country = country.get('name')
    zone = next(iter(zones)) if len(zones) == 1 else None
    if not zone and str(country).casefold() in ('ie', 'ireland', 'republic of ireland'):
        zone = 'Europe/Dublin'
    if not zone and (spec is not PROFILES['bookwhen'] or str(country).casefold() in ('gb', 'uk', 'united kingdom')):
        zone = 'Europe/London'
    if zone:
        try:
            ZoneInfo(zone)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            return [], 1
        row['timezone'] = zone
    return [_attach_native(row, source, descriptive_item, narrative)], 0


def validate_native(row, source):
    from roomquest.registered_native_content import VERSION, image_candidate
    if (not isinstance(row, dict) or not enabled(source) or not event_url(source, row.get('event_url'))
            or not isinstance(row.get('id'), str) or not 1 <= len(row['id']) <= 180
            or row['id'] != row['id'].strip()):
        raise ValueError('registered_native_evidence_invalid')
    proof = row.get('registered_native_content')
    if not isinstance(proof, dict) or not evidence_url(source, proof.get('evidence_url')):
        raise ValueError('registered_native_evidence_invalid')
    text, image = row.get('description'), row.get('image_url')
    expected = {
        'version': 1, 'source_key': source['source_key'], 'feed_url': source['feed_url'],
        'adapter': 'jsonld', 'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': 'description' if text else None, 'image_field': 'image' if image else None,
        'extraction': EXTRACTION, 'evidence_url': proof['evidence_url'],
    }
    if (proof != expected or not isinstance(text, str) or len(text) > MAX_DESCRIPTION
            or re.search(r'<[^>]+>', text) or row.get('image_extractor_version') != VERSION
            or image and (image_candidate(image) != image or row.get('image_provenance') != VERSION
                          or row.get('image_evidence_url') != proof['evidence_url'])
            or not image and any(row.get(key) is not None for key in ('image_provenance', 'image_evidence_url'))):
        raise ValueError('registered_native_evidence_invalid')
