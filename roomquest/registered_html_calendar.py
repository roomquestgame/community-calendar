"""Bounded publisher listings whose linked details contain Event JSON-LD.

Registration and recurring collection use the same extractor. A listing is not
accepted merely because it links to one event: it must establish calendar scope,
and every selected detail must complete within the bounded snapshot. No guessed
URLs, browser execution, vendor venue facts, or partial-success prefix is used.
"""
from copy import deepcopy
from collections import Counter
from datetime import datetime
import json
import re
from time import monotonic
from urllib.parse import parse_qsl, urldefrag, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from roomquest import jsonld_adapter
from roomquest.registration_formats import document_kind, source_key

VERSION = 'registered_html_jsonld_v1'
CAPABILITY = 'registered_html_calendar_version'
MAX_HTML_BYTES = 3_000_000
MAX_DETAILS = 40
# Listing traversal stays all-or-nothing: a page beyond this cap remains a
# technical hold, never a truncated authoritative snapshot. Extend the
# complete-navigation headroom for standard WordPress archives without
# raising per-run detail fetches or the registration's 35-second deadline.
MAX_LISTING_PAGES = 8
MAX_NODES = 5000
MAX_EVENTS = 500

CALENDAR_NAMES = {
    'events', 'calendar', 'shows', 'concerts', 'performances', 'upcoming-events',
    'events-calendar', 'event-calendar', 'whats-on', 'whatson', 'schedule',
    'music-and-events',
}
INDEX_SEGMENTS = {
    'calendar', 'category', 'categories', 'tag', 'tags', 'page', 'month',
    'week', 'day', 'past', 'upcoming', 'all', 'venues', 'locations',
}
# Venue event sections vary by publisher. The collection path itself is
# not a detail; only a non-index child can be followed as a candidate.
DETAIL_PATH = re.compile(
    r'/(?:events?|shows?|performances?|concerts?|whats-on|whatson|live-events)/(.+)', re.I)
COLLECTION_HEADING = re.compile(
    r'^(?:(?:all|upcoming|our|current)\s+)?(?:events|shows|concerts|performances)'
    r'(?:\s+(?:calendar|schedule|listing))?$|^event calendar$|^what[’\']?s on$', re.I)
COLLECTION_SELECTOR = (
    '.view-indiecommerce-event-list, .upcoming-events, '
    '[itemtype="https://schema.org/ItemList"], '
    '[itemtype="http://schema.org/ItemList"]'
)
PAGINATION_LABEL = re.compile(
    r'^(?:next(?:\s+(?:page|month))?|(?:load|show|view|see)\s+more(?:\s+events)?'
    r'|more\s+(?:events|shows|performances)|older\s+events)\s*[›»→]*$', re.I)


def _fail(reason):
    raise ValueError(reason)


def _html(payload):
    if not isinstance(payload, str) or not payload.lstrip('\ufeff \t\r\n').startswith('<'):
        _fail('html_calendar_payload_invalid')
    if len(payload.encode('utf-8')) > MAX_HTML_BYTES:
        _fail('html_calendar_payload_limit')
    if document_kind(payload) == 'xml':
        _fail('html_calendar_payload_invalid')
    return BeautifulSoup(payload, 'html.parser')


def _public_url(value, base):
    from roomquest.registered_native_content import native_url
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        value = urldefrag(urljoin(base, value.strip())).url
        if not native_url(value) or urlsplit(value).hostname != urlsplit(base).hostname:
            return None
    except (ValueError, TypeError):
        return None
    return value


