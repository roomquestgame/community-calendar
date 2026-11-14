"""Additional Atlantic City venue calendars with complete publisher narratives.

Hard Rock Cafe's native iCalendar is the dated manifest, but its descriptions
are excerpts and its generated UIDs are unstable. Details supply the full prose;
eventid plus date supplies stable identity. A complete-only checkpoint keeps the
37+ detail fetches inside the existing worker budget.

Garden State publishes complete calendar data in its own linked GoDaddy bundle.
Decode the JSON literals as data (never execute JavaScript), and use only dated
manual events belonging to the calendar widgets visible on the publisher page.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import plain, record, timestamp


ZONE = "America/New_York"
HARD_ROCK = "hard_rock_cafe_atlantic_city_nj"
GARDEN = "garden_state_beer_company_nj"
HARD_ROCK_URL = "https://cafe.hardrock.com/atlantic-city/event-calendar.aspx"
GARDEN_URL = "https://gardenstatebeerco.com/whats-happening%3F"
SOURCES = {HARD_ROCK: (HARD_ROCK_URL, "html", "html"),
           GARDEN: (GARDEN_URL, "html", "html")}
ALLOWED_HOSTS = {HARD_ROCK: ("cafe.hardrock.com",),
                 GARDEN: ("gardenstatebeerco.com", "img1.wsimg.com")}
CHECKPOINT_KEYS = {HARD_ROCK}
# Exact venue streets from https://cafe.hardrock.com/atlantic-city/ and
# https://gardenstatebeerco.com/contact, reviewed November 14, 2026.
# The Hard Rock feed retains the former hotel name and loses the ZIP's zero;
# these are venue-specific repairs, never a calendar search-center fallback.
VENUES = {
    HARD_ROCK: ("Hard Rock Cafe Atlantic City", "1000 Boardwalk, Atlantic City, NJ 08401", "Atlantic City"),
    GARDEN: ("Garden State Beer Company", "247 E White Horse Pike, Galloway, NJ 08205", "Galloway"),
}
GARDEN_SITE = "39be5fd2-002c-42cf-85d6-4fb824b97fe9"
GARDEN_PAGE = "bce4bf58-ca53-4f69-a979-1aea4c5d1c39"
UUID = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
MAX_EVENTS = 150
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900_000
MAX_DETAILS_PER_CHUNK = 6
MIN_DETAIL_SECONDS = 18
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|closed|private event|private party)\b", re.I)


def event_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return False
    if key == GARDEN:
        return value == GARDEN_URL
    if key != HARD_ROCK:
        return False
    try:
        p = urlsplit(value)
        q = parse_qs(p.query)
        if (p.scheme != "https" or p.netloc != "cafe.hardrock.com" or p.fragment
                or p.path != "/atlantic-city/event-calendar.aspx"
                or set(q) != {"date", "display", "eventid"}
                or any(len(v) != 1 for v in q.values()) or q["display"] != ["event"]
                or not re.fullmatch(r"[1-9][0-9]{0,9}", q["eventid"][0])
                or not re.fullmatch(r"\d{1,2}/\d{1,2}/20\d{2}", q["date"][0])):
            return False
        datetime.strptime(q["date"][0], "%m/%d/%Y")
        return True
    except (ValueError, TypeError):
        return False


def photo_url(key, value):
    if key != HARD_ROCK or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme == "https" and p.netloc == "cafe.hardrock.com"
                and not p.query and not p.fragment
                and re.fullmatch(r"/atlantic-city/files/[0-9]+/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)", p.path, re.I)):
            return value
    except ValueError:
        pass
    return None


def _source(source, key):
    if (key not in SOURCES or (source.get("source_key"), source.get("feed_url"),
            source.get("kind"), source.get("platform_adapter"), source.get("timezone"))
            != (key, *SOURCES[key], ZONE)):
        raise ValueError("unregistered_atlantic_nightlife_source")


def _text(value):
    text = "\n".join(re.sub(r"[\t\r\f\v ]+", " ", line).strip()
                     for line in str(value or "").splitlines() if line.strip())
    if not text:
        raise ValueError("atlantic_nightlife_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("atlantic_city_description_limit")
    return text


def _clock(day, value):
    value = re.sub(r"\s+", "", value).upper()
    fmt = "%I:%M%p" if ":" in value else "%I%p"
    return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _row(key, title, start, end, url, identity, body, category="", image=None):
    if not event_url(key, url) or not title or len(title) > 180 or end <= start:
        raise ValueError("atlantic_nightlife_event_identity")
    venue, address, city = VENUES[key]
    row = record(title, start.isoformat(), end.isoformat(), venue, address, city,
                 url, identity, category, tz=ZONE, retain_until_end=True)
    if row is not None:
        row.update(description=_text(body), attendance_mode="in_person", timezone=ZONE,
                   location_provenance="reviewed_venue_street_address_pending_geocode")
        # NJ Office of GIS, reviewed 2026-11-14: score-100 PointAddress for
        # the publisher's exact East White Horse Pike street, town and ZIP.
        # https://gardenstatebeerco.com/contact
        # https://geo.nj.gov/arcgis/rest/services/Tasks/NJ_Geocode/GeocodeServer/findAddressCandidates
        # SingleLine=247 E White Horse Pike, Galloway, NJ 08205; outSR=4326.
        if (key, row.get("venue_name"), row.get("venue_address")) == (
                GARDEN, "Garden State Beer Company", "247 E White Horse Pike, Galloway, NJ 08205"):
            row.update(lat=39.446046000003, lng=-74.527533000001,
                       location_provenance="reviewed_nj_ogis_point_address")
            if row.get("reason") == "missing_verified_venue_geo":
                row["reason"] = None
        if candidate := photo_url(key, image):
            row["image_url"] = candidate
    return row


def _hard_rock_manifest(payload, now):
    calendar = Calendar.from_ical(payload)
    events = calendar.walk("VEVENT")
    if len(events) > MAX_EVENTS:
        raise ValueError("atlantic_nightlife_event_limit")
    result = {}
    for e in events:
        if str(e.get("STATUS", "")).upper() in {"CANCELED", "CANCELLED"}:
            continue
        title = plain(e.get("SUMMARY"))
        if NONPUBLIC.search(title):
            continue
        raw_start = e.decoded("DTSTART")
        raw_end = e.decoded("DTEND")
        if (not isinstance(raw_start, datetime)
                or any(e.get(field) for field in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"))):
            raise ValueError("hard_rock_calendar_schedule_changed")
        start = timestamp(raw_start, ZONE)
        # Their midnight DTEND uses VALUE=DATE even when DTSTART is timed.
        # The detail page's explicit clock and JSON-LD must independently agree.
        if isinstance(raw_end, date) and not isinstance(raw_end, datetime):
            raw_end = datetime.combine(raw_end, time.min)
        end = timestamp(raw_end, ZONE)
        if not end or end <= start or end - start > timedelta(days=1):
            raise ValueError("hard_rock_calendar_schedule_changed")
        if not _within(start, end, now):
            continue
        url = str(e.get("URL", ""))
        if not event_url(HARD_ROCK, url):
            raise ValueError("atlantic_nightlife_event_identity")
        query = parse_qs(urlsplit(url).query)
        day = datetime.strptime(query["date"][0], "%m/%d/%Y").date()
        if day != start.astimezone(ZoneInfo(ZONE)).date():
            raise ValueError("hard_rock_calendar_schedule_changed")
        location = str(e.get("LOCATION", ""))
        if not (location.split(" - ", 1)[0] in ("Hard Rock Cafe Atlantic City", "BACKSTAGE CAFE")
                and "1000 Boardwalk" in location):
            raise ValueError("hard_rock_calendar_venue_changed")
        url = HARD_ROCK_URL + "?" + urlencode({"date": day.strftime("%m/%d/%Y"),
                                               "display": "event", "eventid": query["eventid"][0]})
        item = dict(url=url, title=title, start=start.isoformat(), end=end.isoformat(),
                    eventid=query["eventid"][0], identity=f"hard-rock:{query['eventid'][0]}:{day}")
        if url in result and result[url] != item:
            raise ValueError("atlantic_nightlife_duplicate_occurrence")
        result[url] = item
    return sorted(result.values(), key=lambda item: (item["start"], item["url"]))


def _hard_rock_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    cards = soup.select(".calListDayEvent[data-eventid]")
    if len(cards) != 1 or cards[0].get("data-eventid") != item["eventid"]:
        raise ValueError("hard_rock_detail_identity_changed")
    card = cards[0]
    title = plain(card.select_one(".calListDayEventTitle").get_text()) if card.select_one(".calListDayEventTitle") else ""
    if title != item["title"]:
        raise ValueError("hard_rock_detail_identity_changed")
    data = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("@type") == "Event":
            data.append(obj)
    if len(data) != 1:
        raise ValueError("hard_rock_detail_identity_changed")
    event = data[0]
    # The detail can announce a cancellation before the native export updates.
    # Do not certify a snapshot with a stale scheduled manifest in that case.
    status = str(event.get("eventStatus") or "").rstrip("/").rsplit("/", 1)[-1].casefold()
    if status not in ("", "eventscheduled"):
        raise ValueError("hard_rock_detail_status_changed")
    if plain(event.get("name")) != title or not event_url(HARD_ROCK, event.get("url")):
        raise ValueError("hard_rock_detail_identity_changed")
    detail_query = parse_qs(urlsplit(event["url"]).query)
    manifest_query = parse_qs(urlsplit(item["url"]).query)
    if (detail_query["eventid"] != manifest_query["eventid"]
            or datetime.strptime(detail_query["date"][0], "%m/%d/%Y")
                != datetime.strptime(manifest_query["date"][0], "%m/%d/%Y")):
        raise ValueError("hard_rock_detail_identity_changed")
    start, end = timestamp(item["start"]), timestamp(item["end"])
    if timestamp(event.get("startDate"), ZONE) != start or timestamp(event.get("endDate"), ZONE) != end:
        raise ValueError("hard_rock_detail_schedule_changed")
    clocks = card.select_one(".calListDayEventTime")
    match = re.fullmatch(r"(\d{1,2}:\d{2}\s*[AP]M)\s*[-–]\s*(\d{1,2}:\d{2}\s*[AP]M)", plain(clocks.get_text()) if clocks else "", re.I)
    if not match:
        raise ValueError("hard_rock_detail_schedule_changed")
    day = start.astimezone(ZoneInfo(ZONE)).date()
    display_start, display_end = _clock(day, match[1]), _clock(day, match[2])
    if display_end <= display_start:
        display_end = _clock(day + timedelta(days=1), match[2])
    if (display_start, display_end) != (start, end):
        raise ValueError("hard_rock_detail_schedule_changed")
    place = event.get("location") or {}
    address = place.get("address") or {}
    if (place.get("name") not in ("Hard Rock Cafe Atlantic City", "BACKSTAGE CAFE")
            or "1000 Boardwalk" not in str(address.get("streetAddress", ""))
            or address.get("addressLocality") != "Atlantic City"
            or address.get("addressRegion") not in ("New Jersey", "NJ")):
        raise ValueError("hard_rock_calendar_venue_changed")
    description = card.select_one(".calListDayEventDescription")
    body = narrative(description) if description else ""
    if not body:
        raise ValueError("atlantic_nightlife_description_missing")
    category_node = card.select_one(".calListDayEventCategory")
    category = plain(category_node.get_text()) if category_node else ""
    image = card.select_one(".calListDayEventSlideshowImage img[src]")
    return _row(HARD_ROCK, title, start, end, item["url"], item["identity"], body,
                category, image.get("src") if image else None)


def _checkpoint(value, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get("version") != 1
            or type(value.get("version")) is not int or value.get("source_key") != HARD_ROCK
            or type(value.get("cursor")) is not int or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_EVENTS
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or not isinstance(value.get("events"), list) or len(value["events"]) > value["cursor"]
            or not isinstance(value.get("diagnostics"), list)
            or len(value["diagnostics"]) + len(value["events"]) != value["cursor"]
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("manifest_hash", "")))
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError("atlantic_nightlife_checkpoint_invalid")
    try:
        started = timestamp(value["started_at"])
        if started.tzinfo is None or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (TypeError, KeyError, ValueError):
        raise ValueError("atlantic_nightlife_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=24):
        return None
    prefix = {item["url"]: item for item in value["queue"][:value["cursor"]]
              if isinstance(item, dict) and event_url(HARD_ROCK, item.get("url"))}
    if len(prefix) != value["cursor"]:
        raise ValueError("atlantic_nightlife_checkpoint_invalid")
    seen = set()
    for row in value["events"]:
        item = prefix.get(row.get("event_url")) if isinstance(row, dict) else None
        if (item is None or row["event_url"] in seen or row.get("id") != item["identity"]
                or row.get("title") != item["title"]
                or timestamp(row.get("starts_at")) != timestamp(item["start"])
                or timestamp(row.get("ends_at")) != timestamp(item["end"])
                or (row.get("venue_name"), row.get("venue_address"), row.get("venue_city")) != VENUES[HARD_ROCK]
                or row.get("lat") is not None or row.get("lng") is not None
                or not isinstance(row.get("description"), str) or _text(row["description"]) != row["description"]
                or (row.get("image_url") is not None and photo_url(HARD_ROCK, row["image_url"]) is None)):
            raise ValueError("atlantic_nightlife_checkpoint_invalid")
        seen.add(row["event_url"])
    for item in value["diagnostics"]:
        if (not isinstance(item, dict) or item.get("event_url") not in prefix
                or item["event_url"] in seen or item.get("disposition") != "held"
                or item.get("reason") != "event_ended_during_collection"):
            raise ValueError("atlantic_nightlife_checkpoint_invalid")
        seen.add(item["event_url"])
    if seen != set(prefix):
        raise ValueError("atlantic_nightlife_checkpoint_invalid")
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    _source(source, HARD_ROCK)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("atlantic_nightlife_checkpoint_invalid")
    state = _checkpoint(checkpoint, current)
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(HARD_ROCK_URL + "?format=ical", "text/calendar")
    queue = _hard_rock_manifest(payload, anchor)
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest or state["queue"] != queue:
        queue = _hard_rock_manifest(payload, current)
        digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        state = dict(version=1, source_key=HARD_ROCK, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=digest, manifest_count=len(queue), cursor=0,
                     queue=queue, events=[], diagnostics=[])
    prior = state["cursor"]
    count = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state["cursor"] < len(queue) and state["cursor"] - prior < count:
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        item = queue[state["cursor"]]
        row = _hard_rock_detail(item, fetch(item["url"], "text/html"))
        if row is not None:
            state["events"].append(row)
        else:
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason="event_ended_during_collection"))
        state["cursor"] += 1
    if state["cursor"] == prior < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("atlantic_nightlife_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    rows = sorted(state["events"], key=lambda r: (r["starts_at"], r["id"])) if complete else []
    return dict(complete=complete, events=deepcopy(rows), checkpoint=state)


def _garden_script_url(value):
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.netloc == "img1.wsimg.com" and not p.query and not p.fragment
                and re.fullmatch(r"/blobby/go/" + GARDEN_SITE + r"/gpub/[a-f0-9]{16}/script\.js", p.path) is not None)
    except (ValueError, TypeError):
        return False


def _garden_objects(payload):
    decoder = json.JSONDecoder()
    for match in re.finditer(r"JSON\.parse\(", payload):
        try:
            literal, _ = decoder.raw_decode(payload[match.end():])
            obj = json.loads(literal) if isinstance(literal, str) else None
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and "manualEvents" in obj:
            yield obj


def _garden_description(value):
    data = json.loads(value)
    if (not isinstance(data, dict) or not isinstance(data.get("blocks"), list)
            or len(data["blocks"]) > 200 or any(not isinstance(b, dict)
                or not isinstance(b.get("text"), str) for b in data["blocks"])):
        raise ValueError("garden_state_calendar_changed")
    return _text("\n".join(block["text"] for block in data["blocks"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    _source(source, GARDEN)
    current = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(fetch(GARDEN_URL, "text/html"), "html.parser")
    visible = set()
    for heading in soup.select('[data-aid="CALENDAR_SECTION_TITLE_RENDERED"]'):
        section = heading.find_parent("section")
        widget = section.select_one('[id$="-bootstrap-container"]') if section else None
        if widget is None or not re.fullmatch(UUID + "-bootstrap-container", widget.get("id", "")):
            raise ValueError("garden_state_calendar_changed")
        visible.add(widget["id"].removesuffix("-bootstrap-container"))
    scripts = sorted(set(urljoin(GARDEN_URL, node["src"]) for node in soup.select("script[src]")
                         if _garden_script_url(urljoin(GARDEN_URL, node["src"]))))
    if not visible or len(visible) > 12 or not 1 <= len(scripts) <= 4:
        raise ValueError("garden_state_calendar_changed")
    widgets = {}
    for url in scripts:
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            raise ValueError("collection_deadline")
        for obj in _garden_objects(fetch(url, "application/javascript")):
            if obj.get("id") not in visible:
                continue
            if (obj.get("websiteId") != GARDEN_SITE or obj.get("pageId") != GARDEN_PAGE
                    or obj.get("widgetId") != obj["id"] or obj.get("isManual") is not True
                    or not isinstance(obj.get("manualEvents"), list)
                    or len(obj["manualEvents"]) > MAX_EVENTS):
                raise ValueError("garden_state_calendar_changed")
            if obj["id"] in widgets and widgets[obj["id"]] != obj:
                raise ValueError("garden_state_calendar_changed")
            widgets[obj["id"]] = obj
    if set(widgets) != visible:
        raise ValueError("garden_state_calendar_incomplete")
    rows = {}
    for widget in widgets.values():
        for item in widget["manualEvents"]:
            if not isinstance(item, dict) or not re.fullmatch(UUID, str(item.get("id", ""))):
                raise ValueError("garden_state_calendar_changed")
            title = plain(item.get("title"))
            if NONPUBLIC.search(title):
                continue
            day = datetime.strptime(item["date"], "%m/%d/%y").date()
            if item.get("allDay"):
                # No clock is inferred for a publisher's all-day notice.
                continue
            start, end = _clock(day, item["start"]), _clock(day, item["end"])
            if end == start:
                raise ValueError("garden_state_calendar_time_conflict")
            if end < start:
                end = _clock(day + timedelta(days=1), item["end"])
            if not _within(start, end, current):
                continue
            if plain(item.get("location")) not in ("", VENUES[GARDEN][0], VENUES[GARDEN][1]):
                raise ValueError("garden_state_calendar_venue_changed")
            body = _garden_description(item.get("desc"))
            # Use the explicit dated card, not prose such as "last Sunday";
            # November's dated book-club card is Nov 22. No recurrence is inferred.
            identity = f"garden-state:{item['id']}:{day}"
            row = _row(GARDEN, title, start, end, GARDEN_URL, identity, body)
            if row is not None:
                if identity in rows and rows[identity] != row:
                    raise ValueError("atlantic_nightlife_duplicate_occurrence")
                rows[identity] = row
    if len(rows) > MAX_EVENTS:
        raise ValueError("atlantic_nightlife_event_limit")
    return sorted(rows.values(), key=lambda r: (r["starts_at"], r["id"]))
