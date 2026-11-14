"""Cardboard Arena's public Carde calendar and full native event narratives.

The publisher lists each occurrence separately. Do not expand its recurrence
metadata. A narrowly scoped worker renderer supplies the public Generic Events
routing header for the one establishment calendar endpoint; ordinary public
HTML details supply complete native event objects and descriptions. All I/O is
provided by the worker's existing guarded transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_community import _full_description, _nj_address
from roomquest.mapsee_adapter import plain, record, timestamp


KEY = "cardboard_arena_nj"
ZONE = "America/New_York"
OWNER = "0571b1bc-5f97-40ac-bd29-b73170f3df8b"
PUBLIC_GAME = "2f532764-e06a-494b-9ca1-3e5dfea425ec"
FEED_URL = "https://play.carde.io/stores/" + OWNER
PUBLIC_CALENDAR_PATH = "/api/play/establishments/" + OWNER + "/events"
SOURCES = {KEY: (FEED_URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("play.carde.io", "api.carde.io")}
CHECKPOINT_KEYS = frozenset({KEY})
MAX_MANIFEST = 100
MAX_DESCRIPTION = 12_000
MAX_CHECKPOINT_BYTES = 900_000
MAX_CHECKPOINT_AGE = timedelta(hours=4)
MAX_DETAILS_PER_CHUNK = 2
MIN_DETAIL_SECONDS = 8
UUID = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
STREET = "15 8th Street, Hammonton, NJ 08037"
SCHEMA_VERSION = 1


def event_url(source_key, value):
    if source_key != KEY or not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and parsed.netloc == "play.carde.io"
            and not parsed.query and not parsed.fragment
            and re.fullmatch(r"/events/" + UUID, parsed.path) is not None)


def _source(source):
    if ((source.get("source_key"), source.get("feed_url"), source.get("kind"),
         source.get("platform_adapter"), source.get("timezone")) !=
            (KEY, *SOURCES[KEY], ZONE)):
        raise ValueError("unregistered_cardboard_arena_source")


def _full_text(value):
    # This is normalized prose. A second HTML parse would remove meaningful
    # escaped literals such as <bring your deck> from the publisher's text.
    if not isinstance(value, str) or not value.strip():
        raise ValueError("cardboard_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("cardboard_description_limit")
    return value


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _flight_models(payload):
    """Decode inert Next Flight JSON literals; never evaluate publisher JS.

    Text frames use UTF-8 byte lengths, so long descriptions and literal
    newlines remain complete even when React moves them into a referenced
    frame. Non-data module/preload frames are irrelevant to event records.
    """
    if not isinstance(payload, str) or len(payload.encode()) > 3_000_000:
        raise ValueError("cardboard_calendar_shape_changed")
    soup = BeautifulSoup(payload, "html.parser")
    decoder = json.JSONDecoder()
    chunks = []
    for script in soup.find_all("script"):
        text = script.get_text()
        for match in re.finditer(r"self\.__next_f\.push\(", text):
            try:
                item, _ = decoder.raw_decode(text[match.end():])
            except (ValueError, TypeError):
                raise ValueError("cardboard_calendar_shape_changed") from None
            if (isinstance(item, list) and len(item) == 2 and item[0] == 1
                    and isinstance(item[1], str)):
                chunks.append(item[1])
    if not chunks:
        raise ValueError("cardboard_calendar_shape_changed")
    stream = "".join(chunks).encode("utf-8")
    records, cursor = {}, 0
    while cursor < len(stream):
        if stream[cursor:cursor + 1] in (b"\n", b"\r"):
            cursor += 1
            continue
        marker = re.match(rb"([a-f0-9]+):", stream[cursor:])
        if not marker or len(records) > 10_000:
            raise ValueError("cardboard_calendar_shape_changed")
        identity = marker[1].decode()
        cursor += marker.end()
        text_frame = re.match(rb"T([a-f0-9]+),", stream[cursor:])
        if text_frame:
            size = int(text_frame[1], 16)
            cursor += text_frame.end()
            if size > 3_000_000 or cursor + size > len(stream):
                raise ValueError("cardboard_calendar_shape_changed")
            try:
                value = stream[cursor:cursor + size].decode("utf-8", errors="strict")
            except UnicodeError:
                raise ValueError("cardboard_calendar_shape_changed") from None
            cursor += size
        else:
            end = stream.find(b"\n", cursor)
            end = len(stream) if end < 0 else end
            line = stream[cursor:end]
            cursor = end + 1
            if not line[:1] or line[:1] not in b'{["ntf-0123456789':
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                raise ValueError("cardboard_calendar_shape_changed") from None
        if identity in records and records[identity] != value:
            raise ValueError("cardboard_calendar_shape_changed")
        records[identity] = value
    return records


def _deref(value, records):
    seen = set()
    while isinstance(value, str) and re.fullmatch(r"\$[a-f0-9]+", value):
        identity = value[1:]
        if identity in seen or identity not in records or len(seen) > 32:
            raise ValueError("cardboard_calendar_shape_changed")
        seen.add(identity)
        value = records[identity]
    if value == "$undefined":
        return None
    return value[1:] if isinstance(value, str) and value.startswith("$$") else value


def _store_context(payload):
    models = _flight_models(payload)
    objects = list(_walk(models))
    routes = {obj["storeId"] for obj in objects if isinstance(obj.get("storeId"), str)}
    games = [obj for obj in objects if obj.get("id") == PUBLIC_GAME]
    if (routes != {OWNER} or not games or any(obj.get("slug") != "play"
            or obj.get("name") != "Generic Events" or obj.get("isLive") is not True for obj in games)):
        raise ValueError("cardboard_public_calendar_identity_changed")


def _time(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value)):
        raise ValueError("cardboard_schedule_changed")
    result = timestamp(value)
    if result is None:
        raise ValueError("cardboard_schedule_changed")
    return result


def _within(item, now):
    return _time(item["startsAt"]) < now + timedelta(days=60) and _time(item["endsAt"]) > now


def _metadata(item, records=None):
    records = records or {}
    configuration = _deref(item.get("configuration"), records)
    address = _deref(item.get("address"), records)
    owner = _deref(item.get("owner"), records)
    activities = _deref(item.get("activities"), records)
    if (not isinstance(configuration, dict) or configuration.get("timezone") != ZONE
            or configuration.get("playSetting") != "inPerson"
            or not isinstance(owner, dict) or owner.get("id") != OWNER or owner.get("name") != "Cardboard Arena"
            or not isinstance(activities, list) or not 1 <= len(activities) <= 40):
        raise ValueError("cardboard_public_calendar_identity_changed")
    start, end = _time(_deref(item.get("startsAt"), records)), _time(_deref(item.get("endsAt"), records))
    if end <= start or end - start > timedelta(days=1):
        raise ValueError("cardboard_schedule_changed")
    name = plain(_deref(item.get("name"), records))
    if not name or len(name) > 180:
        raise ValueError("cardboard_event_identity_changed")
    selected = []
    for activity in activities:
        activity = _deref(activity, records)
        if (not isinstance(activity, dict) or not re.fullmatch(UUID, str(activity.get("id", "")))
                or not isinstance(activity.get("status"), str) or not plain(activity.get("name"))):
            raise ValueError("cardboard_event_identity_changed")
        selected.append({k: _deref(activity.get(k), records) for k in ("id", "name", "status", "startsAt")})
    selected_address = None
    if isinstance(address, dict):
        selected_address = {k: _deref(address.get(k), records)
                            for k in ("name", "address1", "address2", "address3", "city", "state", "zip", "country", "geo")}
        geo = selected_address.get("geo")
        if isinstance(geo, dict):
            selected_address["geo"] = {k: _deref(geo.get(k), records) for k in ("lat", "lng")}
    return {"id": item["id"], "name": name, "startsAt": start.isoformat(), "endsAt": end.isoformat(),
            "ownerId": item["ownerId"], "ownerType": item["ownerType"], "public": item["public"],
            "status": item["status"], "configuration": {"timezone": ZONE, "playSetting": "inPerson"},
            "address": selected_address,
            "activities": selected, "event_url": "https://play.carde.io/events/" + item["id"]}


def _manifest(payload, now):
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except ValueError:
        raise ValueError("cardboard_calendar_shape_changed") from None
    if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not isinstance(data.get("pagination"), dict):
        raise ValueError("cardboard_calendar_shape_changed")
    pagination = data["pagination"]
    if any(type(pagination.get(key)) is not int for key in ("activePage", "totalPages", "resultsThisPage", "totalResults")):
        raise ValueError("cardboard_calendar_shape_changed")
    if (len(data["data"]) > MAX_MANIFEST or pagination.get("nextPage") is not None
            or pagination.get("totalPages") not in (0, 1)):
        raise ValueError("source_record_limit")
    if (pagination.get("activePage") != 1 or pagination.get("resultsThisPage") != len(data["data"])
            or pagination.get("totalResults") != len(data["data"])):
        raise ValueError("cardboard_manifest_incomplete")
    result, identities = [], set()
    for item in data["data"]:
        if (not isinstance(item, dict) or not re.fullmatch(UUID, str(item.get("id", "")))
                or item.get("ownerId") != OWNER or item.get("ownerType") != "Establishment"
                or type(item.get("public")) is not bool or not isinstance(item.get("status"), str)
                or item["id"] in identities):
            raise ValueError("cardboard_event_identity_changed")
        identities.add(item["id"])
        if item["public"] is not True or item["status"] != "published":
            continue
        selected = _metadata(item)
        # Metadata stores canonical UTC strings; _within expects the native Z
        # form, which is preserved on the public item for this window check.
        if _within(item, now):
            result.append(selected)
    return sorted(result, key=lambda item: (item["startsAt"], item["id"]))


def _location(item):
    address = item.get("address")
    if not isinstance(address, dict) or address.get("country") != "US" or address.get("state") != "NJ":
        return None
    street = re.sub(r"^(\d+),\s*", r"\1 ", plain(address.get("address1")))
    extra = " ".join(plain(address.get(key)) for key in ("address2", "address3") if plain(address.get(key)))
    if extra:
        street += " " + extra
    city, postal = plain(address.get("city")), plain(address.get("zip"))
    home = (re.fullmatch(r"15 8th St(?:reet)?\.?", street, re.I) is not None
            and city == "Hammonton" and postal in ("", "08037"))
    if home:
        full, city, venue = STREET, "Hammonton", "Cardboard Arena"
    else:
        parsed = _nj_address(f"{street}, {city}, NJ {postal}")
        if not parsed or not re.search(r", NJ \d{5}(?:-\d{4})?$", parsed[0]):
            return None
        full, city = parsed
        venue = plain(address.get("name")) or street
    lat, lng = None, None
    geo = address.get("geo")
    if home and isinstance(geo, dict):
        try:
            a, b = float(geo.get("lat")), float(geo.get("lng"))
            if math.isfinite(a) and math.isfinite(b) and 39.60 <= a <= 39.63 and -74.79 <= b <= -74.76:
                lat, lng = a, b
        except (ValueError, TypeError):
            pass
    return venue, full, city, lat, lng


def _detail(item, payload):
    models = _flight_models(payload)
    candidates = []
    for obj in _walk(models):
        if obj.get("id") != item["id"] or "activities" not in obj or "ownerId" not in obj:
            continue
        if (obj.get("ownerId") != OWNER or obj.get("ownerType") != "Establishment"
                or obj.get("public") is not True or obj.get("status") != "published"):
            raise ValueError("cardboard_detail_changed")
        if _metadata(obj, models) != item:
            raise ValueError("cardboard_detail_changed")
        activities = _deref(obj.get("activities"), models)
        prose = []
        parent_html = _deref(obj.get("descriptionHtml"), models)
        if parent_html:
            prose.append(_full_description(parent_html))
        for activity in activities:
            activity = _deref(activity, models)
            if activity.get("status") != "published":
                return None, "publisher_record_not_eligible"
            html = _deref(activity.get("descriptionHtml"), models)
            body = _full_description(html)
            if not body:
                return None, "description_unavailable"
            prose.append(body if len(activities) == 1 else plain(activity.get("name")) + "\n" + body)
        candidates.append(_full_text("\n\n".join(prose)))
    if not candidates or len(set(candidates)) != 1:
        raise ValueError("cardboard_detail_changed")
    location = _location(item)
    if not location:
        return None, "venue_street_unresolved"
    venue, address, city, lat, lng = location
    # Numbered street names (8th Street) are complete structured streets. The
    # reviewed native point is checked above before bypassing record's legacy
    # alphabetic street-name heuristic; no default location is assigned.
    row = record(item["name"], item["startsAt"], item["endsAt"], venue, address, city,
                 item["event_url"], "cardboard-arena:" + item["id"], "Gaming and hobbies",
                 lat=lat, lng=lng, tz=ZONE, publisher_geo=lat is not None, retain_until_end=True)
    if row is None:
        return None, "event_ended_during_collection"
    row.update(description=candidates[0], timezone=ZONE, attendance_mode="in_person",
               location_provenance="publisher_event_venue_coordinates" if lat is not None else "publisher_street_address")
    return row, None


def _digest(queue):
    return sha256(json.dumps({"schema": SCHEMA_VERSION, "events": queue}, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _checkpoint(value, now):
    if value is None:
        return None
    invalid = "cardboard_checkpoint_invalid"
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or value.get("source_key") != KEY or type(value.get("cursor")) is not int
            or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_MANIFEST
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or not isinstance(value.get("events"), list) or not isinstance(value.get("diagnostics"), list)
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES
            or value.get("manifest_hash") != _digest(value["queue"])):
        raise ValueError(invalid)
    try:
        started = datetime.fromisoformat(value["started_at"])
        if started.tzinfo is None or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError(invalid) from None
    if now < started or now - started > MAX_CHECKPOINT_AGE:
        return None
    urls = [item.get("event_url") for item in value["queue"] if isinstance(item, dict)]
    if (len(urls) != value["manifest_count"] or len(set(urls)) != len(urls)
            or any(not event_url(KEY, url) for url in urls)):
        raise ValueError(invalid)
    for item in value["queue"]:
        try:
            valid = (re.fullmatch(UUID, str(item.get("id", ""))) is not None
                     and item["event_url"] == "https://play.carde.io/events/" + item["id"]
                     and item.get("ownerId") == OWNER and item.get("ownerType") == "Establishment"
                     and item.get("public") is True and item.get("status") == "published"
                     and item.get("configuration") == {"timezone": ZONE, "playSetting": "inPerson"}
                     and isinstance(item.get("name"), str) and 0 < len(item["name"]) <= 180
                     and timestamp(item.get("startsAt")) is not None
                     and timestamp(item.get("endsAt")) > timestamp(item["startsAt"])
                     and isinstance(item.get("activities"), list) and 1 <= len(item["activities"]) <= 40)
        except (ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            raise ValueError(invalid)
    prefix = {item["event_url"]: item for item in value["queue"][:value["cursor"]]}
    accepted, held = set(), set()
    for row in value["events"]:
        if not isinstance(row, dict) or row.get("event_url") not in prefix or row["event_url"] in accepted:
            raise ValueError(invalid)
        item = prefix[row["event_url"]]
        location = _location(item)
        if (row.get("id") != "cardboard-arena:" + item["id"] or not location
                or row.get("title") != item["name"] or row.get("venue_name") != location[0]
                or row.get("venue_address") != location[1]
                or row.get("lat") != location[3] or row.get("lng") != location[4]
                or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                or row.get("location_provenance") != ("publisher_event_venue_coordinates" if location[3] is not None else "publisher_street_address")
                or timestamp(row.get("starts_at")) != timestamp(item["startsAt"])
                or timestamp(row.get("ends_at")) != timestamp(item["endsAt"])
                or not isinstance(row.get("description"), str) or not row["description"].strip()
                or len(row["description"]) > MAX_DESCRIPTION):
            raise ValueError(invalid)
        accepted.add(row["event_url"])
    for row in value["diagnostics"]:
        if (not isinstance(row, dict) or row.get("event_url") not in prefix
                or row["event_url"] in accepted | held or row.get("disposition") != "held"
                or row.get("reason") not in {"description_unavailable", "venue_street_unresolved",
                                            "publisher_record_not_eligible", "event_ended_during_collection"}):
            raise ValueError(invalid)
        held.add(row["event_url"])
    if accepted | held != set(prefix):
        raise ValueError(invalid)
    return deepcopy(value)


def collect_chunk(source, fetch, *, render_calendar=None, checkpoint=None, deadline_at=None,
                  now=None, max_details=MAX_DETAILS_PER_CHUNK):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("cardboard_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, current)
    anchor = datetime.fromisoformat(state["started_at"]) if state else current
    if render_calendar is None:
        raise ValueError("cardboard_public_renderer_required")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    _store_context(fetch(FEED_URL, "text/html"))
    lower = (anchor - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    upper = (anchor + timedelta(days=60)).replace(microsecond=0)
    payload = render_calendar(starts_at=lower.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              ends_at=upper.strftime("%Y-%m-%dT%H:%M:%SZ"))
    queue = _manifest(payload, anchor)
    digest = _digest(queue)
    if state is None or state["manifest_hash"] != digest:
        state = {"version": 1, "source_key": KEY, "started_at": anchor.isoformat(),
                 "window_start": anchor.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 "manifest_hash": digest, "manifest_count": len(queue), "cursor": 0,
                 "queue": queue, "events": [], "diagnostics": []}
    previous = state["cursor"]
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state["cursor"] < len(queue) and state["cursor"] - previous < limit:
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        item = queue[state["cursor"]]
        row, reason = _detail(item, fetch(item["event_url"], "text/html"))
        if row is not None:
            state["events"].append(row)
        else:
            state["diagnostics"].append({"event_url": item["event_url"], "disposition": "held", "reason": reason})
        state["cursor"] += 1
    if state["cursor"] == previous < len(queue):
        raise ValueError("collection_deadline")
    complete = state["cursor"] == state["manifest_count"]
    if complete:
        still_upcoming = []
        for row in state["events"]:
            if timestamp(row["ends_at"]) <= current:
                state["diagnostics"].append({"event_url": row["event_url"], "disposition": "held",
                                             "reason": "event_ended_during_collection"})
            else:
                still_upcoming.append(row)
        state["events"] = still_upcoming
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("cardboard_checkpoint_size_limit")
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    return {"complete": complete, "events": deepcopy(rows), "checkpoint": state}


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source)
    raise ValueError("publisher_checkpoint_required")
