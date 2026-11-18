"""Bounded publisher RSS read for three Batch 01 library canaries.

BiblioCommons RSS is distinct from its proprietary JSON gateway. This module
does not authorize commercial republication or any publisher image. Exact
source registry approval and rights review still gate production collection.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

GATEWAY = "gateway.bibliocommons.com"
EVENT_NS = "{http://bibliocommons.com/rss/1.0/modules/event/}"
PAGE_SIZE = 25
MAX_PAGES = 24
MAX_RECORDS = 500
HORIZON_DAYS = 21
MAX_DESCRIPTION = 12000
# Every profile is one exact publisher tenant. A publisher may have offsite
# events, but no other state's branch address is silently assigned a home pin.
SOURCES = {
    "king_county_library_rss_wa": ("kcls", "America/Los_Angeles", "WA"),
    "central_rappahannock_library_rss_va": ("librarypoint", "America/New_York", "VA"),
    "palm_beach_county_library_rss_fl": ("pbclibrary", "America/New_York", "FL"),
}
EVENT_ID = re.compile(r"[a-f0-9]{24}")
LOCAL_START = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?")
_XML_UNSAFE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.I)


def _field(element, name):
    return (element.findtext(EVENT_NS + name) or "").strip() if element is not None else ""


def _event_identity(item, slug):
    url = (item.findtext("link") or "").strip()
    guid = (item.findtext("guid") or "").strip()
    parsed = urlsplit(url)
    match = re.fullmatch(r"/events/([a-f0-9]{24})", parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != f"{slug}.bibliocommons.com"
            or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
            or not match or guid != url):
        raise ValueError("bibliocommons_rss_event_identity_invalid")
    return url, match.group(1)


def _geo(location, state):
    number, road, city = (_field(location, k) for k in ("number", "street", "city"))
    region, zipcode = (_field(location, k) for k in ("state", "zip"))
    venue = _field(location, "name")
    if (not venue or not number or not road or not city or region != state
            or not re.fullmatch(r"\d{1,6}[A-Za-z]?", number.strip())
            or not re.fullmatch(r"\d{5}(?:-\d{4})?", zipcode)
            or any("," in field for field in (number, road, city))):
        return "", "", "", None, None
    street = f"{number} {road}, {city}, {region} {zipcode}"
    lat_text, lng_text = _field(location, "latitude"), _field(location, "longitude")
    lat = lng = None
    if lat_text or lng_text:
        if not lat_text or not lng_text:
            raise ValueError("bibliocommons_rss_incomplete_geo")
        try:
            lat, lng = float(lat_text), float(lng_text)
        except (ValueError, OverflowError) as exc:
            raise ValueError("bibliocommons_rss_geo_invalid") from exc
        if (not math.isfinite(lat) or not math.isfinite(lng)
                or not 18 <= lat <= 72 or not -175 <= lng <= -65):
            raise ValueError("bibliocommons_rss_geo_invalid")
    return venue, street, city, lat, lng


def _description(item):
    raw = item.findtext("description") or ""
    # Clean HTML once, and detect oversize rather than truncating the event.
    narrative = description(raw, limit=MAX_DESCRIPTION + 1)
    if len(narrative) > MAX_DESCRIPTION:
        raise ValueError("bibliocommons_rss_description_oversize")
    return narrative


def _categories(item):
    out = []
    for node in item.findall("category"):
        name = plain(node.text)
        if name and name not in out:
            if len(name) > 100 or len(out) >= 20:
                raise ValueError("bibliocommons_rss_categories_oversize")
            out.append(name)
    return out


def parse_page(payload, *, slug, zone, state, now, horizon):
    """Return (observed items, dated rows, every-item-beyond-horizon)."""
    if not isinstance(payload, (str, bytes)) or len(payload) > 900000:
        raise ValueError("bibliocommons_rss_response_limit")
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if _XML_UNSAFE.search(raw):
        raise ValueError("bibliocommons_rss_unsafe_xml")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("bibliocommons_rss_invalid_xml") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("bibliocommons_rss_invalid_xml")
    items = channel.findall("item")
    if len(items) > PAGE_SIZE:
        raise ValueError("bibliocommons_rss_page_limit")
    rows = []
    beyond = bool(items)
    for item in items:
        url, event_id = _event_identity(item, slug)
        start_local = _field(item, "start_date_local")
        # Date-only listings are real all-day programmes, not a licence to
        # invent a 12 AM event clock. Leave them for explicit all-day support.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_local):
            day = datetime.fromisoformat(start_local).date()
            if day <= horizon.date():
                beyond = False
            continue
        if not LOCAL_START.fullmatch(start_local):
            raise ValueError("bibliocommons_rss_time_invalid")
        begins = timestamp(_field(item, "start_date"))
        if begins is None:
            raise ValueError("bibliocommons_rss_time_missing")
        local = begins.astimezone(ZoneInfo(zone))
        if local.strftime("%Y-%m-%dT%H:%M") != start_local[:16]:
            raise ValueError("bibliocommons_rss_timezone_mismatch")
        if local.date() <= horizon.date():
            beyond = False
        ending = timestamp(_field(item, "end_date"))
        if ending is not None and ending < begins:
            raise ValueError("bibliocommons_rss_end_before_start")
        if begins > horizon or (ending or begins) < now:
            continue
        if _field(item, "is_cancelled") == "true" or _field(item, "is_virtual") == "true":
            continue
        place, street, city, lat, lng = _geo(item.find(EVENT_NS + "location"), state)
        if not street:
            continue
        title = plain(item.findtext("title"))
        if not title:
            raise ValueError("bibliocommons_rss_title_missing")
        narrative = _description(item)
        if not narrative:
            # An unavailable original narrative must not become invented text.
            continue
        classes = _categories(item)
        row = record(title, begins.isoformat(), ending.isoformat() if ending else None,
                     place, street, city, url, event_id, lat=lat, lng=lng, tz=zone,
                     publisher_geo=(lat is not None and lng is not None))
        if row is not None:
            row["description"] = narrative
            row["publisher_categories"] = classes
            # RSS enclosure is NOT publisher image permission. Intentionally
            # leave image_url and image_candidate_url unset for fallback.
            row.pop("image_candidate_url", None)
            row.pop("image_url", None)
            rows.append(row)
    return items, rows, beyond


def collect(source, fetch, *, deadline_at=None, now=None):
    profile = SOURCES.get(source.get("source_key"))
    if profile is None:
        raise ValueError("unregistered_bibliocommons_rss_source")
    slug, zone, state = profile
    canonical = f"https://{GATEWAY}/v2/libraries/{slug}/rss/events"
    if ((source.get("feed_url"), source.get("timezone"), source.get("kind"),
         source.get("platform_adapter")) != (canonical, zone, "rss", "library")):
        raise ValueError("unregistered_bibliocommons_rss_source")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    horizon = current + timedelta(days=HORIZON_DAYS)
    records, seen = {}, {}
    beyond_pages = 0
    for page in range(1, MAX_PAGES + 1):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        url = f"{canonical}?page={page}"
        items, rows, beyond = parse_page(fetch(url, "application/rss+xml"), slug=slug,
                                        zone=zone, state=state, now=current, horizon=horizon)
        if not items:
            return sorted(records.values(), key=lambda r: (r["starts_at"], r["id"]))
        new_identifiers = 0
        for item in items:
            identity, _ = _event_identity(item, slug)
            # Exact content conflict or repeated pages cannot masquerade as
            # a complete source read.
            content = ET.tostring(item, encoding="utf-8")
            if identity in seen and seen[identity] != content:
                raise ValueError("bibliocommons_rss_conflicting_occurrence")
            if identity not in seen:
                new_identifiers += 1
                seen[identity] = content
        if not new_identifiers:
            raise ValueError("bibliocommons_rss_repeated_page")
        for row in rows:
            records[row["id"], row["starts_at"]] = row
        if len(records) > MAX_RECORDS:
            raise ValueError("bibliocommons_rss_record_limit")
        if beyond:
            beyond_pages += 1
        else:
            beyond_pages = 0
        if len(items) < PAGE_SIZE or beyond_pages >= 2:
            return sorted(records.values(), key=lambda r: (r["starts_at"], r["id"]))
    raise ValueError("bibliocommons_rss_pagination_incomplete")
