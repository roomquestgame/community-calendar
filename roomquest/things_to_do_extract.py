"""Bounded general-source extraction. All results remain review candidates."""
from hashlib import sha256
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from roomquest.things_to_do_search import canonical_url

TYPES = {"Park", "Playground", "Museum", "TouristAttraction", "PublicSwimmingPool"}
HINT = re.compile(r"\b(park|playground|trail|garden|museum|nature center|dog park|swimming|picnic)\b", re.I)
BAD = re.compile(r"\b(access denied|captcha|page not found|sign in to continue|403 forbidden)\b", re.I)


def in_scope(url, context):
    value = canonical_url(url)
    if not value or value != url.split("#")[0]:
        return False
    prefixes = context.get("url_prefixes", [])
    return any(value == prefix or value.startswith(prefix.rstrip("/") + "/")
               for prefix in prefixes if canonical_url(prefix))


def _text(value, limit=12000):
    if not isinstance(value, str):
        return None
    value = " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())
    return value if 0 < len(value) <= limit else None


def _nodes(value, depth=0):
    if depth > 8:
        return
    if isinstance(value, list):
        for item in value[:80]:
            yield from _nodes(item, depth + 1)
    elif isinstance(value, dict):
        yield value
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in value:
                yield from _nodes(value[key], depth + 1)


def parse_page(raw, url, context):
    if not in_scope(url, context) or len(raw.encode()) > 1_500_000:
        raise ValueError("invalid_activity_scope")
    soup = BeautifulSoup(raw, "html.parser")
    main = soup.select_one("main, article")
    if not main or BAD.search(main.get_text(" ", strip=True)[:500]):
        raise ValueError("unusable_activity_page")
    city, state = context.get("city"), context.get("state")
    if not city or not state:
        raise ValueError("unverified_locality_context")
    candidates, seen = [], set()
    for script in soup.select('script[type="application/ld+json"]')[:20]:
        if len(script.get_text()) > 100_000:
            continue
        try:
            nodes = list(_nodes(json.loads(script.get_text())))[:100]
        except (ValueError, RecursionError):
            continue
        for node in nodes:
            kinds = node.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not isinstance(kinds, list) or not all(isinstance(t, str) for t in kinds):
                continue
            if "Event" in kinds or node.get("startDate") or not TYPES.intersection(kinds):
                continue
            title = _text(node.get("name"), 300)
            address = node.get("address")
            if not title or not isinstance(address, dict):
                continue
            # Target locality is a check, never the source of a location claim.
            if (str(address.get("addressLocality", "")).casefold() != city.casefold()
                    or str(address.get("addressRegion", "")).casefold() != state.casefold()):
                continue
            node_url = node.get('url')
            if node_url is not None and not isinstance(node_url, str):
                continue
            source = canonical_url(urljoin(url, node_url or url))
            if source != canonical_url(url):
                continue  # an index's organization/other facility is not this page
            identity = node.get("@id")
            identity = urljoin(url, identity) if isinstance(identity, str) else source
            if canonical_url(identity) != source:
                continue
            external_id = "web:sha256:" + sha256(identity.encode()).hexdigest()
            if external_id in seen:
                continue
            seen.add(external_id)
            candidate = {"external_id": external_id, "title": title, "source_url": source,
                         "extracted_from_url": url, "location_text": f"{city}, {state}",
                         "source_key": context["source_key"], "evidence_level": "detail",
                         "location_evidence": {"url": url, "method": "publisher_address"}}
            for dest, source_key, limit in (("description", "description", 12000),
                                           ("availability_text", "openingHours", 6000)):
                value = _text(node.get(source_key), limit)
                if value:
                    candidate[dest] = value
            candidates.append(candidate)
            if len(candidates) >= 40:
                return candidates
    # HTML fallback requires a reviewed detail scope and explicit local address
    # within the main article; never use the sitewide footer/HQ or target query.
    if not candidates and context.get("html_detail_reviewed") is True:
        title = _text(str(main.find("h1")), 300) if main.find("h1") else None
        address = main.find("address")
        location = _text(str(address), 600) if address else None
        if (title and HINT.search(title) and location
                and re.search(r"\b" + re.escape(city) + r"\b", location, re.I)
                and re.search(r"\b" + re.escape(state) + r"\b", location, re.I)
                and not main.select_one("time[datetime]")):
            candidates.append({"external_id": "web:sha256:" + sha256(url.encode()).hexdigest(),
                               "title": title, "source_url": url, "extracted_from_url": url,
                               "location_text": location, "source_key": context["source_key"],
                               "evidence_level": "detail"})
    return candidates


def discover_links(raw, url, context):
    if not in_scope(url, context) or len(raw.encode()) > 1_500_000:
        raise ValueError("invalid_activity_scope")
    soup = BeautifulSoup(raw, "html.parser")
    links = []
    for link in soup.select("main a[href], article a[href]")[:500]:
        target = canonical_url(urljoin(url, link.get("href", "")))
        if (target and target != url and target not in links and in_scope(target, context)
                and HINT.search(link.get_text(" ", strip=True) + " " + urlsplit(target).path)):
            links.append(target)
        if len(links) == 40:
            break
    return links
