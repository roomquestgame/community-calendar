"""Evidence for recurring collections at the submitted URL."""
from collections import Counter
from html.parser import HTMLParser
import json
import re
from hashlib import md5
from urllib.parse import urlsplit, parse_qsl, urlunsplit, urljoin, urldefrag

from bs4 import BeautifulSoup

EVENT_LINK = re.compile(r'/(?:events?|shows?|performances?|concerts?)/(?:detail/)?[^/?#]+', re.I)
MAX_DOCUMENT_PREFIX = 64 * 1024
XHTML_NAMESPACE = 'http://www.w3.org/1999/xhtml'
XML_ROOTS = {'rss', 'feed', 'rdf', 'urlset', 'sitemapindex', 'arrayofeventdisplay'}


class _DocumentRootFound(Exception):
    pass


class _DocumentStart(HTMLParser):
    """Read only lexical document identity, without a DOM or XML entities."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = None
        self.attributes = {}
        self.xml_declaration = False
        self.xml_doctype = False

    def handle_pi(self, data):
        parts = data.split(None, 1)
        self.xml_declaration |= bool(parts) and parts[0].rstrip('?').lower() == 'xml'

    def handle_decl(self, declaration):
        parts = declaration.split(None, 2)
        if len(parts) >= 2 and parts[0].lower() == 'doctype':
            self.xml_doctype |= parts[1].lower() != 'html'

    def handle_starttag(self, tag, attributes):
        self.root, self.attributes = tag, dict(attributes)
        raise _DocumentRootFound


def document_kind(payload):
    """Separate declared XML/feeds from HTML before generic calendar discovery.

    This bounded prefix check grants no parser/source capability. Known XML
    adapters keep their own validation; an HTML root keeps XHTML compatible.
    """
    if not isinstance(payload, str):
        return None
    prefix = payload[:MAX_DOCUMENT_PREFIX].lstrip('\ufeff \t\r\n')
    if prefix.startswith(('{', '[')):
        return 'json'
    if not prefix.startswith('<'):
        return None
    reader = _DocumentStart()
    try:
        reader.feed(prefix)
    except _DocumentRootFound:
        pass
    except (AssertionError, ValueError):
        return 'xml' if reader.xml_declaration or reader.xml_doctype else 'html'
    root = reader.root
    if root is None:
        return 'xml' if reader.xml_declaration or reader.xml_doctype else 'html'
    namespace = reader.attributes.get('xmlns')
    if (root == 'html' and not reader.xml_doctype
            and namespace in (None, '', XHTML_NAMESPACE)):
        return 'html'
    if (reader.xml_declaration or reader.xml_doctype or ':' in root
            or root in XML_ROOTS or namespace not in (None, '', XHTML_NAMESPACE)):
        return 'xml'
    # Undeclared custom roots may be ordinary HTML component/fragment wrappers.
    # Preserve that path; the existing collection checks still decide admission.
    return 'html'


def source_key(url):
    return 'municipal_' + md5(('feed_registration:' + url).encode()).hexdigest()[:24]


def scoped_endpoint(listing, endpoint):
    # Keep all selectors including repeated values. A generic site subscription
    # on a filtered page may represent a different calendar.
    selectors = Counter(parse_qsl(urlsplit(listing).query, keep_blank_values=True))
    return selectors <= Counter(parse_qsl(urlsplit(endpoint).query, keep_blank_values=True))


def extraction_hold(family, error):
    reason = str(error)
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,70}', reason):
        reason = family + '_extraction_needed'
    return {'p_outcome': 'review', 'p_reason': reason, 'p_type': family}


def provider_calendar_destination(url, page):
    """Find one advertised calendar after the caller identifies its provider.

    Registration fetches the destination and runs the provider collector.
    Keep selectors and do not widen a venue-specific path.
    """
    names = {'calendar', 'events', 'shows', 'whats-on', 'whatson',
             'upcoming-events', 'events-calendar', 'event-calendar', 'schedule'}
    base = urlsplit(url)
    segments = [part for part in base.path.split('/') if part]
    if segments and (len(segments) != 1 or segments[0].lower() not in names):
        return None
    targets = set()
    for node in BeautifulSoup(page, 'html.parser').select('a[href]'):
        target = urldefrag(urljoin(url, node['href'])).url
        parts = urlsplit(target)
        if (parts.scheme == 'https' and parts.netloc == base.netloc
                and not parts.username and not parts.password
                and parts.path.rstrip('/').rsplit('/', 1)[-1].lower() in names
                and scoped_endpoint(url, target) and target != url):
            targets.add(target)
    return next(iter(targets)) if len(targets) == 1 else None


def collection_evidence(url, body, obj=None):
    from roomquest.jsonld_adapter import parse as parse_jsonld
    from roomquest.squarespace import parse_registered
    if isinstance(obj, dict) and (isinstance(obj.get('upcoming'), list)
            or (isinstance(obj.get('items'), list) and isinstance(obj.get('collection'), dict)
                and any(isinstance(i, dict) and 'startDate' in i for i in obj['items']))):
        try:
            rows = parse_registered(obj, url)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return extraction_hold('squarespace', exc)
        if rows:
            return {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'squarespace'}
        return {'p_outcome': 'review', 'p_reason': 'no_extractable_events', 'p_type': 'squarespace'}
    html = obj is None and document_kind(body) != 'xml'
    soup = BeautifulSoup(body, 'html.parser') if html else None
    if html and soup.find('meta', attrs={'property': 'og:type', 'content': re.compile(r'^(?:event|event\.event)$', re.I)}):
        return {'p_outcome': 'review', 'p_reason': 'single_event_page', 'p_type': 'html'}
    if html:
        from roomquest.localist_registration import endpoint
        try:
            localist = endpoint(url, soup)
        except ValueError as exc:
            return extraction_hold('localist', exc)
        if localist:
            return {'p_outcome': 'discovered', 'p_type': 'localist', 'p_endpoint': localist}
        # Prefer the native collection to its possibly partial SEO JSON-LD.
        parts = urlsplit(url)
        if ('collection-type-events' in body.lower() and 'squarespace' in body.lower()
                and 'format' not in dict(parse_qsl(parts.query))):
            query = parts.query + ('&' if parts.query else '') + 'format=json'
            return {'p_outcome': 'discovered', 'p_type': 'squarespace',
                    'p_endpoint': urlunsplit(parts._replace(query=query))}
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
            reason = 'single_event_page' if url.split('#')[0] in links else 'collection_scope_unverified'
            return {'p_outcome': 'review', 'p_reason': reason, 'p_type': 'jsonld'}
    if html:
        hrefs = {a['href'].split('#')[0] for a in soup.select('a[href]') if EVENT_LINK.search(a['href'])}
        path = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1].lower()
        if len(hrefs) >= 2 or path in {'events','calendar','shows','upcoming-events','event-calendar'}:
            return {'p_outcome': 'review', 'p_reason': 'html_adapter_needed', 'p_type': 'html'}
        if any('squarespace' in str(tag.get('src', '')).lower() for tag in soup.find_all('script', src=True)):
            return {'p_outcome': 'review', 'p_reason': 'squarespace_collection_unverified', 'p_type': 'squarespace'}
    return None


def probe(url, body, kind):
    """Use the same normalization as recurring collection before first activation."""
    from roomquest.ics_adapter import parse as parse_ical
    from roomquest.mapsee_adapter import TRIBE_UTC_DEFAULT_ZONES, parse_tribe
    try:
        if kind == 'ical':
            rows = parse_ical(body, {'url': url, 'source_key': source_key(url)}, legacy=True)
        elif kind == 'wordpress':
            from roomquest.reviewed_venue_addresses import complete_tec_venues
            payload = complete_tec_venues(json.loads(body), {'url': url, 'source_key': source_key(url)})
            rows = parse_tribe(payload, strict_public=True, retain_description=True,
                               utc_default_zone=TRIBE_UTC_DEFAULT_ZONES.get(source_key(url)))
        else:
            return True  # collection_evidence already ran the family parser
        return bool(rows)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return False
