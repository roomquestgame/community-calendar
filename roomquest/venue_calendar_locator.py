"""Locate a reusable first-party calendar from a publisher-verified venue website.

This is the producer side of feed registration: it finds candidate endpoints,
but the shared registration checker still owns final source acceptance. Bounded
publisher visits, same-host URLs, robots/pacing and no fabricated feed URLs.
"""
from html.parser import HTMLParser
import json
from urllib.parse import parse_qs, parse_qsl, urlencode, urldefrag, urljoin, urlsplit, urlunsplit
import re

from roomquest.feed_registration import classify, is_event_export, is_tec_collection
from roomquest.registration_formats import scoped_endpoint
from roomquest.preview_worker import PreviewError, public_source_url

CALENDAR_PAGE = re.compile(
    r"(?:^|[-_/])(?:events?|calendar|events-calendar|event-calendar|"
    r"upcoming-events|shows|whatson|whats-on|schedule|what-s-on)(?:/|$)", re.I)
EVENT_LABEL = re.compile(
    r"\b(?:events? calendar|all events|view (?:all |upcoming )?events|"
    r"upcoming events|what.s on|show calendar|event schedule|see all events)\b", re.I)
DATE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b|"
    r"\b20\d\d-[01]\d-[0-3]\d\b", re.I)
SINGLE_EVENT = re.compile(r"/(?:events?|shows?)/[^/?#]{4,}/?$", re.I)
ONE_OFF = re.compile(r"\b(?:add to (?:my |your )?calendar|download event|"
                     r"add this event|save this event)\b", re.I)
TEC_HINTS = ("tribe-events", "the-events-calendar", "tribe_events")
MAX_SOURCE_BYTES = 1_000_000
MAX_PAGES = 2
MAX_FEEDS = 2
MAX_REQUESTS = 4   # Beyond the verified website page already fetched.


def _host(url):
    return (urlsplit(url).hostname or "").lower()


def _link(base, raw):
    if not raw or not isinstance(raw, str) or len(raw) > 1000:
        return None
    if raw.lower().startswith("webcal://"):
        raw = "https://" + raw[9:]
    try:
        value = urldefrag(urljoin(base, raw.strip())).url
        parts = urlsplit(value)
        if (not public_source_url(value) or _host(value) != _host(base)
                or parts.username or parts.password or is_event_export(value)):
            return None
        return value
    except (ValueError, TypeError):
        return None


def _feed_type(url, attrs, label):
    parts = urlsplit(url)
    keys = parse_qs(parts.query)
    low_label = label.lower()
    if ONE_OFF.search(low_label) or is_event_export(url):
        return None
    if is_tec_collection(url):
        return "wordpress"
    if (parts.path.lower().endswith(".ics") or
            keys.get("ical") == ["1"] or
            parts.path.lower().endswith("/ical_subscribe.php") or
            (parts.path.lower().endswith("/icalendar.aspx") and
             keys.get("feed") == ["calendar"]) or
            (attrs.get("type", "").lower() == "text/calendar" and
             ("calendar" in low_label or attrs.get("rel", "").lower() == "alternate"))):
        # An event-detail iCal download is NOT a venue-wide subscription.
        if SINGLE_EVENT.search(parts.path) and not EVENT_LABEL.search(low_label):
            return None
        return "ical"
    return None


