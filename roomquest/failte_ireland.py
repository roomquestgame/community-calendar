"""The official Fáilte Ireland per-occurrence CSV, through normal Admin intake.

Only the exact published CSV endpoint is a source. Contact/booking URLs are
publisher-provided record evidence, never additional crawl targets. The
historical CKAN mirror is useful for schema fixtures but is not a source alias.
"""
from collections import Counter
import csv
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
import logging
import math
import re
from time import monotonic

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.registration_formats import source_key

URL = 'https://failteireland.azure-api.net/opendata-api/v2/events/csv'
HOST = 'failteireland.azure-api.net'
ZONE = 'Europe/Dublin'
VERSION = 'registered_failte_csv_v1'
ACCEPT = 'text/csv,text/plain;q=0.9'
MAX_BYTES = 3_000_000
MAX_ROWS = 10_000
MAX_EVENTS = 5_000
MAX_DESCRIPTION = 12_000
LOGGER = logging.getLogger(__name__)
FIELDS = ('Name', 'Event Type', 'Description', 'Contact URL', 'Booking URL',
          'Contact Phone Number', 'Booking Phone Number', 'Venue Name', 'Address',
          'County', 'Latitude', 'Longitude', 'Is Free To Visit', 'Price',
          'Start Date', 'End Date', 'Start Time', 'End Time', 'Recurring Dates')
COUNTIES = {'Carlow', 'Cavan', 'Clare', 'Cork', 'Donegal', 'Dublin', 'Galway',
            'Kerry', 'Kildare', 'Kilkenny', 'Laois', 'Leitrim', 'Limerick',
            'Longford', 'Louth', 'Mayo', 'Meath', 'Monaghan', 'Offaly',
            'Roscommon', 'Sligo', 'Tipperary', 'Waterford', 'Westmeath',
            'Wexford', 'Wicklow'}
IDENTITY_FIELDS = ('title', 'starts_at', 'ends_at', 'venue_name', 'venue_address',
                   'venue_city', 'lat', 'lng', 'event_url', 'timezone')
IMAGE_FIELDS = ('image_url', 'image_provenance', 'image_evidence_url')


def _fail(reason):
    raise ValueError('failte_' + reason)


def is_source(url):
    return url == URL


def registration_source():
    return {'feed_url': URL, 'source_key': source_key(URL), 'kind': 'json',
            'platform_adapter': 'jsonld', 'registered_native_content_version': 1,
            'timezone': ZONE}


def enabled(source):
    return (source.get('feed_url') == URL and source.get('source_key') == source_key(URL)
            and source.get('kind') == 'json' and source.get('platform_adapter') == 'jsonld'
            and type(source.get('registered_native_content_version')) is int
            and source['registered_native_content_version'] == 1
            and source.get('timezone') in (None, ZONE))


def validate_source(source):
    if not enabled(source):
        _fail('source_unregistered')


def event_url_allowed(value):
    from roomquest.registered_native_content import native_url
    return value != URL and native_url(value)


def _event_url(item):
    for field in ('Contact URL', 'Booking URL'):
        candidate = item[field].strip()
        if event_url_allowed(candidate):
            return candidate, field
    return None, None


def _identity(row):
    facts = {key: row.get(key) for key in IDENTITY_FIELDS}
    encoded = json.dumps(facts, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
    return 'failte:' + sha256(encoded.encode('utf-8')).hexdigest()[:40]


def _proof(row, source, url_field):
    return {'version': 1, 'source_key': source['source_key'], 'feed_url': URL,
            'adapter': 'jsonld', 'event_id': row['id'], 'event_url': row['event_url'],
            'description_field': 'Description' if row['description'] else None,
            'image_field': None, 'evidence_url': URL, 'extraction': VERSION,
            'event_url_field': url_field}


def validate_native(row, source):
    """Exact original-feed evidence, including the selected publisher URL field."""
    validate_source(source)
    from roomquest.registered_native_content import VERSION as native_version
    proof = row.get('registered_native_content') if isinstance(row, dict) else None
    field = proof.get('event_url_field') if isinstance(proof, dict) else None
    if (not isinstance(row, dict) or field not in ('Contact URL', 'Booking URL')
            or row.get('timezone') != ZONE or not event_url_allowed(row.get('event_url'))
            or not isinstance(row.get('description'), str)
            or len(row['description']) > MAX_DESCRIPTION or re.search(r'<[^>]+>', row['description'])
            or row.get('id') != _identity(row)
            or type(proof.get('version')) is not int
            or proof != _proof(row, source, field)
            or row.get('image_extractor_version') != native_version
            or any(row.get(key) is not None for key in IMAGE_FIELDS)):
        _fail('native_evidence_invalid')


def _date(value, *, optional=False):
    if optional and not value:
        return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T00:00:00)?', value):
        _fail('date_unverified')
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError('failte_date_unverified') from exc


def _time(value):
    if not value:
        return None
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?', value):
        _fail('time_unverified')
    return time.fromisoformat(value)


