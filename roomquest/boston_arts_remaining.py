"""Remaining Boston museum programs and the existing Brookline library repair.

Native schedules and full public event descriptions, with complete-only durable
hydration for museum calendars. All publisher requests use the worker transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest import boston_arts as shared
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = shared.ZONE
MFA = 'museum_fine_arts_boston_ma'
ICA = 'institute_contemporary_art_boston_ma'
BCA = 'boston_center_arts_ma'
SOWA = 'sowa_christmas_market_ma'
BROOKLINE = 'municipal_mapsee_28acdd50f36a6c7a3a9d8a47'
SOURCES = {
    MFA: ('https://www.mfa.org/programs', 'html', 'html'),
    ICA: ('https://www.icaboston.org/calendar/', 'html', 'html'),
    BCA: ('https://bostonarts.org/experiences/', 'html', 'html'),
    SOWA: ('https://www.sowaboston.com/sowa-christmas-market/', 'html', 'html'),
    BROOKLINE: ('https://brooklinelibrary.libcal.com/ical_subscribe.php?cid=20102', 'html', 'html'),
}
LABELS = {
    MFA: 'Museum of Fine Arts, Boston', ICA: 'Institute of Contemporary Art/Boston',
    BCA: 'Boston Center for the Arts', SOWA: 'SoWa Christmas Market', BROOKLINE: 'Public Library of Brookline',
}
EXISTING_SOURCE_IDS = {BROOKLINE: 3718}
SOURCE_NOTES = {
    MFA: 'Complete native program-calendar pagination and selected-occurrence full detail bodies; rolling 60-day window.',
    ICA: 'Native permitted per-event ICS supplies all occurrences; full HTML body replaces the truncated JSON-LD summary.',
    BCA: 'Native public experiences calendar and complete event-detail narrative with explicit venue address.',
    SOWA: 'Exact November20–December27,2026 native seasonal program; November/December hours and stated holiday exceptions, no future-year projection.',
    BROOKLINE: 'Repair existing source id3718; native ICS descriptions and exact official branch street resolution.',
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = {MFA, ICA, BCA}
CHECKPOINT_MANIFEST_LIMITS = {MFA: 500}
CHECKPOINT_EVENT_LIMITS = {MFA: 500}
# These are ceilings, not a reason to overrun the worker's deadline or publisher
# pacing. MFA has one request per occurrence, ICA has two, and BCA declares a
# ten-second crawl delay. Stop before the next detail when the reserve is spent.
DETAILS_PER_CHUNK = {MFA: 20, ICA: 4, BCA: 2}
LISTING_PAGES_PER_CHUNK = {MFA: 4, ICA: 1, BCA: 1}
# Exact Museum.geo in the museum's Google Arts & Culture partner profile at
# https://artsandculture.google.com/partner/museum-of-fine-arts-boston , naming
# the same 465 Huntington Ave / Boston / MA02115. The MassGIS/MHC building point
# BOS.7493 independently corroborates the actual building. Not a map viewport.
MFA_VENUE_POINT = (42.339381, -71.094048)
MAX_DESCRIPTION = shared.MAX_DESCRIPTION
MAX_CHECKPOINT_BYTES = shared.MAX_CHECKPOINT_BYTES
MAX_RECORDS = 500
DAYS = 60
HOLD_REASONS = shared.HOLD_REASONS | {'boston_arts_remaining_no_physical_venue', 'boston_arts_remaining_description_unavailable'}


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError('unregistered_boston_arts_remaining_source')
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.netloc != ALLOWED_HOSTS[key][0] or p.fragment
                or '..' in p.path.split('/') or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)):
            return False
        if key == SOWA:
            return value == SOURCES[SOWA][0]
        if key == MFA:
            return bool(re.fullmatch(r'/event/[a-z0-9/-]+', p.path) and re.fullmatch(r'event=\d+', p.query))
        if p.query:
            return False
        return bool(re.fullmatch(r'/(?:event/\d+|calendar/events/[A-Za-z0-9-]+)' if key == BROOKLINE else r'/events/[a-z0-9-]+/' if key == ICA else r'/event/[a-z0-9-]+/', p.path))
    except ValueError:
        return False


def _finish(key, row, body, labels=()):
    if row is None:
        return None
    if not event_url(key, row.get('event_url')):
        raise ValueError('boston_arts_remaining_identity_changed')
    row.update(description=body, timezone=ZONE, attendance_mode='in_person',
               location_provenance='publisher_event_street_pending_geocode')
    if key == MFA:
        row['location_provenance'] = 'publisher_partner_museum_geo'
    if labels:
        row['publisher_categories'] = list(dict.fromkeys(labels))
    return row


BRANCHES = {
    'Brookline Village': ('361 Washington Street, Brookline, MA 02445', 'Brookline'),
    'Coolidge Corner': ('31 Pleasant Street, Brookline, MA 02446', 'Brookline'),
    'Putterham': ('959 West Roxbury Parkway, Chestnut Hill, MA 02467', 'Chestnut Hill'),
}
# Exact currently published library-room labels, verified against the native ICS
# and https://www.brooklinelibrary.org/about/hours-locations/ .
BRANCH_LOCATIONS = {
    'Brookline Village': 'Brookline Village',
    'Brookline Village - First Floor, Brookline Village': 'Brookline Village',
    'Conference Room - Brookline Village, Brookline Village': 'Brookline Village',
    'Hunneman Hall - Brookline Village': 'Brookline Village',
    'Hunneman Hall - Brookline Village, Brookline Village': 'Brookline Village',
    'Teen Room, Brookline Village': 'Brookline Village',
    'The Rabbit Hole, Brookline Village': 'Brookline Village',
    'Tween Room, Brookline Village': 'Brookline Village',
    'Coolidge Corner': 'Coolidge Corner',
    'Meeting Room - Coolidge Corner, Coolidge Corner': 'Coolidge Corner',
    'Meeting Room - Putterham, Putterham': 'Putterham',
    'Putterham Lawn, Putterham': 'Putterham',
}
ADMIN_TITLE = re.compile(r'\b(?:staff use|unavailable|hold for|room setup|staff development|department|dept[.]?/div[.]?)\b', re.I)


def _brookline(payload, now):
    events = Calendar.from_ical(payload).walk('VEVENT')
    if len(events) > 1000:
        raise ValueError('boston_arts_remaining_feed_limit')
    if len(events) >= 500 and max(e.decoded('DTSTART') for e in events) < now + timedelta(days=DAYS):
        raise ValueError('boston_arts_remaining_feed_limit')
    rows = []
    for native in events:
        title = plain(native.get('SUMMARY'))
        if (shared.NONPUBLIC.search(title) or shared.REMOTE.search(title) or ADMIN_TITLE.search(title)
                or str(native.get('STATUS', '')).upper() == 'CANCELLED'):
            continue
        if any(name in native for name in ('RRULE', 'RDATE', 'RECURRENCE-ID')):
            raise ValueError('boston_arts_remaining_recurrence_changed')
        start, end = native.decoded('DTSTART'), native.decoded('DTEND', None)
        if not isinstance(start, datetime) or start.tzinfo is None or not isinstance(end, datetime) or end.tzinfo is None or end <= start:
            raise ValueError('boston_arts_schedule_unresolved')
        if not shared._within(start, end, now, DAYS):
            continue
        link, uid = str(native.get('URL', '')), str(native.get('UID', ''))
        if not event_url(BROOKLINE, link) or not re.fullmatch(r'LibCal-20102-\d+', uid) or (urlsplit(link).path.startswith('/event/') and not link.endswith('/' + uid.split('-')[-1])):
            raise ValueError('boston_arts_remaining_identity_changed')
        location = plain(native.get('LOCATION'))
        if location == 'Virtual':
            continue
        branch = BRANCH_LOCATIONS.get(location)
        try:
            body = shared._body(str(native.get('DESCRIPTION', '')))
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            shared._held(BROOKLINE, uid, str(exc))
            continue
        if branch:
            address, city = BRANCHES[branch]
            venue = 'Public Library of Brookline — ' + location
        elif location == 'Off-site' and 'United Parish Church at 210 Harvard Street' in body:
            # The native event states the offsite street. The church's official
            # contact/directions page confirms Brookline MA02446 and the
            # weekday Marion Street entrance (also retained in the narrative).
            address, city = '210 Harvard Street, Brookline, MA 02446', 'Brookline'
            venue = 'United Parish in Brookline (Marion Street entrance)'
        else:
            shared._held(BROOKLINE, uid, 'boston_arts_remaining_no_physical_venue')
            continue
        labels = [str(v) for v in native['CATEGORIES'].cats] if native.get('CATEGORIES') else []
        row = record(title, start.isoformat(), end.isoformat(), venue,
                     address, city, link, uid, tz=ZONE, retain_until_end=True)
        row = _finish(BROOKLINE, row, body, labels)
        if row:
            rows.append(row)
    return shared._unique(rows)


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _listed_url(key, url):
    if url == SOURCES[key][0]:
        return True
    if key == MFA:
        return bool(re.fullmatch(r'https://www[.]mfa[.]org/programs\?page=\d{1,2}', url))
    return False


def _mfa_days(value):
    """Read calendar date bounds without guessing missing event clock times."""
    line = value.split('\n')[0]
    years = re.findall(r'\b20\d{2}\b', line)
    months = re.findall(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})', line)
    if not years or not months:
        raise ValueError('boston_arts_remaining_listing_changed')
    first = datetime.strptime(' '.join((*months[0], years[0])), '%B %d %Y').date()
    last = datetime.strptime(' '.join((*months[-1], years[-1])), '%B %d %Y').date()
    if last < first:
        raise ValueError('boston_arts_remaining_listing_changed')
    return first, last


def _mfa_listing(payload, page, now):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('main')
    if not main or not main.find(string=re.compile('Program Calendar')):
        raise ValueError('boston_arts_remaining_listing_changed')
    queue = []
    for card in main.select('.well'):
        link = card.select_one('h2 a[href]')
        if not link or '/event/' not in link['href']:
            continue  # Film-series umbrella pages are not timed occurrences.
        url, title = urljoin(page, link['href']), plain(link.get_text(' '))
        dates = card.select_one('.date-display-range')
        if not event_url(MFA, url) or not dates:
            raise ValueError('boston_arts_remaining_identity_changed')
        if (shared.NONPUBLIC.search(title) or shared.REMOTE.search(title) or title.startswith('Member ')
                or re.search(r'\b(?:Canceled|Cancelled|Online)\b', card.get_text(' '))):
            continue
        first, last = _mfa_days(dates.get_text('\n', strip=True))
        if last < now.astimezone(ZoneInfo(ZONE)).date() or first >= (now + timedelta(days=DAYS)).date():
            continue
        queue.append(dict(url=url, title=title, id=parse_qs(urlsplit(url).query)['event'][0],
                          day=first.isoformat(), last_day=last.isoformat()))
    following = main.select('nav[aria-label="Pagination"] a[rel~=next]')
    if len(following) > 1:
        raise ValueError('boston_arts_remaining_pagination_changed')
    next_page = urljoin(page, following[0]['href']) if following else None
    if next_page and not _listed_url(MFA, next_page):
        raise ValueError('boston_arts_remaining_pagination_changed')
    return queue, next_page


def _mfa_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('main')
    buttons = main.select('add-to-calendar-button') if main else []
    node = main.select_one('.node--type-performance[data-history-node-id]') if main else None
    heading = main.select_one('h1') if main else None
    if (len(buttons) != 1 or not node or node['data-history-node-id'] != item['id'] or not heading
            or plain(heading.get_text(' ')) != item['title']):
        raise ValueError('boston_arts_remaining_identity_changed')
    button = buttons[0]
    if button.get('timezone') != ZONE or plain(button.get('name')) != item['title']:
        raise ValueError('boston_arts_remaining_schedule_changed')
    try:
        start = timestamp(button['startdate'] + 'T' + button['starttime'], ZONE)
        end = timestamp(button['enddate'] + 'T' + button['endtime'], ZONE)
    except KeyError:
        raise ValueError('boston_arts_schedule_unresolved') from None
    if not start or not end or end <= start or start.date().isoformat() != item['day']:
        raise ValueError('boston_arts_remaining_schedule_changed')
    if not shared._within(start, end, now, DAYS):
        return []
    location = plain(button.get('location'))
    if location != 'Museum of Fine Arts, Boston, 465 Huntington Ave, Boston, MA 02115, USA':
        raise ValueError('boston_arts_remaining_no_physical_venue')
    bodies = main.select('.field--name-body')
    # Includes the selected session's theme plus the complete generic event
    # narrative. The schedule's other sessions and their bodies are separate
    # views-field-body nodes, not part of this selector.
    body = shared._body('\n\n'.join(str(n) for n in bodies))
    labels = [plain(n.get_text(' ')) for n in main.select('.field--name-field-event-type .field__item')]
    row = record(item['title'], start.isoformat(), end.isoformat(), 'Museum of Fine Arts, Boston',
                 '465 Huntington Avenue, Boston, MA 02115', 'Boston', item['url'], item['id'],
                 lat=MFA_VENUE_POINT[0], lng=MFA_VENUE_POINT[1], tz=ZONE, publisher_geo=True, retain_until_end=True)
    return [row] if (row := _finish(MFA, row, body, labels)) else []


def _ica_listing(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    calendar = soup.select_one('.view-calendar')
    if not calendar or calendar.select('a[rel~=next]'):
        raise ValueError('boston_arts_remaining_listing_changed')
    queue = []
    for card in calendar.select('.node-event'):
        links = list(dict.fromkeys(a['href'] for a in card.select('a[href]') if event_url(ICA, a['href'])))
        if len(links) != 1:
            raise ValueError('boston_arts_remaining_identity_changed')
        url = links[0]
        heading = card.select_one('h2, h3')
        if not heading:
            raise ValueError('boston_arts_remaining_listing_changed')
        title = plain(heading.get_text(' '))
        tags = [a.get_text(' ', strip=True) for a in card.select('a[href]') if 'event_type' in a['href']]
        if shared.NONPUBLIC.search(title) or shared.REMOTE.search(title) or title.startswith('Member ') or set(tags) & {'Virtual events', 'ICA Members'}:
            continue
        queue.append(dict(url=url, title=title, labels=tags))
    return queue, None


def _ica_detail(item, payload, fetch, now):
    soup = BeautifulSoup(payload, 'html.parser')
    canonical = soup.select_one('link[rel~=canonical]')
    heading, bodies = soup.select_one('h1.page-title'), soup.select('.field-name-body')
    nodes, page_urls = [], []
    for script in soup.select('script[type="application/ld+json"]'):
        value = json.loads(script.get_text())
        if isinstance(value, dict) and value.get('@type') == 'Event':
            nodes.append(value)
        if isinstance(value, dict):
            page_urls += [node.get('url') for node in value.get('@graph', []) if isinstance(node, dict) and node.get('@type') == 'WebPage']
    canonical_url = canonical.get('href') if canonical else (page_urls[0] if len(page_urls) == 1 else None)
    if (canonical_url != item['url'] or not heading or len(bodies) != 1
            or plain(str(heading)) != item['title'] or len(nodes) != 1 or plain(nodes[0].get('name')) != item['title']):
        raise ValueError('boston_arts_remaining_identity_changed')
    native = nodes[0]
    if native.get('eventStatus') != 'https://schema.org/EventScheduled' or native.get('eventAttendanceMode') != 'https://schema.org/OfflineEventAttendanceMode':
        return []
    body = shared._body(str(bodies[0]))
    where = native.get('location') or {}
    if (where.get('name'), where.get('address')) != ('ICA Boston', '25 Harbor Shore Drive. Boston MA 02210'):
        raise ValueError('boston_arts_remaining_no_physical_venue')
    if set(item.get('labels', [])) & {'At Seaport Studio', 'At the Watershed'}:
        raise ValueError('boston_arts_remaining_no_physical_venue')
    export = item['url'].rstrip('/') + '/addtocal/ics'
    if not soup.find('a', href=export):
        raise ValueError('boston_arts_remaining_schedule_changed')
    events = Calendar.from_ical(fetch(export, 'text/calendar')).walk('VEVENT')
    dates_node = soup.select_one('.field-name-event-date')
    visible = dates_node.select('.event-date-display') if dates_node else []
    if not events or len(events) > 100 or len(events) != len(visible):
        raise ValueError('boston_arts_remaining_schedule_changed')
    rows = []
    for index, event in enumerate(events):
        uid = re.fullmatch(r'event-(\d+)-(\d+)@www[.]icaboston[.]org', str(event.get('UID', '')))
        start, end = event.decoded('DTSTART'), event.decoded('DTEND', None)
        if (not uid or plain(plain(event.get('SUMMARY'))) != item['title']
                or any(name in event for name in ('RRULE', 'RDATE', 'RECURRENCE-ID'))
                or not isinstance(start, datetime) or start.tzinfo is None
                or not isinstance(end, datetime) or end.tzinfo is None or end < start):
            raise ValueError('boston_arts_remaining_schedule_changed')
        if index == 0 and (timestamp(native.get('startDate')) != start or timestamp(native.get('endDate')) != end):
            raise ValueError('boston_arts_remaining_schedule_changed')
        if end == start:
            end = None  # Some tours publish only a starting time.
        if not shared._within(start, end, now, DAYS):
            continue
        # Export index shifts as expired dates disappear; identity uses the
        # stable WordPress event id and the exact UTC occurrence instead.
        identity = 'ica:' + uid[1] + ':' + start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        row = record(item['title'], start.isoformat(), end.isoformat() if end else None,
                     'Institute of Contemporary Art/Boston', '25 Harbor Shore Drive, Boston, MA 02210',
                     'Boston', item['url'], identity, tz=ZONE, retain_until_end=True)
        row = _finish(ICA, row, body, item.get('labels', []))
        if row:
            rows.append(row)
    return rows


def _bca_listing(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    listing = soup.select_one('#listing-items')
    if not listing:
        raise ValueError('boston_arts_remaining_listing_changed')
    queue = []
    # The publisher's Listing class reveals six cards at a time. Every card
    # already occurs in this HTML; Load More has no network pagination.
    for card in listing.select('article.card-event'):
        link, heading = card.select_one('a[href]'), card.select_one('h5')
        if not link or not heading or not event_url(BCA, link.get('href')):
            raise ValueError('boston_arts_remaining_identity_changed')
        queue.append(dict(url=link['href'], title=plain(heading.get_text(' ')), labels=card.get('data-categories', '').split(',')))
    return queue, None


def _clock(value):
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', value, re.I)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError('boston_arts_schedule_unresolved')
    return (int(match[1]) % 12 + (12 if match[3].lower() == 'pm' else 0), int(match[2] or 0))


def _bca_detail(item, payload, now):
    soup = BeautifulSoup(payload, 'html.parser')
    main = soup.select_one('main')
    heading = main.select_one('.section-hero h1') if main else None
    canonical = soup.select_one('link[rel~=canonical]')
    sidebar = main.select_one('.is-description .wysiwyg.sidebar') if main else None
    if (not heading or not canonical or canonical.get('href') != item['url'] or not sidebar
            or plain(heading.get_text(' ')) != item['title']):
        raise ValueError('boston_arts_remaining_identity_changed')
    schedule = sidebar.select_one('p strong')
    lines = [plain(x) for x in schedule.stripped_strings] if schedule else []
    if not lines or not re.fullmatch(r'\d{2}/\d{2}/20\d{2}(?: - \d{2}/\d{2}/20\d{2})?', lines[0]):
        raise ValueError('boston_arts_schedule_unresolved')
    dates = [datetime.strptime(x, '%m/%d/%Y').date() for x in lines[0].split(' - ')]
    body_nodes = main.select('section.section-copy .wysiwyg:not(.sidebar), section.section-callout')
    body = shared._body('\n\n'.join(str(n) for n in body_nodes))
    clocks = lines[1] if len(lines) > 1 else ''
    if len(dates) == 2:
        # A broad series/tour range is not one continuous public occurrence.
        # Require the current detail narrative's explicit day and clock.
        named = re.findall(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\s*(?:\||from)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)(?:\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm))?)', body, re.I)
        if len(named) != 1:
            raise ValueError('boston_arts_schedule_unresolved')
        month, day, year, clocks = named[0]
        day = datetime.strptime(f'{month} {day} {year or dates[-1].year}', '%B %d %Y').date()
        if not dates[0] <= day <= dates[-1]:
            raise ValueError('boston_arts_remaining_schedule_changed')
    else:
        day = dates[0]
    pieces = re.split(r'\s*[-–]\s*', clocks)
    if len(pieces) not in (1, 2):
        raise ValueError('boston_arts_schedule_unresolved')
    start_clock = _clock(pieces[0])
    start = datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)).replace(hour=start_clock[0], minute=start_clock[1])
    end = None
    if len(pieces) == 2:
        end_clock = _clock(pieces[1]);end = start.replace(hour=end_clock[0], minute=end_clock[1])
        if end <= start:
            raise ValueError('boston_arts_remaining_schedule_changed')
    if not shared._within(start, end, now, DAYS):
        return []
    venue = sidebar.select_one('h6.address-title')
    address_node = venue.find_next_sibling('p') if venue else None
    address_lines = list(address_node.stripped_strings) if address_node else []
    cityline = re.fullmatch(r'(.+),\s*MA\s+(\d{5}(?:-\d{4})?)', plain(address_lines[-1])) if address_lines else None
    if len(address_lines) != 2 or not cityline:
        raise ValueError('boston_arts_street_unresolved')
    complete = shared._address(address_lines[0], cityline[1], 'MA', cityline[2])
    row = record(item['title'], start.isoformat(), end.isoformat() if end else None,
                 plain(venue.get_text(' ')), complete, cityline[1], item['url'],
                 urlsplit(item['url']).path.split('/')[-2] + ':' + day.isoformat(), tz=ZONE, retain_until_end=True)
    return [row] if (row := _finish(BCA, row, body, item.get('labels', []))) else []


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        started = timestamp(value['started_at'])
        queue = value['queue']
        limit = CHECKPOINT_MANIFEST_LIMITS.get(key, 200)
        valid = (value['source_key'] == key and type(value['version']) is int and value['version'] == 1
                 and type(value['manifest_count']) is int and 0 <= value['manifest_count'] <= limit
                 and type(value['cursor']) is int and 0 <= value['cursor'] <= value['manifest_count']
                 and type(value['listing_complete']) is bool
                 and isinstance(queue, list) and len(queue) == value['manifest_count']
                 and len({item['url'] for item in queue}) == len(queue)
                 and value['manifest_hash'] == _hash(queue)
                 and all(event_url(key, item['url']) and isinstance(item['title'], str) and 0 < len(item['title']) <= 500 for item in queue)
                 and isinstance(value['listed_pages'], list) and 1 <= len(value['listed_pages']) <= 40
                 and len(set(value['listed_pages'])) == len(value['listed_pages'])
                 and all(_listed_url(key, page) for page in value['listed_pages'])
                 and (value['next_page'] is None if value['listing_complete'] else _listed_url(key, value['next_page']))
                 and (value['listing_complete'] or value['cursor'] == 0 and not value['events'])
                 and isinstance(value['events'], list) and len(value['events']) <= CHECKPOINT_EVENT_LIMITS.get(key, 201)
                 and isinstance(value['diagnostics'], list) and len(value['diagnostics']) <= 400
                 and value['window_start'] == started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                 and started.tzinfo is not None and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        processed = {item['url'] for item in queue[:value['cursor']]}
        identities = set()
        for row in value['events']:
            start, end = timestamp(row['starts_at']), timestamp(row.get('ends_at'))
            identity = (row['id'], row['starts_at'])
            valid = (valid and row['event_url'] in processed and identity not in identities
                     and isinstance(row['description'], str) and 0 < len(row['description']) <= MAX_DESCRIPTION
                     and bool(row.get('venue_name')) and shared.STREET.match(row.get('venue_address', '')) is not None
                     and re.search(r', MA \d{5}(?:-\d{4})?$', row['venue_address']) is not None
                     and row.get('timezone') == ZONE and row.get('attendance_mode') == 'in_person'
                     and (key != MFA or ((row.get('lat'), row.get('lng')) == MFA_VENUE_POINT
                         and row.get('location_provenance') == 'publisher_partner_museum_geo'))
                     and start.tzinfo is not None and (end is None or end.tzinfo is not None and end >= start)
                     and shared._within(start, end, started, DAYS))
            identities.add(identity)
        for item in value['diagnostics']:
            valid = valid and item['event_url'] in processed and item['disposition'] == 'held' and item['reason'] in HOLD_REASONS
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('boston_arts_remaining_checkpoint_invalid')
    if not started <= now <= started + timedelta(hours=4):
        return None
    return deepcopy(value)


def _listing(key, payload, url, now):
    if key == MFA:
        return _mfa_listing(payload, url, now)
    if key == ICA:
        return _ica_listing(payload)
    return _bca_listing(payload)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=20):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError('publisher_checkpoint_required')
    current = now or datetime.now(timezone.utc)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    state = _checkpoint(checkpoint, key, current)
    if state is None:
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=_hash([]), manifest_count=0, cursor=0, queue=[], events=[], diagnostics=[],
                     listed_pages=[], next_page=SOURCES[key][0], listing_complete=False)
    if not state['listing_complete']:
        prior_pages = len(state['listed_pages'])
        # MFA's complete calendar spans many pages. Reuse the same bounded
        # transport for a few consecutive pages while retaining the durable
        # listing phase and the detail phase's twelve-second reserve. Existing
        # version-one checkpoints resume at their exact saved next_page.
        for _ in range(LISTING_PAGES_PER_CHUNK[key]):
            if state['listing_complete'] or key == MFA and monotonic() + 12 >= deadline:
                break
            shared._check(deadline)
            url = state['next_page']
            if url in state['listed_pages'] or len(state['listed_pages']) >= 40:
                raise ValueError('boston_arts_remaining_pagination_changed')
            added, next_page = _listing(key, fetch(url, 'text/html'), url, timestamp(state['started_at']))
            existing = {item['url']: item for item in state['queue']}
            for item in added:
                if item['url'] in existing and existing[item['url']] != item:
                    raise ValueError('boston_arts_remaining_manifest_changed')
                existing[item['url']] = item
            state['queue'] = sorted(existing.values(), key=lambda item: item['url'])
            if len(state['queue']) > CHECKPOINT_MANIFEST_LIMITS.get(key, 200):
                raise ValueError('boston_arts_remaining_manifest_limit')
            state['listed_pages'].append(url)
            state['manifest_count'], state['manifest_hash'] = len(state['queue']), _hash(state['queue'])
            state['next_page'], state['listing_complete'] = next_page, next_page is None
            if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
                raise ValueError('boston_arts_remaining_checkpoint_size_limit')
        if len(state['listed_pages']) == prior_pages:
            raise ValueError('collection_deadline')
        return dict(complete=state['listing_complete'] and not state['queue'], events=[], checkpoint=state)
    if state['cursor'] == state['manifest_count']:
        return dict(complete=True, events=shared._unique(deepcopy(state['events'])), checkpoint=state)
    prior = state['cursor']
    for _ in range(min(max_details, DETAILS_PER_CHUNK[key])):
        if state['cursor'] == state['manifest_count'] or monotonic() + 12 >= deadline:
            break
        item = state['queue'][state['cursor']]
        payload = fetch(item['url'], 'text/html')
        try:
            anchor = timestamp(state['started_at'])
            rows = (_mfa_detail(item, payload, anchor) if key == MFA else
                    _ica_detail(item, payload, fetch, anchor) if key == ICA else
                    _bca_detail(item, payload, anchor))
            state['events'] = shared._unique(state['events'] + rows)
            if len(state['events']) > CHECKPOINT_EVENT_LIMITS.get(key, 201):
                raise ValueError('boston_arts_remaining_record_limit')
            if not rows:
                state['diagnostics'].append(dict(event_url=item['url'], disposition='held', reason='event_not_current'))
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            state['diagnostics'].append(dict(event_url=item['url'], disposition='held', reason=str(exc)))
        state['cursor'] += 1
    if prior == state['cursor']:
        raise ValueError('collection_deadline')
    if len(state['diagnostics']) > 400 or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('boston_arts_remaining_checkpoint_size_limit')
    complete = state['cursor'] == state['manifest_count']
    return dict(complete=complete, events=deepcopy(state['events']) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    if key in CHECKPOINT_KEYS:
        raise ValueError('publisher_checkpoint_required')
    current = now or datetime.now(timezone.utc)
    if key == SOWA:
        return _sowa_season(fetch(SOURCES[key][0], 'text/html'), current)
    return _brookline(fetch(SOURCES[key][0], 'text/calendar'), current)


ERROR_CODES = shared.ERROR_CODES | {
    'unregistered_boston_arts_remaining_source', 'boston_arts_remaining_identity_changed',
    'boston_arts_remaining_listing_changed', 'boston_arts_remaining_schedule_changed',
    'boston_arts_remaining_pagination_changed', 'boston_arts_remaining_manifest_changed',
    'boston_arts_remaining_manifest_limit', 'boston_arts_remaining_record_limit',
    'boston_arts_remaining_checkpoint_invalid', 'boston_arts_remaining_checkpoint_size_limit',
    'boston_arts_remaining_feed_limit', 'boston_arts_remaining_recurrence_changed',
    'boston_arts_remaining_no_physical_venue', 'boston_arts_remaining_description_unavailable',
    'boston_arts_remaining_season_changed',
}


SOWA_NOVEMBER_HOURS = [
    'Opening Night (Nov 20): 4 PM – 9 PM', 'Monday: Closed',
    'Tuesday – Thursday: 4 PM – 8 PM', 'Friday: 4 PM – 9 PM',
    'Saturday: 10 AM – 9 PM', 'Sunday: 10 AM – 7 PM',
    'Black Friday (Nov 27): 10 AM – 7 PM', 'Thanksgiving Day: Closed',
]
SOWA_DECEMBER_HOURS = [
    'Monday: Closed', 'Tuesday – Thursday: 4 PM – 9 PM',
    'Friday: 4 PM – 10 PM', 'Saturday: 10 AM – 10 PM', 'Sunday: 10 AM – 7 PM',
    'Christmas Eve (Dec 24): 10 AM – 4 PM', 'Christmas Day: Closed',
]


def _sowa_season(payload, now):
    """Expand only the publisher's reviewed 2026 season and explicit exceptions."""
    soup = BeautifulSoup(payload, 'html.parser')
    article = soup.select_one('article#post-23882')
    canonical = soup.select_one('link[rel~=canonical]')
    if not article or not canonical or canonical.get('href') != SOURCES[SOWA][0]:
        raise ValueError('boston_arts_remaining_season_changed')
    headings = [plain(n.get_text(' ')) for n in article.select('h2, h4')]
    if 'The 11th Annual SoWa Christmas Market' not in headings or 'November 20 through December 27, 2026' not in headings:
        raise ValueError('boston_arts_remaining_season_changed')
    intros = [n for n in article.select('.elementor-widget-text-editor') if 'Boston’s premier indoor holiday shopping experience' in n.get_text()]
    hour_nodes = [n for n in article.select('.elementor-widget-text-editor') if n.find('h3', string='Hours of Operation')]
    if len(intros) != 1 or len(hour_nodes) != 1:
        raise ValueError('boston_arts_remaining_season_changed')
    expected = {'November Hours': SOWA_NOVEMBER_HOURS, 'Starting December 1': SOWA_DECEMBER_HOURS}
    for title, lines in expected.items():
        heading = hour_nodes[0].find('h5', string=title)
        paragraph = heading.find_next_sibling('p') if heading else None
        actual = [plain(v) for v in paragraph.stripped_strings] if paragraph else []
        if actual != lines:
            raise ValueError('boston_arts_remaining_season_changed')
    faq = {}
    for node in article.select('.elementor-toggle-item'):
        title, body = node.select_one('.elementor-toggle-title'), node.select_one('.elementor-tab-content')
        if not title or not body or plain(title.get_text()) in faq:
            raise ValueError('boston_arts_remaining_season_changed')
        faq[plain(title.get_text())] = (node, body)
    location = faq.get('Where is SoWa Christmas Market located?')
    schedule = faq.get('When is the Christmas Market open?')
    if not location or not schedule or plain(location[1].get_text(' ')) != 'SoWa Boston, 550 Harrison Ave., Boston, MA 02118':
        raise ValueError('boston_arts_remaining_season_changed')
    schedule_text = plain(schedule[1].get_text(' '))
    if not all(line in schedule_text for line in SOWA_NOVEMBER_HOURS + SOWA_DECEMBER_HOURS):
        raise ValueError('boston_arts_remaining_season_changed')
    # Complete current program narrative and every current visitor FAQ. Hidden
    # legacy 8th-annual Winter Festival copy and vendor-directory names are not
    # the 11th-annual program description.
    body = shared._body(str(intros[0]) + '\n' + '\n'.join(str(item[0]) for item in faq.values()))
    begins = datetime(2026, 11, 20, tzinfo=ZoneInfo(ZONE))
    last = datetime(2026, 12, 27, tzinfo=ZoneInfo(ZONE))
    rows = []
    day = begins
    while day <= last:
        if day.weekday() != 0 and (day.month, day.day) not in {(11, 26), (12, 25)}:
            if (day.month, day.day) == (11, 27):
                opening, closing = 10, 19
            elif (day.month, day.day) == (12, 24):
                opening, closing = 10, 16
            elif day.weekday() in (1, 2, 3):
                opening, closing = 16, 20 if day.month == 11 else 21
            elif day.weekday() == 4:
                opening, closing = 16, 21 if day.month == 11 else 22
            elif day.weekday() == 5:
                opening, closing = 10, 21 if day.month == 11 else 22
            else:
                opening, closing = 10, 19
            start, end = day.replace(hour=opening), day.replace(hour=closing)
            if shared._within(start, end, now, DAYS):
                row = record('SoWa Christmas Market', start.isoformat(), end.isoformat(), 'SoWa Power Station',
                             '550 Harrison Avenue, Boston, MA 02118', 'Boston', SOURCES[SOWA][0],
                             'sowa-christmas-2026:' + day.date().isoformat(), tz=ZONE, retain_until_end=True)
                row = _finish(SOWA, row, body, ['Markets', 'Makers', 'Food & Drink', 'Family'])
                if row:
                    rows.append(row)
        day += timedelta(days=1)
    return rows
