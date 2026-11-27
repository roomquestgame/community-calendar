"""MeloMelo Santa Cruz's official embedded Google Calendar at its local venue.

Parse only real dated occurrences rendered by the first-party Simple Calendar
widget; never synthesize Mondays or admit weekly price promotions as events.
A name-only 'Open Mic Night' venue resolves only through the publisher's own
Santa Cruz address, not a Santa Cruz centroid or a borrowed location.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import record

KEY = "melo_melo_kava_santa_cruz_ca"
URL = "https://melomelokavabar.com/santacruz/"
ZONE = "America/Los_Angeles"
ADDRESS = "1101 Pacific Ave Suite D, Santa Cruz, CA 95060"
VENUE = "MeloMelo Kava Bar — Santa Cruz"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("melomelokavabar.com",)}
MAX_RECORDS = 30
MAX_DESCRIPTION = 12000
MAX_LIST_ITEMS = 120
EVENT_TITLES = {
    "Open Mic Night": ("Open Mic Night", "Live Music"),
    "Charity Poker Tournament": ("Gaming", "Fundraiser"),
    "Thanksgiving Community Potluck": ("Community", "Food & Drink"),
}
NONPUBLIC = re.compile(r"\b(?:canceled|cancelled|postponed|private event|invite[- ]only)\b", re.I)


def event_url(value):
    try:
        p = urlsplit(value)
        return (isinstance(value, str) and p.scheme == "https" and
                p.hostname == "melomelokavabar.com" and p.port in (None, 443)
                and not p.username and not p.password and not p.fragment
                and not p.query and p.path == "/santacruz/")
    except (TypeError, ValueError):
        return False


def _time(item, attr):
    tag = item.select_one("span." + attr + "[content]")
    if tag is None:
        raise ValueError("melo_missing_original_occurrence_time")
    try:
        dt = datetime.fromisoformat(tag["content"])
    except (TypeError, ValueError) as exc:
        raise ValueError("melo_invalid_original_occurrence_time") from exc
    if dt.utcoffset() is None or dt.utcoffset() != dt.astimezone(ZoneInfo(ZONE)).utcoffset():
        raise ValueError("melo_publisher_timezone_drift")
    return dt


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("timezone") != ZONE or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]):
        raise ValueError("melo_unregistered_source")
    raw = fetch(URL, "text/html")
    if not isinstance(raw, str) or not 500 < len(raw) <= 1000000:
        raise ValueError("melo_invalid_publisher_body")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    if ("SANTA CRUZ" not in text.upper() or
            "1101 Pacific Ave" not in text or "Santa Cruz, CA 95060" not in text):
        raise ValueError("melo_official_street_unverified")
    entries = soup.select("li.simcal-event.simcal-events-calendar-922")
    if len(entries) > MAX_LIST_ITEMS or not entries:
        raise ValueError("melo_calendar_missing_or_oversize")
    now = calendar_anchor(now or datetime.now(timezone.utc))
    found = {}
    for item in entries:
        name_el = item.select_one(":scope > span.simcal-event-title")
        title = name_el.get_text(" ", strip=True) if name_el else ""
        if title not in EVENT_TITLES:
            continue
        start = _time(item, "simcal-event-start-time")
        end = _time(item, "simcal-event-end-time")
        if end <= start or end - start > timedelta(hours=8):
            raise ValueError("melo_invalid_event_duration")
        if not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
            continue
        venue_meta = item.select_one("meta[itemprop=address]")
        physical = venue_meta.get("content", "").strip() if venue_meta else ""
        if not (physical in (title, VENUE, "MeloMelo Kava Bar", "Open Mic Night")
                or ("1101 Pacific Ave" in physical and "Santa Cruz" in physical)):
            continue
        narrative = item.select_one(".simcal-event-description")
        prose = description(str(narrative), limit=MAX_DESCRIPTION+1) if narrative else ""
        if (not prose or len(prose) < 55 or len(prose) > MAX_DESCRIPTION or NONPUBLIC.search(prose)):
            continue
        if title == "Open Mic Night" and "local musicians" not in prose:
            continue
        if title == "Charity Poker Tournament" and "All proceeds donated" not in prose:
            continue
        if title == "Thanksgiving Community Potluck" and "Bring your leftovers" not in prose:
            continue
        identity = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") + "-" + start.strftime("%Y%m%dT%H%M")
        row = record(title, start.isoformat(), end.isoformat(), VENUE, ADDRESS,
                     "Santa Cruz", URL, identity, ", ".join(EVENT_TITLES[title]),
                     None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=prose, timezone=ZONE,
                   occurrence_identity=identity,
                   publisher_categories=list(EVENT_TITLES[title]),
                   location_evidence_url=URL,
                   location_provenance="publisher_first_party_local_venue_street")
        from roomquest.publisher_evidence import attach
        row = attach(row, KEY)
        unique = (identity, row["starts_at"])
        if unique in found and found[unique] != row:
            raise ValueError("melo_conflicting_occurrence")
        found[unique] = row
    if len(found) > MAX_RECORDS:
        raise ValueError("melo_event_limit")
    return sorted(found.values(), key=lambda x: (x["starts_at"], x["title"], x["id"]))

