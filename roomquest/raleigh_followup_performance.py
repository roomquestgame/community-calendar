"""Complete anonymous publisher calendars for ComedyWorx and Chapel of Bones.

The caller supplies the existing guarded GET transport and two exact public
calendar read transports. Public Wix instance tokens stay in memory; they are
never part of a checkpoint. No weekly or monthly dates are inferred.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
COMEDYWORX = "comedyworx_raleigh_nc"
CHAPEL = "chapel_of_bones_raleigh_nc"
SOURCES = {
    COMEDYWORX: ("https://www.comedyworx.com/upcoming-shows", "html", "html"),
    CHAPEL: ("https://chapelofbones.com/events/", "html", "html"),
}
ALLOWED_HOSTS = {
    COMEDYWORX: ("www.comedyworx.com",),
    CHAPEL: ("chapelofbones.com", "www.tickpick.com"),
}
LABELS = {COMEDYWORX: "ComedyWorx", CHAPEL: "Chapel of Bones"}
CHECKPOINT_KEYS = set(SOURCES)
MAX_RECORDS = 200
MAX_MANIFEST = 200
CHECKPOINT_MANIFEST_LIMITS = {key: MAX_MANIFEST for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: MAX_RECORDS for key in SOURCES}
MAX_BYTES = 850_000
MAX_PAGES = 20
MAX_FETCHES = 10
MIN_SECONDS = 10
WIX_APP_ID = "140603ad-af8d-84a5-2c80-a0f60cb47351"
WIX_INSTANCE_ID = "d286c3b9-0c70-4d0c-b176-aaeb56257c1e"
WIX_METASITE_ID = "b88bddea-924c-450a-89c8-06f6d12c1a5a"
WIX_COMPONENT_ID = "comp-l37lv4zi"
WIX_PAGE_SIZE = 18
WIX_API = "https://www.comedyworx.com/_api/wix-one-events-server/web/paginated-events/viewer"
CHAPEL_API = "https://www.tickpick.com/organizer/api/"
CHAPEL_ORGANIZER = "https://www.tickpick.com/organizer/o/chapel-of-bones"
HOLD_CODES = {
    "raleigh_followup_description_missing", "raleigh_followup_description_limit",
    "raleigh_followup_schedule_unresolved", "raleigh_followup_venue_unresolved",
    "raleigh_followup_outside_window", "raleigh_followup_nonpublic",
}
ERROR_CODES = HOLD_CODES | {
    "unregistered_raleigh_followup_source", "raleigh_followup_calendar_changed",
    "raleigh_followup_detail_changed", "raleigh_followup_record_limit",
    "raleigh_followup_checkpoint_invalid", "raleigh_followup_checkpoint_size_limit",
    "raleigh_followup_checkpoint_required", "raleigh_followup_api_transport_required",
    "invalid_chapel_calendar_request", "invalid_comedyworx_calendar_request",
    "collection_deadline",
}
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|private\s+(?:event|party))\b", re.I)
STATE_KEYS = {
    "version", "source_key", "started_at", "window_start", "phase", "listing_complete",
    "queue", "cursor", "manifest_count", "manifest_hash", "listing_pages", "listing_total",
    "listing_raw_count", "listing_seen", "listing_last_start", "initial_manifest_hash",
    "outside_window_count", "nonpublic_count", "events", "diagnostics", "payload_hash",
}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                             source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_raleigh_followup_source")
    return key


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1500 or re.search(r"[\s\\<>\x00-\x1f]", value):
        return None
    try:
        p = urlsplit(value)
        decoded = unquote(p.path)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or p.fragment
                or ".." in decoded.split("/") or re.search(r"[\\\x00-\x1f]", decoded)):
            return None
        return p
    except ValueError:
        return None


def event_url(key, value):
    p = _safe_url(value)
    if not p or p.query:
        return False
    if key == COMEDYWORX:
        return p.netloc == "www.comedyworx.com" and bool(re.fullmatch(r"/event-details/[a-z0-9-]+", p.path))
    return key == CHAPEL and p.netloc == "www.tickpick.com" and bool(re.fullmatch(r"/organizer/event/[a-z0-9-]+-\d+", p.path))


def photo_url(key, value):
    p = _safe_url(value)
    if not p:
        return None
    valid = (key == COMEDYWORX and p.hostname == "static.wixstatic.com" and p.path.startswith("/media/")
             or key == CHAPEL and p.hostname == "static-o.tickpick.com" and p.path.startswith("/cdn-cgi/image/"))
    return value if valid else None


def chapel_calendar_request(*, page=1, bootstrap=False):
    """The publisher widget's anonymous JSON POST; never a purchase operation."""
    if type(page) is not int or not 1 <= page <= MAX_PAGES or type(bootstrap) is not bool or bootstrap and page != 1:
        raise ValueError("invalid_chapel_calendar_request")
    body = dict(param="chapel-of-bones", page=page,
                filters={key: {"values": []} for key in ("category", "city", "price", "when")},
                location="All locations", name_filter=None, tour_type_filter="All Types", selected_performer="")
    if bootstrap:
        body["include_prices"] = True
    url = CHAPEL_API + ("get_organizer_page_bootstrap" if bootstrap else "get_organizer_events")
    return url, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def valid_chapel_calendar_request(url, body):
    try:
        if not isinstance(body, bytes) or len(body) > 1000:
            return False
        data = json.loads(body)
        bootstrap = url == CHAPEL_API + "get_organizer_page_bootstrap"
        return (url, body) == chapel_calendar_request(page=data["page"], bootstrap=bootstrap)
    except (ValueError, TypeError, KeyError):
        return False


