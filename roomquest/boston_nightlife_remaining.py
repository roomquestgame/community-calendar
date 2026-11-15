"""Second Boston cohort: publisher HTML, public calendar data, declared schedules.

Network reads remain on the caller's guarded transport. Eataly has paginated
public catalog HTML; its complete product narratives are hydrated durably.
Waverley Oaks is the venue operator's own tenant calendar, not an aggregator.
Night Shift's explicitly published weekly rules are bounded to 28 days.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.boston_nightlife import (
    _body, _clock, _square_clock, _title_key, _validated_body, _within, NONPUBLIC,
)
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
EATALY = "eataly_boston_ma"
TRILLIUM = "trillium_brewing_ma"
NIGHTSHIFT = "night_shift_brewing_ma"
WAVERLEY = "waverley_oaks_park_ma"
SOURCES = {
    EATALY: ("https://www.eataly.com/c/classes-boston", "html", "html"),
    TRILLIUM: ("https://trilliumbrewing.com/pages/event-calendar", "html", "html"),
    NIGHTSHIFT: ("https://nightshiftbrewing.com/events/", "html", "html"),
    WAVERLEY: ("https://waverleyoakspark.com/events", "html", "html"),
}
LABELS = {EATALY: "Eataly Boston Classes & Events", TRILLIUM: "Trillium Brewing",
          NIGHTSHIFT: "Night Shift Brewing", WAVERLEY: "Waverley Oaks Park"}
SOURCE_NOTES = {
    EATALY: "Both Boston classes and events catalogs. Native UTC clocks corroborated against the organizer's linked Eventbrite listing; full product narrative and native street.",
    TRILLIUM: "Official EventCalendarApp widget; full longDescription, explicit dated occurrences and local/UTC clock agreement. Closures excluded.",
    NIGHTSHIFT: "Publisher-declared weekday/clock schedules expanded at most 28 days, full detail prose, no assumed Run Club end. Conflicting Nerd Night end clocks held.",
    WAVERLEY: "Official property/venue operator's dated tenant calendar, including Mighty Squirrel gaming/run/trivia events. All excerpts hydrate full native details.",
}
ALLOWED_HOSTS = {k: (urlsplit(v[0]).hostname,) for k, v in SOURCES.items()}
ALLOWED_HOSTS[TRILLIUM] += ("api.eventcalendarapp.com", "trillium.eventcalendarapp.com")
CHECKPOINT_KEYS = set(SOURCES)
EATALY_EVENTS = "https://www.eataly.com/c/events-boston"
TRILLIUM_WIDGET = "6336b28e-d559-413b-98dc-1e6ca65c95be"
TRILLIUM_API = "https://api.eventcalendarapp.com/events?id=11960&widgetUuid=" + TRILLIUM_WIDGET
MAX_RECORDS = 200
MAX_PAGES = 12
MAX_BYTES = 900000
MAX_FETCHES = 5
# These two detail-heavy calendars can use more of the existing worker window.
# The pre-fetch reserve and guarded transport still stop a slow publisher early;
# no budget value is serialized, so in-flight version-1 checkpoints remain valid.
SOURCE_FETCH_CAPS = {EATALY: 12, WAVERLEY: 12}
MIN_SECONDS = 10
VENUES = {
    "eataly": ("Eataly Boston", "800 Boylston Street, Boston, MA 02199", "Boston"),
    "canton": ("Trillium Canton", "100 Royall Street, Canton, MA 02021", "Canton"),
    "fort_point": ("Trillium Fort Point", "50 Thomson Place, Boston, MA 02210", "Boston"),
    "fenway": ("Trillium Fenway", "401 Park Drive, Boston, MA 02215", "Boston"),
    "night_shift": ("Night Shift Brewing Everett Taproom", "87 Santilli Highway, Everett, MA 02149", "Everett"),
    "mighty": ("Mighty Squirrel Brewing Co.", "411 Waverley Oaks Road, Waltham, MA 02452", "Waltham"),
    "city_streets": ("City Streets Restaurant", "411 Waverley Oaks Road, Waltham, MA 02452", "Waltham"),
    "birdie": ("Birdie Bar", "411 Waverley Oaks Road, Waltham, MA 02452", "Waltham"),
    "athletic": ("Waverley Oaks Athletic Club", "425 Waverley Oaks Road, Waltham, MA 02452", "Waltham"),
    "beaver": ("Beaver Brook Reservation", "66 Mill Street, Belmont, MA 02478", "Belmont"),
}
VENUE_KEYS = {EATALY: {"eataly"}, TRILLIUM: {"canton", "fort_point", "fenway"},
              NIGHTSHIFT: {"night_shift"}, WAVERLEY: {"mighty", "city_streets", "birdie", "athletic", "beaver"}}
POINTS = {"eataly": (42.34764320000001, -71.0825231)}
HOLD_CODES = {"boston_nightlife_description_missing", "boston_nightlife_description_limit",
              "boston_remaining_venue_unresolved", "boston_remaining_schedule_conflict",
              "boston_remaining_outside_window"}
ERROR_CODES = HOLD_CODES | {"unregistered_boston_remaining_source", "boston_remaining_calendar_changed",
    "boston_remaining_detail_changed", "boston_remaining_schedule_changed", "boston_remaining_record_limit",
    "boston_remaining_checkpoint_invalid", "boston_remaining_checkpoint_size_limit",
    "boston_remaining_checkpoint_required", "collection_deadline"}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_boston_remaining_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1500:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
                or p.fragment or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I) or ".." in p.path.split("/")):
            return False
        if key == TRILLIUM:
            q = parse_qs(p.query)
            return (p.netloc == "trillium.eventcalendarapp.com" and bool(re.fullmatch(r"/[a-z0-9/-]+", p.path))
                    and (not q or set(q) == {"repeatId"} and len(q["repeatId"]) == 1
                         and bool(re.fullmatch(r"r?\d+", q["repeatId"][0]))))
        if p.netloc != urlsplit(SOURCES[key][0]).netloc or p.query:
            return False
        if key == EATALY:
            return bool(re.fullmatch(r"/p/(?:[a-z0-9-]|%3[Aa])+\d{10,16}\.html", p.path))
        return bool(re.fullmatch(r"/events/[a-z0-9/-]+/?", p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or p.fragment or ".." in p.path.split("/"):
            return None
        if key == WAVERLEY and p.netloc == "images.squarespace-cdn.com" and p.path.startswith("/content/v1/622f58aa6c7bcb4b2724bc5c/") and set(parse_qs(p.query)) <= {"format"}:
            return value if re.search(r"\.(?:png|jpe?g|webp)$", p.path, re.I) else None
        if key == NIGHTSHIFT and p.netloc == "nightshiftbrewing.com" and p.path.startswith("/wp-content/uploads/") and not p.query:
            return value if re.search(r"\.(?:png|jpe?g|webp)$", p.path, re.I) else None
        # Eataly's media uses robots-disallowed /on/ routes; leave it unimported.
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    for k in VENUE_KEYS.get(key, ()):
        if (venue, address) == VENUES[k][:2]:
            return POINTS.get(k)
    return None


def _ident(key, item):
    return "boston:" + sha256(f'{key}:{item["url"]}:{item["start"]}:{item["title"]}'.encode()).hexdigest()


def _item(key, url, title, start, end, venue, body=None):
    title = plain(title)
    if (not event_url(key, url) or not 1 <= len(title) <= 180 or start.tzinfo is None
            or end is not None and (end.tzinfo is None or end <= start)):
        raise ValueError("boston_remaining_schedule_changed")
    if venue not in VENUE_KEYS[key]:
        raise ValueError("boston_remaining_venue_unresolved")
    item = dict(url=url, title=title, start=start.isoformat(), end=end.isoformat() if end else None, venue_key=venue)
    if body is not None:
        item["body"] = _body(body)
    return item


def _row(key, item):
    place = VENUES[item["venue_key"]]
    point = reviewed_venue_location(key, *place[:2]) or (None, None)
    row = record(item["title"], item["start"], item.get("end"), *place, item["url"],
                 _ident(key, item), lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row is None:
        raise ValueError("boston_remaining_outside_window")
    row.update(description=_validated_body(item["body"]), timezone=ZONE, attendance_mode="in_person",
               location_provenance="reviewed_publisher_street_point" if point[0] is not None else "reviewed_publisher_street_pending_geocode")
    if item.get("published_schedule"):
        row.update(schedule_provenance="publisher_declared_weekly_schedule", published_schedule=item["published_schedule"], schedule_window_days=28)
    if item.get("image"):
        row["image_url"] = item["image"]
    return row


def _eataly_page_url(value):
    p = urlsplit(value)
    q = parse_qs(p.query)
    return (p.scheme == "https" and p.netloc == "www.eataly.com" and not p.fragment
            and p.path in {"/c/classes-boston", "/c/events-boston"}
            and (not q or set(q) == {"page"} and len(q["page"]) == 1
                 and q["page"][0].isdigit() and 2 <= int(q["page"][0]) <= MAX_PAGES))


def _eataly_listing(payload, url):
    soup = BeautifulSoup(payload, "html.parser")
    script = soup.select_one('script#category-schema[type="application/ld+json"]')
    try:
        data = json.loads(script.string or script.get_text())
        items = data["mainEntity"]["itemListElement"]
        if data["@type"] != "CollectionPage" or not isinstance(items, list) or len(items) > 30:
            raise ValueError
        queue = []
        for item in items:
            item = item["item"]
            if (item.get("@type") != "Product" or not event_url(EATALY, item.get("url"))
                    or not re.fullmatch(r"\d{10,16}", item.get("sku", ""))
                    or not item["url"].endswith("-" + item["sku"] + ".html")):
                raise ValueError
            queue.append(dict(url=item["url"], title=plain(item["name"]), sku=item["sku"]))
        pages = {urlsplit(url)._replace(query="").geturl()}
        for a in soup.select('a[href]'):
            target = urljoin(url, a["href"])
            if _eataly_page_url(target) and urlsplit(target).path == urlsplit(url).path:
                page = int(parse_qs(urlsplit(target).query).get("page", ["1"])[0])
                pages.update(urlsplit(url)._replace(query="page=" + str(n)).geturl() for n in range(2, page + 1))
        if len(pages) > MAX_PAGES:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("boston_remaining_calendar_changed") from None
    return queue, sorted(pages, key=lambda u: int(parse_qs(urlsplit(u).query).get("page", ["1"])[0]))


def _eataly_native(payload):
    """Decode only inert JSON's scalar event fields; never evaluate page scripts."""
    soup = BeautifulSoup(payload, "html.parser")
    marker = "streamController.enqueue("
    for script in soup.select("script"):
        value = script.string or script.get_text()
        if marker not in value:
            continue
        try:
            serialized, _ = json.JSONDecoder().raw_decode(value[value.index(marker) + len(marker):])
            if not isinstance(serialized, str) or not serialized.startswith("["):
                continue
            table = json.loads(serialized)
            if not isinstance(table, list) or len(table) > 15000:
                raise ValueError
            keys = {i: x for i, x in enumerate(table) if isinstance(x, str) and x.startswith("c_event")}
            start_keys = {"_" + str(i) for i, name in keys.items() if name == "c_eventStartDate"}
            native = []
            for obj in table:
                if not isinstance(obj, dict) or not start_keys.intersection(obj):
                    continue
                event = {}
                for k, ref in obj.items():
                    if re.fullmatch(r"_\d+", k) and int(k[1:]) in keys:
                        if type(ref) is not int or not 0 <= ref < len(table):
                            raise ValueError
                        event[keys[int(k[1:])]] = table[ref]
                native.append(event)
            if native:
                return soup, native
        except (ValueError, TypeError, IndexError):
            raise ValueError("boston_remaining_detail_changed") from None
    raise ValueError("boston_remaining_detail_changed")


