"""First-party Modern Events Calendar (MEC): The Porch on Main, Flowery Branch GA.

Only linked, timed, physically located publisher event details are collected.
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

KEY = "porch_on_main_flowery_branch_ga"
URL = "https://visittheporch.com/"
HOST = "visittheporch.com"
ZONE = "America/New_York"
SOURCES = {KEY: (URL, "html", "html")}
PATH = re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/", re.I)
STREET = re.compile(r"^[1-9][0-9]{0,5}\s+[^,]{3,100},\s*Flowery Branch,\s*GA\s*30542$", re.I)
CLOCK = re.compile(r"^(\d{1,2}:\d{2}\s*[ap]m)\s*[-–]\s*(\d{1,2}:\d{2}\s*[ap]m)$", re.I)
MAX_DETAILS = 12
MAX_DESCRIPTION = 12000


def event_url(value):
    if not isinstance(value, str) or len(value) > 300:
        return False
    p = urlsplit(value)
    return (p.scheme == "https" and p.hostname == HOST and not p.username
            and not p.password and p.port in (None, 443) and not p.query
            and not p.fragment and bool(PATH.fullmatch(p.path)))


def image_candidate(value):
    if not isinstance(value, str) or len(value) > 1000:
        return None
    p = urlsplit(value)
    return value if (p.scheme == "https" and p.hostname == HOST
                     and not p.username and not p.password and p.port in (None, 443)
                     and p.path.startswith("/wp-content/uploads/")
                     and bool(re.search(r"\.(?:jpg|jpeg|png|webp)$", p.path, re.I))
                     and not p.query and not p.fragment) else None


def listing_urls(html):
    out = []
    for a in BeautifulSoup(html, "html.parser").select("a[href]"):
        url = urljoin(URL, a.get("href", ""))
        if event_url(url) and url not in out:
            out.append(url)
        if len(out) >= MAX_DETAILS:
            break
    return out


def _text(node):
    return node.get_text(" ", strip=True) if node else ""


def event_detail(html, url, *, now=None):
    if not event_url(url):
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone_unresolved")
    soup = BeautifulSoup(html, "html.parser")
    canon = soup.select_one('link[rel="canonical"]')
    if canon is None or canon.get("href") != url:
        return None
    title = _text(soup.select_one("h1.mec-single-title"))
    day = _text(soup.select_one(".mec-single-event-date .mec-start-date-label"))
    clock = _text(soup.select_one(".mec-single-event-time .mec-events-abbr"))
    venue = _text(soup.select_one(".mec-single-event-location .author h6"))
    street = _text(soup.select_one(".mec-single-event-location .mec-address"))
    body = soup.select_one(".mec-single-event-description.mec-events-content")
    if not title or not day or not clock or not venue or not STREET.fullmatch(street):
        return None
    if re.search(r"\bcancell?ed\b|\bpostponed\b|\bTBD\b", title, re.I):
        return None
    match = CLOCK.fullmatch(clock)
    if not match:
        return None
    try:
        date = datetime.strptime(day, "%b %d %Y")
        start = datetime.combine(date.date(), datetime.strptime(match[1].replace(" ", "").upper(), "%I:%M%p").time(), ZoneInfo(ZONE))
        end = datetime.combine(date.date(), datetime.strptime(match[2].replace(" ", "").upper(), "%I:%M%p").time(), ZoneInfo(ZONE))
    except ValueError:
        return None
    if not (now - timedelta(hours=24) <= start.astimezone(timezone.utc) <= now + timedelta(days=90)):
        return None
    if not (start < end <= start + timedelta(hours=12)):
        return None
    narrative = description(str(body) if body else "", limit=MAX_DESCRIPTION)
    if len(narrative) >= MAX_DESCRIPTION:  # prevent silently truncated publisher narratives
        return None
    tags = (["Wine Tasting", "Food & Drink"] if "wine" in title.lower()
            else ["Christmas Market", "Shopping", "Holiday"] if "market" in title.lower()
            else ["Lantern Parade", "Holiday", "Community"] if "parade" in title.lower()
            else ["Community"])
    category = "Food / Drink" if "wine" in title.lower() else "Community / Social"
    row = record(title, start.isoformat(), end.isoformat(), venue, street,
                 "Flowery Branch", url, url, category, tz=ZONE,
                 retain_until_end=True)
    if row is None:
        return None
    row.update(description=narrative, timezone=ZONE, publisher_categories=tags,
               location_provenance="publisher_event_venue")
    image = soup.select_one('meta[property="og:image"]')
    return attach(row, KEY, candidate=image_candidate(image.get("content") if image else None),
                  evidence_url=url)


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or
            (source.get("feed_url"), source.get("kind"),
             source.get("platform_adapter")) != SOURCES[KEY] or
            source.get("timezone") != ZONE):
        raise ValueError("unregistered_porch_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 72, deadline_at or float("inf"))
    rows = {}
    for url in listing_urls(fetch(URL, "text/html")):
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        item = event_detail(fetch(url, "text/html"), url, now=now)
        if item:
            rows[item["event_url"]] = item
    return sorted(rows.values(), key=lambda x: x["starts_at"])
