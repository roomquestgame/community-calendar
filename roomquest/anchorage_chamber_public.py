"""First-party Anchorage Chamber public calendar, GrowthZone HTML.

Only individually dated public Chamber-sponsored occurrences with publisher
detail URLs, full prose, an explicit known on-site venue and reviewed street
geolocation. Nonpublic committees, virtual meetings, member-only functions,
unreviewed venues and aggregator member ads are deliberately held.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo
import re
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record

KEY = "anchorage_chamber_public_events_ak"
ROOT = "https://business.anchoragechamber.org"
FEED = ROOT + "/events/calendarcatgid/6"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("business.anchoragechamber.org",)}
ZONE = "America/Anchorage"
MAX_DESCRIPTION = 12000
MAX_HTML = 450000
MAX_CANDIDATES = 30
WINDOW_DAYS = 60
VENUES = {
    "denaina": ("Dena'ina Center", "600 W 7th Ave, Anchorage, AK 99501",
                "Anchorage", 61.215542722741, -149.893601953117),
    "gumbo": ("Gumbo House", "508 W 6th Ave, Anchorage, AK 99501",
              "Anchorage", 61.21652571019, -149.89170529566),
    "empower": ("Empower Physical Therapy", "300 E Dimond Blvd #16, Anchorage, AK 99515",
                "Anchorage", 61.144671712453, -149.877076096011),
}
GEO_EVIDENCE = ("US Census Public_AR_Current street address matched individually "
                "in Anchorage AK on 2026-11-19; street interpolation, not rooftop")
PATH = re.compile(r"/events/details/[a-z0-9]+(?:-[a-z0-9]+)*-\d{4,7}/?")
DATE = re.compile(
    r"\bDate and Time\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"([A-Za-z]{3})\s+(\d{1,2}),?\s+(20\d{2})\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s*[-–]\s*(\d{1,2}:\d{2}\s*[AP]M)\s+(AKST|AKDT)\b",
    re.I)
NOT_PUBLIC = re.compile(r"\b(?:members? only|members in good standing|private|by invitation|cancelled|canceled|postponed)\b", re.I)
QUALIFY = (
    (re.compile(r"^\"?Make it Monday\"? Forum Luncheon\b", re.I), "learn"),
    (re.compile(r"^Annual YPG White Elephant Gift Exchange\b", re.I), "hang_out"),
    (re.compile(r"^Ribbon Cutting - Empower Physical Therapy$", re.I), "hang_out"),
    (re.compile(r"^2026 Holiday Member Mixer Hosted by Anchorage Convention Centers$", re.I), "hang_out"),
)

def event_url(source_key, value):
    if source_key != KEY or not isinstance(value, str) or len(value) > 1300:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "business.anchoragechamber.org"
                and p.port in (None, 443) and not p.username and not p.password
                and not p.query and not p.fragment and bool(PATH.fullmatch(p.path)))
    except ValueError:
        return False

def photo_url(source_key, value):
    return None  # No independently cleared rights for event or sponsor art.

def _category(title):
    for pattern, category in QUALIFY:
        if pattern.search(title):
            return category
    return None

def _venue(meta, title):
    region = meta.split("Location ", 1)[-1].split(" Fees/Admission", 1)[0]
    if not region or region == meta:
        return None
    if ("Dena'ina Center" in region
            and ("600 W 7th Ave" in region
                 or (title == "2026 Holiday Member Mixer Hosted by Anchorage Convention Centers"
                     and "Third-floor" in region))):
        return VENUES["denaina"]
    if "Gumbo House" in region and re.search(r"508\s+W\s+6th\s+Ave\b", region, re.I):
        return VENUES["gumbo"]
    if ("300 E Dimond Blvd" in region and re.search(r"(?:#|Suite\s*)16\b", region, re.I)
            and title == "Ribbon Cutting - Empower Physical Therapy"):
        return VENUES["empower"]
    return None

def _months(now):
    window_start = calendar_anchor(now)
    today = window_start.astimezone(ZoneInfo(ZONE)).date()
    future = (window_start + timedelta(days=WINDOW_DAYS)).astimezone(ZoneInfo(ZONE)).date()
    year, month = today.year, today.month
    result = []
    while (year, month) <= (future.year, future.month) and len(result) <= 4:
        result.append(f"{year:04d}-{month:02d}-01")
        month += 1
        if month == 13:
            month = 1
            year += 1
    if len(result) > 4:
        raise ValueError("chamber_calendar_window_excessive")
    return result

def _parse_detail(url, claimed_title, payload, now):
    window_start = calendar_anchor(now)
    if not isinstance(payload, str) or not payload or len(payload) > MAX_HTML:
        raise ValueError("chamber_detail_unreadable")
    soup = BeautifulSoup(payload, "html.parser")
    panel = soup.select_one(".gz-event-details")
    heading = soup.find("h1") if panel else None
    title = plain(heading.get_text(" ", strip=True)) if heading else ""
    if (not title or title.casefold() != claimed_title.casefold()
            or NOT_PUBLIC.search(title) or _category(title) is None):
        return None
    desc_node = panel.select_one(".gz-event-description")
    description = plain(desc_node.get_text(" ", strip=True)) if desc_node else ""
    if not description or len(description) > MAX_DESCRIPTION or NOT_PUBLIC.search(description):
        return None
    metadata_node = panel.select_one(".gz-details-links .col-sm-5")
    metadata = plain(metadata_node.get_text(" ", strip=True)) if metadata_node else ""
    match = DATE.search(metadata)
    if not match:
        return None
    weekday, month, day, year, startclock, endclock, printedzone = match.groups()
    try:
        date_text = f"{weekday.title()} {month.title()} {day} {year}"
        day_date = datetime.strptime(date_text, "%A %b %d %Y").date()
        if day_date.strftime("%A").casefold() != weekday.casefold():
            return None
        zone = ZoneInfo(ZONE)
        starts = datetime.strptime(f"{day_date} {startclock.upper().replace(' ', '')}", "%Y-%m-%d %I:%M%p").replace(tzinfo=zone)
        ends = datetime.strptime(f"{day_date} {endclock.upper().replace(' ', '')}", "%Y-%m-%d %I:%M%p").replace(tzinfo=zone)
    except ValueError:
        return None
    if (starts.tzname() != printedzone.upper() or ends.tzname() != printedzone.upper()
            or not (starts < ends <= starts + timedelta(hours=8))
            or ends.astimezone(timezone.utc) <= window_start
            or starts.astimezone(timezone.utc) > window_start + timedelta(days=WINDOW_DAYS)):
        return None
    venue = _venue(metadata, title)
    if not venue or "Location " not in metadata or NOT_PUBLIC.search(metadata.split("Location ",1)[1].split(" Fees/Admission",1)[0]):
        return None
    # Nonmember registration on either side of a membership discount is allowed;
    # public access must be explicit and must not imply membership restriction.
    if "non-member" not in metadata.casefold() and "nonmember" not in metadata.casefold() and title != "Ribbon Cutting - Empower Physical Therapy":
        return None
    ident = urlsplit(url).path.rsplit("-", 1)[-1].strip("/")
    if not ident.isdigit():
        return None
    name, addr, city, lat, lng = venue
    row = record(title, starts.isoformat(), ends.isoformat(), name, addr, city,
                 url, "anchorage_chamber:" + ident, _category(title),
                 lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=description, category=_category(title), timezone=ZONE,
               lat=lat, lng=lng, location_provenance=GEO_EVIDENCE,
               publisher_categories=["Chamber of Commerce", "Public Chamber Events"],
               image_rights="unreviewed")
    row.pop("image_url", None)
    return row

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("timezone") != ZONE
            or (source.get("feed_url"), source.get("kind"),
                source.get("platform_adapter")) != SOURCES[KEY]):
        raise ValueError("chamber_source_mismatch")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 38, deadline_at if deadline_at is not None else float("inf"))
    # Only first-party chamber-category calendars. Member-event aggregation is not a new publisher.
    candidates = {}
    for month in _months(now):
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        html = fetch(FEED + "?m=" + month, "text/html")
        if not isinstance(html, str) or not html or len(html) > MAX_HTML:
            raise ValueError("chamber_calendar_unreadable")
        soup = BeautifulSoup(html, "html.parser")
        if not soup.find("title") or "Anchorage Chamber" not in soup.title.get_text(" ", strip=True):
            raise ValueError("chamber_calendar_wrong_publisher")
        for a in soup.select('a[href*="/events/details/"]'):
            title = plain(a.get_text(" ", strip=True))
            link = urljoin(ROOT, a["href"])
            p = urlsplit(link)
            url = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
            if not _category(title):
                continue
            if not event_url(KEY, url):
                raise ValueError("chamber_invalid_event_link")
            if url in candidates and candidates[url] != title:
                raise ValueError("chamber_conflicting_event_identity")
            candidates[url] = title
            if len(candidates) > MAX_CANDIDATES:
                raise ValueError("chamber_event_capacity_exceeded")
    output = {}
    for url, title in candidates.items():
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        row = _parse_detail(url, title, fetch(url, "text/html"), now)
        if row is None:
            continue
        identity = row["id"], row["starts_at"]
        if identity in output and output[identity] != row:
            raise ValueError("chamber_conflicting_occurrence")
        output[identity] = row
    return sorted(output.values(), key=lambda x: (x["starts_at"], x["id"]))
