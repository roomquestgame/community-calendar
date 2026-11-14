"""Public Atlantic County library, chamber and Jewish community calendars.

Native RSS/XML/TEC bodies are preserved in full.  The library's RSS contains
the same body as its event pages (including genuinely blank film descriptions),
not list excerpts.  JFS is the exception: its JSON-LD is an excerpt, so its full
visible event body is fetched.  Paginated/detail collections publish only after
their durable checkpoint is complete; ordinary public religious programs remain
eligible alongside arts, games and educational events.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = "America/New_York"
MARGATE = "margate_city_public_library_nj"
CHAMBER = "greater_atlantic_city_chamber_nj"
FED = "jewish_federation_shore_nj"
JFS = "jewish_family_service_atlantic_nj"
SOURCES = {
    MARGATE: ("https://www.margatelibrary.org/events/rss/feeds?per_page=100", "html", "html"),
    CHAMBER: ("https://business.acchamber.com/api/events", "html", "html"),
    FED: ("https://jewishbytheshore.org/wp-json/tribe/events/v1/events/", "html", "html"),
    JFS: ("https://www.jfsatlantic.org/events/", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = {FED, JFS}
CONTRACT = 1
MAX_CHECKPOINT_BYTES = 900_000
MAX_PAGES = 12
MAX_RECORDS = 600
MIN_FETCH_SECONDS = 18
MAX_DETAILS_PER_CHUNK = 2
EV = "{http://purl.org/rss/1.0/modules/event/}"
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|private (?:event|party)|invite[- ]only|invitation[- ]only|executive committee only|staff[- ]only)\b", re.I)
VIRTUAL = re.compile(r"\b(?:zoom|online only|virtual only)\b", re.I)
STREET = r"\d{1,6}\s+[A-Za-z][^,\n]+"

# Exact venue metadata published by Margate Library and the city, reviewed
# November 14, 2026.  Wednesday Tai Chi expressly moved to Bloom Pavilion;
# Friday's "Inside MCPL" remains in the library.  No source-center GPS is used.
# https://www.margatelibrary.org/tai-chi-17
# https://www.margatelibrary.org/tai-chi-49
# https://www.margate-nj.com/1352/Martin-Bloom-Pavilion
LIBRARY = ("Margate City Public Library", "8100 Atlantic Avenue, Margate, NJ 08402", "Margate")
BLOOM = ("Martin Bloom Pavilion", "101 S Huntington Avenue, Margate, NJ 08402", "Margate")
# These exact named streets are independently present in the Federation's
# current structured venue records.  They supply missing postal fields in JFS,
# never a different venue inferred from an organizer's office.
JFS_VENUES = {
    ("shirat hayam", "700 north swarthmore avenue", "ventnor"): (
        "Shirat Hayam", "700 North Swarthmore Avenue, Ventnor City, NJ 08406", "Ventnor City"),
    ("margate library meeting room", "8100 atlantic avenue", "margate"): LIBRARY,
    ("beth el synagogue", "500 n jerome ave", "margate"): (
        "Beth El Synagogue", "500 N Jerome Avenue, Margate City, NJ 08402", "Margate City"),
}


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc != ALLOWED_HOSTS[key][0]
                or p.username or p.password or p.port not in (None, 443)
                or p.query or p.fragment):
            return False
        pattern = {
            MARGATE: r"/[a-z0-9]+(?:-[a-z0-9]+)*/?",
            CHAMBER: r"/events/details/[a-z0-9]+(?:-[a-z0-9]+)*-[1-9][0-9]*",
            FED: r"/event/[a-z0-9]+(?:-[a-z0-9]+)*/(?:20[0-9]{2}-[0-9]{2}-[0-9]{2}/)?",
            JFS: r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/(?:20[0-9]{2}-[0-9]{2}-[0-9]{2}/)?",
        }[key]
        return re.fullmatch(pattern, p.path) is not None
    except ValueError:
        return False


def _identity(source):
    key = source.get("source_key")
    profile = SOURCES.get(key)
    if not profile or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != profile or source.get("timezone") != ZONE:
        raise ValueError("unregistered_atlantic_library_chamber_source")
    return key


def _body(value):
    if not plain(value):
        return ""
    return narrative(value)


def _held(key, identity, reason):
    log.warning("atlantic_library_chamber_held source=%s id=%s reason=%s", key, identity, reason)


def _within(start, end, now):
    return bool(start and start < now + timedelta(days=60)
                and (end or start + timedelta(hours=3)) > now)


def _row(key, identity, title, url, start, end, venue, body, now, categories=()):
    if not body or not event_url(key, url):
        return None
    if not _within(start, end, now):
        return None
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 *venue, url, identity, tz=ZONE, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                   publisher_categories=list(categories),
                   location_provenance="publisher_venue_street_address_pending_geocode")
    return row


def _rfc_date(value):
    try:
        result = parsedate_to_datetime(value)
        if result.tzinfo is None:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValueError("margate_event_date_invalid") from None


def _margate(raw, now):
    root = ET.fromstring(raw)
    if root.tag != "rss" or root.findtext("channel/title") != "Upcoming Events RSS Feed":
        raise ValueError("margate_feed_changed")
    items = root.findall("channel/item")
    if len(items) > 1000:
        raise ValueError("source_record_limit")
    closed = set()
    for item in items:
        if re.search(r"\blibrary closed\b", plain(item.findtext("title")), re.I):
            begins = _rfc_date(item.findtext("pubDate")).astimezone(ZoneInfo(ZONE))
            finishes = _rfc_date(item.findtext(EV + "endDate")).astimezone(ZoneInfo(ZONE))
            start, end = begins.date(), finishes.date()
            # A later midnight is an exclusive boundary; a zero-length dated
            # closure (as Christmas is published) denotes that single day.
            if finishes > begins and finishes.time().isoformat() == "00:00:00":
                end -= timedelta(days=1)
            if end < start or end - start > timedelta(days=14):
                raise ValueError("margate_closure_range_invalid")
            closed.update(start + timedelta(days=n) for n in range((end - start).days + 1))
    rows = []
    for item in items:
        title, url = plain(item.findtext("title")), item.findtext("link")
        start, end = _rfc_date(item.findtext("pubDate")), _rfc_date(item.findtext(EV + "endDate"))
        if not _within(start, end, now):
            continue
        reason = None
        body = _body(item.findtext("description"))
        venue = LIBRARY
        if "inside the Bloom Pavilion" in body:
            venue = BLOOM
        label = plain(item.findtext(EV + "location"))
        # Stacks omits ev:location for some entries whose body explicitly
        # identifies a library room.  That text supplies the venue association.
        if label != LIBRARY[0] and not (not label and re.search(r"\b(?:at|in) the (?:[A-Za-z]+\s+)?library\b", body, re.I)):
            reason = "unreviewed_venue"
        elif re.search(r"\b(?:closed|time tbd|time to be determined)\b", title, re.I):
            reason = "closure_or_unresolved_clock"
        elif start.astimezone(ZoneInfo(ZONE)).date() in closed and venue == LIBRARY:
            reason = "library_closure_exception"
        elif end <= start or end > start + timedelta(hours=16):
            reason = "publisher_schedule_conflict"
        elif not body:
            reason = "publisher_description_missing"
        elif NONPUBLIC.search(title + " " + body):
            reason = "nonpublic_or_cancelled"
        if reason:
            _held(MARGATE, url, reason)
            continue
        row = _row(MARGATE, sha256(urlsplit(url).path.encode()).hexdigest(), title, url,
                   start, end, venue, body, now,
                   [plain(c.text) for c in item.findall("category") if plain(c.text)])
        if row:
            rows.append(row)
    return rows


def _address(text):
    # Use only the first complete event-local postal street.  Parking notes
    # after that address never become part of its city or geocoding query.
    pattern = r"(" + STREET + r")(?:,\s*(Suite|Ste|Unit)\s*([\w-]+))?,\s*([A-Za-z .'-]+),\s*(?:NJ|New Jersey)\s+(\d{5}(?:-\d{4})?)\b"
    text = re.sub(r"<br\s*/?>", ", ", str(text or ""), flags=re.I)
    match = re.search(pattern, plain(text))
    if not match:
        return None
    street, unit, number, city, postal = match.groups()
    if unit:
        street += " " + unit + " " + number
    return f"{street}, {city.strip()}, NJ {postal}", city.strip()


def _weekday_conflict(body, start):
    local = start.astimezone(ZoneInfo(ZONE))
    pattern = r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(" + local.strftime("%B") + r")\s+0?" + str(local.day) + r"\b"
    return any(m.group(1).casefold() != local.strftime("%A").casefold() for m in re.finditer(pattern, body, re.I))


def _chamber(raw, now):
    root = ET.fromstring(raw)
    if root.tag != "ArrayOfEventDisplay" or len(root) > 1000:
        raise ValueError("chamber_payload_changed")
    rows = []
    for item in root:
        if item.tag != "EventDisplay" or item.findtext("CCID") != "2391":
            raise ValueError("chamber_identity_changed")
        if item.findtext("Status") != "APPROVED" or "Public" not in (item.findtext("VisibilityFlags") or "").split():
            continue
        identity, slug = item.findtext("EventID"), item.findtext("Slug")
        if not re.fullmatch(r"[1-9][0-9]*", identity or "") or not re.fullmatch(r"[a-z0-9-]+", slug or ""):
            raise ValueError("chamber_event_identity_changed")
        url = "https://business.acchamber.com/events/details/" + slug + ("" if slug.endswith("-" + identity) else "-" + identity)
        title = plain(item.findtext("Name"))
        start, end = timestamp(item.findtext("StartDate"), ZONE), timestamp(item.findtext("EndDate"), ZONE)
        if not _within(start, end, now):
            continue
        body = _body(item.findtext("Description"))
        location = plain(item.findtext("LocationDesc"))
        candidate = _address(item.findtext("LocationDesc")) or _address(body)
        reason = None
        if item.findtext("IsAllDayEvent") != "false" or not start or not end or end <= start or end > start + timedelta(hours=16):
            reason = "publisher_schedule_unresolved"
        elif NONPUBLIC.search(title + " " + body) or VIRTUAL.search(location):
            reason = "nonpublic_or_virtual"
        elif _weekday_conflict(body, start):
            reason = "publisher_schedule_conflict"
        elif not body:
            reason = "publisher_description_missing"
        elif not candidate:
            reason = "publisher_venue_unresolved"
        if reason:
            _held(CHAMBER, identity, reason)
            continue
        address, city = candidate
        venue = re.split(r"\b\d{1,6}\s", location, maxsplit=1)[0].strip(" ,") if location else ""
        if not venue:
            # The only fallback is the name immediately preceding this exact
            # street in the event's own explicit Location sentence.
            match = re.search(r"\bLocation:\s*([^,\n]+),\s*" + re.escape(address.split(",", 1)[0]), body, re.I)
            venue = match.group(1).strip() if match else address
        row = _row(CHAMBER, identity, title, url, start, end, (venue, address, city), body, now)
        if row:
            rows.append(row)
    return rows


def _fed_item(item, now):
    identity = str(item.get("id", ""))
    if not re.fullmatch(r"[1-9][0-9]*", identity) or not event_url(FED, item.get("url")):
        raise ValueError("federation_event_identity_changed")
    title = plain(item.get("title"))
    body = _body(item.get("description"))
    if item.get("status") != "publish" or any(item.get(f) in (True, 1, "1", "true") for f in ("all_day", "is_virtual", "hide_from_listings")) or NONPUBLIC.search(title + " " + body):
        return None, "nonpublic_virtual_or_cancelled"
    if item.get("timezone") != ZONE:
        raise ValueError("federation_timezone_changed")
    start, end = timestamp(item.get("start_date"), ZONE), timestamp(item.get("end_date"), ZONE)
    if start != timestamp(item.get("utc_start_date"), "UTC") or end != timestamp(item.get("utc_end_date"), "UTC"):
        return None, "publisher_schedule_conflict"
    if not _within(start, end, now):
        return None, "outside_window"
    if end and (end < start or end > start + timedelta(hours=16)):
        return None, "publisher_schedule_conflict"
    if end == start:
        end = None
    if not body:
        return None, "publisher_description_missing"
    venue = item.get("venue")
    if not isinstance(venue, dict):
        return None, "publisher_venue_unresolved"
    name = plain(venue.get("venue"))
    if VIRTUAL.search(name) and not venue.get("address"):
        return None, "virtual_only"
    street, city, state, postal = [plain(x) for x in (venue.get("address"), venue.get("city"),
        venue.get("state") or venue.get("province") or venue.get("stateprovince"), venue.get("zip"))]
    if not re.fullmatch(STREET, street) or state not in ("NJ", "New Jersey") or not city or not re.fullmatch(r"\d{5}(?:-\d{4})?", postal):
        return None, "publisher_venue_unresolved"
    if "board meeting" in title.casefold() or "board retreat" in title.casefold():
        # Internal board calendar entries are not publicly advertised programs.
        # A future explicitly open meeting remains eligible.
        if not re.search(r"\b(?:open to the public|public meeting|open to the community)\b", body, re.I):
            return None, "board_access_unverified"
    row = _row(FED, identity, title, item["url"], start, end,
               (name, f"{street}, {city}, NJ {postal}", city), body, now,
               [plain(x.get("name")) for x in item.get("categories", []) if isinstance(x, dict) and plain(x.get("name"))])
    return row, None if row else "outside_window"


def _events_json(raw):
    soup = BeautifulSoup(raw, "html.parser")
    result = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except ValueError:
            continue
        values = payload if isinstance(payload, list) else [payload]
        result.extend(v for v in values if isinstance(v, dict) and v.get("@type") == "Event")
    return soup, result


def _jfs_detail(url, card, raw, now):
    soup, events = _events_json(raw)
    candidates = [e for e in events if e.get("url") == url]
    if len(candidates) != 1:
        raise ValueError("jfs_detail_identity_changed")
    item = candidates[0]
    if any(item.get(k) != card.get(k) for k in ("name", "startDate", "endDate")):
        raise ValueError("jfs_detail_schedule_changed")
    section = soup.select_one(".tribe-events-single-event-description")
    if section is None:
        raise ValueError("jfs_description_container_changed")
    body = _body(str(section))
    if not body or NONPUBLIC.search(plain(item.get("name")) + " " + body):
        return None, "publisher_description_missing_or_nonpublic"
    location = item.get("location") or {}
    if not isinstance(location, dict):
        return None, "publisher_venue_unresolved"
    address = location.get("address") or {}
    if not isinstance(address, dict):
        return None, "publisher_venue_unresolved"
    name = plain(location.get("name"))
    street, city = plain(address.get("streetAddress")), plain(address.get("addressLocality"))
    normalized_street = re.sub(r"\bN\.?\s+", "North ", street, flags=re.I).casefold()
    venue = JFS_VENUES.get((name.casefold(), normalized_street, city.casefold()))
    if not venue and re.search(r"\bShirat Hayam,\s*700 North Swarthmore Avenue,\s*Ventnor\b", body):
        venue = JFS_VENUES[("shirat hayam", "700 north swarthmore avenue", "ventnor")]
    if not venue:
        complete = _address(", ".join((street, city, plain(address.get("addressRegion")) + " " + plain(address.get("postalCode")))))
        venue = (name, *complete) if complete else None
    if not venue:
        return None, "publisher_venue_unresolved"
    start, end = timestamp(item.get("startDate")), timestamp(item.get("endDate"))
    row = _row(JFS, sha256(urlsplit(url).path.encode()).hexdigest(), item.get("name"), url,
               start, end, venue, body, now)
    return row, None if row else "outside_window"


def _validate_checkpoint(value, key, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != 1
            or type(value.get("contract")) is not int or value.get("contract") != CONTRACT
            or value.get("source_key") != key or len(json.dumps(value).encode()) > MAX_CHECKPOINT_BYTES
            or type(value.get("cursor")) is not int or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_RECORDS
            or not isinstance(value.get("events"), list) or len(value["events"]) > 201
            or not isinstance(value.get("diagnostics"), list)
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("manifest_hash")))):
        raise ValueError("atlantic_library_checkpoint_invalid")
    try:
        started = datetime.fromisoformat(value["started_at"])
        anchor = date.fromisoformat(value["window_start"])
        if started.tzinfo is None or anchor != started.astimezone(ZoneInfo(ZONE)).date():
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("atlantic_library_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=4) or now.astimezone(ZoneInfo(ZONE)).date() != anchor:
        return None
    identities = set()
    for row in value["events"]:
        if (not isinstance(row, dict) or not event_url(key, row.get("event_url"))
                or not row.get("description") or len(row["description"]) > 12000
                or not row.get("venue_name") or not _address(row.get("venue_address"))
                or row.get("lat") is not None or row.get("lng") is not None
                or not timestamp(row.get("starts_at"))
                or (key == FED and not re.fullmatch(r"[1-9][0-9]*", str(row.get("id"))))
                or (key == JFS and row.get("id") != sha256(urlsplit(row["event_url"]).path.encode()).hexdigest())):
            raise ValueError("atlantic_library_checkpoint_invalid")
        identity = (row.get("id"), row["starts_at"])
        if identity in identities:
            raise ValueError("atlantic_library_checkpoint_invalid")
        identities.add(identity)
    for diagnostic in value["diagnostics"]:
        if (not isinstance(diagnostic, dict) or not event_url(key, diagnostic.get("event_url"))
                or diagnostic.get("disposition") != "held" or not isinstance(diagnostic.get("reason"), str)
                or not diagnostic["reason"]):
            raise ValueError("atlantic_library_checkpoint_invalid")
    if key == FED:
        seen = value.get("seen")
        page_hashes = value.get("page_hashes")
        total = value.get("total_items")
        pages = value.get("data_pages")
        if (not isinstance(seen, list) or not isinstance(page_hashes, list)
                or type(pages) is not int or not 0 <= pages <= MAX_PAGES
                or value["manifest_count"] != 2 * pages
                or len(page_hashes) != min(value["cursor"], pages)
                or any(not re.fullmatch(r"[a-f0-9]{64}", str(h)) for h in page_hashes)
                or type(total) is not int or not 0 <= total <= MAX_RECORDS
                or pages != (total + 49) // 50
                or len(seen) != min(min(value["cursor"], pages) * 50, total)
                or len(value["events"]) + len(value["diagnostics"]) != len(seen)
                or any(not isinstance(i, dict) or not event_url(key, i.get("event_url"))
                       or not re.fullmatch(r"[1-9][0-9]*", str(i.get("id"))) for i in seen)
                or len({(i["id"], i["event_url"]) for i in seen}) != len(seen)):
            raise ValueError("atlantic_library_checkpoint_invalid")
        accepted = {(i["id"], i["event_url"], i["starts_at"]) for i in seen}
        if any((r["id"], r["event_url"], r["starts_at"]) not in accepted for r in value["events"]):
            raise ValueError("atlantic_library_checkpoint_invalid")
    elif (not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
          or len(set(value["queue"])) != len(value["queue"])
          or any(not event_url(key, url) for url in value["queue"])):
        raise ValueError("atlantic_library_checkpoint_invalid")
    else:
        completed = [r["event_url"] for r in value["events"]] + [d["event_url"] for d in value["diagnostics"]]
        if len(completed) != value["cursor"] or set(completed) != set(value["queue"][:value["cursor"]]):
            raise ValueError("atlantic_library_checkpoint_invalid")
    return deepcopy(value)


def _state(key, now, count, digest):
    return {"version": 1, "contract": CONTRACT, "source_key": key,
            "started_at": now.isoformat(), "window_start": now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
            "cursor": 0, "manifest_count": count, "manifest_hash": digest,
            "events": [], "diagnostics": []}


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    key = _identity(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError("atlantic_library_checkpoint_source")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("atlantic_library_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _validate_checkpoint(checkpoint, key, current)
    if key == FED and state is not None and state["cursor"] == state["manifest_count"]:
        # The completed checkpoint is durable before staging. A staging or RPC
        # retry must reuse it, not request nonexistent page data_pages + 1.
        rows = sorted(state["events"], key=lambda r: (r["starts_at"], r["id"]))
        return {"complete": True, "events": deepcopy(rows), "checkpoint": state}
    anchor = date.fromisoformat(state["window_start"]) if state else current.astimezone(ZoneInfo(ZONE)).date()
    if deadline_at is not None and monotonic() + MIN_FETCH_SECONDS >= deadline_at:
        raise ValueError("collection_deadline")
    if key == FED:
        verifying = bool(state and state["data_pages"] and state["cursor"] >= state["data_pages"])
        page = state["cursor"] - state["data_pages"] + 1 if verifying else (state["cursor"] + 1 if state else 1)
        params = {"per_page": 50, "start_date": str(anchor), "end_date": str(anchor + timedelta(days=60)), "page": page}
        payload = json.loads(fetch(SOURCES[FED][0] + "?" + urlencode(params), "application/json"))
        if not isinstance(payload, dict):
            raise ValueError("federation_payload_invalid")
        items, pages, total = payload.get("events"), payload.get("total_pages"), payload.get("total")
        if (not isinstance(items, list) or len(items) > 50 or type(pages) is not int
                or not 0 <= pages <= MAX_PAGES or type(total) is not int or not 0 <= total <= MAX_RECORDS
                or pages != (total + 49) // 50 or page > max(1, pages)
                or len(items) != min(50, max(0, total - (page - 1) * 50))):
            raise ValueError("federation_pagination_invalid")
        response = urlsplit(payload.get("rest_url", ""))
        if (response.scheme != "https" or response.netloc != ALLOWED_HOSTS[FED][0]
                or response.path.rstrip("/") != urlsplit(SOURCES[FED][0]).path.rstrip("/")
                or parse_qs(response.query).get("page") != [str(page)]):
            raise ValueError("federation_pagination_identity_changed")
        digest = sha256(json.dumps({"window_start": str(anchor), "pages": pages, "total": total}, sort_keys=True).encode()).hexdigest()
        changed = bool(state and state["manifest_hash"] != digest)
        page_hash = sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
        if verifying and not changed:
            changed = state["page_hashes"][page - 1] != page_hash
        if changed:
            # A stable total is not sufficient: descriptions, venues or order
            # can change while a paginated API is read.  Discard that snapshot
            # and restart from page one on the next bounded worker invocation.
            state = {**_state(key, current, 2 * pages, digest), "total_items": total,
                     "data_pages": pages, "seen": [], "page_hashes": []}
            return {"complete": False, "events": [], "checkpoint": state}
        if not state:
            state = {**_state(key, current, 2 * pages, digest), "total_items": total,
                     "data_pages": pages, "seen": [], "page_hashes": []}
        if verifying:
            state["cursor"] += 1
            complete = state["cursor"] == state["manifest_count"]
            rows = sorted(state["events"], key=lambda r: (r["starts_at"], r["id"])) if complete else []
            return {"complete": complete, "events": deepcopy(rows), "checkpoint": state}
        seen = {(row["id"], row["starts_at"]) for row in state["events"]}
        all_seen = {(i["id"], i["event_url"]) for i in state["seen"]}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("federation_payload_invalid")
            row, reason = _fed_item(item, current)
            identity_url = (str(item["id"]), item["url"])
            if identity_url in all_seen:
                raise ValueError("federation_pagination_duplicate")
            all_seen.add(identity_url)
            state["seen"].append({"id": str(item["id"]), "event_url": item["url"],
                                  "starts_at": row["starts_at"] if row else None})
            if row:
                identity = (row["id"], row["starts_at"])
                if identity in seen:
                    raise ValueError("federation_pagination_duplicate")
                seen.add(identity)
                state["events"].append(row)
            else:
                state["diagnostics"].append({"event_url": item.get("url"), "disposition": "held", "reason": reason})
        if pages:
            state["page_hashes"].append(page_hash)
        state["cursor"] = page if pages else 0
    else:
        soup, items = _events_json(fetch(SOURCES[JFS][0], "text/html"))
        if not soup.select_one(".tribe-events") and not soup.select_one(".tribe-events-view"):
            raise ValueError("jfs_calendar_changed")
        manifest = {}
        for item in items:
            url = item.get("url")
            if not event_url(JFS, url):
                raise ValueError("jfs_event_identity_changed")
            start, end = timestamp(item.get("startDate")), timestamp(item.get("endDate"))
            location = item.get("location") or {}
            if not _within(start, end, current) or VIRTUAL.search(plain(location.get("name"))):
                continue
            manifest[url] = item
        queue = sorted(manifest)
        if len(queue) > 80:
            raise ValueError("source_record_limit")
        digest = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        if not state or state["manifest_hash"] != digest:
            state = {**_state(key, current, len(queue), digest), "queue": queue}
        previous = state["cursor"]
        limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
        while state["cursor"] < len(queue) and state["cursor"] - previous < limit:
            if deadline_at is not None and monotonic() + MIN_FETCH_SECONDS >= deadline_at:
                break
            url = queue[state["cursor"]]
            row, reason = _jfs_detail(url, manifest[url], fetch(url, "text/html"), current)
            if row:
                state["events"].append(row)
            else:
                state["diagnostics"].append({"event_url": url, "disposition": "held", "reason": reason})
            state["cursor"] += 1
        if state["cursor"] == previous < len(queue):
            raise ValueError("collection_deadline")
    if len(state["events"]) > 201 or len(json.dumps(state).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("atlantic_library_checkpoint_size_limit")
    complete = state["cursor"] == state["manifest_count"]
    events = sorted(state["events"], key=lambda r: (r["starts_at"], r["id"])) if complete else []
    return {"complete": complete, "events": deepcopy(events), "checkpoint": state}


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _identity(source)
    current = now or datetime.now(timezone.utc)
    if key in CHECKPOINT_KEYS:
        result = collect_chunk(source, fetch, deadline_at=deadline_at, now=current)
        if not result["complete"]:
            raise ValueError("publisher_checkpoint_required")
        return result["events"]
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    raw = fetch(SOURCES[key][0], "application/xml")
    rows = _margate(raw, current) if key == MARGATE else _chamber(raw, current)
    unique = {}
    for row in rows:
        identity = (row["id"], row["starts_at"])
        if identity in unique and unique[identity] != row:
            raise ValueError("conflicting_event_occurrence")
        unique[identity] = row
    return sorted(unique.values(), key=lambda r: (r["starts_at"], r["id"]))
