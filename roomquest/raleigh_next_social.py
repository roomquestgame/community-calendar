"""Public Raleigh Brewing and Longleaf calendars, with complete native details.

Wix's listing exposes the next instance of a series. Its own dated links and,
when needed, its public occurrence manifest account for every advertised date.
Every eligible occurrence still reads its complete detail body. No weekly dates
are inferred from a title. Squarespace's explicit dated cards are hydrated from
their complete post bodies. All I/O uses the shared guarded transport.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.chase_city_chamber import _times
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.raleigh_direct_community import _body, _digest, _schemas, _within

ZONE = "America/New_York"
BREWING = "raleigh_brewing_neil_st_nc"
LONGLEAF = "longleaf_hotel_raleigh_nc"
SOURCES = {
    BREWING: ("https://www.raleighbrewing.com/upcoming-events", "html", "html"),
    LONGLEAF: ("https://www.thelongleafhotel.com/events", "html", "html"),
}
LABELS = {BREWING: "Raleigh Brewing — Neil Street", LONGLEAF: "The Longleaf Hotel & Lounge"}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {key: 100 for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: 200 for key in SOURCES}
MAX_FETCHES = 3
MAX_CHECKPOINT_BYTES = 850_000
WIX_APP = "140603ad-af8d-84a5-2c80-a0f60cb47351"
WIX_INSTANCE = "d9b6ce78-f5e4-4cc7-8760-95ba5b961194"
WIX_METASITE = "095eb44b-7f9f-4b83-bdae-f9685310e8c0"
WIX_API = "https://www.raleighbrewing.com/_api/wix-one-events-server/web/events/"
HOTEL_SITE = "5ce6c597bf8b2d000159fcd5"
HOTEL_COLLECTION = "60cbe7b63838956a5aab62da"
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
HOLD_CODES = {"raleigh_direct_description_missing", "raleigh_direct_description_limit",
              "raleigh_next_social_nonpublic", "raleigh_next_social_schedule_unresolved"}
ERROR_CODES = HOLD_CODES | {
    "unregistered_raleigh_next_social", "raleigh_next_social_calendar_changed",
    "raleigh_next_social_detail_changed", "raleigh_next_social_location_changed",
    "raleigh_next_social_occurrences_incomplete", "raleigh_next_social_record_limit",
    "raleigh_next_social_checkpoint_invalid", "publisher_checkpoint_required", "collection_deadline",
    "invalid_raleigh_brewing_request",
}
STATE_KEYS = {"version", "source_key", "started_at", "window_start", "completion_profile", "phase",
              "listing_complete", "queue", "cursor", "manifest_count", "manifest_hash", "events",
              "diagnostics", "series_counts", "series_urls", "excluded_urls", "source_listing_count",
              "api_progress", "outcomes", "payload_hash"}


def valid_brewing_public_instance(value):
    """Accept only the anonymous instance emitted by this publisher's page."""
    try:
        if not isinstance(value, str) or len(value) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]+", value):
            return False
        encoded = value.split(".", 1)[1]
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return (data.get("instanceId") == WIX_INSTANCE and data.get("appDefId") == WIX_APP
                and data.get("metaSiteId") == WIX_METASITE and data.get("demoMode") is False
                and not any(data.get(k) for k in ("uid", "permissions", "visitorId")))
    except (ValueError, TypeError, AttributeError):
        return False


def brewing_occurrences_url(event_id, offset):
    if not isinstance(event_id, str) or not UUID.fullmatch(event_id) or type(offset) is not int or not 0 <= offset < 100:
        raise ValueError("invalid_raleigh_brewing_request")
    return WIX_API + event_id + "/occurrences?status=0&status=1&locale=en-US&offset=" + str(offset)


