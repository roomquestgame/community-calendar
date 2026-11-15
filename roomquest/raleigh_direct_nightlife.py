"""Five first-party Raleigh calendars with complete native event narratives.

The existing worker injects all robots-aware, paced HTTP I/O.  This module only
reads public calendar data and inert JSON-LD; it does not execute publisher JS.
Explicit occurrences are captured completely before any records are returned.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
NEPTUNES = "neptunes_raleigh_nc"
SPORTS = "sports_social_cary_nc"
SLIMS = "slims_dive_bar_raleigh_nc"
HONE = "hone_sharpen_raleigh_nc"
CANNONBALL = "cannonball_music_hall_nc"
SOURCES = {
    NEPTUNES: ("https://www.neptunesraleigh.com/events", "html", "html"),
    SPORTS: ("https://sportsandsocial.com/cary/events/", "html", "html"),
    SLIMS: ("https://slimsraleigh.com/calendar/", "html", "html"),
    HONE: ("https://hone-sharpen.com/", "html", "html"),
    CANNONBALL: ("https://www.cannonballmusichall.com/upcomingshows", "html", "html"),
}
LABELS = {NEPTUNES: "Neptunes", SPORTS: "Sports & Social Cary", SLIMS: "Slim's Dive Bar",
          HONE: "Hone-Sharpen", CANNONBALL: "Cannonball Music Hall"}
VENUES = {
    NEPTUNES: (LABELS[NEPTUNES], "14 W Martin St, Raleigh, NC 27601", "Raleigh"),
    SPORTS: (LABELS[SPORTS], "301 Fenton Gateway Drive, Cary, NC 27511", "Cary"),
    SLIMS: (LABELS[SLIMS], "227 S Wilmington St, Raleigh, NC 27601", "Raleigh"),
    HONE: (LABELS[HONE], "516 N West St, Raleigh, NC 27603", "Raleigh"),
    CANNONBALL: (LABELS[CANNONBALL], "2304 Atlantic Ave, Raleigh, NC 27604", "Raleigh"),
}
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
ALLOWED_HOSTS[CANNONBALL] += ("events.humanitix.com",)
CHECKPOINT_KEYS = set(SOURCES)
TEC_API = {
    SPORTS: "https://sportsandsocial.com/cary/wp-json/tribe/events/v1/events",
    SLIMS: "https://slimsraleigh.com/wp-json/tribe/events/v1/events",
    HONE: "https://hone-sharpen.com/wp-json/tribe/events/v1/events",
}
HUMANITIX_HOST = "https://events.humanitix.com/host/cannonball-music-hall"
MAX_RECORDS = 200
MAX_MANIFEST = 200
MAX_PAGES = 4
MAX_BYTES = 850_000
MAX_FETCHES = 10
MIN_SECONDS = 10
HOLD_CODES = {"raleigh_direct_description_missing", "raleigh_direct_description_limit",
              "raleigh_direct_venue_unresolved", "raleigh_direct_schedule_unresolved",
              "raleigh_direct_nonpublic", "raleigh_direct_outside_window"}
ERROR_CODES = HOLD_CODES | {"unregistered_raleigh_direct_source", "raleigh_direct_calendar_changed",
    "raleigh_direct_detail_changed", "raleigh_direct_record_limit", "raleigh_direct_checkpoint_invalid",
    "raleigh_direct_checkpoint_size_limit", "raleigh_direct_checkpoint_required", "collection_deadline"}
NONPUBLIC = re.compile(r"\b(?:private\s+(?:event|party|class)|closed|cancelled|canceled|postponed)\b", re.I)
WEEKDAYS = {name.lower(): n for n, name in enumerate(
    ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))}
MONTHS = {name.lower(): n for n, name in enumerate(("", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December")) if n}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
PROVENANCE = "reviewed_publisher_street_pending_geocode"


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                             source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_raleigh_direct_source")
    return key


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1500 or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I):
        return None
    try:
        p = urlsplit(value)
        return p if (p.scheme == "https" and not p.username and not p.password and p.port in (None, 443)
                     and not p.fragment and ".." not in p.path.split("/")) else None
    except ValueError:
        return None


def event_url(key, value):
    p = _safe_url(value)
    if not p or key not in SOURCES or p.query:
        return False
    if key == CANNONBALL:
        return p.netloc == "events.humanitix.com" and bool(re.fullmatch(r"/[a-z0-9-]+", p.path))
    if p.netloc != urlsplit(SOURCES[key][0]).netloc:
        return False
    prefix = {NEPTUNES: "/events/", SPORTS: "/cary/event/", SLIMS: "/calendar/", HONE: "/event/"}[key]
    return bool(re.fullmatch(re.escape(prefix) + r"[a-zA-Z0-9-]+(?:/\d{4}-\d{2}-\d{2}(?:/[1-9]\d?)?)?/?", p.path))


def photo_url(key, value):
    p = _safe_url(value)
    if not p:
        return None
    if key == NEPTUNES:
        okay = p.hostname == "images.squarespace-cdn.com" and p.path.startswith("/content/")
    elif key == CANNONBALL:
        okay = p.hostname == "images.humanitix.com" and p.path.startswith("/i/")
    else:
        okay = p.hostname == urlsplit(SOURCES[key][0]).hostname and "/wp-content/uploads/" in p.path
    return value if okay else None


def _body(value):
    if value is not None and not isinstance(value, str):
        raise ValueError("raleigh_direct_calendar_changed")
    text = description(value, limit=12001)
    if len(text) > 12000:
        raise ValueError("raleigh_direct_description_limit")
    if not text or not re.search(r"[A-Za-z]{2}", text):
        raise ValueError("raleigh_direct_description_missing")
    return text


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _occurrence(start, end=None):
    if not start or start.tzinfo is None or end and (end.tzinfo is None or end <= start):
        raise ValueError("raleigh_direct_schedule_unresolved")
    return {"start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat() if end else None}


def _identity(key, item, occurrence):
    return "raleigh:" + sha256(f'{key}:{item["url"]}:{occurrence["start"]}'.encode()).hexdigest()


def _packet(key, url, title, native_id, occurrences, *, body=None, image=None, held=None, detail=False):
    title = plain(title)
    if not event_url(key, url) or not 1 <= len(title) <= 180 or not isinstance(native_id, str) or not native_id:
        raise ValueError("raleigh_direct_calendar_changed")
    if not isinstance(occurrences, list) or len(occurrences) > MAX_RECORDS:
        raise ValueError("raleigh_direct_record_limit")
    for occurrence in occurrences:
        if _occurrence(timestamp(occurrence["start"]), timestamp(occurrence["end"])) != occurrence:
            raise ValueError("raleigh_direct_calendar_changed")
    out = dict(url=url, title=title, native_id=native_id, occurrences=occurrences, detail=bool(detail))
    if body is not None:
        out["body"] = body
    if held:
        out["held"] = held
    if photo := photo_url(key, image):
        out["image"] = photo
    return out


def _street_key(value):
    text = re.sub(r"[^a-z0-9 ]", " ", plain(value).lower())
    for full, short in (("street", "st"), ("avenue", "ave"), ("drive", "dr"), ("north", "n"),
                        ("south", "s"), ("east", "e"), ("west", "w")):
        text = re.sub(r"\b" + full + r"\b", short, text)
    return " ".join(text.split())


def _venue(key, native):
    if not native:
        return
    if not isinstance(native, dict):
        raise ValueError("raleigh_direct_venue_unresolved")
    aliases = {SPORTS: {"sports social cary", "sports and social cary"}, SLIMS: {"slims", "slim s", "slim s dive bar"},
               HONE: {"hone sharpen", "demonstration kitchen"}, NEPTUNES: {"neptunes", "neptunes parlour"},
               CANNONBALL: {"cannonball music hall"}}
    name = _street_key(native.get("venue") or native.get("name"))
    if name and name not in aliases[key]:
        raise ValueError("raleigh_direct_venue_unresolved")
    expected = VENUES[key][1]
    street = native.get("address") or native.get("streetAddress")
    if street and _street_key(str(street).split(",")[0]) != _street_key(expected.split(",")[0]):
        raise ValueError("raleigh_direct_venue_unresolved")
    city = native.get("city") or native.get("addressLocality")
    region = native.get("state") or native.get("stateprovince") or native.get("province") or native.get("addressRegion")
    zipcode = native.get("zip") or native.get("postalCode")
    if (city and plain(city).lower() != VENUES[key][2].lower()
            or region and plain(region).lower() not in {"nc", "north carolina"}
            or zipcode and str(zipcode)[:5] != expected[-5:]):
        raise ValueError("raleigh_direct_venue_unresolved")


def _tec_url(key, now, page=1, overlap=False):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    # TEC rejects the Unix epoch itself as a falsey parsed timestamp. The next
    # day is a valid historical lower bound for every event on these calendars.
    args = {"per_page": 50, "start_date": "1970-01-02 00:00:00" if overlap else str(day - timedelta(days=1)) + " 00:00:00",
            "end_date": str(day + timedelta(days=61)) + " 00:00:00", "status": "publish", "page": page}
    if overlap:
        # end_date filters a series' final date, not just an occurrence in the
        # requested window. Keep the API's normal future horizon for series;
        # starts_before/ends_after express the overlapping-window predicate.
        args.pop("end_date")
        args.update(starts_before=str(day + timedelta(days=61)) + " 00:00:00",
                    ends_after=str(day - timedelta(days=1)) + " 00:00:00")
    return TEC_API[key] + "?" + urlencode(args)


def _clock(day, value):
    word = plain(value).lower().replace(" ", "").replace(".", "")
    if word in {"noon", "midnight"}:
        hour, minute = (12, 0) if word == "noon" else (0, 0)
    else:
        match = re.fullmatch(r"(1[0-2]|[1-9])(?::([0-5]\d))?(am|pm)", word)
        if not match:
            raise ValueError("raleigh_direct_schedule_unresolved")
        hour, minute = int(match[1]) % 12 + (12 if match[3] == "pm" else 0), int(match[2] or 0)
    return timestamp(datetime.combine(day, time(hour, minute)).isoformat(), ZONE)


def _range(day, first, last=None):
    start, end = _clock(day, first), _clock(day, last) if last else None
    if end and end <= start:
        end = _clock(day + timedelta(days=1), last)
    return _occurrence(start, end)


def _sports_occurrences(event, start, end, now, body):
    """Expand only clocks and weekdays explicitly stated by this publisher."""
    text = plain(body)
    title = plain(event.get("title"))
    rules, exceptions = {}, {}
    if title == "Weekend Brunch":
        match = re.search(r"Available every Saturday and Sunday from\s+(\d+(?::\d+)?am)\s*[-–]\s*(\d+(?::\d+)?pm)", text, re.I)
        if match:
            rules = {5: (match[1], match[2]), 6: (match[1], match[2])}
    elif title in {"Monday Night Music Bingo", "Fired Up Wednesday Night Trivia"}:
        weekday = "Monday" if "Monday" in title else "Wednesday"
        matches = re.findall(r"Every\s+" + weekday + r"\s*[,|]\s*(\d{1,2}(?::\d{2})?\s*[AP]M)\b", text, re.I)
        if len(set(x.lower().replace(" ", "") for x in matches)) == 1:
            rules[WEEKDAYS[weekday.lower()]] = (matches[0], None)
    elif title == "Tinsel Tavern Holiday Pop-Up Bar":
        main = re.search(r"Hours of Operation:\s*(.*?)\s*Note:", text, re.I)
        holiday = re.search(r"Holiday Hours:\s*(.*?)\s*Visit the ultimate", text, re.I)
        if main and holiday:
            pattern = r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?:[-–](Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))?:\s*(CLOSED|\d+(?::\d+)?[ap]m\s*[-–]\s*\d+(?::\d+)?[ap]m)"
            matches = list(re.finditer(pattern, main[1], re.I))
            if not matches or plain(re.sub(pattern, "", main[1], flags=re.I)):
                raise ValueError("raleigh_direct_schedule_unresolved")
            for match in matches:
                first, last = WEEKDAYS[match[1].lower()], WEEKDAYS[(match[2] or match[1]).lower()]
                for weekday in range(first, last + 1):
                    if weekday in rules:
                        raise ValueError("raleigh_direct_schedule_unresolved")
                    rules[weekday] = None if match[3].upper() == "CLOSED" else tuple(re.split(r"\s*[-–]\s*", match[3]))
            if set(rules) != set(range(7)):
                raise ValueError("raleigh_direct_schedule_unresolved")
            pattern = r"(?:Thanksgiving|Christmas)\s+(?:Eve|Day)\s*\(([A-Za-z]+)\.?\s+(\d{1,2})\):\s*(CLOSED|\d+(?::\d+)?[ap]m\s*[-–]\s*\d+(?::\d+)?[ap]m)"
            matches = list(re.finditer(pattern, holiday[1], re.I))
            if not matches or plain(re.sub(pattern, "", holiday[1], flags=re.I)):
                raise ValueError("raleigh_direct_schedule_unresolved")
            for match in matches:
                day = date(start.year, MONTHS[match[1].lower()], int(match[2]))
                exceptions[day] = None if match[3].upper() == "CLOSED" else tuple(re.split(r"\s*[-–]\s*", match[3]))
    elif start.date() == end.date():
        # A one-day all-day placeholder may have an explicit main-venue clock.
        match = re.search(r"We[’']ll be open from\s+(\d+(?::\d+)?\s*[ap]m)\s+to\s+(midnight|\d+(?::\d+)?\s*[ap]m)", text, re.I)
        if match:
            rules[start.weekday()] = (match[1], match[2])
    if not rules:
        raise ValueError("raleigh_direct_schedule_unresolved")
    out = []
    day = max(start.date(), now.astimezone(ZoneInfo(ZONE)).date() - timedelta(days=1))
    last = min(end.date(), (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date())
    while day <= last:
        clocks = exceptions.get(day, rules.get(day.weekday()))
        if clocks:
            item = _range(day, *clocks)
            if _within(timestamp(item["start"]), timestamp(item["end"]), now):
                out.append(item)
        day += timedelta(days=1)
    return out


def _tec_listing(key, payload, now):
    try:
        data = json.loads(payload)
        events, total, count = data["events"], data["total"], data["total_pages"]
        if (not isinstance(events, list) or len(events) > 50 or type(total) is not int or not 0 <= total <= MAX_RECORDS
                or type(count) is not int or not 0 <= count <= MAX_PAGES or count != (total + 49) // 50):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("raleigh_direct_calendar_changed") from None
    queue, raw_ids = [], []
    for event in events:
        if not isinstance(event, dict) or type(event.get("id")) is not int:
            raise ValueError("raleigh_direct_calendar_changed")
        raw_ids.append(str(event["id"]))
        title = plain(event.get("title"))
        url = event.get("url")
        if not event_url(key, url):
            raise ValueError("raleigh_direct_calendar_changed")
        if event.get("status") != "publish" or NONPUBLIC.search(title) or event.get("event_status") in {"cancelled", "canceled", "postponed"}:
            continue
        if any(event.get(k) in (True, 1, "1", "true") for k in ("hide_from_listings", "is_virtual", "virtual")):
            continue
        if event.get("timezone") != ZONE:
            raise ValueError("raleigh_direct_calendar_changed")
        try:
            start, end = timestamp(event.get("start_date"), ZONE), timestamp(event.get("end_date"), ZONE)
            if not start or not end or end <= start:
                raise ValueError
            if (timestamp(event.get("utc_start_date"), "UTC") != start
                    or timestamp(event.get("utc_end_date"), "UTC") != end):
                raise ValueError
        except ValueError:
            raise ValueError("raleigh_direct_calendar_changed") from None
        if not _within(start, end, now):
            continue
        if key == SPORTS and end - start > timedelta(hours=24):
            # TEC exposes the same series through both its base permalink and
            # a dated recurrence permalink. Explicit series hours below share
            # one canonical permalink and occurrence identity.
            url = re.sub(r"/\d{4}-\d{2}-\d{2}(?:/[1-9]\d?)?/$", "/", url)
            # Two live TEC posts expose this exact same weekly series. The
            # final row equality check still rejects any narrative/hour drift.
            if url == "https://sportsandsocial.com/cary/event/wednesday-night-trivia-2/":
                url = "https://sportsandsocial.com/cary/event/wednesday-night-trivia/"
        body, held = None, None
        try:
            body = _body(event.get("description"))
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            held = str(exc)
        occurrences = [_occurrence(start, end)]
        try:
            _venue(key, event.get("venue"))
            if event.get("all_day") or end - start > timedelta(hours=24):
                if key != SPORTS or body is None:
                    raise ValueError("raleigh_direct_schedule_unresolved")
                occurrences = _sports_occurrences(event, start, end, now, body)
        except ValueError as exc:
            held = str(exc)
        # Missing prose gets one actual publisher detail read before a hold.
        detail = held == "raleigh_direct_description_missing"
        if detail:
            held = None
        queue.append(_packet(key, url, title, str(event["id"]), occurrences, body=body,
            image=(event.get("image") or {}).get("url") if isinstance(event.get("image"), dict) else None,
            held=held, detail=detail))
    if len(set(raw_ids)) != len(raw_ids):
        raise ValueError("raleigh_direct_calendar_changed")
    return queue, total, count, raw_ids


def _schema_events(soup):
    out = []
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            kind = value.get("@type")
            if kind == "Event" or isinstance(kind, list) and "Event" in kind:
                out.append(value)
            for key in ("@graph", "itemListElement", "item"):
                if key in value:
                    walk(value[key])
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(node.string or node.get_text()))
        except (ValueError, TypeError):
            raise ValueError("raleigh_direct_calendar_changed") from None
    return out


def _tec_detail(key, item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    names = soup.select("h1.tribe-events-single-event-title")
    if not names and key == HONE:
        names = soup.select("h1.entry-title")
    all_schemas = _schema_events(soup)
    schemas = [x for x in all_schemas if x.get("url") == item["url"]]
    if not schemas and key == SLIMS:
        # TEC can put the artist's website in Event.url. The exact canonical
        # permalink and WordPress post ID independently bind this fetched page
        # to the API item; its sole matching event name and clock still apply.
        canonical = [x.get("href") for x in soup.select('link[rel="canonical"]')]
        post_id = "postid-" + item["native_id"]
        if canonical == [item["url"]] and soup.body and post_id in (soup.body.get("class") or []):
            matching = [x for x in all_schemas if plain(x.get("name")) == item["title"]]
            if len(matching) == 1:
                schemas = matching
    if len(names) != 1 or plain(names[0].get_text(" ")) != item["title"] or not schemas:
        raise ValueError("raleigh_direct_detail_changed")
    starts = {timestamp(x.get("startDate")) for x in schemas}
    if any(timestamp(x["start"]) not in starts for x in item["occurrences"]):
        raise ValueError("raleigh_direct_detail_changed")
    blocks = soup.select(".tribe-events-single-event-description.tribe-events-content")
    if not blocks:
        blocks = soup.select(".tribe-events-content:not(#tribe-events-content)")
    if len(blocks) != 1:
        raise ValueError("raleigh_direct_description_missing")
    return _body(str(blocks[0]))


def _neptunes(payload, now):
    try:
        data = json.loads(payload)
        events = data["upcoming"]
        if not isinstance(events, list) or len(events) > MAX_RECORDS or not isinstance(data.get("past"), list):
            raise ValueError
        # Squarespace's separate upcoming array is complete. Its nextPage and
        # offset page through the past array (verified against the live next page).
        if (data.get("collection") or {}).get("urlId") != "events":
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("raleigh_direct_calendar_changed") from None
    queue = []
    for event in events:
        if event.get("recordType") != 12 or event.get("workflowState") != 1:
            raise ValueError("raleigh_direct_calendar_changed")
        start, end = timestamp(event.get("startDate")), timestamp(event.get("endDate"))
        if not start or not end:
            raise ValueError("raleigh_direct_calendar_changed")
        if not _within(start, end, now) or NONPUBLIC.search(plain(event.get("title"))):
            continue
        url = urljoin(SOURCES[NEPTUNES][0], event.get("fullUrl", ""))
        held, body = None, None
        loc = event.get("location") or {}
        try:
            # NYC mapLat/markerLat placeholders are never usable as venue proof.
            _venue(NEPTUNES, {"name": loc.get("addressTitle"), "address": loc.get("addressLine1")})
            body = _body(event.get("body"))
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            held = str(exc)
        queue.append(_packet(NEPTUNES, url, event.get("title"), str(event.get("id", "")),
            [_occurrence(start, end)], body=body, image=event.get("assetUrl"), held=held))
    return queue


def _humanitix_manifest(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    if soup.find(string=re.compile(r"^Load more$", re.I)) or soup.select('[rel="next"]'):
        raise ValueError("raleigh_direct_calendar_changed")
    schemas = _schema_events(soup)
    if not schemas:
        raise ValueError("raleigh_direct_calendar_changed")
    queue, seen = [], set()
    for event in schemas:
        url = event.get("url")
        if url in seen:
            raise ValueError("raleigh_direct_calendar_changed")
        seen.add(url)
        start, end = timestamp(event.get("startDate")), timestamp(event.get("endDate"))
        if not _within(start, end, now):
            continue
        queue.append(_packet(CANNONBALL, url, event.get("name"), url.rsplit("/", 1)[-1],
            [_occurrence(start, end)], image=event.get("image"), detail=True))
    return queue


def _humanitix_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    schemas = _schema_events(soup)
    if not schemas or any(event.get("url") != item["url"] or plain(event.get("name")) != item["title"] for event in schemas):
        raise ValueError("raleigh_direct_detail_changed")
    blocks = soup.select(".EventModuleRichText .RichContent")
    if not blocks:
        raise ValueError("raleigh_direct_description_missing")
    body = _body("\n".join(str(block) for block in blocks))
    occurrences = []
    for event in schemas:
        if event.get("eventStatus", "").rsplit("/", 1)[-1] != "EventScheduled" or event.get("eventAttendanceMode", "").rsplit("/", 1)[-1] != "OfflineEventAttendanceMode":
            continue
        place = event.get("location") or {}
        address = place.get("address") or {}
        _venue(CANNONBALL, dict(address, name=place.get("name")))
        start, end = timestamp(event.get("startDate")), timestamp(event.get("endDate"))
        if _within(start, end, now):
            occurrences.append(_occurrence(start, end))
    if not {x["start"] for x in item["occurrences"]}.issubset({x["start"] for x in occurrences}):
        raise ValueError("raleigh_direct_detail_changed")
    if len({_hash(x) for x in occurrences}) != len(occurrences):
        raise ValueError("raleigh_direct_detail_changed")
    return dict(item, body=body, occurrences=occurrences, detail=False)


def _row(key, item, occurrence):
    if item.get("held"):
        raise ValueError(item["held"])
    body = _body(item.get("body"))
    venue, street, city = VENUES[key]
    row = record(item["title"], occurrence["start"], occurrence["end"], venue, street, city,
        item["url"], _identity(key, item, occurrence), tz=ZONE, retain_until_end=True)
    if row is None:
        raise ValueError("raleigh_direct_outside_window")
    row.update(description=body, timezone=ZONE, attendance_mode="in_person",
               location_provenance=PROVENANCE, location_evidence_url=SOURCES[key][0])
    if item.get("image"):
        row["image_url"] = item["image"]
    return row


def _plans(key, anchor, totals):
    if key not in TEC_API:
        return [SOURCES[NEPTUNES][0] + "?format=json" if key == NEPTUNES else HUMANITIX_HOST]
    out = []
    for group, meta in enumerate(totals):
        out.extend(_tec_url(key, anchor, page, bool(group)) for page in range(1, max(1, meta["pages"]) + 1))
    return out


def _validate_packets(key, items):
    if not isinstance(items, list) or len(items) > MAX_RECORDS:
        raise ValueError("raleigh_direct_record_limit")
    for item in items:
        _packet(key, item["url"], item["title"], item["native_id"], item["occurrences"])
        if item.get("held") is not None and item["held"] not in HOLD_CODES:
            raise ValueError("raleigh_direct_calendar_changed")
        if item.get("body") is not None and _body(item["body"]) != item["body"]:
            raise ValueError("raleigh_direct_calendar_changed")
        if item.get("image") and photo_url(key, item["image"]) != item["image"]:
            raise ValueError("raleigh_direct_calendar_changed")


def _seal(state):
    state["payload_hash"] = _hash({k: v for k, v in state.items() if k != "payload_hash"})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("raleigh_direct_checkpoint_size_limit")
    return state


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or value["payload_hash"] != _hash({k: v for k, v in value.items() if k != "payload_hash"}):
            raise ValueError
        totals = value["totals"]
        expected_groups = 2 if key == SPORTS else 1 if key in TEC_API else 0
        if not isinstance(totals, list) or len(totals) != expected_groups:
            raise ValueError
        for meta in totals:
            if (not isinstance(meta, dict) or set(meta) != {"total", "pages"}
                    or type(meta["total"]) is not int or not 0 <= meta["total"] <= MAX_RECORDS
                    or type(meta["pages"]) is not int or meta["pages"] != (meta["total"] + 49) // 50):
                raise ValueError
        started = timestamp(value["started_at"])
        if (type(value["version"]) is not int or value["version"] != 1 or value["source_key"] != key
                or not started or started.utcoffset() != timedelta(0) or started > now + timedelta(seconds=60)
                or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or value["pages"] != _plans(key, started, value["totals"])
                or value["manifest_hash"] != _hash({"pages": value["pages"], "totals": value["totals"]})
                or type(value["manifest_count"]) is not int or value["manifest_count"] != len(value["pages"])
                or not 1 <= value["manifest_count"] <= MAX_MANIFEST
                or type(value["cursor"]) is not int or not 0 <= value["cursor"] <= value["manifest_count"]
                or type(value["pending_cursor"]) is not int or not 0 <= value["pending_cursor"] <= len(value["pending"])
                or not isinstance(value["events"], list) or not isinstance(value["diagnostics"], list)
                or len(value["events"]) > MAX_RECORDS or len(value["diagnostics"]) > MAX_RECORDS * 2):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        _validate_packets(key, value["pending"])
        loaded = value["loaded_page"]
        if (loaded is not None and (value["cursor"] >= len(value["pages"]) or loaded != value["pages"][value["cursor"]])
                or loaded is None and (value["pending"] or value["pending_cursor"])):
            raise ValueError
        if not isinstance(value["raw_seen"], dict) or set(value["raw_seen"]) - {str(n) for n in range(expected_groups)}:
            raise ValueError
        for group, ids in value["raw_seen"].items():
            if (not isinstance(ids, list) or len(ids) > totals[int(group)]["total"] or len(set(ids)) != len(ids)
                    or any(not isinstance(identity, str) or not re.fullmatch(r"[1-9]\d*", identity) for identity in ids)):
                raise ValueError
        for page, seed in value["seeds"].items():
            if page not in value["pages"]:
                raise ValueError
            _validate_packets(key, seed["items"])
        seen = set()
        for row in value["events"]:
            if (row["id"] in seen or not re.fullmatch(r"raleigh:[a-f0-9]{64}", row["id"])
                    or row["id"] != _identity(key, {"url": row["event_url"]}, {"start": timestamp(row["starts_at"]).astimezone(timezone.utc).isoformat()})
                    or not event_url(key, row["event_url"]) or _body(row["description"]) != row["description"]
                    or (row["venue_name"], row["venue_address"], row["venue_city"]) != VENUES[key]
                    or row.get("lat") is not None or row.get("lng") is not None
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or row.get("location_provenance") != PROVENANCE or row.get("location_evidence_url") != SOURCES[key][0]
                    or row.get("image_url") and photo_url(key, row["image_url"]) != row["image_url"]):
                raise ValueError
            seen.add(row["id"])
        for diagnostic in value["diagnostics"]:
            if not event_url(key, diagnostic["event_url"]) or diagnostic["reason"] not in HOLD_CODES or diagnostic["disposition"] != "held":
                raise ValueError
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError("raleigh_direct_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_fetches=MAX_FETCHES):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("raleigh_direct_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    fetched = 0
    def read(url, accept):
        nonlocal fetched
        if fetched >= max_fetches or deadline_at is not None and monotonic() + MIN_SECONDS >= deadline_at:
            raise ValueError("collection_deadline")
        fetched += 1
        return fetch(url, accept)
    if state is None:
        anchor = current
        seeds, totals = {}, []
        if key in TEC_API:
            # The separate overlapping query includes ongoing series whose
            # original start predates the window; native explicit hours govern
            # expansion, never the months-long placeholder timestamp pair.
            for overlap in ([False, True] if key == SPORTS else [False]):
                url = _tec_url(key, anchor, overlap=overlap)
                items, total, pages, ids = _tec_listing(key, read(url, "application/json"), anchor)
                totals.append(dict(total=total, pages=pages))
                seeds[url] = dict(items=items, ids=ids)
        elif key == NEPTUNES:
            url = SOURCES[key][0] + "?format=json"
            seeds[url] = dict(items=_neptunes(read(url, "application/json"), anchor), ids=[])
        else:
            calendar = read(SOURCES[key][0], "text/html")
            if 'data-collection="cannonball-calendar"' not in calendar:
                raise ValueError("raleigh_direct_calendar_changed")
            seeds[HUMANITIX_HOST] = dict(items=_humanitix_manifest(read(HUMANITIX_HOST, "text/html"), anchor), ids=[])
        pages = _plans(key, anchor, totals)
        state = dict(version=1, source_key=key, started_at=anchor.isoformat(),
            window_start=anchor.astimezone(ZoneInfo(ZONE)).date().isoformat(), pages=pages, totals=totals,
            manifest_hash=_hash(dict(pages=pages, totals=totals)), manifest_count=len(pages), cursor=0,
            seeds=seeds, pending=[], pending_cursor=0, loaded_page=None, raw_seen={},
            events=[], diagnostics=[])
    anchor = timestamp(state["started_at"])
    before = (state["cursor"], state["pending_cursor"], state["loaded_page"])
    while state["cursor"] < state["manifest_count"]:
        page = state["pages"][state["cursor"]]
        if state["loaded_page"] is None:
            if page in state["seeds"]:
                payload = state["seeds"].pop(page)
            else:
                try:
                    items, total, pages, ids = _tec_listing(key, read(page, "application/json"), anchor)
                except ValueError as exc:
                    if str(exc) == "collection_deadline":
                        break
                    raise
                group = 1 if "starts_before=" in page else 0
                if dict(total=total, pages=pages) != state["totals"][group]:
                    raise ValueError("raleigh_direct_calendar_changed")
                payload = dict(items=items, ids=ids)
            if key in TEC_API:
                group = str(1 if "starts_before=" in page else 0)
                seen = state["raw_seen"].setdefault(group, [])
                if set(seen) & set(payload["ids"]):
                    raise ValueError("raleigh_direct_calendar_changed")
                seen.extend(payload["ids"])
            state.update(pending=payload["items"], pending_cursor=0, loaded_page=page)
        if state["pending_cursor"] == len(state["pending"]):
            state.update(cursor=state["cursor"] + 1, pending=[], pending_cursor=0, loaded_page=None)
            continue
        item = deepcopy(state["pending"][state["pending_cursor"]])
        try:
            if item["detail"]:
                detail = read(item["url"], "text/html")
                if key == CANNONBALL:
                    item = _humanitix_detail(item, detail, anchor)
                else:
                    item["body"] = _tec_detail(key, item, detail)
            for occurrence in item["occurrences"]:
                row = _row(key, item, occurrence)
                prior = next((x for x in state["events"] if x["id"] == row["id"]), None)
                if prior is not None and prior != row:
                    raise ValueError("raleigh_direct_calendar_changed")
                if prior is None:
                    state["events"].append(row)
        except ValueError as exc:
            if str(exc) == "collection_deadline":
                break
            if str(exc) not in HOLD_CODES:
                raise
            for occurrence in item["occurrences"]:
                diagnostic = dict(id=_identity(key, item, occurrence), event_url=item["url"], title=item["title"],
                                  starts_at=occurrence["start"], reason=str(exc), disposition="held")
                if diagnostic not in state["diagnostics"]:
                    state["diagnostics"].append(diagnostic)
        state["pending_cursor"] += 1
        if len(state["events"]) > MAX_RECORDS or len(state["diagnostics"]) > MAX_RECORDS * 2:
            raise ValueError("raleigh_direct_record_limit")
    complete = state["cursor"] == state["manifest_count"]
    if complete and key in TEC_API and any(len(state["raw_seen"].get(str(n), [])) != meta["total"] for n, meta in enumerate(state["totals"])):
        raise ValueError("raleigh_direct_calendar_changed")
    if not complete and before == (state["cursor"], state["pending_cursor"], state["loaded_page"]):
        raise ValueError("collection_deadline")
    _seal(state)
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda x: (x["starts_at"], x["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("raleigh_direct_checkpoint_required")
    return result["events"]
