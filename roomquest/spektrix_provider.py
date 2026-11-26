"""Native collection for ordinary public Spektrix v3 feeds.

A canonical Spektrix URL already contains the exact client identity. Public
Event, Instance, Plan and Venue resources provide the remaining collection
facts. Stored profiles are optional reviewed overrides, not an admission gate.
"""
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest import spektrix_v3
from roomquest.registration_formats import source_key

SOURCE = re.compile(
    r'^https://([a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?)/'
    r'([a-z][a-z0-9_-]{1,59})/api/v3/events$')
MAX_PROBE_DAYS = spektrix_v3.MAX_DAYS
MAX_PROBE_EVENTS = 150


def _fail(reason):
    raise ValueError('spektrix_provider_' + reason)


def family(url):
    """Exact, canonical read-only event collection URL only."""
    match = SOURCE.fullmatch(url) if isinstance(url, str) else None
    if not match:
        return False
    host = match[1]
    return (host in ('system.spektrix.com', 'api.system.spektrix.com')
            or host.split('.', 1)[0] in ('tickets', 'ticketing', 'boxoffice',
                                         'booking', 'book'))


def _organization_domain(host):
    parts = host.casefold().split('.')
    if (len(parts) >= 3 and parts[-1] in ('uk', 'au', 'nz')
            and parts[-2] in ('co', 'org', 'ac', 'net', 'gov')):
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host.casefold()


def profile(url, stored=None):
    """Build the ordinary public-feed profile directly from its canonical URL."""
    match = SOURCE.fullmatch(url) if isinstance(url, str) else None
    if not match or not family(url):
        _fail('source_invalid')
    api_base = url[:-len('/events')]
    value = {
        'client': match[2],
        'api_base': api_base,
        'publisher_url': api_base[:-len('/api/v3')] + '/website/',
        'event_urls': {},
        'verified_venues': {},
        'verified_plans': {},
    }
    # Publisher-hosted ticketing APIs commonly return their own main-site CMS
    # links in webUrl. Admit only the exact parent organization and its www
    # alias; this does not add fetch hosts or authorize central Spektrix access.
    host = match[1]
    parent = host.split('.', 1)[1] if '.' in host else ''
    if (not stored
            and host.split('.', 1)[0] in ('tickets', 'ticketing', 'boxoffice', 'booking', 'book')
            and parent == _organization_domain(host)
            and parent != 'spektrix.com'):
        value['verified_event_hosts'] = [parent, 'www.' + parent]
    if stored:
        if not isinstance(stored, dict):
            _fail('profile_invalid')
        value.update(stored)
    return value


def validate(source, value):
    if (not isinstance(source, dict) or source.get('kind') != 'json'
            or source.get('platform_adapter') != 'spektrix'):
        _fail('source_invalid')
    url = source.get('feed_url')
    match = SOURCE.fullmatch(url) if isinstance(url, str) else None
    value = profile(url, value)
    if (not match or source.get('source_key') != source_key(url)
            or value.get('client') != match[2]):
        _fail('source_invalid')
    api_base = spektrix_v3.api_base(value['client'], value.get('api_base'))
    if url != api_base + '/events':
        _fail('source_invalid')

    publisher = urlsplit(value.get('publisher_url'))
    api = urlsplit(api_base)
    central = api.hostname in ('system.spektrix.com', 'api.system.spektrix.com')
    if (publisher.scheme != 'https' or not publisher.hostname
            or publisher.username or publisher.password or publisher.fragment
            or not publisher.path
            or (not central and _organization_domain(api.hostname)
                != _organization_domain(publisher.hostname))):
        _fail('publisher_invalid')

    zone = value.get('timezone')
    if zone is not None:
        try:
            ZoneInfo(zone)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            _fail('timezone_invalid')

    links = value.get('event_urls') or {}
    if not isinstance(links, dict) or len(links) > 1000:
        _fail('event_links_invalid')
    allowed = {publisher.hostname, api.hostname, *(value.get('verified_event_hosts') or ())}
    for key, link in links.items():
        candidate = urlsplit(link) if isinstance(link, str) else None
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9-]{10,80}', key)
                or candidate is None or candidate.scheme != 'https'
                or candidate.hostname not in allowed or not candidate.path
                or candidate.username or candidate.password or candidate.fragment):
            _fail('event_links_invalid')

    venues = value.get('verified_venues') or {}
    if not isinstance(venues, dict) or len(venues) > 150:
        _fail('venues_invalid')
    plans = value.get('verified_plans', {})
    if plans is None:
        plans = {}
    if (not isinstance(plans, dict) or len(plans) > spektrix_v3.MAX_PLANS
            or any(not re.fullmatch(r'[A-Za-z0-9-]{10,80}', key)
                   or not isinstance(details, dict)
                   for key, details in plans.items())):
        _fail('plans_invalid')
    return value