def _url_key(value):
    """Treat a trailing slash as equivalent; never erase a query selector."""
    parts = urlsplit(urldefrag(value).url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') or '/', parts.query, ''))


def _is_detail(value):
    match = DETAIL_PATH.search(urlsplit(value).path)
    if not match:
        return False
    pieces = [part.lower() for part in match[1].split('/') if part]
    if not pieces or pieces[0] in INDEX_SEGMENTS:
        return False
    # Published year/month calendar navigation is not an individual event.
    if all(re.fullmatch(r'\d{1,4}', part) for part in pieces):
        return False
    return True


def _event(node):
    return isinstance(node, dict) and any(
        kind.endswith('Event') or kind in {'Festival', 'Hackathon', 'CourseInstance', 'EventSeries'}
        for kind in jsonld_adapter.types(node))


def _document(payload):
    reader = jsonld_adapter.Blocks()
    reader.feed(payload)
    reader.close()
    if reader.active:
        _fail('html_calendar_jsonld_invalid')
    nodes = []

    def visit(value, depth=0):
        if depth > 30 or len(nodes) >= MAX_NODES:
            _fail('html_calendar_jsonld_limit')
        if isinstance(value, dict):
            nodes.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)

    visit(reader.blocks)
    return nodes


def _content(soup):
    return soup.find('main') or soup.find(attrs={'role': 'main'}) or soup.body or soup


def _navigation(node, root):
    return any(parent is not root and parent.name in {'header', 'footer', 'nav', 'aside', 'form'}
               for parent in node.parents)


def _links(url, soup):
    root = _content(soup)
    links = {}
    for anchor in root.select('a[href]'):
        if _navigation(anchor, root):
            continue
        link = _public_url(anchor.get('href'), url)
        if not link or _url_key(link) == _url_key(url):
            continue
        if _is_detail(link):
            links.setdefault(_url_key(link), link)
    # An ItemList's explicit item URLs are structured calendar links even when
    # the publisher does not use /event/ in its permalink paths.
    try:
        nodes = _document(str(soup))
    except (ValueError, TypeError, KeyError, RecursionError):
        nodes = []
    for node in nodes:
        if 'ItemList' not in jsonld_adapter.types(node):
            continue
        entries = node.get('itemListElement')
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item = entry.get('item', entry)
            raw = item if isinstance(item, str) else (
                item.get('url') or item.get('@id') if isinstance(item, dict) else None)
            link = _public_url(raw, url)
            if link and _url_key(link) != _url_key(url):
                links.setdefault(_url_key(link), link)
    return list(links.values())


def _single_page(url, soup):
    if _is_detail(url):
        return True
    if soup.find('meta', attrs={'property': 'og:type', 'content': re.compile(r'^event(?:\.event)?$', re.I)}):
        return True
    try:
        for node in _document(str(soup)):
            if _event(node):
                link = _public_url(node.get('url') or node.get('@id'), url)
                if link and _url_key(link) == _url_key(url):
                    return True
    except (ValueError, TypeError, KeyError, RecursionError):
        pass
    return False


def _calendar_destinations(url, soup):
    basename = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1].lower()
    if basename in CALENDAR_NAMES:
        return []
    links = {}
    for node in soup.select('a[href]'):
        link = _public_url(node.get('href'), url)
        if not link or _url_key(link) == _url_key(url):
            continue
        name = urlsplit(link).path.rstrip('/').rsplit('/', 1)[-1].lower()
        if name in CALENDAR_NAMES:
            links.setdefault(_url_key(link), link)
    return list(links.values())


def calendar_destination(url, body):
    """One actually linked full calendar can supersede homepage highlights.

    Query selectors remain distinct; two different calendar destinations are
    ambiguous. The caller fetches the returned URL under its normal same-host,
    robots and registration-deadline protections before considering acceptance.
    """
    try:
        if _public_url(url, url) != url:
            return None
        # A venue/subsite path may belong to a larger operator. Its navigation
        # can point at the operator-wide calendar and lose the venue's scope.
        if urlsplit(url).path not in ('', '/'):
            return None
        soup = _html(body)
        if _single_page(url, soup):
            return None
        links = _calendar_destinations(url, soup)
        return links[0] if len(links) == 1 else None
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def _listing_shape(url, soup, links, *, collection_url=None):
    if _single_page(url, soup):
        return False
    # A landing page may show only featured events. If it points to a separate
    # calendar, its visible highlights cannot certify the calendar's scope.
    if not collection_url and _calendar_destinations(url, soup):
        return False
    root = _content(soup)
    heading = any(COLLECTION_HEADING.fullmatch(node.get_text(' ', strip=True))
                  for node in root.select('h1,h2,h3') if not _navigation(node, root))
    basename = urlsplit(collection_url or url).path.rstrip('/').rsplit('/', 1)[-1].lower()
    collection = root.select_one(COLLECTION_SELECTOR) is not None
    if not collection:
        try:
            collection = any('ItemList' in jsonld_adapter.types(node)
                             for node in _document(str(soup)))
        except (ValueError, TypeError, KeyError, RecursionError):
            pass
    # A clear calendar path can contain one current event. A homepage must
    # explicitly show a calendar section with multiple distinct event details.
    return bool(links) and (
        collection or (basename in CALENDAR_NAMES and (heading or len(links) >= 2))
        or (heading and len(links) >= 2))


