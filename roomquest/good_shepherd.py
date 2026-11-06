"""The church's explicitly dated Food Pantry calendar occurrences only.

The public calendar renders ordinary HTML through its own read-only AJAX
action. The shared worker supplies that narrowly scoped POST; this module has
no network client. Dates come from rendered calendar rows, never a recurrence
rule inferred from ministry opening hours. Other parish programs remain outside
this reviewed limited catalog, and missing rows never imply cancellation.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'good_shepherd_food_pantry_south_hill_va'
CALENDAR = 'https://goodshepherdsouthhill.org/welcome/calendar/'
FEED_URL = CALENDAR
MINISTRY = 'https://goodshepherdsouthhill.org/ministries/food-pantry/'
RENDER_URL = 'https://goodshepherdsouthhill.org/wp-admin/admin-ajax.php'
TIMEZONE = 'America/New_York'
MAX_SECONDS = 30
MAX_DOCUMENT = 2_000_000
MAX_FACT_TEXT = 50_000
MAX_MONTHS = 8
MAX_ROWS = 400
MAX_DESCRIPTION = 2000
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
VENUE = 'Drops of Love Food Pantry, Church of the Good Shepherd'
ADDRESS = '1664 N Mecklenburg Avenue, South Hill, VA 23970'
_PRIVATE = re.compile(r'\b(?:members?[ -]+only|private (?:event|service)|invitation[ -]+only|exclusively for members)\b', re.I)
_OFFSITE = re.compile(r'\b(?:Location|Venue):|\boff[ -]site\b|\brelocat(?:ed|ing|ion)\b|\bmoved? to\b|\bnew location\b', re.I)


class EventHold(ValueError):
    """A known pantry occurrence has missing or conflicting public facts."""


def _soup(payload):
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('good_shepherd_document_limit')
    return BeautifulSoup(payload, 'html.parser')


def _text(node):
    copy = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in copy.select('script, style, template, noscript'):
        tag.decompose()
    value = '\n'.join(x.strip() for x in copy.get_text('\n').splitlines() if x.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('good_shepherd_fact_text_limit')
    return value


def _canonical(soup, expected):
    nodes = soup.select('link[rel=canonical]')
    if len(nodes) != 1 or nodes[0].get('href') != expected:
        raise ValueError('good_shepherd_page_identity_unverified')


def calendar_request(payload):
    """Read only the public tokens used by the publisher's observed script."""
    soup = _soup(payload)
    _canonical(soup, CALENDAR)
    nodes = soup.select('main .r34ics-ajax-container')
    scripts = soup.select('script#ics-calendar-js-after')
    if len(nodes) != 1 or len(scripts) != 1:
        raise ValueError('good_shepherd_calendar_structure_unverified')
    node = nodes[0]
    matches = re.findall(r'var\s+r34ics_ajax_obj\s*=\s*(\{[^;]+\})\s*;', scripts[0].get_text())
    try:
        config = json.loads(matches[0]) if len(matches) == 1 else None
        args = node.get('data-args', '')
        js_args = json.loads(node.get('data-js-args', ''))
        calendar_id = node.get('id', '')
        month, day = node.get('data-r34icsym', ''), node.get('data-r34icsymd', '')
        if (not isinstance(config, dict) or set(config) != {'ajaxurl', 'r34ics_nonce'}
                or config.get('ajaxurl') != RENDER_URL
                or not re.fullmatch(r'[a-f0-9]{10}', config.get('r34ics_nonce', ''))
                or not re.fullmatch(r'[a-f0-9]{40}', args)
                or js_args != {'debug': False} or node.get('data-view') != 'month'
                or not re.fullmatch(r'r[a-f0-9]{8,40}-ajax', calendar_id)
                or not re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])', month)
                or not re.fullmatch(month + r'\d{2}', day)):
            raise ValueError
        date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    except (ValueError, TypeError, IndexError):
        raise ValueError('good_shepherd_render_request_unverified') from None
    return {'nonce': config['r34ics_nonce'], 'args': args,
            'calendar_id': calendar_id[:-5], 'month': month}


def _identity(day):
    return 'good_shepherd_pantry:' + sha256(('food-pantry\n' + day.isoformat()).encode()).hexdigest()[:32]


