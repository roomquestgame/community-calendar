"""Receive recurring Localist calendar and venue URLs through feed registration."""
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from roomquest.mapsee_adapter import MAX_PAGES, MAX_RECORDS, parse_localist
from roomquest.collection_window import localist_dates


def is_api(url):
    return urlsplit(url).path.rstrip('/') == '/api/2/events'


def endpoint(url, soup=None):
    parts = urlsplit(url)
    args = parse_qsl(parts.query, keep_blank_values=True)
    if is_api(url):
        # Only transport settings that describe the first page of our normal
        # 60-day collection can be removed without changing the scope.
        selectors = [(k, v) for k, v in args if (k, v) not in
                     {('page', '1'), ('days', '60'), ('pp', '50')}]
        if selectors and not (len(selectors) == 1 and selectors[0][0] == 'venue_id'
                              and re.fullmatch(r'[1-9]\d{0,17}', selectors[0][1])):
            raise ValueError('localist_filter_unverified')
    elif soup is not None:
        if not any(urlsplit(tag['src']).hostname == 'localist-images.azureedge.net'
                   for tag in soup.select('script[src]')):
            return None
        if parts.query:
            raise ValueError('localist_filter_unverified')
        selectors = []
        if parts.path not in ('', '/'):
            badges = soup.select('ul#share-buttons[class*="em-list-buttons-business_"]')
            ids = {m[1] for tag in badges for cls in tag.get('class', [])
                   if (m := re.fullmatch(r'em-list-buttons-business_([1-9]\d{0,17})', cls))}
            if len(ids) != 1:
                return None
            selectors = [('venue_id', ids.pop())]
    else:
        return None
    return urlunsplit((parts.scheme, parts.netloc, '/api/2/events', urlencode(selectors), ''))


def collect(url, fetch, *, retain_original=False):
    if not is_api(url) or endpoint(url) != url:
        raise ValueError('unregistered_localist_endpoint')
    venue = dict(parse_qsl(urlsplit(url).query)).get('venue_id')
    rows = {}
    seen = 0
    expected_total = None
    for page in range(1, MAX_PAGES + 1):
        target = url + ('&' if venue else '?') + urlencode({**localist_dates(), 'pp':50, 'page':page})
        data = json.loads(fetch(target, 'application/json'))
        meta = data.get('page') if isinstance(data, dict) else None
        if not isinstance(meta, dict) or meta.get('current') != page or type(meta.get('total')) is not int:
            raise ValueError('invalid_localist_pagination')
        if meta['total'] > MAX_PAGES:
            raise ValueError('pagination_limit')
        if expected_total is not None and expected_total != meta['total']:
            raise ValueError('localist_page_count_changed')
        expected_total = meta['total']
        events = data.get('events')
        if not isinstance(events, list) or len(events) > 50 or meta['total'] < 0:
            raise ValueError('invalid_localist_collection')
        if not events and (page != 1 or meta['total'] > 1):
            raise ValueError('invalid_localist_pagination')
        if events and meta['total'] < page:
            raise ValueError('invalid_localist_pagination')
        for wrapper in events:
            event = wrapper.get('event') if isinstance(wrapper, dict) else None
            if not isinstance(event, dict) or not isinstance(event.get('localist_url'), str) or not event.get('id'):
                raise ValueError('invalid_localist_collection')
            if venue and str(event.get('venue_id')) != venue:
                raise ValueError('localist_venue_filter_mismatch')
        seen += len(events)
        for row in parse_localist(data, registered=True, retain_original=retain_original):
            key = row['id']
            if key in rows and rows[key] != row:
                raise ValueError('conflicting_event_occurrence')
            rows[key] = row
        if len(rows) > MAX_RECORDS:
            raise ValueError('source_record_limit')
        if page >= meta['total']:
            if type(meta.get('total_items')) is int and seen != meta['total_items']:
                raise ValueError('invalid_localist_pagination')
            return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
    raise ValueError('pagination_limit')