def supports_listing(url, body):
    """Read-only scope evidence; final acceptance still runs every detail."""
    from roomquest import forestry_england
    if forestry_england.owns_url(url):
        return forestry_england.supports_listing(url, body)
    try:
        if _public_url(url, url) != url:
            return False
        soup = _html(body)
        return _listing_shape(url, soup, _links(url, soup))
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def _page_in_scope(target, collection_url):
    """A published next link may change only an ordinary page selector."""
    if not target:
        return False
    base, page = urlsplit(collection_url), urlsplit(target)
    if (base.scheme, base.netloc) != (page.scheme, page.netloc):
        return False
    base_path = base.path.rstrip('/') or '/'
    page_path = page.path.rstrip('/') or '/'
    base_query = parse_qsl(base.query, keep_blank_values=True)
    page_query = parse_qsl(page.query, keep_blank_values=True)
    if page_path == base_path:
        keys = {'page', 'paged'}
        selectors = [(key, value) for key, value in page_query if key in keys]
        return (len(selectors) == 1 and re.fullmatch(r'[1-9][0-9]{0,4}', selectors[0][1]) is not None
                and Counter((k, v) for k, v in page_query if k not in keys)
                == Counter((k, v) for k, v in base_query if k not in keys))
    return (base_path.rsplit('/', 1)[-1].lower() in CALENDAR_NAMES
            and re.fullmatch(re.escape(base_path) + r'/page/[1-9][0-9]{0,4}', page_path) is not None
            and Counter(page_query) == Counter(base_query))


