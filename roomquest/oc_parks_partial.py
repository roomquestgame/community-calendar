"""OC Parks: truthful, bounded, *partial* Drupal FullCalendar event collector.

The public calendar exposes at most 500 event IDs; that is not full coverage.
We review no more than 20 nearest future detail pages per claim. We only emit
events whose official detail page confirms the exact local start/end, complete
publisher narrative and event-owned numbered street. A known shared Irvine
Ranch administrative address is NOT an event start point, so those records are
held. Publisher photos are intentionally never imported without media rights.
No source registration, geocoding RPC, timer, or writer is created here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

SOURCE_KEY = "oc_parks_verified_partial_ca"
HOST = "parks.oc.gov"
CALENDAR = "https://parks.oc.gov/events"
ZONE = "America/Los_Angeles"
HORIZON_DAYS = 21
CALENDAR_MAX_ITEMS = 500
MAX_DETAIL_FETCHES = 20
MAX_RETURNED_EVENTS = 14
DESCRIPTION_LIMIT = 2000   # Shared current external-event writer constraint
URL_RE = re.compile(r"/events/([a-z0-9-]{3,130})")
START_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
ADDRESS_NUMBER_RE = re.compile(r"^\d{1,6}[A-Za-z]?\s+\S")
POSTAL_RE = re.compile(r"9\d{4}")
DETAIL_TIME = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+"
    r"(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)\s*(PST|PDT)$", re.I)
EXCLUDED_AREA_ADDRESS = "13333 Black Star Canyon Rd"
CANCELLATION_TITLE = re.compile(
    r"^\s*(?:(?:cancelled|canceled|postponed|rescheduled)\b|"
    r"(?:this|the)\s+(?:event|program)\s+(?:has\s+been|is)\s+(?:cancelled|canceled)\b)", re.I)
# Reviewed direct OC Parks location-node GPS (via 2026-10-11 public Mapsee
# configuration); keys must match ALL official event-detail address fields.
# Never use generic Black Star Canyon gateway or Mapsee's distant OSM centroids.
REVIEWED_PARK_PINS = [
    ("28373 Alicia Parkway", "Laguna Niguel", "92677", "Aliso and Wood Canyons Wilderness Park", 33.551329, -117.720442),
    ("4442 Carbon Canyon Road", "Brea", "92823", "Carbon Canyon Regional Park", 33.921791, -117.837496),
    ("25151 Serrano Road", "Lake Forest", "92630", "Heritage Hill Historical Park", 33.646734, -117.689346),
    ("1 Irvine Park Rd.", "Orange", "92869", "Irvine Regional Park", 33.796935, -117.753463),
    ("16801 Euclid St.", "Fountain Valley", "92708", "Mile Square Regional Park", 33.727486, -117.938584),
    ("8548 E. Canyon View Ave.", "Orange", "92869", "Peters Canyon Regional Park", 33.783909, -117.762107),
    ("8800 Rosecrans Ave.", "Buena Park", "90621", "Ralph B. Clark Regional Park", 33.893138, -117.977892),
    ("33401 Ortega Hwy.", "San Juan Capistrano", "92675", "Ronald W. Caspers Wilderness Park", 33.533510, -117.551625),
    ("33333 S. Pacific Coast Hwy.", "Dana Point", "92629", "Salt Creek Beach Park", 33.480469, -117.720117),
    ("2145 N. Windes Drive", "Orange", "92869", "Santiago Oaks Regional Park", 33.816145, -117.779097),
    ("2301 University Drive", "Newport Beach", "92660", "Upper Newport Bay Nature Preserve", 33.653427, -117.885280),
    ("7600 E. La Palma Ave.", "Anaheim", "92807", "Yorba Regional Park", 33.869170, -117.766250),
]


def _norm(value):
    return re.sub(r"[^a-z0-9]", "", plain(value).casefold())


def _park_pin(street, city, postal):
    matches = [v for v in REVIEWED_PARK_PINS
               if (_norm(v[0]), _norm(v[1]), v[2]) == (_norm(street), _norm(city), postal)]
    return matches[0] if len(matches) == 1 else None


def _date(value):
    if not isinstance(value, str) or not START_RE.fullmatch(value):
        raise ValueError("oc_parks_calendar_time_invalid")
    result = timestamp(value, ZONE)
    return result.astimezone(ZoneInfo(ZONE))


def parse_calendar(html, *, now=None):
    if not isinstance(html, str) or len(html) > 2_000_000:
        raise ValueError("oc_parks_calendar_body_limit")
    settings = BeautifulSoup(html, "html.parser").select_one(
        'script[data-drupal-selector="drupal-settings-json"]')
    if settings is None:
        raise ValueError("oc_parks_calendar_settings_missing")
    try:
        data = json.loads(settings.string or "")
        fc = data["fullCalendarView"]
        if not isinstance(fc, list) or len(fc) != 1:
            raise ValueError
        opts = json.loads(fc[0]["calendar_options"])
        events = opts["events"]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("oc_parks_calendar_schema_invalid") from exc
    if not isinstance(events, list) or not 1 <= len(events) <= CALENDAR_MAX_ITEMS:
        raise ValueError("oc_parks_calendar_count_invalid")
    reference = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE))
    horizon = reference + timedelta(days=HORIZON_DAYS)
    selected = {}
    for e in events:
        if not isinstance(e, dict):
            raise ValueError("oc_parks_calendar_entry_invalid")
        url = e.get("url")
        if not isinstance(url, str) or not URL_RE.fullmatch(url):
            raise ValueError("oc_parks_calendar_url_invalid")
        eid = e.get("eid")
        title = plain(e.get("title"))
        if CANCELLATION_TITLE.search(title):
            # A cancelled row never becomes a newly scheduled event. Source
            # release additionally requires a reviewed cancellation tombstone
            # path for already-published occurrences.
            continue
        if not re.fullmatch(r"[1-9]\d{0,10}", str(eid or "")) or not title:
            raise ValueError("oc_parks_calendar_identity_invalid")
        start, end = _date(e.get("start")), _date(e.get("end"))
        if end <= start:
            # Unsupported/zero length does not turn into an invented duration.
            continue
        if end < reference or start > horizon:
            continue
        if url in selected:
            previous = selected[url]
            if previous["eid"] != str(eid) or previous["starts_at"] != start:
                raise ValueError("oc_parks_calendar_identity_conflict")
            continue
        selected[url] = {"eid": str(eid), "title": title, "url": url,
                         "starts_at": start, "ends_at": end}
    return sorted(selected.values(), key=lambda x: (x["starts_at"], x["eid"]))[:MAX_DETAIL_FETCHES]


def cancellation_records(calendar_html, *, now=None):
    """Only explicit publisher cancellation/postponement titles make tombstones.

    Missing from a 500-capped listing never implies a cancellation. Tombstones
    never create events: the database matches an existing exact URL, provider ID,
    occurrence timestamp and source before changing its status.
    """
    settings = BeautifulSoup(calendar_html, "html.parser").select_one(
        'script[data-drupal-selector="drupal-settings-json"]')
    if settings is None:
        raise ValueError("oc_parks_calendar_settings_missing")
    try:
        data = json.loads(settings.string or "")
        fc = data["fullCalendarView"]
        if not isinstance(fc, list) or len(fc) != 1:
            raise ValueError
        entries = json.loads(fc[0]["calendar_options"])["events"]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("oc_parks_calendar_schema_invalid") from exc
    if not isinstance(entries, list) or not 1 <= len(entries) <= CALENDAR_MAX_ITEMS:
        raise ValueError("oc_parks_calendar_count_invalid")
    reference = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE))
    horizon = reference + timedelta(days=HORIZON_DAYS)
    rows, seen = [], set()
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError("oc_parks_calendar_entry_invalid")
        title = plain(e.get("title"))
        match = CANCELLATION_TITLE.search(title)
        if not match:
            continue
        url, eid = e.get("url"), str(e.get("eid") or "")
        if (not isinstance(url, str) or not URL_RE.fullmatch(url)
                or not re.fullmatch(r"[1-9]\d{0,10}", eid)):
            raise ValueError("oc_parks_cancellation_identity_invalid")
        start, end = _date(e.get("start")), _date(e.get("end"))
        if end <= start or end < reference - timedelta(days=1) or start > horizon:
            continue
        identity = (eid, url, start)
        if identity in seen:
            raise ValueError("oc_parks_cancellation_duplicate")
        seen.add(identity)
        status = "postponed" if re.match(r"^\s*(?:postponed|rescheduled)\b", title, re.I) else "cancelled"
        rows.append({
            "id": eid, "title": title, "starts_at": start.isoformat(),
            "ends_at": end.isoformat(), "event_url": "https://" + HOST + url,
            "venue_name": "", "venue_address": "", "venue_city": "",
            "lat": None, "lng": None, "category": "",
            "timezone": ZONE, "publisher_status": status,
            "status_evidence": "calendar_title", "status_evidence_url": CALENDAR,
            "description": "", "publisher_categories": [],
        })
        if len(rows) > 50:
            raise ValueError("oc_parks_cancellation_batch_limit")
    return rows


def _detail_cancellation(item, *, status):
    """A changed status on the exact publisher detail URL, not a guessed title."""
    if status not in ("cancelled", "postponed"):
        raise ValueError("oc_parks_detail_status_invalid")
    return {
        "id": item["eid"], "title": item["title"],
        "starts_at": item["starts_at"].isoformat(),
        "ends_at": item["ends_at"].isoformat(),
        "event_url": "https://" + HOST + item["url"],
        "venue_name": "", "venue_address": "", "venue_city": "",
        "lat": None, "lng": None, "category": "",
        "timezone": ZONE, "publisher_status": status,
        "status_evidence": "detail_page",
        "status_evidence_url": "https://" + HOST + item["url"],
        "description": "", "publisher_categories": [],
    }



def _detail_date(text):
    match = DETAIL_TIME.fullmatch(" ".join((text or "").split()))
    if match is None:
        raise ValueError("oc_parks_detail_time_unverified")
    month, day, year, first, last, abbr = match.groups()
    try:
        prefix = f"{month} {int(day)} {year} "
        start = datetime.strptime(prefix + first.upper().replace(" ", ""), "%B %d %Y %I:%M%p")
        end = datetime.strptime(prefix + last.upper().replace(" ", ""), "%B %d %Y %I:%M%p")
    except ValueError as exc:
        raise ValueError("oc_parks_detail_time_unverified") from exc
    zone = ZoneInfo(ZONE)
    begin, finish = start.replace(tzinfo=zone), end.replace(tzinfo=zone)
    if begin.strftime("%Z").upper() != abbr.upper() or end <= start:
        raise ValueError("oc_parks_detail_time_unverified")
    return begin, finish


def parse_detail(entry, html):
    if not isinstance(html, str) or len(html) > 900000:
        raise ValueError("oc_parks_detail_body_limit")
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.title
    page_title = plain(title_node.get_text(" ", strip=True)) if title_node else ""
    if CANCELLATION_TITLE.search(page_title):
        raise ValueError("oc_parks_detail_postponed" if re.match(r"^\s*(postponed|rescheduled)\b", page_title, re.I)
                         else "oc_parks_detail_cancelled")
    if not page_title.endswith(" | OC Parks") or _norm(page_title[:-11]) != _norm(entry["title"]):
        raise ValueError("oc_parks_detail_title_mismatch")
    timing = soup.select_one(".info-date-time__body")
    if timing is None:
        raise ValueError("oc_parks_detail_time_unverified")
    start, end = _detail_date(timing.get_text(" ", strip=True))
    if start != entry["starts_at"] or end != entry["ends_at"]:
        raise ValueError("oc_parks_detail_schedule_mismatch")
    address = soup.select_one(".info-location__body p.address")
    if address is None:
        raise ValueError("oc_parks_detail_street_missing")
    def span(css):
        el = address.select_one(css)
        return plain(el.get_text(" ", strip=True)) if el else ""
    street, city, state, postal = (
        span(".address-line1"), span(".locality"),
        span(".administrative-area"), span(".postal-code"))
    if (state != "CA" or not city or not ADDRESS_NUMBER_RE.match(street)
            or not POSTAL_RE.fullmatch(postal) or "," in street):
        raise ValueError("oc_parks_detail_street_missing")
    # Black Star Canyon Rd is explicitly a shared administrative address for
    # programmes that may depart 2.6–11.2 km away. No false gate pin.
    if _norm(street) == _norm(EXCLUDED_AREA_ADDRESS) and _norm(city) == "silverado":
        raise ValueError("oc_parks_detail_shared_area_address")
    body = soup.select_one("#wysiwyg-body-node-na-0")
    if body is None:
        raise ValueError("oc_parks_detail_description_missing")
    body = BeautifulSoup(str(body), "html.parser")
    for hidden in body.select("span.visually-hidden"):
        hidden.decompose()
    text = description(str(body), limit=DESCRIPTION_LIMIT + 1)
    if len(text) > DESCRIPTION_LIMIT:
        raise ValueError("oc_parks_description_requires_long_text_review")
    if CANCELLATION_TITLE.search(text):
        raise ValueError("oc_parks_detail_postponed" if re.match(r"^\s*(postponed|rescheduled)\b", text, re.I)
                         else "oc_parks_detail_cancelled")
    if not text:
        raise ValueError("oc_parks_detail_description_missing")
    pin = _park_pin(street, city, postal)
    name = pin[3] if pin else f"{street}, {city}"
    full_address = f"{street}, {city}, CA {postal}"
    return record(entry["title"], start.isoformat(), end.isoformat(),
                  name, full_address, city, "https://" + HOST + entry["url"],
                  entry["eid"], lat=pin[4] if pin else None,
                  lng=pin[5] if pin else None,
                  tz=ZONE, publisher_geo=pin is not None), text


def collect(source, fetch, *, deadline_at=None, now=None):
    expected = (SOURCE_KEY, CALENDAR, "html", "html", ZONE)
    if tuple(source.get(k) for k in
             ("source_key", "feed_url", "kind", "platform_adapter", "timezone")) != expected:
        raise ValueError("unregistered_oc_parks_source")
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    calendar = fetch(CALENDAR, "text/html")
    selected = parse_calendar(calendar, now=now)
    canceled = cancellation_records(calendar, now=now)
    records = []
    seen = set()
    for item in selected:
        if len(records) >= MAX_RETURNED_EVENTS:
            break
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        body = fetch("https://" + HOST + item["url"], "text/html")
        try:
            row, narrative = parse_detail(item, body)
        except ValueError as exc:
            if str(exc) in ("oc_parks_detail_cancelled", "oc_parks_detail_postponed"):
                canceled.append(_detail_cancellation(
                    item, status="postponed" if str(exc) == "oc_parks_detail_postponed" else "cancelled"))
                continue
            if str(exc) in {
                "oc_parks_detail_street_missing",
                "oc_parks_detail_shared_area_address",
                "oc_parks_detail_description_missing",
                "oc_parks_description_requires_long_text_review",
                "oc_parks_detail_time_unverified",
                "oc_parks_detail_schedule_mismatch",
                "oc_parks_detail_title_mismatch",
                "oc_parks_detail_cancelled",
            }:
                continue   # Explicit partial admission, not a full publisher feed.
            raise
        if row is not None:
            if row["id"] in seen:
                raise ValueError("oc_parks_duplicate_event_id")
            seen.add(row["id"])
            row["description"] = narrative
            # The shared record normalizer returns an absolute UTC start but
            # omits the original publisher timezone. Staging requires BOTH.
            row["timezone"] = ZONE
            row["publisher_status"] = "scheduled"
            # No unlicensed photographs, image URLs, organizer HQ coordinates,
            # invented category overlays, or invented attendance guarantees.
            row.pop("image_url", None)
            row.pop("image_candidate_url", None)
            records.append(row)
    # Every negative status is an explicit publisher statement. Never treat
    # absent entries in the 500-capped calendar as cancelled.
    merged = { (r["id"], r["starts_at"]): r for r in records }
    for row in canceled:
        key = (row["id"], row["starts_at"])
        if key in merged and merged[key].get("publisher_status") == "scheduled":
            raise ValueError("oc_parks_cancellation_positive_conflict")
        merged[key] = row
    return sorted(merged.values(), key=lambda r: (r["starts_at"], r["id"]))
