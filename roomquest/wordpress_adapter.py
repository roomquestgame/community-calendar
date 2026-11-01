"""Shared Events Calendar collection, independent of catalog provenance.

Uses the existing factual parser, SSRF/robots transport and downstream staging.
No venue search, source-wide pin, extra scheduler or provider identity change.
"""
from datetime import datetime, timedelta, timezone
import json
from time import monotonic
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

MAX_PAGES = 5
MAX_RECORDS = 500


def collect(source, fetch, *, deadline_at=None):
    from roomquest.mapsee_adapter import parse_tribe
    root = urlsplit(source['feed_url'])
    if '/wp-json/tribe/events/v1/events' in root.path:
        if root.path.rstrip('/').split('/wp-json/', 1)[1] != 'tribe/events/v1/events':
            raise ValueError('unsupported_wordpress_endpoint')
        path = root.path
    else:
        path = root.path.rstrip('/') + '/wp-json/tribe/events/v1/events'
    params = dict(parse_qsl(root.query, keep_blank_values=True))
    now = datetime.now(timezone.utc)
    params.update(per_page=100, start_date=now.date().isoformat(),
                  end_date=(now + timedelta(days=60)).date().isoformat())
    deadline = min(monotonic() + 35, deadline_at or float('inf'))
    rows = []
    for page in range(1, MAX_PAGES + 1):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        params['page'] = page
        payload = json.loads(fetch(urlunsplit((root.scheme, root.netloc, path,
                                               urlencode(params), '')), 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
            raise ValueError('unsupported_wordpress_payload')
        if len(payload['events']) > 100:
            raise ValueError('source_record_limit')
        # Never follow response next links; rebuild only this registered URL.
        rows.extend(parse_tribe(payload))
        if len(rows) > MAX_RECORDS:
            raise ValueError('source_record_limit')
        total_pages = payload.get('total_pages', 1)
        if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 0:
            raise ValueError('invalid_wordpress_pagination')
        if not payload.get('next_rest_url') and page >= total_pages:
            break
        if page == MAX_PAGES:
            raise ValueError('pagination_limit')
    unique = {}
    for row in rows:
        key = (row.get('id') or row['title'], row['starts_at'])
        if key in unique and any(unique[key].get(k) != row.get(k)
                                for k in ('title', 'venue_name', 'venue_address', 'lat', 'lng')):
            raise ValueError('conflicting_event_occurrence')
        unique[key] = row
    result = sorted(unique.values(), key=lambda e: (e['starts_at'], e['title']))
    if result and not any(e.get('venue_name') or e.get('venue_address') for e in result):
        raise ValueError('venue_extraction_unavailable')
    return result
