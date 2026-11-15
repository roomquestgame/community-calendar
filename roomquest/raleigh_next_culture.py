"""Page 158 Books' complete native IndieCommerce occurrence calendar.

All requests use the injected ordinary guarded GET transport.  The entire
published list is exhausted before any detail is accepted for staging.  Each
dated native instance is read independently; no recurrence or prose is invented.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
SOURCE = "page158_books_wake_forest_nc"
CALENDAR = "https://page158books.com/events/list/upcoming-events"
SOURCES = {SOURCE: (CALENDAR, "html", "html")}
LABELS = {SOURCE: "Page 158 Books"}
ALLOWED_HOSTS = {SOURCE: ("page158books.com",)}
CHECKPOINT_KEYS = {SOURCE}
CHECKPOINT_MANIFEST_LIMITS = {SOURCE: 200}
CHECKPOINT_EVENT_LIMITS = {SOURCE: 200}
MAX_BYTES = 850_000
MAX_PAGES = 20
PAGE_SIZE = 25
PREFIX = "raleigh_culture_"
PENDING_GEO = "publisher_event_address_pending_geocode"
NATIVE_GEO = "publisher_event_geo"
HOLD_CODES = {PREFIX + value for value in (
    "description_missing", "description_limit", "schedule_unresolved",
    "schedule_conflict", "street_unresolved", "native_point_unresolved",
    "nonpublic", "outside_window")}
ERROR_CODES = HOLD_CODES | {PREFIX + value for value in (
    "source_unregistered", "calendar_changed", "pagination_changed",
    "detail_identity", "manifest_limit", "checkpoint_invalid", "checkpoint_size_limit")}
ERROR_CODES |= {"collection_deadline", "publisher_checkpoint_required"}
STREET = re.compile(r"^\d{1,6}(?:-\d{1,6})?\s+\S")
UNIT = re.compile(r"^(?:suite|ste[.]?|unit|#)\s*\S", re.I)
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|private\s+(?:event|party)|members[- ]only|online[- ]only)\b", re.I)
MONTHS = {datetime(2000, number, 1).strftime("%B").lower(): number for number in range(1, 13)}
STATE_KEYS = {"version", "source_key", "started_at", "window_start", "phase",
    "listing_complete", "next_page", "listed_pages", "listing_total_pages",
    "listing_seen", "outside_window_count", "queue", "cursor", "manifest_count",
    "manifest_hash", "events", "diagnostics", "outcomes", "state_hash"}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _source(source):
    if (source.get("source_key") != SOURCE or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[SOURCE], ZONE)):
        raise ValueError(PREFIX + "source_unregistered")


def event_url(key, value):
    return key == SOURCE and isinstance(value, str) and len(value) <= 600 and bool(re.fullmatch(
        r"https://page158books[.]com/event/20\d{2}-\d{2}-\d{2}/[a-z0-9]+(?:-[a-z0-9]+)*", value))


def _page(index):
    if type(index) is not int or not 0 <= index < MAX_PAGES:
        raise ValueError(PREFIX + "pagination_changed")
    return CALENDAR if index == 0 else CALENDAR + "?page=" + str(index)


def _page_number(value):
    if value == CALENDAR:
        return 0
    match = re.fullmatch(re.escape(CALENDAR) + r"\?page=(0|[1-9]\d?)", str(value))
    if not match or int(match[1]) >= MAX_PAGES:
        raise ValueError(PREFIX + "pagination_changed")
    return int(match[1])


def photo_url(value):
    if not isinstance(value, str) or len(value) > 1200:
        return None
    url = urljoin(CALENDAR, value)
    return url if re.fullmatch(
        r"https://page158books[.]com/sites/default/files/[A-Za-z0-9_/-]+[.](?:png|jpe?g|webp|gif)"
        r"(?:\?itok=[A-Za-z0-9_-]+)?", url, re.I) else None


def _window(anchor):
    first = anchor.astimezone(ZoneInfo(ZONE)).date()
    return first, first + timedelta(days=60)


def _day(text, code="calendar_changed"):
    match = re.fullmatch(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*(\d{1,2}/\d{1,2}/20\d{2})", plain(text))
    if not match:
        raise ValueError(PREFIX + code)
    try:
        result = datetime.strptime(match[2], "%m/%d/%Y").date()
    except ValueError:
        raise ValueError(PREFIX + code) from None
    if result.strftime("%a") != match[1]:
        raise ValueError(PREFIX + code)
    return result


def _clocks(text):
    clock = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    match = re.fullmatch(clock + r"(?:\s*[-–—]\s*" + clock + r")?", plain(text), re.I)
    if not match:
        raise ValueError(PREFIX + "schedule_unresolved")
    values = []
    for offset in (0, 3):
        hour, minute, meridiem = match.groups()[offset:offset + 3]
        if hour is None:
            values.append(None)
            continue
        if not 1 <= int(hour) <= 12 or minute is not None and int(minute) > 59:
            raise ValueError(PREFIX + "schedule_unresolved")
        values.append(time(int(hour) % 12 + (12 if meridiem.lower() == "pm" else 0), int(minute or 0)))
    return values


def _place(node):
    containers = node.select(".event-details__location--location")
    if len(containers) != 1:
        raise ValueError(PREFIX + "street_unresolved")
    container = containers[0]
    postal = container.select_one("p.address")
    if postal:
        def part(cls):
            values = postal.select("." + cls)
            if len(values) != 1:
                raise ValueError(PREFIX + "street_unresolved")
            return plain(values[0].get_text(" "))
        city, state, zip_code = part("locality"), part("administrative-area"), part("postal-code")
        lines = [plain(item.get_text(" ")) for item in postal.select(".address-line1, .address-line2, .address-line3")]
    else:
        addresses = container.find_all("address")
        if len(addresses) != 1:
            raise ValueError(PREFIX + "street_unresolved")
        lines = [plain(text) for text in addresses[0].stripped_strings if plain(text)]
        if lines and lines[-1] in {"United States", "USA", "US"}:
            lines.pop()
        if not lines:
            raise ValueError(PREFIX + "street_unresolved")
        match = re.fullmatch(r"([^,]+),\s*(NC|North Carolina)\s+(\d{5}(?:-\d{4})?)", lines.pop())
        if not match:
            raise ValueError(PREFIX + "street_unresolved")
        city, state, zip_code = match.groups()
    street_indices = [number for number, text in enumerate(lines) if STREET.match(text)]
    if (len(street_indices) != 1 or state not in {"NC", "North Carolina"}
            or not re.fullmatch(r"\d{5}(?:-\d{4})?", zip_code) or not city or len(city) > 80):
        raise ValueError(PREFIX + "street_unresolved")
    street_index = street_indices[0]
    units = [text for index, text in enumerate(lines) if index != street_index and UNIT.match(text)]
    names = [text for index, text in enumerate(lines) if index != street_index and not UNIT.match(text)]
    venue = ", ".join(names)
    street = " ".join([lines[street_index]] + units)
    address = f"{street}, {city}, NC {zip_code}"
    if not venue or len(venue) > 160 or len(address) > 200:
        raise ValueError(PREFIX + "street_unresolved")
    return {"venue_name": venue, "venue_address": address, "venue_city": city}


def _listing(payload, url):
    soup = BeautifulSoup(payload, "html.parser")
    views = soup.select("main .view-event-carousel.view-display-id-event_carousel_page_block")
    canonical = soup.find_all("link", rel="canonical")
    if (len(views) != 1 or len(canonical) != 1 or canonical[0].get("href") != CALENDAR
            or not soup.title or plain(soup.title.get_text()) != "Upcoming Events | Page 158 Books"):
        raise ValueError(PREFIX + "calendar_changed")
    view, index = views[0], _page_number(url)
    cards = view.select("article.event-list")
    pagers = view.select("nav.pager")
    if len(pagers) != 1 or not cards or len(cards) > PAGE_SIZE:
        # Do not certify an empty/truncated response as an exhausted calendar.
        raise ValueError(PREFIX + "calendar_changed")
    active = pagers[0].select('a[aria-current="page"][href]')
    links = pagers[0].select("a[href]")
    indices = [_page_number(urljoin(url, item["href"])) for item in links]
    next_links = pagers[0].select('a[rel~="next"][href]')
    last_links = pagers[0].select(".pager__item--last a[href]")
    if (len(active) != 1 or _page_number(urljoin(url, active[0]["href"])) != index
            or len(next_links) > 1 or len(last_links) > 1 or not indices):
        raise ValueError(PREFIX + "pagination_changed")
    last = _page_number(urljoin(url, last_links[0]["href"])) if last_links else max(indices)
    total = last + 1
    next_page = urljoin(url, next_links[0]["href"]) if next_links else None
    if (index > last or next_page != (_page(index + 1) if index < last else None)
            or max(indices) > last or index < last and len(cards) != PAGE_SIZE):
        raise ValueError(PREFIX + "pagination_changed")
    result = []
    for card in cards:
        links = card.select(".event-list__title a[href]")
        identity = card.get("id", "")
        if len(links) != 1 or not re.fullmatch(r"event-[1-9]\d{0,8}", identity):
            raise ValueError(PREFIX + "calendar_changed")
        title, href = plain(links[0].get_text(" ")), urljoin(url, links[0]["href"])
        if not title or len(title) > 180 or not event_url(SOURCE, href):
            raise ValueError(PREFIX + "calendar_changed")
        fields = {}
        for label in card.select(".event-list__details--label"):
            key = plain(label.get_text()).rstrip(":")
            if key in {"Date", "Time"}:
                if key in fields:
                    raise ValueError(PREFIX + "calendar_changed")
                fields[key] = plain(label.parent.get_text(" ")).removeprefix(key + ":").strip()
        day = _day(fields.get("Date", ""))
        if day.isoformat() != urlsplit(href).path.split("/")[2] or not fields.get("Time") or len(fields["Time"]) > 100:
            raise ValueError(PREFIX + "calendar_changed")
        try:
            place = _place(card)
        except ValueError:
            place = None  # The full detail must supply its own complete address.
        result.append({"id": identity[6:], "url": href, "title": title,
            "day": day.isoformat(), "clock_text": fields["Time"], "place": place})
    return result, next_page, total


def _body(node):
    body = description(str(node), limit=12001)
    if len(body) > 12000:
        raise ValueError(PREFIX + "description_limit")
    if not body or not re.search(r"[A-Za-z]{3}", body):
        raise ValueError(PREFIX + "description_missing")
    return body


def _event_body_date_conflict(body, day):
    # Only an explicit invitation date, not dates appearing in a book synopsis.
    pattern = (r"\bjoin us\b[^.!?]{0,180}?\bon\s+(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
               r"(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b")
    for match in re.finditer(pattern, body, re.I):
        try:
            stated = date(int(match[3]) if match[3] else day.year, MONTHS[match[1].lower()], int(match[2]))
        except ValueError:
            return True
        if stated != day:
            return True
    return False


def _detail(item, payload, anchor):
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.select("main article.eventinstance-full")
    canonical = soup.find_all("link", rel="canonical")
    nodes = []
    try:
        for tag in soup.select('script[type="application/ld+json"]'):
            value = json.loads(tag.get_text())
            values = value.get("@graph", [value]) if isinstance(value, dict) else value
            if not isinstance(values, list):
                raise ValueError
            nodes.extend(node for node in values if isinstance(node, dict) and node.get("@type") == "Event")
    except (ValueError, TypeError):
        raise ValueError(PREFIX + "detail_identity") from None
    if len(main) != 1 or len(nodes) != 1 or len(canonical) != 1 or canonical[0].get("href") != item["url"]:
        raise ValueError(PREFIX + "detail_identity")
    main, native = main[0], nodes[0]
    headings, bodies = main.select("h1.event-details__info--title"), main.select(".event-details__info--body")
    if (len(headings) != 1 or len(bodies) != 1 or native.get("url") != item["url"]
            or native.get("@id") != item["url"] or plain(native.get("name")) != item["title"]
            or plain(headings[0].get_text(" ")) != item["title"]):
        raise ValueError(PREFIX + "detail_identity")
    labels = [plain(node.get_text(" ")) for node in main.select(".event-details__info--tags .event-tag__term")]
    if (native.get("eventStatus") != "https://schema.org/EventScheduled"
            or native.get("eventAttendanceMode") == "https://schema.org/OnlineEventAttendanceMode"
            or NONPUBLIC.search(item["title"]) or any(NONPUBLIC.search(value) for value in labels)):
        raise ValueError(PREFIX + "nonpublic")
    try:
        start, end = timestamp(native.get("startDate")), timestamp(native.get("endDate"))
        if start is None or start.tzinfo is None or end is not None and end.tzinfo is None:
            raise ValueError
        if start.utcoffset() != start.astimezone(ZoneInfo(ZONE)).utcoffset():
            raise ValueError
        if end is not None and (end.utcoffset() != end.astimezone(ZoneInfo(ZONE)).utcoffset()
                or end <= start or end - start > timedelta(hours=24)):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError(PREFIX + "schedule_unresolved") from None
    local = start.astimezone(ZoneInfo(ZONE))
    dates = main.select(".event-details__location--date")
    if len(dates) != 1:
        raise ValueError(PREFIX + "schedule_unresolved")
    match = re.fullmatch(r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*\d{1,2}/\d{1,2}/20\d{2})\s*-\s*(.+)",
                         plain(dates[0].get_text(" ")))
    if not match:
        raise ValueError(PREFIX + "schedule_unresolved")
    visible_day = _day(match[1], "schedule_conflict")
    list_clocks, visible_clocks = _clocks(item["clock_text"]), _clocks(match[2])
    if (visible_day.isoformat() != item["day"] or visible_day != local.date()
            or local.second or local.microsecond or list_clocks != visible_clocks
            or visible_clocks[0] != local.time()
            or visible_clocks[1] is not None and (end is None or visible_clocks[1] != end.astimezone(ZoneInfo(ZONE)).time())):
        raise ValueError(PREFIX + "schedule_conflict")
    first, stop = _window(anchor)
    if not first <= local.date() < stop or (end or start + timedelta(hours=3)) <= anchor:
        raise ValueError(PREFIX + "outside_window")
    place = _place(main)
    if item["place"] is not None and item["place"] != place:
        raise ValueError(PREFIX + "street_unresolved")
    body = _body(bodies[0])
    if _event_body_date_conflict(body, local.date()):
        raise ValueError(PREFIX + "schedule_conflict")
    lat = lng = None
    location = native.get("location")
    if not isinstance(location, dict) or location.get("@type") != "Place":
        raise ValueError(PREFIX + "street_unresolved")
    geo = location.get("geo")
    if geo is not None:
        try:
            if not isinstance(geo, dict) or set(geo) - {"@type", "latitude", "longitude"}:
                raise ValueError
            if any(isinstance(geo.get(field), bool) for field in ("latitude", "longitude")):
                raise ValueError
            lat, lng = float(geo["latitude"]), float(geo["longitude"])
            if not math.isfinite(lat) or not math.isfinite(lng) or not 33.8 <= lat <= 36.7 or not -84.4 <= lng <= -75.3:
                raise ValueError
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError(PREFIX + "native_point_unresolved") from None
    identity = "page158:" + sha256(f'{item["url"]}|{local.isoformat()}'.encode()).hexdigest()
    row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
        place["venue_name"], place["venue_address"], place["venue_city"], item["url"], identity,
        lat=lat, lng=lng, tz=ZONE, publisher_geo=lat is not None, retain_until_end=True)
    if row is None:
        raise ValueError(PREFIX + "outside_window")
    row.update(description=body, timezone=ZONE, attendance_mode="in_person",
        publisher_categories=labels, location_provenance=NATIVE_GEO if lat is not None else PENDING_GEO,
        location_evidence_url=item["url"])
    pictures = main.select(".event-details__image img[src]")
    if len(pictures) == 1 and photo_url(pictures[0]["src"]):
        row["image_url"] = photo_url(pictures[0]["src"])
    return row


def _seal(state):
    state["manifest_count"], state["manifest_hash"] = len(state["queue"]), _hash(state["queue"])
    state["state_hash"] = _hash({key: value for key, value in state.items() if key != "state_hash"})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError(PREFIX + "checkpoint_size_limit")


def checkpoint_complete(state):
    try:
        return (isinstance(state, dict) and state.get("source_key") == SOURCE
            and state.get("phase") == "details" and state.get("listing_complete") is True
            and "next_page" in state and state["next_page"] is None
            and type(state.get("listing_total_pages")) is int and 1 <= state["listing_total_pages"] <= MAX_PAGES
            and state.get("listed_pages") == [_page(index) for index in range(state["listing_total_pages"])]
            and type(state.get("cursor")) is int and type(state.get("manifest_count")) is int
            and state["cursor"] == state["manifest_count"] == len(state["queue"]) == len(state["outcomes"])
            and len(state["events"]) + len(state["diagnostics"]) == state["cursor"]
            and len(state["listing_seen"]) == state["manifest_count"] + state["outside_window_count"])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def _checkpoint(value, current):
    if value is None:
        return None
    try:
        anchor = timestamp(value["started_at"])
        page_count, total_pages = len(value["listed_pages"]), value["listing_total_pages"]
        valid = (set(value) == STATE_KEYS and type(value["version"]) is int and value["version"] == 1
            and value["source_key"] == SOURCE and anchor.utcoffset() == timedelta(0)
            and anchor <= current + timedelta(seconds=60)
            and value["window_start"] == _window(anchor)[0].isoformat()
            and value["state_hash"] == _hash({key: item for key, item in value.items() if key != "state_hash"})
            and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_BYTES
            and type(total_pages) is int and 1 <= total_pages <= MAX_PAGES and 1 <= page_count <= total_pages
            and value["listed_pages"] == [_page(index) for index in range(page_count)]
            and value["next_page"] == (_page(page_count) if page_count < total_pages else None)
            and value["listing_complete"] is (page_count == total_pages)
            and value["phase"] == ("details" if value["listing_complete"] else "listing")
            and type(value["outside_window_count"]) is int and value["outside_window_count"] >= 0
            and isinstance(value["queue"], list) and len(value["queue"]) <= 200
            and type(value["manifest_count"]) is int and value["manifest_count"] == len(value["queue"])
            and value["manifest_hash"] == _hash(value["queue"])
            and type(value["cursor"]) is int and 0 <= value["cursor"] <= len(value["queue"])
            and isinstance(value["events"], list) and isinstance(value["diagnostics"], list)
            and isinstance(value["outcomes"], list) and len(value["outcomes"]) == value["cursor"]
            and len(value["events"]) + len(value["diagnostics"]) == value["cursor"]
            and (value["listing_complete"] or value["cursor"] == 0))
        first, stop = _window(anchor)
        seen_ids, seen_urls = set(), set()
        eligible = []
        for item in value["listing_seen"]:
            valid = (valid and set(item) == {"id", "url", "day"}
                and re.fullmatch(r"[1-9]\d{0,8}", item["id"]) is not None
                and event_url(SOURCE, item["url"]) and item["day"] == urlsplit(item["url"]).path.split("/")[2]
                and item["id"] not in seen_ids and item["url"] not in seen_urls)
            if first <= date.fromisoformat(item["day"]) < stop:
                eligible.append(item)
            seen_ids.add(item["id"])
            seen_urls.add(item["url"])
        valid = (valid and 0 < len(seen_ids) <= MAX_PAGES * PAGE_SIZE
            and len(value["listing_seen"]) == value["manifest_count"] + value["outside_window_count"]
            and len(eligible) == len(value["queue"]))
        for expected, item in zip(eligible, value["queue"]):
            valid = (valid and set(item) == {"id", "url", "title", "day", "clock_text", "place"}
                and all(item[key] == expected[key] for key in expected)
                and isinstance(item["title"], str) and 0 < len(item["title"]) <= 180
                and isinstance(item["clock_text"], str) and 0 < len(item["clock_text"]) <= 100
                and (item["place"] is None or set(item["place"]) == {"venue_name", "venue_address", "venue_city"}))
        rows, diagnostics = {}, []
        for item, outcome in zip(value["queue"], value["outcomes"]):
            valid = valid and outcome["item_hash"] == _hash(item)
            if outcome["reason"]:
                valid = valid and outcome["reason"] in HOLD_CODES and outcome["row"] is None
                diagnostics.append({"id": item["id"], "event_url": item["url"], "disposition": "held", "reason": outcome["reason"]})
            else:
                proof = outcome["row"]
                valid = valid and proof["id"] not in rows
                rows[proof["id"]] = (proof["hash"], item)
        valid = valid and diagnostics == value["diagnostics"] and len(rows) == len(value["events"])
        for row in value["events"]:
            proof, item = rows[row["id"]]
            lat, lng = row.get("lat"), row.get("lng")
            valid = (valid and proof == _hash(row) and row["event_url"] == item["url"]
                and row["title"] == item["title"] and row["timezone"] == ZONE
                and row["location_evidence_url"] == item["url"]
                and row["location_provenance"] == (PENDING_GEO if lat is None else NATIVE_GEO)
                and ((lat is None and lng is None) or type(lat) in (int, float) and type(lng) in (int, float)
                     and math.isfinite(lat) and math.isfinite(lng) and 33.8 <= lat <= 36.7 and -84.4 <= lng <= -75.3)
                and isinstance(row["venue_name"], str) and 0 < len(row["venue_name"]) <= 160
                and isinstance(row["venue_address"], str) and STREET.match(row["venue_address"]) is not None
                and len(row["venue_address"]) <= 200 and re.search(r"\bNC \d{5}(?:-\d{4})?$", row["venue_address"]) is not None
                and isinstance(row["description"], str) and 0 < len(row["description"]) <= 12000
                and timestamp(row["starts_at"]).astimezone(ZoneInfo(ZONE)).date().isoformat() == item["day"]
                and (not row.get("ends_at") or timestamp(row["ends_at"]) > timestamp(row["starts_at"]))
                and (not row.get("image_url") or photo_url(row["image_url"]) == row["image_url"]))
        if not valid:
            raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        raise ValueError(PREFIX + "checkpoint_invalid") from None
    if current - anchor > timedelta(hours=4):
        return None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_fetches=3):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or type(max_fetches) is not int or not 1 <= max_fetches <= 3:
        raise ValueError(PREFIX + "checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, current)
    if state is None:
        state = {"version": 1, "source_key": SOURCE, "started_at": current.isoformat(),
            "window_start": _window(current)[0].isoformat(), "phase": "listing", "listing_complete": False,
            "next_page": CALENDAR, "listed_pages": [], "listing_total_pages": None, "listing_seen": [],
            "outside_window_count": 0, "queue": [], "cursor": 0, "manifest_count": 0,
            "manifest_hash": _hash([]), "events": [], "diagnostics": [], "outcomes": []}
    if checkpoint_complete(state):
        return {"complete": True, "events": deepcopy(state["events"]), "checkpoint": state}
    anchor = timestamp(state["started_at"])
    first, stop = _window(anchor)
    fetched, before = 0, (len(state["listed_pages"]), state["cursor"])
    while fetched < max_fetches and (deadline_at is None or monotonic() + 12 < deadline_at):
        if not state["listing_complete"]:
            url = state["next_page"]
            items, next_page, total = _listing(fetch(url, "text/html"), url)
            fetched += 1
            if state["listing_total_pages"] is not None and state["listing_total_pages"] != total:
                raise ValueError(PREFIX + "pagination_changed")
            state["listing_total_pages"] = total
            known_ids = {item["id"] for item in state["listing_seen"]}
            known_urls = {item["url"] for item in state["listing_seen"]}
            for item in items:
                if item["id"] in known_ids or item["url"] in known_urls:
                    raise ValueError(PREFIX + "calendar_changed")
                known_ids.add(item["id"])
                known_urls.add(item["url"])
                state["listing_seen"].append({key: item[key] for key in ("id", "url", "day")})
                if first <= date.fromisoformat(item["day"]) < stop:
                    state["queue"].append(item)
                else:
                    state["outside_window_count"] += 1
            if len(state["queue"]) > 200 or len(state["listing_seen"]) > MAX_PAGES * PAGE_SIZE:
                raise ValueError(PREFIX + "manifest_limit")
            state["listed_pages"].append(url)
            state["next_page"] = next_page
            state["listing_complete"] = next_page is None
            state["phase"] = "details" if state["listing_complete"] else "listing"
            continue
        if state["cursor"] == len(state["queue"]):
            break
        item = state["queue"][state["cursor"]]
        reason, row = None, None
        payload = fetch(item["url"], "text/html")
        fetched += 1
        try:
            row = _detail(item, payload, anchor)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            reason = str(exc)
        if row is not None:
            state["events"].append(row)
        else:
            state["diagnostics"].append({"id": item["id"], "event_url": item["url"],
                "disposition": "held", "reason": reason})
        state["outcomes"].append({"item_hash": _hash(item), "reason": reason,
            "row": {"id": row["id"], "hash": _hash(row)} if row else None})
        state["cursor"] += 1
    if before == (len(state["listed_pages"]), state["cursor"]):
        raise ValueError("collection_deadline")
    _seal(state)
    complete = checkpoint_complete(state)
    return {"complete": complete, "events": deepcopy(state["events"]) if complete else [], "checkpoint": state}


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("publisher_checkpoint_required")
    return result["events"]