def valid_brewing_occurrences_request(url, public_instance):
    if not isinstance(url, str) or not valid_brewing_public_instance(public_instance):
        return False
    match = re.fullmatch(re.escape(WIX_API) + r"([a-f0-9-]{36})/occurrences\?status=0&status=1&locale=en-US&offset=(0|[1-9][0-9]?)", url)
    try:
        return bool(match and url == brewing_occurrences_url(match[1], int(match[2])))
    except ValueError:
        return False


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1500:
        return False
    try:
        p = urlsplit(value)
        prefix = "/event-details/" if key == BREWING else "/events/"
        return bool(p.scheme == "https" and p.netloc == ALLOWED_HOSTS[key][0]
                    and not p.query and not p.fragment and not p.username and not p.password
                    and re.fullmatch(re.escape(prefix) + r"[a-z0-9]+(?:-[a-z0-9]+)*", p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.username or p.password or p.query or p.fragment
                or p.netloc != p.hostname or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)):
            return None
        if key == LONGLEAF:
            valid = p.hostname == "images.squarespace-cdn.com" and p.path.startswith("/content/v1/" + HOTEL_SITE + "/")
        else:
            valid = (p.hostname == "static.wixstatic.com"
                     and re.fullmatch(r"/media/(?:6fb289|7d00a3)_[a-f0-9]{32}(?:~|%7E)mv2\.(?:png|jpe?g|webp)", p.path, re.I))
        return value if valid else None
    except ValueError:
        return None


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or tuple(source.get(k) for k in ("feed_url", "kind", "platform_adapter", "timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_raleigh_next_social")
    return key


def _canonical(soup, url):
    links = soup.select('link[rel="canonical"][href]')
    if len(links) != 1 or links[0]["href"] != url:
        raise ValueError("raleigh_next_social_detail_changed")


def _real_time(value):
    result = timestamp(value)
    if result is None or result.utcoffset() is None:
        raise ValueError("raleigh_next_social_schedule_unresolved")
    return result.astimezone(timezone.utc)


def _hotel_street(value):
    cleaned = re.sub(r"\s*,?\s*United States\s*$", "", str(value or ""), flags=re.I)
    cleaned = re.sub(r"[\n,\s]+", " ", cleaned).strip()
    if cleaned != "300 North Dawson Street Raleigh NC 27603":
        raise ValueError("raleigh_next_social_location_changed")
    return "300 North Dawson Street, Raleigh, NC 27603"


def _hotel_context(soup):
    contexts = []
    for node in soup.select("script"):
        text = node.string or node.get_text()
        match = re.search(r"\bStatic\.SQUARESPACE_CONTEXT\s*=\s*", text)
        if match:
            try:
                contexts.append(json.JSONDecoder().raw_decode(text[match.end():])[0])
            except (ValueError, TypeError):
                raise ValueError("raleigh_next_social_calendar_changed") from None
    if len(contexts) != 1:
        raise ValueError("raleigh_next_social_calendar_changed")
    data = contexts[0]
    website, collection = data.get("website") or {}, data.get("collection") or {}
    if (website.get("id") != HOTEL_SITE or website.get("timeZone") != ZONE
            or collection.get("id") != HOTEL_COLLECTION or collection.get("fullUrl") != "/events"
            or collection.get("permissionType") != 1):
        raise ValueError("raleigh_next_social_calendar_changed")
    # This venue point may be used only after the event itself names the same
    # venue and complete street. It is never a calendar-wide fallback location.
    location = website.get("location") or {}
    _hotel_street(" ".join(str(location.get(k, "")) for k in ("addressLine1", "addressLine2")))
    if location.get("addressTitle") != "The Longleaf Hotel":
        raise ValueError("raleigh_next_social_location_changed")
    lat, lng = location.get("mapLat"), location.get("mapLng")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lng)) or not (35.78 < lat < 35.79 and -78.65 < lng < -78.63):
        raise ValueError("raleigh_next_social_location_changed")
    return lat, lng


def _visible_hotel_times(card, start, end):
    clocks = card.select(".eventlist-meta-time span.event-time-24hr time")
    if not clocks:
        clocks = card.select(".eventlist-meta-time time.event-time-24hr")
    if len(clocks) != 2:
        raise ValueError("raleigh_next_social_schedule_unresolved")
    for node, instant in zip(clocks, (start, end)):
        local = instant.astimezone(ZoneInfo(ZONE))
        if node.get("datetime") != local.date().isoformat() or plain(node.get_text()) != local.strftime("%H:%M"):
            raise ValueError("raleigh_next_social_schedule_unresolved")


