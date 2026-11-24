"""Read-only Spektrix Web/Public v3 event and performance extraction.

This is a source-independent *collector core*, not admission to EventQuest.
Callers provide an audited client-name/profile, an existing robots-aware fetch
callback and verified first-party event links. The database must authorize
registration, checkpointing, staging and publication separately.

Spektrix's Web/Public events and instances list different objects; joining
them through instance.event.id, instance.planId and plan.venue.id is required
to avoid assigning a ticketing client's headquarters to every performance.
"""
from datetime import date, datetime, timedelta, timezone
from html import unescape
import json
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_DAYS = 60
PAGE_DAYS = 7
MAX_EVENTS = 700
MAX_INSTANCES = 3000
MAX_VENUES = 150
MAX_PLANS = 120
MAX_BODY = 3_000_000
CLIENT = re.compile(r'[a-z][a-z0-9_-]{1,59}\Z')
API_ID = re.compile(r'[A-Za-z0-9-]{10,80}\Z')


def _fail(reason):
    raise ValueError(reason)


def _day(value):
    try:
        if isinstance(value, datetime):
            _fail('spektrix_window_invalid')
        return value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError):
        _fail('spektrix_window_invalid')


def windows(start, end):
    """Inclusive intervals covering at most 60 *calendar days* exactly once."""
    start, end = _day(start), _day(end)
    if end < start or (end - start).days >= MAX_DAYS:
        _fail('spektrix_window_invalid')
    out = []
    next_day = start
    while next_day <= end:
        last_day = min(end, next_day + timedelta(days=PAGE_DAYS - 1))
        out.append((next_day, last_day))
        next_day = last_day + timedelta(days=1)
    return tuple(out)


def _client(client):
    if not isinstance(client, str) or not CLIENT.fullmatch(client):
        _fail('spektrix_client_invalid')
    return client


def api_url(client, resource, *, start=None, end=None, identity=None):
    """Construct *only* documented, read-only Spektrix public API routes."""
    client = _client(client)
    if resource not in ('events', 'instances', 'venues', 'plans'):
        _fail('spektrix_route_invalid')
    if resource == 'plans':
        if not isinstance(identity, str) or not API_ID.fullmatch(identity):
            _fail('spektrix_plan_invalid')
        tail = '/plans/' + identity
        if start is not None or end is not None:
            _fail('spektrix_route_invalid')
        query = ''
    elif resource == 'venues':
        if start is not None or end is not None or identity is not None:
            _fail('spektrix_route_invalid')
        tail, query = '/venues', ''
    else:
        if identity is not None or start is None or end is None:
            _fail('spektrix_route_invalid')
        windows(start, end)  # Never construct unbounded requests.
        keys = ('instanceStart_from', 'instanceStart_to') if resource == 'events' else (
            'startFrom', 'startTo')
        query = '?' + urlencode(((keys[0], str(_day(start))), (keys[1], str(_day(end)))))
        tail = '/' + resource
    return 'https://system.spektrix.com/' + client + '/api/v3' + tail + query


def _payload(value):
    if isinstance(value, str):
        if len(value.encode('utf-8')) > MAX_BODY:
            _fail('spektrix_payload_limit')
        try:
            return json.loads(value)
        except (ValueError, RecursionError):
            _fail('spektrix_payload_invalid')
    return value


def _items(payload, maximum, name):
    payload = _payload(payload)
    if not isinstance(payload, list) or len(payload) > maximum:
        _fail('spektrix_' + name + '_invalid')
    if any(not isinstance(item, dict) for item in payload):
        _fail('spektrix_' + name + '_invalid')
    return payload


def _id(value):
    return isinstance(value, str) and bool(API_ID.fullmatch(value))


def _merge(entries, rows, label, limit):
    for row in rows:
        key = row.get('id')
        if not _id(key):
            _fail('spektrix_' + label + '_invalid')
        if key in entries and entries[key] != row:
            _fail('spektrix_' + label + '_conflict')
        entries[key] = row
        if len(entries) > limit:
            _fail('spektrix_' + label + '_limit')


