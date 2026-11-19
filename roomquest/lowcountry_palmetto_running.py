"""Bounded first-party Palmetto Running Company public event calendar.

Trust only original event details, explicit local wall-clock time and event-level
GeoCoordinates. Publisher's JSON-LD incorrectly labels local wall times with Z;
we validate its calendar date/time against the visible local date rather than
treating that Z as UTC. Missing end times remain NULL.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record, plain

KEY = "palmetto_running_company_sc"
URL = "https://shop.palmettorunningcompany.com/content/events"
HOST = "shop.palmettorunningcompany.com"
ZONE = "America/New_York"
SOURCE = (URL, "html", "html", ZONE)
ALLOWED_HOSTS = {KEY: (HOST,)}
MAX_INDEX_BYTES = 350_000
MAX_DETAIL_BYTES = 300_000
MAX_DETAILS = 25
MAX_DESCRIPTION = 12000
DAYS = 75
PATH = re.compile(r"/event/([0-9]{4,8})/[A-Za-z0-9_-]{3,100}", re.I)
PRIVATE = re.compile(r"\b(residents? only|members? only|private event|closed to the public)\b", re.I)
CANCEL = re.compile(r"\b(cancelled|canceled|postponed)\b", re.I)

# Direct publisher event coordinates, not the company's store location/centroid.
# These are event-specific coordinates independently reviewed against exact
# original event pages 2026-11-19; two streets have additional Census matches.
# Fail closed on future venue/coordinate drift, rather than assigning default GEO.
VENUES = {
    "94 pope ave.": ("Celebration Park", "Hilton Head Island", "29928",
                     32.143658656436074, -80.7540233977956),
    "30 new mustang drive": ("Bluffton Middle School", "Bluffton", "29910",
                             32.254177, -80.8777152),
    "2 village park square": ("Palmetto Bluff", "Bluffton", "29910",
                             32.207898, -80.881045),
    "349 hope pond way unit 104,": ("The Grind at New River Village", "Bluffton", "29910",
                                    32.23876051265373, -80.98212402839278),
    "4211 north okatie hwy": ("John Paul II Catholic School", "Ridgeland", "29936",
                              32.35368896360131, -80.9155498897757),
}
MONTHS = {m.lower(): i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"), 1)}

def source_valid(s):
    return (isinstance(s, dict) and s.get("source_key") == KEY
            and (s.get("feed_url"), s.get("kind"), s.get("platform_adapter"),
                 s.get("timezone")) == SOURCE)

def event_url(u):
    if not isinstance(u, str) or len(u)>300:
        return False
    try:
        p = urlsplit(u)
        return (p.scheme == "https" and p.hostname == HOST and p.port in (None,443)
                and not p.username and not p.password and not p.query and not p.fragment
                and bool(PATH.fullmatch(p.path)))
    except ValueError:
        return False

def _body(fetch, url):
    b = fetch(url, "text/html")
    if isinstance(b, bytes):
        b = b.decode("utf-8", "replace")
    if not isinstance(b, str) or not b or len(b.encode("utf-8")) > (
            MAX_INDEX_BYTES if url == URL else MAX_DETAIL_BYTES):
        raise ValueError("prc_html_size")
    return BeautifulSoup(b, "html.parser")

def _local_date(page):
    d, t = page.select_one("h3 .date"), page.select_one("h3 .time")
    if d is None or t is None:
        return None
    match = re.fullmatch(
        r"([A-Za-z]+) ([0-9]{1,2})(?:st|nd|rd|th), (20[0-9]{2})",
        d.get_text(" ", strip=True))
    time = re.fullmatch(r"at ([0-9]{1,2}):([0-9]{2}) (AM|PM)",
                        t.get_text(" ", strip=True), re.I)
    if not match or not time or match.group(1).lower() not in MONTHS:
        return None
    month = MONTHS[match.group(1).lower()]
    h = int(time.group(1)) % 12 + (12 if time.group(3).upper()=="PM" else 0)
    try:
        return datetime(int(match.group(3)), month, int(match.group(2)),
                        h, int(time.group(2)), tzinfo=ZoneInfo(ZONE))
    except ValueError:
        return None

def _original_event(page):
    events = []
    for tag in page.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(data,dict) and data.get("@type") == "Event":
            events.append(data)
    return events[0] if len(events) == 1 else None

def _parse(source_link, card, page, now):
    if not event_url(source_link):
        return None
    e = _original_event(page)
    name_node = page.select_one("h1")
    narrative_node = page.select_one("#EventContent")
    local = _local_date(page)
    if not isinstance(e, dict) or name_node is None or narrative_node is None or local is None:
        return None
    if e.get("eventStatus") != "https://schema.org/EventScheduled":
        return None
    if e.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode":
        return None
    name = plain(e.get("name", ""))
    if name != plain(name_node.get_text(" ",strip=True)) or not name or CANCEL.search(name):
        return None
    teaser = card.select_one(".date")
    if teaser is None:
        return None
    index_date = plain(teaser.get_text(" ", strip=True))
    if not re.search(r"\b" + local.strftime("%b") + r"\s+" + str(local.day)
                     + r"(?:st|nd|rd|th)\b",index_date,re.I):
        return None
    if local.strftime("%I:%M %p").lstrip("0") not in index_date.upper().replace(" 0"," "):
        return None
    # The publisher's Z-labelled JSON-LD is a wall-clock value, NOT reliable UTC.
    try:
        raw = datetime.fromisoformat(e["startDate"].replace("Z","+00:00"))
    except (KeyError,ValueError,TypeError):
        return None
    if raw.replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    if not (now < local.astimezone(timezone.utc) < now + timedelta(days=DAYS)):
        return None
    location = e.get("location")
    if not isinstance(location,dict) or not isinstance(location.get("address"),dict) or not isinstance(location.get("geo"),dict):
        return None
    addr = location["address"]
    street = plain(addr.get("streetAddress", ""))
    venue = plain(location.get("name", ""))
    city = plain(addr.get("addressLocality", ""))
    zip_code = str(addr.get("postalCode", ""))
    verified = VENUES.get(street.lower().strip())
    if not verified or (venue, city, zip_code) != verified[:3] or addr.get("addressRegion") != "SC" or addr.get("addressCountry") != "US":
        return None
    try:
        lat = float(location["geo"]["latitude"])
        lng = float(location["geo"]["longitude"])
    except (ValueError,TypeError,KeyError):
        return None
    if abs(lat-verified[3])>0.0001 or abs(lng-verified[4])>0.0001:
        return None
    narrative = description(str(narrative_node),limit=MAX_DESCRIPTION+1)
    if not 70 <= len(narrative) <= MAX_DESCRIPTION or PRIVATE.search(narrative) or CANCEL.search(narrative[:100]):
        return None
    event_id = int(PATH.fullmatch(urlsplit(source_link).path).group(1))
    identity = f"prc-{event_id}:{local.date().isoformat()}"
    address = f"{street.rstrip(',')}, {city}, SC {zip_code}"
    row = record(name,int(local.timestamp()*1000),None,venue,address,city,
                 source_link,identity,"sports",lat,lng,ZONE)
    if row is None:
        return None
    row.update(description=narrative,category="sports",venue_name=venue,
               venue_address=address,venue_city=city,lat=lat,lng=lng,
               timezone=ZONE,location_provenance="publisher_event_specific_geo_20261119",
               category_provenance="publisher_athletic_event",
               publisher_categories=["running","fitness"],end_time_verified=False)
    return row

def collect(source, fetch, *, deadline_at=None, now=None):
    if not source_valid(source):
        raise ValueError("unregistered_palmetto_running_source")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("unaware_now")
    page = _body(fetch, URL)
    cards = page.select('#EventList a[href^="/event/"]')
    if not cards or len(cards)>MAX_DETAILS:
        raise ValueError("prc_index_card_bounds")
    events = {}
    for card in cards:
        href = card.get("href", "")
        url = "https://" + HOST + href
        if not event_url(url):
            continue
        detail = _body(fetch,url)
        row = _parse(url,card,detail,now)
        if row:
            if row["id"] in events and events[row["id"]]!=row:
                raise ValueError("prc_duplicate_conflict")
            events[row["id"]]=row
    if not events:
        raise ValueError("prc_no_valid_future")
    return sorted(events.values(),key=lambda x:(x["starts_at"],x["id"]))