def _hotel_listing(payload, anchor, diagnostics):
    soup = BeautifulSoup(payload, "html.parser")
    _canonical(soup, SOURCES[LONGLEAF][0])
    lat, lng = _hotel_context(soup)
    if not soup.select_one(".eventlist") or soup.select(".eventlist-pagination a"):
        raise ValueError("raleigh_next_social_calendar_changed")
    cards = soup.select("article.eventlist-event--upcoming")
    if len(cards) > 100:
        raise ValueError("raleigh_next_social_record_limit")
    queue = []
    for card in cards:
        link = card.select_one(".eventlist-title-link[href]")
        marker = card.select_one(".sqs-simple-like[data-item-id]")
        if link is None or marker is None:
            raise ValueError("raleigh_next_social_calendar_changed")
        url = urljoin(SOURCES[LONGLEAF][0], link["href"])
        title, identity = plain(link.get_text()), marker["data-item-id"]
        if not title or not re.fullmatch(r"[a-f0-9]{24}", identity) or not event_url(LONGLEAF, url):
            raise ValueError("raleigh_next_social_calendar_changed")
        try:
            start, end, query = _times(card)
            if start is None or end is None:
                raise ValueError("raleigh_next_social_schedule_unresolved")
            _visible_hotel_times(card, start, end)
            if not _within(start, end, anchor):
                continue
            if end - start > timedelta(days=8):
                raise ValueError("raleigh_next_social_schedule_unresolved")
            locations = query.get("location", [])
            if len(locations) != 1:
                raise ValueError("raleigh_next_social_location_changed")
            street = _hotel_street(locations[0])
            address_node = card.select_one(".eventlist-meta-address")
            name = re.sub(r"\s*\(map\)\s*$", "", plain(address_node.get_text()) if address_node else "")
            if name != "The Longleaf Hotel":
                raise ValueError("raleigh_next_social_location_changed")
            image = card.select_one(".eventlist-column-thumbnail img")
            queue.append(dict(kind="native", native_id=identity, title=title, url=url,
                start=start.isoformat(), end=end.isoformat(), venue=name, street=street, lat=lat, lng=lng,
                image=photo_url(LONGLEAF, image.get("data-image") if image else None)))
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            diagnostics.append(dict(event_url=url, reason=str(exc)))
    return queue, len(cards)


def _wix_state(payload, detail=False):
    soup = BeautifulSoup(payload, "html.parser")
    nodes = soup.select("script#wix-warmup-data")
    if len(nodes) != 1:
        raise ValueError("raleigh_next_social_calendar_changed")
    try:
        data = json.loads(nodes[0].string or nodes[0].get_text())["appsWarmupData"][WIX_APP]
        widget = data["EventsPageInitialState" if detail else "widgetcomp-ltyv4rsv"]
        if widget["instance"]["instanceId"] != WIX_INSTANCE:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("raleigh_next_social_calendar_changed") from None
    return soup, widget