def _pagination(soup, url, *, collection_url=None, previous_pages=()):
    root = _content(soup)
    # A FacetWP template with an otherwise empty client-side pager can be
    # certified complete only when its publisher preload says there is exactly
    # one page and its rendered card count equals the full declared total.
    if root.select_one('#events-feed .facetwp-pager'):
        configs = []
        for script in soup.select('script'):
            raw = script.string or ''
            match = re.search(r'\b(?:window[.])?FWP_JSON\s*=\s*', raw)
            if match:
                try:
                    configs.append(json.JSONDecoder().raw_decode(raw[match.end():])[0])
                except (ValueError, TypeError):
                    _fail('html_calendar_pagination_needed')
        if len(configs) != 1 or not isinstance(configs[0], dict):
            _fail('html_calendar_pagination_needed')
        pager = configs[0].get('preload_data', {}).get('settings', {}).get('pager', {})
        visible = len(root.select('#events-feed .facetwp-template[data-name="events"] .excerpt-box'))
        if (not isinstance(pager, dict) or pager.get('page') != 1
                or pager.get('total_pages') != 1
                or type(pager.get('total_rows')) is not int
                or pager['total_rows'] != visible or not visible):
            _fail('html_calendar_pagination_needed')
    # FacetWP renders these controls client-side. A captured Swallow Hill page
    # had empty pager divs while its preload declared 45 rows over 5 pages; lack
    # of visible buttons does not make the initial 9 a complete calendar.
    if root.select_one('.facetwp-facet[data-type="pager"],.facetwp-type-pager'):
        _fail('html_calendar_pagination_needed')
    previous = {_url_key(page) for page in previous_pages}
    forward = {}
    required = set()
    for node in soup.select('a[rel],link[rel]'):
        rel = node.get('rel') or []
        if isinstance(rel, str):
            rel = rel.split()
        relations = {value.lower() for value in rel}
        if not {'next', 'prev'}.intersection(relations) or not node.get('href'):
            continue
        target = _public_url(node['href'], url)
        if 'prev' in relations:
            if not target or _url_key(target) not in previous:
                _fail('html_calendar_pagination_needed')
        if 'next' in relations:
            if not collection_url:
                _fail('html_calendar_pagination_needed')
            if target and _url_key(target) in previous | {_url_key(url)}:
                _fail('html_calendar_pagination_cycle')
            if not _page_in_scope(target, collection_url):
                _fail('html_calendar_pagination_scope_conflict')
            forward.setdefault(_url_key(target), target)
    if len(forward) > 1:
        _fail('html_calendar_pagination_ambiguous')
    # Only a real numbered pagination navigation with exactly one declared
    # current page can identify a next-page URL without rel=next.
    for pager in root.select('nav.pagination,nav[aria-label*="pagination" i]'):
        active = pager.select('[aria-current="page"]')
        if not active:
            # An unlinked numbered span within a genuine numbered pager may
            # identify the current page, unlike a random nav number.
            active = [node for node in pager.select('.pagination > li > span')
                      if node.get_text(' ', strip=True).isdigit()]
        if len(active) != 1 or not active[0].get_text(' ', strip=True).isdigit():
            continue
        current_number = int(active[0].get_text(' ', strip=True))
        if current_number != len(previous_pages) + 1:
            _fail('html_calendar_pagination_scope_conflict')
        next_links = []
        for node in pager.select('a[href]'):
            label = node.get_text(' ', strip=True)
            if label.isdigit() and int(label) == current_number + 1:
                target = _public_url(node['href'], url)
                if not target or not collection_url or not _page_in_scope(target, collection_url):
                    _fail('html_calendar_pagination_scope_conflict')
                next_links.append(target)
        if len(set(next_links)) > 1:
            _fail('html_calendar_pagination_ambiguous')
        if next_links:
            forward.setdefault(_url_key(next_links[0]), next_links[0])
    if len(forward) > 1:
        _fail('html_calendar_pagination_ambiguous')
    for node in root.select('a[href],button,[role="button"]'):
        label = node.get('aria-label') or node.get_text(' ', strip=True)
        classes = ' '.join(node.get('class') or [])
        marker = classes + ' ' + str(node.get('id') or '')
        target = _public_url(node.get('href'), url)
        supported = bool(target and _url_key(target) in forward)
        disabled = node.has_attr('disabled') or node.get('aria-disabled') == 'true'
        dynamic_more = (re.search(r'load[-_]?more|show[-_]?more', marker, re.I)
                        or node.has_attr('data-offset') and PAGINATION_LABEL.fullmatch(label.strip()))
        # Carbonhouse initially disables its offset-backed Load More button
        # while JavaScript initializes. Disabled does not prove the final page.
        if dynamic_more and (disabled or not supported):
            _fail('html_calendar_pagination_needed')
        if disabled:
            continue
        pagination = any(re.search(r'\b(?:pagination|pager)\b', ' '.join(parent.get('class') or []), re.I)
                         for parent in node.parents if getattr(parent, 'attrs', None))
        if (PAGINATION_LABEL.fullmatch(label.strip()) and (not _navigation(node, root) or pagination)
                or re.search(r'(?:load[-_]?more|show[-_]?more)', classes, re.I)):
            if not supported:
                _fail('html_calendar_pagination_needed')
        if pagination and node.get('aria-current') != 'page':
            if not node.get('href') or not target:
                _fail('html_calendar_pagination_needed')
            # Treat /events?page=1 as the publisher's already visited
            # canonical /events root, preserving all original query selectors.
            first_page = urlsplit(collection_url or '')
            candidate_page = urlsplit(target)
            if (collection_url and _url_key(collection_url) in previous
                    and candidate_page.scheme == first_page.scheme
                    and candidate_page.netloc == first_page.netloc
                    and candidate_page.path.rstrip('/') == first_page.path.rstrip('/')
                    and Counter((k, v) for k, v in parse_qsl(candidate_page.query)
                                if k != 'page') == Counter(parse_qsl(first_page.query))
                    and [v for k, v in parse_qsl(candidate_page.query) if k == 'page'] == ['1']):
                continue
            if _url_key(target) not in previous | {_url_key(url)}:
                if not collection_url or not _page_in_scope(target, collection_url):
                    _fail('html_calendar_pagination_needed')
                required.add(_url_key(target))
    return next(iter(forward.values()), None), required


