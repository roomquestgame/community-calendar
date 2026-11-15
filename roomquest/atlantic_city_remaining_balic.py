"""Balic's reviewed 2026 gala poster, with clocks from the actual performers.

The winery advertises five dates but no start times. Only the two dates whose
performers currently publish explicit clocks are eligible. The complete poster
and native program text are retained; opening hours never become event times.
Every read, including the reviewed JPEG, uses the worker's guarded callback.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import record


KEY = "balic_winery_nj"
ZONE = "America/New_York"
FEED = "https://www.balicwinery.com/events.html"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.balicwinery.com", "www.bittersweetduo.com", "bethtinnon.com")}
CHECKPOINT_KEYS = frozenset()
MAX_DESCRIPTION = 12_000
MAX_IMAGE = 3_000_000
POSTER_URL = ("https://www.balicwinery.com/uploads/6/8/4/3/68439105/published/"
              "balic-winery-gala-2026-entainters-fall-1024.jpg?1793131015")
POSTER_SHA256 = "f4520c111867064b4adba04521d9bc0ab1e1355d00dd3b2f319f73dda33ea2e4"
TERRACE_IMAGE = ("https://www.balicwinery.com/uploads/6/8/4/3/68439105/editor/"
                 "terrace-0287-2000.jpg?1788975250")
BITTER_URL = "https://www.bittersweetduo.com/our-upcoming-schedule"
BETH_URL = ("https://bethtinnon.com/event/6594096/764728165/"
            "beth-tinnon-at-balic-winery-for-their-holiday-extravaganza")
BETH_TITLE = "BETH TINNON at BALIC Winery for their holiday extravaganza"
VENUE = "Balic Winery"
STREET = "6623 Harding Hwy, Mays Landing, NJ 08330"
CITY = "Mays Landing"
# Independent literals: a future edit to VENUE/STREET cannot rebind this pin.
# NJ Office of GIS score-100 PointAddress matches the winery's official street
# and corroborates its explicit point=1 map marker within approximately 3 m.
REVIEWED_VENUE_POINTS = {
    ("balic_winery_nj", "Balic Winery", "6623 Harding Hwy, Mays Landing, NJ 08330"):
        (39.460896000003, -74.791057500001),
}
POSTER_TEXT = (
    "Balic Winery\nHoliday Galas\n"
    "SAT, NOVEMBER 21-\nACOUSTIC BREEZE TRIO\n"
    "/THEY BRING THE LIVELY AND UPBEAT ATMOSPHERE TO WINERY/\n"
    "SUN, NOVEMBER 22\nFran The Piano Man\n"
    "FRI, NOVEMBER 27\nBitter Sweet Duo\n"
    "SAT, NOVEMBER 28\nBeth Tinnon\n"
    "SUN, NOVEMBER 29\nOnce Upon a Full Moon Night"
)
HELD_OCCURRENCES = (
    {"date": "2026-11-21", "title": "Acoustic Breeze Trio", "reason": "publisher_start_time_missing"},
    {"date": "2026-11-22", "title": "Fran The Piano Man", "reason": "publisher_start_time_missing"},
    {"date": "2026-11-29", "title": "Once Upon a Full Moon Night", "reason": "publisher_start_time_missing"},
)


def event_url(key, value):
    return key == KEY and isinstance(value, str) and value == FEED


def photo_url(key, value):
    return value if key == KEY and value == POSTER_URL else None


def reviewed_venue_location(key, venue, street):
    return REVIEWED_VENUE_POINTS.get((key, venue, street))


def _source(source):
    if (not isinstance(source, dict) or source.get("source_key") != KEY
            or source.get("timezone") != ZONE
            or tuple(source.get(k) for k in ("feed_url", "kind", "platform_adapter")) != SOURCES[KEY]):
        raise ValueError("balic_source_identity")


def _fetch(fetch, url, accept, deadline_at):
    if deadline_at is not None and monotonic() + 2 >= deadline_at:
        raise ValueError("collection_deadline")
    return fetch(url, accept)


def _text(node):
    value = node.get_text(" ", strip=True) if node is not None else ""
    return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())


def _plain(value):
    # Already-normalized publisher plaintext is never reparsed as HTML.
    return " ".join(value.split()) if isinstance(value, str) else ""


def _description(*parts):
    if any(not isinstance(part, str) or not part.strip() for part in parts):
        raise ValueError("balic_description_missing")
    value = "\n\n".join(parts)
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("balic_description_limit")
    return value


def _page(payload, url):
    if not isinstance(payload, str):
        raise ValueError("balic_page_changed")
    soup = BeautifulSoup(payload, "html.parser")
    identities = [n.get("content") for n in soup.select('meta[property="og:url"]')]
    canonical = [n.get("href") for n in soup.select('link[rel="canonical"]')]
    if identities != [url] or (canonical and canonical != [url]):
        raise ValueError("balic_page_identity")
    return soup


def _winery(payload, fetch, deadline_at):
    soup = _page(payload, FEED)
    headings = [h for h in soup.select("h2") if _text(h) == "Save the Dates"]
    if len(headings) != 1:
        raise ValueError("balic_manifest_changed")
    section = headings[0].parent
    urls = {urljoin(FEED, n.get("src") or "") for n in section.find_all("img")}
    if urls != {POSTER_URL, TERRACE_IMAGE}:
        raise ValueError("balic_manifest_changed")
    paragraphs = section.find_all("div", class_="paragraph", recursive=False)
    if (not paragraphs or _text(paragraphs[0]) != "Live Music November 21, 22, 27, 28, & 29th"):
        raise ValueError("balic_manifest_changed")
    page_text = _text(soup)
    if "Route 40 (6623 Harding Hwy)" not in page_text or "Mays Landing, NJ 08330" not in page_text:
        raise ValueError("balic_venue_changed")
    image = _fetch(fetch, POSTER_URL, "image/jpeg", deadline_at)
    if (not isinstance(image, bytes) or not 4 <= len(image) <= MAX_IMAGE
            or not image.startswith(b"\xff\xd8\xff")):
        raise ValueError("balic_invalid_image")
    if sha256(image).hexdigest() != POSTER_SHA256:
        raise ValueError("balic_poster_edition_changed")
    # All native announcement paragraphs are retained. The first one binds
    # the reviewed five-date manifest; later prose may grow without clipping.
    announcement = "\n".join(narrative(str(n)) for n in paragraphs)
    if re.search(r"\b(?:cancelled|canceled|postponed|sold out|private event|members only)\b", announcement, re.I):
        raise ValueError("balic_program_eligibility_changed")
    return _description(POSTER_TEXT, announcement)


def _clock(value):
    try:
        return datetime.strptime(value.replace(" ", "").upper(), "%I:%M%p").time()
    except ValueError:
        try:
            return datetime.strptime(value.replace(" ", "").upper(), "%I%p").time()
        except ValueError:
            raise ValueError("balic_clock_missing") from None


def _bittersweet(payload):
    soup = _page(payload, BITTER_URL)
    if "BITTERSWEET DUO SCHEDULE 2026" not in _text(soup):
        raise ValueError("balic_performer_year_changed")
    lines = [_text(n) for n in soup.select("p") if re.match(r"^11/27\b", _text(n)) and "Balic Winery" in _text(n)]
    if len(lines) != 1:
        raise ValueError("balic_performer_occurrence_missing")
    line = lines[0]
    match = re.fullmatch(r"11/27 Friday Balic Winery (\d{1,2}(?::\d{2})?\s*[ap]m) to (\d{1,2}(?::\d{2})?\s*[ap]m)", line, re.I)
    if not match:
        raise ValueError("balic_performer_clock_changed")
    day = date(2026, 11, 27)
    start = datetime.combine(day, _clock(match[1]), ZoneInfo(ZONE))
    end = datetime.combine(day, _clock(match[2]), ZoneInfo(ZONE))
    if end <= start:
        raise ValueError("balic_performer_clock_conflict")
    return start, end, line


def _beth(payload):
    soup = _page(payload, BETH_URL)
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(script.get_text())
        except (TypeError, ValueError):
            raise ValueError("balic_performer_json_changed") from None
        if isinstance(obj, dict) and obj.get("@type") == "MusicEvent":
            events.append(obj)
    if len(events) != 1:
        raise ValueError("balic_performer_occurrence_missing")
    item = events[0]
    location = item.get("location")
    titles = soup.select(".event-title a[href]")
    if (item.get("url") != BETH_URL or item.get("name") != BETH_TITLE
            or len(titles) != 1 or titles[0].get("href") != BETH_URL or _text(titles[0]) != BETH_TITLE
            or not isinstance(location, dict) or location.get("name") != VENUE
            or location.get("address") != "6623 Harding Hwy, Mays Landing, NJ, US"):
        raise ValueError("balic_performer_identity_changed")
    notes = soup.select(".event-notes")
    if len(notes) != 1:
        raise ValueError("balic_description_missing")
    body = narrative(str(notes[0]))
    if not body or _plain(item.get("description")) != _plain(body):
        raise ValueError("balic_performer_description_conflict")
    if (item.get("eventStatus") not in (None, "https://schema.org/EventScheduled", "http://schema.org/EventScheduled")
            or re.search(r"\b(?:cancelled|canceled|postponed|sold out|private event|members only)\b", body, re.I)):
        raise ValueError("balic_performer_eligibility_changed")
    try:
        start = datetime.fromisoformat(item["startDate"])
        end = datetime.fromisoformat(item["endDate"]) if item.get("endDate") else None
    except (KeyError, ValueError, TypeError):
        raise ValueError("balic_performer_clock_changed") from None
    if (start.date() != date(2026, 11, 28) or start.tzinfo is not None
            or end is not None and (end.date() != start.date() or end.tzinfo is not None or end <= start)):
        raise ValueError("balic_performer_clock_conflict")
    dates = soup.select(".date-long .from .date")
    starts = soup.select(".date-long .from .time")
    ends = soup.select(".date-long .to .time")
    end_conflict = (len(ends) != 1 or _clock(_text(ends[0])) != end.time()) if end is not None else bool(ends)
    if (len(dates) != 1 or _text(dates[0]) != "Saturday, November 28" or len(starts) != 1
            or _clock(_text(starts[0])) != start.time() or end_conflict):
        raise ValueError("balic_performer_clock_conflict")
    return start.replace(tzinfo=ZoneInfo(ZONE)), end.replace(tzinfo=ZoneInfo(ZONE)) if end else None, body


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("balic_timezone_required")
    page = _fetch(fetch, FEED, "text/html", deadline_at)
    common = _winery(page, fetch, deadline_at)
    bitter = _bittersweet(_fetch(fetch, BITTER_URL, "text/html", deadline_at))
    beth = _beth(_fetch(fetch, BETH_URL, "text/html", deadline_at))
    programs = [
        ("bittersweet-duo-2026-11-27", "Balic Winery Holiday Galas — Bitter Sweet Duo", *bitter),
        ("beth-tinnon-2026-11-28", BETH_TITLE, *beth),
    ]
    point = reviewed_venue_location(KEY, VENUE, STREET)
    lat, lng = point or (None, None)
    rows = []
    for native_id, title, start, end, body in programs:
        description = _description(common, body)
        if start >= current + timedelta(days=60) or (end <= current if end else start <= current):
            continue
        identity = sha256((KEY + ":" + native_id).encode()).hexdigest()
        row = record(title, start.isoformat(), end.isoformat() if end else None,
                     VENUE, STREET, CITY, FEED, identity, "", lat=lat, lng=lng,
                     tz=ZONE, retain_until_end=True)
        if row is not None:
            row.update(description=description, timezone=ZONE, attendance_mode="in_person",
                       image_url=POSTER_URL,
                       location_provenance=("reviewed_nj_ogis_point_address" if point else
                                            "reviewed_publisher_street_address_pending_geocode"))
            rows.append(row)
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