def _brewing_packet(native):
    try:
        url = "https://www.raleighbrewing.com/event-details/" + native["slug"]
        if not event_url(BREWING, url) or not UUID.fullmatch(native["id"]) or native.get("instanceId") != WIX_INSTANCE:
            raise ValueError
        location = native["location"]
        full = location["fullAddress"]
        if full.get("city") != "Raleigh":
            return None  # The same publisher also operates a separate Smithfield venue.
        street = re.sub(r",\s*USA\s*$", "", location["address"])
        if (street != "3709 Neil St, Raleigh, NC 27607" or full.get("country") != "US"
                or full.get("subdivision") != "NC" or full.get("postalCode") != "27607"
                or location.get("type") != 0 or location.get("tbd") is not False
                or location.get("name") not in ("3709 Neil St", "Raleigh Brewing", "Raleigh Brewing Company")):
            raise ValueError("raleigh_next_social_location_changed")
        coordinates, geocode = location["coordinates"], full["geocode"]
        lat, lng = coordinates["lat"], coordinates["lng"]
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lng))
                or not (35.78 < lat < 35.81 and -78.70 < lng < -78.68)
                or not math.isclose(lat, geocode["latitude"], abs_tol=1e-7, rel_tol=0)
                or not math.isclose(lng, geocode["longitude"], abs_tol=1e-7, rel_tol=0)):
            raise ValueError("raleigh_next_social_location_changed")
        config = native["scheduling"]["config"]
        if config.get("scheduleTbd") is not False or config.get("timeZoneId") != ZONE or config.get("endDateHidden") is not False:
            raise ValueError("raleigh_next_social_schedule_unresolved")
        start, end = _real_time(config["startDate"]), _real_time(config["endDate"])
        if end <= start or end - start > timedelta(days=1):
            raise ValueError("raleigh_next_social_schedule_unresolved")
        recurrence = config.get("recurrences") or {}
        series = recurrence.get("categoryId") or native["id"]
        if not UUID.fullmatch(series) or (recurrence and (recurrence.get("status") not in (1, 2) or recurrence.get("occurrences") != [])):
            raise ValueError("raleigh_next_social_calendar_changed")
        return dict(kind="native", native_id=native["id"], series_id=series,
                    title=plain(native["title"]), url=url, start=start.isoformat(), end=end.isoformat(),
                    venue=location["name"], street=street, lat=lat, lng=lng,
                    image=photo_url(BREWING, (native.get("mainImage") or {}).get("url")))
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
        if str(exc) in ERROR_CODES:
            raise
        raise ValueError("raleigh_next_social_calendar_changed") from None


def _brewing_listing(payload, anchor, diagnostics):
    soup, widget = _wix_state(payload)
    _canonical(soup, SOURCES[BREWING][0])
    listing = widget.get("events") or {}
    native = listing.get("events")
    if (listing.get("hasMore") is not False or listing.get("filterType") != 2
            or not isinstance(native, list) or len(native) > 100):
        raise ValueError("raleigh_next_social_calendar_changed")
    queue = []
    for event in native:
        try:
            packet = _brewing_packet(event)
            if packet is None:
                diagnostics.append(dict(native_id=str(event.get("id", "")), reason="publisher_other_city"))
            elif _within(_real_time(packet["start"]), _real_time(packet["end"]), anchor):
                queue.append(packet)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            diagnostics.append(dict(native_id=str(event.get("id", "")), reason=str(exc)))
    return queue, len(native)


def _row(key, item, body):
    identity = "raleigh:" + _digest([key, item["url"], item["start"]])
    result = record(item["title"], item["start"], item["end"], item["venue"], item["street"],
        "Raleigh", item["url"], identity, lat=item["lat"], lng=item["lng"], tz=ZONE,
        publisher_geo=True, retain_until_end=True)
    if result is None:
        raise ValueError("raleigh_next_social_schedule_unresolved")
    result.update(description=body, timezone=ZONE, attendance_mode="in_person",
        location_provenance="publisher_event_geo" if key == BREWING else "publisher_named_venue_and_matching_street_geo",
        location_evidence_url=item["url"], schedule_provenance="publisher_explicit_dated_occurrence")
    if item.get("image"):
        result["image_url"] = item["image"]
    return result


def _hotel_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    _canonical(soup, item["url"])
    lat, lng = _hotel_context(soup)
    heading = soup.select_one("article.eventitem .eventitem-title")
    content = soup.select_one('article.eventitem .eventitem-column-content [data-layout-label="Post Body"]')
    schemas = _schemas(soup)
    if (heading is None or plain(heading.get_text()) != item["title"] or content is None
            or content.get("id") != "item-" + item["native_id"] or len(schemas) != 1):
        raise ValueError("raleigh_next_social_detail_changed")
    event = schemas[0]
    if plain(event.get("name")) != item["title"] + " | The Longleaf Hotel":
        raise ValueError("raleigh_next_social_detail_changed")
    if (_real_time(event.get("startDate")).isoformat() != item["start"]
            or _real_time(event.get("endDate")).isoformat() != item["end"]):
        raise ValueError("raleigh_next_social_schedule_unresolved")
    location = event.get("location") or {}
    if (location.get("name") != item["venue"] or _hotel_street(location.get("address")) != item["street"]
            or (lat, lng) != (item["lat"], item["lng"])):
        raise ValueError("raleigh_next_social_location_changed")
    body = _body(content)
    # Preserve an explicitly week-long promotion as one native interval. A
    # performance accidentally dated over several days is not expanded or kept.
    if _real_time(item["end"]) - _real_time(item["start"]) > timedelta(days=1):
        if not re.search(r"\bevery week\b", body, re.I) or not item["title"].startswith("Bottle of the Week:"):
            raise ValueError("raleigh_next_social_schedule_unresolved")
    return _row(LONGLEAF, item, body)


