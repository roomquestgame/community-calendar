"""First-party Lanier Islands holiday program, from its live publisher calendar.

Only the explicitly published nightly 2026-27 Magical Nights of Lights dates are
admitted. The generic/dated-stale schema.org graph is intentionally never used.
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

KEY = "lanier_islands_events_ga"
HOST = "www.lanierislands.com"
LIST = "https://www.lanierislands.com/events/"
DETAIL = "https://www.lanierislands.com/holiday-events/magical-nights-of-lights/"
LINKED_EVENT = "/events/decorated-car-night/"
ZONE = "America/New_York"
VENUE = "Lanier Islands Resort"
STREET = "7000 Lanier Islands Parkway, Buford, GA 30518"
SOURCES = {KEY: (LIST, "html", "html")}
DATE = re.compile(
    r"^Dates:\s*Nightly,\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+to\s+"
    r"([A-Za-z]+\s+\d{1,2},\s+\d{4}),\s*including holidays$", re.I
)
HOURS = re.compile(r"^Hours:\s*(\d{1,2})\s*PM\s+to\s+(\d{1,2})\s*PM$", re.I)
LOCATION = re.compile(
    r"^Location:\s*Lanier Islands Resort,\s*7000 Lanier Islands Parkway,\s*Buford,\s*GA$", re.I
)
MAX_OCCURRENCES = 60


def event_url(value):
    if not isinstance(value, str) or len(value) > 300:
        return False
    p = urlsplit(value)
    return p.scheme == "https" and p.hostname == HOST and p.port in (None, 443) and (
        not p.username and not p.password and not p.query and not p.fragment
        and p.path == urlsplit(DETAIL).path
    )


def image_candidate(value):
    if not isinstance(value, str) or len(value) > 1200:
        return None
    p = urlsplit(value)
    return value if (p.scheme == "https" and p.hostname == HOST and
                     p.port in (None, 443) and not p.username and not p.password and
                     not p.query and not p.fragment and
                     p.path.startswith("/site/assets/files/") and
                     re.search(r"\.(?:jpg|jpeg|png|webp)$", p.path, re.I)) else None


def parse(listing_html, detail_html, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone_unresolved")
    # Must be linked from the actual live publisher event calendar: not a
    # historical special-event landing page or a fabricated future recurrence.
    listing = BeautifulSoup(listing_html, "html.parser")
    if not any(a.get("href", "").split("?")[0].rstrip("/") == LINKED_EVENT.rstrip("/")
               for a in listing.select("a[href]")):
        return []
    soup = BeautifulSoup(detail_html, "html.parser")
    canon = soup.select_one('link[rel="canonical"]')
    if not canon or canon.get("href") != DETAIL:
        return []
    intro = next((a for a in soup.select("article") if
                  a.select_one("h1") and
                  a.select_one("h1").get_text(" ", strip=True) == "Magical Nights of Lights"), None)
    glance = next((a for a in soup.select("article") if
                   "Magical Nights of Lights At A Glance" in a.get_text(" ", strip=True)), None)
    if not intro or not glance:
        return []
    facts = [li.get_text(" ", strip=True) for li in glance.select("li")]
    dates = next((DATE.fullmatch(x) for x in facts if x.startswith("Dates:")), None)
    hours = next((HOURS.fullmatch(x) for x in facts if x.startswith("Hours:")), None)
    has_location = any(LOCATION.fullmatch(x) for x in facts)
    if not dates or not hours or not has_location:
        return []
    try:
        first = datetime.strptime(dates[1], "%B %d, %Y").date()
        last = datetime.strptime(dates[2], "%B %d, %Y").date()
        start_hour, end_hour = int(hours[1]), int(hours[2])
    except ValueError:
        return []
    days = (last - first).days + 1
    if not (1 <= days <= MAX_OCCURRENCES and 1 <= start_hour < end_hour <= 12):
        return []
    narrative = description(str(intro), limit=12000)
    if len(narrative) >= 12000:
        return []
    og = soup.select_one('meta[property="og:image"]')
    candidate = image_candidate(og.get("content") if og else None)
    result = []
    tz = ZoneInfo(ZONE)
    for n in range(days):
        day = first + timedelta(days=n)
        start = datetime(day.year, day.month, day.day, start_hour + 12, tzinfo=tz)
        end = datetime(day.year, day.month, day.day, end_hour + 12, tzinfo=tz)
        if not (now - timedelta(hours=24) <= start.astimezone(timezone.utc) <=
                now + timedelta(days=90)):
            continue
        row = record("Magical Nights of Lights", start.isoformat(), end.isoformat(),
                     VENUE, STREET, "Buford", DETAIL, DETAIL, "Community / Social",
                     tz=ZONE, retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative, timezone=ZONE,
                   publisher_categories=["Holiday", "Family", "Light Show", "Outdoors"],
                   location_provenance="publisher_event_venue")
        result.append(attach(row, KEY, candidate=candidate, evidence_url=DETAIL))
    return result


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
            (source.get("feed_url"), source.get("kind"),
             source.get("platform_adapter")) != SOURCES[KEY] or
            source.get("timezone") != ZONE):
        raise ValueError("unregistered_lanier_source")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    listing_html = fetch(LIST, "text/html")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    detail_html = fetch(DETAIL, "text/html")
    return parse(listing_html, detail_html, now=now)
