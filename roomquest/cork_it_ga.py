"""Exact publisher-owned Cork It Gainesville Squarespace event calendar.

An event must provide its *own* Gainesville street and valid coordinates.
Unlocated, outside-town, all-day or non-timed calendar entries are held.
"""
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import math
import re

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach
from roomquest.squarespace import check_pagination

KEY = "cork_it_gainesville_ga"
URL = "https://www.corkitgainesville.com/eventdates?format=json"
HOST = "www.corkitgainesville.com"
ZONE = "America/New_York"
VENUE = "Cork It Gainesville"
STREET = re.compile(r"^118 Main (?:Street Southwest|St SW)$", re.I)
LOCALITY = re.compile(r"^Gainesville,\s*(?:GA|Georgia),\s*30501$", re.I)
MAX_DAYS = 90
MAX_RECORDS = 70
MAX_DESCRIPTION = 12000


def event_url(value):
    if not isinstance(value, str) or len(value) > 260:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST
                and p.username is None and p.password is None
                and p.port in (None, 443) and not p.query and not p.fragment
                and bool(re.fullmatch(r"/eventdates/[A-Za-z0-9-]{6,120}", p.path)))
    except ValueError:
        return False


def _clock(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("event_time_missing")
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
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
        if item.get("workflowState") != 1 or item.get("cancelled") is True or item.get("allDay") or item.get("allDayEvent"):
            continue
        identity, path = item.get("id"), item.get("fullUrl")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9]{12,40}", identity) or not event_url("https://" + HOST + path):
            continue
        title = plain(item.get("title"))
        if not title:
            continue
        try:
            start, end = _clock(item.get("startDate")), _clock(item.get("endDate"))
        except ValueError:
            continue
        if not (now <= start <= now + timedelta(days=MAX_DAYS) and start < end
                and end - start <= timedelta(hours=24)):
            continue
        location = item.get("location") or {}
        if not isinstance(location, dict):
            continue
        venue = plain(location.get("addressTitle"))
        street = plain(location.get("addressLine1"))
        locality = plain(location.get("addressLine2"))
        if not (venue == VENUE and STREET.fullmatch(street) and LOCALITY.fullmatch(locality)
                and location.get("addressCountry") == "United States"):
            continue
        lat, lng = location.get("markerLat"), location.get("markerLng")
        if (isinstance(lat, bool) or isinstance(lng, bool)
                or not isinstance(lat, (int, float)) or not isinstance(lng, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lng)
                or not (34.25 <= lat <= 34.35 and -83.88 <= lng <= -83.78)):
            continue
        address = street + ", " + locality
        link = "https://" + HOST + path
        row = record(title, start.isoformat(), end.isoformat(), venue, address,
                     "Gainesville", link, identity, "Live Music",
                     lat=lat, lng=lng, tz=ZONE, publisher_geo=True,
                     retain_until_end=True)
        if row is None:
            continue
        text = description(item.get("body") or item.get("excerpt") or "", limit=MAX_DESCRIPTION)
        row.update(description=text, timezone=ZONE,
                   location_provenance="publisher_event_venue",
                   publisher_categories=["Live Music"],
                   publisher_status="scheduled")
        # The published asset is a metadata endpoint without an image extension.
        # No photo is claimed unless a separate rights/provenance check approves it.
        row = attach(row, KEY, evidence_url=URL,
                     facts={"publisher_event_id": identity,
                            "publisher_timezone": ZONE, "venue_address": address})
        key = (identity, row["starts_at"])
        if key in output and output[key] != row:
            raise ValueError("conflicting_event_occurrence")
        output[key] = row
    return sorted(output.values(), key=lambda r: (r["starts_at"], r["id"]))


def collect(source, fetch, *, deadline_at=None):
    if (source.get("source_key") != KEY or source.get("feed_url") != URL
            or source.get("kind") != "json"
            or source.get("platform_adapter") != "squarespace"
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_cork_it_source")
    if deadline_at is not None and monotonic() > deadline_at:
        raise ValueError("collection_deadline")
    return parse(fetch(URL, "application/json"))
