"""Bound one publisher-owned venue address to already-collected HTML events.

This is a shared HTML capability, not a source table. A calendar may request
one ordinary same-host Contact/Visit page only when its complete event capture
contains addressless rows for the publisher venue itself. Off-site venues,
multiple candidate pages and ambiguous address pages remain unresolved.
"""
from copy import deepcopy
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)
STREET = re.compile(
    r"\b(\d{1,5}(?:\s*-\s*\d{1,5})?\s+"
    # A street name starts with a letter. This prevents a preceding telephone
    # number from being absorbed as the building number when footer strings
    # are joined across adjacent nodes.
    r"[A-Za-z][A-Za-z0-9'&. -]{1,89}?\s+"
    r"(?:Road|Rd|Street|St|Lane|Ln|Avenue|Ave|Square|Sq|Way|Drive|Dr|"
    r"Place|Pl|Terrace|Gardens|Northside|Southside|Eastside|Westside))"
    r"\s*,?\s*London\s*,?\s*(" + POSTCODE.pattern + r")\b", re.I)
CONTACT_LABELS = {"contact", "contact us", "visit us", "your visit", "plan your visit"}


def _plain(value):
    return re.sub(r"\s+", " ", value or "").strip()


def _key(value):
    return re.sub(r"[^a-z0-9]+", " ", _plain(value).casefold()).strip()


def _root_venue(value):
    return _plain(re.split(r"\s+[-–—]\s+", value or "", maxsplit=1)[0])


def contact_link(soup, base_url):
    """Return exact same-host publisher contact/visit page candidates."""
    host = urlsplit(base_url).netloc
    found = set()
    for node in soup.select("a[href]"):
        if _key(node.get_text(" ", strip=True)) not in CONTACT_LABELS:
            continue
        target = urljoin(base_url, node.get("href", ""))
        parsed = urlsplit(target)
        if (parsed.scheme == "https" and parsed.netloc == host and not parsed.query
                and not parsed.fragment and target != base_url and len(target) <= 1000):
            found.add(target)
    return found


def contact_identity(url):
    """Collapse only a page's optional trailing slash, retaining its host/path."""
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed.scheme, parsed.netloc, path


def _addresses(soup):
    strings = [_plain(value) for value in soup.stripped_strings if _plain(value)]
    found = set()
    # Publisher templates split semantic addresses across short adjacent nodes.
    for start in range(len(strings)):
        for size in range(1, 6):
            value = " ".join(strings[start:start + size])
            if len(value) > 240:
                break
            for match in STREET.finditer(value):
                street = _plain(match[1]).replace(" - ", "-")
                postcode = _plain(match[2]).upper()
                found.add(f"{street}, London, {postcode}, United Kingdom")
    return found


def apply(rows, payload, contact_url):
    """Fill only addressless rows that name the contact page's own venue."""
    if not rows or not isinstance(payload, str) or not isinstance(contact_url, str):
        return None
    unresolved = [row for row in rows if not _plain(row.get("venue_address"))]
    if not unresolved:
        return rows
    roots = {_root_venue(row.get("venue_name")) for row in unresolved}
    if len(roots) != 1 or not next(iter(roots)):
        return None
    root = next(iter(roots))
    soup = BeautifulSoup(payload, "html.parser")
    sites = [_plain(node.get("content")) for node in
             soup.select('meta[property="og:site_name"][content]')]
    body = _plain(soup.get_text(" ", strip=True))
    if not ((len(sites) == 1 and _key(sites[0]) == _key(root))
            or re.search(r"\b" + re.escape(root) + r"\b", body, re.I)):
        return None
    addresses = _addresses(soup)
    if len(addresses) != 1:
        return None
    address = next(iter(addresses))
    completed = []
    for original in rows:
        row = deepcopy(original)
        if not _plain(row.get("venue_address")):
            if _key(_root_venue(row.get("venue_name"))) != _key(root):
                return None
            row["venue_address"] = address
            row["venue_city"] = "London"
            row["location_provenance"] = "publisher_contact_street_pending_geocode"
            details = row.get("publisher_details")
            row["publisher_details"] = dict(details) if isinstance(details, dict) else {}
            row["publisher_details"]["venue_address_evidence_url"] = contact_url
        completed.append(row)
    return completed
