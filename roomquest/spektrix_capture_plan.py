"""Deterministic Spektrix v3 capture phases, derived from real public instances.

This is a pure planning/projection helper for the eventual lease-backed worker.
No HTTP, SQL, registration, staging or source authorization happens here.
"""
from urllib.parse import urlsplit

from roomquest import feedzilla_capture_store as store
from roomquest import spektrix_v3 as api


def _fail(reason):
    raise ValueError('spektrix_capture_' + reason)


def _client(source, profile):
    if not isinstance(source, dict) or not isinstance(profile, dict):
        _fail('source_invalid')
    client = api._client(profile.get('client'))
    expected = api.api_url(client, 'events', start='2026-01-01', end='2026-01-01',
                           base=profile.get('api_base')).split('?', 1)[0]
    if (source.get('feed_url') != expected
            or source.get('platform_adapter') != 'spektrix'):
        _fail('source_invalid')
    return client


def base_tasks(source, profile, start, end):
    """Bounded seven-day events/instances requests and one public venues GET."""
    client = _client(source, profile)
    urls = []
    for first, last in api.windows(start, end):
        urls.append(api.api_url(client, 'events', start=first, end=last,
                                base=profile.get('api_base')))
        urls.append(api.api_url(client, 'instances', start=first, end=last,
                                base=profile.get('api_base')))
    urls.append(api.api_url(client, 'venues', base=profile.get('api_base')))
    return urls


def _read_base(source, profile, state):
    cursor = state['progress']
    expected = base_tasks(source, profile, cursor['window_start'], cursor['window_end'])
    if (len(state['pages']) < len(expected)
            or cursor['tasks'][:len(expected)] != expected
            or any(page['url'] != url for page, url in zip(state['pages'][:len(expected)], expected))):
        _fail('base_manifest_incomplete')
    events, instances, venues = {}, {}, {}
    for page in state['pages'][:len(expected)]:
        path = urlsplit(page['url']).path
        resource = path.split('/')[-1]
        if resource not in ('events', 'instances', 'venues'):
            _fail('base_manifest_invalid')
        limit = {'events': api.MAX_EVENTS, 'instances': api.MAX_INSTANCES,
                 'venues': api.MAX_VENUES}[resource]
        rows = api._items(page['body'], limit, resource)
        api._merge({'events': events, 'instances': instances,
                    'venues': venues}[resource], rows, resource, limit)
    for item in instances.values():
        if item.get('cancelled') is True or item.get('isOnSale') is False:
            continue
        parent = item.get('event')
        if (not isinstance(parent, dict) or parent.get('id') not in events
                or not api._id(item.get('planId'))):
            _fail('instance_identity_invalid')
    return events, instances, venues, expected


def plan_tasks(source, profile, envelope, *, at=None):
    """Only return plan URLs actually referenced by complete API instances."""
    state = store.decode(source, envelope, at=at)
    if (state['phase'] != 'fetch' or state['progress']['terminal_verified']
            or state['progress']['cursor'] != len(state['progress']['tasks'])):
        _fail('base_manifest_incomplete')
    _, instances, _, expected = _read_base(source, profile, state)
    if state['progress']['tasks'] != expected:
        _fail('base_manifest_invalid')
    plans = {row['planId'] for row in instances.values()
             if row.get('cancelled') is False and row.get('isOnSale') is True}
    if len(plans) >= api.MAX_PLANS:
        _fail('plan_limit')
    return [api.api_url(profile['client'], 'plans', identity=identity,
                        base=profile.get('api_base'))
            for identity in sorted(plans)]


def project(source, profile, envelope, *, at=None, cms_pages=None):
    """Project a complete authenticated *shape* of pages, not a staged result.

    The caller must separately verify publisher access, store CAS, the active
    worker lease, event links and actual staging receipts before publication.
    """
    state = store.decode(source, envelope, at=at)
    if state['phase'] != 'project':
        _fail('not_complete')
    events, instances, venues, expected = _read_base(source, profile, state)
    client = _client(source, profile)
    plan_ids = {row['planId'] for row in instances.values()
                if row.get('cancelled') is False and row.get('isOnSale') is True}
    plan_urls = [api.api_url(client, 'plans', identity=p,
                             base=profile.get('api_base')) for p in sorted(plan_ids)]
    if (state['progress']['tasks'] != expected + plan_urls
            or len(state['pages']) != len(expected) + len(plan_urls)):
        _fail('plan_manifest_invalid')
    plans = {}
    for url, page in zip(plan_urls, state['pages'][len(expected):]):
        if page['url'] != url:
            _fail('plan_manifest_invalid')
        body = api._payload(page['body'])
        if not isinstance(body, dict) or body.get('id') != url.rsplit('/', 1)[-1]:
            _fail('plan_identity_invalid')
        api._merge(plans, [body], 'plans', api.MAX_PLANS)
    return api.project(profile, list(events.values()), list(instances.values()),
                       list(plans.values()), list(venues.values()),
                       state['progress']['window_start'],
                       state['progress']['window_end'], cms_pages=cms_pages)
