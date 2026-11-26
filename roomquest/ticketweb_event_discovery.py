"""Collect TicketWeb's standard Event Discovery WordPress calendar output."""
from datetime import datetime, timedelta
import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from collections import Counter
import logging

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record
from roomquest.registration_formats import provider_calendar_destination

PLUGIN = '/wp-content/plugins/event-discovery/'
ACTION = 'get_events_artist_calendar'
LOGGER = logging.getLogger(__name__)


class ParsedEvents(list):
    """Valid rows plus bounded completeness evidence for the provider snapshot."""

    def __init__(self, rows, *, rejected=None, complete=True):
        super().__init__(rows)
        self.rejected = dict(rejected or {})
        self.complete = complete


def _origin(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('invalid_event_discovery_calendar')
    return urlunsplit((parts.scheme, parts.netloc, '/', '', ''))


def calendar_destination(url, page):
    if PLUGIN not in page:
        return None
    _origin(url)
    return provider_calendar_destination(url, page)


def contract(url, page):
    if PLUGIN not in page:
        raise ValueError('event_discovery_calendar_missing')
    origin = _origin(url)
    endpoint = origin + 'wp-admin/admin-ajax.php'
    if endpoint not in page or f"action: '{ACTION}'" not in page:
        raise ValueError('event_discovery_calendar_missing')
    nonce = re.search(r"\bnonce\s*:\s*'([a-zA-Z0-9]{8,24})'", page)
    params = re.search(r"\bparams\s*:\s*'(\{.*?\})'\s*,\s*\n\s*monthview", page, re.S)
    if nonce is None or params is None or len(params[1]) > 40_000:
        raise ValueError('event_discovery_calendar_missing')
    try:
        settings = json.loads(html.unescape(params[1]))
        zone = settings['current_datetime']['timezone']
        ZoneInfo(zone)
    except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError) as exc:
        raise ValueError('invalid_event_discovery_calendar') from exc
    if settings.get('type') not in ('calendar', 'calendar2', 'calendar3'):
        raise ValueError('invalid_event_discovery_calendar')
    return {'endpoint': endpoint, 'nonce': nonce[1], 'params': json.dumps(settings, separators=(',', ':')),
            'timezone': zone}


def supports_listing(url, page):
    try:
        contract(url, page)
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def form(spec, start, end):
    return {'action': ACTION, 'nonce': spec['nonce'], 'start': start, 'end': end,
            'params': spec['params'], 'monthview': 'standard', 'calcount': '1',
            'statefilter': '', 'cityfilter': '', 'locationfilter': '', 'showmobilelist': 'true'}


def valid_form(value):
    """Validate the display-only request before the shared transport can POST it."""
    if not isinstance(value, dict) or set(value) != {
            'action', 'nonce', 'start', 'end', 'params', 'monthview', 'calcount',
            'statefilter', 'cityfilter', 'locationfilter', 'showmobilelist'}:
        return False
    if (value.get('action') != ACTION or value.get('monthview') != 'standard'
            or value.get('calcount') != '1' or value.get('statefilter') != ''
            or value.get('cityfilter') != '' or value.get('locationfilter') != ''
            or value.get('showmobilelist') != 'true'
            or not re.fullmatch(r'[a-zA-Z0-9]{8,24}', str(value.get('nonce') or ''))
            or not isinstance(value.get('params'), str) or len(value['params']) > 40_000):
        return False
    try:
        start = datetime.strptime(value['start'], '%Y-%m-%d').date()
        end = datetime.strptime(value['end'], '%Y-%m-%d').date()
        settings = json.loads(value['params'])
        zone = settings['current_datetime']['timezone']
        ZoneInfo(zone)
    except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError):
        return False
    return settings.get('type') in ('calendar', 'calendar2', 'calendar3') and 1 <= (end - start).days <= 62


def _plain_fragment(value):
    return BeautifulSoup(str(value or ''), 'html.parser').get_text(' ', strip=True)


def parse(payload, *, url, zone):
    try:
        envelope = json.loads(payload)
        events = envelope['events']
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('invalid_event_discovery_calendar') from exc
    if not isinstance(events, list) or len(events) > 500:
        raise ValueError('invalid_event_discovery_calendar')
    if not events:
        return ParsedEvents([])  # A valid empty refresh is distinct from malformed rows.
    host = urlsplit(url).hostname
    rows = []
    rejected = Counter()
    incomplete = False
    for event in events:
        if not isinstance(event, dict):
            rejected['non_object'] += 1
            incomplete = True
            continue
        event_url = html.unescape(str(event.get('url') or ''))
        parts = urlsplit(event_url)
        if (parts.scheme != 'https' or parts.username or parts.password
                or parts.hostname not in (host, 'www.ticketweb.com', 'ticketweb.com')):
            rejected['untrusted_url'] += 1
            continue
        stamp = str(event.get('sortkey') or '')
        try:
            datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            rejected['invalid_start'] += 1
            incomplete = True
            continue
        venue = _plain_fragment(event.get('venue'))
        image_node = BeautifulSoup(str(event.get('imageUrl') or ''), 'html.parser').find('img', src=True)
        try:
            item = record(html.unescape(str(event.get('title') or '')), stamp, None, venue, '', '',
                          event_url, event_url + ':' + stamp, tz=zone)
        except (TypeError, ValueError, OverflowError):
            rejected['invalid_event'] += 1
            incomplete = True
            continue
        if item is not None:
            if image_node:
                image = urljoin(url, image_node['src'])
                image_parts = urlsplit(image)
                if image_parts.scheme == 'https' and image_parts.hostname and not image_parts.username and not image_parts.password:
                    item['image_url'] = image
            rows.append(item)
    if not rows:
        raise ValueError('invalid_event_discovery_calendar')
    return ParsedEvents(rows, rejected=rejected, complete=not incomplete)


def collect(source, fetch, *, body=None, deadline_at=None):
    listing = source.get('feed_url')
    if source.get('platform_adapter') != 'event_discovery' or source.get('kind') != 'json':
        raise ValueError('unregistered_event_discovery_source')
    try:
        page = body if body is not None else fetch(listing, 'text/html,application/xhtml+xml')
        spec = contract(listing, page)
    except TypeError as exc:
        raise ValueError('event_discovery_contract_type_error') from exc
    today = datetime.now(ZoneInfo(spec['timezone'])).date()
    end = today + timedelta(days=61)
    try:
        payload = fetch(spec['endpoint'], 'application/json', calendar_form=form(spec, today.isoformat(), end.isoformat()))
    except TypeError as exc:
        raise ValueError('event_discovery_transport_type_error') from exc
    try:
        records = parse(payload, url=listing, zone=spec['timezone'])
        if records.rejected:
            LOGGER.warning('event_discovery_rows_rejected host=%s reasons=%s',
                           urlsplit(listing).hostname,
                           json.dumps(records.rejected, sort_keys=True, separators=(',', ':')))
        if not records.complete:
            # Preserve the last complete snapshot. A malformed first-party row
            # cannot be interpreted as an event withdrawal.
            raise ValueError('incomplete_event_discovery_snapshot')
        return records
    except TypeError as exc:
        raise ValueError('event_discovery_parse_type_error') from exc
