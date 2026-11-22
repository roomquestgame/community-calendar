"""Forestry England's published Drupal venue calendars and event details.

The calendar URL remains the source scope. Only its observed same-host pager
and event links are fetched, through the caller's normal protected transport.
JSON-LD supplies identity and venue facts; the visible schedule supplies actual
sessions, because the publisher often uses start/endDate as a season envelope.
Unscheduled/untimed activities are diagnosed rather than given invented dates.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qsl, urljoin, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import address, plain, record

HOST = 'www.forestryengland.uk'
ZONE = 'Europe/London'
MAX_PAGES = 10
MAX_DETAILS = 100
MAX_OCCURRENCES = 500
DESCRIPTION_FIELD = 'forestry_event_description'
LOGGER = logging.getLogger(__name__)
MONTHS = {name: number for number, names in enumerate((
    ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'),
    ('may',), ('jun', 'june'), ('jul', 'july'), ('aug', 'august'),
    ('sep', 'sept', 'september'), ('oct', 'october'), ('nov', 'november'),
    ('dec', 'december')), 1) for name in names}
WEEKDAYS = {name: number for number, names in enumerate((
    ('mon', 'monday'), ('tue', 'tues', 'tuesday'), ('wed', 'wednesday'),
    ('thu', 'thur', 'thurs', 'thursday'), ('fri', 'friday'),
    ('sat', 'saturday'), ('sun', 'sunday'))) for name in names}
MONTH = '(?:' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + ')'
WEEKDAY = '(?:' + '|'.join(sorted(WEEKDAYS, key=len, reverse=True)) + ')'
DAY_TOKEN = re.compile(r'(?:(?P<weekday>' + WEEKDAY + r')\s*)?'
                       r'(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*'
                       r'(?P<month>' + MONTH + r')?(?:\s+(?P<year>20\d{2}))?', re.I)
CLOCK = r'(?:\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2})'
CLOCK_PATTERN = re.compile(CLOCK, re.I)


def _fail(reason):
    raise ValueError('forestry_' + reason)


class Ineligible(ValueError):
    """A fully observed activity has no supported, fixed occurrence schedule."""


def _omit(reason):
    raise Ineligible(reason)


def _key(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc, parts.path.rstrip('/') or '/', parts.query


def owns_url(url):
    """Recognize the publisher only; the document must still prove its scope."""
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.netloc == HOST and not p.query and not p.fragment
                and bool(re.fullmatch(r'/(?:[a-z0-9-]+/(?:venue/events(?:-[a-z0-9-]+)?|events)'
                                      r'|node/[1-9]\d*)/?', p.path)))
    except (ValueError, TypeError):
        return False


def _target(raw, base):
    from roomquest.registered_html_calendar import _public_url
    value = _public_url(raw, base)
    if not value or urlsplit(value).netloc != HOST:
        _fail('link_scope_conflict')
    return value


def _canonical(soup, expected):
    values = soup.select('link[rel="canonical"]')
    if len(values) != 1 or _key(_target(values[0].get('href'), expected)) != _key(expected):
        _fail('canonical_scope_conflict')


def _fields(node):
    fields = node.select('.event-details__date')
    if len(fields) != 1:
        _fail('schedule_field_unverified')
    times = fields[0].select('time[datetime]')
    if not 2 <= len(times) <= 3:
        _fail('schedule_field_unverified')
    labels = [plain(item.get_text(' ', strip=True)) for item in times]
    if len(times) == 2:
        day, clock = labels
    elif all(CLOCK_PATTERN.fullmatch(value) for value in labels[1:]):
        day, clock = labels[0], labels[1] + ' - ' + labels[2]
    else:
        day, clock = labels[0] + ' - ' + labels[1], labels[2]
    try:
        anchor = datetime.fromisoformat(times[0]['datetime']).date()
    except (TypeError, ValueError):
        _fail('schedule_field_unverified')
    return day, clock, anchor


def _listing(url, payload, *, collection=None):
    from roomquest.registered_html_calendar import _html
    base = collection or url
    if not owns_url(base):
        _fail('calendar_scope_unverified')
    soup = _html(payload)
    _canonical(soup, base)
    if not soup.body or 'page-node-type-venue' not in (soup.body.get('class') or []):
        _fail('calendar_scope_unverified')
    headers = [plain(node.get_text(' ', strip=True)) for node in soup.select('h1')]
    if not headers or any(not re.match(r'^Events (?:at|in)\b', value) for value in headers):
        _fail('calendar_scope_unverified')
    lists = soup.select('.event-date-list')
    if len(lists) != 1 or [plain(n.get_text(' ', strip=True)) for n in lists[0].select('h2')] != ['Dates and events']:
        _fail('calendar_scope_unverified')
    scope = lists[0]
    cards = []
    items = scope.select('.main-view-content .event-details')
    for item in items:
        titles = item.select('.event-details__title h3 a[href]')
        venues = item.select('.event-details__venue a[href]')
        if len(titles) != 1 or len(venues) != 1 or _key(_target(venues[0]['href'], base)) != _key(base):
            _fail('calendar_card_unverified')
        link = _target(titles[0]['href'], base)
        if _key(link) == _key(base) or urlsplit(link).query or urlsplit(link).fragment:
            _fail('calendar_card_unverified')
        cards.append({'url': link, 'title': plain(titles[0].get_text(' ', strip=True)),
                      'fields': _fields(item)})
    if not cards:
        empty = scope.select('.field--name-field-no-result-message')
        content = scope.select('.main-view-content')
        messages = {'There are no upcoming events. Please check back soon.',
                    'There are no upcoming events. Please check again soon.',
                    'Events are advertised on our Facebook page'}
        # The unfiltered New Forest view renders an empty content container;
        # Thetford explicitly redirects readers to Facebook instead of listing
        # events. Neither is permission to crawl a different site.
        if not (len(empty) == 1 and plain(empty[0].get_text(' ', strip=True)) in messages
                or not empty and len(content) == 1 and not content[0].find(True)
                and not content[0].get_text(strip=True)):
            _fail('calendar_empty_unverified')
    elif scope.select_one('.field--name-field-no-result-message'):
        _fail('calendar_empty_conflict')
    return soup, scope, cards


def supports_listing(url, payload):
    if not owns_url(url):
        return False
    try:
        _listing(url, payload)
        return True
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def _page(target, base):
    p, original = urlsplit(target), urlsplit(base)
    query = parse_qsl(p.query, keep_blank_values=True)
    if ((p.scheme, p.netloc, p.path.rstrip('/')) !=
            (original.scheme, original.netloc, original.path.rstrip('/'))
            or p.fragment or len(query) != 1 or query[0][0] != 'page'
            or not re.fullmatch(r'0|[1-9]\d{0,2}', query[0][1])):
        _fail('pagination_scope_conflict')
    index = int(query[0][1])
    if index >= MAX_PAGES:
        _fail('pagination_limit')
    return index


def _pager(scope, url, base, index):
    pagers = scope.select('nav.pager')
    if scope.select_one('button,[data-offset],[class*="load-more"],[class*="load_more"]'):
        _fail('pagination_unverified')
    if not pagers:
        if index:
            _fail('pagination_unverified')
        return None, {0}
    if len(pagers) != 1:
        _fail('pagination_unverified')
    pager = pagers[0]
    active = pager.select('a[aria-current="page"][href]')
    if len(active) != 1 or _page(_target(active[0]['href'], url), base) != index:
        _fail('pagination_unverified')
    links = {}
    next_links = set()
    for anchor in pager.select('a[href]'):
        target = _target(anchor['href'], url)
        number = _page(target, base)
        if number in links and _key(links[number]) != _key(target):
            _fail('pagination_ambiguous')
        links[number] = target
        if 'next' in (anchor.get('rel') or []):
            next_links.add(target)
    if any(n > index for n in links):
        if len(next_links) != 1 or _page(next(iter(next_links)), base) != index + 1:
            _fail('pagination_unverified')
    elif next_links:
        _fail('pagination_cycle')
    return next(iter(next_links), None), set(links)


def _window():
    from roomquest import preview_worker
    now = preview_worker.datetime.now(timezone.utc)
    return now, now + timedelta(days=preview_worker.LOOKAHEAD_DAYS)


def _date_tokens(label, start, end, *, visible_authority=False):
    """Resolve explicit ordered dates only within the publisher's dated bounds."""
    text = plain(label).casefold().replace('–', '-').replace('—', '-')
    prefix = re.match(r'^(' + WEEKDAY + r'):\s*', text)
    fixed_weekday = WEEKDAYS[prefix[1]] if prefix else None
    if prefix:
        text = text[prefix.end():]
    matches = list(DAY_TOKEN.finditer(text))
    if not matches or len(matches) > MAX_OCCURRENCES:
        _omit('dates_not_fixed')
    residual = DAY_TOKEN.sub('', text)
    if re.sub(r'\b(?:and|to)\b|[\s,&-]', '', residual):
        _omit('dates_not_fixed')
    months = [MONTHS.get(m['month']) if m['month'] else None for m in matches]
    # "Sat 5 & Sun 6 Dec" / "15, 30 November" explicitly share the following month.
    for i in range(len(months) - 2, -1, -1):
        if months[i] is None:
            months[i] = months[i + 1]
    if any(month is None for month in months):
        _omit('dates_not_fixed')
    is_range = len(matches) == 2 and bool(re.fullmatch(r'\s*(?:-|to)\s*', text[matches[0].end():matches[1].start()]))
    limit = end
    # A complete ordered visible date list can outlive a stale schema envelope.
    # Permit only an explicit year or weekday-checked single annual cycle from
    # its first dated anchor; never extend a range or an unspecific recurrence.
    if visible_authority and not is_range and len(matches) > 1:
        if fixed_weekday is not None or all(m['weekday'] or m['year'] for m in matches):
            limit = max(end, start + timedelta(days=366))
    result = []
    for i, (match, month) in enumerate(zip(matches, months)):
        lower = result[-1] if result else start
        years = [int(match['year'])] if match['year'] else range(lower.year, limit.year + 1)
        if is_range and i == 1 and not match['year'] and (month, int(match['day'])) == (end.month, end.day):
            years = [end.year]
        candidates = []
        for year in years:
            try:
                value = date(year, month, int(match['day']))
            except ValueError:
                continue
            if lower <= value <= limit:
                candidates.append(value)
        if not candidates:
            _fail('schedule_date_conflict')
        value = min(candidates)
        # A visible weekday is a factual constraint, never a hint to move year.
        weekday = WEEKDAYS[match['weekday']] if match['weekday'] else fixed_weekday
        if weekday is not None and value.weekday() != weekday:
            _fail('schedule_weekday_conflict')
        if not result and value != start:
            _fail('schedule_date_conflict')
        if result and value <= result[-1]:
            _fail('schedule_date_conflict')
        result.append(value)
    if is_range:
        return result, True
    return result, False


