"""Nine New York venue calendars, using public HTML and full native narratives.

Squarespace and Google export endpoints are deliberately not fetched: the
publishers disallow those routes. Native Squarespace body layouts are complete;
listing excerpts require the linked detail. Shopify's dated product variants
are read as inert JSON from its public product HTML, never as booking actions.
All HTTP is supplied by the existing guarded publisher transport. Detail work
uses its complete-only durable checkpoint protocol.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
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
CHILOS = "chilos_brooklyn_ny"
FOREVER = "forever_brewing_brooklyn_ny"
FIFTH = "fifth_hammer_queens_ny"
WONDER = "wonderville_brooklyn_ny"
STARR = "starr_bar_brooklyn_ny"
SKINNY = "skinny_dennis_brooklyn_ny"
KILLS = "kills_boro_staten_island_ny"
SAKE = "sake_studies_brooklyn_ny"
TWENTY = "twenty_sided_brooklyn_ny"
SOURCES = {
    CHILOS: ("https://www.chilosbk.com/eventscalendar", "html", "html"),
    FOREVER: ("https://www.foreverbrewing.com/events-calendar", "html", "html"),
    FIFTH: ("https://www.fifthhammerbrewing.com/fifth-hammer-calendar", "html", "html"),
    WONDER: ("https://www.wonderville.nyc/events", "html", "html"),
    STARR: ("https://www.starrbar.com/events", "html", "html"),
    SKINNY: ("https://skinnydennisbrooklyn.com/calendar", "html", "html"),
    KILLS: ("https://killsboro.com/events", "html", "html"),
    SAKE: ("https://www.sakestudiescenter.com/calendar", "html", "html"),
    TWENTY: ("https://twentysidedstore.com/collections/events", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(profile[0]).hostname,) for key, profile in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
SQUARE = {CHILOS, FOREVER, FIFTH, WONDER, STARR, SKINNY}
VENUES = {
    CHILOS: ("Chilo’s", "323 Franklin Avenue, Brooklyn, NY 11238", "Brooklyn"),
    FOREVER: ("Forever Brewing", "574 President Street, Brooklyn, NY 11215", "Brooklyn"),
    FIFTH: ("Fifth Hammer Brewing", "10-28 46th Avenue, Long Island City, NY 11101", "Long Island City"),
    WONDER: ("Wonderville", "1186 Broadway, Brooklyn, NY 11221", "Brooklyn"),
    STARR: ("Starr Bar", "214 Starr Street, Brooklyn, NY 11237", "Brooklyn"),
    SKINNY: ("Skinny Dennis", "152 Metropolitan Avenue, Brooklyn, NY 11249", "Brooklyn"),
    KILLS: ("Kills Boro Brewing Co.", "814 Richmond Terrace, Staten Island, NY 10301", "Staten Island"),
    SAKE: ("Sake Studies Center at Brooklyn Kura", "34 34th Street Industry City Building 6, Brooklyn, NY 11232", "Brooklyn"),
    TWENTY: ("Twenty Sided Store", "280 Grand Street, Brooklyn, NY 11211", "Brooklyn"),
}
# Official publisher addresses and exact street/borough/ZIP matches in NYC
# Planning's Property Address Directory, reviewed 2026-11-14. See the evidence
# file. Skinny Dennis uses the exact 152 result from a second search, never
# the initial wrong house number. Kills Boro supplies its own matching geo.
POINTS = {
    CHILOS: (40.688369, -73.956904), FOREVER: (40.676815, -73.984152),
    FIFTH: (40.746434, -73.951562), WONDER: (40.692404, -73.927613),
    STARR: (40.704982, -73.922909), KILLS: (40.644642, -74.0994638),
    SAKE: (40.657125, -74.006418), TWENTY: (40.713011, -73.957949),
    SKINNY: (40.715874, -73.962182),
}
SITES = {
    CHILOS: "5eb0e8194ae22907547016f0", FOREVER: "69ea9988a7a8477623dbed11",
    FIFTH: "5d852ede68787e0988342d29", WONDER: "5ca40c7b40978c0001458f5d",
    STARR: "62671664c8a31c211e051cf3", SKINNY: "5d71a6398ad44900015c5e96",
}
STREET_RE = {
    CHILOS: r"323\s+Franklin\s+Ave(?:nue)?", FOREVER: r"574\s+President\s+St(?:reet)?",
    FIFTH: r"10-28\s+46(?:th)?\s+Ave(?:nue)?", WONDER: r"1186\s+Broadway",
    STARR: r"214\s+Starr\s+St(?:reet)?", SKINNY: r"152\s+Metropolitan\s+Ave(?:nue)?",
}
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|private (?:event|party)|holiday hours)\b", re.I)
MAX_EVENTS = 200
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900_000
MAX_DETAILS_PER_CHUNK = 6
MIN_DETAIL_SECONDS = 12
ERROR_CODES = {
    "unregistered_new_york_nightlife_source", "new_york_nightlife_calendar_changed",
    "new_york_nightlife_event_identity", "new_york_nightlife_schedule_conflict",
    "new_york_nightlife_description_missing", "new_york_nightlife_description_limit",
    "new_york_nightlife_venue_unresolved", "new_york_nightlife_record_limit",
    "new_york_nightlife_checkpoint_invalid", "new_york_nightlife_checkpoint_size_limit",
    "new_york_nightlife_checkpoint_required", "new_york_nightlife_product_changed",
    "new_york_nightlife_detail_changed", "collection_deadline",
}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_new_york_nightlife_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.query or p.fragment
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I) or ".." in p.path.split("/")):
            return False
        if key == KILLS:
            return value == SOURCES[key][0]
        if key == SAKE:
            return bool(re.fullmatch(r"/(?:classes/[a-z0-9-]+|brewery-tour)(?:\.html)?", p.path))
        if key == TWENTY:
            return bool(re.fullmatch(r"/products/[a-z0-9-]+", p.path))
        prefix = urlsplit(SOURCES[key][0]).path
        return bool(re.fullmatch(re.escape(prefix) + r"/[a-zA-Z0-9/-]+", p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
                or p.fragment or ".." in p.path.split("/") or not re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)):
            return None
        if key in SQUARE:
            site = SITES.get(key)
            if (p.netloc == "images.squarespace-cdn.com" and site
                    and p.path.startswith("/content/v1/" + site + "/")
                    and set(parse_qs(p.query)) <= {"format"}):
                return value
        elif key == KILLS and p.netloc == "killsboro.com" and p.path.startswith("/images/") and not p.query:
            return value
        elif key == SAKE and p.netloc == "www.sakestudiescenter.com" and p.path.startswith("/assets/img/") and not p.query:
            return value
        elif key == TWENTY and p.netloc == "twentysidedstore.com" and p.path.startswith("/cdn/shop/files/") and set(parse_qs(p.query)) <= {"v", "width"}:
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    if key in VENUES and (venue, address) == VENUES[key][:2]:
        return POINTS.get(key)
    return None


def _text(value):
    if not isinstance(value, str) or not value.strip() or not re.search(r"[A-Za-z]", value):
        raise ValueError("new_york_nightlife_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("new_york_nightlife_description_limit")
    return value


def _narrative(value):
    # Ask the shared cleaner for one more character than the allowed size;
    # over-limit prose is withheld, never silently clipped to the limit.
    return _text(description(str(value or ""), limit=MAX_DESCRIPTION + 1))


def _clock(day, value):
    value = re.sub(r"\s+", "", value).upper()
    if re.fullmatch(r"\d{1,2}(?::\d{2})?[AP]", value):
        value += "M"
    fmt = "%H:%M" if re.fullmatch(r"\d{1,2}:\d{2}", value) else "%I:%M%p" if ":" in value else "%I%p"
    return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)


def _square_clock(node, suffix):
    times = node.select(".event-time-localized-" + suffix + ",.event-time-12hr-" + suffix)
    if not times:
        # Overnight Squarespace cards explicitly print two dated clocks and
        # omit start/end class suffixes. Preserve both calendar dates.
        clocks = node.select("time.event-time-localized,time.event-time-12hr")
        if len(clocks) != 2:
            raise ValueError("new_york_nightlife_schedule_conflict")
        times = [clocks[0 if suffix == "start" else 1]]
    values = {_clock(date.fromisoformat(x.get("datetime", "")), x.get_text()) for x in times}
    if len(values) != 1:
        raise ValueError("new_york_nightlife_schedule_conflict")
    return values.pop()


def _within(start, end, now):
    window_start = calendar_anchor(now)
    return start < window_start + timedelta(days=60) and (end or start + timedelta(hours=3)) > window_start


def _publisher_location(node):
    """Return only location text carried by this event card or detail."""
    locations = node.select(".eventlist-meta-address,.eventitem-meta-address")
    supplied_name = plain(locations[0].get_text(" ")).removesuffix("(map)").strip() if locations else ""
    facts = {"venue_name": supplied_name} if supplied_name else {}
    queries = []
    for link in node.select('a[href]'):
        parsed = urlsplit(link["href"])
        if parsed.hostname in {"maps.google.com", "www.google.com"}:
            queries.extend(parse_qs(parsed.query).get("q", []))
    if queries:
        if len(set(queries)) != 1:
            raise ValueError("new_york_nightlife_venue_unresolved")
        facts["venue_address"] = plain(queries[0])
    return facts


def _attach_content(row, item, body, *, native_options=None):
    if row is None:
        return None
    place = item.get("content_venue") if isinstance(item.get("content_venue"), dict) else {}
    facts = {
        "title": item["title"],
        "description": body,
        "is_all_day": False,
        "starts_at_utc": timestamp(item["start"]).astimezone(timezone.utc).isoformat(),
        "ends_at_utc": (timestamp(item.get("end")).astimezone(timezone.utc).isoformat()
                         if timestamp(item.get("end")) else None),
        "event_url": item["url"],
        "venue_name": place.get("venue_name"),
        "venue_address": place.get("venue_address"),
        "venue_city": place.get("venue_city"),
        "venue_region": place.get("venue_region"),
        "venue_postal_code": place.get("venue_postal_code"),
        "venue_country": place.get("venue_country"),
        "source_image_url": photo_url(item.get("source_key"), item.get("image")),
        "native_options": native_options,
    }
    facts = {key: value for key, value in facts.items()
             if value is not None and value != "" and value != {}}
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
    expected = {
        "title": row.get("title"),
        "description": row.get("description"),
        "is_all_day": False,
        "starts_at_utc": timestamp(row.get("starts_at")).astimezone(timezone.utc).isoformat(),
        "event_url": row.get("event_url"),
    }
    end = timestamp(row.get("ends_at"))
    if end is not None:
        expected["ends_at_utc"] = end.astimezone(timezone.utc).isoformat()
    return all(facts.get(key) == value for key, value in expected.items())


def _location(key, node):
    """Resolve only this venue; retain a newly explicit complete off-site street."""
    locations = node.select(".eventlist-meta-address,.eventitem-meta-address")
    supplied_name = plain(locations[0].get_text(" ")).removesuffix("(map)").strip() if locations else ""
    queries = []
    for a in node.select('a[href]'):
        p = urlsplit(a["href"])
        if p.hostname in {"maps.google.com", "www.google.com"}:
            queries.extend(parse_qs(p.query).get("q", []))
    for query in queries:
        if re.match(STREET_RE[key] + r"\b", query, re.I):
            return VENUES[key]
        match = re.fullmatch(r"(\d[\w -]*\s+.+?)\s+(Brooklyn|Queens|Bronx|Staten Island|New York|Long Island City),\s*(?:NY|New York),?\s*(\d{5})(?:\s+(?:USA|United States))?", query, re.I)
        if match:
            street, city, zipcode = match.groups()
            return supplied_name or street, f"{street}, {city}, NY {zipcode}", city
        if query.strip():
            raise ValueError("new_york_nightlife_venue_unresolved")
    expected = {plain(VENUES[key][0]).casefold()}
    if key == CHILOS:
        expected.update({"chilo's", "chilo’s"})
    if supplied_name and supplied_name.casefold() not in expected:
        raise ValueError("new_york_nightlife_venue_unresolved")
    # The reviewed empty-location sites are single-venue calendars. Their
    # publisher home/contact/footer supplies the precise street above.
    if key not in {STARR, SKINNY} and not supplied_name:
        raise ValueError("new_york_nightlife_venue_unresolved")
    return VENUES[key]


def _identity(key, url, start, variant=""):
    return "nyc:" + sha256(f"{key}:{url}:{start}:{variant}".encode()).hexdigest()


def _row(key, item, body, *, venue=None, variant="", image=None):
    start, end = timestamp(item["start"]), timestamp(item.get("end"))
    if not event_url(key, item["url"]) or not item.get("title") or len(item["title"]) > 180 or end and end <= start:
        raise ValueError("new_york_nightlife_event_identity")
    place = tuple(venue or item.get("venue") or VENUES[key])
    point = reviewed_venue_location(key, place[0], place[1]) or (None, None)
    identity = _identity(key, item["url"], start.isoformat(), item["title"] if key == KILLS else variant)
    row = record(item["title"], start.isoformat(), end.isoformat() if end else None,
                 *place, item["url"], identity, lat=point[0], lng=point[1], tz=ZONE,
                 retain_until_end=True)
    if row is not None:
        row.update(description=_text(body), timezone=ZONE, attendance_mode="in_person",
                   location_provenance=("reviewed_publisher_venue_geo" if key == KILLS and point[0] is not None
                                        else "reviewed_nyc_pad_address_point" if point[0] is not None
                                        else "reviewed_venue_street_address_pending_geocode"))
        # The shared historical address recognizer rejects NYC numeric street
        # names and hyphenated Queens house numbers. Restore only the exact
        # reviewed name/address point above, never a source/search center.
        if point[0] is not None:
            row.update(lat=point[0], lng=point[1])
            if row.get("reason") == "missing_verified_venue_geo":
                row["reason"] = None
        if candidate := photo_url(key, image or item.get("image")):
            row["image_url"] = candidate
    content_item = dict(item, source_key=key)
    if image is not None:
        content_item["image"] = image
    return _attach_content(
        row,
        content_item,
        _text(body),
        native_options=({"variant_id": variant, "variant_label": item.get("variant_label"),
                         "variant_price": item.get("variant_price")}
                        if variant else None),
    )


def _square_manifest(key, soup, now):
    cards = soup.select("article.eventlist-event--upcoming")
    if not soup.select_one(".eventlist"):
        if key == FIFTH:
            return _month_manifest(key, soup, now)
        raise ValueError("new_york_nightlife_calendar_changed")
    queue = []
    for card in cards:
        link = card.select_one("a.eventlist-title-link[href]")
        if link is None:
            raise ValueError("new_york_nightlife_event_identity")
        title = plain(link.get_text(" "))
        if NONPUBLIC.search(title):
            continue
        start, end = _square_clock(card, "start"), _square_clock(card, "end")
        if end <= start:
            raise ValueError("new_york_nightlife_schedule_conflict")
        if not _within(start, end, now):
            continue
        url = urljoin(SOURCES[key][0], link["href"])
        if not event_url(key, url):
            raise ValueError("new_york_nightlife_event_identity")
        item = dict(type="square", url=url, title=title, start=start.isoformat(), end=end.isoformat())
        try:
            item["venue"] = list(_location(key, card))
            item["content_venue"] = _publisher_location(card)
            layouts = card.select(".eventlist-description .sqs-layout")
            if len(layouts) == 1 and not card.select_one(".eventlist-excerpt"):
                item["body"] = _narrative(layouts[0])
        except ValueError as exc:
            item["held"] = str(exc)
        image = card.select_one("img[data-src],img[src]")
        if image:
            item["image"] = image.get("data-src") or image.get("src")
        queue.append(item)
    return queue


def _month_manifest(key, soup, now):
    """Squarespace's normal HTML accessible month list, without query exports."""
    queue = []
    for link in soup.select("h1 > a[href]"):
        url = urljoin(SOURCES[key][0], link["href"])
        if not event_url(key, url):
            continue
        card = link.find_parent("li")
        if card is None:
            raise ValueError("new_york_nightlife_calendar_changed")
        title = plain(link.get_text(" "))
        if NONPUBLIC.search(title):
            continue
        clocks = [plain(x.get_text(" ")) for x in card.find_all("div", recursive=False)]
        matches = [re.fullmatch(r"([A-Za-z]+, [A-Za-z]+ \d{1,2}, 20\d{2}), (\d{1,2}:\d{2}\s*[AP]M)\s*[–—-]\s*(\d{1,2}:\d{2}\s*[AP]M)", x) for x in clocks]
        matches = [m for m in matches if m]
        if len(matches) != 1:
            raise ValueError("new_york_nightlife_schedule_conflict")
        m = matches[0]
        day = datetime.strptime(m[1], "%A, %B %d, %Y").date()
        if not m[1].startswith(day.strftime("%A")):
            raise ValueError("new_york_nightlife_schedule_conflict")
        start, end = _clock(day, m[2]), _clock(day, m[3])
        if end <= start:
            end += timedelta(days=1)
        if not _within(start, end, now):
            continue
        item = dict(type="square", url=url, title=title, start=start.isoformat(), end=end.isoformat())
        try:
            item["venue"] = list(_location(key, card))
            item["content_venue"] = _publisher_location(card)
        except ValueError as exc:
            item["held"] = str(exc)
        image = card.select_one("img[data-src],img[src]")
        if image:
            item["image"] = image.get("data-src") or image.get("src")
        queue.append(item)
    if not queue and not soup.select_one(".sqs-events-collection-list"):
        # An empty month must still have a recognizable calendar container.
        if not re.search(r"event-calendar|events-collection", str(soup)):
            raise ValueError("new_york_nightlife_calendar_changed")
    return queue


