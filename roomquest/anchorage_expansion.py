"""Anchorage expansion: exact Zoo and Cook Inlet Historical Society Squarespace JSON.

Reuse existing EventQuest Squarespace JSON, description, identity and staging.
Event-specific official streets and publisher points only; no city pins.
The Zoo's current/next two monthly snapshots are bounded, never followed via
arbitrary pagination. Incomplete/offsite/private/uncertain records are withheld.
"""
from __future__ import annotations

from calendar import month_name
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.anchorage_sources import _description, NONPUBLIC, VIRTUAL, ZONE

log = logging.getLogger(__name__)
ZOO = "alaska_zoo_anchorage_ak"
HISTORY = "cook_inlet_historical_society_ak"
SOURCES = {
    ZOO: ("https://www.alaskazoo.org/event-calendar", "json", "squarespace"),
    HISTORY: ("https://www.cookinlethistoricalsociety.org/lecture-series", "json", "squarespace"),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
ZOO_VENUE = ("The Alaska Zoo", "4731 O'Malley Road, Anchorage, AK 99507", "Anchorage")
HISTORY_VENUE = ("Anchorage Museum", "625 C Street, Anchorage, AK 99501", "Anchorage")
ZOO_POINT = (61.1236344, -149.7908746)
HISTORY_POINT = (61.215893, -149.8846999)
MAX_RECORDS = 500
MAX_DESCRIPTION = 12000
LOOKAHEAD = 60
# Squarespace Zoo slugs are /year/slug, /year/season/slug, OR /year/mm/dd/slug.
ZOO_URL = re.compile(r"/event-calendar/20[0-9]{2}/(?:[a-z0-9-]+/){0,2}[a-z0-9]+(?:-[a-z0-9]+)*/?")
HISTORY_URL = re.compile(r"/lecture-series/[a-z0-9]+(?:-[a-z0-9]+)*/?")
PHOTO_PATH = re.compile(r"/content/v1/[A-Za-z0-9]+/[A-Za-z0-9_-]+/[^?#]+\.(?:jpe?g|png|webp)", re.I)
NOT_PHOTO = re.compile(r"(?:^|[-_/])(?:favicon|logo|icon|avatar|pixel|placeholder)(?:[-_.]|$)", re.I)
NOT_PUBLIC_ZOO = re.compile(r"\b(?:member.?only|members only|cybermonday|ticket sale|discount sale|sold out|staff only|online only)\b", re.I)

def _hold(key, identity, reason):
    log.warning("anchorage_event_held source=%s id=%s reason=%s", key, str(identity)[:140], reason)

def event_url(key, url):
    if key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == urlsplit(SOURCES[key][0]).hostname
                and not p.username and not p.password and p.port in (None, 443)
                and not p.query and not p.fragment
                and bool((ZOO_URL if key == ZOO else HISTORY_URL).fullmatch(p.path)))
    except ValueError:
        return False

def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        return value if (p.scheme == "https" and p.netloc == "images.squarespace-cdn.com"
                         and not p.query and not p.fragment and PHOTO_PATH.fullmatch(p.path)
                         and not NOT_PHOTO.search(p.path)) else None
    except ValueError:
        return None

def _point(loc, expected):
    if not isinstance(loc, dict):
        return None
    try:
        lat, lng = float(loc.get("mapLat")), float(loc.get("mapLng"))
    except (ValueError, TypeError, OverflowError):
        return None
    if (not math.isfinite(lat) or not math.isfinite(lng)
            or abs(lat - expected[0]) > 0.004
            or abs(lng - expected[1]) > 0.004):
        return None
    return lat, lng

def _times(item, now):
    start, end = item.get("startDate"), item.get("endDate")
    if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (start, end))):
        return None
    begins, ends = timestamp(start), timestamp(end)
    if ends <= begins or ends <= now or begins > now + timedelta(days=LOOKAHEAD):
        return None
    return begins, ends

def _labels(item):
    return [plain(v) for v in item.get("categories", []) if isinstance(v, str)]

def _row(key, item, title, category, times, venue, point, desc):
    original = item.get("fullUrl")
    event_link = urljoin(SOURCES[key][0], original) if isinstance(original, str) else ""
    if not event_url(key, event_link):
        _hold(key, item["id"], "publisher_event_url_invalid")
        return None
    row = record(title, times[0].isoformat(), times[1].isoformat(),
                 *venue, event_link, item["id"], category,
                 lat=point[0], lng=point[1], tz=ZONE,
                 publisher_geo=True, retain_until_end=True)
    if row is None:
        return None
    row.update(description=desc, category=category, timezone=ZONE,
               publisher_categories=_labels(item),
               location_provenance="publisher_venue_point_verified_street")
    from roomquest.publisher_evidence import attach
    return attach(row, key, candidate=item.get("assetUrl"))

def _zoo_category(title):
    if re.search(r"\b(?:storytime|lecture|science|workshop|class|educational talk)\b", title, re.I):
        return "learn"
    if re.search(r"\b(?:winter tour|wild icons|animal encounter|wildlife tour|zoo tour)\b", title, re.I):
        return "gardens_nature"
    if re.search(r"\b(?:zoo lights|holiday lights|christmas for the animals|zoo fest)\b", title, re.I):
        return "festival"
    return None

