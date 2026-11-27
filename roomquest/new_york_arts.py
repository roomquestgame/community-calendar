"""New York arts, family, books and markets with complete publisher narratives.

The existing factual TEC parser owns occurrence normalization. Source-scoped
reviews supply evidenced museum rooms/addresses and restore the complete native
description after that parser's legacy 2,000-character preview limit. Squarespace
uses permitted public HTML, never its robots-disallowed JSON/ICS exports.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from hashlib import sha256
import json
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = "America/New_York"
CMOM = "municipal_mapsee_4d60394f1806d3366dd987d3"
SI_CHILDREN = "municipal_mapsee_ff1f81293a6a6ae75a21a2d8"
SI_MUSEUM = "staten_island_museum_ny"
QUEENS_FARM = "queens_county_farm_museum_ny"
MOVING_IMAGE = "museum_of_moving_image_ny"
POSTER = "poster_house_ny"
MATERIALS = "materials_for_arts_ny"
LATIMER = "lewis_latimer_house_ny"
RICHMOND = "historic_richmond_town_ny"
POWERHOUSE = "powerhouse_arena_ny"
BAZAAR = "grand_bazaar_nyc_ny"
SOURCES = {
    CMOM: ("https://cmom.org", "html", "html"),
    SI_CHILDREN: ("https://sichildrensmuseum.org", "html", "html"),
    SI_MUSEUM: ("https://www.statenislandmuseum.org/events/", "html", "html"),
    QUEENS_FARM: ("https://www.queensfarm.org/events-calendar/", "html", "html"),
    MOVING_IMAGE: ("https://movingimage.org/events/", "html", "html"),
    POSTER: ("https://posterhouse.org/events/", "html", "html"),
    MATERIALS: ("https://www.materialsforthearts.org/events/", "html", "html"),
    LATIMER: ("https://www.lewislatimerhouse.org/events", "html", "html"),
    RICHMOND: ("https://www.historicrichmondtown.org/events", "html", "html"),
    POWERHOUSE: ("https://powerhousearena.com/events/", "html", "html"),
    BAZAAR: ("https://grandbazaarnyc.org/events/", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
TRIBE_API = {key: "https://" + ALLOWED_HOSTS[key][0] + "/wp-json/tribe/events/v1/events"
             for key in (CMOM, SI_CHILDREN, SI_MUSEUM, QUEENS_FARM, MOVING_IMAGE, POSTER, MATERIALS)}
MAX_RECORDS = 500
MAX_PAGES = 5
MAX_DETAILS = 10
MAX_DESCRIPTION = 12000
CHECKPOINT_KEYS = {BAZAAR}
MAX_CHECKPOINT_BYTES = 900_000
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|private (?:event|party|function)|"
                       r"members?[- ]only|invitation[- ]only)\b", re.I)
REMOTE_TITLE = re.compile(r"\b(?:virtual|online|webinar)\b", re.I)
STREET = re.compile(r"^\d{1,6}(?:-\d{1,6})?\s+\S")

# Exact addresses from publisher visit/venue pages, reviewed 2026-11-14. Do not
# replace another venue's event address with an institution-wide location.
VENUES = {
    CMOM: ("Children's Museum of Manhattan", "212 West 83rd Street", "New York", "10024"),
    SI_CHILDREN: ("Staten Island Children's Museum", "1000 Richmond Terrace Building M", "Staten Island", "10301"),
    MOVING_IMAGE: ("Museum of the Moving Image", "36-01 35th Avenue", "Astoria", "11106"),
    POSTER: ("Poster House", "119 West 23rd Street", "New York", "10011"),
    LATIMER: ("Lewis Latimer House", "34-41 137th Street", "Flushing", "11354"),
    RICHMOND: ("Historic Richmond Town", "441 Clarke Avenue", "Staten Island", "10306"),
    BAZAAR: ("Grand Bazaar NYC", "100 West 77th Street", "New York", "10024"),
}
CMOM_ROOMS = {1785: "Inside Art", 1006: "PlayWorks", 1059: "Makerspace",
              3793: "PlayWorks Classroom", 1791: "Discovery Classroom"}
SI_PARKS = {
    4669: ("Silver Lake Park", "700 Victory Boulevard", "Staten Island", "10301"),
    4737: ("Blue Heron Park", "222 Poillon Ave", "Staten Island", "10312"),
    # NPS / NASA Night Sky Network identify this park entrance. The event's
    # complete description retains its more precise parking-lot meeting point.
    4741: ("Great Kills Park (park entrance; see meeting directions)", "3270 Hylan Boulevard", "Staten Island", "10306"),
    # The publisher supplies 420 Cornelia and parking-lot directions. NYC PAD
    # has only a named-park point, so disclose the meeting-point approximation.
    5184: ("Wolfe’s Pond Park (approximate meeting point)", "420 Cornelia Ave.", "Staten Island", "10312"),
}
POWERHOUSE_VENUES = {
    "/locations/powerhouse/": ("POWERHOUSE Arena", "28 Adams Street", "Brooklyn", "11201"),
    "/locations/powerhouse-at-columbus-circle/": ("Powerhouse at Columbus Circle", "10 Columbus Circle #304", "New York", "10019"),
}
SQUARESPACE_SITE = {LATIMER: "611e9f67902c95124eaa0d6e", RICHMOND: "5b24209fda02bc5bf5953ca1"}
# Exact NYC Planning PAD address points, reviewed against the museums' own
# visitor addresses. The geocoder returned nearby alternatives; only matching
# house numbers, streets, Queens neighborhoods and ZIPs were selected.
REVIEWED_PAD_POINTS = {
    (MOVING_IMAGE, "Museum of the Moving Image", "36-01 35th Avenue, Astoria, NY 11106"):
        (40.756305, -73.923916),
    (QUEENS_FARM, "Queens County Farm Museum", "73-50 Little Neck Parkway, Queens, NY 11004"):
        (40.748426, -73.720186),
    (POWERHOUSE, "Powerhouse at Columbus Circle", "10 Columbus Circle #304, New York, NY 10019"):
        (40.768554, -73.983181),
}
REVIEWED_APPROXIMATE_POINTS = {
    (SI_MUSEUM, "Wolfe’s Pond Park (approximate meeting point)", "420 Cornelia Ave., Staten Island, NY 10312"):
        (40.51806, -74.19006),
}


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.query or p.fragment:
            return False
        prefix = "/event/" if key in TRIBE_API else "/events/"
        return bool(re.fullmatch(re.escape(prefix) + r"[a-z0-9-]+(?:/20\d{2}-\d{2}-\d{2})?(?:/\d+)?/?", p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.fragment:
            return None
        if key in SQUARESPACE_SITE:
            if (p.netloc == "images.squarespace-cdn.com"
                    and p.path.startswith("/content/v1/" + SQUARESPACE_SITE[key] + "/")
                    and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)
                    and set(parse_qs(p.query)) <= {"format"}):
                return value
        elif (p.netloc in ALLOWED_HOSTS[key] and not p.query
              and re.fullmatch(r"/(?:arena/)?wp-content/uploads/20\d{2}/\d{2}/[^/]+\.(?:jpe?g|png|webp)", p.path, re.I)):
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    # The museum and Materials for the Arts expose these exact venue points in
    # their own TEC venue objects. No city-center/coverage pins are used.
    points = {
        (SI_CHILDREN, "Staten Island Children's Museum", "1000 Richmond Terrace Building M, Staten Island, NY 10301"):
            (40.644743798098, -74.102321811388),
        (MATERIALS, "Materials for the Arts", "33-00 Northern Blvd 3rd Floor, Long Island City, NY 11101"):
            (40.751751, -73.931411),
        # Museum's own directions-page Map link, Google place CID
        # 12990998295020515734; use marker coordinates, not map viewport center.
        (SI_MUSEUM, "Staten Island Museum at Snug Harbor", "1000 Richmond Terrace Building A, Staten Island, NY 10301"):
            (40.6444768, -74.1027563),
    }
    identity = (key, venue, address)
    return points.get(identity) or REVIEWED_PAD_POINTS.get(identity) or REVIEWED_APPROXIMATE_POINTS.get(identity)


def _held(key, identity, reason):
    log.warning("new_york_arts_event_held source=%s id=%s reason=%s", key, identity, reason)


def _check_deadline(deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")


def _body(value):
    # Probe one character beyond the contract instead of silently truncating.
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError("new_york_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("new_york_description_limit")
    return text


def _address(street, city, state, postal):
    street = re.sub(r"\s*,\s*", " ", plain(street)).strip()
    state = "NY" if plain(state) in ("NY", "New York") else plain(state)
    if not STREET.match(street) or not city or state != "NY" or not re.fullmatch(r"\d{5}(?:-\d{4})?", str(postal or "")):
        raise ValueError("new_york_street_address_unresolved")
    return f"{street}, {plain(city)}, {state} {postal}"


def _venue_dict(profile):
    name, street, city, postal = profile
    return {"venue": name, "address": street, "city": city, "state": "NY", "zip": postal}


def _within(start, end, now):
    window_start = calendar_anchor(now)
    return start < window_start + timedelta(days=60) and (end or start + timedelta(hours=3)) > window_start


def _source_coordinates(venue):
    """Return only coordinates stated by this event's native venue object."""
    if not isinstance(venue, dict):
        return None, None
    try:
        lat = float(venue.get("geo_lat"))
        lng = float(venue.get("geo_lng"))
    except (TypeError, ValueError):
        return None, None
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else (None, None)