def _jsonld(soup):
    def walk(value):
        if isinstance(value, list):
            for entry in value:
                yield from walk(entry)
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


def _json_manifest(key, soup, now):
    events = list(_jsonld(soup))
    if not events:
        raise ValueError("new_york_nightlife_calendar_changed")
    queue = []
    for entry in events:
        title = plain(entry.get("name"))
        if NONPUBLIC.search(title) or str(entry.get("eventStatus", "")).endswith(("EventCancelled", "EventPostponed")):
            continue
        start, end = timestamp(entry.get("startDate")), timestamp(entry.get("endDate"))
        if start is None or start.tzinfo is None or end and (end.tzinfo is None or end <= start):
            raise ValueError("new_york_nightlife_schedule_conflict")
        if not _within(start, end, now):
            continue
        location = entry.get("location") or {}
        address = location.get("address") or {}
        expected_street = "814 Richmond Terrace" if key == KILLS else "34 34th Street, Industry City Building 6"
        if not (isinstance(address, dict) and address.get("streetAddress") == expected_street
                and address.get("addressLocality") == VENUES[key][2]
                and address.get("addressRegion") == "NY"
                and str(address.get("postalCode")) == VENUES[key][1][-5:]):
            raise ValueError("new_york_nightlife_venue_unresolved")
        url = SOURCES[KILLS][0] if key == KILLS else str(entry.get("url", "")).removesuffix(".html")
        if not event_url(key, url):
            raise ValueError("new_york_nightlife_event_identity")
        item = dict(type="jsonld", url=url, title=title, start=start.isoformat(), end=end.isoformat() if end else None,
                    content_venue={
                        "venue_name": plain(location.get("name")),
                        "venue_address": plain(address.get("streetAddress")),
                        "venue_city": plain(address.get("addressLocality")),
                        "venue_region": plain(address.get("addressRegion")),
                        "venue_postal_code": plain(str(address.get("postalCode") or "")),
                        "venue_country": plain(address.get("addressCountry")),
                    })
        if key == KILLS:
            body = _narrative(entry.get("description"))
            # The structured prose is the complete matching visible event
            # paragraph, not a metadata excerpt hiding a longer description.
            visible = " ".join(soup.get_text(" ", strip=True).split())
            if " ".join(body.split()) not in visible:
                raise ValueError("new_york_nightlife_detail_changed")
            item["body"] = body
        image = entry.get("image")
        item["image"] = image[0] if isinstance(image, list) and image else image
        queue.append(item)
    if key == SAKE:
        grouped = {}
        for item in queue:
            grouped.setdefault(item["url"], []).append(item)
        return [dict(type="sake", url=url, occurrences=items) for url, items in sorted(grouped.items())]
    return queue