def _eataly_detail(item, payload, now):
    soup, native = _eataly_native(payload)
    script = soup.select_one('script#product-schema[type="application/ld+json"]')
    product = json.loads(script.string or script.get_text()) if script else {}
    matches = [e for e in native if e.get("c_eventId") == item["sku"] and e.get("c_eventInstanceId") == item["sku"]
               and product.get("sku") == item["sku"] + "-" + str(e.get("c_eventTicketClassId"))]
    if len(matches) != 1:
        raise ValueError("boston_remaining_detail_changed")
    e = matches[0]
    if (_title_key(product.get("name")) != _title_key(item["title"])
            or not str(product.get("sku", "")).startswith(item["sku"] + "-")
            or e.get("c_eventStatus") != "live" or e.get("c_eventOnlineFlag") is not False):
        raise ValueError("boston_remaining_detail_changed")
    if (e.get("c_eventStoreId") != "EBO 1" or e.get("c_eventVenueCity") != "Boston"
            or e.get("c_eventVenueRegion") != "MA" or e.get("c_eventVenuePostalCode") != "02199"
            or not re.fullmatch(r"800 Boylston (?:Street|St\.?)", str(e.get("c_eventVenueAddress", "")), re.I)):
        raise ValueError("boston_remaining_venue_unresolved")
    start, end = timestamp(e["c_eventStartDate"]), timestamp(e["c_eventEndDate"])
    if not _within(start, end, now):
        raise ValueError("boston_remaining_outside_window")
    # The organizer's Eventbrite page corroborates these UTC fields. The new
    # Eataly renderer displays their clock face without converting the zone.
    body = _body(product.get("description"))
    lead = soup.select_one("h2.heading-title-l")
    if lead:
        lead_text = _body(lead)
        if not body.startswith(lead_text):
            body = _validated_body(lead_text + "\n" + body)
    result = _item(EATALY, item["url"], item["title"], start, end, "eataly")
    result["body"] = body
    return [result]


