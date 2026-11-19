"""First-party Winter Wonder Fest annual Anchorage event.

The official Festival JSON-LD spans December 5 noon through December 6 6pm.
The publisher explicitly states '12:00 - 6:00 PM · Both Days', so emit two
real six-hour sessions, never a fictional continuous 30-hour event. When the
publisher changes its schedule, hold for review rather than infer new dates.
No photo publishing rights have been established.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, time
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record

KEY = "winter_wonder_fest_anchorage_ak"
FEED = "https://winterwonderfestak.com/"
ZONE = "America/Anchorage"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("winterwonderfestak.com",)}
VENUE = ("Dena'ina Center", "600 W 7th Ave, Anchorage, AK 99501", "Anchorage")
# US Census Bureau matched 600 W 7TH AVE, Public_AR_Current, dated 2026-11-19.
# Street-interpolated point, not a surveyed entrance.
POINT = (61.215542722741, -149.893601953117)
POINT_EVIDENCE = "US Census address matched 600 W 7th Ave Anchorage AK 99501; street interpolation, not rooftop, 2026-11-19"
MAX_HTML = 650_000
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
FESTIVAL_NAME = re.compile(r"^Winter Wonder Fest \d{4}$")


def event_url(source_key, value):
    if source_key != KEY or value != FEED:
        return False
    p = urlsplit(value)
    return (p.scheme == "https" and p.hostname == "winterwonderfestak.com"
            and not p.username and not p.password and p.port in (None, 443)
            and p.path == "/" and not p.query and not p.fragment)


def photo_url(source_key, value):
    return None  # Site's /og-promo.png is an unlicensed candidate, not permission.


def _festival_jsonld(soup):
    found = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            items = data.get("@graph", [data])
        elif isinstance(data, list):
            items = data
        else:
            continue
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Festival":
                found.append(item)
    if len(found) != 1:
        raise ValueError("festival_metadata_missing_or_ambiguous")
    return found[0]


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_winter_wonder_fest")
    deadline = min(monotonic() + 35, deadline_at if deadline_at is not None else float("inf"))
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    now = now or datetime.now(timezone.utc)
    raw = fetch(FEED, "text/html")
    if not isinstance(raw, str) or len(raw) > MAX_HTML:
        raise ValueError("festival_page_missing_or_oversized")
    soup = BeautifulSoup(raw, "html.parser")
    event = _festival_jsonld(soup)
    title = plain(event.get("name"))
    if not FESTIVAL_NAME.fullmatch(title):
        raise ValueError("festival_event_identity_changed")
    year = int(title.rsplit(" ", 1)[-1])
    if (event.get("eventStatus") != "https://schema.org/EventScheduled"
            or event.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
            or not isinstance(event.get("organizer"), dict)
            or plain(event["organizer"].get("name")) != "Winter Wonder Fest"):
        raise ValueError("festival_status_or_organizer_unverified")
    loc = event.get("location")
    postal = loc.get("address") if isinstance(loc, dict) else None
    if (not isinstance(postal, dict) or plain(loc.get("name")) != VENUE[0]
            or plain(postal.get("streetAddress")) != "600 W 7th Ave"
            or plain(postal.get("addressLocality")) != "Anchorage"
            or plain(postal.get("addressRegion")) != "AK"
            or plain(postal.get("postalCode")) != "99501"
            or plain(postal.get("addressCountry")) != "US"):
        raise ValueError("festival_venue_unverified")
    description = plain(event.get("description"))
    if not description or len(description) > MAX_DESCRIPTION:
        raise ValueError("festival_description_missing_or_oversized")
    try:
        start = datetime.fromisoformat(event["startDate"])
        end = datetime.fromisoformat(event["endDate"])
        zone = ZoneInfo(ZONE)
        first, last = start.astimezone(zone), end.astimezone(zone)
    except (TypeError, ValueError, KeyError):
        raise ValueError("festival_dates_unverified")
    if (start.tzinfo is None or end.tzinfo is None
            or first.year != year or first.month != 12
            or (last.date() - first.date()) != timedelta(days=1)
            or first.hour != 12 or first.minute or last.hour != 18 or last.minute
            or first.utcoffset() != start.utcoffset()
            or last.utcoffset() != end.utcoffset()):
        raise ValueError("festival_dates_do_not_match_local_schedule")
    text = soup.get_text(" ", strip=True)
    evidence = (rf"\bDecember\s+{first.day}\s*(?:&|and)\s*{last.day}\s*,?\s*{year}\b")
    if (not re.search(evidence, text, re.I)
            or not re.search(r"12:00\s*[-\u2013]\s*6:00\s*PM\s*[·|]\s*Both\s+Days", text, re.I)):
        raise ValueError("festival_each_day_schedule_unverified")
    result = []
    for day in (first.date(), last.date()):
        begins = datetime.combine(day, time(12), tzinfo=zone)
        ends = datetime.combine(day, time(18), tzinfo=zone)
        if not (now < ends.astimezone(timezone.utc)
                and begins.astimezone(timezone.utc) <= now + timedelta(days=WINDOW_DAYS)):
            continue
        row = record(title, begins.isoformat(), ends.isoformat(),
                     *VENUE, FEED, "winter_wonder_fest:" + day.isoformat(),
                     "festival", lat=POINT[0], lng=POINT[1], tz=ZONE,
                     retain_until_end=True)
        if row is None:
            continue
        row.update(description=description, category="festival", timezone=ZONE,
                   location_provenance=POINT_EVIDENCE,
                   publisher_categories=["Holiday Festival", "Family Activities"],
                   publisher_details={"image_candidate_only": FEED + "og-promo.png"},
                   image_rights="unreviewed")
        row.pop("image_url", None)
        result.append(row)
    return result
