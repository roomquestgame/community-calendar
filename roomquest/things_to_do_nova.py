"""Pure, bounded NOVA Parks activity extraction for the private pilot.

The caller owns fetching, robots/rate checks, scheduling, and persistence.  This
module reads only supplied HTML and verified park context.  It does not create
dated events, infer admission/ages, or inherit a park's hours for its activities.

``parse_page(html, source_url, park_context)`` returns candidate dictionaries.
``discover_links(...)`` returns same-park activity detail URLs only.  A candidate
without its own detail page uses the publisher's existing ``#node-N`` fragment;
the Drupal node ID stays the same when a detail page is subsequently fetched.
All descriptive fields are optional.  Unexpected page shape is an error, not a
successful empty crawl.  Tests use small synthetic markup, not publisher copies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag


HOST = "www.novaparks.com"
ORIGIN = "https://" + HOST
PARK_SLUGS = frozenset({
    "potomac-overlook-regional-park",
    "upton-hill-regional-park",
    "meadowlark-botanical-gardens",
})
MAX_HTML_BYTES = 1_500_000
MAX_CANDIDATES = 40
MAX_LINKS = 40
MAX_TEXT_CHARS = 12_000
_NODE_ID = re.compile(r"[1-9][0-9]{0,11}\Z")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_DONATION_TITLES = frozenset({
    "adopt an animal", "donate", "donations", "make a donation",
    "support your park", "support the park",
})
_ACTIVITY_TYPES = frozenset({
    "node--type-thing-to-do", "node--type-waterpark",
    "node--type-wedding-venue", "node--type-golf-course",
})
_BOOKING_HOSTS = frozenset({
    HOST, "apm.activecommunities.com", "anc.apm.activecommunities.com",
    "fareharbor.com",
})


def _text(node: Tag | None, limit: int = MAX_TEXT_CHARS) -> str | None:
    if node is None:
        return None
    copy = BeautifulSoup(str(node), "html.parser")
    for unwanted in copy.select("script, style, template, noscript, iframe"):
        unwanted.decompose()
    value = " ".join(copy.get_text(" ", strip=True).split())
    return value[:limit] or None


def _string(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _https_url(value: object, base: str) -> str | None:
    """Normalize a public link without allowing credentials or unusual ports."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    if value != value.strip() or "\\" in value or re.search(r"[\x00-\x20\x7f]", value):
        return None
    try:
        parsed = urlsplit(urljoin(base, value))
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)):
            return None
        return urlunsplit(("https", parsed.hostname.lower(), parsed.path,
                           parsed.query, parsed.fragment))
    except (TypeError, ValueError):
        return None


def _park_url(value: object, base: str, park_slug: str) -> str | None:
    url = _https_url(value, base)
    if url is None:
        return None
    parts = urlsplit(url)
    prefix = "/parks/" + park_slug
    path = parts.path.rstrip("/")
    if parts.hostname != HOST or parts.query or "%" in path:
        return None
    suffix = path[len(prefix):] if path.startswith(prefix) else None
    if suffix not in ("", "/things-to-do"):
        if not (suffix and suffix.startswith("/things-to-do/")
                and _SLUG.fullmatch(suffix[len("/things-to-do/"):])):
            return None
    if parts.fragment and not re.fullmatch(r"node-[1-9][0-9]{0,11}", parts.fragment):
        return None
    return urlunsplit(("https", HOST, path, "", parts.fragment))


def _context(context: Mapping[str, object]) -> dict[str, str]:
    if not isinstance(context, Mapping):
        raise ValueError("nova_park_context_invalid")
    values = {key: _string(context.get(key)) for key in (
        "park_slug", "park_name", "city", "state", "location_text", "location_source_url",
    )}
    if (values["park_slug"] not in PARK_SLUGS or not values["park_name"]
            or not values["city"] or not re.fullmatch(r"[A-Z]{2}", values["state"])):
        raise ValueError("nova_park_context_invalid")
    if not values["location_text"]:
        values["location_text"] = ", ".join((values["park_name"], values["city"], values["state"]))
    parent = ORIGIN + "/parks/" + values["park_slug"]
    if _park_url(values["location_source_url"], parent, values["park_slug"]) != parent:
        raise ValueError("nova_location_source_invalid")
    return values