def _rockhouse_archive(url, soup):
    """Recognize the complete, unfiltered Rockhouse archive List widget.

    Reviewed public frontend dependencies on 2026-11-22 use `rhp_paged` for
    this widget; search-suggestion pagination and WordPress SEO head links are
    separate. The captured native archive is fully rendered, with explicit
    month/year groups and no widget pager/loader. Ignore document-level SEO
    pagination only while every part of this narrow platform contract holds.
    """
    if not soup.select_one('#isEventsArchivePage,#rhp-events-pg-template,.generalView .rhpSingleEvent'):
        return None

    def invalid():
        _fail('html_calendar_rockhouse_scope_unverified')

    parsed = urlsplit(url)
    flags = soup.select('input#isEventsArchivePage')
    widgets = soup.select('#rhp-events-pg-template')
    canonical = soup.select('link[rel="canonical"]')
    if (parsed.path.rstrip('/') != '/events' or parsed.query
            or len(flags) != 1 or flags[0].get('value', '').casefold() != 'true'
            or len(widgets) != 1 or len(canonical) != 1
            or not (target := _public_url(canonical[0].get('href'), url))
            or _url_key(target) != _url_key(url)):
        invalid()
    widget = widgets[0]
    views = widget.select('.generalView')
    if len(views) != 1:
        invalid()
    for selector in ('.eventDesktopView', '.eventMobileView'):
        values = widget.select(selector)
        if len(values) != 1 or values[0].get('value', '').casefold() != 'list':
            invalid()
    filters = widget.select('.filterValInput,#rhpSearchText,#rhp_bar_rhp_gen,#rhp_bar_rhp_month,'
                            '#rhp_bar_rhp_venue,#rhp_bar_rhp_performer,#rhp-bar-just-announced,'
                            '#rhp-bar-feature')
    if not filters or any(node.get('value') not in ('', '0') for node in filters):
        invalid()
    search = widget.select('#rhp_bar_search_box')
    if len(search) != 1 or search[0].get('value', ''):
        invalid()
    if widget.select_one('[name="rhp_paged"],#rhp_paged'):
        _fail('html_calendar_pagination_needed')
    # Default checkbox attributes are cleared by the reviewed frontend before
    # applying query filters; the hidden values and empty URL query own scope.
    for node in widget.select('a[href]'):
        if any(key == 'rhp_paged' for key, _ in parse_qsl(urlsplit(node['href']).query)):
            _fail('html_calendar_pagination_needed')
    for node in widget.find_all(True):
        marker = ' '.join(node.get('class') or []) + ' ' + str(node.get('id') or '')
        if re.search(r'pagination|pager|load[-_]?more|infinite', marker, re.I):
            _fail('html_calendar_pagination_needed')

    from roomquest.mapsee_adapter import plain
    current_month = None
    links = {}
    cards = []
    for node in views[0].children:
        if not getattr(node, 'name', None):
            continue
        classes = node.get('class') or []
        if 'rhp-events-list-separator-month' in classes:
            try:
                current_month = datetime.strptime(plain(node.get_text(' ', strip=True)), '%B %Y')
            except ValueError:
                invalid()
        elif 'rhpSingleEvent' in classes:
            cards.append(node)
            titles = node.select('a#eventTitle[href]')
            dates = node.select('.singleEventDate')
            if current_month is None or len(titles) != 1 or len(dates) != 1:
                invalid()
            link = _public_url(titles[0]['href'], url)
            if not link or not _is_detail(link):
                invalid()
            label = plain(dates[0].get_text(' ', strip=True))
            try:
                day = datetime.strptime(label + ' ' + str(current_month.year), '%a, %b %d %Y')
                if (day.month != current_month.month
                        or day.strftime('%a').casefold() != label.split(',')[0].casefold()):
                    invalid()
            except ValueError:
                invalid()
            identity = _url_key(link)
            facts = (plain(titles[0].get_text(' ', strip=True)), day.date())
            if identity in links and links[identity][1] != facts:
                invalid()
            links.setdefault(identity, (link, facts))
        else:
            invalid()
    if (not cards or len(cards) != len(views[0].select('.rhpSingleEvent'))
            or set(links) != {_url_key(link) for link in _links(url, widget)}):
        invalid()
    return widget, [value[0] for value in links.values()]


