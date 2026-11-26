"""Resolve publisher venue identities to evidenced addresses before geocoding.

No search-provider subscription or new geocoding provider. Only server-claimed
publisher/event URLs and explicitly verified venue pages are fetched. A durable
source-scoped cache links future occurrences to the same verified address.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from time import monotonic
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from roomquest.preview_worker import (
    PreviewError, public_source_url, validate_public_dns, supabase_rpc,
    fetch_publisher,
)

RPC = "community_collector_venues"
MAX_BODY = 750_000
MAX_PAGES = 2
TIMEOUT = 5
STREET = r"\d{1,6}[A-Za-z]?\s+[^,\n]{2,100}?"
ADDRESS = re.compile(
    r"(?P<street>" + STREET + r"(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|"
    r"Drive|Dr\.?|Lane|Ln\.?|Court|Ct\.?|Way|Parkway|Pkwy\.?|Place|Pl\.?|"
    r"Circle|Cir\.?|Highway|Hwy\.?|Terrace|Ter\.?))\s*(?:,|[-–—])?\s*"
    r"(?P<city>[A-Za-z][A-Za-z .'-]{1,59}),\s*(?P<state>[A-Z]{2})"
    r"(?P<zip>\s+\d{5}(?:-\d{4})?)?\b", re.I)


def words(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize(
        "NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()).strip()


def venue_matches(expected: str, actual: str) -> bool:
    """A room suffix may be dropped; a generic room or campus never identifies a venue."""
    a, b = words(expected).replace('free public library', 'public library'), words(actual).replace('free public library', 'public library')
    generic = {"meeting", "room", "floor", "hall", "building", "campus", "library",
               "center", "centre", "community", "the", "at", "and", "of", "public"}
    ta, tb = a.split(), b.split()
    if not a or not b or not (set(ta) - generic) or not (set(tb) - generic):
        return False
    if 'library' in ta and 'library' not in tb:
        return False
    return a == b or (len(tb) >= 2 and " " + b + " " in " " + a + " ") or (
        len(ta) >= 2 and " " + a + " " in " " + b + " ") or (
        len((set(ta) & set(tb)) - generic) >= 2
        and len((set(ta) & set(tb)) - generic) >= min(len(set(ta) - generic), len(set(tb) - generic)))


def structured_address(value, *, allow_gb=False) -> str | None:
    if not isinstance(value, dict):
        return None
    street, city, state = (str(value.get(k) or "").strip() for k in
                           ("streetAddress", "addressLocality", "addressRegion"))
    country = value.get("addressCountry", "US")
    if isinstance(country, dict):
        country = country.get("name", "")
    if allow_gb and str(country).upper() in {'GB', 'UK', 'UNITED KINGDOM', 'GREAT BRITAIN'}:
        from roomquest.forward_geocoder import normalize_gb_postcode, gb_address_part
        postcode = normalize_gb_postcode(str(value.get('postalCode') or ''))
        street, city = gb_address_part(street, street=True), gb_address_part(city)
        if street and city and postcode:
            return ','.join((street, city, postcode))
        return None
    if str(country).upper() not in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return None
    if not re.match(r"^\d{1,6}[A-Za-z]?\s+", street) or not city or not state:
        return None
    if any(x in (street + city).lower() for x in ("https://", "p.o. box", "virtual", "zoom")):
        return None
    postcode = str(value.get("postalCode") or "").strip()
    return ", ".join(x for x in (street, city, state, postcode) if x)[:400]


def json_nodes(value):
    if isinstance(value, dict):
        yield value
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            yield from json_nodes(value.get(key))
    elif isinstance(value, list):
        for item in value[:100]:
            yield from json_nodes(item)


def gb_contact_addresses(soup, expected):
    """Read one short semantic address block, never a publisher-wide default."""
    from roomquest.forward_geocoder import normalize_gb_postcode, gb_address_part
    found = set()
    pattern = re.compile(
        r"^([A-Za-z0-9' .–&-]{3,100}?),\s*([A-Za-z' .-]{2,80}?)\s*,?\s+"
        r"([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})(?:,\s*(?:UK|GB|United Kingdom))?$", re.I)
    for tag in soup.select('address,p,h2,h3')[:150]:
        block = BeautifulSoup(str(tag), 'html.parser')
        for br in block.select('br'):
            br.replace_with(', ')
        text = re.sub(r'\s+', ' ', block.get_text(' ', strip=True)).strip()
        # A semantic address can begin with its own explicit place identity.
        # Remove only that matched component, never an arbitrary organization.
        first, separator, rest = text.partition(',')
        if separator and venue_matches(expected, first):
            text = rest.strip()
        if len(text) > 220:
            continue
        match = pattern.fullmatch(text)
        if not match:
            continue
        street, town, postcode = (value.strip() for value in match.groups())
        if not re.search(r'\b(?:street|st|road|rd|lane|ln|avenue|ave|square|hill|way|gardens|place|terrace)\.?$', street, re.I):
            continue
        street, town = gb_address_part(street, street=True), gb_address_part(town)
        postcode = normalize_gb_postcode(postcode)
        if street and town and postcode:
            found.add(','.join((street, town, postcode)))
    return sorted(found)


def extract_candidates(html: str, url: str, claim: dict) -> list[dict]:
    """Require matched place identity or the exact claimed event's location metadata."""
    if claim.get('provider') == 'event_discovery':
        from roomquest.event_calendar_export import evidence
        answer = evidence(html, url, claim.get('location_identity'))
        return [answer] if answer else []
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    expected = claim["venue_name"]
    spektrix = claim.get('provider') == 'spektrix'

    def add(place, method, event_match=False):
        if not isinstance(place, dict):
            return
        name = str(place.get("name") or "").strip()
        if not event_match and not venue_matches(expected, name):
            return
        address = structured_address(place.get("address"), allow_gb=spektrix)
        if address:
            candidates.append({"address": address, "evidence_url": url,
                               "evidence_name": name or expected, "method": method,
                               **({'country_code': 'GB'} if spektrix and re.search(
                                   r',[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$', address) else {})})

    for script in soup.select('script[type="application/ld+json"]')[:30]:
        try:
            nodes = json_nodes(json.loads(script.string or script.get_text()))
            for node in nodes:
                types = node.get("@type", [])
                types = types if isinstance(types, list) else [types]
                is_event = any(str(t).split("/")[-1].endswith("Event") for t in types)
                if is_event and (words(node.get("name")) == words(claim.get("event_title"))
                                 and bool(words(claim.get("event_title")))):
                    locations = node.get("location", [])
                    for place in locations if isinstance(locations, list) else [locations]:
                        add(place, "event_jsonld", event_match=True)
                else:
                    add(node, "venue_jsonld")
        except (ValueError, TypeError, RecursionError):
            continue

    # Schema microdata is common on library, WordPress and campus place pages.
    for tag in soup.select('[itemtype*="Place"], [itemtype*="LocalBusiness"], [itemtype*="Organization"]')[:30]:
        name = tag.select_one('[itemprop="name"]')
        name = name.get("content") or name.get_text(" ", strip=True) if name else ""
        address = {}
        for field in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"):
            element = tag.select_one('[itemprop="' + field + '"]')
            if element:
                address[field] = element.get("content") or element.get_text(" ", strip=True)
        add({"name": name, "address": address}, "venue_microdata")

    # Plain contact pages must identify this venue in their title/heading. Never
    # take an organization's footer address from an unrelated event page.
    headings = [x.get_text(" ", strip=True) for x in soup.select("title,h1,h2")[:20]]
    if any(venue_matches(expected, name) for name in headings):
        if spektrix:
            for address in gb_contact_addresses(soup, expected):
                candidates.append({'address': address, 'country_code': 'GB',
                                   'evidence_url': url, 'evidence_name': expected,
                                   'method': 'venue_contact'})
        for br in soup.select("br"):
            br.replace_with(", ")
        for tag in soup.select("script,style,nav"):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        for match in ADDRESS.finditer(text):
            # Publisher typography between street and city is a separator,
            # not part of the city name supplied to the shared geocoder.
            address = (f"{match['street'].strip()}, {match['city'].strip()}, "
                       f"{match['state']}{match['zip'] or ''}")
            candidates.append({"address": address, "evidence_url": url,
                               "evidence_name": expected, "method": "venue_contact"})
    # Distinct addresses are an ambiguity, not a reason to choose the first one.
    return list({words(c["address"]): c for c in candidates}.values())


