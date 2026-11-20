"""First-party venue verification and calendar discovery from DB-issued API leads.

This is NOT a general-purpose public crawler. Tickets only resolve short-lived,
publisher-provenance candidates already selected by Supabase. Each candidate
uses the existing bounded robots-aware transport, and the private backend owns
permanent website/feed registration.
"""
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
import re

from roomquest.feed_registration import CalendarLinks, classify, is_event_export
from roomquest.preview_worker import (
    PreviewError, fetch_publisher, public_source_url, supabase_rpc,
)
from roomquest.publisher_pacing import capture_publisher_pacing

DENIALS = {"robots_denied", "publisher_http_401", "publisher_http_403"}
RETRIES = {"dns_unavailable", "robots_unavailable", "source_network_error",
           "source_fetch_deadline", "publisher_pacing_deferred",
           "publisher_rate_limited", "publisher_http_408", "publisher_http_429"}
# A ticketing directory or social site is not an independent venue website.
AGGREGATORS = {
    "eventbrite.com", "ticketmaster.com", "tixr.com", "facebook.com",
    "instagram.com", "yelp.com", "tripadvisor.com", "findlocal.community",
    "thingstodoapi.com", "meetup.com", "allevents.in", "seatgeek.com",
    "stubhub.com", "bandsintown.com", "songkick.com", "dice.fm",
}
PATHS = ("events", "calendar", "whatson", "upcoming", "event-calendar")
MAX_HTML = 3_000_000


def host(url):
    return (urlsplit(url).hostname or "").lower()


def aggregator(url):
    domain = host(url)
    return any(domain == value or domain.endswith("." + value)
               for value in AGGREGATORS)


def root(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "noscript"):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "noscript") and self.ignore:
            self.ignore -= 1

    def handle_data(self, value):
        if not self.ignore and len(self.parts) < 25000:
            self.parts.append(value)

    def text(self):
        return normalize(" ".join(self.parts))


def find_city(address):
    # The publisher's own page must corroborate the venue. An API city/point
    # is not itself independent evidence of a first-party venue.
    chunks = [normalize(x) for x in (address or "").split(",")]
    return chunks[-2] if len(chunks) >= 3 else (
        chunks[-1].split()[0] if len(chunks) == 2 else "")


def name_forms(name):
    # Branch suffixes such as "(Plaza Midwood)" do not have to occur verbatim
    # in the official brewery's page title.
    variants = [normalize(name), normalize(re.sub(r"\([^)]{1,60}\)", "", name))]
    return [x for x in dict.fromkeys(variants) if len(x) >= 7]


def venue_proof(page, url, lead):
    viewer = VisibleText()
    viewer.feed(page[:MAX_HTML])
    text = viewer.text()
    forms = name_forms(lead["name"])
    if not forms or not any(f in text for f in forms):
        return None
    address = lead.get("address") or ""
    match = re.search(r"\b(\d{1,6})\s+([\w .'-]+)", address)
    if match:
        number = match.group(1)
        street_words = [x for x in normalize(match.group(2)).split()
                        if len(x) > 4 and x not in ("street", "avenue", "boulevard",
                                                     "drive", "road", "highway", "north",
                                                     "south", "east", "west")]
        if number in text.split() and street_words and street_words[0] in text:
            return "name_and_street"
    city = find_city(address)
    page_path = normalize(urlsplit(url).path)
    if city and city in text and any(form in page_path for form in forms):
        return "name_city_official_page"
    # A site directly publishing the linked event can establish its own
    # venue brand without copying FindLocal's venue facts permanently.
    event_url = lead.get("event_url") or ""
    website_hint = lead.get("website") or ""
    domain_words = normalize(host(url)).split()
    brand = forms[-1].split()[0]
    if (event_url and host(event_url) == host(url)
            and (not website_hint or host(website_hint) == host(url))
            and len(brand) >= 5 and brand in "".join(domain_words)):
        return "publisher_event_owner"
    return None


