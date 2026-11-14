"""Ocean City Chamber and MainStreet Hammonton public event calendars.

Both adapters use the normal guarded fetch(url, accept) callback. The TEC
snapshot must finish every declared page; the Wix manifest must explicitly say
hasMore=False and every selected detail must validate before anything returns.
Native narratives are preserved in full and are never replaced by JSON-LD
taglines, clipped, or passed through an HTML parser after normalization.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp, tribe_timezone


log = logging.getLogger(__name__)
ZONE = "America/New_York"
OCEAN_CITY = "ocean_city_chamber_nj"
HAMMONTON = "downtown_hammonton_nj"
SOURCES = {
    OCEAN_CITY: ("https://oceancityvacation.com/resources/events-calendar/", "html", "html"),
    HAMMONTON: ("https://www.downtownhammonton.com/", "html", "html"),
}
ALLOWED_HOSTS = {
    OCEAN_CITY: ("oceancityvacation.com",),
    HAMMONTON: ("www.downtownhammonton.com",),
}
CHECKPOINT_KEYS = frozenset()
TEC_API = "https://oceancityvacation.com/wp-json/tribe/events/v1/events/"
WIX_APP = "140603ad-af8d-84a5-2c80-a0f60cb47351"
WIX_WIDGET = "widgetcomp-mhkznah2"
MAX_RECORDS = 500
MAX_PAGES = 5
MAX_DETAILS = 8
MAX_DESCRIPTION = 12_000
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|private (?:event|party)|invitation[- ]only|members?[- ]only|sold[- ]out)\b", re.I)
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
APPROXIMATE_VENUE = "Hammonton Tree Lighting / The Bellevue (approximate meeting point)"

# These are reviewed venue associations, not source-wide defaults. The Chamber
# publishes both addresses and exact venue points in the current TEC payload.
# Frozen Jr.'s own producer confirms the Music Pier for all three dated shows:
# https://oceancitytheatrecompany.com/season/2026season/
# https://oceancitytheatrecompany.com/show/frozen-jr/
# Nov 21 carriage text itself says "9th & Asbury Ave in front of City Hall";
# later occurrences in the same publisher identify 901 Asbury Avenue.
MUSIC_PIER = ("Music Pier", "825 Boardwalk, Ocean City, NJ 08226", "Ocean City",
              39.2751976, -74.5695462)
CITY_HALL = ("Downtown Asbury Avenue", "901 Asbury Avenue, Ocean City, NJ 08226", "Ocean City",
             39.27853, -74.57623)
MISSING_VENUE_REVIEW = {
    "388424": ("Horse & Carriage Rides", "2026-11-21", "ee7dd0c255cc12f2fc2bb8721a185b381ffa34b52fed83e29b24d8517dedd5d1", CITY_HALL),
    "388436": ("Annual Fast & Furriest 5k Turkey Trot", "2026-11-26", "e4cf00abb5e83139a20dfc64a06bf55b1714b7937e6091c64987bf5983e57e79", MUSIC_PIER),
    "10002117": ("FROZEN JR", "2026-12-18", "1dd53df53aef4516fda099431f8f3879ab7c1f30511dfb8436cfaa18da645360", MUSIC_PIER),
    "10002118": ("FROZEN JR", "2026-12-19", "1dd53df53aef4516fda099431f8f3879ab7c1f30511dfb8436cfaa18da645360", MUSIC_PIER),
    "10002119": ("FROZEN JR", "2026-12-19", "1dd53df53aef4516fda099431f8f3879ab7c1f30511dfb8436cfaa18da645360", MUSIC_PIER),
}

# Corrections apply only to the reviewed publisher occurrence, original clock
# pair, and unchanged full native description. A new date/body cannot inherit
# an old correction. RunSignup's 2026 SportsEvent + public Place establish the
# Turkey Trot at 08:30, Music Pier; its prose still contains a stale 2025 date.
# https://runsignup.com/Race/NJ/OceanCity/TheFastandthefurriest5KTurkeyTrot
# https://www.firstnightocnj.com/first-day confirms the 13:00 race separately
# from 11:00 registration. First Night's own complete Chamber body explicitly
# begins festivities with the 15:45 kickoff and continues to midnight fireworks;
# 23:59 is not a verified finish for those fireworks, so the end stays unknown.
SCHEDULE_REVIEW = {
    "388436": ("2026-11-26 08:00:00", "2026-11-26 17:00:00",
               "e4cf00abb5e83139a20dfc64a06bf55b1714b7937e6091c64987bf5983e57e79",
               "2026-11-26T08:30:00", None, "reviewed_organizer_2026_race_start_unknown_end"),
    "388452": ("2027-01-01 11:00:00", "2027-01-01 13:30:00",
               "8b0c70b1f35d4475cad861e5ea2006d7143fb687b44941f4e3d235f54e303b83",
               "2027-01-01T13:00:00", "2027-01-01T13:30:00", "publisher_body_race_start_after_registration"),
    "388448": ("2026-12-31 16:00:00", "2026-12-31 23:59:00",
               "f4281e2c5b6ee7fc34569beead1bc9ab9cc3dcaa11bdb403f1c507127fefde71",
               "2026-12-31T15:45:00", None, "publisher_body_kickoff_unknown_fireworks_end"),
}


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc != ALLOWED_HOSTS[key][0]
                or p.username or p.password or p.port not in (None, 443)
                or p.query or p.fragment or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)):
            return False
        pattern = (r"/events-calendar/[a-z0-9]+(?:-[a-z0-9]+)*/(?:20\d{2}-\d{2}-\d{2}/(?:[1-9]\d*/)?)?"
                   if key == OCEAN_CITY else r"/event-details-registration/[a-z0-9]+(?:-[a-z0-9]+)*")
        return re.fullmatch(pattern, p.path) is not None
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
                or p.netloc != p.hostname or p.fragment or p.query or ".." in p.path.split("/")
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)):
            return None
        if key == OCEAN_CITY and p.hostname == "oceancityvacation.com" and p.path.startswith("/wp-content/uploads/"):
            return value if re.search(r"\.(?:png|jpe?g|webp)$", p.path, re.I) else None
        # The Wix image host's robots endpoint returned 403 during this batch.
        # Do not enqueue optional Hammonton images for a known-denied fetch.
    except ValueError:
        pass
    return None


def _check_deadline(deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _body(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("atlantic_city_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("atlantic_city_description_limit")
    return value


def _space(value):
    # Whitespace-only comparison: literal <...> in already normalized prose is
    # meaningful and must not be stripped by the shared HTML title helper.
    return re.sub(r"\s+", " ", value).strip()


def _point(key, lat, lng):
    if isinstance(lat, bool) or isinstance(lng, bool):
        raise ValueError("local_markets_venue_point_invalid")
    try:
        lat, lng = float(lat), float(lng)
    except (ValueError, TypeError):
        raise ValueError("local_markets_venue_point_invalid") from None
    bounds = (39.20, 39.35, -74.68, -74.50) if key == OCEAN_CITY else (39.57, 39.70, -74.90, -74.74)
    if not (math.isfinite(lat) and math.isfinite(lng)
            and bounds[0] <= lat <= bounds[1] and bounds[2] <= lng <= bounds[3]):
        raise ValueError("local_markets_venue_point_invalid")
    return lat, lng


def _full_street(street, city, state, postal):
    street, city, state, postal = (plain(x) for x in (street, city, state, postal))
    if (not re.fullmatch(r"\d{1,6}\s+[^,\n]+", street) or not city
            or state not in ("NJ", "New Jersey") or not re.fullmatch(r"\d{5}(?:-\d{4})?", postal)):
        raise ValueError("local_markets_street_missing")
    return f"{street}, {city}, NJ {postal}"


def _tec_schedule(item):
    zone = item.get("timezone")
    if zone not in (ZONE, "UTC-5", "UTC-4"):
        raise ValueError("local_markets_timezone_changed")
    fixed_zone, _ = tribe_timezone(zone)
    values = []
    for field in ("start_date", "end_date"):
        local = timestamp(item.get(field), ZONE)
        utc = timestamp(item.get("utc_" + field), "UTC")
        if local is None or utc is None or local != utc or local.utcoffset() != local.astimezone(fixed_zone).utcoffset():
            raise ValueError("local_markets_schedule_conflict")
        values.append(local)
    start, end = values
    if end < start:
        raise ValueError("local_markets_schedule_conflict")
    provenance = "publisher_native_schedule"
    review = SCHEDULE_REVIEW.get(str(item["id"]))
    if review:
        native_pair = (item["start_date"], item["end_date"])
        corrected_pair = tuple(value.replace("T", " ") if value else None for value in review[3:5])
        # A changed bad clock must not evade the review merely by differing
        # from the original bad pair. Only the reviewed original or the exact
        # corrected pair, with the unchanged full native body, is accepted.
        if (native_pair not in (review[:2], corrected_pair)
                or sha256(item["description"].encode()).hexdigest() != review[2]):
            raise ValueError("local_markets_clock_review_changed")
        start, end = timestamp(review[3], ZONE), timestamp(review[4], ZONE)
        provenance = review[5]
    return start, None if end == start else end, provenance


def _tec_venue(item, start):
    native = item.get("venue")
    if not native:
        reviewed = MISSING_VENUE_REVIEW.get(str(item["id"]))
        if (not reviewed or (plain(item["title"]), start.date().isoformat(),
                             sha256(item["description"].encode()).hexdigest()) != reviewed[:3]):
            raise ValueError("local_markets_street_missing")
        return (*reviewed[3], "reviewed_event_venue_association_publisher_point")
    if not isinstance(native, dict):
        raise ValueError("local_markets_venue_changed")
    city = plain(native.get("city"))
    if city != "Ocean City" or not plain(native.get("venue")):
        raise ValueError("local_markets_venue_changed")
    street = _full_street(native.get("address"), city,
                          native.get("state") or native.get("stateprovince") or native.get("province"), native.get("zip"))
    lat, lng = _point(OCEAN_CITY, native.get("geo_lat"), native.get("geo_lng"))
    return plain(native["venue"]), street, city, lat, lng, "publisher_event_venue_point"


def _enrich(row, body, venue, schedule_provenance, image=None):
    if row is None:
        return None
    name, street, city, lat, lng, location_provenance = venue
    row.update(description=_body(body), venue_name=name, venue_address=street, venue_city=city,
               lat=lat, lng=lng, timezone=ZONE, attendance_mode="in_person", reason=None,
               location_provenance=location_provenance, schedule_provenance=schedule_provenance)
    if image:
        row["image_url"] = image
    return row


def _tribe(fetch, deadline, now):
    local_now = now.astimezone(ZoneInfo(ZONE))
    params = dict(start_date=local_now.date().isoformat(),
                  end_date=(local_now + timedelta(days=60)).date().isoformat(), per_page=100)
    accepted, info, seen = [], {}, set()
    totals = None
    for page in range(1, MAX_PAGES + 1):
        _check_deadline(deadline)
        data = json.loads(fetch(TEC_API + "?" + urlencode({**params, "page": page}), "application/json"))
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise ValueError("unsupported_wordpress_payload")
        pages, total = data.get("total_pages"), data.get("total")
        if (type(pages) is not int or not 0 <= pages <= MAX_PAGES
                or type(total) is not int or not 0 <= total <= MAX_RECORDS or len(data["events"]) > 100):
            raise ValueError("invalid_wordpress_pagination")
        if totals is None:
            totals = (pages, total)
        elif totals != (pages, total):
            raise ValueError("local_markets_snapshot_changed")
        for item in data["events"]:
            if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0:
                raise ValueError("local_markets_event_identity")
            identity = str(item["id"])
            if identity in seen:
                raise ValueError("local_markets_duplicate_occurrence")
            seen.add(identity)
            title = plain(item.get("title"))
            if (item.get("status") != "publish" or NONPUBLIC.search(title)
                    or item.get("event_status") in ("cancelled", "canceled", "postponed")
                    or any(item.get(flag) in (True, 1, "1", "true") for flag in
                           ("all_day", "virtual", "is_virtual", "hide_from_listings"))):
                continue
            if not isinstance(item.get("description"), str):
                raise ValueError("invalid_wordpress_description")
            start, end, schedule_provenance = _tec_schedule(item)
            if not _within(start, end, now):
                continue
            if not title or not event_url(OCEAN_CITY, item.get("url")):
                raise ValueError("local_markets_event_identity")
            body = narrative(item["description"])
            if NONPUBLIC.search(body):
                log.warning("local_markets_held source=%s id=%s reason=nonpublic_or_unavailable", OCEAN_CITY, identity)
                continue
            venue = _tec_venue(item, start)
            name, full, city, lat, lng, _ = venue
            street = full.rsplit(", ", 2)[0]
            normalized = dict(venue=name, address=street, city=city, state="NJ",
                              zip=full.rsplit(" ", 1)[-1], geo_lat=lat, geo_lng=lng)
            accepted.append({**item, "venue": normalized, "timezone": ZONE,
                             "utc_start_date": start.astimezone(timezone.utc).isoformat(),
                             "utc_end_date": end.astimezone(timezone.utc).isoformat() if end else None,
                             "end_date": end.isoformat() if end else None})
            image = item.get("image") or {}
            info[identity] = (body, venue, schedule_provenance,
                              photo_url(OCEAN_CITY, image.get("url")) if isinstance(image, dict) else None)
        if page >= pages:
            if len(seen) != total:
                raise ValueError("local_markets_incomplete_snapshot")
            break
    # Reuse the established TEC factual parser without its general 2k body
    # helper. The complete native narrative is explicitly mapped afterward.
    rows = parse_tribe({"events": accepted}, strict_public=True, retain_description=False)
    parsed = {r["id"] for r in rows}
    for item in accepted:
        identity = str(item["id"])
        if identity in parsed:
            continue
        start, end = timestamp(item["utc_start_date"]), timestamp(item["utc_end_date"])
        if not start <= now < (end or start + timedelta(hours=3)):
            raise ValueError("local_markets_incomplete_parse")
        venue = info[identity][1]
        row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
                     *venue[:3], item["url"], identity, lat=venue[3], lng=venue[4], tz=ZONE,
                     publisher_geo=True, retain_until_end=True)
        if row is None:
            raise ValueError("local_markets_incomplete_parse")
        rows.append(row)
    return [_enrich(row, *info[row["id"]]) for row in rows]


def _wix_app(soup):
    scripts = soup.select('script#wix-warmup-data[type="application/json"]')
    if len(scripts) != 1:
        raise ValueError("local_markets_wix_calendar_changed")
    data = json.loads(scripts[0].get_text())
    if not isinstance(data, dict):
        raise ValueError("local_markets_wix_calendar_changed")
    app = data.get("appsWarmupData", {}).get(WIX_APP)
    if not isinstance(app, dict):
        raise ValueError("local_markets_wix_calendar_changed")
    return app


def _wix_schedule(event):
    if (not isinstance(event, dict) or not UUID.fullmatch(str(event.get("id", "")))
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(event.get("slug", "")))
            or not plain(event.get("title"))):
        raise ValueError("local_markets_event_identity")
    config = event.get("scheduling", {}).get("config", {})
    if (config.get("timeZoneId") != ZONE or config.get("scheduleTbd") is not False
            or type(config.get("endDateHidden")) is not bool):
        raise ValueError("local_markets_wix_clock_changed")
    recurrence = config.get("recurrences")
    if not isinstance(recurrence, dict) or recurrence.get("occurrences") != [] or recurrence.get("status") != 0:
        raise ValueError("local_markets_wix_recurrence_unreviewed")
    if not isinstance(config.get("startDate"), str) or not config["startDate"].endswith("Z"):
        raise ValueError("local_markets_wix_clock_changed")
    start = timestamp(config["startDate"]).astimezone(ZoneInfo(ZONE))
    end = None
    if not config["endDateHidden"]:
        if not isinstance(config.get("endDate"), str) or not config["endDate"].endswith("Z"):
            raise ValueError("local_markets_wix_clock_changed")
        end = timestamp(config["endDate"]).astimezone(ZoneInfo(ZONE))
        if end <= start:
            raise ValueError("local_markets_schedule_conflict")
    return start, end


def _rich_text(value, depth=0):
    if depth > 30 or not isinstance(value, dict):
        raise ValueError("local_markets_wix_description_shape_changed")
    kind = value.get("type")
    if kind == "TEXT":
        text = value.get("textData", {}).get("text")
        if not isinstance(text, str):
            raise ValueError("local_markets_wix_description_shape_changed")
        return text
    if kind not in (None, "PARAGRAPH", "HEADING", "BULLETED_LIST", "ORDERED_LIST", "LIST_ITEM", "BLOCKQUOTE"):
        raise ValueError("local_markets_wix_description_shape_changed")
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 500:
        raise ValueError("local_markets_wix_description_shape_changed")
    joined = "".join(_rich_text(node, depth + 1) for node in nodes)
    return joined + ("\n" if kind in ("PARAGRAPH", "HEADING", "LIST_ITEM", "BLOCKQUOTE") else "")


def _wix_venue(event, body):
    location = event.get("location")
    if not isinstance(location, dict) or location.get("type") != 0 or location.get("tbd") is not False:
        raise ValueError("local_markets_venue_changed")
    full = location.get("fullAddress") or {}
    if full.get("country") != "US" or full.get("subdivision") != "NJ" or full.get("city") != "Hammonton":
        raise ValueError("local_markets_venue_changed")
    if (event["id"] == "5db02f30-416d-45cb-96b0-8f6015ee87e9"
            and event["slug"] == "hammonton-tree-lighting-ceremony"
            and location.get("name") == "Hammonton"
            and full.get("formattedAddress") == "Central Ave, Hammonton, NJ 08037, USA"
            and "The Bellevue Christmas Village" in body):
        # The source's road-center pin is several miles from this downtown
        # intersection. The participating Bellevue is ~48m from the tree's
        # Bellevue/Central intersection and provides an honest numbered meeting
        # point. Native prose is unchanged; the venue label exposes approximation.
        # Venue: https://www.hammontonimaginarium.com/ (236 Bellevue Avenue).
        # NJ OGIS PointAddress, score100, reviewed 2026-11-14:
        # https://geo.nj.gov/arcgis/rest/services/Tasks/NJ_Geocode/GeocodeServer/findAddressCandidates
        return (APPROXIMATE_VENUE, "236 Bellevue Avenue, Hammonton, NJ 08037", "Hammonton",
                39.636711000003, -74.802199500001, "reviewed_nearby_event_landmark_approximate_meeting_point")
    street = full.get("streetAddress") or {}
    if not isinstance(street, dict) or not str(street.get("number", "")).isdigit():
        raise ValueError("local_markets_street_missing")
    address = _full_street(f"{street['number']} {street.get('name', '')}", "Hammonton", "NJ", full.get("postalCode"))
    if street.get("apt"):
        raise ValueError("local_markets_venue_changed")
    coordinates, geocode = location.get("coordinates") or {}, full.get("geocode") or {}
    lat, lng = _point(HAMMONTON, coordinates.get("lat"), coordinates.get("lng"))
    if (lat, lng) != _point(HAMMONTON, geocode.get("latitude"), geocode.get("longitude")):
        raise ValueError("local_markets_venue_point_invalid")
    if not plain(location.get("name")):
        raise ValueError("local_markets_venue_changed")
    return plain(location["name"]), address, "Hammonton", lat, lng, "publisher_event_venue_point"


def _wix_detail(expected, payload):
    soup = BeautifulSoup(payload, "html.parser")
    app = _wix_app(soup)
    event = app.get("EventsPageInitialState", {}).get("event", {}).get("event")
    if not isinstance(event, dict):
        raise ValueError("local_markets_event_identity")
    for field in ("id", "slug", "title", "status", "scheduling", "location"):
        if event.get(field) != expected.get(field):
            raise ValueError("local_markets_snapshot_changed")
    url = SOURCES[HAMMONTON][0] + "event-details-registration/" + event["slug"]
    canonical = soup.select_one('link[rel="canonical"]')
    heading = soup.select_one('[data-hook="event-title"]')
    if (not event_url(HAMMONTON, url) or canonical is None or canonical.get("href") != url
            or heading is None or _space(heading.get_text(" ")) != _space(event["title"])):
        raise ValueError("local_markets_event_identity")
    start, end = _wix_schedule(event)
    bodies = soup.select('[data-hook="about-section"] [data-id="content-viewer"]')
    if len(bodies) != 1:
        raise ValueError("local_markets_wix_description_container_changed")
    body = narrative(bodies[0])
    full_native = _body(_rich_text(event.get("longDescription")).strip())
    if _space(body) != _space(full_native):
        raise ValueError("local_markets_full_description_mismatch")
    venue = _wix_venue(event, body)
    # Cross-check the public JSON-LD schedule; deliberately ignore its tagline.
    ld = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            item = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict) and item.get("@type") == "Event":
            ld.append(item)
    if (len(ld) != 1 or ld[0].get("eventStatus") != "https://schema.org/EventScheduled"
            or ld[0].get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
            or timestamp(ld[0].get("startDate")) != start
            or timestamp(ld[0].get("endDate")) != end):
        raise ValueError("local_markets_schedule_conflict")
    row = record(event["title"], start.isoformat(), end.isoformat() if end else None,
                 *venue[:3], url, event["id"], lat=venue[3], lng=venue[4], tz=ZONE,
                 publisher_geo=True, retain_until_end=True)
    image = ld[0].get("image")
    image = image.get("url") if isinstance(image, dict) else image
    row = _enrich(row, body, venue, "publisher_visible_end" if end else "publisher_hidden_end_unknown",
                  photo_url(HAMMONTON, image))
    if row is None:
        raise ValueError("local_markets_incomplete_parse")
    if venue[0] == APPROXIMATE_VENUE:
        row["publisher_venue_address"] = "Central Ave, Hammonton, NJ 08037, USA"
        row["location_resolution_note"] = "Bellevue/Central tree gathering; participating Bellevue Christmas Village is an approximate meeting point, not an exact tree pin."
    return row


def _hammonton(fetch, deadline, now):
    soup = BeautifulSoup(fetch(SOURCES[HAMMONTON][0], "text/html"), "html.parser")
    widget = _wix_app(soup).get(WIX_WIDGET)
    data = widget.get("events") if isinstance(widget, dict) else None
    if (not isinstance(data, dict) or not isinstance(data.get("events"), list)
            or data.get("hasMore") is not False or data.get("moreLoading") is not False):
        raise ValueError("local_markets_wix_incomplete_manifest")
    events = data["events"]
    if len(events) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    selected, seen, manifest_urls = [], set(), set()
    for event in events:
        start, end = _wix_schedule(event)
        if event["id"] in seen:
            raise ValueError("local_markets_duplicate_occurrence")
        seen.add(event["id"])
        url = SOURCES[HAMMONTON][0] + "event-details-registration/" + event["slug"]
        if not event_url(HAMMONTON, url):
            raise ValueError("local_markets_event_identity")
        manifest_urls.add(url)
        if event.get("status") == 0 and not NONPUBLIC.search(event["title"]) and _within(start, end, now):
            selected.append((url, event))
    visible_urls = {a.get("href") for a in soup.select('a[href*="/event-details-registration/"]')}
    if visible_urls != manifest_urls:
        raise ValueError("local_markets_wix_incomplete_manifest")
    if len(selected) > MAX_DETAILS:
        raise ValueError("local_markets_detail_limit")
    rows = []
    for url, event in selected:
        _check_deadline(deadline)
        rows.append(_wix_detail(event, fetch(url, "text/html")))
    return rows


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    if (key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                              source.get("timezone")) != (*SOURCES[key], ZONE)):
        raise ValueError("unregistered_atlantic_local_markets_source")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("local_markets_clock_invalid")
    deadline = min(deadline_at or float("inf"), monotonic() + 35)

    def get(url, accept):
        _check_deadline(deadline)
        return fetch(url, accept)

    rows = _tribe(get, deadline, now) if key == OCEAN_CITY else _hammonton(get, deadline, now)
    if len(rows) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    identities = {(row["id"], row["starts_at"]) for row in rows}
    if len(identities) != len(rows):
        raise ValueError("local_markets_duplicate_occurrence")
    _check_deadline(deadline)
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"]))