def _suggested_start(suggestion):
    slug = suggestion.get("slug")
    match = re.fullmatch(r"[a-z0-9-]+-(\d{4}-\d{2}-\d{2})-(\d{2})-(\d{2})", slug or "")
    if not match:
        raise ValueError("raleigh_next_social_occurrences_incomplete")
    start = timestamp(f"{match[1]}T{match[2]}:{match[3]}:00", ZONE)
    shown = re.sub(r"\s+", " ", suggestion.get("shortStartDateTime", "")).strip()
    expected = start.strftime("%a, %b %d, %I:%M %p").replace(", 0", ", ")
    if shown != expected:
        raise ValueError("raleigh_next_social_occurrences_incomplete")
    return start.astimezone(timezone.utc)


def _discover_occurrences(state, packet, widget, anchor):
    series = packet["series_id"]
    count, suggestions = widget.get("upcomingOccurrencesCount"), widget.get("upcomingOccurrencesSuggestions")
    if type(count) is not int or not 1 <= count <= 100 or not isinstance(suggestions, list) or len(suggestions) > 100:
        raise ValueError("raleigh_next_social_occurrences_incomplete")
    if series in state["series_counts"] and state["series_counts"][series] != count:
        raise ValueError("raleigh_next_social_occurrences_incomplete")
    state["series_counts"][series] = count
    known = set(state["series_urls"].get(series, [])) | {packet["url"]}
    queued = {item["url"] for item in state["queue"]}
    for suggestion in suggestions:
        start = _suggested_start(suggestion)
        url = "https://www.raleighbrewing.com/event-details/" + suggestion["slug"]
        if not event_url(BREWING, url):
            raise ValueError("raleigh_next_social_occurrences_incomplete")
        known.add(url)
        if start >= anchor + timedelta(days=60) or start + timedelta(days=1) <= anchor:
            if url not in state["excluded_urls"]:
                state["excluded_urls"].append(url)
            continue
        if url not in queued:
            state["queue"].append(dict(kind="wix_occurrence", url=url, series_id=series, start=start.isoformat()))
            queued.add(url)
    state["series_urls"][series] = sorted(known)


def _brewing_detail(state, item, payload, anchor):
    soup, widget = _wix_state(payload, detail=True)
    _canonical(soup, item["url"])
    native = (widget.get("event") or {}).get("event")
    packet = _brewing_packet(native)
    if packet is None or packet["url"] != item["url"] or packet["series_id"] != item["series_id"]:
        raise ValueError("raleigh_next_social_detail_changed")
    if ((item["kind"] == "native" and packet != item) or packet["start"] != item["start"]
            or (item.get("native_id") is not None and packet["native_id"] != item["native_id"])):
        raise ValueError("raleigh_next_social_detail_changed")
    schemas = _schemas(soup)
    if len(schemas) != 1 or schemas[0].get("name") != packet["title"]:
        raise ValueError("raleigh_next_social_detail_changed")
    event = schemas[0]
    _discover_occurrences(state, packet, widget, anchor)
    if (event.get("eventStatus") != "https://schema.org/EventScheduled"
            or event.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
            or native.get("status") not in (0, 1)
            or (native.get("registration") or {}).get("restrictedTo") not in (None, 0)):
        raise ValueError("raleigh_next_social_nonpublic")
    if (_real_time(event.get("startDate")).isoformat() != packet["start"]
            or _real_time(event.get("endDate")).isoformat() != packet["end"]):
        raise ValueError("raleigh_next_social_schedule_unresolved")
    location = event.get("location") or {}
    if (location.get("url") != item["url"] or location.get("name") != packet["venue"]
            or re.sub(r",\s*USA\s*$", "", location.get("address", "")) != packet["street"]):
        raise ValueError("raleigh_next_social_location_changed")
    nodes = soup.select('[data-hook="about-section"] [data-id="content-viewer"]')
    if len(nodes) > 1:
        raise ValueError("raleigh_next_social_detail_changed")
    # A body takes priority over the short JSON-LD teaser. If the publisher has
    # no longer body, retain its complete standalone description when present.
    body = _body(nodes[0] if nodes else event.get("description"))
    if not _within(_real_time(packet["start"]), _real_time(packet["end"]), anchor):
        raise ValueError("raleigh_next_social_schedule_unresolved")
    return _row(BREWING, packet, body)


