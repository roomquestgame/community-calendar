"""Reviewed Holly Hill-area library programs and OCTech public class sessions.

Network I/O belongs to the worker's injected, robots-aware publisher fetcher.
Branch aliases require an explicit event location; an off-site event never
inherits a library address. Course ranges are expanded only from the dates,
weekdays and daily hours actually printed on the course's own detail page.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.ics_adapter import parse as parse_ics
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.mycountyparks import cancelled

ZONE = 'America/New_York'
ST_GEORGE = 'st_george_library_sc'
MONCKS = 'moncks_corner_library_sc'
OCTECH = 'octech_continuing_education_sc'
CANE_BAY = 'cane_bay_ymca_sc'
ICS = {
    ST_GEORGE: 'https://dorchesterlibrarysc.libcal.com/ical_subscribe.php?src=p&cid=22342',
    MONCKS: 'https://berkeleylibrarysc.libcal.com/ical_subscribe.php?src=p&cid=8209',
}
HTML = {OCTECH: 'https://octech.coursestorm.com/browse', CANE_BAY: 'https://ymcagc.org/events/'}
SOURCES = {**ICS, **HTML}
CALENDAR_IDS = {ST_GEORGE: '22342', MONCKS: '8209'}
BRANCHES = {
    ST_GEORGE: ('Dorchester County Library — St. George Branch',
                '506 N Parler Ave, St. George, SC 29477', 'St. George'),
    MONCKS: ('Moncks Corner Library', '1003 Highway 52, Moncks Corner, SC 29461', 'Moncks Corner'),
}
ALIASES = {
    ST_GEORGE: {'st. george branch - 506 n parler ave, st. george, sc 29477'},
    MONCKS: {'activity room, moncks corner', 'moncks corner'},
}
NON_PROGRAM = re.compile(
    r'^(?:outside group\b|(?:private )?(?:room )?(?:booking|reservation)\b|'
    r'closed(?:\s*[-:–—]|$)|(?:thanksgiving|winter) holiday.*\bclosed\b|'
    r'all (?:library )?locations.*\bclosed\b)', re.I)
PRIVATE = re.compile(r'\b(?:members?[ -]+only|invitation[ -]+only|private (?:class|event|party))\b', re.I)
COURSE_URL = re.compile(r'https://octech[.]coursestorm[.]com/course/[a-z0-9]+(?:-[a-z0-9]+)*')
MAX_DOCUMENT = 2_000_000
MAX_DESCRIPTION = 2000
MAX_PAGES = 3
MAX_DETAILS = 6
MAX_RECORDS = 500
MAX_SECONDS = 36
LOOKAHEAD_DAYS = 60
MONTHS = {name.lower(): number for number, name in enumerate(
    'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}
WEEKDAYS = {name.lower(): number for number, name in enumerate(
    'Mon Tue Wed Thu Fri Sat Sun'.split())}


def validate(source):
    key = source.get('source_key')
    kind = 'ical' if key in ICS else 'html'
    url = SOURCES.get(key)
    if not url or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
                   source.get('timezone')) != (url, kind, kind, ZONE):
        raise ValueError('unregistered_holly_hill_institution')
    return key, url


def _location(value):
    """Recognize a complete address actually supplied in this event's text."""
    value = re.sub(r'\s+-\s+(?=\d)', ', ', value)
    parts = [part.strip() for part in value.split(',')]
    if (len(parts) < 3 or not re.fullmatch(r'[A-Z]{2}\s+\d{5}(?:-\d{4})?', parts[-1])
            or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", parts[-2])):
        return None
    streets = [i for i, part in enumerate(parts[:-2]) if re.match(r'^\d{1,6}\s+[A-Za-z]', part)]
    if len(streets) != 1:
        return None
    first = streets[0]
    street = ', '.join(parts[first:])
    venue = ', '.join(parts[:first]) or parts[first]
    return venue, street, parts[-2]


def _where_venue(description):
    """Read a literal, three-line Where block; never search general prose."""
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    headings = [i for i, line in enumerate(lines) if line.casefold() == 'where:']
    if len(headings) != 1:
        return None
    block = lines[headings[0] + 1:headings[0] + 4]
    if len(block) != 3 or not re.match(r'^\d{1,6}\s+[A-Za-z]', block[1]):
        return None
    return _location(', '.join(block))


def collect_ics(source, payload):
    key, url = validate(source)
    if key not in ICS:
        raise ValueError('unregistered_holly_hill_library')
    if not isinstance(payload, str) or len(payload) > MAX_DOCUMENT:
        raise ValueError('library_document_limit')
    calendar = Calendar.from_ical(payload)
    events = calendar.walk('VEVENT')
    if len(events) > 1000:
        raise ValueError('source_record_limit')
    # A private exception cannot be removed in a way that resurrects a public
    # recurring master occurrence; conservatively exclude its entire UID.
    private_ids = {str(e.get('UID', '')) for e in events
                   if str(e.get('CLASS', 'PUBLIC')).strip().upper() != 'PUBLIC'}
    closures = []
    for event in events:
        title = str(event.get('SUMMARY', ''))
        if NON_PROGRAM.search(title) and re.search(r'\bclosed\b', title, re.I):
            starts, ends = event.decoded('DTSTART'), event.decoded('DTEND', None)
            if isinstance(starts, date) and not isinstance(starts, datetime):
                ends = ends or starts + timedelta(days=1)
                if not isinstance(ends, date) or isinstance(ends, datetime):
                    raise ValueError('library_closure_time_unresolved')
                starts = timestamp(datetime.combine(starts, time()), ZONE)
                ends = timestamp(datetime.combine(ends, time()), ZONE)
            if (not isinstance(starts, datetime) or not isinstance(ends, datetime)
                    or starts.tzinfo is None or ends.tzinfo is None or ends <= starts):
                raise ValueError('library_closure_time_unresolved')
            closures.append((starts, ends, plain(event.get('LOCATION')).casefold()))
    calendar.subcomponents = [e for e in calendar.subcomponents if e.name != 'VEVENT' or (
        str(e.get('UID', '')) not in private_ids
        and not NON_PROGRAM.search(str(e.get('SUMMARY', '')))
        and not PRIVATE.search(str(e.get('SUMMARY', '')) + '\n' + str(e.get('DESCRIPTION', '')))
        and not cancelled(str(e.get('SUMMARY', '')), str(e.get('DESCRIPTION', ''))))]
    rows = parse_ics(calendar.to_ical().decode(), {'source_key': key, 'url': url},
                     legacy=True, include_description=True)
    result = []
    for row in rows:
        identity = row['id'].split('__', 1)[0]
        match = re.fullmatch(r'LibCal-' + CALENDAR_IDS[key] + r'-([1-9][0-9]*)', identity)
        if not match or row.get('event_url') != 'https://' + urlsplit(url).netloc + '/event/' + match[1]:
            raise ValueError('library_event_identity_unverified')
        location = plain(row.get('venue_name'))
        narrative = row.get('description', '')
        if re.search(r'\b(?:zoom|virtual|online)\b', location, re.I):
            continue
        venue = BRANCHES[key] if location.casefold() in ALIASES[key] else _location(location)
        if not location:
            venue = _where_venue(narrative)
        starts = datetime.fromisoformat(row['starts_at'])
        ends = datetime.fromisoformat(row['ends_at']) if row.get('ends_at') else starts
        if any((bool(location) and closed_location == location.casefold() or
                venue == BRANCHES[key] and (not closed_location or closed_location in ALIASES[key]))
               and starts < closed_end and (ends > closed_start or starts == ends and starts >= closed_start)
               for closed_start, closed_end, closed_location in closures):
            continue
        if venue:
            row.update(venue_name=venue[0], venue_address=venue[1], venue_city=venue[2])
        else:
            # Retain a factual but unresolved location for review. The shared
            # ICS parser's location-as-address fallback is not street evidence.
            row.update(venue_address='', venue_city='', lat=None, lng=None)
        row.update(description=narrative[:MAX_DESCRIPTION], timezone=ZONE)
        row.pop('image_url', None)
        result.append(row)
    return result


def _page(payload):
    if not isinstance(payload, str) or not payload.strip() or len(payload) > MAX_DOCUMENT:
        raise ValueError('octech_document_invalid')
    soup = BeautifulSoup(payload, 'html.parser')
    if not any(plain(h.get_text()) == 'Orangeburg-Calhoun Technical College' for h in soup.select('h1')):
        raise ValueError('octech_publisher_unverified')
    return soup


def _text(node):
    return plain(node.get_text(' ', strip=True)) if node else ''


def _narrative(node):
    if not node:
        return ''
    copy = BeautifulSoup(str(node), 'html.parser')
    for element in copy.select('script, style, template, noscript'):
        element.decompose()
    return '\n'.join(line.strip() for line in copy.get_text('\n').splitlines() if line.strip())


def _clock(value):
    value = re.sub(r'\s+', '', value).upper()
    try:
        return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()
    except ValueError:
        raise ValueError('octech_time_unresolved') from None


def _next_start(value):
    value = re.sub(r'\s+,', ',', value)
    match = re.fullmatch(r'([A-Za-z]{3}) (\d{1,2}), (20\d{2}) at (\d{1,2}(?::\d{2})?\s*[ap]m)'
                         r'(?:, runs for \d+ weeks?)?', value, re.I)
    if not match:
        raise ValueError('octech_listing_date_unresolved')
    try:
        day = date(int(match[3]), MONTHS[match[1].lower()], int(match[2]))
    except (KeyError, ValueError):
        raise ValueError('octech_listing_date_unresolved') from None
    return timestamp(datetime.combine(day, _clock(match[4])), ZONE)


def _listing(payload, page_number):
    soup = _page(payload)
    container = soup.select_one('.course-list')
    sort = soup.select_one('#sort-select')
    options = sort.select('option') if sort else []
    chosen = [option for option in options if option.has_attr('selected')] or options[:1]
    if not container or len(chosen) != 1 or chosen[0].get('value') != 'date':
        raise ValueError('octech_listing_structure_unverified')
    cards = container.select('.course-item')
    if len(cards) > 30:
        raise ValueError('source_record_limit')
    rows, seen, previous = [], set(), None
    for card in cards:
        title = card.select_one('.course-detail a[href] h2')
        clock = card.select_one('.next-session')
        url = urljoin(HTML[OCTECH], title.parent.get('href', '')) if title else ''
        if not title or not clock or not COURSE_URL.fullmatch(url) or url in seen:
            raise ValueError('octech_listing_event_unverified')
        starts = _next_start(_text(clock))
        if previous and starts < previous:
            raise ValueError('octech_listing_order_conflict')
        seen.add(url)
        previous = starts
        rows.append({'url': url, 'title': _text(title), 'next_start': starts})
    next_links = [a for a in soup.select('a[href]') if _text(a) == 'Next']
    if len(next_links) > 1:
        raise ValueError('octech_pagination_unverified')
    next_url = urljoin(HTML[OCTECH], next_links[0]['href']) if next_links else None
    if next_url and next_url != HTML[OCTECH] + '?page=' + str(page_number + 1):
        raise ValueError('octech_pagination_unverified')
    return rows, next_url


def _visible_dates(node):
    months, days, years = ([ _text(x) for x in node.select('.' + field)]
                           for field in ('month', 'day', 'year'))
    if not 1 <= len(months) <= 2 or not 1 <= len(days) <= 2 or not 1 <= len(years) <= 2:
        raise ValueError('octech_schedule_unverified')
    try:
        start = date(int(years[0]), MONTHS[months[0].lower()[:3]], int(re.sub(r'(st|nd|rd|th)$', '', days[0])))
        end = date(int(years[-1]), MONTHS[months[-1].lower()[:3]], int(re.sub(r'(st|nd|rd|th)$', '', days[-1])))
    except (KeyError, ValueError):
        raise ValueError('octech_schedule_unverified') from None
    return start, end


def _daily_hours(value):
    match = re.fullmatch(r'(\d{1,2}(?::\d{2})?)(?:\s*([ap]m))?\s*[-–—]\s*'
                         r'(\d{1,2}(?::\d{2})?)\s*([ap]m)', value, re.I)
    if not match:
        raise ValueError('octech_time_unresolved')
    start, end = _clock(match[1] + (match[2] or match[4])), _clock(match[3] + match[4])
    if end <= start:
        raise ValueError('octech_time_unresolved')
    return start, end


def _venue(soup, event):
    locations = soup.select('.course-location .location-info')
    if len(locations) != 1:
        raise ValueError('octech_venue_unverified')
    location = locations[0]
    name = _text(location.select_one('h3'))
    street = location.select_one('address')
    if not name or not street:
        raise ValueError('octech_venue_unverified')
    schema_venue = event.get('location')
    if not isinstance(schema_venue, dict) or plain(schema_venue.get('name')) != name:
        raise ValueError('octech_venue_conflict')
    street = BeautifulSoup(str(street), 'html.parser')
    for link in street.select('a'):
        link.decompose()
    address = _text(street)
    known = ('Orangeburg Calhoun Technical College',
             'Continuing Education 3250 St. Matthews Road, SC 29118')
    if (name, address) == known:
        footer_node = BeautifulSoup(str(soup.select_one('#site-address') or ''), 'html.parser')
        for link in footer_node.select('.site-address-directions'):
            link.decompose()
        footer = _text(footer_node)
        if footer != '3250 St. Matthews Road, Orangeburg, SC 29118':
            raise ValueError('octech_venue_unverified')
        schema_address = schema_venue.get('address') or {}
        if not isinstance(schema_address, dict) or any(schema_address.get(field) != expected for field, expected in {
            'streetAddress': 'Continuing Education', 'addressLocality': '3250 St. Matthews Road',
            'addressRegion': 'SC', 'postalCode': '29118',
        }.items()):
            raise ValueError('octech_venue_conflict')
        venue = (name, footer, 'Orangeburg')
    else:
        venue = _location(name + ', ' + address)
        if not venue:
            raise ValueError('octech_venue_unverified')
    return venue, _text(location.select_one('.room'))


def parse_course(payload, listing):
    if not COURSE_URL.fullmatch(listing.get('url', '')):
        raise ValueError('octech_course_identity_conflict')
    soup = _page(payload)
    body = soup.select_one('#course-detail')
    if not body or _text(body.select_one('.course-title h2')) != listing['title']:
        raise ValueError('octech_course_identity_conflict')
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            raise ValueError('octech_schema_unverified') from None
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data
        if not isinstance(nodes, list):
            raise ValueError('octech_schema_unverified')
        events.extend(node for node in nodes if isinstance(node, dict) and node.get('@type') == 'Event')
    if len(events) != 1:
        raise ValueError('octech_schema_unverified')
    event = events[0]
    offers = event.get('offers') or {}
    offer_url = offers.get('url') if isinstance(offers, dict) else None
    if (plain(event.get('name')) != listing['title'] or not isinstance(offer_url, str)
            or not re.fullmatch(re.escape(listing['url']) + r'#/cart/register/[a-f0-9]{32}', offer_url)):
        raise ValueError('octech_course_identity_conflict')
    narrative = _narrative(body.select_one('.description'))
    if (cancelled(listing['title'], narrative) or PRIVATE.search(_narrative(body))
            or str(event.get('eventStatus', '')).endswith(('EventCancelled', 'EventPostponed'))):
        return []
    blocks = body.select('.sessions .date-span')
    if len(blocks) != 1:
        raise ValueError('octech_schedule_unverified')
    block = blocks[0]
    dates = block.select('.session-dates')
    labels = block.select('strong')
    if len(dates) != 1 or len(labels) != 2:
        raise ValueError('octech_schedule_unverified')
    first_day, last_day = _visible_dates(dates[0])
    if not 0 <= (last_day - first_day).days <= 365:
        raise ValueError('octech_schedule_unverified')
    tokens = re.split(r'\s*(?:,|\band\b|&)\s*', _text(labels[0]), flags=re.I)
    if not tokens or any(not re.fullmatch(r'(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|'
                                         r'Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)',
                                         token, re.I) for token in tokens):
        raise ValueError('octech_weekdays_unresolved')
    weekdays = {WEEKDAYS[token[:3].lower()] for token in tokens}
    start_clock, end_clock = _daily_hours(_text(labels[1]))
    start = timestamp(datetime.combine(first_day, start_clock), ZONE)
    end = timestamp(datetime.combine(last_day, end_clock), ZONE)
    if (timestamp(event.get('startDate'), ZONE) != start or timestamp(event.get('endDate'), ZONE) != end
            or first_day.weekday() not in weekdays or last_day.weekday() not in weekdays):
        raise ValueError('octech_schedule_conflict')
    sessions = []
    day = first_day
    while day <= last_day:
        if day.weekday() in weekdays:
            sessions.append((timestamp(datetime.combine(day, start_clock), ZONE),
                             timestamp(datetime.combine(day, end_clock), ZONE)))
        day += timedelta(days=1)
    if len(sessions) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    if listing['next_start'] not in {starts for starts, _ in sessions}:
        raise ValueError('octech_listing_detail_conflict')
    (venue, address, city), room = _venue(soup, event)
    description = '\n\n'.join(part for part in (narrative, _text(block), room) if part)
    rows = []
    for starts, ends in sessions:
        row = record(listing['title'], starts, ends, venue, address, city, listing['url'],
                     'octech:' + urlsplit(listing['url']).path.rsplit('/', 1)[-1] + ':' + starts.date().isoformat(), tz=ZONE)
        if row:
            row.update(description=description[:MAX_DESCRIPTION], timezone=ZONE,
                       publisher_categories=[], attendance_mode='in_person')
            rows.append(row)
    return rows


def _card_field(card, names, *, required=True):
    labels = [label for label in card.select('strong') if _text(label).rstrip(':').casefold() in names]
    if len(labels) != 1:
        if not labels and not required:
            return ''
        raise ValueError('cane_bay_event_fields_unverified')
    parts = []
    for sibling in labels[0].next_siblings:
        if getattr(sibling, 'name', None) in ('br', 'strong'):
            break
        parts.append(sibling.get_text(' ', strip=True) if hasattr(sibling, 'get_text') else str(sibling))
    return plain(' '.join(parts))


def parse_cane_bay(payload, *, now=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('cane_bay_now_timezone_missing')
    if not isinstance(payload, str) or not payload.strip() or len(payload) > MAX_DOCUMENT:
        raise ValueError('cane_bay_document_invalid')
    soup = BeautifulSoup(payload, 'html.parser')
    grids = soup.select('.event-grid')
    if (len(grids) != 1 or _text(soup.select_one('h1')) != 'CANE BAY YMCA UPCOMING EVENTS'
            or 'Cane Bay Family YMCA' not in _text(soup.select_one('title'))):
        raise ValueError('cane_bay_calendar_unverified')
    if soup.select('a[rel~=next], .pagination a, .page-numbers'):
        raise ValueError('cane_bay_pagination_unverified')
    cards = grids[0].select('.type-events')
    if len(cards) > 50:
        raise ValueError('source_record_limit')
    results = {}
    for card in cards:
        if 'status-publish' not in card.get('class', []):
            continue
        titles = card.select('.event-data h4 a[href]')
        identities = [value[5:] for value in card.get('class', []) if re.fullmatch(r'post-[1-9][0-9]*', value)]
        if len(titles) != 1 or len(identities) != 1:
            raise ValueError('cane_bay_event_identity_unverified')
        title, link = _text(titles[0]), titles[0]['href']
        if not title or not re.fullmatch(r'https://ymcagc[.]org/events/(?:[a-z0-9-]+/)?', link):
            raise ValueError('cane_bay_event_identity_unverified')
        try:
            day = datetime.strptime(_card_field(card, {'date'}), '%B %d, %Y').date()
        except ValueError:
            raise ValueError('cane_bay_date_unresolved') from None
        start_clock, end_clock = _daily_hours(_card_field(card, {'timinings', 'timings'}))
        starts, ends = (timestamp(datetime.combine(day, value), ZONE) for value in (start_clock, end_clock))
        if starts < current or starts > current + timedelta(days=LOOKAHEAD_DAYS):
            continue
        description = _narrative(titles[0].parent.parent.select_one('p'))
        if cancelled(title, description) or PRIVATE.search(_narrative(card)):
            continue
        supplied = _card_field(card, {'location', 'venue'}, required=False)
        venue = _location(supplied) if supplied else None
        if (not supplied and 'cane bay family ymca' in description.casefold()
                and re.search(r'1655 Cane Bay Blvd[.]?\s+Summerville, SC 29486', _text(soup))):
            venue = ('Cane Bay Family YMCA', '1655 Cane Bay Blvd., Summerville, SC 29486', 'Summerville')
        # A site footer alone is not event venue evidence. New cards without
        # a location remain unlocated candidates for normal review/resolution.
        name, address, city = venue or (supplied, '', '')
        row = record(title, starts, ends, name, address, city, link,
                     'cane_bay:' + identities[0] + ':' + day.isoformat(), tz=ZONE)
        if row:
            row.update(description=description[:MAX_DESCRIPTION], timezone=ZONE, publisher_categories=[])
            if row['id'] in results and results[row['id']] != row:
                raise ValueError('conflicting_event_occurrence')
            results[row['id']] = row
    return sorted(results.values(), key=lambda row: (row['starts_at'], row['id']))


def collect_html(source, fetch, *, deadline_at=None, now=None):
    key, url = validate(source)
    if key == CANE_BAY:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        return parse_cane_bay(fetch(url, 'text/html'), now=now)
    if key != OCTECH:
        raise ValueError('unregistered_holly_hill_html')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('octech_now_timezone_missing')
    cutoff = current + timedelta(days=LOOKAHEAD_DAYS)
    deadline = min(monotonic() + MAX_SECONDS, deadline_at or float('inf'))
    def get(address):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        return fetch(address, 'text/html')
    candidates, seen, previous = [], set(), None
    for page in range(1, MAX_PAGES + 1):
        rows, next_url = _listing(get(url), page)
        for item in rows:
            if item['url'] in seen or previous and item['next_start'] < previous:
                raise ValueError('octech_listing_order_conflict')
            seen.add(item['url'])
            previous = item['next_start']
            if current <= item['next_start'] <= cutoff:
                candidates.append(item)
        # The publisher's verified date ordering proves all remaining pages
        # are outside the lookahead; do not pay for their detail requests.
        if not next_url or rows and rows[-1]['next_start'] > cutoff:
            break
        if page == MAX_PAGES:
            raise ValueError('pagination_limit')
        url = next_url
    if len(candidates) > MAX_DETAILS:
        raise ValueError('octech_detail_limit')
    results = []
    for item in candidates:
        results.extend(parse_course(get(item['url']), item))
    if len(results) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    return sorted(results, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    key, url = validate(source)
    if key in ICS:
        return collect_ics(source, fetch(url, 'text/calendar'))
    return collect_html(source, fetch, deadline_at=deadline_at, now=now)