def _product_manifest(soup):
    products = {}
    for link in soup.select('a[href]'):
        path = urlsplit(link["href"]).path
        match = re.fullmatch(r"/collections/events/products/([a-z0-9-]+)", path)
        if match and not match[1].startswith("booking-private"):
            url = "https://twentysidedstore.com/products/" + match[1]
            products[url] = dict(type="product", url=url)
    if not products or len(products) > 30:
        raise ValueError("new_york_nightlife_calendar_changed")
    return sorted(products.values(), key=lambda x: x["url"])


def _manifest(key, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    queue = (_square_manifest(key, soup, now) if key in SQUARE else
             _product_manifest(soup) if key == TWENTY else _json_manifest(key, soup, now))
    unique = {}
    for item in queue:
        identity = (item["url"], item.get("start", ""), item.get("title", ""))
        if identity in unique and unique[identity] != item:
            raise ValueError("new_york_nightlife_event_identity")
        unique[identity] = item
    if len(unique) > MAX_EVENTS:
        raise ValueError("new_york_nightlife_record_limit")
    return sorted(unique.values(), key=lambda x: (x.get("start", ""), x["url"]))


def _square_detail(key, item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    heading = soup.select_one("h1.eventitem-title")
    canonical = soup.select_one('link[rel="canonical"]')
    if (heading is None or plain(heading.get_text(" ")) != item["title"]
            or canonical is None or canonical.get("href") != item["url"]):
        raise ValueError("new_york_nightlife_detail_changed")
    if (_square_clock(soup, "start"), _square_clock(soup, "end")) != (timestamp(item["start"]), timestamp(item["end"])):
        raise ValueError("new_york_nightlife_schedule_conflict")
    venue = _location(key, soup)
    if tuple(item.get("venue", ())) != tuple(venue):
        raise ValueError("new_york_nightlife_venue_unresolved")
    layouts = soup.select(".eventitem-column-content .sqs-layout")
    if len(layouts) != 1:
        raise ValueError("new_york_nightlife_detail_changed")
    observed = dict(item, content_venue=_publisher_location(soup))
    row = _row(key, observed, _narrative(layouts[0]), venue=venue)
    return [row] if row else []


def _sake_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    bodies = soup.select(".detail-body")
    canonical = soup.select_one('link[rel="canonical"]')
    if len(bodies) != 1 or canonical is None or canonical.get("href", "").removesuffix(".html") != item["url"]:
        raise ValueError("new_york_nightlife_detail_changed")
    body = _narrative(bodies[0])
    text = plain(soup.get_text(" "))
    if not re.search(r"34\s+34th Street", text) or "Brooklyn" not in text:
        raise ValueError("new_york_nightlife_venue_unresolved")
    return [row for occurrence in item["occurrences"] if (row := _row(SAKE, occurrence, body))]


def _product_detail(item, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    scripts = soup.select('script[type="application/json"][data-section-type="static-product"]')
    canonical = soup.select_one('link[rel="canonical"]')
    if len(scripts) != 1 or canonical is None or canonical.get("href") != item["url"]:
        raise ValueError("new_york_nightlife_product_changed")
    data = json.loads(scripts[0].string or scripts[0].get_text())
    product = data.get("product")
    if (not isinstance(product, dict) or product.get("vendor") != "Event" or product.get("type") != "EVENTS"
            or item["url"] != "https://twentysidedstore.com/products/" + str(product.get("handle"))
            or not isinstance(product.get("description"), str)
            or not isinstance(product.get("variants"), list) or len(product["variants"]) > 100
            or any(not isinstance(v, dict) or type(v.get("id")) is not int for v in product["variants"])):
        raise ValueError("new_york_nightlife_product_changed")
    # This product HTML includes the official store/event street in its footer.
    if not re.search(r"280\s+Grand\s+St(?:reet)?\b", plain(soup.get_text(" ")), re.I):
        raise ValueError("new_york_nightlife_venue_unresolved")
    title = plain(product.get("title"))
    if NONPUBLIC.search(title) or title.startswith("Private Party"):
        return []
    body = _narrative(product.get("description"))
    visible = soup.select_one(".product-description")
    if visible is None or _narrative(visible) != body:
        raise ValueError("new_york_nightlife_detail_changed")
    rows = []
    for variant in product["variants"]:
        label = plain(variant.get("title"))
        # Only publisher-dated individual sessions; never infer dates from the
        # recurring product title, a monthly package, or a private booking.
        match = re.search(r"\b(MON|TUE|WED|THU|FRI|SAT|SUN)\s+(\d{1,2}/\d{1,2}/20\d{2})\s*@\s*(\d{1,2}(?::\d{2})?\s*[ap]m?)\s*[-–]\s*(\d{1,2}(?::\d{2})?\s*[ap]m?)\b", label, re.I)
        if not match or variant.get("available") is not True:
            continue
        day = datetime.strptime(match[2], "%m/%d/%Y").date()
        if day.strftime("%a").upper() != match[1].upper():
            raise ValueError("new_york_nightlife_schedule_conflict")
        start, end = _clock(day, match[3]), _clock(day, match[4])
        if end <= start:
            end += timedelta(days=1)
        if not _within(start, end, now):
            continue
        spec = dict(url=item["url"], title=title, start=start.isoformat(), end=end.isoformat(),
                    variant_label=label, variant_price=variant.get("price"))
        image = product.get("featured_image")
        if isinstance(image, str):
            image = urljoin("https://twentysidedstore.com", image)
        row = _row(TWENTY, spec, body, variant=str(variant.get("id")), image=image)
        if row:
            rows.append(row)
    return rows


def _validate_checkpoint(value, key, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or value.get("source_key") != key or type(value.get("cursor")) is not int
            or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_EVENTS
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or not isinstance(value.get("events"), list) or len(value["events"]) > MAX_EVENTS
            or not isinstance(value.get("diagnostics"), list)
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("manifest_hash", "")))
            or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
        raise ValueError("new_york_nightlife_checkpoint_invalid")
    try:
        started = timestamp(value["started_at"])
        if started.tzinfo is None or value["window_start"] != calendar_anchor(started).astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("new_york_nightlife_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=24):
        return None
    for item in value["queue"]:
        if not isinstance(item, dict) or not event_url(key, item.get("url")):
            raise ValueError("new_york_nightlife_checkpoint_invalid")
    prefix = value["queue"][:value["cursor"]]
    urls = {item["url"] for item in prefix}
    bindings = {}
    if key != TWENTY:
        for item in prefix:
            for occurrence in item.get("occurrences", [item]):
                if not isinstance(occurrence, dict):
                    raise ValueError("new_york_nightlife_checkpoint_invalid")
                try:
                    start = timestamp(occurrence["start"])
                    identity = _identity(key, occurrence["url"], start.isoformat(),
                                         occurrence["title"] if key == KILLS else "")
                except (KeyError, TypeError, ValueError, AttributeError):
                    raise ValueError("new_york_nightlife_checkpoint_invalid") from None
                bindings[identity] = occurrence
    seen, covered = set(), set()
    for row in value["events"]:
        if (not isinstance(row, dict) or row.get("event_url") not in urls
                or not re.fullmatch(r"nyc:[a-f0-9]{64}", str(row.get("id", "")))
                or row["id"] in seen or not isinstance(row.get("title"), str)
                or not 1 <= len(row["title"]) <= 180 or NONPUBLIC.search(row["title"])
                or not isinstance(row.get("description"), str) or not 1 <= len(row["description"]) <= MAX_DESCRIPTION
                or not row.get("venue_address") or not row.get("venue_name")
                or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                or not _content_envelope_valid(row)
                or row.get("image_url") is not None and photo_url(key, row["image_url"]) is None):
            raise ValueError("new_york_nightlife_checkpoint_invalid")
        try:
            start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
            if (start is None or start.tzinfo is None or end and (end.tzinfo is None or end <= start)
                    or not _within(start, end, started) or _text(row["description"]) != row["description"]):
                raise ValueError
            place = (row["venue_name"], row["venue_address"], row.get("venue_city"))
            if key != TWENTY:
                native = bindings.get(row["id"])
                if (native is None or row["event_url"] != native["url"] or row["title"] != native["title"]
                        or start != timestamp(native["start"]) or end != timestamp(native.get("end"))
                        or place != tuple(native.get("venue") or VENUES[key])
                        or "body" in native and row["description"] != native["body"]):
                    raise ValueError
            elif place != VENUES[key]:
                raise ValueError
            point = reviewed_venue_location(key, place[0], place[1]) or (None, None)
            if (row.get("lat"), row.get("lng")) != point:
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("new_york_nightlife_checkpoint_invalid") from None
        seen.add(row["id"])
        covered.add(row["event_url"])
    if len(value["diagnostics"]) > value["cursor"]:
        raise ValueError("new_york_nightlife_checkpoint_invalid")
    for item in value["diagnostics"]:
        if (not isinstance(item, dict) or item.get("event_url") not in urls
                or item.get("disposition") != "held" or item.get("reason") not in {
                    "no_available_future_occurrence", "new_york_nightlife_description_missing",
                    "new_york_nightlife_description_limit", "new_york_nightlife_venue_unresolved"}):
            raise ValueError("new_york_nightlife_checkpoint_invalid")
        covered.add(item["event_url"])
    if covered != urls:
        raise ValueError("new_york_nightlife_checkpoint_invalid")
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("new_york_nightlife_checkpoint_invalid")
    state = _validate_checkpoint(checkpoint, key, current)
    legacy_prefix = bool(state and state["events"] and
                         any("collector_event_content_v1" not in row for row in state["events"]))
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(SOURCES[key][0], "text/html")
    queue = _manifest(key, payload, anchor)
    digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest or state["queue"] != queue:
        queue = _manifest(key, payload, current)
        digest = sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
                     window_start=calendar_anchor(current).astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=digest, manifest_count=len(queue), cursor=0,
                     queue=queue, events=[], diagnostics=[])
    prior, fetched = state["cursor"], 0
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state["cursor"] < len(queue):
        item = queue[state["cursor"]]
        needs_detail = "body" not in item and "held" not in item
        if needs_detail and (fetched >= limit or deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at):
            break
        try:
            if item.get("held"):
                raise ValueError(item["held"])
            if not needs_detail:
                row = _row(key, item, item["body"])
                rows = [row] if row else []
            else:
                detail = fetch(item["url"], "text/html")
                fetched += 1
                rows = (_product_detail(item, detail, current) if key == TWENTY else
                        _sake_detail(item, detail) if key == SAKE else _square_detail(key, item, detail))
            if legacy_prefix:
                for row in rows:
                    row.pop("collector_event_content_v1", None)
            state["events"].extend(rows)
            if not rows:
                state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason="no_available_future_occurrence"))
        except ValueError as exc:
            if str(exc) not in {"new_york_nightlife_description_missing", "new_york_nightlife_description_limit", "new_york_nightlife_venue_unresolved"}:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=str(exc)))
        state["cursor"] += 1
        if len(state["events"]) > MAX_EVENTS:
            raise ValueError("new_york_nightlife_record_limit")
    if state["cursor"] == prior < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_nightlife_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    rows = sorted(state["events"], key=lambda x: (x["starts_at"], x["id"])) if complete else []
    unique = {}
    for row in rows:
        identity = (row["id"], row["starts_at"])
        if identity in unique and unique[identity] != row:
            raise ValueError("new_york_nightlife_event_identity")
        unique[identity] = row
    return dict(complete=complete, events=deepcopy(list(unique.values())), checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("new_york_nightlife_checkpoint_required")
    return result["events"]
