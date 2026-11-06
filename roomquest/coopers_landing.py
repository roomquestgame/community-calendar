"""Cooper's published, year-scoped Monday cooking classes.

The maintained Class Schedule is a limited HTML catalog. The separate holiday
list omits occurrence years and is deliberately not a collection endpoint.
Weekend lodging packages, private bookings and generic page artwork are not
events or event images. All network access is supplied by the shared worker.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'coopers_landing_clarksville_va'
CALENDAR = 'https://cooperslandinginn.net/?page_id=119'
FEED_URL = CALENDAR
TIMEZONE = 'America/New_York'
MAX_SECONDS = 20
MAX_DOCUMENT = 2_000_000
MAX_FACT_TEXT = 50_000
MAX_CARDS = 60
MAX_DESCRIPTION = 2000
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
VENUE = "Cooper's Landing Inn Cooking School"
ADDRESS = '801 Virginia Avenue, Clarksville, VA 23927'
_MONTHS = {}
for _number, _name in enumerate('January February March April May June July August September October November December'.split(), 1):
    _MONTHS[_name.lower()] = _MONTHS[_name[:3].lower()] = _number
_DATE = re.compile(r'(Mon(?:day)?)[.]?\s+([A-Za-z]+)[.]?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?', re.I)
_CLOCK = r'\d{1,2}:\d{2}(?:\s*[ap][.]?m[.]?)?'
_PRIVATE = re.compile(r'\b(?:private (?:class|event|party)|members?[ -]+only|invitation[ -]+only|exclusively for members)\b', re.I)
_OFFSITE = re.compile(r'\b(?:Location|Venue):|\boff[ -]site\b|\brelocat(?:ed|ing|ion)\b|\bmoved? to\b|\bnew location\b', re.I)


class EventHold(ValueError):
    """A dated class needs reviewed, non-conflicting publisher facts."""


def _text(node):
    copy = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in copy.select('script, style, template, noscript'):
        tag.decompose()
    value = '\n'.join(x.strip() for x in copy.get_text('\n').splitlines() if x.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('cooper_fact_text_limit')
    return value


def _identity(day):
    return 'coopers_landing:' + sha256(('class\n' + day.isoformat()).encode()).hexdigest()[:32]


def _note(diagnostics, disposition, identity, reason):
    diagnostics.setdefault(disposition, []).append({'id': identity, 'reason': reason, 'event_url': CALENDAR})


def _status(title, narrative):
    choices = set()
    prefix = re.match(r'^\s*(cancelled|canceled|postponed)\s*[:–—-]', title, re.I)
    if prefix:
        choices.add(prefix[1].lower().replace('canceled', 'cancelled'))
    choices.update(x.lower().replace('canceled', 'cancelled') for x in re.findall(
        r'^(?:Status:\s*)?(Scheduled|Cancelled|Canceled|Postponed)\s*$', narrative, re.I | re.M))
    if len(choices) > 1:
        raise EventHold('publisher_status_conflict')
    if choices:
        return choices.pop()
    if re.search(r'\b(?:cancelled|canceled|postponed)\b', narrative, re.I):
        raise EventHold('publisher_status_unresolved')
    return None


def _label(value):
    return re.sub(r'^\s*(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', plain(value), flags=re.I)


def _evening_clock(value):
    value = re.sub(r'[\s.]', '', value).upper()
    if not re.fullmatch(r'\d{1,2}:\d{2}(?:AM|PM)?', value):
        raise EventHold('publisher_time_unresolved')
    # The reviewed heading says Monday Night / Evening. Do not apply this to
    # arbitrary classes or to a new morning program.
    if value.endswith('AM'):
        raise EventHold('publisher_time_conflict')
    if not value.endswith('PM'):
        value += 'PM'
    try:
        return datetime.strptime(value, '%I:%M%p').time()
    except ValueError:
        raise EventHold('publisher_time_unresolved') from None


def _program(body):
    headings = [node for node in body.select('.menuitem')
                if plain(node.get_text()).casefold() == 'monday night evening class & small bites']
    if len(headings) != 1:
        raise ValueError('cooper_program_structure_unverified')
    parent = headings[0].find_parent('p')
    if parent is None:
        raise ValueError('cooper_program_structure_unverified')
    parts = []
    for node in parent.find_next_siblings():
        if node.select_one('.menuitem'):
            break
        parts.append(_text(node))
    narrative = '\n'.join(parts).strip()
    if not narrative or len(narrative) > MAX_FACT_TEXT:
        raise ValueError('cooper_program_structure_unverified')
    text = plain(narrative)
    # A conditional minimum-enrollment cancellation policy is not a current
    # cancellation. A newly published blanket status needs explicit review.
    if re.search(r'\bclasses? (?:are|is|have been|will be) (?:cancelled|canceled|postponed)\b', text, re.I):
        raise EventHold('publisher_program_status_requires_review')
    span = re.search(rf'All Monday night classes will be held from\s+({_CLOCK})\s*[–—-]\s*({_CLOCK})', text, re.I)
    start = _evening_clock(span[1]) if span else None
    end = _evening_clock(span[2]) if span else None
    if start and end <= start:
        raise EventHold('publisher_time_conflict')
    if start and re.search(r'\btwo[ -]hour Monday night session\b', text, re.I):
        if (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute) != 120:
            raise EventHold('publisher_time_conflict')
    reception = re.search(rf'gather in the tavern at\s+({_CLOCK})', text, re.I)
    reception = _evening_clock(reception[1]) if reception else None
    cost = re.search(r'Price:\s*(\$\d+(?:\.\d{2})?\s+per person(?:\s+plus taxes)?[.]?)', text, re.I)
    registration = re.search(r'(For Monday Night Cooking Classes,.*?)(?=Cooper[’\']s Landing|$)', text, re.I)
    facts = {}
    if cost:
        facts['cost'] = cost[1]
    if registration:
        facts['registration'] = registration[1].strip()[:400]
    return narrative, start, end, facts, reception


def _venue(soup, body, card_text, program_text):
    intro = plain(_text(body))
    introductions = [plain(p.get_text(' ', strip=True)) for p in body.select('p')
                     if 'Kitchen Classroom' in p.get_text()]
    address_blocks = [plain(node.get_text(' ', strip=True)) for node in soup.select('#widgetbody')]
    if (not re.search(r'Cooper[’\']s Landing', intro, re.I) or 'Kitchen Classroom' not in intro
            or not any(re.search(r'\b801 Virginia Avenue\s+Clarksville,\s*VA\s+23927\b', x) for x in address_blocks)
            or _OFFSITE.search(card_text + '\n' + program_text + '\n' + '\n'.join(introductions))):
        raise EventHold('event_venue_unreviewed')
    return VENUE, ADDRESS, 'Clarksville'


def _terminal_row(title, day_start, end, identity, venue, address, city):
    return {'id': identity, 'title': title[:180], 'starts_at': day_start.astimezone(timezone.utc).isoformat(),
            'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
            'venue_name': venue, 'venue_address': address, 'venue_city': city,
            'lat': None, 'lng': None, 'event_url': CALENDAR, 'category': '',
            'reason': 'missing_verified_venue_geo'}


def parse(payload, *, now=None, diagnostics=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('cooper_now_timezone_missing')
    diagnostics = diagnostics if diagnostics is not None else {}
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('cooper_document_limit')
    soup = BeautifulSoup(payload, 'html.parser')
    canonical = soup.select('link[rel=canonical]')
    bodies = soup.select('#content-aa')
    if (len(canonical) != 1 or canonical[0].get('href') != CALENDAR or len(bodies) != 1
            or not any(plain(h.get_text()).casefold() == 'class schedule' for h in bodies[0].select('h1,h2,h3'))):
        raise ValueError('cooper_listing_structure_unverified')
    body = bodies[0]
    body_text = _text(body)
    if body.select('[rel~=next], .pagination, [data-next-page]'):
        raise ValueError('cooper_pagination_requires_review')
    program_error = None
    try:
        program_text, program_start, program_end, program_facts, program_reception = _program(body)
    except EventHold as exc:
        program_error = str(exc)
    except ValueError as exc:
        if str(exc) != 'cooper_program_structure_unverified':
            raise
        program_error = str(exc)
    if program_error:
        program_text, program_start, program_end, program_facts, program_reception = '', None, None, {}, None
    rows, seen, year, count = [], {}, None, 0
    for node in body.find_all(['p', 'h2', 'h3'], recursive=False):
        text = plain(node.get_text(' ', strip=True))
        heading = re.fullmatch(r'(20\d{2})\s+Classes', text, re.I)
        if heading:
            year = int(heading[1])
            continue
        if node.select_one('.menuitem') and text.casefold() == 'monday night evening class & small bites':
            break
        strong = node.find('strong', recursive=False)
        if strong is None:
            continue
        raw_label = plain(strong.get_text())
        label = _label(raw_label)
        if not re.search(r'\bcooking\b|\bclass\b', label, re.I):
            continue
        count += 1
        if count > MAX_CARDS:
            raise ValueError('cooper_source_record_limit')
        card_text = _text(node)
        diagnostic_id = 'coopers_landing:card:' + sha256(card_text.encode()).hexdigest()[:16]
        if 'weekend' in label.casefold():
            _note(diagnostics, 'excluded', diagnostic_id, 'lodging_package_without_complete_session_schedule')
            continue
        if label.casefold() not in ('local monday night cooking class', 'monday night local cooking class'):
            _note(diagnostics, 'held', diagnostic_id, 'unreviewed_class_program')
            continue
        try:
            status = _status(raw_label, card_text)
            terminal = status in ('cancelled', 'postponed')
            if not terminal and _PRIVATE.search(card_text + '\n' + program_text):
                _note(diagnostics, 'excluded', diagnostic_id, 'nonpublic_event')
                continue
            dates = [m for line in card_text.splitlines() if (m := _DATE.fullmatch(line))]
            if len(dates) != 1:
                raise EventHold('publisher_date_unresolved')
            stated = dates[0]
            if not year or (stated[4] and int(stated[4]) != year):
                raise EventHold('publisher_year_unresolved')
            try:
                day = date(year, _MONTHS[stated[2].lower()], int(stated[3]))
            except (ValueError, KeyError):
                raise EventHold('publisher_date_unresolved') from None
            if day.weekday() != 0:
                raise EventHold('publisher_schedule_conflict')
            identity = diagnostic_id = _identity(day)
            clocks = re.findall(rf'({_CLOCK})\s+class begins\b', plain(card_text), re.I)
            if len(clocks) != 1:
                raise EventHold('publisher_time_unresolved')
            wall = _evening_clock(clocks[0])
            if program_start and wall != program_start:
                raise EventHold('publisher_time_conflict')
            receptions = re.findall(rf'({_CLOCK})\s+Wine\s*&\s*Cheese reception\b', plain(card_text), re.I)
            if len(receptions) > 1:
                raise EventHold('publisher_time_conflict')
            if receptions:
                reception = _evening_clock(receptions[0])
                if reception >= wall or (program_reception and reception != program_reception):
                    raise EventHold('publisher_time_conflict')
            start = timestamp(datetime.combine(day, wall).isoformat(), TIMEZONE)
            end = timestamp(datetime.combine(day, program_end).isoformat(), TIMEZONE) if program_end else None
            if (start > current + timedelta(days=LOOKAHEAD_DAYS)
                    or (terminal and start < current - timedelta(days=STATUS_LOOKBACK_DAYS))
                    or (not terminal and (end or start + timedelta(hours=3)) <= current)):
                diagnostics['outside_window'] = diagnostics.get('outside_window', 0) + 1
                continue
            if program_error and not terminal:
                raise EventHold(program_error)
            topic = re.search(r'Topic:\s*[“\"]([^”\"]+)[”\"]', plain(card_text), re.I)
            if not topic and not terminal:
                raise EventHold('class_topic_unresolved')
            title = label + (' — ' + topic[1].strip() if topic else '')
            try:
                venue, address, city = _venue(soup, body, card_text, program_text)
            except EventHold:
                if not terminal:
                    raise
                venue = address = city = ''
            row = (_terminal_row(title, start, end, identity, venue, address, city) if terminal else
                   record(title, start.isoformat(), end.isoformat() if end else None,
                          venue, address, city, CALENDAR, identity, tz=TIMEZONE, retain_until_end=True))
            if row is None:
                continue
            row.update(timezone=TIMEZONE, description=(card_text + '\n\n' + program_text)[:MAX_DESCRIPTION],
                       location_provenance=('publisher_named_cooking_school_and_current_address' if address else
                                            'publisher_explicit_status_without_current_venue'),
                       publisher_categories=[])
            if status:
                row['publisher_status'] = status
            facts = dict(program_facts)
            upcharge = re.search(r'\$\d+(?:\.\d{2})?\s+upcharge', card_text, re.I)
            if upcharge and facts.get('cost'):
                facts['cost'] = (facts['cost'] + ' ' + upcharge[0])[:400]
            attach(row, SOURCE_KEY, facts=facts)
            if identity in seen:
                if seen[identity] != row:
                    raise ValueError('cooper_conflicting_occurrence')
                continue
            seen[identity] = row
            rows.append(row)
        except EventHold as exc:
            _note(diagnostics, 'held', diagnostic_id, str(exc))
    diagnostics['schedule_cards'] = count
    if not count and not re.search(r'\bno upcoming classes\b', body_text, re.I):
        raise ValueError('cooper_listing_empty_unverified')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_cooper_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    payload = fetch(CALENDAR, 'text/html')
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    diagnostics = {}
    rows = parse(payload, now=now, diagnostics=diagnostics)
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
    print(json.dumps({'event': 'coopers_landing_normalized', 'source_key': SOURCE_KEY,
                      'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('cooper_event_evidence_unavailable')
    return rows