def _canonical(soup, url):
    canonicals = {_public_url(node.get('href'), url)
                  for node in soup.select('link[rel="canonical"]')}
    if canonicals and (None in canonicals or any(_url_key(value) != _url_key(url) for value in canonicals)):
        _fail('html_calendar_detail_identity_conflict')


def _without_events(value):
    if isinstance(value, dict):
        if _event(value):
            return None
        return {key: trimmed for key, child in value.items()
                if (trimmed := _without_events(child)) is not None}
    if isinstance(value, list):
        return [trimmed for child in value if (trimmed := _without_events(child)) is not None]
    return value


def _description(soup, original, row):
    """A reviewed Rockhouse event block can supply its missing native narrative.

    The Event's explicit offset remains the clock authority. Visible heading,
    calendar date, and Show time must independently agree before this precise
    event-body container can be used; site metadata/navigation is never a body.
    """
    value = original.get('description')
    if value is not None and (not isinstance(value, str) or value.strip()):
        return value, 'description'
    sections = soup.select('#RhpEventsSingle .singleEventDetails')
    if not sections:
        return value, 'description'
    if len(sections) != 1:
        _fail('html_calendar_description_ambiguous')
    section = sections[0]
    bodies = section.select('.singleEventDescription')
    if not bodies:
        return value, 'description'
    if len(bodies) != 1:
        _fail('html_calendar_description_ambiguous')
    # _canonical already checked URL agreement. Requiring a canonical as well
    # as exact Event URL prevents an unbound copy of a Rockhouse body elsewhere.
    if len(soup.select('link[rel="canonical"]')) != 1:
        _fail('html_calendar_description_identity_conflict')
    from roomquest.mapsee_adapter import plain
    from roomquest.rockhouse import DAY, SHOW, show_date
    headings = section.select('h1')
    days = section.select('.eventStDate')
    clocks = section.select('.eventDoorStartDate')
    if (len(headings) != 1 or len(days) != 1 or len(clocks) != 1
            or plain(headings[0].get_text(' ', strip=True)).casefold()
            != plain(row['title']).casefold()):
        _fail('html_calendar_description_identity_conflict')
    try:
        begins = datetime.fromisoformat(original['startDate'].replace('Z', '+00:00'))
        if begins.tzinfo is None or begins.utcoffset() is None:
            raise ValueError
        day_match = DAY.search(plain(days[0].get_text(' ', strip=True)))
        day = show_date(day_match, begins.date(), begins.date()) if day_match else None
        show = SHOW.search(plain(clocks[0].get_text(' ', strip=True)))
        if day is None or show is None:
            raise ValueError
        hour, minute, half = show.groups()
        if not 1 <= int(hour) <= 12:
            raise ValueError
        if (begins.hour, begins.minute, begins.second, begins.microsecond) != (
                int(hour) % 12 + (12 if half.casefold() == 'p' else 0), int(minute or 0), 0, 0):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError):
        _fail('html_calendar_description_identity_conflict')
    body = str(bodies[0])
    if plain(bodies[0].get_text(' ', strip=True)).casefold() == plain(row['title']).casefold():
        return None, 'description'
    return body, 'rockhouse_event_description'