def _attach_content(row, **facts):
    """Attach event-owned facts before EventQuest enrichment or source labels."""
    if row is None:
        return None
    compact = {key: value for key, value in facts.items()
               if value is not None and value != "" and value != [] and value != {}}
    compact["is_all_day"] = False
    row["collector_event_content_v1"] = {
        "version": 1,
        "event_id": row["id"],
        "facts": compact,
    }
    return row


def _enrich(key, row, body, image=None):
    if row is None:
        return None
    if not event_url(key, row.get("event_url")):
        raise ValueError("new_york_event_identity_changed")
    if not body or len(body) > MAX_DESCRIPTION or not row.get("venue_address"):
        raise ValueError("new_york_event_incomplete")
    row.update(description=body, timezone=ZONE, attendance_mode="in_person",
               location_provenance="publisher_event_street_pending_geocode")
    if row.get("lat") is not None and row.get("lng") is not None:
        row["location_provenance"] = "publisher_event_venue_coordinates"
    if point := reviewed_venue_location(key, row["venue_name"], row["venue_address"]):
        provenance = ("reviewed_named_park_approximate_meeting_point"
                      if (key, row["venue_name"], row["venue_address"]) in REVIEWED_APPROXIMATE_POINTS
                      else "reviewed_nyc_pad_address_point"
                      if (key, row["venue_name"], row["venue_address"]) in REVIEWED_PAD_POINTS
                      else "reviewed_publisher_venue_coordinates")
        row.update(lat=point[0], lng=point[1], location_provenance=provenance)
        if row.get("reason") == "missing_verified_venue_geo":
            row["reason"] = None
    if candidate := photo_url(key, image):
        row["image_url"] = candidate
    return row


