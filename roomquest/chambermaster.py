"""Shared ChamberMaster public-API intake over Udell's XML and ICS parsers."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime
from time import monotonic
from urllib.parse import urlparse

from icalendar import Calendar

from roomquest.preview_worker import (
    PreviewError, _location, parse_growthzone_preview, fetch_publisher,
)
from roomquest.incremental_snapshot import RevalidatedDetail, detail_request, utc_start

MAX_DETAILS = 20


def collect(source, payload, deadline_at, fetcher=fetch_publisher, *, retain_original=False):
    """Require a complete bounded snapshot; never silently truncate a chamber."""
    from roomquest.registration_formats import source_key
    if (not source.get('source_key', '').startswith('municipal_chambermaster_')
            and source.get('source_key') != source_key(source['feed_url'])):
        raise PreviewError('unregistered_chambermaster_source')
    api = urlparse(source['feed_url'])
    if api.path != '/api/events' or api.query or api.fragment:
        raise PreviewError('invalid_chambermaster_api')
    from roomquest.reviewed_chambers import SOURCES, collect as reviewed_collect
    if source.get('source_key') in SOURCES:
        return reviewed_collect(source, payload)
    records = parse_growthzone_preview(payload, source, retain_original=retain_original)
    if len(records) > MAX_DETAILS:
        raise PreviewError('chambermaster_detail_limit')
    def enrich(row):
        # The XML schedule is the complete event snapshot. ICS supplies optional
        # venue evidence: unavailable details must never erase valid timed events
        # or invent a map pin. Conflicting identity/time and robots denials fail.
        if monotonic() >= deadline_at:
            row.pop('collector_event_content_v1', None)
            return {**row, 'reason': 'publisher_venue_details_unavailable'}
        detail = row['event_url'].replace('/events/details/', '/events/addtocalendar/') + '?format=ICal'
        with detail_request(detail, 'text/calendar', row) as snapshot:
            try:
                raw = fetcher(detail, 'text/calendar', respect_robots=True, deadline_at=deadline_at)
            except PreviewError as exc:
                if str(exc) in {'source_network_error', 'source_fetch_deadline',
                                'publisher_rate_limited', 'publisher_pacing_deferred'}:
                    row.pop('collector_event_content_v1', None)
                    return {**row, 'reason': 'publisher_venue_details_unavailable'}
                raise
            if isinstance(raw, RevalidatedDetail):
                evidence = raw.evidence
            else:
                calendar = Calendar.from_ical(raw)
                matches = [event for event in calendar.walk('VEVENT')
                           if str(event.get('UID', '')).split('.')[-1] == row['id']]
                if len(matches) != 1:
                    raise PreviewError('chambermaster_detail_identity')
                event = matches[0]
                start = event.decoded('DTSTART')
                if not isinstance(start, datetime) or start.tzinfo is None or start != datetime.fromisoformat(row['starts_at']):
                    raise PreviewError('chambermaster_detail_time')
                address = str(event.get('LOCATION', '')).strip()
                geo = event.get('GEO')
                _, lat, lng = _location(address, getattr(geo, 'latitude', None), getattr(geo, 'longitude', None))
                evidence = {
                    'kind': 'chambermaster_ical_v1', 'id': row['id'],
                    'starts_at': utc_start(row['starts_at']),
                    'status': 'cancelled' if str(event.get('STATUS', '')).upper() in ('CANCELLED', 'CANCELED') else 'scheduled',
                    'venue_address': address[:400], 'lat': lat, 'lng': lng,
                }
            # A validated HTTP representation never bypasses the XML schedule's
            # identity/time checks or the normal venue-coordinate validation.
            if evidence['id'] != row['id']:
                raise PreviewError('chambermaster_detail_identity')
            if utc_start(evidence['starts_at']) != utc_start(row['starts_at']):
                raise PreviewError('chambermaster_detail_time')
            if snapshot is not None:
                snapshot.remember_detail(detail, 'text/calendar', evidence)
            if evidence['status'] == 'cancelled':
                return None
        address = evidence['venue_address']
        row['venue_address'] = address
        name, lat, lng = _location(address, evidence['lat'], evidence['lng'])
        row.update(venue_name=name, lat=lat, lng=lng,
                   reason=None if lat is not None else 'missing_verified_venue_geo')
        original = row.get('collector_event_content_v1')
        if original is not None:
            original['facts'].update(venue_address=address or None,
                                     source_latitude=lat, source_longitude=lng)
        return row
    # The shared transport still enforces the publisher's per-host crawl delay.
    # Three bounded in-flight responses avoid serial network latency consuming
    # the entire source deadline; request count and snapshot semantics stay fixed.
    with ThreadPoolExecutor(max_workers=3) as pool:
        # Each task needs its own Context, sharing only the bounded recorder and
        # pacing state. ContextVars do not propagate into executor threads.
        tasks = [(copy_context(), row) for row in sorted(records, key=lambda x: (x['starts_at'], x['id']))]
        return [row for row in pool.map(lambda task: task[0].run(enrich, task[1]), tasks)
                if row is not None]


def collect_batch():
    """Claim one chamber from the private DB registry; no request-supplied URLs."""
    from roomquest.preview_worker import supabase_rpc, _process_claimed_source
    sources = supabase_rpc('community_collector_claim_chambermaster', {'p_limit': 1}) or []
    if len(sources) > 1:
        raise PreviewError('invalid_chambermaster_batch')
    result = {'claimed': len(sources), 'complete': 0, 'failed': 0, 'staged': 0}
    for source in sources:
        if not source.get('source_key', '').startswith('municipal_chambermaster_'):
            raise PreviewError('invalid_chambermaster_batch')
        counts = _process_claimed_source(source, deadline_at=monotonic() + 44)
        for field in ('complete', 'failed', 'staged'):
            result[field] += counts[field]
    return result
