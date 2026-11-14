"""Reviewed Gulf Coast schedules, using only explicit publisher occurrences.

City Park's public list view has complete Event JSON-LD, including the actual
venue for each occurrence. Its API/ICS omit those venues. Read consecutive list
pages through the shared lookahead horizon; an incomplete traversal is an error,
never a successful truncated replacement. All I/O uses the supplied paced fetcher.
"""
from datetime import date, datetime, timedelta, timezone
import html
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import address, plain, record, timestamp
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import attach

ZONE = 'America/Chicago'
NOLA = 'gulf_nola_christmasfest_la'
CITY_PARK = 'municipal_mapsee_d871199cc551aa175f82de2b'
SOURCES = {
    NOLA: 'https://nolachristmasfest.com/plan-your-visit/',
    CITY_PARK: 'https://neworleanscitypark.org/calendar/',
}
MAX_CITY_PAGES = 3
MAX_CITY_EVENTS_PER_PAGE = 50
_CITY_EVENT = re.compile(
    r'https://neworleanscitypark[.]org/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?'
)
# Arts New Orleans' existing json/wordpress source, registry ID 4285
# (municipal_mapsee_123326fd5be1b9af7ecaaf9b),
# owns this reviewed series, with the precise Popp Bandstand address. City Park
# republishes it with a generic park venue; retain the organizer's occurrences.
_CITY_ORGANIZER_SERIES = {'arts-market-new-orleans-holiday-market'}
_CLOCK = r'(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*[ap]m'
_HOURS = re.compile(rf'({_CLOCK})\s*[-–—]\s*({_CLOCK})', re.I)
_MONTHS = {'Dec': 12, 'Jan': 1}
_NOLA_VENUE = 'New Orleans Ernest N. Morial Convention Center, Halls G–I'
_NOLA_ADDRESS = '900 Convention Center Blvd, New Orleans, LA'


def allowed_hosts(key):
    return {urlsplit(SOURCES[key]).hostname} if key in SOURCES else set()


def event_url(key, url):
    if not isinstance(url, str):
        return False
    return url == SOURCES[NOLA] if key == NOLA else bool(
        key == CITY_PARK and _CITY_EVENT.fullmatch(url)
    )