def _waverley_venue(node):
    loc = node.select_one(".eventlist-meta-address,.eventitem-meta-address")
    if not loc:
        raise ValueError("boston_remaining_venue_unresolved")
    label = loc.select_one(".eventitem-meta-address-line--title")
    name = plain(label.get_text() if label else loc.get_text(" ")).removesuffix("(map)").strip()
    maps = [parse_qs(urlsplit(a["href"]).query).get("q", [""])[0] for a in loc.select('a[href]')
            if urlsplit(a["href"]).hostname in {"maps.google.com", "www.google.com"}]
    for key in VENUE_KEYS[WAVERLEY]:
        venue, address, city = VENUES[key]
        if name == venue and len(maps) == 1 and maps[0].startswith(address.split(",")[0] + " ") and city in maps[0]:
            return key
    raise ValueError("boston_remaining_venue_unresolved")


def _waverley_listing(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    if not soup.select_one(".eventlist"):
        raise ValueError("boston_remaining_calendar_changed")
    queue = []
    for card in soup.select("article.eventlist-event--upcoming"):
        a = card.select_one("a.eventlist-title-link[href]")
        if not a:
            raise ValueError("boston_remaining_calendar_changed")
        title = plain(a.get_text())
        if NONPUBLIC.search(title):
            continue
        start, end = _square_clock(card, "start"), _square_clock(card, "end")
        if not _within(start, end, now):
            continue
        item = _item(WAVERLEY, urljoin(SOURCES[WAVERLEY][0], a["href"]), title, start, end, _waverley_venue(card))
        img = card.select_one("img[data-src]")
        if img and (url := photo_url(WAVERLEY, img["data-src"])):
            item["image"] = url
        queue.append(item)
    return queue


def _waverley_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    title = soup.select_one("h1.eventitem-title")
    if not title or _title_key(title.get_text()) != _title_key(item["title"]):
        raise ValueError("boston_remaining_detail_changed")
    if (_square_clock(soup, "start") != timestamp(item["start"]) or _square_clock(soup, "end") != timestamp(item["end"])):
        raise ValueError("boston_remaining_schedule_changed")
    result = deepcopy(item)
    result["venue_key"] = _waverley_venue(soup)
    if result["venue_key"] != item["venue_key"]:
        raise ValueError("boston_remaining_venue_unresolved")
    result["body"] = _body(soup.select_one(".eventitem-column-content .sqs-layout,.eventitem-content .sqs-layout"))
    return [result]


def _trillium_url(now):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    return TRILLIUM_API + f"&viewmode=grid&start={int(start.timestamp())}&end={int((start + timedelta(days=61)).timestamp())}"


def _trillium_listing(payload, now):
    data = json.loads(payload)
    if (not isinstance(data, dict) or data.get("errors") or data.get("pages", {}).get("total") != 1
            or not isinstance(data.get("events"), list) or len(data["events"]) > MAX_RECORDS):
        raise ValueError("boston_remaining_calendar_changed")
    queue = []
    for e in data["events"]:
        title = plain(e.get("summary"))
        if NONPUBLIC.search(title):
            continue
        if e.get("onlineEvent") or e.get("isAllDayEvent") or e.get("timezone") not in {ZONE, "US/Eastern"}:
            raise ValueError("boston_remaining_schedule_changed")
        start = datetime.fromtimestamp(e["utcStartTime"], timezone.utc)
        end = datetime.fromtimestamp(e["utcEndTime"], timezone.utc)
        if start != timestamp(e["timezoneStart"], ZONE) or end != timestamp(e["timezoneEnd"], ZONE):
            raise ValueError("boston_remaining_schedule_changed")
        if not _within(start, end, now):
            continue
        loc = plain((e.get("location") or {}).get("description"))
        place = (e.get("venueName") or loc).casefold()
        venue = "canton" if place == "trillium canton" or loc == "100 Royall St. Canton, MA 02021" else "fort_point" if place == "trillium fort point" else "fenway" if place == "trillium fenway" else None
        item = dict(url=e.get("url"), title=title, start=start.isoformat(), end=end.isoformat())
        if not event_url(TRILLIUM, item["url"]):
            raise ValueError("boston_remaining_calendar_changed")
        try:
            if not venue:
                raise ValueError("boston_remaining_venue_unresolved")
            item = _item(TRILLIUM, item["url"], title, start, end, venue, e.get("longDescription"))
            if re.fullmatch(r"Details coming soon!?", item["body"], re.I):
                raise ValueError("boston_nightlife_description_missing")
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            item["held"] = str(exc)
        queue.append(item)
    return queue


def _nightshift_listing(payload):
    soup = BeautifulSoup(payload, "html.parser")
    cards = soup.select("article.type-event")
    if not cards:
        raise ValueError("boston_remaining_calendar_changed")
    queue = []
    for card in cards:
        a = card.select_one("h3.entry-title a[href]")
        values = [plain(x.get_text()) for x in card.select(".event-location-time-container .element-text")]
        if not a or len(values) != 2 or not event_url(NIGHTSHIFT, a["href"]):
            raise ValueError("boston_remaining_calendar_changed")
        title = plain(a.get_text())
        if NONPUBLIC.search(title):
            continue
        item = dict(url=a["href"], title=title, schedule=values[0], location=values[1])
        if values[1] != "Everett Taproom":
            item["held"] = "boston_remaining_venue_unresolved"
        queue.append(item)
    return queue


def _schedule_key(value):
    return re.sub(r"\s+", "", value).replace("–", "-").replace("—", "-").casefold()


def _nightshift_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.select_one("main article.single-content-event")
    title = main.select_one("h1.entry-title") if main else None
    if not title or _title_key(title.get_text()) != _title_key(item["title"]):
        raise ValueError("boston_remaining_detail_changed")
    values = [plain(n.get_text()) for n in main.select(".event-location-time-container .element-text")]
    if len(values) != 2 or _schedule_key(values[0]) != _schedule_key(item["schedule"]) or values[1] != item["location"]:
        raise ValueError("boston_remaining_schedule_changed")
    body = _body(main.select_one(".element-wysiwyg"))
    if NONPUBLIC.search(body):
        raise ValueError("boston_remaining_schedule_conflict")
    # Explicit current prose contradicts the calendar's 9pm end. Do not pick
    # either end or discard contradictory native prose to make it publishable.
    if item["title"] == "Nerd Night" and re.search(r"4\s*[–—-]\s*7\s*PM", body, re.I):
        raise ValueError("boston_remaining_schedule_conflict")
    recurring = re.fullmatch(r"Every (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (\d{1,2}:\d{2})(?:\s*[-–—]\s*(\d{1,2}:\d{2}))?\s*(AM|PM)", item["schedule"], re.I)
    dates = []
    if recurring:
        known = {"Trivia": ("Monday", "7:30", "9:30", "PM"), "Run Club": ("Saturday", "11:30", None, "AM"),
                 "Nerd Night": ("Sunday", "4:00", "9:00", "PM")}
        if tuple(recurring.groups()) != known.get(item["title"]):
            raise ValueError("boston_remaining_schedule_changed")
        weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].index(recurring[1])
        day = now.astimezone(ZoneInfo(ZONE)).date()
        dates = [day + timedelta(days=n) for n in range(29) if (day + timedelta(days=n)).weekday() == weekday]
        start_clock, end_clock = recurring[2] + recurring[4], recurring[3] + recurring[4] if recurring[3] else None
    else:
        match = re.fullmatch(r"([A-Za-z]+), ([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)?, (\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})(AM|PM)", item["schedule"])
        if not match:
            raise ValueError("boston_remaining_schedule_changed")
        # The event's native article publication supplies its omitted year.
        years = []
        for script in soup.select('script[type="application/ld+json"]'):
            graph = json.loads(script.string or script.get_text()).get("@graph", [])
            years.extend(timestamp(x["datePublished"]).year for x in graph if x.get("@type") == "WebPage" and x.get("url") == item["url"] and x.get("datePublished"))
        if len(set(years)) != 1:
            raise ValueError("boston_remaining_schedule_changed")
        day = datetime.strptime(f"{match[2]} {match[3]} {years[0]}", "%B %d %Y").date()
        if day.strftime("%A") != match[1]:
            raise ValueError("boston_remaining_schedule_changed")
        dates = [day]
        start_clock, end_clock = match[4] + match[6], match[5] + match[6]
    results = []
    for day in dates:
        start = _clock(day, start_clock)
        end = _clock(day, end_clock) if end_clock else None
        if not _within(start, end, now) or recurring and start >= now + timedelta(days=28):
            continue
        native = _item(NIGHTSHIFT, item["url"], item["title"], start, end, "night_shift")
        native["body"] = body
        if recurring:
            native["published_schedule"] = item["schedule"]
        results.append(native)
    return results


