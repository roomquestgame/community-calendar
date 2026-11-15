"""Visit Raleigh's public calendar, with complete pagination and durable stages.

The website's EventsApi supplies already-expanded occurrence days. Its ``date``
is the end of that local day, not an event time; only the publisher's ``times``
field supplies clocks. No RSS publication date or implied recurrence is used.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo
import zlib

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

SOURCE_KEY = "visit_raleigh_nc"
HOST = "www.visitraleigh.com"
CALENDAR = f"https://{HOST}/events/"
API = f"https://{HOST}/includes/rest/plugins_events_events_by_date/find/"
ZONE = ZoneInfo("America/New_York")
CONTRACT = "visit_raleigh_v1"
PAGE_SIZE = 100
MAX_PAGES = 100
MAX_RECORDS = 6000
MAX_DESCRIPTION = 12000
MAX_DECODED_BYTES = 24 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 850000
MAX_AGE = timedelta(hours=4)
MAX_PAGES_PER_CHUNK = 5
MIN_FETCH_SECONDS = 9
DETAIL = re.compile(r"/event/[^/?#]+/[1-9][0-9]{0,8}/")
_DAY_WORD = (r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
             r"thurs|tues|thur|mon|tue|wed|thu|fri|sat|sun")
_DAY = re.compile(r"\b(" + _DAY_WORD + r")s?\.?\b", re.I)
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_CLOCK = re.compile(r"(1[0-2]|[1-9])(?::([0-5][0-9]))?\s*(am|pm)?", re.I)
FIELDS = ("title", "recId", "date", "startDate", "endDate", "nextDate", "recurType",
          "recurrence", "times", "description", "location", "address1", "city", "state",
          "zip", "latitude", "longitude", "loc", "url", "media_raw", "categories",
          "admission", "listing.title", "listing.address1", "listing.city", "listing.state",
          "listing.zip", "listing.latitude", "listing.longitude", "host.title")
DIAGNOSTIC_CODES = frozenset({
    "collection_deadline",
    "unregistered_visit_raleigh", "visit_raleigh_calendar_configuration",
    "visit_raleigh_api_payload", "visit_raleigh_record_limit", "visit_raleigh_pagination_changed",
    "visit_raleigh_occurrence_identity", "visit_raleigh_occurrence_date",
    "visit_raleigh_checkpoint_invalid", "visit_raleigh_checkpoint_expired",
    "visit_raleigh_checkpoint_size_limit", "visit_raleigh_description_limit",
    "visit_raleigh_incomplete_event", "visit_raleigh_staging_acknowledgement",
})


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_source(source):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "kind", "platform_adapter", "timezone")) != (
            SOURCE_KEY, CALENDAR, "html", "html", ZONE.key):
        raise ValueError("unregistered_visit_raleigh")


def event_url(value):
    if not isinstance(value, str) or len(value) > 2000 or re.search(r"[\s\\<>]|%2f|%5c", value, re.I):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and parsed.netloc == HOST and not parsed.query
            and not parsed.fragment and ".." not in parsed.path.split("/")
            and bool(DETAIL.fullmatch(parsed.path)))


def calendar_configuration(payload):
    """Read the same public token and category selection used by the page."""
    tokens = re.findall(r'new\s+EventsApi\(\s*\{\s*"apiToken"\s*:\s*"([^"\r\n]+)"\s*\}', payload)
    modules = []
    for match in re.finditer(r"\bvar\s+moduleData\s*=\s*", payload):
        try:
            value, _ = json.JSONDecoder().raw_decode(payload[match.end():])
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and "eventCategories" in value:
            modules.append(value)
    if (len(tokens) != 1 or not 1 <= len(tokens[0]) <= 2000 or len(modules) != 1
            or not isinstance(modules[0]["eventCategories"], list)):
        raise ValueError("visit_raleigh_calendar_configuration")
    categories = modules[0]["eventCategories"]
    if (not 0 < len(categories) <= 100 or any(not isinstance(v, str) or not re.fullmatch(r"\d{1,8}", v)
                                            for v in categories) or len(set(categories)) != len(categories)):
        raise ValueError("visit_raleigh_calendar_configuration")
    return tokens[0], categories


def api_url(token, categories, window_start, window_end, page):
    if (not isinstance(token, str) or not 1 <= len(token) <= 2000
            or type(page) is not int or not 0 <= page < MAX_PAGES):
        raise ValueError("visit_raleigh_calendar_configuration")
    begins = datetime.combine(window_start, time.min, ZONE).astimezone(timezone.utc)
    ends = datetime.combine(window_end + timedelta(days=1), time.min, ZONE).astimezone(timezone.utc) - timedelta(seconds=1)
    params = [("filter[sites]", "primary"), ("filter[date][$gte]", begins.isoformat().replace("+00:00", "Z")),
              ("filter[date][$lte]", ends.isoformat().replace("+00:00", "Z")),
              ("options[skip]", page * PAGE_SIZE), ("options[limit]", PAGE_SIZE),
              ("options[sort][date]", 1), ("options[sort][rank]", 1),
              ("options[sort][title]", 1), ("options[sort][recId]", 1),
              ("options[hooks][]", "afterFind_listing"), ("options[hooks][]", "afterFind_host"),
              ("token", token)]
    params.extend(("filter[categories.catId][$in][]", value) for value in categories)
    params.extend(("options[fields][" + field + "]", 1) for field in FIELDS)
    return API + "?" + urlencode(params)


def _clock(value, inherited=None):
    match = _CLOCK.fullmatch(value.strip())
    if not match or not (match[3] or inherited):
        return None
    return time(int(match[1]) % 12 + (12 if (match[3] or inherited).lower() == "pm" else 0),
                int(match[2] or 0))


def _hours(value):
    """Parse explicit clocks and conventional shared-suffix ranges, e.g. 4–6pm."""
    value = value.strip().rstrip(".").lower()
    value = re.sub(r"a\.?\s*m\.?", "am", value)
    value = re.sub(r"p\.?\s*m\.?", "pm", value)
    value = re.sub(r"\bnoon\b", "12pm", value)
    value = re.sub(r"\bmidnight\b", "12am", value)
    value = re.sub(r"^(?:from\s*:?\s*|at\s+)", "", value)
    parts = re.split(r"\s*(?:&|,\s*(?:and\s+)?|\band\b)\s*", value)
    if not parts or len(parts) > 8:
        return []
    result = []
    # A common suffix also applies to a published showtime list: "2 and 7pm".
    suffix = re.search(r"(am|pm)$", value)
    next_start = None
    for part in reversed(parts):
        clocks = re.split(r"\s*(?:[-–—]|\bto\b)\s*", part.strip())
        if len(clocks) == 1:
            match = _CLOCK.fullmatch(clocks[0])
            starts = _clock(clocks[0], suffix[1] if suffix else None)
            if starts is None:
                return []
            if match is not None and not match[3] and next_start is not None and starts >= next_start:
                starts = time((starts.hour - 12) % 24, starts.minute)
            result.append((starts, None))
            next_start = starts
            continue
        if len(clocks) != 2:
            return []
        end_match = _CLOCK.fullmatch(clocks[1])
        start_match = _CLOCK.fullmatch(clocks[0])
        if not end_match or not end_match[3] or not start_match:
            return []
        ends = _clock(clocks[1])
        starts = _clock(clocks[0], end_match[3])
        if not start_match[3] and starts >= ends:
            # A compact "11–1pm" interval explicitly shares the suffix;
            # choose the immediately preceding 11am, never a 14-hour interval.
            starts = time((starts.hour - 12) % 24, starts.minute)
        if starts == ends:
            return []
        result.append((starts, ends))
        next_start = starts
    return list(reversed(result))


def schedule_hours(value, day):
    """Select the occurrence's explicit weekday clause without expanding dates."""
    value = plain(value)
    if not value:
        return []
    # Doors/sign-up times describe admission, not another performance.
    value = re.sub(r"\([^()]*(?:doors?\s+(?:open|at)|doors?\s*\d)[^()]*\)", "", value, flags=re.I)
    value = re.sub(r"[,.]?\s*doors?\s+open[^;]*", "", value, flags=re.I)
    value = re.sub(r"\.\s*sign\s*up\s+starts[^;]*", "", value, flags=re.I)
    uncertain_end = re.search(r"\(\s*or\s+(?:1[0-2]|[1-9])(?::[0-5][0-9])?\s*[ap]m\s+depending\s+on\s+the\s+date\s*\)", value, re.I)
    if uncertain_end:
        value = value[:uncertain_end.start()] + value[uncertain_end.end():]
    if re.search(r"\bor\b", value, re.I):
        return []
    if re.search(r"closed\s+(?:on\s+)?christmas(?:\s+day)?", value, re.I) and (day.month, day.day) == (12, 25):
        return []
    if (re.search(r"closed\s+(?:on\s+)?thanksgiving(?:\s+day)?", value, re.I)
            and day.month == 11 and day.weekday() == 3 and 22 <= day.day <= 28):
        return []
    # "First Wednesday" can mean first of the run or first of the month.
    # Retain unaffected weekdays, but do not invent which Wednesday it means.
    exception = re.search(r"\(\s*(?:the\s+)?first\s+(" + _DAY_WORD + r")\s+is\s+only\s+([^()]+)\)", value, re.I)
    if exception:
        if day.weekday() == _DAYS[exception[1][:3].lower()]:
            ordinary = schedule_hours(value[:exception.start()] + value[exception.end():], day)
            # The intersection is certain under either meaning of "first".
            return [hours for hours in ordinary if hours in _hours(exception[2])]
        value = value[:exception.start()] + value[exception.end():]
    # Split different weekday schedules joined by "and", while preserving
    # weekday lists that have not yet supplied any clock.
    chunks = re.split(r"\s*;\s*|(?:\s+and\s+|,\s*)(?=(?:" + _DAY_WORD + r")\b)", value, flags=re.I)
    clauses, pending = [], ""
    for chunk in chunks:
        if not re.search(r"\d|\b(?:noon|midnight)\b", chunk, re.I) and _DAY.search(chunk):
            pending += chunk + ", "
            continue
        clauses.append(pending + chunk)
        pending = ""
    if pending:
        return []
    chosen = []
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        if re.match(r"(?:closed\b|sign\s*ups?\b|doors?\b|seating\s+starts\b)", clause, re.I):
            continue
        clause = re.sub(r"^(?:singing|show|performance|departure\s+times|late\s+show|early\s+show)\s*[:,]\s*", "", clause, flags=re.I)
        clause = re.sub(r"\b(?:early|late)\s+show\s*,\s*", "", clause, flags=re.I)
        month_names = "January|February|March|April|May|June|July|August|September|October|November|December"
        season = re.match(r"(" + month_names + r")\s*[-–—]\s*(" + month_names + r")\s+", clause, re.I)
        if season:
            a, b = (datetime.strptime(v.title(), "%B").month for v in season.groups())
            if day.month not in {(a - 1 + n) % 12 + 1 for n in range((b - a) % 12 + 1)}:
                continue
            clause = clause[season.end():]
        first_clock = re.search(r"\d|\b(?:noon|midnight)\b", clause, re.I)
        if first_clock is None:
            return []
        prefix = clause[:first_clock.start()]
        matches = list(_DAY.finditer(prefix))
        if matches:
            weekdays = {_DAYS[m[1][:3].lower()] for m in matches}
            if len(matches) == 2 and re.search(r"[-–—]|\bthrough\b|\bto\b", prefix[matches[0].end():matches[1].start()], re.I):
                a, b = (_DAYS[m[1][:3].lower()] for m in matches)
                weekdays = {(a + n) % 7 for n in range((b - a) % 7 + 1)}
            if day.weekday() not in weekdays:
                continue
            prefix_without_days = _DAY.sub("", prefix)
            if re.sub(r"[\s,.:&/–—-]|\band\b|\bthrough\b|\bto\b", "", prefix_without_days, flags=re.I):
                return []
            clocks = clause[first_clock.start():]
        else:
            if prefix and not re.fullmatch(r"\s*(?:daily|every day|from|at)?[\s,:.]*", prefix, re.I):
                return []
            clocks = clause[first_clock.start():]
        hours = _hours(clocks)
        if not hours:
            return []
        chosen.extend(hours)
    chosen = sorted(set(chosen), key=lambda pair: (pair[0], pair[1] or pair[0]))
    if uncertain_end:
        return [(chosen[0][0], None)] if len(chosen) == 1 and chosen[0][1] is not None else []
    return chosen


