"""Hummingbird's next dated public yoga sessions, from publisher SSR data.

The studio's current class cards identify the six reviewed public classes. Each
independent WellnessLiving Explorer page publishes its own nextBookableSession,
complete class narrative, venue and explicit local/UTC clocks. No occurrence is
generated from a weekly card or recurring period. The embedded widget host is
not used. A complete six-page manifest is collected in bounded checkpoints;
partial results never enter staging.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import record, timestamp


SOURCE_KEY = 'hummingbird_yoga_nj'
ZONE = 'America/New_York'
SOURCES = {SOURCE_KEY: ('https://www.hummingbirdyoganj.com/classes', 'html', 'html')}
ALLOWED_HOSTS = {SOURCE_KEY: ('www.hummingbirdyoganj.com', 'www.wellnessliving.com')}
CHECKPOINT_KEYS = {SOURCE_KEY}
CONTRACT = 'atlantic_city_studio_v1'
MAX_DETAILS_PER_CHUNK = 2
MIN_DETAIL_SECONDS = 15
MAX_CHECKPOINT_BYTES = 120_000
MAX_DESCRIPTION = 12000
MAX_HTML = 1_000_000
MAX_CHECKPOINT_AGE = timedelta(hours=4)
BUSINESS_ID = 146915
LOCATION_ID = 141251
VENUE = ('Hummingbird Yoga NJ', '1637 New Road Suite 2, Northfield, NJ 08225', 'Northfield')
LOCATION = (39.3706889, -74.5584344)
LOCATION_PROVENANCE = 'publisher_wellnessliving_location'
CLASS_BASE = ('https://www.wellnessliving.com/explore/locations/yoga/'
              'us-nj-northfield/hummingbirdyoga/schedule/classes/')
# IDs are published in the studio's current class filter links. Slugs and all
# business/location associations were verified in the public Explorer pages.
CLASSES = {
    444005: ('Kripalu', 'kripalu-141251444005'),
    444002: ('Joyful Morning Yoga', 'joyful-morning-yoga-141251444002'),
    657493: ('Soulful Stretch', 'soulful-stretch-141251657493'),
    877223: ('Flow and Restore', 'flow-and-restore-141251877223'),
    444006: ('Restorative Yin', 'restorative-yin-141251444006'),
    521671: ('Mindful Movement', 'mindful-movement-141251521671'),
}
MINDFUL = 521671
HOLD_REASONS = {
    'no_published_next_session', 'cancelled', 'not_bookable', 'sold_out',
    'not_public_in_person', 'prerequisite_unresolved', 'outside_window',
    'event_ended_during_collection',
}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _source(source):
    if ((source.get('source_key'), source.get('feed_url'), source.get('kind'),
         source.get('platform_adapter'), source.get('timezone')) !=
            (SOURCE_KEY, *SOURCES[SOURCE_KEY], ZONE)):
        raise ValueError('unregistered_atlantic_studio_source')


def _complete(value):
    """Validate normalized prose without stripping escaped literal markup twice."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('publisher_description_missing')
    if len(value) > MAX_DESCRIPTION:
        raise ValueError('publisher_description_limit')
    return value


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def _html(payload):
    if not isinstance(payload, str) or not payload or len(payload.encode()) > MAX_HTML:
        raise ValueError('atlantic_studio_html_invalid')
    return BeautifulSoup(payload, 'html.parser')


def event_url(key, value):
    return key == SOURCE_KEY and isinstance(value, str) and value in {
        CLASS_BASE + slug + '/' for _, slug in CLASSES.values()}