def _review_tribe_venue(key, item, categories):
    value = item.get("venue")
    venue = dict(value) if isinstance(value, dict) else {}
    if key == CMOM:
        if venue:
            if CMOM_ROOMS.get(venue.get("id")) != plain(venue.get("venue")):
                raise ValueError("new_york_museum_room_unreviewed")
            room = plain(venue["venue"])
            venue = _venue_dict(VENUES[key])
            venue["venue"] += " (" + room + ")"
        elif categories & {"Drop-in Programs", "Sign-up Workshops", "Performances & Shows"}:
            venue = _venue_dict(VENUES[key])
        else:
            raise ValueError("new_york_museum_room_unreviewed")
    elif key == MOVING_IMAGE and not venue:
        if not categories & {"Screening", "Event", "Screening + Intro", "Screening + Discussion"}:
            raise ValueError("new_york_museum_room_unreviewed")
        venue = _venue_dict(VENUES[key])
    elif key == POSTER and not venue:
        if not categories & {"In-Person", "Hybrid"}:
            raise ValueError("new_york_museum_room_unreviewed")
        venue = _venue_dict(VENUES[key])
    elif key == SI_MUSEUM and venue.get("id") in SI_PARKS:
        expected = SI_PARKS[venue["id"]]
        native = expected[0].split(" (")[0]
        if plain(venue.get("venue")) != native:
            raise ValueError("new_york_park_venue_changed")
        if venue.get("address") and plain(venue["address"]) != expected[1]:
            raise ValueError("new_york_park_venue_changed")
        venue = {**venue, **_venue_dict(expected)}
    if not venue or not plain(venue.get("venue")):
        raise ValueError("new_york_street_address_unresolved")
    if key == SI_CHILDREN:
        if (venue.get("id") != 82 or plain(venue.get("venue")).replace("’", "'") != VENUES[key][0]
                or plain(venue.get("address")).replace(",", "") != VENUES[key][1]):
            raise ValueError("new_york_museum_venue_changed")
        venue["venue"] = VENUES[key][0]
    if key == SI_MUSEUM and venue.get("id") == 28:
        if plain(venue.get("address")) != "1000 Richmond Terrace, Building A":
            raise ValueError("new_york_museum_venue_changed")
    # Stateprovince is how some TEC venue records expose New York.
    state = venue.get("state") or venue.get("stateprovince") or venue.get("province")
    street = re.sub(r"\s*,\s*", " ", plain(venue.get("address"))).strip()
    complete = _address(street, venue.get("city"), state, venue.get("zip"))
    return {**venue, "address": street, "state": "NY"}, complete


