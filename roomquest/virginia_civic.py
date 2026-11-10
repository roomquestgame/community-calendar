"""Reviewed Virginia public calendars, with explicit publisher coverage limits.

The Commonwealth page exposes its current seven-day calendar in one response.
Its calendar-template links carry the publisher's dates, location and narrative;
we read these values locally and never request Google. DMV Connect permits its
default first page but forbids query/pagination routes in robots.txt. We collect
only that declared first-page scope and never infer cancellation from absence.
"""
from datetime import datetime, time, timedelta, timezone
import hashlib
import logging
import re
from time import monotonic
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
COMMONWEALTH = 'virginia_commonwealth_calendar'
DMV = 'virginia_dmv_connect'
SOURCES = {
    COMMONWEALTH: {
        'url': 'https://commonwealthcalendar.virginia.gov/',
        'hosts': ('commonwealthcalendar.virginia.gov',),
        'scope': 'publisher_current_seven_day_window',
    },
    DMV: {
        'url': 'https://www.dmv.virginia.gov/locations/dmv-connects',
        'hosts': ('www.dmv.virginia.gov',), 'scope': 'publisher_first_page',
    },
}
MAX_RECORDS = 500
MAX_DESCRIPTION = 2000
_LOG = logging.getLogger(__name__)
_CLOCK = re.compile(r'^(\d{1,2}):(\d{2})\s*([AP])\.?M\.?$', re.I)
_HOURS = re.compile(r'\bHours:\s*(\d{1,2}:\d{2}\s*[ap]\.?m\.?)\s*(?:to|–|-)\s*'
                    r'(\d{1,2}:\d{2}\s*[ap]\.?m\.?)', re.I)


def source_payload(key):
    return {'source_key': key, 'feed_url': SOURCES[key]['url'], 'kind': 'html',
            'platform_adapter': 'html', 'timezone': ZONE,
            'civic_contract_version': 1, 'civic_jurisdiction_id': 'us-va'}


def validate(source):
    key = source.get('source_key')
    if (key not in SOURCES or type(source.get('civic_contract_version')) is not int
            or any(source.get(k) != v for k, v in source_payload(key).items())):
        raise ValueError('unregistered_virginia_civic_source')
    return SOURCES[key]


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('timezone_unresolved')
    return value.astimezone(timezone.utc)


def _check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _metadata(url, current, valid_until, *, kind='meeting', topic='government', precision='timed'):
    return {'version': 1, 'kind': kind, 'topic': topic,
            'jurisdiction_id': 'us-va', 'jurisdiction_name': 'Virginia',
            'applicability': 'jurisdiction', 'source_url': url,
            'verified_at': current.isoformat(),
            'valid_until': valid_until,
            'time_precision': precision, 'timezone': ZONE}


def _text(node):
    return node.get_text(' ', strip=True) if node else ''


def _clock(value):
    match = _CLOCK.fullmatch(' '.join(value.split()))
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2]) > 59:
        raise ValueError('civic_event_time_unresolved')
    return time(int(match[1]) % 12 + (12 if match[3].upper() == 'P' else 0), int(match[2]))


def _date_row(title, day, ends_on, venue, url, identity, current):
    """Transport bounds only; civic date precision forbids a midnight event UI."""
    if ends_on <= day or (ends_on - day).days > 60:
        raise ValueError('invalid_civic_date_range')
    local_day = current.astimezone(ZoneInfo(ZONE)).date()
    if ends_on <= local_day or day > local_day + timedelta(days=60):
        return None
    begins = datetime.combine(day, time(), ZoneInfo(ZONE))
    ends = datetime.combine(ends_on, time(), ZoneInfo(ZONE))
    return {'id': identity, 'title': title[:180],
            'starts_at': begins.astimezone(timezone.utc).isoformat(),
            'ends_at': ends.astimezone(timezone.utc).isoformat(),
            'starts_on': day.isoformat(), 'ends_on': ends_on.isoformat(),
            'venue_name': venue[:400], 'venue_address': venue[:400], 'venue_city': '',
            'lat': None, 'lng': None, 'event_url': url,
            'category': 'Civic & Public Services', 'reason': 'missing_verified_venue_geo'}