def manifest(payload):
    """The current studio site, including the exact native Mindful narrative."""
    soup = _html(payload)
    services = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or '')
        except (TypeError, ValueError):
            raise ValueError('atlantic_studio_manifest_invalid') from None
        if isinstance(data, dict) and data.get('@type') == 'Service':
            services.append(data)
    if len(services) != 1:
        raise ValueError('atlantic_studio_manifest_invalid')
    service = services[0]
    provider = service.get('provider')
    if (not isinstance(provider, dict) or provider.get('@type') != 'YogaStudio'
            or provider.get('name') != VENUE[0]
            or provider.get('@id') != 'https://www.hummingbirdyoganj.com/#studio'
            or service.get('areaServed') != {'@type': 'City', 'name': 'Northfield, NJ'}
            or not isinstance(service.get('offers'), list)
            or not any(isinstance(o, dict) and o.get('@type') == 'Offer'
                       and o.get('name') == 'Drop-in class' and o.get('priceCurrency') == 'USD'
                       and str(o.get('price')) == '20' for o in service['offers'])
            or not re.search(r'1637 New Rd, Suite 2[ ,]+Northfield, NJ 08225', _text(soup))):
        raise ValueError('atlantic_studio_manifest_invalid')
    found = {}
    for link in soup.select('a[data-filter]'):
        raw_id = link.get('data-filter', '')
        if not re.fullmatch(r'[1-9][0-9]{0,9}', raw_id):
            raise ValueError('atlantic_studio_manifest_invalid')
        class_id = int(raw_id)
        card = link.find_parent('article')
        if (class_id not in CLASSES or class_id in found or card is None
                or link.get('href') != f'/classes?class={class_id}'
                or _text(card.select_one('h3')) != CLASSES[class_id][0]):
            raise ValueError('atlantic_studio_manifest_invalid')
        body_nodes = card.select('p.text-moss')
        if len(body_nodes) != 1 or not _text(card.select_one('p.when')):
            raise ValueError('atlantic_studio_manifest_invalid')
        body = _complete(narrative(body_nodes[0]))
        found[class_id] = {'class_id': class_id, 'title': CLASSES[class_id][0],
                           'url': CLASS_BASE + CLASSES[class_id][1] + '/',
                           'when': _text(card.select_one('p.when')),
                           'studio_description': body}
    if set(found) != set(CLASSES):
        raise ValueError('atlantic_studio_manifest_invalid')
    return [found[class_id] for class_id in CLASSES]


def _location(location):
    if (not isinstance(location, dict) or type(location.get('wBusinessId')) is not int
            or location.get('wBusinessId') != BUSINESS_ID
            or type(location.get('wLocationId')) is not int or location.get('wLocationId') != LOCATION_ID
            or location.get('title') != VENUE[0] or location.get('city') != VENUE[2]
            or location.get('streetAddress') != '1637 New Rd. Suite2'
            or location.get('state') != 'New Jersey' or location.get('zipcode') != '08225'
            or location.get('country') != 'USA' or location.get('timezone') != ZONE
            or location.get('urlSite') not in ('https://hummingbirdyoganj.com/',
                                             'https://www.hummingbirdyoganj.com/')):
        raise ValueError('atlantic_studio_location_changed')
    for field, expected in zip(('latitude', 'longitude'), LOCATION):
        value = location.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value - expected) > 0.0000001:
            raise ValueError('atlantic_studio_location_changed')


def _identity(value, class_id):
    return (isinstance(value, dict)
            and type(value.get('wBusinessId')) is int and value['wBusinessId'] == BUSINESS_ID
            and type(value.get('wClassId')) is int and value['wClassId'] == class_id)


def _clocks(session):
    try:
        values = [session.get(name) for name in ('utcDateTimeStart', 'startDateTime', 'localDateTimeStart')]
        if any(not isinstance(v, str) for v in values):
            raise ValueError
        utc, starts = (datetime.fromisoformat(v.replace('Z', '+00:00')) for v in values[:2])
        local_naive = datetime.fromisoformat(values[2])
        if (utc.tzinfo is None or utc.utcoffset() != timedelta(0)
                or starts.tzinfo is None or starts != utc or local_naive.tzinfo is not None
                or session.get('timezone') != 'ET'):
            raise ValueError
        local = timestamp(local_naive, ZONE)
        if local != utc:
            raise ValueError
        duration = session.get('durationMinutes')
        if type(duration) is not int or not 1 <= duration <= 1440:
            raise ValueError
        return local, (utc + timedelta(minutes=duration)).astimezone(ZoneInfo(ZONE))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('atlantic_studio_clock_conflict') from None


