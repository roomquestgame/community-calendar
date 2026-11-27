"""Reviewed Brooklyn calendars: full Squarespace bodies and finite FAD markets.

Reuses the existing Squarespace clock and narrative cleaners. The publisher
transport owns every request and robots check; calendar export routes are not
used. Blank publisher bodies remain held. FAD's reviewed 2026 holiday series is
finite and never rolls into another year merely because its page remains live.
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

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.new_york_nightlife import _square_clock, _within, NONPUBLIC

ZONE = "America/New_York"
FREDDYS = "freddys_bar_brooklyn_ny"
STRONG = "strong_rope_brooklyn_ny"
FAD = "fad_market_brooklyn_ny"
SOURCES = {
    FREDDYS: ("https://www.freddysbar.com/events", "html", "html"),
    STRONG: ("https://www.strongropebrewery.com/events-calendar", "html", "html"),
    FAD: ("https://fadmarket.co/", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {key: 200 for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: 200 for key in SOURCES}
MAX_RECORDS = 200
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 900_000
MAX_DETAILS_PER_CHUNK = 2
MIN_DETAIL_SECONDS = 14
VENUES = {
    FREDDYS: ("Freddy’s Bar", "627 5th Avenue, Brooklyn, NY 11215", "Brooklyn"),
    STRONG: ("Strong Rope Brewery", "185 Van Dyke Street, Brooklyn, NY 11231", "Brooklyn"),
    "empire": ("FAD Market at Empire Stores", "55 Water Street, Brooklyn, NY 11201", "Brooklyn"),
    "cobble": ("FAD Market at St. Paul", "190 Court Street, Brooklyn, NY 11201", "Brooklyn"),
}
# Exact house/street/borough/ZIP matches in NYC Planning's Property Address
# Directory, reviewed 2026-11-15. These are address points, not entrance claims.
POINTS = {
    FREDDYS: (40.663246, -73.991124), STRONG: (40.677561, -74.018397),
    "empire": (40.703638, -73.991651), "cobble": (40.687565, -73.993855),
}
SITES = {FREDDYS: "63473903169dc774610eeca7", STRONG: "6406349731f96111d7d4c951",
         FAD: "56c378ad1d07c06524ed17b0"}
STREET_RE = {FREDDYS: r"627\s+(?:5th|Fifth)\s+Ave(?:nue)?", STRONG: r"185\s+Van\s+Dyke\s+St(?:reet)?"}
FAD_SERIES = {
    "https://fadmarket.co/empirestores-holiday-market": {
        "venue": "empire", "heading": "HOLIDAY POP-UP", "title": "FAD Market: Holiday Pop-Up at Empire Stores",
        "schedule": "November 30 - December 20 11am - 6pm",
        "address": "Empire Stores 55 Water Street Brooklyn, NY 11201",
        "dates": tuple(date(2026, 11, 30) + timedelta(days=n) for n in range(21)),
    },
    "https://fadmarket.co/cobble-hill-holiday-market": {
        "venue": "cobble", "heading": "HOLIDAY POP-UP [COBBLE HILL]", "title": "FAD Market: Holiday Pop-Up at St. Paul",
        "schedule": "December 5+6 | 12+13 | 19+20 11am - 6pm",
        "address": "St. Paul 190 Court Street Brooklyn, NY 11201",
        "dates": tuple(date(2026, 12, n) for n in (5, 6, 12, 13, 19, 20)),
    },
}
HELD = {"new_york_local_description_missing", "new_york_local_description_limit", "new_york_local_venue_unresolved"}
ERROR_CODES = HELD | {
    "unregistered_new_york_local_source", "new_york_local_calendar_changed", "new_york_local_event_identity",
    "new_york_local_schedule_conflict", "new_york_local_detail_changed", "new_york_local_record_limit",
    "new_york_local_checkpoint_invalid", "new_york_local_checkpoint_size_limit", "new_york_local_checkpoint_required",
    "collection_deadline",
}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                             source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_new_york_local_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.query or p.fragment
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I) or ".." in p.path.split("/")):
            return False
        if key == FAD:
            return value in FAD_SERIES
        return bool(re.fullmatch(re.escape(urlsplit(SOURCES[key][0]).path) + r"/[A-Za-z0-9/-]+", p.path))
    except ValueError:
        return False


def photo_url(key, value):
    if key not in SITES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme == "https" and p.netloc == "images.squarespace-cdn.com"
                and p.path.startswith("/content/v1/" + SITES[key] + "/") and not p.fragment
                and ".." not in p.path.split("/") and not re.search(r"%2e|%2f|%5c", p.path, re.I)
                and set(parse_qs(p.query)) <= {"format"}
                and re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)):
            return value
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, address):
    candidates = ("empire", "cobble") if key == FAD else (key,)
    return next((POINTS[name] for name in candidates if name in VENUES and (venue, address) == VENUES[name][:2]), None)


def _body(value):
    body = description(str(value or ""), limit=MAX_DESCRIPTION + 1)
    # A bare set of social links supplies no publisher narrative. Do not turn
    # it into invented prose or copy navigation/venue boilerplate instead.
    narrative = re.sub(r"\b(?:https?://|www\.|linktr\.ee/|youtu\.be/)[^\s]+", "", body, flags=re.I)
    if not re.search(r"[A-Za-z]", narrative):
        raise ValueError("new_york_local_description_missing")
    if len(body) > MAX_DESCRIPTION:
        raise ValueError("new_york_local_description_limit")
    return body


def _clock(node, suffix):
    try:
        return _square_clock(node, suffix)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("new_york_local_schedule_conflict") from None


def _location(key, node):
    locations = node.select(".eventlist-meta-address,.eventitem-meta-address")
    title = locations[0].select_one(".eventitem-meta-address-line--title") if locations else None
    supplied = (plain(title.get_text(" ")) if title else
                plain(locations[0].get_text(" ")).removesuffix("(map)").strip() if locations else "")
    names = {FREDDYS: {"freddy’s bar", "freddy's bar", "freddy's", "freddys"},
             STRONG: {"strong rope brewery", "strong rope red hook"}}[key]
    queries = [q for location in locations for a in location.select("a[href]") if urlsplit(a["href"]).hostname in {"maps.google.com", "www.google.com"}
               for q in parse_qs(urlsplit(a["href"]).query).get("q", [])]
    if any(not re.fullmatch(STREET_RE[key] + r"\s+Brooklyn,?\s+NY,?\s+" + VENUES[key][1][-5:] + r"(?:\s+(?:United States|USA))?", q.strip(), re.I) for q in queries):
        raise ValueError("new_york_local_venue_unresolved")
    if supplied and supplied.casefold() not in names:
        raise ValueError("new_york_local_venue_unresolved")
    if key == STRONG and not supplied and not queries:
        raise ValueError("new_york_local_venue_unresolved")
    return VENUES[key]


def _identity(key, item):
    return "nyc:" + sha256(f"{key}:{item['url']}:{timestamp(item['start']).isoformat()}".encode()).hexdigest()


def _content_venue(place):
    if (not isinstance(place, (tuple, list)) or len(place) != 3
            or any(not isinstance(value, str) or not value.strip() for value in place)):
        raise ValueError("new_york_local_venue_unresolved")
    postal = re.search(r"\bNY\s+(\d{5}(?:-\d{4})?)\s*$", place[1], re.I)
    result = {
        "venue_name": plain(place[0]), "venue_address": plain(place[1]),
        "venue_city": plain(place[2]), "venue_region": "NY", "venue_country": "US",
    }
    if postal:
        result["venue_postal_code"] = postal[1]
    return result


def _attach_content(row, body, *, content_venue, image=None):
    start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
    if start is None or start.tzinfo is None or end is None or end.tzinfo is None or end <= start:
        raise ValueError("new_york_local_schedule_conflict")
    facts = {
        "title": row["title"], "description": body, "is_all_day": False,
        "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
        "ends_at_utc": end.astimezone(timezone.utc).isoformat(),
        "source_timezone": ZONE, "event_url": row["event_url"],
        "source_image_url": image, "attendance_mode": "in_person", **content_venue,
    }
    facts = {name: value for name, value in facts.items() if value not in (None, "")}
    row["collector_event_content_v1"] = {"version": 1, "event_id": row["id"], "facts": facts}
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
        "source_timezone", "event_url", "source_image_url", "venue_name",
        "venue_address", "venue_city", "venue_region", "venue_postal_code",
        "venue_country", "attendance_mode",
    }
    if not set(facts) <= allowed:
        return False
    try:
        start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
        expected = {
            "title": row.get("title"), "description": row.get("description"),
            "is_all_day": False, "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
            "ends_at_utc": end.astimezone(timezone.utc).isoformat(),
            "source_timezone": ZONE, "event_url": row.get("event_url"),
            "attendance_mode": "in_person", **_content_venue(
                (row.get("venue_name"), row.get("venue_address"), row.get("venue_city"))),
        }
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return (facts.get("source_image_url") == row.get("image_url")
            and all(facts.get(name) == value for name, value in expected.items()))


def _row(key, item, body, image=None):
    place = tuple(item["venue"])
    point = reviewed_venue_location(key, *place[:2])
    start, end = timestamp(item["start"]), timestamp(item["end"])
    if not point or not event_url(key, item["url"]) or not 0 < len(item["title"]) <= 180 or end <= start:
        raise ValueError("new_york_local_event_identity")
    row = record(item["title"], start.isoformat(), end.isoformat(), *place, item["url"], _identity(key, item),
                 lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row:
        native_body = _body(body)
        row.update(description=native_body, timezone=ZONE, attendance_mode="in_person", lat=point[0], lng=point[1],
                   location_provenance="reviewed_nyc_pad_address_point")
        if row.get("reason") == "missing_verified_venue_geo":
            row["reason"] = None
        candidate = photo_url(key, image or item.get("image"))
        if candidate:
            row["image_url"] = candidate
        _attach_content(row, native_body, content_venue=_content_venue(place), image=candidate)
    return row


def _manifest(key, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    queue = []
    if key == FAD:
        links = {urljoin(SOURCES[key][0], a["href"]) for a in soup.select('a[href]')}
        if not all(url in links for url in FAD_SERIES):
            raise ValueError("new_york_local_calendar_changed")
        for url, series in FAD_SERIES.items():
            occurrences = []
            for day in series["dates"]:
                start = datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)) + timedelta(hours=11)
                end = start + timedelta(hours=7)
                if _within(start, end, now):
                    occurrences.append(dict(url=url, title=series["title"], start=start.isoformat(), end=end.isoformat(),
                                            venue=list(VENUES[series["venue"]])))
            if occurrences:
                queue.append(dict(type="fad", url=url, occurrences=occurrences))
    else:
        if not soup.select_one(".eventlist"):
            raise ValueError("new_york_local_calendar_changed")
        if key == FREDDYS and not re.search(STREET_RE[key], plain(soup.get_text(" ")), re.I):
            raise ValueError("new_york_local_venue_unresolved")
        for card in soup.select("article.eventlist-event--upcoming"):
            link = card.select_one("a.eventlist-title-link[href]")
            if link is None:
                raise ValueError("new_york_local_event_identity")
            title = plain(link.get_text(" "))
            if NONPUBLIC.search(title):
                continue
            start, end = _clock(card, "start"), _clock(card, "end")
            if end <= start:
                raise ValueError("new_york_local_schedule_conflict")
            if not _within(start, end, now):
                continue
            url = urljoin(SOURCES[key][0], link["href"])
            if not event_url(key, url) or not 0 < len(title) <= 180:
                raise ValueError("new_york_local_event_identity")
            item = dict(type="square", url=url, title=title, start=start.isoformat(), end=end.isoformat())
            try:
                item["venue"] = list(_location(key, card))
                layouts = card.select(".eventlist-description .sqs-layout")
                if len(layouts) == 1 and not card.select_one(".eventlist-excerpt"):
                    item["body"] = _body(layouts[0])
            except ValueError as exc:
                item["held"] = str(exc)
            image = card.select_one("img[data-src],img[src]")
            if image:
                item["image"] = image.get("data-src") or image.get("src")
            queue.append(item)
    unique = {}
    for item in queue:
        identity = (item["url"], item.get("start", ""))
        if identity in unique and unique[identity] != item:
            raise ValueError("new_york_local_event_identity")
        unique[identity] = item
    if len(unique) > MAX_RECORDS:
        raise ValueError("new_york_local_record_limit")
    return sorted(unique.values(), key=lambda item: (item.get("start", ""), item["url"]))


def _detail(key, item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    if canonical is None or canonical.get("href") != item["url"]:
        raise ValueError("new_york_local_detail_changed")
    if key == FAD:
        series = FAD_SERIES[item["url"]]
        layouts = soup.select('.sqs-layout[data-type="page"]')
        if len(layouts) != 1:
            raise ValueError("new_york_local_detail_changed")
        layout = layouts[0]
        values = [plain(layout.select_one(tag).get_text(" ")) if layout.select_one(tag) else None for tag in ("h1", "h2", "h3")]
        if values != [series["heading"], series["schedule"], series["address"]]:
            raise ValueError("new_york_local_schedule_conflict")
        # Read every prose block in the market page, including accessibility,
        # admission and pet policies. Headings are structured separately above.
        blocks = [node for node in layout.select(".sqs-html-content") if not node.select("h1,h2,h3")]
        body = _body("\n".join(str(node) for node in blocks))
        image = layout.select_one("img[data-src],img[src]")
        image = (image.get("data-src") or image.get("src")) if image else None
        return [row for occurrence in item["occurrences"] if (row := _row(key, occurrence, body, image))]
    heading = soup.select_one("h1.eventitem-title")
    if heading is None or plain(heading.get_text(" ")) != item["title"]:
        raise ValueError("new_york_local_detail_changed")
    if (_clock(soup, "start"), _clock(soup, "end")) != (timestamp(item["start"]), timestamp(item["end"])):
        raise ValueError("new_york_local_schedule_conflict")
    if _location(key, soup) != tuple(item["venue"]):
        raise ValueError("new_york_local_venue_unresolved")
    layouts = soup.select(".eventitem-column-content .sqs-layout")
    if len(layouts) != 1:
        raise ValueError("new_york_local_detail_changed")
    row = _row(key, item, _body(layouts[0]))
    return [row] if row else []


def _digest(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_checkpoint(value, key, now):
    if value is None:
        return None
    try:
        if (not isinstance(value, dict) or type(value["version"]) is not int or value["version"] != 1
                or value["source_key"] != key or type(value["cursor"]) is not int or type(value["manifest_count"]) is not int
                or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_RECORDS
                or not isinstance(value["queue"], list) or len(value["queue"]) != value["manifest_count"]
                or value["manifest_hash"] != _digest(value["queue"])
                or not isinstance(value["events"], list) or len(value["events"]) > MAX_RECORDS
                or not isinstance(value["diagnostics"], list) or len(value["diagnostics"]) > value["cursor"]
                or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES):
            raise ValueError
        started = timestamp(value["started_at"])
        if started.tzinfo is None or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat():
            raise ValueError
        if now < started or now - started > timedelta(hours=4):
            return None
        for item in value["queue"]:
            if not isinstance(item, dict) or not event_url(key, item.get("url")) or item.get("type") != ("fad" if key == FAD else "square"):
                raise ValueError
        bindings, urls = {}, set()
        for item in value["queue"][:value["cursor"]]:
            urls.add(item["url"])
            for occurrence in item.get("occurrences", [item]):
                bindings[_identity(key, occurrence)] = occurrence
        seen, covered = set(), set()
        for row in value["events"]:
            native = bindings.get(row.get("id"))
            if (not native or row["id"] in seen or row.get("event_url") != native["url"]
                    or row.get("title") != native["title"] or NONPUBLIC.search(row["title"])
                    or timestamp(row.get("starts_at")) != timestamp(native["start"])
                    or timestamp(row.get("ends_at")) != timestamp(native["end"])
                    or tuple(row.get(field) for field in ("venue_name", "venue_address", "venue_city")) != tuple(native["venue"])
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or _body(row.get("description")) != row.get("description")
                    or not _content_envelope_valid(row)
                    or "body" in native and row["description"] != native["body"]
                    or (row.get("lat"), row.get("lng")) != reviewed_venue_location(key, row["venue_name"], row["venue_address"])
                    or row.get("image_url") is not None and photo_url(key, row["image_url"]) is None
                    or not _within(timestamp(row["starts_at"]), timestamp(row["ends_at"]), started)):
                raise ValueError
            seen.add(row["id"])
            covered.add(row["event_url"])
        for item in value["diagnostics"]:
            if (not isinstance(item, dict) or item.get("event_url") not in urls or item.get("disposition") != "held"
                    or item.get("reason") not in HELD | {"no_available_future_occurrence"}):
                raise ValueError
            covered.add(item["event_url"])
        if covered != urls:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ValueError("new_york_local_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS_PER_CHUNK):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("new_york_local_checkpoint_invalid")
    state = _validate_checkpoint(checkpoint, key, current)
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(SOURCES[key][0], "text/html")
    queue = _manifest(key, payload, anchor)
    if state is None or state["manifest_hash"] != _digest(queue) or state["queue"] != queue:
        queue = _manifest(key, payload, current)
        state = dict(version=1, source_key=key, started_at=current.isoformat(),
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=_digest(queue), manifest_count=len(queue), cursor=0,
                     queue=queue, events=[], diagnostics=[])
    legacy_prefix = bool(state["events"] and
                         any("collector_event_content_v1" not in row for row in state["events"]))
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
            if needs_detail:
                detail = fetch(item["url"], "text/html")
                fetched += 1
                rows = _detail(key, item, detail)
            else:
                row = _row(key, item, item["body"])
                rows = [row] if row else []
            if legacy_prefix:
                for row in rows:
                    row.pop("collector_event_content_v1", None)
            state["events"].extend(rows)
            if not rows:
                state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason="no_available_future_occurrence"))
        except ValueError as exc:
            if str(exc) not in HELD:
                raise
            state["diagnostics"].append(dict(event_url=item["url"], disposition="held", reason=str(exc)))
        state["cursor"] += 1
        if len(state["events"]) > MAX_RECORDS:
            raise ValueError("new_york_local_record_limit")
    if state["cursor"] == prior < len(queue):
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_local_checkpoint_size_limit")
    complete = state["cursor"] == len(queue)
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("new_york_local_event_identity")
    return dict(complete=complete, events=deepcopy(rows), checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("new_york_local_checkpoint_required")
    return result["events"]