class CalendarSignals(HTMLParser):
    """Bounded HTML navigation, subscription and scheduled-event signals."""

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.feeds = {}
        self.pages = {}
        self.event_links = set()
        self.date_marks = set()
        self.heading = False
        self.headline = []
        self.link = None
        self.label_parts = []

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == "time":
            val = attrs.get("datetime", "")
            if DATE.search(val):
                self.date_marks.add(val[:32])
        if tag in ("link", "a"):
            url = _link(self.base, attrs.get("href"))
            if tag == "a":
                self.link = (url, attrs)
                self.label_parts = []
            elif url:
                self._save(url, attrs, attrs.get("title", ""))
        if tag in ("h1", "h2", "h3"):
            self.heading = True

    def handle_data(self, data):
        if self.link is not None and len(self.label_parts) < 8:
            self.label_parts.append(data)
        if self.heading and len(self.headline) < 40:
            self.headline.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            url, attrs = self.link
            if url:
                self._save(url, attrs, " ".join(self.label_parts))
            self.link = None
            self.label_parts = []
        if tag in ("h1", "h2", "h3"):
            self.heading = False

    def _save(self, url, attrs, label):
        kind = _feed_type(url, attrs, label)
        if kind:
            self.feeds[url] = kind
            return
        path = urlsplit(url).path.lower().rstrip("/")
        if SINGLE_EVENT.search(path):
            self.event_links.add(url)
            return
        basename = path.rsplit("/", 1)[-1]
        if (basename in ("events", "calendar", "event-calendar", "events-calendar",
                          "upcoming-events", "whats-on", "whatson", "shows",
                          "schedule", "event-listing", "event-listings")
                or EVENT_LABEL.search(label)):
            score = 0
            if EVENT_LABEL.search(label):
                score += 3
            if basename in ("events", "calendar", "upcoming-events"):
                score += 2
            if urlsplit(url).query:
                score += 1  # Preserve venue-specific selectors.
            self.pages[url] = max(self.pages.get(url, 0), score)

    def is_dated_listing(self, html):
        text = html[:MAX_SOURCE_BYTES]
        # Structured multi-event listing or distinct published dated links.
        structured = len(re.findall(r'"@type"\s*:\s*"Event"', text, re.I))
        years = len(set(DATE.findall(text)))
        has_collection = ("all events" in text.lower() or
                          "upcoming events" in text.lower() or
                          "event calendar" in text.lower())
        return structured >= 2 or (
            len(self.event_links) >= 3 and has_collection and
            (len(self.date_marks) >= 2 or years >= 2)
        )


def _signals(html, base):
    parsed = CalendarSignals(base)
    parsed.feed(html[:MAX_SOURCE_BYTES])
    return parsed


def _squarespace_candidate(html, base):
    body = html[:MAX_SOURCE_BYTES].lower()
    # Squarespace exposes a JSON version of its calendar collection. Probe
    # ONLY from a publisher calendar page containing Squarespace fingerprints.
    if not any(token in body for token in ('squarespace.com', 'squarespace-cdn',
                                           'static.squarespace.com', 'squarespace-context')):
        return None
    path = urlsplit(base)
    if not CALENDAR_PAGE.search(path.path.lower().rstrip('/')):
        return None
    pairs = parse_qsl(path.query, keep_blank_values=True)
    if any(key == 'format' and value != 'json' for key,value in pairs):
        return None
    pairs = [(key,value) for key,value in pairs if key != 'format']
    pairs.append(('format','json'))
    return urlunsplit((path.scheme,path.netloc,path.path,urlencode(pairs),''))


def _squarespace_collection(body):
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return False
    if not isinstance(data,dict):
        return False
    entries = data.get('upcoming',data.get('items'))
    if not isinstance(entries,list) or not 0<len(entries)<=500:
        return False
    # Do not interpret ordinary Squarespace blog/article JSON as an event feed.
    return all(isinstance(x,dict) and isinstance(x.get('id'),str)
               and isinstance(x.get('startDate'),(int,float))
               and not isinstance(x['startDate'],bool)
               for x in entries[:10])


def _publisher_event_index(event_url, official_url):
    """A linked original event can suggest its parent calendar for verification.

    No derived path is registered or retained before visiting that page through
    the normal robots/pacing-aware publisher fetcher.
    """
    if not event_url:
        return None
    url = _link(official_url, event_url)
    if not url:
        return None
    path = urlsplit(url).path
    segments = [part for part in path.split("/") if part]
    if not segments:
        return None
    if segments[0].lower() not in (
        "events", "calendar", "shows", "schedule", "upcoming-events"):
        return None
    root_path = "/" + segments[0]
    if len(segments) == 1 and not urlsplit(url).query:
        return url
    parts = urlsplit(official_url)
    return urlunsplit((parts.scheme, parts.netloc, root_path, "", ""))


