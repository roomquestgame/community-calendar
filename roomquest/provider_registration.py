"""Registration and recurring collection share one bounded provider dispatch."""
import json
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest import (chambermate, eventon, legistar, mapsee_adapter, revize,
                       south_carolina_parks, spektrix_provider, tickera_provider,
                       ticketweb_event_discovery, venuepilot_provider)
from roomquest.registration_formats import source_key

PARK = re.compile(r'https://southcarolinaparks\.com/api/events#park=([1-9][0-9]{0,9})')
TENANT = re.compile(r'https://api\.chambermate\.com/core/biz/webPresence/getEventsInfo\?'
                    r'websiteShorthand=([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)&websiteDomain=\1\.chambermate\.com')
LEGISTAR = re.compile(r'https://webapi\.legistar\.com/v1/([a-z0-9-]+)/events')
SOCRATA = re.compile(r'/resource/[a-z0-9]{4}-[a-z0-9]{4}\.json')
REVIZE = '/_assets_/plugins/revizeCalendar/calendar_data_handler.php'
FAMILIES = {'chambermate', 'eventon', 'event_discovery', 'growthzone', 'legistar',
            'socrata', 'revize', 'south_carolina_parks', 'spektrix', 'tickera', 'venuepilot'}
DEFAULT_VENUE_FAMILIES = {'event_discovery', 'tickera'}


def apply_verified_default_venue(source, records):
    """Hand a verified single-venue default to the shared staging policy.

    The database remains responsible for matching the name to its reviewed
    coordinates. A provider snapshot with any publisher venue evidence is
    left unchanged, so multi-venue calendars continue through venue lookup.
    """
    venue = source.get('publisher_default_venue')
    evidence = source.get('publisher_default_evidence')
    lat = source.get('publisher_default_lat')
    lng = source.get('publisher_default_lng')
    if (source.get('platform_adapter') not in DEFAULT_VENUE_FAMILIES
            or not isinstance(records, list) or not records
            or not isinstance(venue, str) or not 3 <= len(venue.strip()) <= 160
            or not isinstance(evidence, str) or not 12 <= len(evidence.strip()) <= 1000
            or not isinstance(lat, (int, float)) or isinstance(lat, bool) or not -90 <= lat <= 90
            or not isinstance(lng, (int, float)) or isinstance(lng, bool) or not -180 <= lng <= 180):
        return records
    if any(not isinstance(row, dict) or any((
            str(row.get('venue_name') or '').strip(),
            str(row.get('venue_address') or '').strip(),
            str(row.get('venue_city') or '').strip(),
            row.get('lat') is not None,
            row.get('lng') is not None,
    )) for row in records):
        return records
    return [{**row, 'venue_name': venue.strip()} for row in records]


def family(url, body=None):
    parts = urlsplit(url)
    if spektrix_provider.family(url):
        return 'spektrix'
    if venuepilot_provider.family(url):
        return 'venuepilot'
    if body and eventon.supports_listing(url, body):
        return 'eventon'
    if body and ticketweb_event_discovery.supports_listing(url, body):
        return 'event_discovery'
    if body and tickera_provider.supports_listing(url, body):
        return 'tickera'
    if TENANT.fullmatch(url):
        return 'chambermate'
    if PARK.fullmatch(url):
        return 'south_carolina_parks'
    if LEGISTAR.fullmatch(url):
        return 'legistar'
    if SOCRATA.fullmatch(parts.path) and not parts.fragment and not parts.query:
        return 'socrata'
    if parts.path == REVIZE and parts.query and not parts.fragment:
        return 'revize'
    if parts.path == '/api/events' and not parts.query and not parts.fragment and body:
        if re.search(r'<ArrayOfEventDisplay(?:\s|>)', body[:4096]):
            return 'growthzone'
    return None


def timezone(config):
    name = config.get('timezone')
    try:
        ZoneInfo(name)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError('source_timezone_required') from exc
    return name


