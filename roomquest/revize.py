"""Bounded Revize calendar JSON intake for the reviewed South Hill publisher.

The JSON is the complete array used by the town's public calendar. Recurrences
are expanded as local wall times, with explicit DST validation, before the
shared factual normalizer is called. No browser-generated ICS, event permalink,
publisher-office venue, photograph, or cancellation from absence is invented.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil.rrule import rruleset, rrulestr

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'south_hill_town_va'
CALENDAR = 'https://www.southhillva.gov/calendar.php'
FEED_URL = ('https://www.southhillva.gov/_assets_/plugins/revizeCalendar/'
            'calendar_data_handler.php?webspace=southhillva&relative_revize_url='
            '%2F%2Fcms2.revize.com&protocol=https%3A')
TIMEZONE = 'America/New_York'
MAX_RECORDS = 500
MAX_OCCURRENCES = 500
MAX_RECURRENCE_MASTERS = 50
MAX_RECURRENCE_STEPS = 10000
MAX_EXCEPTION_DATES = 500
MAX_SECONDS = 25
LOOKAHEAD_DAYS = 60
MAX_DURATION = timedelta(days=7)

# These are exact named-venue mappings, never a source's default address.
# The November 9, 2026 agenda independently confirms the temporary location:
# https://www.southhillva.gov/261109%20Regular_DRAFT.pdf?t=202611041628380
# The town identifies Centennial Park at /parks.php; the Chamber's official
# homepage identifies the same park at 225 E. Danville St for its park concert:
# https://www.southhillchamber.com/ (reviewed November 6, 2026).
REVIEWED_VENUES = {
    '111 e. danville st. (temporary location)': (
        '111 E. Danville St. (Temporary Location)',
        '111 E. Danville Street, South Hill, VA 23970', 'South Hill'),
    'centennial park': (
        'Centennial Park', '225 E. Danville St, South Hill, VA 23970', 'South Hill'),
}


class EventHold(ValueError):
    """A known event has unresolved facts; unrelated valid events may proceed."""


def _log(kind, **fields):
    print(json.dumps({'event': 'revize_' + kind, 'source_key': SOURCE_KEY,
                      **fields}, sort_keys=True), file=sys.stderr)


def _check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _text(value, field, *, limit=50000):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('invalid_revize_' + field)
    return value


def _narrative(value):
    soup = BeautifulSoup(unquote(_text(value, 'description')), 'html.parser')
    for node in soup.select('script, style, template, noscript, iframe, head'):
        node.decompose()
    return '\n'.join(line.strip() for line in soup.get_text('\n').splitlines()
                     if line.strip())[:2000]


def _local(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?', value):
        raise EventHold('event_time_missing')
    try:
        return timestamp(value, TIMEZONE).astimezone(ZoneInfo(TIMEZONE))
    except (ValueError, OverflowError) as exc:
        raise EventHold(str(exc)) from exc


def _wall(value):
    return value.astimezone(ZoneInfo(TIMEZONE)).replace(tzinfo=None)


def _wall_instant(value):
    # dateutil expands local wall times. Revalidate each occurrence; attaching a
    # ZoneInfo directly would silently select an ambiguous/nonexistent offset.
    return _local(value.isoformat(timespec='seconds'))


def _duration(item, start):
    end = _local(item['end']) if item.get('end') else None
    declared = item.get('duration')
    duration = None
    if declared not in (None, ''):
        if not isinstance(declared, str) or not re.fullmatch(r'\d{1,3}:[0-5]\d', declared):
            raise EventHold('invalid_event_duration')
        hours, minutes = map(int, declared.split(':'))
        duration = timedelta(hours=hours, minutes=minutes)
    if end is not None:
        span = _wall(end) - _wall(start)
        if duration is not None and duration != span:
            raise EventHold('publisher_schedule_conflict')
        duration = span
    if duration is None:
        raise EventHold('event_end_missing')
    if duration <= timedelta(0) or duration > MAX_DURATION:
        raise EventHold('invalid_event_end')
    return duration


def _rule_date(value):
    if not re.fullmatch(r'\d{8}T\d{6}Z?', value):
        raise ValueError('recurrence_invalid')
    try:
        dt = datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S')
        if value.endswith('Z'):
            dt = _wall(dt.replace(tzinfo=timezone.utc))
        return dt
    except ValueError as exc:
        raise ValueError('recurrence_invalid') from exc


def _rule_set(raw, start, horizon, deadline):
    raw = _text(raw, 'recurrence', limit=20000)
    result = rruleset()
    rule_count = date_count = start_count = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'(DTSTART|RRULE|RDATE|EXDATE)(?:;TZID=America/New_York)?:(.+)', line.strip())
        if not match:
            raise ValueError('recurrence_invalid')
        name, value = match.groups()
        if name == 'RRULE':
            rule_count += 1
            if rule_count > 1:
                raise ValueError('recurrence_invalid')
            fields = value.split(';')
            if any('=' not in field for field in fields):
                raise ValueError('recurrence_invalid')
            pairs = [field.split('=', 1) for field in fields]
            config = dict(pairs)
            if len(config) != len(pairs) or config.get('FREQ') not in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}:
                raise ValueError('unsupported_dense_recurrence')
            density = 1
            for key in ('BYSECOND', 'BYMINUTE', 'BYHOUR', 'BYDAY'):
                density *= len(config.get(key, '0').split(','))
            if density > 24:
                raise ValueError('unsupported_dense_recurrence')
            for field in ('INTERVAL', 'COUNT'):
                if field in config and not re.fullmatch(r'[1-9]\d{0,5}', config[field]):
                    raise ValueError('recurrence_invalid')
            if 'UNTIL' in config and 'COUNT' in config:
                raise ValueError('recurrence_invalid')
            count = int(config.pop('COUNT')) if 'COUNT' in config else None
            until = min(_rule_date(config['UNTIL']), _wall(horizon)) if 'UNTIL' in config else _wall(horizon)
            config['UNTIL'] = until.strftime('%Y%m%dT%H%M%S')
            if _wall(start) < _wall(horizon) - timedelta(days=366 * 50):
                raise ValueError('recurrence_expansion_limit')
            try:
                rule = rrulestr(';'.join(k + '=' + v for k, v in config.items()),
                               dtstart=_wall(start))
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError('recurrence_invalid') from exc
            # Bound the rule itself by the actual window, including impossible
            # combinations that otherwise search until year 9999 without ever
            # yielding. Apply COUNT before merging RDATEs, preserving its RFC
            # meaning without introducing COUNT+UNTIL into the publisher rule.
            for index, candidate in enumerate(rule, 1):
                _check_deadline(deadline)
                if count is not None and index > count:
                    break
                if index > MAX_RECURRENCE_STEPS:
                    raise ValueError('recurrence_expansion_limit')
                result.rdate(candidate)
        else:
            values = value.split(',')
            date_count += len(values)
            if date_count > MAX_EXCEPTION_DATES:
                raise ValueError('recurrence_record_limit')
            for part in values:
                parsed = _rule_date(part)
                if name == 'DTSTART':
                    start_count += 1
                    if start_count != 1 or parsed != _wall(start):
                        raise ValueError('publisher_schedule_conflict')
                elif name == 'RDATE':
                    result.rdate(parsed)
                else:
                    result.exdate(parsed)
    if rule_count != 1:
        raise ValueError('recurrence_invalid')
    return result


def _occurrences(item, start, duration, current, deadline):
    horizon = current + timedelta(days=LOOKAHEAD_DAYS)
    if not item.get('rrule'):
        candidates = (_wall(start),)
    else:
        candidates = _rule_set(item['rrule'], start, horizon, deadline)
    lower = _wall(current - duration)
    upper = _wall(horizon)
    result = []
    for scanned, wall in enumerate(candidates, 1):
        _check_deadline(deadline)
        if scanned > MAX_RECURRENCE_STEPS:
            raise ValueError('recurrence_expansion_limit')
        if wall > upper:
            break
        if wall < lower:
            continue
        begins = _wall_instant(wall)
        ends = _wall_instant(wall + duration)
        if ends <= begins:
            raise EventHold('invalid_event_end')
        if ends > current and begins <= horizon:
            result.append((begins, ends))
            if len(result) > MAX_OCCURRENCES:
                raise ValueError('source_record_limit')
    return result


def _venue(value):
    location = plain(_text(value, 'location', limit=2000))
    if re.search(r'\b(?:virtual|online|zoom|webinar)\b', location, re.I):
        raise EventHold('virtual_event')
    if matched := REVIEWED_VENUES.get(location.casefold()):
        return (*matched, 'reviewed_named_venue_address')
    # Other future events must carry their own full street/locality/state.
    locality = re.search(r',\s*([^,]+),\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?(?:,?\s+USA)?$', location)
    if not re.search(r'\b\d{1,6}\s+[A-Za-z]', location) or not locality:
        raise EventHold('event_venue_unreviewed')
    return location, location, locality[1].strip(), 'publisher_event_address_pending_geocode'


def _status(item):
    raw = item.get('status')
    if raw in (None, ''):
        return None
    if not isinstance(raw, str):
        raise ValueError('invalid_revize_status')
    status = raw.casefold()
    if status in ('cancelled', 'canceled'):
        return 'cancelled'
    if status in ('postponed', 'scheduled'):
        return status
    if status == 'confirmed':
        return 'scheduled'
    raise EventHold('unsupported_event_status')


def _status_row(title, begins, ends, venue, address, city, identity, category):
    """Exact status facts can update an existing occurrence without new venue.

    This is used only for positively cancelled/postponed rows whose exact start
    lies in the bounded status window. It never turns a past start into a future
    event or assigns the normalizer's optional three-hour ongoing fallback.
    """
    return {'id': identity, 'title': title[:180],
            'starts_at': begins.astimezone(timezone.utc).isoformat(),
            'ends_at': ends.astimezone(timezone.utc).isoformat() if ends else None,
            'venue_name': venue[:400], 'venue_address': address[:400], 'venue_city': city[:120],
            'lat': None, 'lng': None, 'event_url': CALENDAR,
            'category': category[:80], 'reason': 'missing_verified_venue_geo'}


def parse(payload, *, now=None, deadline_at=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('revize_now_timezone_missing')
    try:
        data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    except (ValueError, UnicodeError) as exc:
        raise ValueError('unsupported_revize_payload') from exc
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError('unsupported_revize_payload')
    if len(data) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    if sum(bool(item.get('rrule')) for item in data) > MAX_RECURRENCE_MASTERS:
        raise ValueError('recurrence_record_limit')
    records, seen, held, excluded = [], {}, 0, 0
    for item in data:
        _check_deadline(deadline_at)
        rid = item.get('id')
        if not isinstance(rid, str) or not re.fullmatch(r'[1-9]\d{0,11}', rid) or item.get('rid') != rid:
            raise ValueError('revize_event_identity_missing')
        title = plain(_text(item.get('title'), 'title', limit=2000))
        if not title:
            raise ValueError('event_title_missing')
        if rid in seen:
            if item != seen[rid]:
                raise ValueError('conflicting_event_identity')
            continue
        seen[rid] = item
        narrative = _narrative(item.get('desc'))
        # A closing notice is not an activity. Never turn omission into a
        # cancellation; backend limited-catalog semantics retain prior facts.
        if (str(item.get('status', '')).casefold() not in ('cancelled', 'canceled', 'postponed')
                and re.search(r'\b(?:closed|closure|closing\s+early|private\s+(?:event|party|function)|'
                              r'members?[\s-]+only|invitation[\s-]+only)\b', title + ' ' + narrative, re.I)):
            excluded += 1
            continue
        try:
            status = _status(item)
            if status is None and re.search(r'\b(?:cancelled|canceled|postponed)\b', title, re.I):
                raise EventHold('cancellation_requires_exact_status')
            start = _local(item.get('start'))
            if not isinstance(item.get('allDay', False), bool):
                raise ValueError('invalid_revize_all_day')
            if item.get('allDay'):
                if item.get('rrule') or current.date() <= start.date() <= (current + timedelta(days=LOOKAHEAD_DAYS)).date():
                    raise EventHold('unsupported_all_day_time')
                continue
            status_update = status in ('cancelled', 'postponed')
            if status_update and not item.get('rrule'):
                end = _local(item['end']) if item.get('end') else None
                if end is not None and end <= start:
                    raise EventHold('invalid_event_end')
                occurrences = ([(start, end)] if current - MAX_DURATION <= start <=
                               current + timedelta(days=LOOKAHEAD_DAYS) else [])
            else:
                duration = _duration(item, start)
                occurrences = _occurrences(item, start, duration, current, deadline_at)
            if not occurrences:
                continue
            try:
                venue, address, city, provenance = _venue(item.get('location'))
            except EventHold:
                if not status_update:
                    raise
                venue = plain(_text(item.get('location'), 'location', limit=2000))
                address = city = ''
                provenance = 'publisher_status_without_venue'
            category = plain(_text(item.get('primary_calendar_name'), 'category', limit=100))
            for begins, ends in occurrences:
                identity = 'revize:' + rid + '__' + begins.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                row = (_status_row(title, begins, ends, venue, address, city, identity, category)
                       if status_update else
                       record(title, begins.isoformat(), ends.isoformat(), venue, address,
                              city, CALENDAR, identity, category, tz=TIMEZONE,
                              retain_until_end=True))
                if row is None:
                    continue
                row.update(timezone=TIMEZONE, description=narrative,
                           publisher_categories=[category] if category else [],
                           location_provenance=provenance)
                if status:
                    row['publisher_status'] = status
                attach(row, SOURCE_KEY, facts={})
                records.append(row)
                if len(records) > MAX_OCCURRENCES:
                    raise ValueError('source_record_limit')
        except EventHold as exc:
            held += 1
            _log('event_held', identity='revize:' + rid, reason=str(exc))
    _log('normalized', upstream_records=len(data), held=held, excluded=excluded, records=len(records))
    if held and not records:
        raise ValueError('revize_event_evidence_unavailable')
    _check_deadline(deadline_at)
    return sorted(records, key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != FEED_URL
            or source.get('kind') != 'json' or source.get('platform_adapter') != 'revize'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_revize_source')
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    _check_deadline(deadline)
    payload = fetch(FEED_URL, 'application/json')
    _check_deadline(deadline)
    return parse(payload, now=now, deadline_at=deadline)