def _seed(key, payload, now):
    if key == EATALY:
        queue, pages = _eataly_listing(payload, SOURCES[key][0])
        if EATALY_EVENTS.replace("https://www.eataly.com", "") not in payload:
            raise ValueError("boston_remaining_calendar_changed")
        pages.append(EATALY_EVENTS)
    elif key == WAVERLEY:
        pages, queue = [SOURCES[key][0]], _waverley_listing(payload, now)
    elif key == NIGHTSHIFT:
        pages, queue = [SOURCES[key][0]], _nightshift_listing(payload)
    else:
        if TRILLIUM_WIDGET not in payload or "window.eventCalId=11960" not in payload:
            raise ValueError("boston_remaining_calendar_changed")
        pages, queue = [_trillium_url(now)], []
    return pages, queue


def _page(key, url, payload, now):
    if key == EATALY:
        return _eataly_listing(payload, url)[0]
    if key == WAVERLEY:
        return _waverley_listing(payload, now)
    if key == NIGHTSHIFT:
        return _nightshift_listing(payload)
    return _trillium_listing(payload, now)


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        started = timestamp(value["started_at"])
        if (value["version"] != 1 or value["source_key"] != key or started.tzinfo is None
                or started > now + timedelta(seconds=60) or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or not isinstance(value["pages"], list) or not 1 <= len(value["pages"]) <= MAX_PAGES + 1
                or value["manifest_count"] != len(value["pages"]) or type(value["cursor"]) is not int
                or not 0 <= value["cursor"] <= len(value["pages"])
                or value["manifest_hash"] != _hash({"pages": value["pages"], "seed": value["seed"]})
                or not isinstance(value["pending"], list) or len(value["pending"]) > MAX_RECORDS
                or value["pending_hash"] != _hash(value["pending"]) or type(value["pending_cursor"]) is not int
                or not 0 <= value["pending_cursor"] <= len(value["pending"])
                or len(value["events"]) > MAX_RECORDS or len(value["diagnostics"]) > 400
                or len(value["row_hashes"]) != len(value["events"])):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        places = {VENUES[k] for k in VENUE_KEYS[key]}
        seen = set()
        for row in value["events"]:
            place = (row["venue_name"], row["venue_address"], row["venue_city"])
            if (row["id"] in seen or value["row_hashes"].get(row["id"]) != _hash(row)
                    or not event_url(key, row["event_url"]) or place not in places
                    or _validated_body(row["description"]) != row["description"]
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or (row.get("lat"), row.get("lng")) != (reviewed_venue_location(key, *place[:2]) or (None, None))):
                raise ValueError
            seen.add(row["id"])
        if any(x.get("reason") not in HOLD_CODES or not event_url(key, x.get("event_url")) for x in value["diagnostics"]):
            raise ValueError
        if any(not event_url(key, x.get("url")) for x in value["pending"]):
            raise ValueError
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError("boston_remaining_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("boston_remaining_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    listing = fetch(SOURCES[key][0], "text/html")
    pages, seed_queue = _seed(key, listing, anchor)
    digest = _hash({"pages": pages, "seed": seed_queue})
    if state is None or state["manifest_hash"] != digest or state["pages"] != pages or state["seed"] != seed_queue:
        anchor = current
        pages, seed_queue = _seed(key, listing, anchor)
        digest = _hash({"pages": pages, "seed": seed_queue})
        state = dict(version=1, source_key=key, started_at=anchor.isoformat(),
                     window_start=anchor.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=digest, manifest_count=len(pages), cursor=0, pages=pages, seed=seed_queue,
                     pending=[], pending_hash=_hash([]), pending_cursor=0, loaded_page=None,
                     events=[], row_hashes={}, diagnostics=[], seen_urls=[])
    prior = (state["cursor"], state["pending_cursor"], len(state["events"]), len(state["diagnostics"]))
    calls = 0
    cap = SOURCE_FETCH_CAPS.get(key, MAX_FETCHES)
    budget = cap if max_details is None else min(cap, max(1, int(max_details)))
    def can_fetch():
        return calls < budget and (deadline_at is None or monotonic() + MIN_SECONDS < deadline_at)
    while state["cursor"] < len(pages):
        page_url = pages[state["cursor"]]
        if state["loaded_page"] != page_url:
            if page_url == SOURCES[key][0]:
                queue = deepcopy(seed_queue)
            else:
                if not can_fetch():
                    break
                calls += 1
                queue = _page(key, page_url, fetch(page_url, "application/json" if key == TRILLIUM else "text/html"), anchor)
            if len(queue) > MAX_RECORDS:
                raise ValueError("boston_remaining_record_limit")
            state.update(pending=queue, pending_hash=_hash(queue), pending_cursor=0, loaded_page=page_url)
        queue = state["pending"]
        if state["pending_cursor"] == len(queue):
            state.update(cursor=state["cursor"] + 1, pending=[], pending_hash=_hash([]), pending_cursor=0, loaded_page=None)
            continue
        item = queue[state["pending_cursor"]]
        if key == EATALY and item["url"] in state["seen_urls"]:
            state["pending_cursor"] += 1
            continue
        needs_detail = key != TRILLIUM and not item.get("held")
        if needs_detail and not can_fetch():
            break
        try:
            if item.get("held"):
                raise ValueError(item["held"])
            if needs_detail:
                calls += 1
                detail = fetch(item["url"], "text/html")
                items = (_eataly_detail(item, detail, anchor) if key == EATALY else
                         _waverley_detail(item, detail) if key == WAVERLEY else _nightshift_detail(item, detail, anchor))
            else:
                items = [item]
            if not items:
                raise ValueError("boston_remaining_outside_window")
            for native in items:
                row = _row(key, native)
                if row["id"] not in state["row_hashes"]:
                    state["events"].append(row)
                    state["row_hashes"][row["id"]] = _hash(row)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], title=item["title"], reason=str(exc), disposition="held"))
        state["seen_urls"].append(item["url"])
        state["pending_cursor"] += 1
        if len(state["events"]) > MAX_RECORDS:
            raise ValueError("boston_remaining_record_limit")
    complete = state["cursor"] == len(pages)
    after = (state["cursor"], state["pending_cursor"], len(state["events"]), len(state["diagnostics"]))
    if not complete and after == prior:
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("boston_remaining_checkpoint_size_limit")
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda x: (x["starts_at"], x["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("boston_remaining_checkpoint_required")
    return result["events"]