def parse_detail(payload, item, *, now):
    soup = _html(payload)
    nodes = soup.select('script#__NEXT_DATA__')
    if len(nodes) != 1:
        raise ValueError('atlantic_studio_detail_invalid')
    try:
        data = json.loads(nodes[0].string or '')
        props = data['props']['pageProps']
        course, settings = props['course'], props['settings']
        location = props['defaults']['location']
    except (TypeError, ValueError, KeyError):
        raise ValueError('atlantic_studio_detail_invalid') from None
    class_id = item['class_id']
    if (data.get('page') != '/listings/class/[slug]'
            or data.get('query') != {'slug': CLASSES[class_id][1]}
            or not _identity(course, class_id) or course.get('title') != item['title']
            or course.get('urlSlug') != CLASSES[class_id][1]
            or not isinstance(settings, dict) or settings.get('wBusinessId') != BUSINESS_ID
            or settings.get('title') != VENUE[0] or settings.get('currencyCode') != 'USD'
            or type(settings.get('clientMustSignIn')) is not bool):
        raise ValueError('atlantic_studio_detail_identity')
    _location(location)
    locations = props.get('locations')
    if not isinstance(locations, list) or len(locations) != 1:
        raise ValueError('atlantic_studio_location_changed')
    _location(locations[0])
    if (type(course.get('isVirtual')) is not bool or type(course.get('onlineBookingEnabled')) is not bool
            or type(course.get('purchaseOptionsEnabled')) is not bool
            or not isinstance(course.get('prerequisiteCourses'), list)
            or not isinstance(course.get('prerequisiteEvents'), list)):
        raise ValueError('atlantic_studio_eligibility_invalid')
    if (course['isVirtual'] or not course['onlineBookingEnabled']
            or not course['purchaseOptionsEnabled'] or settings['clientMustSignIn']):
        return None, 'not_public_in_person'
    if course['prerequisiteCourses'] or course['prerequisiteEvents']:
        return None, 'prerequisite_unresolved'
    if 'nextBookableSession' not in props:
        raise ValueError('atlantic_studio_detail_invalid')
    session = props['nextBookableSession']
    if session is None:
        return None, 'no_published_next_session'
    if (not _identity(session, class_id) or type(session.get('wLocationId')) is not int
            or session.get('wLocationId') != LOCATION_ID or type(session.get('id')) is not int
            or session['id'] <= 0 or any(type(session.get(k)) is not bool for k in
                                        ('isCancelled', 'isBookable', 'isVirtual'))):
        raise ValueError('atlantic_studio_session_identity')
    if session['isCancelled']:
        return None, 'cancelled'
    if not session['isBookable']:
        return None, 'not_bookable'
    if session['isVirtual']:
        return None, 'not_public_in_person'
    total, used = session.get('bookingSlotsTotal'), session.get('bookingSlotsUsed')
    if type(total) is not int or type(used) is not int or total < 0 or used < 0:
        raise ValueError('atlantic_studio_eligibility_invalid')
    if used >= total:
        return None, 'sold_out'
    if type(session.get('denyReasonId')) is not int or session['denyReasonId'] != 0:
        raise ValueError('atlantic_studio_eligibility_invalid')
    start, end = _clocks(session)
    if end <= now or start >= now + timedelta(days=60):
        return None, 'outside_window'
    description = course.get('description')
    if not isinstance(description, str):
        raise ValueError('publisher_description_missing')
    if description.strip():
        body = _complete(narrative(description))
        origin = item['url']
    elif class_id == MINDFUL and course['title'] == CLASSES[MINDFUL][0]:
        # The own-site class paragraph is explicitly current and matched by
        # title AND native class filter ID. No other blank course inherits it.
        body = _complete(item['studio_description'])
        origin = SOURCES[SOURCE_KEY][0] + '?class=' + str(MINDFUL)
    else:
        raise ValueError('publisher_description_missing')
    parts = [body]
    for owner in (course, session):
        special = owner.get('specialInstructions')
        if not isinstance(special, str):
            raise ValueError('atlantic_studio_instructions_invalid')
        if special.strip():
            if course.get('canShowSpecialInstructions') is not True:
                raise ValueError('atlantic_studio_instructions_invalid')
            text = _complete(narrative(special))
            if text not in parts:
                parts.append(text)
    body = _complete('\n\n'.join(parts))
    result = record(item['title'], start.isoformat(), end.isoformat(), *VENUE,
                    item['url'], str(session['id']), 'Sports & Fitness',
                    lat=LOCATION[0], lng=LOCATION[1], tz=ZONE, retain_until_end=True)
    if result is None:
        return None, 'outside_window'
    result.update(description=body, timezone=ZONE, attendance_mode='in_person',
                  location_provenance=LOCATION_PROVENANCE, description_source_url=origin)
    return result, None


