"""The exact Liberty public calendar, through its anonymous display API.

Next's two public bootstrap getters are discovered in the current page's own
AuthProvider scripts. Their action identifiers and the returned anonymous token
are never configuration, event fields, checkpoint data or log messages. This
module only reads the bounded, published public events view used by that page.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record, timestamp
from roomquest.registration_formats import source_key

ORIGINAL = 'https://events.liberty.edu/'
HOST = 'events.liberty.edu'
API_ORIGIN = 'https://edn.liberty.edu'
API_HOST = 'edn.liberty.edu'
API = API_ORIGIN + '/events'
SOURCE_KEY = source_key(ORIGINAL)
# Ordinary HTML/script GETs never need the API host. Its transient bearer token
# is confined to read_liberty_events and that wrapper's separate exact scope.
ALLOWED_HOSTS = (HOST,)
ZONE = 'America/New_York'
WINDOW_DAYS = 30
PAGE_SIZE = 100
MAX_PAGES = 1
MAX_OCCURRENCES = PAGE_SIZE * MAX_PAGES
MAX_SCRIPTS = 3
MAX_SCRIPT_BYTES = 1_000_000
MAX_ACTION_BYTES = 16_384
GETTERS = ('getApiUrl', 'getApiToken')

_SCRIPT_PATH = re.compile(r'/_next/static/chunks/[0-9a-f]{16}\.js')
_ACTION = re.compile(
    r'\(\s*0\s*,\s*(?P<binding>[A-Za-z_$][\w$]*)\.createServerReference\s*\)'
    r'\(\s*["\'](?P<id>[0-9a-f]{42})["\']\s*,\s*(?P=binding)\.callServer\s*,'
    r'\s*void\s+0\s*,\s*(?P=binding)\.findSourceMapURL\s*,'
    r'\s*["\'](?P<getter>getApiUrl|getApiToken)["\']\s*\)')

# Building identity comes from each occurrence's own publisher location labels.
# Addresses were reviewed on 2026-11-22; this is deliberately not a campus-wide
# default. Rooms across different buildings, unknown buildings, parking lots,
# generic "Liberty University" and placeholder locations remain on hold.
# Montview physical address: liberty.edu/business-relations/.../2025/04/
# Equiity-for-Africa-2021-Montview-Map.pdf (building 045, both floor-plan sheets).
# Ice Center: libertyclubsports.com/sports/2023/11/14/lahaye-ice-center
# Library: liberty.edu/library/about/location/ (its published visitor address).
_BUILDINGS = (
    (re.compile(r'^Montview Student Union(?: - | Tabling | Starbucks )'),
     'Montview Student Union', '1410 Regents Pkwy, Lynchburg, VA 24515'),
    (re.compile(r'^LaHaye Ice Center - '),
     'LaHaye Ice Center', '1971 University Blvd, Lynchburg, VA 24515'),
    (re.compile(r'^JF Library '),
     'Jerry Falwell Library', '1971 University Blvd, Lynchburg, VA 24515'),
)
_UNRESOLVED_LOCATION = re.compile(r'\b(?:parking|placeholder|virtual|online|TBD|off[- ]campus)\b', re.I)
_NON_EVENT = re.compile(
    r'\b(?:cancelled|canceled|postponed)\b|'
    r'^(?:Thanksgiving|Christmas|New Year[’\']?s Day|Memorial Day|Labor Day|'
    r'Independence Day|Martin Luther King(?: Jr\.?)? Day|Easter(?: Sunday)?|'
    r'(?:Fall|Spring|Summer|Winter|Thanksgiving|Christmas) Break|University Closed)$', re.I)


def _deadline(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def valid_script_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.netloc == HOST and not parsed.query
            and not parsed.fragment and bool(_SCRIPT_PATH.fullmatch(parsed.path)))


def bootstrap_scripts(listing):
    """Read at most three scripts actually referenced by this public page.

    Flight strings are decoded as data, never evaluated as JavaScript. Requiring
    the named AuthProvider import and matching script tags avoids probing a grid
    of guessed hashes or following unrelated scripts, links or remote origins.
    """
    soup = listing if isinstance(listing, BeautifulSoup) else BeautifulSoup(listing, 'html.parser')
    included = {urljoin(ORIGINAL, node.get('src', '')) for node in soup.select('script[src]')}
    found = set()
    for node in soup.select('script:not([src])'):
        raw = node.get_text()
        if len(raw) > 300_000:
            raise ValueError('liberty_bootstrap_changed')
        match = re.fullmatch(r'\s*self\.__next_f\.push\((.*)\);?\s*', raw, re.S)
        if not match:
            continue
        try:
            packet = json.loads(match[1])
        except (ValueError, TypeError):
            raise ValueError('liberty_bootstrap_changed') from None
        if not (isinstance(packet, list) and len(packet) == 2 and packet[0] == 1
                and isinstance(packet[1], str)):
            continue
        for line in packet[1].splitlines():
            imported = re.fullmatch(r'[0-9a-f]+:I(.+)', line)
            if not imported:
                continue
            try:
                value = json.loads(imported[1])
            except (ValueError, TypeError):
                raise ValueError('liberty_bootstrap_changed') from None
            if not (isinstance(value, list) and len(value) == 3 and value[2] == 'AuthProvider'):
                continue
            chunks = value[1]
            if (not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_SCRIPTS
                    or any(not isinstance(chunk, str) for chunk in chunks)):
                raise ValueError('liberty_bootstrap_changed')
            urls = tuple(urljoin(ORIGINAL, chunk) for chunk in chunks)
            if (len(set(urls)) != len(urls)
                    or any(not valid_script_url(url) or url not in included for url in urls)):
                raise ValueError('liberty_bootstrap_changed')
            found.add(urls)
    if len(found) != 1:
        raise ValueError('liberty_bootstrap_changed')
    # App helpers occur after shared runtime chunks in this publisher's import.
    return tuple(reversed(next(iter(found))))


def action_references(script_url, script):
    if (not valid_script_url(script_url) or not isinstance(script, str)
            or len(script.encode('utf-8')) > MAX_SCRIPT_BYTES):
        raise ValueError('invalid_liberty_action_request')
    found = {}
    for match in _ACTION.finditer(script):
        if match['getter'] in found:
            raise ValueError('liberty_bootstrap_changed')
        found[match['getter']] = match['id']
    if found and (set(found) != set(GETTERS) or len(set(found.values())) != 2):
        raise ValueError('liberty_bootstrap_changed')
    return found


def action_reference(script_url, script, getter):
    """Only these observed display getters can become fixed-body POSTs."""
    if getter not in GETTERS:
        raise ValueError('invalid_liberty_action_request')
    found = action_references(script_url, script)
    if getter not in found:
        raise ValueError('invalid_liberty_action_request')
    return found[getter]


def action_result(payload):
    """Read Next's bounded JSON/text result frames without exposing the body.

    A long string uses a byte-counted T frame followed immediately by another
    row, so splitting by newline alone can accidentally retain the return frame
    in the token. Only the explicit frame-1 string result is accepted.
    """
    if not isinstance(payload, str):
        raise ValueError('liberty_bootstrap_changed')
    raw = payload.encode('utf-8')
    if not 1 <= len(raw) <= MAX_ACTION_BYTES:
        raise ValueError('liberty_bootstrap_changed')
    frames, cursor = {}, 0
    try:
        while cursor < len(raw):
            if raw[cursor:cursor + 1] == b'\n':
                cursor += 1
                continue
            header = re.match(rb'([0-9a-f]{1,4}):', raw[cursor:])
            if not header or len(frames) >= 16:
                raise ValueError
            key = header[1].decode('ascii')
            if key in frames:
                raise ValueError
            cursor += header.end()
            text_frame = re.match(rb'T([0-9a-f]{1,5}),', raw[cursor:])
            if text_frame:
                size = int(text_frame[1], 16)
                cursor += text_frame.end()
                if size > MAX_ACTION_BYTES or cursor + size > len(raw):
                    raise ValueError
                frames[key] = raw[cursor:cursor + size].decode('utf-8')
                cursor += size
            else:
                end = raw.find(b'\n', cursor)
                end = len(raw) if end == -1 else end
                frames[key] = json.loads(raw[cursor:end])
                cursor = end
        if not isinstance(frames.get('0'), dict) or frames['0'].get('a') != '$@1':
            raise ValueError
        value = frames.get('1')
        visited = set()
        for _ in range(4):
            if not isinstance(value, str) or not value:
                raise ValueError
            reference = re.fullmatch(r'\$([0-9a-f]{1,4})', value)
            if not reference:
                return value
            if reference[1] in visited:
                raise ValueError
            visited.add(reference[1])
            value = frames.get(reference[1])
    except (ValueError, TypeError, UnicodeError):
        pass
    raise ValueError('liberty_bootstrap_changed') from None


def valid_public_token(token):
    # The token's public provenance is the fresh, unauthenticated getter above;
    # this shape check prevents header injection, not a claim of JWT verification.
    return (isinstance(token, str) and 40 <= len(token) <= 8192
            and bool(re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token)))


def events_url(*, page, window_start):
    today = datetime.now(ZoneInfo(ZONE)).date()
    if (type(page) is not int or not 1 <= page <= MAX_PAGES or type(window_start) is not date
            or not timedelta(0) <= today - window_start <= timedelta(days=1)):
        raise ValueError('invalid_liberty_events_request')
    last = window_start + timedelta(days=WINDOW_DAYS - 1)
    return API + '?' + urlencode({
        'page': page, 'resultsPerPage': PAGE_SIZE, 'sortBy': 'datetimeStart asc',
        'afterDate': window_start.isoformat() + ' 00:00:00',
        'beforeDate': last.isoformat() + ' 23:59:59', 'published': '1', 'groupOccurrences': 'false',
    })


def valid_events_request(url, public_token):
    if not isinstance(url, str) or not valid_public_token(public_token):
        return False
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.scheme != 'https' or parsed.netloc != API_HOST or parsed.path != '/events' or parsed.fragment:
            return False
        if any(len(values) != 1 for values in query.values()):
            return False
        start = date.fromisoformat(query['afterDate'][0].split(' ')[0])
        return url == events_url(page=int(query['page'][0]), window_start=start)
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def _wall_time(value):
    if not isinstance(value, dict):
        raise ValueError('liberty_event_time_changed')
    keys = ('year', 'month', 'day', 'hour', 'minute', 'second')
    if (any(type(value.get(key)) is not int for key in keys)
            or type(value.get('timezone')) is not int or value['timezone'] != 0):
        raise ValueError('liberty_event_time_changed')
    try:
        result = datetime(*(value[key] for key in keys))
        text = value.get('timeString')
        if (not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?', text)
                or datetime.fromisoformat(text) != result):
            raise ValueError
        # The public JS constructs new Date(year, month-1, day, hour, minute,
        # second); timezone:0 is not a UTC assertion. These reviewed campus
        # wall clocks are Eastern. timestamp also rejects DST gaps/folds.
        return timestamp(result, ZONE)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('liberty_event_time_changed') from None


def _venue(locations):
    if not isinstance(locations, list) or not locations or len(locations) > 50:
        return None
    buildings, labels = set(), []
    for location in locations:
        if not isinstance(location, dict) or type(location.get('locationId')) is not int or location['locationId'] <= 0:
            return None
        label = location.get('locationFormalName')
        if not isinstance(label, str) or len(label) > 200 or _UNRESOLVED_LOCATION.search(label):
            return None
        matched = [(name, address) for pattern, name, address in _BUILDINGS if pattern.match(label)]
        if len(matched) != 1:
            return None
        buildings.add(matched[0])
        labels.append(label)
    if len(buildings) != 1:
        return None
    name, address = next(iter(buildings))
    return (labels[0] if len(set(labels)) == 1 else name), address


def _description_time_conflict(narrative, start, end):
    """Hold an explicit visitor time outside the native occurrence interval.

    The reviewed public response includes a hockey occurrence ending at 17:15
    whose description says "at 5:45PM". Do not turn a reservation window into
    an invented public start time. This check only holds a contradiction; the
    narrative is never used to synthesize or overwrite occurrence timestamps.
    """
    for match in re.finditer(r'\bat\s+(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?m\.?\b', narrative, re.I):
        clause = re.split(r'[.;!?\n,]', narrative[:match.start()])[-1]
        if re.search(r'\b(?:doors?|arriv(?:al|e|ing)|check[- ]?in|registration|register|RSVP|'
                     r'deadline|cut[- ]?off|parking|warm[- ]?up|set[- ]?up|box office|on sale)\b', clause, re.I):
            continue
        hour = int(match[1]) % 12 + (12 if match[3].lower() == 'p' else 0)
        instant = start.replace(hour=hour, minute=int(match[2] or 0), second=0, microsecond=0)
        if instant < start:
            instant += timedelta(days=1)
        if instant > end:
            return True
    return False


def _page(payload, page, expected_total=None):
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        raise ValueError('liberty_calendar_changed') from None
    info = data.get('queryInfo') if isinstance(data, dict) else None
    events = data.get('events') if isinstance(data, dict) else None
    if (not isinstance(info, dict) or not isinstance(events, list)
            or any(type(info.get(key)) is not int for key in ('totalResults', 'totalPages', 'pageIndex'))):
        raise ValueError('liberty_calendar_changed')
    total = info['totalResults']
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if total < 0 or total > MAX_OCCURRENCES or pages > MAX_PAGES:
        raise ValueError('liberty_calendar_limit')
    if (info['pageIndex'] != page or (expected_total is not None and total != expected_total)
            or info['totalPages'] not in ({0, 1} if total == 0 else {pages})
            or page > pages or len(events) != min(PAGE_SIZE, max(0, total - (page - 1) * PAGE_SIZE))):
        raise ValueError('liberty_calendar_incomplete')
    return events, total, pages


def _rows(events, window_start):
    result, seen = [], set()
    last = window_start + timedelta(days=WINDOW_DAYS - 1)
    for event in events:
        if not isinstance(event, dict) or type(event.get('eventId')) is not int or event['eventId'] <= 0:
            raise ValueError('liberty_calendar_changed')
        occurrences = event.get('occurrences')
        if not isinstance(occurrences, list) or len(occurrences) != 1 or not isinstance(occurrences[0], dict):
            raise ValueError('liberty_occurrences_changed')
        occurrence = occurrences[0]
        identity = occurrence.get('occurrenceId')
        if type(identity) is not int or identity <= 0:
            raise ValueError('liberty_occurrences_changed')
        if identity in seen:
            # Repeated rows in an ungrouped paged result may hide a missing
            # occurrence, even if their visible fields happen to be identical.
            raise ValueError('liberty_calendar_incomplete')
        seen.add(identity)
        if event.get('visibility') != 'Public' or type(event.get('published')) is not int or event['published'] != 1:
            continue
        title, slug = event.get('eventName'), event.get('slug')
        if (not isinstance(title, str) or not title.strip() or len(title) > 500
                or not isinstance(slug, str) or len(slug) > 200
                or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug)):
            raise ValueError('liberty_calendar_changed')
        start, end = _wall_time(occurrence.get('startTime')), _wall_time(occurrence.get('endTime'))
        if end <= start or end - start > timedelta(days=7):
            raise ValueError('liberty_event_time_changed')
        if not window_start <= start.date() <= last:
            raise ValueError('liberty_calendar_incomplete')
        venue = _venue(event.get('locations'))
        if (venue is None or _NON_EVENT.search(title.strip())
                or (start.hour == start.minute == start.second == 0 and end - start >= timedelta(hours=20))):
            continue
        narrative = description(event.get('eventDescription'))
        if _description_time_conflict(narrative, start, end):
            continue
        row = record(title, start, end, venue[0], venue[1], 'Lynchburg', ORIGINAL + 'event/' + slug,
                     'liberty-occurrence:' + str(identity), tz=ZONE)
        if row:
            # Only visitor-facing narrative is retained. Creator, approver,
            # department internals and administrative metadata are not copied.
            row['description'] = narrative
            row['timezone'] = ZONE
            result.append(row)
    return sorted(result, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, listing=None, fetch_action=None, fetch_events=None):
    if source.get('feed_url') != ORIGINAL or source.get('source_key') != SOURCE_KEY:
        raise ValueError('unregistered_liberty_calendar')
    if fetch_action is None or fetch_events is None:
        from roomquest.preview_worker import read_liberty_public_action, read_liberty_events
        fetch_action = fetch_action or read_liberty_public_action
        fetch_events = fetch_events or read_liberty_events
    _deadline(deadline_at)
    today = datetime.now(ZoneInfo(ZONE)).date()
    if listing is None:
        listing = fetch(ORIGINAL, 'text/html')
    evidence = None
    for url in bootstrap_scripts(listing):
        _deadline(deadline_at)
        script = fetch(url, 'application/javascript')
        _deadline(deadline_at)
        if action_references(url, script):
            evidence = (url, script)
            break
    if evidence is None:
        raise ValueError('liberty_bootstrap_changed')
    _deadline(deadline_at)
    api = action_result(fetch_action(script_url=evidence[0], script=evidence[1], getter='getApiUrl', deadline_at=deadline_at))
    if api != API_ORIGIN:
        raise ValueError('liberty_api_origin_changed')
    _deadline(deadline_at)
    public_token = action_result(fetch_action(script_url=evidence[0], script=evidence[1], getter='getApiToken', deadline_at=deadline_at))
    if not valid_public_token(public_token):
        raise ValueError('liberty_bootstrap_changed')
    try:
        _deadline(deadline_at)
        events, _, _ = _page(fetch_events(page=1, window_start=today, public_token=public_token, deadline_at=deadline_at), 1)
        _deadline(deadline_at)
        result = _rows(events, today)
        if not result:
            raise ValueError('no_extractable_events')
        return result
    finally:
        # No raw API/bootstrap result is a checkpoint or a return value.
        public_token = None
