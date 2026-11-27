"""Direct Raleigh calendars with complete descriptions and explicit venues.

All I/O uses the caller's existing robots-aware, paced publisher transport.
The calendar snapshot is complete before staging. Detail hydration is resumed
through the existing v1 lease-fenced checkpoint, without a second scheduler.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
FAIR = 'nc_state_fair_events_nc'
GOODNIGHTS = 'goodnights_comedy_raleigh_nc'
OGK = 'our_giving_kitchen_raleigh_nc'
TRANSFER = 'transfer_co_food_hall_raleigh_nc'
GAME = 'game_theory_raleigh_nc'
TRC = 'triangle_rock_club_salvage_yard_nc'
SOURCES = {
    FAIR: ('https://www.ncagr.gov/divisions/ncstatefair/events', 'html', 'html'),
    GOODNIGHTS: ('https://www.goodnightscomedy.com/events', 'html', 'html'),
    OGK: ('https://www.ogkraleigh.org/events', 'html', 'html'),
    TRANSFER: ('https://transfer-co-food-hall.squarespace.com/upcoming-events', 'html', 'html'),
    GAME: ('https://gametheorystore.com/calendar/', 'html', 'html'),
    TRC: ('https://account.trianglerockclub.com/salvage-yard/programs/run-club', 'html', 'html'),
}
LABELS = {FAIR: 'N.C. State Fairgrounds', GOODNIGHTS: 'Goodnights Comedy Club',
          OGK: 'Our Giving Kitchen Raleigh', TRANSFER: 'Transfer Co. Food Hall',
          GAME: 'Game Theory Raleigh', TRC: 'Triangle Rock Club Salvage Yard — Run Club'}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
GAME_API_HOST = 'gzjanhbxzjpdsgusurjt.supabase.co'
GAME_API = 'https://' + GAME_API_HOST + '/rest/v1/events'
GAME_FRAME = 'https://gametheorystore.com/GT_WebCalendar.html'
GAME_FIELDS = 'id,title,description,start_time,end_time,store_location,is_recurring,price,banner_filename'
ALLOWED_HOSTS[GAME] += (GAME_API_HOST,)
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {key: 200 for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: 500 for key in SOURCES}
MAX_RECORDS = 500
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 850_000
MAX_DETAILS = 4
VENUES = {
    FAIR: ('N.C. State Fairgrounds', '4285 Trinity Road, Raleigh, NC 27607', 'Raleigh'),
    GOODNIGHTS: ('Goodnights Comedy Club', '401 Woodburn Road, Raleigh, NC 27605', 'Raleigh'),
    OGK: ('The Shul Downtown', '225 South Wilmington Street, Raleigh, NC 27601', 'Raleigh'),
    TRANSFER: ('Transfer Co. Food Hall', '500 East Davie Street, Raleigh, NC 27601', 'Raleigh'),
    GAME: ('Game Theory Raleigh', '5910 Duraleigh Road Suite 125, Raleigh, NC 27612', 'Raleigh'),
    TRC: ('Triangle Rock Club Salvage Yard', '2330 Salvage Yard Drive, Raleigh, NC 27604', 'Raleigh'),
}
VENUE_EVIDENCE = {key: SOURCES[key][0] for key in SOURCES}
VENUE_EVIDENCE[OGK] = 'https://www.ogkraleigh.org/events/1115'
HOLD_CODES = {'raleigh_direct_description_missing', 'raleigh_direct_description_limit',
    'raleigh_direct_schedule_missing', 'raleigh_direct_schedule_conflict',
    'raleigh_direct_venue_unresolved', 'raleigh_direct_nonpublic',
    'raleigh_direct_missing_occurrences'}
ERROR_CODES = HOLD_CODES | {'unregistered_raleigh_direct_community',
    'raleigh_direct_calendar_changed', 'raleigh_direct_detail_changed',
    'raleigh_direct_duplicate_occurrence', 'raleigh_direct_record_limit',
    'raleigh_direct_checkpoint_invalid', 'raleigh_direct_checkpoint_size_limit',
    'invalid_game_theory_request', 'raleigh_direct_public_api_identity',
    'publisher_checkpoint_required', 'collection_deadline'}
MONTHS = {name.lower(): n for n, name in enumerate(('', 'January', 'February', 'March',
    'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')) if n}
WEEKDAYS = {name.lower(): n for n, name in enumerate(('Monday', 'Tuesday', 'Wednesday',
    'Thursday', 'Friday', 'Saturday', 'Sunday'))}
WEEKDAYS.update({key[:3]: value for key, value in list(WEEKDAYS.items())})
NONPUBLIC = re.compile(r'\b(?:private (?:event|party)|closed for|cancell?ed|postponed)\b', re.I)


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()).hexdigest()


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('unregistered_raleigh_direct_community')
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1500:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.netloc != ALLOWED_HOSTS[key][0] or p.port not in (None, 443)
                or p.username or p.password or p.query or p.fragment
                or '..' in p.path.split('/') or re.search(r'[\s\\<>]|%2e|%5c', value, re.I)):
            return False
        if key in (FAIR, GAME, TRC):
            return value == SOURCES[key][0]
        if key == GOODNIGHTS:
            return bool(re.fullmatch(r'/(?:shows|events)/[1-9]\d{0,9}', p.path))
        return p.path.startswith(urlsplit(SOURCES[key][0]).path.rstrip('/') + '/')
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
                or p.fragment or '..' in p.path.split('/')
                or re.search(r'[\s\\<>]|%2e|%5c', value, re.I)):
            return None
        if key == GOODNIGHTS:
            return value if p.netloc == 'files.seatengine.com' and p.path.startswith('/talent/') else None
        if key in (OGK, TRANSFER):
            return value if p.netloc in ('images.squarespace-cdn.com', 'static1.squarespace.com') and '/content/' in p.path else None
        if key == GAME:
            return value if p.netloc == GAME_API_HOST and p.path.startswith('/storage/v1/object/public/event-banners/') else None
    except ValueError:
        return None
    return None


def _body(value):
    node = BeautifulSoup(str(value or ''), 'html.parser')
    for element in node.select('script, style, template, noscript'):
        element.decompose()
    result = '\n'.join(re.sub(r'[\t \u00a0]+', ' ', line).strip()
                       for line in node.get_text('\n').splitlines() if line.strip())
    if not result:
        raise ValueError('raleigh_direct_description_missing')
    if len(result) > MAX_DESCRIPTION:
        raise ValueError('raleigh_direct_description_limit')
    return result


def _within(start, end, now):
    window_start = calendar_anchor(now)
    return bool(start and start < window_start + timedelta(days=60)
                and (end or start + timedelta(hours=3)) > window_start)


def _hold(diagnostics, identity, reason):
    diagnostics.append({'id': str(identity)[:180], 'reason': reason})


def _row(key, title, start, end, url, identity, body, *, venue=None, photo=None, categories=()):
    if not event_url(key, url):
        raise ValueError('raleigh_direct_detail_changed')
    place = venue or VENUES[key]
    # Callers normalize native HTML exactly once. Re-parsing plain publisher
    # prose as HTML could erase literal angle-bracket instructions.
    if not isinstance(body, str) or not body.strip():
        raise ValueError('raleigh_direct_description_missing')
    if len(body) > MAX_DESCRIPTION:
        raise ValueError('raleigh_direct_description_limit')
    result = record(title, start.isoformat(), end.isoformat() if end else None,
        *place, url, 'raleigh:' + _digest([key, identity, start.isoformat()]),
        tz=ZONE, retain_until_end=True)
    if result:
        result.update(description=body, timezone=ZONE, attendance_mode='in_person',
            publisher_categories=list(categories),
            location_provenance='reviewed_publisher_street_pending_geocode',
            location_evidence_url=VENUE_EVIDENCE[key])
        if photo_url(key, photo):
            result['image_url'] = photo
    return result


def _schemas(soup):
    result = []
    def walk(value):
        if isinstance(value, dict):
            if value.get('@type') == 'Event':
                result.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(node.string or node.get_text()))
        except (TypeError, ValueError):
            continue
    return result


def _goodnights(payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    schemas = _schemas(soup)
    if not schemas or not soup.select('.event-list-item .el-showtimes'):
        raise ValueError('raleigh_direct_calendar_changed')
    # The listing exposes every individual show, not merely its series dates.
    clocks = {}
    titles = {plain(node.get_text()) for node in soup.select('.event-list-item .el-header')}
    for card in soup.select('.event-list-item'):
        for button in card.select('.el-showtimes a[href]'):
            clock = button.parent.select_one('.event-date')
            if clock:
                clocks[urljoin(SOURCES[GOODNIGHTS][0], button['href'])] = plain(clock.get_text())
    rows = []
    for event in schemas:
        identity = event.get('url', '')
        try:
            start = timestamp(event.get('startDate'))
            if not _within(start, None, now):
                continue
            if NONPUBLIC.search(plain(event.get('name'))):
                _hold(diagnostics, identity, 'raleigh_direct_nonpublic'); continue
            shown = clocks.get(identity)
            if plain(event.get('name')) not in titles:
                raise ValueError('raleigh_direct_detail_changed')
            # Multi-show cards link to their series instead of repeating every
            # show clock. The same response's native Event array supplies all
            # explicit UTC instances. Cross-check every visible single-show
            # clock without discarding the structured multi-show instances.
            if shown:
                native = datetime.strptime(re.sub(r'\s+', ' ', shown), '%a %b %d %Y, %I:%M %p')
                if native != start.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None):
                    raise ValueError('raleigh_direct_schedule_conflict')
            address = (event.get('location') or {}).get('address') or {}
            if (not re.fullmatch(r'401 Woodburn (?:Rd\.?|Road)', address.get('streetAddress', ''))
                    or address.get('addressLocality') != 'Raleigh' or address.get('addressRegion') != 'NC'):
                raise ValueError('raleigh_direct_venue_unresolved')
            row = _row(GOODNIGHTS, event['name'], start, None, identity, identity,
                       _body(event.get('description')), photo=event.get('image'))
            if row:
                rows.append(row)
        except ValueError as exc:
            reason = str(exc)
            if reason not in HOLD_CODES:
                raise
            _hold(diagnostics, identity, reason)
    return rows


def game_theory_request(public_key, window_start, window_end):
    """Build only the publisher's anonymous, Raleigh-filtered calendar read.

    The publishable key is read from its public calendar HTML each capture. It
    is never committed, persisted in a checkpoint, accepted as a privileged
    JWT, or sent to any other endpoint/host.
    """
    if not isinstance(public_key, str) or not re.fullmatch(r'sb_publishable_[A-Za-z0-9_-]{16,120}', public_key):
        raise ValueError('invalid_game_theory_request')
    try:
        first, last = date.fromisoformat(window_start), date.fromisoformat(window_end)
        today = datetime.now(ZoneInfo(ZONE)).date()
        if last-first != timedelta(days=60) or abs((first-today).days) > 1:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('invalid_game_theory_request') from None
    begins = datetime.combine(first, datetime.min.time(), ZoneInfo(ZONE)).isoformat()
    ends = datetime.combine(last, datetime.min.time(), ZoneInfo(ZONE)).isoformat()
    params = [('select', GAME_FIELDS), ('store_location', 'eq.Raleigh'),
              ('start_time', 'gte.' + begins), ('start_time', 'lt.' + ends),
              ('order', 'start_time,id'), ('limit', '500')]
    return GAME_API + '?' + urlencode(params)


def valid_game_theory_request(url, public_key):
    try:
        parsed = urlsplit(url)
        q = parse_qs(parsed.query, keep_blank_values=True)
        if (parsed.scheme != 'https' or parsed.netloc != GAME_API_HOST
                or parsed.path != '/rest/v1/events' or parsed.fragment
                or set(q) != {'select', 'store_location', 'start_time', 'order', 'limit'}
                or q['select'] != [GAME_FIELDS] or q['store_location'] != ['eq.Raleigh']
                or q['order'] != ['start_time,id'] or q['limit'] != ['500']
                or len(q['start_time']) != 2):
            return False
        a, b = q['start_time']
        if not a.startswith('gte.') or not b.startswith('lt.'):
            return False
        first, last = timestamp(a[4:]), timestamp(b[3:])
        if first.time() != datetime.min.time() or last.time() != datetime.min.time():
            return False
        return url == game_theory_request(public_key, first.date().isoformat(), last.date().isoformat())
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _game_theory(payload, fetch, read_public_events, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    frames = [urljoin(SOURCES[GAME][0], node.get('src', '')) for node in soup.select('iframe[src]')]
    if frames != [GAME_FRAME] or read_public_events is None:
        raise ValueError('raleigh_direct_public_api_identity')
    frame = fetch(GAME_FRAME, 'text/html')
    endpoint = re.findall(r"const SUPABASE_URL\s*=\s*'([^']+)'", frame)
    keys = re.findall(r"const (?:SUPABASE_ANON_KEY|SUPABASE_KEY)\s*=\s*'([^']+)'", frame)
    if endpoint != ['https://' + GAME_API_HOST] or len(keys) != 1 or ".from('events')" not in frame:
        raise ValueError('raleigh_direct_public_api_identity')
    first = calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date()
    raw = read_public_events(public_key=keys[0], window_start=first.isoformat(),
                             window_end=(first + timedelta(days=60)).isoformat())
    events = json.loads(raw)
    if not isinstance(events, list) or len(events) >= 500:
        raise ValueError('raleigh_direct_record_limit')
    rows = []
    for event in events:
        identity = str(event.get('id', ''))
        try:
            if not identity or event.get('store_location') != 'Raleigh':
                raise ValueError('raleigh_direct_calendar_changed')
            start, end = timestamp(event.get('start_time')), timestamp(event.get('end_time'))
            if not _within(start, end, now):
                continue
            if NONPUBLIC.search(plain(event.get('title'))) or re.search(r'\bclosed\b', plain(event.get('title')), re.I):
                raise ValueError('raleigh_direct_nonpublic')
            body = _body(event.get('description'))
            # A published short sentence remains intact. Empty publisher prose
            # is reported as a hold, never replaced with generated marketing.
            image = None
            filename = event.get('banner_filename')
            if isinstance(filename, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,200}', filename):
                image = 'https://' + GAME_API_HOST + '/storage/v1/object/public/event-banners/' + quote(filename)
            row = _row(GAME, event['title'], start, end, SOURCES[GAME][0], identity,
                       body, photo=image)
            if row:
                rows.append(row)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            _hold(diagnostics, identity, str(exc))
    return rows


def _trc(payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    heading = soup.find('h1')
    containers = [node for node in soup.select('.ContentReset')
                  if re.search(r'Join us every Tuesday at 5:30\s*pm', node.get_text(' ', strip=True), re.I)]
    if (not heading or plain(heading.get_text()) != 'Run Club' or len(containers) != 1
            or '2330 Salvage Yard' not in payload or '27604' not in payload):
        raise ValueError('raleigh_direct_calendar_changed')
    body = _body(containers[0])
    if 'TRC Salvage Yard' not in body:
        raise ValueError('raleigh_direct_venue_unresolved')
    rows = []
    first = calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date()
    for offset in range(28):
        day = first + timedelta(days=offset)
        if day.weekday() != 1:
            continue
        start = datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)) + timedelta(hours=17, minutes=30)
        if not _within(start, None, now):
            continue
        row = _row(TRC, 'Run Club', start, None, SOURCES[TRC][0], 'run-club:' + day.isoformat(), body)
        if row:
            row.update(schedule_provenance='publisher_declared_weekly_schedule',
                       published_schedule='Every Tuesday at 5:30pm', schedule_window_days=28)
            rows.append(row)
    return rows


_CLOCK = r'(?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)'
_RANGE = re.compile(r'(?<![\w/])(' + _CLOCK + r')\s*[-–—]\s*(' + _CLOCK + r')(?![\w/])', re.I)


def _clock_options(value):
    text = re.sub(r'[.\s]', '', value).lower()
    if text in ('noon', 'midnight'):
        return [12*60 if text == 'noon' else 0]
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(am|pm)?', text)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) >= 60:
        raise ValueError('raleigh_direct_schedule_conflict')
    base = int(match[1]) % 12 * 60 + int(match[2] or 0)
    return [base + (720 if match[3] == 'pm' else 0)] if match[3] else [base, base+720]


def _range_clock(day, left, right):
    a, b = _clock_options(left), _clock_options(right)
    # At least one endpoint must specify AM/PM; do not turn an ambiguous
    # publisher's "9-5" into an invented clock.
    if len(a) == len(b) == 2:
        raise ValueError('raleigh_direct_schedule_missing')
    choices = [(x, y) for x in a for y in b if 0 < y-x <= 12*60]
    if len(choices) != 1:
        raise ValueError('raleigh_direct_schedule_conflict')
    x, y = choices[0]
    return (datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)) + timedelta(minutes=x),
            datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)) + timedelta(minutes=y))


def _fair_times(day, body):
    if body.startswith('The Raleigh Market'):
        schedule = body
    else:
        match = re.search(r'Event\s*Time\s*(.*?)(?:Admission|For more information|$)', body, re.I)
        if not match:
            raise ValueError('raleigh_direct_schedule_missing')
        schedule = match[1]
    selected = []
    previous = 0
    for match in _RANGE.finditer(schedule):
        prefix = schedule[previous:match.start()]
        previous = match.end()
        if re.search(r'\bVIP\b', prefix, re.I) and not re.search(r'\bGA\b', prefix, re.I):
            continue
        named = re.findall(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b', prefix, re.I)
        if named and day.weekday() not in {WEEKDAYS[name.lower()] for name in named}:
            continue
        explicit = re.findall(r'\b(\d{1,2})/(\d{1,2})\b', prefix)
        for month_name, number in re.findall(r'\b(' + '|'.join(MONTHS) + r')\s+(\d{1,2})(?:st|nd|rd|th)?\b', prefix, re.I):
            explicit.append((MONTHS[month_name.lower()], int(number)))
        if explicit and (day.month, day.day) not in {(int(m), int(d)) for m, d in explicit}:
            continue
        selected.append(_range_clock(day, match[1], match[2]))
    if len(selected) != 1:
        raise ValueError('raleigh_direct_schedule_missing' if not selected else 'raleigh_direct_schedule_conflict')
    return selected[0]


def _fair_weekdays(label):
    match = re.fullmatch(r'Every\s+(.+)', label, re.I)
    if not match:
        return None
    names = re.split(r'\s*(?:,\s*(?:and\b|&)?|\band\b|&)\s*', match[1], flags=re.I)
    full_names = {name: number for name, number in WEEKDAYS.items() if len(name) > 3}
    if not names or any(name.lower() not in full_names for name in names):
        raise ValueError('raleigh_direct_schedule_missing')
    return {full_names[name.lower()] for name in names}


def _fair_closed_dates(cell, year):
    """Only explicit CLOSED date lists; other closure language needs review."""
    months = {**MONTHS, **{name[:3]: number for name, number in MONTHS.items()}}
    month_names = '|'.join(sorted(months, key=len, reverse=True))
    weekday_names = '|'.join(sorted(WEEKDAYS, key=len, reverse=True))
    token = re.compile(
        r'(?:(?P<weekday>' + weekday_names + r')\.?\s*,?\s+)?'
        r'(?:(?P<month>' + month_names + r')\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?'
        r'(?:(?:\s*,\s*|\s+)(?P<year>20\d{2}))?'
        r'|(?P<nmonth>\d{1,2})/(?P<nday>\d{1,2})(?:/(?P<nyear>20\d{2}))?)', re.I)
    dates, notes = set(), []
    blocks = cell.find_all(['p', 'li']) or [cell]
    texts = [plain(block.get_text(' ')) for block in blocks]
    marker = re.compile(r'\b(?:closed|closures?|cancell?ed|postponed|except|excluding|not\s+open)\b', re.I)
    if sum(len(marker.findall(text)) for text in texts) != len(marker.findall(plain(cell.get_text(' ')))):
        raise ValueError('raleigh_direct_schedule_conflict')
    for text in texts:
        markers = list(marker.finditer(text))
        if not markers:
            continue
        if (len(markers) != 1 or markers[0][0].lower() != 'closed'
                or re.search(r'\b(?:if|unless|may|might|could|not|never|maybe)\b', text[:markers[0].start()], re.I)):
            raise ValueError('raleigh_direct_schedule_conflict')
        tail = re.sub(r'^\s*on\s+', '', text[markers[0].end():], flags=re.I).strip(' \t.:;+*!()')
        if not tail:
            raise ValueError('raleigh_direct_schedule_conflict')
        while tail:
            match = token.match(tail)
            if not match:
                raise ValueError('raleigh_direct_schedule_conflict')
            named_year = match['year'] or match['nyear']
            if named_year and int(named_year) != year:
                raise ValueError('raleigh_direct_schedule_conflict')
            try:
                day = date(year, months[match['month'].lower()] if match['month'] else int(match['nmonth']),
                           int(match['day'] or match['nday']))
            except (ValueError, KeyError):
                raise ValueError('raleigh_direct_schedule_conflict') from None
            if match['weekday'] and WEEKDAYS[match['weekday'].lower()] != day.weekday():
                raise ValueError('raleigh_direct_schedule_conflict')
            dates.add(day)
            tail = tail[match.end():]
            if tail:
                separator = re.match(r'\s*(?:/|,\s*(?:and\b|&)?|&|\band\b)\s*', tail, re.I)
                if not separator or separator.end() == len(tail):
                    raise ValueError('raleigh_direct_schedule_conflict')
                tail = tail[separator.end():]
        notes.append(text[markers[0].start():])
    return dates, notes


def _fair(payload, now, diagnostics):
    soup = BeautifulSoup(payload, 'html.parser')
    years = {int(m[1]) for heading in soup.find_all(['h1', 'h2'])
             if (m := re.search(r'\b(20\d{2}) NC State Fair Event Calendar\b', heading.get_text(' ', strip=True)))}
    if len(years) != 1 or len(soup.find_all('table')) != 12:
        raise ValueError('raleigh_direct_calendar_changed')
    year = years.pop()
    result = []
    window_start = calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date()
    window_end = (calendar_anchor(now) + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date()
    monthly_tables, closed, unresolved = [], {}, set()
    # A January row can announce a February closure. Read the same-year
    # recurring series before filtering months, without widening its venue key.
    for table in soup.find_all('table'):
        heading = table.find_previous(['h2', 'h3', 'h4'])
        month = MONTHS.get(plain(heading.get_text()).lower()) if heading else None
        if not month:
            raise ValueError('raleigh_direct_calendar_changed')
        monthly_tables.append((month, table))
        for tr in table.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 3:
                continue
            if not re.match(r'^Every\b', plain(cells[0].get_text()), re.I):
                continue
            flat = plain(cells[1].get_text(' '))
            strong = cells[1].find(['b', 'strong'])
            title = plain(strong.get_text()) if strong else 'The Raleigh Market' if flat.startswith('The Raleigh Market') else ''
            series = (title.lower(), plain(cells[2].get_text(' ')).lower())
            try:
                dates, _ = _fair_closed_dates(cells[1], year)
                closed.setdefault(series, set()).update(dates)
            except ValueError:
                unresolved.add(series)
    for month, table in monthly_tables:
        if date(year, month, monthrange(year, month)[1]) < window_start or date(year, month, 1) > window_end:
            continue
        for tr in table.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 3:
                continue
            day_label = plain(cells[0].get_text())
            flat = plain(cells[1].get_text(' '))
            strong = cells[1].find(['b', 'strong'])
            title = plain(strong.get_text()) if strong else 'The Raleigh Market' if flat.startswith('The Raleigh Market') else ''
            identity = f'{year}:{month}:{day_label}:{title}'
            try:
                body = _body(cells[1])
                if not title:
                    raise ValueError('raleigh_direct_description_missing')
                if NONPUBLIC.search(title) or re.search(r'\b(?:THIS EVENT (?:IS|HAS BEEN) (?:CLOSED|MOVED|RESCHEDULED)|CLOSED.*WEATHER)\b', flat, re.I):
                    raise ValueError('raleigh_direct_nonpublic')
                weekdays = _fair_weekdays(day_label)
                venue_label = plain(cells[2].get_text(' '))
                series = (title.lower(), venue_label.lower())
                clock_body = flat
                if weekdays is not None:
                    if series in unresolved:
                        raise ValueError('raleigh_direct_schedule_conflict')
                    _, notes = _fair_closed_dates(cells[1], year)
                    for note in notes:
                        clock_body = plain(clock_body.replace(note, ' '))
                    days = [date(year, month, d) for d in range(1, monthrange(year, month)[1]+1)
                            if date(year, month, d).weekday() in weekdays]
                elif match := re.fullmatch(r'(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?', day_label):
                    first, last = int(match[1]), int(match[2] or match[1])
                    days = [date(year, month, d) for d in range(first, last+1)]
                else:
                    raise ValueError('raleigh_direct_schedule_missing')
                if not re.fullmatch(r'(?:Outside Grounds|Jim Graham Building|Kerr Scott Building|Martin Building(?: Gate 9)?|(?:J\.S\. )?Dorton Arena|Agri[- ]?\s*Supply Exposition Center)', venue_label, re.I):
                    raise ValueError('raleigh_direct_venue_unresolved')
                place = (venue_label + ' at N.C. State Fairgrounds', *VENUES[FAIR][1:])
                for day in days:
                    if not window_start <= day <= window_end:
                        continue
                    try:
                        if weekdays is not None and day in closed.get(series, set()):
                            raise ValueError('raleigh_direct_nonpublic')
                        start, end = _fair_times(day, clock_body)
                        if not _within(start, end, now):
                            continue
                        row = _row(FAIR, title, start, end, SOURCES[FAIR][0],
                                   f'{title}:{day.isoformat()}:{venue_label}', body, venue=place)
                        if row:
                            row['schedule_provenance'] = 'publisher_monthly_table_and_time_range'
                            result.append(row)
                    except ValueError as exc:
                        if str(exc) not in HOLD_CODES:
                            raise
                        _hold(diagnostics, identity+':'+day.isoformat(), str(exc))
            except ValueError as exc:
                if str(exc) not in HOLD_CODES:
                    raise
                _hold(diagnostics, identity, str(exc))
    return result


def _squarespace_manifest(key, payload, now, diagnostics):
    from roomquest.chase_city_chamber import _times
    soup = BeautifulSoup(payload, 'html.parser')
    if not soup.select_one('.eventlist'):
        raise ValueError('raleigh_direct_calendar_changed')
    queue = []
    for card in soup.select('article.eventlist-event--upcoming'):
        link = card.select_one('.eventlist-title-link[href]')
        if not link:
            raise ValueError('raleigh_direct_calendar_changed')
        url = urljoin(SOURCES[key][0], link['href'])
        if not event_url(key, url):
            raise ValueError('raleigh_direct_calendar_changed')
        try:
            start, end, _ = _times(card)
            if not _within(start, end, now):
                continue
            # A single evening performance accidentally set to a whole month
            # must not become a continuously ongoing event.
            if end and end-start > timedelta(days=1):
                raise ValueError('raleigh_direct_schedule_conflict')
            title = plain(link.get_text())
            if NONPUBLIC.search(title):
                raise ValueError('raleigh_direct_nonpublic')
            queue.append(dict(url=url, title=title, start=start.isoformat(),
                              end=end.isoformat() if end else None))
        except ValueError as exc:
            reason = str(exc) if str(exc) in HOLD_CODES else 'raleigh_direct_schedule_conflict'
            _hold(diagnostics, url, reason)
    # Pagination cannot silently certify a partial collection.
    if soup.select('.eventlist-pagination .older, .eventlist-pagination .next'):
        raise ValueError('raleigh_direct_calendar_changed')
    return queue


def _squarespace_detail(key, item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    container = soup.select_one('article.eventitem .eventitem-column-content')
    heading = soup.select_one('article.eventitem .eventitem-title')
    schemas = _schemas(soup)
    if not container or not heading or plain(heading.get_text()) != item['title'] or len(schemas) != 1:
        raise ValueError('raleigh_direct_detail_changed')
    event = schemas[0]
    start, end = timestamp(event.get('startDate')), timestamp(event.get('endDate'))
    if start != timestamp(item['start']) or end != timestamp(item['end']):
        raise ValueError('raleigh_direct_schedule_conflict')
    if not _within(start, end, now):
        return []
    body = _body(container)
    if key == OGK:
        if not re.search(r'225\s+S(?:outh)?\.?\s+Wilmington\s+Street', plain(body), re.I):
            raise ValueError('raleigh_direct_venue_unresolved')
    else:
        loc = (event.get('location') or {}).get('address', '')
        if isinstance(loc, dict):
            loc = ' '.join(str(x) for x in loc.values() if isinstance(x, str))
        if not re.search(r'500\s+(?:E\.?|East)\s+Davie\s+(?:St\.?|Street)', plain(loc), re.I):
            raise ValueError('raleigh_direct_venue_unresolved')
    image = event.get('image')
    if isinstance(image, list):
        image = image[0] if image else None
    row = _row(key, item['title'], start, end, item['url'], item['url'], body, photo=image)
    return [row] if row else []


def _state(key, queue, rows, diagnostics, now):
    proof = [{'id': row['id'], 'digest': _digest(row)} for row in rows]
    manifest = queue if queue else proof
    return dict(version=1, source_key=key, started_at=now.astimezone(timezone.utc).isoformat(),
        window_start=calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date().isoformat(),
        manifest_hash=_digest(manifest), manifest_count=len(manifest), cursor=0 if queue else len(manifest),
        queue=queue, seed_proof=proof, events=rows, diagnostics=diagnostics,
        row_hashes={row['id']: _digest(row) for row in rows})


def _checkpoint(key, value, now):
    state = deepcopy(value)
    try:
        started = timestamp(state['started_at'])
        queue = state['queue']
        manifest = queue if queue else state['seed_proof']
        valid = (state['version'] == 1 and state['source_key'] == key
            and -60 <= (now-started).total_seconds() < 4*60*60
            and state['window_start'] == calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date().isoformat()
            and state['manifest_hash'] == _digest(manifest)
            and state['manifest_count'] == len(manifest)
            and type(state['cursor']) is int and 0 <= state['cursor'] <= len(manifest)
            and len(manifest) <= CHECKPOINT_MANIFEST_LIMITS[key]
            and isinstance(state['events'], list) and len(state['events']) <= MAX_RECORDS
            and len(state['diagnostics']) <= 400
            and len(state['row_hashes']) == len(state['events'])
            and all(state['row_hashes'].get(row['id']) == _digest(row) and event_url(key, row['event_url'])
                    and 0 < len(row['description']) <= MAX_DESCRIPTION for row in state['events'])
            and all(event_url(key, item['url']) and timestamp(item['start']) is not None for item in queue))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('raleigh_direct_checkpoint_invalid')
    return state, started


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, read_public_events=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if checkpoint is None:
        if deadline_at is not None and monotonic() + 8 >= deadline_at:
            raise ValueError('collection_deadline')
        payload = fetch(SOURCES[key][0], 'text/html')
        diagnostics = []
        if key in (FAIR, GOODNIGHTS):
            rows = (_fair if key == FAIR else _goodnights)(payload, current, diagnostics)
            state = _state(key, [], rows, diagnostics, current)
        elif key in (GAME, TRC):
            rows = (_game_theory(payload, fetch, read_public_events, current, diagnostics)
                    if key == GAME else _trc(payload, current, diagnostics))
            state = _state(key, [], rows, diagnostics, current)
        else:
            queue = _squarespace_manifest(key, payload, current, diagnostics)
            state = _state(key, queue, [], diagnostics, current)
        started = current
    else:
        state, started = _checkpoint(key, checkpoint, current)
    details = 0
    while state['cursor'] < state['manifest_count']:
        if details >= MAX_DETAILS or (deadline_at is not None and monotonic()+10 >= deadline_at):
            break
        item = state['queue'][state['cursor']]
        try:
            payload = fetch(item['url'], 'text/html')
            rows = _squarespace_detail(key, item, payload, started)
            for row in rows:
                if row['id'] in state['row_hashes']:
                    raise ValueError('raleigh_direct_duplicate_occurrence')
                state['events'].append(row)
                state['row_hashes'][row['id']] = _digest(row)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            _hold(state['diagnostics'], item['url'], str(exc))
        state['cursor'] += 1
        details += 1
    if len(state['events']) > MAX_RECORDS or state['manifest_count'] > CHECKPOINT_MANIFEST_LIMITS[key]:
        raise ValueError('raleigh_direct_record_limit')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('raleigh_direct_checkpoint_size_limit')
    _checkpoint(key, state, current)
    complete = state['cursor'] == state['manifest_count']
    return {'complete': complete, 'events': state['events'] if complete else [], 'checkpoint': state}


def collect(source, fetch, *, deadline_at=None, now=None):
    raise ValueError('publisher_checkpoint_required')