def _cambridge_featured_image(source, soup, url, title):
    """Use only an unambiguous same-event upload on the approved Eventin site.

    Other HTML publishers and pages keep their existing JSON-LD-only behavior.
    A missing image remains missing rather than selecting site chrome.
    """
    if (source.get('feed_url') != 'https://cambridgeppf.org/events-list/'
            or urlsplit(url).hostname != 'cambridgeppf.org'
            or not urlsplit(url).path.startswith('/etn/')):
        return None
    root = soup.find('main')
    if root is None:
        return None

    def words(value):
        return re.findall(r'[a-z0-9]+', (value or '').casefold())

    if not any(words(node.get_text(' ', strip=True)) == words(title)
               for node in root.select('h1')):
        return None
    meaningful = [term for term in words(title)
                  if len(term) >= 4 and term not in {'with', 'from', 'this', 'that'}]
    if len(meaningful) < 2:
        return None
    from roomquest.registered_native_content import image_candidate
    matches = set()
    for img in root.select('img[src]')[:35]:
        if img.find_parent(['aside', 'nav', 'footer', 'header']):
            continue
        candidate = _public_url(img.get('src', ''), url)
        if not candidate or '/wp-content/uploads/' not in urlsplit(candidate).path:
            continue
        if not image_candidate(candidate, url):
            continue
        filename = urlsplit(candidate).path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        parts = words(filename)
        if sum(any(a[:4] == b[:4] for b in parts if len(b) >= 4)
               for a in meaningful) < 2:
            continue
        matches.add(candidate)
    return next(iter(matches)) if len(matches) == 1 else None


def _detail(source, payload, url):
    soup = _html(payload)
    _canonical(soup, url)
    nodes = _document(payload)
    candidates = []
    references = []
    images = {}
    for node in nodes:
        if _event(node):
            link = _public_url(node.get('url') or node.get('@id'), url)
            if link and _url_key(link) == _url_key(url):
                candidates.append(node)
        elif node.get('@id') and len(node) > 1:
            clean = _without_events(node)
            references.append(clean)
            identity = node['@id']
            prior = images.get(identity)
            if prior is None or jsonld_adapter.definition_contains(node, prior):
                images[identity] = node
    if not candidates:
        from roomquest.registered_date_only_clock import date_only_event_with_clock
        completed = date_only_event_with_clock(nodes, soup, url, _event)
        if completed == []:
            return []  # Explicitly variable performance times; do not invent one.
        if completed:
            candidates.append(completed)
        elif any(_event(node) for node in nodes):
            _fail('html_calendar_detail_identity_conflict')
        else:
            from roomquest.registered_venue_event_card import read as read_venue_card
            outcome = read_venue_card(source, soup, url)
            if outcome is not None:
                return outcome
            from roomquest.registered_event_microdata import parse_event_microdata
            try:
                return parse_event_microdata(source, soup, url)
            except ValueError as error:
                if str(error) != 'html_calendar_event_jsonld_missing':
                    raise
                # Reuse exact publisher-labeled Date/Time/Where facts when
                # neither JSON-LD nor Event microdata exists. Ambiguous
                # calendars still retain their original technical hold.
                from roomquest.registered_visible_event import read as visible_event
                outcome = visible_event(source, soup, url)
                if outcome is not None:
                    return outcome
                raise
    if len(candidates) > MAX_EVENTS:
        _fail('html_calendar_event_limit')

    def image_value(value):
        if isinstance(value, dict) and set(value) == {'@id'}:
            return images.get(value['@id'], value)
        if isinstance(value, list):
            return [image_value(item) for item in value[:5]]
        return value

    records = []
    for original in candidates:
        event = deepcopy(original)
        # Resolve page-local Event IDs against their actual fetched document.
        # Two /event/... pages commonly both publish the local ID '#event'.
        identity = event.get('@id') or event.get('url')
        if not isinstance(identity, str) or not identity:
            _fail('html_calendar_event_identity_missing')
        identity = urljoin(url, identity)
        if len(identity) > 180:
            _fail('html_calendar_event_identity_limit')
        event['@id'] = identity
        # Candidate matching already established exact identity apart from a
        # trailing slash/fragment. Bind the record to the document fetched so
        # its native-content evidence names that same actual publisher URL.
        event['url'] = url
        # Parse only this detail's matching Event, retaining local Place/Image
        # references. Sidebar recommendations are not part of this occurrence.
        for key, value in list(event.items()):
            if isinstance(value, (dict, list)):
                event[key] = _without_events(value)
        graph = json.dumps({'@graph': [event, *references]})
        rows = jsonld_adapter.parse(graph, url)
        for row in rows:
            if _url_key(row['event_url']) != _url_key(url):
                _fail('html_calendar_detail_identity_conflict')
            from roomquest.registered_native_content import attach
            description_value, description_field = _description(soup, original, row)
            extra = ({'description_field': description_field}
                     if description_field != 'description' else {})
            primary_image = image_value(original.get('image'))
            from roomquest.registered_native_content import image_candidate
            if not image_candidate(primary_image, url):
                primary_image = _cambridge_featured_image(source, soup, url, row['title'])
            attach(row, source, description_value=description_value,
                   image_value=primary_image, evidence_url=url, **extra)
            records.append(row)
    return records


