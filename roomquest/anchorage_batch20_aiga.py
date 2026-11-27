"""Anchorage batch20: AIGA Alaska's first-party public design meetup RSS.

The WordPress iKit RSS gives complete activity descriptions; its exact-event
page provides official iCalendar date/time + actual venue street. Do not
collect member-only boards, virtual talks or other cities; never guess a pin.
This adapter is preview-only until the whole 20-source batch qualifies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import logging
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.anchorage_sources import _description, ZONE
from roomquest.mapsee_adapter import record

KEY = "aiga_alaska_design_meetups_ak"
FEED = "https://alaska.aiga.org/ikit-feed/?post_types=ikit_event%2Cikit_event_internal&type=events"
ROOT = "https://alaska.aiga.org"
SOURCES = {KEY: (FEED, "rss", "wordpress")}
ALLOWED_HOSTS = {KEY: ("alaska.aiga.org",)}
VENUE = ("W xyz Lounge", "310 West 36th Avenue, Anchorage, AK 99503", "Anchorage")
# 2026-11-19 independent US Census Bureau exact street address match.
# Street-segment interpolation, not surveyed building entrance GPS.
VENUE_LAT = 61.188015711649
VENUE_LNG = -149.886917308221
VENUE_GEO_EVIDENCE = ("US Census Bureau address geocoder Public_AR_Current; "
                      "matched 310 W 36TH AVE, ANCHORAGE AK 99503; "
                      "street-interpolated address geolocation, reviewed 2026-11-19")
MAX_DESCRIPTION = 12000
MAX_RECORDS = 24
WINDOW_DAYS = 60
PERMALINK = re.compile(r"/event/after-hours-by-design(?:-[0-9]+)?/?$")
log = logging.getLogger(__name__)


def event_url(key, url):
    if key != KEY or not isinstance(url, str) or len(url) > 1400:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == "alaska.aiga.org"
                and not p.username and not p.password and p.port in (None, 443)
                and not p.query and not p.fragment and bool(PERMALINK.fullmatch(p.path)))
    except ValueError:
        return False


def photo_url(key, value):
    return None  # No right to reproduce AIGA's event art is assumed.


def _text(node, selector):
    element = node.select_one(selector)
    return element.get_text(" ", strip=True) if element else ""


def _event(item, fetch, now, deadline):
    link = item.findtext("link") or ""
    if not event_url(KEY, link):
        return None
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    html = fetch(link, "text/html")
    if not isinstance(html, str) or len(html) > 700_000:
        raise ValueError("unverified_aiga_event_page")
    soup = BeautifulSoup(html, "html.parser")
    start = _text(soup, "var.atc_date_start")
    end = _text(soup, "var.atc_date_end")
    tz = _text(soup, "var.atc_timezone")
    title = _text(soup, "var.atc_title")
    name = _text(soup, ".event-location-name")
    street = _text(soup, ".event-location-address1")
    city_state = _text(soup, ".event-location-city-state-zip")
    if (tz != ZONE or title.casefold() != "after hours by design"
            or name.casefold() != VENUE[0].casefold()
            or street != "310 West 36th Avenue"
            or not re.fullmatch(r"Anchorage,\s*AK\s*99503", city_state, re.I)):
        return None
    try:
        starts = datetime.fromisoformat(start.replace(" ", "T")).replace(tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
        ends = datetime.fromisoformat(end.replace(" ", "T")).replace(tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
    except ValueError:
        return None
    if ends <= starts or ends <= now or starts > now + timedelta(days=WINDOW_DAYS):
        return None
    rss_description = item.findtext("description") or ""
    desc = _description(rss_description)
    if desc is None or len(desc) > MAX_DESCRIPTION:
        return None
    if not all(marker in desc.casefold() for marker in ("design", "community")):
        return None
    uid = urlsplit(link).path.strip("/").split("/")[-1]
    row = record(title, starts.isoformat(), ends.isoformat(),
                 *VENUE, link, uid, "hang_out", tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(description=desc, category="hang_out", timezone=ZONE,
               publisher_categories=["AIGA Alaska", "Design Meetup"],
               location_provenance=VENUE_GEO_EVIDENCE,
               lat=VENUE_LAT, lng=VENUE_LNG)
    return row


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get("source_key") != KEY
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[KEY]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_anchorage_aiga_source")
    deadline = min(monotonic() + 38, deadline_at if deadline_at is not None else float("inf"))
    now = calendar_anchor(now or datetime.now(timezone.utc))
    raw = fetch(FEED, "text/xml")
    if not isinstance(raw, str) or len(raw) > 800_000 or "<!DOCTYPE" in raw.upper():
        raise ValueError("invalid_aiga_rss_payload")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("invalid_aiga_rss_payload") from exc
    if root.tag != "rss":
        raise ValueError("invalid_aiga_rss_type")
    items = root.findall("./channel/item")
    if len(items) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    records = {}
    for item in items:
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        row = _event(item, fetch, now, deadline)
        if row is None:
            continue
        key = (row["id"], row["starts_at"])
        if key in records and records[key] != row:
            raise ValueError("conflicting_aiga_event_identity")
        records[key] = row
    return sorted(records.values(), key=lambda x:(x["starts_at"],x["id"]))
