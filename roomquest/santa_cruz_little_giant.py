"""Direct Little Giant Collective owner-authored Squarespace event occurrences.

Only explicitly dated and fully described studio Sip 'N' Sketch workshops are
accepted. The owner calendar's months-long Art Club range is NOT expanded into
fictional monthly dates; stale copy in an exhibition page is not reauthored.
Official contact/address proof is mandatory. Coordinates remain unpopulated for
the existing shared Geocodio flow; publisher photos are not licensed here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import json
import re

from bs4 import BeautifulSoup
from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "little_giant_collective_santa_cruz_ca"
URL = "https://www.littlegiantcollective.com/calendar?format=json"
CONTACT = "https://www.littlegiantcollective.com/contact"
HOST = "www.littlegiantcollective.com"
SOURCES = {KEY: (URL, "json", "squarespace")}
ALLOWED_HOSTS = {KEY: (HOST, "littlegiantcollective.com")}
ZONE = "America/Los_Angeles"
STREET = "115 River St South, Santa Cruz, CA 95060"
VENUE = "Little Giant Collective"
MAX_JSON = 650000
MAX_HTML = 160000
MAX_RECORDS = 18
MAX_DESCRIPTION = 12000
TITLE = re.compile(r"Sip\s*['’]\s*N\s*['’]\s*Sketch(?:\s*\(Copy\))?", re.I)
OWNER_STREET = re.compile(r"\b115\s+RIVER\s+ST(?:REET)?\s+SOUTH\b", re.I)
EV_STREET = re.compile(r"\b115\s+River\s+St(?:reet)?\.?\s+South\b", re.I)


def event_url(value):
    if not isinstance(value, str):
        return False
    p = urlsplit(value)
    return (p.scheme == "https" and p.hostname == HOST and p.port in (None,443)
            and not p.username and not p.password and not p.query and not p.fragment
            and bool(re.fullmatch(r"/calendar/\d{4}/\d{1,2}/\d{1,2}/[a-z0-9-]+", p.path)))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("little_giant_source_identity_mismatch")
    owner_html = fetch(CONTACT, "text/html")
    if not isinstance(owner_html, str) or not (80 <= len(owner_html) <= MAX_HTML):
        raise ValueError("little_giant_contact_invalid")
    owner_text = BeautifulSoup(owner_html, "html.parser").get_text(" ", strip=True)
    if not (OWNER_STREET.search(owner_text) and
            re.search(r"SANTA\s+CRUZ,\s*CA\s*95060\b", owner_text, re.I)):
        raise ValueError("little_giant_official_street_missing")
    raw = fetch(URL, "application/json")
    if not isinstance(raw, str) or not (100 <= len(raw) <= MAX_JSON):
        raise ValueError("little_giant_calendar_invalid")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("little_giant_calendar_invalid") from exc
    if not isinstance(data, dict) or not isinstance(data.get("upcoming"), list):
        raise ValueError("little_giant_calendar_invalid")
    now_utc = (calendar_anchor(now or datetime.now(timezone.utc))).astimezone(timezone.utc)
    seen = set()
    out = []
    for item in data["upcoming"][:100]:
        if not isinstance(item, dict):
            continue
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        if not TITLE.fullmatch(title):
            continue
        if item.get("recordType") != 12 or item.get("workflowState") != 1:
            continue
        item_id = item.get("id")
        path = item.get("fullUrl")
        if not isinstance(item_id, str) or not re.fullmatch(r"[0-9a-f]{24}", item_id):
            raise ValueError("little_giant_event_identity_missing")
        url = "https://" + HOST + str(path or "")
        if not event_url(url):
            raise ValueError("little_giant_event_url_invalid")
        if url in seen:
            continue
        seen.add(url)
        loc = item.get("location")
        if not isinstance(loc, dict) or not EV_STREET.search(str(loc.get("addressLine1") or "")):
            raise ValueError("little_giant_event_street_missing")
        if "Santa Cruz" not in str(loc.get("addressLine2") or "") or \
                str(loc.get("addressCountry") or "").casefold() not in ("usa", "united states"):
            raise ValueError("little_giant_event_street_missing")
        start_ms, end_ms = item.get("startDate"), item.get("endDate")
        if not (isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float))):
            raise ValueError("little_giant_event_clock_missing")
        try:
            start = datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).replace(microsecond=0)
            end = datetime.fromtimestamp(end_ms/1000, tz=timezone.utc).replace(microsecond=0)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError("little_giant_event_clock_invalid") from exc
        local_start, local_end = start.astimezone(ZoneInfo(ZONE)), end.astimezone(ZoneInfo(ZONE))
        if (local_start.hour, local_start.minute, local_end.hour, local_end.minute) != (18, 0, 20, 0) \
                or local_start.date() != local_end.date() or local_start.weekday() != 1 \
                or end - start != timedelta(hours=2):
            raise ValueError("little_giant_event_clock_invalid")
        if not now_utc - timedelta(hours=3) <= start <= now_utc + timedelta(days=60):
            continue
        html = item.get("body")
        if not isinstance(html, str) or len(html) > 100000:
            raise ValueError("little_giant_description_missing")
        body = description(BeautifulSoup(html, "html.parser").get_text(" ", strip=True),
                           limit=MAX_DESCRIPTION)
        if not body or not (170 <= len(body) <= MAX_DESCRIPTION) or \
                "Bring your art" not in body or "We have tunes" not in body:
            raise ValueError("little_giant_description_missing")
        row = record("Sip 'N' Sketch — Little Giant Collective",
                     start.isoformat(), end.isoformat(), VENUE, STREET, "Santa Cruz",
                     url, item_id, "art, workshop, drawing, community, hobby",
                     None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=body, timezone=ZONE,
                   publisher_categories=["Arts", "Craft Workshops", "Community"],
                   location_provenance="publisher_event_location_and_contact_page",
                   location_evidence_url=CONTACT, schedule_evidence_url=url)
        out.append(attach(row, KEY, evidence_url=url))
        if len(out) > MAX_RECORDS:
            raise ValueError("little_giant_record_limit")
    return out
