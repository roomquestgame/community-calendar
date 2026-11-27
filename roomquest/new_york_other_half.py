"""Other Half's reviewed NYC venues using ordinary native event HTML.

The nationwide archive is narrowed to one reviewed NYC location per event.
Detail headings, explicit calendar clocks, location links and complete content
builder bodies are checked together. Empty trivia bodies are held; brewery
opening hours, product releases and unrelated venue prose are never substitutes.
All network work is supplied by the existing guarded publisher transport.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.new_york_nightlife import NONPUBLIC, _within

ZONE = "America/New_York"
OTHER = "other_half_nyc_ny"
SOURCES = {OTHER: ("https://otherhalfbrewing.com/events/", "html", "html")}
ALLOWED_HOSTS = {OTHER: ("otherhalfbrewing.com",)}
CHECKPOINT_KEYS = {OTHER}
CHECKPOINT_MANIFEST_LIMITS = {OTHER: 200}
CHECKPOINT_EVENT_LIMITS = {OTHER: 200}
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900_000
MAX_DETAILS_PER_CHUNK = 2
MIN_DETAIL_SECONDS = 14
VENUES = {
    "Centre Street": ("Other Half Brewing – Centre Street", "195 Centre Street, Brooklyn, NY 11231", "Brooklyn"),
    "Domino Park": ("Other Half Brewing – Domino Park", "34 River Street, Brooklyn, NY 11249", "Brooklyn"),
}
LOCATION_URLS = {
    "Centre Street": "https://otherhalfbrewing.com/location/centre-street/",
    "Domino Park": "https://otherhalfbrewing.com/location/domino-park/",
}
# Publisher streets matched to NYC Planning Property Address Directory.
POINTS = {"Centre Street": (40.673887, -73.999079)}
HELD = {"new_york_other_half_description_missing", "new_york_other_half_description_limit",
        "new_york_other_half_venue_unresolved", "no_available_future_occurrence"}
ERROR_CODES = HELD | {
    "unregistered_new_york_other_half_source", "new_york_other_half_calendar_changed",
    "new_york_other_half_event_identity", "new_york_other_half_schedule_conflict",
    "new_york_other_half_detail_changed", "new_york_other_half_record_limit",
    "new_york_other_half_checkpoint_invalid", "new_york_other_half_checkpoint_size_limit",
    "new_york_other_half_checkpoint_required", "collection_deadline",
}


def _source(source):
    if (source.get("source_key") != OTHER or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[OTHER], ZONE)):
        raise ValueError("unregistered_new_york_other_half_source")


def event_url(key, value):
    if key != OTHER or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.netloc == "otherhalfbrewing.com" and not p.query and not p.fragment
                and bool(re.fullmatch(r"/event/[a-z0-9-]+-20\d{2}-\d{2}-\d{2}/", p.path)))
    except ValueError:
        return False


def photo_url(key, value):
    if key != OTHER or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        params = parse_qs(p.query, keep_blank_values=True)
        if (p.scheme == "https" and p.netloc == "cooler-images.arryved.com"
                and re.fullmatch(r"/other-half-brewing/[A-Za-z0-9_+.% -]+\.(?:png|jpe?g|webp)", p.path, re.I)
                and not p.fragment and not re.search(r"%2e|%2f|%5c", p.path, re.I)
                and set(params) <= {"width", "height", "aspect_ratio"}
                and all(len(values) == 1 and re.fullmatch(r"[1-9]\d{0,3}(?::[1-9]\d{0,3})?" if name == "aspect_ratio" else r"[1-9]\d{0,3}", values[0])
                        for name, values in params.items())):
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    if key == OTHER:
        return next((POINTS.get(name) for name, place in VENUES.items() if (venue, address) == place[:2]), None)
    return None


def _body(value):
    body = description(str(value or ""), limit=MAX_DESCRIPTION + 1)
    if not re.search(r"[A-Za-z]", re.sub(r"\bhttps?://\S+", "", body)):
        raise ValueError("new_york_other_half_description_missing")
    if len(body) > MAX_DESCRIPTION:
        raise ValueError("new_york_other_half_description_limit")
    return body


def _identity(url, start):
    return "nyc:" + sha256(f"{OTHER}:{url}:{timestamp(start).astimezone(timezone.utc).isoformat()}".encode()).hexdigest()


def _attach_content(row, body, native_venue, image=None):
    start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
    if start is None or start.tzinfo is None or end is None or end.tzinfo is None or end <= start:
        raise ValueError("new_york_other_half_schedule_conflict")
    facts = {
        "title": row["title"], "description": body, "is_all_day": False,
        "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
        "ends_at_utc": end.astimezone(timezone.utc).isoformat(),
        "source_timezone": ZONE, "event_url": row["event_url"],
        "venue_name": native_venue, "source_image_url": image,
        "attendance_mode": "in_person",
    }
    facts = {name: value for name, value in facts.items() if value not in (None, "")}
    row["collector_event_content_v1"] = {"version": 1, "event_id": row["id"], "facts": facts}
    return row


def _content_envelope_valid(row, item):
    evidence = row.get("collector_event_content_v1")
    if evidence is None:
        return True
    if (not isinstance(evidence, dict) or set(evidence) != {"version", "event_id", "facts"}
            or evidence.get("version") != 1 or evidence.get("event_id") != row.get("id")
            or not isinstance(evidence.get("facts"), dict)):
        return False
    facts = evidence["facts"]
    allowed = {"title", "description", "is_all_day", "starts_at_utc", "ends_at_utc",
               "source_timezone", "event_url", "venue_name", "source_image_url", "attendance_mode"}
    if not set(facts) <= allowed:
        return False
    try:
        start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
        expected = {"title": row.get("title"), "description": row.get("description"),
                    "is_all_day": False, "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
                    "ends_at_utc": end.astimezone(timezone.utc).isoformat(),
                    "source_timezone": ZONE, "event_url": row.get("event_url"),
                    "venue_name": item["location"], "attendance_mode": "in_person"}
    except (AttributeError, TypeError, ValueError, OverflowError, KeyError):
        return False
    return (facts.get("source_image_url") == row.get("image_url")
            and all(facts.get(name) == value for name, value in expected.items()))


def _manifest(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    cards = soup.select("a.excerpt-box.event[href]")
    if not cards and "Nothing coming up" not in soup.get_text(" ", strip=True):
        raise ValueError("new_york_other_half_calendar_changed")
    # Do not silently publish a first page if this archive starts paginating.
    if soup.select('a[rel="next"],.pagination') or any(re.search(r"/events/page/|[?&](?:paged|page)=", a["href"]) for a in soup.select('a[href]')):
        raise ValueError("new_york_other_half_calendar_changed")
    queue = []
    for card in cards:
        locations = [plain(node.get_text(" ")) for node in card.select(".excerpt-box-location")]
        if len(locations) != 1 or locations[0] not in VENUES:
            continue
        heading = card.select_one(".excerpt-box-title")
        day_label = card.select_one(".excerpt-box-date")
        title = plain(heading.get_text(" ")) if heading else ""
        if NONPUBLIC.search(title):
            continue
        url = card["href"]
        if not event_url(OTHER, url) or not 0 < len(title) <= 180 or day_label is None:
            raise ValueError("new_york_other_half_event_identity")
        day = date.fromisoformat(urlsplit(url).path.rstrip("/")[-10:])
        printed = plain(day_label.get_text(" ")).split("/", 1)[0].strip()
        if printed != f"{day:%b} {day.day}":
            # Multiple-day sales/releases are not dated attendance sessions.
            continue
        local_today = calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date()
        if day < local_today - timedelta(days=1) or day > local_today + timedelta(days=60):
            continue
        queue.append(dict(url=url, title=title, day=day.isoformat(), location=locations[0]))
    unique = {}
    for item in queue:
        if item["url"] in unique and unique[item["url"]] != item:
            raise ValueError("new_york_other_half_event_identity")
        unique[item["url"]] = item
    if len(unique) > MAX_RECORDS:
        raise ValueError("new_york_other_half_record_limit")
    return sorted(unique.values(), key=lambda item: (item["day"], item["url"]))


def _detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    main = soup.select_one("main")
    headings = main.select("h2.fl-heading") if main else []
    if (canonical is None or canonical.get("href") != item["url"] or len(headings) != 1
            or plain(headings[0].get_text(" ")) != item["title"]):
        raise ValueError("new_york_other_half_detail_changed")
    clocks = []
    for icon in main.select(".fa-calendar-alt"):
        block = icon.find_parent(class_="fl-module-icon")
        labels = block.select("span.ui-label[title]") if block else []
        if len(labels) != 1 or plain(labels[0].get_text(" ")) != plain(labels[0].get("title")):
            raise ValueError("new_york_other_half_schedule_conflict")
        clocks.append(plain(labels[0].get_text(" ")))
    if len(clocks) != 1:
        raise ValueError("new_york_other_half_schedule_conflict")
    match = re.fullmatch(r"([A-Za-z]+ \d{1,2} 20\d{2}) (\d{1,2}:\d{2} [ap]m)\s*[-–]\s*(\d{1,2}:\d{2} [ap]m)", clocks[0], re.I)
    if match is None:
        raise ValueError("new_york_other_half_schedule_conflict")
    try:
        day = datetime.strptime(match[1], "%B %d %Y").date()
        start = datetime.strptime(match[1] + " " + match[2].upper(), "%B %d %Y %I:%M %p").replace(tzinfo=ZoneInfo(ZONE))
        end = datetime.strptime(match[1] + " " + match[3].upper(), "%B %d %Y %I:%M %p").replace(tzinfo=ZoneInfo(ZONE))
    except ValueError:
        raise ValueError("new_york_other_half_schedule_conflict") from None
    if day.isoformat() != item["day"]:
        raise ValueError("new_york_other_half_schedule_conflict")
    if end <= start:
        end += timedelta(days=1)
    if end - start > timedelta(hours=18):
        raise ValueError("new_york_other_half_schedule_conflict")
    locations = main.select("a.event-info-location[href]")
    if (len(locations) != 1 or locations[0]["href"] != LOCATION_URLS[item["location"]]
            or plain(locations[0].get_text(" ")) != item["location"]):
        raise ValueError("new_york_other_half_venue_unresolved")
    bodies = main.select(".fl-module-cp-content-builder")
    if len(bodies) != 1:
        raise ValueError("new_york_other_half_detail_changed")
    body = _body(bodies[0])
    if not _within(start, end, now):
        return []
    place = VENUES[item["location"]]
    point = POINTS.get(item["location"])
    if point is None:
        raise ValueError("new_york_other_half_venue_unresolved")
    row = record(item["title"], start.isoformat(), end.isoformat(), *place, item["url"], _identity(item["url"], start),
                 lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode="in_person", lat=point[0], lng=point[1],
                   location_provenance="reviewed_nyc_pad_address_point")
        if row.get("reason") == "missing_verified_venue_geo":
            row["reason"] = None
        image = main.select_one(".fl-module-photo img[src]")
        candidate = photo_url(OTHER, image.get("src")) if image else None
        if candidate:
            row["image_url"] = candidate
        _attach_content(row, body, item["location"], candidate)
        return [row]
    return []


def _digest(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_checkpoint(value, now):
    if value is None:
        return None
    try:
        if (not isinstance(value, dict) or type(value["version"]) is not int or value["version"] != 1
                or value["source_key"] != OTHER or type(value["cursor"]) is not int or type(value["manifest_count"]) is not int
                or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_RECORDS
                or not isinstance(value["queue"], list) or len(value["queue"]) != value["manifest_count"]
                or value["manifest_hash"] != _digest(value["queue"])
                or not isinstance(value["events"], list) or len(value["events"]) > value["cursor"]
                or not isinstance(value["diagnostics"], list) or len(value["diagnostics"]) > value["cursor"]
                or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
            raise ValueError
        started = timestamp(value["started_at"])
        if started.tzinfo is None or value["window_start"] != calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        if now < started or now - started > timedelta(hours=4):
            return None
        for item in value["queue"]:
            if (not isinstance(item, dict) or not event_url(OTHER, item.get("url")) or item.get("location") not in VENUES
                    or not isinstance(item.get("title"), str) or not 0 < len(item["title"]) <= 180
                    or item["day"] != urlsplit(item["url"]).path.rstrip("/")[-10:]):
                raise ValueError
            date.fromisoformat(item["day"])
        native = {item["url"]: item for item in value["queue"][:value["cursor"]]}
        covered = set()
        for row in value["events"]:
            item = native.get(row.get("event_url"))
            if item is None:
                raise ValueError
            start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
            if (row["event_url"] in covered or row.get("title") != item["title"]
                    or start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(hours=18)
                    or start.astimezone(ZoneInfo(ZONE)).date().isoformat() != item["day"]
                    or row.get("id") != _identity(row["event_url"], start)
                    or tuple(row.get(field) for field in ("venue_name", "venue_address", "venue_city")) != VENUES[item["location"]]
                    or (row.get("lat"), row.get("lng")) != POINTS.get(item["location"])
                    or _body(row.get("description")) != row.get("description")
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or not _content_envelope_valid(row, item)
                    or row.get("image_url") is not None and photo_url(OTHER, row["image_url"]) is None
                    or not _within(start, end, started)):
                raise ValueError
            covered.add(row["event_url"])
        for item in value["diagnostics"]:
            if (not isinstance(item, dict) or item.get("event_url") not in native or item["event_url"] in covered
                    or item.get("disposition") != "held" or item.get("reason") not in HELD):
                raise ValueError
            covered.add(item["event_url"])
        if covered != set(native):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ValueError("new_york_other_half_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS_PER_CHUNK):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("new_york_other_half_checkpoint_invalid")
    state = _validate_checkpoint(checkpoint, current)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(SOURCES[OTHER][0], "text/html")
    queue = _manifest(payload, timestamp(state["started_at"]) if state else current)
    if state is None or state["queue"] != queue or state["manifest_hash"] != _digest(queue):
        queue = _manifest(payload, current)
        state = dict(version=1, source_key=OTHER, started_at=current.isoformat(),
                     window_start=calendar_anchor(current).astimezone(ZoneInfo(ZONE)).date().isoformat(), manifest_hash=_digest(queue),
                     manifest_count=len(queue), cursor=0, queue=queue, events=[], diagnostics=[])
    legacy_prefix = bool(state["events"] and
                         any("collector_event_content_v1" not in row for row in state["events"]))
    prior, fetched = state["cursor"], 0
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state["cursor"] < len(queue):
        if fetched >= limit or deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        item = queue[state["cursor"]]
        payload = fetch(item["url"], "text/html")
        fetched += 1
        try:
            rows = _detail(item, payload, current)
            if legacy_prefix:
                for row in rows:
                    row.pop("collector_event_content_v1", None)
            state["events"].extend(rows)
            if not rows:
                state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason="no_available_future_occurrence"))
        except ValueError as exc:
            if str(exc) not in HELD:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=str(exc)))
        state["cursor"] += 1
    if state["cursor"] == prior < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_other_half_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    return dict(complete=complete, events=deepcopy(rows), checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("new_york_other_half_checkpoint_required")
    return result["events"]
