"""ChamberMate public JSON events through the shared factual intake pipeline.

The reviewed source registry owns each tenant. This adapter only reads its
public, non-portal event list; it does not schedule work, geocode, classify,
publish, or substitute an organizer's address for an event venue.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest.mapsee_adapter import plain, record

API_HOST = "api.chambermate.com"
API_URL = "https://" + API_HOST + "/core/biz/webPresence/getEventsInfo"
EVENT_TYPES = ("CHMBR", "MBR", "COMM")
MAX_RECORDS = 500
MAX_CATEGORY_OPTIONS = 500
MAX_EVENT_CATEGORIES = 20
MAX_CATEGORY_LENGTH = 100
_TENANT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_IDENTITY = re.compile(r"[A-Za-z0-9_|-]{1,180}")
_UTC_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|\+00:00)?")
_AVATAR = re.compile(r"EVENT/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_TIMEZONE_ALIASES = {
    "EST5EDT": "America/New_York", "CST6CDT": "America/Chicago",
    "MST7MDT": "America/Denver", "PST8PDT": "America/Los_Angeles",
}


@dataclass(frozen=True)
class Source:
    shorthand: str
    domain: str
    timezone: str


def _timezone(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError("source_timezone_required")
    name = _TIMEZONE_ALIASES.get(value, value)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("source_timezone_unresolved") from exc
    return name


def source_config(source):
    """Bind the exact public endpoint to one reviewed ChamberMate tenant host.

    Caller-controlled filters, custom domains, credentials, fragments and extra
    query fields are unsupported. The database provides this source row only
    after its normal rights, review, ownership, demand and lease checks.
    """
    from roomquest.preview_worker import public_source_url

    if source.get("platform_adapter") != "chambermate" or source.get("kind") != "json":
        raise ValueError("unregistered_chambermate_source")
    url = source.get("feed_url")
    if not isinstance(url, str) or not public_source_url(url) or re.search(r"[\x00-\x20\\]", url):
        raise ValueError("unregistered_chambermate_source")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != API_HOST or parsed.fragment
            or parsed.path != "/core/biz/webPresence/getEventsInfo"):
        raise ValueError("unregistered_chambermate_source")
    try:
        fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("unregistered_chambermate_source") from exc
    params = dict(fields)
    if len(fields) != 2 or set(params) != {"websiteShorthand", "websiteDomain"}:
        raise ValueError("unregistered_chambermate_source")
    shorthand, domain = params["websiteShorthand"], params["websiteDomain"]
    if (not _TENANT.fullmatch(shorthand) or shorthand in {"www", "app", "api"}
            or domain != shorthand + ".chambermate.com"):
        raise ValueError("chambermate_tenant_mismatch")
    publisher = source.get("publisher_url")
    if publisher is not None and (not isinstance(publisher, str)
            or not public_source_url(publisher) or urlsplit(publisher).hostname != domain):
        raise ValueError("chambermate_tenant_mismatch")
    return Source(shorthand, domain, _timezone(source.get("timezone")))


def events_url(config, *, now=None):
    # eventsCount describes the full public list, even when host filters hide
    # rows. Always request every host group before asserting completeness.
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("chambermate_window_timezone_missing")
    current = current.astimezone(timezone.utc)
    fields = [
        ("websiteShorthand", config.shorthand), ("websiteDomain", config.domain),
        ("isPortal", "false"),
        *(("eventTypeCodes", kind) for kind in EVENT_TYPES),
        ("includeCategories", "true"), ("includePastEvents", "true"),
        ("startDateTime", current.isoformat(timespec="seconds")),
        ("endDateTime", (current + timedelta(days=60)).isoformat(timespec="seconds")),
        ("rowCount", str(MAX_RECORDS + 1)),
    ]
    return API_URL + "?" + urlencode(fields)


def utc_timestamp(value):
    """The public frontend appends Z; these naive strings are UTC, not local."""
    if not isinstance(value, str) or not _UTC_TIME.fullmatch(value):
        raise ValueError("invalid_chambermate_time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid_chambermate_time") from exc


def _text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("invalid_chambermate_text")
    if len(value) > 2000:
        raise ValueError("chambermate_text_limit")
    return plain(value)


def _description(event):
    from bs4 import BeautifulSoup

    for field in ("eventFullDescription", "eventDescription"):
        value = event.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError("invalid_chambermate_text")
        # Bound HTML parsing separately from the 2,000-character staging field.
        # Empty full-description markup can still fall back to the short text.
        soup = BeautifulSoup(value[:20_000], "html.parser")
        for node in soup.find_all(("script", "style")):
            node.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        if text:
            return text[:2000]
    return ""


def _flag(event, name):
    value = event.get(name, False)
    if not isinstance(value, bool):
        raise ValueError("invalid_chambermate_flags")
    return value


def _category_options(data):
    categories = data.get("eventCategories")
    if not isinstance(categories, dict) or not isinstance(categories.get("systemFieldOptions"), list):
        raise ValueError("invalid_chambermate_categories")
    options = categories["systemFieldOptions"]
    if len(options) > MAX_CATEGORY_OPTIONS:
        raise ValueError("source_category_limit")
    result = {}
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("invalid_chambermate_categories")
        key = option.get("systemFieldOptionKey")
        label = _text(option.get("systemFieldOptionLabel"))
        if not isinstance(key, str) or not key or len(key) > 180 or not label:
            raise ValueError("invalid_chambermate_categories")
        if len(label) > MAX_CATEGORY_LENGTH:
            raise ValueError("source_category_limit")
        if key in result and result[key] != label:
            raise ValueError("conflicting_publisher_category")
        result[key] = label
    return result


def _categories(event, options):
    keys = event.get("eventCategoriesSystemFieldOptionKeys", [])
    if not isinstance(keys, list):
        raise ValueError("invalid_chambermate_categories")
    if len(keys) > MAX_EVENT_CATEGORIES:
        raise ValueError("source_category_limit")
    labels = []
    for key in keys:
        if not isinstance(key, str) or key not in options:
            raise ValueError("unresolved_publisher_category")
        label = options[key]
        if label not in labels:
            labels.append(label)
    # A comma in a label is part of that label. CHMBR/MBR/COMM describe the host,
    # and are never converted into topical labels or an EventQuest category.
    return labels


def _event_url(value, identity, config):
    from roomquest.preview_worker import public_source_url

    if not isinstance(value, str) or not public_source_url(value) or re.search(r"[\x00-\x20\\]", value):
        raise ValueError("invalid_chambermate_event_link")
    parsed = urlsplit(value)
    try:
        fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("invalid_chambermate_event_link") from exc
    if (parsed.scheme != "https" or parsed.netloc != config.domain or parsed.path != "/event-detail" or parsed.fragment
            or fields != [("e", identity)]):
        raise ValueError("chambermate_event_identity_mismatch")
    return value


def _location(event):
    mode = {"In Person": "in_person", "Online": "online", "Phone": "phone", "Hybrid": "hybrid"}.get(event.get("contactTypeCode"))
    if mode in {"online", "phone"}:
        # Associations describe the organizer, including its office address.
        # Even an address mistakenly present on a virtual record is not a pin.
        return mode, "", "", ""
    if mode not in {"in_person", "hybrid"}:
        raise ValueError("unsupported_chambermate_attendance")
    if event.get("addressCode") == "Freeform Custom Text":
        # The public renderer gives this field precedence over any stale
        # structured/contact address. Keep its words without guessing a city.
        custom = _text(event.get("customAddress"))
        if not custom:
            raise ValueError("chambermate_custom_address_missing")
        if len(custom) > 400:
            raise ValueError("chambermate_address_limit")
        return mode, "", custom, ""
    address = event.get("address")
    if address is None:
        address = {}
    if not isinstance(address, dict):
        raise ValueError("invalid_chambermate_address")
    venue = _text(address.get("name") or address.get("nickname"))
    city = _text(address.get("city"))
    region = address.get("stateCode") or address.get("province") or address.get("stateName")
    parts = (address.get("street1"), address.get("street2"), city, region, address.get("zip"))
    street = ", ".join(text for value in parts if (text := _text(value)))
    country = _text(address.get("countryCode"))
    if country and country not in {"US", "USA"}:
        street = ", ".join(value for value in (street, _text(address.get("countryName")) or country) if value)
    if len(street) > 400 or len(venue) > 160 or len(city) > 120:
        raise ValueError("chambermate_address_limit")
    return mode, venue, street, city


def _image_url(event):
    key = event.get("avatarStorageKey")
    if not isinstance(key, str) or not _AVATAR.fullmatch(key):
        return None
    # This is the public event card's direct-storage image route. An explicit
    # key has no organizer/default fallback. Existing media verifies the bytes.
    return "https://" + API_HOST + "/core/app/storage/directView?" + urlencode({"k": key})


def _times(event):
    if _flag(event, "noTimes"):
        raise ValueError("unsupported_all_day_time")
    schedules = event.get("daySchedules")
    if schedules is None:
        schedules = []
    if not isinstance(schedules, list):
        raise ValueError("invalid_chambermate_schedule")
    if len(schedules) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    if schedules:
        pairs = []
        for schedule in schedules:
            if not isinstance(schedule, dict):
                raise ValueError("invalid_chambermate_schedule")
            start = utc_timestamp(schedule.get("startDateTime"))
            end = (utc_timestamp(schedule["endDateTime"])
                   if schedule.get("endDateTime") is not None else None)
            pairs.append((start, end))
        # The frontend displays these exact intervals. The parent range and
        # parent noEndTime flag do not replace their ends or create extra days.
    else:
        start = utc_timestamp(event.get("startDateTime"))
        end = (None if _flag(event, "noEndTime") or event.get("endDateTime") is None
               else utc_timestamp(event["endDateTime"]))
        pairs = [(start, end)]
    if any(end is not None and end <= start for start, end in pairs):
        raise ValueError("invalid_chambermate_end")
    return pairs


def parse(payload, source):
    """Normalize a complete public response; unknown/truncated shapes fail."""
    config = source_config(source)
    if (not isinstance(payload, dict) or payload.get("status") is not True
            or payload.get("error") is not None or not isinstance(payload.get("data"), dict)):
        raise ValueError("invalid_chambermate_payload")
    data = payload["data"]
    events, total = data.get("events"), data.get("eventsCount")
    if not isinstance(events, list) or type(total) is not int or total < 0:
        raise ValueError("invalid_chambermate_snapshot")
    if len(events) > MAX_RECORDS or total > MAX_RECORDS:
        raise ValueError("source_record_limit")
    if total != len(events):
        raise ValueError("incomplete_chambermate_snapshot")
    if _timezone(data.get("timeZoneIANAId")) != config.timezone:
        raise ValueError("chambermate_timezone_mismatch")
    options = _category_options(data)
    unique = {}
    occurrences = 0
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("invalid_chambermate_event")
        identity = event.get("activityKey")
        if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
            raise ValueError("invalid_chambermate_event_id")
        url = _event_url(event.get("eventDetailUrl"), identity, config)
        kind = event.get("eventTypeCode")
        if kind not in EVENT_TYPES:
            raise ValueError("unsupported_chambermate_event_type")
        pairs = _times(event)
        occurrences += len(pairs)
        if occurrences > MAX_RECORDS:
            raise ValueError("source_record_limit")
        mode, venue, street, city = _location(event)
        labels = _categories(event, options)
        description = _description(event)
        image = _image_url(event)
        for start, end in pairs:
            row = record(_text(event.get("eventName")), start.isoformat(), end.isoformat() if end else None,
                         venue, street, city, url, identity, category=", ".join(labels),
                         lat=None, lng=None, tz=config.timezone, retain_until_end=True)
            if row is None:
                continue
            row.update(timezone=config.timezone, publisher_categories=labels,
                       publisher_event_type=kind, attendance_mode=mode)
            if description:
                row["description"] = description
            if mode in {"online", "phone"}:
                row.update(venue_name="", venue_address="", venue_city="", lat=None, lng=None,
                           reason=mode + "_event")
            elif event.get("addressCode") == "Freeform Custom Text":
                row.update(venue_name="", venue_city="")
            if image:
                row["image_url"] = image
            occurrence = (row["id"], row["starts_at"])
            if occurrence in unique and unique[occurrence] != row:
                raise ValueError("conflicting_event_occurrence")
            unique[occurrence] = row
    return sorted(unique.values(), key=lambda row: (row["starts_at"], row["id"]))


def collect(source, fetch, *, deadline_at=None):
    config = source_config(source)
    deadline = min(monotonic() + 20, deadline_at if deadline_at is not None else float("inf"))
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    try:
        payload = json.loads(fetch(events_url(config), "application/json"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_chambermate_payload") from exc
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    rows = parse(payload, source)
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    return rows
