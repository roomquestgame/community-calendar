"""Publisher-owned Webflow show calendar for The Hall at Bourbon Brothers, Gainesville GA.

The only trusted facts are the dated live CMS cards linked to per-show Tixr IDs,
the separately labelled *show* clock (not door opening), and the venue's own street.
Ignore Webflow's unrelated sample schedule and do not synthesize ending times.
"""
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record
from roomquest.event_description import description
from roomquest.publisher_evidence import attach

KEY = "hall_bourbon_brothers_gainesville_ga"
URL = "https://www.thehallga.com/calendar"
HOST = "www.thehallga.com"
ZONE = "America/New_York"
VENUE = "The Hall at Bourbon Brothers"
STREET = "312 Jesse Jewell Pkwy, Gainesville, GA 30501"
SOURCES = {KEY: (URL, "html", "html")}
MAX_CARDS = 55
ASSET_DIR = "/68ffc927e723da37f0cde31f/"
MAX_DESCRIPTION = 12000
CANCELLED = re.compile(r"\bcancell?ed\b|\bpostponed\b|\bTBD\b", re.I)
PHOTO = re.compile(r'url\(\s*["\x27]?(https://cdn\.prod\.website-files\.com/[^" \x27)]+)', re.I)

def event_url(value):
    if not isinstance(value, str) or len(value) > 200:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "tixr.com"
                and p.username is None and p.password is None and p.port in (None, 443)
                and not p.query and not p.fragment
                and bool(re.fullmatch(r"/e/[0-9]{3,12}/?", p.path)))
    except ValueError:
        return False

def photo_url(value):
    if not isinstance(value, str) or len(value) > 1200:
        return None
    try:
        p = urlsplit(value)
        return value if (p.scheme == "https" and p.hostname == "cdn.prod.website-files.com"
                         and p.port in (None, 443) and not p.username and not p.password
                         and p.path.startswith(ASSET_DIR)
                         and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)
                         and not p.query and not p.fragment) else None
    except ValueError:
        return None

def text(el):
    return el.get_text(" ", strip=True) if el else ""

def _time(card, label):
    matches = []
    for block in card.select(".times"):
        strings = [text(x) for x in block.select(".home_events-preview_header-text")]
        if len(strings) == 2 and strings[0].lower().rstrip(": ") == label.lower():
            matches.append(strings[1])
    if len(matches) != 1 or not re.fullmatch(r"\d{1,2}:\d{2}\s*[ap]m", matches[0], re.I):
        return None
    try:
        return datetime.strptime(matches[0].strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None

def parse(html, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_unresolved")
    soup = BeautifulSoup(html, "html.parser")
    # Venue location is explicitly published in this very first-party calendar footer.
    # Never substitute a generic Gainesville city center or Webflow demo location.
    if STREET not in text(soup):
        raise ValueError("publisher_venue_unverified")
    cards = soup.select("div.cal-info.w-dyn-item")
    if not cards or len(cards) > MAX_CARDS:
        raise ValueError("publisher_calendar_shape_invalid")
    rows = {}
    for card in cards:
        a = card.select_one("a.cal-card-link[href]")
        url = a.get("href", "") if a else ""
        if not event_url(url):
            continue
        day = text(card.select_one("p.b-venue.date"))
        title = text(card.select_one(".b-show"))
        show_time = _time(card, "Show Time")
        door_time = _time(card, "Door Time")
        if not (title and day and show_time and door_time and not CANCELLED.search(title)):
            continue
        try:
            d = datetime.strptime(day, "%B %d, %Y").date()
            start = datetime.combine(d, show_time, ZoneInfo(ZONE))
        except ValueError:
            continue
        if not (now - timedelta(hours=24) <= start.astimezone(timezone.utc)
                <= now + timedelta(days=120)):
            continue
        # This publisher has no verified event end time. Never use the door clock as end.
        if not (datetime.combine(d, door_time, ZoneInfo(ZONE)) < start):
            continue
        category = ("Comedy" if re.search(r"comedy|comedian", title, re.I)
                    else "Games" if re.search(r"\bbingo\b", title, re.I)
                    else "Live Music")
        row = record(title, start.isoformat(), None, VENUE, STREET, "Gainesville",
                     url, url, category, tz=ZONE, retain_until_end=True)
        if row is None:
            continue
        featured = text(card.select_one(".event-info_featuring-wrapper"))
        # The listing has lineup facts only, not a long event description.
        # Retain the complete nonduplicative publisher text when present.
        narrative = description(featured if featured else "", limit=MAX_DESCRIPTION)
        row.update(description=narrative, timezone=ZONE, location_provenance="publisher_venue_street",
                   publisher_categories=[category],
                   publisher_status="sold_out" if "SOLD OUT" in title.upper() else "scheduled")
        poster = card.select_one(".poster[style]")
        candidate = PHOTO.search(poster.get("style", "")) if poster else None
        rows[url] = attach(row, KEY, candidate=photo_url(candidate.group(1) if candidate else None),
                           evidence_url=URL, facts={"show_time": show_time.isoformat(),
                                                   "door_time": door_time.isoformat(),
                                                   "venue_address": STREET})
    return sorted(rows.values(), key=lambda x: x["starts_at"])

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
            (source.get("feed_url"), source.get("kind"),
             source.get("platform_adapter")) != SOURCES[KEY] or
            source.get("timezone") != ZONE):
        raise ValueError("unregistered_hall_bourbon_source")
    if deadline_at is not None and monotonic() > deadline_at:
        raise ValueError("collection_deadline")
    return parse(fetch(URL, "text/html"), now=now)
