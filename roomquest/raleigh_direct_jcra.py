"""JCRA's supplemental children and hands-on workshop calendar.

The healthy NC State Localist source already covers its tours, lectures,
photography, Forest Bathing and Moonlight programs.  This profile discovers
only native children-marked programs, workshops and Art and Blooms.  Complete
monthly listings and full detail bodies are required before publication.
Self-guided dates use the publisher's seasonal hours and explicit closures,
never the midnight placeholders in its downloadable calendar.
"""
from __future__ import annotations

from copy import deepcopy
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
SOURCE = 'jc_raulston_family_workshops_nc'
CALENDAR = 'https://jcra.ncsu.edu/events/calendar/index.php'
HOURS = 'https://jcra.ncsu.edu/visit/visitor-information.php'
SOURCES = {SOURCE: (CALENDAR, 'html', 'html')}
LABELS = {SOURCE: 'JC Raulston Arboretum — Children & Workshops'}
VENUE = ('JC Raulston Arboretum', '4415 Beryl Road, Raleigh, NC 27606', 'Raleigh')
ALLOWED_HOSTS = {SOURCE: ('jcra.ncsu.edu',)}
CHECKPOINT_KEYS = {SOURCE}
CHECKPOINT_MANIFEST_LIMITS = {SOURCE: 120}
CHECKPOINT_EVENT_LIMITS = {SOURCE: 300}
MAX_BYTES = 850000
PREFIX = 'raleigh_jcra_'
PROVENANCE = 'reviewed_publisher_street_pending_geocode'
HOLD_CODES = {PREFIX + x for x in ('not_public', 'sold_out', 'schedule_unresolved',
    'description_missing', 'outside_window')}
ERROR_CODES = HOLD_CODES | {PREFIX + x for x in ('source_unregistered', 'calendar_changed',
    'detail_identity', 'street_unresolved', 'description_limit', 'manifest_limit',
    'checkpoint_invalid', 'checkpoint_size_limit')}
ERROR_CODES |= {'collection_deadline', 'publisher_checkpoint_required'}
MONTHS = {datetime(2000, n, 1).strftime('%B'): n for n in range(1, 13)}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def _source(source):
    if (source.get('source_key') != SOURCE or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[SOURCE], ZONE)):
        raise ValueError(PREFIX + 'source_unregistered')


def event_url(key, value):
    return (key == SOURCE and isinstance(value, str) and bool(re.fullmatch(
        r'https://jcra[.]ncsu[.]edu/events/details[.]php\?ID=[1-9]\d{0,6}', value)))


def photo_url(value):
    if not isinstance(value, str):
        return None
    url = urljoin(CALENDAR, value)
    return url if re.fullmatch(r'https://jcra[.]ncsu[.]edu/photographs/[A-Za-z0-9_./% -]+[.](?:jpg|jpeg|png)',
        url, re.I) and not re.search(r'(?:\.\.|%2e|%2f|%5c|\s)', url, re.I) else None


def _window(anchor):
    first = anchor.astimezone(ZoneInfo(ZONE)).date()
    return first, first + timedelta(days=60)


def _plans(anchor):
    first, end = _window(anchor)
    months, day = [], first.replace(day=1)
    while day < end:
        months.append({'url': CALENDAR if not months else CALENDAR + f'?year={day.year}&month={day.month}',
                       'year': day.year, 'month': day.month})
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return months + [{'url': HOURS, 'year': None, 'month': None}]


def _clock(value):
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', plain(value), re.I)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return time(int(match[1]) % 12 + (12 if match[3].lower() == 'pm' else 0), int(match[2] or 0))


