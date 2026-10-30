"""Shared ChamberMaster public-API intake over Udell's XML and ICS parsers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import monotonic
from urllib.parse import urlparse

from icalendar import Calendar

from roomquest.preview_worker import (
    PreviewError, _location, parse_growthzone_preview, fetch_publisher,
)

MAX_DETAILS = 20


def collect(source, payload, deadline_at, fetcher=fetch_publisher):
    """Require a complete bounded snapshot; never silently truncate a chamber."""
    if not source.get('source_key', '').startswith('municipal_chambermaster_'):
        raise PreviewError('unregistered_chambermaster_source')
    api = urlparse(source['feed_url'])
    if api.path != '/api/events' or api.query or api.fragment:
        raise PreviewError('invalid_chambermaster_api')
    records = parse_growthzone_preview(payload, source)
    if len(records) > MAX_DETAILS:
        raise PreviewError('chambermaster_detail_limit')
    def enrich(row):
        # The XML schedule is the complete event snapshot. ICS supplies optional
        # venue evidence: unavailable details must never erase valid timed events
        # or invent a map pin. Conflicting identity/time and robots denials fail.
        if monotonic() >= deadline_at:
            return {**row, 'reason': 'publisher_venue_details_unavailable'}
        detail = row['event_url'].replace('/events/details/', '/events/addtocalendar/') + '?format=ICal'
        try:
            raw = fetcher(detail, 'text/calendar', respect_robots=True, deadline_at=deadline_at)
        except PreviewError as exc:
            if str(exc) in {'source_network_error', 'source_fetch_deadline', 'publisher_rate_limited'}:
                return {**row, 'reason': 'publisher_venue_details_unavailable'}
            raise
        calendar = Calendar.from_ical(raw)
        matches = [event for event in calendar.walk('VEVENT')
                   if str(event.get('UID', '')).split('.')[-1] == row['id']]
        if len(matches) != 1:
            raise PreviewError('chambermaster_detail_identity')
        event = matches[0]
        start = event.decoded('DTSTART')
        if not isinstance(start, datetime) or start.tzinfo is None or start != datetime.fromisoformat(row['starts_at']):
            raise PreviewError('chambermaster_detail_time')
        if str(event.get('STATUS', '')).upper() in ('CANCELLED', 'CANCELED'):
            return None
        address = str(event.get('LOCATION', '')).strip()
        row['venue_address'] = address[:400]
        geo = event.get('GEO')
        name, lat, lng = _location(address, getattr(geo, 'latitude', None), getattr(geo, 'longitude', None))
        row.update(venue_name=name, lat=lat, lng=lng,
                   reason=None if lat is not None else 'missing_verified_venue_geo')
        return row
    # The shared transport still enforces the publisher's per-host crawl delay.
    # Three bounded in-flight responses avoid serial network latency consuming
    # the entire source deadline; request count and snapshot semantics stay fixed.
    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for row in pool.map(enrich, sorted(records, key=lambda x: (x['starts_at'], x['id'])))
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