def valid_comedyworx_public_instance(value):
    """Validate the public site's exact anonymous scope without logging the token."""
    try:
        if not isinstance(value, str) or len(value) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]+", value):
            return False
        encoded = value.split(".", 1)[1]
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return (data.get("instanceId") == WIX_INSTANCE_ID and data.get("appDefId") == WIX_APP_ID
                and data.get("metaSiteId") == WIX_METASITE_ID and data.get("demoMode") is False
                and not any(data.get(key) for key in ("uid", "permissions", "visitorId")))
    except (ValueError, TypeError, AttributeError):
        return False


def comedyworx_calendar_url(offset):
    if type(offset) is not int or not WIX_PAGE_SIZE <= offset < MAX_MANIFEST or offset % WIX_PAGE_SIZE:
        raise ValueError("invalid_comedyworx_calendar_request")
    return WIX_API + "?" + urlencode(dict(offset=offset, filter=1, byEventId="false", members="false",
        paidPlans="false", locale="en-US", recurringFilter=2, filterType=2, sortOrder=0,
        limit=WIX_PAGE_SIZE, fetchBadges="true", draft="false", compId=WIX_COMPONENT_ID))


def valid_comedyworx_calendar_request(url, public_instance):
    try:
        p = _safe_url(url)
        if not p or not valid_comedyworx_public_instance(public_instance):
            return False
        query = parse_qs(p.query, keep_blank_values=True)
        return url == comedyworx_calendar_url(int(query["offset"][0]))
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def _json(payload, reason="raleigh_followup_calendar_changed"):
    try:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise ValueError(reason) from None


def _wix_state(payload, *, detail=False):
    soup = BeautifulSoup(payload, "html.parser")
    nodes = soup.find_all("script", id="wix-warmup-data")
    try:
        if len(nodes) != 1:
            raise ValueError
        apps = json.loads(nodes[0].string or nodes[0].get_text())["appsWarmupData"][WIX_APP_ID]
        state = apps["EventsPageInitialState"] if detail else apps["widget" + WIX_COMPONENT_ID]
        if not isinstance(state, dict):
            raise ValueError
        return soup, state
    except (ValueError, TypeError, KeyError):
        raise ValueError("raleigh_followup_detail_changed" if detail else "raleigh_followup_calendar_changed") from None


