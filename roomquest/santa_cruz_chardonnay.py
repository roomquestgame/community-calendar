"""Original Chardonnay Sailing Charters' December 2026 special owner sailing.

The event's marina check-in is the owner's explicitly documented FF Dock address,
not its separate 704 Soquel Avenue administrative office. No synthetic daily
sailing slots or third-party lighted-parade organizer events are imported.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "chardonnay_sailing_santa_cruz_holiday_ca"
URL = "https://chardonnay.com/public-sails/lighted-boat-parade/"
ADDRESS_URL = "https://chardonnay.com/contact/getting-here/"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("chardonnay.com", "www.chardonnay.com")}
ZONE = "America/Los_Angeles"
STREET = "790 Mariner Park Way, Santa Cruz, CA 95062"
VENUE = "Chardonnay Sailing Charters — FF Dock harbor check-in"
MAX_HTML = 320000
MAX_RECORDS = 1
MAX_DESCRIPTION = 6500
DATE_PATTERN = re.compile(r"Saturday,?\s*December\s*5,?\s*2026,?\s*5:30\s*pm\s*[-–—]\s*7:30\s*pm", re.I)
ADDRESS_PATTERN = re.compile(r"790\s+Mariner\s+Park\s+Way\.?\s*FF\s+Dock,?\s*Santa\s+Cruz,?\s*CA\s*95062", re.I)
CANCELLED = re.compile(r"\b(?:cancelled|canceled|postponed|no longer available)\b", re.I)


def event_url(value):
    p = urlsplit(value)
    return (value == URL and p.scheme == "https" and p.hostname == "chardonnay.com"
            and p.port in (None, 443) and not p.username and not p.password
            and not p.query and not p.fragment)


def _main(payload, *, venue=False):
    if not isinstance(payload, str) or not (100 <= len(payload) <= MAX_HTML):
        raise ValueError("chardonnay_html_invalid")
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.select_one("main") or (soup.select_one("body") if venue else None)
    if main is None:
        raise ValueError("chardonnay_main_missing")
    return main


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("chardonnay_source_identity_mismatch")
    main = _main(fetch(URL, "text/html"))
    address_main = _main(fetch(ADDRESS_URL, "text/html"), venue=True)
    headers = [h.get_text(" ", strip=True) for h in main.find_all(["h1", "h2"])]
    if (headers.count("Lighted Boat Parade & Waterfront Cruise") != 2
            or not any(DATE_PATTERN.fullmatch(h) for h in headers)
            or "Duration: 2 Hours" not in main.get_text(" ", strip=True)):
        raise ValueError("chardonnay_schedule_drift")
    # Explicitly reject original owner cancellation, but do not mistake the
    # published weather-dependent 'confirm/cancel 24hr ahead' policy for a cancel.
    words = main.get_text(" ", strip=True)
    if CANCELLED.search(words):
        raise ValueError("chardonnay_event_cancelled")
    if (not ADDRESS_PATTERN.search(address_main.get_text(" ", strip=True))
            or "Our Harbor Check-In Office" not in address_main.get_text(" ", strip=True)
            or "Our Main Office" not in address_main.get_text(" ", strip=True)):
        raise ValueError("chardonnay_event_checkin_street_missing")
    paras = [p.get_text(" ", strip=True) for p in main.select("p")]
    prelude = [p for p in paras if p.startswith(("Duration:", "Ages:", "Capacity:", "Note: Note:", "When booking publicly,"))]
    owner_details = [p for p in paras if p.startswith(("Enjoy the Santa Cruz Lighted Boat Parade",
                       "Enjoy two house drinks", "** NOTE that all sails are tentative"))]
    if len(prelude) != 5 or len(owner_details) != 3:
        raise ValueError("chardonnay_narrative_missing")
    body = description("\n\n".join(prelude + owner_details), limit=MAX_DESCRIPTION)
    if (not body or len(body) < 550 or not all(x in body for x in
            ("Chardonnay II", "hot cocoa", "24 hr prior", "Ages: All Ages"))):
        raise ValueError("chardonnay_narrative_missing")
    start = datetime(2026, 12, 5, 17, 30, tzinfo=ZoneInfo(ZONE))
    end = datetime(2026, 12, 5, 19, 30, tzinfo=ZoneInfo(ZONE))
    now = (calendar_anchor(now or datetime.now(timezone.utc))).astimezone(timezone.utc)
    if not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
        return []
    row = record("Chardonnay Sailing Charters — Lighted Boat Parade & Waterfront Cruise",
                 start.isoformat(), end.isoformat(), VENUE, STREET, "Santa Cruz",
                 URL, "chardonnay-lighted-boat-cruise-2026-12-05-1730",
                 "sailing, waterfront cruise, boat parade, holiday event, family friendly",
                 None, None, ZONE, retain_until_end=True)
    if row is None:
        return []
    row.update(description=body, timezone=ZONE,
               publisher_categories=["Sailing", "Cruise", "Holiday", "Family Activities"],
               location_provenance="publisher_original_harbor_checkin_not_admin_office",
               location_evidence_url=ADDRESS_URL, schedule_evidence_url=URL)
    return [attach(row, KEY, evidence_url=URL)]