def _tribe(key, fetch, deadline, now):
    rows = {}
    for page in range(1, MAX_PAGES + 1):
        _check_deadline(deadline)
        params = {"per_page": 100, "start_date": calendar_anchor(now).astimezone(ZoneInfo(ZONE)).date().isoformat(),
                  "end_date": (calendar_anchor(now) + timedelta(days=60)).date().isoformat(), "page": page}
        payload = json.loads(fetch(TRIBE_API[key] + "?" + urlencode(params), "application/json"))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list) or len(payload["events"]) > 100:
            raise ValueError("new_york_calendar_payload_changed")
        for item in payload["events"]:
            if not isinstance(item, dict):
                raise ValueError("new_york_calendar_payload_changed")
            identity = str(item.get("id") or "")
            title = plain(item.get("title"))
            categories = {plain(c.get("name")) for c in item.get("categories", []) if isinstance(c, dict)}
            if (item.get("status") != "publish" or item.get("event_status") in ("cancelled", "canceled", "postponed")
                    or any(item.get(k) in (True, 1, "true", "1") for k in ("all_day", "hide_from_listings", "is_virtual", "virtual"))
                    or NONPUBLIC.search(title) or REMOTE_TITLE.search(title)
                    or categories & {"Closure", "Closures", "Members Only"}
                    or ("Virtual" in categories and not categories & {"In-Person", "Hybrid"})):
                continue
            if not identity.isdigit() or not event_url(key, item.get("url")):
                raise ValueError("new_york_event_identity_changed")
            if item.get("timezone") != ZONE:
                raise ValueError("new_york_publisher_timezone_changed")
            start, end = timestamp(item.get("start_date"), ZONE), timestamp(item.get("end_date"), ZONE)
            if not start or not end or end < start:
                raise ValueError("new_york_schedule_changed")
            if (timestamp(item.get("utc_start_date"), "UTC") != start
                    or timestamp(item.get("utc_end_date"), "UTC") != end):
                raise ValueError("new_york_schedule_conflict")
            if not _within(start, end, now):
                continue
            try:
                body = _body(item.get("description"))
                venue, complete = _review_tribe_venue(key, item, categories)
            except ValueError as exc:
                _held(key, identity, str(exc))
                continue
            native_venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
            reviewed = dict(item, venue=venue)
            parsed = parse_tribe({"events": [reviewed]}, strict_public=True, retain_description=False)
            if not parsed:
                continue
            if len(parsed) != 1:
                raise ValueError("new_york_occurrence_changed")
            row = parsed[0]
            row["venue_address"] = complete
            image = item.get("image") or {}
            row = _enrich(key, row, body, image.get("url") if isinstance(image, dict) else None)
            row["publisher_categories"] = sorted(categories)
            row["location_provenance"] = ("reviewed_park_entrance_address_pending_geocode"
                                           if key == SI_MUSEUM and venue.get("id") == 4741
                                           else row["location_provenance"])
            source_lat, source_lng = _source_coordinates(native_venue)
            source_image = photo_url(key, image.get("url")) if isinstance(image, dict) else None
            _attach_content(
                row,
                title=title,
                description=body,
                starts_at_utc=start.astimezone(timezone.utc).isoformat(),
                ends_at_utc=end.astimezone(timezone.utc).isoformat(),
                source_timezone=ZONE,
                publisher_status=item.get("status"),
                event_url=item.get("url"),
                venue_name=plain(native_venue.get("venue")),
                venue_address=plain(native_venue.get("address")),
                venue_city=plain(native_venue.get("city")),
                venue_region=plain(native_venue.get("state") or native_venue.get("stateprovince")
                                   or native_venue.get("province")),
                venue_postal_code=plain(native_venue.get("zip")),
                venue_country=plain(native_venue.get("country")),
                provider_venue_id=str(native_venue.get("id")) if native_venue.get("id") is not None else None,
                source_latitude=source_lat,
                source_longitude=source_lng,
                source_image_url=source_image,
                publisher_categories=sorted(categories),
                cost_text=plain(item.get("cost")),
                attendance_mode="in_person",
            )
            occurrence = (row["id"], row["starts_at"])
            if occurrence in rows and rows[occurrence] != row:
                raise ValueError("new_york_conflicting_occurrence")
            rows[occurrence] = row
        total_pages = payload.get("total_pages", 1)
        if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 0:
            raise ValueError("new_york_invalid_pagination")
        if len(rows) > MAX_RECORDS:
            raise ValueError("new_york_record_limit")
        if page >= total_pages and not payload.get("next_rest_url"):
            return list(rows.values())
    raise ValueError("new_york_pagination_limit")