def _packet(key, row):
    try:
        if key == COMEDYWORX:
            native_id, title = row["id"], plain(row["title"])
            if not isinstance(native_id, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", native_id):
                raise ValueError
            url = "https://www.comedyworx.com/event-details/" + row["slug"]
            config = row["scheduling"]["config"]
            if config.get("scheduleTbd") is not False or config.get("timeZoneId") != ZONE:
                raise ValueError
            start, end = config["startDate"], config.get("endDate")
        else:
            if type(row["id"]) is not int or not 0 < row["id"] < 10**12:
                raise ValueError
            native_id, title = str(row["id"]), plain(row["what"])
            url = "https://www.tickpick.com/organizer/event/" + row["identifier"]
            start, end = row["when"], row.get("end_when")
            if row.get("sells_time_slots") or row.get("is_season_ticket"):
                raise ValueError  # Such products need a distinct explicit occurrence contract.
        if not event_url(key, url) or not 1 <= len(title) <= 180:
            raise ValueError
        begins, ends = timestamp(start), timestamp(end)
        if not begins or begins.utcoffset() != timedelta(0) or ends and (ends.utcoffset() != timedelta(0) or ends < begins):
            raise ValueError
        return dict(native_id=native_id, url=url, title=title, native_start=start, native_end=end)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("raleigh_followup_calendar_changed") from None


def _packet_day(key, item):
    # TickPick's list serializes the venue wall clock with a literal Z. Only
    # detail JSON-LD supplies an actual UTC offset; this is discovery only.
    return (date.fromisoformat(item["native_start"][:10]) if key == CHAPEL else
            timestamp(item["native_start"]).astimezone(ZoneInfo(ZONE)).date())


def _append_page(state, key, rows, anchor, *, total, more):
    if not isinstance(rows, list) or type(more) is not bool or total is not None and (type(total) is not int or not 0 <= total <= MAX_MANIFEST):
        raise ValueError("raleigh_followup_calendar_changed")
    if state["listing_total"] is not None and total != state["listing_total"]:
        raise ValueError("raleigh_followup_calendar_changed")
    if more and not rows:
        raise ValueError("raleigh_followup_calendar_changed")
    if key == COMEDYWORX and more and len(rows) != WIX_PAGE_SIZE:
        raise ValueError("raleigh_followup_calendar_changed")
    first = date.fromisoformat(state["window_start"])
    last = first + timedelta(days=60)
    for row in rows:
        item = _packet(key, row)
        if item["native_id"] in state["listing_seen"]:
            raise ValueError("raleigh_followup_calendar_changed")
        start = timestamp(item["native_start"])
        if state["listing_last_start"] and start < timestamp(state["listing_last_start"]):
            raise ValueError("raleigh_followup_calendar_changed")
        state["listing_seen"].append(item["native_id"])
        state["listing_last_start"] = item["native_start"]
        state["listing_raw_count"] += 1
        if not first <= _packet_day(key, item) < last:
            state["outside_window_count"] += 1
        elif NONPUBLIC.search(item["title"]) or key == CHAPEL and (row.get("is_deleted") is not False or row.get("is_published") is not True):
            state["nonpublic_count"] += 1
        else:
            state["queue"].append(item)
    state["listing_pages"] += 1
    state["listing_total"] = total
    if state["listing_raw_count"] > MAX_MANIFEST or state["listing_pages"] > MAX_PAGES:
        raise ValueError("raleigh_followup_record_limit")
    if total is not None and (state["listing_raw_count"] > total or more != (state["listing_raw_count"] < total)):
        raise ValueError("raleigh_followup_calendar_changed")
    if not more:
        state["listing_total"] = state["listing_raw_count"] if total is None else total
        state.update(phase="details", listing_complete=True)


def _body(value, title=""):
    if value is not None and not isinstance(value, str):
        raise ValueError("raleigh_followup_detail_changed")
    body = description(value, limit=12001)
    if len(body) > 12000:
        raise ValueError("raleigh_followup_description_limit")
    if not re.search(r"[A-Za-z]{2}", body) or plain(body) == plain(title):
        raise ValueError("raleigh_followup_description_missing")
    return body


def _schema(soup):
    events = []
    try:
        for node in soup.find_all("script", type="application/ld+json"):
            data = json.loads(node.string or node.get_text())
            values = data if isinstance(data, list) else data.get("@graph", [data])
            events.extend(item for item in values if isinstance(item, dict) and item.get("@type") == "Event")
        if len(events) != 1:
            raise ValueError
        return events[0]
    except (ValueError, TypeError, AttributeError):
        raise ValueError("raleigh_followup_detail_changed") from None


def _real_time(value):
    try:
        if not isinstance(value, str) or not re.search(r"T\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)$", value):
            raise ValueError
        result = timestamp(value)
        local = result.astimezone(ZoneInfo(ZONE))
        # A schema offset is explicit, but must also be the actual venue zone.
        if result.utcoffset() != local.utcoffset():
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise ValueError("raleigh_followup_schedule_unresolved") from None


def _show_clock(start, body):
    """Use a single explicit show clock when the schema is explicitly doors."""
    clock = r"(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?m\.?"
    def clocks(label):
        values = []
        for reverse, pattern in enumerate((rf"\b(?:{label})\s*(?:open\s*)?(?:at\s*)?[:@]?\s*{clock}\b",
                                           rf"\b{clock}\s*(?:{label})\b")):
            for match in re.finditer(pattern, body, re.I):
                # In "Doors 9 PM Show: 10 PM", the preceding 9 PM belongs to
                # Doors. Only accept a postfix label without its own next clock.
                if reverse and re.match(rf"\s*[:@]?\s*{clock}\b", body[match.end():], re.I):
                    continue
                hour, minute, meridiem = match.groups()
                values.append((int(hour) % 12 + (12 if meridiem.lower() == "p" else 0), int(minute or 0)))
        return set(values)
    doors = clocks("doors?")
    shows = clocks("showtime|show|music|event")
    if not doors or not shows:
        return start
    local = start.astimezone(ZoneInfo(ZONE))
    if len(doors) != 1 or len(shows) != 1:
        raise ValueError("raleigh_followup_schedule_unresolved")
    show = next(iter(shows))
    if (local.hour, local.minute) == show:
        return start
    if (local.hour, local.minute) not in doors:
        raise ValueError("raleigh_followup_schedule_unresolved")
    proposed = timestamp(f"{local.date().isoformat()}T{show[0]:02}:{show[1]:02}:00", ZONE)
    if not start < proposed <= start + timedelta(hours=4):
        raise ValueError("raleigh_followup_schedule_unresolved")
    return proposed


def _venue(key, location):
    try:
        if not isinstance(location, dict) or plain(location.get("name")) != LABELS[key]:
            raise ValueError
        if key == CHAPEL:
            address = location["address"]
            if (not isinstance(address, dict) or address.get("addressLocality") != "Raleigh"
                    or address.get("addressRegion") != "NC" or address.get("postalCode") != "27603"
                    or address.get("addressCountry") != "US"
                    or not re.fullmatch(r"658 Maywood (?:Ave\.?|Avenue)", plain(address.get("streetAddress")), re.I)):
                raise ValueError
            return LABELS[key], f'{plain(address["streetAddress"])}, Raleigh, NC 27603', "Raleigh", None, None
        address = plain(location["address"])
        full = location["fullAddress"]
        if (location.get("tbd") is not False or full.get("city") != "Raleigh" or full.get("subdivision") != "NC"
                or full.get("country") != "US" or not re.fullmatch(r"27607(?:-\d{4})?", full.get("postalCode", ""))
                or full.get("formattedAddress") != location["address"]
                or not re.match(r"^3801 Hillsborough (?:St\b|Street\b)", address, re.I)):
            raise ValueError
        match = re.fullmatch(
            r"(?P<street>3801 Hillsborough (?:St\.?|Street)(?: (?:Suite|Ste\.?|#)\s*\d+[A-Za-z]?)?),\s*"
            r"Raleigh,\s*NC\s+(?P<zip>27607(?:-\d{4})?)(?:,\s*USA)?"
            r"(?:\s+(?P<suite>(?:Suite|Ste\.?|#)\s*\d+[A-Za-z]?))?", address, re.I)
        components = full.get("streetAddress") or {}
        if (not match or components.get("number") != "3801"
                or not re.fullmatch(r"Hillsborough (?:St\.?|Street)", components.get("name", ""), re.I)
                or len(match["zip"]) > 5 and match["zip"] != full["postalCode"]):
            raise ValueError
        # The public formatted address sometimes places "Ste. 123" after USA.
        # Move that exact supplied suite into the street, omit the country, and
        # retain the same event's native full postal code. No unit is inferred.
        street = match["street"] + (" " + match["suite"] if match["suite"] else "")
        if components.get("apt"):
            unit = re.sub(r"^(?:Suite|Ste\.?|Apt\.?|#)\s*", "", plain(components["apt"]), flags=re.I)
            if not re.search(r"\b(?:Suite|Ste\.?|#)\s*" + re.escape(unit) + r"\b", street, re.I):
                raise ValueError
        canonical_address = f"{street}, Raleigh, NC {full['postalCode']}"
        lat, lng = location["coordinates"]["lat"], location["coordinates"]["lng"]
        geo = full["geocode"]
        if (type(lat) not in (int, float) or type(lng) not in (int, float) or not math.isfinite(lat) or not math.isfinite(lng)
                or not 33.8 <= lat <= 36.7 or not -84.4 <= lng <= -75.3
                or abs(lat - geo["latitude"]) > 1e-8 or abs(lng - geo["longitude"]) > 1e-8):
            raise ValueError
        return LABELS[key], canonical_address, "Raleigh", lat, lng
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("raleigh_followup_venue_unresolved") from None


def _row(key, item, start, end, body, venue, image, anchor):
    window_start = calendar_anchor(anchor)
    if not start or end and (end <= start or end > start + timedelta(hours=36)):
        raise ValueError("raleigh_followup_schedule_unresolved")
    first = window_start.astimezone(ZoneInfo(ZONE)).date()
    if not first <= start.astimezone(ZoneInfo(ZONE)).date() < first + timedelta(days=60) or (end or start + timedelta(hours=3)) <= window_start:
        raise ValueError("raleigh_followup_outside_window")
    identity = "raleigh:" + sha256(f'{key}:{item["url"]}:{start.astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()
    name, street, city, lat, lng = venue
    result = record(item["title"], start.isoformat(), end.isoformat() if end else None, name, street, city,
                    item["url"], identity, lat=lat, lng=lng, tz=ZONE, publisher_geo=lat is not None, retain_until_end=True)
    if result is None:
        raise ValueError("raleigh_followup_outside_window")
    result.update(description=_body(body, item["title"]), timezone=ZONE, attendance_mode="in_person",
                  location_provenance="publisher_event_geo" if lat is not None else "publisher_event_address_pending_geocode",
                  location_evidence_url=item["url"])
    if photo := photo_url(key, image):
        result["image_url"] = photo
    return result


def _detail(key, item, payload, anchor):
    if key == COMEDYWORX:
        soup, state = _wix_state(payload, detail=True)
        try:
            native = state["event"]["event"]
            if _packet(key, native) != item or native.get("instanceId") != WIX_INSTANCE_ID:
                raise ValueError
            canonical = soup.find("link", rel="canonical")
            if not canonical or canonical.get("href") != item["url"]:
                raise ValueError
            schema = _schema(soup)
            if plain(schema.get("name")) != item["title"]:
                raise ValueError
            if (schema.get("eventStatus") != "https://schema.org/EventScheduled"
                    or schema.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
                    or (native.get("registration") or {}).get("restrictedTo") not in (None, 0)):
                raise ValueError("raleigh_followup_nonpublic")
            start, end = _real_time(schema.get("startDate")), _real_time(schema["endDate"]) if schema.get("endDate") else None
            # Wix's edit timestamps sometimes leave fractional seconds on the
            # end time, while its public schema and visible schedule use whole
            # seconds. Ignore only that fractional precision, never minutes.
            native_start, native_end = timestamp(item["native_start"]), timestamp(item["native_end"])
            if (start.replace(microsecond=0) != native_start.replace(microsecond=0)
                    or bool(end) != bool(native_end)
                    or end and end.replace(microsecond=0) != native_end.replace(microsecond=0)):
                raise ValueError("raleigh_followup_schedule_unresolved")
            nodes = soup.select('[data-hook="about-section"] [data-id="content-viewer"]')
            if len(nodes) != 1:
                raise ValueError("raleigh_followup_description_missing")
            body = _body(str(nodes[0]), item["title"])
            venue = _venue(key, native["location"])
            image = (native.get("mainImage") or {}).get("url")
        except (KeyError, TypeError, AttributeError):
            raise ValueError("raleigh_followup_detail_changed") from None
        except ValueError as exc:
            if str(exc) in HOLD_CODES:
                raise
            raise ValueError("raleigh_followup_detail_changed") from None
    else:
        soup = BeautifulSoup(payload, "html.parser")
        schema = _schema(soup)
        if (schema.get("url") != item["url"] or plain(schema.get("name")) != item["title"]
                or (schema.get("organizer") or {}).get("url") != CHAPEL_ORGANIZER
                or (schema.get("organizer") or {}).get("name") != LABELS[key]):
            raise ValueError("raleigh_followup_detail_changed")
        if (schema.get("eventStatus") != "https://schema.org/EventScheduled"
                or schema.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"):
            raise ValueError("raleigh_followup_nonpublic")
        start = _real_time(schema.get("startDate"))
        end = _real_time(schema["endDate"]) if schema.get("endDate") else None
        # Validate the schema against the native listing in wall-clock space.
        if start.replace(tzinfo=None) != timestamp(item["native_start"]).replace(tzinfo=None):
            raise ValueError("raleigh_followup_schedule_unresolved")
        if bool(end) != bool(item["native_end"]) or end and end.replace(tzinfo=None) != timestamp(item["native_end"]).replace(tzinfo=None):
            raise ValueError("raleigh_followup_schedule_unresolved")
        body = _body(schema.get("description"), item["title"])
        start = _show_clock(start, body)
        venue = _venue(key, schema.get("location"))
        images = schema.get("image") or []
        image = images[0] if isinstance(images, list) and images else images if isinstance(images, str) else None
    return _row(key, item, start, end, body, venue, image, anchor)


def _refresh_manifest(state):
    state["manifest_count"] = len(state["queue"])
    state["manifest_hash"] = _hash(state["queue"])
    if len(state["queue"]) > MAX_MANIFEST or len(state["events"]) > MAX_RECORDS:
        raise ValueError("raleigh_followup_record_limit")


def _seal(state):
    _refresh_manifest(state)
    state["payload_hash"] = _hash({key: value for key, value in state.items() if key != "payload_hash"})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("raleigh_followup_checkpoint_size_limit")
    return state


def checkpoint_complete(state):
    """Exact family proof used by the shared worker before staging."""
    try:
        return (all(type(state[field]) is int for field in ("listing_pages", "listing_raw_count", "listing_total",
                    "manifest_count", "outside_window_count", "nonpublic_count", "cursor"))
                and state["phase"] == "details" and state["listing_complete"] is True
                and type(state["listing_pages"]) is int and state["listing_pages"] >= 1
                and state["listing_raw_count"] == state["listing_total"]
                == state["manifest_count"] + state["outside_window_count"] + state["nonpublic_count"]
                and state["cursor"] == state["manifest_count"] == len(state["queue"])
                and len(state["events"]) + len(state["diagnostics"]) == state["cursor"])
    except (KeyError, TypeError):
        return False


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or set(value) != STATE_KEYS or value["payload_hash"] != _hash({k: v for k, v in value.items() if k != "payload_hash"}):
            raise ValueError
        started = timestamp(value["started_at"])
        if (type(value["version"]) is not int or value["version"] != 1 or value["source_key"] != key
                or not started or started.utcoffset() != timedelta(0) or started > now + timedelta(seconds=60)
                or value["window_start"] != calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date().isoformat()
                or value["phase"] not in {"listing", "details"} or type(value["listing_complete"]) is not bool
                or value["listing_complete"] != (value["phase"] == "details")
                or not isinstance(value["queue"], list) or len(value["queue"]) > MAX_MANIFEST
                or type(value["manifest_count"]) is not int or value["manifest_count"] != len(value["queue"])
                or value["manifest_hash"] != _hash(value["queue"])
                or type(value["cursor"]) is not int or not 0 <= value["cursor"] <= len(value["queue"])
                or value["phase"] == "listing" and (value["cursor"] or value["events"] or value["diagnostics"])
                or not isinstance(value["events"], list) or len(value["events"]) > MAX_RECORDS
                or not isinstance(value["diagnostics"], list) or len(value["diagnostics"]) > MAX_MANIFEST
                or type(value["listing_pages"]) is not int or not 0 <= value["listing_pages"] <= MAX_PAGES
                or type(value["listing_raw_count"]) is not int or not 0 <= value["listing_raw_count"] <= MAX_MANIFEST
                or not isinstance(value["listing_seen"], list) or len(value["listing_seen"]) != value["listing_raw_count"]
                or len(set(value["listing_seen"])) != len(value["listing_seen"])
                or value["listing_total"] is not None and (type(value["listing_total"]) is not int or not value["listing_raw_count"] <= value["listing_total"] <= MAX_MANIFEST)
                or value["listing_complete"] and value["listing_total"] != value["listing_raw_count"]
                or value["listing_complete"] and value["listing_pages"] < 1
                or any(type(value[field]) is not int or value[field] < 0 for field in ("outside_window_count", "nonpublic_count"))
                or len(value["queue"]) + value["outside_window_count"] + value["nonpublic_count"] != value["listing_raw_count"]
                or len(value["events"]) + len(value["diagnostics"]) != value["cursor"]):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        queue = {}
        for item in value["queue"]:
            if (set(item) != {"native_id", "url", "title", "native_start", "native_end"}
                    or not event_url(key, item["url"]) or not 1 <= len(item["title"]) <= 180
                    or item["native_id"] not in value["listing_seen"] or item["url"] in queue
                    or not timestamp(item["native_start"])):
                raise ValueError
            queue[item["url"]] = item
        processed = {item["url"] for item in value["queue"][:value["cursor"]]}
        seen = set()
        for row in value["events"]:
            expected = "raleigh:" + sha256(f'{key}:{row["event_url"]}:{timestamp(row["starts_at"]).astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()
            url = row["event_url"]
            if (url not in processed or url in seen or row["id"] != expected or row["title"] != queue[url]["title"]
                    or _body(row["description"], row["title"]) != row["description"]
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or row.get("venue_name") != LABELS[key] or row.get("venue_city") != "Raleigh"
                    or row.get("location_evidence_url") != url
                    or row.get("image_url") and photo_url(key, row["image_url"]) != row["image_url"]):
                raise ValueError
            if key == CHAPEL:
                if (row.get("lat") is not None or row.get("lng") is not None
                        or row.get("location_provenance") != "publisher_event_address_pending_geocode"
                        or not re.fullmatch(r"658 Maywood (?:Ave\.?|Avenue), Raleigh, NC 27603", row["venue_address"], re.I)):
                    raise ValueError
            elif (row.get("location_provenance") != "publisher_event_geo"
                    or type(row.get("lat")) not in (int, float) or type(row.get("lng")) not in (int, float)
                    or not 33.8 <= row["lat"] <= 36.7 or not -84.4 <= row["lng"] <= -75.3
                    or not re.match(r"^3801 Hillsborough (?:St\b|Street\b)", row["venue_address"], re.I)):
                raise ValueError
            seen.add(url)
        for diagnostic in value["diagnostics"]:
            url = diagnostic["event_url"]
            if (url not in processed or url in seen or diagnostic["title"] != queue[url]["title"]
                    or diagnostic["reason"] not in HOLD_CODES or diagnostic["disposition"] != "held"):
                raise ValueError
            seen.add(url)
        if seen != processed or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError("raleigh_followup_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, read_public_events=None, checkpoint=None, deadline_at=None, now=None, max_fetches=MAX_FETCHES):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("raleigh_followup_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    fetched = 0
    public_instance = None
    def budget():
        nonlocal fetched
        if fetched >= max_fetches or deadline_at is not None and monotonic() + MIN_SECONDS >= deadline_at:
            raise ValueError("collection_deadline")
        fetched += 1
    def read(url, accept):
        budget()
        return fetch(url, accept)
    def read_api(**kwargs):
        if read_public_events is None:
            raise ValueError("raleigh_followup_api_transport_required")
        budget()
        return read_public_events(**kwargs)
    def wix_frontend():
        payload = read(SOURCES[key][0], "text/html")
        _, widget = _wix_state(payload)
        try:
            token = widget["instance"]["instance"]
            settings = widget["component"]["settings"]
            if (not valid_comedyworx_public_instance(token) or widget["component"]["id"] != WIX_COMPONENT_ID
                    or settings.get("recurringFilter") != 2 or widget["events"]["filterType"] != 2
                    or len(widget["events"]["events"]) > WIX_PAGE_SIZE):
                raise ValueError
            return widget["events"], token
        except (ValueError, TypeError, KeyError):
            raise ValueError("raleigh_followup_calendar_changed") from None
    if state is None:
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
            window_start=calendar_anchor(current).astimezone(ZoneInfo(ZONE)).date().isoformat(), phase="listing", listing_complete=False,
            queue=[], cursor=0, manifest_count=0, manifest_hash=_hash([]), listing_pages=0, listing_total=None,
            listing_raw_count=0, listing_seen=[], listing_last_start=None, initial_manifest_hash=None,
            outside_window_count=0, nonpublic_count=0, events=[], diagnostics=[])
        if key == COMEDYWORX:
            native, public_instance = wix_frontend()
            state["initial_manifest_hash"] = _hash([_packet(key, row) for row in native["events"]])
            _append_page(state, key, native["events"], current, total=None, more=native["hasMore"])
        else:
            soup = BeautifulSoup(read(SOURCES[key][0], "text/html"), "html.parser")
            script = soup.find("script", src="https://www.tickpick.com/organizer/api/widgets/tickpick-events-widget.js")
            if not script or not re.search(r"companyId\s*:\s*['\"]chapel-of-bones['\"]", str(soup)):
                raise ValueError("raleigh_followup_calendar_changed")
    anchor = timestamp(state["started_at"])
    before = (state["phase"], state["listing_pages"], state["cursor"])
    while state["phase"] == "listing":
        if state["listing_pages"] >= MAX_PAGES:
            raise ValueError("raleigh_followup_record_limit")
        try:
            if key == COMEDYWORX:
                if public_instance is None:
                    initial, public_instance = wix_frontend()
                    if _hash([_packet(key, row) for row in initial["events"]]) != state["initial_manifest_hash"]:
                        raise ValueError("raleigh_followup_calendar_changed")
                data = _json(read_api(request_kind="comedyworx_page", offset=state["listing_raw_count"], public_instance=public_instance))
                rows, total, more = data["events"], data["total"], data["hasMore"]
                if len(rows) > WIX_PAGE_SIZE:
                    raise ValueError("raleigh_followup_calendar_changed")
            else:
                bootstrap = state["listing_pages"] == 0
                data = _json(read_api(request_kind="chapel_bootstrap" if bootstrap else "chapel_page", page=state["listing_pages"] + 1))
                if bootstrap and (data.get("performer") or {}).get("id") != "chapel-of-bones":
                    raise ValueError("raleigh_followup_calendar_changed")
                rows, total = data["events"], data["total_events"]
                more = state["listing_raw_count"] + len(rows) < total
            _append_page(state, key, rows, anchor, total=total, more=more)
        except ValueError as exc:
            if str(exc) == "collection_deadline":
                break
            raise
        except (KeyError, TypeError):
            raise ValueError("raleigh_followup_calendar_changed") from None
    while state["phase"] == "details" and state["cursor"] < len(state["queue"]):
        item = state["queue"][state["cursor"]]
        try:
            payload = read(item["url"], "text/html")
            row = _detail(key, item, payload, anchor)
            if any(existing["id"] == row["id"] for existing in state["events"]):
                raise ValueError("raleigh_followup_detail_changed")
            state["events"].append(row)
        except ValueError as exc:
            if str(exc) == "collection_deadline":
                break
            if str(exc) not in HOLD_CODES:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], title=item["title"], reason=str(exc), disposition="held"))
        state["cursor"] += 1
        _refresh_manifest(state)
    _refresh_manifest(state)
    complete = checkpoint_complete(state)
    if not complete and before == (state["phase"], state["listing_pages"], state["cursor"]) and checkpoint is not None:
        raise ValueError("collection_deadline")
    _seal(state)
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda row: (row["starts_at"], row["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, read_public_events=None, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, read_public_events=read_public_events, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("raleigh_followup_checkpoint_required")
    return result["events"]
