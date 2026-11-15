"""Eataly's public NYC classes and events, including native series occurrences.

Reuses the existing Eataly inert-data decoder and the shared description/record
contracts. Every HTTP request is supplied by the ordinary guarded transport.
The product's complete long description and its displayed introductory text are
retained. The publisher-disallowed /on/ image routes are never imported.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.boston_nightlife_remaining import _eataly_native, _title_key
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
EATALY = "eataly_new_york_ny"
SOURCES = {EATALY: ("https://www.eataly.com/c/classes-new-york", "html", "html")}
ALLOWED_HOSTS = {EATALY: ("www.eataly.com",)}
CHECKPOINT_KEYS = {EATALY}
CHECKPOINT_MANIFEST_LIMITS = {EATALY: 24}
CHECKPOINT_EVENT_LIMITS = {EATALY: 300}
EVENTS_URL = "https://www.eataly.com/c/events-new-york"
MAX_PAGES = 24
MAX_EVENTS = 300
MAX_BYTES = 900_000
MAX_DESCRIPTION = 12_000
# As with the existing Boston Eataly adapter, the worker's time reserve still
# bounds this cap; no host pacing, HTTP timeout or robots policy is changed.
MAX_FETCHES = 12
MIN_SECONDS = 12
VENUES = {
    "ENY 1": ("Eataly NYC Flatiron", "200 5th Avenue, New York, NY 10010", "New York"),
    "USDT-US00_88": ("Eataly NYC Downtown", "101 Liberty Street, New York, NY 10007", "New York"),
    "ELF 1": ("Eataly Soho", "200 Lafayette Street, New York, NY 10012", "New York"),
}
# Exact points carried by the same publisher's structured event/venue objects.
POINTS = {
    "ENY 1": (40.742045, -73.9900845),
    "USDT-US00_88": (40.7103713, -74.0117875),
    "ELF 1": (40.7213863, -73.9981026),
}
NATIVE_STREETS = {
    "ENY 1": {"200 5th avenue"},
    "USDT-US00_88": {"101 liberty street"},
    "ELF 1": {"200 lafayette st", "200 lafayette street"},
}
# The publisher carries two exact geocoded variants for this same street
# address. Normalize both reviewed variants to the current event-venue point.
NATIVE_POINT_VARIANTS = {
    "ELF 1": {
        "200 lafayette st": (40.7213863, -73.9981026),
        "200 lafayette street": (40.7213773, -73.9983436),
    },
}
HOLD_CODES = {
    "new_york_food_description_missing", "new_york_food_description_limit",
    "new_york_food_venue_unresolved", "new_york_food_outside_window",
    "new_york_food_not_public",
}
ERROR_CODES = HOLD_CODES | {
    "unregistered_new_york_food_source", "new_york_food_calendar_changed",
    "new_york_food_detail_changed", "new_york_food_schedule_changed",
    "new_york_food_record_limit", "new_york_food_checkpoint_invalid",
    "new_york_food_checkpoint_size_limit", "new_york_food_checkpoint_required",
    "collection_deadline",
}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()).hexdigest()


def _source(source):
    key = source.get("source_key")
    if key != EATALY or (source.get("feed_url"), source.get("kind"),
                        source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[EATALY], ZONE):
        raise ValueError("unregistered_new_york_food_source")
    return key


def event_url(key, value):
    if key != EATALY or not isinstance(value, str) or len(value) > 1500:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc != "www.eataly.com" or p.fragment
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)
                or not re.fullmatch(r"/p/(?:[a-z0-9-]|%3[Aa]|%7[Cc]|%[Ee]2%80%9[Dd])+\d{10,16}\.html", p.path)):
            return False
        q = parse_qs(p.query, keep_blank_values=True)
        return not p.query or (set(q) == {"eventInstanceId", "eventTicketClassId"}
            and all(len(q[k]) == 1 and re.fullmatch(r"\d{6,16}", q[k][0]) for k in q)
            and len(p.query.split("&")) == 2)
    except ValueError:
        return False


def photo_url(key, value):
    # Eataly's actual product media is under robots-disallowed /on/ paths.
    return None


def reviewed_venue_location(key, venue, address):
    if key == EATALY:
        for store, place in VENUES.items():
            if (venue, address) == place[:2]:
                return POINTS[store]
    return None


def _body(value):
    text = description(str(value or ""), limit=MAX_DESCRIPTION + 1)
    if not text or not re.search(r"[A-Za-z]", text) or re.fullmatch(r"https?://\S+", text):
        raise ValueError("new_york_food_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("new_york_food_description_limit")
    return text


def _page_url(value):
    try:
        p = urlsplit(value)
        q = parse_qs(p.query, keep_blank_values=True)
        return (p.scheme == "https" and p.netloc == "www.eataly.com" and not p.fragment
            and p.path in {"/c/classes-new-york", "/c/events-new-york"}
            and (not p.query or (set(q) == {"page"} and len(q["page"]) == 1
                 and re.fullmatch(r"\d{1,2}", q["page"][0])
                 and 2 <= int(q["page"][0]) <= 12 and "&" not in p.query)))
    except (ValueError, TypeError):
        return False


def _listing(payload, url):
    if not _page_url(url):
        raise ValueError("new_york_food_calendar_changed")
    soup = BeautifulSoup(payload, "html.parser")
    try:
        script = soup.select_one('script#category-schema[type="application/ld+json"]')
        data = json.loads(script.string or script.get_text())
        items = data["mainEntity"]["itemListElement"]
        if data["@type"] != "CollectionPage" or not isinstance(items, list) or len(items) > 30:
            raise ValueError
        queue = []
        for entry in items:
            item = entry["item"]
            if (item.get("@type") != "Product" or not event_url(EATALY, item.get("url"))
                    or urlsplit(item["url"]).query
                    or not re.fullmatch(r"\d{10,16}", item.get("sku", ""))
                    or not urlsplit(item["url"]).path.endswith("-" + item["sku"] + ".html")):
                raise ValueError
            title = plain(item.get("name"))
            if not title or len(title) > 180:
                raise ValueError
            queue.append(dict(url=item["url"], sku=item["sku"], title=title))
        root = urlsplit(url)._replace(query="", fragment="").geturl()
        pages = {root}
        for a in soup.select("a[href]"):
            candidate = urlsplit(urljoin(url, a["href"]))
            if candidate.fragment not in ("", "main-content"):
                continue
            target = candidate._replace(fragment="").geturl()
            if _page_url(target) and candidate.path == urlsplit(root).path:
                last = int(parse_qs(candidate.query).get("page", ["1"])[0])
                pages.update(root + "?page=" + str(n) for n in range(2, last + 1))
        return queue, sorted(pages, key=lambda p: int(parse_qs(urlsplit(p).query).get("page", ["1"])[0]))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("new_york_food_calendar_changed") from None


def _product_fields(soup):
    """Read selected scalar fields from the same bounded inert reference table."""
    marker = "streamController.enqueue("
    wanted = {"id", "name", "longDescription", "shortDescription", "c_url",
              "c_eventInstanceId", "c_eventTicketClassId"}
    for script in soup.select("script"):
        value = script.string or script.get_text()
        if marker not in value:
            continue
        try:
            serialized, _ = json.JSONDecoder().raw_decode(value[value.index(marker) + len(marker):])
            if not isinstance(serialized, str) or not serialized.startswith("["):
                continue
            table = json.loads(serialized)
            if not isinstance(table, list) or len(table) > 15_000:
                raise ValueError
            names = {i: x for i, x in enumerate(table) if isinstance(x, str) and x in wanted}
            instance_keys = {"_" + str(i) for i, x in names.items() if x == "c_eventInstanceId"}
            products = {}
            for obj in table:
                if not isinstance(obj, dict) or not instance_keys.intersection(obj):
                    continue
                fields = {}
                for k, ref in obj.items():
                    if re.fullmatch(r"_\d+", k) and int(k[1:]) in names:
                        if type(ref) is not int or not 0 <= ref < len(table) or not isinstance(table[ref], str):
                            raise ValueError
                        fields[names[int(k[1:])]] = table[ref]
                identity = fields["c_eventInstanceId"] + "-" + fields["c_eventTicketClassId"]
                if fields.get("id") != identity or identity in products and products[identity] != fields:
                    raise ValueError
                products[identity] = fields
            if products:
                return products
        except (ValueError, KeyError, TypeError, IndexError):
            raise ValueError("new_york_food_detail_changed") from None
    raise ValueError("new_york_food_detail_changed")


def _place(native):
    store = native.get("c_eventStoreId")
    if store not in VENUES:
        raise ValueError("new_york_food_venue_unresolved")
    place = VENUES[store]
    if (native.get("c_eventVenueCountry") != "US" or native.get("c_eventVenueCity") != "New York"
            or native.get("c_eventVenueRegion") != "NY"
            or native.get("c_eventVenuePostalCode") != place[1][-5:]
            or plain(native.get("c_eventVenueAddress")).casefold() not in NATIVE_STREETS[store]
            or plain(native.get("c_eventVenueName")).casefold() != place[0].casefold()):
        raise ValueError("new_york_food_venue_unresolved")
    try:
        point = (float(native["c_eventVenueLatitude"]), float(native["c_eventVenueLongitude"]))
        expected_point = NATIVE_POINT_VARIANTS.get(store, {}).get(
            plain(native.get("c_eventVenueAddress")).casefold(), POINTS[store])
        if any(not math.isfinite(v) or abs(v - expected) > 0.000001 for v, expected in zip(point, expected_point)):
            raise ValueError
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("new_york_food_venue_unresolved") from None
    return place, POINTS[store]


def _identity(instance, start):
    return "nyc-food:" + sha256(f"{EATALY}:{instance}:{start}".encode()).hexdigest()


def _detail(item, payload, now):
    try:
        soup, native = _eataly_native(payload)
        products = _product_fields(soup)
        script = soup.select_one('script#product-schema[type="application/ld+json"]')
        product = json.loads(script.string or script.get_text())
        selected = products[product["sku"]]
        if (product.get("@type") != "Product" or _title_key(product.get("name")) != _title_key(item["title"])
                or _body(product.get("description")) != _body(selected.get("longDescription"))
                or product.get("url") != urljoin(item["url"], selected["c_url"])):
            raise ValueError("new_york_food_detail_changed")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError("new_york_food_detail_changed") from None
    except ValueError as exc:
        if str(exc) in HOLD_CODES or str(exc) == "new_york_food_detail_changed":
            raise
        raise ValueError("new_york_food_detail_changed") from None
    if len(native) > 80:
        raise ValueError("new_york_food_record_limit")
    rows, holds, seen = [], [], {}
    for event in native:
        instance, ticket = event.get("c_eventInstanceId"), event.get("c_eventTicketClassId")
        if (not isinstance(instance, str) or not re.fullmatch(r"\d{10,16}", instance)
                or not isinstance(ticket, str) or not re.fullmatch(r"\d{6,16}", ticket)
                or event.get("c_eventId") != instance
                or item["sku"] not in {instance, event.get("c_eventSeriesId")}):
            raise ValueError("new_york_food_detail_changed")
        fields = products.get(instance + "-" + ticket)
        if fields is None or _title_key(fields.get("name")) != _title_key(item["title"]):
            raise ValueError("new_york_food_detail_changed")
        url = urljoin(item["url"], fields["c_url"])
        if (not event_url(EATALY, url) or urlsplit(url).path != urlsplit(item["url"]).path
                or parse_qs(urlsplit(url).query) != {"eventInstanceId": [instance], "eventTicketClassId": [ticket]}):
            raise ValueError("new_york_food_detail_changed")
        try:
            if event.get("c_eventStatus") != "live" or event.get("c_eventOnlineFlag") is not False:
                raise ValueError("new_york_food_not_public")
            start, end = timestamp(event.get("c_eventStartDate")), timestamp(event.get("c_eventEndDate"))
            if (start is None or end is None or start.tzinfo is None or end.tzinfo is None or end <= start):
                raise ValueError("new_york_food_schedule_changed")
            if start >= now + timedelta(days=60) or end <= now:
                raise ValueError("new_york_food_outside_window")
            place, point = _place(event)
            body = _body(fields.get("longDescription"))
            intro = _body(fields["shortDescription"]) if fields.get("shortDescription") else ""
            if intro and not body.startswith(intro):
                body = _body(intro + "\n" + body)
            identity = _identity(instance, start.isoformat())
            row = record(fields["name"], start.isoformat(), end.isoformat(), *place, url, identity,
                         lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
            if row is None:
                raise ValueError("new_york_food_outside_window")
            row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                       source_native_event_id=instance,
                       location_provenance="publisher_structured_address_reviewed_venue_geo",
                       lat=point[0], lng=point[1])
            if row.get("reason") == "missing_verified_venue_geo":
                row["reason"] = None
            # Ticket price classes are the same attendance occurrence only
            # when their complete event semantics agree. Do not lose a second
            # ticket class's narrative merely because its occurrence ID agrees.
            semantic = {k: v for k, v in row.items() if k != "event_url"}
            if identity in seen:
                if seen[identity] != semantic:
                    raise ValueError("new_york_food_detail_changed")
                continue
            seen[identity] = semantic
            rows.append(row)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            holds.append(dict(event_url=url, source_native_event_id=instance,
                              disposition="held", reason=str(exc)))
    return rows, holds


def _pending_valid(item):
    return (isinstance(item, dict) and event_url(EATALY, item.get("url"))
        and not urlsplit(item["url"]).query and isinstance(item.get("sku"), str)
        and re.fullmatch(r"\d{10,16}", item["sku"])
        and urlsplit(item["url"]).path.endswith("-" + item["sku"] + ".html")
        and isinstance(item.get("title"), str) and 1 <= len(item["title"]) <= 180)


def _checkpoint(value, now):
    if value is None:
        return None
    try:
        started = timestamp(value["started_at"])
        if (type(value["version"]) is not int or value["version"] != 1 or value["source_key"] != EATALY
                or started.tzinfo is None or started > now + timedelta(seconds=60)
                or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or not isinstance(value["pages"], list) or not 2 <= len(value["pages"]) <= MAX_PAGES
                or len(set(value["pages"])) != len(value["pages"]) or any(not _page_url(p) for p in value["pages"])
                or value["manifest_count"] != len(value["pages"])
                or type(value["cursor"]) is not int or not 0 <= value["cursor"] <= len(value["pages"])
                or value["manifest_hash"] != _hash({"pages": value["pages"], "seed_hash": value["seed_hash"]})
                or not isinstance(value["pending"], list) or len(value["pending"]) > 30
                or any(not _pending_valid(i) for i in value["pending"])
                or value["pending_hash"] != _hash(value["pending"])
                or type(value["pending_cursor"]) is not int or not 0 <= value["pending_cursor"] <= len(value["pending"])
                or not isinstance(value["events"], list) or len(value["events"]) > MAX_EVENTS
                or not isinstance(value["diagnostics"], list) or len(value["diagnostics"]) > 400
                or len(value["row_hashes"]) != len(value["events"])
                or not isinstance(value["seen_urls"], list) or len(value["seen_urls"]) > MAX_EVENTS
                or len(set(value["seen_urls"])) != len(value["seen_urls"])
                or any(not event_url(EATALY, url) or urlsplit(url).query for url in value["seen_urls"])):
            raise ValueError
        if value["loaded_page"] is not None and (value["cursor"] >= len(value["pages"])
                or value["loaded_page"] != value["pages"][value["cursor"]]):
            raise ValueError
        if value["loaded_page"] is None and (value["pending"] or value["pending_cursor"]):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        seen = set()
        for row in value["events"]:
            point = reviewed_venue_location(EATALY, row["venue_name"], row["venue_address"])
            start, end = timestamp(row["starts_at"]), timestamp(row["ends_at"])
            instance = row["source_native_event_id"]
            if (row["id"] in seen or value["row_hashes"].get(row["id"]) != _hash(row)
                    or not event_url(EATALY, row["event_url"])
                    or urlsplit(row["event_url"])._replace(query="").geturl() not in value["seen_urls"]
                    or parse_qs(urlsplit(row["event_url"]).query).get("eventInstanceId") != [instance]
                    or row["id"] != _identity(instance, start.isoformat())
                    or point is None or (row.get("lat"), row.get("lng")) != point
                    or row.get("venue_city") != "New York" or row.get("timezone") != ZONE
                    or row.get("attendance_mode") != "in_person"
                    or _body(row["description"]) != row["description"]
                    or start.tzinfo is None or end.tzinfo is None or end <= start
                    or start >= started + timedelta(days=60) or end <= started):
                raise ValueError
            seen.add(row["id"])
        for held in value["diagnostics"]:
            if (held.get("reason") not in HOLD_CODES or held.get("disposition") != "held"
                    or not event_url(EATALY, held.get("event_url"))):
                raise ValueError
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError("new_york_food_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=None):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("new_york_food_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, current)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    listing = fetch(SOURCES[EATALY][0], "text/html")
    seed, class_pages = _listing(listing, SOURCES[EATALY][0])
    if "/c/events-new-york" not in listing:
        raise ValueError("new_york_food_calendar_changed")
    seed_hash = _hash({"pages": class_pages, "seed": seed})
    if state is None or state["seed_hash"] != seed_hash:
        pages = class_pages + [EVENTS_URL]
        state = dict(version=1, source_key=EATALY, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     pages=pages, seed_hash=seed_hash, manifest_count=len(pages), cursor=0,
                     manifest_hash=_hash({"pages": pages, "seed_hash": seed_hash}),
                     pending=[], pending_hash=_hash([]), pending_cursor=0, loaded_page=None,
                     events=[], row_hashes={}, diagnostics=[], seen_urls=[])
    anchor = timestamp(state["started_at"])
    prior = (state["cursor"], state["pending_cursor"], len(state["seen_urls"]), state["loaded_page"])
    budget = MAX_FETCHES if max_details is None else min(MAX_FETCHES, max(1, int(max_details)))
    calls = 0
    def can_fetch():
        return calls < budget and (deadline_at is None or monotonic() + MIN_SECONDS < deadline_at)
    while state["cursor"] < len(state["pages"]):
        page = state["pages"][state["cursor"]]
        if state["loaded_page"] != page:
            if page == SOURCES[EATALY][0]:
                queue, discovered = deepcopy(seed), class_pages
            else:
                if not can_fetch():
                    break
                calls += 1
                queue, discovered = _listing(fetch(page, "text/html"), page)
            for target in discovered:
                if target not in state["pages"]:
                    state["pages"].append(target)
            if len(state["pages"]) > MAX_PAGES:
                raise ValueError("new_york_food_record_limit")
            state.update(manifest_count=len(state["pages"]),
                         manifest_hash=_hash({"pages": state["pages"], "seed_hash": seed_hash}),
                         pending=queue, pending_hash=_hash(queue), pending_cursor=0, loaded_page=page)
        if state["pending_cursor"] == len(state["pending"]):
            state.update(cursor=state["cursor"] + 1, pending=[], pending_hash=_hash([]),
                         pending_cursor=0, loaded_page=None)
            continue
        item = state["pending"][state["pending_cursor"]]
        if item["url"] in state["seen_urls"]:
            state["pending_cursor"] += 1
            continue
        if not can_fetch():
            break
        calls += 1
        payload = fetch(item["url"], "text/html")
        try:
            rows, holds = _detail(item, payload, anchor)
            for row in rows:
                if row["id"] in state["row_hashes"]:
                    if state["row_hashes"][row["id"]] != _hash(row):
                        raise ValueError("new_york_food_detail_changed")
                    continue
                state["events"].append(row)
                state["row_hashes"][row["id"]] = _hash(row)
            state["diagnostics"].extend(holds)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=str(exc)))
        state["seen_urls"].append(item["url"])
        state["pending_cursor"] += 1
        if len(state["events"]) > MAX_EVENTS or len(state["seen_urls"]) > MAX_EVENTS or len(state["diagnostics"]) > 400:
            raise ValueError("new_york_food_record_limit")
    complete = state["cursor"] == len(state["pages"])
    if not complete and (state["cursor"], state["pending_cursor"], len(state["seen_urls"]), state["loaded_page"]) == prior:
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("new_york_food_checkpoint_size_limit")
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    return dict(complete=complete, events=deepcopy(rows), checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("new_york_food_checkpoint_required")
    return result["events"]
