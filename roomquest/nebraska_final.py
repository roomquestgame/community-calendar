"""Read the final Nebraska sources through their public calendars."""
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from lxml import html

from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record

ZONE = "America/Chicago"
LOCALHOP_HOST = "api.getlocalhop.com"
LOCALHOP_API = f"https://{LOCALHOP_HOST}/1/classes/EventInstance"
LOCALHOP_EMBED = "https://events.getlocalhop.com/widgets/embed-calendar-js"
LINCOLN = "lincoln_city_libraries_localhop_ne"
GRETNA = "gretna_public_library_localhop_ne"
SKYYBOX = "skyybox_trivia_ne"
POSTSCRIPT = "postscript_elfsight_ne"
ELLEINAD = "elleinad_storytimes_ne"
ZOO_BAR = "zoo_bar_lincoln_html_ne"
PARKS = "calendar.outdoornebraska.gov"
ELFSIGHT = "core.service.elfsight.com"
WIDGET = "bf123e26-8031-4a6e-9df8-15c815d921b6"
SOURCES = {
    ZOO_BAR: ("https://zoobar.com/calendar/zoo-bar-calendar-list-form/", ("zoobar.com",)),
    LINCOLN: ("https://www.lincolnlibraries.org/programs-and-events/events-calendar/",
              (LOCALHOP_HOST, "events.getlocalhop.com")),
    GRETNA: ("https://gretnahub.org/", (LOCALHOP_HOST, "events.getlocalhop.com")),
    SKYYBOX: ("https://www.skyyboxbarandgrill.com/events",
              ("www.skyyboxbarandgrill.com", "midwestpubtrivia.com")),
    POSTSCRIPT: ("https://postscript.press/pages/event-schedule", (ELFSIGHT, "postscript.press")),
    ELLEINAD: (f"https://{PARKS}/event/turkey-storytime/", (PARKS,)),
}
GROUPS = {
    LINCOLN: ("6AtaVnGPEG", "nK5vBZe484", "80HRrgeDwT", "4564snjkLG", "63gzyMgEK9",
              "lv5NRuKBHq", "SnpJDYGwJd", "2eg12ZWClL", "RE2w8AISgs", "UhFI0W5rYY"),
    GRETNA: ("kTUfS2moiB",),
}
ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
STREET = re.compile(r"\d{1,6}\s+[A-Za-z]")
EXCLUDED = re.compile(r"\b(cancelled|canceled|postponed|closed)\b", re.I)
MAX_DESCRIPTION = 12000


def _narrative(value):
    text = description(value or "", limit=MAX_DESCRIPTION + 1)
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("publisher_description_limit")
    return text


def _local(value):
    if value is None:
        return None
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(ZONE))
    return value.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None).isoformat(timespec="seconds")


def _image(item):
    value = item.get("image") or item.get("imageUrl")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        value = next((entry for entry in value if isinstance(entry, (str, dict))), None)
    if isinstance(value, dict):
        return value.get("url") or value.get("contentUrl")
    return None


def _categories(item):
    value = item.get("categories") or item.get("tags") or item.get("keywords")
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = [entry.get("name") if isinstance(entry, dict) else entry for entry in value]
    else:
        return None
    return [plain(entry) for entry in values if isinstance(entry, str) and plain(entry)] or None


