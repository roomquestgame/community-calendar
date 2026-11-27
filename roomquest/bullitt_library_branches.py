"""Four audited first-party Bullitt County Library branches in Greater Louisville.

Official LibraryMarket branch iCalendars supply per-event street/GEO, UTC times,
publisher categories, narrative and event links. Their long-range unfiltered
exports are never used: fetch only a rolling 60-day publisher-supported window.
No source-center venue pin, inferred event time or fabricated recurring event.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import logging
import re

from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain

HOST = "bullittcounty.librarycalendar.com"
BASE = f"https://{HOST}/events/feed/ical"
ZONE = "America/New_York"
MAX_ITEMS = 500
MAX_DESCRIPTION = 12000
LOGGER = logging.getLogger(__name__)

# First-party branch IDs from publisher's public branch form (2026-11-19).
# Streets and GEO below are per-event facts independently present in each
# branch-filtered iCalendar; no default venue for missing/offsite locations.
SOURCES = {
    "bullitt_library_shepherdsville_ky": (
        87, "Bullitt County Public Library — Central Library",
        "740 Conestoga Parkway", "Shepherdsville", "40165",
        38.001917362655, -85.705027752149,
        "740 Conestoga Parkway, Shepherdsville, KY, 40165, US"),
    "bullitt_library_lebanon_junction_ky": (
        124, "Bullitt County Public Library — Lebanon Junction Branch",
        "11382 S. Preston Highway", "Lebanon Junction", "40150",
        37.8417704, -85.7309325,
        "11382 S. Preston Highway, Lebanon Junction, KY, 40150, US"),
    "bullitt_library_mt_washington_ky": (
        121, "Bullitt County Public Library — Mt. Washington Branch",
        "214 N. Bardstown Road", "Mt. Washington", "40047",
        38.04902, -85.54377,
        "214 N. Bardstown Road, Mt. Washington, KY, 40047, US"),
    "bullitt_library_west_point_ky": (
        123, "Bullitt County Public Library — Nichols Branch",
        "10729 Highway 44 West", "West Point", "40177",
        38.0142438, -85.8874136,
        "10729 Highway 44 West, West Point, KY, 40177, US"),
}
ALLOWED_HOSTS = {key: (HOST,) for key in SOURCES}
PRIVATE = re.compile(r"\b(?:staff[- ]only|private event|invitation only|members only)\b", re.I)
CLOSED = re.compile(r"\b(?:library closed|branch library closed|closure|renovation closing)\b", re.I)
CATEGORIES = {
    "books & authors": "learn", "adult learning & lectures": "learn",
    "early childhood": "learn", "storytelling": "learn", "stem learning": "learn",
    "technology": "learn", "arts & crafts": "create",
    "games & play": "hang_out", "fandom fun": "hang_out",
    "group meetup": "hang_out", "community event": "hang_out",
    "music & dance": "music", "health & wellness": "health",
    "holiday program": "party",
}
CORE = frozenset(CATEGORIES.values())


def feed_url(key: str) -> str:
    if key not in SOURCES:
        raise ValueError("unregistered_bullitt_library_source")
    branch = SOURCES[key][0]
    return f"{BASE}?branches%5B{branch}%5D={branch}"


def collection_url(key: str, now=None) -> str:
    today = (calendar_anchor(now or datetime.now(timezone.utc))).date()
    # Source identity is stable; the bounded first-party export window rolls.
    return (feed_url(key) + f"&start={today.isoformat()}"
            + f"&end={(today + timedelta(days=60)).isoformat()}")


def source_valid(source) -> bool:
    if not isinstance(source, dict):
        return False
    key = source.get("source_key")
    return key in SOURCES and (
        source.get("feed_url"), source.get("kind"),
        source.get("platform_adapter"), source.get("timezone"),
    ) == (feed_url(key), "ical", "ical", ZONE)


def event_url(key, url) -> bool:
    if key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname == HOST
                and u.port in (None, 443) and not u.username and not u.password
                and not u.query and not u.fragment
                and re.fullmatch(r"/event/[a-z0-9]+(?:-[a-z0-9]+)*/?",
                                 u.path, re.I) is not None)
    except (TypeError, ValueError):
        return False


def event_image(key, url):
    if key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        u = urlsplit(url)
        if (u.scheme == "https" and u.hostname == HOST
                and u.port in (None, 443) and not u.username and not u.password
                and not u.query and not u.fragment
                and not re.search(r"(?:^|[/_.-])(?:icon|logo|avatar|placeholder|thumbnail)(?:[/_.-]|$)",
                                  u.path, re.I)
                and re.fullmatch(
                    r"/sites/default/files/(?:20\d{2}/)?[a-z0-9_./-]+\.(?:jpe?g|png|webp)",
                    u.path, re.I)):
            return url
    except (TypeError, ValueError):
        pass
    return None


def category_for(labels, title):
    if PRIVATE.search(title) or CLOSED.search(title):
        return None
    # Publisher-supplied labels are facts; never infer an audience or category
    # merely from the source being a library.
    for label in labels:
        value = CATEGORIES.get(plain(label).casefold())
        if value:
            return value
    return None


def _original_evidence(payload, key):
    from icalendar import Calendar
    elements = Calendar.from_ical(payload).walk("VEVENT")
    if len(elements) > 1000:
        raise ValueError("source_record_limit")
    result = {}
    for event in elements:
        uid = str(event.get("UID") or "")
        if not uid:
            raise ValueError("publisher_event_uid_missing")
        raw = event.get("DESCRIPTION")
        narrative = description(str(raw) if raw is not None else "",
                                limit=MAX_DESCRIPTION + 1)
        if len(narrative) > MAX_DESCRIPTION:
            raise ValueError("publisher_description_over_limit")
        attach = event.get("ATTACH")
        attachments = attach if isinstance(attach, list) else ([attach] if attach else [])
        original_image = next(
            (str(item) for item in attachments if event_image(key, str(item))),
            None)
        before = result.get(uid)
        candidate = (narrative, original_image)
        if before is not None and before != candidate:
            raise ValueError("conflicting_publisher_ical_description")
        result[uid] = candidate
    return result


def collect(source, fetch, *, deadline_at=None):
    if not source_valid(source):
        raise ValueError("unregistered_bullitt_library_source")
    from roomquest.ics_adapter import parse
    from roomquest.publisher_evidence import attach
    key = source["source_key"]
    _, publisher, street, city, zip_code, verified_lat, verified_lng, raw_location = SOURCES[key]
    source_url = feed_url(key)
    payload = fetch(collection_url(key), "text/calendar")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    if not isinstance(payload, str):
        raise ValueError("invalid_ical_payload")
    original = _original_evidence(payload, key)
    rows = parse(payload, {"source_key": key, "url": source_url,
                           "feed_url": source_url, "timezone": ZONE},
                 legacy=False, include_description=True)
    if len(rows) > MAX_ITEMS:
        raise ValueError("source_record_limit")
    records = {}
    for row in rows:
        uid = str(row.get("id") or "").split("__", 1)[0]
        if uid not in original:
            continue
        title = plain(row.get("title"))
        location = plain(row.get("venue_address") or row.get("venue_name"))
        if location.casefold() != plain(raw_location).casefold():
            LOGGER.info("bullitt_library_hold source=%s reason=offsite_or_missing_venue", key)
            continue
        lat, lng = row.get("lat"), row.get("lng")
        if (not isinstance(lat, (int, float)) or isinstance(lat, bool)
                or not isinstance(lng, (int, float)) or isinstance(lng, bool)
                or abs(lat - verified_lat) > 0.005
                or abs(lng - verified_lng) > 0.005):
            LOGGER.info("bullitt_library_hold source=%s reason=unverified_branch_geo", key)
            continue
        if not event_url(key, row.get("event_url")):
            LOGGER.info("bullitt_library_hold source=%s reason=unverified_event_url", key)
            continue
        labels = row.get("publisher_categories") or []
        if not isinstance(labels, list):
            raise ValueError("invalid_publisher_categories")
        category = category_for(labels, title)
        if category not in CORE:
            LOGGER.info("bullitt_library_hold source=%s reason=unclassified_or_private", key)
            continue
        narrative, image = original[uid]
        row.update(title=title, venue_name=publisher,
                   venue_address=f"{street}, {city}, KY {zip_code}",
                   venue_city=city, lat=lat, lng=lng, timezone=ZONE,
                   description=narrative, category=category,
                   publisher_categories=[plain(x) for x in labels if plain(x)],
                   category_provenance="publisher_event_categories",
                   location_provenance="publisher_ical_event_branch_geo")
        row = attach(row, key, candidate=image)
        identity = (row["id"], row["starts_at"])
        if identity in records and records[identity] != row:
            raise ValueError("conflicting_event_occurrence")
        records[identity] = row
    return sorted(records.values(), key=lambda r: (r["starts_at"], r["title"], r["id"]))
