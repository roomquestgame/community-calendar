"""Verified first-party Bargetto Winery event list and exact event detail.

Use the publisher's JSON-LD event clock and its independently written
daily opening hours. Never turn a multi-day festival into an overnight event.
Only Soquel winery events with original numbered venue street are admitted;
Monterey tasting-room records are outside this source's scoped identity.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import record

KEY = "bargetto_winery_soquel_ca"
URL = "https://www.bargetto.com/events/upcoming"
DETAIL = "https://www.bargetto.com/events/upcoming/art-and-wine-art-in-the-cellars-2026-12-06"
ZONE = "America/Los_Angeles"
VENUE = "Bargetto Winery — Soquel Historic Winery"
ADDRESS = "3535 N Main Street, Soquel, CA 95073"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.bargetto.com",)}
MAX_RECORDS = 8
MAX_DESCRIPTION = 12000

def event_url(value):
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "www.bargetto.com"
                and p.port in (None, 443) and not p.username and not p.password
                and not p.query and not p.fragment and p.path == urlsplit(DETAIL).path)
    except ValueError:
        return False

def _document(text):
    if not isinstance(text, str) or not 200 < len(text) < 900000:
        raise ValueError("bargetto_invalid_html")
    soup = BeautifulSoup(text, "html.parser")
    if not soup.body:
        raise ValueError("bargetto_invalid_html")
    return soup

def _event_from_list(soup):
    found = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("@type") != "CollectionPage":
            continue
        entity = data.get("mainEntity") or {}
        if entity.get("@type") != "ItemList":
            continue
        for entry in entity.get("itemListElement") or []:
            item = entry.get("item") if isinstance(entry, dict) else None
            if not isinstance(item, dict):
                continue
            if (item.get("@type") == "Event" and item.get("name") == "Art in the Cellars"
                    and (item.get("location") or {}).get("name") == "Historic Winery & Tasting Room"):
                found.append(item)
    if len(found) != 1:
        raise ValueError("bargetto_event_identity_changed")
    e = found[0]
    if urlsplit(e.get("url") or "").path != urlsplit(DETAIL).path or urlsplit(e.get("url") or "").hostname not in ("bargetto.com", "www.bargetto.com"):
        raise ValueError("bargetto_event_identity_changed")
    try:
        start = datetime.fromisoformat(e["startDate"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(e["endDate"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError) as exc:
        raise ValueError("bargetto_invalid_event_time") from exc
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError("bargetto_invalid_event_time")
    return start.astimezone(ZoneInfo(ZONE)), end.astimezone(ZoneInfo(ZONE))

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY] or
            source.get("timezone") != ZONE):
        raise ValueError("bargetto_unregistered_source")
    listing = _document(fetch(URL, "text/html"))
    start, end = _event_from_list(listing)
    now = calendar_anchor(now or datetime.now(timezone.utc))
    if start.astimezone(timezone.utc) > now + timedelta(days=60) or end.astimezone(timezone.utc) < now - timedelta(hours=3):
        return []
    if not (start.year == end.year and start.month == 12 and end.month == 12
            and start.day == 5 and end.day == 6 and start.hour == 11 and start.minute == 0
            and end.hour == 17 and end.minute == 0 and start.year == 2026):
        raise ValueError("bargetto_calendar_detail_date_drift")
    detail = _document(fetch(DETAIL, "text/html"))
    main = detail.find("main")
    if main is None:
        raise ValueError("bargetto_missing_detail")
    text = main.get_text(" ", strip=True).replace("\xa0", " ")
    checks = ("Art in the Cellars", "December 5 - 6", "Soquel Historic Winery",
              "3535 N Main Street, Soquel, CA", "Saturday & Sunday: 11am - 5pm")
    if any(term not in text for term in checks) or re.search(r"\b(cancelled|canceled|postponed|sold out)\b",text,re.I):
        raise ValueError("bargetto_detail_drift_or_closed")
    prose_blocks = []
    for elem in main.find_all("div"):
        classes = elem.get("class") or []
        if "prose" in classes:
            body = elem.get_text(" ", strip=True)
            if "Explore a world of creativity" in body:
                prose_blocks.append(body)
    if len(prose_blocks) != 1 or not 160 <= len(prose_blocks[0]) <= MAX_DESCRIPTION:
        raise ValueError("bargetto_missing_original_description")
    narrative = prose_blocks[0]
    records = []
    for day in (5, 6):
        begins = datetime(2026, 12, day, 11, tzinfo=ZoneInfo(ZONE))
        finishes = datetime(2026, 12, day, 17, tzinfo=ZoneInfo(ZONE))
        if not now - timedelta(hours=3) <= begins.astimezone(timezone.utc) <= now + timedelta(days=60):
            continue
        identity = f"art-in-the-cellars-2026-12-{day:02d}"
        row = record("Art in the Cellars", begins.isoformat(), finishes.isoformat(),
                     VENUE, ADDRESS, "Soquel", DETAIL, identity,
                     "Festivals, Makers Market", None, None, ZONE, retain_until_end=True)
        if row:
            row.update(description=narrative, timezone=ZONE,
                       publisher_categories=["Festivals", "Art", "Makers Market"],
                       location_provenance="official_bargetto_detail_and_venue_street",
                       location_evidence_url=DETAIL,
                       occurrence_identity=identity)
            from roomquest.publisher_evidence import attach
            records.append(attach(row, KEY))
    if len(records) > MAX_RECORDS:
        raise ValueError("bargetto_record_limit")
    return records

