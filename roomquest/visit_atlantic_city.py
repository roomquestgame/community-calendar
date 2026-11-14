"""Visit Atlantic City's public sitemap and complete event detail pages.

The RSS export is a 30-item excerpt, and the interactive search endpoint is not
available to this collector. The publisher sitemap supplies the bounded event
manifest. Detail reads resume through the existing private checkpoint gateway;
only a completely visited manifest can enter ordinary staging/publication.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record


SOURCE_KEY = "visit_atlantic_city_nj"
HOST = "www.visitatlanticcity.com"
CALENDAR = f"https://{HOST}/events/"
SITEMAP = f"https://{HOST}/sitemap.xml"
ZONE = ZoneInfo("America/New_York")
CONTRACT = "visit_atlantic_city_v1"
MAX_MANIFEST = 200
MAX_EVENTS = 500
MAX_BYTES = 900_000
MAX_DESCRIPTION = 12_000
MAX_AGE = timedelta(hours=4)
MAX_DETAILS_PER_CHUNK = 6
MIN_DETAIL_SECONDS = 12
DETAIL = re.compile(r"/event/[^/?#]+/[1-9][0-9]{0,7}/")
CLOCK = re.compile(r"(1[0-2]|[1-9])(?::([0-5][0-9]))?\s*([ap])\.?\s*m\.?", re.I)
DAYS = {name: n for n, name in enumerate(
    ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def event_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and parsed.netloc == HOST
            and not parsed.query and not parsed.fragment and bool(DETAIL.fullmatch(parsed.path)))


def _source(source):
    if tuple(source.get(k) for k in ("source_key", "feed_url", "kind", "platform_adapter", "timezone")) != (
            SOURCE_KEY, CALENDAR, "html", "html", ZONE.key):
        raise ValueError("unregistered_visit_atlantic_city")


def manifest(payload):
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("visit_atlantic_sitemap_invalid") from exc
    if root.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
        raise ValueError("visit_atlantic_sitemap_invalid")
    urls = sorted({node.text.strip() for node in root.iter()
                   if node.tag.endswith("}loc") and node.text and event_url(node.text.strip())})
    if not urls or len(urls) > MAX_MANIFEST:
        raise ValueError("visit_atlantic_manifest_limit")
    return urls


def _variable(payload, name, *, optional=False):
    values = []
    for match in re.finditer(r"\bvar\s+" + re.escape(name) + r"\s*=\s*", payload):
        try:
            value, _ = json.JSONDecoder().raw_decode(payload[match.end():])
        except (ValueError, TypeError):
            continue
        values.append(value)
    if not values and optional:
        return ""
    if len(values) != 1:
        raise ValueError("visit_atlantic_detail_structure")
    return values[0]


def _clock(value):
    match = CLOCK.fullmatch(value.strip())
    if not match:
        return None
    hour, minute, meridiem = match.groups()
    return time(int(hour) % 12 + 12 * (meridiem.lower() == "p"), int(minute or 0))


def _hours(value):
    """Only explicit clocks; no prose-based guess or implicit all-day default."""
    value = plain(value)
    if not value:
        return []
    parts = [part for part in re.split(r"\s*(?:&|;|,|\band\b)\s*", value, flags=re.I) if part.strip()]
    if not parts or len(parts) > 5:
        return []
    out = []
    for part in parts:
        clocks = re.split(r"\s*(?:[-–—]|\bto\b)\s*", part, flags=re.I)
        if len(clocks) > 2:
            return []
        start = _clock(clocks[0])
        end = _clock(clocks[1]) if len(clocks) == 2 else None
        if start is None or (len(clocks) == 2 and (end is None or end == start)):
            return []
        out.append((start, end))
    return out


def _days(start, end, recurrence, window_start, explicit_dates=""):
    """Expand only the exact daily/weekly recurrence published on the event."""
    stop = min(end or window_start + timedelta(days=60), window_start + timedelta(days=60))
    first = max(start, window_start)
    if stop < first:
        return []
    if (isinstance(explicit_dates, str) and re.fullmatch(
            r"\d{1,2}/\d{1,2}/\d{4}(?:,\s*\d{1,2}/\d{1,2}/\d{4})*", explicit_dates.strip())):
        try:
            days = sorted({datetime.strptime(value.strip(), "%m/%d/%Y").date()
                           for value in explicit_dates.split(",")})
        except ValueError as exc:
            raise ValueError("visit_atlantic_detail_dates") from exc
        if any(day < start or (end and day > end) for day in days):
            raise ValueError("visit_atlantic_detail_dates")
        return [day for day in days if first <= day <= stop]
    rule = plain(recurrence).casefold()
    if not rule:
        # A multi-day range without a recurrence is not proof of daily sessions.
        return [start] if start >= window_start and (end is None or end == start) else None
    if rule == "recurring daily":
        weekdays = set(range(7))
    elif rule.startswith("recurring weekly on "):
        names = re.split(r",\s*|\s+and\s+", rule.removeprefix("recurring weekly on "))
        if any(name not in DAYS for name in names):
            return None
        weekdays = {DAYS[name] for name in names}
    elif match := re.fullmatch(r"recurring monthly on the ([1-5])(?:st|nd|rd|th) (\w+)", rule):
        if match[2] not in DAYS:
            return None
        return [first + timedelta(days=i) for i in range((stop - first).days + 1)
                if (first + timedelta(days=i)).weekday() == DAYS[match[2]]
                and ((first + timedelta(days=i)).day - 1) // 7 + 1 == int(match[1])]
    else:
        return None
    return [first + timedelta(days=i) for i in range((stop - first).days + 1)
            if (first + timedelta(days=i)).weekday() in weekdays]


def _schedule_hours(day, field, narrative, *, extra_one_day_times=False, weekly=False):
    """Respect explicit weekday showtimes and dated overrides in the prose."""
    clocks = _hours(field)
    weekday_hours = {}
    date_hours = {}
    clock = r"(?:1[0-2]|[1-9])(?::[0-5][0-9])?\s*[ap]\.?\s*m\.?"
    for line in narrative.splitlines():
        match = re.fullmatch(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*:\s*(.+)", line, re.I)
        if match and weekly:
            weekday_hours[DAYS[match[1].casefold()]] = _hours(match[2])
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*[-–—:]\s*(.+)", line)
        if match:
            date_hours[(int(match[1]), int(match[2]), int(match[3]) if match[3] else None)] = _hours(match[4])
    prose = " ".join(narrative.split())
    # Reviewed visible prose can carry the weekday-specific schedule instead
    # of Simpleview's single Time field (for example the Diva Royale show).
    day_names = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
    clock_list = clock + r"(?:(?:,\s*(?:and\s+)?|\s+(?:and|&)\s+)" + clock + r")*"
    if weekly:
        for match in re.finditer(r"\b(" + day_names + r")(?:s)?(?:\s+Brunch Show)?\s+at\s+(" + clock_list + r")", prose, re.I):
            weekday_hours[DAYS[match[1].casefold()]] = _hours(match[2])
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    for match in re.finditer(r"\b(" + months + r")\s+(\d{1,2})\s+starting at\s+(" + clock_list + r")", prose, re.I):
        month = datetime.strptime(match[1].title(), "%B").month
        date_hours[month, int(match[2]), None] = _hours(match[3])
    if (day.month, day.day, day.year) in date_hours:
        return date_hours[day.month, day.day, day.year]
    if (day.month, day.day, None) in date_hours:
        return date_hours[day.month, day.day, None]
    if weekday_hours:
        return weekday_hours.get(day.weekday(), [])
    if extra_one_day_times and len(clocks) == 1 and clocks[0][1] is None:
        matches = re.findall(r"\bat\s+(" + clock + r"(?:\s*(?:and|&)\s*" + clock + r")+)",
                             prose, re.I)
        expanded = [_hours(value) for value in matches]
        expanded = [value for value in expanded if clocks[0] in value]
        if len(expanded) == 1:
            return expanded[0]
    return clocks


def _coordinate(value, lower, upper):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and lower <= value <= upper else None


def parse_detail(payload, url, *, window_start):
    """Return complete normalized occurrences and a nonpublication reason."""
    if not event_url(url):
        raise ValueError("visit_atlantic_detail_identity")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    soup = BeautifulSoup(payload, "html.parser")
    canonical = soup.select('link[rel~="canonical"]')
    if len(canonical) != 1 or canonical[0].get("href") != url:
        raise ValueError("visit_atlantic_detail_identity")
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            block = json.loads(script.get_text())
        except ValueError as exc:
            raise ValueError("visit_atlantic_detail_structure") from exc
        nodes = block.get("@graph", [block]) if isinstance(block, dict) else block
        if not isinstance(nodes, list):
            raise ValueError("visit_atlantic_detail_structure")
        events.extend(node for node in nodes if isinstance(node, dict)
                      and isinstance(node.get("@type"), str)
                      and (node["@type"].endswith("Event") or node["@type"] == "Festival"))
    if len(events) != 1 or events[0].get("url") != url:
        raise ValueError("visit_atlantic_detail_identity")
    event = events[0]
    data = _variable(payload, "data")
    if (not isinstance(data, dict) or str(data.get("recid")) != url.rstrip("/").split("/")[-1]
            or plain(data.get("title")) != plain(event.get("name"))):
        raise ValueError("visit_atlantic_detail_identity")
    if data.get("expired") or data.get("past") or event.get("eventStatus") in (
            "https://schema.org/EventCancelled", "https://schema.org/EventPostponed"):
        return [], "past_or_cancelled"
    try:
        start_day = date.fromisoformat(event["startDate"])
        end_day = date.fromisoformat(event["endDate"]) if event.get("endDate") else None
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("visit_atlantic_detail_dates") from exc
    if end_day and end_day < start_day:
        raise ValueError("visit_atlantic_detail_dates")
    if start_day > window_start + timedelta(days=60) or (end_day and end_day < window_start):
        return [], "outside_window"
    days = _days(start_day, end_day, data.get("recurrence"), window_start,
                 _variable(payload, "dates", optional=True))
    if days is None:
        return [], "schedule_requires_review"
    if not days:
        return [], "outside_window"
    narrative = description(data.get("description"), limit=MAX_DESCRIPTION + 1)
    if not narrative:
        return [], "event_description_missing"
    if len(narrative) > MAX_DESCRIPTION:
        raise ValueError("visit_atlantic_description_limit")
    clock_field = _variable(payload, "time")
    schedules = {day: _schedule_hours(day, clock_field, narrative,
                                    extra_one_day_times=start_day == end_day,
                                    weekly=plain(data.get("recurrence")).casefold().startswith("recurring weekly on "))
                 for day in days}
    if any(not clocks for clocks in schedules.values()):
        return [], "event_time_missing_or_ambiguous"
    location = event.get("location")
    address = location.get("address") if isinstance(location, dict) else None
    if not isinstance(address, dict):
        return [], "venue_address_missing"
    street = plain(address.get("streetAddress"))
    venue = location.get("name") or data.get("location")
    resolved_parade_finish = False
    # Official city park inventory and the North to Shore venue directory both
    # identify 3501 Atlantic Avenue. The event explicitly ends at this market;
    # label that meeting point rather than inventing a numbered parade route.
    if (str(data["recid"]) == "7140" and street.casefold() == "atlantic avenue"
            and "O'Donnell Memorial Park" in plain(narrative)):
        street = "3501 Atlantic Avenue"
        venue = "O'Donnell Memorial Park (holiday market / parade finish)"
        resolved_parade_finish = True
    if plain(venue).casefold() == "boogie nights" and street.startswith("2831 Boardwalk"):
        street = "2831 Boardwalk"
    # The hotel's 2026 Wave press-release address supplies the street number
    # omitted from its tourism listing's Huron/Brigantine intersection.
    if (plain(venue).casefold() == "golden nugget atlantic city"
            and street.casefold() == "huron ave. & brigantine blvd."):
        street = "600 Huron Avenue"
    # This publisher address includes a separate parking/entry instruction.
    # Preserve both the unit and that instruction without treating the second
    # street as an alternative venue or an extra address component.
    if (plain(venue).casefold() == "little water distillery"
            and street == "807 Baltic Ave., Unit B (park and enter at 813 Lexington Ave.)"):
        street = "807 Baltic Avenue Unit B"
        access = "park and enter at 813 Lexington Ave."
        if access.casefold() not in narrative.casefold():
            narrative += "\nPublisher venue access note: " + access
        if len(narrative) > MAX_DESCRIPTION:
            raise ValueError("visit_atlantic_description_limit")
    # Some publishers place the building name before the actual street number.
    street_match = re.search(r"(?<!\d)(\d{1,6}\s+[A-Za-z].*)", street)
    street = street_match.group(1) if street_match else ""
    city = plain(address.get("addressLocality"))
    if city.casefold() == "atantic city":
        city = "Atlantic City"
    region = plain(address.get("addressRegion"))
    if region.casefold() == "new jersey":
        region = "NJ"
    postal = plain(address.get("postalCode"))
    if not street or not city or region != "NJ" or not re.fullmatch(r"\d{5}(?:-\d{4})?", postal):
        return [], "venue_address_missing"
    full_address = f"{street}, {city}, {region} {postal}"
    geo = location.get("geo") or {}
    lat = _coordinate(geo.get("latitude"), 38.8, 41.4)
    lng = _coordinate(geo.get("longitude"), -75.6, -73.8)
    if lat is None or lng is None or resolved_parade_finish:
        lat = lng = None
    categories = [plain(item.get("catName")) for item in data.get("categories", [])
                  if isinstance(item, dict) and plain(item.get("catName"))]
    image = event.get("image")
    image = image.get("url") if isinstance(image, dict) else image
    rows = []
    for day in days:
        for start_clock, end_clock in schedules[day]:
            begins = datetime.combine(day, start_clock)
            ends = datetime.combine(day, end_clock) if end_clock else None
            if ends and ends < begins:
                ends += timedelta(days=1)
            row = record(event["name"], begins.isoformat(), ends.isoformat() if ends else None,
                         venue, full_address, city, url,
                         str(data["recid"]), ", ".join(categories), lat, lng, ZONE.key,
                         retain_until_end=True)
            if row:
                row["description"] = narrative
                row["publisher_categories"] = categories
                if isinstance(image, str) and image.startswith("https://assets.simpleviewinc.com/"):
                    row["image_url"] = image
                rows.append(row)
    return rows, None if rows else "outside_window"


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS_PER_CHUNK):
    _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("visit_atlantic_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    urls = manifest(fetch(SITEMAP, "application/xml,text/xml"))
    digest = sha256(_encoded(urls).encode()).hexdigest()
    state = None
    if checkpoint is not None:
        if (not isinstance(checkpoint, dict) or checkpoint.get("contract") != CONTRACT
                or type(checkpoint.get("version")) is not int or checkpoint["version"] != 1
                or checkpoint.get("source_key") != SOURCE_KEY
                or type(checkpoint.get("cursor")) is not int
                or type(checkpoint.get("manifest_count")) is not int
                or not 0 <= checkpoint["cursor"] <= checkpoint["manifest_count"] <= MAX_MANIFEST
                or not isinstance(checkpoint.get("events"), list)
                or len(checkpoint["events"]) > MAX_EVENTS
                or not isinstance(checkpoint.get("diagnostics"), list)
                or len(checkpoint["diagnostics"]) > MAX_MANIFEST
                or len(_encoded(checkpoint).encode()) > MAX_BYTES):
            raise ValueError("visit_atlantic_checkpoint_invalid")
        try:
            started = datetime.fromisoformat(checkpoint["started_at"])
            if (started.tzinfo is None or started.utcoffset() is None
                    or checkpoint["window_start"] != started.astimezone(ZONE).date().isoformat()):
                raise ValueError
        except (TypeError, ValueError, KeyError):
            raise ValueError("visit_atlantic_checkpoint_invalid") from None
        if (started <= current <= started + MAX_AGE and checkpoint.get("manifest_hash") == digest
                and checkpoint["manifest_count"] == len(urls)):
            state = deepcopy(checkpoint)
            seen = set()
            completed_urls = set(urls[:state["cursor"]])
            for row in state["events"]:
                if (not isinstance(row, dict) or row.get("event_url") not in completed_urls
                        or not isinstance(row.get("description"), str)
                        or not 0 < len(row["description"]) <= MAX_DESCRIPTION
                        or not isinstance(row.get("id"), str) or not isinstance(row.get("starts_at"), str)
                        or not isinstance(row.get("venue_address"), str) or not row["venue_address"]):
                    raise ValueError("visit_atlantic_checkpoint_invalid")
                identity = row["id"], row["starts_at"]
                if identity in seen:
                    raise ValueError("visit_atlantic_checkpoint_invalid")
                seen.add(identity)
            if any(not isinstance(d, dict) or d.get("event_url") not in completed_urls
                   or not isinstance(d.get("reason"), str) for d in state["diagnostics"]):
                raise ValueError("visit_atlantic_checkpoint_invalid")
    if state is None:
        state = {"version": 1, "contract": CONTRACT, "source_key": SOURCE_KEY,
                 "started_at": current.isoformat(), "window_start": current.astimezone(ZONE).date().isoformat(),
                 "manifest_hash": digest, "manifest_count": len(urls), "cursor": 0,
                 "events": [], "diagnostics": []}
    previous = state["cursor"]
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    for offset in range(previous, min(len(urls), previous + limit)):
        if deadline_at is not None and deadline_at - monotonic() < MIN_DETAIL_SECONDS:
            break
        url = urls[offset]
        try:
            payload = fetch(url, "text/html")
        except ValueError as exc:
            from roomquest.preview_worker import PreviewError
            if isinstance(exc, PreviewError) and str(exc) == "publisher_http_410":
                # A retired publisher page may linger in its official sitemap.
                # The explicit Gone response is observed evidence, not an
                # assumed cancellation of an earlier published occurrence.
                rows, reason = [], "publisher_page_gone"
            elif (isinstance(exc, PreviewError) and str(exc) in (
                    "source_fetch_deadline", "publisher_pacing_deferred") and offset > previous):
                break
            else:
                raise
        else:
            rows, reason = parse_detail(payload, url,
                                       window_start=date.fromisoformat(state["window_start"]))
        state["events"].extend(rows)
        if reason:
            state["diagnostics"].append({"event_url": url, "reason": reason})
        state["cursor"] = offset + 1
        if len(state["events"]) > MAX_EVENTS:
            raise ValueError("visit_atlantic_event_limit")
    if len(_encoded(state).encode()) > MAX_BYTES:
        raise ValueError("visit_atlantic_checkpoint_size_limit")
    complete = state["cursor"] == state["manifest_count"]
    if not complete and state["cursor"] == previous:
        raise ValueError("collection_deadline")
    rows = sorted(state["events"], key=lambda row: (row["starts_at"], row["id"])) if complete else []
    if complete and len({(row["id"], row["starts_at"]) for row in rows}) != len(rows):
        raise ValueError("visit_atlantic_duplicate_occurrence")
    return {"checkpoint": state, "complete": complete, "events": rows}


def collect(source, fetch, *, deadline_at=None, now=None):
    """Read-only callers cannot accidentally accept the first partial chunk."""
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("visit_atlantic_checkpoint_required")
    return result["events"]