def _checkpoint(value, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
            or value.get('contract') != CONTRACT or value.get('source_key') != SOURCE_KEY
            or type(value.get('cursor')) is not int or type(value.get('manifest_count')) is not int
            or value['manifest_count'] != len(CLASSES) or not 0 <= value['cursor'] <= len(CLASSES)
            or not isinstance(value.get('queue'), list) or len(value['queue']) != len(CLASSES)
            or not isinstance(value.get('events'), list) or not isinstance(value.get('diagnostics'), list)
            or len(value['events']) + len(value['diagnostics']) != value['cursor']
            or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('manifest_hash')))
            or len(_encoded(value).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError('atlantic_studio_checkpoint_invalid')
    try:
        started = datetime.fromisoformat(value['started_at'])
        if started.tzinfo is None or value['window_start'] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError('atlantic_studio_checkpoint_invalid') from None
    if now < started or now - started > MAX_CHECKPOINT_AGE:
        return None
    for item, class_id in zip(value['queue'], CLASSES):
        if (not isinstance(item, dict) or type(item.get('class_id')) is not int
                or item['class_id'] != class_id or item.get('title') != CLASSES[class_id][0]
                or item.get('url') != CLASS_BASE + CLASSES[class_id][1] + '/'
                or not isinstance(item.get('when'), str) or not item['when']
                or not isinstance(item.get('studio_description'), str)
                or not 0 < len(item['studio_description'].strip()) <= MAX_DESCRIPTION):
            raise ValueError('atlantic_studio_checkpoint_invalid')
    if sha256(_encoded(value['queue']).encode()).hexdigest() != value['manifest_hash']:
        raise ValueError('atlantic_studio_checkpoint_invalid')
    prefix = {item['url']: item for item in value['queue'][:value['cursor']]}
    seen, identities = set(), set()
    for row in value['events']:
        item = prefix.get(row.get('event_url')) if isinstance(row, dict) else None
        if (item is None or row['event_url'] in seen or row.get('title') != item['title']
                or not isinstance(row.get('id'), str) or not re.fullmatch(r'[1-9][0-9]*', row['id'])
                or row['id'] in identities
                or (row.get('venue_name'), row.get('venue_address'), row.get('venue_city')) != VENUE
                or (row.get('lat'), row.get('lng')) != LOCATION
                or row.get('location_provenance') != LOCATION_PROVENANCE or row.get('timezone') != ZONE
                or row.get('attendance_mode') != 'in_person'
                or not isinstance(row.get('description'), str)
                or not 0 < len(row['description'].strip()) <= MAX_DESCRIPTION
                or row.get('description_source_url') not in (item['url'],
                   SOURCES[SOURCE_KEY][0] + '?class=' + str(MINDFUL))
                or (row.get('description_source_url') != item['url'] and item['class_id'] != MINDFUL)):
            raise ValueError('atlantic_studio_checkpoint_invalid')
        try:
            start, end = timestamp(row.get('starts_at')), timestamp(row.get('ends_at'))
            if (start is None or end is None or start.tzinfo is None or end.tzinfo is None
                    or end <= start or end - start > timedelta(days=1)
                    or start >= started + timedelta(days=60) or end <= started):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError('atlantic_studio_checkpoint_invalid') from None
        seen.add(row['event_url'])
        identities.add(row['id'])
    for diagnostic in value['diagnostics']:
        if (not isinstance(diagnostic, dict) or diagnostic.get('event_url') not in prefix
                or diagnostic['event_url'] in seen or diagnostic.get('disposition') != 'held'
                or diagnostic.get('reason') not in HOLD_REASONS):
            raise ValueError('atlantic_studio_checkpoint_invalid')
        seen.add(diagnostic['event_url'])
    if seen != set(prefix):
        raise ValueError('atlantic_studio_checkpoint_invalid')
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('atlantic_studio_checkpoint_invalid')
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, current)
    _check(deadline_at)
    queue = manifest(fetch(SOURCES[SOURCE_KEY][0], 'text/html'))
    digest = sha256(_encoded(queue).encode()).hexdigest()
    if state is None or state['manifest_hash'] != digest or state['queue'] != queue:
        state = {'version': 1, 'contract': CONTRACT, 'source_key': SOURCE_KEY,
                 'started_at': current.isoformat(),
                 'window_start': current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 'manifest_hash': digest, 'manifest_count': len(queue), 'cursor': 0,
                 'queue': queue, 'events': [], 'diagnostics': []}
    previous = state['cursor']
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state['cursor'] < len(queue) and state['cursor'] - previous < limit:
        if deadline_at is not None and deadline_at - monotonic() < MIN_DETAIL_SECONDS:
            break
        item = queue[state['cursor']]
        try:
            payload = fetch(item['url'], 'text/html')
        except ValueError as exc:
            from roomquest.preview_worker import PreviewError
            if (isinstance(exc, PreviewError) and str(exc) in
                    ('source_fetch_deadline', 'publisher_pacing_deferred') and state['cursor'] > previous):
                break
            raise
        # Every resumed chunk shares the original snapshot's 60-day window.
        # Already-ended rows are checked against current time at completion.
        row, reason = parse_detail(payload, item, now=timestamp(state['started_at']))
        if row is not None:
            state['events'].append(row)
        else:
            state['diagnostics'].append({'event_url': item['url'], 'disposition': 'held', 'reason': reason})
        state['cursor'] += 1
    if state['cursor'] == previous < len(queue):
        raise ValueError('collection_deadline')
    complete = state['cursor'] == len(queue)
    if complete:
        for row in list(state['events']):
            if timestamp(row['ends_at']) <= current:
                state['events'].remove(row)
                state['diagnostics'].append({'event_url': row['event_url'], 'disposition': 'held',
                                             'reason': 'event_ended_during_collection'})
        if len({row['id'] for row in state['events']}) != len(state['events']):
            raise ValueError('atlantic_studio_duplicate_session')
    if len(_encoded(state).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('atlantic_studio_checkpoint_size_limit')
    rows = sorted(state['events'], key=lambda r: (r['starts_at'], r['id'])) if complete else []
    return {'complete': complete, 'events': deepcopy(rows), 'checkpoint': state}


def collect(source, fetch, *, deadline_at=None, now=None):
    """A caller without a durable checkpoint must never accept a partial read."""
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result['complete']:
        raise ValueError('publisher_checkpoint_required')
    return result['events']