def _hold(key, identity, error):
    reason = str(error)
    if not re.fullmatch(r'[a-z_]{3,100}', reason):
        reason = 'invalid_civic_record'
    _LOG.warning('virginia_civic_record_held source=%s id=%s reason=%s', key, identity, reason)


def _template(node):
    links = []
    for link in node.select('a[href]'):
        parsed = urlsplit(link['href'])
        if parsed.scheme == 'https' and parsed.netloc == 'calendar.google.com' and parsed.path == '/calendar/render':
            links.append(link['href'])
    if len(links) != 1:
        raise ValueError('commonwealth_template_missing')
    # Read the source attribute as data, not as a navigable Google URL. The
    # publisher leaves literal # room numbers and meeting links unescaped.
    query = links[0].split('?', 1)[1]
    # The publisher's template values sometimes contain literal ampersands.
    # Split the observed named boundaries, rather than losing narrative text
    # through a generic query parser. Ambiguous duplicate boundaries are held.
    for marker in ('&dates=', '&details=', '&location=', '&text='):
        if query.count(marker) != 1:
            raise ValueError('commonwealth_template_ambiguous')
    match = re.fullmatch(r'action=TEMPLATE&dates=(.*?)&details=(.*?)&location=(.*?)&text=(.*)', query, re.S)
    if not match:
        raise ValueError('commonwealth_template_invalid')
    dates, description, location, title = (unquote(value) for value in match.groups())
    return dates, plain(description), plain(location), plain(title)


def _template_stamp(value):
    if not re.fullmatch(r'\d{8}T\d{6}(?:\.\d+)?[+-]\d{2}:\d{2}', value):
        raise ValueError('commonwealth_event_date_invalid')
    result = datetime.fromisoformat(value)
    local = result.astimezone(ZoneInfo(ZONE))
    if local.replace(tzinfo=None) != result.replace(tzinfo=None):
        raise ValueError('commonwealth_timezone_conflict')
    return result


