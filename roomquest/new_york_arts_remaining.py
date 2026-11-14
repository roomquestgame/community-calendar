"""Remaining NYC public programs: scoped repairs and complete event detail pages.

Commonpoint's public Event category is separate from thousands of enrolled Class
sessions. NYU's documented LiveWhale JSON API preserves UTF-8 and full event
descriptions without changing the shared transport's strict encoding checks.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = "America/New_York"
COMMONPOINT = "municipal_mapsee_8ada9fb25b90788ab8a89a73"
NYU = "municipal_mapsee_59cd82df6a4f146d4b15acec"
BRONX = "bronx_museum_ny"
GREENLIGHT = "greenlight_bookstore_ny"
SOURCES = {
    COMMONPOINT: ("https://www.commonpoint.org", "html", "html"),
    NYU: ("https://events.nyu.edu/", "html", "html"),
    BRONX: ("https://bronxmuseum.org/events/", "html", "html"),
    GREENLIGHT: ("https://greenlightbookstore.com/events", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = {GREENLIGHT}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 200
MAX_CHECKPOINT_BYTES = 900000
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|closure|members?[- ]only|private event)\b", re.I)
REMOTE = re.compile(r"\b(?:virtual|webinar|online only)\b", re.I)
NYU_INTERNAL = re.compile(r"\b(?:faculty champion|office hours|registration begins|application deadline)\b", re.I)
CP_API = "https://www.commonpoint.org/wp-json/tribe/events/v1/events"
NYU_API = ("https://events.nyu.edu/live/json/events/category/Open%20to%20the%20Public/"
           "exclude_category/Athletics")
NYU_FIELDS = "description,summary,location,event_types,status,custom_room_number"

# Exact publisher location IDs/names, paired with official NYU location pages.
# Native event points are used only after the ID and name agree with this table.
NYU_VENUES = {
    371: ("20 Cooper Square", "20 Cooper Square", "10003"),
    471: ("Skirball Center for the Performing Arts", "566 LaGuardia Place", "10012"),
    417: ("Institute for the Study of the Ancient World (ISAW)", "15 East 84th Street", "10028"),
    404: ("Global Center for Academic and Spiritual Life", "238 Thompson Street", "10012"),
    469: ("Silver Center for Arts and Science", "100 Washington Square East", "10003"),
    392: ("Casa Italiana", "24 West 12th Street", "10011"),
    2091: ("1 Washington Square North", "1 Washington Square North", "10003"),
    986: ("NYU Silver School of Social Work", "1 Washington Square North", "10003"),
    367: ("19 Washington Square North", "19 Washington Square North", "10011"),
    13279: ("Main Event Space, Rm. 101, 105 East 17th Street", "105 East 17th Street", "10003"),
    390: ("Cantor Film Center", "36 East 8th Street", "10003"),
    2056: ("7 East 12th Street, New York, New York, 10003", "7 East 12th Street", "10003"),
    398: ("Eisner-Lubin Auditorium", "60 Washington Square South", "10012"),
}


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.query or p.fragment:
            return False
        pattern = (r"/event/20\d{2}-\d{2}-\d{2}/[a-z0-9-]+" if key == GREENLIGHT
                   else r"/event/(?:\d+(?:-[a-z0-9-]+)?|[a-z][a-z0-9-]+)" if key == NYU
                   else r"/event/[a-z0-9-]+(?:/20\d{2}-\d{2}-\d{2})?/?")
        return bool(re.fullmatch(pattern, p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.fragment:
            return None
        if key == GREENLIGHT:
            if (p.path.startswith("/sites/default/files/") and ".." not in p.path
                    and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)
                    and set(parse_qs(p.query)) <= {"itok"}):
                return value
        elif key != NYU and not p.query and re.fullmatch(r"/wp-content/uploads/20\d{2}/\d{2}/[^/]+\.(?:jpe?g|png|webp)", p.path, re.I):
            return value
    except ValueError:
        pass
    return None


def _check(deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError("nyc_remaining_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("nyc_remaining_description_limit")
    return text


def _address(street, city, state, postal):
    street = re.sub(r"\s*,\s*", " ", plain(street)).strip()
    state = "NY" if plain(state) in ("NY", "New York") else plain(state)
    if (not re.match(r"^\d{1,6}(?:-\d{1,6})?\s+\S", street) or not city
            or state != "NY" or not re.fullmatch(r"\d{5}(?:-\d{4})?", str(postal or ""))):
        raise ValueError("nyc_remaining_street_unresolved")
    return f"{street}, {plain(city)}, NY {postal}"


def _held(key, identity, reason):
    log.warning("nyc_remaining_event_held source=%s id=%s reason=%s", key, identity, reason)


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _finish(key, row, body, *, labels=(), image=None):
    if not row:
        return None
    if not event_url(key, row.get("event_url")):
        raise ValueError("nyc_remaining_identity_changed")
    row.update(description=body, timezone=ZONE, attendance_mode="in_person",
               location_provenance="publisher_street_pending_geocode")
    if row.get("lat") is not None and row.get("lng") is not None:
        row["location_provenance"] = "publisher_venue_point_reviewed_street"
    if labels:
        row["publisher_categories"] = list(dict.fromkeys(labels))
    if photo := photo_url(key, image):
        row["image_url"] = photo
    return row


def _commonpoint(fetch, deadline, now):
    rows = []
    for page in range(1, 5):
        _check(deadline)
        params = dict(per_page=50, start_date=now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                      end_date=(now + timedelta(days=60)).date().isoformat(), categories=4, page=page)
        payload = json.loads(fetch(CP_API + "?" + urlencode(params), "application/json"))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list) or len(payload["events"]) > 50:
            raise ValueError("nyc_remaining_payload_changed")
        for item in payload["events"]:
            if not isinstance(item, dict):
                raise ValueError("nyc_remaining_payload_changed")
            categories = item.get("categories") or []
            if not any(c.get("id") == 4 and plain(c.get("name")) == "Event" for c in categories if isinstance(c, dict)):
                raise ValueError("nyc_remaining_commonpoint_scope_changed")
            title = plain(item.get("title"))
            if (item.get("status") != "publish" or item.get("all_day") or item.get("is_virtual")
                    or item.get("hide_from_listings") or NONPUBLIC.search(title) or REMOTE.search(title)):
                continue
            if (item.get("timezone") != ZONE or not event_url(COMMONPOINT, item.get("url"))
                    or type(item.get("id")) is not int or item["id"] <= 0):
                raise ValueError("nyc_remaining_identity_changed")
            start, end = timestamp(item.get("start_date"), ZONE), timestamp(item.get("end_date"), ZONE)
            if (not start or not end or end < start or timestamp(item.get("utc_start_date"), "UTC") != start
                    or timestamp(item.get("utc_end_date"), "UTC") != end):
                raise ValueError("nyc_remaining_schedule_changed")
            if not _within(start, end, now):
                continue
            try:
                body = _body(item.get("description"))
                # Publisher prose says 1–3pm; its machine start is 1am. Do not
                # publish a fourteen-hour children's festival from that conflict.
                if item.get("id") == 145501 and start.astimezone(ZoneInfo(ZONE)).hour == 1 and "1-3pm" in body:
                    raise ValueError("nyc_remaining_publisher_schedule_conflict")
                venue = item.get("venue")
                if not isinstance(venue, dict):
                    raise ValueError("nyc_remaining_street_unresolved")
                complete = _address(venue.get("address"), venue.get("city"),
                                    venue.get("state") or venue.get("stateprovince"), venue.get("zip"))
                if not str(venue.get("zip", "")).startswith(("100", "101", "102", "103", "104", "111", "112", "113", "114", "116")):
                    raise ValueError("nyc_remaining_outside_city")
            except ValueError as exc:
                _held(COMMONPOINT, item.get("id"), str(exc))
                continue
            parsed = parse_tribe({"events": [item]}, strict_public=True, retain_description=False)
            if len(parsed) != 1:
                continue
            row = parsed[0]
            row["venue_address"] = complete
            image = item.get("image") or {}
            row = _finish(COMMONPOINT, row, body, labels=[plain(c.get("name")) for c in categories],
                          image=image.get("url") if isinstance(image, dict) else None)
            rows.append(row)
        total = payload.get("total_pages")
        if type(total) is not int or not 0 <= total <= 4:
            raise ValueError("nyc_remaining_pagination_limit")
        if page >= total:
            return rows
    raise ValueError("nyc_remaining_pagination_limit")


def _nyu_url(now, page):
    return (NYU_API + "/start_date/" + now.astimezone(ZoneInfo(ZONE)).date().isoformat()
            + "/end_date/" + (now + timedelta(days=60)).date().isoformat()
            + "/response_fields/" + NYU_FIELDS + "?page=" + str(page))


def _nyu_place(item):
    profile = NYU_VENUES.get(item.get("location_id"))
    if not profile or plain(item.get("location_title")) != profile[0] or plain(item.get("location")) != profile[0]:
        raise ValueError("nyc_remaining_nyu_venue_unreviewed")
    name, street, postal = profile
    try:
        lat, lng = float(item["location_latitude"]), float(item["location_longitude"])
        if not (math.isfinite(lat) and math.isfinite(lng) and 40.5 <= lat <= 40.95 and -74.25 <= lng <= -73.7):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("nyc_remaining_nyu_venue_unreviewed") from None
    return name, _address(street, "New York", "NY", postal), lat, lng


def _nyu(fetch, deadline, now):
    rows, expected_total = [], None
    for page in range(1, 5):
        _check(deadline)
        payload = json.loads(fetch(_nyu_url(now, page), "application/json"))
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not isinstance(payload.get("meta"), dict):
            raise ValueError("nyc_remaining_payload_changed")
        meta = payload["meta"]
        if (meta.get("type") != "events" or meta.get("page") != page or meta.get("per_page") != 100
                or type(meta.get("total_pages")) is not int or not 1 <= meta["total_pages"] <= 4
                or len(payload["data"]) > 100 or not set(NYU_FIELDS.split(",")) <= set(meta.get("response_fields", []))):
            raise ValueError("nyc_remaining_pagination_limit")
        signature = (meta.get("total_results"), meta["total_pages"])
        if expected_total is not None and signature != expected_total:
            raise ValueError("nyc_remaining_manifest_changed")
        expected_total = signature
        for item in payload["data"]:
            if not isinstance(item, dict):
                raise ValueError("nyc_remaining_payload_changed")
            labels = [plain(label) for label in item.get("event_types") or []]
            title = plain(item.get("title"))
            if (item.get("status") != 1 or item.get("is_canceled") or item.get("is_online")
                    or item.get("is_all_day") or item.get("timezone") != ZONE
                    or "Open to the Public" not in labels or NONPUBLIC.search(title) or REMOTE.search(title)
                    or NYU_INTERNAL.search(title)):
                continue
            if type(item.get("id")) is not int or item["id"] <= 0:
                raise ValueError("nyc_remaining_identity_changed")
            if not event_url(NYU, item.get("url")):
                _held(NYU, item["id"], "nyc_remaining_external_event_url")
                continue
            start, end = timestamp(item.get("date_iso")), timestamp(item.get("date2_iso"))
            if (not start or timestamp(item.get("date_utc"), "UTC") != start
                    or (end and (end < start or timestamp(item.get("date2_utc"), "UTC") != end))):
                raise ValueError("nyc_remaining_schedule_changed")
            if not _within(start, end, now):
                continue
            try:
                # Summary is introductory publisher content, never a substitute
                # for a missing full-description field.
                main = _body(item.get("description"))
                parts = []
                for value in (item.get("summary"), main, item.get("cost")):
                    part = description(value, limit=MAX_DESCRIPTION + 1)
                    if part and not any(plain(part) in plain(other) for other in (main, *parts) if other != part):
                        if part not in parts:
                            parts.append(part)
                body = _body("\n\n".join(parts))
                venue, address, lat, lng = _nyu_place(item)
            except ValueError as exc:
                _held(NYU, item.get("id"), str(exc))
                continue
            row = record(title, start.isoformat(), end.isoformat() if end else None,
                         venue, address, "New York", item["url"], str(item["id"]),
                         lat=lat, lng=lng, tz=ZONE, publisher_geo=True, retain_until_end=True)
            row = _finish(NYU, row, body, labels=labels)
            if row:
                rows.append(row)
        if page >= meta["total_pages"]:
            return rows
    raise ValueError("nyc_remaining_pagination_limit")


def _bronx(fetch, deadline, now):
    soup = BeautifulSoup(fetch(SOURCES[BRONX][0], "text/html"), "html.parser")
    cards = soup.select("article.event-card")
    if not cards:
        raise ValueError("nyc_remaining_listing_changed")
    manifest = {}
    for card in cards:
        link, heading, clock = card.select_one("a.event-link[href]"), card.select_one(".event-title"), card.select_one(".event-date")
        if not link or not heading or not clock:
            raise ValueError("nyc_remaining_listing_changed")
        title = plain(heading.get_text(" "))
        if NONPUBLIC.search(title) or REMOTE.search(title):
            continue
        match = re.search(r"\b([A-Z][a-z]{2} \d{1,2}, 20\d{2})\b", clock.get_text(" "))
        if not match:
            raise ValueError("nyc_remaining_schedule_changed")
        day = datetime.strptime(match[1], "%b %d, %Y").date()
        if not now.astimezone(ZoneInfo(ZONE)).date() <= day <= (now + timedelta(days=60)).date():
            continue
        if not event_url(BRONX, link["href"]):
            raise ValueError("nyc_remaining_identity_changed")
        manifest[link["href"]] = title
    if len(manifest) > 8:
        raise ValueError("nyc_remaining_detail_limit")
    rows = []
    for url, title in manifest.items():
        _check(deadline)
        detail = BeautifulSoup(fetch(url, "text/html"), "html.parser")
        calendar, content = detail.select_one("[data-add-to-calendar]"), detail.select(".show-content")
        canonical = detail.select_one('link[rel="canonical"]')
        if (not calendar or len(content) != 1 or not canonical or canonical.get("href") != url
                or plain(calendar.get("data-title")) != title
                or calendar.get("data-address") != "1040 Grand Concourse The Bronx, NY 10456"):
            raise ValueError("nyc_remaining_identity_changed")
        try:
            start, end = [datetime.fromtimestamp(int(calendar.get(field)), timezone.utc) for field in ("data-start", "data-end")]
        except (TypeError, ValueError, OverflowError):
            raise ValueError("nyc_remaining_schedule_changed") from None
        if not start < end <= start + timedelta(days=1):
            raise ValueError("nyc_remaining_schedule_changed")
        if not _within(start, end, now):
            continue
        try:
            body = _body(str(content[0]))
        except ValueError as exc:
            _held(BRONX, url, str(exc))
            continue
        label = detail.select_one(".show-category")
        image = detail.select_one(".show-image img[src]")
        row = record(title, start.isoformat(), end.isoformat(), "The Bronx Museum",
                     "1040 Grand Concourse, Bronx, NY 10456", "Bronx", url, urlsplit(url).path,
                     tz=ZONE, retain_until_end=True)
        row = _finish(BRONX, row, body, labels=[plain(label.get_text(" "))] if label else [], image=image.get("src") if image else None)
        if row:
            rows.append(row)
    return rows


def _greenlight_address(soup):
    location = soup.select_one(".event-details__location--location")
    postal = location.select_one("p.address") if location else None
    if postal:
        def component(name):
            node = postal.select_one("." + name)
            return plain(node.get_text(" ")) if node else ""
        venue, street = component("address-line1"), component("address-line2")
        city, state, zip_code = component("locality"), component("administrative-area"), component("postal-code")
    else:
        address = location.select_one("address") if location else None
        lines = [plain(line) for line in address.stripped_strings] if address else []
        if lines != ["Greenlight Bookstore", "686 Fulton Street", "Brooklyn, NY 11217-1609"]:
            raise ValueError("nyc_remaining_street_unresolved")
        venue, street, city, state, zip_code = "Greenlight Bookstore", "686 Fulton Street", "Brooklyn", "NY", "11217-1609"
    complete = _address(street, city, state, zip_code)
    if not venue or city not in ("Brooklyn", "New York", "Bronx", "Queens", "Staten Island"):
        raise ValueError("nyc_remaining_street_unresolved")
    return dict(venue_name=venue, venue_address=complete, venue_city=city)


def _greenlight_manifest(fetch, deadline, now):
    start, last = now.astimezone(ZoneInfo(ZONE)).date(), (now + timedelta(days=60)).date()
    month, seen, manifest = start.replace(day=1), set(), []
    for _ in range(3):
        _check(deadline)
        url = "https://greenlightbookstore.com/events/" + month.strftime("%Y/%m")
        soup = BeautifulSoup(fetch(url, "text/html"), "html.parser")
        if not soup.select_one("main .view-indiecommerce-event-list"):
            # Empty future months retain the same Drupal view wrapper.
            if not soup.select_one('form[data-drupal-selector="views-exposed-form-indiecommerce-event-list-page-events"]'):
                raise ValueError("nyc_remaining_listing_changed")
        for card in soup.select("article.event-list"):
            link = card.select_one(".event-list__title a[href]")
            identity = card.get("id", "")
            if not link or not re.fullmatch(r"event-\d+", identity):
                raise ValueError("nyc_remaining_identity_changed")
            title, href = plain(link.get_text(" ")), urljoin(url, link["href"])
            if NONPUBLIC.search(title) or REMOTE.search(title):
                continue
            labels = [plain(n.get_text(" ")) for n in card.select(".event-tag__term a")]
            if "Virtual" in labels or "Holiday Hours" in labels:
                continue
            if not event_url(GREENLIGHT, href):
                raise ValueError("nyc_remaining_identity_changed")
            day = datetime.strptime(urlsplit(href).path.split("/")[2], "%Y-%m-%d").date()
            if not start <= day <= last:
                continue
            try:
                place = _greenlight_address(card)
            except ValueError as exc:
                _held(GREENLIGHT, identity, str(exc))
                continue
            item = dict(url=href, title=title, id=identity[6:], **place)
            if href in seen:
                raise ValueError("nyc_remaining_manifest_changed")
            manifest.append(item)
            seen.add(href)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        if month > last:
            break
    if len(manifest) > MAX_RECORDS:
        raise ValueError("nyc_remaining_manifest_limit")
    return sorted(manifest, key=lambda item: item["url"])


def _greenlight_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        value = json.loads(script.get_text())
        nodes = value.get("@graph", [value]) if isinstance(value, dict) else value
        events += [node for node in nodes if isinstance(node, dict) and node.get("@type") == "Event"]
    heading, contents = soup.select_one("h1.event-details__info--title"), soup.select(".event-details__info--body")
    if (len(events) != 1 or not heading or len(contents) != 1 or events[0].get("url") != item["url"]
            or plain(events[0].get("name")) != item["title"] or plain(heading.get_text(" ")) != item["title"]):
        raise ValueError("nyc_remaining_identity_changed")
    native = events[0]
    if native.get("eventStatus") != "https://schema.org/EventScheduled":
        return None
    labels = [plain(n.get_text(" ")) for n in soup.select(".event-details__info--tags .event-tag__term a")]
    if "Virtual" in labels or native.get("eventAttendanceMode") == "https://schema.org/OnlineEventAttendanceMode":
        return None
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", str(native.get("startDate", ""))):
        raise ValueError("nyc_remaining_schedule_unresolved")
    start, end = timestamp(native["startDate"]), timestamp(native.get("endDate"))
    if not start or (end and end < start) or start.astimezone(ZoneInfo(ZONE)).hour == 0:
        raise ValueError("nyc_remaining_schedule_unresolved")
    if not _within(start, end, now):
        return None
    place = _greenlight_address(soup)
    if any(item.get(field) != value for field, value in place.items()):
        raise ValueError("nyc_remaining_venue_changed")
    copied = BeautifulSoup(str(contents[0]), "html.parser")
    for node in copied.select(".visually-hidden"):
        node.decompose()
    body = _body(str(copied))
    row = record(item["title"], start.isoformat(), end.isoformat() if end else None, place["venue_name"],
                 place["venue_address"], place["venue_city"], item["url"], item["id"], tz=ZONE, retain_until_end=True)
    image = soup.select_one(".event-details__image img[src]")
    return _finish(GREENLIGHT, row, body, labels=labels, image=urljoin(item["url"], image["src"]) if image else None)


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_nyc_arts_remaining")
    return key


def _unique(rows):
    result = {}
    for row in rows:
        identity = (row["id"], row["starts_at"])
        if identity in result and result[identity] != row:
            raise ValueError("nyc_remaining_conflicting_occurrence")
        result[identity] = row
    if len(result) > MAX_RECORDS:
        raise ValueError("nyc_remaining_record_limit")
    return sorted(result.values(), key=lambda row: (row["starts_at"], row["id"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    if key in CHECKPOINT_KEYS:
        raise ValueError("publisher_checkpoint_required")
    current, deadline = now or datetime.now(timezone.utc), deadline_at or monotonic() + 35
    _check(deadline)
    return _unique({COMMONPOINT: _commonpoint, NYU: _nyu, BRONX: _bronx}[key](fetch, deadline, current))


HOLD_REASONS = {"nyc_remaining_description_missing", "nyc_remaining_description_limit",
                "nyc_remaining_street_unresolved", "nyc_remaining_schedule_unresolved", "event_not_current"}


def _checkpoint(value, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get("version") != 1 or type(value.get("version")) is not int
            or value.get("source_key") != GREENLIGHT or type(value.get("cursor")) is not int
            or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_RECORDS
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or not isinstance(value.get("events"), list) or not isinstance(value.get("diagnostics"), list)
            or len(value["events"]) + len(value["diagnostics"]) != value["cursor"]
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError("nyc_remaining_checkpoint_invalid")
    try:
        started = timestamp(value["started_at"])
        if not started or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("nyc_remaining_checkpoint_invalid") from None
    if not started <= now <= started + timedelta(hours=24):
        return None
    queue = value["queue"]
    if any(not isinstance(item, dict) or set(item) != {"url", "title", "id", "venue_name", "venue_address", "venue_city"}
           or not event_url(GREENLIGHT, item["url"]) or not isinstance(item["title"], str)
           or not item["title"].strip() or not str(item["id"]).isdigit()
           or not isinstance(item["venue_name"], str) or not item["venue_name"].strip()
           or item["venue_city"] not in ("Brooklyn", "New York", "Bronx", "Queens", "Staten Island")
           or not isinstance(item["venue_address"], str)
           or not re.fullmatch(r"\d{1,6}(?:-\d{1,6})? [^\n]+, " + re.escape(item["venue_city"]) + r", NY \d{5}(?:-\d{4})?", item["venue_address"])
           for item in queue):
        raise ValueError("nyc_remaining_checkpoint_invalid")
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if value.get("manifest_hash") != digest or len({item["url"] for item in queue}) != len(queue):
        raise ValueError("nyc_remaining_checkpoint_invalid")
    processed, seen = {item["url"]: item for item in queue[:value["cursor"]]}, set()
    for row in value["events"]:
        item = processed.get(row.get("event_url")) if isinstance(row, dict) else None
        if (not item or row["event_url"] in seen or row.get("id") != item["id"] or row.get("title") != item["title"]
                or any(row.get(field) != item.get(field) for field in ("venue_name", "venue_address", "venue_city"))
                or not isinstance(row.get("description"), str) or not 0 < len(row["description"]) <= MAX_DESCRIPTION
                or not row["description"].strip() or not row.get("venue_name")
                or not re.fullmatch(r"\d{1,6}(?:-\d{1,6})? [^\n]+, (?:Brooklyn|New York|Bronx|Queens|Staten Island), NY \d{5}(?:-\d{4})?", str(row.get("venue_address", "")))
                or row.get("lat") is not None or row.get("lng") is not None
                or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                or (row.get("image_url") is not None and photo_url(GREENLIGHT, row["image_url"]) is None)):
            raise ValueError("nyc_remaining_checkpoint_invalid")
        try:
            start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
        except (ValueError, TypeError, OverflowError):
            raise ValueError("nyc_remaining_checkpoint_invalid") from None
        if not start or start.tzinfo is None or (end and (end.tzinfo is None or end < start)):
            raise ValueError("nyc_remaining_checkpoint_invalid")
        seen.add(row["event_url"])
    for item in value["diagnostics"]:
        if (not isinstance(item, dict) or item.get("event_url") not in processed
                or item["event_url"] in seen or item.get("disposition") != "held"
                or item.get("reason") not in HOLD_REASONS):
            raise ValueError("nyc_remaining_checkpoint_invalid")
        seen.add(item["event_url"])
    if seen != set(processed):
        raise ValueError("nyc_remaining_checkpoint_invalid")
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=3):
    if _source(source) != GREENLIGHT:
        raise ValueError("unregistered_nyc_arts_remaining")
    current = now or datetime.now(timezone.utc)
    state = _checkpoint(checkpoint, current)
    if state and state["cursor"] == state["manifest_count"]:
        return dict(complete=True, events=_unique(deepcopy(state["events"])), checkpoint=state)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    queue = _greenlight_manifest(fetch, deadline, timestamp(state["started_at"]) if state else current)
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest:
        state = dict(version=1, source_key=GREENLIGHT, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=digest, manifest_count=len(queue), cursor=0, queue=queue, events=[], diagnostics=[])
    prior, maximum = state["cursor"], min(3, max(1, int(max_details)))
    while state["cursor"] < len(queue) and state["cursor"] - prior < maximum:
        if monotonic() + 8 >= deadline:
            break
        item = queue[state["cursor"]]
        reason = "event_not_current"
        try:
            row = _greenlight_detail(item, fetch(item["url"], "text/html"), timestamp(state["started_at"]))
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            row, reason = None, str(exc)
        if row:
            state["events"].append(row)
        else:
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=reason))
        state["cursor"] += 1
    if prior == state["cursor"] < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("nyc_remaining_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    return dict(complete=complete, events=_unique(deepcopy(state["events"])) if complete else [], checkpoint=state)


ERROR_CODES = {
    "unregistered_nyc_arts_remaining", "nyc_remaining_description_missing", "nyc_remaining_description_limit",
    "nyc_remaining_street_unresolved", "nyc_remaining_identity_changed", "nyc_remaining_payload_changed",
    "nyc_remaining_commonpoint_scope_changed", "nyc_remaining_schedule_changed",
    "nyc_remaining_publisher_schedule_conflict", "nyc_remaining_outside_city", "nyc_remaining_pagination_limit",
    "nyc_remaining_manifest_changed", "nyc_remaining_nyu_venue_unreviewed", "nyc_remaining_listing_changed",
    "nyc_remaining_detail_limit", "nyc_remaining_manifest_limit", "nyc_remaining_schedule_unresolved",
    "nyc_remaining_conflicting_occurrence", "nyc_remaining_record_limit", "nyc_remaining_checkpoint_invalid",
    "nyc_remaining_checkpoint_size_limit", "nyc_remaining_external_event_url", "nyc_remaining_venue_changed",
    "publisher_checkpoint_required", "collection_deadline",
}
