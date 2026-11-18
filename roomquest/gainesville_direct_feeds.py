"""Direct Gainesville/Flowery Branch publisher feeds on existing TEC, ICS and RSS lanes.

These are first-party calendars, not Mapsee catalog source identities. All venue
addresses are per-event or tied to an exact officially verified venue/branch.
Missing descriptions and images are allowed; offered text is never truncated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo
import json
import logging
import math
import re
import xml.etree.ElementTree as ET

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.gainesville_sources import _narrative, _street

ZONE = "America/New_York"
BRENAU = "brenau_public_events_ga"
MEEPLE = "meeple_madness_flowery_branch_ga"
LIBRARY = "hall_library_gainesville_ga"
# Exact publisher calendar IDs and official facility addresses, not guessed
# event locations or a default point for off-site events.
LIBRARY_VENUE = "Gainesville Library on the Square"
LIBRARY_STREET = "127 Main St NW, Gainesville, GA 30501"
LIBRARY_PROFILES = {
    LIBRARY: (18963, LIBRARY_VENUE, LIBRARY_STREET, "Gainesville"),
    "hall_library_blackshear_place_ga": (
        18964, "Blackshear Place Library", "2927 Atlanta Highway, Gainesville, GA 30507", "Gainesville"),
    "hall_library_east_hall_ga": (
        19167, "East Hall Library", "3911 P Davidson Road, Gainesville, GA 30507", "Gainesville"),
    "hall_library_murrayville_ga": (
        18965, "Murrayville Library", "4796 Thompson Bridge Road, Gainesville, GA 30506", "Gainesville"),
    "hall_library_north_hall_tech_ga": (
        18966, "North Hall Tech Center", "4175 Nopone Road Suite B, Gainesville, GA 30506", "Gainesville"),
    "hall_library_spout_springs_ga": (
        18955, "Spout Springs Library", "6488 Spout Springs Road, Flowery Branch, GA 30542", "Flowery Branch"),
}
SOURCES = {
    BRENAU: ("https://www.brenau.edu/wp-json/tribe/events/v1/events", "json", "wordpress"),
    MEEPLE: ("https://tockify.com/api/feeds/ics/meeplemadness", "ical", "ical"),
    **{key: (
        f"https://hallcountylibrary.libcal.com/rss.php?iid=6354&m=month&cid={profile[0]}",
        "rss", "library") for key, profile in LIBRARY_PROFILES.items()},
}
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
MAX_RECORDS = 500
WINDOW_DAYS = 60
MAX_DESCRIPTION = 12000
MEEPLE_STREET = "7400 Spout Springs Rd Suite 205, Flowery Branch, GA 30542"
MEEPLE_LOCATION = re.compile(
    r"^(?P<name>Meeple Madness(?:\s*-\s*[^,]{1,80})?),\s*"
    r"7400 Spout Springs Rd (?:suite|ste\.?|#)\s*205,\s*"
    r"Flowery Branch,\s*GA\s*30542(?:,\s*USA)?$", re.I)
CANCEL = re.compile(r"\b(?:cancelled|canceled|postponed|invitation only|private event|members? only)\b", re.I)
VIRTUAL = re.compile(r"\b(?:zoom|virtual|online only)\b", re.I)
LOGGER = logging.getLogger(__name__)


def event_url(key, url):
    if key not in SOURCES or not isinstance(url, str):
        return False
    u = urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.query or u.fragment:
        return False
    if key == BRENAU:
        return bool(u.hostname == "www.brenau.edu" and
            re.fullmatch(r"/event/[a-z0-9]+(?:-[a-z0-9]+)*/(?:20\d{2}-\d{2}-\d{2}/)?", u.path))
    if key == MEEPLE:
        return bool(u.hostname == "events.meeplemadness.com" and
            re.fullmatch(r"/meeplemadness/detail/\d{1,7}/\d{10,16}", u.path))
    return bool(u.hostname == "hallcountylibrary.libcal.com" and
        re.fullmatch(r"/event/\d{5,12}", u.path))


def photo_url(key, value):
    if key != BRENAU or not isinstance(value, str) or len(value) > 2000:
        return None
    u = urlsplit(value)
    if (u.scheme != "https" or u.hostname != "www.brenau.edu" or u.query or u.fragment
        or u.username or u.password or not re.fullmatch(
            r"/wp-content/uploads/20\d{2}/(?:0[1-9]|1[0-2])/"
            r"[^?#\s/]+\.(?:jpe?g|png|webp)", u.path, re.I)
        or re.search(r"(?:^|[-_/])(?:logo|icon|avatar|placeholder|favicon)(?:[-_.]|$)", u.path, re.I)
        or re.search(r"-\d{2,3}x\d{2,3}\.", u.path, re.I)):
        return None
    return value


def _point(venue):
    try:
        lat, lng = float(venue.get("geo_lat")), float(venue.get("geo_lng"))
        return (lat, lng) if (math.isfinite(lat) and math.isfinite(lng) and
                              32.5 <= lat <= 35.3 and -85 <= lng <= -82) else (None, None)
    except (TypeError, ValueError):
        return None, None


def _hold(key, identity, reason):
    LOGGER.info("gainesville_direct_held source=%s id=%s reason=%s",
                key, str(identity)[:120], reason)


def _brenau(item):
    if not isinstance(item, dict) or item.get("id") in (None, ""):
        raise ValueError("invalid_wordpress_payload")
    identity = str(item["id"])
    if (item.get("status") != "publish" or item.get("hide_from_listings")
            or item.get("all_day") or item.get("event_status") in ("cancelled", "canceled", "postponed")):
        return None
    title = plain(item.get("title"))
    venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
    name = plain(venue.get("venue"))
    if not title or CANCEL.search(title) or VIRTUAL.search(name):
        return None
    address = _street(venue.get("address"), venue.get("city"),
                      venue.get("state") or venue.get("stateprovince"), venue.get("zip"))
    if not address or not name:
        _hold(BRENAU, identity, "street_unverified")
        return None
    if item.get("timezone") != ZONE:
        _hold(BRENAU, identity, "timezone_unverified")
        return None
    start = timestamp(item.get("utc_start_date"), "UTC")
    end = timestamp(item.get("utc_end_date"), "UTC")
    if not start or end and end < start:
        _hold(BRENAU, identity, "time_unverified")
        return None
    try:
        local = datetime.fromisoformat(item["start_date"])
        if local.tzinfo is None:
            offsets = {local.replace(tzinfo=ZoneInfo(ZONE), fold=i).astimezone(timezone.utc)
                       for i in (0, 1)}
            valid = start.astimezone(timezone.utc) in offsets
        else:
            valid = local.astimezone(timezone.utc) == start.astimezone(timezone.utc)
        if not valid:
            raise ValueError("publisher_schedule_conflict")
    except (TypeError, KeyError, ValueError):
        _hold(BRENAU, identity, "publisher_schedule_conflict")
        return None
    url = item.get("url")
    if not event_url(BRENAU, url):
        _hold(BRENAU, identity, "event_url_unverified")
        return None
    # Do not replace missing publisher descriptions with titles or boilerplate.
    try:
        narrative = _narrative(item.get("description"))
    except ValueError as exc:
        _hold(BRENAU, identity, str(exc))
        return None
    labels = [plain(c["name"]) for c in item.get("categories") or []
              if isinstance(c, dict) and isinstance(c.get("name"), str)]
    lat, lng = _point(venue)
    row = record(title, start.isoformat(), end.isoformat() if end and end > start else None,
                 name, address, plain(venue.get("city")), url, identity,
                 ", ".join(labels), lat, lng, ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=narrative, timezone=ZONE, publisher_categories=labels,
               location_provenance="publisher_event_venue")
    image = item.get("image") if isinstance(item.get("image"), dict) else {}
    candidate = image.get("url")
    if isinstance(image.get("width"), (int, float)) and image["width"] < 600:
        candidate = None
    from roomquest.publisher_evidence import attach
    return attach(row, BRENAU, candidate=candidate)


def _meeple(source, fetch):
    from roomquest.ics_adapter import parse
    url = SOURCES[MEEPLE][0]
    payload = fetch(url, "text/calendar")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    # Existing iCalendar adapter expands recurring VEVENT instances and retains
    # per-occurrence DESCRIPTION and UTC start/end timestamps.
    events = parse(payload, {"url": url, "source_key": MEEPLE, "timezone": ZONE},
                   legacy=False, include_description=True)
    results = {}
    for row in events:
        identity = row.get("id", "")
        title = plain(row.get("title"))
        if CANCEL.search(title):
            continue
        location = plain(row.get("venue_name") or row.get("venue_address"))
        match = MEEPLE_LOCATION.fullmatch(location)
        if not match:
            _hold(MEEPLE, identity, "event_location_unverified")
            continue
        if not event_url(MEEPLE, row.get("event_url")):
            _hold(MEEPLE, identity, "event_url_unverified")
            continue
        if row.get("description") and len(row["description"]) > MAX_DESCRIPTION:
            _hold(MEEPLE, identity, "publisher_description_limit")
            continue
        from roomquest.event_description import description
        narrative = description(row.get("description") or "",
                                limit=max(MAX_DESCRIPTION + 1,
                                          len(row.get("description") or "")))
        if len(narrative) > MAX_DESCRIPTION:
            _hold(MEEPLE, identity, "publisher_description_limit")
            continue
        room = match.group("name")
        row.update(description=narrative,
                   venue_name=plain(room), venue_address=MEEPLE_STREET,
                   venue_city="Flowery Branch", timezone=ZONE,
                   location_provenance="publisher_event_location_and_official_venue")
        key = (identity, row["starts_at"])
        if key in results and results[key] != row:
            raise ValueError("conflicting_event_occurrence")
        results[key] = row
    if len(results) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    return sorted(results.values(), key=lambda r: (r["starts_at"], r["title"], r["id"]))


def _libcal(source, fetch):
    from roomquest.event_description import description
    key = source["source_key"]
    profile = LIBRARY_PROFILES[key]
    raw = fetch(SOURCES[key][0], "application/rss+xml,application/xml")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("unsafe_xml_payload")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("invalid_library_rss") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("unsupported_library_rss")
    entries = root.findall("./channel/item")
    if len(entries) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    now = datetime.now(ZoneInfo(ZONE))
    out = {}
    for item in entries:
        values = {node.tag.rsplit("}", 1)[-1]:
                  "".join(node.itertext()).strip() for node in item}
        identity = values.get("eventid")
        title = plain(values.get("title"))
        if not identity or not identity.isdigit() or not title or CANCEL.search(title):
            continue
        if values.get("campus") != profile[1]:
            _hold(key, identity, "branch_unverified")
            continue
        day = values.get("date", "")
        start_text, end_text = values.get("start", ""), values.get("end", "")
        if not (re.fullmatch(r"20\d{2}-\d{2}-\d{2}", day) and
                re.fullmatch(r"\d{2}:\d{2}:\d{2}", start_text)):
            _hold(key, identity, "start_time_unverified")
            continue
        # An all-day calendar placeholder does not mean the library is open 24h.
        if start_text == "00:00:00" and end_text == "23:59:59":
            _hold(key, identity, "date_only_without_open_hours")
            continue
        try:
            start = timestamp(day+"T"+start_text, ZONE)
            end = timestamp(day+"T"+end_text, ZONE) if end_text else None
        except ValueError:
            _hold(key, identity, "timezone_ambiguous")
            continue
        if not start or end and end < start or start > now+timedelta(days=WINDOW_DAYS):
            continue
        url = values.get("link")
        if not event_url(key, url):
            _hold(key, identity, "event_url_unverified")
            continue
        html = values.get("description", "")
        narrative = description(html, limit=max(len(html), MAX_DESCRIPTION+1))
        if len(narrative) > MAX_DESCRIPTION:
            _hold(key, identity, "publisher_description_limit")
            continue
        labels = [plain(x.text) for x in item.findall("category") if x.text]
        room = plain(values.get("location"))
        venue = profile[1] + (" — " + room if room else "")
        row = record(title, start.isoformat(), end.isoformat() if end else None,
                     venue, profile[2], profile[3], url, identity,
                     ", ".join(labels), None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative, timezone=ZONE, publisher_categories=labels,
                   location_provenance="publisher_branch_identity_official_street")
        occurrence_key = (row["id"], row["starts_at"])
        if occurrence_key in out and out[occurrence_key] != row:
            raise ValueError("conflicting_event_occurrence")
        out[occurrence_key] = row
    return sorted(out.values(), key=lambda r: (r["starts_at"], r["title"], r["id"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    expected = SOURCES.get(key)
    if not expected or (source.get("feed_url"), source.get("kind"),
                        source.get("platform_adapter")) != expected or source.get("timezone") != ZONE:
        raise ValueError("unregistered_gainesville_direct_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 42, deadline_at or float("inf"))
    if key == MEEPLE:
        return _meeple(source, fetch)
    if key in LIBRARY_PROFILES:
        return _libcal(source, fetch)
    url = SOURCES[BRENAU][0]
    current = now.astimezone(ZoneInfo(ZONE))
    params = {"per_page":100, "start_date":current.date().isoformat(),
              "end_date":(current+timedelta(days=30)).date().isoformat()}
    rows = {}
    for page in range(1, 3):
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        payload = json.loads(fetch(url+"?"+urlencode(dict(params, page=page)),
                                   "application/json"))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise ValueError("invalid_wordpress_payload")
        pages = payload.get("total_pages", 1)
        if type(pages) is not int or pages < 1 or pages > 2 or len(payload["events"]) > 100:
            raise ValueError("pagination_limit")
        for item in payload["events"]:
            row = _brenau(item)
            if row:
                key = (row["id"], row["starts_at"])
                if key in rows and rows[key] != row:
                    raise ValueError("conflicting_event_occurrence")
                rows[key] = row
        if page >= pages:
            break
    if len(rows) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    return sorted(rows.values(), key=lambda r: (r["starts_at"], r["title"], r["id"]))