def _outside_horizon(card, until):
    day_label, _, anchor = card['fields']
    if anchor <= until.astimezone(ZoneInfo(ZONE)).date():
        return False
    try:
        days, _ = _date_tokens(day_label, anchor, anchor + timedelta(days=370))
        return bool(days) and min(days) == anchor
    except Ineligible:
        return False
    # Conflicting dates must not become a shortcut to omit the detail.
    except ValueError:
        return False


def _clock(value):
    value = plain(value).lower().replace('.', ':').replace(' ', '')
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(am|pm)?', value)
    if not match:
        _omit('times_not_fixed')
    hour, minute, half = int(match[1]), int(match[2] or 0), match[3]
    if minute >= 60 or hour > 23 or (half == 'am' and hour > 12):
        _fail('schedule_time_invalid')
    if half and hour <= 12:
        hour = hour % 12 + (12 if half == 'pm' else 0)
    elif not half and not match[2]:
        _omit('times_not_fixed')
    return time(hour, minute)


def _times(label):
    text = plain(label).casefold().replace('–', '-').replace('—', '-')
    if re.search(r'\ball day\b', text):
        _omit('all_day_not_supported')
    if re.search(r'\b(?:various|selected|vary|timetable|morning and afternoon|timeslots)\b', text):
        _omit('times_not_fixed')
    # Registration/opening clocks are not the advertised activity start.
    starts = re.fullmatch(r'(?:registration opens:?\s*' + CLOCK + r'\s*)?'
                          r'(?:race|run) starts?(?: at|:)?\s*(' + CLOCK + r')', text)
    if starts:
        return [(_clock(starts[1]), None)]
    text = re.sub(r',?\s*registration from\s+' + CLOCK + r'$', '', text)
    text = re.sub(r'^(?:all runners away at|race starts at|digs start at)\s*', '', text)
    text = re.sub(r'^every\s+' + WEEKDAY + r'\s*(?:from\s*)?', '', text)
    text = re.sub(r'\s*start$', '', text)
    hourly = text.startswith('hourly slots at ')
    if hourly:
        text = text[len('hourly slots at '):]
    segments = re.split(r'\s+(?:&|and|or)\s+|,\s*', text)
    result = []
    for segment in segments:
        pair = re.fullmatch(r'(' + CLOCK + r')\s*(?:-|to)\s*(' + CLOCK + r')', segment)
        if pair:
            start, end = _clock(pair[1]), _clock(pair[2])
            if end <= start:
                _fail('schedule_time_conflict')
            result.append((start, end))
        elif CLOCK_PATTERN.fullmatch(segment):
            result.append((_clock(segment), None))
        else:
            _omit('times_not_fixed')
    if not result or len(result) > 24 or len(set(result)) != len(result):
        _fail('schedule_time_conflict')
    return result


