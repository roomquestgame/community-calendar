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
)

RPC = "community_collector_venues"
MAX_BODY = 750_000
MAX_PAGES = 2
TIMEOUT = 5
STREET = r"\d{1,6}[A-Za-z]?\s+[^,\n]{2,100}?"
ADDRESS = re.compile(
    r"(" + STREET + r"(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|"
    r"Drive|Dr\.?|Lane|Ln\.?|Court|Ct\.?|Way|Parkway|Pkwy\.?|Place|Pl\.?|"
    r"Circle|Cir\.?|Highway|Hwy\.?|Terrace|Ter\.?)\s*,?\s*"
    r"[A-Za-z .'-]{2,60},\s*[A-Z]{2}(?:\s+\d{5}(?:-\d{4})?)?)\b", re.I)


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


def structured_address(value) -> str | None:
    if not isinstance(value, dict):
        return None
    street, city, state = (str(value.get(k) or "").strip() for k in
                           ("streetAddress", "addressLocality", "addressRegion"))
    country = value.get("addressCountry", "US")
    if isinstance(country, dict):
        country = country.get("name", "")
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


def extract_candidates(html: str, url: str, claim: dict) -> list[dict]:
    """Require matched place identity or the exact claimed event's location metadata."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    expected = claim["venue_name"]

    def add(place, method, event_match=False):
        if not isinstance(place, dict):
            return
        name = str(place.get("name") or "").strip()
        if not event_match and not venue_matches(expected, name):
            return
        address = structured_address(place.get("address"))
        if address:
            candidates.append({"address": address, "evidence_url": url,
                               "evidence_name": name or expected, "method": method})

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
        for br in soup.select("br"):
            br.replace_with(", ")
        for tag in soup.select("script,style,nav"):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        for match in ADDRESS.finditer(text):
            candidates.append({"address": match.group(1), "evidence_url": url,
                               "evidence_name": expected, "method": "venue_contact"})
    # Distinct addresses are an ambiguity, not a reason to choose the first one.
    return list({words(c["address"]): c for c in candidates}.values())


def next_links(html: str, url: str, claim: dict) -> list[str]:
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


def fetch_page(url: str) -> str:
    """Bound all redirects, DNS destinations, response bytes and HTTP time."""
    current = url
    deadline = monotonic() + 8
    with requests.Session() as session:
        for _ in range(3):
            remaining = deadline - monotonic()
            if remaining < 1:
                raise PreviewError("venue_page_timeout")
            if not public_source_url(current):
                raise PreviewError("invalid_venue_url")
            validate_public_dns(urlparse(current).hostname or "")
            with session.get(current, timeout=(min(2, remaining), min(TIMEOUT, remaining)), stream=True, allow_redirects=False,
                             headers={"User-Agent": "RoomQuestCommunityCalendar/0.2",
                                      "Accept": "text/html,application/ld+json"}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    redirected = urljoin(current, response.headers.get("Location", ""))
                    if urlparse(redirected).hostname != urlparse(current).hostname:
                        # www/non-www canonicalization is the only host change.
                        hosts = {(urlparse(u).hostname or "").removeprefix("www.")
                                 for u in (current, redirected)}
                        if len(hosts) != 1:
                            raise PreviewError("venue_redirect_host")
                    current = redirected
                    continue
                if response.status_code != 200:
                    raise PreviewError("venue_page_unavailable")
                if int(response.headers.get("Content-Length") or 0) > MAX_BODY:
                    raise PreviewError("venue_page_oversized")
                body, size = [], 0
                for chunk in response.iter_content(16384):
                    if monotonic() >= deadline:
                        raise PreviewError("venue_page_timeout")
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise PreviewError("venue_page_oversized")
                    body.append(chunk)
                return b"".join(body).decode(response.encoding or "utf-8", errors="replace")
    raise PreviewError("venue_redirect_limit")


def resolve(claim: dict, *, fetcher=None, clock=None, deadline=None) -> dict | None:
    fetcher, clock = fetcher or fetch_page, clock or monotonic
    deadline = deadline if deadline is not None else clock() + 12
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
    deadline = clock() + min(18, max(1, deadline_seconds))
    claims = database("claim", {"limit": 1}) or []
    for claim in claims[:1]:
        stats["claimed"] += 1
        identity = {k: claim[k] for k in ("venue_key", "lease_id")}
        try:
            answer = resolver(claim, deadline=deadline)
            if answer:
                database("submit", {**identity, **answer})
                stats["resolved"] += 1
            else:
                database("fail", {**identity, "reason": "needs_review"})
                stats["review"] += 1
        except (PreviewError, requests.RequestException, ValueError, OSError):
            database("fail", {**identity, "reason": "page_unavailable"})
            stats["errors"] += 1
    return stats


def run_pipeline() -> dict:
    """Reuse the existing minute Cron and the shared geocoder quota/deadline."""
    from roomquest.forward_geocoder import run_batch as geocode_batch
    from roomquest.event_media import run_batch as photo_batch
    from datetime import datetime, timezone
    start = monotonic()
    # Keep guaranteed coordinate/venue throughput while the photo backlog drains;
    # all three stages use the existing minute job and their own durable caches.
    phase = int(datetime.now(timezone.utc).timestamp() // 60) % 3
    if phase == 2:
        return {"photos": photo_batch(), "phase": "photos"}
    if phase == 0:
        return {"geocoder": geocode_batch(), "phase": "geocoder"}
    venues = run_batch()
    remaining = max(1, int(45 - (monotonic() - start)))
    return {"venues": venues, "geocoder": geocode_batch(deadline_seconds=remaining)}