def collect(source, fetch, *, deadline_at=None, listing=None):
    """Complete one bounded registered listing; never return a partial prefix."""
    from roomquest.registered_native_content import CAPABILITY as native_capability
    url = source.get('feed_url')
    if (not isinstance(url, str) or _public_url(url, url) != url
            or source.get('source_key') != source_key(url)
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or type(source.get(CAPABILITY)) is not int or source[CAPABILITY] != 1
            or type(source.get(native_capability)) is not int or source[native_capability] != 1):
        _fail('unregistered_html_calendar')

    def check_deadline():
        if deadline_at is not None and monotonic() >= deadline_at:
            _fail('collection_deadline')

    check_deadline()
    payload = listing if listing is not None else fetch(url, 'text/html,application/xhtml+xml')
    from roomquest import forestry_england
    if forestry_england.owns_url(url):
        return forestry_england.collect(source, fetch, deadline_at=deadline_at, listing=payload)
    links = {}
    pages = []
    inventories = set()
    required_pages = set()
    current = url
    while True:
        check_deadline()
        soup = _html(payload)
        observed = _links(current, soup)
        if not _listing_shape(current, soup, observed, collection_url=url if pages else None):
            _fail('html_calendar_scope_unverified')
        archive = _rockhouse_archive(current, soup)
        navigation = soup
        if archive:
            navigation, observed = archive
        next_page, required = _pagination(navigation, current, collection_url=url, previous_pages=pages)
        inventory = frozenset(_url_key(link) for link in observed)
        if inventory in inventories:
            _fail('html_calendar_pagination_stalled')
        inventories.add(inventory)
        for link in observed:
            links.setdefault(_url_key(link), link)
        if len(links) > MAX_DETAILS:
            _fail('html_calendar_detail_limit')
        pages.append(current)
        visited = {_url_key(page) for page in pages}
        required_pages.update(required)
        if not next_page:
            if not required_pages.issubset(visited):
                _fail('html_calendar_pagination_needed')
            break
        if _url_key(next_page) in visited:
            _fail('html_calendar_pagination_cycle')
        if len(pages) >= MAX_LISTING_PAGES:
            _fail('html_calendar_pagination_limit')
        check_deadline()
        payload = fetch(next_page, 'text/html,application/xhtml+xml')
        current = next_page
    records = {}
    for detail_url in links.values():
        check_deadline()
        body = fetch(detail_url, 'text/html,application/ld+json')
        check_deadline()
        for row in _detail(source, body, detail_url):
            key = (row['id'], row['starts_at'])
            if key in records and records[key] != row:
                _fail('conflicting_event_occurrence')
            records[key] = row
            if len(records) > MAX_EVENTS:
                _fail('html_calendar_event_limit')
        check_deadline()
    return sorted(records.values(), key=lambda row: (row['starts_at'], row['id']))
