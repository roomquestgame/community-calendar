"""Publisher-advertised WordPress calendar capabilities, not an API URL guesser.

The registry recognises historical API generations without treating a website
CMS, ticketing widget, custom post type or an API route as a verified feed.
Only a real, GET-enabled TEC event collection can be offered to the existing
registered WordPress collector. Fetching and admission remain with the normal
robots-aware source registration pipeline.
"""
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

MAX_SCAN = 256_000
MAX_INDEX_CHARS = 2_000_000
MAX_ROUTES = 6_000
API_REL = 'https://api.w.org/'
PLUGIN_FINGERPRINTS = {
    'the-events-calendar': ('the-events-calendar', 'tribe-events'),
    'events-manager': ('events-manager', 'em-calendar'),
    'event-organiser': ('event-organiser', 'eo-event'),
    'modern-events-calendar': ('modern-events-calendar', 'mec-calendar'),
    'eventon': ('eventon', 'ajde_evcal'),
    'wp-event-manager': ('wp-event-manager', 'wpem-'),
    'all-in-one-event-calendar': ('all-in-one-event-calendar', 'ai1ec_'),
}
REST_PLUGIN_NAMESPACES = {
    'tribe/events/v1': 'the-events-calendar',
    'events-manager/v1': 'events-manager',
    'mec/v1.0': 'modern-events-calendar',
}
EVENT_ROUTE = re.compile(
    r'^/wp/v2/(?:events?|shows?|performances?|concerts?|workshops?|activities|programmes?)$', re.I)