def _hours(payload, anchor):
    soup = BeautifulSoup(payload, 'html.parser')
    section = soup.select_one('main section[aria-labelledby="hours-heading"]')
    if not section:
        raise ValueError(PREFIX + 'calendar_changed')
    seasons = {}
    expected = {'April 1 through September 30': ('summer', {'Monday — Thursday': [0, 1, 2, 3],
        'Friday': [4], 'Saturday — Sunday': [5, 6]}),
        'October 1 through March 31': ('winter', {'Monday — Friday': [0, 1, 2, 3, 4],
        'Saturday — Sunday': [5, 6]})}
    for heading in section.find_all('h3'):
        label = plain(heading.get_text(' ', strip=True))
        if label not in expected:
            raise ValueError(PREFIX + 'calendar_changed')
        name, days = expected[label]
        values = [None] * 7
        dl = heading.find_next_sibling('dl')
        if dl is None or len(dl.find_all('dt', recursive=False)) != len(days):
            raise ValueError(PREFIX + 'calendar_changed')
        for dt in dl.find_all('dt', recursive=False):
            day_label = plain(dt.get_text(' ', strip=True))
            dd = dt.find_next_sibling('dd')
            if day_label not in days or dd is None:
                raise ValueError(PREFIX + 'calendar_changed')
            clocks = re.split(r'\s+-\s+', plain(dd.get_text(' ', strip=True)))
            if len(clocks) != 2:
                raise ValueError(PREFIX + 'calendar_changed')
            start, end = map(_clock, clocks)
            if not time(6) <= start < end <= time(22):
                raise ValueError(PREFIX + 'calendar_changed')
            for weekday in days[day_label]:
                values[weekday] = [start.isoformat(), end.isoformat()]
        if any(x is None for x in values) or name in seasons:
            raise ValueError(PREFIX + 'calendar_changed')
        seasons[name] = values
    if set(seasons) != {'summer', 'winter'}:
        raise ValueError(PREFIX + 'calendar_changed')
    closures, resolved = {}, True
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        if 'closure alert' not in heading.get_text(' ', strip=True).lower():
            continue
        paragraph = heading.find_next_sibling('p')
        if paragraph is None:
            resolved = False
            continue
        alert = plain(paragraph.get_text(' ', strip=True))
        match = re.fullmatch(r'The JC Raulston Arboretum will close at (\d{1,2}(?::\d{2})?\s*(?:am|pm)) '
            r'on Moonlight in the Garden event nights: Thursday, (\w+) (\d{1,2}) and Fridays and Saturdays, '
            r'(\w+) ([\d, and]+)[.]', alert, re.I)
        if not match or match[2] not in MONTHS or match[4] != match[2]:
            resolved = False
            continue
        month = MONTHS[match[2]]
        year = anchor.astimezone(ZoneInfo(ZONE)).year
        if month < anchor.month - 6:
            year += 1
        clock = _clock(match[1]).isoformat()
        for number in [match[3]] + re.findall(r'\d+', match[5]):
            closures[date(year, month, int(number)).isoformat()] = clock
    return {'seasons': seasons, 'closures': closures, 'closures_resolved': resolved}


