"""First HTML adapter: official Virginia DCR State Parks events.
Independent from ICS / WordPress / JSON-LD collectors. No arbitrary URLs,
guessed sessions or full-state scheduled crawling. Event photo candidates use
only the detail HTML already fetched; a separate worker verifies their bytes.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from functools import lru_cache
from importlib import resources
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup, Tag
from roomquest.collector_errors import safe_error_code
from roomquest.mapsee_adapter import record, timestamp

ROOT = "https://www.dcr.virginia.gov"
CALENDAR = ROOT + "/state-parks/events"
TZ = ZoneInfo("America/New_York")
MAX_EVENT_PAGES = 10
MAX_LISTING_LINKS = 200
IMAGE_EXTRACTOR_VERSION = "publisher_event_html_v2"
NON_EVENT_IMAGE = re.compile(
    r"(?:^|[^a-z0-9])(?:maps?|logo|logos|favicon|icon|avatar|pixel|tracking|"
    r"navigation|breadcrumb|social|banner|header|footer|sidebar|"
    r"licen[cs]e|licen[cs]e[-_ ]?plates?|vsp[-_ ]?plates?)(?:[^a-z0-9]|$)"
    r"|location of .+ (?:in|within) virginia", re.I,
)
NON_EVENT_SECTION = re.compile(
    r"^(?:know before you go|other events|related events|upcoming events|"
    r"park information|contact us|directions|location map|documents|other details|"
    r"event types|additional dates|add to calendar)\b", re.I,
)
DATE_TEXT = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2}"
CLOCK = r"\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?"
SCHEDULE = re.compile(rf"^({DATE_TEXT})\.?\s+({CLOCK})\s*(?:-|–|—|to)\s*"
                      rf"(?:({DATE_TEXT})\.?\s+)?({CLOCK})\.?$", re.I)
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


def event_photo_url(value, base_url="", description=""):
    """The same safe, non-boilerplate URL policy for extraction and verification."""
    from roomquest.preview_worker import event_image

    if isinstance(value, str) and not value.strip():
        return None
    try:
        image = event_image(value, base_url)
        if not image or NON_EVENT_IMAGE.search(unquote(urlparse(image).path) + " " + description):
            return None
    except (ValueError, TypeError):
        # An optional malformed image must not discard valid event facts.
        return None
    return image


def event_photo_candidate(soup, section, url, title):
    """Select unverified event imagery, never the page's generic first image.

    Structured data must identify this event. Inline images must be in DCR's
    unique event_description container, with descriptive publisher text.
    Ambiguous images fail closed. No network
    access occurs here; the media worker validates URLs, redirects and bytes.
    """
    def candidate(value, description=""):
        return event_photo_url(value, url, description)

    def same_event(value):
        if not isinstance(value, str):
            return False
        try:
            parsed = urlparse(urljoin(url, value))
        except (ValueError, TypeError):
            return False
        return (parsed.scheme == "https" and parsed.netloc == urlparse(url).netloc
                and parsed.path.rstrip("/") == "/state-parks/event"
                and parse_qs(parsed.query).get("id") == parse_qs(urlparse(url).query).get("id"))

    structured = set()
    for script in soup.select('script[type="application/ld+json"]')[:30]:
        try:
            pending = [json.loads(script.string or script.get_text())]
        except (ValueError, TypeError, RecursionError):
            continue
        # Bound graph traversal even when unrelated structured data is large.
        for _ in range(200):
            if not pending:
                break
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node[:200])
                continue
            if not isinstance(node, dict):
                continue
            pending.extend(value for value in node.values() if isinstance(value, (dict, list)))
            kinds = node.get("@type", [])
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if not any(str(kind).rsplit("/", 1)[-1].endswith("Event") for kind in kinds):
                continue
            if normal_name(node.get("name")) != normal_name(title):
                continue
            if any(not same_event(node[key]) for key in ("url", "@id") if node.get(key)):
                continue
            values = node.get("image", [])
            values = values if isinstance(values, list) else [values]
            for value in values[:5]:
                description = " ".join(str(value.get(key, "")) for key in ("caption", "name", "description")) if isinstance(value, dict) else ""
                if image := candidate(value, description):
                    structured.add(image)
    if structured:
        return next(iter(structured)) if len(structured) == 1 else None

    # Captured DCR pages put both event content and generic promotional cards
    # inside main. Only this publisher-owned description holds event imagery.
    descriptions = section.select("div#event_description")
    if len(descriptions) != 1:
        return None
    description_container = descriptions[0]
    inline = set()
    in_event, after_when = False, False
    for tag in section.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "img"]):
        if tag.name != "img":
            heading = clean(tag.get_text(" ", strip=True))
            if tag.name == "h1":
                if in_event:
                    break
                in_event = normal_name(heading) == normal_name(title)
            if in_event and NON_EVENT_SECTION.search(heading):
                break
            if in_event and heading.casefold() == "when":
                after_when = True
            continue
        if (not in_event or tag.find_parent("div", id="event_description") is not description_container
                or not (after_when or "image" in str(tag.get("itemprop", "")).split())):
            continue
        excluded = False
        for ancestor in [tag, *tag.parents]:
            if not isinstance(ancestor, Tag):
                continue
            signature = " ".join([str(ancestor.get("id", "")), " ".join(ancestor.get("class", []))])
            if (ancestor.name in ("header", "nav", "footer", "aside")
                    or ancestor.get("role") in ("navigation", "banner", "complementary", "contentinfo")
                    or ancestor.has_attr("hidden") or ancestor.get("aria-hidden") == "true"
                    or NON_EVENT_IMAGE.search(signature)
                    or re.search(r"(?:^|[ _-])(?:related|recommended)(?:[ _-]|$)", signature, re.I)):
                excluded = True
                break
            if ancestor.name == "a" and ancestor.get("href"):
                try:
                    linked = urlparse(urljoin(url, ancestor["href"]))
                except (ValueError, TypeError):
                    excluded = True
                    break
                if linked.path.rstrip("/").endswith("/event") and not same_event(ancestor["href"]):
                    excluded = True
                    break
        if excluded:
            continue
        figure = tag.find_parent("figure")
        caption = figure.find("figcaption") if figure else None
        description = clean(" ".join([clean(tag.get("alt")),
            clean(caption.get_text(" ", strip=True)) if caption else ""]))
        if len(description) < 20 or len(re.findall(r"[A-Za-z]+", description)) < 3:
            continue
        try:
            if any(tag.get(key) is not None and int(tag[key]) < minimum for key, minimum in (("width", 160), ("height", 90))):
                continue
        except (ValueError, TypeError):
            continue
        # src is the publisher's displayed image. Do not infer a lazy URL or
        # choose an arbitrary member of a gallery/srcset.
        if image := candidate(tag.get("src"), description):
            inline.add(image)
    return next(iter(inline)) if len(inline) == 1 else None


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


def primary_when(section):
    """Read only the value immediately after the unique primary When heading."""
    headings = [tag for tag in section.find_all(re.compile(r"^h[1-6]$"))
                if clean(tag.get_text(" ", strip=True)).casefold() == "when"]
    if len(headings) != 1:
        raise ValueError("event_schedule_missing" if not headings else "event_schedule_ambiguous")
    for node in headings[0].next_siblings:
        text = clean(node.get_text(" ", strip=True)) if isinstance(node, Tag) else clean(str(node))
        if not text:
            continue
        if isinstance(node, Tag) and re.fullmatch(r"h[1-6]", node.name):
            break
        return text
    raise ValueError("event_schedule_missing")


def parse_schedule(value):
    """Accept explicit same-day or start-date/time to end-date/time schedules."""
    match = SCHEDULE.fullmatch(clean(value))
    if not match:
        raise ValueError("event_schedule_missing")
    start_date, start_clock, end_date, end_clock = match.groups()

    def day(value):
        date_str = re.sub(r"(?<=\w)\.(?=\s+\d)", "", value).replace(",", "")
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        raise ValueError("event_date_invalid")

    def clock(value):
        value = re.sub(r"[.\s]", "", value).upper()
        for fmt in ("%I:%M%p", "%I%p"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
        raise ValueError("event_time_invalid")

    start_day = day(start_date)
    end_day = day(end_date) if end_date else start_day
    start = timestamp(datetime.combine(start_day, clock(start_clock)).isoformat(), TZ.key)
    end = timestamp(datetime.combine(end_day, clock(end_clock)).isoformat(), TZ.key)
    if end <= start:
        # No invented next day for a time-only overnight range.
        raise ValueError("event_end_invalid")
    return start, end


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
    start, end = parse_schedule(primary_when(section))

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
    item["image_extractor_version"] = IMAGE_EXTRACTOR_VERSION
    evidence_url = ROOT + "/state-parks/event?id=" + page_id
    if image := event_photo_candidate(soup, section, evidence_url, title):
        item["image_url"] = image
        item["image_provenance"] = IMAGE_EXTRACTOR_VERSION
        item["image_evidence_url"] = evidence_url
    return item


def registered_calendar_url(park):
    """Use the vetted GUID, or the official all-parks calendar as lookup only."""
    official_id = park.get("dcr_calendar_id")
    if official_id is None:
        # Unique historical per-source registry identity. The old srchloc
        # parameter is NOT trusted as a park filter: collect() instead
        # resolves the official GUID through DCR's park picker.
        return CALENDAR + "?eventtype=all&srchloc=" + park["code"]
    if not isinstance(official_id, str) or not EVENT_ID.fullmatch(official_id):
        raise ValueError("unverified_park_calendar_identifier")
    return CALENDAR + "?park=" + official_id


def discover_calendar_id(html, park):
    """Read a park's GUID from DCR's actual calendar select; never guess it."""
    soup = BeautifulSoup(html, "html.parser")
    target = normal_name(park["name"])
    matches = set()
    for select in soup.select("select"):
        signature = normal_name(" ".join([
            select.get("name", ""), select.get("id", ""),
            select.get("aria-label", ""),
        ]))
        if "park" not in signature:
            continue
        for option in select.select("option[value]"):
            if normal_name(option.get_text(" ", strip=True)) != target:
                continue
            value = clean(option.get("value"))
            if EVENT_ID.fullmatch(value) and value.lower() != "all":
                matches.add(value)
    if len(matches) != 1:
        raise ValueError("park_calendar_identifier_missing_or_ambiguous")
    return next(iter(matches))


def listing_url(park, *, today=None, calendar_id=None):
    """Filter event listing to exactly one park in the next 60-day window."""
    official_id = calendar_id or park.get("dcr_calendar_id")
    if not isinstance(official_id, str) or not EVENT_ID.fullmatch(official_id):
        raise ValueError("unverified_park_calendar_identifier")
    begin = today or datetime.now(TZ).date()
    until = begin + timedelta(days=60)
    return CALENDAR + "?" + urlencode({
        "park": official_id,
        "start": begin.strftime("%m/%d/%Y"),
        "end": until.strftime("%m/%d/%Y"),
    })


def discover(html, park):
    soup = BeautifulSoup(html, "html.parser")
    found, seen, all_count = [], set(), 0
    target = normal_name(park["name"])
    # A park-filtered DCR listing may place the park heading outside the cards.
    headings = [clean(node.get_text(" ", strip=True))
                for node in soup.select("h1,h2,h3,h4")]
    filtered_park_heading = any(
        normal_name(heading) == normal_name("Park: " + park["name"])
        for heading in headings
    )
    for link in soup.select("a[href]"):
        # Live DCR cards use page-relative event?id=..., unlike our original
        # root-relative fixtures. Resolve first, then validate the full URL.
        try:
            url = urljoin(CALENDAR, link.get("href", ""))
            parsed = urlparse(url)
            ids = parse_qs(parsed.query).get("id", [])
            if (parsed.scheme != "https" or parsed.hostname != "www.dcr.virginia.gov"
                    or parsed.username is not None or parsed.password is not None
                    or parsed.port not in (None, 443)
                    or parsed.path != "/state-parks/event" or len(ids) != 1
                    or not EVENT_ID.fullmatch(ids[0])):
                continue
            eid = ids[0]
        except (TypeError, ValueError):
            continue
        all_count += 1
        if all_count > MAX_LISTING_LINKS:
            raise ValueError("calendar_listing_too_large")
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
        if len(found) < MAX_EVENT_PAGES:
            found.append(ROOT + "/state-parks/event?id=" + eid)
    if not found:
        # A successful HTTP response is not proof of an empty calendar. DCR
        # explicitly states '(0) Events Found' under the selected park heading.
        # Missing links on any other page must be reported as a parser failure.
        counts = {int(value) for heading in headings for value in re.findall(
            r"\(\s*(\d+)\s*\)\s*Events?\s+Found\b", heading, re.I)}
        if all_count or not filtered_park_heading or counts != {0}:
            raise ValueError("park_listing_structure_unverified")
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
    calendar_id = park.get("dcr_calendar_id")
    if calendar_id is None:
        # The state's own park picker provides stable official GUIDs. Fetch
        # this bootstrap page only for the demanded park; never scan statewide
        # event details or guess a code from another park's calendar.
        bootstrap = fetch(CALENDAR + "?park=all", "text/html")
        if time.monotonic() >= deadline:
            raise ValueError("collection_deadline")
        calendar_id = discover_calendar_id(bootstrap, park)
    page = fetch(listing_url(park, calendar_id=calendar_id), "text/html")
    if time.monotonic() >= deadline:
        raise ValueError("collection_deadline")
    links, all_count = discover(page, park)
    print("virginia_parks_listing", source_key, "links", all_count,
          "selected", len(links))
    records = []
    for url in links:
        if time.monotonic() >= deadline:
            raise ValueError("collection_deadline")
        # Redirect resolution is owned by the existing vetted HTTP transport;
        # any off-domain redirect will be rejected there.
        try:
            detail = fetch(url, "text/html")
            item = parse_event(detail, url, park)
        except ValueError as exc:
            # This public event ID and registered source key identify the
            # failing page without logging publisher bodies or exception text.
            event_id = parse_qs(urlparse(url).query).get("id", [""])[0]
            print(json.dumps({"event": "virginia_parks_event_error", "source_key": source_key,
                              "event_id": event_id if EVENT_ID.fullmatch(event_id) else None,
                              "error_code": safe_error_code(exc)}, sort_keys=True), file=sys.stderr)
            if str(exc) != "offsite_venue_requires_address":
                raise  # Unexpected parser errors must not publish partial snapshots.
            # Off-site events await their own verified venue coordinates. One
            # municipal meeting must not block the other valid park sessions.
            print("virginia_parks_offsite_skipped", source_key,
                  parse_qs(urlparse(url).query).get("id", [""])[0])
            continue
        if item:
            records.append(item)
    print("virginia_parks_records", source_key, len(records))
    return records
