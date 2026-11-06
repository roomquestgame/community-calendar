"""Clarksville Tourism's bounded Locable calendar and dated event details.

Collection uses only the injected publisher transport. All advertised pages
must agree before detail extraction succeeds. The embedded calendar is evidence
for the displayed occurrence, not a reusable feed or permission to invent the
one-hour end Locable supplies for start-only listings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import base64
import binascii
import json
import re
import sys
from time import monotonic
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'clarksville_tourism_va'
HOST = 'tourism.visitclarksvilleva.com'
CALENDAR = 'https://' + HOST + '/calendar/'
TIMEZONE = 'America/New_York'
MAX_PAGES = 5
MAX_LISTINGS = 100
MAX_DETAILS = 20
MAX_SECONDS = 34
MAX_DESCRIPTION = 2000
MAX_FACT_TEXT = 50_000
MAX_INLINE_CALENDAR = 100_000
LOOKAHEAD_DAYS = 60
STATUS_LOOKBACK_DAYS = 7
_EVENT_PATH = re.compile(
    r'/connections/([1-9]\d{0,11}-[a-z0-9]+(?:-[a-z0-9]+)*)/events/'
    r'(20\d{2})/([1-9]|1[0-2])/([1-9]|[12]\d|3[01])/'
    r'([1-9]\d{0,11})/([a-z0-9]+(?:-[a-z0-9]+)*)/')
_TIME = r'(\d{1,2}:\d{2}\s*[AP]M)\s+(E[DS]T)'
_REVIEWED_REPLACEMENTS = {'636949': '667469'}


class EventHold(ValueError):
    """An identified occurrence lacks consistent public publisher evidence."""


class EventExcluded(ValueError):
    """The publisher positively identifies a nonpublic occurrence."""


@dataclass(frozen=True)
class Listing:
    identity: str
    organizer: str
    url: str
    title: str
    day: date
    visible_time: str
    address: str


@dataclass
class Event:
    listing: Listing
    row: dict
    narrative: str
    title: str


def _log(kind, **fields):
    print(json.dumps({'event': 'clarksville_tourism_' + kind,
                      'source_key': SOURCE_KEY, **fields}, sort_keys=True), file=sys.stderr)


def _check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _text(node):
    soup = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in soup.select('script,style,template,noscript,iframe,head'):
        tag.decompose()
    value = '\n'.join(line.strip() for line in soup.get_text('\n').splitlines() if line.strip())
    if len(value) > MAX_FACT_TEXT:
        raise ValueError('tourism_fact_text_limit')
    return value


def _key(value):
    return re.sub(r'[^a-z0-9]+', ' ', plain(value).casefold()).strip()


def _address_key(value):
    value = _key(value)
    for long, short in (('avenue', 'ave'), ('street', 'st'), ('road', 'rd'),
                        ('drive', 'dr'), ('boulevard', 'blvd')):
        value = re.sub(r'\b' + long + r'\b', short, value)
    return value


def _title(value):
    return re.sub(r'^\s*(?:cancelled|canceled|postponed)\s*[:–—-]\s*', '', plain(value), flags=re.I)


def _url(value):
    if not isinstance(value, str) or len(value) > 2000 or re.search(r'[\x00-\x20\\<>]', value):
        raise ValueError('invalid_tourism_link')
    p = urlsplit(value)
    if p.scheme != 'https' or p.netloc != HOST or p.fragment or p.username or p.password:
        raise ValueError('invalid_tourism_link')
    return p


def canonical_event_url(value):
    p = _url(value)
    match = _EVENT_PATH.fullmatch(p.path)
    if not match or p.query:
        raise ValueError('invalid_tourism_event_link')
    try:
        day = date(int(match[2]), int(match[3]), int(match[4]))
    except ValueError:
        raise ValueError('invalid_tourism_event_date') from None
    return value, match[5], match[1], day


def _page_url(value, base):
    url = urljoin(base, value)
    p = _url(url)
    if p.path != '/calendar/':
        raise ValueError('unsupported_tourism_pagination')
    query = parse_qsl(p.query, keep_blank_values=True)
    if not query:
        return CALENDAR, 1
    if (len(query) != 1 or query[0][0] != 'page'
            or not re.fullmatch(r'[1-9]\d{0,2}', query[0][1])
            or p.query != 'page=' + query[0][1]):
        raise ValueError('unsupported_tourism_pagination')
    number = int(query[0][1])
    if number > MAX_PAGES:
        raise ValueError('tourism_pagination_limit')
    return (CALENDAR if number == 1 else CALENDAR + '?page=' + str(number)), number


def _day(value):
    if not re.fullmatch(r'[A-Za-z]{3} \d{1,2}, 20\d{2}', value):
        raise EventHold('publisher_year_or_date_unresolved')
    try:
        return datetime.strptime(value, '%b %d, %Y').date()
    except ValueError:
        raise EventHold('publisher_year_or_date_unresolved') from None


def _clock(day, value, zone):
    try:
        clock = datetime.strptime(re.sub(r'\s+', '', value), '%I:%M%p').time()
        result = timestamp(datetime.combine(day, clock).isoformat(), TIMEZONE)
    except ValueError:
        raise EventHold('publisher_time_or_timezone_unresolved') from None
    if result.tzname() != zone:
        raise EventHold('publisher_timezone_conflict')
    return result


def _listing_page(payload, url):
    soup = BeautifulSoup(payload, 'html.parser')
    counts = soup.select('.event-count')
    if len(counts) != 1:
        raise ValueError('unsupported_tourism_listing')
    match = re.fullmatch(r'Displaying ([0-9]+) Events:', plain(counts[0].get_text()))
    if not match:
        raise ValueError('unsupported_tourism_listing')
    total = int(match[1])
    if total > MAX_LISTINGS:
        raise ValueError('tourism_source_record_limit')
    # This is a date-filtered catalog. A date rollover between pages is not a
    # complete, consistent snapshot even if the result count happens to agree.
    filters = soup.select('input#start_date')
    if len(filters) != 1:
        raise ValueError('unsupported_tourism_listing')
    scope = (filters[0].get('value', ''), filters[0].get('placeholder', ''))
    if not any(scope):
        raise ValueError('tourism_calendar_scope_missing')
    cards = soup.select('.event-block')
    if len(cards) > MAX_LISTINGS or (total and not cards):
        raise ValueError('unsupported_tourism_listing')
    listings = []
    for card in cards:
        links, dates = card.select('a.title[href]'), card.select('.time .date')
        if len(links) != 1 or len(dates) != 1:
            raise ValueError('unsupported_tourism_listing')
        event_url, identity, organizer, path_day = canonical_event_url(urljoin(url, links[0]['href']))
        try:
            day = _day(plain(dates[0].get_text()))
        except EventHold as exc:
            raise ValueError('tourism_listing_date_unresolved') from exc
        if day != path_day:
            raise ValueError('tourism_listing_date_conflict')
        title = plain(links[0].get_text())
        if not title:
            raise ValueError('tourism_listing_identity_missing')
        times = card.select('.time .start-time')
        streets, cities = card.select('.location .street1'), card.select('.location .city-state-zip')
        if len(times) > 1 or len(streets) > 1 or len(cities) > 1:
            raise ValueError('unsupported_tourism_listing')
        street = plain(streets[0].get_text()) if streets else ''
        city = plain(cities[0].get_text()) if cities else ''
        address = ', '.join(x for x in (street, city) if x)
        listings.append(Listing(identity, organizer, event_url, title, day,
                                plain(times[0].get_text()) if times else '', address))
    _, page_number = _page_url(url, CALENDAR)
    pagers = soup.select('.pagination')
    if len(pagers) > 1:
        raise ValueError('unsupported_tourism_pagination')
    following = set()
    if pagers:
        active = pagers[0].select('li.active')
        if len(active) != 1 or plain(active[0].get_text()) != str(page_number):
            raise ValueError('tourism_pagination_page_conflict')
        for anchor in pagers[0].select('a[href]'):
            if anchor.find_parent('li', class_='active'):
                if anchor['href'] != 'javascript:void(0)':
                    active_url, _ = _page_url(anchor['href'], url)
                    if active_url != url:
                        raise ValueError('tourism_pagination_page_conflict')
                continue
            following.add(_page_url(anchor['href'], url)[0])
    # Pagination outside the reviewed widget must not silently disappear.
    for anchor in soup.select('a[rel~="next"][href]'):
        if anchor.find_parent(class_='pagination') is None:
            raise ValueError('unsupported_tourism_pagination')
    return total, scope, listings, following


def _one(section, selector, *, required=True):
    values = section.select(selector)
    if len(values) > 1 or (required and not values):
        raise EventHold('publisher_event_facts_missing')
    return values[0] if values else None


def _inline_calendar(section):
    links = {a['href'] for a in section.select('.add-to-calendar a[href]')
             if a['href'].startswith('data:text/calendar')}
    if len(links) != 1:
        raise EventHold('publisher_calendar_evidence_missing')
    link = next(iter(links))
    if len(link) > MAX_INLINE_CALENDAR or not link.startswith('data:text/calendar;charset=utf8,'):
        raise ValueError('tourism_inline_calendar_limit_or_shape')
    payload = unquote(link.split(',', 1)[1])
    if not payload.startswith('BEGIN:VCALENDAR') or not payload.rstrip().endswith('END:VCALENDAR'):
        raise ValueError('tourism_inline_calendar_invalid')
    try:
        events = Calendar.from_ical(payload).walk('VEVENT')
    except (TypeError, ValueError) as exc:
        raise ValueError('tourism_inline_calendar_invalid') from exc
    if len(events) != 1:
        raise ValueError('tourism_inline_calendar_count')
    event = events[0]
    if any(event.get(key) is not None for key in ('RRULE', 'RDATE', 'RECURRENCE-ID', 'EXDATE')):
        raise EventHold('publisher_occurrence_recurrence_unreviewed')
    return event


def _status(raw_title, event, section):
    values = set()
    if match := re.match(r'^\s*(cancelled|canceled|postponed)\s*[:–—-]', raw_title, re.I):
        values.add('cancelled' if match[1].lower() == 'canceled' else match[1].lower())
    status = str(event.get('STATUS', '')).upper()
    if status in ('CANCELLED', 'CANCELED'):
        values.add('cancelled')
    elif status == 'CONFIRMED':
        values.add('scheduled')
    elif status:
        raise EventHold('publisher_status_unresolved')
    for node in section.select('[itemprop="eventStatus"]'):
        status = node.get('content') or node.get('href') or plain(node.get_text())
        mapping = {'EventCancelled': 'cancelled', 'EventPostponed': 'postponed',
                   'EventScheduled': 'scheduled'}
        value = mapping.get(status.rsplit('/', 1)[-1])
        if not value:
            raise EventHold('publisher_status_unresolved')
        values.add(value)
    if len(values) > 1:
        raise EventHold('publisher_status_conflict')
    return next(iter(values)) if values else 'scheduled'


def _postal(value):
    match = re.fullmatch(r'(\d{1,6}\s+[^,]+),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', value)
    if not match or re.search(r'\b(?:tba|tbd|unknown|virtual|online|zoom)\b', value, re.I):
        raise EventHold('publisher_street_venue_unresolved')
    return match[2]


def _profile_address_conflict(soup, section, venue, address):
    # A publisher's office is not an offsite event venue. Compare only when the
    # event explicitly names that very profile as its venue.
    container = section.find_parent('div', class_='container')
    if container is None:
        raise EventHold('publisher_profile_venue_unresolved')
    for adr in container.select('.adr'):
        if section in adr.parents:
            continue
        parent = adr.parent
        heading = parent.find('h2')
        if not heading:
            raise EventHold('publisher_profile_venue_unresolved')
        copied = BeautifulSoup(str(heading), 'html.parser')
        for small in copied.select('small'):
            small.decompose()
        if _key(copied.get_text()) != _key(venue):
            continue
        nodes = adr.select('[itemprop="address"]')
        if len(nodes) != 1:
            raise EventHold('publisher_profile_venue_unresolved')
        if _address_key(nodes[0].get_text(' ', strip=True)) != _address_key(address):
            raise EventHold('publisher_venue_address_conflict')


def _narrative_schedule(narrative, start, end):
    # Check only explicitly labelled event hours, never a check-in range or a
    # registration deadline occurring elsewhere in the same description.
    pattern = r'Event Hours:\s*(\d{1,2}:\d{2}\s*[AP]M)\s*[–—-]\s*(\d{1,2}:\d{2}\s*[AP]M)'
    for match in re.finditer(pattern, narrative, re.I):
        if (_clock(start.date(), match[1].upper(), start.tzname()) != start
                or end is None or _clock(end.date(), match[2].upper(), end.tzname()) != end):
            raise EventHold('publisher_narrative_schedule_conflict')
    date_pattern = (r'Date:\s*(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*)?'
                    r'(January|February|March|April|May|June|July|August|September|October|November|December)'
                    r'\s+(\d{1,2}),?\s+(20\d{2})\b')
    for match in re.finditer(date_pattern, narrative, re.I):
        try:
            day = datetime.strptime(' '.join((match[2], match[3], match[4])), '%B %d %Y').date()
        except ValueError:
            raise EventHold('publisher_narrative_date_conflict') from None
        if day != start.date() or (match[1] and day.strftime('%A').casefold() != match[1].casefold()):
            raise EventHold('publisher_narrative_date_conflict')


def _photo(section):
    photos = section.select('.blog-show-image img[itemprop="image"][src]')
    if len(photos) != 1:
        return None
    candidate = photos[0]['src']
    try:
        parts = urlsplit(candidate)
        if (parts.scheme != 'https' or parts.netloc != 'images.locable.com'
                or parts.query or parts.fragment or len(candidate) > 2000):
            return None
        data = json.loads(base64.b64decode(unquote(parts.path.lstrip('/')), validate=True))
        key = data.get('key', '')
        if (data.get('bucket') != 'impact-production' or not isinstance(key, str)
                or not re.fullmatch(r'_originals/[0-9a-f-]{36}/[^/]+\.(?:png|jpe?g|webp|gif)', key, re.I)
                or re.search(r'\b(?:logo|avatar|favicon|pixel|placeholder|default)\b', key, re.I)):
            return None
    except (ValueError, TypeError, AttributeError, binascii.Error):
        return None
    return candidate


def _status_row(title, start, end, listing):
    return {'id': 'locable_clarksville:' + listing.identity, 'title': title[:180],
            'starts_at': start.astimezone(timezone.utc).isoformat(),
            'ends_at': end.astimezone(timezone.utc).isoformat() if end else None,
            'event_url': listing.url, 'category': '', 'lat': None, 'lng': None,
            'reason': 'missing_verified_venue_geo'}


def parse_detail(payload, listing, *, now=None):
    current = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(payload, 'html.parser')
    sections = soup.select('[itemtype="http://schema.org/Event"], [itemtype="https://schema.org/Event"]')
    if len(sections) != 1:
        raise ValueError('unsupported_tourism_event_page')
    section = sections[0]
    raw_title = plain(_one(section, 'h1[itemprop="name"]').get_text())
    title = _title(raw_title)
    listed = _title(listing.title)
    truncated = listed.endswith('...') or listed.endswith('…')
    prefix = _key(re.sub(r'(?:\.\.\.|…)\s*$', '', listed))
    if not title or (not truncated and _key(title) != prefix) or (truncated and (len(prefix) < 12 or not _key(title).startswith(prefix))):
        raise EventHold('publisher_event_title_conflict')
    profile_link = '/connections/' + listing.organizer + '/'
    if not section.select_one('.breadcrumb a[href="' + profile_link + '"]'):
        raise EventHold('publisher_event_organizer_conflict')
    event = _inline_calendar(section)
    if _key(_title(str(event.get('SUMMARY', '')))) != _key(title):
        raise EventHold('publisher_calendar_identity_conflict')
    status = _status(raw_title, event, section)
    terminal = status in ('cancelled', 'postponed')
    day = _day(plain(_one(section, '[itemprop="startDate"]').get_text()))
    if day != listing.day:
        raise EventHold('publisher_calendar_date_conflict')
    display = _one(section, '[itemprop="doorTime"]')
    visible = re.fullmatch(_TIME, plain(display.get_text()))
    if not visible:
        raise EventHold('publisher_time_or_timezone_unresolved')
    start = _clock(day, visible[1], visible[2])
    listed_time = re.fullmatch(_TIME, listing.visible_time)
    if not listed_time or _clock(day, listed_time[1], listed_time[2]) != start:
        raise EventHold('publisher_listing_time_conflict')
    try:
        raw_start = event.decoded('DTSTART')
        raw_end = event.decoded('DTEND') if event.get('DTEND') else None
    except (KeyError, ValueError) as exc:
        raise EventHold('publisher_calendar_time_unresolved') from exc
    if not isinstance(raw_start, datetime) or raw_start.tzinfo is None or raw_start != start:
        raise EventHold('publisher_calendar_time_conflict')
    full_time = plain(display.parent.get_text())
    time_range = re.fullmatch(_TIME + r'\s+to\s+' + _TIME, full_time)
    end = None
    if time_range:
        ending_date = _one(section, '[itemprop="endDate"]', required=False)
        end_day = _day(plain(ending_date.get_text())) if ending_date else day
        end = _clock(end_day, time_range[3], time_range[4])
        if end <= start or end - start > timedelta(days=7):
            raise EventHold('publisher_calendar_end_conflict')
        if raw_end is None and terminal:
            end = None
        elif not isinstance(raw_end, datetime) or raw_end.tzinfo is None or raw_end != end:
            raise EventHold('publisher_calendar_end_conflict')
    elif full_time != plain(display.get_text()) and not terminal:
        raise EventHold('publisher_displayed_end_unresolved')
    # A start-only page's synthetic one-hour export end is deliberately ignored.
    if (start > current + timedelta(days=LOOKAHEAD_DAYS)
            or (terminal and start < current - timedelta(days=STATUS_LOOKBACK_DAYS))
            or (not terminal and (end or start + timedelta(hours=3)) <= current)):
        return None
    description_node = _one(section, '[itemprop="description"]', required=not terminal)
    narrative = _text(description_node)
    subtitle = _one(section, '.page-header h3', required=False)
    full_narrative = (plain(subtitle.get_text()) + '\n' if subtitle else '') + narrative
    notices = set()
    for sentence in re.split(r'[.!?\n]+', full_narrative):
        notice = re.match(r'^\s*(?:this|the) event\s+(?:has been|is(?: now)?|was)\s+'
                          r'(cancelled|canceled|postponed)\b', sentence, re.I)
        if notice and not re.search(r'\b(?:if|unless|in case)\b', sentence, re.I):
            notices.add('cancelled' if notice[1].casefold() == 'canceled' else notice[1].casefold())
    if notices and status == 'scheduled':
        # A stale inline export must not turn a direct body cancellation into
        # a positively scheduled occurrence. Unsupported prose status stays
        # held; cancellation-policy language alone does not trigger this rule.
        raise EventHold('publisher_narrative_status_unreviewed')
    if notices and notices != {status}:
        raise EventHold('publisher_status_conflict')
    if not terminal:
        _narrative_schedule(full_narrative, start, end)
        if re.search(r'\b(?:private event|members?[-\s]+only|exclusively for members|invitation[-\s]+only|not open to the public)\b', full_narrative + ' ' + title, re.I):
            raise EventExcluded('publisher_nonpublic_event')
        if (re.search(r'\bpoker\b', title, re.I) and re.search(r'\bpool tournament\b', narrative, re.I)
                or re.search(r'\bpool\b', title, re.I) and re.search(r'\bpoker tournament\b', narrative, re.I)):
            raise EventHold('publisher_activity_conflict')
        if not narrative:
            raise EventHold('publisher_description_missing')
    venue_node = _one(section, '.event-details [itemprop="location"]', required=False)
    address_node = _one(section, '.event-details [itemprop="address"]', required=False)
    venue = plain(venue_node.get_text()) if venue_node else ''
    address = plain(address_node.get_text()) if address_node else ''
    try:
        if not venue or re.search(r'\b(?:virtual|online|zoom|tba|tbd)\b', venue, re.I):
            raise EventHold('publisher_street_venue_unresolved')
        city = _postal(address)
        if not listing.address or _address_key(listing.address) != _address_key(address):
            raise EventHold('publisher_listing_address_conflict')
        if _address_key(str(event.get('LOCATION', ''))) != _address_key(address):
            raise EventHold('publisher_calendar_address_conflict')
        _profile_address_conflict(soup, section, venue, address)
    except EventHold:
        if not terminal:
            raise
        venue = address = city = ''
    row = (_status_row(title, start, end, listing) if terminal else
           record(title, start.isoformat(), end.isoformat() if end else None,
                  venue, address, city, listing.url, 'locable_clarksville:' + listing.identity,
                  tz=TIMEZONE, retain_until_end=True))
    if row is None:
        return None
    row.update(venue_name=venue, venue_address=address, venue_city=city, timezone=TIMEZONE,
               description=narrative[:MAX_DESCRIPTION], publisher_status=status,
               location_provenance=('publisher_explicit_status_without_current_venue' if not address
                                    else 'publisher_event_address_pending_geocode'),
               publisher_categories=[])
    facts = {}
    price = _one(section, '.event-details [itemprop="price"]', required=False)
    if price is not None:
        facts['cost'] = plain(price.get_text())[:400]
    tickets = [a for a in section.select('.event-details a[href]')
               if plain(a.get_text()).rstrip(' »').casefold() == 'tickets']
    if len(tickets) == 1:
        ticket_url = tickets[0]['href']
        parts = urlsplit(ticket_url)
        if (parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password
                and len(ticket_url) <= 350 and not re.search(r'[\x00-\x20\\<>]', ticket_url)):
            facts['registration'] = ('Tickets required. ' if re.search(r'tickets required', narrative, re.I) else '') + 'Tickets: ' + ticket_url
    if re.search(r'\bbring the family\b', narrative, re.I):
        facts['audience'] = 'Bring the family.'
    attach(row, SOURCE_KEY, facts=facts, candidate=_photo(section), evidence_url=listing.url)
    return Event(listing, row, narrative, title)


def _deduplicate(events, diagnostics):
    """Suppress only the reviewed teaser/final pair with current matching facts."""
    by_id = {event.listing.identity: event for event in events}
    suppressed = set()
    for teaser_id, final_id in _REVIEWED_REPLACEMENTS.items():
        teaser, final = by_id.get(teaser_id), by_id.get(final_id)
        if teaser and not final and any(
                held['id'] == final_id and held['reason'] in
                ('publisher_narrative_status_unreviewed', 'publisher_status_conflict')
                for held in diagnostics.get('held', [])):
            suppressed.add(teaser_id)
            diagnostics.setdefault('held', []).append({
                'id': teaser_id, 'event_url': teaser.listing.url,
                'reason': 'reviewed_teaser_final_status_unresolved'})
            continue
        if not teaser or not final:
            continue
        a, b = teaser.row, final.row
        common = (teaser.listing.organizer == final.listing.organizer
                  and a['starts_at'] == b['starts_at']
                  and _key(teaser.title).startswith('save the date ')
                  and all('cookie cocoa crawl' in _key(event.title) for event in (teaser, final)))
        if common and b['publisher_status'] in ('cancelled', 'postponed'):
            # Keep exact status evidence on the canonical final occurrence.
            # An older teaser must not reappear as a new scheduled event when
            # that final occurrence loses its venue/end during cancellation.
            # The teaser is held, never assigned another ID's cancellation.
            suppressed.add(teaser_id)
            diagnostics.setdefault('held', []).append({
                'id': teaser_id, 'event_url': teaser.listing.url,
                'reason': 'reviewed_teaser_conflicts_with_final_terminal_status'})
            continue
        if (not common or a.get('ends_at') != b.get('ends_at')
                or a.get('publisher_status') != b.get('publisher_status')
                or not a['venue_address'] or _address_key(a['venue_address']) != _address_key(b['venue_address'])
                or _key(a['venue_name']) != _key(b['venue_name'])
                or not re.search(r'ticket information.+coming soon', teaser.narrative, re.I | re.S)
                or not b['publisher_details'].get('cost') or not b['publisher_details'].get('registration')
                or _key(final.title).startswith('save the date ')):
            continue
        suppressed.add(teaser_id)
        diagnostics.setdefault('duplicates', []).append({'id': teaser_id, 'replaced_by': final_id,
                                                        'reason': 'reviewed_matching_teaser_and_final'})
    return [event.row for event in events if event.listing.identity not in suppressed]


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != CALENDAR
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_clarksville_tourism_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('tourism_now_timezone_missing')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))

    def get(url):
        _check_deadline(deadline)
        payload = fetch(url, 'text/html')
        _check_deadline(deadline)
        return payload

    pending, visited, listings, total, scope = [CALENDAR], set(), {}, None, None
    while pending:
        url = pending.pop(0)
        if url in visited:
            continue
        if len(visited) >= MAX_PAGES:
            raise ValueError('tourism_pagination_limit')
        visited.add(url)
        count, page_scope, items, links = _listing_page(get(url), url)
        if total is not None and count != total:
            raise ValueError('tourism_result_count_changed')
        if scope is not None and page_scope != scope:
            raise ValueError('tourism_calendar_scope_changed')
        total, scope = count, page_scope
        for event in items:
            if event.identity in listings and listings[event.identity] != event:
                raise ValueError('tourism_conflicting_event_identity')
            listings[event.identity] = event
        for link in sorted(links):
            if link not in visited and link not in pending:
                pending.append(link)
    if len(listings) != total:
        raise ValueError('tourism_result_count_mismatch')
    start_day = (current - timedelta(days=STATUS_LOOKBACK_DAYS)).astimezone(ZoneInfo(TIMEZONE)).date()
    end_day = (current + timedelta(days=LOOKAHEAD_DAYS)).astimezone(ZoneInfo(TIMEZONE)).date()
    eligible = [event for event in listings.values() if start_day <= event.day <= end_day]
    if len(eligible) > MAX_DETAILS:
        raise ValueError('tourism_detail_limit')
    events, diagnostics = [], {'held': [], 'excluded': []}
    for listing in sorted(eligible, key=lambda event: (event.day, event.identity)):
        try:
            if event := parse_detail(get(listing.url), listing, now=current):
                events.append(event)
        except EventHold as exc:
            diagnostics['held'].append({'id': listing.identity, 'reason': str(exc), 'event_url': listing.url})
        except EventExcluded as exc:
            diagnostics['excluded'].append({'id': listing.identity, 'reason': str(exc), 'event_url': listing.url})
    rows = _deduplicate(events, diagnostics)
    _check_deadline(deadline)
    _log('normalized', upstream_records=total, pages=len(visited), details=len(eligible),
         outside_window=len(listings) - len(eligible), records=len(rows), **diagnostics)
    if not rows and diagnostics['held']:
        raise ValueError('clarksville_tourism_event_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
