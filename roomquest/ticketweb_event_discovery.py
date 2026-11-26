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
CALENDAR_ACTION = 'get_events_for_calendar'
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
    actions = set(re.findall(r"\baction\s*:\s*['\"](get_events_(?:artist_calendar|for_calendar))['\"]", page))
    if endpoint not in page or len(actions) != 1:
        raise ValueError('event_discovery_calendar_missing')
    action = next(iter(actions))
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
    if action == CALENDAR_ACTION and settings['type'] != 'calendar':
        raise ValueError('invalid_event_discovery_calendar')
    return {'endpoint': endpoint, 'action': action, 'nonce': nonce[1], 'params': json.dumps(settings, separators=(',', ':')),
            'timezone': zone}


def supports_listing(url, page):
    try:
        contract(url, page)
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def form(spec, start, end):
    return {'action': spec['action'], 'nonce': spec['nonce'], 'start': start, 'end': end,
            'params': spec['params'], 'monthview': 'standard', 'calcount': '1',
            'statefilter': '', 'cityfilter': '', 'locationfilter': '', 'showmobilelist': 'true'}


def valid_form(value):
    """Validate the display-only request before the shared transport can POST it."""
    if not isinstance(value, dict) or set(value) != {
            'action', 'nonce', 'start', 'end', 'params', 'monthview', 'calcount',
            'statefilter', 'cityfilter', 'locationfilter', 'showmobilelist'}:
        return False
    if (value.get('action') not in (ACTION, CALENDAR_ACTION) or value.get('monthview') != 'standard'
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
    return (settings.get('type') in ('calendar', 'calendar2', 'calendar3')
            and (value['action'] != CALENDAR_ACTION or settings['type'] == 'calendar')
            and 1 <= (end - start).days <= 62)


def _dialog_title(value):
    # WordPress wptexturize maps a spaced hyphen to an en dash. Compare
    # that display transformation only; retain the raw publisher title/ID.
    return html.unescape(str(value or '')).replace(' - ', ' – ')


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
    popup_html = envelope.get('popupdata', '')
    if not isinstance(popup_html, str) or len(popup_html) > 2_000_000:
        raise ValueError('invalid_event_discovery_calendar')
    popups = BeautifulSoup(popup_html, 'html.parser')
    rows = []
    rejected = Counter()
    incomplete = False
    for event in events:
        if not isinstance(event, dict):
            rejected['non_object'] += 1
            incomplete = True
            continue
        event_url = html.unescape(str(event.get('url') or ''))
        if event_url.startswith('#tw-event-dialog-'):
            # Standard calendar view links to an exact dialog in this same
            # response. Use its title link, never the fragment or a buy button.
            expected = 'tw-event-dialog-' + str(event.get('id') or '')
            dialogs = popups.find_all(id=expected)
            links = dialogs[0].select('.tw-name a[href]') if len(dialogs) == 1 else []
            if (event_url != '#' + expected or len(links) != 1
                    or _dialog_title(links[0].get_text(' ', strip=True)) != _dialog_title(event.get('title'))):
                rejected['dialog_identity_unverified'] += 1
                incomplete = True
                continue
            event_url = html.unescape(links[0]['href'])
        parts = urlsplit(event_url)
        if (parts.scheme != 'https' or parts.username or parts.password
                or parts.hostname not in (host, 'www.ticketweb.com', 'ticketweb.com')):
            rejected['untrusted_url'] += 1
            continue
        stamp = str(event.get('sortkey') or '')
        try:
            primary = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            rejected['invalid_start'] += 1
            incomplete = True
            continue
        # Each artist-card anchor is a publisher-authored performance. Its
        # date comes from the same card, and the primary clock must agree with
        # sortkey. Never infer recurrence or roll a late clock into tomorrow.
        performances = BeautifulSoup(str(event.get('times') or ''), 'html.parser')
        links = performances.select('a[href]')
        occurrences = [(event_url, stamp)]
        if links:
            try:
                if (len(links) > 20 or event.get('start') != primary.date().isoformat()
                        or primary.second != 0):
                    raise ValueError()
                occurrences = []
                for anchor in links:
                    target = html.unescape(anchor['href'])
                    part = urlsplit(target)
                    clock = re.sub(r'\s+', '', anchor.get_text(' ', strip=True)).upper()
                    if (not re.fullmatch(r'(?:[1-9]|1[0-2]):[0-5][0-9](?:AM|PM)', clock)
                            or part.scheme != 'https' or part.username or part.password
                            or part.hostname not in (host, 'www.ticketweb.com', 'ticketweb.com')):
                        raise ValueError()
                    time = datetime.strptime(clock, '%I:%M%p').time()
                    when = datetime.combine(primary.date(), time)
                    pair = (target, when.strftime('%Y-%m-%d %H:%M:%S'))
                    if any(target == previous[0] and pair != previous for previous in occurrences):
                        raise ValueError()
                    if pair not in occurrences:
                        occurrences.append(pair)
                if (event_url, stamp) not in occurrences:
                    raise ValueError()
            except ValueError:
                rejected['grouped_performances_unverified'] += 1
                incomplete = True
                continue
        venue = _plain_fragment(event.get('venue'))
        image_node = BeautifulSoup(str(event.get('imageUrl') or ''), 'html.parser').find('img', src=True)
        for event_url, stamp in occurrences:
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
    if len(rows) > 500:
        raise ValueError('oversized_event_discovery_snapshot')
    unique = {}
    for item in rows:
        if item['id'] in unique and unique[item['id']] != item:
            raise ValueError('conflicting_event_discovery_event')
        unique[item['id']] = item
    rows = list(unique.values())
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
    reviewed_clock = source.get('publisher_event_timezone')
    if reviewed_clock is not None:
        if (not isinstance(reviewed_clock, dict)
                or urlsplit(str(reviewed_clock.get('evidence_url') or '')).hostname != urlsplit(listing).hostname
                or not str(reviewed_clock.get('evidence_url') or '').startswith('https://')):
            raise ValueError('invalid_reviewed_event_timezone')
        try:
            ZoneInfo(reviewed_clock['timezone'])
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError('invalid_reviewed_event_timezone') from exc
        spec['timezone'] = reviewed_clock['timezone']
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
