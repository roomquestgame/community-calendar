"""Remaining Boston public programs, using reviewed native publisher formats.

Localist supplies complete descriptions and dated instances. Events Manager and
Mass Audubon supply complete detail HTML, consumed through complete-only durable
snapshots. Boston Cares' public display POST supplies full opportunity prose.
All requests are delegated to the worker's ordinary guarded publisher transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import html
import json
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.boston_community import _full, _point, LOCALITIES as BOSTON_LOCALITIES
from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = "America/New_York"
BC = "municipal_mapsee_64dd0126cc162e1c90b57edc"
GREENWAY = "rose_kennedy_greenway_ma"
NATURE = "boston_nature_center_ma"
CARES = "boston_cares_ma"
CARES_API = "https://www.bostoncares.org/search/getOpportunitiesCalendar"
SOURCES = {
    BC: ("https://events.bc.edu", "html", "html"),
    GREENWAY: ("https://www.rosekennedygreenway.org/calendar/", "html", "html"),
    NATURE: ("https://www.massaudubon.org/programs/boston-nature-center", "html", "html"),
    CARES: ("https://www.bostoncares.org/calendar", "html", "html"),
}
LABELS = {BC: "Boston College Public Events", GREENWAY: "Rose Kennedy Greenway",
          NATURE: "Mass Audubon Boston Nature Center", CARES: "Boston Cares — next 14 days"}
SOURCE_NOTES = {
    BC: "Repairs existing empty paused Localist identity; public timed physical events, full native narratives and reviewed actual venue streets.",
    GREENWAY: "Official dated calendar and complete detail HTML; variable volunteer meeting points held pending publication.",
    NATURE: "Official program details and explicitly enumerated sessions; actual meeting points take priority over default sanctuary metadata.",
    CARES: "Official public calendar display POST, next 14 days of open physical Boston-metro shifts; full native prose and event-specific reviewed venue streets.",
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = {GREENWAY, NATURE}
REVIEWED_INTERSECTIONS = ({"source_key": GREENWAY,
    "venue_name": "Boston Harbor Distillery at The Greenway",
    "venue_address": "High Street & Atlantic Avenue, Boston, MA 02110",
    "lat": 42.3566833, "lng": -71.0507724},)
# Exact physical venues still ambiguous in production after the November 14
# batch. Streets and native occurrence bodies/identities remain unchanged.
# Government address/building geometry and the publisher's own place record
# establish these points; no viewport center or organization headquarters.
REVIEWED_EVENT_POINTS = {
    (CARES, "Catholic Charities Yawkey Center Food Pantry", "185 Columbia Road, Dorchester, MA 02121"): (
        (42.306336, -71.076838),
        "https://gis.boston.gov/arcgis/rest/services/SAM/Live_SAM_Address/MapServer/1",
        "Boston SAM primary address 35171 / building 207372, exact 185 Columbia Road and ZIP 02121; Catholic Charities confirms this Yawkey pantry site."),
    (CARES, "Torchlight Recovery Cafe", "2 Washington Street, Dorchester, MA 02121"): (
        (42.308499, -71.082661),
        "https://gis.boston.gov/arcgis/rest/services/SAM/Live_SAM_Address/MapServer/1",
        "Boston SAM exact address 438957 / building 183083, primary 145975 at 2-4 Washington Street; Torchlight confirms both address forms and ZIP 02121."),
    (CARES, "First Congregational Church Food Pantry", "230 Beach Street, Revere, MA 02151"): (
        (42.409298, -71.008602),
        "https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/MHC_Inventory_GDB/FeatureServer/0",
        "MassGIS/MHC building REV.45 / OBJECTID 51351 names First Congregational Church at 230 Beach Street, Revere; current church pantry directions corroborate."),
    (CARES, "Central Square Farmers Market", "76 Bishop Allen Drive, Cambridge, MA 02139"): (
        (42.3649, -71.1009),
        "https://www.centralsq.org/mapajax.json/member-groups/special-events",
        "Central Square BID's named market feature 423649711009 supplies explicit geometry at 76 Bishop Allen Drive and links the market operator."),
    (CARES, "Copley Square Farmers Market", "227-230 Dartmouth Street, Boston, MA 02116"): (
        (42.3495856, -71.0770735),
        "https://marketspread.com/market/5060/copley-square-farmers-market/",
        "The market operator embeds Marketspread market 5060; its named McKim Plaza profile supplies explicit geo.position at 227 Dartmouth Street, and the operator confirms the native 227-230 range."),
    (CARES, "Franklin Hill Boys & Girls Club", "42 Shandon Road, Dorchester, MA 02124"): (
        (42.295434, -71.090103),
        "https://gis.boston.gov/arcgis/rest/services/SAM/Live_SAM_Address/MapServer/1",
        "Boston SAM exact address 353255 / building 216265 at 42 Shandon Road and ZIP 02124; Fresh Truck's November 2026 schedule confirms this market stop. The club's separate 5 Shandon Road entrance is not used."),
    (BC, "Chestnut Hill, Mass., Conte Forum", "2601 Beacon Street, Chestnut Hill, MA 02467"): (
        (42.335342, -71.167717), "https://events.bc.edu/conte_forum",
        "Boston College's verified Localist place 190074 has exact Conte Forum address, ZIP and native geo; original athletic venue label retained."),
    (BC, "Chestnut, Hill, Mass., Conte Forum", "2601 Beacon Street, Chestnut Hill, MA 02467"): (
        (42.335342, -71.167717), "https://events.bc.edu/conte_forum",
        "Boston College's verified Localist place 190074 has exact Conte Forum address, ZIP and native geo; original athletic venue label retained."),
    (BC, "Stuart House, 315", "899 Centre Street, Newton, MA 02459"): (
        (42.341629, -71.193954), "https://events.bc.edu/stuart_house",
        "Boston College's verified Stuart House place 190148 and the event's Place.geo agree; the publisher pairs this point with 899 Centre Street while its geo street uses the campus's 885 address. Native display street and room retained."),
    (BC, "Chestnut Hill, Mass., Alumni Stadium", "2604 Beacon Street, Chestnut Hill, MA 02467"): (
        (42.334999, -71.166389), "https://events.bc.edu/alumni_stadium",
        "Boston College's verified Alumni Stadium place 190055 explicitly supplies this geo and display street 2604 Beacon Street; its internal geo street/ZIP differs as 2587 Beacon Street/02135. Reviewed named stadium identity and original display street retained."),
    (BC, "MCLE Conference Center", "10 Winter Place, Boston, MA 02108"): (
        (42.355469, -71.061701),
        "https://gis.boston.gov/arcgis/rest/services/SAM/Live_SAM_Address/MapServer/1",
        "Boston SAM exact 10 Winter Place address 356713 / building 218689; MCLE confirms the Temple Place back entrance matching SAM's primary frontage. SAM postcode 02111 differs from publisher 02108, which is retained."),
    (BC, "Simboli Chapel", "9 Lake Street, Boston, MA 02135"): (
        (42.341625, -71.164566), "https://events.bc.edu/Simboli_Hall",
        "Boston College's verified Simboli Hall place 190053 supplies exact 9 Lake Street, Boston 02135 and native geo. This is the containing building point for Simboli Chapel; original chapel label and street retained."),
}
MAX_MANIFEST = 200
MAX_RECORDS = 500
MAX_CHECKPOINT_EVENTS = 200
MAX_CHECKPOINT_BYTES = 900000
# Use available time in the existing worker claim while retaining the same
# 18-second admission reserve before every ordinary, paced detail fetch.
DETAILS_PER_CHUNK = 8
LOCALITIES = BOSTON_LOCALITIES | {"Back Bay", "Bay Village", "West End", "Dedham"}
ERROR_CODES = {"unregistered_boston_remaining_source", "boston_remaining_feed_changed",
    "boston_remaining_calendar_changed", "boston_remaining_detail_changed",
    "boston_remaining_pagination_incomplete", "boston_remaining_record_limit",
    "boston_remaining_time_conflict", "boston_remaining_description_missing",
    "boston_remaining_street_unresolved", "boston_remaining_not_public",
    "boston_remaining_placeholder", "boston_remaining_checkpoint_invalid",
    "boston_remaining_checkpoint_limit", "boston_remaining_deadline",
    "boston_remaining_location_conflict", "boston_remaining_outside_window"}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_boston_remaining_source")
    return key


def _budget(deadline_at, reserve=8):
    if deadline_at is not None and monotonic() + reserve >= deadline_at:
        raise ValueError("boston_remaining_deadline")


def _hold(key, identity, reason, diagnostics):
    log.warning("boston_remaining_record_held source=%s id=%s reason=%s", key, identity, reason)
    diagnostics.append({"id": str(identity), "reason": reason})


def _street(value):
    match = re.fullmatch(r"(\d{1,6}(?:-\d{1,6})?\s+.+?),\s*([^,]+),\s*(?:MA|Massachusetts),?\s*"
                         r"(\d{5}(?:-\d{4})?)(?:,\s*(?:USA|United States))?", plain(value), re.I)
    if not match or match[2] not in LOCALITIES:
        return None
    return f"{match[1]}, {match[2]}, MA {match[3]}", match[2]


def _street_key(value):
    text = plain(value).split(",", 1)[0].casefold()
    for long, short in (("street", "st"), ("avenue", "ave"), ("road", "rd"),
                        ("saint", "st"), ("boulevard", "blvd")):
        text = re.sub(r"\b" + long + r"\b", short, text)
    return re.sub(r"[^a-z0-9]", "", text)


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        prefixes = {BC: r"/event/[a-z0-9_-]+", GREENWAY: r"/events/[a-z0-9_-]+/",
                    NATURE: r"/programs/boston-nature-center/[1-9][0-9]*-[a-z0-9_-]+",
                    CARES: r"/opportunity/a0C[A-Za-z0-9]{15}"}
        return bool(p.scheme == "https" and p.netloc in ALLOWED_HOSTS[key]
                    and not (p.query or p.fragment) and re.fullmatch(prefixes[key], p.path, re.I))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.fragment or p.username or p.password:
            return False
        if key == BC:
            return bool(p.netloc == "localist-images.azureedge.net" and not p.query
                        and re.fullmatch(r"/photos/\d+/huge/[a-z0-9-]+\.(?:jpg|jpeg|png|webp)", p.path, re.I))
        if key == GREENWAY:
            return p.netloc in ALLOWED_HOSTS[key] and p.path.startswith("/wp-content/uploads/")
        if key == NATURE:
            return p.netloc == "links.imagerelay.com" and p.path.startswith("/cdn/3299/")
    except ValueError:
        pass
    return False


def _within(start, end, now, days=60):
    return bool(start and start < now + timedelta(days=days) and (end or start + timedelta(hours=3)) > now)


def _row(key, title, start, end, url, identity, body, venue, street, city, *, point=None,
         categories=(), photo=None, provenance="publisher_event_street", evidence=None):
    if not body or not body.strip() or len(body) > 12000:
        raise ValueError("boston_remaining_description_missing")
    if reviewed := REVIEWED_EVENT_POINTS.get((key, venue, street)):
        point, evidence, provenance = reviewed
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue, street, city, url, identity, "", lat=point[0] if point else None,
                 lng=point[1] if point else None, tz=ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                   publisher_categories=list(categories), location_provenance=provenance,
                   location_evidence_url=evidence or url)
        if photo_url(key, photo):
            row["image_url"] = photo
    return row


# Reviewed official Localist place directory and BC's public directions. Missing
# event streets are resolved only for exact venue identities, never a generic
# college headquarters. Conflicting native geocodes are discarded for geocoding.
BC_VENUES = {
    "McMullen Museum of Art": ("2101 Commonwealth Avenue, Boston, MA 02135", "https://events.bc.edu/McMullen_Museum"),
    "Conte Forum": ("2601 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/conte_forum"),
    "Burns Library": ("89 College Road, Chestnut Hill, MA 02467", "https://events.bc.edu/burns_library"),
    "Robsham Theater Arts Center": ("50 St. Thomas More Road, Chestnut Hill, MA 02467", "https://events.bc.edu/robsham_theater_arts_center"),
    "Margot Connell Recreation Center": ("140 Commonwealth Avenue, Chestnut Hill, MA 02467", "https://www.bc.edu/bc-web/offices/rec/about/facilities/directions.html"),
    "Devlin Hall": ("255 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/devlin_hall"),
    "Higgins Hall": ("231 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/higgins_hall"),
    "Gasson Hall": ("140 Commonwealth Avenue, Chestnut Hill, MA 02467", "https://bceagles.com/sports/2025/8/7/gasson-hall-parking"),
    "Merkert Chemistry Center": ("2609 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/merkert_chemistry_center"),
    "Connolly House": ("300 Hammond Street, Chestnut Hill, MA 02467", "https://events.bc.edu/connolly_house"),
    "Trinity Chapel": ("883 Centre Street, Newton, MA 02459", "https://events.bc.edu/trinity_chapel"),
    "Fulton Hall": ("257 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/fulton_hall"),
    "St. Ignatius Church": ("28 Commonwealth Avenue, Chestnut Hill, MA 02467", "https://events.bc.edu/st_ignatius_church"),
    "Stuart House": ("899 Centre Street, Newton, MA 02459", "https://events.bc.edu/stuart_house"),
    "Walsh Hall": ("150 Saint Thomas More Road, Boston, MA 02135", "https://events.bc.edu/walsh_hall"),
    "Saint Mary's Hall": ("140 Commonwealth Avenue, Chestnut Hill, MA 02467", "https://events.bc.edu/saint_marys_hall"),
    "MCLE Conference Center": ("10 Winter Place, Boston, MA 02108", "https://www.mcle.org/about/contact.cfm"),
    "Hayden Hall": ("245 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/245_beacon_street_928"),
    "Simboli Hall": ("9 Lake Street, Boston, MA 02135", "https://events.bc.edu/Simboli_Hall"),
    "Alumni Stadium": ("2604 Beacon Street, Chestnut Hill, MA 02467", "https://events.bc.edu/alumni_stadium"),
}
BC_ALIASES = {"Chestnut Hill, Mass., Conte Forum": "Conte Forum",
    "Chestnut, Hill, Mass., Conte Forum": "Conte Forum", "Gasson Hall 100": "Gasson Hall",
    "Gasson Hall100": "Gasson Hall", "Merkert": "Merkert Chemistry Center",
    "St. Ignatius Parish": "St. Ignatius Church", "St. Mary's Hall South": "Saint Mary's Hall",
    "Simboli Chapel": "Simboli Hall", "Chestnut Hill, Mass., Alumni Stadium": "Alumni Stadium"}


def _bc_location(event):
    venue = plain(event.get("location_name")).strip(" ,")
    canonical = BC_ALIASES.get(venue, venue)
    native = _street(event.get("address"))
    reviewed = BC_VENUES.get(canonical)
    if not venue or not (native or reviewed):
        return None
    evidence = event.get("localist_url")
    provenance = "publisher_event_street"
    if reviewed:
        resolved = _street(reviewed[0])
        if native and _street_key(native[0]) != _street_key(resolved[0]):
            return None
        address, city = resolved
        evidence = reviewed[1]
        provenance = "reviewed_named_venue_street"
    else:
        address, city = native
    geo = event.get("geo") or {}
    if not isinstance(geo, dict):
        raise ValueError("boston_remaining_feed_changed")
    point = None
    if (geo.get("street") and _street_key(geo["street"]) == _street_key(address)
            and str(geo.get("zip", "")).zfill(5) == address[-5:]
            and geo.get("state") in {"MA", "Massachusetts"}):
        point = _point(geo.get("latitude"), geo.get("longitude"))
    if canonical in {"Gasson Hall", "Margot Connell Recreation Center"}:
        venue += " (campus access address)"
        provenance = "official_named_venue_campus_access_street_pending_geocode"
        point = None
    room = plain(event.get("room_number"))
    return ", ".join(filter(None, (venue, room))), address, city, point, provenance, evidence


def _bc_events(events, now, diagnostics):
    output = {}
    for wrapper in events:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("event"), dict):
            raise ValueError("boston_remaining_feed_changed")
        event = wrapper["event"]
        identity = event.get("id")
        if type(identity) is not int or identity <= 0:
            raise ValueError("boston_remaining_feed_changed")
        filters = event.get("filters") or {}
        if not isinstance(filters, dict):
            raise ValueError("boston_remaining_feed_changed")
        audiences = [plain(x.get("name")) for x in filters.get("event_audience", []) if isinstance(x, dict)]
        if (event.get("private") is not False or event.get("rejected") is not False
                or event.get("publish_status") != "published" or event.get("status") != "live"
                or event.get("experience") not in {"inperson", "hybrid"} or "Public" not in audiences):
            continue
        title, body = plain(event.get("title")), _full(event.get("description"))
        if not body or plain(body).casefold() == title.casefold():
            _hold(BC, identity, "boston_remaining_description_missing", diagnostics)
            continue
        if plain(body).casefold() in {"tbd", "research summary", "to be announced", "description forthcoming"}:
            _hold(BC, identity, "boston_remaining_placeholder", diagnostics)
            continue
        location = _bc_location(event)
        if not location:
            _hold(BC, identity, "boston_remaining_street_unresolved", diagnostics)
            continue
        url = event.get("localist_url")
        if not event_url(BC, url):
            raise ValueError("boston_remaining_feed_changed")
        instances = event.get("event_instances")
        if not isinstance(instances, list) or not instances:
            raise ValueError("boston_remaining_feed_changed")
        for item in instances:
            inst = item.get("event_instance") if isinstance(item, dict) else None
            if not isinstance(inst, dict) or inst.get("event_id") != identity or type(inst.get("id")) is not int:
                raise ValueError("boston_remaining_feed_changed")
            if inst.get("all_day") is not False:
                _hold(BC, inst["id"], "boston_remaining_time_conflict", diagnostics)
                continue
            start, end = _offset_time(inst.get("start")), _offset_time(inst["end"]) if inst.get("end") else None
            if end is not None and end <= start:
                raise ValueError("boston_remaining_time_conflict")
            if not _within(start, end, now):
                continue
            venue, address, city, point, provenance, evidence = location
            categories = list(dict.fromkeys(plain(x.get("name")) for name in
                    ("event_types", "event_event_types_by_interest") for x in filters.get(name, [])
                    if isinstance(x, dict) and plain(x.get("name"))))
            row = _row(BC, title, start, end, url, f"bc:{identity}:{inst['id']}", body,
                       venue, address, city, point=point, categories=categories,
                       photo=event.get("photo_url"), provenance=provenance, evidence=evidence)
            if row:
                key = (row["id"], row["starts_at"])
                if key in output and output[key] != row:
                    raise ValueError("boston_remaining_feed_changed")
                output[key] = row
    if len(output) > MAX_RECORDS:
        raise ValueError("boston_remaining_record_limit")
    return list(output.values())


def _offset_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("boston_remaining_time_conflict")
    return timestamp(value)


def _bc_collect(fetch, now, deadline_at, diagnostics):
    start = now.astimezone(ZoneInfo(ZONE)).date()
    wrappers, total_items, total_pages = [], None, None
    for page in range(1, 7):
        _budget(deadline_at)
        url = SOURCES[BC][0] + "/api/2/events?" + urlencode({"start": start.isoformat(),
                "end": (start + timedelta(days=60)).isoformat(), "pp": 100, "page": page})
        data = json.loads(fetch(url, "application/json"))
        meta, items = data.get("page"), data.get("events")
        if not isinstance(meta, dict) or not isinstance(items, list) or len(items) > 100:
            raise ValueError("boston_remaining_feed_changed")
        if page == 1:
            total_items, total_pages = meta.get("total_items"), meta.get("total")
        if (type(total_items) is not int or type(total_pages) is not int or not 0 <= total_items <= 600
                or not 1 <= total_pages <= 6 or meta.get("current") != page
                or meta.get("total_items") != total_items or meta.get("total") != total_pages
                or meta.get("next_page") != (page + 1 if page < total_pages else None)):
            raise ValueError("boston_remaining_pagination_incomplete")
        wrappers.extend(items)
        if page == total_pages:
            break
    if len(wrappers) != total_items:
        raise ValueError("boston_remaining_pagination_incomplete")
    return _bc_events(wrappers, now, diagnostics)


def _local_clock(day, value):
    value = plain(value).lower().replace(".", "")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*(am|pm)", value)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2]) > 59:
        raise ValueError("boston_remaining_time_conflict")
    hour = int(match[1]) % 12 + (12 if match[3] == "pm" else 0)
    return timestamp(f"{day}T{hour:02}:{int(match[2]):02}:00", ZONE)


def _clock_range(day, value):
    parts = re.split(r"\s*[-–]\s*", plain(value))
    if len(parts) != 2:
        raise ValueError("boston_remaining_time_conflict")
    start, end = _local_clock(day, parts[0]), _local_clock(day, parts[1])
    if end <= start:
        raise ValueError("boston_remaining_time_conflict")
    return start, end


def _greenway_month(payload, year, month, now):
    soup = BeautifulSoup(payload, "html.parser")
    calendars = soup.select(".em-calendar")
    if len(calendars) != 1 or calendars[0].get("data-month") != str(month) or calendars[0].get("data-year") != str(year):
        raise ValueError("boston_remaining_calendar_changed")
    grid = {}
    for item in calendars[0].select(".em-cal-event[data-event-url]"):
        url = item["data-event-url"]
        day = item.find_parent(class_="em-cal-day")
        date_node = day.select_one(".em-cal-day-date[data-date]") if day else None
        a = item.select_one("a[href]")
        if not date_node or not a or a["href"] != url or not event_url(GREENWAY, url):
            raise ValueError("boston_remaining_calendar_changed")
        value = {"title": plain(a.get_text()), "day": date_node["data-date"],
                 "native_id": item.get("data-event-id")}
        if url in grid and grid[url] != value:
            raise ValueError("boston_remaining_calendar_changed")
        grid[url] = value
    out, seen = [], set()
    for preview in soup.select(".em-calendar-preview .em-event.em-item"):
        a = preview.select_one(".em-item-read-more[href]")
        if a is None:
            # Events Manager also renders a compact duplicate preview for
            # mobile. The full cards below must still cover every grid URL.
            continue
        date_node, time_node = preview.select_one(".em-event-date"), preview.select_one(".em-event-time")
        if a["href"] not in grid and date_node and not plain(date_node.get_text()):
            # The plugin leaves undated recurrence previews beyond its rendered
            # calendar horizon. No date is inferred from their URL/title.
            continue
        if not a or not date_node or not time_node or a["href"] not in grid:
            raise ValueError("boston_remaining_calendar_changed")
        url, facts = a["href"], grid[a["href"]]
        if url in seen:
            raise ValueError("boston_remaining_calendar_changed")
        seen.add(url)
        day = datetime.strptime(plain(date_node.get_text()), "%m/%d/%Y").date().isoformat()
        if day != facts["day"]:
            raise ValueError("boston_remaining_time_conflict")
        if plain(time_node.get_text()).lower() in {"all day", "all-day"}:
            continue
        start, end = _clock_range(day, time_node.get_text())
        if not _within(start, end, now):
            continue
        place = preview.select_one(".em-event-location")
        categories = [plain(n.get_text()) for n in preview.select(".event-categories a")]
        out.append({"url": url, "title": facts["title"], "start": start.isoformat(),
                    "end": end.isoformat(), "native_id": facts["native_id"],
                    "venue": plain(place.get_text()) if place else "", "categories": categories})
    if set(grid) != seen:
        raise ValueError("boston_remaining_calendar_changed")
    return out


def _greenway_manifest(fetch, now, deadline_at):
    start = now.astimezone(ZoneInfo(ZONE)).date()
    last = (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date()
    year, month = start.year, start.month
    items = {}
    while (year, month) <= (last.year, last.month):
        _budget(deadline_at)
        url = SOURCES[GREENWAY][0] + "?" + urlencode({"mo": month, "yr": year})
        for item in _greenway_month(fetch(url, "text/html"), year, month, now):
            if item["url"] in items and items[item["url"]] != item:
                raise ValueError("boston_remaining_calendar_changed")
            items[item["url"]] = item
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return sorted(items.values(), key=lambda x: (x["start"], x["url"]))


def _greenway_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    nodes = soup.select(".elementor-widget-theme-post-content .elementor-widget-container")
    exports = soup.select("a.em-a2c-google[href]")
    if not canonical or canonical.get("href") != card["url"] or len(nodes) != 1 or len(exports) != 1:
        raise ValueError("boston_remaining_detail_changed")
    # This link is parsed as publisher metadata; Google Calendar is never fetched.
    query = parse_qs(urlsplit(exports[0]["href"]).query)
    if query.get("ctz") != [ZONE] or plain((query.get("text") or [""])[0]) != card["title"]:
        raise ValueError("boston_remaining_detail_changed")
    dates = (query.get("dates") or [""])[0].split("/")
    if len(dates) != 2 or any(not re.fullmatch(r"\d{8}T\d{6}", d) for d in dates):
        raise ValueError("boston_remaining_time_conflict")
    start, end = [timestamp(datetime.strptime(d, "%Y%m%dT%H%M%S").isoformat(), ZONE) for d in dates]
    if start.isoformat() != card["start"] or end.isoformat() != card["end"]:
        raise ValueError("boston_remaining_time_conflict")
    body = _full(str(nodes[0]))
    if re.search(r"\b(?:cancelled|canceled|postponed)\b", card["title"], re.I):
        _hold(GREENWAY, card["url"], "boston_remaining_not_public", diagnostics)
        return []
    if not body or plain(body).casefold() == card["title"].casefold():
        _hold(GREENWAY, card["url"], "boston_remaining_description_missing", diagnostics)
        return []
    if not _within(start, end, now):
        _hold(GREENWAY, card["url"], "boston_remaining_outside_window", diagnostics)
        return []
    venue, raw = card["venue"], plain((query.get("location") or [""])[0])
    resolved = _street(raw)
    provenance, evidence, point = "publisher_event_export_street", card["url"], None
    if "Greenway Carousel" in card["title"] and resolved:
        venue = "The Greenway Carousel"
    if "Winter Supply Drive" in card["title"] and "Dewey Square Plaza" in body:
        venue, resolved = "Dewey Square Plaza", _street("600 Atlantic Avenue, Boston, MA 02210")
        provenance = "reviewed_named_venue_street"
        evidence = "https://www.rosekennedygreenway.org/locations/dewey-square-plaza/"
    if card["title"] in {"Giving Thanks: Coming Together", "CANDLELIT LABYRINTH WALK: IN PEACE & HARMONY"}:
        if "Mercantile" in raw and "Atlantic" in raw:
            venue, resolved = "Armenian Heritage Park", _street("115 Atlantic Avenue, Boston, MA 02110")
            provenance = "official_named_park_directions_street_pending_geocode"
            evidence = "https://www.armenianheritagepark.org/directions-parking"
    if card["title"] in {"Boston Harbor Distillery at The Greenway", "Boston Harbor Distillery on The Greenway"}:
        if "Beverage Garden" in body and "Greenway" in body and not raw:
            reviewed = REVIEWED_INTERSECTIONS[0]
            venue = reviewed["venue_name"]
            resolved = (reviewed["venue_address"], "Boston")
            point = (reviewed["lat"], reviewed["lng"])
            provenance = "official_named_venue_intersection_and_linked_map_marker"
            evidence = "https://bostonharbordistillery.com/pages/bhd-at-the-greenway"
    # Explicit per-event meeting sites for these park programs are reviewed
    # below. Unknown/variable Greenway locations never inherit office address.
    if not resolved or not venue:
        _hold(GREENWAY, card["url"], "boston_remaining_street_unresolved", diagnostics)
        return []
    image = soup.select_one('meta[property="og:image"]')
    row = _row(GREENWAY, card["title"], start, end, card["url"], f"greenway:{card['native_id']}",
               body, venue, resolved[0], resolved[1], point=point, categories=card["categories"],
               photo=image.get("content") if image else None, provenance=provenance, evidence=evidence)
    return [row] if row else []


def _nature_manifest(fetch, now, deadline_at):
    items, previous = {}, None
    for page in range(1, 9):
        _budget(deadline_at)
        url = SOURCES[NATURE][0] + (f"?page={page}" if page > 1 else "")
        soup = BeautifulSoup(fetch(url, "text/html"), "html.parser")
        cards = soup.select("article.event-card[data-next_meeting]")
        if not cards:
            raise ValueError("boston_remaining_calendar_changed")
        beyond = False
        for card in cards:
            a, title_node = card.select_one("a[href]"), card.select_one("h4")
            if not a or not title_node:
                raise ValueError("boston_remaining_calendar_changed")
            link = urljoin(SOURCES[NATURE][0], a["href"])
            start = timestamp(card["data-next_meeting"].replace(" ", "T"), ZONE)
            if (not event_url(NATURE, link) or not str(card.get("data-next_meeting_ts", "")).isdigit()
                    or int(start.timestamp()) != int(card["data-next_meeting_ts"])
                    or (previous is not None and start < previous)):
                raise ValueError("boston_remaining_calendar_changed")
            previous = start
            if start >= now + timedelta(days=60):
                beyond = True
                continue
            if start + timedelta(days=1) < now:
                continue
            venue = card.select_one(".event-card__content__place")
            item = {"url": link, "title": plain(title_node.get_text()), "start": start.isoformat(),
                    "venue": plain(venue.get_text(" ")) if venue else ""}
            if link in items and items[link] != item:
                raise ValueError("boston_remaining_calendar_changed")
            items[link] = item
        next_url = SOURCES[NATURE][0] + f"?page={page + 1}"
        has_next = any(urljoin(url, a["href"]) == next_url for a in soup.select('a[href*="page="]'))
        if beyond or not has_next:
            return list(items.values())
    raise ValueError("boston_remaining_pagination_incomplete")


def _nature_schema(soup):
    found = []
    def walk(obj):
        if isinstance(obj, list):
            for value in obj: walk(value)
        elif isinstance(obj, dict):
            if obj.get("@type") == "Event": found.append(obj)
            if "@graph" in obj: walk(obj["@graph"])
    for node in soup.select('script[type="application/ld+json"]'):
        try: walk(json.loads(node.string or node.get_text()))
        except (ValueError, TypeError): continue
    if len(found) != 1:
        raise ValueError("boston_remaining_detail_changed")
    return found[0]


def _nature_location(card, data, body, start):
    native = data.get("location") or {}
    if not isinstance(native, dict):
        return None
    address = native.get("address") or {}
    if not isinstance(address, dict):
        return None
    venue = plain(native.get("name"))
    resolved = _street(", ".join(plain(address.get(k)) for k in
                      ("streetAddress", "addressLocality", "addressRegion", "postalCode")))
    provenance, evidence = "publisher_program_postal_address", card["url"]
    # Specific meeting directions take precedence over a site's park centroid
    # or reusable sanctuary metadata. Never put a Milton walk in Boston.
    if "takes place along the Neponset River Reservation in Milton" in body:
        return None
    if "Squantum Point Park" in card["title"] or ("Nature Year" in card["title"] and start.month == 12
            and "Squantum Point Park" in body):
        return None  # Road lacks a numbered public entrance; separate review required.
    if "Winter Duck Walk Through Jamaica Plain" == card["title"]:
        return None  # Pond Ave parking lot is explicit, but street number is unverified.
    if "Belle Isle Marsh" in card["title"]:
        if "1399 Bennington" not in body and "1399 Bennington" not in plain(address.get("streetAddress")):
            return None  # Winthrop title alone does not establish the East Boston entrance.
        venue, resolved = "Belle Isle Marsh main entrance", _street("1399 Bennington Street, Boston, MA 02128")
        provenance = "publisher_program_meeting_instructions"
    if "Castle Island" in card["title"] and "2080 William J Day Blvd" in body:
        venue = "Sullivan's Castle Island parking lot"
        resolved = _street("2080 William J Day Boulevard, South Boston, MA 02127")
        provenance = "publisher_meeting_instructions_override_park_address"
    if "Millennium Park" in card["title"] and "300 Gardner St" in body:
        venue = "Millennium Park parking lot near canoe launch"
        resolved = _street("300 Gardner Street, West Roxbury, MA 02132")
        provenance = "publisher_program_meeting_instructions"
    return (venue, resolved[0], resolved[1], provenance, evidence) if venue and resolved else None


def _nature_detail(card, payload, now, diagnostics):
    soup = BeautifulSoup(payload, "html.parser")
    title_node = soup.select_one("h1")
    narrative = soup.select_one(".overview__content .attr-description")
    data = _nature_schema(soup)
    if not title_node or plain(title_node.get_text()) != card["title"] or plain(data.get("name")) != card["title"]:
        raise ValueError("boston_remaining_detail_changed")
    if (data.get("eventStatus") in {"https://schema.org/EventCancelled", "https://schema.org/EventPostponed"}
            or data.get("eventAttendanceMode") == "https://schema.org/OnlineEventAttendanceMode"
            or re.search(r"\b(?:cancelled|canceled|postponed)\b", card["title"], re.I)):
        _hold(NATURE, card["url"], "boston_remaining_not_public", diagnostics)
        return []
    core = _full(str(narrative)) if narrative else ""
    if not core or plain(core).casefold() == card["title"].casefold():
        _hold(NATURE, card["url"], "boston_remaining_description_missing", diagnostics)
        return []
    # Preserve complete native instructions, audience and admission facts as
    # published; JSON-LD's shortened marketing description is never used.
    sections = [str(narrative)]
    for selector in (".instructions-wrapper", ".info-card--who", ".info-card--admissions"):
        node = soup.select_one(selector)
        if node: sections.append(str(node))
    body = _full("\n".join(sections))
    dates = []
    for item in soup.select(".info-card--when li.short-date-time"):
        day, clock = item.select_one(".icon-date"), item.select_one(".icon-clock")
        if not day or not clock:
            raise ValueError("boston_remaining_time_conflict")
        date = datetime.strptime(plain(day.get_text()), "%a, %b %d, %Y").date().isoformat()
        dates.append(_clock_range(date, clock.get_text()))
    if (not dates or len(dates) > 50 or len(set(dates)) != len(dates)
            or timestamp(card["start"]) not in {start for start, _ in dates}
            or _offset_time(data.get("startDate")) not in {start for start, _ in dates}):
        raise ValueError("boston_remaining_time_conflict")
    out = []
    for start, end in dates:
        if not _within(start, end, now):
            continue
        location = _nature_location(card, data, body, start)
        if not location:
            _hold(NATURE, card["url"], "boston_remaining_street_unresolved", diagnostics)
            continue
        venue, street, city, provenance, evidence = location
        identity = "nature:" + urlsplit(card["url"]).path.split("/")[-1].split("-")[0] + ":" + start.astimezone(timezone.utc).isoformat()
        photo = data.get("image")
        if isinstance(photo, dict): photo = photo.get("url")
        if isinstance(photo, list): photo = photo[0] if photo else None
        row = _row(NATURE, card["title"], start, end, card["url"], identity, body, venue, street, city,
                   photo=photo, provenance=provenance, evidence=evidence)
        if row: out.append(row)
    if not out and not any(d["id"] == card["url"] for d in diagnostics):
        _hold(NATURE, card["url"], "boston_remaining_outside_window", diagnostics)
    return out


# These mappings identify the activity's actual public site, not the serving
# organization's headquarters. Matching requires both organization and native
# activity title, plus the publisher's ZIP. New locations remain held for review.
CARES_VENUES = (
    ("Catholic Charities Boston", "Yawkey Center Food Pantry", "Catholic Charities Yawkey Center Food Pantry",
     "185 Columbia Road, Dorchester, MA 02121", "https://www.ccab.org/about-us/locations/"),
    ("First Congregational Church Food Pantry of Revere", "FCC Food Pantry of Revere", "First Congregational Church Food Pantry",
     "230 Beach Street, Revere, MA 02151", None),
    ("Ellis Early Learning", "Jamaica Plain", "Ellis Early Learning Jamaica Plain",
     "555 Amory Street, Jamaica Plain, MA 02130", None),
    ("Mass Farmers Markets", "Central Square Farmers Market", "Central Square Farmers Market",
     "76 Bishop Allen Drive, Cambridge, MA 02139", "https://marketspread.com/market/4432/cambridge-central-square-farmers-market/"),
    ("Mass Farmers Markets", "Copley Square Farmers Market", "Copley Square Farmers Market",
     "227-230 Dartmouth Street, Boston, MA 02116", None),
    ("Mass Farmers Markets", "Davis Square Farmers Market", "Davis Square Farmers Market municipal lot",
     "44 Day Street, Somerville, MA 02144", "https://marketspread.com/market/10422/somervilledavis-square/"),
    ("Torchlight Recovery", "Daily Operations at Torchlight Recovery Cafe", "Torchlight Recovery Cafe",
     "2 Washington Street, Dorchester, MA 02121", "https://torchlightrecovery.org/contact-us/"),
    ("Hyde Park Emergency Food Pantry", "Hyde Park Emergency Food Pantry", "Hyde Park Emergency Food Pantry",
     "1179 River Street, Hyde Park, MA 02136", "https://www.boston.gov/sites/default/files/file/2026/02/KIPP.2.17.2026.pdf"),
    ("American Red Cross of Eastern Massachusetts Food Pantry", "American Red Cross Food Pantry", "American Red Cross Boston Food Pantry",
     "1033 Massachusetts Avenue, Boston, MA 02118", "https://www.redcross.org/local/massachusetts/about-us/our-work/food-and-nutrition-programs.html"),
    ("Victory Programs - Boston Living Center", "Boston Living Center", "Boston Living Center",
     "29 Stanhope Street, Boston, MA 02116", "https://www.vpi.org/blc-volunteers/"),
    ("Cambridge Women's Center", "Drop In Sessions at Cambridge Women's Center", "Cambridge Women's Center",
     "46 Pleasant Street, Cambridge, MA 02139", "https://www.cambridgewomenscenter.org/contact"),
    ("East End House", "East End House Pantry", "East End House Community Food Pantry",
     "105 Spring Street, Cambridge, MA 02141", None),
    ("St. Paul A.M.E. Church Food Pantry", "Church Food Pantry", "St. Paul AME Church Elnora Yard Food Pantry",
     "85 Bishop Allen Drive, Cambridge, MA 02139", "https://www.cambridgepublichealth.org/wp-content/uploads/2025/10/English-Food-Resource-Guide.pdf"),
    ("Friday Night Supper Program", "Friday Night Supper Program", "Friday Night Supper Program at Arlington Street Church",
     "351 Boylston Street, Boston, MA 02116", "https://www.fridaynightsupper.org/contact"),
    ("St. Luke's-San Lucas Episcopal Church", "St. Luke's Food Pantry", "St. Luke's-San Lucas Episcopal Church Food Pantry",
     "201 Washington Avenue, Chelsea, MA 02150", "https://lukelucas.org/contact-us/"),
    ("Hostelling International Boston", "HI Boston Hostel Welcome Parties", "HI Boston Hostel",
     "19 Stuart Street, Boston, MA 02116", "https://www.hiusa.org/hi-boston-hostel-faq"),
    ("Four Corners Main Street", "Indoor Garden Caretaker", "Codman Square Branch Library",
     "690 Washington Street, Dorchester, MA 02124", "https://www.bpl.org/locations/codman-square/"),
    ("Dedham Community House", "DCH Annual Tree & Wreath Sale", "Dedham Community House",
     "671 High Street, Dedham, MA 02026", "https://dchma.recdesk.com/Community/Facility/Detail?facilityId=1"),
)
FRESH_TRUCK_EVIDENCE = "https://cdn.shopify.com/s/files/1/0582/7896/9428/files/November_26.pdf?v=1793643796"
# The operator's November 2026 calendar is linked from its official weekly
# markets page. Only the venue address is reused; volunteer dates/times are
# always supplied by Boston Cares' explicit occurrence instances.
FRESH_TRUCK_VENUES = {
    "Neponset Health Center": ("Neponset Health Center", "10 Minot Street, Dorchester, MA 02122"),
    "Bowdoin St. Health Center": ("Bowdoin Street Health Center", "230 Bowdoin Street, Dorchester, MA 02122"),
    "Franklin Hill BGCB": ("Franklin Hill Boys & Girls Club", "42 Shandon Road, Dorchester, MA 02124"),
    "2Life Communities": ("2Life Communities Brighton", "40 Wallingford Road, Brighton, MA 02135"),
    "Mattapan Health Center": ("Mattapan Community Health Center", "1575 Blue Hill Avenue, Mattapan, MA 02126"),
    "ABCD Geneva": ("ABCD Geneva", "198 Geneva Avenue, Dorchester, MA 02121"),
    "Mission Park Apartments": ("Mission Park Apartments", "2 New Whitney Street, Boston, MA 02115"),
    "Elm Hill": ("Charles Street AME Church market", "13 Elm Hill Avenue, Dorchester, MA 02121"),
    "Charlestown BHA": ("Charlestown BHA market", "38 O'Reilly Way, Charlestown, MA 02129"),
    "Menino YMCA": ("Thomas M. Menino YMCA", "1137 River Street, Hyde Park, MA 02136"),
    "Village at Brookline": ("Village at Brookline", "99 Kent Street, Brookline, MA 02445"),
    "Lenox Camden": ("Lenox Camden market", "32 Kendall Street, Boston, MA 02118"),
    "Villa Victoria": ("Villa Victoria market", "15 San Juan Street, Boston, MA 02118"),
    "Mario Umana Academy": ("Mario Umana Academy market", "312 Border Street, East Boston, MA 02128"),
    "United Housing Management": ("United Housing market", "3 Quincy Street, Dorchester, MA 02121"),
}


def _cares_location(item, title, body):
    org = plain(item.get("organizationServedName"))
    postal = plain(item.get("locationZipCode")).split("-")[0]
    if org == "Fresh Truck":
        for marker, (venue, street) in FRESH_TRUCK_VENUES.items():
            if marker.casefold() in title.casefold() and street.endswith(postal):
                return venue, street, _street(street)[1], FRESH_TRUCK_EVIDENCE, "reviewed_operator_named_market_street"
        return None
    for organization, marker, venue, street, evidence in CARES_VENUES:
        if org != organization or marker.casefold() not in title.casefold() or not street.endswith(postal):
            continue
        # Native narrative guards avoid borrowing a specific site from a
        # differently located activity by the same organization.
        required = {"Ellis Early Learning": "555 Amory Street", "East End House": "105 Spring Street",
                    "First Congregational Church Food Pantry of Revere": "230 Beach Street",
                    "Four Corners Main Street": "Codman Square Branch"}
        if org in required and required[org].casefold() not in body.casefold():
            return None
        provenance = "reviewed_named_activity_venue_street" if evidence else "publisher_opportunity_full_narrative_street"
        if org.startswith("American Red Cross") and "02128" in body:
            provenance = "reviewed_official_pantrys_street_and_zip_override_native_zip_typo"
        return venue, street, _street(street)[1], evidence or item["opportunityLink"], provenance
    return None


def _cares_events(payload, now, first, last, diagnostics):
    data = json.loads(payload)
    if not isinstance(data, dict) or data.get("code") != 200 or not isinstance(data.get("items"), list):
        raise ValueError("boston_remaining_feed_changed")
    out, seen_days, seen_ids = [], set(), set()
    for day in data["items"]:
        if (not isinstance(day, dict) or day.get("overMaxToReturn") is not False
                or day.get("events") != [] or not isinstance(day.get("occurrences"), list)):
            raise ValueError("boston_remaining_pagination_incomplete")
        raw_day = day.get("dayDate")
        if not isinstance(raw_day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_day):
            raise ValueError("boston_remaining_time_conflict")
        date = datetime.strptime(raw_day, "%Y-%m-%d").date()
        if not first <= date <= last or raw_day in seen_days:
            raise ValueError("boston_remaining_feed_changed")
        seen_days.add(raw_day)
        for item in day["occurrences"]:
            if not isinstance(item, dict):
                raise ValueError("boston_remaining_feed_changed")
            url, identity = item.get("opportunityLink"), item.get("occurrenceId")
            if not event_url(CARES, url) or url.rsplit("/", 1)[-1] != identity or identity in seen_ids:
                raise ValueError("boston_remaining_feed_changed")
            seen_ids.add(identity)
            if (item.get("locationType") != "Address" or plain(item.get("locationState")) != "MA"
                    or plain(item.get("locationCity")) not in LOCALITIES
                    or not re.fullmatch(r"[1-9][0-9]*", str(item.get("volunteersStillNeeded", "")))):
                continue
            if item.get("scheduledType") != "Date & Time Specific" or item.get("timezone") != ZONE:
                raise ValueError("boston_remaining_time_conflict")
            dates = [item.get("startDateTimeISO"), item.get("endDateTimeISO")]
            if any(not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value) for value in dates):
                raise ValueError("boston_remaining_time_conflict")
            start, end = [timestamp(value, ZONE) for value in dates]
            if (start.date() != date or end <= start
                    or start != _local_clock(raw_day, item.get("startTime"))
                    or end != _local_clock(end.date().isoformat(), item.get("endTime"))):
                raise ValueError("boston_remaining_time_conflict")
            if not _within(start, end, now, days=14):
                continue
            title, body = plain(item.get("opportunityName")), _full(item.get("description"))
            if not title or not body or plain(body).casefold() == title.casefold():
                _hold(CARES, identity, "boston_remaining_description_missing", diagnostics)
                continue
            location = _cares_location(item, title, body)
            if not location:
                _hold(CARES, identity, "boston_remaining_street_unresolved", diagnostics)
                continue
            venue, street, city, evidence, provenance = location
            row = _row(CARES, title, start, end, url, "cares:" + identity, body,
                       venue, street, city, provenance=provenance, evidence=evidence)
            if row: out.append(row)
    if len(out) > MAX_RECORDS:
        raise ValueError("boston_remaining_record_limit")
    return out


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _checkpoint_valid(key, state, now):
    try:
        started = _offset_time(state["started_at"])
        manifest = state["manifest"]
        if (state["version"] != 1 or state["source_key"] != key
                or type(state["cursor"]) is not int or type(state["manifest_count"]) is not int
                or not isinstance(manifest, list) or not 0 <= state["cursor"] <= len(manifest) <= MAX_MANIFEST
                or state["manifest_count"] != len(manifest) or state["manifest_hash"] != _digest(manifest)
                or started.utcoffset() != timedelta(0) or not -60 <= (now - started).total_seconds() <= 14400
                or state["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or not isinstance(state["events"], list) or len(state["events"]) > MAX_CHECKPOINT_EVENTS
                or not isinstance(state["diagnostics"], list) or len(state["diagnostics"]) > 400
                or not isinstance(state["outcomes"], list) or len(state["outcomes"]) != state["cursor"]):
            return False
        for card in manifest:
            if (not isinstance(card, dict) or not event_url(key, card.get("url"))
                    or not isinstance(card.get("title"), str) or not card["title"].strip()
                    or not isinstance(card.get("start"), str) or _offset_time(card["start"]) is None):
                return False
        if len({c["url"] for c in manifest}) != len(manifest):
            return False
        prefix = {c["url"]: c for c in manifest[:state["cursor"]]}
        by_url = {url: [] for url in prefix}
        ids = set()
        for row in state["events"]:
            if not isinstance(row, dict) or row.get("event_url") not in prefix:
                return False
            card = prefix[row["event_url"]]
            exact_intersection = any(all(row.get(field) == place[field]
                for field in ("venue_name", "venue_address", "lat", "lng"))
                for place in REVIEWED_INTERSECTIONS if place["source_key"] == key)
            if (row.get("title") != card["title"] or row.get("timezone") != ZONE
                    or not isinstance(row.get("description"), str) or not row["description"].strip()
                    or len(row["description"]) > 12000 or not row.get("venue_name")
                    or (not _street(row.get("venue_address")) and not exact_intersection)
                    or ((row.get("lat") is not None or row.get("lng") is not None) and not exact_intersection)
                    or (row.get("image_url") and not photo_url(key, row["image_url"]))):
                return False
            start = _offset_time(row.get("starts_at"))
            end = _offset_time(row["ends_at"]) if row.get("ends_at") else None
            expected_id = (f"greenway:{card['native_id']}" if key == GREENWAY else
                "nature:" + urlsplit(card["url"]).path.split("/")[-1].split("-")[0] + ":" + start.isoformat())
            if (row.get("id") != expected_id or (expected_id, row["starts_at"]) in ids
                    or not _within(start, end, started)
                    or (key == GREENWAY and (start != timestamp(card["start"]) or end != timestamp(card["end"])))):
                return False
            ids.add((expected_id, row["starts_at"]))
            by_url[row["event_url"]].append(row)
        for index, outcome in enumerate(state["outcomes"]):
            if not isinstance(outcome, dict) or outcome.get("url") != manifest[index]["url"]:
                return False
            url = outcome["url"]
            if outcome.get("rows_hash") != _digest(by_url[url]):
                return False
            if not by_url[url] and not any(d.get("id") == url for d in state["diagnostics"] if isinstance(d, dict)):
                return False
        for diag in state["diagnostics"]:
            if not isinstance(diag, dict) or diag.get("id") not in prefix or diag.get("reason") not in ERROR_CODES:
                return False
        return len(json.dumps(state).encode()) <= MAX_CHECKPOINT_BYTES
    except (TypeError, ValueError, KeyError, OverflowError, AttributeError):
        return False


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, render_calendar=None):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError("unregistered_boston_remaining_source")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("boston_remaining_checkpoint_invalid")
    now = now.astimezone(timezone.utc)
    state = deepcopy(checkpoint) if checkpoint is not None else None
    if state is not None and not _checkpoint_valid(key, state, now):
        raise ValueError("boston_remaining_checkpoint_invalid")
    if state is None:
        manifest = (_greenway_manifest if key == GREENWAY else _nature_manifest)(fetch, now, deadline_at)
        if len(manifest) > MAX_MANIFEST:
            raise ValueError("boston_remaining_record_limit")
        state = {"version": 1, "source_key": key, "started_at": now.isoformat(),
                 "window_start": now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 "manifest": manifest, "manifest_hash": _digest(manifest),
                 "manifest_count": len(manifest), "cursor": 0, "events": [],
                 "diagnostics": [], "outcomes": []}
    for index in range(state["cursor"], min(len(state["manifest"]), state["cursor"] + DETAILS_PER_CHUNK)):
        if deadline_at is not None and monotonic() + 18 >= deadline_at:
            break
        card = state["manifest"][index]
        rows = (_greenway_detail if key == GREENWAY else _nature_detail)(
            card, fetch(card["url"], "text/html"), now, state["diagnostics"])
        state["events"].extend(rows)
        if not rows and not any(d["id"] == card["url"] for d in state["diagnostics"]):
            _hold(key, card["url"], "boston_remaining_outside_window", state["diagnostics"])
        state["outcomes"].append({"url": card["url"], "rows_hash": _digest(rows)})
        state["cursor"] = index + 1
    if len(state["events"]) > MAX_CHECKPOINT_EVENTS or len(json.dumps(state).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("boston_remaining_checkpoint_limit")
    complete = state["cursor"] == len(state["manifest"])
    return {"complete": complete, "events": deepcopy(state["events"]) if complete else [],
            "checkpoint": state, "diagnostics": deepcopy(state["diagnostics"])}


def collect(source, fetch, *, deadline_at=None, now=None, render_calendar=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)
    if key in CHECKPOINT_KEYS:
        state = None
        for _ in range(MAX_MANIFEST + 1):
            _budget(deadline_at)
            result = collect_chunk(source, fetch, checkpoint=state, deadline_at=deadline_at, now=now)
            if result["complete"]:
                return result["events"]
            state = result["checkpoint"]
        raise ValueError("boston_remaining_record_limit")
    diagnostics = []
    if key == BC:
        return _bc_collect(fetch, now, deadline_at, diagnostics)
    if key == CARES:
        if render_calendar is None:
            raise ValueError("boston_remaining_feed_changed")
        _budget(deadline_at)
        first = now.astimezone(ZoneInfo(ZONE)).date()
        # The public endpoint treats both supplied dates as inclusive.
        end = first + timedelta(days=13)
        payload = render_calendar(start_day=first.isoformat(), end_day=end.isoformat())
        return _cares_events(payload, now, first, end, diagnostics)
    raise ValueError("unregistered_boston_remaining_source")