def _zoo_event(item, now):
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise ValueError("invalid_zoo_record")
    if item.get("workflowState") != 1 or item.get("cancelled") or item.get("allDay") or item.get("allDayEvent"):
        return None
    title = plain(item.get("title"))
    if not title or NONPUBLIC.search(title) or VIRTUAL.search(title) or NOT_PUBLIC_ZOO.search(title):
        return None
    category = _zoo_category(title)
    if not category:
        _hold(ZOO, item["id"], "category_review_required")
        return None
    loc = item.get("location") if isinstance(item.get("location"), dict) else {}
    if (plain(loc.get("addressTitle")).casefold() != "the alaska zoo"
            or not re.fullmatch(r"4731 O['’]Malley Road", plain(loc.get("addressLine1")), re.I)
            or not re.fullmatch(r"Anchorage,\s*AK,\s*99507", plain(loc.get("addressLine2")), re.I)):
        _hold(ZOO, item["id"], "zoo_venue_street_unverified")
        return None
    point = _point(loc, ZOO_POINT)
    if point is None:
        _hold(ZOO, item["id"], "zoo_venue_coordinates_unverified")
        return None
    dates = _times(item, now)
    if dates is None:
        return None
    desc = _description(item.get("body") or item.get("excerpt"))
    if desc is None:
        _hold(ZOO, item["id"], "description_missing_or_oversized")
        return None
    return _row(ZOO, item, title, category, dates, ZOO_VENUE, point, desc)

def _zoo_months(now):
    current = now.astimezone(ZoneInfo(ZONE))
    for i in range(3):
        month = current.month - 1 + i
        yield f"{month_name[month % 12 + 1].lower()}-{current.year + month // 12}"

def _collect_zoo(fetch, now, deadline):
    events = {}
    for month in _zoo_months(now):
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        url = SOURCES[ZOO][0] + f"?month={month}&view=calendar&format=json"
        data = json.loads(fetch(url, "application/json"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("invalid_zoo_squarespace_payload")
        if (data.get("website") or {}).get("timeZone") != ZONE:
            raise ValueError("publisher_timezone_changed")
        if len(data["items"]) > 180:
            raise ValueError("source_record_limit")
        for item in data["items"]:
            row = _zoo_event(item, now)
            if row:
                key = (row["id"], row["starts_at"])
                if key in events and events[key] != row:
                    raise ValueError("conflicting_zoo_occurrence")
                events[key] = row
    return list(events.values())

def _collect_history(fetch, now, deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    data = json.loads(fetch(SOURCES[HISTORY][0] + "?format=json", "application/json"))
    if not isinstance(data, dict) or not isinstance(data.get("upcoming"), list):
        raise ValueError("invalid_history_squarespace_payload")
    if (data.get("website") or {}).get("timeZone") != ZONE:
        raise ValueError("publisher_timezone_changed")
    from roomquest.squarespace import check_pagination
    check_pagination(data, upcoming=True)
    rows = {}
    for item in data["upcoming"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("invalid_history_record")
        if item.get("workflowState") != 1 or item.get("cancelled") or item.get("allDay") or item.get("allDayEvent"):
            continue
        title = plain(item.get("title"))
        if not title or NONPUBLIC.search(title) or VIRTUAL.search(title):
            continue
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        # Publisher lists an inconsistent "99508" ZIP; the Anchorage Museum's
        # official address is 625 C Street, Anchorage, AK 99501. Never invent a
        # new number or reuse this fixed venue for an offsite talk.
        if (plain(loc.get("addressTitle")).casefold() != "anchorage museum"
                or not re.fullmatch(r"625 C Street", plain(loc.get("addressLine1")), re.I)
                or not re.fullmatch(r"Anchorage,\s*AK\s*99508", plain(loc.get("addressLine2")), re.I)):
            _hold(HISTORY, item["id"], "museum_venue_street_unverified")
            continue
        point = _point(loc, HISTORY_POINT)
        if point is None:
            _hold(HISTORY, item["id"], "museum_publisher_coordinates_unverified")
            continue
        dates = _times(item, now)
        if dates is None:
            continue
        desc = _description(item.get("body") or item.get("excerpt"))
        if desc is None:
            _hold(HISTORY, item["id"], "description_missing_or_oversized")
            continue
        row = _row(HISTORY, item, title, "learn", dates, HISTORY_VENUE, point, desc)
        if row:
            key = (row["id"], row["starts_at"])
            if key in rows and rows[key] != row:
                raise ValueError("conflicting_history_occurrence")
            rows[key] = row
    return list(rows.values())

def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    if (key not in SOURCES
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[key]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_anchorage_expansion_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 36, deadline_at if deadline_at is not None else float("inf"))
    rows = _collect_zoo(fetch, now, deadline) if key == ZOO else _collect_history(fetch, now, deadline)
    if len(rows) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    return sorted(rows, key=lambda e: (e["starts_at"], e["title"], e["id"]))
