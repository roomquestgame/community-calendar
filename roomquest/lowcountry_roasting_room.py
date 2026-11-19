"""Bounded first-party Roasting Room music listings, Hilton Head Lowcountry.

Official JSON-LD MusicEvent dates and anchor detail narratives are matched
strictly. An event's end time is deliberately LEFT UNKNOWN because the publisher
does not supply one. Images are not ingested without rights review.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record, plain

KEY = "roasting_room_bluffton_sc"
URL = "https://roastingroom.live/"
HOST = "roastingroom.live"
ZONE = "America/New_York"
VENUE = "Roasting Room"
STREET = "1297 May River Road, Bluffton, SC 29910"
# U.S. Census Public_AR_Current exact numbered-address result (2026-11-19).
LAT, LNG = 32.237307650723, -80.861864789765
SOURCE = (URL, "html", "html", ZONE)
ALLOWED_HOSTS = {KEY: (HOST,)}
MAX_ITEMS = 30
MAX_DESCRIPTION = 12000
MAX_BYTES = 700000
SLUG = re.compile(r"show-[a-z0-9]+(?:-[a-z0-9]+){0,12}$")


def source_valid(source):
    return isinstance(source, dict) and source.get("source_key") == KEY and (
        source.get("feed_url"), source.get("kind"),
        source.get("platform_adapter"), source.get("timezone")) == SOURCE


def event_url(url):
    if not isinstance(url, str) or len(url) > 300:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == HOST and p.port in (None, 443)
                and not p.username and not p.password and p.path == "/"
                and not p.query and SLUG.fullmatch(p.fragment) is not None)
    except ValueError:
        return False


def collect(source, fetch, *, deadline_at=None, now=None):
    if not source_valid(source):
        raise ValueError("unregistered_roasting_room_source")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("roasting_room_unaware_now")
    body = fetch(URL, "text/html")
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_BYTES:
        raise ValueError("roasting_room_listing_size")

    soup = BeautifulSoup(body, "html.parser")
    graphs = []
    for script in soup.select('script[type="application/ld+json"]')[:8]:
        try:
            block = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(block, dict):
            graphs.extend(block.get("@graph", []))
    places = [x for x in graphs if isinstance(x, dict)
              and x.get("@id") == URL + "#venue"]
    if len(places) != 1:
        raise ValueError("roasting_room_venue_missing")
    place = places[0]
    addr = place.get("address")
    if (not isinstance(addr, dict)
            or plain(addr.get("streetAddress")) != "1297 May River Road"
            or addr.get("addressLocality") != "Bluffton"
            or addr.get("addressRegion") != "SC"
            or str(addr.get("postalCode")) != "29910"
            or addr.get("addressCountry") != "US"
            or plain(place.get("name")) != VENUE):
        raise ValueError("roasting_room_address_drift")

    details = {node.get("id"): node for node in
               soup.select("article.artist-page[id][data-show-date]")
               if SLUG.fullmatch(node.get("id", ""))}
    events = {}
    for event in graphs:
        if not isinstance(event, dict) or event.get("@type") != "MusicEvent":
            continue
        url = event.get("url")
        if not event_url(url):
            continue
        if (event.get("eventStatus") != "https://schema.org/EventScheduled"
                or event.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
                or event.get("location") != {"@id": URL + "#venue"}):
            continue
        offers = event.get("offers")
        if (not isinstance(offers, dict) or offers.get("url") != url
                or offers.get("@type") != "Offer"):
            continue
        try:
            starts = datetime.fromisoformat(event["startDate"])
        except (TypeError, ValueError, KeyError):
            continue
        if starts.tzinfo is None or not (now < starts.astimezone(timezone.utc) < now + timedelta(days=75)):
            continue
        if starts.utcoffset() != starts.astimezone(ZoneInfo(ZONE)).utcoffset():
            continue
        fragment = urlsplit(url).fragment
        detail = details.get(fragment)
        if detail is None or detail.get("data-show-date") != starts.astimezone(ZoneInfo(ZONE)).date().isoformat():
            continue
        heading = detail.select_one("h1")
        name = plain(unescape(event.get("name", "")))
        if heading is None or name != plain(heading.get_text(" ", strip=True)) or len(name) < 3:
            continue
        # Preserve the complete organizer's event narrative, not seat purchasing,
        # ticket/refund boilerplate, nav, or invented summaries.
        parts = [n.get_text(" ", strip=True) for n in detail.select("p.bio, p.bio.long, p.vibe")]
        prose = description("\n".join(parts), limit=MAX_DESCRIPTION + 1)
        if len(prose) < 65 or len(prose) > MAX_DESCRIPTION:
            continue
        identity = fragment + ":" + starts.date().isoformat()
        row = record(name, int(starts.timestamp() * 1000), None,
                     VENUE, STREET, "Bluffton", url, identity, "music",
                     LAT, LNG, ZONE)
        if row is None:
            continue
        row.update(description=prose, category="music", venue_name=VENUE,
                   venue_address=STREET, venue_city="Bluffton", lat=LAT, lng=LNG,
                   timezone=ZONE, end_time_verified=False,
                   location_provenance="census_exact_numbered_address_match_20261119",
                   category_provenance="publisher_music_event", publisher_categories=["music"])
        if identity in events and events[identity] != row:
            raise ValueError("roasting_room_conflicting_occurrence")
        events[identity] = row
    if not events:
        raise ValueError("roasting_room_no_valid_future_events")
    if len(events) > MAX_ITEMS:
        raise ValueError("roasting_room_over_capacity")
    return sorted(events.values(), key=lambda x: (x["starts_at"], x["id"]))
