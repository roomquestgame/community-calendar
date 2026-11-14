"""Reviewed Boston venue calendars with complete publisher narratives.

Reuse the shared description cleaner, clock normalizer and event record. The
Squarespace adapters consume normal HTML (their export routes are disallowed).
Google calendar exports and Roundhead's challenge page are explicitly held.
All network reads are delegated to the worker's guarded publisher transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
AERONAUT = "aeronaut_brewing_ma"
NOTCH = "notch_brighton_ma"
REMNANT = "remnant_brewing_ma"
CASTLE = "castle_island_brewing_ma"
BEBOP = "bebop_boston_ma"
LAMPLIGHTER = "lamplighter_brewing_ma"
CLUB = "club_cafe_boston_ma"
MARKET = "boston_public_market_ma"
DORCHESTER = "dorchester_brewing_ma"
PANDEMONIUM = "pandemonium_books_games_ma"
SOURCES = {
    AERONAUT: ("https://www.aeronautbrewing.com/visit/somerville/", "html", "html"),
    NOTCH: ("https://www.notchbrewing.com/brighton-events", "html", "html"),
    REMNANT: ("https://www.remnantsomerville.com/live", "html", "html"),
    CASTLE: ("https://www.castleislandbeer.com/calendar", "html", "html"),
    BEBOP: ("https://www.thebebopboston.com/new-events", "html", "html"),
    LAMPLIGHTER: ("https://lamplighterbrewing.com/collections/events", "html", "html"),
    CLUB: ("https://www.clubcafe.com/club-events/", "html", "html"),
    MARKET: ("https://bostonpublicmarket.org/events/", "html", "html"),
    DORCHESTER: ("https://www.dorchesterbrewing.com/events/", "html", "html"),
    PANDEMONIUM: ("https://pandemoniumbooks.com/apps/bookthatapp/calendar", "html", "html"),
}
LABELS = {AERONAUT: "Aeronaut Brewing Company", NOTCH: "Notch Brewing Brighton",
          REMNANT: "Remnant Brewing & Satellite", CASTLE: "Castle Island Brewing",
          BEBOP: "The Bebop", LAMPLIGHTER: "Lamplighter Brewing Company",
          CLUB: "Club Café Boston", MARKET: "Boston Public Market",
          DORCHESTER: "Dorchester Brewing Company", PANDEMONIUM: "Pandemonium Books & Games"}
AERONAUT_JSON = "https://d3izki9aezxlkr.cloudfront.net/public_events.json"
PANDEMONIUM_SCHEDULE = "https://pandemonium-books-games.bookthatapp.com/availability/schedule.json"
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
ALLOWED_HOSTS[AERONAUT] += ("d3izki9aezxlkr.cloudfront.net",)
ALLOWED_HOSTS[PANDEMONIUM] += ("pandemonium-books-games.bookthatapp.com",)
CHECKPOINT_KEYS = set(SOURCES)
SQUARE = {NOTCH, REMNANT, CASTLE, BEBOP}
SQUARE_SITES = {NOTCH: "5910b112414fb5fd1689da74", REMNANT: "5f8064635ef8ee4fb4a00e97",
                CASTLE: "68137a7ade1b7b4f731c238c", BEBOP: "5938a339db29d6cb76bf2e83"}

# Each address is from the publisher's own venue/contact page. Multi-location
# calendars require a matching event-level location; no publisher HQ fallback.
VENUES = {
    "aeronaut": ("Aeronaut Brewing Company", "14 Tyler Street, Somerville, MA 02143", "Somerville"),
    "notch": ("Notch Brewing Brighton", "525 Western Avenue, Brighton, MA 02135", "Brighton"),
    "remnant": ("Remnant Brewing", "2 Bow Market Way, Somerville, MA 02143", "Somerville"),
    "satellite": ("Remnant Satellite", "877 Cambridge Street, Cambridge, MA 02141", "Cambridge"),
    "castle_southie": ("Castle Island Brewing South Boston", "10 Old Colony Avenue, South Boston, MA 02127", "South Boston"),
    "castle_norwood": ("Castle Island Brewing Norwood", "31 Astor Avenue, Norwood, MA 02062", "Norwood"),
    "bebop": ("The Bebop", "1116 Boylston Street, Boston, MA 02215", "Boston"),
    "lamp_broadway": ("Lamplighter Brewing Broadway", "284 Broadway, Cambridge, MA 02139", "Cambridge"),
    "lamp_cx": ("Lamplighter Brewing CX", "110 North First Street, Cambridge, MA 02141", "Cambridge"),
    "club": ("Club Café", "209 Columbus Avenue, Boston, MA 02116", "Boston"),
    "market": ("Boston Public Market", "100 Hanover Street, Boston, MA 02108", "Boston"),
    "dorchester": ("Dorchester Brewing Company", "1250 Massachusetts Avenue, Boston, MA 02125", "Boston"),
    "pandemonium": ("Pandemonium Books & Games", "4 Pleasant Street, Cambridge, MA 02139", "Cambridge"),
}
VENUE_KEYS = {
    AERONAUT: {"aeronaut"}, NOTCH: {"notch"}, REMNANT: {"remnant", "satellite"},
    CASTLE: {"castle_southie", "castle_norwood"}, BEBOP: {"bebop"},
    LAMPLIGHTER: {"lamp_broadway", "lamp_cx"}, CLUB: {"club"},
    MARKET: {"market"}, DORCHESTER: {"dorchester"}, PANDEMONIUM: {"pandemonium"},
}
# Only street-matching native publisher markers are retained. Squarespace's
# NYC placeholder and Notch's copied Salem marker are deliberately discarded.
POINTS = {"satellite": (42.3727419, -71.0914447),
          "castle_southie": (42.337764, -71.0565789),
          "castle_norwood": (42.1688601, -71.1922675),
          "bebop": (42.3467319, -71.0887255),
          # Exact !3d/!4d target markers in the publisher's Get Directions
          # links, not the different @latitude,longitude map viewport centers.
          # https://lamplighterbrewing.com/pages/110-n-first-street-cx-taproom
          "lamp_cx": (42.372213, -71.0753146),
          # https://www.dorchesterbrewing.com/contact-us/
          "dorchester": (42.322132, -71.0623169)}
MAX_DESCRIPTION = 12000
MAX_EVENTS = 200
MAX_CHECKPOINT_BYTES = 900000
MAX_DETAILS_PER_CHUNK = 5
MIN_DETAIL_SECONDS = 10
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|closure|private (?:party|event))\b", re.I)
ERROR_CODES = {"unregistered_boston_nightlife_source", "boston_nightlife_calendar_changed",
    "boston_nightlife_identity_changed", "boston_nightlife_schedule_changed",
    "boston_nightlife_description_missing", "boston_nightlife_description_limit",
    "boston_nightlife_venue_unresolved", "boston_nightlife_detail_changed",
    "boston_nightlife_record_limit", "boston_nightlife_checkpoint_invalid",
    "boston_nightlife_checkpoint_size_limit", "boston_nightlife_checkpoint_required",
    "collection_deadline"}
HOLD_CODES = {"boston_nightlife_description_missing", "boston_nightlife_description_limit",
              "boston_nightlife_venue_unresolved"}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_boston_nightlife_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1500:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc != urlsplit(SOURCES[key][0]).netloc
                or p.fragment or ".." in p.path.split("/")
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)):
            return False
        if key == AERONAUT:
            return value == SOURCES[key][0]
        if key == CLUB:
            query = parse_qs(p.query)
            return (bool(re.fullmatch(r"/club-events/[a-z0-9-]+/", p.path))
                    and set(query) == {"occurrence"} and len(query["occurrence"]) == 1
                    and bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}", query["occurrence"][0])))
        if p.query:
            return False
        if key in {LAMPLIGHTER, PANDEMONIUM}:
            return bool(re.fullmatch(r"/products/[a-z0-9-]+", p.path))
        prefix = "/bpm-events" if key == MARKET else "/events/event" if key == DORCHESTER else urlsplit(SOURCES[key][0]).path.rstrip("/")
        return bool(re.fullmatch(re.escape(prefix) + r"/[A-Za-z0-9/-]+/?", p.path))
    except (ValueError, KeyError):
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    if value.startswith("//"):
        value = "https:" + value
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
                or p.fragment or ".." in p.path.split("/")):
            return None
        if key == AERONAUT:
            return value if p.netloc == "imagedelivery.net" and re.fullmatch(
                r"/i1GtTC2HMEIvh05dUN1Tag/[0-9a-f-]+/600x450", p.path) and not p.query else None
        if not re.search(r"\.(?:jpe?g|png|webp|avif)$", p.path, re.I):
            return None
        if key in SQUARE and p.netloc == "images.squarespace-cdn.com" and p.path.startswith("/content/v1/") and set(parse_qs(p.query)) <= {"format"}:
            site = SQUARE_SITES.get(key)
            return value if site is None or p.path.startswith("/content/v1/" + site + "/") else None
        if key == LAMPLIGHTER and p.netloc == "lamplighterbrewing.com" and p.path.startswith("/cdn/shop/files/") and set(parse_qs(p.query)) <= {"v", "width"}:
            return value
        if key in {CLUB, MARKET, DORCHESTER} and p.netloc == urlsplit(SOURCES[key][0]).netloc and p.path.startswith("/wp-content/uploads/") and not p.query:
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    for venue_key in VENUE_KEYS.get(key, ()):
        if (venue, address) == VENUES[venue_key][:2]:
            return POINTS.get(venue_key)
    return None


def _validated_body(text):
    if not isinstance(text, str):
        raise ValueError("boston_nightlife_description_missing")
    if not text or not re.search(r"[A-Za-z]", text) or re.fullmatch(
            r"(?:more details to come!?|tickets:?\s*https?://\S+|rsvp(?: here)?)", text, re.I):
        raise ValueError("boston_nightlife_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("boston_nightlife_description_limit")
    return text


def _body(value):
    return _validated_body(description(str(value or ""), limit=MAX_DESCRIPTION + 1))


def _title_key(value):
    return plain(value).translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})).casefold()


def _clock(day, value):
    value = re.sub(r"\s+", "", value).upper()
    fmt = "%H:%M" if re.fullmatch(r"\d{1,2}:\d{2}", value) else "%I:%M%p" if ":" in value else "%I%p"
    try:
        return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)
    except ValueError:
        raise ValueError("boston_nightlife_schedule_changed") from None


def _square_clock(node, suffix):
    nodes = node.select(".event-time-localized-" + suffix + ",.event-time-12hr-" + suffix)
    if not nodes:
        nodes = node.select("time.event-time-localized,time.event-time-12hr")
        if len(nodes) != 2:
            raise ValueError("boston_nightlife_schedule_changed")
        nodes = [nodes[0 if suffix == "start" else 1]]
    values = {_clock(date.fromisoformat(x.get("datetime", "")), x.get_text()) for x in nodes}
    if len(values) != 1:
        raise ValueError("boston_nightlife_schedule_changed")
    return values.pop()


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _item(key, url, title, start, end, venue_key=None, image=None):
    title = plain(title)
    if (not event_url(key, url) or not 1 <= len(title) <= 180 or not start
            or start.tzinfo is None or end and (end.tzinfo is None or end <= start)):
        raise ValueError("boston_nightlife_identity_changed")
    result = dict(url=url, title=title, start=start.isoformat(), end=end.isoformat() if end else None)
    if venue_key:
        if venue_key not in VENUE_KEYS[key]:
            raise ValueError("boston_nightlife_venue_unresolved")
        result["venue_key"] = venue_key
    if photo := photo_url(key, image):
        result["image"] = photo
    return result


def _square_location(key, node):
    loc = node.select_one(".eventlist-meta-address,.eventitem-meta-address")
    name = plain(loc.get_text(" ")).removesuffix("(map)").strip() if loc else ""
    if loc and (label := loc.select_one(".eventitem-meta-address-line--title")):
        name = plain(label.get_text(" "))
    queries = []
    for a in node.select('a[href]'):
        p = urlsplit(a["href"])
        if p.hostname in {"maps.google.com", "www.google.com"}:
            queries.extend(parse_qs(p.query).get("q", []))
    q = " ".join(queries)
    if key == NOTCH and (not q or q == "Notch Brewing" or re.match(r"525\s+Western\b", q, re.I)):
        if not name or name.lower() in {"notch brewing", "notch brewing brighton"}:
            return "notch"
    if key == BEBOP and (not q or re.match(r"1116\s+Boylston\b", q, re.I)):
        if not name or name.lower() == "the bebop":
            return "bebop"
    if key == REMNANT:
        if re.match(r"877\s+Cambridge\b", q, re.I) and "satellite" in name.lower():
            return "satellite"
        if re.match(r"2\s+Bow Market Way\b", q, re.I) and name.lower() == "remnant brewing":
            return "remnant"
    if key == CASTLE:
        if re.match(r"10\s+Old Colony\b", q, re.I) and "south" in name.lower():
            return "castle_southie"
        if re.match(r"31\s+Astor\b", q, re.I) and "norwood" in name.lower():
            return "castle_norwood"
    raise ValueError("boston_nightlife_venue_unresolved")


def _square_manifest(key, soup, now):
    cards = soup.select("article.eventlist-event--upcoming")
    if not soup.select_one(".eventlist"):
        if key == BEBOP:
            return _bebop_manifest(soup, now)
        raise ValueError("boston_nightlife_calendar_changed")
    queue = []
    for card in cards:
        a = card.select_one("a.eventlist-title-link[href]")
        if not a:
            raise ValueError("boston_nightlife_calendar_changed")
        title = plain(a.get_text(" "))
        if NONPUBLIC.search(title):
            continue
        start, end = _square_clock(card, "start"), _square_clock(card, "end")
        if not _within(start, end, now):
            continue
        image = card.select_one("img[data-src],img[src]")
        item = _item(key, urljoin(SOURCES[key][0], a["href"]), title, start, end,
                     image=(image.get("data-src") or image.get("src")) if image else None)
        try:
            item["venue_key"] = _square_location(key, card)
        except ValueError:
            # Detail may carry a missing listing address; hydrate before hold.
            pass
        layouts = card.select(".eventlist-description .sqs-layout")
        if len(layouts) == 1 and not card.select_one(".eventlist-excerpt"):
            try:
                item["body"] = _body(layouts[0])
            except ValueError as exc:
                item["held"] = str(exc)  # Complete native body really is blank.
        queue.append(item)
    return queue


def _bebop_manifest(soup, now):
    queue = []
    for a in soup.select("h1 > a[href]"):
        url = urljoin(SOURCES[BEBOP][0], a["href"])
        if not event_url(BEBOP, url):
            continue
        node = a.find_parent("li")
        if node is None:
            raise ValueError("boston_nightlife_calendar_changed")
        matches = [re.fullmatch(r"([A-Za-z]+, [A-Za-z]+ \d{1,2}, 20\d{2}), (\d{1,2}:\d{2}\s*[AP]M)\s*[–—-]\s*(\d{1,2}:\d{2}\s*[AP]M)", plain(x.get_text(" "))) for x in node.find_all("div", recursive=False)]
        matches = [m for m in matches if m]
        if len(matches) != 1:
            raise ValueError("boston_nightlife_schedule_changed")
        m = matches[0]
        day = datetime.strptime(m[1], "%A, %B %d, %Y").date()
        if not m[1].startswith(day.strftime("%A")):
            raise ValueError("boston_nightlife_schedule_changed")
        start, end = _clock(day, m[2]), _clock(day, m[3])
        if (not _within(start, end, now) or NONPUBLIC.search(a.get_text())
                or re.match(r"No (?:Gypsy Jazz|Bluegrass Jam)\b", plain(a.get_text()), re.I)):
            continue
        item = _item(BEBOP, url, a.get_text(), start, end)
        # Dedicated venue calendar. Reject explicitly different map addresses.
        item["venue_key"] = _square_location(BEBOP, node)
        queue.append(item)
    if not soup.select("h1 > a[href]"):
        raise ValueError("boston_nightlife_calendar_changed")
    return queue


def _aeronaut_manifest(payload, now):
    data = json.loads(payload)
    if not isinstance(data, list) or len(data) > 1000:
        raise ValueError("boston_nightlife_calendar_changed")
    queue = []
    for event in data:
        if not isinstance(event, dict) or event.get("venue_slug") != "somerville":
            continue
        if NONPUBLIC.search(str(event.get("name", ""))):
            continue
        day = date.fromisoformat(event["date"])
        start, end = _clock(day, event["start"]), _clock(day, event["end"]) if event.get("end") else None
        if end and end < start:
            end += timedelta(days=1)
        if not _within(start, end, now):
            continue
        item = _item(AERONAUT, SOURCES[AERONAUT][0], event.get("name"), start, end, "aeronaut", event.get("img_url"))
        try:
            item["body"] = _body(event.get("description"))
        except ValueError as exc:
            item["held"] = str(exc)
        if event.get("category"):
            item["category"] = plain(event["category"])
        queue.append(item)
    return queue


def _lamplighter_manifest(soup, now):
    cards = soup.select("a[data-table-row][href]")
    if not cards:
        raise ValueError("boston_nightlife_calendar_changed")
    queue = []
    for card in cards:
        values = {x["data-index"]: plain(x.get_text(" ")) for x in card.select("[data-index]")}
        if set(values) != {"0", "1", "2", "3"}:
            raise ValueError("boston_nightlife_calendar_changed")
        day = datetime.strptime(values["1"], "%B %d, %Y").date()
        clocks = re.split(r"\s*[-–—]\s*", values["2"])
        if len(clocks) != 2:
            raise ValueError("boston_nightlife_schedule_changed")
        start, end = (_clock(day, x) for x in clocks)
        if not _within(start, end, now) or NONPUBLIC.search(values["0"]):
            continue
        venue = {"284 Broadway": "lamp_broadway", "Lamplighter CX": "lamp_cx"}.get(values["3"])
        image = card.select_one("img[src]")
        item = _item(LAMPLIGHTER, urljoin(SOURCES[LAMPLIGHTER][0], card["href"]), values["0"], start, end, venue,
                     image.get("src") if image else None)
        if not venue:
            item["held"] = "boston_nightlife_venue_unresolved"
        queue.append(item)
    return queue


def _jsonld(soup):
    def walk(value):
        if isinstance(value, list):
            for x in value:
                yield from walk(x)
        elif isinstance(value, dict):
            if value.get("@type") == "Event":
                yield value
            if "@graph" in value:
                yield from walk(value["@graph"])
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def _club_manifest(soup, now):
    events = {e.get("url"): e for e in _jsonld(soup)}
    queue = []
    cards = soup.select("article.mec-event-article")
    if not cards:
        raise ValueError("boston_nightlife_calendar_changed")
    for card in cards:
        a = card.select_one(".mec-event-title a[href]")
        if a is None or a["href"] not in events:
            raise ValueError("boston_nightlife_calendar_changed")
        native = events[a["href"]]
        title = plain(a.get_text(" "))
        if NONPUBLIC.search(title):
            continue
        start_node, end_node = card.select_one(".mec-start-time"), card.select_one(".mec-end-time")
        if not start_node or not end_node:
            raise ValueError("boston_nightlife_schedule_changed")
        start = _clock(date.fromisoformat(native["startDate"]), start_node.get_text())
        end = _clock(date.fromisoformat(native["endDate"]), end_node.get_text())
        if not _within(start, end, now):
            continue
        loc = native.get("location") or {}
        item = _item(CLUB, a["href"], title, start, end, image=native.get("image"))
        if plain(loc.get("address")) == "209 Columbus Avenue, Boston, MA 02116":
            item["venue_key"] = "club"
        else:
            item["held"] = "boston_nightlife_venue_unresolved"
        queue.append(item)
    return queue


def _market_manifest(soup, now):
    nodes = soup.select("[data-eventurl][data-eventid]")
    if not nodes:
        raise ValueError("boston_nightlife_calendar_changed")
    queue = []
    for node in nodes:
        title = node.select_one(".sugar-calendar-block__event-cell__title")
        if title is not None and NONPUBLIC.search(title.get_text()):
            continue
        clocks = node.select("time[datetime]")
        if title is None or len(clocks) != 2:
            raise ValueError("boston_nightlife_schedule_changed")
        start, end = (timestamp(x["datetime"], ZONE) for x in clocks)
        if not _within(start, end, now) or NONPUBLIC.search(title.get_text()):
            continue
        queue.append(_item(MARKET, node["data-eventurl"], title.get_text(), start, end, "market"))
    return queue


def _dorchester_manifest(soup, now):
    cards = soup.select("article.hcalendar")
    if not cards:
        raise ValueError("boston_nightlife_calendar_changed")
    queue = []
    for card in cards:
        a = card.select_one("h3.entry-title a[href]")
        sn, en = card.select_one("abbr.dtstart[title]"), card.select_one("abbr.dtend[title]")
        if not a or not sn or not en:
            raise ValueError("boston_nightlife_calendar_changed")
        start, end = timestamp(sn["title"], ZONE), timestamp(en["title"], ZONE)
        if not _within(start, end, now) or NONPUBLIC.search(a.get_text()):
            continue
        image = card.select_one("img[src]")
        queue.append(_item(DORCHESTER, a["href"], a.get_text(), start, end, "dorchester", image.get("src") if image else None))
    return queue


def _bookthatapp_time(value):
    if not isinstance(value, list) or len(value) != 6 or any(type(x) is not int for x in value):
        raise ValueError("boston_nightlife_schedule_changed")
    try:
        return timestamp(datetime(*value), ZONE)
    except ValueError:
        raise ValueError("boston_nightlife_schedule_changed") from None


def _pandemonium_manifest(payload, now):
    data = json.loads(payload)
    if (not isinstance(data, dict) or not isinstance(data.get("schedule"), list)
            or len(data["schedule"]) > 1000 or not isinstance(data.get("products"), list)
            or not isinstance(data.get("blackouts"), list)):
        raise ValueError("boston_nightlife_calendar_changed")
    products = {p["handle"]: p["id"] for p in data["products"] if isinstance(p, dict) and p.get("handle") and p.get("id")}
    blackouts = []
    for block in data["blackouts"]:
        if (not isinstance(block, dict) or block.get("event_type") != "blackout"
                or block.get("resources") or block.get("locations") or not isinstance(block.get("products"), list)):
            raise ValueError("boston_nightlife_calendar_changed")
        ids = {p.get("externalProductId") for p in block["products"]}
        if None in ids:
            raise ValueError("boston_nightlife_calendar_changed")
        blackouts.append((_bookthatapp_time(block["start"]), _bookthatapp_time(block["end"]), ids))
    queue = []
    for event in data["schedule"]:
        if (not isinstance(event, dict) or event.get("vendor") != "Pandemonium Books & Games"
                or event.get("handle") not in products or event.get("allDay") != 0):
            raise ValueError("boston_nightlife_calendar_changed")
        start, end = _bookthatapp_time(event["start"]), _bookthatapp_time(event["end"])
        if not _within(start, end, now) or NONPUBLIC.search(event.get("title", "")):
            continue
        if any(start < block_end and end > block_start and (not ids or products[event["handle"]] in ids)
               for block_start, block_end, ids in blackouts):
            continue
        url = "https://pandemoniumbooks.com/products/" + event["handle"]
        item = _item(PANDEMONIUM, url, event.get("title"), start, end)
        # The store has one public venue. A future explicitly online/offsite
        # product cannot inherit its street address merely from the publisher.
        if event.get("locations") or re.search(r"\b(?:online|virtual|webcam)\b", item["title"], re.I):
            item["held"] = "boston_nightlife_venue_unresolved"
        else:
            item["venue_key"] = "pandemonium"
        queue.append(item)
    return queue


def _manifest(key, payload, now):
    soup = None if key in {AERONAUT, PANDEMONIUM} else BeautifulSoup(payload, "html.parser")
    queue = (_aeronaut_manifest(payload, now) if key == AERONAUT else
             _pandemonium_manifest(payload, now) if key == PANDEMONIUM else
             _square_manifest(key, soup, now) if key in SQUARE else
             _lamplighter_manifest(soup, now) if key == LAMPLIGHTER else
             _club_manifest(soup, now) if key == CLUB else
             _market_manifest(soup, now) if key == MARKET else _dorchester_manifest(soup, now))
    found = {}
    for item in queue:
        ident = (item["url"], item["start"], item["title"])
        if ident in found and found[ident] != item:
            raise ValueError("boston_nightlife_identity_changed")
        found[ident] = item
    if len(found) > MAX_EVENTS:
        raise ValueError("boston_nightlife_record_limit")
    return sorted(found.values(), key=lambda x: (x["start"], x["url"], x["title"]))


def _detail(key, item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    result = deepcopy(item)
    if key in SQUARE:
        title = soup.select_one("h1.eventitem-title")
        if not title or _title_key(title.get_text()) != _title_key(item["title"]):
            raise ValueError("boston_nightlife_detail_changed")
        start, end = _square_clock(soup, "start"), _square_clock(soup, "end")
        if start != timestamp(item["start"]) or end != timestamp(item["end"]):
            raise ValueError("boston_nightlife_schedule_changed")
        result["venue_key"] = _square_location(key, soup)
        body = soup.select_one(".eventitem-column-content .sqs-layout,.eventitem-content .sqs-layout")
        if body is None:
            body = soup.select_one(".eventitem .sqs-layout")
    elif key == LAMPLIGHTER:
        section = soup.select_one("section[data-product-root][x-data]")
        match = re.search(r"\bproduct:\s*", section["x-data"] if section else "")
        if not match:
            raise ValueError("boston_nightlife_detail_changed")
        product, _ = json.JSONDecoder().raw_decode(section["x-data"][match.end():])
        if (product.get("handle") != urlsplit(item["url"]).path.split("/")[-1]
                or _title_key(product.get("title")) != _title_key(item["title"]) or product.get("type") != "Event"):
            raise ValueError("boston_nightlife_detail_changed")
        body = product.get("description")
    elif key == PANDEMONIUM:
        title, canonical = soup.select_one("h1"), soup.select_one('link[rel="canonical"][href]')
        if (not title or _title_key(title.get_text()) != _title_key(item["title"])
                or not canonical or canonical["href"] != item["url"]):
            raise ValueError("boston_nightlife_detail_changed")
        bodies = soup.select(".product__description")
        if len(bodies) != 1:
            raise ValueError("boston_nightlife_detail_changed")
        body = bodies[0]
    elif key == CLUB:
        title = soup.select_one("h1.mec-single-title")
        if not title or _title_key(title.get_text()) != _title_key(item["title"]):
            raise ValueError("boston_nightlife_detail_changed")
        body = soup.select_one(".mec-single-event-description")
        if body:
            for el in body.select(".custom-share-container,script,style,button"):
                el.decompose()
    elif key == MARKET:
        title = soup.select_one("h1")
        if not title or _title_key(title.get_text()) != _title_key(item["title"]):
            raise ValueError("boston_nightlife_detail_changed")
        body = soup.select_one(".et_pb_post_content,.sc-event-content,.sugar-calendar-event-content,.entry-content")
    else:
        title = soup.select_one(".events-container-single > h2,h1.entry-title,h2.entry-title")
        if not title or _title_key(title.get_text()) != _title_key(item["title"]):
            raise ValueError("boston_nightlife_detail_changed")
        clocks = soup.select(".events-container-single abbr.dtstart[title],.events-container-single abbr.dtend[title]")
        if len(clocks) != 2 or [timestamp(n["title"], ZONE) for n in clocks] != [timestamp(item["start"]), timestamp(item["end"])]:
            raise ValueError("boston_nightlife_schedule_changed")
        body = soup.select_one(".entry-content")
    result["body"] = _body(body)
    if not result.get("venue_key"):
        raise ValueError("boston_nightlife_venue_unresolved")
    return result


def _identity(key, item):
    return "boston:" + sha256(f'{key}:{item["url"]}:{item["start"]}:{item["title"]}'.encode()).hexdigest()


def _row(key, item):
    place = VENUES[item["venue_key"]]
    point = reviewed_venue_location(key, place[0], place[1]) or (None, None)
    row = record(item["title"], item["start"], item.get("end"), *place, item["url"],
                 _identity(key, item), lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row is not None:
        row.update(description=_validated_body(item["body"]), timezone=ZONE, attendance_mode="in_person",
                   location_provenance="reviewed_publisher_street_point" if point[0] is not None else "reviewed_publisher_street_pending_geocode")
        if item.get("image"):
            row["image_url"] = item["image"]
        if item.get("category"):
            row["publisher_categories"] = [item["category"]]
    return row


def _checkpoint(value, key, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get("version") != 1 or value.get("source_key") != key
            or not isinstance(value.get("queue"), list) or len(value["queue"]) > MAX_EVENTS
            or type(value.get("cursor")) is not int or not 0 <= value["cursor"] <= len(value["queue"])
            or value.get("manifest_count") != len(value["queue"])
            or not isinstance(value.get("events"), list) or not isinstance(value.get("diagnostics"), list)
            or len(value["events"]) + len(value["diagnostics"]) != value["cursor"]
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError("boston_nightlife_checkpoint_invalid")
    try:
        started = timestamp(value["started_at"])
        if started.tzinfo is None or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        expected_hash = sha256(json.dumps(value["queue"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if expected_hash != value["manifest_hash"]:
            raise ValueError
        if started > now + timedelta(seconds=60):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        prefix = {_identity(key, item): item for item in value["queue"][:value["cursor"]]}
        covered = set()
        for row in value["events"]:
            native = prefix[row["id"]]
            if row["id"] in covered or not event_url(key, row["event_url"]) or row["event_url"] != native["url"]:
                raise ValueError
            place = (row["venue_name"], row["venue_address"], row["venue_city"])
            allowed_places = {VENUES[k] for k in VENUE_KEYS[key]}
            if (place not in allowed_places or native.get("venue_key") and place != VENUES[native["venue_key"]]
                    or row["title"] != native["title"] or row["starts_at"] != timestamp(native["start"]).astimezone(timezone.utc).isoformat()
                    or row.get("ends_at") != (timestamp(native["end"]).astimezone(timezone.utc).isoformat() if native.get("end") else None)
                    or _validated_body(row["description"]) != row["description"] or native.get("body") and row["description"] != native["body"]
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or (row.get("lat"), row.get("lng")) != (reviewed_venue_location(key, place[0], place[1]) or (None, None))
                    or row.get("image_url") is not None and photo_url(key, row["image_url"]) is None):
                raise ValueError
            covered.add(row["id"])
        for item in value["diagnostics"]:
            if (item.get("id") not in prefix or item["id"] in covered or item.get("event_url") != prefix[item["id"]]["url"]
                    or item.get("disposition") != "held" or item.get("reason") not in HOLD_CODES | {"no_available_future_occurrence"}):
                raise ValueError
            covered.add(item["id"])
        if covered != set(prefix):
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("boston_nightlife_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS_PER_CHUNK):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("boston_nightlife_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(SOURCES[key][0], "text/html")
    if key == AERONAUT:
        if AERONAUT_JSON not in payload:
            raise ValueError("boston_nightlife_calendar_changed")
        payload = fetch(AERONAUT_JSON, "application/json")
    elif key == PANDEMONIUM:
        if PANDEMONIUM_SCHEDULE not in payload:
            raise ValueError("boston_nightlife_calendar_changed")
        day = anchor.astimezone(ZoneInfo(ZONE)).date()
        url = PANDEMONIUM_SCHEDULE + f"?start={day}&end={day + timedelta(days=61)}&calendar=true&show_all_course_occurrences=false"
        payload = fetch(url, "application/json")
    queue = _manifest(key, payload, anchor)
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest or state["queue"] != queue:
        queue = _manifest(key, payload, current)
        digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=digest, manifest_count=len(queue), cursor=0,
                     queue=queue, events=[], diagnostics=[])
    prior, fetched = state["cursor"], 0
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    # BookThatApp explicitly dates each recurrence, while its product page owns
    # one complete narrative. Reuse that narrative within this validated run,
    # including across resumptions, instead of rereading the same product page.
    product_bodies = {(row["event_url"], row["title"]): {"body": row["description"]}
                      for row in state["events"]} if key == PANDEMONIUM else {}
    if key == PANDEMONIUM:
        prefix = {_identity(key, x): x for x in queue[:state["cursor"]]}
        for held in state["diagnostics"]:
            if held["reason"] in {"boston_nightlife_description_missing", "boston_nightlife_description_limit"}:
                native = prefix[held["id"]]
                product_bodies[(native["url"], native["title"])] = {"held": held["reason"]}
    while state["cursor"] < len(queue):
        item = deepcopy(queue[state["cursor"]])
        if key == PANDEMONIUM:
            item.update(product_bodies.get((item["url"], item["title"]), {}))
        needs_detail = "held" not in item and ("body" not in item or "venue_key" not in item)
        if needs_detail and (fetched >= limit or deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at):
            break
        try:
            if item.get("held"):
                raise ValueError(item["held"])
            fetched += int(needs_detail)
            full = _detail(key, item, fetch(item["url"], "text/html")) if needs_detail else item
            if key == PANDEMONIUM:
                product_bodies[(item["url"], item["title"])] = {"body": full["body"]}
            row = _row(key, full)
            if row is None:
                raise ValueError("no_available_future_occurrence")
            state["events"].append(row)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES | {"no_available_future_occurrence"}:
                raise
            if key == PANDEMONIUM and str(exc) in {"boston_nightlife_description_missing", "boston_nightlife_description_limit"}:
                product_bodies[(item["url"], item["title"])] = {"held": str(exc)}
            state["diagnostics"].append(dict(id=_identity(key, item), event_url=item["url"],
                                              disposition="held", reason=str(exc)))
        state["cursor"] += 1
    if state["cursor"] == prior < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("boston_nightlife_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda r: (r["starts_at"], r["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("boston_nightlife_checkpoint_required")
    return result["events"]