def _venue(item):
    county = plain(item['County'])
    if county not in COUNTIES:
        return None  # No inferred county or Northern Ireland attribution.
    name, street = plain(item['Venue Name']), plain(item['Address'])
    if not name or not street:
        return None
    if len(name) > 200 or len(street) > 350:
        _fail('venue_field_limit')
    # The exact reviewed source and explicit Republic of Ireland county are
    # country evidence; County is not mislabeled as a town/addressLocality.
    if not re.search(r'\b' + re.escape(county) + r'\b', street, re.I):
        street += ', ' + county
    if not re.search(r'\b(?:Ireland|Éire)\s*$', street, re.I):
        street += ', Ireland'
    lat, lng = item['Latitude'].strip(), item['Longitude'].strip()
    if bool(lat) != bool(lng):
        _fail('venue_geo_unverified')
    if lat:
        try:
            lat, lng = float(lat), float(lng)
        except ValueError as exc:
            raise ValueError('failte_venue_geo_unverified') from exc
        if not (math.isfinite(lat) and math.isfinite(lng)
                and 51.3 <= lat <= 55.5 and -10.8 <= lng <= -5.8):
            _fail('venue_geo_unverified')
    else:
        lat = lng = None
    return name, street, lat, lng


def parse(payload, source, *, deadline_at=None, diagnostics=None):
    validate_source(source)
    if not isinstance(payload, str) or len(payload.encode('utf-8')) > MAX_BYTES or '\x00' in payload:
        _fail('csv_payload_invalid')
    audit = diagnostics if diagnostics is not None else {}
    audit.update(rows=0, occurrences=0, omitted=[], warnings=[])
    from roomquest import preview_worker
    from roomquest.registered_native_content import VERSION as native_version
    now = preview_worker.datetime.now(timezone.utc)
    until = now + timedelta(days=preview_worker.LOOKAHEAD_DAYS)

    def deadline():
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')

    def omit(index, reason):
        audit['omitted'].append({'csv_record': index, 'reason': reason})

    deadline()
    reader = csv.reader(StringIO(payload.lstrip('\ufeff'), newline=''), strict=True)
    records = {}
    try:
        headers = next(reader, None)
        if not headers or len(headers) != len(FIELDS) or set(headers) != set(FIELDS):
            _fail('csv_schema_unverified')
        for values in reader:
            deadline()
            if not values or not any(value.strip() for value in values):
                continue
            audit['rows'] += 1
            index = audit['rows']
            if index > MAX_ROWS:
                _fail('csv_row_limit')
            if len(values) != len(headers):
                _fail('csv_row_unverified')
            item = dict(zip(headers, values))
            if item['Recurring Dates'].strip() not in ('Yes', 'No', ''):
                _fail('recurrence_field_unverified')
            # Recurring Dates is an informational flag. The publisher already
            # emits each occurrence as a separate row; never expand it again.
            first_day = _date(item['Start Date'].strip())
            last_day = _date(item['End Date'].strip(), optional=True)
            if last_day and last_day < first_day:
                _fail('end_date_conflict')
            first_clock = _time(item['Start Time'].strip())
            last_clock = _time(item['End Time'].strip())
            if first_clock is None:
                omit(index, 'missing_start_time')
                continue
            if last_clock and last_day is None:
                _fail('end_date_missing')
            first = timestamp(datetime.combine(first_day, first_clock), ZONE)
            last = timestamp(datetime.combine(last_day, last_clock), ZONE) if last_clock else None
            if last and last < first:
                _fail('end_time_conflict')
            if (last and last - first > timedelta(days=1)
                    or last is None and last_day and last_day != first_day):
                omit(index, 'multi_day_schedule_unresolved')
                continue
            if last == first:
                last = None
                audit['warnings'].append({'csv_record': index, 'reason': 'equal_end_time_omitted'})
            if first > until or first < now - timedelta(days=1) or first < now and (last is None or last < now):
                omit(index, 'outside_collection_window')
                continue
            name = plain(item['Name'])
            if not name or len(name) > 180:
                _fail('event_title_unverified')
            location = _venue(item)
            if location is None:
                omit(index, 'venue_or_jurisdiction_unresolved')
                continue
            link, url_field = _event_url(item)
            if link is None:
                omit(index, 'no_public_https_event_url')
                continue
            narrative = description(item['Description'], limit=MAX_DESCRIPTION + 1)
            if len(narrative) > MAX_DESCRIPTION:
                raise ValueError('registered_native_description_too_long')
            venue, street, lat, lng = location
            row = record(name, first, last, venue, street, '', link, 'pending',
                         plain(item['Event Type']), lat, lng, tz=ZONE, publisher_geo=True)
            if row is None:
                omit(index, 'outside_collection_window')
                continue
            row['timezone'] = ZONE
            row['id'] = _identity(row)
            row['description'] = narrative
            row['registered_native_content'] = _proof(row, source, url_field)
            row['image_extractor_version'] = native_version
            validate_native(row, source)
            identity = row['id'], row['starts_at']
            if identity in records and records[identity] != row:
                _fail('conflicting_occurrence')
            records[identity] = row
            if len(records) > MAX_EVENTS:
                _fail('occurrence_limit')
    except csv.Error as exc:
        raise ValueError('failte_csv_invalid') from exc
    deadline()
    audit['occurrences'] = len(records)
    LOGGER.info('Fáilte CSV complete: rows=%d occurrences=%d omitted=%s warnings=%s',
                audit['rows'], audit['occurrences'], dict(Counter(v['reason'] for v in audit['omitted'])),
                dict(Counter(v['reason'] for v in audit['warnings'])))
    return sorted(records.values(), key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, body=None, diagnostics=None):
    validate_source(source)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    payload = body if body is not None else fetch(URL, ACCEPT)
    return parse(payload, source, deadline_at=deadline_at, diagnostics=diagnostics)
