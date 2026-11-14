"""Independent Atlantic City-area social schedules with complete native prose.

Clancy's publishes a Simple Calendar month grid backed by its Google calendar.
Read the publisher's complete event-description nodes and explicit occurrences;
do not project weekly recurrences beyond the dates present in that grid.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import plain, record, timestamp


ZONE = "America/New_York"
CLANCY = "clancys_by_the_bay_nj"
URL = "https://clancysrestaurantgroup.com/calendar/clancys-by-the-bay/"
SOURCES = {CLANCY: (URL, "html", "html")}
ALLOWED_HOSTS = {CLANCY: ("clancysrestaurantgroup.com",)}
VENUE = ("Clancy's By The Bay", "101 E Maryland Ave, Somers Point, NJ 08244", "Somers Point")
NATIVE_ADDRESS = "Clancy's By the Bay, 101 E Maryland Ave, Somers Point, NJ 08244, USA"
# NJ Office of GIS returned score-100 PointAddress for this exact publisher
# street, town and postal code on November 14, 2026. The unqualified Maryland
# Avenue alternative was a different, lower-score street-interpolated match.
VENUE_POINT = (39.318957000003, -74.589232500001)
REVIEWED_POINT_KEY = (CLANCY, "Clancy's By The Bay", "101 E Maryland Ave, Somers Point, NJ 08244")
CALENDAR = "cpmenub0ufsf5cpqej9nfkber0@g"
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|closed|private event|private party)\b", re.I)


def _native_identity(node, start):
    links = node.select('a[href*="google.com/calendar/event"]')
    if len(links) != 1:
        raise ValueError("atlantic_social_event_identity_changed")
    parsed = urlsplit(links[0]["href"])
    query = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.netloc != "www.google.com"
            or parsed.path != "/calendar/event" or parsed.fragment
            or set(query) != {"eid", "ctz"} or query.get("ctz") != [ZONE]
            or len(query["eid"]) != 1):
        raise ValueError("atlantic_social_event_identity_changed")
    encoded = query["eid"][0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,300}", encoded):
        raise ValueError("atlantic_social_event_identity_changed")
    try:
        identity, calendar = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode().split(" ")
    except (ValueError, UnicodeError):
        raise ValueError("atlantic_social_event_identity_changed") from None
    match = re.fullmatch(r"([a-z0-9]{10,50})_(\d{8}T\d{6}Z)", identity)
    if (calendar != CALENDAR or not match
            or match[2] != start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")):
        raise ValueError("atlantic_social_event_identity_changed")
    return "clancy:" + identity


def _time(node, edge):
    nodes = node.select(f".simcal-event-{edge}-time")
    if len(nodes) != 1:
        raise ValueError("atlantic_social_schedule_changed")
    stamp = nodes[0].get("content", "")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", stamp):
        raise ValueError("atlantic_social_schedule_changed")
    value = timestamp(stamp)
    local = value.astimezone(ZoneInfo(ZONE))
    try:
        epoch = int(nodes[0].get("data-event-" + edge, ""))
        visible = datetime.strptime(re.sub(r"\s+", "", nodes[0].get_text()), "%I:%M%p").time()
    except (ValueError, TypeError):
        raise ValueError("atlantic_social_schedule_changed") from None
    if (int(value.timestamp()) != epoch or local.utcoffset() != value.utcoffset()
            or local.time().replace(tzinfo=None) != visible):
        raise ValueError("atlantic_social_schedule_changed")
    return value


def parse_calendar(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    calendars = soup.select('.simcal-calendar[data-calendar-id="1642"]')
    if len(calendars) != 1:
        raise ValueError("atlantic_social_calendar_changed")
    calendar = calendars[0]
    month = calendar.select_one(".simcal-current-month")
    year = calendar.select_one(".simcal-current-year")
    try:
        current = datetime.strptime(plain(month.get_text()) + " " + plain(year.get_text()), "%B %Y")
    except (ValueError, AttributeError):
        raise ValueError("atlantic_social_calendar_changed") from None
    items = calendar.select("li.simcal-event")
    if len(items) > 500:
        raise ValueError("atlantic_social_record_limit")
    output = {}
    for item in items:
        title_node = item.select_one('[itemprop="name"].simcal-event-title')
        title = plain(title_node.get_text()) if title_node else ""
        if not title or len(title) > 180:
            raise ValueError("atlantic_social_event_identity_changed")
        if NONPUBLIC.search(title):
            continue
        start, end = _time(item, "start"), _time(item, "end")
        local = start.astimezone(ZoneInfo(ZONE))
        if ((local.year, local.month) != (current.year, current.month)
                or end <= start or end - start > timedelta(days=1)):
            raise ValueError("atlantic_social_schedule_changed")
        identity = _native_identity(item, start)
        if not (start < now + timedelta(days=60) and end > now):
            continue
        address = item.select_one('[itemprop="address"]')
        if not address or address.get("content") != NATIVE_ADDRESS:
            raise ValueError("atlantic_social_venue_changed")
        descriptions = item.select(".simcal-event-description")
        if len(descriptions) != 1:
            raise ValueError("atlantic_city_description_missing")
        # This is the complete native field, not the short grid title or an
        # excerpt. The shared normalizer rejects blank and over-limit prose.
        body = narrative(str(descriptions[0]))
        point = VENUE_POINT if (CLANCY, *VENUE[:2]) == REVIEWED_POINT_KEY else (None, None)
        row = record(title, start.isoformat(), end.isoformat(), *VENUE,
                     URL, identity, lat=point[0], lng=point[1],
                     tz=ZONE, retain_until_end=True)
        if row is not None:
            row.update(description=body, attendance_mode="in_person", timezone=ZONE,
                       location_provenance=("reviewed_nj_ogis_point_address" if point[0] is not None
                                            else "publisher_street_pending_geocode"))
            if identity in output and output[identity] != row:
                raise ValueError("atlantic_social_duplicate_occurrence")
            output[identity] = row
    return sorted(output.values(), key=lambda row: (row["starts_at"], row["id"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "kind", "platform_adapter", "timezone")) != (
            CLANCY, URL, "html", "html", ZONE):
        raise ValueError("unregistered_atlantic_social_source")
    return parse_calendar(fetch(URL, "text/html"), now or datetime.now(timezone.utc))
