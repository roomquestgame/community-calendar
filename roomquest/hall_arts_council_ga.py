"""Strict first-party Squarespace calendar: The Arts Council, Gainesville, Georgia."""
from datetime import datetime, timedelta, timezone
import json
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach
from roomquest.squarespace import check_pagination

KEY = "hall_arts_council_gainesville_ga"
URL = "https://www.theartscouncil.net/events?format=json"
HOST = "www.theartscouncil.net"
ZONE = "America/New_York"
VENUE = "Smithgall Arts Center"
STREET = re.compile(r"^331 Spring (?:St SW|Street Southwest)$", re.I)
LOCALITY = re.compile(r"^Gainesville,\s*(?:GA|Georgia),\s*30501$", re.I)
ASSET_PREFIX = "/content/v1/68653a54760bb4069e9577b0/"
MAX_RECORDS = 60
MAX_DAYS = 90


def event_url(value):
    if not isinstance(value, str) or len(value) > 350:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST
                and p.username is None and p.password is None and p.port in (None, 443)
                and not p.query and not p.fragment
                and bool(re.fullmatch(r"/events/[A-Za-z0-9][A-Za-z0-9-]{3,150}", p.path)))
    except ValueError:
        return False


def photo_url(value):
    if not isinstance(value, str) or len(value) > 1800:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme == "https" and p.hostname == "images.squarespace-cdn.com"
                and p.port in (None, 443) and not p.username and not p.password
                and p.path.startswith(ASSET_PREFIX)
                and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)
                and not p.query and not p.fragment):
            return value
    except ValueError:
        pass
    return None


def _clock(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError("event_time_missing")
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (OSError, ValueError, OverflowError) as exc:
        raise ValueError("event_time_invalid") from exc


def parse(payload, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_unresolved")
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("upcoming"), list):
        raise ValueError("unsupported_squarespace_payload")
    if (data.get("website") or {}).get("timeZone") != ZONE:
        raise ValueError("publisher_timezone_changed")
    if len(data["upcoming"]) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    check_pagination(data, upcoming=True)
    output = {}
    for item in data["upcoming"]:
        if not isinstance(item, dict):
            raise ValueError("invalid_calendar_record")
        if item.get("workflowState") != 1 or item.get("cancelled") is True:
            continue
        if item.get("allDay") or item.get("allDayEvent"):
            continue
        identity = item.get("id")
        path = item.get("fullUrl")
        if (not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9]{12,40}", identity)
                or not isinstance(path, str)):
            continue
        link = "https://" + HOST + path
        if not path.startswith("/events/") or not event_url(link):
            continue
        title = plain(item.get("title"))
        if not title:
            continue
        try:
            start = _clock(item.get("startDate"))
            end = _clock(item.get("endDate"))
        except ValueError:
            continue
        if not (now <= start <= now + timedelta(days=MAX_DAYS) and start < end):
            continue
        # Squarespace emits a New York (40.720..., -74.000...) default map point
        # for events whose venue is missing. Never map them to Gainesville.
        location = item.get("location") or {}
        if not isinstance(location, dict):
            continue
        venue = plain(location.get("addressTitle"))
        street = plain(location.get("addressLine1"))
        locality = plain(location.get("addressLine2"))
        if not (venue == VENUE and STREET.fullmatch(street)
                and LOCALITY.fullmatch(locality)
                and plain(location.get("addressCountry")) == "United States"):
            continue
        lat, lng = location.get("markerLat"), location.get("markerLng")
        if (isinstance(lat, bool) or isinstance(lng, bool)
                or not isinstance(lat, (int, float)) or not isinstance(lng, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lng)
                or not (34.15 <= lat <= 34.45 and -83.96 <= lng <= -83.65)):
            continue
        # Avoid admitting an undifferentiated concert series alongside its
        # individually ticketed shows, even if the publisher later fixes its pin.
        if re.search(r"\b(?:20\d\d)\s+Jazz at the Smithgall Series\b", title, re.I):
            continue
        address = street + ", " + locality
        row = record(title, start.isoformat(), end.isoformat(), venue,
                     address, "Gainesville", link, identity, "Live Music",
                     lat=lat, lng=lng, tz=ZONE, publisher_geo=True,
                     retain_until_end=True)
        if row is None:
            continue
        body = item.get("body") or item.get("excerpt") or ""
        narrative = description(body, limit=12000)
        row.update(description=narrative, timezone=ZONE,
                   location_provenance="publisher_event_venue",
                   publisher_categories=item.get("categories") if isinstance(item.get("categories"), list) else [],
                   publisher_status="scheduled")
        row = attach(row, KEY, candidate=photo_url(item.get("assetUrl")),
                     evidence_url=URL, facts={"publisher_event_id": identity,
                                             "venue_address": address,
                                             "publisher_timezone": ZONE})
        duplicate = (identity, row["starts_at"])
        if duplicate in output and output[duplicate] != row:
            raise ValueError("conflicting_event_occurrence")
        output[duplicate] = row
    return sorted(output.values(), key=lambda r: (r["starts_at"], r["id"]))


def collect(source, fetch, *, deadline_at=None):
    if (source.get("source_key") != KEY or source.get("feed_url") != URL
            or source.get("kind") != "json"
            or source.get("platform_adapter") != "squarespace"
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_hall_arts_source")
    if deadline_at is not None and monotonic() > deadline_at:
        raise ValueError("collection_deadline")
    return parse(fetch(URL, "application/json"))