def _listing(payload, plan, anchor):
    soup = BeautifulSoup(payload, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    expected = datetime(plan['year'], plan['month'], 1).strftime('%B %Y')
    if 'JC Raulston Arboretum Events Calendar for ' + expected != title:
        raise ValueError(PREFIX + 'calendar_changed')
    month_name = datetime(plan['year'], plan['month'], 1).strftime('%B').lower()
    day_nodes = soup.find_all('h2', attrs={'aria-label': re.compile(r'^' + month_name + r' \d+$')})
    day_numbers = []
    for node in day_nodes:
        rendered = plain(node.get_text(' ', strip=True))
        if not rendered.isdigit() or node['aria-label'] != month_name + ' ' + str(int(rendered)):
            raise ValueError(PREFIX + 'calendar_changed')
        day_numbers.append(int(rendered))
    if sorted(day_numbers) != list(range(1, monthrange(plan['year'], plan['month'])[1] + 1)):
        raise ValueError(PREFIX + 'calendar_changed')
    first, end = _window(anchor)
    rows = {}
    cards = soup.select('p.calendar-text')
    if not cards and not soup.find('h1', string=re.compile(re.escape(expected))):
        raise ValueError(PREFIX + 'calendar_changed')
    for card in cards:
        links = card.select('a[href*="/events/details.php?ID="]')
        if len(links) != 1:
            raise ValueError(PREFIX + 'calendar_changed')
        link = links[0]
        name = plain(link.get_text(' ', strip=True))
        children = card.select_one('.childrens-program-asterisk') is not None
        if not (children or re.search(r'\bWorkshop\b', name, re.I)
                or name in {'Holiday Creations', 'Art and Blooms at the JCRA'}):
            continue
        # Scope is explicit; ordinary healthy Localist programs never enter it.
        if re.search(r'\b(?:registration opens|members only)\b', name, re.I):
            continue
        text = plain(card.get_text(' ', strip=True))
        if 'In Person' not in text:
            continue
        day_node = card.parent.find('h2', attrs={'aria-label': re.compile(r'^[a-z]+ \d+$')})
        if day_node is None:
            raise ValueError(PREFIX + 'calendar_changed')
        day = date(plan['year'], plan['month'], int(day_node.get_text(strip=True)))
        if not first <= day < end:
            continue
        url = urljoin(CALENDAR, link['href'])
        if not event_url(SOURCE, url):
            raise ValueError(PREFIX + 'detail_identity')
        identity = parse_qs(urlsplit(url).query)['ID'][0]
        item = rows.setdefault(identity, {'id': identity, 'url': url, 'title': name,
            'days': [], 'children': children, 'listed_sold_out': False})
        if item['title'] != name or item['children'] != children or day.isoformat() in item['days']:
            raise ValueError(PREFIX + 'calendar_changed')
        item['days'].append(day.isoformat())
        item['listed_sold_out'] |= bool(re.search(r'full\s*[—-]\s*waitlist|sold out', text, re.I))
    return list(rows.values())


def _merge(queue, incoming):
    keyed = {item['id']: item for item in queue}
    for item in incoming:
        if item['id'] not in keyed:
            queue.append(item)
            keyed[item['id']] = item
        else:
            old = keyed[item['id']]
            if any(old[k] != item[k] for k in ('url', 'title', 'children', 'listed_sold_out')):
                raise ValueError(PREFIX + 'calendar_changed')
            if set(old['days']) & set(item['days']):
                raise ValueError(PREFIX + 'calendar_changed')
            old['days'] = sorted(old['days'] + item['days'])
    queue.sort(key=lambda x: (x['days'][0], x['id']))
    if len(queue) > 120:
        raise ValueError(PREFIX + 'manifest_limit')


def _body(main):
    # A cost/location block alone does not establish event-specific prose.
    paragraphs = [p for p in main.find_all('p') if p.find_parent('dl') is None]
    if not any(len(plain(p.get_text(' ', strip=True))) >= 40 for p in paragraphs):
        raise ValueError(PREFIX + 'description_missing')
    node = BeautifulSoup(str(main), 'html.parser')
    for element in node.select('h1, a.btn, .btn-group, .badge, .sr-only'):
        element.decompose()
    for heading in node.find_all('h2'):
        if heading.select_one('.eventdates') or 'during garden open hours' in heading.get_text(' ', strip=True):
            heading.decompose()
    text = description(str(node), limit=12001)
    if len(text) > 12000:
        raise ValueError(PREFIX + 'description_limit')
    if len(text) < 60 or not re.search(r'[A-Za-z]{3}', text):
        raise ValueError(PREFIX + 'description_missing')
    return text


def _visible_day_range(main, item, anchor):
    headings = [plain(h.get_text(' ', strip=True)) for h in main.find_all('h2')
                if 'during garden open hours' in h.get_text(' ', strip=True).lower()]
    if len(headings) != 1:
        raise ValueError(PREFIX + 'schedule_unresolved')
    match = re.fullmatch(r'(\w+), (\w+) (\d{1,2}) through (\w+), (\w+) (\d{1,2})(?:, (20\d{2}))?'
        r' — during garden open hours', headings[0])
    if not match or match[2] not in MONTHS or match[5] not in MONTHS:
        raise ValueError(PREFIX + 'schedule_unresolved')
    first, stop = _window(anchor)
    years = [int(match[7])] if match[7] else range(first.year - 1, stop.year + 2)
    candidates = []
    for year in years:
        try:
            end = date(year, MONTHS[match[5]], int(match[6]))
            start = date(year - (MONTHS[match[2]] > MONTHS[match[5]]), MONTHS[match[2]], int(match[3]))
        except ValueError:
            continue
        if (start.strftime('%A') != match[1] or end.strftime('%A') != match[4]
                or not timedelta(0) <= end - start <= timedelta(days=120)):
            continue
        days, day = [], max(first, start)
        while day <= end and day < stop:
            days.append(day.isoformat())
            day += timedelta(days=1)
        if days == item['days']:
            candidates.append((start, end))
    if len(candidates) != 1:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return candidates[0]


def _detail(item, payload, anchor, hours):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('main#maincontent')
    if not main or not main.h1 or plain(main.h1.get_text(' ', strip=True)) != item['title']:
        raise ValueError(PREFIX + 'detail_identity')
    icals = main.select('a[href*="/events/save-to-calendar.php?"]')
    if len(icals) != 1 or parse_qs(urlsplit(icals[0]['href']).query) != {'ID': [item['id']], 'mode': ['ical']}:
        raise ValueError(PREFIX + 'detail_identity')
    text = plain(main.get_text(' ', strip=True))
    native_children = any(plain(node.get_text(' ', strip=True)) == "Children's Program"
                          for node in main.select('.badge'))
    if item['children'] and not native_children:
        raise ValueError(PREFIX + 'detail_identity')
    if ('In Person' not in text or re.search(r'\b(?:invitation only|private event|cancelled|canceled|postponed)\b', text, re.I)):
        raise ValueError(PREFIX + 'not_public')
    if item['listed_sold_out'] or re.search(r'full\s*[—-]\s*waitlist|sold out', text, re.I):
        raise ValueError(PREFIX + 'sold_out')
    location = next((dt.find_next_sibling('dd') for dt in main.select('dl dt')
                     if plain(dt.get_text()) == 'Location'), None)
    if location is None or not re.search(r'4415 Beryl Road, Raleigh, (?:NC|North Carolina)\b',
                                         plain(location.get_text(' ', strip=True))):
        raise ValueError(PREFIX + 'street_unresolved')
    links = [a for a in main.find_all('a', href=True)
             if a['href'].startswith('https://calendar.google.com/calendar/render?')]
    if len(links) != 1:
        raise ValueError(PREFIX + 'schedule_unresolved')
    query = parse_qs(urlsplit(links[0]['href']).query, keep_blank_values=True)
    if (query.get('action') != ['TEMPLATE'] or query.get('text') != [item['title']]
            or query.get('ctz') != [ZONE] or len(query.get('dates', [])) != 1
            or query.get('location') != ['JC Raulston Arboretum, 4415 Beryl Road, Raleigh, NC 27606']):
        raise ValueError(PREFIX + 'schedule_unresolved')
    match = re.fullmatch(r'(\d{8}T\d{6})/(\d{8}T\d{6})', query['dates'][0])
    if not match:
        raise ValueError(PREFIX + 'schedule_unresolved')
    start, end = (datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(ZONE))
                  for value in match.groups())
    spans = []
    if 'during garden open hours' in text.lower():
        # JCRA's Google/ICS exports have observed wrong range boundaries for
        # these self-guided programs. The visible dated heading and every day
        # in the complete native month grids must agree independently instead.
        if start.time() != time() or not hours['closures_resolved']:
            raise ValueError(PREFIX + 'schedule_unresolved')
        range_start, range_end = _visible_day_range(main, item, anchor)
        first, stop = _window(anchor)
        days, day = [], max(first, range_start)
        while day <= range_end and day < stop:
            days.append(day.isoformat())
            season = 'summer' if 4 <= day.month <= 9 else 'winter'
            opens, closes = (time.fromisoformat(v) for v in hours['seasons'][season][day.weekday()])
            if day.isoformat() in hours['closures']:
                closes = min(closes, time.fromisoformat(hours['closures'][day.isoformat()]))
            if closes <= opens:
                raise ValueError(PREFIX + 'schedule_unresolved')
            spans.append((datetime.combine(day, opens, ZoneInfo(ZONE)),
                          datetime.combine(day, closes, ZoneInfo(ZONE))))
            day += timedelta(days=1)
        if days != item['days']:
            raise ValueError(PREFIX + 'schedule_unresolved')
    else:
        if (query.get('recur') or start.time() == time() or end <= start
                or end - start > timedelta(hours=18) or item['days'] != [start.date().isoformat()]):
            raise ValueError(PREFIX + 'schedule_unresolved')
        dates_node = main.select_one('.eventdates')
        if dates_node is None:
            raise ValueError(PREFIX + 'schedule_unresolved')
        rendered_date = plain(dates_node.get_text(' ', strip=True)).split('—', 1)[0].strip()
        try:
            parsed_date = datetime.strptime(rendered_date, '%A, %B %d, %Y').date()
        except ValueError:
            raise ValueError(PREFIX + 'schedule_unresolved') from None
        if parsed_date != start.date() or not rendered_date.startswith(start.strftime('%A,')):
            raise ValueError(PREFIX + 'schedule_unresolved')
        clocks = dates_node.select('.text-smallcaps')
        if len(clocks) != 2 or [_clock(x.get_text(' ', strip=True)) for x in clocks] != [start.time(), end.time()]:
            raise ValueError(PREFIX + 'schedule_unresolved')
        spans = [(start, end)]
    body = _body(main)
    photo = next((photo_url(img.get('src')) for img in main.find_all('img') if photo_url(img.get('src'))), None)
    rows = []
    for start, end in spans:
        if end <= anchor:
            continue
        identity = 'raleigh-jcra:' + sha256(f'{item["id"]}|{start.isoformat()}'.encode()).hexdigest()
        row = record(item['title'], start.isoformat(), end.isoformat(), *VENUE,
            item['url'], identity, tz=ZONE, retain_until_end=True)
        if row:
            row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                publisher_categories=["Children's Program"] if native_children else [],
                location_provenance=PROVENANCE, location_evidence_url=item['url'])
            if photo:
                row['image_url'] = photo
            rows.append(row)
    return rows