def _days(label, start, end, narrative, now, until, *, diagnostics=None, url=None):
    text = plain(label).casefold().replace('–', '-').replace('—', '-')
    window_start = max(start, (now.astimezone(ZoneInfo(ZONE)) - timedelta(days=1)).date())
    window_end = min(end, until.astimezone(ZoneInfo(ZONE)).date())
    recurring = bool(re.search(r'\bevery\b|\bdaily\b|\bmornings\b|\bafternoons\b', text))
    if recurring and re.search(r'\bterm[ -]time\b|\bexcept\b|\bexcluding\b|\bholidays?\b|\bcancel', narrative, re.I):
        _omit('recurrence_exceptions_unresolved')
    fortnight = re.fullmatch(r'(.+?)\s*-\s*then every other (' + WEEKDAY + r')', text)
    if fortnight:
        days, interval = _date_tokens(fortnight[1], start, end)[0], 14
        if len(days) != 1 or days[0].weekday() != WEEKDAYS[fortnight[2]]:
            _fail('schedule_date_conflict')
        return [window_start + timedelta(days=i) for i in range((window_end - window_start).days + 1)
                if (window_start + timedelta(days=i) - start).days % interval == 0]
    if text in ('daily', 'available daily', 'every day'):
        weekdays = set(range(7))
        months = set(range(1, 13))
    else:
        weekly = re.fullmatch(r'(?:every )?(' + WEEKDAY + r'(?:\s*(?:&|and|,)\s*' + WEEKDAY + r')*)'
                              r'(?: mornings| afternoons)?(?:\s*\((' + MONTH + r')\s*-\s*(' + MONTH + r')\))?', text)
        if weekly:
            weekdays = {WEEKDAYS[v] for v in re.findall(WEEKDAY, weekly[1])}
            months = set(range(MONTHS[weekly[2]], MONTHS[weekly[3]] + 1)) if weekly[2] else set(range(1, 13))
            if not months:
                _fail('schedule_date_conflict')
        else:
            if re.search(r'\b(?:selected|various|throughout|alternating|term|course|see|timetable)\b', text):
                _omit('dates_not_fixed')
            days, is_range = _date_tokens(text, start, end, visible_authority=True)
            later = [value for value in days if value > end]
            if later and diagnostics is not None:
                diagnostics['warnings'].append({'url': url, 'reason': 'schema_envelope_ends_before_visible_dates',
                                                'schema_end': end.isoformat(),
                                                'visible_dates_after_end': [value.isoformat() for value in later]})
            if is_range and re.search(r'\b(?:selected|various|except|excluding|closed)\b', narrative, re.I):
                _omit('recurrence_exceptions_unresolved')
            if is_range:
                # Expand only the active window, never a decades-long envelope.
                first, last = max(days[0], window_start), min(days[-1], window_end)
                return [first + timedelta(days=i) for i in range((last - first).days + 1)]
            # Explicit dates, unlike a recurring envelope, remain authoritative
            # beyond the schema end once their own dated grouping is verified.
            visible_end = until.astimezone(ZoneInfo(ZONE)).date()
            return [value for value in days if window_start <= value <= visible_end]
    return [window_start + timedelta(days=i) for i in range((window_end - window_start).days + 1)
            if (window_start + timedelta(days=i)).weekday() in weekdays
            and (window_start + timedelta(days=i)).month in months]