def next_links(html: str, url: str, claim: dict) -> list[str]:
    if claim.get('provider') == 'event_discovery':
        return []  # Its claim is bound to one occurrence, never the publisher's footer.
    soup = BeautifulSoup(html, "html.parser")
    host = (urlparse(url).hostname or "").lower()
    links = []
    for anchor in soup.select("a[href]")[:300]:
        target = urljoin(url, anchor["href"])
        label = anchor.get_text(" ", strip=True)
        # Crawl one publisher-local venue/contact page, never an arbitrary
        # cross-domain link or a generic calendar/advertisement.
        if (public_source_url(target) and urlparse(target).hostname == host and target != url
                and (venue_matches(claim["venue_name"], label)
                     or (words(label) in {"contact", "contact us", "directions", "visit us"}
                         and venue_matches(claim["venue_name"], claim.get("publisher_name", ""))))):
            if target not in links:
                links.append(target)
    return links[:3]


def fetch_page(url: str, *, deadline_at=None) -> str:
    """Use the registration collector's robots-aware bounded transport.

    Venue lookup must not bypass robots/crawl delay merely because an event
    source is registered. The shared publisher transport checks DNS, redirects,
    policies, deadlines and per-host pacing before returning a public page.
    """
    if not public_source_url(url):
        raise PreviewError("invalid_venue_url")
    host = urlparse(url).hostname or ""
    validate_public_dns(host)
    raw = fetch_publisher(
        url, "text/html,application/ld+json", respect_robots=True,
        deadline_at=deadline_at if deadline_at is not None else monotonic() + 8, allowed_hosts=(host,),
    )
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        raise PreviewError("venue_page_unavailable")
    if len(raw.encode("utf-8")) > MAX_BODY:
        raise PreviewError("venue_page_oversized")
    return raw