def _pending_series(state):
    for series, count in state["series_counts"].items():
        progress = state["api_progress"].get(series)
        if ((progress is not None and progress["offset"] < progress["total"])
                or len(state["series_urls"].get(series, [])) < count):
            return series
    return None


def _occurrence_page(state, series, payload, anchor):
    """Reconcile the native paginated manifest; descriptions still use details."""
    try:
        data = json.loads(payload)
        progress = state["api_progress"][series]
        native, dates = data["events"], data["dates"]["events"]
        if (type(data["total"]) is not int or data["total"] != progress["total"]
                or not isinstance(native, list) or not 1 <= len(native) <= 100
                or progress["offset"] + len(native) > data["total"]
                or not isinstance(dates, dict)):
            raise ValueError
        queued = {item["url"]: item for item in state["queue"]}
        known = set(state["series_urls"].get(series, []))
        for event in native:
            packet = _brewing_packet(event)
            if (packet is None or packet["series_id"] != series or event.get("status") not in (0, 1)
                    or (event.get("registration") or {}).get("restrictedTo") not in (None, 0)
                    or packet["native_id"] in progress["ids"] or packet["url"] in progress["urls"]):
                raise ValueError
            shown = dates[packet["native_id"]]
            if (_real_time(shown["startDateISOFormatNotUTC"]).isoformat() != packet["start"]
                    or _real_time(shown["endDateISOFormatNotUTC"]).isoformat() != packet["end"]):
                raise ValueError
            progress["ids"].append(packet["native_id"])
            progress["urls"].append(packet["url"])
            known.add(packet["url"])
            prior = queued.get(packet["url"])
            if prior is not None:
                fields = ("series_id", "start") if prior["kind"] == "wix_occurrence" else (
                    "native_id", "series_id", "title", "start", "end", "venue", "street", "lat", "lng")
                if any(prior[k] != packet[k] for k in fields):
                    raise ValueError
            elif _within(_real_time(packet["start"]), _real_time(packet["end"]), anchor):
                item = {k: packet[k] for k in ("url", "series_id", "native_id", "start")}
                item["kind"] = "wix_occurrence"
                state["queue"].append(item)
                queued[packet["url"]] = item
            elif packet["url"] not in state["excluded_urls"]:
                state["excluded_urls"].append(packet["url"])
        progress["offset"] += len(native)
        state["series_urls"][series] = sorted(known)
        if (len(known) > progress["total"] or len(state["queue"]) > 100
                or (progress["offset"] == progress["total"] and set(progress["urls"]) != known)):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        raise ValueError("raleigh_next_social_occurrences_incomplete") from None


def _seal(state):
    state["manifest_count"] = len(state["queue"])
    state["manifest_hash"] = _digest(state["queue"])
    state["payload_hash"] = _digest({k: v for k, v in state.items() if k != "payload_hash"})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("raleigh_next_social_record_limit")


def checkpoint_complete(state):
    queue = state.get("queue", [])
    series = {item["series_id"] for item in queue if "series_id" in item}
    return bool(state.get("completion_profile") == "social_v1" and state.get("phase") == "details"
        and state.get("listing_complete") is True and state.get("cursor") == state.get("manifest_count")
        and len(queue) == state.get("manifest_count")
        and set(state.get("outcomes", {})) == {item["url"] for item in queue}
        and len(state.get("events", [])) == sum(v == "accepted" for v in state.get("outcomes", {}).values())
        and set(state.get("series_counts", {})) == series
        and all(len(state.get("series_urls", {}).get(series, [])) == count
                for series, count in state.get("series_counts", {}).items())
        and all(p["offset"] == p["total"] == len(p["urls"]) == len(p["ids"])
                for p in state.get("api_progress", {}).values()))


