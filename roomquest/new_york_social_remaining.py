"""Repair four unpublished NYC sources through reviewed public publisher pages.

Squarespace native HTML, advertised TEC REST metadata with complete event HTML,
and Wix's advertised public sitemap reuse the existing normalized record shape.
Only fully hydrated durable manifests are published; no export routes disallowed
by robots, private APIs, registration forms or calendar subscriptions are used.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.new_york_nightlife import _square_clock

ZONE = "America/New_York"
IRISH = "municipal_mapsee_531e3bb7ca6b8a000c88ee80"
REPAIR = "municipal_mapsee_de7d26035617ddd2af35f829"
INDUSTRY = "municipal_mapsee_f8b8293b927ebc8172bbc1a9"
PRIDE = "municipal_mapsee_8944f57397b034b9df390cd7"
SOURCES = {
    IRISH: ("https://www.newyorkirishcenter.org/events", "html", "html"),
    REPAIR: ("https://www.repaircafe.nyc/upcoming-events", "html", "html"),
    INDUSTRY: ("https://industrycity.com/events/", "html", "html"),
    PRIDE: ("https://www.lgbtbrooklyn.org/calendar", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {PRIDE: 500}
CHECKPOINT_EVENT_LIMITS = {PRIDE: 500}
MAX_MANIFEST = 500
MAX_RECORDS = 500
MAX_CHECKPOINT_BYTES = 900_000
MAX_DIAGNOSTICS = 400
MAX_DESCRIPTION = 12000
MAX_DETAILS_PER_CHUNK = 6
MAX_DETAILS_PER_SOURCE = {PRIDE: 12}
MIN_DETAIL_SECONDS = 12
WIX_APP = "140603ad-af8d-84a5-2c80-a0f60cb47351"
WIX_SITEMAP = "https://www.lgbtbrooklyn.org/event-pages-sitemap.xml"
INDUSTRY_API = "https://industrycity.com/wp-json/tribe/events/v1/events"
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|private (?:event|party)|0 appointments left|sold out)\b", re.I)
VENUES = {
    IRISH: ("New York Irish Center", "10-40 Jackson Avenue, Long Island City, NY 11101", "Long Island City"),
    REPAIR: ("Another World", "629 Nostrand Avenue, Brooklyn, NY 11216", "Brooklyn"),
}
# Exact current publisher streets corroborated by NYC Planning PAD (2026-11-14).
POINTS = {IRISH: (40.742096, -73.953059), REPAIR: (40.675529, -73.949746)}
INDUSTRY_POINTS = {
    ("Barrow’s Intense NY Tasting Room", "86 34th Street Building 6, Brooklyn, NY 11232"): (40.657125, -74.006418),
    ("Brooklyn Creative Reuse", "254 36th Street Building 2, Brooklyn, NY 11232"): (40.65623, -74.007951),
    ("Craftsman Ave", "68 34th Street Building 6, Brooklyn, NY 11232"): (40.657125, -74.006418),
    ("Fort Hamilton Distillery", "68 34th Street Building 6, Brooklyn, NY 11232"): (40.657125, -74.006418),
    ("Industry City", "220 36th Street, Brooklyn, NY 11232"): (40.65623, -74.007951),
    ("Industry City", "33 35th Street 2nd Floor, Brooklyn, NY 11232"): (40.657125, -74.006418),
    ("Ippin Project", "67 35th Street Building 5, Brooklyn, NY 11232"): (40.657125, -74.006418),
    ("KAJIHA", "67 35th Street Building 5, Brooklyn, NY 11232"): (40.657125, -74.006418),
    ("Lista Studios", "34 35th Street Building 4, Brooklyn, NY 11232"): (40.656627, -74.007099),
    ("The Box Factory", "51 34th Street, Brooklyn, NY 11232"): (40.657685, -74.005843),
    ("brooklynONE Tom Kane Theater", "51 35th Street Building 5, Brooklyn, NY 11232"): (40.657125, -74.006418),
}
ERROR_CODES = {
    "unregistered_new_york_social_source", "new_york_social_calendar_changed",
    "new_york_social_manifest_limit", "new_york_social_record_limit",
    "new_york_social_identity", "new_york_social_schedule_conflict",
    "new_york_social_description_missing", "new_york_social_description_limit",
    "new_york_social_detail_changed", "new_york_social_location_unresolved",
    "new_york_social_checkpoint_invalid", "new_york_social_checkpoint_size_limit",
    "new_york_social_checkpoint_required", "collection_deadline",
}
HELD_REASONS = {
    "new_york_social_description_missing", "new_york_social_description_limit",
    "new_york_social_location_unresolved", "publisher_schedule_conflict",
    "existing_direct_sake_source", "no_available_future_occurrence",
    "not_in_person_or_unpublished", "no_available_appointments", "publisher_event_not_active",
}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_new_york_social_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.query or p.fragment
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I) or ".." in p.path.split("/")):
            return False
        prefix = "/event-details/" if key == PRIDE else "/event/" if key == INDUSTRY else urlsplit(SOURCES[key][0]).path + "/"
        pattern = r"[a-z0-9-]+" if key == PRIDE else r"[a-zA-Z0-9/-]+"
        return bool(re.fullmatch(re.escape(prefix) + pattern, p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.fragment or ".." in p.path.split("/"):
            return None
        if key == INDUSTRY:
            return value if p.netloc == "industrycity.com" and not p.query and re.fullmatch(r"/wp-content/uploads/20\d{2}/\d{2}/[^/]+\.(?:jpe?g|png|webp)", p.path, re.I) else None
        if key == PRIDE:
            return value if p.netloc == "static.wixstatic.com" and not p.query and re.fullmatch(r"/media/(?:9f0aae|6975e6)_[a-f0-9]{32}(?:~|%7E)mv2\.(?:jpe?g|png|webp)", p.path, re.I) else None
        site = {IRISH: "5c58ea3ee8ba441e0562414a", REPAIR: "68978b464835ee5a17b7ded8"}.get(key)
        if site and p.netloc == "images.squarespace-cdn.com" and p.path.startswith("/content/v1/" + site + "/") and set(parse_qs(p.query)) <= {"format"}:
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, street):
    if key in VENUES and (venue, street) == VENUES[key][:2]:
        return POINTS[key]
    if key == INDUSTRY:
        return INDUSTRY_POINTS.get((venue, street))
    return None


def _body(value):
    # Invisible editor separators differ between TEC's API and rendered HTML;
    # normalize those, preserving every visible word and paragraph.
    text = description(str(value or "").replace("\u200b", "").replace("\ufeff", ""), limit=MAX_DESCRIPTION + 1)
    if not text or not any(char.isalpha() for char in text):
        raise ValueError("new_york_social_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("new_york_social_description_limit")
    return text


def _clock(node, suffix):
    try:
        return _square_clock(node, suffix)
    except (TypeError, ValueError):
        raise ValueError("new_york_social_schedule_conflict") from None


def _within(start, end, now):
    if start is None or start.tzinfo is None or end and (end.tzinfo is None or end <= start):
        raise ValueError("new_york_social_schedule_conflict")
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _id(key, url, start, native=""):
    return "nyc-social:" + sha256(f"{key}:{url}:{timestamp(start).isoformat()}:{native}".encode()).hexdigest()


def _content_venue(place):
    """Retain publisher-supplied venue text without reviewed point enrichment."""
    if (not isinstance(place, (tuple, list)) or len(place) != 3
            or any(not isinstance(value, str) or not value.strip() or len(value) > 500
                   for value in place)):
        raise ValueError("new_york_social_location_unresolved")
    postcode = re.search(r",\s*NY\s+(\d{5}(?:-\d{4})?)\b", place[1], re.I)
    result = {
        "venue_name": plain(place[0]),
        "venue_address": plain(place[1]),
        "venue_city": plain(place[2]),
        "venue_region": "NY",
        "venue_country": "US",
    }
    if postcode:
        result["venue_postal_code"] = postcode[1]
    return result


def _attach_content(row, body, *, content_venue, image=None,
                    provider_venue_id=None, source_coordinates=None):
    """Retain only event-owned facts before EventQuest location enrichment."""
    start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
    if start is None or start.tzinfo is None or end is not None and end.tzinfo is None:
        raise ValueError("new_york_social_schedule_conflict")
    facts = {
        "title": row["title"],
        "description": body,
        "is_all_day": False,
        "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
        "ends_at_utc": end.astimezone(timezone.utc).isoformat() if end else None,
        "source_timezone": ZONE,
        "event_url": row["event_url"],
        "provider_venue_id": str(provider_venue_id) if provider_venue_id else None,
        "source_image_url": image,
        "publisher_categories": [],
        "attendance_mode": "in_person",
        **content_venue,
    }
    if source_coordinates is not None:
        try:
            lat, lng = map(float, source_coordinates)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("new_york_social_location_unresolved") from None
        if not (math.isfinite(lat) and math.isfinite(lng)
                and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("new_york_social_location_unresolved")
        facts.update(source_latitude=lat, source_longitude=lng)
    facts = {name: value for name, value in facts.items()
             if value is not None and value != "" and value != [] and value != {}}
    row["collector_event_content_v1"] = {
        "version": 1,
        "event_id": row["id"],
        "facts": facts,
    }
    return row


def _content_envelope_valid(row):
    evidence = row.get("collector_event_content_v1")
    if evidence is None:
        return True
    if (not isinstance(evidence, dict) or set(evidence) != {"version", "event_id", "facts"}
            or evidence.get("version") != 1 or evidence.get("event_id") != row.get("id")
            or not isinstance(evidence.get("facts"), dict)):
        return False
    facts = evidence["facts"]
    allowed = {
        "title", "description", "is_all_day", "starts_at_utc", "ends_at_utc",
        "source_timezone", "event_url", "provider_venue_id", "venue_name",
        "venue_address", "venue_city", "venue_region", "venue_postal_code",
        "venue_country", "source_latitude", "source_longitude", "source_image_url",
        "publisher_categories", "attendance_mode",
    }
    if not set(facts) <= allowed or ("source_latitude" in facts) != ("source_longitude" in facts):
        return False
    try:
        start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
        expected = {
            "title": row.get("title"),
            "description": row.get("description"),
            "is_all_day": False,
            "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
            "source_timezone": ZONE,
            "event_url": row.get("event_url"),
            "venue_name": row.get("venue_name"),
            "venue_address": row.get("venue_address"),
            "venue_city": row.get("venue_city"),
            "attendance_mode": "in_person",
        }
        if end is not None:
            expected["ends_at_utc"] = end.astimezone(timezone.utc).isoformat()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    if facts.get("source_image_url") != row.get("image_url"):
        return False
    return all(facts.get(name) == value for name, value in expected.items())


def _row(key, item, body, place, *, point=None, native="", publisher_geo=False,
         source_coordinates=None):
    start, end = timestamp(item["start"]), timestamp(item.get("end"))
    if not event_url(key, item["url"]) or not isinstance(item.get("title"), str) or not 1 <= len(item["title"]) <= 180:
        raise ValueError("new_york_social_identity")
    body = _body(body)
    point = point or reviewed_venue_location(key, *place[:2]) or (None, None)
    row = record(item["title"], start, end, *place, item["url"], _id(key, item["url"], start, native),
                 category=item.get("category", ""), lat=point[0], lng=point[1], tz=ZONE,
                 publisher_geo=publisher_geo, retain_until_end=True)
    if row is not None:
        row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                   location_provenance="publisher_event_geo" if publisher_geo else
                   "reviewed_nyc_pad_address_point" if point[0] is not None else
                   "publisher_event_street_pending_geocode")
        if point[0] is not None:
            row.update(lat=point[0], lng=point[1])
            if row.get("reason") == "missing_verified_venue_geo":
                row["reason"] = None
        image = photo_url(key, item.get("image"))
        if image:
            row["image_url"] = image
        if key == PRIDE:
            row["publisher_native_id"] = native
        _attach_content(row, body, content_venue=_content_venue(place), image=image,
                        provider_venue_id=native or None,
                        source_coordinates=source_coordinates)
    return row


def _single_venue_evidence(key, node):
    """A newly supplied offsite location cannot inherit a reviewed home pin."""
    aliases = {IRISH: {"new york irish center", "ny irish center"}, REPAIR: {"another world"}}
    street = {IRISH: r"10[- ]?40\s+Jackson\s+Ave(?:nue)?", REPAIR: r"629\s+Nostrand\s+Ave(?:nue)?"}[key]
    for location in node.select(".eventlist-meta-address,.eventitem-meta-address"):
        supplied = plain(location.get_text(" ")).removesuffix("(map)").strip().casefold()
        if supplied and supplied not in aliases[key]:
            raise ValueError("new_york_social_location_unresolved")
        for a in location.select("a[href]"):
            target = urlsplit(a["href"])
            if target.hostname not in {"maps.google.com", "www.google.com"}:
                continue
            for query in parse_qs(target.query).get("q", []):
                if not re.match(street + r"\b", query, re.I):
                    raise ValueError("new_york_social_location_unresolved")


def _square_manifest(key, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    if soup.select_one(".eventlist") is None:
        raise ValueError("new_york_social_calendar_changed")
    result = []
    for card in soup.select("article.eventlist-event--upcoming"):
        link = card.select_one("a.eventlist-title-link[href]")
        if link is None:
            raise ValueError("new_york_social_identity")
        title = plain(link.get_text(" "))
        start, end = _clock(card, "start"), _clock(card, "end")
        if NONPUBLIC.search(title) or not _within(start, end, now):
            continue
        url = urljoin(SOURCES[key][0], link["href"])
        if not event_url(key, url):
            raise ValueError("new_york_social_identity")
        item = dict(type="square", url=url, title=title, start=start.isoformat(), end=end.isoformat())
        try:
            _single_venue_evidence(key, card)
        except ValueError as exc:
            item["held"] = str(exc)
        excerpt = card.select_one(".eventlist-excerpt")
        if excerpt:
            try:
                item["excerpt"] = _body(excerpt)
            except ValueError:
                # An incomplete teaser never blocks access to the full detail.
                pass
        image = card.select_one("img[data-src],img[src]")
        if image:
            item["image"] = image.get("data-src") or image.get("src")
        if key == REPAIR:
            bodies = card.select(".eventlist-description .sqs-layout")
            if len(bodies) == 1 and not excerpt:
                try:
                    item["body"] = _body(bodies[0])
                    if not re.search(r"\bAnother World\b", item["body"]) or not re.search(r"\b629\s+Nostrand\s+Ave(?:nue)?\b", item["body"], re.I):
                        item["held"] = "new_york_social_location_unresolved"
                except ValueError as exc:
                    item["held"] = str(exc)
        result.append(item)
    return result


def _square_detail_root(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    heading = soup.select_one("h1.eventitem-title")
    if canonical is None or canonical.get("href") != item["url"] or heading is None or plain(heading.get_text(" ")) != item["title"]:
        raise ValueError("new_york_social_detail_changed")
    if (_clock(soup, "start"), _clock(soup, "end")) != (timestamp(item["start"]), timestamp(item["end"])):
        raise ValueError("new_york_social_schedule_conflict")
    return soup


def _repair_detail(item, payload):
    soup = _square_detail_root(item, payload)
    _single_venue_evidence(REPAIR, soup)
    bodies = soup.select(".eventitem-column-content .sqs-layout")
    if len(bodies) != 1:
        raise ValueError("new_york_social_description_missing")
    body = _body(bodies[0])
    if not re.search(r"\bAnother World\b", body) or not re.search(r"\b629\s+Nostrand\s+Ave(?:nue)?\b", body, re.I):
        raise ValueError("new_york_social_location_unresolved")
    row = _row(REPAIR, item, body, VENUES[REPAIR])
    return [row] if row else []


def _irish_detail(item, payload):
    soup = _square_detail_root(item, payload)
    _single_venue_evidence(IRISH, soup)
    container = soup.select_one(".eventitem-column-content")
    bodies = container.select(".sqs-layout") if container else []
    if len(bodies) == 1:
        body = _body(bodies[0])
    elif container and not container.get_text(strip=True) and not container.select("img,iframe,video"):
        # Computer Club's complete published narrative exists solely in the
        # listing and all native description metadata; its detail body is empty.
        metas = [plain(x.get("content")) for x in soup.select('meta[property="og:description"],meta[name="description"]')]
        excerpt = item.get("excerpt", "")
        if len(metas) != 2 or set(metas) != {plain(excerpt)} or not re.search(r"[.!?]$", excerpt) or "..." in excerpt or "…" in excerpt:
            raise ValueError("new_york_social_description_missing")
        body = _body(excerpt)
    else:
        raise ValueError("new_york_social_description_missing")
    # An outing's destination/show address is not evidence of its departure
    # point. Do not substitute the Center into an off-site outing.
    if re.search(r"\b(?:outing|excursion|field trip|off.site)\b", item["title"], re.I):
        raise ValueError("new_york_social_location_unresolved")
    if item["url"].endswith("/2026/12/11/new-york-croons-for-christmas") and (item["start"], item["end"]) == ("2026-12-11T18:00:00-05:00", "2026-12-11T20:00:00-05:00"):
        # Linked official Humanitix says18:30–21:00; source prose says doors18:00
        # and show19:00. This exact conflicting occurrence is withheld.
        raise ValueError("publisher_schedule_conflict")
    if not re.search(r"\b10[- ]?40\s+Jackson\s+Ave(?:nue)?\b", soup.get_text(" "), re.I):
        raise ValueError("new_york_social_location_unresolved")
    row = _row(IRISH, item, body, VENUES[IRISH])
    return [row] if row else []


def _industry_manifest(fetch, now):
    start_day = now.astimezone(ZoneInfo(ZONE)).date()
    queue = []
    total, raw_ids = None, set()
    for page in range(1, 3):
        query = urlencode(dict(start_date=start_day.isoformat(), end_date=(start_day + timedelta(days=61)).isoformat(), per_page=100, page=page))
        payload = json.loads(fetch(INDUSTRY_API + "?" + query, "application/json"))
        if (not isinstance(payload, dict) or not isinstance(payload.get("events"), list)
                or type(payload.get("total")) is not int or not 0 <= payload["total"] <= 200
                or type(payload.get("total_pages")) is not int or not 0 <= payload["total_pages"] <= 2):
            raise ValueError("new_york_social_calendar_changed")
        if len(payload["events"]) > 100 or total is not None and total != payload["total"]:
            raise ValueError("new_york_social_calendar_changed")
        total = payload["total"]
        for event in payload["events"]:
            if not isinstance(event, dict) or not event_url(INDUSTRY, event.get("url")) or type(event.get("id")) is not int:
                raise ValueError("new_york_social_identity")
            if event["id"] in raw_ids:
                raise ValueError("new_york_social_calendar_changed")
            raw_ids.add(event["id"])
            if event.get("status") != "publish" or event.get("all_day") or event.get("is_virtual") or event.get("hide_from_listings"):
                continue
            # The publisher's TEC installation labels local NYC wall clocks
            # UTC+0. Its visible pages and Fort Hamilton's own calendar confirm
            # these are local times; never shift the printed event five hours.
            if event.get("timezone") not in {"UTC+0", "UTC", ZONE}:
                raise ValueError("new_york_social_schedule_conflict")
            start = timestamp(datetime.strptime(event["start_date"], "%Y-%m-%d %H:%M:%S"), ZONE)
            end = timestamp(datetime.strptime(event["end_date"], "%Y-%m-%d %H:%M:%S"), ZONE)
            if not _within(start, end, now):
                continue
            item = dict(type="industry", url=event["url"], title=plain(event.get("title")), start=start.isoformat(), end=end.isoformat(), native=str(event["id"]))
            if re.search(r"/(?:sake-and-cheese-pairing-class-and-brewery-tour|guided-brewery-tour-and-sake-tasting)/", item["url"]):
                item["held"] = "existing_direct_sake_source"
            try:
                item["body"] = _body(event.get("description"))
            except ValueError as exc:
                item["held"] = str(exc)
            if ("/spirited-away-psychic-paranormal-night/" in item["url"]
                    and re.search(r"\bTuesday, November 10th, 7-11pm\b", item.get("body", ""))
                    and (start.month, start.day) != (11, 10)):
                item["held"] = "publisher_schedule_conflict"
            image = event.get("image")
            if isinstance(image, dict):
                item["image"] = image.get("url")
            queue.append(item)
        if page >= payload["total_pages"]:
            break
    if len(raw_ids) != total:
        raise ValueError("new_york_social_calendar_changed")
    return queue


def _industry_location(soup):
    section = soup.select_one(".business-left-side")
    if section is None:
        raise ValueError("new_york_social_location_unresolved")
    tenants = section.select(".location-line-wrapper")
    if len(tenants) == 1:
        name = tenants[0].select_one("strong")
        line = tenants[0].select_one(".location-line")
        if name is None or line is None:
            raise ValueError("new_york_social_location_unresolved")
        venue = plain(name.get_text(" "))
        address = plain(line.get_text(" "))
        address = re.sub(r"\s*BLDG:\s*", " Building ", address, flags=re.I)
        if not re.fullmatch(r"\d[\w -]*\s+\d+(?:st|nd|rd|th)?\s+St(?:reet)?(?:\s+Building\s+[\w-]+)?", address, re.I):
            raise ValueError("new_york_social_location_unresolved")
        address = re.sub(r"\bSt(?:reet)?\b", "Street", address, flags=re.I)
        return venue, f"{address}, Brooklyn, NY 11232", "Brooklyn"
    if tenants:
        raise ValueError("new_york_social_location_unresolved")
    # These are event-specific paragraphs directly in the event column. The
    # site's headquarters footer is outside this selector and cannot be used.
    candidates = []
    for node in section.find_all("p", recursive=False):
        text = plain(node.get_text(" "))
        text = re.sub(r",?\s*USA$", "", text)
        text = re.sub(r"St[.]", "St", text)
        city = re.search(r",?\s+Brooklyn,?\s+NY\s*(11232)$", text, re.I)
        if not city:
            continue
        before = text[:city.start()].strip(" ,")
        streets = list(re.finditer(r"\b\d+\s+\d+(?:st|nd|rd|th)?\s+St(?:reet)?\b", before, re.I))
        if len(streets) != 1:
            continue
        match = streets[0]
        venue = before[:match.start()].strip(" ,")
        floor = before[match.end():].strip(" ,")
        if floor and not re.fullmatch(r"2nd\s+(?:FL|Floor)", floor, re.I):
            continue
        building = re.search(r"\bBuilding\s+([\w-]+)$", venue, re.I)
        if building:
            venue = venue[:building.start()].strip(" ,")
        street = re.sub(r"\bSt(?:reet)?\b", "Street", match[0], flags=re.I)
        if building:
            street += " Building " + building[1]
        if floor:
            street += " 2nd Floor"
        candidates.append((venue or "Industry City", f"{street}, Brooklyn, NY {city[1]}", "Brooklyn"))
    if len(candidates) != 1:
        raise ValueError("new_york_social_location_unresolved")
    return candidates[0]


def _industry_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    title = soup.select_one("h1.tribe-events-single-event-title")
    canonical = soup.select_one('link[rel="canonical"]')
    body = soup.select_one(".tribe-events-single-event-description")
    if title is None or plain(title.get_text(" ")) != item["title"] or canonical is None or canonical.get("href") != item["url"] or body is None:
        raise ValueError("new_york_social_detail_changed")
    full = _body(body)
    if full != item["body"]:
        raise ValueError("new_york_social_detail_changed")
    schedule = soup.select_one(".business-left-side .event-date-time")
    start, end = timestamp(item["start"]), timestamp(item["end"])
    clocks = f"{start.strftime('%I:%M %p').lstrip('0').lower()} - {end.strftime('%I:%M %p').lstrip('0').lower()}"
    expected = {f"{start:%a}, {start:%B} {start.day} | {clocks}",
                f"{start:%B} {start.day}, {start.year} | {clocks}"}
    if schedule is None or plain(schedule.get_text(" ")) not in expected:
        raise ValueError("new_york_social_schedule_conflict")
    row = _row(INDUSTRY, item, full, _industry_location(soup), native=item["native"])
    return [row] if row else []


def _wix_manifest(calendar, sitemap, now):
    if "<!DOCTYPE" in sitemap.upper() or "<!ENTITY" in sitemap.upper():
        raise ValueError("new_york_social_calendar_changed")
    root = ET.fromstring(sitemap)
    if root.tag.rsplit("}", 1)[-1] != "urlset" or len(root) > 5000:
        raise ValueError("new_york_social_calendar_changed")
    day = now.astimezone(ZoneInfo(ZONE)).date()
    candidates = {}
    for entry in root:
        parts = {child.tag.rsplit("}", 1)[-1]: child.text for child in entry}
        raw = parts.get("loc", "")
        url = raw.removesuffix("/form").rstrip("/")
        if not event_url(PRIDE, url):
            raise ValueError("new_york_social_identity")
        dated = re.search(r"-(20\d{2})-(\d{2})-(\d{2})-\d{2}-\d{2}(?:-\d+)?$", url)
        hint = date(*map(int, dated.groups())) if dated else None
        # The URL date only bounds sitemap discovery. Actual start/end and
        # attendance always come from each full native event document.
        if (hint is None or day - timedelta(days=1) <= hint <= day + timedelta(days=61)
                or parts.get("lastmod", "") >= (day - timedelta(days=7)).isoformat()):
            candidates[url] = max(candidates.get(url, ""), parts.get("lastmod", ""))
    soup = BeautifulSoup(calendar, "html.parser")
    script = soup.select_one('script#wix-warmup-data[type="application/json"]')
    if script is None:
        raise ValueError("new_york_social_calendar_changed")
    widgets = json.loads(script.string or script.get_text())["appsWarmupData"][WIX_APP]
    found = False
    for widget in widgets.values():
        envelope = widget.get("events") if isinstance(widget, dict) else None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("events"), list):
            continue
        found = True
        for event in envelope["events"]:
            url = "https://www.lgbtbrooklyn.org/event-details/" + str(event.get("slug", ""))
            if url not in candidates:
                raise ValueError("new_york_social_calendar_changed")
    if not found or not candidates or len(candidates) > MAX_MANIFEST:
        raise ValueError("new_york_social_manifest_limit")
    return [dict(type="wix", url=url, modified=candidates[url]) for url in sorted(candidates)]


def _wix_text(value):
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
        return ""
    def content(node):
        if not isinstance(node, dict) or not isinstance(node.get("nodes", []), list):
            raise ValueError("new_york_social_detail_changed")
        if node.get("type") == "TEXT":
            text = (node.get("textData") or {}).get("text")
            if not isinstance(text, str):
                raise ValueError("new_york_social_detail_changed")
            return text
        if node.get("type") == "LINE_BREAK":
            return "\n"
        inner = "".join(content(child) for child in node.get("nodes", []))
        return inner + ("\n" if node.get("type") in {"PARAGRAPH", "HEADING", "LIST_ITEM", "BLOCKQUOTE"} else "")
    # Wix emits an empty PARAGRAPH even when no long narrative is supplied.
    # Its newline is not content and must not mask a complete short narrative.
    return "".join(content(node) for node in value["nodes"]).replace("\u200b", "").replace("\ufeff", "").strip()


def _wix_location(event):
    loc = event.get("location") or {}
    full = loc.get("fullAddress") or {}
    if loc.get("type") != 0 or loc.get("tbd") is not False or full.get("country") != "US" or full.get("subdivision") != "NY":
        raise ValueError("new_york_social_location_unresolved")
    venue, address, city = plain(loc.get("name")), plain(loc.get("address")), plain(full.get("city"))
    structured = full.get("streetAddress") or {}
    number, street = str(structured.get("number") or ""), plain(structured.get("name"))
    city_postcode = re.search(r",\s*" + re.escape(city) + r",\s*NY\s*(\d{5})(?:-\d{4})?\b", address, re.I)
    if (not venue or city not in {"Brooklyn", "New York", "Queens", "Bronx", "Staten Island", "Long Island City", "Astoria"}
            or address != plain(full.get("formattedAddress")) or not re.match(re.escape(number) + r"\s+", address)
            or not number or not street or city_postcode is None
            or full.get("postalCode") and str(full["postalCode"])[:5] != city_postcode[1]):
        raise ValueError("new_york_social_location_unresolved")
    aliases = {"avenue": "ave", "street": "st", "road": "rd", "boulevard": "blvd", "drive": "dr"}
    def words(value):
        return [aliases.get(word, word) for word in re.findall(r"[a-z0-9]+", value.lower())]
    if words(address.split(",")[0]) != words(number + " " + street):
        raise ValueError("new_york_social_location_unresolved")
    coords, geo = loc.get("coordinates") or {}, full.get("geocode") or {}
    try:
        lat, lng = float(coords["lat"]), float(coords["lng"])
        if not all(math.isfinite(v) for v in (lat, lng)) or not 40.45 < lat < 40.96 or not -74.26 < lng < -73.69 or abs(lat - float(geo["latitude"])) > 0.00001 or abs(lng - float(geo["longitude"])) > 0.00001:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("new_york_social_location_unresolved") from None
    return (venue, re.sub(r",\s*USA$", "", address), city), (lat, lng)


def _wix_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    script = soup.select_one('script#wix-warmup-data[type="application/json"]')
    if canonical is None or canonical.get("href", "").removesuffix("/form").rstrip("/") != item["url"] or script is None:
        raise ValueError("new_york_social_detail_changed")
    try:
        event = json.loads(script.string or script.get_text())["appsWarmupData"][WIX_APP]["EventsPageInitialState"]["event"]["event"]
    except (KeyError, TypeError, ValueError):
        raise ValueError("new_york_social_detail_changed") from None
    if not isinstance(event, dict) or not UUID.fullmatch(str(event.get("id", ""))) or "https://www.lgbtbrooklyn.org/event-details/" + str(event.get("slug")) != item["url"]:
        raise ValueError("new_york_social_identity")
    config = (event.get("scheduling") or {}).get("config") or {}
    if event.get("status") != 0:
        raise ValueError("publisher_event_not_active")
    if not event.get("publishedDate") or config.get("scheduleTbd") is not False:
        raise ValueError("not_in_person_or_unpublished")
    if config.get("timeZoneId") != ZONE:
        raise ValueError("new_york_social_schedule_conflict")
    start, end = timestamp(config.get("startDate")), None if config.get("endDateHidden") else timestamp(config.get("endDate"))
    if not _within(start, end, now):
        return []
    title = plain(event.get("title"))
    if NONPUBLIC.search(title):
        raise ValueError("no_available_appointments")
    if (event.get("location") or {}).get("type") != 0:
        raise ValueError("not_in_person_or_unpublished")
    long_text = _wix_text(event.get("longDescription"))
    body = _body(long_text or event.get("about") or event.get("description"))
    place, point = _wix_location(event)
    native = dict(item, title=title, start=start.isoformat(), end=end.isoformat() if end else None,
                  image=(event.get("mainImage") or {}).get("url"))
    row = _row(PRIDE, native, body, place, point=point, native=event["id"], publisher_geo=True,
               source_coordinates=point)
    return [row] if row else []


def _manifest(key, fetch, now):
    if key == INDUSTRY:
        queue = _industry_manifest(fetch, now)
    elif key == PRIDE:
        queue = _wix_manifest(fetch(SOURCES[key][0], "text/html"), fetch(WIX_SITEMAP, "application/xml"), now)
    else:
        queue = _square_manifest(key, fetch(SOURCES[key][0], "text/html"), now)
    maximum = MAX_MANIFEST if key == PRIDE else 200
    if len(queue) > maximum or len({(x["url"], x.get("start")) for x in queue}) != len(queue):
        raise ValueError("new_york_social_manifest_limit")
    return sorted(queue, key=lambda x: (x.get("start", ""), x["url"]))


def _checkpoint(value, key, now):
    if value is None:
        return None
    maximum = MAX_MANIFEST if key == PRIDE else 200
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or value.get("source_key") != key or type(value.get("cursor")) is not int or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= maximum
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or not isinstance(value.get("events"), list) or len(value["events"]) > maximum
            or not isinstance(value.get("diagnostics"), list) or len(value["diagnostics"]) > MAX_DIAGNOSTICS
            or len(value["events"]) + len(value["diagnostics"]) != value["cursor"]
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("manifest_hash", "")))
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError("new_york_social_checkpoint_invalid")
    try:
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:\+00:00|Z)", str(value.get("started_at", ""))):
            raise ValueError
        started = timestamp(value["started_at"])
        if started is None or started.tzinfo is None or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("new_york_social_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=4):
        return None
    for item in value["queue"]:
        if not isinstance(item, dict) or not event_url(key, item.get("url")):
            raise ValueError("new_york_social_checkpoint_invalid")
    prefix = {item["url"]: item for item in value["queue"][:value["cursor"]]}
    seen = set()
    for row in value["events"]:
        item = prefix.get(row.get("event_url")) if isinstance(row, dict) else None
        if (item is None or row["event_url"] in seen or not re.fullmatch(r"nyc-social:[a-f0-9]{64}", str(row.get("id", "")))
                or not isinstance(row.get("description"), str) or not 1 <= len(row["description"]) <= MAX_DESCRIPTION
                or not row.get("venue_name") or not row.get("venue_address") or row.get("timezone") != ZONE
                or not _content_envelope_valid(row)
                or row.get("image_url") is not None and photo_url(key, row["image_url"]) is None):
            raise ValueError("new_york_social_checkpoint_invalid")
        try:
            if _body(row["description"]) != row["description"]:
                raise ValueError
        except ValueError:
            raise ValueError("new_york_social_checkpoint_invalid") from None
        if key != PRIDE and (row["id"] != _id(key, item["url"], item["start"], item.get("native", ""))
                or row.get("title") != item["title"] or timestamp(row.get("starts_at")) != timestamp(item["start"])
                or timestamp(row.get("ends_at")) != timestamp(item.get("end"))
                or "body" in item and row["description"] != item["body"]):
            raise ValueError("new_york_social_checkpoint_invalid")
        if key in VENUES and ((row.get("venue_name"), row.get("venue_address"), row.get("venue_city")) != VENUES[key]
                or (row.get("lat"), row.get("lng")) != POINTS[key]):
            raise ValueError("new_york_social_checkpoint_invalid")
        evidence = row.get("collector_event_content_v1")
        if evidence is not None:
            facts = evidence["facts"]
            expected_venue = _content_venue((row["venue_name"], row["venue_address"], row["venue_city"]))
            expected_provider = (str(row.get("publisher_native_id")) if key == PRIDE
                                 else str(item.get("native")) if item.get("native") else None)
            if (any(facts.get(name) != value for name, value in expected_venue.items())
                    or facts.get("provider_venue_id") != expected_provider):
                raise ValueError("new_york_social_checkpoint_invalid")
            if key == PRIDE:
                if ((facts.get("source_latitude"), facts.get("source_longitude"))
                        != (float(row["lat"]), float(row["lng"]))):
                    raise ValueError("new_york_social_checkpoint_invalid")
            elif "source_latitude" in facts or "source_longitude" in facts:
                raise ValueError("new_york_social_checkpoint_invalid")
        if key == PRIDE:
            native = str(row.get("publisher_native_id", ""))
            start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
            try:
                lat, lng = float(row.get("lat")), float(row.get("lng"))
                valid_point = all(math.isfinite(v) for v in (lat, lng)) and 40.45 < lat < 40.96 and -74.26 < lng < -73.69
            except (TypeError, ValueError, OverflowError):
                valid_point = False
            if (not UUID.fullmatch(native) or start is None or start.tzinfo is None or end is not None and end <= start
                    or row["id"] != _id(key, row["event_url"], start, native) or not valid_point
                    or not isinstance(row.get("title"), str) or not 1 <= len(row["title"]) <= 180
                    or row.get("location_provenance") != "publisher_event_geo" or row.get("attendance_mode") != "in_person"
                    or not re.match(r"\d[\w-]*\s+\S", row["venue_address"])
                    or not re.search(r",\s*NY\s*\d{5}(?:-\d{4})?$", row["venue_address"])):
                raise ValueError("new_york_social_checkpoint_invalid")
        seen.add(row["event_url"])
    for item in value["diagnostics"]:
        if not isinstance(item, dict) or item.get("event_url") not in prefix or item["event_url"] in seen or item.get("disposition") != "held" or item.get("reason") not in HELD_REASONS:
            raise ValueError("new_york_social_checkpoint_invalid")
        seen.add(item["event_url"])
    if seen != set(prefix):
        raise ValueError("new_york_social_checkpoint_invalid")
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("new_york_social_checkpoint_invalid")
    state = _checkpoint(checkpoint, key, current)
    legacy_prefix = bool(state and state["events"] and
                         any("collector_event_content_v1" not in row for row in state["events"]))
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    queue = _manifest(key, fetch, anchor)
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest or state["queue"] != queue:
        if state is not None:
            queue = _manifest(key, fetch, current)
            digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        state = dict(version=1, source_key=key, started_at=current.astimezone(timezone.utc).isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(), manifest_hash=digest,
                     manifest_count=len(queue), queue=queue, cursor=0, events=[], diagnostics=[])
    prior, fetched = state["cursor"], 0
    source_limit = MAX_DETAILS_PER_SOURCE.get(key, MAX_DETAILS_PER_CHUNK)
    limit = source_limit if max_details is None else min(source_limit, max(1, int(max_details)))
    while state["cursor"] < len(queue):
        item = queue[state["cursor"]]
        detail = "held" not in item and not (key == REPAIR and "body" in item)
        if detail and (fetched >= limit or deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at):
            break
        try:
            if item.get("held"):
                raise ValueError(item["held"])
            if not detail:
                row = _row(key, item, item["body"], VENUES[key])
                rows = [row] if row else []
            else:
                payload = fetch(item["url"], "text/html")
                fetched += 1
                rows = (_industry_detail(item, payload) if key == INDUSTRY else
                        _wix_detail(item, payload, current) if key == PRIDE else
                        _repair_detail(item, payload) if key == REPAIR else _irish_detail(item, payload))
            if legacy_prefix:
                for row in rows:
                    row.pop("collector_event_content_v1", None)
            state["events"].extend(rows)
            if not rows:
                raise ValueError("no_available_future_occurrence")
        except ValueError as exc:
            if str(exc) not in HELD_REASONS:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=str(exc)))
            if len(state["diagnostics"]) > MAX_DIAGNOSTICS:
                raise ValueError("new_york_social_checkpoint_size_limit")
        state["cursor"] += 1
        if len(state["events"]) > MAX_RECORDS:
            raise ValueError("new_york_social_record_limit")
    if state["cursor"] == prior < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_social_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda x: (x["starts_at"], x["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("new_york_social_checkpoint_required")
    return result["events"]