def _utc(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+]00:00)?',
            value):
        _fail('spektrix_time_invalid')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        _fail('spektrix_time_invalid')


def _local(when, name):
    if not isinstance(when, str) or not re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?', when):
        _fail('spektrix_time_invalid')
    try:
        zone = ZoneInfo(name)
    except (TypeError, ZoneInfoNotFoundError):
        _fail('spektrix_timezone_invalid')
    try:
        dt = datetime.fromisoformat(when).replace(tzinfo=zone)
    except ValueError:
        _fail('spektrix_time_invalid')
    if (dt.utcoffset() != dt.replace(fold=1).utcoffset()
            or dt.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            != dt.replace(tzinfo=None)):
        _fail('spektrix_time_invalid')
    return dt


def _text(value):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', value))).strip()


def _event_url(event, profile):
    link = event.get('webUrl') or profile.get('event_urls', {}).get(event['id'])
    if not isinstance(link, str):
        _fail('spektrix_event_link_missing')
    parts = urlsplit(link)
    publisher = urlsplit(profile['publisher_url'])
    allowed = {publisher.hostname, *(profile.get('verified_event_hosts') or ())}
    if (parts.scheme != 'https' or parts.username or parts.password
            or parts.hostname not in allowed or parts.fragment
            or len(link) > 1200 or not parts.path):
        _fail('spektrix_event_link_unverified')
    return link


def project(profile, events, instances, plans, venues, start, end):
    """Project one *complete* bounded snapshot; never publish a partial prefix.

    An on-sale performance must have a matching Event, plan, real Venue,
    explicit timezone and publisher-owned event link. Missing facts hold the
    whole snapshot rather than silently dropping that performance.
    """
    intervals = windows(start, end)
    client = _client(profile.get('client'))
    if not isinstance(profile.get('publisher_url'), str):
        _fail('spektrix_publisher_invalid')
    publisher = urlsplit(profile['publisher_url'])
    country = profile.get('country')
    if (publisher.scheme != 'https' or not publisher.hostname
            or publisher.username or publisher.password
            or not isinstance(country, str) or not re.fullmatch(r'[A-Z]{2}', country)):
        _fail('spektrix_publisher_invalid')
    events_by_id, instances_by_id, plans_by_id, venues_by_id = {}, {}, {}, {}
    _merge(events_by_id, _items(events, MAX_EVENTS, 'events'), 'events', MAX_EVENTS)
    _merge(instances_by_id, _items(instances, MAX_INSTANCES, 'instances'), 'instances', MAX_INSTANCES)
    _merge(plans_by_id, _items(plans, MAX_PLANS, 'plans'), 'plans', MAX_PLANS)
    _merge(venues_by_id, _items(venues, MAX_VENUES, 'venues'), 'venues', MAX_VENUES)
    records = []
    rejected = 0
    for instance in instances_by_id.values():
        if instance.get('cancelled') is True or instance.get('isOnSale') is False:
            rejected += 1
            continue
        if instance.get('cancelled') is not False or instance.get('isOnSale') is not True:
            _fail('spektrix_instance_visibility_unverified')
        parent = instance.get('event')
        event_id = parent.get('id') if isinstance(parent, dict) else None
        event = events_by_id.get(event_id)
        if event is None:
            _fail('spektrix_event_manifest_mismatch')
        title = _text(event.get('name'))
        if not title:
            _fail('spektrix_event_title_missing')
        plan = plans_by_id.get(instance.get('planId'))
        venue_id = (plan.get('venue') or {}).get('id') if isinstance(plan, dict) else None
        venue = venues_by_id.get(venue_id)
        if not venue:
            _fail('spektrix_plan_venue_unresolved')
        details = (profile.get('verified_venues') or {}).get(venue_id) or {}
        address = _text(venue.get('address'))
        if not address and details.get('address'):
            evidence = details.get('evidence_url')
            url = urlsplit(evidence) if isinstance(evidence, str) else None
            if (url is None or url.scheme != 'https' or url.hostname != publisher.hostname
                    or url.username or url.password):
                _fail('spektrix_venue_evidence_missing')
            address = _text(details['address'])
        city = _text(details.get('city'))
        if not city and profile.get('home_city') and re.search(
                r'\b' + re.escape(profile['home_city']) + r'\b', address, re.I):
            city = profile['home_city']
        time_zone = details.get('timezone') or profile.get('timezone')
        if (not address or not city or not isinstance(time_zone, str)
                or not _text(venue.get('name'))):
            _fail('spektrix_venue_location_unresolved')
        local = _local(instance.get('start'), time_zone)
        instant = _utc(instance.get('startUtc'))
        if local.astimezone(timezone.utc) != instant:
            _fail('spektrix_time_conflict')
        if not intervals[0][0] <= local.date() <= intervals[-1][1]:
            _fail('spektrix_instance_window_mismatch')
        minutes = event.get('duration')
        if type(minutes) is not int or minutes < 0 or minutes > 24 * 60:
            _fail('spektrix_duration_invalid')
        end_time = instant + timedelta(minutes=minutes) if minutes else None
        event_url = _event_url(event, profile)
        image_url = event.get('imageUrl') or event.get('thumbnailUrl')
        if not isinstance(image_url, str) or not image_url.startswith('https://'):
            image_url = None
        records.append({
            'id': client + ':' + instance['id'],
            'source_event_id': event_id,
            'source_instance_id': instance['id'],
            'source_venue_id': venue_id,
            'title': title,
            'starts_at': instant.isoformat(),
            'ends_at': end_time.isoformat() if end_time else None,
            'venue_name': _text(venue['name']),
            'venue_address': address,
            'venue_city': city,
            'timezone': time_zone,
            'event_url': event_url,
            'description': _text(event.get('description') or event.get('htmlDescription'))[:12000],
            'image_url': image_url,
            'spektrix_adapter_version': 1,
        })
    return {
        'complete': True,
        'client': client,
        'window_start': intervals[0][0].isoformat(),
        'window_end': intervals[-1][1].isoformat(),
        'instance_total': len(instances_by_id),
        'held_unsale_or_cancelled': rejected,
        'events': sorted(records, key=lambda row: (row['starts_at'], row['id'])),
    }