def _square_schedule(node, prefix):
    # Google calendar link is publisher-embedded data; it is never fetched.
    links = node.select(f"a.{prefix}-meta-export-google[href]")
    if len(links) != 1:
        raise ValueError("new_york_square_schedule_changed")
    url = urlsplit(links[0]["href"])
    data = parse_qs(url.query)
    if url.hostname != "www.google.com" or data.get("action") != ["TEMPLATE"]:
        raise ValueError("new_york_square_schedule_changed")
    dates = data.get("dates", [""])[0].split("/")
    if len(dates) != 2:
        raise ValueError("new_york_square_schedule_changed")
    try:
        start, end = [datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) for value in dates]
    except ValueError:
        raise ValueError("new_york_square_schedule_changed") from None
    if end <= start:
        raise ValueError("new_york_square_schedule_changed")
    return start, end, data.get("location", [""])[0]


def _squarespace(key, fetch, deadline, now):
    listing = BeautifulSoup(fetch(SOURCES[key][0], "text/html"), "html.parser")
    if not listing.select_one(".eventlist"):
        raise ValueError("new_york_square_calendar_changed")
    selected = []
    for card in listing.select("article.eventlist-event--upcoming"):
        title_link = card.select_one("a.eventlist-title-link[href]")
        if not title_link:
            raise ValueError("new_york_square_identity_changed")
        title = plain(title_link.get_text(" "))
        if NONPUBLIC.search(title) or REMOTE_TITLE.search(title):
            continue
        start, end, native_address = _square_schedule(card, "eventlist")
        # A months-long tour season or undivided multi-day series is not a
        # continuously running event. Never invent daily occurrences/hours.
        if end - start > timedelta(days=1):
            _held(key, title_link["href"], "undivided_multi_day_schedule")
            continue
        if not _within(start, end, now):
            continue
        url = urljoin(SOURCES[key][0], title_link["href"])
        if not event_url(key, url):
            raise ValueError("new_york_event_identity_changed")
        selected.append((url, title, card, start, end, native_address))
    if len(selected) > MAX_DETAILS:
        raise ValueError("new_york_detail_checkpoint_required")
    rows = []
    for url, title, card, start, end, native_address in selected:
        _check_deadline(deadline)
        detail = BeautifulSoup(fetch(url, "text/html"), "html.parser")
        heading = detail.select_one("h1.eventitem-title")
        canonical = detail.select_one('link[rel="canonical"]')
        detail_schedule = _square_schedule(detail, "eventitem")
        if (not heading or plain(heading.get_text(" ")) != title or not canonical
                or canonical.get("href") != url or detail_schedule[:2] != (start, end)
                or detail_schedule[2] != native_address):
            raise ValueError("new_york_square_identity_changed")
        content = detail.select(".eventitem-column-content .sqs-layout")
        if len(content) != 1:
            raise ValueError("new_york_description_container_changed")
        try:
            body = _body(str(content[0]))
            venue, street, city, postal = VENUES[key]
            if key == LATIMER:
                location = detail.select_one(".eventitem-meta-address")
                if (not location or "34-41 137th Street" not in plain(location.get_text(" "))
                        or "Lewis Latimer House" not in plain(location.get_text(" "))):
                    raise ValueError("new_york_offsite_address_unresolved")
            elif (native_address and "441 Clarke Avenue" not in native_address
                  or "441 Clarke Avenue" not in detail.get_text(" ")):
                raise ValueError("new_york_museum_venue_changed")
            complete = _address(street, city, "NY", postal)
        except ValueError as exc:
            _held(key, urlsplit(url).path, str(exc))
            continue
        native = content[0].get("id", "")
        if not re.fullmatch(r"item-[a-f0-9]{24}", native):
            raise ValueError("new_york_square_identity_changed")
        row = record(title, start.isoformat(), end.isoformat(), venue, complete, city,
                     url, native[5:], tz=ZONE, retain_until_end=True)
        image = card.select_one("img[data-src], img[src]")
        row = _enrich(key, row, body, (image.get("data-src") or image.get("src")) if image else None)
        if row:
            _attach_content(
                row,
                title=title,
                description=body,
                starts_at_utc=start.astimezone(timezone.utc).isoformat(),
                ends_at_utc=end.astimezone(timezone.utc).isoformat(),
                source_timezone=ZONE,
                publisher_status="publish",
                event_url=url,
                venue_address=plain(native_address),
                source_image_url=photo_url(key, (image.get("data-src") or image.get("src")) if image else None),
                attendance_mode="in_person",
            )
            rows.append(row)
    return rows


