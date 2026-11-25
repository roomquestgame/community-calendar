"""Publisher-advertised branded Spektrix API inside registered HTML capture.

The submitted publisher listing remains the source.  Its first response must
advertise one exact same-organization branded v3 base before this traversal can
leave the listing host.  Requests, receipts, staging and publication continue
through the existing registered-HTML checkpoint; this module owns no queue,
lease, source registration or network transport.
"""
from datetime import datetime, timedelta
from html import unescape
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest import spektrix_discovery as discovery
from roomquest import spektrix_provider as provider
from roomquest import spektrix_v3 as api

VERSION = 'registered_html_spektrix_v1'
ZONE = 'Europe/London'
POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)


def _fail(reason):
    raise ValueError('html_spektrix_' + reason)


def _candidate(publisher_url, html):
    found = discovery.discover(publisher_url, html)
    rows = found.get('candidates') if isinstance(found, dict) else None
    if (found.get('status') != 'unverified' or not isinstance(rows, list)
            or len(rows) != 1 or rows[0].get('evidence_type') != 'first_party_api'
            or not isinstance(rows[0].get('api_base'), str)):
        return None
    row = rows[0]
    base = api.api_base(row.get('client'), row['api_base'])
    publisher, branded = urlsplit(publisher_url), urlsplit(base)
    if (not publisher.hostname or not publisher.hostname.endswith('.uk')
            or branded.hostname in discovery.THIRD_PARTY
            or discovery._organization_domain(branded.hostname)
            != discovery._organization_domain(publisher.hostname)):
        return None
    return {'client': row['client'], 'api_base': base,
            'publisher_url': publisher_url, 'country': 'GB', 'timezone': ZONE}


def supports_listing(publisher_url, html):
    """True only for one branded, same-organization, UK public v3 base."""
    try:
        return _candidate(publisher_url, html) is not None
    except (ValueError, TypeError, KeyError):
        return False


def verified_api_host(publisher_url, html, target):
    """Return the evidenced host only when *target* is a bounded v3 GET."""
    try:
        profile = _candidate(publisher_url, html)
        if profile is None:
            return None
        expected = profile['api_base'] + '/'
        if not isinstance(target, str) or not target.startswith(expected):
            return None
        parts = urlsplit(target)
        resource = parts.path[len(urlsplit(profile['api_base']).path):].lstrip('/')
        if (resource not in ('events', 'instances', 'venues')
                and not re.fullmatch(r'plans/[A-Za-z0-9-]{10,80}', resource)):
            return None
        if resource in ('events', 'instances') and not parts.query:
            return None
        if resource.startswith('plans/') or resource == 'venues':
            if parts.query:
                return None
        return parts.hostname
    except (ValueError, TypeError, KeyError):
        return None


def transport_hosts(source, target):
    """Fail closed transport scope for requests selected by this parser."""
    publisher = source.get('feed_url') if isinstance(source, dict) else None
    try:
        home, requested = urlsplit(publisher), urlsplit(target)
        if (home.scheme != 'https' or requested.scheme != 'https'
                or not home.hostname or not requested.hostname
                or requested.username or requested.password):
            _fail('request_scope_invalid')
        if requested.hostname == home.hostname:
            return (home.hostname,)
        path = requested.path
        match = re.fullmatch(
            r'/([a-z][a-z0-9_-]{1,59})/api/v3/'
            r'(?:events|instances|venues|plans/[A-Za-z0-9-]{10,80})', path)
        if (not match or discovery._organization_domain(requested.hostname)
                != discovery._organization_domain(home.hostname)
                or requested.hostname in discovery.THIRD_PARTY):
            _fail('request_scope_invalid')
        return (requested.hostname,)
    except (ValueError, TypeError, KeyError):
        _fail('request_scope_invalid')


def _today():
    return datetime.now(ZoneInfo(ZONE)).date()


def _city(raw):
    """Read a postal town only from publisher punctuation/newline evidence."""
    if not isinstance(raw, str) or len(raw) > 500:
        return ''
    text = unescape(re.sub(r'<br\s*/?>', ', ', raw, flags=re.I))
    text = re.sub(r'[\r\n]+', ', ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    parts = [re.sub(r'\s+', ' ', part).strip(' ,')
             for part in text.split(',') if part.strip(' ,')]
    if len(parts) < 2:
        return ''
    for index, part in enumerate(parts):
        match = POSTCODE.search(part)
        if not match:
            continue
        prefix = part[:match.start()].strip(' ,')
        candidate = prefix or (parts[index - 1] if index else '')
        if (index == 0 or not candidate or len(candidate) > 60
                or not re.fullmatch(r"[A-Za-z][A-Za-z .'’\-]{1,59}", candidate)):
            return ''
        return candidate
    return ''


def stream(source, publisher_url, listing_html, *, deadline_at=None):
    """Yield one complete 60-day v3 traversal and return ordinary HTML rows."""
    profile = _candidate(publisher_url, listing_html)
    if profile is None:
        _fail('discovery_invalid')
    start, end = _today(), _today() + timedelta(days=59)
    events, instances, venues, plans = {}, {}, {}, {}

    def check():
        if deadline_at is not None and monotonic() >= deadline_at:
            _fail('collection_deadline')

    def read(resource, url, maximum):
        check()
        body = yield (url, 'application/json')
        check()
        rows = api._items(body, maximum, resource)
        api._merge({'events': events, 'instances': instances,
                    'venues': venues}[resource], rows, resource, maximum)

    for first, last in api.windows(start, end):
        yield from read('events', api.api_url(profile['client'], 'events', start=first,
                                              end=last, base=profile['api_base']),
                        api.MAX_EVENTS)
        yield from read('instances', api.api_url(profile['client'], 'instances', start=first,
                                                 end=last, base=profile['api_base']),
                        api.MAX_INSTANCES)
    yield from read('venues', api.api_url(profile['client'], 'venues',
                                          base=profile['api_base']), api.MAX_VENUES)

    active = set()
    for instance in instances.values():
        if instance.get('cancelled') is False and instance.get('isOnSale') is True:
            plan_id = instance.get('planId')
            if not api._id(plan_id):
                _fail('plan_invalid')
            active.add(plan_id)
    if len(active) > api.MAX_PLANS:
        _fail('plan_limit')
    for plan_id in sorted(active):
        check()
        target = api.api_url(profile['client'], 'plans', identity=plan_id,
                             base=profile['api_base'])
        body = yield (target, 'application/json')
        value = api._payload(body)
        if not isinstance(value, dict) or value.get('id') != plan_id:
            _fail('plan_invalid')
        plans[plan_id] = value

    locations = {}
    for venue_id, venue in venues.items():
        city = _city(venue.get('address'))
        if city:
            locations[venue_id] = {'city': city, 'timezone': ZONE}
    profile['verified_venues'] = locations
    snapshot = api.project(profile, list(events.values()), list(instances.values()),
                           list(plans.values()), list(venues.values()), start, end)
    rows = provider.stageable(source, snapshot)
    from roomquest.registered_native_content import attach_spektrix
    for row in rows:
        attach_spektrix(row, source, client=profile['client'],
                        api_base=profile['api_base'],
                        description_value=row.get('description'),
                        image_value=row.get('image_url'))
    return rows
