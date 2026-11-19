"""Official Explore Braselton Wix calendar, narrowly parsed from dated event details.

Research-stage adapter: do not register this source until its actual robots-aware
collector preview confirms current records and venue identities. The Wix URL slug
is sometimes unrelated to the visible event title; require canonical URL,
publisher-visible title/time, and event-owned street instead of guessing.
"""
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record
from roomquest.event_description import description
from roomquest.publisher_evidence import attach

KEY = "explore_braselton_official_ga"
URL = "https://www.explorebraselton.com/event-list"
HOST = "www.explorebraselton.com"
ZONE = "America/New_York"
SOURCES = {KEY: (URL, "html", "html")}
PATH = re.compile(r"/event-details/[a-z0-9]+(?:-[a-z0-9]+)*/?", re.I)
SCHEDULE = re.compile(
    r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s+(20\d{2}),\s*"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s*[-–—]\s*"
    r"(\d{1,2}:\d{2}\s*[AP]M)\b", re.I
)
LOCATION = re.compile(
    r"(?P<venue>[A-Za-z][^,]{3,90}),\s*"
    r"(?P<street>\d{1,6}\s+[^,]{3,110}),\s*"
    r"Braselton,\s*GA\s*(?P<zip>\d{5})(?:,\s*USA)?",
    re.I
)
CANCEL = re.compile(r"\bcancell?ed\b|\bpostponed\b|\bTBD\b", re.I)
MAX_DETAILS = 4  # A bounded robots-paced pass, not a whole Wix crawl.
MAX_DESCRIPTION = 12000


def event_url(value):
    if not isinstance(value, str) or len(value) > 400:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST and
                p.username is None and p.password is None and p.port in (None, 443)
                and not p.query and not p.fragment and bool(PATH.fullmatch(p.path)))
    except ValueError:
        return False


def image_candidate(value):
    if not isinstance(value, str) or len(value) > 1400:
        return None
    try:
        p = urlsplit(value)
        return (value if p.scheme == "https" and p.hostname == "static.wixstatic.com"
                and p.path.startswith("/media/") and p.port in (None, 443)
                and not p.username and not p.password and not p.query and not p.fragment
                and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I) else None)
    except ValueError:
        return None


def listing_urls(html):
    found = []
    for node in BeautifulSoup(html, "html.parser").select("a[href]"):
        value = urljoin(URL, node.get("href", ""))
        if event_url(value) and value not in found:
            found.append(value)
        if len(found) == MAX_DETAILS:
            break
    return found


def _clock(day, token):
    return datetime.combine(day, datetime.strptime(
        re.sub(r"\s+", "", token).upper(), "%I:%M%p").time(), ZoneInfo(ZONE))


def event_detail(html, url, *, now=None):
    if not event_url(url):
        return None
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("timezone_unresolved")
    soup = BeautifulSoup(html, "html.parser")
    canon = soup.select_one('link[rel="canonical"]')
    if canon is None or canon.get("href", "").rstrip("/") != url.rstrip("/"):
        return None
    heading = soup.select_one("h1")
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title or CANCEL.search(title):
        return None
    whole = soup.get_text(" ", strip=True)
    # Wix detail pages publish this labelled block; listing dates without a
    # full year are never used as evidence of a specific future occurrence.
    if whole.count("Time & Location") != 1 or whole.count("About the event") != 1:
        return None
    time_and_location = whole.split("Time & Location", 1)[1].split("About the event", 1)[0]
    matches = list(SCHEDULE.finditer(time_and_location))
    if len(matches) != 1:
        return None
    m = matches[0]
    try:
        day = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%b %d %Y").date()
        start, end = _clock(day, m[4]), _clock(day, m[5])
    except ValueError:
        return None
    if not (now - timedelta(hours=24) <= start.astimezone(timezone.utc)
            <= now + timedelta(days=90)) or not start < end <= start + timedelta(hours=15):
        return None
    address_matches = list(LOCATION.finditer(time_and_location[m.end():]))
    if len(address_matches) != 1:
        return None
    loc = address_matches[0]
    venue = loc["venue"].strip()
    street = f"{loc['street'].strip()}, Braselton, GA {loc['zip']}"
    # Exact street is on this event detail, not a site-wide coverage point.
    if not venue or CANCEL.search(time_and_location):
        return None
    body = whole.split("About the event", 1)[1]
    for tail in ("Events may sell out or details may change", "Share this event"):
        body = body.split(tail, 1)[0]
    if len(body) > MAX_DESCRIPTION * 2:
        return None
    narrative = description(body, limit=MAX_DESCRIPTION)
    if len(narrative) >= MAX_DESCRIPTION:
        return None  # never silently truncate a full publisher description
    label = ("Sports" if re.search(r"\b(?:5k|race|run|marathon)\b", title, re.I)
             else "Arts & Crafts" if re.search(r"\b(?:woodworking|craft|art class)\b", title, re.I)
             else "Food & Drink" if re.search(r"\b(?:brunch|buffet|wine tasting)\b", title, re.I)
             else "Festival" if re.search(r"\b(?:parade|festival|tree lighting)\b", title, re.I)
             else "Community")
    row = record(title, start.isoformat(), end.isoformat(), venue, street,
                 "Braselton", url, url, label, tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=narrative, timezone=ZONE, publisher_categories=[label],
               location_provenance="publisher_event_detail_street")
    img = soup.select_one('meta[property="og:image"]')
    photo = image_candidate(img.get("content") if img else None)
    return attach(row, KEY, candidate=photo, evidence_url=url)


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
            (source.get("feed_url"), source.get("kind"),
             source.get("platform_adapter")) != SOURCES[KEY] or
            source.get("timezone") != ZONE):
        raise ValueError("unregistered_explore_braselton_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 48, deadline_at or float("inf"))
    results = {}
    for url in listing_urls(fetch(URL, "text/html")):
        if monotonic() >= deadline:
            break
        event = event_detail(fetch(url, "text/html"), url, now=now)
        if event:
            results[(event["event_url"], event["starts_at"])] = event
    return sorted(results.values(), key=lambda row: row["starts_at"])
