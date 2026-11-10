"""Read Discover Halifax's normal event window in durable bounded chunks.

``collect_chunk`` returns an explicit incomplete checkpoint. Only its completed
aggregate is suitable for the ordinary staging/certification path. All network
access, robots checks, pacing and persistence remain owned by the shared worker.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach, optional_description
from roomquest.publisher_schedule import earliest_published_time
from roomquest.reviewed_chambers import STREET_SUFFIX

KEY = 'discover_halifax_va'
URL = 'https://gohalifaxva.com/events/'
ZONE = 'America/New_York'
EVENT_URL = re.compile(r'https://gohalifaxva[.]com/directory/[a-z0-9]+(?:-[a-z0-9]+)*/')
PHOTO_URL = re.compile(r'https://gohalifaxva[.]com/site/wp-content/uploads/20[0-9]{2}/[01][0-9]/[A-Za-z0-9_.-]+[.](?:jpe?g|png|webp)', re.I)
_ADDRESS = re.compile(
    r'(?P<venue>.+?),\s*(?P<number>[0-9]{1,6})[,]?\s+(?P<street>[^,]+),\s*'
    r'(?P<city>[A-Za-z][A-Za-z .\x27-]+),\s*(?:[^,]+ County,\s*)?'
    r'(?:Virginia|VA),?\s+(?P<zip>\d{5})(?:, United States)?', re.I)
MAX_CARDS = 200
MAX_DETAILS_PER_CHUNK = 6
# Shared publisher transport allows one network request up to eighteen seconds.
# Do not begin another detail that can consume the checkpoint-write reserve.
MIN_DETAIL_SECONDS = 18
CHECKPOINT_VERSION = 1
MAX_CHECKPOINT_BYTES = 900_000
MAX_CHECKPOINT_AGE = timedelta(hours=4)
THE_LIGHT_EVENT = 'https://gohalifaxva.com/directory/still-life-drawing-at-the-light/'
THE_LIGHT_ADDRESS = '435 Main Street, South Boston, VA 24592'
FAIRE_EVENT = 'https://gohalifaxva.com/directory/12646/'
FAIRE_TICKETS = 'https://www.tickettailor.com/events/fbeconsultingandeventplanningllc/2345250'
log = logging.getLogger(__name__)


def _note(diagnostics, url, reason, *, disposition='held'):
    """Log bounded occurrence identities/reasons, never raw publisher payloads."""
    item = {'event_url': url, 'reason': reason, 'disposition': disposition}
    if diagnostics is not None:
        diagnostics.append(item)
    log.info('publisher_event_decision source=%s occurrence=%r disposition=%s reason=%s',
             KEY, url, disposition, reason)


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def _date(value):
    return datetime.strptime(value, '%B %d, %Y').date()


def _start(day, value):
    clock = datetime.strptime(value.upper(), '%I:%M %p').time()
    return timestamp(datetime.combine(day, clock), ZONE)


def _directory(payload, today):
    from roomquest.preview_worker import LOOKAHEAD_DAYS

    page = BeautifulSoup(payload, 'html.parser')
    count = page.select_one('.directorist-header-found-title span')
    cards = page.select('article.directorist-listing-single')
    if (not count or not _text(count).isdigit() or int(_text(count)) != len(cards)
            or not 0 <= len(cards) <= MAX_CARDS
            or page.select_one('.directorist-pagination, [rel="next"]')):
        raise ValueError('halifax_directory_incomplete')
    found, seen = [], set()
    for card in cards:
        link = card.select_one('.directorist-listing-title a[href]')
        url = link['href'] if link else ''
        if not EVENT_URL.fullmatch(url) or url in seen:
            raise ValueError('halifax_directory_event_identity')
        seen.add(url)
        day = _date(_text(card.select_one('.directorist-listing-card-date')))
        # Include the final local calendar day; the shared factual normalizer
        # applies the precise rolling 60-day timestamp boundary to each record.
        if today <= day <= today + timedelta(days=LOOKAHEAD_DAYS):
            found.append((url, _text(link), day, _text(card.select_one('.directorist-listing-card-time'))))
    # Publisher display order is not an identity or a reason to restart work.
    return sorted(found, key=lambda item: (item[2], item[0]))


def _detail(payload, url, title, day, clock, *, diagnostics=None):
    page = BeautifulSoup(payload, 'html.parser')
    canonical = page.select_one('link[rel="canonical"]')
    header = page.select_one('h1.directorist-listing-details__listing-title')
    if not canonical or canonical.get('href') != url or _text(header) != title:
        raise ValueError('halifax_directory_detail_identity')
    fields = {}
    for row in page.select('.directorist-single-info'):
        label = _text(row.select_one('.directorist-single-info__label__text'))
        value = _text(row.select_one('.directorist-single-info__value'))
        if label and value:
            if label in fields and fields[label] != value:
                raise ValueError('halifax_directory_detail_conflict')
            fields[label] = value
    if fields.get('Start Date') != day.strftime('%B %d, %Y').replace(' 0', ' '):
        _note(diagnostics, url, 'publisher_date_conflict')
        return None
    if not clock or not fields.get('Start Time'):
        _note(diagnostics, url, 'publisher_time_missing')
        return None
    listed_start, detail_start = _start(day, clock), _start(day, fields['Start Time'])
    start = earliest_published_time(listed_start, detail_start)
    if listed_start != detail_start:
        _note(diagnostics, url, 'earlier_published_start_selected', disposition='warning')
    # Owner decision in the South Hill continuation: for a matched occurrence with two explicit
    # published clocks choose the earlier one. In particular, the November 15
    # Woodbine market's current 11 a.m. listing/detail remain collectable even
    # though its flyer also advertises noon. No date/year is inferred here.
    detail = page.select_one('.directorist-card-general-section')
    description = _text(detail).removeprefix('Description ').strip()
    if re.search(r'\b(cancelled|canceled|postponed|online only|virtual only)\b', title+' '+description, re.I):
        _note(diagnostics, url, 'publisher_status_or_attendance_excluded', disposition='excluded')
        return None
    address = _ADDRESS.fullmatch(fields.get('Address', ''))
    if address and (address['city'].lower().endswith(' county')
                    or not re.search(r'\b' + STREET_SUFFIX + r'\b', address['street'], re.I)):
        address = None
    if address:
        venue, city = address['venue'], address['city']
        street = f"{address['number']} {address['street']}, {city}, VA {address['zip']}"
    elif _reviewed_light_venue(fields, url, day, clock, description):
        venue, city, street = 'The Light Spiritual Wellness', 'South Boston', THE_LIGHT_ADDRESS
    else:
        _note(diagnostics, url, 'event_address_unresolved')
        return None
    end = _start(_date(fields['End Date']) if fields.get('End Date') else day,
                 fields['End Time']) if fields.get('End Time') else None
    if end and not start < end <= start + timedelta(hours=24):
        _note(diagnostics, url, 'publisher_end_unverified', disposition='warning')
        end = None
    row = record(title, start, end, venue, street, city, url, url, retain_until_end=True)
    if row:
        row.update(description=optional_description(KEY, row['id'], description[:3000]),
                   attendance_mode='in_person')
        photos = {tag.get('content') for tag in page.select('meta[property="og:image"]')
                  if PHOTO_URL.fullmatch(tag.get('content', ''))}
        attach(row, KEY, candidate=next(iter(photos)) if len(photos) == 1 else None)
    else:
        _note(diagnostics, url, 'outside_shared_event_window', disposition='excluded')
    return row


def _reviewed_light_venue(fields, url, day, clock, description):
    """Complete only the exact reviewed occurrence's name-only venue.

    The venue's official contact page confirms its address, and its dated
    public event pages corroborate ZIP 24592. An explicit publisher street is
    never overwritten. This is not a default for other events or locations.
    """
    website = fields.get('Website', '').strip()
    if '://' not in website:
        website = 'https://' + website
    try:
        host = urlsplit(website)
        known_site = (host.scheme in ('http', 'https') and not host.username
                      and not host.password and host.port in (None, 80, 443)
                      and host.hostname in ('thelightspiritualwellness.com',
                                            'www.thelightspiritualwellness.com'))
    except ValueError:
        known_site = False
    return (url == THE_LIGHT_EVENT and day == date(2026, 11, 12)
            and clock.upper() == '6:00 PM' and fields.get('Start Time', '').upper() == '6:00 PM'
            and fields.get('End Time', '').upper() == '9:00 PM'
            and fields.get('Address') == 'The Light Spiritual Wellness' and known_site
            and not re.search(r'\b(?:off[ -]site|relocated|moved to|new location|venue:)\b', description, re.I))


def _reviewed_sessions(row, diagnostics):
    """Separate the two explicitly scheduled, separately admitted Nov 21 sessions."""
    if row['event_url'] != FAIRE_EVENT or row['starts_at'][:10] != '2026-11-21':
        return [row]
    prose = row.get('description', '')
    spans = (
        re.search(r'Renaissance Faire from\s+11:00\s*AM\s*[–—-]\s*5:00\s*PM', prose, re.I),
        re.search(r'Fantasy Ball from\s+7:00\s*PM\s*[–—-]\s*11:00\s*PM', prose, re.I),
    )
    day = date(2026, 11, 21)
    if (not all(spans) or row['starts_at'] != _start(day, '11:00 AM').astimezone(timezone.utc).isoformat()
            or row.get('ends_at') != _start(day, '11:00 PM').astimezone(timezone.utc).isoformat()
            or row.get('venue_name') != 'Woodbine Vineyards'
            or row.get('venue_address') != '1142 Hite Drive, Buffalo Springs, VA 24529'):
        _note(diagnostics, FAIRE_EVENT, 'reviewed_session_schedule_conflict')
        return []
    # Both session times are in the currently fetched tourism narrative. Age
    # restrictions are from the exact dated organizer ticket page reviewed in
    # this continuation; registration points back to that original evidence.
    faire_copy = re.search(r'(Spend the day\b.*?)(?=When the faire closes\b|Early Bird Tickets\b|$)', prose, re.I)
    ball_copy = re.search(r'(When the faire closes\b.*?)(?=Early Bird Tickets\b|$)', prose, re.I)
    faire_price = re.search(r'Renaissance Faire\s*\(11\s*AM\s*[–—-]\s*5\s*PM\)\s*:\s*\$[0-9]+(?:[.][0-9]{2})?', prose, re.I)
    ball_price = re.search(r'Fantasy Ball\s*\(7\s*PM\s*[–—-]\s*11\s*PM\)\s*:\s*\$[0-9]+(?:[.][0-9]{2})?', prose, re.I)
    sessions = (
        ('faire-20261121', 'Wine and Whimsey Renaissance Faire', '11:00 AM', '5:00 PM',
         'All ages; children 10 and under enter free with a ticketed adult.',
         faire_copy[1].strip() if faire_copy else 'Renaissance Faire, 11:00 AM–5:00 PM at Woodbine Vineyards.',
         faire_price[0] if faire_price else None),
        ('fantasy-ball-20261121', 'Wine and Whimsey Fantasy Ball', '7:00 PM', '11:00 PM',
         'Adults ages 18 and older.',
         ball_copy[1].strip() if ball_copy else 'Separately ticketed Fantasy Ball, 7:00 PM–11:00 PM at Woodbine Vineyards.',
         ball_price[0] if ball_price else None),
    )
    result = []
    for suffix, title, start, end, audience, description, price in sessions:
        if price:
            description += '\n\nEarly Bird Tickets: ' + price
        item = deepcopy(row)
        item.update(id=FAIRE_EVENT + '#' + suffix, title=title,
                    starts_at=_start(day, start).astimezone(timezone.utc).isoformat(),
                    ends_at=_start(day, end).astimezone(timezone.utc).isoformat(),
                    description=description + '\n\n' + audience + '\n\nRegistration: ' + FAIRE_TICKETS)
        item['publisher_details'] = {**item.get('publisher_details', {}),
                                     'audience': audience, 'registration': FAIRE_TICKETS}
        if price:
            item['publisher_details']['cost'] = 'Early Bird Tickets: ' + price
        result.append(item)
    return result


def _validate_source(source):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone'),
        source.get('kind'), source.get('platform_adapter')) != (KEY, URL, ZONE, 'html', 'html'):
        raise ValueError('unregistered_discover_halifax')


def _now(value=None):
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('halifax_now_timezone_missing')
    return current.astimezone(timezone.utc)


def _manifest(events):
    encoded = [[url, title, day.isoformat(), clock] for url, title, day, clock in events]
    return sha256(json.dumps(encoded, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _checkpoint(value, current):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('version')) is not int
            or value.get('version') != CHECKPOINT_VERSION
            or value.get('source_key') != KEY
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES
            or type(value.get('cursor')) is not int or not 0 <= value['cursor'] <= MAX_CARDS
            or type(value.get('manifest_count')) is not int
            or not value['cursor'] <= value['manifest_count'] <= MAX_CARDS
            or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('manifest_hash', '')))
            or not isinstance(value.get('events'), list) or len(value['events']) > MAX_CARDS + 1
            or not isinstance(value.get('diagnostics'), list) or len(value['diagnostics']) > MAX_CARDS * 2):
        raise ValueError('halifax_checkpoint_invalid')
    try:
        anchor = date.fromisoformat(value['window_start'])
        started = datetime.fromisoformat(value['started_at'])
        if started.tzinfo is None or anchor != started.astimezone(ZoneInfo(ZONE)).date():
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError('halifax_checkpoint_invalid') from None
    if current < started or current - started > MAX_CHECKPOINT_AGE:
        return None
    return deepcopy(value)


def _accounted_prefix(state, manifest):
    """A persisted cursor may only cover explicitly accepted or held details."""
    prefix = {url: day for url, _, day, _ in manifest[:state['cursor']]}
    accepted, accounted = {}, set()
    for item in state['events']:
        if not isinstance(item, dict) or item.get('event_url') not in prefix:
            raise ValueError('halifax_checkpoint_invalid')
        url, identity = item['event_url'], item.get('id')
        allowed = ({FAIRE_EVENT + '#faire-20261121', FAIRE_EVENT + '#fantasy-ball-20261121'}
                   if url == FAIRE_EVENT and prefix[url] == date(2026, 11, 21) else {url})
        if identity not in allowed or identity in accepted:
            raise ValueError('halifax_checkpoint_invalid')
        try:
            begins = datetime.fromisoformat(item['starts_at'])
            if (begins.tzinfo is None or begins.utcoffset() is None
                    or begins.astimezone(ZoneInfo(ZONE)).date() != prefix[url]):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError('halifax_checkpoint_invalid') from None
        accepted[identity] = url
        accounted.add(url)
    for item in state['diagnostics']:
        if (not isinstance(item, dict) or item.get('event_url') not in prefix
                or item.get('disposition') not in ('held', 'excluded', 'warning')
                or not isinstance(item.get('reason'), str)
                or not re.fullmatch(r'[a-z_]{3,100}', item['reason'])):
            raise ValueError('halifax_checkpoint_invalid')
        if item['disposition'] != 'warning':
            accounted.add(item['event_url'])
    if accounted != set(prefix):
        raise ValueError('halifax_checkpoint_invalid')
    split = {identity for identity, url in accepted.items() if url == FAIRE_EVENT}
    if (FAIRE_EVENT in prefix and prefix[FAIRE_EVENT] == date(2026, 11, 21) and split
            and split != {FAIRE_EVENT + '#faire-20261121', FAIRE_EVENT + '#fantasy-ball-20261121'}):
        raise ValueError('halifax_checkpoint_invalid')


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    """Advance a bounded complete-manifest snapshot without certifying a prefix.

    Persistence/revision checks belong to the caller. A transport/parser error
    propagates without returning a new checkpoint, leaving the last durable
    chunk intact. Each retry validates the listing before reusing cached rows.
    """
    _validate_source(source)
    current = _now(now)
    state = _checkpoint(checkpoint, current)
    anchor = date.fromisoformat(state['window_start']) if state else current.astimezone(ZoneInfo(ZONE)).date()
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    payload = fetch(URL, 'text/html')
    events = _directory(payload, anchor)
    digest = _manifest(events)
    if state is None or state['manifest_hash'] != digest or state['manifest_count'] != len(events):
        # Never mix facts from a removed/replaced listing with the new snapshot.
        anchor = current.astimezone(ZoneInfo(ZONE)).date()
        events = _directory(payload, anchor)
        state = {'version': CHECKPOINT_VERSION, 'source_key': KEY,
                 'started_at': current.isoformat(), 'window_start': anchor.isoformat(),
                 'manifest_hash': _manifest(events), 'manifest_count': len(events),
                 'cursor': 0, 'events': [], 'diagnostics': []}
    _accounted_prefix(state, events)
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    previous_cursor = state['cursor']
    stop = min(len(events), previous_cursor + limit)
    for offset in range(state['cursor'], stop):
        # Keep enough source budget for a normal bounded detail request and
        # durable progress write. The caller retains the ordinary finish reserve.
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        url, title, day, clock = events[offset]
        row = _detail(fetch(url, 'text/html'), url, title, day, clock,
                      diagnostics=state['diagnostics'])
        if row:
            state['events'].extend(_reviewed_sessions(row, state['diagnostics']))
        state['cursor'] = offset + 1
    if state['cursor'] == previous_cursor < len(events):
        # A slow listing must not cause an immediate zero-progress continuation
        # loop. Keep the prior durable checkpoint and use ordinary retry/backoff.
        raise ValueError('collection_deadline')
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError('halifax_checkpoint_size_limit')
    complete = state['cursor'] == len(events)
    return {'complete': complete, 'events': deepcopy(state['events']) if complete else [],
            'checkpoint': state}


def collect(source, fetch, *, deadline_at=None):
    """Read-only single-invocation audit; prefixes never masquerade as success."""
    _validate_source(source)
    today = datetime.now(ZoneInfo(ZONE)).date()
    events = _directory(fetch(URL, 'text/html'), today)
    result, diagnostics = [], []
    for url, title, day, clock in events:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if row := _detail(fetch(url, 'text/html'), url, title, day, clock, diagnostics=diagnostics):
            result.extend(_reviewed_sessions(row, diagnostics))
    return result


def collect_legacy(source, fetch, *, deadline_at=None):
    """Retain the old seven-day bound for claims without checkpoint support.

    This path makes no new RPC calls and does not widen an unfenced legacy
    invocation into a complete sixty-day snapshot. Expanded collection only
    runs through ``collect_chunk`` after an integer v1 backend capability.
    """
    _validate_source(source)
    today = datetime.now(ZoneInfo(ZONE)).date()
    events = [item for item in _directory(fetch(URL, 'text/html'), today)
              if item[2] < today + timedelta(days=7)]
    if len(events) > 18:
        raise ValueError('halifax_directory_detail_limit')
    result = []
    for url, title, day, clock in events:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if row := _detail(fetch(url, 'text/html'), url, title, day, clock):
            result.append(row)
    return result