def _note(diagnostics, identity, reason):
    diagnostics.setdefault('held', []).append({'id': identity, 'reason': reason, 'event_url': CALENDAR})


def _months(calendar, current, expected_month):
    selectors = calendar.select('select.ics-calendar-select')
    if len(selectors) != 1:
        raise ValueError('good_shepherd_months_unverified')
    selector = selectors[0]
    values = [x.get('value', '') for x in selector.select('option')]
    if (not values or len(values) > MAX_MONTHS or len(set(values)) != len(values)
            or any(not re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])', x) for x in values)):
        raise ValueError('good_shepherd_months_unverified')
    ordinals = [int(x[:4]) * 12 + int(x[4:]) for x in values]
    if ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
        raise ValueError('good_shepherd_months_incomplete')
    local = current.astimezone(ZoneInfo(TIMEZONE))
    this_month = local.strftime('%Y%m')
    last_month = (local + timedelta(days=LOOKAHEAD_DAYS)).strftime('%Y%m')
    if (selector.get('data-this-month') != this_month
            or (expected_month is not None and expected_month != this_month)
            or this_month not in values or last_month not in values):
        raise ValueError('good_shepherd_calendar_window_unverified')
    calendar_id = calendar.get('id', '')
    tables = calendar.select('table.ics-calendar-month-grid')
    labels = [t.get('aria-labelledby') for t in tables]
    if len(tables) != len(values) or labels != [calendar_id + '-' + x for x in values]:
        raise ValueError('good_shepherd_months_incomplete')
    for month, table in zip(values, tables):
        days = []
        for cell in table.select('td'):
            day_classes = [x for x in cell.get('class', []) if re.fullmatch(r'd_\d{2}', x)]
            if not day_classes:
                if cell.select('li.event'):
                    raise ValueError('good_shepherd_calendar_grid_incomplete')
                continue  # Leading/trailing blank grid fillers have no date.
            if len(day_classes) != 1:
                raise ValueError('good_shepherd_calendar_grid_incomplete')
            day_number = int(day_classes[0][2:])
            try:
                day = date(int(month[:4]), int(month[4:]), day_number)
            except ValueError:
                raise ValueError('good_shepherd_calendar_grid_incomplete') from None
            expected_id = calendar_id + '-' + day.strftime('%Y%m%d')
            labels = [x.get('id') for x in cell.select('.day .phone_only[id]')]
            weekday = str((day.weekday() + 1) % 7)
            lists = cell.select('ul.events')
            if (labels != [expected_id] or cell.get('data-dow') != weekday
                    or 'dow_' + weekday not in cell.get('class', []) or len(lists) > 1
                    or (lists and lists[0].get('aria-labelledby') != expected_id)):
                raise ValueError('good_shepherd_calendar_grid_incomplete')
            days.append(day_number)
        if days != list(range(1, monthrange(int(month[:4]), int(month[4:]))[1] + 1)):
            raise ValueError('good_shepherd_calendar_grid_incomplete')
    return set(values)


def _ministry(payload):
    soup = _soup(payload)
    _canonical(soup, MINISTRY)
    mains = soup.select('main .entry-content')
    if len(mains) != 1 or not any(plain(x.get_text()).casefold() == 'drops of love food pantry'
                                  for x in mains[0].select('h1,h2,h3')):
        raise EventHold('pantry_program_identity_unverified')
    narrative = _text(mains[0])
    body = plain(narrative)
    full = plain(_text(soup))
    if _PRIVATE.search(body):
        raise EventHold('nonpublic_program')
    if re.search(r'\b(?:closed|cancelled|canceled|postponed)\b', body, re.I):
        raise EventHold('pantry_program_status_requires_review')
    if not re.search(r'Church of The Good Shepherd, through our Social Ministry, has a food pantry', body, re.I):
        raise EventHold('pantry_program_identity_unverified')
    # This exact reviewed ministry schedule supplies an end time only for
    # individually published Tuesday calendar rows with the matching start.
    if not re.search(r'open on Tuesdays\s+10:30\s*[-–—]\s*12:00\b', body, re.I):
        raise EventHold('pantry_program_hours_unreviewed')
    audience = re.search(r'(for any parishioner or anyone who needs food[.]?)', full, re.I)
    if audience is None:
        raise EventHold('pantry_public_audience_unverified')
    addresses = [plain(p.get_text(' ', strip=True)) for p in soup.select('p')
                 if re.match(r'^Church of the Good Shepherd\s+\d', plain(p.get_text(' ', strip=True)), re.I)]
    if (not addresses or any(not re.fullmatch(
            r'Church of the Good Shepherd\s+1664 N Mecklenburg Avenue\s+South Hill,\s*VA\s+23970', x, re.I)
            for x in addresses) or _OFFSITE.search(body)):
        raise EventHold('event_venue_unreviewed')
    return {'description': narrative, 'audience': audience[1], 'venue': VENUE,
            'address': ADDRESS, 'city': 'South Hill'}


