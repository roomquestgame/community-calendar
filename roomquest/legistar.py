"""Bounded public Legistar meetings through RoomQuest's guarded transport.

Only the reviewed source tuples below are enabled.  This module does not use
the upstream CLI's curl, guessed meeting durations, or floating-time ICS.
"""
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record, timestamp

HOST = 'webapi.legistar.com'
MAX_PAGES = 5
PAGE_SIZE = 100
MAX_RECORDS = MAX_PAGES * PAGE_SIZE
LOOKAHEAD_DAYS = 60
ZONE = 'America/New_York'
SOURCES = {
    'richmond_va_legistar': {
        'url': 'https://webapi.legistar.com/v1/richmondva/events',
        'client': 'richmondva', 'jurisdiction_id': 'us-va-richmond-city',
        'jurisdiction_name': 'Richmond, Virginia', 'timezone': ZONE,
    },
    'alexandria_va_legistar': {
        'url': 'https://webapi.legistar.com/v1/alexandria/events',
        'client': 'alexandria', 'jurisdiction_id': 'us-va-alexandria-city',
        'jurisdiction_name': 'Alexandria, Virginia', 'timezone': ZONE,
    },
}
_LOG = logging.getLogger(__name__)
_TIME = re.compile(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', re.I)

# Exact publisher-named room aliases, independently documented at
# https://www.rva.gov/office-city-clerk/council-meetings (2026-11-09).
# Other rooms and all changed locations stay in the shared venue resolver.
_RICHMOND_COUNCIL_ROOM = 'council chamber, 2nd floor - city hall'


def source_payload(key):
    return {'source_key': key, 'feed_url': SOURCES[key]['url'], 'kind': 'json',
            'platform_adapter': 'legistar', 'timezone': SOURCES[key]['timezone'],
            'civic_contract_version': 1, 'civic_jurisdiction_id': SOURCES[key]['jurisdiction_id']}


def validate(source):
    key = source.get('source_key')
    if (key not in SOURCES or type(source.get('civic_contract_version')) is not int
            or any(source.get(k) != v for k, v in source_payload(key).items())):
        raise ValueError('unregistered_legistar_source')
    return SOURCES[key]


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('timezone_unresolved')
    return value.astimezone(timezone.utc)


def _check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _metadata(spec, url, current, valid_until):
    return {'version': 1, 'kind': 'meeting', 'topic': 'government',
            'jurisdiction_id': spec['jurisdiction_id'],
            'jurisdiction_name': spec['jurisdiction_name'],
            'applicability': 'jurisdiction', 'source_url': url,
            'verified_at': current.isoformat(),
            'valid_until': valid_until.astimezone(timezone.utc).isoformat(),
            'time_precision': 'timed', 'timezone': spec['timezone']}


def _event_url(value, spec):
    if not isinstance(value, str):
        raise ValueError('legistar_event_link_missing')
    url = urlsplit(value)
    if (url.scheme != 'https' or url.netloc.lower() != spec['client'] + '.legistar.com'
            or url.path.lower() != '/meetingdetail.aspx' or url.fragment):
        raise ValueError('legistar_event_link_mismatch')
    return value


def _start(item, zone):
    raw_date = item.get('EventDate')
    raw_time = item.get('EventTime')
    if not isinstance(raw_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?', raw_date):
        raise ValueError('legistar_event_date_invalid')
    if not isinstance(raw_time, str) or not (match := _TIME.fullmatch(' '.join(raw_time.split()))):
        raise ValueError('legistar_event_time_unresolved')
    hour, minute = int(match[1]), int(match[2])
    if not 1 <= hour <= 12 or minute > 59:
        raise ValueError('legistar_event_time_unresolved')
    hour = hour % 12 + (12 if match[3].upper() == 'PM' else 0)
    return timestamp(f'{raw_date[:10]}T{hour:02d}:{minute:02d}:00', zone)


def _identity(item, spec):
    event_id = item.get('EventId')
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        raise ValueError('legistar_event_identity_invalid')
    # EventId is stable inside its client database; avoid changing it on a
    # reschedule. The publisher GUID is retained as evidence when supplied.
    return f"legistar:{spec['client']}:{event_id}"


def parse_page(data, source, *, now=None):
    spec = validate(source)
    current = _now(now)
    if not isinstance(data, list) or len(data) > PAGE_SIZE:
        raise ValueError('invalid_legistar_payload')
    rows, held, seen = [], 0, set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError('invalid_legistar_payload')
        identity = _identity(item, spec)
        if identity in seen:
            raise ValueError('legistar_duplicate_identity')
        seen.add(identity)
        try:
            begins = _start(item, spec['timezone'])
            status = plain(item.get('EventAgendaStatusName')).casefold()
            status = 'cancelled' if status in {'cancelled', 'canceled'} else (
                'postponed' if status == 'postponed' else 'scheduled')
            if begins > current + timedelta(days=LOOKAHEAD_DAYS):
                continue
            if begins < current - timedelta(days=7):
                continue
            if not isinstance(item.get('EventBodyName'), str):
                raise ValueError('event_title_missing')
            title = plain(item['EventBodyName'])
            if not title:
                raise ValueError('event_title_missing')
            url = _event_url(item.get('EventInSiteURL'), spec)
            if item.get('EventLocation') is not None and not isinstance(item['EventLocation'], str):
                raise ValueError('legistar_event_location_invalid')
            if item.get('EventComment') is not None and not isinstance(item['EventComment'], str):
                raise ValueError('legistar_event_description_invalid')
            location = plain(item.get('EventLocation'))
            venue, address, city = location, location, ''
            alias = location.replace('–', '-').replace('—', '-').casefold()
            if spec['client'] == 'richmondva' and alias == _RICHMOND_COUNCIL_ROOM:
                address, city = '900 E. Broad Street, Richmond, VA 23219', 'Richmond'
            row = record(title, begins.isoformat(), None, venue, address, city, url,
                         identity, 'Civic & Public Services', tz=spec['timezone'],
                         retain_until_end=True)
            if row is None and status in {'cancelled', 'postponed'}:
                row = {'id': identity, 'title': title[:180],
                       'starts_at': begins.astimezone(timezone.utc).isoformat(), 'ends_at': None,
                       'venue_name': venue[:400], 'venue_address': address[:400],
                       'venue_city': city, 'lat': None, 'lng': None, 'event_url': url,
                       'category': 'Civic & Public Services', 'reason': 'missing_verified_venue_geo'}
            if row is None:
                continue
            parts = [plain(item.get('EventComment'))]
            agenda = item.get('EventAgendaFile')
            if isinstance(agenda, str):
                parsed = urlsplit(agenda)
                if (parsed.scheme == 'https' and not parsed.username and not parsed.password
                        and parsed.hostname in {'legistar.granicus.com', 'legistar2.granicus.com',
                                                spec['client'] + '.legistar.com'}):
                    parts.append('Agenda: ' + agenda)
            row.update(description='\n\n'.join(x for x in parts if x)[:2000],
                       timezone=spec['timezone'], publisher_categories=['Civic & Public Services', 'Public Meeting'],
                       # Internal app visibility cutoff only; the unknown
                       # publisher end remains None in the event contract.
                       publisher_status=status,
                       civic=_metadata(spec, url, current, begins + timedelta(hours=3)))
            rows.append(row)
        except (ValueError, TypeError, OverflowError) as exc:
            held += 1
            reason = str(exc)
            if not re.fullmatch(r'[a-z_]{3,100}', reason):
                reason = 'invalid_legistar_record'
            _LOG.warning('legistar_record_held source=%s id=%s reason=%s', source['source_key'], identity, reason)
    return rows, held


def collect(source, fetch, *, deadline_at=None, now=None):
    spec = validate(source)
    current = _now(now)
    local_date = current.astimezone(ZoneInfo(spec['timezone'])).date()
    rows, held, identities = [], 0, set()
    for page in range(MAX_PAGES):
        _check_deadline(deadline_at)
        params = {'$filter': f"EventDate ge datetime'{local_date - timedelta(days=7)}' and "
                            f"EventDate lt datetime'{local_date + timedelta(days=LOOKAHEAD_DAYS + 1)}'",
                  '$orderby': 'EventDate asc,EventId asc', '$top': PAGE_SIZE, '$skip': page * PAGE_SIZE}
        url = spec['url'] + '?' + urlencode(params, safe="$'")
        try:
            data = json.loads(fetch(url, 'application/json'))
        except json.JSONDecodeError as exc:
            raise ValueError('invalid_legistar_payload') from exc
        if not isinstance(data, list) or len(data) > PAGE_SIZE:
            raise ValueError('invalid_legistar_payload')
        for item in data:
            if not isinstance(item, dict):
                raise ValueError('invalid_legistar_payload')
            identity = _identity(item, spec)
            if identity in identities:
                raise ValueError('legistar_pagination_repeated')
            identities.add(identity)
        parsed, rejected = parse_page(data, source, now=current)
        rows.extend(parsed)
        held += rejected
        if len(data) < PAGE_SIZE:
            _check_deadline(deadline_at)
            if held and not rows:
                raise ValueError('legistar_event_evidence_unavailable')
            return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
    raise ValueError('legistar_pagination_limit')