def photo_url(key, url):
    # No reviewed event-owned image contract for these publishers yet.
    return None


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def _check_deadline(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _page(fetch, url, canonical, deadline_at):
    _check_deadline(deadline_at)
    payload = fetch(url, 'text/html')
    _check_deadline(deadline_at)
    soup = BeautifulSoup(payload, 'html.parser')
    links = soup.select('link[rel="canonical"]')
    if len(links) != 1 or links[0].get('href') != canonical:
        raise ValueError('gulf_seasonal_publisher_unverified')
    return soup


def _clock(day, value):
    value = re.sub(r'\s+', '', value).upper()
    clock = datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()
    return timestamp(datetime.combine(day, clock), ZONE)


def _row(key, title, start, end, venue, street, city, url, identity, prose='', facts=None):
    if cancelled(title, prose):
        return None
    result = record(title, start, end, venue, street, city, url, identity, tz=ZONE)
    if result:
        result.update(description=prose, attendance_mode='in_person', timezone=ZONE)
        attach(result, key, facts=facts)
    return result


def _nola(soup):
    hours = soup.select_one('section#hours')
    edition = re.fullmatch(r'(20\d{2}) Hours of Operation', _text(hours.select_one('h2')) if hours else '')
    venue_text = _text(soup.select_one('section#transport'))
    if (not edition or 'New Orleans Ernest N. Morial Convention Center' not in venue_text
            or not re.search(r'\bHall G[-–]I\b', venue_text)
            or _NOLA_ADDRESS not in venue_text):
        raise ValueError('nola_christmasfest_schedule_unverified')
    days = hours.select('.hours-lists > .hours-list')
    if not 1 <= len(days) <= 62:
        raise ValueError('nola_christmasfest_schedule_unverified')
    year = int(edition[1])
    previous_day = None
    rows = []
    for item in days:
        labels = item.select('.left-block .month-day > span')
        number = _text(item.select_one('.left-block .edate'))
        if len(labels) != 2 or _text(labels[0]) not in _MONTHS or not re.fullmatch(r'\d{1,2}', number):
            raise ValueError('nola_christmasfest_invalid_date')
        month = _MONTHS[_text(labels[0])]
        # The printed edition is authoritative. Only an explicit Dec -> Jan
        # sequence advances its year; an old edition never rolls to "this year".
        if previous_day and previous_day.month == 12 and month == 1:
            year += 1
        day = date(year, month, int(number))
        if (day.strftime('%a') != _text(labels[1]) or (previous_day and day <= previous_day)
                or year > int(edition[1]) + 1 or (not previous_day and month != 12)):
            raise ValueError('nola_christmasfest_date_conflict')
        previous_day = day
        clocks = _text(item.select_one('.middle-block'))
        note = _text(item.select_one('.right-block'))
        if re.fullmatch(r'closed', clocks, re.I):
            continue
        sessions = re.split(r'\s*(?:&|\band\b)\s*', clocks, flags=re.I)
        if not 1 <= len(sessions) <= 4 or not re.search(r'\bopen to public\b', note, re.I):
            raise ValueError('nola_christmasfest_session_unverified')
        previous_end = None
        for session in sessions:
            match = _HOURS.fullmatch(session)
            if not match:
                raise ValueError('nola_christmasfest_session_unverified')
            start, end = (_clock(day, value) for value in match.groups())
            if end <= start or (previous_end and start < previous_end):
                raise ValueError('nola_christmasfest_session_conflict')
            previous_end = end
            identity = f'nola-christmasfest-{edition[1]}:{start.strftime("%Y-%m-%dT%H:%M")}'
            rows.append(_row(NOLA, 'NOLA ChristmasFest', start, end, _NOLA_VENUE,
                             _NOLA_ADDRESS, 'New Orleans', SOURCES[NOLA], identity,
                             'Open to public.', {'meeting_location': _NOLA_VENUE}))
    return [row for row in rows if row]


def _events(soup):
    events = []

    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            kinds = node.get('@type', [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if isinstance(kinds, list) and 'Event' in kinds:
                events.append(node)
            if '@graph' in node:
                walk(node['@graph'])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError) as exc:
            raise ValueError('city_park_invalid_jsonld') from exc
    if len(events) > MAX_CITY_EVENTS_PER_PAGE:
        raise ValueError('city_park_page_limit')
    return events


def _city_time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('city_park_time_unverified')
    result = timestamp(value)
    if result.utcoffset() != result.astimezone(ZoneInfo(ZONE)).utcoffset():
        raise ValueError('city_park_timezone_conflict')
    return result


def _city_page(soup):
    cards = soup.select('article.tribe-events-calendar-list__event')
    events = _events(soup)
    if not cards:
        empty = soup.select_one('.tribe-events-c-messages__message')
        if events or not empty or not re.search(r'no (?:upcoming )?events', _text(empty), re.I):
            raise ValueError('city_park_calendar_unverified')
        return []
    if len(cards) != len(events) or len(cards) > MAX_CITY_EVENTS_PER_PAGE:
        raise ValueError('city_park_incomplete_jsonld')
    by_url = {}
    for event in events:
        url = event.get('url')
        if not event_url(CITY_PARK, url) or url in by_url:
            raise ValueError('city_park_event_identity_conflict')
        by_url[url] = event
    result = []
    previous_start = None
    for card in cards:
        link = card.select_one('a.tribe-events-calendar-list__event-title-link[href]')
        clock_node = card.select_one('time.tribe-events-calendar-list__event-datetime[datetime]')
        event = by_url.pop(link.get('href'), None) if link else None
        if (not event or not clock_node or plain(event.get('name')) != _text(link)):
            raise ValueError('city_park_event_identity_conflict')
        day = date.fromisoformat(clock_node['datetime'])
        visible_clocks = re.findall(_CLOCK, _text(clock_node), flags=re.I)
        # The date-only cards render artificial 02:00 / 01:59:59 timestamps in
        # JSON-LD. Never interpret those as admission hours or expand the range.
        timed = bool(visible_clocks)
        if timed:
            start = _city_time(event.get('startDate'))
            end = _city_time(event.get('endDate'))
            if (len(visible_clocks) != 2 or start.date() != day or end <= start
                    or end - start >= timedelta(days=1)
                    or _clock(start.date(), visible_clocks[0]) != start
                    or _clock(end.date(), visible_clocks[1]) != end):
                raise ValueError('city_park_schedule_conflict')
        else:
            # Still validate chronology for pagination even when withholding an
            # all-day entry. Its visible start date is authoritative.
            raw_day = str(event.get('startDate', ''))[:10]
            if raw_day != day.isoformat():
                raise ValueError('city_park_schedule_conflict')
            start, end = timestamp(datetime.combine(day, datetime.min.time()), ZONE), None
        if previous_start and start < previous_start:
            raise ValueError('city_park_calendar_order_conflict')
        previous_start = start
        result.append((event, card, start, end, timed))
    if by_url:
        raise ValueError('city_park_incomplete_jsonld')
    return result


def _city_row(event, card, start, end):
    title, url = plain(event.get('name')), event['url']
    if urlsplit(url).path.split('/')[2] in _CITY_ORGANIZER_SERIES:
        return None
    raw_prose = html.unescape(event.get('description') or '')
    # TEC sometimes double-escapes a final newline after an HTML paragraph.
    prose = description(re.sub(r'(?:\\+n)+\s*$', '', raw_prose))
    if not prose:
        prose = description(str(card.select_one('.tribe-events-calendar-list__event-description') or ''))
    if (event.get('eventStatus') not in (None, 'https://schema.org/EventScheduled', 'http://schema.org/EventScheduled')
            or event.get('eventAttendanceMode') not in (
                None, 'https://schema.org/OfflineEventAttendanceMode', 'http://schema.org/OfflineEventAttendanceMode')
            or '/merry-maker-mixer/' in url
            or re.search(r'\b(?:invitation[- ]only|private event|sponsors? (?:only|are invited))\b', prose, re.I)):
        return None
    location = event.get('location')
    if not isinstance(location, dict) or not plain(location.get('name')):
        return None
    postal = location.get('address')
    if not isinstance(postal, (str, dict)):
        postal = ''
    city = plain(postal.get('addressLocality')) if isinstance(postal, dict) else ''
    identity = f'{urlsplit(url).path}:{start.strftime("%Y-%m-%dT%H:%M")}'
    facts = {'audience': 'Adults only'} if re.search(r'\badults[- ]only\b', prose, re.I) else None
    # Coordinates from the source catalog are not venue coordinates. The
    # shared geocoder receives this occurrence's own published address.
    return _row(CITY_PARK, title, start, end, plain(location.get('name')), address(postal),
                city, url, identity, prose, facts)


def _city(fetch, deadline_at, now):
    from roomquest.preview_worker import LOOKAHEAD_DAYS
    horizon = now + timedelta(days=LOOKAHEAD_DAYS)
    rows, seen = [], {}
    previous_start = None
    for number in range(1, MAX_CITY_PAGES + 1):
        url = SOURCES[CITY_PARK] if number == 1 else SOURCES[CITY_PARK] + f'list/page/{number}/'
        canonical = SOURCES[CITY_PARK] if number == 1 else SOURCES[CITY_PARK] + f'page/{number}/'
        soup = _page(fetch, url, canonical, deadline_at)
        events = _city_page(soup)
        next_links = {node.get('href') for node in soup.select('a.tribe-events-c-nav__next[href]')}
        expected_next = SOURCES[CITY_PARK] + f'list/page/{number + 1}/'
        if next_links and next_links != {expected_next}:
            raise ValueError('city_park_pagination_unverified')
        for event, card, start, end, timed in events:
            if previous_start and start < previous_start:
                raise ValueError('city_park_calendar_order_conflict')
            previous_start = start
            identity = (event['url'], start.isoformat())
            if identity in seen:
                if seen[identity] != event:
                    raise ValueError('city_park_duplicate_conflict')
                continue
            seen[identity] = event
            if timed and start <= horizon:
                row = _city_row(event, card, start, end)
                if row:
                    rows.append(row)
        _check_deadline(deadline_at)
        if not next_links or (events and events[-1][2] > horizon):
            return rows
        if not events:
            raise ValueError('city_park_empty_paginated_calendar')
    raise ValueError('city_park_incomplete_horizon')


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if (key not in SOURCES or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (SOURCES.get(key), 'html', 'html', ZONE)):
        raise ValueError('unregistered_gulf_seasonal_source')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('gulf_seasonal_now_timezone_missing')
    if key == NOLA:
        return _nola(_page(fetch, SOURCES[key], SOURCES[key], deadline_at))
    return _city(fetch, deadline_at, now)