def _status(raw_title, narrative):
    prefix = re.fullmatch(r'(Cancelled|Canceled|Postponed)\s*[:–—-]\s*Food Pantry', raw_title, re.I)
    suffix = re.fullmatch(r'Food Pantry\s*[:–—-]\s*(Cancelled|Canceled|Postponed)', raw_title, re.I)
    title = 'Food Pantry' if prefix or suffix else raw_title
    choices = {(prefix or suffix)[1].lower().replace('canceled', 'cancelled')} if prefix or suffix else set()
    choices.update(x.lower().replace('canceled', 'cancelled') for x in re.findall(
        r'^(?:Status:\s*)?(Scheduled|Cancelled|Canceled|Postponed)\s*$', narrative, re.I | re.M))
    if len(choices) > 1:
        raise EventHold('publisher_status_conflict')
    status = choices.pop() if choices else None
    if not status and re.search(r'\b(?:cancelled|canceled|postponed)\b', narrative, re.I):
        raise EventHold('publisher_status_unresolved')
    return title, status


def _terminal_row(start, end, identity, program):
    return {'id': identity, 'title': 'Food Pantry', 'starts_at': start.astimezone(timezone.utc).isoformat(),
            'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
            'venue_name': program['venue'] if program else '',
            'venue_address': program['address'] if program else '',
            'venue_city': program['city'] if program else '', 'lat': None, 'lng': None,
            'event_url': CALENDAR, 'category': '', 'reason': 'missing_verified_venue_geo'}