def _reusable_html_index(parsed, html, url, event_url):
    """Allow *verified recurring event listings*, never generic homepages."""
    segments = [part for part in urlsplit(url).path.split("/") if part]
    if not segments or segments[-1].lower() not in (
        "events", "calendar", "shows", "schedule", "upcoming-events",
        "events-calendar", "event-calendar", "whatson", "whats-on"):
        return False
    if parsed.is_dated_listing(html):
        return True
    # Dynamic JS calendars can render their dates only in the browser; require
    # both explicit publisher event-index language and upstream event ownership
    # corroboration (the exact site hosts the original event or events index).
    original = _link(url, event_url)
    if not original:
        return False
    u = urlsplit(url)
    o = urlsplit(original)
    root_path = u.path.rstrip("/")
    event_path = o.path.rstrip("/")
    if event_path != root_path and not event_path.startswith(root_path + "/"):
        return False
    if not re.search(r"\b(?:all|upcoming|view all)\s+events\b|"
                     r"<h[1-3][^>]*>\s*(?:events|calendar|shows)\b", html, re.I):
        return False
    return True


def _wp_candidate(html, site):
    # Never replace a location-filtered events listing with an unfiltered TEC
    # collection that could silently import events for unrelated venues.
    if urlsplit(site).query:
        return None
    text = html[:MAX_SOURCE_BYTES].lower()
    if not any(token in text for token in TEC_HINTS):
        return None
    # This path is a documented TEC endpoint, but still MUST be fetched and
    # validated. Website technology evidence alone cannot register a feed.
    return urlunsplit((urlsplit(site).scheme, urlsplit(site).netloc,
                       "/wp-json/tribe/events/v1/events", "", ""))