def resolve(claim: dict, *, fetcher=None, clock=None, deadline=None) -> dict | None:
    clock = clock or monotonic
    deadline = deadline if deadline is not None else clock() + 12
    if claim.get("provider") == "event_discovery":
        # One exact event page uses the existing 15-second claim allowance.
        # This admits a publisher crawl delay without adding requests, a fresh
        # budget, or changing the shared transport/network/redirect caps.
        target = claim.get("event_url")
        if not target or not public_source_url(target) or clock() + TIMEOUT + 1 >= deadline:
            return None
        page = fetcher(target) if fetcher is not None else fetch_page(target, deadline_at=deadline)
        candidates = extract_candidates(page, target, claim)
        return candidates[0] if len(candidates) == 1 else None
    fetcher = fetcher or fetch_page
    urls = [u for u in (claim.get("evidence_hint"), claim.get("event_url"),
                        claim.get("publisher_url")) if u and public_source_url(u)]
    visited, candidates = set(), []
    while urls and len(visited) < MAX_PAGES and clock() + TIMEOUT + 1 < deadline:
        url = urls.pop(0)
        if url in visited:
            continue
        visited.add(url)
        html = fetcher(url)
        candidates.extend(extract_candidates(html, url, claim))
        if candidates:
            break
        urls[0:0] = next_links(html, url, claim)
    unique = {words(c["address"]): c for c in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def rpc(action: str, payload=None):
    return supabase_rpc(RPC, {"p_action": action, "p_payload": payload or {}})


def run_batch(*, database=None, resolver=None, clock=None, deadline_seconds=15) -> dict:
    stats = {"claimed": 0, "resolved": 0, "review": 0, "errors": 0}
    if os.environ.get("FORWARD_GEOCODER_ENABLED") != "true" or os.environ.get("VERCEL_ENV") != "production":
        return stats
    database, resolver, clock = database or rpc, resolver or resolve, clock or monotonic
    from roomquest import venue_research
    research_config = venue_research.configured()
    start = clock()
    # Keep ordinary work at its existing 15-second budget. A scheduled
    # research claim is eligible only when the route has the full research
    # allowance plus its separate completion headroom.
    research_ready = bool(research_config and deadline_seconds >= venue_research.RESEARCH_WORK_SECONDS)
    ordinary_deadline = start + min(15 if research_ready else 18, max(1, deadline_seconds))
    research_deadline = start + venue_research.RESEARCH_WORK_SECONDS if research_ready else ordinary_deadline
    claims = database("claim", venue_research.claim_options(research_config if research_ready else None)) or []
    for claim in claims[:1]:
        stats["claimed"] += 1
        identity = {k: claim[k] for k in ("venue_key", "lease_id")}
        try:
            outcome = venue_research.handle_claim(database, claim, identity, research_config if research_ready else None,
                                                   fetch=fetch_page, deadline=research_deadline, clock=clock)
            if outcome is not None:
                stats[outcome] += 1
                continue
            answer = resolver(claim, deadline=ordinary_deadline)
            if answer:
                database("submit", {**identity, **answer})
                stats["resolved"] += 1
            elif venue_research.defer_miss(database, claim, identity, research_config):
                stats["research_deferred"] = stats.get("research_deferred", 0) + 1
            else:
                database("fail", {**identity, "reason": "needs_review"})
                stats["review"] += 1
        except PreviewError as exc:
            # Publisher deny/robots restrictions are review holds, not
            # retryable generic network outages; never test a bypass URL.
            blocked = str(exc) in {
                "robots_denied", "publisher_http_401", "publisher_http_403",
            }
            database("fail", {**identity, "reason":
                              "needs_review" if blocked else "page_unavailable"})
            stats["review" if blocked else "errors"] += 1
        except (requests.RequestException, ValueError, OSError):
            database("fail", {**identity, "reason": "page_unavailable"})
            stats["errors"] += 1
    return stats


def run_pipeline() -> dict:
    """Run geocoding first; optional venue/photo stages cannot block it."""
    from roomquest.forward_geocoder import run_batch as geocode_batch
    from roomquest.event_media import dedicated_media_ready, run_batch as photo_batch
    from datetime import datetime, timezone

    start = monotonic()
    # The HTTP route has a 60-second cap. Budget optional work against 55s to
    # allow response headroom; existing I/O deadlines remain cooperative. A slow
    # geocoder must not start a fresh venue/photo budget near the request's end.
    deadline = start + 55
    phase = int(datetime.now(timezone.utc).timestamp() // 60) % 3
    result = {"phase": ("photos" if phase == 2 else "venues" if phase == 1 else "geocoder")}

    def optional_stage(worker, work_seconds, completion_seconds):
        remaining = deadline - monotonic() - completion_seconds
        # Keep the full existing work allowance. Shrinking it after a claim
        # could turn an unfinished lookup into needs_review/no_event_image.
        if remaining < work_seconds:
            return {"stop_reason": "deadline"}
        return worker(deadline_seconds=min(work_seconds, remaining))

    # Geocoding is the critical path. Keep it first and isolate failures so an
    # optional worker cannot turn the entire cron request into a 503.
    try:
        remaining = max(1, int(45 - (monotonic() - start)))
        result["geocoder"] = geocode_batch(deadline_seconds=remaining)
    except Exception as exc:
        print("geocoder_stage_failed", type(exc).__name__, str(exc)[:120])
        result["geocoder"] = {"stop_reason": "stage_failed"}

    if phase == 2:
        try:
            if deadline - monotonic() < 4:  # Capability RPC timeout.
                result["photos"] = {"stop_reason": "deadline"}
            elif dedicated_media_ready():
                result["photos"] = {"stop_reason": "dedicated_worker"}
            else:
                # Recheck after the capability RPC, reserving up to three
                # four-second completion RPCs for the legacy batch.
                result["photos"] = optional_stage(photo_batch, 38, 12)
        except Exception:
            result["photos"] = {"stop_reason": "stage_failed"}
    elif phase == 1:
        try:
            # One four-second completion RPC, plus an eight-second page fetch
            # and final five-second read beyond the six-second admission guard.
            from roomquest import venue_research
            if venue_research.configured() and deadline - monotonic() - 11 >= venue_research.RESEARCH_WORK_SECONDS:
                result["venues"] = optional_stage(run_batch, venue_research.RESEARCH_WORK_SECONDS, 11)
            else:
                result["venues"] = optional_stage(run_batch, 15, 11)
        except Exception:
            result["venues"] = {"stop_reason": "stage_failed"}

    return result