def stageable(source, data, *, retain_original=False):
    """Convert a complete v3 snapshot into the shared ordinary stage records."""
    if not isinstance(data, dict) or data.get('complete') is not True:
        _fail('snapshot_incomplete')
    rows = data.get('events')
    if not isinstance(rows, list) or len(rows) > 3000:
        _fail('snapshot_invalid')
    from roomquest.mapsee_adapter import record
    from roomquest.preview_worker import event_image
    out = []
    for row in rows:
        if (not isinstance(row, dict) or not row.get('id')
                or not row.get('event_url')
                or not row.get('starts_at')):
            _fail('event_invalid')
        converted = record(
            row['title'], row['starts_at'], row.get('ends_at'),
            row.get('venue_name'), row.get('venue_address', ''), row.get('venue_city', ''),
            row['event_url'], row['id'], tz=row.get('timezone'))
        if converted is None:
            continue
        if row.get('timezone'):
            converted['timezone'] = row['timezone']
        converted['venue_name'] = str(row.get('venue_name') or '')[:160]
        # Retain native location identity through the ordinary stage writer.
        # A generic Venue may be reused by physically distinct Plans. Never
        # fill a blank name with the publisher's organization or main building.
        converted['spektrix_location'] = {
            'version': 1,
            **{key: row.get(key, '') for key in (
                'source_event_id', 'source_instance_id', 'source_plan_id', 'source_venue_id')},
            **{key: str(row.get(key, ''))[:400 if key.endswith('address') else 160]
               for key in ('source_plan_name', 'source_venue_name', 'source_venue_address')},
            'venue_name': converted['venue_name'],
            'venue_address': converted['venue_address'],
        }
        from roomquest.event_description import description
        converted['description'] = description(row.get('description', ''))
        if row.get('image_url'):
            image = event_image(row['image_url'], row['event_url'])
            if image:
                converted['image_url'] = image
        if retain_original:
            converted['collector_event_content_v1'] = {
                'version': 1,
                'event_id': converted['id'],
                'facts': {
                    'title': row['title'], 'description': converted['description'],
                    'starts_at_utc': row['starts_at'], 'ends_at_utc': row.get('ends_at'),
                    'is_all_day': False, 'publisher_status': 'scheduled',
                    'event_url': row.get('source_event_url'),
                    'source_image_url': converted.get('image_url'),
                    'provider_venue_id': row.get('source_venue_id'),
                    'venue_name': row.get('source_venue_name') or None,
                    'venue_address': row.get('source_venue_address') or None,
                },
            }
        out.append(converted)
    return sorted(out, key=lambda row: (row['starts_at'], row['id']))


def _collect(source, value, fetch, days, *, deadline_at=None, today=None, retain_original=False):
    value = validate(source, value)
    if today is None:
        today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days - 1)
    snapshot = spektrix_v3.collect(value, today, end, fetch, deadline_at=deadline_at)
    return stageable(source, snapshot, retain_original=retain_original)


def probe(source, value, fetch, *, deadline_at=None, today=None):
    """Prove the same bounded window used by recurring collection.

    A shorter probe incorrectly defers calendars whose first performance is
    later in the ordinary 60-day window. Keep the same request and size bounds,
    venue evidence and complete-snapshot validation as recurring collection.
    """
    return _collect(source, value, fetch, MAX_PROBE_DAYS,
                    deadline_at=deadline_at, today=today)


def collect(source, value, fetch, *, deadline_at=None, today=None, retain_original=False):
    """Complete rolling 60-day snapshot through the ordinary provider dispatch."""
    return _collect(source, value, fetch, spektrix_v3.MAX_DAYS,
                    deadline_at=deadline_at, today=today, retain_original=retain_original)