def parse(payload, ministry_payload, *, now=None, diagnostics=None,
          expected_calendar_id=None, expected_month=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('good_shepherd_now_timezone_missing')
    diagnostics = diagnostics if diagnostics is not None else {}
    soup = _soup(payload)
    calendars = soup.select('.ics-calendar')
    if len(calendars) != 1:
        raise ValueError('good_shepherd_render_structure_unverified')
    calendar = calendars[0]
    calendar_id = calendar.get('id', '')
    if (not re.fullmatch(r'r[a-f0-9]{8,40}', calendar_id)
            or (expected_calendar_id is not None and calendar_id != expected_calendar_id)
            or calendar.select('[rel~=next], .pagination, [data-next-page]')):
        raise ValueError('good_shepherd_calendar_identity_unverified')
    _text(calendar)
    months = _months(calendar, current, expected_month)
    entries = calendar.select('li.event')
    if len(entries) > MAX_ROWS:
        raise ValueError('good_shepherd_source_record_limit')
    if sum(len(table.select('li.event')) for table in calendar.select('table.ics-calendar-month-grid')) != len(entries):
        raise ValueError('good_shepherd_calendar_grid_incomplete')
    # A clipped table cannot look like an empty or complete calendar.
    for cell in calendar.select('td[data-events-count]'):
        count = cell.get('data-events-count', '')
        if not re.fullmatch(r'\d{1,3}', count) or int(count) != len(cell.select('li.event')):
            raise ValueError('good_shepherd_calendar_rows_incomplete')
    try:
        program, program_error = _ministry(ministry_payload), None
    except EventHold as exc:
        program, program_error = None, str(exc)
    rows, seen = [], {}
    diagnostics['calendar_rows'] = len(entries)
    for entry in entries:
        titles = entry.find_all(class_='title', recursive=False)
        if len(titles) != 1:
            raise ValueError('good_shepherd_row_structure_unverified')
        raw_title = plain(titles[0].get_text())
        narrative = _text(entry)
        classes = entry.get('class', [])
        dates = [x[1:] for x in classes if re.fullmatch(r'd\d{8}', x)]
        diagnostic_id = 'good_shepherd_pantry:row:' + sha256((raw_title + '\n' + ','.join(dates)).encode()).hexdigest()[:16]
        if not re.search(r'\bfood pantry\b', raw_title, re.I):
            diagnostics['other_program_rows'] = diagnostics.get('other_program_rows', 0) + 1
            continue
        try:
            title, status = _status(raw_title, narrative)
            if title.casefold() != 'food pantry':
                _note(diagnostics, diagnostic_id, 'pantry_title_or_closure_requires_review')
                continue
            terminal = status in ('cancelled', 'postponed')
            if not terminal and (_PRIVATE.search(narrative) or re.search(r'\bclosed\b', narrative, re.I)):
                _note(diagnostics, diagnostic_id, 'nonpublic_or_closed_occurrence')
                continue
            times = [x[1:] for x in classes if re.fullmatch(r't\d{6}', x)]
            if len(dates) != 1 or len(times) != 1:
                raise EventHold('publisher_date_or_time_unresolved')
            try:
                day = datetime.strptime(dates[0], '%Y%m%d').date()
                wall = datetime.strptime(times[0], '%H%M%S').time()
            except ValueError:
                raise EventHold('publisher_date_or_time_unresolved') from None
            identity = diagnostic_id = _identity(day)
            table = entry.find_parent('table', class_='ics-calendar-month-grid')
            events = entry.find_parent('ul', class_='events')
            if (dates[0][:6] not in months or table is None or events is None
                    or table.get('aria-labelledby') != calendar_id + '-' + dates[0][:6]
                    or events.get('aria-labelledby') != calendar_id + '-' + dates[0]):
                raise EventHold('publisher_date_conflict')
            shown = entry.find_all(class_='time', recursive=False)
            if (len(shown) > 1 or (not terminal and len(shown) != 1)
                    or (shown and plain(shown[0].get_text()).upper() != '10:30 AM')
                    or wall != time(10, 30) or day.weekday() != 1):
                raise EventHold('pantry_occurrence_hours_conflict')
            start = timestamp(datetime.combine(day, wall).isoformat(), TIMEZONE)
            if (start > current + timedelta(days=LOOKAHEAD_DAYS)
                    or (terminal and start < current - timedelta(days=STATUS_LOOKBACK_DAYS))
                    or (not terminal and timestamp(datetime.combine(day, time(12)).isoformat(), TIMEZONE) <= current)):
                diagnostics['outside_window'] = diagnostics.get('outside_window', 0) + 1
                continue
            if program is None and not terminal:
                raise EventHold(program_error)
            end = timestamp(datetime.combine(day, time(12)).isoformat(), TIMEZONE) if program else None
            row = (_terminal_row(start, end, identity, program) if terminal else
                   record('Food Pantry', start.isoformat(), end.isoformat(), program['venue'], program['address'],
                          program['city'], CALENDAR, identity, tz=TIMEZONE, retain_until_end=True))
            if row is None:
                continue
            row.update(timezone=TIMEZONE, description=(program['description'] if program else narrative)[:MAX_DESCRIPTION],
                       location_provenance=('publisher_named_pantry_and_current_ministry_address' if program else
                                            'publisher_explicit_status_without_current_venue'),
                       publisher_categories=[])
            if status:
                row['publisher_status'] = status
            attach(row, SOURCE_KEY, facts={'audience': program['audience']} if program else {})
            if identity in seen:
                if seen[identity] != row:
                    raise ValueError('good_shepherd_conflicting_occurrence')
                continue
            seen[identity] = row
            rows.append(row)
        except EventHold as exc:
            _note(diagnostics, diagnostic_id, str(exc))
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, render_calendar, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_good_shepherd_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    def check():
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
    def get(url):
        check()
        value = fetch(url, 'text/html')
        check()
        return value
    request = calendar_request(get(CALENDAR))
    check()
    rendered = render_calendar(nonce=request['nonce'], args=request['args'])
    check()
    ministry = get(MINISTRY)
    diagnostics = {}
    rows = parse(rendered, ministry, now=now, diagnostics=diagnostics,
                 expected_calendar_id=request['calendar_id'], expected_month=request['month'])
    check()
    print(json.dumps({'event': 'good_shepherd_normalized', 'source_key': SOURCE_KEY,
                      'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('good_shepherd_event_evidence_unavailable')
    return rows