def collect(profile, start, end, fetch, *, deadline_at=None):
    """One-shot probe only. Large feeds require durable runner/checkpoint wiring.

    The normal publisher transport must be injected. A deadline/size failure
    is an incomplete snapshot, never a successful empty or truncated list.
    """
    client = _client(profile.get('client'))
    items = {'events': {}, 'instances': {}, 'plans': {}, 'venues': {}}

    def read(url):
        if deadline_at is not None and monotonic() >= deadline_at:
            _fail('spektrix_collection_deadline')
        return fetch(url, 'application/json')

    for first, last in windows(start, end):
        for family, limit in (('events', MAX_EVENTS), ('instances', MAX_INSTANCES)):
            rows = _items(read(api_url(client, family, start=first, end=last)), limit, family)
            _merge(items[family], rows, family, limit)
    active_plans = set()
    for instance in items['instances'].values():
        if instance.get('cancelled') is False and instance.get('isOnSale') is True:
            if not _id(instance.get('planId')):
                _fail('spektrix_plan_invalid')
            active_plans.add(instance['planId'])
    if len(active_plans) > MAX_PLANS:
        _fail('spektrix_plans_limit')
    for plan_id in sorted(active_plans):
        plan = _payload(read(api_url(client, 'plans', identity=plan_id)))
        if not isinstance(plan, dict) or plan.get('id') != plan_id:
            _fail('spektrix_plan_invalid')
        items['plans'][plan_id] = plan
    _merge(items['venues'], _items(read(api_url(client, 'venues')), MAX_VENUES, 'venues'),
           'venues', MAX_VENUES)
    return project(profile, list(items['events'].values()), list(items['instances'].values()),
                   list(items['plans'].values()), list(items['venues'].values()), start, end)
