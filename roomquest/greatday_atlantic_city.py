"""Great Day Atlantic City: complete detail prose and bounded upcoming pages.

Only the upcoming Webflow collection is followed.  Every accepted occurrence
uses its detail page's date and clock; list-card summaries are never descriptions.
Partial snapshots remain in the durable checkpoint until all details finish.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import plain, record, timestamp


KEY = "greatday_atlantic_city_nj"
URL = "https://www.greatdayatlanticcity.com/events"
ZONE = "America/New_York"
SOURCES = {KEY: (URL, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.greatdayatlanticcity.com",)}
MAX_PAGES = 8
MAX_DETAILS = 100
MAX_DETAILS_PER_CHUNK = 6
MAX_CHECKPOINT_BYTES = 900_000
MIN_DETAIL_SECONDS = 18
CONTRACT = 1

# Current event detail pages explicitly identify these buildings and streets.
# Directions and street suffixes are normalized, retaining every street number.
# Uptown is the one reviewed intersection-to-building resolution; its local
# neighborhood partnership supplies 201 N Massachusetts Ave:
# https://acinlet.org/uptown-skatepark/
LOCATIONS = (
    (r"7\s+S(?:outh)?\.?\s+Ohio\s+Ave(?:nue)?", "AtlantiCare Medical Arts Pavilion", "7 S Ohio Avenue"),
    (r"123\s+S(?:outh)?\.?\s+Indiana\s+Ave(?:nue)?", "The Claridge Hotel", "123 South Indiana Avenue"),
    (r"1535\s+Bacharach\s+(?:Blvd|Boulevard)", "Atlantic Cape Community College — Charles D. Worthington Campus", "1535 Bacharach Boulevard"),
    (r"2200\s+Fairmount\s+Ave(?:nue)?", "Noyes Arts Garage of Stockton University", "2200 Fairmount Avenue"),
    (r"1000\s+Boardwalk", "Hard Rock Hotel & Casino Atlantic City", "1000 Boardwalk"),
    (r"35\s+S(?:outh)?\.?\s+(?:Dr\.?|Doctor)\s+Martin\s+Luther\s+King(?:\s+Jr\.?)?\s+(?:Blvd|Boulevard)", "Carnegie Center", "35 S Dr Martin Luther King Boulevard"),
    (r"201\s+N(?:orth)?\.?\s+Pennsylvania\s+Ave(?:nue)?", "New York Avenue School", "201 North Pennsylvania Avenue"),
    (r"167\s+S(?:outh)?\.?\s+Tennessee\s+Ave(?:nue)?", "C.R.O.P.S. Food Hub", "167 S Tennessee Avenue"),
    (r"250\s+N(?:orth)?\.?\s+New\s+York\s+Ave(?:nue)?", "Atlantic City PAL Building", "250 N New York Avenue"),
    (r"1\s+N(?:orth)?\.?\s+Tennessee\s+Ave(?:nue)?", "Atlantic City Free Public Library — Main Library", "1 North Tennessee Avenue"),
    (r"108\s+N(?:orth)?\.?\s+Pennsylvania\s+Ave(?:nue)?", "Sister Jean's Kitchen", "108 N Pennsylvania Avenue"),
    (r"201\s+N(?:orth)?\.?\s+Massachusetts\s+Ave(?:nue)?", "Uptown Skatepark", "201 N Massachusetts Avenue"),
    (r"1200\s+N(?:orth)?\.?\s+(?:Doctor|Dr\.?)\s+Martin\s+Luther\s+King(?:\s+Jr\.?)?\s+(?:Blvd|Boulevard)", "Pop Lloyd Stadium", "1200 N Doctor Martin Luther King Jr Boulevard"),
    (r"1709\s+Arctic\s+Ave(?:nue)?", "St. Augustine’s Episcopal Church", "1709 Arctic Avenue"),
    (r"3598\s+Captain\s+John\s+A\s+O[’']?\s*Donnell\s+(?:Pkwy|Parkway)", "O'Donnell Memorial Park", "3598 Captain John A O Donnell Pkwy"),
    (r"2253\s+Arctic\s+Ave(?:nue)?", "Ducktown Park", "2253 Arctic Avenue"),
    (r"1510\s+Adriatic\s+Ave(?:nue)?", "All Wars Memorial Building", "1510 Adriatic Avenue"),
    (r"3900\s+Ventnor\s+Ave(?:nue)?", "Spanish Community Center", "3900 Ventnor Avenue"),
    (r"1800\s+(?:Block\s+of\s+)?Marmora\s+Avenu(?:e)?", "1800 Block of Marmora Avenue", "1800 Marmora Avenue"),
)

# Exact official tourism and service-location metadata.  Pins
# are associated with the full resolved venue/street, never the coverage center.
# https://www.visitatlanticcity.com/event/ed-bassmaster/7545/
# https://www.visitatlanticcity.com/event/c-r-o-p-s-farmers-market/7561/
# https://www.visitatlanticcity.com/event/chelsea-holiday-tree-lighting/6595/
# https://www.visitatlanticcity.com/event/ducktown-park-tree-lighting/6466/
# PAL's own https://acpal.org/contact/ links its exact 250 N New York map;
# the map's building point is 39.3653551,-74.4321693.
# Sister Jean's own https://www.sisterjeanskitchen.org/ confirms 108 N
# Pennsylvania, and NJ211's current physical service record supplies the point:
# https://search.nj211.org/search/861ce7b3-ec45-5fe4-8e80-bc091265161b
# Spanish Community Center's Atlantic City service location (not Landisville):
# https://search.nj211.org/search/41c48b1e-4f9e-5c08-ad88-9b7bfd5deeb9
VENUE_POINTS = {
    ("The Claridge Hotel", "123 South Indiana Avenue, Atlantic City, NJ 08401"): (39.3575555, -74.4317609),
    ("C.R.O.P.S. Food Hub", "167 S Tennessee Avenue, Atlantic City, NJ 08401"): (39.3593597, -74.4260272),
    ("O'Donnell Memorial Park", "3598 Captain John A O Donnell Pkwy, Atlantic City, NJ 08401"): (39.3516824, -74.453553),
    ("Ducktown Park", "2253 Arctic Avenue, Atlantic City, NJ 08401"): (39.3593366, -74.4403665),
    ("Atlantic City PAL Building", "250 N New York Avenue, Atlantic City, NJ 08401"): (39.3653551, -74.4321693),
    ("Sister Jean's Kitchen", "108 N Pennsylvania Avenue, Atlantic City, NJ 08401"): (39.361843, -74.423196),
    ("Spanish Community Center", "3900 Ventnor Avenue, Atlantic City, NJ 08401"): (39.350256, -74.457095),
}

# The Nov 19 event's text and attached flyer pair New York Avenue School with
# 201 N Pennsylvania.  The district identifies that street as Pennsylvania Ave
# School (https://pas.acboe.org/), while New York Avenue School is at 411 N New
# York (https://nyas.acboe.org/).  No current relocation evidence resolves it.
# Hold only this reviewed occurrence; never replace its address with a guess.
REVIEWED_LOCATION_CONFLICTS = {
    ("south-jersey-gas-energy-assistance-event", "2026-11-19T14:00:00+00:00",
     "2026-11-19T18:00:00+00:00", "201 North Pennsylvania Avenue, Atlantic City, NJ 08401"),
}

# Only reviewed, exact occurrences already supplied by active primary feeds.
# New dates, changed clocks or different streets do not inherit suppression.
# ACFPL occurrence 7375ae11d100b95ff5084392f593d26cd275fb6805b1aebe636ea8530ffde207;
# city details https://www.acnj.gov/Calendar/ViewEvent/2077 and /2078.
PRIMARY_OCCURRENCES = {
    ("diy-holiday-craft-fair", "2026-11-21T18:00:00+00:00", "2026-11-21T21:00:00+00:00",
     "1 North Tennessee Avenue, Atlantic City, NJ 08401"),
    ("post-thanksgiving-turkey-dinner", "2026-11-28T17:00:00+00:00", "2026-11-28T19:00:00+00:00",
     "1709 Arctic Avenue, Atlantic City, NJ 08401"),
    ("shredding-event-third-ward", "2026-12-12T14:00:00+00:00", "2026-12-12T17:00:00+00:00",
     "1800 Marmora Avenue, Atlantic City, NJ 08401"),
}
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|private event|invitation[- ]only)\b", re.I)
CLOCK = r"(?:\b(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*[ap]\.?\s*m\.?|\bnoon\b|\bmidnight\b)"
CLOCK_RANGE = re.compile(r"(" + CLOCK + r")\s*(?:[-–—]|to|until|through)\s*(" + CLOCK + r")", re.I)
MONTHS = "January February March April May June July August September October November December".split()
MONTH_PATTERN = "|".join(month + "|" + month[:3] for month in MONTHS)
BODY_DATE = re.compile(r"\b(" + MONTH_PATTERN + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b", re.I)


def event_url(source_key, value):
    if source_key != KEY or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.netloc == "www.greatdayatlanticcity.com"
                and not parsed.query and not parsed.fragment
                and re.fullmatch(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*", parsed.path) is not None)
    except ValueError:
        return False


def _page_url(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.netloc == "www.greatdayatlanticcity.com"
                and parsed.path == "/events" and not parsed.fragment
                and (not parsed.query or re.fullmatch(r"[a-f0-9]{8}_page=[1-9][0-9]?", parsed.query)))
    except (ValueError, TypeError):
        return False


def _image(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    parsed = urlsplit(value)
    return value if (parsed.scheme == "https" and parsed.netloc == "cdn.prod.website-files.com"
                     and not parsed.query and not parsed.fragment
                     and re.fullmatch(r"/67527a6c8f757cda3e333e95/[A-Za-z0-9_%().&+,-]+\.(?:jpg|jpeg|png|webp)", parsed.path, re.I)) else None


def _text(node):
    return plain(node.get_text(" ", strip=True)) if node else ""


def _manifest(fetch, anchor, deadline_at):
    current, pages, result, pagination_key = URL, set(), {}, None
    while current:
        if current in pages or len(pages) >= MAX_PAGES or not _page_url(current):
            raise ValueError("greatday_pagination_invalid")
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError("collection_deadline")
        pages.add(current)
        soup = BeautifulSoup(fetch(current, "text/html"), "html.parser")
        sections = [section for section in soup.select("section")
                    if any(_text(h) == "All Upcoming Area Events" for h in section.select("h1,h2,h3"))]
        if len(sections) != 1:
            raise ValueError("greatday_upcoming_collection_changed")
        section = sections[0]
        cards = section.select(".home_event_item")
        if not cards and not section.select_one(".w-dyn-empty"):
            raise ValueError("greatday_upcoming_collection_changed")
        for card in cards:
            link, title = card.select_one("a.card-link[href]"), _text(card.select_one("h3"))
            fields = card.select(".home_event_item-content-top .card-detail-icon-text")
            if link is None or not title or not fields:
                raise ValueError("greatday_card_identity_changed")
            url = urljoin(URL, link["href"])
            if not event_url(KEY, url):
                raise ValueError("greatday_event_identity")
            try:
                day = datetime.strptime(_text(fields[0]), "%m/%d/%Y").date()
            except ValueError:
                raise ValueError("greatday_card_date_invalid") from None
            if day < anchor or day >= anchor + timedelta(days=61):
                continue
            poster = card.select_one(".event-image-wrap img[src]")
            item = {"title": title, "date": day.isoformat(),
                    "location": _text(fields[1]) if len(fields) > 1 else "",
                    "category": _text(card.select_one(".tag-red")),
                    "image": _image(poster.get("src")) if poster else None}
            if url in result and result[url] != item:
                raise ValueError("greatday_duplicate_identity")
            result[url] = item
        if len(result) > MAX_DETAILS:
            raise ValueError("greatday_record_limit")
        next_links = section.select("a.w-pagination-next[href]")
        if len(next_links) > 1:
            raise ValueError("greatday_pagination_invalid")
        if not next_links:
            break
        next_url = urljoin(URL, next_links[0]["href"])
        if not _page_url(next_url) or not urlsplit(next_url).query:
            raise ValueError("greatday_pagination_invalid")
        key, number = next(iter(parse_qs(urlsplit(next_url).query).items()))
        if pagination_key is not None and key != pagination_key or int(number[0]) != len(pages) + 1:
            raise ValueError("greatday_pagination_invalid")
        pagination_key, current = key, next_url
    return result


def _clock(day, value):
    token = re.sub(r"[.\s]", "", value).lower()
    if token == "noon":
        token = "12pm"
    elif token == "midnight":
        token = "12am"
    clock = datetime.strptime(token, "%I:%M%p" if ":" in token else "%I%p").time()
    return datetime.combine(day, clock, ZoneInfo(ZONE)).astimezone(timezone.utc)


def _schedule(day, body):
    ranges = list(CLOCK_RANGE.finditer(body))
    if not ranges:
        # Explicit starts are eligible; doors, drop-off and all-night prose do
        # not establish the event's start. No all-day midnight placeholder.
        match = re.search(r"\b(?:begins?|starts?)\b[^\n.!?]{0,100}?\bat\s+(?:approximately\s+)?(" + CLOCK + r")", body, re.I)
        return (_clock(day, match[1]), None) if match else None
    dates = []
    for match in BODY_DATE.finditer(body):
        month = next(i + 1 for i, name in enumerate(MONTHS) if name.lower().startswith(match[1].lower()))
        try:
            value = date(int(match[3] or day.year), month, int(match[2]))
        except ValueError:
            raise ValueError("greatday_detail_date_invalid") from None
        dates.append((match.start(), match.end(), value))
    matching = [item for item in dates if item[2] == day]
    if matching:
        begin = matching[0][1]
        later_dates = [pos for pos, _, _ in dates if pos > begin]
        stop = min(later_dates) if later_dates else len(body)
        choices = [item for item in ranges if begin <= item.start() < stop]
    elif dates and len(ranges) == 1 and re.search(r"\bdaily\b", body, re.I):
        # NACA's three-day schedule explicitly says daily; each separately
        # dated Webflow record receives the published daily hours.
        choices = ranges if min(value for _, _, value in dates) <= day <= max(value for _, _, value in dates) else []
    else:
        choices = ranges if not dates and len(ranges) == 1 else []
    if not choices:
        return None
    start, end = _clock(day, choices[0][1]), _clock(day, choices[0][2])
    if end <= start:
        # A midnight or overnight interval needs an explicit next-day notice.
        if re.search(r"\b(?:next day|following day|overnight)\b", body, re.I):
            end += timedelta(days=1)
        else:
            return None
    return start, end


def _location(header, body):
    if re.search(r"\b(?:virtual|online|zoom)\b", header, re.I):
        return None
    if (re.fullmatch(r"Massachusetts and Melrose Avenues", header, re.I)
            and "Uptown Skatepark" in body):
        return "Uptown Skatepark", "201 N Massachusetts Avenue, Atlantic City, NJ 08401"
    for pattern, venue, street in LOCATIONS:
        # When the publisher has a structured location field, bind that
        # location; an unrelated address in the prose cannot override it.
        value = header if header else body
        if re.search(r"\b" + pattern + r"\b", value, re.I):
            return venue, street + ", Atlantic City, NJ 08401"
    match = re.fullmatch(r"(\d{1,6}\s+[^,]+),\s*([^,]+),\s*NJ\s+(\d{5})", header)
    if match:
        return match[1], f"{match[1]}, {match[2]}, NJ {match[3]}"
    return None


def _detail(url, card, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    title = _text(soup.select_one("h1"))
    info = soup.select(".blog-post-info-detail .card-detail-icon-text")
    bodies = soup.select(".blog-rich-text.w-richtext")
    if title != card["title"] or not info or len(bodies) != 1:
        raise ValueError("greatday_detail_identity_changed")
    try:
        day = datetime.strptime(_text(info[0]), "%b %d, %Y").date()
    except ValueError:
        raise ValueError("greatday_detail_date_invalid") from None
    if day.isoformat() != card["date"]:
        raise ValueError("greatday_detail_schedule_changed")
    if NONPUBLIC.search(title):
        return None, "cancelled_or_nonpublic"
    raw = str(bodies[0]).replace("\u200d", "").replace("\u200b", "").replace("\ufeff", "")
    if not _text(BeautifulSoup(raw, "html.parser")):
        return None, "full_description_missing"
    body = narrative(raw)
    schedule = _schedule(day, body)
    if schedule is None:
        return None, "published_clock_missing_or_ambiguous"
    start, end = schedule
    if (end or start + timedelta(hours=3)) <= now or start >= now + timedelta(days=60):
        return None, "outside_current_window"
    header = _text(info[1]) if len(info) > 1 else ""
    if header != card["location"]:
        raise ValueError("greatday_detail_location_changed")
    location = _location(header, body)
    if not location:
        return None, "structured_street_unresolved"
    venue, address = location
    identity = urlsplit(url).path.rsplit("/", 1)[-1]
    if ((identity, start.isoformat(), end.isoformat() if end else None, address)
            in REVIEWED_LOCATION_CONFLICTS):
        return None, "publisher_venue_address_conflict"
    if (identity, start.isoformat(), end.isoformat() if end else None, address) in PRIMARY_OCCURRENCES:
        return None, "already_covered_primary_occurrence"
    lat, lng = VENUE_POINTS.get(location, (None, None))
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue, address, address.split(", ")[-2], url, sha256(urlsplit(url).path.encode()).hexdigest(),
                 card["category"], lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
    if row is None:
        return None, "outside_current_window"
    row.update(description=body, timezone=ZONE, attendance_mode="in_person",
               location_provenance="reviewed_venue_location" if lat is not None else "publisher_street_pending_geocode")
    if card["image"]:
        row["image_url"] = card["image"]
    return row, None


def _checkpoint(value, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value.get("version") != 1 or value.get("contract") != CONTRACT
            or value.get("source_key") != KEY or len(json.dumps(value).encode()) > MAX_CHECKPOINT_BYTES
            or type(value.get("cursor")) is not int or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_DETAILS
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("manifest_hash")))
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or any(not event_url(KEY, url) for url in value["queue"])
            or len(set(value["queue"])) != len(value["queue"])
            or not isinstance(value.get("events"), list) or not isinstance(value.get("diagnostics"), list)):
        raise ValueError("greatday_checkpoint_invalid")
    try:
        started = datetime.fromisoformat(value["started_at"])
        anchor = date.fromisoformat(value["window_start"])
        if started.tzinfo is None or anchor != started.astimezone(ZoneInfo(ZONE)).date():
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("greatday_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=4):
        return None
    done = set()
    for row in value["events"]:
        if (not isinstance(row, dict) or row.get("event_url") not in value["queue"][:value["cursor"]]
                or row["event_url"] in done
                or row.get("id") != sha256(urlsplit(row["event_url"]).path.encode()).hexdigest()
                or not isinstance(row.get("description"), str) or not row["description"].strip()
                or len(row["description"]) > 12000
                or not re.fullmatch(r"\d{1,6}\s+[^,]+,\s*[^,]+, NJ \d{5}", str(row.get("venue_address")))
                or not timestamp(row.get("starts_at"))
                or (row.get("lat"), row.get("lng")) != VENUE_POINTS.get(
                    (row.get("venue_name"), row.get("venue_address")), (None, None))):
            raise ValueError("greatday_checkpoint_invalid")
        done.add(row["event_url"])
    for item in value["diagnostics"]:
        if (not isinstance(item, dict) or item.get("event_url") not in value["queue"][:value["cursor"]]
                or item["event_url"] in done or item.get("disposition") != "held" or not item.get("reason")):
            raise ValueError("greatday_checkpoint_invalid")
        done.add(item["event_url"])
    if done != set(value["queue"][:value["cursor"]]):
        raise ValueError("greatday_checkpoint_invalid")
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    if ((source.get("source_key"), source.get("feed_url"), source.get("kind"),
         source.get("platform_adapter"), source.get("timezone")) != (KEY, URL, "html", "html", ZONE)):
        raise ValueError("unregistered_greatday_source")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("greatday_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, current)
    anchor = date.fromisoformat(state["window_start"]) if state else current.astimezone(ZoneInfo(ZONE)).date()
    manifest = _manifest(fetch, anchor, deadline_at)
    queue = sorted(manifest, key=lambda url: (manifest[url]["date"], url))
    digest = sha256(json.dumps({"contract": CONTRACT, "manifest": manifest}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if state is None or state["manifest_hash"] != digest or state["queue"] != queue:
        state = {"version": 1, "contract": CONTRACT, "source_key": KEY,
                 "started_at": current.isoformat(), "window_start": anchor.isoformat(),
                 "manifest_hash": digest, "manifest_count": len(queue), "queue": queue,
                 "cursor": 0, "events": [], "diagnostics": []}
    previous = state["cursor"]
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    while state["cursor"] < len(queue) and state["cursor"] - previous < limit:
        if deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        url = queue[state["cursor"]]
        row, reason = _detail(url, manifest[url], fetch(url, "text/html"), current)
        if row is not None:
            state["events"].append(row)
        else:
            state["diagnostics"].append({"event_url": url, "disposition": "held", "reason": reason})
        state["cursor"] += 1
    if state["cursor"] == previous < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("greatday_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    return {"complete": complete, "events": deepcopy(rows), "checkpoint": state}


def collect(source, fetch, *, now=None, deadline_at=None):
    result = collect_chunk(source, fetch, now=now, deadline_at=deadline_at)
    if not result["complete"]:
        raise ValueError("publisher_checkpoint_required")
    return result["events"]