def _checkpoint(value, key, now):
    try:
        if not isinstance(value, dict) or set(value) != STATE_KEYS:
            raise ValueError
        if value["payload_hash"] != _digest({k: v for k, v in value.items() if k != "payload_hash"}):
            raise ValueError
        anchor = _real_time(value["started_at"])
        queue = value["queue"]
        if (type(value["version"]) is not int or value["version"] != 1 or value["source_key"] != key
                or value["completion_profile"] != "social_v1" or value["phase"] != "details"
                or value["listing_complete"] is not True or not -60 <= (now-anchor).total_seconds() <= 14400
                or value["window_start"] != anchor.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or not isinstance(queue, list) or len(queue) > CHECKPOINT_MANIFEST_LIMITS[key]
                or value["manifest_count"] != len(queue) or type(value["manifest_count"]) is not int
                or value["manifest_hash"] != _digest(queue) or type(value["cursor"]) is not int
                or not 0 <= value["cursor"] <= len(queue) or len(value["diagnostics"]) > 400
                or not isinstance(value["events"], list) or len(value["events"]) > CHECKPOINT_EVENT_LIMITS[key]
                or len({item["url"] for item in queue}) != len(queue)
                or any(not event_url(key, item["url"]) or item["kind"] not in ("native", "wix_occurrence")
                       or (key != BREWING and item["kind"] != "native") for item in queue)):
            raise ValueError
        for item in queue:
            _real_time(item["start"])
        if (not isinstance(value["outcomes"], dict)
                or set(value["outcomes"]) != {item["url"] for item in queue[:value["cursor"]]}
                or any(v not in HOLD_CODES | {"accepted"} for v in value["outcomes"].values())
                or not isinstance(value["series_counts"], dict) or not isinstance(value["series_urls"], dict)
                or not isinstance(value["api_progress"], dict) or not isinstance(value["excluded_urls"], list)
                or any(not event_url(key, url) for url in value["excluded_urls"])):
            raise ValueError
        required_series = {item["series_id"] for item in queue if "series_id" in item}
        if (not set(value["series_counts"]) <= required_series or set(value["series_urls"]) != required_series
                or not set(value["api_progress"]) <= set(value["series_counts"])):
            raise ValueError
        for series, urls in value["series_urls"].items():
            count = value["series_counts"].get(series, 100)
            if (not UUID.fullmatch(series) or type(count) is not int or not 1 <= count <= 100
                    or not isinstance(urls, list) or len(urls) != len(set(urls)) or len(urls) > count
                    or any(not event_url(BREWING, url) for url in urls)):
                raise ValueError
        for series, progress in value["api_progress"].items():
            if (set(progress) != {"seed_id", "offset", "total", "urls", "ids"}
                    or not UUID.fullmatch(progress["seed_id"])
                    or type(progress["offset"]) is not int or type(progress["total"]) is not int
                    or progress["total"] != value["series_counts"][series]
                    or not 0 <= progress["offset"] <= progress["total"]
                    or progress["offset"] != len(progress["urls"]) or progress["offset"] != len(progress["ids"])
                    or len(set(progress["urls"])) != progress["offset"] or len(set(progress["ids"])) != progress["offset"]
                    or not set(progress["urls"]) <= set(value["series_urls"][series])
                    or any(not UUID.fullmatch(identity) for identity in progress["ids"])):
                raise ValueError
        for row in value["events"]:
            if (not event_url(key, row.get("event_url")) or not isinstance(row.get("description"), str)
                    or not 0 < len(row["description"]) <= 12000):
                raise ValueError
        if len({row["id"] for row in value["events"]}) != len(value["events"]):
            raise ValueError
        if ({row["event_url"] for row in value["events"]}
                != {url for url, result in value["outcomes"].items() if result == "accepted"}):
            raise ValueError
        return deepcopy(value), anchor
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        raise ValueError("raleigh_next_social_checkpoint_invalid") from None


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_fetches=MAX_FETCHES, read_public_events=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or type(max_fetches) is not int or not 1 <= max_fetches <= MAX_FETCHES:
        raise ValueError("raleigh_next_social_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    fetched, public_instance = 0, None
    def reserve_fetch():
        nonlocal fetched
        if fetched >= max_fetches or (deadline_at is not None and monotonic() + 10 >= deadline_at):
            raise ValueError("collection_deadline")
        fetched += 1
    def read(url):
        reserve_fetch()
        return fetch(url, "text/html")
    if checkpoint is None:
        payload = read(SOURCES[key][0])
        diagnostics = []
        queue, listing_count = (_hotel_listing(payload, current, diagnostics) if key == LONGLEAF
                                else _brewing_listing(payload, current, diagnostics))
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
            window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(), completion_profile="social_v1",
            phase="details", listing_complete=True, queue=queue, cursor=0, manifest_count=0, manifest_hash="",
            events=[], diagnostics=diagnostics, series_counts={}, series_urls={}, excluded_urls=[],
            source_listing_count=listing_count, api_progress={}, outcomes={}, payload_hash="")
        for packet in queue:
            if key == BREWING:
                state["series_urls"].setdefault(packet["series_id"], []).append(packet["url"])
        anchor = current
    else:
        state, anchor = _checkpoint(checkpoint, key, current)
    previous_progress = _digest(state)
    while True:
        if state["cursor"] == len(state["queue"]):
            series = _pending_series(state)
            if series is None:
                break
            if key != BREWING or read_public_events is None:
                raise ValueError("raleigh_next_social_occurrences_incomplete")
            seed = next(item for item in state["queue"] if item.get("series_id") == series and item["kind"] == "native")
            try:
                if public_instance is None:
                    _, widget = _wix_state(read(seed["url"]), detail=True)
                    public_instance = widget["instance"].get("instance")
                if not valid_brewing_public_instance(public_instance):
                    raise ValueError("invalid_raleigh_brewing_request")
                progress = state["api_progress"].setdefault(series, dict(seed_id=seed["native_id"],
                    offset=0, total=state["series_counts"][series], urls=[], ids=[]))
                reserve_fetch()
                payload = read_public_events(event_id=progress["seed_id"], offset=progress["offset"],
                    public_instance=public_instance)
                _occurrence_page(state, series, payload, anchor)
            except ValueError as exc:
                if str(exc) == "collection_deadline":
                    break
                raise
            continue
        item = state["queue"][state["cursor"]]
        try:
            payload = read(item["url"])
            if key == BREWING:
                _, widget = _wix_state(payload, detail=True)
                public_instance = widget["instance"].get("instance")
            row = (_hotel_detail(item, payload) if key == LONGLEAF
                   else _brewing_detail(state, item, payload, anchor))
            if any(row["id"] == old["id"] for old in state["events"]):
                raise ValueError("raleigh_next_social_detail_changed")
            state["events"].append(row)
            state["outcomes"][item["url"]] = "accepted"
        except ValueError as exc:
            if str(exc) == "collection_deadline":
                break
            if str(exc) not in HOLD_CODES:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], reason=str(exc)))
            state["outcomes"][item["url"]] = str(exc)
        state["cursor"] += 1
        if len(state["queue"]) > 100 or len(state["events"]) > 200:
            raise ValueError("raleigh_next_social_record_limit")
    changed = _digest(state) != previous_progress
    _seal(state)
    complete = checkpoint_complete(state)
    if state["cursor"] == len(state["queue"]) and not complete and _pending_series(state) is None:
        raise ValueError("raleigh_next_social_occurrences_incomplete")
    if not complete and checkpoint is not None and not changed:
        raise ValueError("collection_deadline")
    _checkpoint(state, key, current)
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda r: (r["starts_at"], r["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None, read_public_events=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now, read_public_events=read_public_events)
    if not result["complete"]:
        raise ValueError("publisher_checkpoint_required")
    return result["events"]