def _bounds(event):
    try:
        start = datetime.fromisoformat(event['startDate'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(event.get('endDate', event['startDate']).replace('Z', '+00:00'))
        if not start.tzinfo or not end.tzinfo or end < start or end - start > timedelta(days=36600):
            _fail('schedule_bounds_unverified')
        for value in (start, end):
            if value.utcoffset() != value.astimezone(ZoneInfo(ZONE)).utcoffset():
                _fail('schedule_offset_conflict')
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError('forestry_schedule_bounds_unverified') from exc
    return start.astimezone(ZoneInfo(ZONE)), end.astimezone(ZoneInfo(ZONE))


def _venue(event, base, scope):
    venue = event.get('location')
    if (not isinstance(venue, dict) or not plain(venue.get('name'))
            or _key(_target(venue.get('url'), base)) != _key(scope)):
        _fail('venue_scope_conflict')
    facts = venue.get('address')
    if not isinstance(facts, dict) or facts.get('addressCountry') != 'GB':
        _fail('venue_facts_unverified')
    facts = dict(facts)
    street = facts.get('streetAddress')
    if isinstance(street, list) and street and all(isinstance(v, str) and v.strip() for v in street):
        facts['streetAddress'] = ', '.join(street)
    if not all(isinstance(facts.get(key), str) and facts[key].strip()
               for key in ('streetAddress', 'postalCode')):
        _fail('venue_facts_unverified')
    if facts.get('addressLocality') is not None and not isinstance(facts['addressLocality'], str):
        _fail('venue_facts_unverified')
    geo = venue.get('geo')
    try:
        lat, lng = float(geo['latitude']), float(geo['longitude'])
        if not math.isfinite(lat) or not math.isfinite(lng) or not (49 <= lat <= 56 and -7 <= lng <= 3):
            _fail('venue_facts_unverified')
    except (TypeError, KeyError, ValueError):
        _fail('venue_facts_unverified')
    return plain(venue['name']), address(facts), plain(facts.get('addressLocality')), lat, lng


def _description(soup, event):
    """Retain the full native event body, with distinct verified evidence."""
    from roomquest.event_description import description
    bodies = soup.select('main .field--name-body')
    if not bodies:
        return event.get('description'), 'description'
    if len(bodies) != 1:
        _fail('description_ambiguous')
    body = str(bodies[0])
    summary = description(event.get('description'), limit=12001)
    full = description(body, limit=12001)
    # Drupal's summary strip_tags may remove boundaries between paragraphs;
    # the sanitizer restores them. Compare the ordered letters/digits while
    # retaining the original sanitized body unchanged in the actual record.
    words = lambda value: re.sub(r'\W+', '', plain(value).casefold())
    if summary and words(summary) not in words(full):
        _fail('description_identity_conflict')
    return body, DESCRIPTION_FIELD


def detail(source, payload, url, *, card=None, diagnostics=None):
    from roomquest import registered_html_calendar as shared
    from roomquest.registered_native_content import attach
    soup = shared._html(payload)
    _canonical(soup, url)
    if not soup.body or 'page-node-type-event' not in (soup.body.get('class') or []):
        _fail('detail_identity_unverified')
    matches = [node for node in shared._document(payload) if shared._event(node)
               and isinstance(node.get('url'), str) and _key(node['url']) == _key(url)]
    if len(matches) != 1:
        _fail('detail_identity_unverified')
    event = matches[0]
    if not any(plain(node.get_text(' ', strip=True)) == plain(event.get('name')) for node in soup.select('h1')):
        _fail('detail_identity_unverified')
    if card and plain(card['title']) != plain(event.get('name')):
        _fail('detail_title_conflict')
    blocks = soup.select('#block-eventdetails')
    if len(blocks) != 1:
        _fail('detail_schedule_unverified')
    block = blocks[0]
    fields = _fields(block)
    if card and fields != card['fields']:
        _fail('listing_detail_schedule_conflict')
    venues = block.select('.event-details__venue a[href]')
    if len(venues) != 1 or _key(_target(venues[0]['href'], url)) != _key(source['feed_url']):
        _fail('venue_scope_conflict')
    venue, street, city, lat, lng = _venue(event, url, source['feed_url'])
    narrative, description_field = _description(soup, event)
    if str(event.get('eventStatus', '')).endswith(('EventCancelled', 'EventPostponed')):
        if diagnostics is not None:
            diagnostics['omitted'].append({'url': url, 'reason': 'cancelled_or_postponed'})
        return []
    start, end = _bounds(event)
    if fields[2] != start.date():
        _fail('schedule_date_conflict')
    now, until = _window()
    try:
        days = _days(fields[0], start.date(), end.date(), plain(narrative), now, until,
                     diagnostics=diagnostics, url=url)
        weekly_clock = re.match(r'^every\s+(' + WEEKDAY + r')\s+(?:from\s+)?', fields[1], re.I)
        if weekly_clock:
            if re.search(r'\bterm[ -]time\b|\bexcept\b|\bexcluding\b|\bholidays?\b|\bcancel', plain(narrative), re.I):
                _omit('recurrence_exceptions_unresolved')
            days = [day for day in days if day.weekday() == WEEKDAYS[weekly_clock[1].casefold()]]
        slots = _times(fields[1]) if days else []
    except Ineligible as exc:
        if diagnostics is not None:
            diagnostics['omitted'].append({'url': url, 'reason': str(exc)})
        return []
    if not days and diagnostics is not None:
        diagnostics['omitted'].append({'url': url, 'reason': 'outside_collection_window'})
    result = []
    for day in days:
        for begins, finishes in slots:
            first = datetime.combine(day, begins)
            last = datetime.combine(day, finishes) if finishes else None
            identity = 'forestry:' + sha256(url.encode()).hexdigest()[:24] + ':' + first.strftime('%Y%m%dT%H%M')
            row = record(event['name'], first, last, venue, street, city, url, identity,
                         lat=lat, lng=lng, tz=ZONE, publisher_geo=True)
            if row:
                row['timezone'] = ZONE
                # Website text is OGL; logos/images are expressly excluded.
                attach(row, source, description_value=narrative, image_value=None,
                       evidence_url=url, description_field=description_field)
                result.append(row)
    return result


def collect(source, fetch, *, deadline_at=None, listing=None, diagnostics=None):
    """A complete bounded forest calendar, including explicit empty snapshots."""
    from roomquest.registered_native_content import enabled
    if not enabled(source, adapter='html'):
        _fail('source_unregistered')
    base = source['feed_url']
    audit = diagnostics if diagnostics is not None else {}
    audit.update(pages=0, cards=0, fetched_details=0, outside_horizon=[], omitted=[], warnings=[])

    def deadline():
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')

    deadline()
    payload = listing if listing is not None else fetch(base, 'text/html,application/xhtml+xml')
    current = base
    cards = {}
    inventories = set()
    required = {0}
    index = 0
    while True:
        deadline()
        _, scope, observed = _listing(current, payload, collection=base)
        inventory = frozenset(item['url'] for item in observed)
        if inventory in inventories:
            _fail('pagination_stalled')
        inventories.add(inventory)
        for item in observed:
            if item['url'] in cards and cards[item['url']] != item:
                _fail('calendar_card_conflict')
            cards[item['url']] = item
        if len(cards) > MAX_DETAILS:
            _fail('detail_limit')
        target, numbers = _pager(scope, current, base, index)
        required.update(numbers)
        audit['pages'] += 1
        if not target:
            if required != set(range(index + 1)):
                _fail('pagination_incomplete')
            break
        if index + 1 >= MAX_PAGES:
            _fail('pagination_limit')
        deadline()
        payload = fetch(target, 'text/html,application/xhtml+xml')
        current, index = target, index + 1
    audit['cards'] = len(cards)
    rows = {}
    _, until = _window()
    for card in cards.values():
        deadline()
        if _outside_horizon(card, until):
            audit['outside_horizon'].append(card['url'])
            continue
        payload = fetch(card['url'], 'text/html,application/ld+json')
        audit['fetched_details'] += 1
        deadline()
        for row in detail(source, payload, card['url'], card=card, diagnostics=audit):
            key = row['id'], row['starts_at']
            if key in rows and rows[key] != row:
                _fail('occurrence_conflict')
            rows[key] = row
            if len(rows) > MAX_OCCURRENCES:
                _fail('occurrence_limit')
    deadline()
    audit['occurrences'] = len(rows)
    LOGGER.info('Forestry calendar complete %s: pages=%d cards=%d details=%d future_skips=%d '
                'occurrences=%d ineligible=%s', base, audit['pages'], audit['cards'],
                audit['fetched_details'], len(audit['outside_horizon']), len(rows),
                dict(Counter(item['reason'] for item in audit['omitted'])))
    return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
