"""Boston outdoor, fitness and community programs from their official publishers.

Squarespace's permitted HTML carries complete event bodies; its JSON/ICS exports
are deliberately not requested. Detail calendars resume as complete snapshots
using the existing durable collector contract. Boston.gov RSS needs a reviewed
wall-clock correction: its visible Eastern times are mislabeled with ``Z``.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_community import _google_times
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = "America/New_York"
FOOD_FOREST = "boston_food_forest_coalition_ma"
BACKYARD = "backyard_boston_ma"
TITUS = "titus_sparrow_park_ma"
CRWA = "charles_river_watershed_ma"
GATORS = "new_england_gator_club_ma"
CITY = "city_of_boston_events_ma"
CYCLISTS = "municipal_mapsee_a14b1d13603f6a7a9b6eadba"
SOURCES = {
    FOOD_FOREST: ("https://www.bostonfoodforest.org/workshops", "html", "html"),
    BACKYARD: ("https://www.backyardbos.com/upcoming-events", "html", "html"),
    TITUS: ("https://www.titussparrowpark.org/events", "html", "html"),
    CRWA: ("https://www.crwa.org/events", "html", "html"),
    GATORS: ("https://newenglandgatorclub.org/events", "html", "html"),
    CITY: ("https://www.boston.gov/rss/events", "html", "html"),
    # Repair the existing source identity. The guarded migration changes only
    # its empty legacy JSON/WordPress adapter to this complete-description path.
    CYCLISTS: ("https://bostoncyclistsunion.org", "html", "html"),
}
LABELS = {
    FOOD_FOREST: "Boston Food Forest Coalition",
    BACKYARD: "Backyard Boston",
    TITUS: "Friends of Titus Sparrow Park",
    CRWA: "Charles River Watershed Association",
    GATORS: "New England Gator Club",
    CITY: "City of Boston Events",
    CYCLISTS: "Boston Cyclists Union",
}
SOURCE_NOTES = {
    FOOD_FOREST: "Official dated garden stewardship and workshops; full event HTML and per-event streets.",
    BACKYARD: "Official community fitness, fundraising and competition calendar; 5 Necco Street.",
    TITUS: "Official park, garden club and food-pantry programs; preserve each event's actual venue.",
    CRWA: "Official river ecology and community programs; virtual-only events held out of physical map results.",
    GATORS: "Official Boston watch parties and volunteer events; tentative/unlocated travel held.",
    CITY: "Official RSS, all 25 published items consumed; event times come from visible Eastern clocks, never pubDate.",
    CYCLISTS: "Existing empty source repaired through its official TEC REST feed; identity and native event IDs retained.",
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = {FOOD_FOREST, BACKYARD, TITUS, CRWA, GATORS}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
MAX_MANIFEST = 200
DETAILS_PER_CHUNK = 3
MAX_CHECKPOINT_BYTES = 900000
ERROR_CODES = {
    "unregistered_boston_community_source", "boston_community_description_limit",
    "boston_community_calendar_changed", "boston_community_detail_changed",
    "boston_community_feed_changed", "boston_community_record_limit",
    "boston_community_time_unverified", "boston_community_deadline",
    "boston_community_pagination_incomplete", "boston_community_checkpoint_invalid",
    "boston_community_checkpoint_limit", "boston_community_description_or_street_missing",
    "boston_community_not_public_event", "boston_community_schedule_conflict",
}
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|private event|date may change|closed|closure)\b", re.I)
REMOTE = re.compile(r"\b(?:virtual|via zoom|online only|webinar|tbd|to be determined)\b", re.I)
LOCALITIES = {
    "Boston", "Jamaica Plain", "Mattapan", "Dorchester", "Roxbury", "West Roxbury",
    "Roslindale", "Hyde Park", "Allston", "Brighton", "Charlestown", "East Boston",
    "Cambridge", "Somerville", "Medford", "Brookline", "Chestnut Hill", "Watertown",
    "Arlington", "Belmont", "Everett", "Malden", "Chelsea", "Revere", "Quincy",
    "Newton", "Milton", "South Boston", "South End", "North End", "Winthrop",
}
# Official BPL branch and Union Church addresses fill publisher omissions only
# when both the venue identity and exact street agree. No default source HQ.
CITY_POSTAL_RESOLUTIONS = {
    ("Boston Public Library Mattapan", "1350 Blue Hill Ave", "Mattapan"): (
        "02126", "https://www.bpl.org/locations/mattapan/"),
    ("Union Church", "485 Columbus Avenue", "South End"): (
        "02118", "https://www.titussparrowpark.org/events"),
}
# Follow-up review of still-unpublished B1 venue rows, November 14, 2026.
# Match the exact source + native venue + full street only. Keep valid native
# streets intact; publisher target pins replace default/missing event OG maps.
# Google Maps !3d/!4d targets are used, never the @ viewport coordinates.
REVIEWED_EVENT_POINTS = {
    (FOOD_FOREST, "Uphams Corner Food Forest", "11 A Everett Avenue, Boston, MA 02125"): (
        (42.315585, -71.063221), "https://www.bostonfoodforest.org/locations",
        "Official food-forest locations page links the exact 11A Everett Avenue target pin; native event street retained."),
    (FOOD_FOREST, "Hope Garden", "424 Geneva Avenue, Boston, MA 02122"): (
        (42.3007808, -71.0667882), "https://www.bostonfoodforest.org/locations",
        "Official Hope Garden map target for 424-428A Geneva Avenue includes the native event's 424 address; native street retained."),
    (TITUS, "Museum of Fine Arts, Boston (MFA)", "465 Huntington Avenue, Boston, MA 02115"): (
        (42.339381, -71.094048), "https://artsandculture.google.com/partner/museum-of-fine-arts-boston",
        "Museum partner profile's exact address and Museum.geo, corroborated by MassGIS/MHC building BOS.7493; native street retained."),
    (TITUS, "Titus Sparrow Park", "75 West Rutland Square, Boston, MA 02118"): (
        (42.343569, -71.0797897), "https://www.titussparrowpark.org/",
        "Friends of Titus Sparrow Park's explicit map marker is tied to 75 West Rutland Square and ZIP 02118, corroborated by Boston SAM address 342665; native street retained."),
}
CITY_EXACT_LOCATION_REPAIRS = {
    ("Union Church", "485 Columbus Avenue, South End, MA 02118"): (
        "485 Columbus Avenue, South End, MA 02118", "South End", (42.3431615, -71.0791651),
        "https://www.unionboston.org/visit"),
}


def _full(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("boston_community_description_limit")
    return text


def _budget(deadline_at, reserve=8):
    if deadline_at is not None and monotonic() + reserve >= deadline_at:
        raise ValueError("boston_community_deadline")


def _hold(key, identity, reason, diagnostics):
    log.warning("boston_community_record_held source=%s id=%s reason=%s", key, identity, reason)
    diagnostics.append({"id": str(identity), "reason": reason})


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
                             source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_boston_community_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        prefix = ("/calendar/" if key == CITY else "/event/" if key == CYCLISTS
                  else urlsplit(SOURCES[key][0]).path.rstrip("/") + "/")
        return bool(p.scheme == "https" and p.netloc in ALLOWED_HOSTS[key] and not (p.query or p.fragment)
                    and p.path.startswith(prefix) and len(p.path) > len(prefix)
                    and re.fullmatch(r"/[A-Za-z0-9/_%-]+", p.path)
                    and not re.search(r"%2f|%5c|%2e", p.path, re.I))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        hosts = set(ALLOWED_HOSTS.get(key, ()))
        if key in CHECKPOINT_KEYS:
            hosts |= {"images.squarespace-cdn.com", "static1.squarespace.com"}
        return bool(p.scheme == "https" and p.netloc in hosts and not p.fragment
                    and ".." not in p.path.split("/")
                    and (p.path.startswith("/content/") or p.path.startswith("/wp-content/uploads/")))
    except ValueError:
        return False


def _point(lat, lng):
    try:
        if isinstance(lat, bool) or isinstance(lng, bool):
            return None
        lat, lng = float(lat), float(lng)
        if math.isfinite(lat) and math.isfinite(lng) and 42.1 <= lat <= 42.6 and -71.5 <= lng <= -70.8:
            return lat, lng
    except (TypeError, ValueError):
        pass
    return None


def _street(value):
    value = plain(value)
    match = re.fullmatch(
        r"(\d{1,6}(?:\s?[A-Za-z])?\s+.+?),\s*([^,]+),\s*(?:MA|Massachusetts),?\s*(\d{5}(?:-\d{4})?)"
        r"(?:,\s*(?:United States|USA))?", value, re.I)
    if not match or match[2] not in LOCALITIES or REMOTE.search(value):
        return None
    return f"{match[1]}, {match[2]}, MA {match[3]}", match[2]


def _within(start, end, now):
    return start is not None and start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _row(key, title, start, end, url, identity, body, venue, address, city, *, point=None,
         category="", image=None, provenance="Publisher's event-specific street address.", evidence=None):
    row = record(title, start.isoformat(), end.isoformat() if end else None, venue, address, city,
                 url, identity, category, lat=point[0] if point else None, lng=point[1] if point else None,
                 tz=ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                   location_provenance=provenance, location_evidence_url=evidence or url)
        if photo_url(key, image):
            row["image_url"] = image
    return row


def _manifest(key, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    if soup.select_one(".eventlist") is None:
        raise ValueError("boston_community_calendar_changed")
    out = []
    for card in soup.select("article.eventlist-event--upcoming"):
        anchor = card.select_one(".eventlist-title-link[href]")
        if anchor is None:
            raise ValueError("boston_community_calendar_changed")
        url = urljoin(SOURCES[key][0], anchor["href"])
        title = plain(anchor.get_text())
        start, end, facts = _google_times(card)
        if not event_url(key, url) or plain((facts.get("text") or [""])[0]) != title:
            raise ValueError("boston_community_calendar_changed")
        if not _within(start, end, now):
            continue
        venue = card.select_one(".eventlist-meta-address")
        if venue:
            venue = BeautifulSoup(str(venue), "html.parser")
            for a in venue.select("a"):
                a.decompose()
        excerpt = card.select_one(".eventlist-excerpt, .eventlist-description")
        out.append({"url": url, "title": title, "start": start.isoformat(),
                    "end": end.isoformat() if end else None,
                    "location": plain((facts.get("location") or [""])[0]),
                    "venue": plain(venue.get_text()) if venue else "",
                    "excerpt_hash": sha256(_full(str(excerpt or "")).encode()).hexdigest()})
    if len(out) > MAX_MANIFEST or len({c["url"] for c in out}) != len(out):
        raise ValueError("boston_community_record_limit")
    return out


def _detail_point(soup, main, location):
    """Bind event OG coordinates to the same street in visible/export/map data.

    Squarespace default NYC marker points are rejected by the Boston bounds.
    This does not use the website's general location or a map viewport from a
    different event. A missing or contradictory point goes to street geocoding.
    """
    lat = soup.select('meta[property="og:latitude"]')
    lng = soup.select('meta[property="og:longitude"]')
    maps = main.select(".eventitem-meta-address-maplink[href]")
    lines = main.select(".eventitem-meta-address-line:not(.eventitem-meta-address-line--title)")
    if len(lat) != 1 or len(lng) != 1 or len(maps) != 1 or not lines:
        return None
    target = urlsplit(maps[0]["href"])
    query = parse_qs(target.query).get("q")
    if target.hostname not in ("maps.google.com", "www.google.com") or len(query or []) != 1:
        return None
    fingerprint = lambda v: re.sub(r"[^a-z0-9]", "", plain(v).casefold())
    visible = " ".join(n.get_text(" ", strip=True) for n in lines)
    if fingerprint(query[0]) != fingerprint(location) or fingerprint(visible) != fingerprint(location):
        return None
    return _point(lat[0].get("content"), lng[0].get("content"))


def _squarespace_detail(key, card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.select_one(".eventitem")
    title = main.select_one(".eventitem-title") if main else None
    body = main.select_one(".eventitem-column-content .sqs-layout") if main else None
    canonical = soup.select('meta[property="og:url"]')
    if (title is None or body is None or len(canonical) != 1 or canonical[0].get("content") != card["url"]):
        raise ValueError("boston_community_detail_changed")
    title = plain(title.get_text())
    start, end, facts = _google_times(main)
    venue = main.select_one(".eventitem-meta-address-line--title")
    venue = plain(venue.get_text()) if venue else ""
    location = plain((facts.get("location") or [""])[0])
    if (title != card["title"] or start is None or start.isoformat() != card["start"]
            or (end.isoformat() if end else None) != card["end"] or location != card["location"]
            or venue != card["venue"] or plain((facts.get("text") or [""])[0]) != title):
        raise ValueError("boston_community_detail_changed")
    text, address = _full(str(body)), _street(location)
    if NONPUBLIC.search(title):
        _hold(key, card["url"], "boston_community_not_public_event", diagnostics)
        return None
    if not text or not address or not venue:
        _hold(key, card["url"], "boston_community_description_or_street_missing", diagnostics)
        return None
    # The November Leland work-party header currently ends at 11:30 while its
    # complete narrative explicitly says the work/picnic runs until 4 PM. Hold
    # that contradiction rather than silently selecting one publisher time.
    if (key == FOOD_FOREST and "Leland Cooperative Garden Work Party/Picnic" in title
            and re.search(r"10:30\s*AM\s*[-–]\s*4\s*PM", text, re.I)
            and (end is None or (end.astimezone(ZoneInfo(ZONE)).hour,
                                 end.astimezone(ZoneInfo(ZONE)).minute) != (16, 0))):
        _hold(key, card["url"], "boston_community_schedule_conflict", diagnostics)
        return None
    if not _within(start, end, now):
        _hold(key, card["url"], "outside_current_window", diagnostics)
        return None
    point = _detail_point(soup, main, location)
    image = body.select_one("img[data-src], img[src]")
    image = (image.get("data-src") or image.get("src")) if image else None
    if not image:
        meta = soup.select_one('meta[property="og:image"]')
        image = meta.get("content") if meta else None
    provenance = ("Publisher event address, export and map destination agree; event OG point within Boston bounds."
                  if point else "Publisher event-specific full street; missing/default/conflicting coordinates left for geocoding.")
    evidence = card["url"]
    if reviewed := REVIEWED_EVENT_POINTS.get((key, venue, address[0])):
        point, evidence, provenance = reviewed
    row = _row(key, title, start, end, card["url"], sha256(urlsplit(card["url"]).path.encode()).hexdigest(),
               text, venue, address[0], address[1], point=point, image=image, provenance=provenance,
               evidence=evidence,
               category=", ".join(plain(a.get_text()) for a in main.select(".eventitem-meta-cats a, .eventitem-meta-tags a")))
    if row is None:
        _hold(key, card["url"], "outside_current_window", diagnostics)
    return row


def _checkpoint_rows_valid(key, state, manifest):
    prefix = {c["url"]: c for c in manifest[:state["cursor"]]}
    seen = set()
    for row in state["events"]:
        card = prefix.get(row.get("event_url")) if isinstance(row, dict) else None
        place = _street(card["location"]) if card else None
        if (not card or not place or row["event_url"] in seen
                or row.get("id") != sha256(urlsplit(card["url"]).path.encode()).hexdigest()
                or row.get("title") != card["title"] or row.get("starts_at") != card["start"]
                or row.get("ends_at") != card["end"] or row.get("venue_name") != card["venue"]
                or row.get("venue_address") != place[0] or row.get("timezone") != ZONE
                or not isinstance(row.get("description"), str) or not row["description"].strip()
                or len(row["description"]) > MAX_DESCRIPTION
                or ((row.get("lat") is not None or row.get("lng") is not None)
                    and _point(row.get("lat"), row.get("lng")) is None)
                or (row.get("image_url") and not photo_url(key, row["image_url"]))):
            return False
        seen.add(row["event_url"])
    for diag in state["diagnostics"]:
        if (not isinstance(diag, dict) or diag.get("id") not in prefix or diag["id"] in seen
                or diag.get("reason") not in ERROR_CODES | {"outside_current_window"}):
            return False
        seen.add(diag["id"])
    return seen == set(prefix)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError("unregistered_boston_community_source")
    now = now or datetime.now(timezone.utc)
    state = deepcopy(checkpoint) if checkpoint is not None else None
    anchor = now
    if state is not None:
        try:
            started = datetime.fromisoformat(state["started_at"])
            valid = (state["version"] == 1 and state["source_key"] == key
                     and type(state["cursor"]) is int and type(state["manifest_count"]) is int
                     and 0 <= state["cursor"] <= state["manifest_count"] <= MAX_MANIFEST
                     and re.fullmatch(r"[a-f0-9]{64}", state["manifest_hash"])
                     and isinstance(state["events"], list) and len(state["events"]) <= state["cursor"]
                     and isinstance(state["diagnostics"], list) and len(state["diagnostics"]) <= state["cursor"]
                     and started.tzinfo is not None and now.tzinfo is not None
                     and state["window_start"] == started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                     and timedelta(0) <= now - started <= timedelta(hours=4))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("boston_community_checkpoint_invalid")
        anchor = started
    if now.tzinfo is None:
        raise ValueError("boston_community_checkpoint_invalid")
    _budget(deadline_at)
    payload = fetch(SOURCES[key][0], "text/html")
    manifest = _manifest(key, payload, anchor)
    digest = sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is not None:
        if state["manifest_hash"] != digest or state["manifest_count"] != len(manifest):
            state = None
        elif not _checkpoint_rows_valid(key, state, manifest):
            raise ValueError("boston_community_checkpoint_invalid")
    if state is None:
        manifest = _manifest(key, payload, now)
        digest = sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        state = {"version": 1, "source_key": key, "started_at": now.isoformat(),
                 "window_start": now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 "manifest_hash": digest, "manifest_count": len(manifest), "cursor": 0,
                 "events": [], "diagnostics": []}
    for index in range(state["cursor"], min(len(manifest), state["cursor"] + DETAILS_PER_CHUNK)):
        if deadline_at is not None and monotonic() + 18 >= deadline_at:
            break
        card = manifest[index]
        row = _squarespace_detail(key, card, fetch(card["url"], "text/html"), now, state["diagnostics"])
        if row:
            state["events"].append(row)
        state["cursor"] = index + 1
    if len(json.dumps(state).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("boston_community_checkpoint_limit")
    complete = state["cursor"] == len(manifest)
    return {"complete": complete, "events": deepcopy(state["events"]) if complete else [],
            "checkpoint": state, "diagnostics": state["diagnostics"]}


def _rss_clock(node):
    raw = node.get("datetime", "")
    visible = plain(node.get_text()).replace(" ", "")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    # Review requires the visible day and clock to corroborate the wall-time
    # correction; do not make this assumption for a changed feed format.
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4}).*?(\d{1,2}):(\d{2})(am|pm)", visible, re.I)
    if not match:
        raise ValueError("boston_community_time_unverified")
    month, day, year, hour, minute = (int(match[x]) for x in range(1, 6))
    hour = hour % 12 + (12 if match[6].lower() == "pm" else 0)
    if (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute) != (year, month, day, hour, minute):
        raise ValueError("boston_community_time_unverified")
    return timestamp(parsed.replace(tzinfo=None).isoformat(), ZONE)


def _city(payload, now, diagnostics):
    xml = BeautifulSoup(payload, "xml")
    channel = xml.find("channel")
    if not channel or not channel.title or channel.title.get_text() != "City of Boston Events":
        raise ValueError("boston_community_feed_changed")
    items, out = channel.find_all("item", recursive=False), {}
    if len(items) > MAX_RECORDS:
        raise ValueError("boston_community_record_limit")
    for item in items:
        link = item.link.get_text().strip() if item.link else ""
        title = plain(item.title.get_text()) if item.title else ""
        if not title or not event_url(CITY, link) or not item.description:
            raise ValueError("boston_community_feed_changed")
        soup = BeautifulSoup(item.description.get_text(), "html.parser")
        venue_node = soup.select_one(".address")
        if not venue_node or REMOTE.search(venue_node.get_text(" ", strip=True)) or NONPUBLIC.search(title):
            _hold(CITY, link, "boston_community_description_or_street_missing", diagnostics)
            continue
        field = lambda selector: plain(venue_node.select_one(selector).get_text()) if venue_node.select_one(selector) else ""
        venue, street, city, postal = field(".address-line1"), field(".address-line2"), field(".locality"), field(".postal-code")
        state = field(".administrative-area")
        if state and state not in {"MA", "Massachusetts"}:
            continue
        evidence = link
        if not postal and (venue, street, city) in CITY_POSTAL_RESOLUTIONS:
            postal, evidence = CITY_POSTAL_RESOLUTIONS[(venue, street, city)]
        address = _street(f"{street}, {city}, MA {postal}")
        dates = soup.select(".date-recur-date")
        if not address or not dates:
            _hold(CITY, link, "boston_community_description_or_street_missing", diagnostics)
            continue
        occurrences = []
        for dates_node in dates:
            clocks = dates_node.select("time[datetime]")
            if not 1 <= len(clocks) <= 2:
                raise ValueError("boston_community_time_unverified")
            start = _rss_clock(clocks[0])
            end = _rss_clock(clocks[1]) if len(clocks) == 2 else None
            if end and end <= start:
                raise ValueError("boston_community_schedule_conflict")
            if _within(start, end, now):
                occurrences.append((start, end))
        for node in soup.select(".date-recur-date, .address"):
            node.decompose()
        for p in soup.find_all("p"):
            label = p.find("b")
            if label and plain(label.get_text()).rstrip(":") in {"Event Date", "Address", "Contact Department", "Publish Date"}:
                p.decompose()
        text = _full(str(soup))
        if not text:
            _hold(CITY, link, "boston_community_description_or_street_missing", diagnostics)
            continue
        point = None
        provenance = "Official City of Boston event street; exact venue/street ZIP resolutions only where omitted."
        if reviewed := CITY_EXACT_LOCATION_REPAIRS.get((venue, address[0])):
            street, city, point, evidence = reviewed
            address = (street, city)
            provenance = "Church's official 485 Columbus Avenue, Boston address and matching native businessLocationCoordinates corroborate the unchanged City South End street."
        for start, end in occurrences:
            identity = sha256((urlsplit(link).path + "|" + start.isoformat()).encode()).hexdigest()
            row = _row(CITY, title, start, end, link, identity, text, venue, address[0], address[1],
                       point=point, category="Civic & Community", evidence=evidence, provenance=provenance)
            if row:
                if identity in out and out[identity] != row:
                    raise ValueError("boston_community_feed_changed")
                out[identity] = row
    return sorted(out.values(), key=lambda e: (e["starts_at"], e["id"]))


def _cyclists(fetch, now, deadline_at, diagnostics):
    query = {"start_date": now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
             "end_date": (now.astimezone(ZoneInfo(ZONE)).date() + timedelta(days=60)).isoformat(),
             "per_page": 100, "page": 1}
    events, seen, total, pages = [], set(), None, None
    for page in range(1, 6):
        _budget(deadline_at)
        query["page"] = page
        data = json.loads(fetch("https://bostoncyclistsunion.org/wp-json/tribe/events/v1/events?" + urlencode(query), "application/json"))
        if (not isinstance(data, dict) or not isinstance(data.get("events"), list)
                or type(data.get("total")) is not int or type(data.get("total_pages")) is not int):
            raise ValueError("boston_community_feed_changed")
        if total is None:
            total, pages = data["total"], data["total_pages"]
            if not 0 <= total <= MAX_RECORDS or not 0 <= pages <= 5:
                raise ValueError("boston_community_record_limit")
        if (data["total"], data["total_pages"]) != (total, pages):
            raise ValueError("boston_community_pagination_incomplete")
        for event in data["events"]:
            if not isinstance(event, dict) or not event.get("id") or event["id"] in seen:
                raise ValueError("boston_community_pagination_incomplete")
            seen.add(event["id"])
            events.append(event)
        if page >= pages:
            break
    if len(events) != total:
        raise ValueError("boston_community_pagination_incomplete")
    out = []
    for event in events:
        title, link, identity = plain(event.get("title")), event.get("url"), str(event["id"])
        if not title or not event_url(CYCLISTS, link):
            raise ValueError("boston_community_feed_changed")
        if NONPUBLIC.search(title) or event.get("all_day") or event.get("status") not in (None, "publish"):
            _hold(CYCLISTS, identity, "boston_community_not_public_event", diagnostics)
            continue
        if event.get("timezone") != ZONE:
            raise ValueError("boston_community_time_unverified")
        start, end = timestamp(event.get("start_date"), ZONE), timestamp(event.get("end_date"), ZONE)
        if start is None or (end and end <= start):
            raise ValueError("boston_community_time_unverified")
        if not _within(start, end, now):
            continue
        venue = event.get("venue") or {}
        if not isinstance(venue, dict):
            venue = {}
        address = _street(
            f"{plain(venue.get('address'))}, {plain(venue.get('city'))}, "
            f"{plain(venue.get('state') or venue.get('province'))} {plain(venue.get('zip'))}")
        text = _full(event.get("description"))
        if not text or not address or not plain(venue.get("venue")):
            _hold(CYCLISTS, identity, "boston_community_description_or_street_missing", diagnostics)
            continue
        point = _point(venue.get("geo_lat"), venue.get("geo_lng"))
        image = event.get("image") or {}
        row = _row(CYCLISTS, title, start, end, link, identity, text, plain(venue["venue"]), address[0], address[1],
                   point=point, image=image.get("url") if isinstance(image, dict) else None,
                   category=", ".join(plain(c.get("name")) for c in event.get("categories", []) if isinstance(c, dict)))
        if row:
            out.append(row)
    return out


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)
    if key == CITY:
        _budget(deadline_at)
        return _city(fetch(SOURCES[key][0], "application/rss+xml"), now, [])
    if key == CYCLISTS:
        return _cyclists(fetch, now, deadline_at, [])
    checkpoint = None
    for _ in range((MAX_MANIFEST + DETAILS_PER_CHUNK - 1) // DETAILS_PER_CHUNK + 1):
        part = collect_chunk(source, fetch, checkpoint=checkpoint, deadline_at=deadline_at, now=now)
        if part["complete"]:
            return part["events"]
        if checkpoint and checkpoint["cursor"] == part["checkpoint"]["cursor"]:
            raise ValueError("boston_community_deadline")
        checkpoint = part["checkpoint"]
    raise ValueError("boston_community_record_limit")
