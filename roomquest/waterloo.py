"""Exact reviewed Waterloo public event index; original event facts only."""
from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record, plain, timestamp
from roomquest.publisher_evidence import attach, optional_description
from roomquest.mycountyparks import cancelled

KEY = 'experience_waterloo_ia'
FEED = 'https://experiencewaterloo.com/events/'
APP = 'EYQHJ2IY2M'
INDEX = 'prod-experience-waterloo-listings'
API_HOST = 'eyqhj2iy2m-dsn.algolia.net'


def parse_hits(hits, *, now=None):
    now = now or datetime.now(timezone.utc)
    rows = {}
    if not isinstance(hits, list) or len(hits) > 500:
        raise ValueError('publisher_record_limit')
    for e in hits:
        if not isinstance(e, dict):
            raise ValueError('publisher_payload_changed')
        if e.get('typeHandle') != 'event' or e.get('sectionHandle') != 'events':
            continue
        if e.get('isAllDay') is not False or e.get('isMultiDay') is not False:
            continue
        ident = str(e.get('id', ''))
        uri = e.get('uri', '')
        if not re.fullmatch(r'[1-9][0-9]{0,19}', ident) or not re.fullmatch(r'/[a-z0-9-]+/', uri):
            raise ValueError('publisher_identity_changed')
        if any(type(e.get(k)) is not int for k in ('startDate', 'endDate')):
            continue
        # This index encodes publisher wall-clock fields as UTC-shaped epochs.
        # Canonical pages confirm 18:35 means 18:35 Chicago, not 12:35.
        start, end = (timestamp(datetime.fromtimestamp(e[k], timezone.utc).replace(tzinfo=None).isoformat(),
                                'America/Chicago') for k in ('startDate', 'endDate'))
        if not start < end <= start + timedelta(hours=16) or end <= now or start >= now + timedelta(days=60):
            continue
        address = e.get('address')
        if not isinstance(address, list) or len(address) < 3 or not all(isinstance(v, str) for v in address):
            continue
        # Only a numbered street and explicit Iowa locality from this event.
        # Never pass the search index's unverified coordinates to publication.
        if not re.fullmatch(r'\d+[A-Za-z-]*\s+[^,]+', address[1].strip()) or not re.search(r',\s*IA(?:\s+\d{5})?$', address[-1].strip(), re.I):
            continue
        if '&' in address[1]:
            continue  # multi-venue attendance has no one verified pin
        description = plain(e.get('content') or e.get('snippet'))[:2000]
        title = plain(e.get('title'))
        if not title or cancelled(title, description):
            continue
        url = FEED.rstrip('/') + uri
        row = record(title, start.isoformat(), end.isoformat(), address[0],
                     ', '.join(value.strip() for value in address[1:]), address[-1].split(',')[0].strip(), url,
                     'waterloo:' + ident, tz='America/Chicago', retain_until_end=True)
        if not row:
            continue
        row['description'] = optional_description(KEY, row['id'], description)
        row['publisher_categories'] = [plain(x)[:100] for x in e.get('eventCategories', []) if isinstance(x, str)][:20]
        candidate = e.get('primaryImageUrl')
        # Accept only this publisher's original storage image; the sanitizer
        # may remove its numeric cache-version parameter, never an access token.
        row = attach(row, KEY, candidate=candidate)
        identity = (row['id'], row['starts_at'])
        if identity in rows and rows[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        rows[identity] = row
    return sorted(rows.values(), key=lambda r: (r['starts_at'], r['id']))


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key') != KEY or source.get('feed_url') != FEED
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone') != 'America/Chicago'):
        raise ValueError('unregistered_waterloo_source')
    deadline = min(monotonic() + 25, deadline_at or float('inf'))
    soup = BeautifulSoup(fetch(FEED, 'text/html'), 'html.parser')
    nodes = soup.select('[data-listings][data-info][data-config]')
    if len(nodes) != 1:
        raise ValueError('publisher_calendar_structure_changed')
    info, config = (json.loads(nodes[0][x]) for x in ('data-info', 'data-config'))
    if info.get('appId') != APP or info.get('index') != INDEX or not isinstance(info.get('apiKey'), str):
        raise ValueError('publisher_index_changed')
    key = info['apiKey']
    if not re.fullmatch(r'[A-Za-z0-9+/=]{20,1000}', key):
        raise ValueError('publisher_index_changed')
    filters = config.get('filters')
    if not isinstance(filters, str) or len(filters) > 2000 or not filters.startswith('calendarName:'):
        raise ValueError('publisher_index_changed')
    hits = []
    for page in range(5):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        params = {'query': '', 'hitsPerPage': 100, 'page': page, 'filters': filters,
                  'x-algolia-application-id': APP, 'x-algolia-api-key': key}
        data = json.loads(fetch('https://' + API_HOST + '/1/indexes/' + INDEX + '?' + urlencode(params), 'application/json'))
        pages = data.get('nbPages')
        if type(pages) is not int or not 0 <= pages <= 5 or not isinstance(data.get('hits'), list) or len(data['hits']) > 100:
            raise ValueError('publisher_pagination_limit')
        hits.extend(data['hits'])
        if page + 1 >= pages:
            return parse_hits(hits)
    raise ValueError('publisher_pagination_limit')