def _page(html: str, source_url: str, context: Mapping[str, object]):
    park = _context(context)
    url = _park_url(source_url, ORIGIN, park["park_slug"])
    if not url or "/things-to-do" not in urlsplit(url).path:
        raise ValueError("nova_source_url_out_of_scope")
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError("nova_html_limit")
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main#main-content")
    if main is None or (_text(main.select_one("h1")) or "").casefold() != park["park_name"].casefold():
        raise ValueError("nova_page_shape_changed")
    canonical = soup.select_one('link[rel="canonical"]')
    if canonical and not _park_url(canonical.get("href"), url, park["park_slug"]):
        raise ValueError("nova_canonical_out_of_scope")
    for unwanted in main.select("nav, script, style, template, noscript, iframe"):
        unwanted.decompose()
    path = urlsplit(url).path
    listing = path.endswith("/things-to-do")
    if listing:
        container = main.select_one("article.node--type-page.node--view-mode-full .listing.activity .content")
        if container is None:
            raise ValueError("nova_listing_shape_changed")
        nodes = container.find_all("article", recursive=False)
        # These finite pilot catalogs are known to contain activities.  An empty
        # or redesigned container needs review, not healthy empty/partial data.
        if not nodes or any(
            "node--view-mode-teaser" not in node.get("class", [])
            or not _ACTIVITY_TYPES.intersection(node.get("class", []))
            for node in nodes
        ):
            raise ValueError("nova_listing_shape_changed")
    else:
        nodes = main.select("article.node--type-thing-to-do.node--view-mode-full")
        if len(nodes) != 1:
            raise ValueError("nova_detail_shape_changed")
    if len(nodes) > MAX_CANDIDATES:
        raise ValueError("nova_candidate_limit")
    return park, url, nodes, listing


def _node_id(node: Tag) -> str:
    identity = str(node.get("data-history-node-id") or "")
    fragment = str(node.get("id") or "")
    if not identity and fragment.startswith("node-"):
        identity = fragment[5:]
    if not _NODE_ID.fullmatch(identity) or (fragment and fragment != "node-" + identity):
        raise ValueError("nova_node_identity_invalid")
    return identity


def _heading(node: Tag, listing: bool) -> Tag | None:
    if listing:
        return node.select_one("h3, h2, h4")
    # The first h1 is the park, while the activity title is this content h2.
    return node.select_one(".content-container.t-align-center > h2")


def _is_donation(title: str, node: Tag) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]", "", title.casefold())
    if normalized in _DONATION_TITLES:
        return True
    heading = node.select_one("h3 a[href], h2 a[href]")
    return bool(heading and urlsplit(str(heading.get("href"))).path.rstrip("/").endswith("/adopt-an-animal"))


def _detail_link(node: Tag, heading: Tag | None, url: str, slug: str) -> str | None:
    candidates = list(heading.select("a[href]")) if heading else []
    candidates += [a for a in node.select("a[href]")
                   if re.match(r"read\s*more\b", _text(a) or "", re.I)]
    for link in candidates:
        target = _park_url(link.get("href"), url, slug)
        if target and "/things-to-do/" in urlsplit(target).path:
            return target.split("#", 1)[0]
    return None


def _image(node: Tag, base: str) -> str | None:
    for image in node.select(".field--name-field-image img"):
        for key in ("data-src", "src"):
            url = _https_url(image.get(key), base)
            if url and urlsplit(url).hostname == HOST and urlsplit(url).path.startswith("/sites/default/files/"):
                return url
    return None


def _labelled_text(node: Tag, labels: str) -> str | None:
    values = []
    for heading in node.select("h2, h3, h4, caption"):
        if not re.fullmatch(labels, _text(heading) or "", re.I):
            continue
        level = int(heading.name[1]) if heading.name != "caption" else 1
        section = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag):
                # A peer section can have a wrapping div/section.  Do not copy
                # that entire wrapper (and its alerts/promotions) into hours.
                headings = ([sibling] if re.fullmatch(r"h[1-6]", sibling.name)
                            else sibling.select("h1, h2, h3, h4, h5, h6"))
                if any(int(peer.name[1]) <= level for peer in headings):
                    break
                if sibling.name in {"aside", "footer", "header", "nav"}:
                    break
                if {"node--type-notification", "node--type-promo"}.intersection(sibling.get("class", [])):
                    break
                text = _text(sibling)
                if text:
                    section.append(text)
        if section:
            values.append(" ".join(section))
    return "\n".join(dict.fromkeys(values))[:MAX_TEXT_CHARS] or None


