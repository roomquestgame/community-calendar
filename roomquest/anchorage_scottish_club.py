"""First-party Alaskan Scottish Club public Eagle River events, original Wix details.

Only two independently verified November 21 2026 events at Odd Man Rush Brewing.
2025 Celtic Market link and unrelated 2027/member activities are excluded.
The U.S. Census matching Mausel St point is interpolated, not rooftop GPS.
Source images remain candidates only, without publishing rights.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record

KEY = "alaskan_scottish_club_eagle_river_events_ak"
ROOT = "https://www.alaskanscottish.org"
FEED = ROOT + "/events"
ZONE = "America/Anchorage"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.alaskanscottish.org",)}
VENUE = ("Odd Man Rush Brewing", "10930 Mausel St, Eagle River, AK 99577", "Eagle River")
POINT = (61.319365548775, -149.580456913545)
POINT_EVIDENCE = ("US Census Public_AR_Current exact 10930 MAUSEL ST EAGLE RIVER AK "
                  "99577 match 2026-11-19; interpolated street, not rooftop coordinates")
MAX_HTML = 2_000_000
MAX_DESCRIPTION = 12_000
WINDOW_DAYS = 60
EVENTS = {
    "celtic-holiday-market-1": (
        "Celtic Holiday Market", "2026-11-21T11:00:00-09:00",
        "2026-11-21T17:00:00-09:00", "festival"),
    "st-andrews-day-celebration": (
        "St Andrew's Day Celebration", "2026-11-21T18:00:00-09:00",
        "2026-11-21T20:00:00-09:00", "arts_culture"),
}
BAD_PUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|members[- ]only|private event)\b", re.I)

def event_url(source_key, value):
    if source_key != KEY or not isinstance(value, str) or len(value) > 250:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "www.alaskanscottish.org"
                and p.port in (None, 443) and p.username is None and p.password is None
                and not p.query and not p.fragment
                and p.path in {"/event-details/" + slug for slug in EVENTS})
    except ValueError:
        return False

def photo_url(source_key, value):
    return None  # No publisher image rights established.

def _one(slug, page, now):
    url = ROOT + "/event-details/" + slug
    if not event_url(KEY, url) or not isinstance(page, str) or not 100 < len(page) <= MAX_HTML:
        raise ValueError("scottish_detail_invalid")
    soup = BeautifulSoup(page, "html.parser")
    title, start_expected, end_expected, category = EVENTS[slug]
    if not soup.title or plain(soup.title.get_text(" ", strip=True)) != title + " | Alaska Scottish Club":
        raise ValueError("scottish_identity_invalid")
    ld = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            ob = json.loads(script.get_text())
        except (ValueError, TypeError):
            raise ValueError("scottish_jsonld_invalid")
        if isinstance(ob, dict) and ob.get("@type") == "Event":
            ld.append(ob)
    if len(ld) != 1:
        raise ValueError("scottish_event_jsonld_invalid")
    item = ld[0]
    if (item.get("name") != title or item.get("startDate") != start_expected
            or item.get("endDate") != end_expected
            or item.get("eventStatus") != "https://schema.org/EventScheduled"
            or item.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"):
        raise ValueError("scottish_event_identity_changed")
    loc = item.get("location")
    if (not isinstance(loc, dict) or loc.get("@type") != "Place"
            or loc.get("name") != VENUE[0]
            or loc.get("address") != "10930 Mausel St, Eagle River, AK 99577, USA"
            or loc.get("url") != url):
        raise ValueError("scottish_unverified_venue")
    start, end = datetime.fromisoformat(start_expected), datetime.fromisoformat(end_expected)
    local_start, local_end = start.astimezone(ZoneInfo(ZONE)), end.astimezone(ZoneInfo(ZONE))
    if (start != local_start or end != local_end
            or start.tzname() not in ("UTC-09:00", "AKST")
            or start.utcoffset() != timedelta(hours=-9)
            or not start < end <= start + timedelta(hours=8)):
        raise ValueError("scottish_invalid_alaska_clock")
    if end.astimezone(timezone.utc) <= now or start.astimezone(timezone.utc) > now + timedelta(days=WINDOW_DAYS):
        return None
    heading = soup.select_one('h2[data-hook="about"]')
    body = heading.find_next_sibling("div") if heading else None
    if not body:
        raise ValueError("scottish_missing_about")
    description = plain(body.get_text(" ", strip=True))
    if (len(description) < 90 or len(description) > MAX_DESCRIPTION
            or BAD_PUBLIC.search(title + " " + description)):
        raise ValueError("scottish_description_invalid")
    row = record(title, start.isoformat(), end.isoformat(), *VENUE, url,
                 "alaskan_scottish:" + slug + ":2026-11-21", category,
                 lat=POINT[0], lng=POINT[1], tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=description, category=category, timezone=ZONE,
               location_provenance=POINT_EVIDENCE,
               publisher_categories=["Celtic culture", "Community", "Scottish Club"],
               image_rights="unreviewed")
    row.pop("image_url", None)
    image = item.get("image")
    if isinstance(image, dict):
        candidate = image.get("url")
        if isinstance(candidate, str) and re.fullmatch(
                r"https://static\.wixstatic\.com/media/[A-Za-z0-9_~./,-]+\.(?:jpg|jpeg|png|webp)(?:/v1/fill/[A-Za-z0-9_~./,-]+)?",
                candidate, re.I):
            row["publisher_details"] = {"image_candidate_only": candidate}
    return row

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("timezone") != ZONE
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]):
        raise ValueError("scottish_source_mismatch")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 38, deadline_at if deadline_at is not None else float("inf"))
    calendar = fetch(FEED, "text/html")
    if not isinstance(calendar, str) or not 50 < len(calendar) <= MAX_HTML:
        raise ValueError("scottish_calendar_invalid")
    soup = BeautifulSoup(calendar, "html.parser")
    links = {a.get("href") for a in soup.select("a[href]")}
    rows = []
    for slug in EVENTS:
        url = ROOT + "/event-details/" + slug
        if url not in links:
            raise ValueError("scottish_missing_original_event_link")
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        row = _one(slug, fetch(url, "text/html"), now)
        if row is not None:
            rows.append(row)
    if len({(row["id"], row["starts_at"]) for row in rows}) != len(rows):
        raise ValueError("scottish_duplicate_occurrence")
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