def _seal(state):
    state['manifest_count'], state['manifest_hash'] = len(state['queue']), _hash(state['queue'])
    state['state_hash'] = _hash({k: v for k, v in state.items() if k != 'state_hash'})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError(PREFIX + 'checkpoint_size_limit')


def checkpoint_complete(state):
    try:
        return (isinstance(state, dict) and state.get('source_key') == SOURCE
            and state.get('listing_complete') is True and state.get('pending_pages') == []
            and state.get('listed_pages') == _plans(timestamp(state['started_at']))
            and isinstance(state.get('queue'), list) and isinstance(state.get('hours'), dict)
            and set(state['hours']) == {'seasons', 'closures', 'closures_resolved'}
            and isinstance(state.get('outcomes'), list)
            and state.get('cursor') == state.get('manifest_count') == len(state['queue']) == len(state['outcomes']))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def _checkpoint(value, current):
    if value is None:
        return None
    try:
        anchor = timestamp(value['started_at'])
        plans = _plans(anchor)
        n = len(value['listed_pages'])
        valid = (type(value['version']) is int and value['version'] == 1 and value['source_key'] == SOURCE
            and anchor.utcoffset() == timedelta(0) and anchor <= current + timedelta(seconds=60)
            and value['window_start'] == _window(anchor)[0].isoformat()
            and value['listed_pages'] == plans[:n] and value['pending_pages'] == plans[n:]
            and 0 <= n <= len(plans) and value['listing_complete'] is (not value['pending_pages'])
            and isinstance(value['queue'], list) and len(value['queue']) <= 120
            and value['manifest_count'] == len(value['queue']) and value['manifest_hash'] == _hash(value['queue'])
            and type(value['cursor']) is int and 0 <= value['cursor'] <= len(value['queue'])
            and len(value['outcomes']) == value['cursor'] and len(value['events']) <= 300
            and (value['listing_complete'] or value['cursor'] == 0 and value['events'] == [])
            and value['state_hash'] == _hash({k: v for k, v in value.items() if k != 'state_hash'})
            and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_BYTES)
        first, end = _window(anchor)
        ids = set()
        for item in value['queue']:
            valid = (valid and event_url(SOURCE, item['url']) and item['url'].endswith('ID=' + item['id'])
                and item['id'] not in ids and isinstance(item['title'], str) and 0 < len(item['title']) <= 180
                and type(item['children']) is bool and type(item['listed_sold_out']) is bool
                and item['days'] == sorted(set(item['days'])) and len(item['days']) > 0
                and all(first <= date.fromisoformat(day) < end for day in item['days']))
            ids.add(item['id'])
        if value['listing_complete']:
            hours = value['hours']
            valid = valid and set(hours) == {'seasons', 'closures', 'closures_resolved'}
            valid = valid and set(hours['seasons']) == {'summer', 'winter'} and type(hours['closures_resolved']) is bool
            for season in hours['seasons'].values():
                valid = valid and len(season) == 7 and all(len(pair) == 2 and
                    time(6) <= time.fromisoformat(pair[0]) < time.fromisoformat(pair[1]) <= time(22) for pair in season)
            for day, clock in hours['closures'].items():
                date.fromisoformat(day)
                time.fromisoformat(clock)
        proofs, diagnostics = {}, []
        for item, outcome in zip(value['queue'], value['outcomes']):
            valid = valid and outcome['item_hash'] == _hash(item)
            if outcome['reason']:
                valid = valid and outcome['reason'] in HOLD_CODES and outcome['rows'] == []
                diagnostics.append({'id': item['id'], 'event_url': item['url'], 'disposition': 'held', 'reason': outcome['reason']})
            else:
                for proof in outcome['rows']:
                    valid = valid and proof['id'] not in proofs
                    proofs[proof['id']] = proof['hash']
        valid = valid and diagnostics == value['diagnostics'] and len(proofs) == len(value['events'])
        for row in value['events']:
            valid = (valid and proofs.get(row['id']) == _hash(row) and event_url(SOURCE, row['event_url'])
                and (row['venue_name'], row['venue_address'], row['venue_city']) == VENUE
                and row.get('lat') is None and row.get('lng') is None and row.get('timezone') == ZONE
                and row.get('location_provenance') == PROVENANCE and row.get('location_evidence_url') == row['event_url']
                and isinstance(row['description'], str) and 60 <= len(row['description']) <= 12000
                and timestamp(row['ends_at']) > timestamp(row['starts_at'])
                and (not row.get('image_url') or photo_url(row['image_url']) == row['image_url']))
        if not valid:
            raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        raise ValueError(PREFIX + 'checkpoint_invalid') from None
    if current - anchor > timedelta(hours=4):
        return None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_fetches=3):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError(PREFIX + 'checkpoint_invalid')
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, current)
    if state is None:
        state = {'version': 1, 'source_key': SOURCE, 'started_at': current.isoformat(),
            'window_start': _window(current)[0].isoformat(), 'pending_pages': _plans(current), 'listed_pages': [],
            'listing_complete': False, 'queue': [], 'manifest_count': 0, 'manifest_hash': _hash([]),
            'cursor': 0, 'hours': None, 'events': [], 'diagnostics': [], 'outcomes': []}
    if checkpoint_complete(state):
        return {'complete': True, 'events': deepcopy(state['events']), 'checkpoint': state}
    anchor = timestamp(state['started_at'])
    fetched, before = 0, (len(state['listed_pages']), state['cursor'])
    while fetched < max_fetches and (deadline_at is None or monotonic() + 12 < deadline_at):
        if state['pending_pages']:
            plan = state['pending_pages'][0]
            payload = fetch(plan['url'], 'text/html')
            fetched += 1
            if plan['url'] == HOURS:
                state['hours'] = _hours(payload, anchor)
            else:
                _merge(state['queue'], _listing(payload, plan, anchor))
            state['listed_pages'].append(plan)
            state['pending_pages'].pop(0)
            state['listing_complete'] = not state['pending_pages']
            continue
        if state['cursor'] == len(state['queue']):
            break
        item = state['queue'][state['cursor']]
        reason, rows = None, []
        try:
            if item['listed_sold_out']:
                raise ValueError(PREFIX + 'sold_out')
            payload = fetch(item['url'], 'text/html')
            fetched += 1
            rows = _detail(item, payload, anchor, state['hours'])
            if not rows:
                reason = PREFIX + 'outside_window'
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            reason = str(exc)
        if reason:
            state['diagnostics'].append({'id': item['id'], 'event_url': item['url'], 'disposition': 'held', 'reason': reason})
        state['events'].extend(rows)
        state['outcomes'].append({'item_hash': _hash(item), 'reason': reason,
            'rows': [{'id': row['id'], 'hash': _hash(row)} for row in rows]})
        state['cursor'] += 1
    if before == (len(state['listed_pages']), state['cursor']):
        raise ValueError('collection_deadline')
    _seal(state)
    complete = checkpoint_complete(state)
    return {'complete': complete, 'events': deepcopy(state['events']) if complete else [], 'checkpoint': state}


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result['complete']:
        raise ValueError('publisher_checkpoint_required')
    return result['events']
