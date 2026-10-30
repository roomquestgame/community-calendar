"""Shared ChamberMaster public-API intake over Udell's XML and ICS parsers."""
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
    output = []
    for row in sorted(records, key=lambda x: (x['starts_at'], x['id'])):
        if monotonic() >= deadline_at:
            raise PreviewError('collection_deadline')
        detail = row['event_url'].replace('/events/details/', '/events/addtocalendar/') + '?format=ICal'
        calendar = Calendar.from_ical(fetcher(detail, 'text/calendar',
                                            respect_robots=True, deadline_at=deadline_at))
        matches = [event for event in calendar.walk('VEVENT')
                   if str(event.get('UID', '')).split('.')[-1] == row['id']]
        if len(matches) != 1:
            raise PreviewError('chambermaster_detail_identity')
        event = matches[0]
        start = event.decoded('DTSTART')
        if not isinstance(start, datetime) or start.tzinfo is None or start != datetime.fromisoformat(row['starts_at']):
            raise PreviewError('chambermaster_detail_time')
        if str(event.get('STATUS', '')).upper() in ('CANCELLED', 'CANCELED'):
            continue
        address = str(event.get('LOCATION', '')).strip()
        row['venue_address'] = address[:400]
        geo = event.get('GEO')
        name, lat, lng = _location(address, getattr(geo, 'latitude', None), getattr(geo, 'longitude', None))
        row.update(venue_name=name, lat=lat, lng=lng,
                   reason=None if lat is not None else 'missing_verified_venue_geo')
        output.append(row)
    return output


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
