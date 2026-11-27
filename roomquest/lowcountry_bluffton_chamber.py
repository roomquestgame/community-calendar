"""Bounded, original Greater Bluffton Chamber public events.

Only Chamber-owned category-6 listing entries with individually verified event
room/address evidence. No chamber-office centroid, syndication, member calendars,
guessed venue locations, or images without permissions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import plain, record

KEY = "greater_bluffton_chamber_sc"
HOST = "blufftonchamberofcommerce.org"
FEED = "https://" + HOST + "/events/catgid/6"
ZONE = "America/New_York"
SOURCE = (FEED, "html", "html", ZONE)
ALLOWED_HOSTS = {KEY: (HOST,)}
WINDOW_DAYS = 60
MAX_INDEX_BYTES = 450000
MAX_DETAIL_BYTES = 350000
MAX_CANDIDATES = 24
MAX_DESCRIPTION = 12000
DETAIL = re.compile(r"/events/details/[a-z0-9-]+-([1-9][0-9]{3,7})/?")
DATE = re.compile(
    r"Date and Time\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"([A-Za-z]{3})\s+(\d{1,2}),?\s+(20\d{2})\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s*[-–]\s*(\d{1,2}:\d{2}\s*[AP]M)\s+(EST|EDT)\b",
    re.I)
PRIVATE = re.compile(r"\b(residents? only|members? only|private event|invitation only|cancelled|canceled|postponed)\b", re.I)
# Source publishes events at many independently owned buildings. Never assign
# Chamber headquarters' pin to other site events. This one event room address
# has direct current publisher evidence and an independent Census street point.
VENUES = {
    "the cove": {
        "street": "97 Progressive Street",
        "name": "The Cove",
        "city": "Bluffton",
        "zip": "29910",
        "lat": 32.272939834494,
        "lng": -80.915951812245,
        "evidence": "Publisher Dec 3 2026 Get to Know Your Chamber original detail; "
                    "U.S. Census Public_AR_Current 97 Progressive Street street-address point",
    },
}
OWNED = re.compile(r"^Get to Know Your Chamber - Membership Benefits Overview - (?:November|December|January|February|March|April|May|June|July|August|September|October) 20\d{2}$", re.I)

def source_valid(source):
    return (isinstance(source, dict) and source.get("source_key") == KEY
            and tuple(source.get(k) for k in ("feed_url", "kind", "platform_adapter", "timezone")) == SOURCE)

def event_url(value):
    if not isinstance(value, str) or len(value) > 400:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST and p.port in (None, 443)
                and not p.username and not p.password and not p.query and not p.fragment
                and bool(DETAIL.fullmatch(p.path)))
    except ValueError:
        return False

def _html(fetch, url, max_size):
    response = fetch(url, "text/html")
    if isinstance(response, bytes):
        response = response.decode("utf-8", "replace")
    if not isinstance(response, str) or not response or len(response.encode("utf-8")) > max_size:
        raise ValueError("bluffton_chamber_html_invalid")
    return BeautifulSoup(response, "html.parser")

def _detail(url, claimed, soup, now):
    heading = soup.find("h1")
    title = plain(heading.get_text(" ", strip=True)) if heading else ""
    if title != claimed or not OWNED.fullmatch(title) or PRIVATE.search(title):
        return None
    panel = soup.select_one(".gz-event-details")
    if panel is None:
        raise ValueError("bluffton_chamber_detail_unrecognized")
    desc_node = panel.select_one(".gz-event-description")
    narrative = plain(desc_node.get_text(" ", strip=True)) if desc_node else ""
    if not 80 <= len(narrative) <= MAX_DESCRIPTION or PRIVATE.search(narrative):
        return None
    meta_node = panel.select_one(".gz-details-links")
    meta = plain(meta_node.get_text(" ", strip=True)) if meta_node else ""
    found = DATE.search(meta)
    if not found:
        return None
    weekday, month, day, year, clock1, clock2, abbreviation = found.groups()
    try:
        date = datetime.strptime(f"{weekday} {month} {day} {year}", "%A %b %d %Y").date()
        if date.strftime("%A").lower() != weekday.lower():
            return None
        zone = ZoneInfo(ZONE)
        start = datetime.strptime(f"{date} {clock1.upper().replace(' ', '')}", "%Y-%m-%d %I:%M%p").replace(tzinfo=zone)
        end = datetime.strptime(f"{date} {clock2.upper().replace(' ', '')}", "%Y-%m-%d %I:%M%p").replace(tzinfo=zone)
    except ValueError:
        return None
    if (start.tzname() != abbreviation.upper() or end.tzname() != abbreviation.upper()
            or not (start < end <= start + timedelta(hours=7))
            or not (now < start.astimezone(timezone.utc) < now + timedelta(days=WINDOW_DAYS))):
        return None
    if "Location " not in meta:
        return None
    venue_meta = meta.split("Location ", 1)[1].split(" Fees/Admission", 1)[0].split(" Website", 1)[0]
    venue = VENUES["the cove"]
    if (not re.search(r"\bThe Cove\b", venue_meta, re.I)
            or not re.search(r"\b97\s+Progressive\s+(?:St\.?|Street)\b", venue_meta, re.I)
            or not re.search(r"\bBluffton,?\s+SC\s+29910\b", venue_meta, re.I)):
        return None
    # Future members and the public are explicitly allowed by original description.
    if not re.search(r"\b(FUTURE|prospective|non[- ]?members?)\b", narrative, re.I):
        return None
    ident = DETAIL.fullmatch(urlsplit(url).path).group(1)
    street = venue["street"] + ", Bluffton, SC 29910"
    row = record(title, start.isoformat(), end.isoformat(), venue["name"], street,
                 venue["city"], url, "bluffton_chamber:" + ident, "learn",
                 lat=venue["lat"], lng=venue["lng"], tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=narrative, category="learn", timezone=ZONE,
               venue_name=venue["name"], venue_address=street, venue_city=venue["city"],
               lat=venue["lat"], lng=venue["lng"],
               location_provenance=venue["evidence"],
               publisher_categories=["Chamber of Commerce", "Business Education"],
               image_rights="unreviewed", end_time_verified=True)
    row.pop("image_url", None)
    return row

def collect(source, fetch, *, deadline_at=None, now=None):
    if not source_valid(source):
        raise ValueError("unregistered_bluffton_chamber_source")
    now = calendar_anchor(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("bluffton_chamber_unaware_now")
    deadline = min(monotonic() + 37, deadline_at if deadline_at is not None else float("inf"))
    listing = _html(fetch, FEED, MAX_INDEX_BYTES)
    if listing.find("title") is None or "Bluffton Chamber" not in listing.title.get_text(" ", strip=True):
        raise ValueError("bluffton_chamber_wrong_publisher")
    # Listing is limited to the Chamber's own category; do not fetch the
    # community calendar because it syndicates other publishers' events.
    links = {}
    for link in listing.select('a[href*="/events/details/"]'):
        title = plain(link.get_text(" ", strip=True))
        if not OWNED.fullmatch(title):
            continue
        href = urljoin(FEED, link.get("href", ""))
        if not event_url(href):
            raise ValueError("bluffton_chamber_invalid_detail_url")
        if href in links and links[href] != title:
            raise ValueError("bluffton_chamber_identity_conflict")
        links[href] = title
        if len(links) > MAX_CANDIDATES:
            raise ValueError("bluffton_chamber_capacity")
    if not links:
        raise ValueError("bluffton_chamber_no_original_candidates")
    rows = {}
    for url, claimed in links.items():
        if monotonic() >= deadline:
            raise ValueError("bluffton_chamber_deadline")
        item = _detail(url, claimed, _html(fetch, url, MAX_DETAIL_BYTES), now)
        if item is not None:
            fingerprint = (item["id"], item["starts_at"])
            if fingerprint in rows and rows[fingerprint] != item:
                raise ValueError("bluffton_chamber_duplicate_conflict")
            rows[fingerprint] = item
    if not rows:
        raise ValueError("bluffton_chamber_no_verified_occurrences")
    return sorted(rows.values(), key=lambda row: (row["starts_at"], row["id"]))