def find_calendar(website_html, website_url, event_url, fetch, deadline, *, require_unique_calendar_page=False):
    """Return (URL, finding) from at most four additional first-party requests.

    'ical'/'wordpress': actual validated response, eligible for registration.
    'html_listing': dated first-party events collection for adapter review.
    'none'/'access_denied': no reusable public calendar evidenced.
    """
    inspected = set()
    inspected_api_roots = set()
    candidates = [(website_url, website_html)]
    pages = []
    endpoints = []
    best_html = None
    count = 0
    machine_checks = 0
    page_checks = 0
    while candidates:
        base, html = candidates.pop(0)
        if base in inspected:
            continue
        inspected.add(base)
        parsed = _signals(html, base)
        # Registration of a standalone page must not arbitrarily choose between
        # multiple publisher-linked event calendars. Venue discovery keeps its
        # existing, separately evidenced ranking behavior.
        if require_unique_calendar_page and base == website_url:
            linked_pages = [u for u in parsed.pages if scoped_endpoint(website_url, u)]
            if len(linked_pages) > 1:
                return None, "multiple_pages"
        # Multiple distinct source subscriptions are ambiguous in a singular
        # handoff. Prefer one proven TEC collection over duplicate iCal exports,
        # otherwise preserve the website for review instead of guessing.
        direct = [u for u in parsed.feeds
                  if scoped_endpoint(base,u)]
        wp_direct = [u for u in direct if parsed.feeds[u] == "wordpress"]
        wp = _wp_candidate(html, base)
        if len(direct) > 1 and len(wp_direct) != 1:
            if not wp:
                return None, "multiple_feeds"
            # Several iCal exports are not permission to guess their scope.
            # Probe the publisher-evidenced TEC collection instead; if it fails,
            # the caller retains the original ambiguous-registration hold.
            direct = []
        elif len(wp_direct) == 1:
            direct = wp_direct
        for endpoint in direct:
            if endpoint not in endpoints:
                endpoints.append(endpoint)
        if wp and wp not in endpoints:
            endpoints.insert(0, wp)
        square = _squarespace_candidate(html, base)
        if square and square not in endpoints:
            endpoints.append(square)
        if (_reusable_html_index(parsed, html, base, event_url)
                or (base != website_url and parsed.is_dated_listing(html))):
            if best_html is None:
                best_html = base
        for u, score in sorted(parsed.pages.items(), key=lambda x: (-x[1], x[0])):
            if u not in pages and u != base:
                pages.append(u)
        # A provider-owned event permalink supplies a verified clue about its
        # *potential* parent listing. Probe it; never register it by inference.
        parent = _publisher_event_index(event_url, website_url)
        if parent and parent not in pages and parent != base:
            pages.append(parent)  # Keep verified venue-specific page filters first.
        if event_url:
            matched = _link(website_url, event_url)
            if matched and urlsplit(matched).path.rstrip("/").lower().endswith(
                    ("/events", "/calendar", "/upcoming-events")) and matched not in pages:
                pages.append(matched)

        # Prefer proven endpoints over generic HTML and stay within budget.
        while endpoints and count < MAX_REQUESTS and machine_checks < MAX_FEEDS:
            url = endpoints.pop(0)
            if url in inspected:
                continue
            inspected.add(url)
            count += 1
            machine_checks += 1
            try:
                data = fetch(url, "text/calendar,application/json,text/html",
                             respect_robots=True, allowed_hosts=(_host(website_url),),
                             deadline_at=deadline)
            except PreviewError as e:
                if str(e) in ("robots_denied", "publisher_http_401", "publisher_http_403"):
                    return best_html, "access_denied" if best_html else "access_denied"
                continue
            check = classify(url, data, endpoint_only=True)
            if check.get("p_outcome") == "verified" and check.get("p_type") in ("ical", "wordpress"):
                return url, check["p_type"]
            if parse_qs(urlsplit(url).query).get("format") == ["json"] and _squarespace_collection(data):
                return url, "squarespace"
            # Invalid/cancelled/single event feed never becomes a registered source.
        # WordPress advertises its REST root in a rel=api.w.org link. Read
        # *that* index for an actual supported TEC GET route, rather than
        # assuming WordPress has a particular plugin or /wp-json location.
        # This is an optional fallback after publisher-linked subscriptions:
        # never broaden a filtered calendar, exceed the shared probe budget,
        # or let an inaccessible API block ordinary HTML review.
        if (count + 2 <= MAX_REQUESTS and machine_checks + 2 <= MAX_FEEDS
                and not urlsplit(base).query
                and CALENDAR_PAGE.search(urlsplit(base).path.lower().rstrip('/'))):
            from roomquest.wordpress_capabilities import advertised_rest_root, inspect_rest_index
            api_root = advertised_rest_root(base, html)
            if (api_root and api_root not in inspected_api_roots
                    and scoped_endpoint(base, api_root)):
                inspected_api_roots.add(api_root)
                count += 1
                machine_checks += 1
                try:
                    index_body = fetch(api_root, "application/json",
                                       respect_robots=True, allowed_hosts=(_host(website_url),),
                                       deadline_at=deadline)
                except PreviewError:
                    pass
                else:
                    capability = inspect_rest_index(api_root, index_body)
                    endpoint = capability.get('endpoint') if capability else None
                    if (endpoint and endpoint not in inspected
                            and scoped_endpoint(base, endpoint)):
                        inspected.add(endpoint)
                        count += 1
                        machine_checks += 1
                        try:
                            data = fetch(endpoint, "application/json",
                                         respect_robots=True, allowed_hosts=(_host(website_url),),
                                         deadline_at=deadline)
                        except PreviewError:
                            pass
                        else:
                            checked = classify(endpoint, data, endpoint_only=True)
                            if (checked.get("p_outcome") == "verified"
                                    and checked.get("p_type") == "wordpress"):
                                return endpoint, "wordpress"
        if count >= MAX_REQUESTS:
            break
        if not candidates and pages and page_checks < MAX_PAGES:
            page_url = pages.pop(0)
            if page_url in inspected:
                continue
            count += 1
            page_checks += 1
            try:
                data = fetch(page_url, "text/html,application/xhtml+xml",
                             respect_robots=True, allowed_hosts=(_host(website_url),),
                             deadline_at=deadline)
            except PreviewError as e:
                if str(e) in ("robots_denied", "publisher_http_401", "publisher_http_403"):
                    return best_html, "access_denied"
                continue
            if data.lstrip().startswith("<"):
                candidates.append((page_url, data))
    return (best_html, "html_listing") if best_html else (None, "none")
