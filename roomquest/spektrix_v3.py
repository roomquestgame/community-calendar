"""Read-only Spektrix Web/Public v3 event and performance extraction.

This is a source-independent *collector core*, not admission to EventQuest.
Callers provide an audited client-name/profile, an existing robots-aware fetch
callback and verified first-party event links. The database must authorize
registration, checkpointing, staging and publication separately.

Spektrix's Web/Public events and instances list different objects; joining
them through instance.event.id, instance.planId and plan.venue.id is required
to avoid assigning a ticketing client's headquarters to every performance.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import date, datetime, timedelta, timezone
from html import unescape
import json
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_DAYS = 60
PAGE_DAYS = 60
MAX_EVENTS = 700
MAX_INSTANCES = 3000
MAX_VENUES = 150
MAX_PLANS = 120
MAX_BODY = 3_000_000
MAX_CONCURRENT_PLAN_REQUESTS = 3
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


def api_base(client, value=None):
    """Validate the exact v3 base advertised by a publisher page.

    The default retains the legacy central public host. A branded base must
    name this exact client and API version; provider admission separately
    proves that its hostname belongs to the publisher organization.
    """
    client = _client(client)
    value = value or 'https://system.spektrix.com/' + client + '/api/v3'
    try:
        parts = urlsplit(value)
    except (TypeError, ValueError):
        _fail('spektrix_api_base_invalid')
    expected = '/' + client + '/api/v3'
    if (not isinstance(value, str) or parts.scheme != 'https' or not parts.hostname
            or parts.username or parts.password or parts.port is not None
            or parts.path.rstrip('/') != expected or parts.query or parts.fragment):
        _fail('spektrix_api_base_invalid')
    return 'https://' + parts.hostname.casefold() + expected


def api_url(client, resource, *, start=None, end=None, identity=None, base=None):
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
    return api_base(client, base) + tail + query


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
    # A response at our ceiling could itself have been truncated by the
    # upstream API; never certify that as a complete calendar.
    if not isinstance(payload, list) or len(payload) >= maximum:
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
            # A recurring production may be returned by several consecutive
            # 7-day windows. The first/last instance *range* is window-relative;
            # title, public attributes and the event's real ID must still agree.
            transient = {'firstInstanceDateTime', 'lastInstanceDateTime',
                         'firstInstanceDateTimeUtc', 'lastInstanceDateTimeUtc',
                         'instanceDates'}
            previous = {k: v for k, v in entries[key].items() if k not in transient}
            current = {k: v for k, v in row.items() if k not in transient}
            if label != 'events' or previous != current:
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
    """Use publisher URL evidence, then Spektrix's documented event route."""
    link = event.get('webUrl') or profile.get('event_urls', {}).get(event['id'])
    if not link:
        value = event.get('webEventId')
        params = None
        if isinstance(value, str) and value and len(value) <= 100:
            params = {'WebEventId': value}
        else:
            numeric = re.match(r'^([0-9]{1,12})', event.get('id') or '')
            if numeric:
                params = {'EventId': numeric[1]}
        if params:
            base = api_base(profile['client'], profile.get('api_base'))
            link = base[:-len('/api/v3')] + '/website/EventDetails.aspx?' + urlencode(params)
    if not isinstance(link, str):
        _fail('spektrix_event_link_missing')
    parts = urlsplit(link)
    publisher = urlsplit(profile['publisher_url'])
    api = urlsplit(api_base(profile['client'], profile.get('api_base')))
    allowed = {publisher.hostname, api.hostname, *(profile.get('verified_event_hosts') or ())}
    if (parts.scheme != 'https' or parts.username or parts.password
            or parts.hostname not in allowed or parts.fragment
            or len(link) > 1200 or not parts.path):
        _fail('spektrix_event_link_unverified')
    return link


def _city(address):
    """Retain an API-published locality hint; geocoding remains downstream."""
    parts = [part.strip() for part in str(address or '').split(',') if part.strip()]
    if len(parts) >= 3 and re.fullmatch(r'[A-Z]{2}(?:\s+\d{5}(?:-\d{4})?)?', parts[-1]):
        return parts[-2]
    if len(parts) >= 2:
        postcode = re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', parts[-1], re.I)
        candidate = parts[-1][:postcode.start()].strip() if postcode else ''
        return candidate or parts[-2]
    return ''