def candidate_page(page, url, lead):
    links = CalendarLinks(url)
    links.feed(page[:MAX_HTML])
    # Only a single clearly linked source can be automatically handed off.
    same_host_feeds = [(u, kind) for u, kind in links.links.items()
                       if host(u) == host(url) and not is_event_export(u)]
    if len(same_host_feeds) == 1:
        return same_host_feeds[0][0]
    if len(same_host_feeds) > 1:
        return None
    event = lead.get("event_url") or ""
    if (public_source_url(event) and host(event) == host(url)
            and urlsplit(event).path.rstrip("/").lower().endswith("/events")):
        return event
    pages = [u for u in links.calendar_pages if host(u) == host(url)]
    return pages[0] if len(pages) == 1 else None


def discover(lead, fetch=fetch_publisher, *, deadline_at=None):
    """A bounded first-party proof and at most one linked calendar-page check."""
    if not isinstance(lead, dict) or not lead.get("name"):
        return {"p_outcome": "review", "p_reason": "missing_venue_name"}
    evidence = lead.get("event_url") or ""
    explicit = lead.get("website") or ""
    if explicit and (not public_source_url(explicit) or aggregator(explicit)):
        return {"p_outcome": "review", "p_reason": "untrusted_venue_website"}
    if not explicit and (not public_source_url(evidence) or aggregator(evidence)):
        return {"p_outcome": "review", "p_reason": "official_venue_website_needed"}
    official = explicit or root(evidence)
    if not public_source_url(official) or aggregator(official):
        return {"p_outcome": "review", "p_reason": "official_venue_website_needed"}
    deadline = min(monotonic() + 34, deadline_at if deadline_at is not None else float("inf"))
    scope = (host(official),)
    html = fetch(official, "text/html,application/xhtml+xml", respect_robots=True,
                 allowed_hosts=scope, deadline_at=deadline)
    proof = venue_proof(html, official, lead)
    if not proof:
        return {"p_outcome": "review", "p_reason": "publisher_identity_unverified"}
    feed = candidate_page(html, official, lead)
    if feed and feed != official:
        # One additional request validates the calendar link is actually live.
        # HTML calendars without a reusable adapter remain review candidates.
        child = fetch(feed, "text/calendar,application/json,text/html",
                      respect_robots=True, allowed_hosts=scope, deadline_at=deadline)
        result = classify(feed, child)
        if result.get("p_outcome") == "verified":
            feed = result.get("p_endpoint", feed)
        elif result.get("p_outcome") == "discovered":
            endpoint = result.get("p_endpoint")
            feed = endpoint if endpoint and host(endpoint) == host(official) else None
        elif result.get("p_reason") in ("single_event_page", "invalid_ical"):
            feed = None
        # A genuine HTML calendar page remains a candidate even without an
        # implemented adapter; the shared registrar will mark it for review.
    return {"p_outcome": "verified", "p_website_url": official,
            "p_feed_url": feed if feed and host(feed) == host(official) else None,
            "p_proof": proof}


def run(ticket):
    candidate = supabase_rpc("community_collector_claim_api_venue_discovery",
                             {"p_ticket": ticket}, timeout=6)
    if not candidate:
        return {"outcome": "idle"}
    with capture_publisher_pacing() as pacing:
        try:
            result = discover(candidate)
        except PreviewError as exc:
            reason = str(exc)
            if reason in DENIALS:
                result = {"p_outcome": "disabled", "p_reason": reason}
            elif pacing.get("wait_unbounded"):
                result = {"p_outcome": "review",
                          "p_reason": "publisher_wait_requires_review"}
            elif reason in RETRIES or re.fullmatch(r"publisher_http_5\d\d", reason):
                result = {"p_outcome": "retry", "p_reason": reason}
            else:
                result = {"p_outcome": "review",
                          "p_reason": reason if re.fullmatch(r"[a-z0-9_]{1,100}", reason)
                          else "publisher_check_failed"}
        except (ValueError, TypeError, KeyError):
            result = {"p_outcome": "review", "p_reason": "publisher_check_failed"}
    receipt = supabase_rpc("community_collector_finish_api_venue_discovery",
                           {"p_ticket": ticket, **result}, timeout=8)
    return {"outcome": receipt.get("status") if isinstance(receipt, dict)
            else "lease_expired"}
