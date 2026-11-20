"""Evidence for recurring collections at the submitted URL."""
from collections import Counter
import json
import re
from hashlib import md5
from urllib.parse import urlsplit, parse_qsl, urlunsplit

from bs4 import BeautifulSoup

EVENT_LINK = re.compile(r'/(?:events?|shows?|performances?|concerts?)/(?:detail/)?[^/?#]+', re.I)


def source_key(url):
    return 'municipal_' + md5(('feed_registration:' + url).encode()).hexdigest()[:24]


def scoped_endpoint(listing, endpoint):
    # Keep all selectors including repeated values. A generic site subscription
    # on a filtered page may represent a different calendar.
    selectors = Counter(parse_qsl(urlsplit(listing).query, keep_blank_values=True))
    return selectors <= Counter(parse_qsl(urlsplit(endpoint).query, keep_blank_values=True))


def collection_evidence(url, body, obj=None):
    from roomquest.jsonld_adapter import parse as parse_jsonld
    from roomquest.squarespace import parse_registered
    if isinstance(obj, dict) and (isinstance(obj.get('upcoming'), list)
            or (isinstance(obj.get('items'), list) and isinstance(obj.get('collection'), dict)
                and any(isinstance(i, dict) and 'startDate' in i for i in obj['items']))):
        try:
            rows = parse_registered(obj, url)
        except (ValueError, TypeError, KeyError, OverflowError):
            rows = []
        if rows:
            return {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'squarespace'}
        return {'p_outcome': 'review', 'p_reason': 'squarespace_extraction_needed', 'p_type': 'squarespace'}
    html = obj is None
    soup = BeautifulSoup(body, 'html.parser') if html else None
    if html and soup.find('meta', attrs={'property': 'og:type', 'content': re.compile(r'^(?:event|event\.event)$', re.I)}):
        return {'p_outcome': 'review', 'p_reason': 'single_event_page', 'p_type': 'html'}
    blocks = soup.find_all('script', type=re.compile('^application/ld\\+json', re.I)) if html else []
    structured = bool(blocks) if html else isinstance(obj, (dict, list))
    if structured:
        try:
            rows = parse_jsonld(body, url)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError):
            rows = []
        links = {r['event_url'].split('#')[0] for r in rows if r.get('event_url')}
        if len(links) >= 2 and url.split('#')[0] not in links:
            return {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'jsonld'}
        if rows:
            reason = 'single_event_page' if links == {url.split('#')[0]} else 'collection_scope_unverified'
            return {'p_outcome': 'review', 'p_reason': reason, 'p_type': 'jsonld'}
    if html:
        hrefs = {a['href'].split('#')[0] for a in soup.select('a[href]') if EVENT_LINK.search(a['href'])}
        parts = urlsplit(url)
        if ('collection-type-events' in body.lower() and 'squarespace' in body.lower()
                and 'format' not in dict(parse_qsl(parts.query))):
            query = parts.query + ('&' if parts.query else '') + 'format=json'
            return {'p_outcome': 'discovered', 'p_type': 'squarespace',
                    'p_endpoint': urlunsplit(parts._replace(query=query))}
        path = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1].lower()
        if len(hrefs) >= 2 or path in {'events','calendar','shows','upcoming-events','event-calendar'}:
            return {'p_outcome': 'review', 'p_reason': 'html_adapter_needed', 'p_type': 'html'}
        if any('squarespace' in str(tag.get('src', '')).lower() for tag in soup.find_all('script', src=True)):
            return {'p_outcome': 'review', 'p_reason': 'squarespace_collection_unverified', 'p_type': 'squarespace'}
    return None


def probe(url, body, kind):
    """Use the same normalization as recurring collection before first activation."""
    from roomquest.ics_adapter import parse as parse_ical
    from roomquest.mapsee_adapter import parse_tribe
    try:
        if kind == 'ical':
            rows = parse_ical(body, {'url': url, 'source_key': source_key(url)}, legacy=True)
        elif kind == 'wordpress':
            rows = parse_tribe(json.loads(body), strict_public=True, retain_description=True)
        else:
            return True  # collection_evidence already ran the family parser
        return bool(rows)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return False