def _ticket_extra(event):
    """Exclude explicit ticket products, not every supplementary experience.

    Spektrix supplementary events can also be real talks/tours. Soho's public
    API exposes no universal supplementary flag: its four ticket products have
    zero duration and all three listing categories explicitly blank. Require
    that metadata together with an unambiguous product title; missing categories,
    an uncategorized show, or a zero-duration real show alone is insufficient.
    """
    title = _text(event.get('name'))
    description = _text(event.get('description') or event.get('htmlDescription'))
    product_copy = _text((event.get('description') or '') + ' '
                         + (event.get('htmlDescription') or ''))
    # Multiple clients publish refund protection as a dated supplementary
    # product with a blank/generic venue. It is not a physical performance.
    # Require both its exact product label and explanatory API copy; neither
    # zero duration nor a supplementary flag alone excludes a real event.
    if (event.get('duration') == 0
            and re.fullmatch(r'Secure My Booking(?: Ticket Refund Protection)?'
                             r'|Ticket Protection Secure My Booking', title, re.I)
            and re.search(r'ticket (?:refund )?protection', product_copy, re.I)
            and re.search(r'protect your (?:tickets?|order)', product_copy, re.I)
            and re.search(r'refund', product_copy, re.I)):
        return True
    if (event.get('duration') == 0
            and re.fullmatch(r'Refreshments (?:Ice Creams|Drinks and Sweets)', title, re.I)
            and re.search(r'pre-buy their refreshments when buying tickets', product_copy, re.I)):
        return True
    if (event.get('duration') == 0
            and re.fullmatch(r'Ticket Bank Donation \([^()]+\)', title, re.I)
            and re.search(r'adding a donation to our Ticket Bank', product_copy, re.I)
            and re.search(r'cover someone else', product_copy, re.I)):
        return True
    if event.get('duration') == 0 and (
        (re.fullmatch(r'Pre[ -]?Order\s+Drinks?', title, re.I)
         and re.search(r'pre[ -]?order your drinks', description, re.I))
        or (re.fullmatch(r'Audio Description Headset', title, re.I)
            and re.search(r'pre[ -]?book your Audio Description headset', description, re.I))
        or (re.fullmatch(r'Captioning Facilities', title, re.I)
            and re.search(r'captioning facilities', description, re.I))
    ):
        return True
    categories = [f'attribute_WebsiteFilterCategory{i}' for i in (1, 2, 3)]
    if (event.get('duration') != 0
            or any(key not in event or event[key] != '' for key in categories)):
        return False
    title = _text(event.get('name'))
    return bool(re.fullmatch(
        r'Pre[ -]?Order\s*:?\s*(?:Drinks?(?:\s+(?:Downstairs|Main House))?|Pizza)'
        r'|Babes in Arms\s*\([^()]+\)', title, re.I))


def project(profile, events, instances, plans, venues, start, end, *, cms_pages=None):
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
    if (publisher.scheme != 'https' or not publisher.hostname
            or publisher.username or publisher.password):
        _fail('spektrix_publisher_invalid')
    events_by_id, instances_by_id, plans_by_id, venues_by_id = {}, {}, {}, {}
    _merge(events_by_id, _items(events, MAX_EVENTS, 'events'), 'events', MAX_EVENTS)
    _merge(instances_by_id, _items(instances, MAX_INSTANCES, 'instances'), 'instances', MAX_INSTANCES)
    _merge(plans_by_id, _items(plans, MAX_PLANS, 'plans'), 'plans', MAX_PLANS)
    _merge(venues_by_id, _items(venues, MAX_VENUES, 'venues'), 'venues', MAX_VENUES)
    if cms_pages is not None:
        # Craft CMS and other publisher pages may be the only trustworthy
        # deep-link evidence when Spektrix Event.webUrl is empty. Reconcile
        # against verified exact-title and performance-time evidence.
        from roomquest.spektrix_cms_links import resolve
        verified = resolve(profile['publisher_url'], list(events_by_id.values()),
                           list(instances_by_id.values()), cms_pages)
        prior = profile.get('event_urls') or {}
        if (not isinstance(prior, dict) or any(
                key in prior and prior[key] != url for key, url in verified.items())):
            _fail('spektrix_event_link_conflict')
        profile = dict(profile, event_urls={**prior, **verified})
    records = []
    rejected = 0
    ticket_extras = 0
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
        if _ticket_extra(event):
            ticket_extras += 1
            continue
        title = _text(event.get('name'))
        if not title:
            _fail('spektrix_event_title_missing')
        plan = plans_by_id.get(instance.get('planId'))
        venue_id = (plan.get('venue') or {}).get('id') if isinstance(plan, dict) else None
        venue = venues_by_id.get(venue_id)
        if not venue:
            _fail('spektrix_plan_venue_unresolved')
        # Some tenants attach many physical locations to one generic Venue and
        # expose the real place only through the performance Plan. A reviewed
        # plan override is therefore narrower and safer than permanently
        # assigning that generic venue ID to one address. Native Venue.address
        # remains authoritative whenever Spektrix supplies it.
        venue_details = (profile.get('verified_venues') or {}).get(venue_id) or {}
        plan_details = (profile.get('verified_plans') or {}).get(plan.get('id')) or {}
        address = _text(venue.get('address'))
        details = {}
        if not address:
            details = plan_details or venue_details
        if not address and details.get('address'):
            evidence = details.get('evidence_url')
            url = urlsplit(evidence) if isinstance(evidence, str) else None
            if (url is None or url.scheme != 'https' or url.hostname != publisher.hostname
                    or url.username or url.password):
                _fail('spektrix_venue_evidence_missing')
            address = _text(details['address'])
        venue_name = _text(details.get('name')) or _text(venue.get('name'))
        city = _text(details.get('city')) or _city(address)
        time_zone = details.get('timezone') or profile.get('timezone')
        # A complete UK postcode identifies the timezone, not coordinates.
        # Still compare the publisher's local time with startUtc below.
        postcode = re.search(r'\b(?:GIR\s*0AA|[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$', address, re.I)
        if postcode and time_zone in (None, '', 'Europe/London'):
            time_zone = 'Europe/London'
            # The shared UK geocoder accepts street, city, postcode. Preserve
            # the API's actual address, adding only the postcode separator.
            address = address[:postcode.start()].rstrip(', ') + ', ' + postcode.group().strip().upper()
            # Spektrix commonly returns a UK address without a country field.
            # The shared GB address contract accepts the publisher address
            # unchanged, plus an explicit country suffix; do not invent a
            # location or alter the venue identity.
            if (address.count(',') >= 3
                    and not re.search(r'(?:,|\s)(?:United Kingdom|UK|GB|Great Britain)\s*$', address, re.I)):
                address += ', United Kingdom'
        if not address or not venue_name:
            _fail('spektrix_venue_location_unresolved')
        instant = _utc(instance.get('startUtc'))
        if isinstance(time_zone, str):
            local = _local(instance.get('start'), time_zone)
            if local.astimezone(timezone.utc) != instant:
                _fail('spektrix_time_conflict')
            local_date = local.date()
        else:
            raw_local = instance.get('start')
            try:
                local_date = date.fromisoformat(raw_local[:10])
            except (TypeError, ValueError):
                _fail('spektrix_time_invalid')
        if not intervals[0][0] <= local_date <= intervals[-1][1]:
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
            'source_plan_id': plan.get('id'),
            'source_venue_id': venue_id,
            'title': title,
            'starts_at': instant.isoformat(),
            'ends_at': end_time.isoformat() if end_time else None,
            'venue_name': venue_name,
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
        'excluded_ticket_extras': ticket_extras,
        'events': sorted(records, key=lambda row: (row['starts_at'], row['id'])),
    }


