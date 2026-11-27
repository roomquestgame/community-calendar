"""Watsonville Taiko: original structured Squarespace event calendar.

Original publisher JSON, individually dated sessions and official event venue street.
No invented repeat sessions, images, location centroids or public event coordinates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import json
import re
from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record

KEY = "watsonville_taiko_original_events_ca"
FEED = "https://www.watsonvilletaiko.org/events?format=json"
ZONE = "America/Los_Angeles"
SOURCES = {KEY: (FEED, "json", "squarespace")}
ALLOWED_HOSTS = {KEY: ("www.watsonvilletaiko.org",)}
VENUE = "Kizuka Hall"
STREET = "150 Blackburn Street, Watsonville, CA 95076"
PREFIX = "https://www.watsonvilletaiko.org"
MAX_RECORDS = 20
MAX_DESCRIPTION = 12000
SLUG = re.compile(r"/events/20[0-9]{2}/[0-9]{1,2}/[0-9]{1,2}/[a-z0-9-]+\Z")


def event_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == "www.watsonvilletaiko.org"
            and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and bool(SLUG.fullmatch(parsed.path)))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"))
            != SOURCES[KEY] or source.get("timezone") != ZONE):
        raise ValueError("taiko_source_identity_mismatch")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("taiko_naive_now")
    raw = fetch(FEED, "application/json")
    if not isinstance(raw, str) or len(raw) > 2_000_000:
        raise ValueError("taiko_feed_invalid")
    payload = json.loads(raw)
    if (not isinstance(payload, dict)
            or not isinstance(payload.get("upcoming"), list)
            or payload.get("website", {}).get("primaryDomain") != "www.watsonvilletaiko.org"
            or payload.get("website", {}).get("siteTitle") != "Watsonville Taiko"):
        raise ValueError("taiko_publisher_identity_mismatch")
    candidates = payload["upcoming"]
    if len(candidates) > 100:
        raise ValueError("taiko_feed_too_large")
    result = []
    for item in candidates:
        if not isinstance(item, dict) or item.get("recordType") != 12 or item.get("workflowState") != 1:
            continue
        stable_id = item.get("id")
        if not isinstance(stable_id, str) or not re.fullmatch(r"[a-f0-9]{24}", stable_id):
            raise ValueError("taiko_stable_id_missing")
        structured = item.get("structuredContent") or {}
        if not isinstance(structured, dict) or structured.get("_type") != "CalendarEvent":
            raise ValueError("taiko_calendar_identity_invalid")
        starts_ms = item.get("startDate")
        ends_ms = item.get("endDate")
        if (not isinstance(starts_ms, int) or isinstance(starts_ms, bool)
                or not isinstance(ends_ms, int) or isinstance(ends_ms, bool)
                or structured.get("startDate") != starts_ms or structured.get("endDate") != ends_ms):
            raise ValueError("taiko_calendar_clock_missing")
        start = datetime.fromtimestamp(starts_ms / 1000, tz=timezone.utc)
        end = datetime.fromtimestamp(ends_ms / 1000, tz=timezone.utc)
        if not timedelta(minutes=20) <= end - start <= timedelta(hours=12):
            raise ValueError("taiko_invalid_duration")
        if not now - timedelta(hours=3) <= start <= now + timedelta(days=60):
            continue
        relative_url = item.get("fullUrl")
        if not isinstance(relative_url, str) or not SLUG.fullmatch(relative_url):
            raise ValueError("taiko_source_event_url_invalid")
        url = PREFIX + relative_url
        if not event_url(url):
            raise ValueError("taiko_source_event_url_invalid")
        local = start.astimezone(ZoneInfo(ZONE))
        if (f"/{local.year}/{local.month}/{local.day}/" not in relative_url):
            raise ValueError("taiko_local_date_mismatch")
        location = item.get("location") or {}
        if (not isinstance(location, dict)
                or location.get("addressTitle") != VENUE
                or str(location.get("addressLine1", "")).strip() != "150 Blackburn Street"
                or location.get("addressLine2") != "Watsonville, CA, 95076"
                or location.get("addressCountry") != "United States"):
            raise ValueError("taiko_event_venue_review_required")
        description = BeautifulSoup(str(item.get("body") or ""), "html.parser").get_text(" ", strip=True)
        if not 90 <= len(description) <= MAX_DESCRIPTION:
            raise ValueError("taiko_full_description_missing")
        title = item.get("title") or ""
        if not isinstance(title, str) or not 5 <= len(title.strip()) <= 160:
            raise ValueError("taiko_title_missing")
        row = record(title.strip(), start.isoformat(), end.isoformat(), VENUE, STREET,
                     "Watsonville", url, stable_id, "Arts, cooking, community workshop",
                     None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=description, timezone=ZONE,
                   publisher_categories=["Taiko Community", "Workshop"],
                   location_provenance="owner_calendar_event_named_hall_official_street",
                   location_evidence_url=url, schedule_evidence_url=url)
        from roomquest.publisher_evidence import attach
        from roomquest.squarespace import original_content
        row['collector_event_content_v1'] = original_content(item, row, FEED, description)
        result.append(attach(row, KEY, evidence_url=url))
        if len(result) > MAX_RECORDS:
            raise ValueError("taiko_too_many_valid_events")
    return result
