"""Original publisher's 2026–27 GTA theatre season: only explicitly clocked performances.

The season run (Feb 12–20) does NOT imply a curtain time on every date.
Only the official, individually described Feb 12 opening-night performance
is currently admitted. The April Ed Cabell Oakwood production is not assigned
a clock or artificially backfilled. Other future dates need publisher evidence.
"""
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record
from roomquest.event_description import description
from roomquest.publisher_evidence import attach

KEY = "gainesville_theatre_alliance_ga"
HOST = "www.gainesvilletheatrealliance.org"
URL = "https://" + HOST + "/2026-2027-season"
DETAIL = "https://" + HOST + "/pride-prejudice-2027"
ZONE = "America/New_York"
VENUE = "Brenau University's Hosch Theatre"
STREET = "429 Academy St NE, Gainesville, GA 30501"
TITLE = "Pride & Prejudice"
D = datetime(2027, 2, 12, 19, 30, tzinfo=ZoneInfo(ZONE))
MAX_DAYS = 90

RUN = re.compile(r"February\s+12\s*[–-]\s*20,?\s*2027", re.I)
PERFORMANCE = re.compile(r"following\s+the\s+Friday,?\s+Feb\.?\s*12,?\s+7:30\s*PM\s+performance\b", re.I)


def event_url(value):
    if not isinstance(value, str) or len(value) > 300:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST
                and p.username is None and p.password is None
                and p.port in (None, 443) and not p.query and not p.fragment
                and p.path == "/pride-prejudice-2027")
    except ValueError:
        return False


def _canonical(soup, url):
    link = soup.select_one('link[rel="canonical"][href]')
    return bool(link and link.get("href") == url)


def parse(season_html, detail_html, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_unresolved")
    index = BeautifulSoup(season_html, "html.parser")
    detail = BeautifulSoup(detail_html, "html.parser")
    if not _canonical(index, URL):
        raise ValueError("gta_official_season_canonical_changed")
    if not _canonical(detail, DETAIL):
        raise ValueError("gta_official_event_canonical_changed")
    # The current season must actually link this production's detail, not just
    # an old bookmarked article with an event date in the calendar horizon.
    if not any(urljoin(URL, a.get("href", "")) == DETAIL for a in index.select("a[href]")):
        return []
    if not re.search(r"February\s+12\s*[–-]\s*20,?\s*2027", plain(index.get_text(" ", strip=True)), re.I):
        return []
    og = detail.select_one('meta[property="og:title"][content]')
    if not og or "Pride & Prejudice" not in plain(og.get("content")):
        return []
    detail_text = plain(detail.get_text(" ", strip=True))
    if not RUN.search(detail_text) or not PERFORMANCE.search(detail_text):
        return []
    if not ("Hosch Theatre" in detail_text and "429 Academy St NE" in detail_text
            and "Gainesville, GA 30501" in detail_text):
        return []
    if not (now <= D.astimezone(timezone.utc) <= now + timedelta(days=MAX_DAYS)):
        return []

    # Complete event-specific blurb when present. No site-wide navigation,
    # synthetic copy or truncation to an excerpt. Optional by design.
    event_copy = ""
    about = next((h for h in detail.find_all(["h1", "h2", "h3", "h4", "h5"])
                  if plain(h.get_text(" ", strip=True)).upper() == "ABOUT THE SHOW"), None)
    if about:
        para = about.find_next("p")
        if para:
            event_copy = description(str(para), limit=12000)

    row = record(TITLE, D.isoformat(), None, VENUE, STREET, "Gainesville",
                 DETAIL, "gta-pride-prejudice-2027-02-12-opening", "Movies / Theater",
                 tz=ZONE, retain_until_end=True)
    if row is None:
        return []
    row.update(description=event_copy, timezone=ZONE,
               location_provenance="publisher_performance_venue_street",
               publisher_categories=["Theatre", "Arts & Culture"],
               publisher_status="scheduled")
    return [attach(row, KEY, evidence_url=DETAIL, facts={
        "publisher_event_id": "gta-pride-prejudice-2027-02-12-opening",
        "publisher_venue_address": STREET,
        "publisher_timezone": ZONE,
        "publisher_clock_evidence": "Friday Feb 12 2027 7:30 PM performance",
        "unclocked_run_dates_excluded": True,
    })]


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("feed_url") != URL
            or source.get("kind") != "html" or source.get("platform_adapter") != "html"
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_gta_source")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    season = fetch(URL, "text/html")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    detail = fetch(DETAIL, "text/html")
    return parse(season, detail, now=now)
