"""Strict original LIUNA Local 71 / Tradeswomen of Alaska public events.

This is a guarded first-party TEC API feed; only event identity / venue
combinations independently verified at original publisher pages are admitted.
Membership meetings, Fairbanks, virtual events, and events lacking a reviewed
venue point are held. The event image is retained only as a rights candidate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re

from bs4 import BeautifulSoup
from roomquest.anchorage_sources import _description, ZONE
from roomquest.mapsee_adapter import plain, record

KEY = "local71_tradeswomen_public_ak"
FEED = "https://local71.com/wp-json/tribe/events/v1/events?per_page=50"
SOURCES = {KEY: (FEED, "json", "wordpress")}
ALLOWED_HOSTS = {KEY: ("local71.com",)}
MAX_DESCRIPTION = 12000
MAX_RESPONSE = 1_000_000
MAX_EVENTS = 50
WINDOW_DAYS = 60
# 2026-11-19 first-party event permalink and event-specific venue audited;
# Census benchmark Public_AR_Current exact 5227 OLD SEWARD HWY street match.
PEANUT_FARM = ("The Peanut Farm", "5227 Old Seward Hwy, Anchorage, AK 99518",
               "Anchorage", 61.173346520514, -149.867964031325)
REVIEWED = {
    10834: {
        "title": "🏈 Thursday Night Football with Tradeswomen of Alaska! (12/10/26)",
        "url": "https://local71.com/event/%f0%9f%8f%88-thursday-night-football-with-tradeswomen-of-alaska-12-10-26/",
        "start": "2026-12-10 16:00:00", "end": "2026-12-10 18:00:00",
        "venue_id": 7877, "venue": PEANUT_FARM, "category": "hang_out",
    },
}


def event_url(source_key, value):
    if source_key != KEY or not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "local71.com"
                and p.port in (None, 443) and not p.username and not p.password
                and not p.query and not p.fragment
                and value in {reviewed["url"] for reviewed in REVIEWED.values()})
    except ValueError:
        return False


def photo_url(source_key, value):
    return None  # No evidence granting commercial photo republication rights.


def _utc_and_local(value, expected, zone):
    if not isinstance(value, str) or value != expected:
        raise ValueError("local71_event_time_changed")
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zone)
    if dt.utcoffset() != timedelta(hours=-9):
        raise ValueError("local71_offset_changed")
    return dt


def _validated_event(event, reviewed, fetch, deadline, now):
    if not isinstance(event, dict) or event.get("id") not in REVIEWED:
        return None
    if (event.get("id") != next(k for k, v in REVIEWED.items() if v is reviewed)
            or event.get("status") != "publish"
            or event.get("hide_from_listings") is not False
            or event.get("all_day") is not False
            or plain(event.get("title")) != reviewed["title"]
            or not event_url(KEY, event.get("url"))
            or event.get("url") != reviewed["url"]
            or event.get("timezone") != ZONE):
        raise ValueError("local71_event_identity_changed")
    venue = event.get("venue")
    v = reviewed["venue"]
    if (not isinstance(venue, dict)
            or venue.get("id") != reviewed["venue_id"]
            or plain(venue.get("venue")) != v[0]
            or plain(venue.get("address")) != "5227 Old Seward Hwy"
            or plain(venue.get("city")) != "Anchorage"
            or plain(venue.get("state")) != "AK"
            or plain(venue.get("zip")) != "99518"):
        raise ValueError("local71_event_venue_changed")
    zone = ZoneInfo(ZONE)
    starts = _utc_and_local(event.get("start_date"), reviewed["start"], zone)
    ends = _utc_and_local(event.get("end_date"), reviewed["end"], zone)
    if ends <= starts or ends - starts > timedelta(hours=12):
        raise ValueError("local71_event_duration_invalid")
    for key, dt in (("utc_start_date", starts), ("utc_end_date", ends)):
        actual = event.get(key)
        if actual != dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
            raise ValueError("local71_utc_conflict")
    if ends.astimezone(timezone.utc) <= now or starts.astimezone(timezone.utc) > now + timedelta(days=WINDOW_DAYS):
        return None
    narrative = _description(event.get("description"))
    if not narrative or len(narrative) > MAX_DESCRIPTION:
        raise ValueError("local71_full_description_missing")
    if re.search(r"\b(members? only|private|cancelled|postponed|online only)\b", narrative, re.I):
        raise ValueError("local71_nonpublic_event")
    if "The Peanut Farm" not in narrative or "Tradeswomen of Alaska" not in narrative:
        raise ValueError("local71_publisher_description_mismatch")
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    detail = fetch(reviewed["url"], "text/html")
    if not isinstance(detail, str) or len(detail) > MAX_RESPONSE:
        raise ValueError("local71_event_page_missing")
    page = BeautifulSoup(detail, "html.parser").get_text(" ", strip=True)
    if ("Thursday Night Football" not in page or "The Peanut Farm" not in page
            or "5227 Old Seward" not in page):
        raise ValueError("local71_detail_does_not_confirm_venue")
    row = record(reviewed["title"], starts.isoformat(), ends.isoformat(),
                 *v[:3], reviewed["url"], "local71:" + str(event["id"]),
                 reviewed["category"], lat=v[3], lng=v[4],
                 tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    candidate = (event.get("image") or {}).get("url") if isinstance(event.get("image"), dict) else None
    if candidate and not (isinstance(candidate, str) and candidate.startswith("https://local71.com/wp-content/uploads/")):
        candidate = None
    row.update(description=narrative, category=reviewed["category"], timezone=ZONE,
               location_provenance="Census Public_AR_Current exact street-interpolated 5227 OLD SEWARD HWY, reviewed 2026-11-19",
               publisher_categories=["Tradeswomen of Alaska", "Social"],
               publisher_details={"image_candidate_only": candidate} if candidate else {},
               image_rights="unreviewed")
    row.pop("image_url", None)
    return row


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_local71_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 38, deadline_at if deadline_at is not None else float("inf"))
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    payload = fetch(FEED, "application/json")
    if not isinstance(payload, str) or len(payload) > MAX_RESPONSE:
        raise ValueError("local71_feed_oversized")
    data = json.loads(payload)
    if (not isinstance(data, dict) or not isinstance(data.get("events"), list)
            or len(data["events"]) > MAX_EVENTS):
        raise ValueError("local71_feed_invalid")
    results = {}
    for event in data["events"]:
        if not isinstance(event, dict) or event.get("id") not in REVIEWED:
            continue
        row = _validated_event(event, REVIEWED[event["id"]], fetch, deadline, now)
        if row:
            identity = (row["id"], row["starts_at"])
            if identity in results and results[identity] != row:
                raise ValueError("local71_duplicate_occurrence_conflict")
            results[identity] = row
    return sorted(results.values(), key=lambda x: (x["starts_at"], x["id"]))
