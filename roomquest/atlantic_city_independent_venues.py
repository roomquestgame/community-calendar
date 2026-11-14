"""Four independent Atlantic County venue calendars with complete publisher prose.

Reuse the factual Tribe parser and the Atlantic City narrative normalizer.
Squarespace exports are disallowed by these publishers, so use their normal
HTML pages. Its detail body always takes precedence over a listing excerpt.
All HTTP remains on the worker's guarded, paced PublisherHTTP callback.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = "America/New_York"
CARDINAL = "cardinal_atlantic_city_nj"
RENAULT = "renault_winery_nj"
COUNTRY_CLUB = "atlantic_city_country_club_nj"
VENTNOR = "ventnor_social_nj"
SOURCES = {
    CARDINAL: ("https://www.cardinal-ac.com/events-at-cardinal", "html", "html"),
    RENAULT: ("https://renaultwinery.com/events/list/", "html", "html"),
    COUNTRY_CLUB: ("https://accountryclub.com/events/list/", "html", "html"),
    VENTNOR: ("https://ventnorsocial.com/events", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
TRIBE_API = {
    RENAULT: "https://renaultwinery.com/wp-json/tribe/events/v1/events",
    COUNTRY_CLUB: "https://accountryclub.com/wp-json/tribe/events/v1/events",
}
# Exact venue addresses in the official calendar/detail/footer, reviewed
# 2026-11-14. Renault's API repeats its state and ZIP inside the city field.
VENUES = {
    CARDINAL: ("Cardinal Atlantic City", "201 S New York Avenue, Atlantic City, NJ 08401", "Atlantic City"),
    RENAULT: ("Renault Winery & Resort", "72 North Bremen Avenue, Egg Harbor City, NJ 08215", "Egg Harbor City"),
    COUNTRY_CLUB: ("Atlantic City Country Club (approximate map location)", "1 Leo Fraser Drive, Northfield, NJ 08225", "Northfield"),
    VENTNOR: ("Ventnor Social", "6417 Ventnor Avenue, Ventnor City, NJ 08406", "Ventnor City"),
}
# NJ Office of GIS, score-100 PointAddress results for the exact publisher
# streets. Proof: docs/evidence/atlantic-city-independent-venue-points.json.
# Match the entire source/name/street tuple; never substitute a coverage point.
REVIEWED_VENUE_POINTS = {
    (CARDINAL, "Cardinal Atlantic City", "201 S New York Avenue, Atlantic City, NJ 08401"):
        (39.358251000003, -74.426868000001),
    (VENTNOR, "Ventnor Social", "6417 Ventnor Avenue, Ventnor City, NJ 08406"):
        (39.338136000003, -74.483122500001),
    # Renault's official contact spells the same estate as 72 Bremen Avenue;
    # that address has a score-100 PointAddress. Preserve the event's North.
    (RENAULT, "Renault Winery & Resort", "72 North Bremen Avenue, Egg Harbor City, NJ 08215"):
        (39.546288000003, -74.604096000001),
    # OpenStreetMap way630332016 is the named clubhouse, with the exact club
    # website and phone. Its inside-polygon centroid is visibly qualified.
    (COUNTRY_CLUB, "Atlantic City Country Club (approximate map location)", "1 Leo Fraser Drive, Northfield, NJ 08225"):
        (39.37029755, -74.54236135),
}
MAX_DESCRIPTION = 12000
MAX_PAGES = 3
MAX_RECORDS = 150
MAX_DETAILS = 12
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|private (?:event|party|function)|"
                       r"members?[- ]only|invitation[- ]only|sold\s+out)\b", re.I)
# Ventnor's current detail has an explicitly empty native body. Its complete
# publisher-authored listing paragraph equals all four detail description
# metadata fields. This exact reviewed paragraph is not a generic excerpt
# fallback: a changed/longer/unknown excerpt requires another content review.
REVIEWED_EMPTY_BODY = {
    (VENTNOR, "/events/holiday-market-1"):
        "58639c50c80dea43e7afea028da77c4fc30e6362e7299b0c791698240114763d",
}


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key]
                or p.query or p.fragment):
            return False
        prefix = "/events-at-cardinal/" if key == CARDINAL else "/events/"
        if key in TRIBE_API:
            return bool(re.fullmatch(r"/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?", p.path))
        return bool(re.fullmatch(re.escape(prefix) + r"[a-z0-9-]+", p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.fragment:
            return None
        if key in TRIBE_API:
            if (p.netloc in ALLOWED_HOSTS[key] and not p.query
                    and re.fullmatch(r"/wp-content/uploads/20\d{2}/\d{2}/[^/]+\.(?:jpe?g|png|webp)", p.path, re.I)):
                return value
        else:
            site = {CARDINAL: "63799021329ebc1f9e726097", VENTNOR: "686dde070656840f6405c24d"}.get(key)
            if (site and p.netloc == "images.squarespace-cdn.com"
                    and p.path.startswith("/content/v1/" + site + "/")
                    and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)
                    and set(parse_qs(p.query)) <= {"format"}):
                return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    return REVIEWED_VENUE_POINTS.get((key, venue, address))


def _held(key, identity, reason):
    log.warning("independent_venue_event_held source=%s id=%s reason=%s", key, identity, reason)


def _check_deadline(deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _body(value):
    # Already-normalized text must never pass through an HTML parser a second
    # time (literal '<' and '&' in the publisher's prose are meaningful).
    if not isinstance(value, str) or not value.strip():
        raise ValueError("atlantic_city_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("atlantic_city_description_limit")
    return value


def _enrich(key, row, body, image=None):
    if row is None:
        return None
    venue, street, city = VENUES[key]
    row.update(description=_body(body), venue_name=venue, venue_address=street,
               venue_city=city, attendance_mode="in_person", timezone=ZONE,
               location_provenance="reviewed_venue_street_address_pending_geocode")
    if point := reviewed_venue_location(key, row["venue_name"], row["venue_address"]):
        row.update(lat=point[0], lng=point[1], location_provenance=(
            "reviewed_osm_clubhouse_polygon_centroid" if key == COUNTRY_CLUB
            else "reviewed_nj_ogis_point_address"))
        if row.get("reason") == "missing_verified_venue_geo":
            row["reason"] = None
    if candidate := photo_url(key, image):
        row["image_url"] = candidate
    return row


def _square_time(node, suffix):
    values = node.select(".event-time-localized-" + suffix + ",.event-time-12hr-" + suffix)
    if len(values) != 1:
        raise ValueError("independent_venue_clock_missing")
    day = date.fromisoformat(values[0].get("datetime", ""))
    clock = re.sub(r"\s+", "", values[0].get_text()).upper()
    wall = datetime.strptime(clock, "%I:%M%p").time()
    return timestamp(datetime.combine(day, wall), ZONE)


def _square_location(key, listing_card, detail):
    venue, street, city = VENUES[key]
    if key == CARDINAL:
        # No per-event location is set on Cardinal's own on-site calendar.
        # Any newly supplied different event location must be reviewed.
        if listing_card.select_one(".eventlist-meta-address") or detail.select_one(".eventitem-meta-address"):
            raise ValueError("independent_venue_location_changed")
        footer = detail.select_one("footer")
        if not footer or "201 S. New York Ave, Atlantic City, NJ 08401" not in plain(footer.get_text(" ")):
            raise ValueError("independent_venue_location_changed")
    else:
        expected = {"og:street-address": "6417 Ventnor Avenue", "og:locality": "Ventnor City",
                    "og:region": "New Jersey", "og:postal-code": "08406"}
        if any(not (node := detail.find("meta", property=field)) or node.get("content") != value
               for field, value in expected.items()):
            raise ValueError("independent_venue_location_changed")
        location = listing_card.select_one(".eventlist-meta-address")
        if not location or plain(location.get_text(" ")).removesuffix("(map)").strip() != venue:
            raise ValueError("independent_venue_location_changed")
    return venue, street, city


def _square_detail(key, card, detail_payload):
    link = card.select_one("a.eventlist-title-link[href]")
    if not link:
        raise ValueError("independent_venue_event_identity")
    url = urljoin(SOURCES[key][0], link["href"])
    title = plain(link.get_text(" "))
    detail = BeautifulSoup(detail_payload, "html.parser")
    heading = detail.select_one("h1.eventitem-title")
    canonical = detail.select_one('link[rel="canonical"]')
    if (not event_url(key, url) or not heading or plain(heading.get_text(" ")) != title
            or not canonical or canonical.get("href") != url):
        raise ValueError("independent_venue_event_identity")
    start, end = _square_time(card, "start"), _square_time(card, "end")
    if (_square_time(detail, "start"), _square_time(detail, "end")) != (start, end) or end <= start:
        raise ValueError("independent_venue_schedule_conflict")
    venue, street, city = _square_location(key, card, detail)
    layouts = detail.select(".eventitem-column-content .sqs-layout")
    if len(layouts) != 1:
        raise ValueError("independent_venue_description_container_changed")
    if layouts[0].get_text(strip=True):
        body = narrative(layouts[0])
    else:
        excerpt = card.select_one(".eventlist-excerpt")
        body = narrative(excerpt) if excerpt else ""
        meta = detail.find("meta", property="og:description")
        if (not meta or plain(meta.get("content")) != plain(body)
                or sha256(body.encode()).hexdigest()
                != REVIEWED_EMPTY_BODY.get((key, urlsplit(url).path))):
            raise ValueError("independent_venue_full_description_unavailable")
    if NONPUBLIC.search(title):
        return None
    point = reviewed_venue_location(key, venue, street) or (None, None)
    identity = urlsplit(url).path + ":" + start.date().isoformat()
    row = record(title, start.isoformat(), end.isoformat(), venue, street, city,
                 url, identity, lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    image = card.select_one("img[data-src],img[src]")
    return _enrich(key, row, body, image.get("data-src") or image.get("src") if image else None)


def _squarespace(key, fetch, deadline, now):
    listing = BeautifulSoup(fetch(SOURCES[key][0], "text/html"), "html.parser")
    if not listing.select_one(".eventlist"):
        raise ValueError("independent_venue_calendar_changed")
    cards = listing.select("article.eventlist-event--upcoming")
    if len(cards) > MAX_RECORDS:
        raise ValueError("source_record_limit")
    selected = []
    for card in cards:
        title = card.select_one("a.eventlist-title-link[href]")
        if not title:
            raise ValueError("independent_venue_event_identity")
        if NONPUBLIC.search(plain(title.get_text(" "))):
            continue
        start, end = _square_time(card, "start"), _square_time(card, "end")
        if end <= start:
            raise ValueError("independent_venue_schedule_conflict")
        if not _within(start, end, now):
            continue
        url = urljoin(SOURCES[key][0], title["href"])
        if not event_url(key, url):
            raise ValueError("independent_venue_event_identity")
        selected.append((url, card))
    if len(selected) > MAX_DETAILS:
        raise ValueError("independent_venue_detail_limit")
    result = []
    for url, card in selected:
        _check_deadline(deadline)
        row = _square_detail(key, card, fetch(url, "text/html"))
        if row:
            result.append(row)
    return result


def _tribe_schedule(item):
    zone = item.get("timezone")
    if zone not in (ZONE, "UTC+0"):
        raise ValueError("independent_venue_timezone_changed")
    values = []
    for field in ("start_date", "end_date"):
        local, utc = item.get(field), item.get("utc_" + field)
        if not local or not utc:
            raise ValueError("independent_venue_clock_missing")
        # Both reviewed venue calendars leave WordPress's zone at UTC+0.
        # Public detail headers and prose publish these exact local clocks.
        # Require the known duplicated representation, never shift actual UTC.
        if zone == "UTC+0":
            if (datetime.fromisoformat(local).tzinfo is not None
                    or datetime.fromisoformat(utc).tzinfo is not None
                    or timestamp(local, "UTC") != timestamp(utc, "UTC")):
                raise ValueError("independent_venue_schedule_conflict")
        elif timestamp(local, ZONE) != timestamp(utc, "UTC"):
            raise ValueError("independent_venue_schedule_conflict")
        values.append(timestamp(local, ZONE))
    start, end = values
    if end < start:
        raise ValueError("independent_venue_schedule_conflict")
    # TEC's start=end represents an unpublished end, e.g. Reindeer Run.
    return start, None if end == start else end


def _tribe_venue(key, item):
    supplied = item.get("venue")
    if key == COUNTRY_CLUB and not supplied:
        # This venue's public calendar publishes no structured venue object;
        # its own event details and footer identify One Leo Fraser Drive.
        return True
    if not isinstance(supplied, dict):
        return False
    name = plain(supplied.get("venue"))
    if key == RENAULT:
        return (name == VENUES[key][0] and supplied.get("address") == "72 North Bremen Avenue"
                and supplied.get("city") in ("Egg Harbor City", "Egg Harbor City, NJ 08215")
                and supplied.get("state") == "NJ" and str(supplied.get("zip")) == "08215")
    return (name == "Atlantic City Country Club" and supplied.get("address") in ("1 Leo Fraser Drive", "One Leo Fraser Drive")
            and supplied.get("city") == "Northfield" and supplied.get("state") == "NJ"
            and str(supplied.get("zip")) == "08225")


def _tribe(key, fetch, deadline, now):
    accepted, bodies, images, seen = [], {}, {}, set()
    expected_totals = None
    local_now = now.astimezone(ZoneInfo(ZONE))
    params = dict(per_page=100, start_date=local_now.date().isoformat(),
                  end_date=(local_now + timedelta(days=60)).date().isoformat())
    for page in range(1, MAX_PAGES + 1):
        _check_deadline(deadline)
        payload = json.loads(fetch(TRIBE_API[key] + "?" + urlencode({**params, "page": page}), "application/json"))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise ValueError("unsupported_wordpress_payload")
        pages = payload.get("total_pages")
        total = payload.get("total")
        if (isinstance(pages, bool) or not isinstance(pages, int) or not 0 <= pages <= MAX_PAGES
                or isinstance(total, bool) or not isinstance(total, int) or not 0 <= total <= MAX_RECORDS
                or len(payload["events"]) > 100):
            raise ValueError("invalid_wordpress_pagination")
        if expected_totals is None:
            expected_totals = (pages, total)
        elif expected_totals != (pages, total):
            raise ValueError("independent_venue_snapshot_changed")
        for item in payload["events"]:
            if not isinstance(item, dict) or not str(item.get("id", "")).isdigit():
                raise ValueError("independent_venue_event_identity")
            identity = str(item["id"])
            if identity in seen:
                raise ValueError("independent_venue_duplicate_occurrence")
            seen.add(identity)
            title = plain(item.get("title"))
            if (item.get("status") != "publish" or NONPUBLIC.search(title)
                    or item.get("event_status") in ("cancelled", "canceled", "postponed")
                    or any(item.get(flag) in (True, 1, "1", "true") for flag in
                           ("all_day", "virtual", "is_virtual", "hide_from_listings"))):
                continue
            start, end = _tribe_schedule(item)
            if not _within(start, end, now):
                continue
            if not title or not event_url(key, item.get("url")):
                raise ValueError("independent_venue_event_identity")
            if not _tribe_venue(key, item):
                _held(key, identity, "publisher_venue_unreviewed")
                continue
            # The publisher currently says 01:00 AM–04:00 PM for this music set.
            # Keep the suspicious 15-hour occurrence on review; never guess PM.
            if (key == RENAULT and identity == "16527" and start.isoformat() == "2026-12-05T01:00:00-05:00"
                    and end and end.isoformat() == "2026-12-05T16:00:00-05:00"):
                _held(key, identity, "publisher_15_hour_music_schedule_requires_review")
                continue
            if not isinstance(item.get("description"), str):
                raise ValueError("invalid_wordpress_description")
            body = narrative(item["description"])
            if re.search(r"\b(?:private (?:event|party|function)|invitation[- ]only|members?[- ]only)\b", body, re.I):
                continue
            venue, street, city = VENUES[key]
            address, _, region = street.partition(", ")
            point = reviewed_venue_location(key, venue, street) or (None, None)
            normalized_venue = dict(venue=venue, address=address, city=city, state="NJ",
                                    zip=region.rsplit(" ", 1)[-1], geo_lat=point[0], geo_lng=point[1])
            accepted.append({**item, "venue": normalized_venue, "timezone": ZONE,
                             "utc_start_date": start.astimezone(timezone.utc).isoformat(),
                             "utc_end_date": end.astimezone(timezone.utc).isoformat() if end else None,
                             "end_date": end.isoformat() if end else None})
            bodies[identity] = body
            images[identity] = item.get("image", {}).get("url") if isinstance(item.get("image"), dict) else None
        if page >= pages:
            if len(seen) != total:
                raise ValueError("independent_venue_incomplete_snapshot")
            break
    # Reuse the shared factual parser, then explicitly map the complete native
    # description. Its general 2k description helper is deliberately not used.
    rows = parse_tribe({"events": accepted}, strict_public=True, retain_description=False)
    parsed_ids = {row["id"] for row in rows}
    for item in accepted:
        identity = str(item["id"])
        if identity in parsed_ids:
            continue
        start = timestamp(item["utc_start_date"])
        end = timestamp(item["utc_end_date"])
        # The general parser requires at least an hour remaining for ongoing
        # events. This reviewed cohort retains an actual occurrence until its
        # published end (or the existing three-hour unknown-end policy).
        # Only an omitted ongoing row gets this narrow normalization override.
        if not start <= now < (end or start + timedelta(hours=3)):
            continue
        venue, street, city = VENUES[key]
        point = reviewed_venue_location(key, venue, street) or (None, None)
        category = ", ".join(c.get("name", "") for c in item.get("categories", []) if isinstance(c, dict))
        row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
                     venue, street, city, item["url"], identity, category,
                     lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
        if row is not None:
            rows.append(row)
    return [_enrich(key, row, bodies[row["id"]], images[row["id"]]) for row in rows]


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get("source_key")
    if (key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                              source.get("timezone")) != (*SOURCES[key], ZONE)):
        raise ValueError("unregistered_atlantic_independent_venue_source")
    now = now or datetime.now(timezone.utc)
    deadline = min(deadline_at or float("inf"), monotonic() + 35)
    rows = (_tribe(key, fetch, deadline, now) if key in TRIBE_API
            else _squarespace(key, fetch, deadline, now))
    unique = {}
    for row in rows:
        identity = (row["id"], row["starts_at"])
        if identity in unique and unique[identity] != row:
            raise ValueError("independent_venue_duplicate_occurrence")
        unique[identity] = row
    _check_deadline(deadline)
    return sorted(unique.values(), key=lambda row: (row["starts_at"], row["id"]))
