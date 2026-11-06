"""South Hill Chamber's public GrowthZone listing -> detail -> linked ICS.

This is the modern HTML publishing surface, not GrowthZone's legacy XML API.
Every advertised result and pagination link is accounted for before a successful
snapshot. Only linked same-publisher exports are fetched; original ICS UIDs and
actual per-event venues survive the shared ICS/factual normalization.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic
from urllib.parse import parse_qsl, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.ics_adapter import parse as parse_ics
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'south_hill_chamber_va'
HOST = 'members.southhillchamber.com'
CALENDAR = 'https://' + HOST + '/calendar'
TIMEZONE = 'America/New_York'
MAX_PAGES = 5
MAX_LISTINGS = 100
MAX_DETAILS = 20
MAX_SECONDS = 30
LOOKAHEAD_DAYS = 60
_DETAIL_PATH = re.compile(r'/(?:calendar|events)/Details/([a-z0-9]+(?:-[a-z0-9]+)*-([1-9]\d{0,11}))/?')


class EventHold(ValueError):
    """An identified event needs factual review, not a guessed replacement."""


class EventExcluded(ValueError):
    """An explicitly nonpublic record is not a public activity."""


@dataclass(frozen=True)
class Listing:
    identity: str
    url: str
    title: str
    start: datetime
    end: datetime
    visible_time: str


@dataclass(frozen=True)
class Detail:
    ics_url: str
    venue: str
    street: str
    city: str
    region: str
    postal: str
    description: str
    status: str | None
    venue_error: str | None = None
    excluded: bool = False

    @property
    def address(self):
        if not self.street or not self.city or not self.region:
            return ''
        return f'{self.street}, {self.city}, {self.region}' + (f' {self.postal}' if self.postal else '')


def _log(kind, **fields):
    print(json.dumps({'event': 'south_hill_chamber_' + kind, 'source_key': SOURCE_KEY,
                      **fields}, sort_keys=True), file=sys.stderr)


def _check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _public_url(url):
    if not isinstance(url, str) or len(url) > 2000 or re.search(r'[\x00-\x20\\<>]', url):
        raise ValueError('invalid_chamber_event_link')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != HOST or parts.username
            or parts.password or parts.fragment):
        raise ValueError('invalid_chamber_event_link')
    return parts


def canonical_event_url(value):
    parts = _public_url(value)
    match = _DETAIL_PATH.fullmatch(parts.path)
    if not match:
        raise ValueError('invalid_chamber_event_link')
    query = parse_qsl(parts.query, keep_blank_values=True)
    if query not in ([], [('sourceTypeId', 'Website')], [('sourceTypeId', 'Hub')]):
        raise ValueError('invalid_chamber_event_link')
    # Both path aliases are observed in this publisher's own page/export; the
    # canonical calendar path without sourceTypeId was verified public.
    return CALENDAR + '/Details/' + match[1], match[2]


def _narrative(value):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > 50000:
        raise ValueError('invalid_chamber_description')
    soup = BeautifulSoup(value, 'html.parser')
    for node in soup.select('script, style, template, noscript, iframe, head'):
        node.decompose()
    return '\n'.join(line.strip() for line in soup.get_text('\n').splitlines()
                     if line.strip())[:2000]


def _listing_time(value):
    try:
        wall = datetime.strptime(value, '%m/%d/%Y %I:%M:%S %p')
        return timestamp(wall.isoformat(), TIMEZONE)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('invalid_chamber_listing_time') from exc


def _pagination_url(value, base):
    url = urljoin(base, value)
    parts = _public_url(url)
    if parts.path.rstrip('/') != '/calendar':
        raise ValueError('unsupported_chamber_pagination')
    fields = parse_qsl(parts.query, keep_blank_values=True)
    if not fields:
        return CALENDAR
    if (len(fields) != 1 or fields[0][0] not in ('page', 'Page')
            or not re.fullmatch(r'[1-9]\d{0,2}', fields[0][1])):
        raise ValueError('unsupported_chamber_pagination')
    return CALENDAR + '?' + fields[0][0] + '=' + fields[0][1]


def _listing_page(payload, url):
    soup = BeautifulSoup(payload, 'html.parser')
    roots = soup.select('.gz-events-listing')
    if len(roots) != 1:
        raise ValueError('unsupported_chamber_listing')
    root = roots[0]
    counts = []
    for node in root.select('.gz-subtitle'):
        match = re.fullmatch(r'Results:\s*([0-9]+)', node.get_text(' ', strip=True))
        if match:
            counts.append(int(match[1]))
    if len(counts) != 1 or len(root.select('.gz-events-cards')) != 1:
        raise ValueError('unsupported_chamber_listing')
    total = counts[0]
    if total > MAX_LISTINGS:
        raise ValueError('source_record_limit')
    items = []
    for card in root.select('.gz-events-cards .gz-events-card'):
        links = card.select('a.gz-event-card-title[href]')
        starts = card.select('meta[itemprop="startDate"][content]')
        ends = card.select('meta[itemprop="endDate"][content]')
        if len(links) != 1 or len(starts) != 1 or len(ends) != 1:
            raise ValueError('chamber_listing_record_incomplete')
        canonical, identity = canonical_event_url(urljoin(url, links[0]['href']))
        title = plain(links[0].get_text())
        if not title:
            raise ValueError('event_title_missing')
        start, end = _listing_time(starts[0]['content']), _listing_time(ends[0]['content'])
        if end <= start:
            raise ValueError('invalid_event_end')
        visible = card.select_one('.gz-event-card-time')
        items.append(Listing(identity, canonical, title, start, end,
                             visible.get_text(' ', strip=True) if visible else ''))
    if len(items) > MAX_LISTINGS or len(items) > total:
        raise ValueError('chamber_result_count_mismatch')
    following = set()
    for anchor in root.select('.pagination a[href], .gz-pagination a[href], a[rel="next"]'):
        if anchor.find_parent(class_='disabled') or anchor.get('aria-disabled') == 'true':
            continue
        if anchor['href'] in ('#', ''):
            continue
        following.add(_pagination_url(anchor['href'], url))
    # Unknown pager controls must not silently truncate a changed publishing UI.
    for anchor in root.select('a[href]'):
        label = plain(anchor.get_text()).casefold().strip('›»→ ')
        if label in ('next', 'next page', 'load more'):
            following.add(_pagination_url(anchor['href'], url))
    return total, items, following


def _event_json(soup):
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid_chamber_detail_json') from exc
        nodes = value if isinstance(value, list) else [value]
        for node in nodes:
            if isinstance(node, dict) and node.get('@type') == 'Event':
                events.append(node)
    if len(events) != 1:
        raise ValueError('unsupported_chamber_detail')
    return events[0]


def _key(value):
    return re.sub(r'[^a-z0-9]', '', plain(value).casefold())


def _clock(value):
    return value.astimezone(ZoneInfo(TIMEZONE)).strftime('%I:%M %p').lstrip('0')


def _visible_times(root, event):
    if re.sub(r'\s+', ' ', event.visible_time).replace('–', '-') != f'{_clock(event.start)} - {_clock(event.end)}':
        raise EventHold('publisher_schedule_conflict')
    nodes = root.select('.gz-details-titles .gz-subtitle, .gz-event-time')
    if not nodes:
        raise EventHold('publisher_schedule_missing')
    for node in nodes:
        text = node.get_text(' ', strip=True)
        match = re.match(r'^[A-Za-z]+,\s+([A-Za-z]+ \d{1,2}, \d{4})\s*'
                         r'\((\d{1,2}:\d{2} [AP]M)\s*[-–]\s*(\d{1,2}:\d{2} [AP]M)\)', text)
        if not match:
            raise EventHold('publisher_schedule_missing')
        try:
            day = datetime.strptime(match[1], '%B %d, %Y').date()
        except ValueError as exc:
            raise EventHold('publisher_schedule_conflict') from exc
        if (day != event.start.date() or match[2] != _clock(event.start)
                or match[3] != _clock(event.end)):
            raise EventHold('publisher_schedule_conflict')
        abbr = node.select_one('abbr')
        if not abbr or plain(abbr.get_text()) != event.start.tzname():
            raise EventHold('publisher_timezone_review_required')


def _detail_venue(root, location):
    if not isinstance(location, dict) or location.get('@type') != 'Place':
        raise EventHold('event_venue_unreviewed')
    venue = plain(location.get('name'))
    if re.search(r'\b(?:zoom|online|virtual|webinar)\b', venue, re.I):
        raise EventHold('virtual_event')
    address = location.get('address')
    if not isinstance(address, dict) or address.get('@type') != 'PostalAddress':
        raise EventHold('event_venue_unreviewed')
    street, city, region, postal = [plain(address.get(key)) for key in
                                   ('streetAddress', 'addressLocality', 'addressRegion', 'postalCode')]
    if (not venue or not re.search(r'\b\d{1,6}\s+[A-Za-z]', street) or not city
            or not re.fullmatch(r'[A-Z]{2}', region)
            or (postal and not re.fullmatch(r'\d{5}(?:-\d{4})?', postal))):
        raise EventHold('event_venue_unreviewed')
    shown = root.select_one('.gz-event-address')
    if not shown:
        raise EventHold('event_venue_unreviewed')
    for selector, value in (('strong', venue), ('.gz-street-address', street),
                            ('.gz-city', city), ('.gz-state', region), ('.gz-postalcode', postal)):
        node = shown.select_one(selector)
        if value and (node is None or _key(node.get_text()) != _key(value)):
            raise EventHold('conflicting_event_venue')
    return venue, street, city, region, postal


def _detail(payload, event):
    soup = BeautifulSoup(payload, 'html.parser')
    roots = soup.select('.gz-event-details')
    if len(roots) != 1:
        raise ValueError('unsupported_chamber_detail')
    root = roots[0]
    title = root.select_one('h1.gz-pagetitle')
    meta = _event_json(soup)
    if (not title or plain(title.get_text()) != event.title
            or plain(meta.get('name')) != event.title):
        raise ValueError('publisher_event_identity_conflict')
    if meta.get('startDate') != event.start.date().isoformat():
        raise EventHold('publisher_schedule_conflict')
    description_node = root.select_one('.gz-event-description')
    if description_node:
        for heading in description_node.select('h3.gz-subtitle'):
            heading.decompose()
    description = _narrative(str(description_node or ''))
    combined = event.title + ' ' + description
    excluded = bool(re.search(r'\b(?:closed|closure|closing\s+early|private\s+(?:event|party|function)|'
                              r'members?[\s-]+only|invitation[\s-]+only)\b', combined, re.I))
    status_value = meta.get('eventStatus')
    statuses = {'https://schema.org/EventScheduled': 'scheduled',
                'https://schema.org/EventCancelled': 'cancelled',
                'https://schema.org/EventPostponed': 'postponed'}
    if status_value not in (None, '', *statuses):
        raise EventHold('unsupported_event_status')
    status = statuses.get(status_value)
    status_update = status in ('cancelled', 'postponed')
    if not status_update:
        _visible_times(root, event)
    if re.search(r'\b(?:cancelled|canceled|postponed)\b', event.title, re.I) and status not in ('cancelled', 'postponed'):
        raise EventHold('cancellation_requires_exact_status')
    duration = meta.get('duration')
    if duration and not status_update:
        match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?', str(duration))
        if not match or not any(match.groups()):
            raise EventHold('publisher_schedule_conflict')
        expected = timedelta(hours=int(match[1] or 0), minutes=int(match[2] or 0))
        if expected != event.end - event.start:
            raise EventHold('publisher_schedule_conflict')
    # Compare an explicit description of *this* workshop's length, not incidental
    # durations elsewhere in prose. The current marketing event says two hours
    # while its schedule/ICS say ninety minutes.
    words = {'one': 1, 'two': 2, 'three': 3, 'four': 4}
    advertised = re.findall(r'\bthis\s+(one|two|three|four|[1-9])[- ]hour\s+(?:workshop|class|program|event)\b', description, re.I)
    for value in advertised if not status_update else []:
        hours = words.get(value.casefold(), int(value) if value.isdigit() else 0)
        if event.end - event.start != timedelta(hours=hours):
            raise EventHold('publisher_schedule_conflict')
    location = meta.get('location')
    venue_error = None
    try:
        venue, street, city, region, postal = _detail_venue(root, location)
    except EventHold as exc:
        # A missing venue must not hide a linked, positively cancelled ICS.
        # Scheduled records still fail this same venue check after status/UID
        # verification; the address is never replaced with a publisher office.
        venue_error = str(exc)
        venue = plain(location.get('name')) if isinstance(location, dict) else ''
        street = city = region = postal = ''
    exports = set()
    expected_path = '/calendar/ICal/' + event.url.rsplit('/', 1)[1] + '.ics'
    for anchor in soup.select('a.gz-sharephone[href]'):
        href = anchor['href']
        if '/ICal/' not in href and not href.lower().endswith('.ics'):
            continue
        link = urljoin(event.url, href)
        parts = _public_url(link)
        if parts.path != expected_path or parts.query:
            raise ValueError('chamber_export_identity_mismatch')
        exports.add(link)
    if len(exports) != 1:
        raise ValueError('chamber_event_export_missing')
    return Detail(next(iter(exports)), venue, street, city, region, postal, description, status, venue_error, excluded)


def _ics_record(payload, event, detail, current):
    if not isinstance(payload, str) or not payload.lstrip('\ufeff \r\n').upper().startswith('BEGIN:VCALENDAR'):
        raise ValueError('invalid_calendar_payload')
    try:
        calendar = Calendar.from_ical(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid_calendar_payload') from exc
    components = calendar.walk('VEVENT')
    # This publisher's linked download is one event, not a complete feed.
    # A changed multi-event export must be reviewed; never silently select one.
    if len(components) != 1:
        raise ValueError('chamber_export_record_count')
    raw = components[0]
    if raw.errors:
        raise ValueError('invalid_ical_component')
    uid = str(raw.get('UID', ''))
    if not uid or len(uid) > 180 or re.search(r'[\x00-\x20]', uid):
        raise ValueError('chamber_export_identity_missing')
    if canonical_event_url(str(raw.get('URL', '')))[0] != event.url:
        raise ValueError('chamber_export_identity_mismatch')
    if plain(str(raw.get('SUMMARY', ''))) != event.title:
        raise ValueError('publisher_event_identity_conflict')
    if raw.get('RRULE') or raw.get('RDATE') or raw.get('EXDATE') or raw.get('RECURRENCE-ID'):
        raise EventHold('chamber_recurring_export_requires_review')
    ics_status = str(raw.get('STATUS', '')).upper()
    if ics_status not in ('', 'CONFIRMED', 'CANCELLED', 'CANCELED', 'TENTATIVE'):
        raise EventHold('unsupported_event_status')
    status = 'cancelled' if ics_status in ('CANCELLED', 'CANCELED') else detail.status
    if status == 'cancelled' and detail.status == 'postponed':
        raise EventHold('publisher_status_conflict')
    if detail.status in ('cancelled', 'postponed') and ics_status == 'CONFIRMED':
        raise EventHold('publisher_status_conflict')
    status_update = status in ('cancelled', 'postponed')
    if detail.excluded and not status_update:
        raise EventExcluded('nonpublic_or_closure_record')
    try:
        begins = raw.decoded('DTSTART')
        ends = raw.decoded('DTEND') if raw.get('DTEND') else None
    except (KeyError, ValueError) as exc:
        raise EventHold('event_time_missing') from exc
    if not isinstance(begins, datetime):
        raise EventHold('unsupported_all_day_time')
    if begins.tzinfo is None:
        raise EventHold('timezone_unresolved')
    if begins != event.start:
        raise EventHold('publisher_schedule_conflict')
    if ends is None and not status_update:
        raise EventHold('event_end_missing')
    if ends is not None:
        if not isinstance(ends, datetime):
            raise EventHold('unsupported_all_day_time')
        if ends.tzinfo is None:
            raise EventHold('timezone_unresolved')
        if ends != event.end:
            raise EventHold('publisher_schedule_conflict')
    if str(raw.get('X-MICROSOFT-CDO-ALLDAYEVENT', '')).upper() == 'TRUE':
        raise EventHold('unsupported_all_day_time')
    location = _key(str(raw.get('LOCATION', '')))
    expected = _key(detail.address)
    if not status_update:
        if detail.venue_error:
            raise EventHold(detail.venue_error)
        if location not in {expected, _key(detail.venue) + expected,
                            expected + 'unitedstates', _key(detail.venue) + expected + 'unitedstates'}:
            raise EventHold('conflicting_event_venue')
    rows = parse_ics(payload, {'source_key': SOURCE_KEY, 'url': event.url},
                     include_description=True)
    if len(rows) > 1:
        raise ValueError('chamber_export_record_count')
    row = rows[0] if rows else None
    if status_update:
        # The shared parser omits CANCELLED. After the exact UID/URL/start are
        # verified, status-only facts may update that existing occurrence even
        # if a publisher removes the end or venue. No end/location is inferred.
        row = {'id': uid, 'title': event.title[:180],
               'starts_at': begins.astimezone(timezone.utc).isoformat(),
               'ends_at': ends.astimezone(timezone.utc).isoformat() if ends else None,
               'category': '', 'publisher_categories': [],
               'description': str(raw.get('DESCRIPTION', ''))}
    elif row is None and ends is not None and begins <= current < ends:
        # Retain a positively timed ongoing event through its advertised end.
        row = record(event.title, begins.isoformat(), ends.isoformat(), detail.venue,
                     detail.address, detail.city, event.url, uid, tz=TIMEZONE,
                     retain_until_end=True)
        if row is not None:
            row['description'] = str(raw.get('DESCRIPTION', ''))
            row['publisher_categories'] = []
    if row is None:
        raise EventHold('chamber_event_normalization_unavailable')
    if row['id'] != uid or row['starts_at'] != begins.astimezone(timezone.utc).isoformat():
        raise ValueError('chamber_export_identity_mismatch')
    row.update(event_url=event.url, timezone=TIMEZONE, venue_name=detail.venue,
               venue_address=detail.address, venue_city=detail.city, lat=None, lng=None,
               reason='missing_verified_venue_geo',
               location_provenance=('publisher_status_without_venue' if status_update and detail.venue_error
                                    else 'publisher_event_address_pending_geocode'),
               description=_narrative(row.get('description')) or detail.description)
    if status:
        row['publisher_status'] = status
    attach(row, SOURCE_KEY, facts={})
    return row


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_south_hill_chamber_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('chamber_now_timezone_missing')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))

    def read(url, accept):
        _check_deadline(deadline)
        payload = fetch(url, accept)
        _check_deadline(deadline)
        return payload

    pending, visited, listings, total = [CALENDAR], set(), {}, None
    while pending:
        url = pending.pop(0)
        if url in visited:
            continue
        if len(visited) >= MAX_PAGES:
            raise ValueError('pagination_limit')
        visited.add(url)
        count, items, links = _listing_page(read(url, 'text/html'), url)
        if total is not None and count != total:
            raise ValueError('chamber_result_count_changed')
        total = count
        for event in items:
            if event.identity in listings and listings[event.identity] != event:
                raise ValueError('conflicting_event_identity')
            listings[event.identity] = event
        for link in sorted(links):
            if link not in visited and link not in pending:
                pending.append(link)
    if len(listings) != total:
        raise ValueError('chamber_result_count_mismatch')
    eligible = [event for event in listings.values()
                if event.end > current and event.start <= current + timedelta(days=LOOKAHEAD_DAYS)]
    if len(eligible) > MAX_DETAILS:
        raise ValueError('source_record_limit')
    records, identities, held, excluded = [], {}, 0, 0
    for event in sorted(eligible, key=lambda value: (value.start, value.identity)):
        try:
            detail = _detail(read(event.url, 'text/html'), event)
            row = _ics_record(read(detail.ics_url, 'text/calendar'), event, detail, current)
            key = (row['id'], row['starts_at'])
            if key in identities:
                if identities[key] != row:
                    raise ValueError('conflicting_event_occurrence')
                continue
            identities[key] = row
            records.append(row)
        except EventHold as exc:
            held += 1
            _log('event_held', identity=event.identity, reason=str(exc))
        except EventExcluded as exc:
            excluded += 1
            _log('event_excluded', identity=event.identity, reason=str(exc))
    _log('normalized', upstream_records=total, pages=len(visited), held=held,
         excluded=excluded, records=len(records))
    _check_deadline(deadline)
    if held and not records:
        raise ValueError('south_hill_chamber_event_evidence_unavailable')
    return sorted(records, key=lambda row: (row['starts_at'], row['id']))
