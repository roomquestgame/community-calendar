"""Mecklenburg YMCA's visible, permitted public program/session HTML.

Scope is the ordinary catalog's linked programs, not the private /core API,
class calendar, registration flow or a claim that the publisher's category
counters describe a complete inventory. All visible divisions/session rows are
accounted for. Full, closed, private, ambiguous and undated sessions are held or
excluded, never translated into cancellations. Backend limited-catalog absence
protection is required for this source. A transport, page-cap or template failure
fails the snapshot rather than returning the successful prefix.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'mecklenburg_ymca_programs_va'
CALENDAR = 'https://mecklenburg.recliquecore.com/programs/'
LOCATIONS = 'https://mecklenburgcountyymca.org/locations.php'
TIMEZONE = 'America/New_York'
MAX_PROGRAM_PAGES = 12
MAX_DIVISIONS = 40
MAX_SESSIONS = 300
MAX_OCCURRENCES = 300
MAX_SERIES_DAYS = 120
MAX_SECONDS = 30
MAX_FACT_TEXT = 50_000
MAX_DESCRIPTION = 2000
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
BRANCH_CITIES = {'Chase City': 'Chase City', 'Clarksville': 'Clarksville', 'Gymnastics': 'Clarksville'}
_DATE = r'\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2})'
_TIME = r'\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?'
_WEEKDAYS = {'Mo': 0, 'Tu': 1, 'We': 2, 'Th': 3, 'Fr': 4, 'Sa': 5, 'Su': 6}
_DAY_NAMES = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split()
_PRIVATE = re.compile(r'\b(?:members?[ -]+only|exclusively for members|invitation[ -]+only|private (?:class|event|session)|competition team only|coach(?:es|[’\']s)? recommendation)\b', re.I)


class SessionHold(ValueError):
    """An identified session lacks unambiguous public occurrence facts."""


class SessionExcluded(ValueError):
    """Publisher explicitly marks this current session outside public intake."""


def _text(node):
    soup = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in soup.select('script, style, template, noscript, .placeholder_link'):
        tag.decompose()
    value = '\n'.join(x.strip() for x in soup.get_text('\n').splitlines() if x.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('ymca_fact_text_limit')
    return value


def _title(value):
    return re.sub(r'^\s*(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', plain(value), flags=re.I)


def _key(value):
    return re.sub(r'[^a-z0-9]+', ' ', plain(value).casefold()).strip()


def program_url(href):
    try:
        if not isinstance(href, str) or re.search(r'[\s\\<>%]|(?:^|/)\.\.(?:/|$)', href):
            raise ValueError
        value = urljoin(CALENDAR, href)
        p = urlsplit(value)
        if (p.scheme != 'https' or p.netloc != 'mecklenburg.recliquecore.com'
                or p.query != 'locations=-1' or p.fragment
                or not re.fullmatch(r'/programs/[1-9]\d*/[a-z0-9]+(?:-[a-z0-9]+)*/', p.path)):
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ValueError('ymca_program_url_unverified') from None


def _no_pagination(node):
    if node.select('[rel~=next], .pagination, [data-next-page], .load-more, [data-load-more]'):
        raise ValueError('ymca_pagination_requires_review')
    if any(re.search(r'[?&]page_n=[1-9]', a.get('href', '')) for a in node.select('a[href]')):
        raise ValueError('ymca_pagination_requires_review')


def discover(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    titles = soup.select('h1.entry-title')
    form, results = soup.select_one('form#search_form'), soup.select_one('#program_results')
    if (len(titles) != 1 or plain(titles[0].get_text()) != 'Programs'
            or form is None or results is None or form.get('action') != '/programs/'):
        raise ValueError('ymca_catalog_structure_unverified')
    all_branches = form.select_one('input[name="locations[]"][value="-1"]')
    all_categories = form.select_one('input[name="categories[]"][value="-1"]')
    page = form.select_one('input[name="page_n"]')
    if (all_branches is None or not all_branches.has_attr('checked')
            or all_categories is None or not all_categories.has_attr('checked')
            or page is None or page.get('value') != '0'):
        raise ValueError('ymca_catalog_scope_unverified')
    _no_pagination(soup)
    cards = results.select('.program')
    if len(cards) > MAX_PROGRAM_PAGES:
        raise ValueError('ymca_program_page_limit')
    if not cards and not re.search(r'\bno (?:available )?programs\b', results.get_text(' ', strip=True), re.I):
        raise ValueError('ymca_catalog_empty_unverified')
    found = {}
    for card in cards:
        anchors = card.select('a.card[href]')
        heading = card.select_one('h3')
        if len(anchors) != 1 or heading is None or not plain(heading.get_text()):
            raise ValueError('ymca_program_card_unverified')
        url = program_url(anchors[0]['href'])
        item = {'url': url, 'title': plain(heading.get_text())}
        if url in found:
            raise ValueError('ymca_duplicate_program_card')
        found[url] = item
    return list(found.values())


def parse_locations(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    found = {}
    for block in soup.select('.locationsCols3'):
        heading, address = block.select_one('h1.locationsTitle'), block.find('p')
        if heading is None:
            raise ValueError('ymca_location_structure_unverified')
        branch = plain(heading.get_text())
        if branch not in BRANCH_CITIES:
            continue
        lines = [plain(x) for x in address.stripped_strings] if address else []
        if len(lines) != 2:
            raise ValueError('ymca_location_address_unverified')
        city = re.fullmatch(r'([^,]+),\s*VA\s+(\d{5}(?:-\d{4})?)', lines[1])
        if (not re.fullmatch(r'\d{1,6}\s+[A-Za-z][^,]*', lines[0]) or not city
                or city[1].strip() != BRANCH_CITIES[branch] or branch in found):
            raise ValueError('ymca_location_address_unverified')
        found[branch] = {'name': 'Mecklenburg County YMCA – ' + branch + (' Branch' if branch != 'Gymnastics' else ''),
                         'address': lines[0] + ', ' + city[1].strip() + ', VA ' + city[2],
                         'city': city[1].strip()}
    if not found:
        raise ValueError('ymca_location_structure_unverified')
    return found


def _day(value):
    match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(20\d{2}|\d{2})', plain(value))
    try:
        if not match:
            raise ValueError
        year = int(match[3]) if len(match[3]) == 4 else 2000 + int(match[3])
        return date(year, int(match[1]), int(match[2]))
    except ValueError:
        raise SessionHold('publisher_date_unresolved') from None


def _date_range(value):
    match = re.fullmatch(rf'({_DATE})(?:\s*[-–—]\s*({_DATE}))?', plain(value))
    if not match:
        raise SessionHold('publisher_date_unresolved')
    first, last = _day(match[1]), _day(match[2] or match[1])
    if last < first:
        raise SessionHold('publisher_date_conflict')
    return first, last


def _clock_pair(value):
    text = plain(value)
    match = re.fullmatch(rf'({_TIME})(?:\s*(?:[-–—]|to)\s*({_TIME}))?', text, re.I)
    if not match:
        raise SessionHold('publisher_time_unresolved')
    parts = [re.sub(r'[\s.]', '', x).lower() if x else None for x in match.groups()]
    suffixes = [re.search(r'[ap]m$', x)[0] if x and re.search(r'[ap]m$', x) else None for x in parts]
    if not any(suffixes) or (parts[1] is None and not suffixes[0]):
        raise SessionHold('publisher_time_unresolved')
    values = []
    for i, part in enumerate(parts):
        if part is None:
            values.append(None)
            continue
        if not suffixes[i]:
            part += suffixes[1 - i]
        try:
            values.append(datetime.strptime(part, '%I:%M%p' if ':' in part else '%I%p').time())
        except ValueError:
            raise SessionHold('publisher_time_unresolved') from None
    # In particular, published "10–12am" is not silently changed to noon.
    if values[1] is not None and values[1] <= values[0]:
        raise SessionHold('publisher_time_conflict')
    return tuple(values)


def _status(raw_title, description, row):
    choices = set()
    prefix = re.match(r'^\s*(cancelled|canceled|postponed)\s*[:–—-]', raw_title, re.I)
    if prefix:
        choices.add(prefix[1].lower().replace('canceled', 'cancelled'))
    text = description + '\n' + _text(row)
    choices.update(x.lower().replace('canceled', 'cancelled') for x in re.findall(
        r'^(?:Status:\s*)?(Cancelled|Canceled|Postponed|Scheduled)\s*$', text, re.I | re.M))
    if len(choices) > 1:
        raise SessionHold('publisher_status_conflict')
    if choices:
        return choices.pop()
    if re.search(r'\b(?:cancelled|canceled|postponed)\b', text, re.I):
        raise SessionHold('publisher_status_unresolved')
    return None


def _session_identity(row):
    match = re.fullmatch(r'session_([1-9]\d*)', row.get('id', ''))
    if not match:
        raise ValueError('ymca_session_identity_missing')
    session = match[1]
    for node in row.select('[data-session-id]'):
        if node.get('data-session-id') != session:
            raise ValueError('ymca_session_identity_conflict')
    for link in row.select('a.reg_single[href]'):
        if link['href'] != '/programs/register/s/' + session + '/':
            raise ValueError('ymca_session_identity_conflict')
    return session


def _registration(row, today):
    box = row.select_one('.class_register_container')
    if box is None:
        raise SessionHold('registration_status_unresolved')
    text = plain(box.get_text(' ', strip=True))
    if re.search(r'\b(?:session is full|sold out)\b', text, re.I):
        raise SessionExcluded('session_full')
    if re.search(r'\bregistration (?:is )?closed\b', text, re.I):
        raise SessionExcluded('registration_closed')
    if len(box.select('a.reg_single[href]')) != 1:
        raise SessionHold('registration_status_unresolved')
    match = re.search(rf'\bCloses\s+({_DATE})\b', text, re.I)
    if not match:
        raise SessionHold('registration_deadline_unresolved')
    closes = _day(match[1])
    if closes < today:
        raise SessionExcluded('registration_deadline_passed')
    return closes


def _fees(division, today):
    tables = division.select('.might-of > .table-responsive > table')
    if len(tables) != 1:
        raise SessionHold('public_registration_cost_unresolved')
    table = tables[0]
    headings = [plain(n.get_text()) for n in table.select('thead th')]
    required = ('Open', 'Close', 'Register At', 'Member', 'Non-Member')
    if any(headings.count(h) != 1 for h in required):
        raise SessionHold('public_registration_cost_unresolved')
    choices = set()
    for row in table.select('tbody tr'):
        cells = [plain(n.get_text(' ', strip=True)) for n in row.find_all('td', recursive=False)]
        if len(cells) != len(headings):
            raise SessionHold('public_registration_cost_unresolved')
        fields = dict(zip(headings, cells))
        opens, closes = _day(fields['Open']), _day(fields['Close'])
        if closes < opens:
            raise SessionHold('registration_date_conflict')
        if opens <= today <= closes:
            costs = []
            for label in ('Member', 'Non-Member'):
                value = fields[label]
                if not re.fullmatch(r'(?:\$\s*\d+(?:\.\d{2})?|free)', value, re.I):
                    raise SessionHold('public_registration_cost_unresolved')
                costs.append(re.sub(r'\$\s+', '$', value))
            choices.add((costs[0], costs[1], fields['Register At'], closes))
    if not choices:
        raise SessionExcluded('registration_pricing_not_open')
    if len(choices) != 1:
        raise SessionHold('registration_cost_conflict')
    return choices.pop()


def _schedule_lines(description, day):
    found = []
    for line in description.splitlines():
        match = re.fullmatch(r'([^:]{2,60}):\s*(\d{1,2}/\d{1,2}(?:/(?:20\d{2}|\d{2}))?),\s*(.+)', line)
        if not match:
            continue
        parts = match[2].split('/')
        if len(parts) == 2:
            try:
                stated = date(day.year, int(parts[0]), int(parts[1]))
            except ValueError:
                raise SessionHold('publisher_date_unresolved') from None
        else:
            stated = _day(match[2])
        if stated == day:
            found.append((plain(match[1]), _clock_pair(match[3])))
    return found


def _row_weekly(label):
    match = re.fullmatch(r'(?:Session\s+\d+\s*[-–—]\s*)?'
                         r'((?:Mo|Tu|We|Th|Fr|Sa|Su)(?:(?:\s*,\s*|\s*/\s*)(?:Mo|Tu|We|Th|Fr|Sa|Su))*)'
                         r'\s*[-–—]\s*(.+)', label)
    if not match:
        return None
    days = {_WEEKDAYS[x] for x in re.findall(r'Mo|Tu|We|Th|Fr|Sa|Su', match[1])}
    return days, _clock_pair(match[2])


def _branch_venue(branch, locations):
    if branch not in locations:
        raise SessionHold('event_venue_unreviewed')
    value = locations[branch]
    return value['name'], value['address'], value['city']


def _explicit_venue(description, locations):
    # Branch affiliations and "All Locations" are never venue evidence.
    statements = re.findall(r'\bat\s+(?:the\s+)?(Chase City|Clarksville|Gymnastics)\s+Branch\b', description, re.I)
    branches = {name for value in statements for name in BRANCH_CITIES if value.casefold() == name.casefold()}
    explicit = []
    for line in description.splitlines():
        match = re.fullmatch(r'(?:Location|Venue):\s*(.+?)[;|]\s*(\d{1,6}\s+[^,]+,\s*([^,]+),\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)', line, re.I)
        if match:
            explicit.append((match[1].strip(), match[2].strip(), match[3].strip()))
    if len(branches) > 1 or len(set(explicit)) > 1 or (branches and explicit):
        raise SessionHold('event_venue_conflict')
    if explicit:
        return explicit[0], None
    if branches:
        branch = next(iter(branches))
        return _branch_venue(branch, locations), branch
    raise SessionHold('event_venue_unreviewed')


def _schedule(first, last, label, description):
    weekly = _row_weekly(label)
    if first == last:
        choices = _schedule_lines(description, first)
        if label in BRANCH_CITIES:
            choices = [x for x in choices if x[0] == label]
        if len(set(choices)) == 1:
            branch, clocks = choices[0]
            if weekly and (first.weekday() not in weekly[0] or weekly[1] != clocks):
                raise SessionHold('publisher_schedule_conflict')
            return [first], clocks, branch
        if choices:
            raise SessionHold('publisher_schedule_conflict')
        if weekly:
            if first.weekday() not in weekly[0]:
                raise SessionHold('publisher_schedule_conflict')
            return [first], weekly[1], None
        times = re.findall(r'^Time:\s*(.+)$', description, re.I | re.M)
        if len(set(times)) == 1:
            return [first], _clock_pair(times[0]), None
        raise SessionHold('publisher_time_unresolved')
    if not weekly:
        raise SessionHold('publisher_time_unresolved')
    if (last - first).days > MAX_SERIES_DAYS:
        raise SessionHold('series_range_requires_review')
    if re.search(r'\b(?:except|excluding|skip|holidays?|no (?:practice|class|classes|sessions?)|not meet)\b', description, re.I):
        raise SessionHold('series_exceptions_require_review')
    # A weekly range can contain holiday gaps expressed only as a finite date
    # list. Until that shape is supported, never invent the omitted weeks.
    months = 'January|February|March|April|May|June|July|August|September|October|November|December'
    if (re.search(rf'\b(?:{months})\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,\s*(?:&\s*)?\d{{1,2}}\b', description, re.I)
            or re.search(r'\b\d{1,2}/\d{1,2}(?:/(?:20\d{2}|\d{2}))?\s*,\s*\d{1,2}/\d{1,2}', description)):
        raise SessionHold('series_explicit_dates_require_review')
    days, clocks = weekly
    for line in description.splitlines():
        stated = re.search(r'\b(?:Sessions?|Classes?)\b.{0,60}?\bon\s+'
                           r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\s+(?:from|at)\s+'
                           rf'({_TIME}\s*[-–—]\s*{_TIME})(?:\s+at\b|\s*[.!]?$)', line, re.I)
        if stated:
            weekday = next(i for i, name in enumerate(_DAY_NAMES) if name.casefold() == stated[1].casefold())
            if days != {weekday} or _clock_pair(stated[2]) != clocks:
                raise SessionHold('publisher_schedule_conflict')
    dates = [first + timedelta(days=i) for i in range((last - first).days + 1)
             if (first + timedelta(days=i)).weekday() in days]
    if not dates or len(dates) > 64:
        raise SessionHold('series_range_requires_review')
    counts = {int(x) for x in re.findall(r'\bfor\s+(\d{1,2})\s+days? of play\b', description, re.I)}
    if counts and counts != {len(dates)}:
        raise SessionHold('series_explicit_dates_require_review')
    return dates, clocks, None


def _note(diagnostics, disposition, session, reason, url, first=None, last=None):
    item = {'id': 'mecklenburg_ymca:session:' + session, 'reason': reason, 'event_url': url}
    if first:
        item['starts_on'] = first.isoformat()
        item['ends_on'] = last.isoformat()
        if first == last:
            item['id'] += ':' + first.isoformat()
    diagnostics.setdefault(disposition, []).append(item)


def _status_row(title, start, end, venue, url, identity, category):
    # Exact negative facts update only an existing backend occurrence. Preserve
    # an unknown end rather than applying the normal three-hour display fallback.
    return {'id': identity, 'title': title[:180],
            'starts_at': start.astimezone(timezone.utc).isoformat(),
            'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
            'venue_name': venue[0][:400], 'venue_address': venue[1][:400], 'venue_city': venue[2][:120],
            'lat': None, 'lng': None, 'event_url': url, 'category': category[:80],
            'reason': 'missing_verified_venue_geo'}


def parse_program(payload, card, locations, *, now=None, diagnostics=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('ymca_now_timezone_missing')
    today = current.astimezone(ZoneInfo(TIMEZONE)).date()
    diagnostics = diagnostics if diagnostics is not None else {}
    url = program_url(card['url'])
    soup = BeautifulSoup(payload, 'html.parser')
    titles, main = soup.select('h1.entry-title'), soup.select_one('#single_program')
    if len(titles) != 1 or main is None or _key(titles[0].get_text()) != _key(card['title']):
        raise ValueError('ymca_program_identity_unverified')
    _no_pagination(main)
    container = main.select_one('#divisions')
    if container is None:
        raise ValueError('ymca_program_structure_unverified')
    divisions = container.select('.division')
    if len(divisions) > MAX_DIVISIONS:
        raise ValueError('ymca_division_limit')
    if not divisions and not re.search(r'\bno (?:available )?(?:sessions|programs)\b', container.get_text(' ', strip=True), re.I):
        raise ValueError('ymca_program_empty_unverified')
    program_description = _text(main.select_one('.content'))
    rows, seen_sessions, seen_divisions = [], set(), set()
    for division in divisions:
        div_id = division.get('id', '')
        heading, content = division.select_one('.top h3'), division.select_one('.bottom .desc')
        if (not re.fullmatch(r'division_[1-9]\d*', div_id) or div_id in seen_divisions
                or heading is None or content is None or not plain(heading.get_text())):
            raise ValueError('ymca_division_structure_unverified')
        seen_divisions.add(div_id)
        raw_title = plain(heading.get_text())
        title, description = _title(raw_title), _text(content)
        combined = program_description + '\n' + description
        if len(combined) > MAX_FACT_TEXT:
            raise ValueError('ymca_fact_text_limit')
        session_tables = division.select('.sessions_container table.sessions')
        if len(session_tables) != 1:
            raise ValueError('ymca_sessions_structure_unverified')
        session_rows = session_tables[0].select('tbody tr')
        if not session_rows and not re.search(r'\bno (?:available )?sessions\b', division.get_text(' ', strip=True), re.I):
            raise ValueError('ymca_sessions_empty_unverified')
        images = {urljoin(url, image.get('src', '')) for image in content.select('img[src]') if image.get('src')}
        candidate = next(iter(images)) if len(images) == 1 else None
        for session_row in session_rows:
            session = _session_identity(session_row)
            if session in seen_sessions:
                raise ValueError('ymca_duplicate_session')
            seen_sessions.add(session)
            if len(seen_sessions) > MAX_SESSIONS:
                raise ValueError('ymca_session_limit')
            dated = session_row.select('.d-inline-block')
            if len(dated) != 2:
                raise ValueError('ymca_session_structure_unverified')
            first = last = None
            try:
                first, last = _date_range(dated[0].get_text(' ', strip=True))
                label = plain(dated[1].get_text(' ', strip=True))
                dates_heading = division.select_one('.top .dates')
                if dates_heading is not None:
                    dates_text = re.sub(r'^Dates:\s*', '', plain(dates_heading.get_text(' ', strip=True)), flags=re.I)
                    bound_first, bound_last = _date_range(dates_text)
                    if first < bound_first or last > bound_last:
                        raise SessionHold('publisher_schedule_conflict')
                status = _status(raw_title, combined, session_row)
                terminal_status = status in ('cancelled', 'postponed')
                earliest = today - timedelta(days=STATUS_LOOKBACK_DAYS) if terminal_status else today
                if last < earliest or first > today + timedelta(days=LOOKAHEAD_DAYS):
                    _note(diagnostics, 'excluded', session, 'outside_collection_window', url, first, last)
                    continue
                registration = fees = None
                if not terminal_status:
                    if _PRIVATE.search(raw_title + '\n' + combined):
                        raise SessionExcluded('nonpublic_or_members_only_session')
                    registration = _registration(session_row, today)
                days, clocks, branch = _schedule(first, last, label, combined)
                try:
                    if branch:
                        venue = _branch_venue(branch, locations)
                    else:
                        venue, branch = _explicit_venue(combined, locations)
                    affiliation = division.select_one('.branches')
                    affiliation = re.sub(r'^Branch:\s*', '', plain(affiliation.get_text(' ', strip=True)), flags=re.I) if affiliation else ''
                    if branch and affiliation in BRANCH_CITIES and branch != affiliation:
                        raise SessionHold('event_venue_conflict')
                except SessionHold:
                    if not terminal_status:
                        raise
                    venue, branch = ('', '', ''), None
                if not terminal_status:
                    fees = _fees(division, today)
                facts = {}
                series = first != last
                context = ''
                if series:
                    context = f'Registered session dates: {first.isoformat()}–{last.isoformat()}. This class is part of that full session.\n\n'
                if fees:
                    member, nonmember, register_at, pricing_close = fees
                    facts['cost'] = ((f'Full session {first.isoformat()}–{last.isoformat()}: ' if series else '')
                                     + f'Member {member}; Non-Member {nonmember}.')[:400]
                    facts['registration'] = ('Registration required. Session registration closes '
                                             + registration.strftime('%m/%d/%Y') + '. Register at: ' + register_at + '.')
                    if pricing_close != registration:
                        facts['registration'] += ' The general pricing table lists ' + pricing_close.strftime('%m/%d/%Y') + '; the session-specific close is stated above.'
                    if re.search(r'\blimited class size\b', combined, re.I):
                        facts['registration'] += ' Publisher notes limited class size.'
                    facts['registration'] = facts['registration'][:400]
                audience = re.search(r'\bAges?\s+\d{1,2}\s*[-–—]\s*\d{1,2}\b', raw_title + '\n' + combined, re.I)
                if audience:
                    facts['audience'] = audience[0][:400]
                # Other branches' dated lines are not this occurrence's venue.
                specific = '\n'.join(line for line in description.splitlines()
                                     if not re.match(r'^(?:Chase City|Clarksville|Gymnastics):\s*\d{1,2}/\d{1,2}', line)
                                     or (branch and line.startswith(branch + ':')))
                narrative = (context + program_description + '\n' + specific).strip()
                for day in days:
                    start = timestamp(datetime.combine(day, clocks[0]).isoformat(), TIMEZONE)
                    end = timestamp(datetime.combine(day, clocks[1]).isoformat(), TIMEZONE) if clocks[1] else None
                    if (start > current + timedelta(days=LOOKAHEAD_DAYS)
                            or (terminal_status and start < current - timedelta(days=STATUS_LOOKBACK_DAYS))
                            or (not terminal_status and (end or start + timedelta(hours=3)) <= current)):
                        continue
                    identity = 'mecklenburg_ymca:session:' + session + ':' + day.isoformat()
                    row = (_status_row(title, start, end, venue, url, identity, card['title']) if terminal_status else
                           record(title, start.isoformat(), end.isoformat() if end else None,
                                  *venue, url, identity, card['title'], tz=TIMEZONE, retain_until_end=True))
                    if row is None:
                        continue
                    row.update(timezone=TIMEZONE, description=narrative[:MAX_DESCRIPTION],
                               publisher_categories=[card['title']],
                               location_provenance=('publisher_session_branch_and_official_directory' if branch and venue[1] else
                                                    'publisher_event_address_pending_geocode' if venue[1] else
                                                    'publisher_explicit_status_without_current_venue'))
                    if status:
                        row['publisher_status'] = status
                    attach(row, SOURCE_KEY, facts=facts, candidate=candidate, evidence_url=url)
                    rows.append(row)
                    if len(rows) > MAX_OCCURRENCES:
                        raise ValueError('ymca_occurrence_limit')
            except SessionExcluded as exc:
                _note(diagnostics, 'excluded', session, str(exc), url, first, last)
            except SessionHold as exc:
                _note(diagnostics, 'held', session, str(exc), url, first, last)
    diagnostics['session_rows'] = diagnostics.get('session_rows', 0) + len(seen_sessions)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_ymca_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    def get(url):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        value = fetch(url, 'text/html')
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        return value
    programs = discover(get(CALENDAR))
    locations = parse_locations(get(LOCATIONS))
    rows, seen, diagnostics = [], set(), {}
    for program in programs:
        parsed = parse_program(get(program['url']), program, locations, now=now, diagnostics=diagnostics)
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        if diagnostics.get('session_rows', 0) > MAX_SESSIONS or len(rows) + len(parsed) > MAX_OCCURRENCES:
            raise ValueError('ymca_source_record_limit')
        for row in parsed:
            if row['id'] in seen:
                raise ValueError('ymca_duplicate_occurrence')
            seen.add(row['id'])
            rows.append(row)
    print(json.dumps({'event': 'ymca_normalized', 'source_key': SOURCE_KEY,
                      'scope': 'visible_program_catalog_only', 'program_pages': len(programs),
                      'records': len(rows), **diagnostics}, sort_keys=True), file=sys.stderr)
    if not rows and diagnostics.get('held'):
        raise ValueError('ymca_event_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