def collect(profile, start, end, fetch, *, deadline_at=None, cms_pages=None):
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

    requests = []
    for first, last in windows(start, end):
        for family, limit in (('events', MAX_EVENTS), ('instances', MAX_INSTANCES)):
            requests.append((family, limit, api_url(
                client, family, start=first, end=last,
                base=profile.get('api_base'))))
    requests.append(('venues', MAX_VENUES, api_url(
        client, 'venues', base=profile.get('api_base'))))

    def read_resource(request):
        family, limit, url = request
        return family, limit, _items(read(url), limit, family)

    # These resources are independent parts of the same complete snapshot.
    # The injected shared transport still spaces starts and applies the exact
    # host, robots and deadline policy; this only overlaps publisher response
    # time so staging retains part of the ordinary worker budget.
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PLAN_REQUESTS) as pool:
        futures = [pool.submit(copy_context().run, read_resource, request)
                   for request in requests]
        for future in futures:
            family, limit, rows = future.result()
            _merge(items[family], rows, family, limit)
    active_plans = set()
    for instance in items['instances'].values():
        if instance.get('cancelled') is False and instance.get('isOnSale') is True:
            if not _id(instance.get('planId')):
                _fail('spektrix_plan_invalid')
            active_plans.add(instance['planId'])
    if len(active_plans) > MAX_PLANS:
        _fail('spektrix_plans_limit')
    if len(items['venues']) == 1:
        # With exactly one API venue every client plan necessarily belongs to
        # that venue. Avoid redundant seating-plan downloads; they can be large
        # and publisher pacing must fit the ordinary worker deadline.
        venue_id = next(iter(items['venues']))
        items['plans'] = {
            plan_id: {'id': plan_id, 'venue': {'id': venue_id}}
            for plan_id in active_plans
        }
    else:
        # A multi-venue client requires its referenced seating plans to resolve
        # each performance to the correct physical Venue. These plan documents
        # can be comparatively expensive even though only venue.id is needed.
        # Keep concurrency deliberately small; the shared publisher transport
        # still applies its host pacing, robots and deadline policy to every
        # request. map() preserves deterministic plan/result ordering and any
        # failed request still holds the complete snapshot.
        plan_ids = sorted(active_plans)

        def read_plan(plan_id):
            return plan_id, _payload(read(api_url(
                client, 'plans', identity=plan_id, base=profile.get('api_base'))))

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PLAN_REQUESTS) as pool:
            futures = [pool.submit(copy_context().run, read_plan, plan_id)
                       for plan_id in plan_ids]
            for future in futures:
                plan_id, plan = future.result()
                if not isinstance(plan, dict) or plan.get('id') != plan_id:
                    _fail('spektrix_plan_invalid')
                items['plans'][plan_id] = plan
    return project(profile, list(items['events'].values()), list(items['instances'].values()),
                   list(items['plans'].values()), list(items['venues'].values()), start, end,
                   cms_pages=cms_pages)

