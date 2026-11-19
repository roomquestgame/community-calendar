"""Organizer-controlled RunSignup registration: one race event, not inferred sub-race times.

The organizer's old top-level "Sunday Nov 21" text conflicts with the live
registration's ISO-8601 local clock. Admit only the exact organizer-controlled
2026 main SportsEvent; never guess street coordinates or repeat a yearly race.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record

KEY = "santa_cruz_track_club_turkey_trot_ca"
URL = "https://runsignup.com/Race/CA/SantaCruz/SCTC2021TurkeyTrot"
ZONE = "America/Los_Angeles"
STREET = "2300 Delaware Ave, Santa Cruz, CA 95060"
VENUE = "Santa Cruz Turkey Trot — Natural Bridges start"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("runsignup.com",)}
MAX_RECORDS = 1
MAX_DESCRIPTION = 12000


def event_url(value):
    try:
        p = urlsplit(value)
        return (isinstance(value, str) and p.scheme == "https" and
                p.hostname == "runsignup.com" and p.port in (None, 443) and
                not p.username and not p.password and not p.query and not p.fragment
                and p.path == "/Race/CA/SantaCruz/SCTC2021TurkeyTrot")
    except (ValueError, TypeError):
        return False


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("timezone") != ZONE or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]):
        raise ValueError("turkey_trot_unregistered_source")
    page = fetch(URL, "text/html")
    if not isinstance(page, str) or not 500 < len(page) < 500000:
        raise ValueError("turkey_trot_invalid_publisher_body")
    soup = BeautifulSoup(page, "html.parser")
    events = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            e = json.loads(s.get_text())
        except (ValueError, TypeError):
            continue
        if (isinstance(e, dict) and e.get("@type") == "SportsEvent" and
                e.get("name") == "Santa Cruz Turkey Trot"):
            events.append(e)
    if len(events) != 1:
        raise ValueError("turkey_trot_organizer_identity_changed")
    e = events[0]
    loc = e.get("location") or {}
    address = loc.get("address") or {}
    if (address.get("streetAddress") != "2300 Delaware Ave" or
            address.get("addressLocality") != "Santa Cruz" or
            address.get("addressRegion") != "CA" or
            address.get("postalCode") != "95060" or
            address.get("addressCountry") != "US"):
        raise ValueError("turkey_trot_event_street_changed")
    if e.get("eventStatus") not in (None, "https://schema.org/EventScheduled"):
        return []
    try:
        begin = datetime.fromisoformat(e["startDate"])
        end = datetime.fromisoformat(e["endDate"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("turkey_trot_invalid_organizer_time") from exc
    if (begin.tzinfo is None or end.tzinfo is None or
            end <= begin or begin.astimezone(ZoneInfo(ZONE)).date() != datetime(2026, 11, 21).date() or
            begin.astimezone(ZoneInfo(ZONE)).hour != 7 or
            begin.astimezone(ZoneInfo(ZONE)).minute != 45 or
            end.astimezone(ZoneInfo(ZONE)).hour != 10):
        raise ValueError("turkey_trot_registration_date_drift")
    now = now or datetime.now(timezone.utc)
    if not now - timedelta(hours=3) <= begin.astimezone(timezone.utc) <= now + timedelta(days=60):
        return []
    narrative = description(html.unescape(e.get("description") or ""), limit=MAX_DESCRIPTION + 1)
    if not narrative or len(narrative) > MAX_DESCRIPTION or len(narrative) < 150:
        raise ValueError("turkey_trot_missing_full_narrative")
    if re.search(r"\b(cancelled|canceled|postponed|closed for registration)\b", narrative, re.I):
        return []
    row = record("Santa Cruz Turkey Trot", begin.isoformat(), end.isoformat(),
                 VENUE, STREET, "Santa Cruz", URL, "runsignup-120332-20261121",
                 "Running, 10K, 5K, Kids 1K", None, None, ZONE, retain_until_end=True)
    if row is None:
        return []
    row.update(description=narrative, timezone=ZONE,
               publisher_categories=["Running", "10K", "5K", "Kids 1K"],
               occurrence_identity="runsignup-120332-20261121",
               location_provenance="organizer_race_registration_official_street",
               location_evidence_url=URL)
    from roomquest.publisher_evidence import attach
    return [attach(row, KEY)]