def _raw_location(item):
    place = item.get("location") or {}
    if not isinstance(place, dict):
        return None, None, None
    address = place.get("address")
    if isinstance(address, str):
        return place.get("name"), address, None
    if not isinstance(address, dict):
        return place.get("name"), None, None
    values = [address.get(name) for name in
              ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
    return place.get("name"), ", ".join(plain(value) for value in values if plain(value)), address.get("addressLocality")


def _finish(row, *, narrative="", raw_venue=None, raw_address=None, raw_city=None,
            status="scheduled", attendance="in_person", image=None, categories=None,
            latitude=None, longitude=None):
    if row is None:
        return None
    narrative = _narrative(narrative)
    if (latitude is None) != (longitude is None):
        latitude = longitude = None
    row.update(description=narrative[:2000], attendance_mode=attendance, timezone=ZONE)
    facts = {
        "title": row["title"], "description": narrative, "is_all_day": False,
        "starts_at_local": _local(row["starts_at"]),
        "ends_at_local": _local(row["ends_at"]) if row.get("ends_at") else None,
        "source_timezone": ZONE, "event_url": row["event_url"],
        "venue_name": plain(raw_venue), "venue_address": plain(raw_address),
        "venue_city": plain(raw_city), "publisher_status": plain(status),
        "attendance_mode": plain(attendance), "source_image_url": image,
        "publisher_categories": categories, "source_latitude": latitude,
        "source_longitude": longitude,
    }
    row["collector_event_content_v1"] = {
        "version": 1, "event_id": row["id"],
        "facts": {name: value for name, value in facts.items()
                  if value is not None and value != "" and value != []},
    }
    return row


def date_value(value):
    return {"__type": "Date", "iso": value.isoformat(timespec="milliseconds").replace("+00:00", "Z")}


def localhop(key, fetch, fetch_localhop, now):
    embed = fetch(LOCALHOP_EMBED, "text/javascript")
    app = re.search(r'window\.AppConfig\.ParseAppId\s*=\s*"([A-Za-z0-9]{20,80})"', embed)
    if not app:
        raise ValueError("localhop_public_app_missing")
    begin = now.replace(hour=0, minute=0, second=0, microsecond=0)
    where = {
        "organization": {"$in": [
            {"__type": "Pointer", "className": "Organization", "objectId": group}
            for group in GROUPS[key]
        ]},
        "standardStartDate": {"$gte": date_value(begin), "$lte": date_value(begin + timedelta(days=60))},
        "status": "publish",
    }
    if key == GRETNA:
        where["myCalendarOnly"] = {"$ne": True}
    url = LOCALHOP_API + "?" + urlencode({
        "order": "standardStartDate,objectId", "limit": 500, "include": "event",
        "where": json.dumps(where, separators=(",", ":")),
    })
    rows = json.loads(fetch_localhop(url, app.group(1))).get("results")
    if not isinstance(rows, list) or len(rows) >= 500:
        raise ValueError("invalid_localhop_calendar")
    output = []
    for row in rows:
        event = row.get("event") or {}
        place = event.get("address") or {}
        geo = row.get("addressLatLng") or event.get("addressLatLng") or {}
        title = plain(event.get("name"))
        street, city = plain(place.get("address1")), plain(place.get("city"))
        event_id, instance_id = event.get("objectId", ""), row.get("objectId", "")
        start = (row.get("actualStartDate") or {}).get("iso")
        end = (row.get("actualEndDate") or {}).get("iso")
        if (not start or not title or EXCLUDED.search(title) or event.get("virtual") or row.get("allDay")
                or row.get("status") != "publish" or event.get("status") != "publish"
                or (row.get("organization") or {}).get("objectId") not in GROUPS[key]
                or place.get("state") != "NE" or not city or not STREET.match(street)
                or not ID.fullmatch(event_id) or not ID.fullmatch(instance_id)):
            continue
        if datetime.fromisoformat(start) < now:
            continue
        address = f"{street}, {city}, NE {plain(place.get('postalCode'))}".rstrip()
        link = f"{SOURCES[key][0]}#/events/{event_id}/instances/{instance_id}/"
        item = record(title, start, end, plain(place.get("place")) or street, address, city,
                             link, instance_id, lat=geo.get("latitude"), lng=geo.get("longitude"),
                             tz=ZONE)
        if item is not None:
            output.append(_finish(
                item, narrative=event.get("description"), raw_venue=place.get("place"),
                raw_address=address, raw_city=city, status="publish",
                image=_image(event), categories=_categories(event),
                latitude=geo.get("latitude"), longitude=geo.get("longitude"),
            ))
    return output


def skyybox(fetch, now):
    url = SOURCES[SKYYBOX][0]
    page = plain(html.fromstring(fetch(url, "text/html")).text_content())
    organizer = plain(html.fromstring(fetch(
        "https://midwestpubtrivia.com/locations-dates/", "text/html")).text_content())
    if (not re.search(r"every tuesday.{0,220}trivia.{0,130}7\s*p", page, re.I)
            or not re.search(r"Skyybox Grill and Bar.{0,260}Tuesday.{0,35}7:00\s*PM", organizer, re.I)
            or not re.search(r"6720\s+S\.?\s+168th\s+St", page, re.I)):
        return []
    day = now.astimezone(ZoneInfo(ZONE)).date()
    output = []
    for offset in range((1 - day.weekday()) % 7, 35, 7):
        start = datetime.combine(day + timedelta(days=offset), time(19), ZoneInfo(ZONE))
        if start > now:
            output.append(_finish(record(
                "Tuesday Trivia at Skyybox", start.isoformat(), None,
                "Skyybox Grill & Bar", "6720 S 168th St, Omaha, NE 68135", "Omaha",
                url, start.date().isoformat(), lat=41.192416422681, lng=-96.177586580445,
                tz=ZONE), raw_venue="Skyybox Grill and Bar", raw_address="6720 S 168th St"))
    return output


def postscript(fetch, now):
    url = SOURCES[POSTSCRIPT][0]
    markup = fetch(url, "text/html")
    if f"elfsight-app-{WIDGET}" not in markup:
        raise ValueError("postscript_widget_missing")
    endpoint = f"https://{ELFSIGHT}/p/boot/?" + urlencode({"w": WIDGET, "page": url})
    widget = json.loads(fetch(endpoint, "application/json"))["data"]["widgets"][WIDGET]["data"]
    if widget.get("app") != "event-calendar" or not isinstance(widget["settings"].get("events"), list):
        raise ValueError("invalid_postscript_widget")
    output = []
    for item in widget["settings"]["events"]:
        start, end = item.get("start") or {}, item.get("end") or {}
        title = plain(item.get("name"))
        if (item.get("repeatPeriod") != "noRepeat" or item.get("isAllDay")
                or item.get("timeZone") != ZONE or start.get("type") != "datetime"
                or not title or EXCLUDED.search(title) or item.get("location")):
            continue
        starts = datetime.fromisoformat(f"{start['date']}T{start['time']}").replace(tzinfo=ZoneInfo(ZONE))
        if not now < starts < now + timedelta(days=60):
            continue
        ends = f"{end['date']}T{end['time']}" if end.get("date") and end.get("time") else None
        row = record(title, starts.isoformat(), ends, "Postscript",
                     "1434 Silver St, Ashland, NE 68003", "Ashland", url, item["id"],
                     lat=41.039166361796, lng=-96.368784765192, tz=ZONE)
        if row is not None:
            output.append(_finish(row, narrative=item.get("description"),
                                  image=_image(item), categories=_categories(item)))
    return output


def elleinad(fetch, now):
    output = []
    for slug in ("turkey-storytime", "winter-birds-storytime"):
        url = f"https://{PARKS}/event/{slug}/"
        document = html.fromstring(fetch(url, "text/html"))
        for raw in document.xpath('//script[@type="application/ld+json"]/text()'):
            payload = json.loads(raw)
            for item in payload if isinstance(payload, list) else [payload]:
                if item.get("@type") != "Event":
                    continue
                venue = item.get("location") or {}
                start = item.get("startDate")
                if (venue.get("name") != "Elleinad Books" or not start
                        or datetime.fromisoformat(start) <= now
                        or not str(item.get("eventStatus", "")).endswith("/EventScheduled")):
                    continue
                row = record(item.get("name"), start, item.get("endDate"), "Elleinad Books",
                                     "4724 Prescott Ave, Lincoln, NE 68506", "Lincoln", url, slug,
                                     lat=40.77296938801, lng=-96.655071487729, tz=ZONE)
                if row is not None:
                    raw_venue, raw_address, raw_city = _raw_location(item)
                    output.append(_finish(
                        row, narrative=item.get("description"), raw_venue=raw_venue,
                        raw_address=raw_address, raw_city=raw_city,
                        image=_image(item), categories=_categories(item),
                    ))
    return output


def zoo_bar(fetch, now):
    url = SOURCES[ZOO_BAR][0]
    document = html.fromstring(fetch(url, "text/html"))

    def has_class(node, name):
        return name in (node.get("class") or "").split()

    rows = [node for node in document.iter("li") if has_class(node, "simcal-event")]
    if not any(has_class(node, "simcal-calendar-list") for node in document.iter()):
        raise ValueError("missing_zoo_bar_calendar")

    output = {}
    for row in rows:
        # Rich event descriptions can nest the next listing in recovered HTML.
        fields = {}
        for node in row.iterdescendants():
            owner = next((parent for parent in node.iterancestors("li")
                          if has_class(parent, "simcal-event")), None)
            if owner is not row:
                continue
            for name in ("simcal-event-title", "simcal-event-start-time", "simcal-event-end-time"):
                if has_class(node, name):
                    fields.setdefault(name, node)
        title_node = fields.get("simcal-event-title")
        start_node = fields.get("simcal-event-start-time")
        if title_node is None or start_node is None:
            continue
        title = plain(title_node.text_content())
        if not title or EXCLUDED.search(title):
            continue
        start = datetime.fromtimestamp(int(start_node.get("data-event-start", "")), timezone.utc)
        if not now < start < now + timedelta(days=60):
            continue
        end_node = fields.get("simcal-event-end-time")
        end = (datetime.fromtimestamp(int(end_node.get("data-event-end", "")), timezone.utc)
               if end_node is not None else None)
        if end is not None and end <= start:
            continue
        identity = sha256(f"{start.isoformat()}|{title.casefold()}".encode()).hexdigest()
        output[identity] = _finish(record(
            title, start.isoformat(), end.isoformat() if end else None,
            "The Zoo Bar", "136 N 14th St, Lincoln, NE 68508", "Lincoln",
            url, identity, "Music", lat=40.814061685175, lng=-96.701083776601,
            tz=ZONE))
    return list(output.values())


def collect(source, fetch, *, deadline_at=None, fetch_localhop=None, now=None):
    key = source.get("source_key")
    if key not in SOURCES or tuple(source.get(field) for field in
            ("feed_url", "timezone", "kind", "platform_adapter")) != (SOURCES[key][0], ZONE, "html", "html"):
        raise ValueError("unregistered_nebraska_final_source")
    now = calendar_anchor(now or datetime.now(timezone.utc))
    if key in GROUPS:
        rows = localhop(key, fetch, fetch_localhop, now)
    else:
        rows = {SKYYBOX: skyybox, POSTSCRIPT: postscript, ELLEINAD: elleinad, ZOO_BAR: zoo_bar}[key](fetch, now)
    return sorted((row for row in rows if row is not None), key=lambda row: (row["starts_at"], row["id"]))