def _html_links(key, listing, *, limit=MAX_DETAILS):
    selected = {}
    for link in listing.select("a[href]"):
        url = urljoin(SOURCES[key][0], link["href"])
        if not event_url(key, url):
            continue
        title_node = link.select_one("h3") if key == BAZAAR else link
        title = plain(title_node.get_text(" ")) if title_node else ""
        if not title or NONPUBLIC.search(title):
            continue
        if key == POWERHOUSE and re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", title):
            continue
        selected[url] = title
    if len(selected) > limit:
        raise ValueError("new_york_detail_checkpoint_required")
    return selected


def _bazaar_detail(url, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    calendar = soup.select_one(".addeventatc")
    heading = soup.select_one("h1")
    if not calendar or not heading:
        raise ValueError("new_york_bazaar_calendar_changed")
    fields = {name: plain(calendar.select_one("." + name).get_text(" ")) if calendar.select_one("." + name) else ""
              for name in ("start", "end", "timezone", "title", "location")}
    title = plain(heading.get_text(" "))
    if fields["title"] != title or fields["timezone"] != ZONE:
        raise ValueError("new_york_bazaar_schedule_changed")
    if NONPUBLIC.search(title):
        return None
    try:
        start = timestamp(datetime.strptime(fields["start"], "%m/%d/%Y %I:%M %p"), ZONE)
        end = timestamp(datetime.strptime(fields["end"], "%m/%d/%Y %I:%M %p"), ZONE)
    except ValueError:
        raise ValueError("new_york_bazaar_schedule_changed") from None
    if end <= start or end - start > timedelta(days=1):
        raise ValueError("new_york_bazaar_schedule_changed")
    if not _within(start, end, now):
        return None
    if fields["location"] != "Grand Bazaar NYC, 100 West 77th St., NY, NY 10024, (At Columbus Avenue)":
        raise ValueError("new_york_bazaar_venue_changed")
    content = calendar.parent
    while content and not content.find("p", recursive=False):
        content = content.parent
    if not content:
        raise ValueError("new_york_description_container_changed")
    # The Add to Calendar description is an excerpt. The actual page's complete
    # narrative consists of the direct paragraphs before that control.
    body = _body("".join(str(node) for node in content.find_all(["p", "ul", "ol", "h2", "h3"], recursive=False)))
    venue, street, city, postal = VENUES[BAZAAR]
    row = record(title, start.isoformat(), end.isoformat(), venue, _address(street, city, "NY", postal), city,
                 url, urlsplit(url).path, "Markets, Makers & Shopping", tz=ZONE, retain_until_end=True)
    image = soup.find("meta", property="og:image")
    return _enrich(BAZAAR, row, body, image.get("content") if image else None)


def _powerhouse_detail(url, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    event = soup.select_one(".em-event-single")
    heading = soup.select_one("h1.entry-title")
    clock = event.select_one(".event-date") if event else None
    if not event or not heading or not clock:
        raise ValueError("new_york_bookshop_calendar_changed")
    title = plain(heading.get_text(" "))
    if NONPUBLIC.search(title) or REMOTE_TITLE.search(title):
        return None
    schedule = re.fullmatch(r"([A-Za-z]+ [A-Za-z]+ \d{1,2}, \d{4}) (\d{1,2}:\d{2} [ap]m) - (\d{1,2}:\d{2} [ap]m)", plain(clock.get_text(" ")), re.I)
    if not schedule:
        raise ValueError("new_york_bookshop_schedule_changed")
    start = timestamp(datetime.strptime(schedule[1] + " " + schedule[2], "%A %b %d, %Y %I:%M %p"), ZONE)
    end = timestamp(datetime.strptime(schedule[1] + " " + schedule[3], "%A %b %d, %Y %I:%M %p"), ZONE)
    if end <= start:
        raise ValueError("new_york_bookshop_schedule_changed")
    if not _within(start, end, now):
        return None
    locations = [node for node in event.select("a[href]") if urlsplit(node["href"]).path in POWERHOUSE_VENUES]
    if len(locations) != 1:
        raise ValueError("new_york_bookshop_venue_changed")
    location = locations[0]
    venue, street, city, postal = POWERHOUSE_VENUES[urlsplit(location["href"]).path]
    evidence = plain(location.parent.get_text(" "))
    if street not in evidence or postal not in evidence or city not in evidence:
        raise ValueError("new_york_bookshop_venue_changed")
    # Retain all native editorial text after removing only the duplicated
    # schedule, venue and booking controls. No metadata/excerpt substitutions.
    copied = BeautifulSoup(str(event), "html.parser").select_one(".em-event-single")
    for node in copied.select(".event-image, .event-date"):
        node.decompose()
    for node in list(copied.select("a[href]")):
        if "/locations/" in node.get("href", ""):
            node.parent.decompose()
        elif "Get Tickets" in node.get_text():
            node.decompose()
    body = _body(str(copied))
    native = next((c.removeprefix("em-event-") for c in event.get("class", []) if re.fullmatch(r"em-event-\d+", c)), None)
    if not native:
        raise ValueError("new_york_bookshop_identity_changed")
    row = record(title, start.isoformat(), end.isoformat(), venue, _address(street, city, "NY", postal), city,
                 url, native, "Books & Literature", tz=ZONE, retain_until_end=True)
    image = event.select_one(".event-image img[src]")
    row = _enrich(POWERHOUSE, row, body, image.get("src") if image else None)
    return _attach_content(
        row,
        title=title,
        description=body,
        starts_at_utc=start.astimezone(timezone.utc).isoformat(),
        ends_at_utc=end.astimezone(timezone.utc).isoformat(),
        source_timezone=ZONE,
        publisher_status="publish",
        event_url=url,
        venue_name=venue,
        venue_address=street,
        venue_city=city,
        venue_region="NY",
        venue_postal_code=postal,
        source_image_url=photo_url(POWERHOUSE, image.get("src") if image else None),
        publisher_categories=["Books & Literature"],
        attendance_mode="in_person",
    )


def _html_calendar(key, fetch, deadline, now):
    listing = BeautifulSoup(fetch(SOURCES[key][0], "text/html"), "html.parser")
    selected = _html_links(key, listing)
    if not selected:
        raise ValueError("new_york_calendar_listing_changed")
    rows = []
    for url in selected:
        _check_deadline(deadline)
        try:
            row = (_bazaar_detail if key == BAZAAR else _powerhouse_detail)(url, fetch(url, "text/html"), now)
        except ValueError as exc:
            if str(exc) in ("new_york_description_missing", "new_york_description_limit", "new_york_bookshop_venue_changed"):
                _held(key, urlsplit(url).path, str(exc))
                continue
            raise
        if row:
            rows.append(row)
    return rows


def _checkpoint(value, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get("version") != 1 or type(value.get("version")) is not int
            or value.get("source_key") != BAZAAR or type(value.get("cursor")) is not int
            or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= 200
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or not isinstance(value.get("events"), list) or not isinstance(value.get("diagnostics"), list)
            or len(value["events"]) + len(value["diagnostics"]) != value["cursor"]
            or len(value["events"]) > 201
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError("new_york_arts_checkpoint_invalid")
    try:
        started = timestamp(value["started_at"])
        if not started or started.tzinfo is None or value["window_start"] != calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("new_york_arts_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=24):
        return None
    queue = value["queue"]
    if any(not isinstance(item, dict) or set(item) != {"url", "title"}
           or not event_url(BAZAAR, item["url"]) or not isinstance(item["title"], str)
           or not item["title"].strip() for item in queue):
        raise ValueError("new_york_arts_checkpoint_invalid")
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if value.get("manifest_hash") != digest or len({item["url"] for item in queue}) != len(queue):
        raise ValueError("new_york_arts_checkpoint_invalid")
    processed = {item["url"]: item for item in queue[:value["cursor"]]}
    seen = set()
    name, street, city, postal = VENUES[BAZAAR]
    address = _address(street, city, "NY", postal)
    for row in value["events"]:
        item = processed.get(row.get("event_url")) if isinstance(row, dict) else None
        if (not item or row["event_url"] in seen or row.get("title") != item["title"]
                or row.get("id") != urlsplit(item["url"]).path
                or (row.get("venue_name"), row.get("venue_address"), row.get("venue_city")) != (name, address, city)
                or not isinstance(row.get("description"), str) or not row["description"].strip()
                or len(row["description"]) > MAX_DESCRIPTION
                or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                or (row.get("image_url") is not None and photo_url(BAZAAR, row["image_url"]) is None)):
            raise ValueError("new_york_arts_checkpoint_invalid")
        try:
            start, end = timestamp(row["starts_at"]), timestamp(row["ends_at"])
            if not start or not end or start.tzinfo is None or end.tzinfo is None or not start < end <= start + timedelta(days=1):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ValueError("new_york_arts_checkpoint_invalid") from None
        point = reviewed_venue_location(BAZAAR, name, address) or (None, None)
        if (row.get("lat"), row.get("lng")) != point:
            raise ValueError("new_york_arts_checkpoint_invalid")
        seen.add(row["event_url"])
    for item in value["diagnostics"]:
        if (not isinstance(item, dict) or item.get("event_url") not in processed
                or item["event_url"] in seen or item.get("disposition") != "held"
                or item.get("reason") not in {"event_ended_during_collection", "new_york_description_missing", "new_york_description_limit"}):
            raise ValueError("new_york_arts_checkpoint_invalid")
        seen.add(item["event_url"])
    if seen != set(processed):
        raise ValueError("new_york_arts_checkpoint_invalid")
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=3):
    if (source.get("source_key") != BAZAAR
            or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[BAZAAR], ZONE)):
        raise ValueError("unregistered_new_york_arts_source")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("new_york_arts_checkpoint_invalid")
    state = _checkpoint(checkpoint, current)
    # A durable complete snapshot is reused for staging retries without more
    # HTTP. Incomplete chunks recheck the listing before advancing its cursor.
    if state and state["cursor"] == state["manifest_count"]:
        return dict(complete=True, events=deepcopy(state["events"]), checkpoint=state)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    _check_deadline(deadline)
    listing = BeautifulSoup(fetch(SOURCES[BAZAAR][0], "text/html"), "html.parser")
    queue = [{"url": url, "title": title} for url, title in sorted(_html_links(BAZAAR, listing, limit=200).items())]
    if not queue:
        raise ValueError("new_york_calendar_listing_changed")
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest:
        state = dict(version=1, source_key=BAZAAR, started_at=current.isoformat(),
                     window_start=calendar_anchor(current).astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=digest, manifest_count=len(queue), cursor=0,
                     queue=queue, events=[], diagnostics=[])
    prior = state["cursor"]
    count = min(3, max(1, int(max_details)))
    while state["cursor"] < len(queue) and state["cursor"] - prior < count:
        if monotonic() + 8 >= deadline:
            break
        item = queue[state["cursor"]]
        reason = "event_ended_during_collection"
        try:
            row = _bazaar_detail(item["url"], fetch(item["url"], "text/html"), timestamp(state["started_at"]))
        except ValueError as exc:
            if str(exc) not in {"new_york_description_missing", "new_york_description_limit"}:
                raise
            row, reason = None, str(exc)
        if row:
            if row["title"] != item["title"]:
                raise ValueError("new_york_bazaar_schedule_changed")
            state["events"].append(row)
        else:
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=reason))
        state["cursor"] += 1
    if prior == state["cursor"] < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_arts_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    return dict(complete=complete, events=deepcopy(rows), checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    expected = SOURCES.get(key)
    if expected is None or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != expected or source.get("timezone") != ZONE:
        raise ValueError("unregistered_new_york_arts_source")
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    current = now or datetime.now(timezone.utc)
    if key in CHECKPOINT_KEYS:
        raise ValueError("publisher_checkpoint_required")
    if key in TRIBE_API:
        rows = _tribe(key, fetch, deadline, current)
    elif key in SQUARESPACE_SITE:
        rows = _squarespace(key, fetch, deadline, current)
    else:
        rows = _html_calendar(key, fetch, deadline, current)
    unique = {}
    for row in rows:
        identity = (row["id"], row["starts_at"])
        if identity in unique and unique[identity] != row:
            raise ValueError("new_york_conflicting_occurrence")
        unique[identity] = row
    if len(unique) > MAX_RECORDS:
        raise ValueError("new_york_record_limit")
    return sorted(unique.values(), key=lambda row: (row["starts_at"], row["id"]))


ERROR_CODES = {
    "unregistered_new_york_arts_source", "new_york_description_missing", "new_york_description_limit",
    "new_york_street_address_unresolved", "new_york_event_identity_changed", "new_york_event_incomplete",
    "new_york_museum_room_unreviewed", "new_york_park_venue_changed", "new_york_museum_venue_changed",
    "new_york_calendar_payload_changed", "new_york_publisher_timezone_changed", "new_york_schedule_changed",
    "new_york_schedule_conflict", "new_york_occurrence_changed", "new_york_conflicting_occurrence",
    "new_york_invalid_pagination", "new_york_record_limit", "new_york_pagination_limit",
    "new_york_square_schedule_changed", "new_york_square_calendar_changed", "new_york_square_identity_changed",
    "new_york_detail_checkpoint_required", "new_york_description_container_changed", "new_york_offsite_address_unresolved",
    "new_york_bazaar_calendar_changed", "new_york_bazaar_schedule_changed", "new_york_bazaar_venue_changed",
    "new_york_bookshop_calendar_changed", "new_york_bookshop_schedule_changed", "new_york_bookshop_venue_changed",
    "new_york_bookshop_identity_changed", "new_york_calendar_listing_changed", "new_york_arts_checkpoint_invalid",
    "new_york_arts_checkpoint_size_limit", "publisher_checkpoint_required", "collection_deadline",
}