def parse_commonwealth(payload, *, now=None):
    current = _now(now)
    if not isinstance(payload, str) or len(payload) > 3_000_000:
        raise ValueError('invalid_commonwealth_payload')
    soup = BeautifulSoup(payload, 'html.parser')
    first = soup.select_one('input[name="START_DT"]')
    last = soup.select_one('input[name="END_DT"]')
    try:
        first_day = datetime.strptime(first['value'], '%m/%d/%Y').date()
        last_day = datetime.strptime(last['value'], '%m/%d/%Y').date()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('commonwealth_window_missing') from exc
    if not (first_day <= current.astimezone(ZoneInfo(ZONE)).date() <= last_day
            and 0 < (last_day - first_day).days <= 8):
        raise ValueError('commonwealth_window_stale')
    nodes = soup.select('.schedule__list__event')
    if len(nodes) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    if not nodes and not re.search(r'\bno (?:events|meetings)\b', _text(soup), re.I):
        raise ValueError('commonwealth_calendar_shape_changed')
    rows, held, seen = [], 0, set()
    for node in nodes:
        link = node.select_one('.schedule__event__title a[href]')
        href = link.get('href', '') if link else ''
        match = re.fullmatch(r'/Event/Details/([1-9]\d*)', href)
        if not match:
            raise ValueError('commonwealth_event_identity_invalid')
        identity = 'commonwealth:' + match[1]
        if identity in seen:
            raise ValueError('commonwealth_duplicate_identity')
        seen.add(identity)
        try:
            title = _text(link)
            if not title:
                raise ValueError('event_title_missing')
            dates, description, location, template_title = _template(node)
            if plain(title) != template_title:
                raise ValueError('commonwealth_event_title_conflict')
            pieces = dates.split('/')
            if len(pieces) != 2:
                raise ValueError('commonwealth_event_date_invalid')
            begins, ends = map(_template_stamp, pieces)
            if ends < begins:
                raise ValueError('invalid_event_end')
            day = begins.astimezone(ZoneInfo(ZONE)).date()
            if not first_day <= day <= last_day:
                raise ValueError('commonwealth_event_outside_window')
            displayed = [_text(part) for part in node.select('.schedule__event__datetime .schedule__event__time')]
            if not 2 <= len(displayed) <= 3 or displayed[0] != day.strftime('%b ') + str(day.day):
                raise ValueError('commonwealth_event_date_conflict')
            url = urljoin(SOURCES[COMMONWEALTH]['url'], href)
            display_time = ' '.join(displayed[1:])
            date_only = display_time.casefold() == 'all day'
            category = _text(node.select_one('.schedule__event__category'))
            if date_only and (category.casefold() == 'open meeting'
                              or re.search(r'\b(?:meetings?|public hearings?)\b', title, re.I)):
                # The publisher sometimes labels a meeting with unresolved
                # structured hours "All Day". Do not turn that into a service
                # window merely to avoid the meeting-time gate.
                raise ValueError('commonwealth_meeting_time_unresolved')
            status_text = _text(node.select_one('.schedule__event__status')).casefold()
            status = ('cancelled' if status_text in {'cancelled', 'canceled'} else
                      'postponed' if status_text == 'postponed' else 'scheduled')
            if status_text and status_text not in {'cancelled', 'canceled', 'postponed', 'scheduled'}:
                raise ValueError('commonwealth_event_status_unknown')
            if date_only:
                if begins.time().replace(tzinfo=None) != time() or ends.time().replace(tzinfo=None) != time():
                    raise ValueError('commonwealth_event_date_conflict')
                end_day = max(day + timedelta(days=1), ends.astimezone(ZoneInfo(ZONE)).date())
                row = _date_row(title, day, end_day, location, url, identity, current)
            else:
                shown_times = re.split(r'\s+(?:-|–)\s+', display_time)
                if not 1 <= len(shown_times) <= 2 or _clock(shown_times[0]) != begins.time().replace(tzinfo=None):
                    raise ValueError('commonwealth_event_time_conflict')
                if len(shown_times) == 2 and _clock(shown_times[1]) != ends.time().replace(tzinfo=None):
                    raise ValueError('commonwealth_event_time_conflict')
                if len(shown_times) == 1 and ends != begins:
                    raise ValueError('commonwealth_event_time_conflict')
                row = record(title, begins.isoformat(), ends.isoformat() if ends > begins else None,
                             location, location, '', url, identity, 'Civic & Public Services',
                             tz=ZONE, retain_until_end=True)
                if row is None and status in {'cancelled', 'postponed'}:
                    # An explicit status can still update a saved occurrence
                    # after its original start. The source's current bounded
                    # calendar, not an inferred absence, supplies this fact.
                    row = {'id': identity, 'title': title[:180],
                           'starts_at': begins.astimezone(timezone.utc).isoformat(),
                           'ends_at': ends.astimezone(timezone.utc).isoformat() if ends > begins else None,
                           'venue_name': location[:400], 'venue_address': location[:400],
                           'venue_city': '', 'lat': None, 'lng': None, 'event_url': url,
                           'category': 'Civic & Public Services', 'reason': 'missing_verified_venue_geo'}
            if row is None:
                continue
            sponsor = _text(node.select_one('.schedule__event__sponsor'))
            # A missing publisher end uses the app's internal visibility
            # cutoff only. The event's ends_at remains None.
            valid_until = row.get('ends_at') or (begins + timedelta(hours=3)).astimezone(timezone.utc).isoformat()
            row.update(description='\n\n'.join(x for x in (description, sponsor) if x)[:MAX_DESCRIPTION],
                       timezone=ZONE, publisher_categories=['Civic & Public Services', category],
                       publisher_status=status,
                       civic=_metadata(url, current, valid_until,
                                       kind='window' if date_only else 'meeting',
                                       precision='date' if date_only else 'timed'))
            rows.append(row)
        except (ValueError, TypeError, OverflowError) as exc:
            held += 1
            _hold(COMMONWEALTH, identity, exc)
    if held and not rows:
        raise ValueError('commonwealth_event_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def parse_dmv(payload, *, now=None):
    current = _now(now)
    if not isinstance(payload, str) or len(payload) > 3_000_000:
        raise ValueError('invalid_dmv_connect_payload')
    soup = BeautifulSoup(payload, 'html.parser')
    listing = soup.select_one('.c-view--connect-listing')
    if listing is None:
        raise ValueError('dmv_connect_calendar_shape_changed')
    nodes = listing.select('.c-connect-teaser')
    summary = _text(listing.select_one('.c-view__header'))
    count = re.fullmatch(r'Displaying 1\s*-\s*(\d+) of (\d+)', summary)
    if not nodes:
        if re.search(r'\bno (?:results|locations|events)\b', _text(listing), re.I):
            return []
        raise ValueError('dmv_connect_calendar_shape_changed')
    if not count or int(count[1]) != len(nodes) or int(count[2]) < len(nodes) or len(nodes) > 10:
        raise ValueError('dmv_connect_page_scope_changed')
    rows, held, seen = [], 0, set()
    for node in nodes:
        identity = 'dmv:unresolved'
        try:
            venue = _text(node.select_one('.c-connect-teaser__title'))
            address = _text(node.select_one('.c-connect-teaser__address'))
            available = re.sub(r'^Available:\s*', '', _text(node.select_one('.c-connect-teaser__dates')))
            day = datetime.strptime(available, '%B %d, %Y').date()
            body = _text(node.select_one('.c-connect-teaser__info'))
            if not venue or not address:
                raise ValueError('dmv_connect_venue_missing')
            if re.search(r'\b(?:not open to the public|private event|employees only)\b', body, re.I):
                continue
            matches = list(_HOURS.finditer(body))
            if len(matches) != 1:
                raise ValueError('dmv_connect_hours_unresolved')
            starts, ends = _clock(matches[0][1]), _clock(matches[0][2])
            if ends <= starts:
                raise ValueError('invalid_event_end')
            begins = timestamp(datetime.combine(day, starts).isoformat(), ZONE)
            finished = timestamp(datetime.combine(day, ends).isoformat(), ZONE)
            identity = 'dmv:' + hashlib.sha256((venue.casefold() + '|' + address.casefold() + '|' + day.isoformat()).encode()).hexdigest()[:32]
            if identity in seen:
                raise ValueError('dmv_connect_duplicate_identity')
            seen.add(identity)
            row = record('DMV Connect at ' + venue, begins.isoformat(), finished.isoformat(),
                         venue, address, '', SOURCES[DMV]['url'], identity,
                         'Civic & Public Services', tz=ZONE, retain_until_end=True)
            if row is None:
                continue
            row.update(description=body[:MAX_DESCRIPTION], timezone=ZONE,
                       publisher_categories=['Civic & Public Services', 'Public Services'],
                       civic=_metadata(SOURCES[DMV]['url'], current, row['ends_at'],
                                       kind='service', topic='public_services'))
            rows.append(row)
        except (ValueError, TypeError, OverflowError) as exc:
            held += 1
            _hold(DMV, identity, exc)
    if held and not rows:
        raise ValueError('dmv_connect_event_evidence_unavailable')
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    spec = validate(source)
    _check_deadline(deadline_at)
    payload = fetch(spec['url'], 'text/html')
    _check_deadline(deadline_at)
    result = (parse_commonwealth(payload, now=now) if source['source_key'] == COMMONWEALTH
              else parse_dmv(payload, now=now))
    _check_deadline(deadline_at)
    return result
