"""Reviewed NYC museum, performing arts and maker calendars remaining after B2.

Native ICS and TEC facts are reused. Blank TEC narratives are hydrated from the
publisher's complete detail page. Slow publishers and external workshop pages
use bounded, replayable checkpoints; no incomplete manifest is published.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from icalendar import Calendar

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

log = logging.getLogger(__name__)
ZONE = "America/New_York"
TRANSIT = "ny_transit_museum_ny"
BCM = "brooklyn_childrens_museum_ny"
FLUSHING = "flushing_town_hall_ny"
MAKER = "makerspace_nyc_ny"
BPL = "brooklyn_public_library_presents_ny"
SOURCES = {
    TRANSIT: ("https://www.nytransitmuseum.org/programs/", "html", "html"),
    BCM: ("https://www.brooklynkids.org/events/", "html", "html"),
    FLUSHING: ("https://www.flushingtownhall.org/events", "html", "html"),
    MAKER: ("https://www.makerspace.nyc/classes", "html", "html"),
    BPL: ("https://www.bklynlibrary.org/bpl-presents/events", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
ALLOWED_HOSTS[MAKER] = ("www.makerspace.nyc", "www.eventbrite.com")
CHECKPOINT_KEYS = {TRANSIT, FLUSHING, MAKER, BPL}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 200
MAX_CHECKPOINT_BYTES = 900000
TRANSIT_API = "https://www.nytransitmuseum.org/wp-json/tribe/events/v1/events"
BCM_ICS = "https://www.brooklynkids.org/events.ics"
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|members?[- ]only|member monday|closed|closes early|private event)\b", re.I)
REMOTE = re.compile(r"\b(?:virtual|webinar|online only|via zoom)\b", re.I)

# Exact native museum identity plus publisher's current numbered postal address.
TRANSIT_VENUE = ("New York Transit Museum, Brooklyn", "99 Schermerhorn Street, Brooklyn, NY 11201", "Brooklyn", 40.6903327, -73.9896449)
BCM_VENUE = ("Brooklyn Children's Museum", "145 Brooklyn Avenue, Brooklyn, NY 11213", "Brooklyn", 40.674511, -73.943896)
FTH_VENUE = ("Flushing Town Hall", "137-35 Northern Boulevard, Flushing, NY 11354", "Flushing", 40.763883, -73.830072)
HOLIDAY_VENUE = ("2 Av–Houston St station (uptown F boarding)", "Second Avenue & East Houston Street, New York, NY 10003", "New York", 40.7239689, -73.9912799)
GRAND_CENTRAL_VENUE = ("Grand Central Terminal (approximate meeting point; check ticket instructions)", "89 East 42nd Street, New York, NY 10017", "New York", 40.752732, -73.977218)
PENN_VENUE = ("Penn Station / Moynihan Train Hall (approximate meeting point; check ticket instructions)", "351 West 31st Street, New York, NY 10001", "New York", 40.751538, -73.995854)
REVIEWED_INTERSECTIONS = [dict(source_key=TRANSIT, venue_name=HOLIDAY_VENUE[0], venue_address=HOLIDAY_VENUE[1],
    lat=HOLIDAY_VENUE[3], lng=HOLIDAY_VENUE[4],
    evidence_url="https://data.ny.gov/Transportation/MTA-Subway-Entrances-and-Exits-2024/i9wp-a4ja/about_data",
    provenance="publisher_named_boarding_station_mta_F14_native_entrance", approximate=False)]

# Exact publisher detail slugs and native venue/street text, reviewed against
# NYC Planning PAD. Off-site programs never inherit the organizer's address.
FTH_OFFSITE = {
    "a-collective-thread-collaborative-drawings-with-older-adults":
        ("Queens Blvd. Extended Care", "61-11 Queens Blvd", ("Queens Boulevard Extended Care Lobby", "61-11 Queens Boulevard, Woodside, NY 11377", "Woodside", 40.741704, -73.903008)),
    "max-pollak-the-rumbatap-jam":
        ("Terraza 7", "40-19 Gleane St", ("Terraza 7", "40-19 Gleane Street, Elmhurst, NY 11373", "Elmhurst", 40.747603, -73.881805)),
    "raising-our-voices-building-bridges-through-words-movement":
        ("Queens Community House", "108-25 62nd Dr", ("Queens Community House", "108-25 62nd Drive, Forest Hills, NY 11375", "Forest Hills", 40.736304, -73.850091)),
    "mapping-queens-stewards-of-historic-houses-heritage-sites":
        ("Lewis Latimer House", "34-41 137th Street", ("Lewis Latimer House", "34-41 137th Street, Flushing, NY 11354", "Flushing", 40.766757, -73.829338)),
    "senior-theater-acting-repertory-star-presents-40-years-young-at-heart":
        ("War Veterans Post 1979", "263-15 Union Tpke", ("War Veterans Post 1979", "263-15 Union Turnpike, Glen Oaks, NY 11004", "Glen Oaks", 40.748863, -73.70922)),
    "stones-throw":
        ("Lorimoto Gallery", "1623 Hancock St", ("Lorimoto Gallery", "1623 Hancock Street, Queens, NY 11385", "Queens", 40.697943, -73.906408)),
}
BPL_VENUES = {
    "/locations/central": ("Central Library", "10 Grand Army Plaza, Brooklyn, NY 11238", "Brooklyn", 40.6724, -73.96809),
    "/locations/center-for-brooklyn-history": ("Center for Brooklyn History", "128 Pierrepont Street, Brooklyn, NY 11201", "Brooklyn", 40.694798, -73.992413),
    "/locations/brooklyn-heights": ("Brooklyn Heights Library", "286 Cadman Plaza West, Brooklyn, NY 11201", "Brooklyn", 40.695753, -73.991452),
    "/locations/library-for-arts-and-culture": ("Library for Arts & Culture", "10 Lafayette Avenue Second Floor, Brooklyn, NY 11217", "Brooklyn", 40.686172, -73.978456),
}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_nyc_arts_final")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        host = "www.eventbrite.com" if key == MAKER else ALLOWED_HOSTS[key][0]
        if p.scheme != "https" or p.netloc != host or p.query or p.fragment:
            return False
        pattern = {TRANSIT: r"/program/[a-z0-9-]+(?:/20\d{2}-\d{2}-\d{2})?/?",
                   BCM: r"/events/[a-z0-9-]+/?", FLUSHING: r"/show-details/[a-z0-9-]+",
                   MAKER: r"/e/[a-z0-9-]+-tickets-\d{10,16}",
                   BPL: r"/calendar/[a-z0-9\u0080-\uffff-]+-20\d{6}-\d{4}(?:am|pm)"}[key]
        return bool(re.fullmatch(pattern, unquote(p.path) if key == BPL else p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or key not in SOURCES or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.fragment or ".." in p.path:
            return None
        if key == MAKER:
            if p.netloc == "img.evbuc.com" and p.path.startswith("/https%3A%2F%2Fcdn.evbuc.com%2Fimages%2F"):
                return value
        elif key == BPL:
            if (p.netloc == "static.bklynlibrary.org" and not p.query
                    and re.fullmatch(r"/prod/public/(?:images|inline-images)/[^\n]+\.(?:jpe?g|png|webp)", p.path, re.I)):
                return value
        elif p.netloc == ALLOWED_HOSTS[key][0] and not p.query:
            prefix = r"/storage/(?:header_image|show_image)/flushingtownhall/" if key == FLUSHING else r"/wp-content/uploads/20\d{2}/\d{2}/"
            if re.fullmatch(prefix + r"[^/]+\.(?:jpe?g|png|webp)", p.path, re.I):
                return value
    except ValueError:
        pass
    return None


def _check(deadline):
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if not text:
        raise ValueError("nyc_final_description_missing")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("nyc_final_description_limit")
    return text


def _within(start, end, now, days=60):
    return start < now + timedelta(days=days) and (end or start + timedelta(hours=3)) > now


def _row(key, identity, title, start, end, venue, url, body, labels=(), image=None):
    if not event_url(key, url):
        raise ValueError("nyc_final_identity_changed")
    name, address, city, lat, lng = venue
    row = record(title, start.isoformat(), end.isoformat() if end else None, name, address, city, url,
                 identity, ", ".join(labels), lat, lng, ZONE, publisher_geo=True, retain_until_end=True)
    if row:
        row.update(description=_body(body), timezone=ZONE, attendance_mode="in_person",
                   location_provenance=("publisher_named_station_reviewed_approximate_meeting_point"
                                        if "approximate meeting point" in name else "publisher_venue_and_reviewed_point"),
                   publisher_categories=list(labels))
        if photo := photo_url(key, image):
            row["image_url"] = photo
    return row


def _unique(rows):
    values = {}
    for row in rows:
        if not row:
            continue
        identity = (row["id"], row["starts_at"])
        if identity in values and values[identity] != row:
            raise ValueError("nyc_final_conflicting_occurrence")
        values[identity] = row
    if len(values) > MAX_RECORDS:
        raise ValueError("nyc_final_record_limit")
    return sorted(values.values(), key=lambda x: (x["starts_at"], x["id"]))


def _bcm(fetch, deadline, now):
    from roomquest.preview_worker import parse_ics_preview
    _check(deadline)
    payload = fetch(BCM_ICS, "text/calendar")
    native = Calendar.from_ical(payload).walk("VEVENT")
    if len(native) > 200 or len({str(e.get("UID")) for e in native}) != len(native) or any(e.get("RRULE") or e.get("RECURRENCE-ID") for e in native):
        raise ValueError("nyc_final_ics_shape_changed")
    if any(not re.fullmatch(r"\d+@brooklynkids\.org", str(e.get("UID"))) for e in native):
        raise ValueError("nyc_final_identity_changed")
    # The publisher's default feed has a 50-item horizon. A rolling 30-day
    # scope is complete only while that horizon reaches the end of our window.
    dates = [e.decoded("DTSTART") for e in native if isinstance(e.decoded("DTSTART"), datetime)]
    if len(native) >= 50 and (not dates or max(dates) < now + timedelta(days=30)):
        raise ValueError("nyc_final_ics_horizon_incomplete")
    by_id = {str(e["UID"]): e for e in native}
    rows = []
    for parsed in parse_ics_preview(payload, allow_ongoing=True, include_images=False, include_description=False):
        item = by_id[parsed["id"]]
        if not isinstance(item.decoded("DTSTART"), datetime):
            continue
        title, body = plain(item.get("SUMMARY")), str(item.get("DESCRIPTION", ""))
        if NONPUBLIC.search(title) or NONPUBLIC.search(body[:180]) or REMOTE.search(body):
            continue
        if item.get("LOCATION") and "Brooklyn Children" not in plain(item["LOCATION"]):
            log.warning("nyc_final_event_held source=%s id=%s reason=nyc_final_venue_unreviewed", BCM, parsed["id"])
            continue
        if re.search(r"\boff[- ]?site\b", body, re.I):
            continue
        start, end = timestamp(parsed["starts_at"]), timestamp(parsed.get("ends_at"))
        if not _within(start, end, now, 30):
            continue
        try:
            rows.append(_row(BCM, parsed["id"], title, start, end, BCM_VENUE, str(item["URL"]),
                             body, ("Family Programs",), str(item.get("ATTACH", ""))))
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            log.warning("nyc_final_event_held source=%s id=%s reason=%s", BCM, parsed["id"], exc)
    return _unique(rows)


def _transit_manifest(fetch, deadline, now):
    queue = []
    for page in range(1, 4):
        _check(deadline)
        params = dict(per_page=100, page=page, start_date=now.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                      end_date=(now + timedelta(days=60)).date().isoformat())
        payload = json.loads(fetch(TRANSIT_API + "?" + urlencode(params), "application/json"))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list) or len(payload["events"]) > 100:
            raise ValueError("nyc_final_payload_changed")
        for e in payload["events"]:
            labels = [plain(c.get("name")) for c in e.get("categories", []) if isinstance(c, dict)]
            if (e.get("status") != "publish" or e.get("all_day") or e.get("is_virtual")
                    or e.get("hide_from_listings") or any("Member" in s or "Virtual" in s for s in labels)
                    or NONPUBLIC.search(plain(e.get("title")))):
                continue
            start, end = timestamp(e.get("start_date"), ZONE), timestamp(e.get("end_date"), ZONE)
            if (e.get("timezone") != ZONE or not start or not end or end < start
                    or timestamp(e.get("utc_start_date"), "UTC") != start
                    or timestamp(e.get("utc_end_date"), "UTC") != end):
                raise ValueError("nyc_final_schedule_changed")
            if not _within(start, end, now):
                continue
            if not event_url(TRANSIT, e.get("url")) or type(e.get("id")) is not int:
                raise ValueError("nyc_final_identity_changed")
            queue.append(dict(id=str(e["id"]), url=e["url"], title=plain(e["title"]), starts_at=start.isoformat(),
                              ends_at=end.isoformat(), labels=labels, modified=plain(e.get("modified_utc"))))
        total = payload.get("total_pages")
        if type(total) is not int or not 0 <= total <= 3:
            raise ValueError("nyc_final_pagination_limit")
        if page >= total:
            return sorted(queue, key=lambda item: item["url"])
    raise ValueError("nyc_final_pagination_limit")


def _html_manifest(key, fetch, deadline):
    _check(deadline)
    soup = BeautifulSoup(fetch(SOURCES[key][0], "text/html"), "html.parser")
    queue = {}
    if key == FLUSHING:
        for node in soup.select(".show-item"):
            link = node.select_one('.show-buttons a[href*="/show-details/"]')
            title = node.select_one(".show-title")
            date = node.select_one(".show-time")
            if not link or not title or not date or not event_url(key, link["href"]):
                raise ValueError("nyc_final_listing_changed")
            url = link["href"]
            queue[url] = dict(url=url, id=url.rsplit("/", 1)[1], title=plain(title.get_text(" ")),
                              listing_date=plain(date.get_text(" ")))
    else:
        for a in soup.select('a[href*="eventbrite.com/e/"]'):
            p = urlsplit(a["href"])
            if set(parse_qs(p.query)) - {"aff"}:
                raise ValueError("nyc_final_identity_changed")
            url = p._replace(query="", fragment="").geturl()
            if not event_url(key, url):
                raise ValueError("nyc_final_identity_changed")
            queue[url] = dict(url=url, id=url.rsplit("-", 1)[1])
    if not queue:
        raise ValueError("nyc_final_listing_changed")
    if len(queue) > MAX_RECORDS:
        raise ValueError("nyc_final_manifest_limit")
    return sorted(queue.values(), key=lambda item: item["url"])


def _bpl_manifest(fetch, deadline, now):
    _check(deadline)
    soup = BeautifulSoup(fetch(SOURCES[BPL][0], "text/html"), "html.parser")
    if soup.select('nav.pager a, .pager a, a[rel="next"]'):
        raise ValueError("nyc_final_pagination_limit")
    queue = {}
    cards = soup.select(".event-item")
    if not cards:
        raise ValueError("nyc_final_listing_changed")
    for card in cards:
        title, location = card.select_one(".card-title"), card.select_one(".location")
        link = card.select_one('.event-content a[href^="/calendar/"]')
        labels = [plain(a.get_text(" ")) for a in card.select(".tags a")]
        if not title or not location or not link or "BPL Presents" not in labels:
            raise ValueError("nyc_final_bpl_scope_changed")
        url = urljoin(SOURCES[BPL][0], link["href"])
        if not event_url(BPL, url):
            raise ValueError("nyc_final_identity_changed")
        suffix = re.search(r"(20\d{6}-\d{4}(?:am|pm))$", url)[1]
        start = datetime.strptime(suffix, "%Y%m%d-%I%M%p").replace(tzinfo=ZoneInfo(ZONE))
        if start.date() < now.astimezone(ZoneInfo(ZONE)).date() or start >= now + timedelta(days=60):
            continue
        queue[url] = dict(url=url, id="bpl:" + sha256(url.encode()).hexdigest()[:24], title=plain(title.get_text(" ")),
                          starts_at=start.isoformat(), venue_name=plain(location.get_text(" ")), labels=labels)
    return sorted(queue.values(), key=lambda item: item["url"])


def _bpl_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    heading, canonical = soup.select_one("main h1"), soup.select_one('link[rel="canonical"]')
    bodies = soup.select("main .layout--twocol-section > .layout__region--first")
    cal, location = soup.select_one("main .addeventatc"), soup.select_one("main .meta .location")
    if (not heading or not canonical or unquote(canonical.get("href", "")) != unquote(item["url"])
            or plain(heading.get_text(" ")) != item["title"] or len(bodies) != 1 or not cal or not location):
        raise ValueError("nyc_final_identity_changed")
    labels = [plain(a.get_text(" ")) for a in soup.select("main p.tags a")]
    if "BPL Presents" not in labels:
        raise ValueError("nyc_final_bpl_scope_changed")
    fields = {name: cal.select_one("." + name) for name in ("start", "end", "timezone", "title")}
    if any(node is None for node in fields.values()) or plain(fields["timezone"].get_text()) != ZONE:
        raise ValueError("nyc_final_schedule_changed")
    try:
        start = datetime.strptime(plain(fields["start"].get_text()), "%m/%d/%Y %I:%M %p").replace(tzinfo=ZoneInfo(ZONE))
        end = datetime.strptime(plain(fields["end"].get_text()), "%m/%d/%Y %I:%M %p").replace(tzinfo=ZoneInfo(ZONE))
    except ValueError:
        raise ValueError("nyc_final_schedule_changed") from None
    if start != timestamp(item["starts_at"]) or end <= start or plain(fields["title"].get_text()) != item["title"]:
        raise ValueError("nyc_final_schedule_changed")
    if not _within(start, end, now) or NONPUBLIC.search(item["title"]) or REMOTE.search(item["title"]):
        return []
    links = soup.select('main a[href^="/locations/"]')
    if len(links) != 1 or links[0]["href"] not in BPL_VENUES:
        raise ValueError("nyc_final_venue_unreviewed")
    place = BPL_VENUES[links[0]["href"]]
    address = soup.select_one('main [itemprop="address"]')
    if not address:
        raise ValueError("nyc_final_venue_unreviewed")
    parts = [address.select_one("." + name) for name in ("thoroughfare", "locality", "state", "postal-code")]
    if any(part is None for part in parts):
        raise ValueError("nyc_final_venue_unreviewed")
    street, city, state, postal = [plain(part.get_text(" ")) for part in parts]
    native_address = f"{street.replace(',', '')}, {city}, {state} {postal}"
    venue_name = plain(location.get_text(" "))
    if (native_address != place[1] or venue_name != item["venue_name"]
            or not (venue_name == place[0] or venue_name.startswith(place[0] + ","))):
        raise ValueError("nyc_final_venue_changed")
    image = soup.select_one('meta[property="og:image"]')
    # Add-to-Calendar's own description is a visibly shortened excerpt. The
    # native first content column contains the complete text and all bios.
    body = _body(str(bodies[0]))
    return [_row(BPL, item["id"], item["title"], start, end, (venue_name,) + place[1:], item["url"],
                 body, labels, image.get("content") if image else None)]


def _transit_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    nodes = []
    for script in soup.select('script[type="application/ld+json"]'):
        value = json.loads(script.get_text())
        nodes.extend(value.get("@graph", [value]) if isinstance(value, dict) else value)
    events = [node for node in nodes if isinstance(node, dict) and node.get("@type") == "Event"]
    contents = soup.select("#tribe-events-content .top-text-content .text-content")
    if len(events) != 1 or not 1 <= len(contents) <= 6:
        raise ValueError("nyc_final_detail_changed")
    event = events[0]
    if event.get("url") != item["url"] or plain(event.get("name")) != item["title"]:
        raise ValueError("nyc_final_identity_changed")
    if event.get("eventStatus") != "https://schema.org/EventScheduled":
        return []
    start, end = timestamp(event.get("startDate")), timestamp(event.get("endDate"))
    if start != timestamp(item["starts_at"]) or end != timestamp(item["ends_at"]):
        raise ValueError("nyc_final_schedule_changed")
    narrative = "\n".join(str(n) for n in contents) + "\n" + "\n".join(str(n) for n in soup.select("#tribe-events-pg-template .ip-collapse"))
    body = _body(narrative)
    if NONPUBLIC.search(item["title"]) or REMOTE.search(item["title"]):
        return []
    place = event.get("location") or {}
    if (place.get("url") == "https://www.nytransitmuseum.org/location/transit-museum/"
            and plain(place.get("name")) == TRANSIT_VENUE[0]):
        geo = place.get("geo") or {}
        if (geo.get("latitude"), geo.get("longitude")) != TRANSIT_VENUE[3:]:
            raise ValueError("nyc_final_venue_changed")
        venue = TRANSIT_VENUE
    elif (item["url"].startswith("https://www.nytransitmuseum.org/program/2026holidayrides/")
          and "2 Av–Houston St" in body and "96 St–2 Av" in body):
        venue = HOLIDAY_VENUE
    elif (re.fullmatch(r"https://www\.nytransitmuseum\.org/program/grandcentral-12-11(?:-2)?/", item["url"])
          and "Grand Central" in body and "Grand Central Madison" in body):
        venue = GRAND_CENTRAL_VENUE
    elif (re.fullmatch(r"https://www\.nytransitmuseum\.org/program/penn-12-16(?:-2)?/", item["url"])
          and "Penn Station" in body and "Moynihan Train Hall" in body):
        venue = PENN_VENUE
    else:
        raise ValueError("nyc_final_meeting_place_not_public")
    image = next((n.get("url") for n in nodes if isinstance(n, dict) and n.get("@type") == "ImageObject"), None)
    return [_row(TRANSIT, item["id"], item["title"], start, end, venue, item["url"], body, item["labels"], image)] if _within(start, end, now) else []


def _clock(value, assumed=None):
    value = plain(value).lower().replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?", value)
    if not match or not (1 <= int(match[1]) <= 12) or int(match[2] or 0) > 59:
        raise ValueError("nyc_final_schedule_unresolved")
    meridiem = match[3] or assumed
    if meridiem not in {"a", "p", "am", "pm"}:
        raise ValueError("nyc_final_schedule_unresolved")
    return (int(match[1]) % 12 + (12 if meridiem.startswith("p") else 0), int(match[2] or 0))


def _time_range(text, date):
    match = re.fullmatch(r"\s*(\d{1,2}(?::\d{2})?\s*(?:[ap]m?)?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*([ap]m?))\s*", text, re.I)
    if not match:
        raise ValueError("nyc_final_schedule_unresolved")
    sh, sm = _clock(match[1], match[3].lower())
    eh, em = _clock(match[2])
    start = datetime.combine(date, datetime.min.time()).replace(hour=sh, minute=sm, tzinfo=ZoneInfo(ZONE))
    end = start.replace(hour=eh, minute=em)
    if end <= start or end - start > timedelta(hours=12):
        raise ValueError("nyc_final_schedule_unresolved")
    return start, end


def _fth_venue(item, body, start):
    reviewed = FTH_OFFSITE.get(item["id"])
    if reviewed:
        if reviewed[0] not in body or reviewed[1] not in body:
            raise ValueError("nyc_final_venue_changed")
        if item["id"].startswith("senior-theater-") and (start.month, start.day, start.year) != (12, 4, 2026):
            raise ValueError("nyc_final_venue_unreviewed")
        return reviewed[2]
    if re.search(r"\b(?:Grantee|Location:)\b", body, re.I):
        raise ValueError("nyc_final_venue_unreviewed")
    return FTH_VENUE


def _stones_occurrences(body, now):
    flat = plain(body)
    match = re.search(r"November 2 through November 15, (20\d{2})", flat)
    if not match or not re.search(r"open Tuesday through Sunday, 12:00 to 6:00 PM", flat):
        raise ValueError("nyc_final_schedule_unresolved")
    year = int(match[1])
    first, last = datetime(year, 11, 2, 12, tzinfo=ZoneInfo(ZONE)), datetime(year, 11, 15, 12, tzinfo=ZoneInfo(ZONE))
    result = []
    for day in range((last - first).days + 1):
        start = first + timedelta(days=day)
        end = start.replace(hour=18)
        if start.weekday() != 0 and _within(start, end, now):
            result.append((start, end, "exhibition", "Stone's Throw — Exhibition"))
    if "Saturday, November 14th at 6:30 PM" in flat:
        start = datetime(year, 11, 14, 18, 30, tzinfo=ZoneInfo(ZONE))
        if _within(start, None, now):
            result.append((start, None, "panel", "Stone's Throw — Panel Talk and Performance"))
    return result


def _flushing_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    heading, about = soup.select_one("#content h1"), soup.select_one("#about")
    if not heading or not about or item["title"] not in plain(heading.get_text(" ")):
        raise ValueError("nyc_final_identity_changed")
    body = _body(str(about))
    if REMOTE.search(body) or NONPUBLIC.search(item["title"]):
        return []
    occurrences = []
    if item["id"] == "stones-throw":
        occurrences = _stones_occurrences(body, now)
    else:
        table = soup.select_one("#tabsparent table")
        if not table:
            raise ValueError("nyc_final_schedule_unresolved")
        for tr in table.select("tbody tr"):
            cells = tr.select("td")
            if len(cells) < 2:
                raise ValueError("nyc_final_schedule_unresolved")
            day = datetime.strptime(plain(cells[0].get_text(" ")), "%b %d, %Y").date()
            for clock in cells[1].select("span"):
                hour, minute = _clock(clock.get_text(" "))
                start = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute, tzinfo=ZoneInfo(ZONE))
                end = None
                # Retain explicit same-day end times where native prose supplies
                # one. The published performance table remains the start authority.
                for match in re.finditer(r"(?<!\d)(\d{1,2}(?::\d{2})?\s*(?:[ap]m?)?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*[ap]m?)\b", plain(body[:650]), re.I):
                    try:
                        pstart, pend = _time_range(match[0], day)
                        if pstart == start:
                            end = pend
                            break
                    except ValueError:
                        continue
                if _within(start, end, now):
                    occurrences.append((start, end, "show", plain(heading.get_text(" "))))
    image = soup.select_one(".adx-top-banner img[src]")
    return [_row(FLUSHING, item["id"] + ":" + start.isoformat() + ":" + suffix, title, start, end,
                 _fth_venue(item, body, start), item["url"], body, (), image["src"] if image else None)
            for start, end, suffix, title in occurrences]


def _maker_place(basic):
    venue = basic.get("venue") or {}
    data = venue.get("address") or {}
    lines = data.get("localizedMultiLineAddressDisplay")
    if (not isinstance(lines, list) or len(lines) != 3 or data.get("country") != "US" or data.get("region") != "NY"
            or not str(venue.get("name", "")).lower().startswith("makerspace nyc")):
        raise ValueError("nyc_final_venue_unreviewed")
    if (plain(lines[0]).lower() not in {"140 58th st", "140 58th street"}
            or re.sub(r"[^a-z0-9]", "", plain(lines[1]).lower()) != "buildingbunit1c"
            or plain(lines[2]) != "Brooklyn, NY 11220"):
        raise ValueError("nyc_final_venue_unreviewed")
    try:
        lat, lng = float(data["latitude"]), float(data["longitude"])
    except (KeyError, ValueError, TypeError):
        raise ValueError("nyc_final_venue_unreviewed") from None
    if not math.isfinite(lat) or not math.isfinite(lng) or not (40.644 < lat < 40.647 and -74.026 < lng < -74.022):
        raise ValueError("nyc_final_venue_changed")
    return ("MakerSpace NYC — Brooklyn Army Terminal", "140 58th Street Building B Unit 1C, Brooklyn, NY 11220", "Brooklyn", lat, lng)


def _maker_series(body, first, last):
    if first.year != last.year or last - first > timedelta(days=180):
        raise ValueError("nyc_final_schedule_unresolved")
    pattern = (r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
               r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
               r"(\d{1,2})(?:st|nd|rd|th)?\s*[-–—:]\s*(\d{1,2}(?::\d{2})?\s*(?:[ap]m?)?\s*[-–—]\s*\d{1,2}(?::\d{2})?\s*[ap]m?)")
    result = []
    for m in re.finditer(pattern, plain(body), re.I):
        date = datetime.strptime(f"{m[1]} {m[2]} {first.year}", "%B %d %Y").date()
        start, end = _time_range(m[3], date)
        if start < first or end > last:
            raise ValueError("nyc_final_schedule_changed")
        result.append((start, end))
    if not result:
        raise ValueError("nyc_final_schedule_unresolved")
    return sorted(set(result))


def _maker_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        raise ValueError("nyc_final_detail_changed")
    try:
        context = json.loads(script.get_text())["props"]["pageProps"]["context"]
        basic = context["basicInfo"]
    except (KeyError, TypeError, ValueError):
        raise ValueError("nyc_final_detail_changed") from None
    if (basic.get("id") != item["id"] or basic.get("url") != item["url"]
            or (basic.get("organizer") or {}).get("id") != "18615337552"
            or basic.get("organizationId") != "61731221749"):
        raise ValueError("nyc_final_identity_changed")
    if (basic.get("status") not in {"live", "started"} or basic.get("isOnline")
            or basic.get("isProtected") or not basic.get("isListed")):
        return []
    start, end = basic.get("startDate") or {}, basic.get("endDate") or {}
    first, last = timestamp(start.get("local"), ZONE), timestamp(end.get("local"), ZONE)
    if (start.get("timezone") != ZONE or end.get("timezone") != ZONE or not first or not last or last < first
            or timestamp(start.get("utc")) != first or timestamp(end.get("utc")) != last
            or basic.get("hideStartDate") or basic.get("hideEndDate")):
        raise ValueError("nyc_final_schedule_changed")
    modules = (context.get("structuredContent") or {}).get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("nyc_final_description_missing")
    texts = [m["text"] for m in modules if isinstance(m, dict) and m.get("type") == "text" and isinstance(m.get("text"), str)]
    if not texts:
        raise ValueError("nyc_final_description_missing")
    if any((context.get("structuredContent") or {}).get("widgets", {}).values()):
        raise ValueError("nyc_final_description_shape_changed")
    # Include every native text module, plus the separate publisher overview.
    body = _body("<p>" + str(basic.get("summary") or "") + "</p>\n" + "\n".join(texts))
    occurrences = _maker_series(body, first, last) if basic.get("isParentEvent") else [(first, last)]
    occurrences = [(start, end) for start, end in occurrences if _within(start, end, now)]
    if not occurrences:
        return []
    venue = _maker_place(basic)
    labels = tuple(str(v) for v in (context.get("taxonomies") or {}).values() if isinstance(v, str) and v)
    images = (context.get("gallery") or {}).get("images") or []
    image = images[0].get("url") if images and isinstance(images[0], dict) else None
    return [_row(MAKER, item["id"] + (":" + start.date().isoformat() if basic.get("isParentEvent") else ""),
                 plain(basic.get("name")), start, end, venue, item["url"], body, labels, image)
            for start, end in occurrences]


HOLD_REASONS = {"nyc_final_description_missing", "nyc_final_description_limit", "nyc_final_description_shape_changed", "nyc_final_venue_unreviewed",
                "nyc_final_meeting_place_not_public", "nyc_final_schedule_unresolved", "event_not_current_or_public"}


def _digest(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reviewed_row_place(key, row):
    if key == TRANSIT:
        venues = (TRANSIT_VENUE, HOLIDAY_VENUE, GRAND_CENTRAL_VENUE, PENN_VENUE)
    elif key == FLUSHING:
        venues = (FTH_VENUE,) + tuple(v[2] for v in FTH_OFFSITE.values())
    elif key == BCM:
        venues = (BCM_VENUE,)
    elif key == BPL:
        return any((row.get("venue_name") == v[0] or str(row.get("venue_name", "")).startswith(v[0] + ","))
                   and (row.get("venue_address"), row.get("venue_city"), float(row["lat"]), float(row["lng"])) == v[1:]
                   for v in BPL_VENUES.values())
    else:
        return (row.get("venue_name") == "MakerSpace NYC — Brooklyn Army Terminal"
                and row.get("venue_address") == "140 58th Street Building B Unit 1C, Brooklyn, NY 11220"
                and row.get("venue_city") == "Brooklyn"
                and (float(row["lat"]), float(row["lng"])) in {
                    (40.6455001, -74.0239072), (40.6451278, -74.02420630000002)})
    return any((row.get("venue_name"), row.get("venue_address"), row.get("venue_city"),
                float(row["lat"]), float(row["lng"])) == venue for venue in venues)


def _checkpoint(key, value, now):
    if value is None:
        return None
    try:
        valid = (isinstance(value, dict) and type(value["version"]) is int and value["version"] == 1
            and value["source_key"] == key and type(value["cursor"]) is int and type(value["manifest_count"]) is int
            and 0 <= value["cursor"] <= value["manifest_count"] <= MAX_RECORDS
            and isinstance(value["queue"], list) and len(value["queue"]) == value["manifest_count"]
            and isinstance(value["events"], list) and len(value["events"]) <= MAX_RECORDS
            and isinstance(value["diagnostics"], list) and len(value["diagnostics"]) == value["cursor"]
            and type(value["manifest_verified"]) is bool
            and (not value["manifest_verified"] or value["cursor"] == value["manifest_count"])
            and isinstance(value["started_at"], str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value["started_at"])
            and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        started = timestamp(value["started_at"])
        if not valid or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        if not started <= now <= started + timedelta(hours=4):
            return None
        queue = value["queue"]
        if (any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                or not event_url(key, item.get("url")) for item in queue)
                or len({item["url"] for item in queue}) != len(queue) or value["manifest_hash"] != _digest(queue)):
            raise ValueError
        processed = {item["url"]: item for item in queue[:value["cursor"]]}
        decisions = {}
        for diagnostic in value["diagnostics"]:
            if (not isinstance(diagnostic, dict) or diagnostic.get("event_url") not in processed
                    or diagnostic["event_url"] in decisions or diagnostic.get("disposition") not in {"accepted", "held"}
                    or type(diagnostic.get("event_count")) is not int or diagnostic["event_count"] < 0
                    or (diagnostic["disposition"] == "held" and diagnostic.get("reason") not in HOLD_REASONS)):
                raise ValueError
            decisions[diagnostic["event_url"]] = diagnostic
        counts = {url: 0 for url in processed}
        for row in value["events"]:
            if not isinstance(row, dict):
                raise ValueError
            item = processed.get(row.get("event_url"))
            if (not item or not (row.get("id") == item["id"] or str(row.get("id", "")).startswith(item["id"] + ":"))
                    or not isinstance(row.get("description"), str) or not 0 < len(row["description"]) <= MAX_DESCRIPTION
                    or not row["description"].strip() or not row.get("venue_name") or not row.get("venue_city")
                    or not re.search(r", NY \d{5}$", str(row.get("venue_address", "")))
                    or not isinstance(row.get("title"), str) or not row["title"].strip()
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or not (40.5 <= float(row["lat"]) <= 40.95 and -74.3 <= float(row["lng"]) <= -73.69)
                    or not _reviewed_row_place(key, row)
                    or (row.get("image_url") is not None and photo_url(key, row["image_url"]) is None)):
                raise ValueError
            start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
            if not start or not start.tzinfo or (end and (not end.tzinfo or end < start)):
                raise ValueError
            if key == TRANSIT and (row["id"] != item["id"] or row["title"] != item["title"]
                    or start != timestamp(item["starts_at"]) or end != timestamp(item["ends_at"])):
                raise ValueError
            if key == BPL and (row["id"] != item["id"] or row["title"] != item["title"]
                    or start != timestamp(item["starts_at"]) or row["venue_name"] != item["venue_name"]):
                raise ValueError
            counts[item["url"]] += 1
        if any(counts[url] != decisions[url]["event_count"] or (counts[url] > 0) != (decisions[url]["disposition"] == "accepted") for url in processed):
            raise ValueError
        if len(_unique(value["events"])) != len(value["events"]):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError("nyc_final_checkpoint_invalid") from None
    return deepcopy(value)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    if key != BCM:
        raise ValueError("publisher_checkpoint_required")
    return _bcm(fetch, deadline_at or monotonic() + 35, now or datetime.now(timezone.utc))


def _manifest(key, fetch, deadline, started):
    queue = (_transit_manifest(fetch, deadline, started) if key == TRANSIT
             else _bpl_manifest(fetch, deadline, started) if key == BPL
             else _html_manifest(key, fetch, deadline))
    if len(queue) > MAX_RECORDS:
        raise ValueError("nyc_final_manifest_limit")
    return queue


def _new_state(key, queue, started):
    return dict(version=1, source_key=key, started_at=started.isoformat(),
                window_start=started.astimezone(ZoneInfo(ZONE)).date().isoformat(), manifest_hash=_digest(queue),
                manifest_count=len(queue), cursor=0, queue=queue, events=[], diagnostics=[], manifest_verified=not queue)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=2):
    key = _source(source)
    if key not in CHECKPOINT_KEYS:
        raise ValueError("unregistered_nyc_arts_final")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = _checkpoint(key, checkpoint, current)
    if state and state["manifest_verified"]:
        return dict(complete=True, events=_unique(deepcopy(state["events"])), checkpoint=state)
    deadline = deadline_at if deadline_at is not None else monotonic() + 35
    started = timestamp(state["started_at"]) if state else current
    if state is None:
        state = _new_state(key, _manifest(key, fetch, deadline, started), started)
    queue = state["queue"]
    prior = state["cursor"]
    maximum = min(3 if key in {MAKER, BPL} else 2, max(1, int(max_details)))
    detail = {TRANSIT: _transit_detail, FLUSHING: _flushing_detail, MAKER: _maker_detail, BPL: _bpl_detail}[key]
    while state["cursor"] < len(queue) and state["cursor"] - prior < maximum:
        # Transit and Flushing advertise a ten-second crawl delay. Leave room
        # for that transport wait, the request, and the durable checkpoint RPC.
        if monotonic() + 15 >= deadline:
            break
        item, reason = queue[state["cursor"]], "event_not_current_or_public"
        try:
            rows = _unique(detail(item, fetch(item["url"], "text/html"), timestamp(state["started_at"])))
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            rows, reason = [], str(exc)
        state["events"].extend(rows)
        state["diagnostics"].append(dict(event_url=item["url"], disposition="accepted" if rows else "held",
                                          event_count=len(rows), reason=None if rows else reason))
        state["cursor"] += 1
    # A full slow manifest can consume the first invocation. Persist cursor 0
    # and resume details directly; do not spend the same crawl delay reloading
    # the listing on every invocation. Before any publication, reload the full
    # manifest and discard all hydrated rows if identity/schedule facts changed.
    if state["cursor"] == len(queue) and not state["manifest_verified"] and monotonic() + 15 < deadline:
        latest = _manifest(key, fetch, deadline, started)
        if _digest(latest) != state["manifest_hash"]:
            state = _new_state(key, latest, started)
        else:
            state["manifest_verified"] = True
    if len(state["events"]) > MAX_RECORDS or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("nyc_final_checkpoint_size_limit")
    complete = state["manifest_verified"]
    return dict(complete=complete, events=_unique(deepcopy(state["events"])) if complete else [], checkpoint=state)


ERROR_CODES = {"unregistered_nyc_arts_final", "publisher_checkpoint_required", "collection_deadline",
    "nyc_final_identity_changed", "nyc_final_conflicting_occurrence", "nyc_final_record_limit",
    "nyc_final_ics_shape_changed", "nyc_final_ics_horizon_incomplete", "nyc_final_payload_changed",
    "nyc_final_schedule_changed", "nyc_final_pagination_limit", "nyc_final_listing_changed",
    "nyc_final_manifest_limit", "nyc_final_detail_changed", "nyc_final_venue_changed",
    "nyc_final_checkpoint_invalid", "nyc_final_checkpoint_size_limit", *HOLD_REASONS}
ERROR_CODES.add("nyc_final_bpl_scope_changed")