class WordPressHead(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.roots = []
        self.alternates = []

    def handle_starttag(self, tag, pairs):
        if tag != 'link':
            return
        attrs = dict(pairs)
        rel = (attrs.get('rel') or '').split()
        href = attrs.get('href')
        if not href:
            return
        if API_REL in rel:
            self.roots.append(href)
        elif 'alternate' in rel and attrs.get('type', '').casefold() == 'application/json':
            self.alternates.append(href)


def _root_url(page_url, raw):
    """Keep only an actual publisher-advertised standard WordPress REST root."""
    try:
        page, candidate = urlsplit(page_url), urlsplit(urljoin(page_url, raw))
        if (page.scheme != 'https' or candidate.scheme != 'https'
                or candidate.netloc != page.netloc or candidate.username or candidate.password
                or candidate.fragment or len(candidate.geturl()) > 1000):
            return None
        params = parse_qsl(candidate.query, keep_blank_values=True)
        if candidate.path.rstrip('/').endswith('/wp-json') and not params:
            return urlunsplit((candidate.scheme, candidate.netloc,
                               candidate.path.rstrip('/') + '/', '', ''))
        if len(params) == 1 and params[0] == ('rest_route', '/'):
            return candidate.geturl()
    except (TypeError, ValueError):
        pass
    return None


def advertised_rest_root(page_url, html):
    """Discover a first-party WP REST root in HTML, not an invented /wp-json path."""
    if not isinstance(html, str) or not html.lstrip('\ufeff \t\r\n').startswith('<'):
        return None
    reader = WordPressHead()
    try:
        reader.feed(html[:MAX_SCAN])
    except (ValueError, AssertionError):
        return None
    roots = {_root_url(page_url, link) for link in reader.roots}
    return next(iter(roots)) if len(roots) == 1 and None not in roots else None


def wordpress_fingerprints(html):
    """Hints only: an HTML plugin stamp never makes its endpoint publishable."""
    if not isinstance(html, str):
        return ()
    body = (html[:MAX_SCAN] + html[-MAX_SCAN:]).casefold()
    # Wix serializes arbitrary collection text, slugs and component names into
    # large JSON script blocks.  Those values can coincidentally contain short
    # WordPress plugin tokens such as ``eo-event`` even though the publisher is
    # not running WordPress.  A native Wix bootstrap is stronger CMS evidence
    # than a substring inside that serialized data, so leave the page to the
    # Wix/HTML detectors instead of assigning a false WordPress adapter hold.
    wix_bootstrap = ('id="wix-warmup-data"' in body
                     or "id='wix-warmup-data'" in body
                     or ('id="wix-viewer-model"' in body
                         and 'static.wixstatic.com/' in body))
    if wix_bootstrap:
        return ()
    found = [name for name, markers in PLUGIN_FINGERPRINTS.items()
             if any(marker in body for marker in markers)]
    if re.search(r'[?&]json=(?:1|get_posts|get_recent_posts)\b|/api/core/get_posts/', body):
        found.append('legacy-json-api')
    return tuple(found)


def rest_route_url(api_root, route):
    """Append an explicitly published REST route, including old permalink mode."""
    if (not isinstance(route, str) or not re.fullmatch(r'/[a-zA-Z0-9_./-]{1,120}', route)
            or not isinstance(api_root, str)):
        return None
    try:
        parts = urlsplit(api_root)
        if parts.scheme != 'https' or parts.username or parts.password or parts.fragment:
            return None
        if parts.query:
            if parse_qsl(parts.query, keep_blank_values=True) != [('rest_route', '/')]:
                return None
            return urlunsplit((parts.scheme, parts.netloc, parts.path,
                               urlencode({'rest_route': route}, safe='/'), ''))
        if not parts.path.rstrip('/').endswith('/wp-json'):
            return None
        return urlunsplit((parts.scheme, parts.netloc,
                           parts.path.rstrip('/') + route, '', ''))
    except ValueError:
        return None


def _public_get(route_record):
    if not isinstance(route_record, dict):
        return False
    groups = route_record.get('endpoints')
    if not isinstance(groups, list):
        groups = [route_record]
    for group in groups[:20]:
        if not isinstance(group, dict):
            continue
        methods = group.get('methods', ())
        if isinstance(methods, dict):
            methods = tuple(methods)
        if isinstance(methods, (list, tuple, set)) and 'GET' in methods:
            return True
    return False


def inspect_rest_index(api_root, raw):
    """Describe observed APIs; only TEC can use the existing native adapter.

    A WordPress 4.4-4.6/oEmbed-only index, a custom post type, a MEC or Events
    Manager namespace, or a legacy JSON plugin is not itself a verified feed.
    """
    if not isinstance(raw, str) or len(raw) > MAX_INDEX_CHARS:
        return None
    try:
        index = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(index, dict):
        return None
    namespaces, routes = index.get('namespaces'), index.get('routes')
    if (not isinstance(namespaces, list) or not isinstance(routes, dict)
            or len(namespaces) > 200 or len(routes) > MAX_ROUTES
            or not all(isinstance(item, str) for item in namespaces)):
        return None
    ns = set(namespaces)
    families = {family for namespace, family in REST_PLUGIN_NAMESPACES.items()
                if namespace in ns}
    if any(namespace.startswith('eventon/') for namespace in ns):
        families.add('eventon')
    if any(namespace.startswith('wpem/') for namespace in ns):
        families.add('wp-event-manager')
    custom_routes = tuple(sorted(route for route, record in routes.items()
                                 if isinstance(route, str) and EVENT_ROUTE.fullmatch(route)
                                 and _public_get(record)))[:25]
    tec = '/tribe/events/v1/events'
    endpoint = (rest_route_url(api_root, tec) if tec in routes and 'tribe/events/v1' in ns
                and _public_get(routes[tec]) else None)
    return {
        'api_root': api_root,
        'rest_generation': ('core_wp_v2' if 'wp/v2' in ns else 'pre_core_or_restricted'),
        'plugin_families': tuple(sorted(families)),
        'custom_event_routes': custom_routes,
        'types_route': bool('wp/v2' in ns and '/wp/v2/types' in routes
                            and _public_get(routes['/wp/v2/types'])),
        'endpoint': endpoint,
        'collector': 'wordpress' if endpoint else None,
    }



def publisher_linked_ical_subscription(url):
    """Recognize documented WordPress *calendar-wide* exports when linked.

    This helper must be called only on real publisher <a>/<link> URLs. It
    never generates a candidate, fetches content or certifies events. The
    existing transport, source-scope, and ical parser own verification.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.username or parts.password or parts.fragment:
            return False
        path = [part.casefold() for part in parts.path.split('/') if part]
        params = parse_qsl(parts.query, keep_blank_values=True)
        keys = {key.casefold() for key, _ in params}
        if keys.intersection({'event_id','eventid','post_id','eid','tribe_event_id'}):
            return False
        if (not params and len(path) == 2 and path[0] in {
                'events', 'calendar', 'whatson', 'whats-on', 'event-calendar'}
                and path[1] == 'ical-feed'):
            return True
        # Timely All-in-One legacy public exporter: the three exact required
        # values identify an existing publisher-linked calendar export.
        actual = dict(params)
        return (
            actual.get('plugin') == 'all-in-one-event-calendar'
            and actual.get('controller') == 'ai1ec_exporter_controller'
            and actual.get('action') == 'export_events'
            and actual.get('no_html') in (None, 'true', '1')
            and keys <= {
                # Reject filtered (category/venue/single-event) exporters.
                # A partial export must not stand in for a full calendar.
                'plugin', 'controller', 'action', 'no_html'
            }
            and not (len(path)>2 or (path and path[-1] not in {
                'events', 'calendar', 'whatson', 'whats-on', 'event-calendar'}))
        )
    except (ValueError, TypeError):
        return False
