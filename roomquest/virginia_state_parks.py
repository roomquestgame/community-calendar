"""First HTML adapter: official Virginia DCR State Parks events.
Independent from ICS / WordPress / JSON-LD collectors. No arbitrary URLs,
page images, guessed sessions or full-state scheduled crawling.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from importlib import resources
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record

ROOT = "https://www.dcr.virginia.gov"
CALENDAR = ROOT + "/state-parks/events"
TZ = ZoneInfo("America/New_York")
MAX_EVENT_PAGES = 10
MAX_LISTING_LINKS = 200
DATE = re.compile(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2})\b", re.I)
CLOCK = r"\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?"
TIMES = re.compile(rf"({CLOCK})\s*(?:-|–|—|to)\s*({CLOCK})", re.I)
EVENT_ID = re.compile(r"^[A-Za-z0-9-]{10,90}$")
OFFSITE = re.compile(r"\b(town hall|municipal building|civic center|city hall)\b", re.I)

# A publisher-supplied meeting street address is evidence of the actual venue.
# Extract it from the event description, NOT from the unrelated park address.
STREET_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Za-z][A-Za-z0-9.'/-]*"
    r"(?:\s+[A-Za-z0-9][A-Za-z0-9.'/-]*){0,7},\s*"
    r"[A-Za-z][A-Za-z .'-]{1,65},\s*VA\s*\d{5}(?:-\d{4})?\b",
    re.I,
)



def clean(value):
    return re.sub(r"\s+", " ", str(value)).strip(" \t:") if value else ""


@lru_cache(maxsize=1)
def catalog():
    with resources.files("roomquest").joinpath("virginia_state_parks_catalog.json").open(encoding="utf-8") as stream:
        data = json.load(stream)
    result = {park["code"].lower(): park for park in data["parks"]}
    if len(result) != 46:
        raise ValueError("park_catalog_incomplete")
    return result


def normal_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def label(lines, title):
    for index, value in enumerate(lines):
        match = re.fullmatch(re.escape(title) + r"\s*:?\s*(.*)", value, re.I)
        if match:
            if match.group(1).strip():
                return clean(match.group(1))
            for nxt in lines[index + 1:index + 4]:
                if nxt.lower().strip(" :") not in ("program location", "main park address", "where", "when", "location"):
                    return nxt
    return ""


def meeting_street_address(paragraphs, meeting_location):
    """Accept an address attached directly to the named meeting venue.

    A paragraph can describe several locations. Matching a venue name somewhere
    in that paragraph is not sufficient evidence for using its first address.
    Conflicting addresses stay unresolved; no park-coordinate substitution.
    """
    if not clean(meeting_location):
        return None
    name = re.compile(re.escape(clean(meeting_location)), re.I)
    addresses = {}
    for paragraph in paragraphs:
        for venue in name.finditer(paragraph):
            tail = paragraph[venue.end():]
            match = STREET_ADDRESS.search(tail)
            if not match:
                continue
            # Only punctuation and an explicit address introducer may separate
            # the venue name and its street. Reject travel/shipping prose.
            bridge = tail[:match.start()]
            if not re.fullmatch(
                r"[\s,:(-]*(?:(?:is\s+)?(?:located\s+at|address(?:\s+is)?\s*:?|at)\s*)?",
                bridge, re.I,
            ):
                continue
            address = clean(match.group(0))
            addresses[normal_name(address)] = address
    return next(iter(addresses.values())) if len(addresses) == 1 else None


def parse_event(html, url, park):
    """Extract actual DCR fields; park catalog supplies the approved park-level GPS."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup.select_one("article") or soup.body
    if main is None:
        raise ValueError("event_html_missing")
    section = BeautifulSoup(str(main), "html.parser")
    for el in section.select("script,style,nav,footer,noscript"):
        el.decompose()
    lines = [clean(t) for t in section.stripped_strings if clean(t)]
    text = "\n".join(lines)
    title_tag = section.find("h1")
    title = clean(title_tag.get_text(" ", strip=True)) if title_tag else ""
    if not title or title.lower() in ("events", "virginia state parks"):
        raise ValueError("event_title_missing")
    # The event page must identify the intended park, not merely the statewide catalog.
    main_address = label(lines, "Main Park Address")
    if normal_name(park["name"]) not in normal_name(main_address or text):
        # One long name has abbreviated punctuation in the historical DCR directory.
        if not (normal_name("Shenandoah River State Park") in normal_name(main_address or text) and park["code"] == "SH"):
            raise ValueError("event_park_mismatch")
    where = label(lines, "Program Location") or label(lines, "Meeting Location")
    paragraphs = [clean(t.get_text(" ", strip=True)) for t in section.select("p")]
    alternate_address = meeting_street_address(paragraphs, where)
    offsite = bool(alternate_address) or bool(where and OFFSITE.search(where))
    if offsite and not alternate_address:
        # Do not guess or substitute the park entrance for a separate venue.
        raise ValueError("offsite_venue_requires_address")
    when_match = re.search(r"\bWhen\b[\s\S]{0,240}", text, re.I)
    when_text = when_match.group(0) if when_match else text
    found_date = DATE.search(when_text) or DATE.search(text)
    found_times = TIMES.search(when_text) or TIMES.search(text)
    if not found_date or not found_times:
        raise ValueError("event_schedule_missing")
    date_str = re.sub(r"(?<=\w)\.(?=\s+\d)", "", found_date.group(1)).replace(",", "")
    day = None
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            day = datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            continue
    if day is None:
        raise ValueError("event_date_invalid")

    def clock(value):
        value = re.sub(r"[.\s]", "", value).upper()
        for fmt in ("%I:%M%p", "%I%p"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
        raise ValueError("event_time_invalid")

    start = datetime.combine(day, clock(found_times.group(1)), TZ)
    end = datetime.combine(day, clock(found_times.group(2)), TZ)
    if end <= start:
        raise ValueError("event_end_invalid")

    desc = next((t for t in paragraphs if len(t) > 55 and not t.startswith("Know Before You Go")), "")
    if offsite:
        # Keep the venue/room instructions even when the first long paragraph
        # is only an introduction to the sponsoring organization.
        venue_paragraph = next((t for t in paragraphs
            if meeting_street_address([t], where) == alternate_address), "")
        if venue_paragraph and venue_paragraph != desc:
            desc = venue_paragraph + ("\n\n" + desc if desc else "")
    if where and where.lower() not in desc.lower():
        desc = "Meeting Location: " + where + ("\n\n" + desc if desc else "")
    venue_name = where if offsite else park["name"]
    street = alternate_address if offsite else park["address"]
    parts = [clean(p) for p in street.split(",")]
    city = parts[-2] if len(parts) >= 3 else ""
    page_id = parse_qs(urlparse(url).query).get("id", [""])[0]
    if not EVENT_ID.fullmatch(page_id):
        raise ValueError("invalid_event_id")
    # In-park events use the reviewed park pin. Offsite activities use the
    # publisher's actual street address, never the unrelated park coordinates.
    # The shared demand-gated address cache/geocoder fills their GPS later.
    item = record(title, start.isoformat(), end.isoformat(), venue_name,
                  street, city, ROOT + "/state-parks/event?id=" + page_id,
                  "vsp:" + park["code"].lower() + ":" + page_id,
                  lat=None if offsite else park["lat"],
                  lng=None if offsite else park["lng"], tz="America/New_York",
                  publisher_geo=not offsite)
    if item is None:
        return None  # Outside normal forward discovery window.
    item["description"] = desc[:2000] if desc else None
    item["park_code"] = park["code"]
    item["location_provenance"] = (
        "publisher_offsite_street_pending_geocode" if offsite
        else "owner_reviewed_park_cache"
    )
    return item


def registered_calendar_url(park):
    """Only known official DCR park identifiers are approved for HTML collection."""
    official_id = park.get("dcr_calendar_id")
    if not isinstance(official_id, str) or not EVENT_ID.fullmatch(official_id):
        raise ValueError("unverified_park_calendar_identifier")
    return CALENDAR + "?park=" + official_id


def listing_url(park, *, today=None):
    """DCR's real calendar uses a park GUID and an explicit date window."""
    begin = today or datetime.now(TZ).date()
    until = begin + timedelta(days=60)
    return CALENDAR + "?" + urlencode({
        "park": park["dcr_calendar_id"],
        "start": begin.strftime("%m/%d/%Y"),
        "end": until.strftime("%m/%d/%Y"),
    })


def discover(html, park):
    soup = BeautifulSoup(html, "html.parser")
    found, seen, all_count = [], set(), 0
    target = normal_name(park["name"])
    # A park-filtered DCR listing may place the park heading outside the cards.
    filtered_park_heading = any(
        normal_name(node.get_text(" ", strip=True))
        == normal_name("Park: " + park["name"])
        for node in soup.select("h1,h2,h3,h4")
    )
    for link in soup.select('a[href*="/state-parks/event"]'):
        url = urljoin(CALENDAR, link.get("href", ""))
        parsed = urlparse(url)
        eid = parse_qs(parsed.query).get("id", [""])[0]
        if parsed.hostname != "www.dcr.virginia.gov" or parsed.path != "/state-parks/event" or not EVENT_ID.fullmatch(eid):
            continue
        all_count += 1
        # Use only event links in a card/context that actually names this park;
        # never fetch every statewide detail page for a single regional search.
        card_matches = filtered_park_heading
        node = link
        for _ in range(6 if not filtered_park_heading else 0):
            node = node.parent
            if node is None or node.name in ("body", "html", "main", "section"):
                break  # Never let another park's nearby card supply identity.
            classes = " ".join(node.get("class", []))
            boundary = (node.name in ("article", "li")
                or re.search(r"(event|card|result|teaser)", classes, re.I))
            text = clean(node.get_text(" ", strip=True))
            if boundary:
                card_matches = len(text) <= 1400 and target in normal_name(text)
                break
            # Some DCR templates use a small unclassified div per event.
            if node.name == "div" and len(text) <= 350 and target in normal_name(text):
                card_matches = True
                break
        if not card_matches or eid in seen:
            continue
        seen.add(eid)
        found.append(ROOT + "/state-parks/event?id=" + eid)
        if len(found) >= MAX_EVENT_PAGES:
            break
    if all_count > MAX_LISTING_LINKS:
        raise ValueError("calendar_listing_too_large")
    return found, all_count


def collect(source, fetch, *, deadline_at=None):
    """One approved registered park per claim. 'fetch' enforces network/robots limits."""
    import time
    source_key = source.get("source_key", "")
    match = re.fullmatch(r"virginia_state_parks_([a-z]{2})", source_key)
    if source.get("kind") != "html" or source.get("platform_adapter") != "html" or not match:
        raise ValueError("unregistered_html_source")
    park = catalog().get(match.group(1))
    if not park:
        raise ValueError("park_code_missing")
    expected = registered_calendar_url(park)
    if source.get("feed_url") != expected:
        raise ValueError("unregistered_html_calendar")
    deadline = min(time.monotonic() + 32, deadline_at or float("inf"))
    page = fetch(listing_url(park), "text/html")
    if time.monotonic() >= deadline:
        raise ValueError("collection_deadline")
    links, all_count = discover(page, park)
    if all_count and not links:
        # An unrecognized HTML listing is NOT a healthy empty source.
        raise ValueError("park_listing_structure_unverified")
    records = []
    for url in links:
        if time.monotonic() >= deadline:
            raise ValueError("collection_deadline")
        # Redirect resolution is owned by the existing vetted HTTP transport;
        # any off-domain redirect will be rejected there.
        detail = fetch(url, "text/html")
        try:
            item = parse_event(detail, url, park)
        except ValueError as exc:
            if str(exc) != "offsite_venue_requires_address":
                raise  # Unexpected parser errors must not publish partial snapshots.
            # Off-site events await their own verified venue coordinates. One
            # municipal meeting must not block the other valid park sessions.
            print("virginia_parks_offsite_skipped", source_key,
                  parse_qs(urlparse(url).query).get("id", [""])[0])
            continue
        if item:
            records.append(item)
    return records
