"""Direct original Downtown Santa Cruz business-district programs, not syndicated venue listings.

The Naughty List is authored by Downtown Santa Cruz and starts at its official
numbered Information Kiosk. Other downtown listings (parade route, multi-store
promotions, first-Friday syndications) are deliberately not emitted. No
coordinates or third-party artist/event images are invented or redistributed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.publisher_evidence import attach

KEY = "downtown_santa_cruz_original_events_ca"
URL = "https://downtownsantacruz.com/do/the-naughty-list-1"
KIOSK = "https://downtownsantacruz.com/visit/downtown-information-kiosk"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("downtownsantacruz.com",)}
ZONE = "America/Los_Angeles"
MAX_HTML = 650000
MAX_RECORDS = 2
MAX_DESCRIPTION = 12000
STREET = "1130 Pacific Ave, Santa Cruz, CA 95060"
VENUE = "Downtown Santa Cruz Information Kiosk (K2) — event check-in"
DATE_CLOCK = re.compile(r"Friday,?\s*Dec\s*11,?\s*2026\s*6\s*pm\s*[-–—]\s*9\s*pm", re.I)
KIOSK_ADDRESS = re.compile(r"1130\s*[- ]?K2\s+Pacific\s+Ave(?:nue)?", re.I)
EVENT_CHECKIN = re.compile(r"Downtown\s+Info\s+Kiosk\s*:\s*1130\s+Pacific\s+Ave\.?\s*K2", re.I)
CANCELLED = re.compile(r"\b(?:cancelled|canceled|postponed|members[- ]only|private event)\b", re.I)


def event_url(value):
    if value != URL:
        return False
    p = urlsplit(value)
    return (p.scheme == "https" and p.hostname == "downtownsantacruz.com"
            and p.port in (None, 443) and not p.username and not p.password
            and not p.query and not p.fragment)


def _main(payload):
    if not isinstance(payload, str) or not (300 <= len(payload) <= MAX_HTML):
        raise ValueError("downtown_html_invalid")
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.select_one("main")
    if main is None:
        raise ValueError("downtown_main_missing")
    return main


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("downtown_source_identity_mismatch")
    main = _main(fetch(URL, "text/html"))
    kiosk = _main(fetch(KIOSK, "text/html"))
    heading = main.select_one("h1")
    if heading is None or heading.get_text(" ", strip=True).strip() != "The Naughty List":
        raise ValueError("downtown_event_heading_drift")
    text = main.get_text(" ", strip=True)
    if (not DATE_CLOCK.search(text) or "Downtown Santa Cruz" not in text
            or not EVENT_CHECKIN.search(text)
            or "event begins at 6PM" not in text
            or "event ends at 9pm" not in text
            or CANCELLED.search(text)):
        raise ValueError("downtown_event_date_or_street_drift")
    kiosk_text = kiosk.get_text(" ", strip=True)
    if not KIOSK_ADDRESS.search(kiosk_text) or "Santa Cruz" not in kiosk_text:
        raise ValueError("downtown_official_kiosk_street_missing")
    paragraphs = [p.get_text(" ", strip=True) for p in main.select("p")]
    start_i = next((i for i, p in enumerate(paragraphs)
                    if p.startswith("Santa's working on his list")), None)
    if start_i is None:
        raise ValueError("downtown_narrative_missing")
    details = [p for p in paragraphs[start_i:]
               if p and p.casefold() not in ("visit website", "category: event calendar")]
    body = description("\n\n".join(details), limit=MAX_DESCRIPTION)
    if (not body or len(body) < 250 or len(body) > MAX_DESCRIPTION
            or "Only ticket buyers" not in body
            or "21 years of age or older" not in body):
        raise ValueError("downtown_narrative_missing")
    start = datetime(2026, 12, 11, 18, tzinfo=ZoneInfo(ZONE))
    end = datetime(2026, 12, 11, 21, tzinfo=ZoneInfo(ZONE))
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
        return []
    row = record(
        "The Naughty List — Downtown Santa Cruz Holiday Scavenger Hunt",
        start.isoformat(), end.isoformat(), VENUE, STREET, "Santa Cruz",
        URL, "downtown-sc-naughty-list-2026-12-11", 
        "holiday, scavenger hunt, nightlife, adult, community",
        None, None, ZONE, retain_until_end=True)
    if row is None:
        return []
    row.update(description=body, timezone=ZONE,
               publisher_categories=["Nightlife", "Scavenger Hunt", "Adults Only"],
               location_provenance="publisher_original_event_checkin_and_official_kiosk_street",
               location_evidence_url=KIOSK, schedule_evidence_url=URL)
    out = [attach(row, KEY, evidence_url=URL)]
    if len(out) > MAX_RECORDS:
        raise ValueError("downtown_record_limit")
    return out