def _booking_link(node: Tag, base: str, slug: str) -> str | None:
    for link in node.select("a[href]"):
        label = _text(link) or ""
        if not re.match(r"^(?:book\s+(?:now|online)|reserve\b|register\b|make\s+a\s+reservation)", label, re.I):
            continue
        url = _https_url(link.get("href"), base)
        if not url:
            continue
        parts = urlsplit(url)
        if parts.hostname not in _BOOKING_HOSTS:
            continue
        if parts.hostname == HOST and not parts.path.startswith("/parks/" + slug + "/"):
            continue
        if re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)|[<>]", url, re.I):
            continue
        return url
    return None


def parse_page(html: str, source_url: str, park_context: Mapping[str, object]) -> list[dict]:
    """Extract sparse activity candidates from one approved park listing/detail.

    Required context: park_slug, park_name, city, state, location_source_url.
    location_text may be omitted when the known park/city/state is sufficient.
    source_url is the activity link; extracted_from_url records the page actually
    supplied.  Unknown optional facts remain None, never zero/free/all-ages.
    """
    park, url, nodes, listing = _page(html, source_url, park_context)
    fragment = urlsplit(url).fragment
    page_url = url.split("#", 1)[0]
    records = []
    seen = set()
    for node in nodes:
        heading = _heading(node, listing)
        title = _text(heading, 512)
        if not title:
            raise ValueError("nova_activity_title_missing")
        if _is_donation(title, node):
            continue
        identity = _node_id(node)
        if fragment and fragment != "node-" + identity:
            continue
        external_id = "novaparks:node:" + identity
        if external_id in seen:
            continue
        seen.add(external_id)
        detail = _detail_link(node, heading, page_url, park["park_slug"]) if listing else page_url
        evidence_url = page_url + "#node-" + identity if listing else page_url
        body = node.select_one(".field--name-body, .field--name-field-listing-description")
        categories = [_text(item, 160) for item in node.select(".field--name-field-categories > .field__item")]
        categories = list(dict.fromkeys(value for value in categories if value))
        fees = node.select_one(".field--name-field-fees")
        record = {
            "external_id": external_id,
            "title": title,
            "source_url": detail or evidence_url,
            "extracted_from_url": page_url,
            **park,
            "description": _text(body),
            "image_url": _image(node, page_url),
            "source_categories": categories or None,
            "availability_text": _labelled_text(node, r"(?:opening\s+)?hours(?:\s+of\s+operation)?|season(?:al\s+hours)?"),
            "price_text": _text(fees) or _labelled_text(node, r"fees|admission(?:\s+fees)?|prices?"),
            "booking_url": _booking_link(node, page_url, park["park_slug"]),
        }
        records.append(record)
    return records


def discover_links(html: str, source_url: str, park_context: Mapping[str, object]) -> list[str]:
    """Find bounded activity detail pages; never enqueue same-page fragments.

    Cross-park attractions, PDF maps, booking hosts, events, donations, and
    sitewide menus/promotions do not expand this pilot's crawl scope.
    """
    park, url, nodes, listing = _page(html, source_url, park_context)
    page_url = url.split("#", 1)[0]
    found = []
    for node in nodes:
        title = _text(_heading(node, listing), 512)
        if not title:
            raise ValueError("nova_activity_title_missing")
        if _is_donation(title, node):
            continue
        for link in node.select("a[href]"):
            target = _park_url(link.get("href"), page_url, park["park_slug"])
            if not target:
                continue
            target = target.split("#", 1)[0]
            if ("/things-to-do/" not in urlsplit(target).path or target == page_url
                    or target.endswith("/adopt-an-animal") or target in found):
                continue
            found.append(target)
            if len(found) > MAX_LINKS:
                raise ValueError("nova_link_limit")
    return found
