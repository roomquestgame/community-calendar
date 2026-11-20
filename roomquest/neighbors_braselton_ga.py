"""Original Neighbors Bar Braselton calendar: individual schema.org Event detail facts.

One real publisher per event, never general weekly opening hours or invented dates.
The index provides first-party detail links; each event page supplies its own
time, title, physical street and canonical URL. No guessed coordinates.
"""
from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlsplit, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach

KEY = "neighbors_bar_braselton_ga"
HOST = "neighborsbraselton.com"
URL = "https://neighborsbraselton.com/events"
ZONE = "America/New_York"
VENUE = "Neighbors Bar"
STREET = "6323 Grand Hickory Dr, Suite 200D"
# The first-party PostalAddress uses a comma within streetAddress before Suite.
# Preserve the exact same unit but normalize punctuation for the shared
# udell_address() parser, which requires one street/city/state split.
ADDRESS = STREET.replace(", Suite ", " Suite ") + ", Braselton, GA 30517"
MAX_DETAILS = 18
MAX_DAYS = 90
DETAIL_RE = re.compile(r"/events/[a-z0-9][a-z0-9-]{2,95}-20\d\d-\d\d-\d\d")


def event_url(value):
    if not isinstance(value, str) or len(value) > 320:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST
                and p.port in (None, 443) and p.username is None and p.password is None
                and not p.query and not p.fragment and bool(DETAIL_RE.fullmatch(p.path)))
    except ValueError:
        return False


def _event_schema(detail_html):
    soup = BeautifulSoup(detail_html, "html.parser")
    matches = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            graph = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if not isinstance(graph, dict):
            continue
        for item in graph.get("@graph", []):
            if isinstance(item, dict) and item.get("@type") in ("Event", "MusicEvent"):
                matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _datetime(value):
    if not isinstance(value, str) or len(value) > 60:
        return None
    try:
        result = datetime.fromisoformat(value)
        local = result.astimezone(ZoneInfo(ZONE))
        if (result.tzinfo is None or result.utcoffset() != local.utcoffset()
                or result.utcoffset() != result.replace(fold=1).utcoffset()):
            return None
        return result
    except (ValueError, TypeError, OverflowError):
        return None


def parse(index_html, fetch_detail, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_unresolved")
    index = BeautifulSoup(index_html, "html.parser")
    links = []
    seen = set()
    for link in index.select("a[href]"):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        candidate = urljoin(URL, href)
        if event_url(candidate) and candidate not in seen:
            links.append(candidate)
            seen.add(candidate)
    if not links:
        raise ValueError("neighbors_calendar_links_missing")
    rows = {}
    for url in links[:MAX_DETAILS]:
        facts = _event_schema(fetch_detail(url, "text/html"))
        if not facts or facts.get("url") != url:
            continue
        if (facts.get("eventStatus") != "https://schema.org/EventScheduled"
                or facts.get("eventAttendanceMode") !=
                "https://schema.org/OfflineEventAttendanceMode"):
            continue
        loc = facts.get("location")
        if not isinstance(loc, dict) or plain(loc.get("name")) != VENUE:
            continue
        address = loc.get("address")
        if (not isinstance(address, dict)
                or plain(address.get("streetAddress")) != STREET
                or plain(address.get("addressLocality")) != "Braselton"
                or plain(address.get("addressRegion")) != "GA"
                or plain(address.get("postalCode")) != "30517"
                or plain(address.get("addressCountry")) != "US"):
            continue
        org = facts.get("organizer")
        if (not isinstance(org, dict)
                or org.get("url") != "https://" + HOST
                or plain(org.get("name")) != VENUE):
            continue
        title = plain(facts.get("name"))
        if not title or re.search(r"\b(cancelled|canceled|private|postponed|members only)\b", title, re.I):
            continue
        start, end = _datetime(facts.get("startDate")), _datetime(facts.get("endDate"))
        if not start or not end or not (start < end <= start + timedelta(hours=16)):
            continue
        if not (now <= start.astimezone(timezone.utc) <= now + timedelta(days=MAX_DAYS)):
            continue
        kind = facts.get("@type")
        category = ("Music" if kind == "MusicEvent" else
                    "Community" if "giving" in title.casefold() else
                    "Hang Out")
        labels = (["Live Music", "Nightlife"] if kind == "MusicEvent" else
                  ["Community", "Social"] if category == "Community" else
                  ["Trivia", "Games", "Social"] if "trivia" in title.casefold() else
                  ["Nightlife", "Social"])
        row = record(title, start.isoformat(), end.isoformat(), VENUE, ADDRESS,
                     "Braselton", url, urlsplit(url).path.rsplit("/", 1)[-1],
                     category, tz=ZONE, retain_until_end=True)
        if row is None:
            continue
        narrative = facts.get("description")
        row.update(description=description(narrative or "", limit=12000),
                   timezone=ZONE, publisher_categories=labels,
                   location_provenance="publisher_event_structured_address")
        row = attach(row, KEY, facts={
            "publisher_event_id": urlsplit(url).path.rsplit("/", 1)[-1],
            "publisher_venue_address": ADDRESS,
            "publisher_timezone": ZONE,
        })
        identity = (row["event_url"], row["starts_at"])
        if identity in rows and rows[identity] != row:
            raise ValueError("conflicting_neighbors_occurrence")
        rows[identity] = row
    return sorted(rows.values(), key=lambda row: (row["starts_at"], row["event_url"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY or source.get("feed_url") != URL
            or source.get("kind") != "html"
            or source.get("platform_adapter") != "html"
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_neighbors_source")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    def _detail(url, accept):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        return fetch(url, accept)
    return parse(fetch(URL, "text/html"), _detail, now=now)
