"""Official Skinny Raven Sports Turkey Trot event; Alaska onsite 5K and 2-mile race.

One first-party annual event page; no generated recurrences. Crawling is gated
by preview_worker robots and publisher pacing (10 seconds from current rules).
The complete event article is retained; site artwork stays unlicensed.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record

KEY = "skinny_raven_turkey_trot_ak"
FEED = "https://skinnyraven.com/events/turkey-trot/"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("skinnyraven.com",)}
ZONE = "America/Anchorage"
VENUE = ("Dena'ina Civic & Convention Center",
         "600 W 7th Ave, Anchorage, AK 99501", "Anchorage")
# Independently Census-matched and already reviewed for Winter Wonder Fest:
# Public_AR_Current street interpolation, NOT a surveyed building entrance.
POINT = (61.215542722741, -149.893601953117)
POINT_EVIDENCE = ("US Census Public_AR_Current matched 600 W 7th Ave Anchorage "
                  "AK 99501, interpolated street point, 2026-11-19")
MAX_HTML = 450_000
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
TITLE = "Trot and Give Thanks!"
DATE = re.compile(r"^(?:Nov|November)\.?\s+(\d{1,2}),?\s+(20\d{2})$", re.I)
STARTS = re.compile(r"\bIn-Person\s+5k\s+(\d{1,2}):(\d{2})\s*([ap]m)\s+2\s+Mile\s+(\d{1,2}):(\d{2})\s*([ap]m)\b", re.I)
NO_PUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|staff[- ]only|private event)\b", re.I)


def event_url(source_key, value):
    if source_key != KEY or value != FEED:
        return False
    p = urlsplit(value)
    return (p.scheme == "https" and p.hostname == "skinnyraven.com"
            and p.port in (None, 443) and p.username is None
            and p.password is None and not p.query and not p.fragment)


def photo_url(source_key, value):
    return None  # Rights not established for organizer art.


def _clock(hh, mm, ampm):
    hour = int(hh)
    minute = int(mm)
    if hour not in range(1, 13) or minute not in range(60):
        raise ValueError("turkey_trot_bad_clock")
    return (hour % 12) + (12 if ampm.lower() == "pm" else 0), minute


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("timezone") != ZONE
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]):
        raise ValueError("turkey_trot_source_mismatch")
    deadline = min(monotonic() + 35, deadline_at if deadline_at is not None else float("inf"))
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    now = now or datetime.now(timezone.utc)
    html = fetch(FEED, "text/html")
    if not isinstance(html, str) or not html or len(html) > MAX_HTML:
        raise ValueError("turkey_trot_bad_html")
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or "Turkey Trot | Skinny Raven Sports" not in soup.title.get_text(" ", strip=True):
        raise ValueError("turkey_trot_wrong_publisher")
    article = soup.find("article")
    if article is None or len(soup.find_all("article")) != 1:
        raise ValueError("turkey_trot_article_missing")
    heads = [plain(h.get_text(" ", strip=True)) for h in article.select("h1")]
    if heads.count(TITLE) != 1 or "In-Person" not in heads:
        raise ValueError("turkey_trot_identity_changed")
    dates = [DATE.fullmatch(h) for h in heads]
    dates = [m for m in dates if m]
    if len(dates) != 1:
        raise ValueError("turkey_trot_date_missing")
    day, year = map(int, dates[0].groups())
    text = plain(article.get_text(" ", strip=True))
    if not text or len(text) > MAX_DESCRIPTION or NO_PUBLIC.search(text):
        raise ValueError("turkey_trot_description_invalid")
    if not re.search(r"\bDena[’']ina Civic & Convention Center\b", text, re.I):
        raise ValueError("turkey_trot_onsite_venue_missing")
    if not re.search(r"\bOur in-person event will be staged from the Dena[’']ina", text, re.I):
        raise ValueError("turkey_trot_event_venue_not_proven")
    m = STARTS.search(text)
    if m is None:
        raise ValueError("turkey_trot_start_missing")
    h1, minute1 = _clock(*m.groups()[:3])
    h2, minute2 = _clock(*m.groups()[3:])
    if (h2 * 60 + minute2) < (h1 * 60 + minute1):
        raise ValueError("turkey_trot_disordered_starts")
    zone = ZoneInfo(ZONE)
    starts = datetime(year, 11, day, h1, minute1, tzinfo=zone)
    if (starts.strftime("%a") != "Thu" or starts.tzname() != "AKST"
            or starts.utcoffset() != timedelta(hours=-9)):
        raise ValueError("turkey_trot_local_time_unverified")
    if (starts.astimezone(timezone.utc) <= now - timedelta(hours=3)
            or starts.astimezone(timezone.utc) > now + timedelta(days=WINDOW_DAYS)):
        return []
    # The organizer gives two different race starts, but no end time; do not invent an end.
    row = record(TITLE, starts.isoformat(), None, *VENUE, FEED,
                 f"skinny_raven_turkey_trot:{year}-{11:02d}-{day:02d}",
                 "sports", lat=POINT[0], lng=POINT[1], tz=ZONE)
    if row is None:
        return []
    candidate = soup.find("meta", attrs={"property": "og:image"})
    candidate = candidate.get("content") if candidate else None
    if candidate and not re.fullmatch(r"https://skinnyraven\.com/wp-content/uploads/[a-zA-Z0-9/_\-.]+\.(?:jpg|jpeg|png|webp)", candidate, re.I):
        candidate = None
    row.update(description=text, category="sports", timezone=ZONE,
               location_provenance=POINT_EVIDENCE,
               publisher_categories=["5K", "2-mile run", "Community fundraiser"],
               image_rights="unreviewed")
    if candidate:
        row["publisher_details"] = {"image_candidate_only": candidate}
    row.pop("image_url", None)
    return [row]