def manifest_hash(window_start, window_end, raw_total, categories):
    return sha256(_encoded(dict(source_key=SOURCE_KEY, window_start=window_start,
        window_end=window_end, raw_total=raw_total, page_size=PAGE_SIZE,
        categories=categories, sort="date,rank,title,recId")).encode()).hexdigest()


def _coordinate(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def parse_occurrence(item, *, window_start, window_end):
    if not isinstance(item, dict):
        raise ValueError("visit_raleigh_api_payload")
    identity = str(item.get("recId") or item.get("recid") or "")
    if not re.fullmatch(r"[1-9][0-9]{0,8}", identity):
        raise ValueError("visit_raleigh_occurrence_identity")
    url = item.get("absoluteUrl") or item.get("url")
    if isinstance(url, str) and url.startswith("/"):
        url = "https://" + HOST + url
    if not event_url(url) or url.rstrip("/").split("/")[-1] != identity:
        raise ValueError("visit_raleigh_occurrence_identity")
    try:
        instant = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        local = instant.astimezone(ZONE)
        if local.time().replace(microsecond=0) != time(23, 59, 59) or not window_start <= local.date() <= window_end:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("visit_raleigh_occurrence_date") from exc
    occurrence_key = identity + ":" + local.date().isoformat()
    title = plain(item.get("title"))
    if not title:
        raise ValueError("visit_raleigh_occurrence_identity")
    if any(item.get(key) is True for key in ("cancelled", "canceled", "expired", "past", "private")) or re.search(
            r"\b(?:cancelled|canceled|postponed)\b", title, re.I):
        return occurrence_key, [], "past_or_cancelled"
    narrative = description(item.get("description"), limit=MAX_DESCRIPTION + 1)
    if len(narrative) > MAX_DESCRIPTION:
        raise ValueError("visit_raleigh_description_limit")
    if not narrative:
        return occurrence_key, [], "event_description_missing"
    hours = schedule_hours(item.get("times"), local.date())
    if not hours:
        return occurrence_key, [], "event_time_missing_or_ambiguous"
    street, city, region, postal = (plain(item.get(field)) for field in ("address1", "city", "state", "zip"))
    if region.lower() == "north carolina":
        region = "NC"
    complete_address = (bool(re.search(r"\b[0-9]{1,6}\s+[A-Za-z]", street)) and bool(city)
                        and region == "NC" and bool(re.fullmatch(r"\d{5}(?:-\d{4})?", postal)))
    listing = item.get("listing")
    venue = plain(item.get("location")) or (plain(listing.get("title")) if isinstance(listing, dict) else "") or street
    full_address = ", ".join(part for part in (street, city, " ".join(part for part in (region, postal) if part)) if part)
    lat = _coordinate(item.get("latitude"), 33.8, 36.7)
    lng = _coordinate(item.get("longitude"), -84.4, -75.3)
    point = item.get("loc")
    coordinates = point.get("coordinates") if isinstance(point, dict) and point.get("type") == "Point" else None
    if isinstance(coordinates, list) and len(coordinates) == 2:
        point_lng, point_lat = _coordinate(coordinates[0], -84.4, -75.3), _coordinate(coordinates[1], 33.8, 36.7)
        if lat is not None and lng is not None and point_lat is not None and point_lng is not None:
            if abs(lat - point_lat) > 0.0001 or abs(lng - point_lng) > 0.0001:
                return occurrence_key, [], "venue_coordinates_conflict"
        elif point_lat is not None and point_lng is not None:
            lat, lng = point_lat, point_lng
    provenance = "publisher_event_geo"
    if lat is None or lng is None:
        lat = lng = None
        if (complete_address and isinstance(listing, dict)
                and item.get("listing_id") == listing.get("recid")
                and all(plain(item.get(field)).casefold() == plain(listing.get(field)).casefold()
                        for field in ("address1", "city", "state", "zip"))):
            lat = _coordinate(listing.get("latitude"), 33.8, 36.7)
            lng = _coordinate(listing.get("longitude"), -84.4, -75.3)
            provenance = "publisher_linked_venue_geo"
        if lat is None or lng is None:
            lat = lng = None
            provenance = "publisher_event_address_pending_geocode"
    if (not full_address or not venue or (lat is None and not complete_address)
            or (region and region != "NC")):
        return occurrence_key, [], "venue_address_missing"
    admission = plain(item.get("admission"))
    if admission and admission.casefold() not in narrative.casefold():
        narrative += "\nAdmission: " + admission
        if len(narrative) > MAX_DESCRIPTION:
            raise ValueError("visit_raleigh_description_limit")
    categories = [plain(category.get("catName")) for category in item.get("categories", [])
                  if isinstance(category, dict) and plain(category.get("catName"))]
    image = None
    for media in item.get("media_raw") or []:
        if not isinstance(media, dict) or str(media.get("mediatype", "")).lower() != "image":
            continue
        candidate = media.get("mediaurl")
        if (isinstance(candidate, str) and len(candidate) <= 2000
                and candidate.startswith("https://assets.simpleviewinc.com/")
                and ("/raleigh/" in candidate or "/sv-raleigh/" in candidate)
                and not re.search(r"[\s\\<>]", candidate)):
            image = candidate
            break
    rows = []
    for clock, end_clock in hours:
        begins = datetime.combine(local.date(), clock)
        ends = datetime.combine(local.date(), end_clock) if end_clock else None
        if ends and ends < begins:
            ends += timedelta(days=1)
        # The shared converter rejects ambiguous/nonexistent local DST times.
        row = record(title, begins.isoformat(), ends.isoformat() if ends else None,
                     venue, full_address, city, url, identity, ", ".join(categories),
                     lat, lng, ZONE.key, publisher_geo=lat is not None, retain_until_end=True)
        if row:
            row.update(description=narrative, timezone=ZONE.key, publisher_categories=categories,
                       location_provenance=provenance)
            if image:
                row["image_url"] = image
            rows.append(row)
    return occurrence_key, rows, None if rows else "outside_window"


def validate_records(records, *, window_start, window_end):
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("visit_raleigh_record_limit")
    seen = set()
    for row in records:
        if (not isinstance(row, dict) or not re.fullmatch(r"[1-9][0-9]{0,8}", str(row.get("id", "")))
                or not event_url(row.get("event_url"))
                or row["event_url"].rstrip("/").split("/")[-1] != row["id"]
                or not isinstance(row.get("description"), str)
                or not 0 < len(row["description"].strip()) <= MAX_DESCRIPTION
                or not isinstance(row.get("venue_address"), str) or not row["venue_address"]
                or not isinstance(row.get("venue_name"), str) or not row["venue_name"]
                or not isinstance(row.get("title"), str) or not row["title"]
                or row.get("timezone") != ZONE.key
                or row.get("location_provenance") not in ("publisher_event_geo", "publisher_linked_venue_geo",
                                                         "publisher_event_address_pending_geocode")):
            raise ValueError("visit_raleigh_incomplete_event")
        if ((row.get("lat") is None) != (row.get("lng") is None)
                or (row.get("lat") is not None and (_coordinate(row["lat"], 33.8, 36.7) is None
                                                     or _coordinate(row["lng"], -84.4, -75.3) is None))):
            raise ValueError("visit_raleigh_incomplete_event")
        try:
            starts, ends = timestamp(row["starts_at"]), timestamp(row.get("ends_at"))
            if starts.tzinfo is None or not window_start <= starts.astimezone(ZONE).date() <= window_end:
                raise ValueError
            if ends is not None and ends <= starts:
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("visit_raleigh_incomplete_event") from exc
        key = (row["id"], row["starts_at"])
        if key in seen:
            raise ValueError("visit_raleigh_occurrence_identity")
        seen.add(key)


def encode_checkpoint(header, payload):
    raw = _encoded(payload).encode("utf-8")
    if len(raw) > MAX_DECODED_BYTES:
        raise ValueError("visit_raleigh_checkpoint_size_limit")
    result = dict(header, diagnostics=[dict(reason=reason, count=count)
                  for reason, count in sorted(payload["diagnostics"].items())],
                  payload_encoding="zlib+base64", payload_sha256=sha256(raw).hexdigest(),
                  payload=base64.b64encode(zlib.compress(raw, level=6)).decode("ascii"), events=[])
    if len(_encoded(result).encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("visit_raleigh_checkpoint_size_limit")
    return result


def decode_checkpoint(checkpoint, *, now):
    """Bound decompression before decoding; accept only canonical verified JSON."""
    if (not isinstance(checkpoint, dict) or len(_encoded(checkpoint).encode()) > MAX_CHECKPOINT_BYTES
            or checkpoint.get("version") != 1 or type(checkpoint.get("version")) is not int
            or checkpoint.get("contract") != CONTRACT or checkpoint.get("source_key") != SOURCE_KEY
            or checkpoint.get("payload_encoding") != "zlib+base64" or checkpoint.get("events") != []
            or not isinstance(checkpoint.get("payload"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(checkpoint.get("payload_sha256", "")))):
        raise ValueError("visit_raleigh_checkpoint_invalid")
    try:
        compressed = base64.b64decode(checkpoint["payload"], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_DECODED_BYTES + 1)
        if (len(raw) > MAX_DECODED_BYTES or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data
                or sha256(raw).hexdigest() != checkpoint["payload_sha256"]):
            raise ValueError
        payload = json.loads(raw.decode("utf-8"))
        if _encoded(payload).encode("utf-8") != raw:
            raise ValueError
        started = datetime.fromisoformat(checkpoint["started_at"])
        window_start = date.fromisoformat(checkpoint["window_start"])
        window_end = date.fromisoformat(checkpoint["window_end"])
        if (started.tzinfo is None or now.tzinfo is None or window_start != started.astimezone(ZONE).date()
                or window_end != window_start + timedelta(days=59)):
            raise ValueError
        if not started <= now <= started + MAX_AGE:
            raise ValueError("visit_raleigh_checkpoint_expired")
        for name in ("cursor", "manifest_count", "raw_total", "record_count", "stage_cursor"):
            if type(checkpoint.get(name)) is not int:
                raise ValueError
        if (not 0 <= checkpoint["raw_total"] <= MAX_RECORDS
                or checkpoint["manifest_count"] != math.ceil(checkpoint["raw_total"] / PAGE_SIZE)
                or not 0 <= checkpoint["cursor"] <= checkpoint["manifest_count"] <= MAX_PAGES
                or not 0 <= checkpoint["stage_cursor"] <= checkpoint["record_count"] <= MAX_RECORDS
                or checkpoint.get("page_size") != PAGE_SIZE or type(checkpoint.get("page_size")) is not int
                or checkpoint["phase"] not in ("fetch", "stage")
                or (checkpoint["phase"] == "fetch" and checkpoint["stage_cursor"] != 0)
                or (checkpoint["phase"] == "stage" and checkpoint["cursor"] != checkpoint["manifest_count"])):
            raise ValueError
        if (not isinstance(payload, dict) or set(payload) != {"token", "categories", "events", "seen", "diagnostics"}
                or not isinstance(payload["token"], str) or not 1 <= len(payload["token"]) <= 2000
                or not isinstance(payload["categories"], list) or not 0 < len(payload["categories"]) <= 100
                or any(not isinstance(v, str) or not re.fullmatch(r"\d{1,8}", v) for v in payload["categories"])
                or not isinstance(payload["seen"], list) or len(set(payload["seen"])) != len(payload["seen"])
                or len(payload["seen"]) != min(checkpoint["cursor"] * PAGE_SIZE, checkpoint["raw_total"])
                or any(not re.fullmatch(r"[1-9][0-9]{0,8}:\d{4}-\d{2}-\d{2}", value) for value in payload["seen"])
                or not isinstance(payload["diagnostics"], dict)
                or any(not re.fullmatch(r"[a-z_]{3,80}", key) or type(value) is not int or value < 0
                       for key, value in payload["diagnostics"].items())
                or checkpoint["record_count"] != len(payload["events"])
                or checkpoint.get("diagnostics") != [dict(reason=reason, count=count)
                    for reason, count in sorted(payload["diagnostics"].items())]
                or checkpoint.get("manifest_hash") != manifest_hash(checkpoint["window_start"],
                    checkpoint["window_end"], checkpoint["raw_total"], payload["categories"])):
            raise ValueError
        validate_records(payload["events"], window_start=window_start, window_end=window_end)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, binascii.Error, zlib.error) as exc:
        if str(exc) == "visit_raleigh_checkpoint_expired":
            raise
        raise ValueError("visit_raleigh_checkpoint_invalid") from exc
    header = {key: value for key, value in checkpoint.items()
              if key not in ("payload_encoding", "payload_sha256", "payload", "events")}
    return header, payload


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_pages=MAX_PAGES_PER_CHUNK):
    validate_source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES_PER_CHUNK:
        raise ValueError("visit_raleigh_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    if checkpoint is not None:
        header, state = decode_checkpoint(checkpoint, now=current)
        if header["phase"] == "stage":
            return dict(checkpoint=checkpoint, complete=True, events=state["events"])
    else:
        token, categories = calendar_configuration(fetch(CALENDAR, "text/html"))
        first = current.astimezone(ZONE).date()
        header = dict(version=1, contract=CONTRACT, source_key=SOURCE_KEY,
                      started_at=current.isoformat(), window_start=first.isoformat(),
                      window_end=(first + timedelta(days=59)).isoformat(),
                      cursor=0, manifest_count=0, raw_total=0, record_count=0, stage_cursor=0,
                      page_size=PAGE_SIZE, phase="fetch")
        state = dict(token=token, categories=categories, events=[], seen=[], diagnostics={})
    first, last = date.fromisoformat(header["window_start"]), date.fromisoformat(header["window_end"])
    seen = set(state["seen"])
    pages_read = 0
    while pages_read < max_pages:
        if deadline_at is not None and monotonic() > deadline_at - MIN_FETCH_SECONDS:
            if not header["cursor"]:
                raise ValueError("collection_deadline")
            break
        target = api_url(state["token"], state["categories"], first, last, header["cursor"])
        try:
            response = json.loads(fetch(target, "application/json"))
        except (TypeError, ValueError) as exc:
            # Preserve ordinary transport failures rather than claiming bad JSON.
            from roomquest.preview_worker import PreviewError
            if isinstance(exc, PreviewError):
                raise
            raise ValueError("visit_raleigh_api_payload") from exc
        if (not isinstance(response, dict) or not isinstance(response.get("docs"), list)
                or type(response.get("total")) is not int or response["total"] < 0):
            raise ValueError("visit_raleigh_api_payload")
        if response["total"] > MAX_RECORDS or math.ceil(response["total"] / PAGE_SIZE) > MAX_PAGES:
            raise ValueError("visit_raleigh_record_limit")
        if header["cursor"] and response["total"] != header["raw_total"]:
            raise ValueError("visit_raleigh_pagination_changed")
        header["raw_total"] = response["total"]
        header["manifest_count"] = math.ceil(response["total"] / PAGE_SIZE)
        header["manifest_hash"] = manifest_hash(header["window_start"], header["window_end"],
                                                header["raw_total"], state["categories"])
        expected = min(PAGE_SIZE, response["total"] - header["cursor"] * PAGE_SIZE)
        if len(response["docs"]) != expected:
            raise ValueError("visit_raleigh_pagination_changed")
        for item in response["docs"]:
            identity, rows, reason = parse_occurrence(item, window_start=first, window_end=last)
            if identity in seen:
                raise ValueError("visit_raleigh_pagination_changed")
            seen.add(identity)
            state["seen"].append(identity)
            state["events"].extend(rows)
            if reason:
                state["diagnostics"][reason] = state["diagnostics"].get(reason, 0) + 1
        header["record_count"] = len(state["events"])
        if header["record_count"] > MAX_RECORDS:
            raise ValueError("visit_raleigh_record_limit")
        header["cursor"] = min(header["cursor"] + 1, header["manifest_count"])
        pages_read += 1
        if header["cursor"] == header["manifest_count"]:
            header["phase"] = "stage"
            validate_records(state["events"], window_start=first, window_end=last)
            break
    # Keep a listing's repeated full narrative adjacent for bounded compression.
    # The final order is deterministic and stays fixed while staging advances.
    state["events"].sort(key=lambda row: (row["id"], row["starts_at"]))
    result = encode_checkpoint(header, state)
    return dict(checkpoint=result, complete=header["phase"] == "stage",
                events=state["events"] if header["phase"] == "stage" else [])
