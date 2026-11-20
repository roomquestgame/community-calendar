"""First-party event carousel for The Landing performing arts center, Scotts Valley.

The live MEC JSON-LD timestamps do NOT agree with the owner-facing Pacific
wall times; deliberately trust the human-visible event date/start/end,
corroborated by linked detail pages. Reject undated, private, incomplete and
offsite records rather than importing incorrect schema time or fake map pins.
Partial scope: publisher's bounded upcoming-homepage carousel only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record

KEY = "the_landing_scotts_valley_ca"
URL = "https://thelandingsv.org/"
ZONE = "America/Los_Angeles"
HOST = "thelandingsv.org"
VENUE = "The Landing"
STREET = "251B Kings Village Rd, Scotts Valley, CA"
CITY = "Scotts Valley"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: (HOST,)}
MAX_RECORDS = 24
MAX_DESCRIPTION = 12000
BLOCKED = re.compile(r"\b(?:private event|cancelled|canceled|postponed|members[- ]only|sold out)\b", re.I)
PATH = re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/")

def event_url(url):
    if not isinstance(url, str) or len(url) > 1200:
        return False
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname == HOST and u.port in (None, 443)
                and not u.username and not u.password and not u.query
                and not u.fragment and bool(PATH.fullmatch(u.path)))
    except ValueError:
        return False

def _schema(html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        todo = value if isinstance(value, list) else [value]
        while todo:
            obj = todo.pop()
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("@graph"), list):
                todo.extend(obj["@graph"])
            if obj.get("@type") != "Event":
                continue
            link = obj.get("url")
            if not event_url(link):
                continue
            if link in found and found[link] != obj:
                raise ValueError("landing_duplicate_schema_conflict")
            found[link] = obj
    return soup, found

def _local(day, clock):
    try:
        d = datetime.strptime(day.strip(), "%d %B %Y").date()
        t = datetime.strptime(clock.strip().upper(), "%I:%M %p").time()
        return datetime.combine(d, t, tzinfo=ZoneInfo(ZONE))
    except (TypeError, ValueError):
        return None

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
        (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
        or source.get("timezone") != ZONE):
        raise ValueError("unregistered_landing_source")
    raw = fetch(URL, "text/html")
    if not isinstance(raw, str) or len(raw) > 900000:
        raise ValueError("invalid_landing_calendar")
    soup, schemas = _schema(raw)
    cards = soup.select(".mec-event-footer-carousel-type3")
    if not cards or len(cards) > MAX_RECORDS:
        raise ValueError("landing_missing_or_oversize_carousel")
    now = now or datetime.now(timezone.utc)
    rows = {}
    for card in cards:
        title_node = card.select_one(".mec-event-carousel-title a[href]")
        day_node = card.select_one(".mec-start-date-label")
        start_node = card.select_one(".mec-start-time")
        end_node = card.select_one(".mec-end-time")
        loc_node = card.select_one(".mec-event-location")
        if not all((title_node, day_node, start_node, end_node, loc_node)):
            continue
        title = plain(title_node.get_text(" ", strip=True))
        link = title_node.get("href")
        if not title or BLOCKED.search(title) or not event_url(link):
            continue
        native_street = plain(loc_node.get_text(" ", strip=True))
        if native_street != "251B Kings Village Rd, Scotts Valley":
            continue
        start = _local(day_node.get_text(" ", strip=True), start_node.get_text(" ", strip=True))
        end = _local(day_node.get_text(" ", strip=True), end_node.get_text(" ", strip=True))
        if not start or not end or not start < end <= start + timedelta(hours=12):
            continue
        if not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
            continue
        source_event = schemas.get(link)
        if not source_event or source_event.get("name") != title:
            continue
        if source_event.get("eventStatus") != "https://schema.org/EventScheduled":
            continue
        # Calendar schema uses incorrect hour/UTC offset: only verify dates.
        if str(source_event.get("startDate", ""))[:10] != start.date().isoformat():
            continue
        if str(source_event.get("endDate", ""))[:10] != end.date().isoformat():
            continue
        place = source_event.get("location") or {}
        if (not isinstance(place, dict) or place.get("name") != VENUE or
            (place.get("address") or "") != "251B Kings Village Rd, Scotts Valley"):
            continue
        prose = description(str(source_event.get("description") or ""), limit=MAX_DESCRIPTION)
        if not prose or len(prose) < 100 or BLOCKED.search(prose[:220]):
            continue
        identity = "landing:" + link.rstrip("/").rsplit("/", 1)[-1]
        row = record(title, start.isoformat(), end.isoformat(), VENUE, STREET, CITY, link,
                     identity, "live performance", None, None, ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=prose, timezone=ZONE,
                   location_provenance="official_publisher_event_street",
                   publisher_categories=[])
        from roomquest.publisher_evidence import attach
        row = attach(row, KEY)
        unique = (identity, row["starts_at"])
        if unique in rows and rows[unique] != row:
            raise ValueError("landing_conflicting_occurrence")
        rows[unique] = row
    return sorted(rows.values(), key=lambda e: (e["starts_at"], e["id"]))