def collect(url, adapter, fetch, *, deadline, profile=None, body=None, registration_probe=False,
            retain_original=False):
    from roomquest.preview_worker import public_source_url
    if not public_source_url(url):
        raise ValueError('invalid_provider_endpoint')
    if adapter == 'growthzone' and body is None:
        body = fetch(url, 'application/xml,text/xml')
    if adapter == 'eventon':
        source = {'source_key': source_key(url), 'feed_url': url,
                  'platform_adapter': adapter, 'kind': 'json'}
        return eventon.collect(source, fetch, body=body, deadline_at=deadline)
    if adapter in ('event_discovery', 'tickera'):
        source = {'source_key': source_key(url), 'feed_url': url,
                  'platform_adapter': adapter, 'kind': 'json'}
        if adapter == 'event_discovery' and isinstance(profile, dict):
            source['publisher_event_timezone'] = profile.get('publisher_event_timezone')
        module = ticketweb_event_discovery if adapter == 'event_discovery' else tickera_provider
        return module.collect(source, fetch, body=body, deadline_at=deadline,
                              retain_original=retain_original)
    if family(url, body) != adapter:
        raise ValueError('provider_endpoint_mismatch')
    source = {'source_key': source_key(url), 'feed_url': url, 'platform_adapter': adapter,
              'kind': 'xml' if adapter == 'growthzone' else 'json'}
    config = profile or {}
    if adapter == 'spektrix':
        # Public Spektrix feeds carry their client identity in the canonical
        # URL and publish venue/address facts through the same v3 API. A stored
        # profile may add reviewed overrides, but it is not a prerequisite for
        # recognizing or collecting an ordinary public feed.
        config = spektrix_provider.profile(url, profile)
        if registration_probe:
            return spektrix_provider.probe(source, config, fetch, deadline_at=deadline)
        return spektrix_provider.collect(source, config, fetch, deadline_at=deadline,
                                         retain_original=retain_original)
    if adapter == 'venuepilot':
        return venuepilot_provider.collect(source, fetch, stored=config, deadline_at=deadline)
    if adapter == 'south_carolina_parks':
        park_id = PARK.fullmatch(url)[1]
        return south_carolina_parks.collect(dict(source, source_key='south_carolina_parks_' + park_id),
                                            fetch, deadline_at=deadline)
    if adapter == 'chambermate':
        # The API expects a bounded date window. It publishes its own timezone.
        seed = chambermate.source_config(dict(source, timezone='UTC'))
        payload = json.loads(fetch(chambermate.events_url(seed), 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
            raise ValueError('invalid_chambermate_payload')
        source['timezone'] = chambermate._timezone(payload['data'].get('timeZoneIANAId'))
        return chambermate.parse(payload, source, retain_original=retain_original)
    if adapter == 'legistar':
        client = LEGISTAR.fullmatch(url)[1]
        spec = {'client': client, 'url': url, 'timezone': timezone(config)}
        return legistar.collect(source, fetch, spec=spec, deadline_at=deadline)
    if adapter == 'socrata':
        # SODA datasets have publisher-defined column names and local-time conventions.
        if not isinstance(config.get('map'), dict) or not {'start','title'} <= config['map'].keys():
            raise ValueError('socrata_field_mapping_required')
        if not config.get('order'):
            raise ValueError('socrata_stable_order_required')
        timezone(config)
        return mapsee_adapter.collect(source, {'type':'opendata', 'config':config}, fetch)
    if adapter == 'revize':
        listing = config.get('calendar_url')
        if not listing or not public_source_url(listing) or urlsplit(listing).netloc != urlsplit(url).netloc:
            raise ValueError('revize_calendar_url_required')
        return revize.parse(fetch(url, 'application/json'), zone=timezone(config), calendar=listing,
                            source_key=source['source_key'], deadline_at=deadline)
    from roomquest.chambermaster import collect as collect_chamber
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError('invalid_chambermaster_xml') from exc
    if root.tag != 'ArrayOfEventDisplay' or len(root) > 500 or any(e.tag != 'EventDisplay' for e in root):
        raise ValueError('invalid_chambermaster_collection')
    for event in list(root):
        if 'Public' not in (event.findtext('VisibilityFlags') or '').split():
            root.remove(event)
    source['timezone'] = timezone(config)
    return collect_chamber(source, ElementTree.tostring(root, encoding='unicode'), deadline,
                           fetcher=lambda target, accept, **kwargs: fetch(target, accept),
                           retain_original=retain_original)


def read_profile(url, adapter, rpc):
    if adapter in ('south_carolina_parks', 'chambermate', 'eventon'):
        return {}
    return rpc('community_collector_feed_profile', {'p_url':url, 'p_adapter':adapter}) or {}
