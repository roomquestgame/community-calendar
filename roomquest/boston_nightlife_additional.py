"""Additional Boston nightlife calendars with complete publisher narratives.

All I/O is injected by the existing robots-aware publisher transport. Public
calendar JSON and inert page data are read as data; no publisher script runs.
Passim and Burren hydrate each unique detail once per complete-only checkpoint.
Long Live uses only its named, weekday-consistent jazz dates, bounded to 28 days.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.boston_nightlife import _body, _clock, _title_key, _validated_body, _within, NONPUBLIC
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = "America/New_York"
LIZARD = "lizard_lounge_ma"
IMPROV = "improv_asylum_ma"
LAUGH = "laugh_boston_ma"
PASSIM = "club_passim_ma"
BURREN = "burren_ma"
LONG_LIVE = "long_live_roxbury_ma"
SOURCES = {
    LIZARD: ("https://lizardloungeclub.com/calendar/", "html", "html"),
    IMPROV: ("https://calendar.improvasylum.com/", "html", "html"),
    LAUGH: ("https://calendar.laughboston.com/", "html", "html"),
    PASSIM: ("https://www.passim.org/live-music/", "html", "html"),
    BURREN: ("https://www.burren.com/music.html", "html", "html"),
    LONG_LIVE: ("https://www.longlivebeerworks.com/boston", "html", "html"),
}
LABELS = {LIZARD: "Lizard Lounge", IMPROV: "Improv Asylum", LAUGH: "Laugh Boston",
          PASSIM: "Club Passim", BURREN: "The Burren", LONG_LIVE: "Long Live Roxbury"}
SOURCE_NOTES = {
    LIZARD: "Official WordPress TEC REST; explicit local/UTC clock agreement, complete native descriptions, closures excluded, 60-day window.",
    IMPROV: "Official calendar's anonymous public JSON, complete description rather than 300-character JSON-LD teaser; event-specific street and clocks corroborated against the calendar schema.",
    LAUGH: "Official calendar's anonymous public JSON, complete description rather than 300-character JSON-LD teaser; event-specific street and clocks corroborated against the calendar schema.",
    PASSIM: "All explicit dated occurrences in inert calendar literals; visible show clocks are local despite the publisher's erroneous +0000 suffix. Full detail prose, nullable unprovided end, and event-specific off-site venue overrides.",
    BURREN: "Publisher's dated front/back room schedule; chronology and weekdays bind omitted years to explicit year headers. Linked 24HourMusic descriptions hydrate completely. Native closed sessions excluded; unprovided ends remain null.",
    LONG_LIVE: "Named dates only within the publisher-declared Thursday 6-9 PM jazz schedule and a 28-day window. Omitted holiday Thursdays are not generated. Complete native series prose; Boston address overrides unrelated Providence organization metadata.",
}
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
ALLOWED_HOSTS[BURREN] += ("tickets.24hourmusic.com",)
CHECKPOINT_KEYS = set(SOURCES)
COMEDY_API = {IMPROV: "https://calendar.improvasylum.com/api/events/improv-asylum",
              LAUGH: "https://calendar.laughboston.com/api/events/laugh-boston"}
TEC_API = "https://lizardloungeclub.com/wp-json/tribe/events/v1/events"
MAX_RECORDS = 200
MAX_PAGES = 4
MAX_BYTES = 900_000
MAX_FETCHES = 12
MIN_SECONDS = 10
_NO_BODY = object()
VENUES = {
    "lizard": ("Lizard Lounge", "1667 Massachusetts Avenue, Cambridge, MA 02138", "Cambridge"),
    "improv": ("Improv Asylum", "216 Hanover Street, Boston, MA 02113", "Boston"),
    "laugh": ("Laugh Boston", "425 Summer Street, Boston, MA 02210", "Boston"),
    "passim": ("Club Passim", "47 Palmer Street, Cambridge, MA 02138", "Cambridge"),
    "armory": ("Arts at the Armory", "191 Highland Avenue, Somerville, MA 02143", "Somerville"),
    "arrow": ("Arrow Street Arts", "2 Arrow Street, Cambridge, MA 02138", "Cambridge"),
    "burren_front": ("The Burren — Front Room", "247 Elm Street, Somerville, MA 02144", "Somerville"),
    "burren_back": ("The Burren — Back Room", "247 Elm Street, Somerville, MA 02144", "Somerville"),
    "long_live": ("Long Live Roxbury", "152 Hampden Street, Boston, MA 02119", "Boston"),
}
VENUE_KEYS = {LIZARD: {"lizard"}, IMPROV: {"improv"}, LAUGH: {"laugh"},
              PASSIM: {"passim", "armory", "arrow"}, BURREN: {"burren_front", "burren_back"},
              LONG_LIVE: {"long_live"}}
# The publisher's Directions & Parking page binds this explicit ACF venue
# marker to Club Passim at 47 Palmer Street. Off-site events never inherit it.
# No unrelated map viewport, organization default, or guessed point is imported.
POINTS = {"passim": (42.3741826, -71.11964540000002)}
VENUE_EVIDENCE = {
    "lizard": "https://lizardloungeclub.com/venue/lizard-lounge/",
    "improv": SOURCES[IMPROV][0], "laugh": SOURCES[LAUGH][0],
    "passim": "https://www.passim.org/live-music/directions-parking/",
    "armory": "https://artsatthearmory.org/contact-us/getting-here/",
    "arrow": "https://www.arrowstarts.org/faq",
    "burren_front": SOURCES[BURREN][0], "burren_back": SOURCES[BURREN][0],
    "long_live": SOURCES[LONG_LIVE][0],
}
HOLD_CODES = {"boston_nightlife_description_missing", "boston_nightlife_description_limit",
              "boston_additional_venue_unresolved", "boston_additional_schedule_conflict",
              "boston_additional_schema_missing", "boston_additional_outside_window"}
ERROR_CODES = HOLD_CODES | {"unregistered_boston_additional_source", "boston_additional_calendar_changed",
    "boston_additional_detail_changed", "boston_additional_record_limit", "boston_additional_checkpoint_invalid",
    "boston_additional_checkpoint_size_limit", "boston_additional_checkpoint_required", "collection_deadline"}
MONTHS = {name.casefold(): n for n, name in enumerate(
    ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")) if n}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
WEEKDAYS = {name.casefold(): i for i, name in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
                             source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_boston_additional_source")
    return key


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1500 or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I):
        return None
    try:
        p = urlsplit(value)
        return p if (p.scheme == "https" and not p.username and not p.password
            and p.port in (None, 443) and not p.fragment and ".." not in p.path.split("/")) else None
    except ValueError:
        return None


def event_url(key, value):
    p = _safe_url(value)
    if not p or key not in SOURCES:
        return False
    if key in COMEDY_API:
        group = "improvasylum" if key == IMPROV else "laughboston"
        return (p.netloc == "www.tixr.com" and not p.query
            and bool(re.fullmatch(r"/groups/" + group + r"/events/[a-z0-9-]+-\d+", p.path)))
    if key == BURREN:
        if value == SOURCES[BURREN][0]:
            return True
        q = parse_qs(p.query, keep_blank_values=True)
        return (p.netloc == "tickets.24hourmusic.com" and p.path == "/eventperformances.asp"
            and set(q) == {"evt"} and len(q["evt"]) == 1 and bool(re.fullmatch(r"[1-9]\d{0,5}", q["evt"][0])))
    if p.netloc != urlsplit(SOURCES[key][0]).netloc or p.query:
        return False
    if key == LONG_LIVE:
        return value == SOURCES[key][0]
    path = r"/event/[a-z0-9-]+/" if key == LIZARD else r"/live-music/events/[a-z0-9-]+/"
    return bool(re.fullmatch(path, p.path))


def reviewed_venue_location(key, venue, address):
    for venue_key in VENUE_KEYS.get(key, ()):
        if (venue, address) == VENUES[venue_key][:2]:
            return POINTS.get(venue_key)
    return None


def _identity(key, native):
    return "boston:" + sha256(f'{key}:{native["native_id"]}:{native["start"]}'.encode()).hexdigest()


def _packet(key, url, title, identity, occurrences, *, venue=None, body=_NO_BODY, **extra):
    title = plain(title)
    if (not event_url(key, url) or not 1 <= len(title) <= 180 or not isinstance(identity, str)
            or not 1 <= len(identity) <= 250 or not isinstance(occurrences, list)
            or not 1 <= len(occurrences) <= MAX_RECORDS):
        raise ValueError("boston_additional_calendar_changed")
    for occurrence in occurrences:
        start, end = timestamp(occurrence["start"]), timestamp(occurrence.get("end"))
        if start.tzinfo is None or end is not None and (end.tzinfo is None or end <= start):
            raise ValueError("boston_additional_schedule_conflict")
    if venue is not None and venue not in VENUE_KEYS[key]:
        raise ValueError("boston_additional_venue_unresolved")
    item = dict(url=url, title=title, native_id=identity, occurrences=occurrences, **extra)
    if venue is not None:
        item["venue_key"] = venue
    if body is not _NO_BODY:
        try:
            item["body"] = _body(body)
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            item["held"] = str(exc)
    return item


def _occurrence(start, end=None):
    return dict(start=start.isoformat(), end=end.isoformat() if end else None)


def _row(key, item):
    place = VENUES[item["venue_key"]]
    point = reviewed_venue_location(key, *place[:2]) or (None, None)
    row = record(item["title"], item["start"], item.get("end"), *place, item["url"],
                 _identity(key, item), lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row is None:
        raise ValueError("boston_additional_outside_window")
    row.update(description=_validated_body(item["body"]), timezone=ZONE, attendance_mode="in_person",
               location_provenance="reviewed_publisher_street_point" if point[0] is not None else "reviewed_publisher_street_pending_geocode",
               location_evidence_url=VENUE_EVIDENCE[item["venue_key"]])
    if item.get("published_schedule"):
        row.update(schedule_provenance="publisher_declared_named_weekly_schedule",
                   published_schedule=item["published_schedule"], schedule_window_days=28)
    return row


def _jsonld(soup):
    result = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(node.string or node.get_text())
        except (ValueError, TypeError):
            continue
        values = obj if isinstance(obj, list) else [obj]
        for value in values:
            if isinstance(value, dict):
                result.extend(value.get("@graph", [value]))
    return [x for x in result if isinstance(x, dict) and x.get("@type") in {"Event", "MusicEvent", "ComedyEvent"}]


def _tec_url(now, page=1):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    return TEC_API + "?" + urlencode(dict(per_page=50, start_date=f"{day} 00:00:00",
        end_date=f"{day + timedelta(days=61)} 00:00:00", status="publish", page=page))


def _lizard_listing(payload, now):
    data = json.loads(payload)
    if (not isinstance(data, dict) or not isinstance(data.get("events"), list)
            or len(data["events"]) > 50 or type(data.get("total_pages")) is not int
            or not 0 <= data["total_pages"] <= MAX_PAGES or type(data.get("total")) is not int
            or not 0 <= data["total"] <= MAX_RECORDS):
        raise ValueError("boston_additional_record_limit")
    queue = []
    for e in data["events"]:
        title = plain(e.get("title"))
        if (e.get("status") != "publish" or e.get("event_status") in {"canceled", "cancelled", "postponed"}
                or e.get("hide_from_listings") or e.get("is_virtual") or e.get("all_day")
                or NONPUBLIC.search(title) or re.search(r"\bno event tonight\b", title, re.I)):
            continue
        if type(e.get("id")) is not int or e.get("timezone") != ZONE:
            raise ValueError("boston_additional_calendar_changed")
        start, end = timestamp(e.get("start_date"), ZONE), timestamp(e.get("end_date"), ZONE)
        if start != timestamp(e.get("utc_start_date"), "UTC") or end != timestamp(e.get("utc_end_date"), "UTC"):
            raise ValueError("boston_additional_schedule_conflict")
        if not _within(start, end, now):
            continue
        venue = e.get("venue") or {}
        native_place = (plain(venue.get("venue")), plain(venue.get("address")), plain(venue.get("city")),
                        venue.get("state") or venue.get("stateprovince"), venue.get("zip"))
        item = _packet(LIZARD, e.get("url"), title, str(e["id"]), [_occurrence(start, end)],
                       venue="lizard", body=e.get("description"))
        if native_place != ("Lizard Lounge", "1667 Massachusetts Avenue", "Cambridge", "MA", "02138"):
            item["held"] = "boston_additional_venue_unresolved"
        queue.append(item)
    return queue, max(1, data["total_pages"])


def _comedy_listing(key, calendar, payload, now):
    schema = {x.get("url") or x.get("@id"): x for x in _jsonld(BeautifulSoup(calendar, "html.parser"))}
    data = json.loads(payload)
    if (not isinstance(data, dict) or not isinstance(data.get("events"), list)
            or len(data["events"]) > 500 or data.get("timezone") != ZONE
            or data.get("total") != len(data["events"])):
        raise ValueError("boston_additional_calendar_changed")
    venue_key = "improv" if key == IMPROV else "laugh"
    name, address, city = VENUES[venue_key]
    street, _, suffix = address.partition(", ")
    zip_code = suffix[-5:]
    queue = []
    for e in data["events"]:
        if e.get("status") in {"cancelled", "canceled", "postponed", "private", "hidden"} or NONPUBLIC.search(plain(e.get("title"))):
            continue
        if e.get("status") not in {"available", "coming_soon", "soldout"} or e.get("timezone") != ZONE:
            raise ValueError("boston_additional_calendar_changed")
        if not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(e.get("id", ""))):
            raise ValueError("boston_additional_calendar_changed")
        start, end = timestamp(e.get("start")), timestamp(e.get("end"))
        if not _within(start, end, now):
            continue
        item = _packet(key, e.get("ticketUrl"), e.get("title"), e["id"], [_occurrence(start, end)],
                       venue=venue_key, body=e.get("description"))
        native = schema.get(e["ticketUrl"])
        if not native:
            item["held"] = "boston_additional_schema_missing"
        else:
            loc = native.get("location") or {}
            a = loc.get("address") or {}
            if (e.get("venue"), loc.get("name"), a.get("streetAddress"), plain(a.get("addressLocality")).casefold(), a.get("addressRegion"), a.get("postalCode")) != (name, name, street, city.casefold(), "MA", zip_code):
                item["held"] = "boston_additional_venue_unresolved"
            if (timestamp(native.get("startDate")) != start or timestamp(native.get("endDate")) != end
                    or _title_key(native.get("name")) != _title_key(e.get("title"))
                    or native.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
                    or native.get("eventStatus") != "https://schema.org/EventScheduled"):
                item["held"] = "boston_additional_schedule_conflict"
        queue.append(item)
    return queue


def _js_string(raw, pos):
    """Decode a quoted literal only. Reject expressions rather than evaluate JS."""
    quote = raw[pos]
    if quote not in {'"', "'"}:
        raise ValueError("boston_additional_calendar_changed")
    if quote == '"':
        try:
            value, end = json.JSONDecoder().raw_decode(raw[pos:])
            if not isinstance(value, str):
                raise ValueError
            return value, pos + end
        except ValueError:
            raise ValueError("boston_additional_calendar_changed") from None
    chars, pos = [], pos + 1
    while pos < len(raw):
        char = raw[pos]
        pos += 1
        if char == quote:
            return "".join(chars), pos
        if char == "\\":
            if pos >= len(raw) or raw[pos] not in "\\'\"/nrt":
                raise ValueError("boston_additional_calendar_changed")
            char = {"n": "\n", "r": "\r", "t": "\t"}.get(raw[pos], raw[pos])
            pos += 1
        chars.append(char)
    raise ValueError("boston_additional_calendar_changed")


def _passim_literals(payload):
    soup = BeautifulSoup(payload, "html.parser")
    rows, found = [], False
    for script in soup.select("script:not([src])"):
        raw = script.string or script.get_text()
        if ".fullCalendar(" not in raw:
            continue
        for match in re.finditer(r"\bevents\s*:\s*\[", raw):
            found = True
            pos = match.end()
            while True:
                while pos < len(raw) and raw[pos] in " \t\r\n,":
                    pos += 1
                if pos < len(raw) and raw[pos] == "]":
                    break
                if pos >= len(raw) or raw[pos] != "{":
                    raise ValueError("boston_additional_calendar_changed")
                pos += 1
                row = {}
                while True:
                    while pos < len(raw) and raw[pos] in " \t\r\n,":
                        pos += 1
                    if pos < len(raw) and raw[pos] == "}":
                        pos += 1
                        break
                    name = re.match(r"([A-Za-z][A-Za-z0-9_]*)\s*:\s*", raw[pos:])
                    if not name or name[1] in row:
                        raise ValueError("boston_additional_calendar_changed")
                    pos += name.end()
                    row[name[1]], pos = _js_string(raw, pos)
                rows.append(row)
                if len(rows) > 2000:
                    raise ValueError("boston_additional_record_limit")
    if not found:
        raise ValueError("boston_additional_calendar_changed")
    return rows


def _passim_manifest(payload, now):
    grouped = {}
    for e in _passim_literals(payload):
        if not all(k in e for k in ("postID", "title", "link", "date", "year", "month", "start", "showtime")):
            raise ValueError("boston_additional_calendar_changed")
        if NONPUBLIC.search(plain(e["title"])):
            continue
        day = date.fromisoformat(e["date"])
        start = _clock(day, e["showtime"])
        # The visible Show clock and explicit date are local. The calendar and
        # JSON-LD incorrectly append UTC to this same wall clock; do not shift it.
        if (e["year"] != str(day.year) or e["month"] != f"{day.month:02d}"
                or e["start"] != start.replace(tzinfo=None).isoformat() + "+0000"
                or not re.fullmatch(r"\d+", e["postID"])):
            raise ValueError("boston_additional_schedule_conflict")
        if not _within(start, None, now):
            continue
        item = grouped.setdefault(e["link"], _packet(PASSIM, e["link"], e["title"], e["postID"], [_occurrence(start)]))
        if item["native_id"] != e["postID"] or _title_key(item["title"]) != _title_key(e["title"]):
            raise ValueError("boston_additional_calendar_changed")
        occurrence = _occurrence(start)
        if occurrence not in item["occurrences"]:
            item["occurrences"].append(occurrence)
    for item in grouped.values():
        item["occurrences"].sort(key=lambda x: x["start"])
    return list(grouped.values())


def _passim_header_dates(text):
    text = plain(text)
    day_words = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*"
    text = re.sub(day_words, "", text, flags=re.I)
    match = re.fullmatch(r"([A-Za-z]+)\s+([\d\s,&-]+(?:and[\d\s,&-]+)?)\s*,\s*(20\d{2})", text)
    if not match or match[1].casefold() not in MONTHS:
        raise ValueError("boston_additional_schedule_conflict")
    days_text = match[2].replace("and", ",").replace("&", ",")
    days = []
    for part in re.split(r"\s*,\s*", days_text):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", part):
            first, last = map(int, re.split(r"\s*-\s*", part))
            if not 1 <= first <= last <= 31:
                raise ValueError("boston_additional_schedule_conflict")
            days.extend(range(first, last + 1))
        elif part.isdigit():
            days.append(int(part))
        else:
            raise ValueError("boston_additional_schedule_conflict")
    return {date(int(match[3]), MONTHS[match[1].casefold()], day) for day in days}


def _passim_venue(article, schema):
    content = article.select_one(".entry-content")
    # Venue declarations occur in the event lead. A musician's biography may
    # list unrelated past halls and must not move the current performance.
    prose = plain(" ".join(x.get_text(" ") for x in content.find_all(["p", "h3"], recursive=False)) if content else "")
    title = plain(article.select_one("h1.entry-title").get_text())
    links = {urlsplit(a["href"]).hostname for a in content.select("a[href]")} if content else set()
    if "Arts at the Armory" in prose and "artsatthearmory.org" in links and re.search(r"event takes place at\s+Arts at the Armory", prose, re.I):
        return "armory"
    if title.endswith(" at Arrow Street Arts") or (re.search(r"event takes place at\s+Arrow Street Arts", prose, re.I) and ("arrowstarts.org" in links or "www.arrowstarts.org" in links)):
        return "arrow"
    if re.search(r"event takes place at|\bat (?:the )?(?:armory|arrow street|[A-Z][a-z]+ (?:theatre|theater|hall|church))", title + " " + prose, re.I):
        raise ValueError("boston_additional_venue_unresolved")
    loc = schema.get("location") or {}
    a = loc.get("address") or {}
    if (loc.get("name"), a.get("streetAddress"), a.get("addressLocality"), a.get("addressRegion"), a.get("postalCode")) != ("Passim", "47 Palmer St", "Cambridge", "MA", "02138"):
        raise ValueError("boston_additional_venue_unresolved")
    return "passim"


def _passim_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    article = soup.select_one("article.event")
    heading = article.select_one("h1.entry-title") if article else None
    header_date = article.select_one("h3.event-time") if article else None
    schemas = [x for x in _jsonld(soup) if _title_key(x.get("name")) == _title_key(item["title"])]
    if (not article or article.get("id") != "post-" + item["native_id"] or not heading or not header_date
            or _title_key(heading.get_text()) != _title_key(item["title"]) or len(schemas) != 1):
        raise ValueError("boston_additional_detail_changed")
    days = _passim_header_dates(header_date.get_text(" "))
    starts = [timestamp(x["start"]) for x in item["occurrences"]]
    if any(start.astimezone(ZoneInfo(ZONE)).date() not in days for start in starts):
        raise ValueError("boston_additional_schedule_conflict")
    schema_start = timestamp(schemas[0].get("startDate"))
    if schema_start is None or schema_start.replace(tzinfo=None).date() not in days:
        raise ValueError("boston_additional_schedule_conflict")
    if schema_start.date() in {start.date() for start in starts} and schema_start.replace(tzinfo=None) not in {start.replace(tzinfo=None) for start in starts}:
        raise ValueError("boston_additional_schedule_conflict")
    show = article.select_one(".doors_show .show")
    if show:
        clocks = re.findall(r"\d{1,2}(?::\d{2})?\s*[AP]M", show.get_text(" "), re.I)
        if not clocks or any(start.time().replace(tzinfo=None) not in {_clock(start.date(), c).time() for c in clocks} for start in starts):
            raise ValueError("boston_additional_schedule_conflict")
    venue = _passim_venue(article, schemas[0])
    content = article.select_one(".entry-content")
    if not content:
        raise ValueError("boston_nightlife_description_missing")
    content = BeautifulSoup(str(content), "html.parser")
    for node in content.select(".artist-sidebar, .categories, .entry-title, iframe"):
        node.decompose()
    narrative = BeautifulSoup(str(content), "html.parser")
    for node in narrative.select("p"):
        if plain(node.get_text()).startswith("All tickets have a $3 processing fee and a $2 preservation fee."):
            node.decompose()
    _body(narrative)  # A generic processing-fee paragraph is not event prose.
    # Artist biographies, event-specific lead text and native ticket information
    # are all retained; only duplicate headings/categories and sidebar CTAs go.
    body = _body(content)
    lead = article.select_one("h2.entry-detail")
    if lead and plain(lead.get_text()) not in body:
        body = _validated_body(plain(lead.get_text()) + "\n" + body)
    return dict(body=body, venue_key=venue)


def _burren_dates(soup, now):
    headers = []
    for node in soup.select(".HEADER"):
        text = plain(node.get_text())
        m = re.fullmatch(r"([A-Z]+)\s+([A-Z]+)\s+(\d{1,2})(?:,?\s+(20\d{2}))?", text, re.I)
        if not m or m[1].casefold() not in WEEKDAYS or m[2].casefold() not in MONTHS:
            raise ValueError("boston_additional_calendar_changed")
        headers.append((node, WEEKDAYS[m[1].casefold()], MONTHS[m[2].casefold()], int(m[3]), int(m[4]) if m[4] else None))
    if not headers:
        raise ValueError("boston_additional_calendar_changed")
    years = [x[4] for x in headers]
    explicit = next((i for i, year in enumerate(years) if year is not None), None)
    if explicit is None:
        # A bounded missing-year inference requires agreement across the entire
        # ordered weekday/date sequence, never a recurring-date guess.
        candidates = []
        for year in range(now.year - 1, now.year + 2):
            trial = [year]
            for i in range(1, len(headers)):
                trial.append(trial[-1] + int(headers[i][2] < headers[i - 1][2]))
            try:
                dates = [date(y, x[2], x[3]) for y, x in zip(trial, headers)]
                if all(d.weekday() == x[1] for d, x in zip(dates, headers)) and any(abs((d - now.date()).days) <= 60 for d in dates):
                    candidates.append(trial)
            except ValueError:
                continue
        if len(candidates) != 1:
            raise ValueError("boston_additional_schedule_conflict")
        years = candidates[0]
    else:
        for i in range(explicit - 1, -1, -1):
            years[i] = years[i + 1] - int(headers[i][2] > headers[i + 1][2])
        for i in range(explicit + 1, len(headers)):
            inferred = years[i - 1] + int(headers[i][2] < headers[i - 1][2])
            if years[i] is not None and years[i] != inferred:
                raise ValueError("boston_additional_schedule_conflict")
            years[i] = inferred
    result = {}
    prior = None
    for year, (node, weekday, month, day, _) in zip(years, headers):
        value = date(year, month, day)
        if value.weekday() != weekday or prior is not None and value < prior:
            raise ValueError("boston_additional_schedule_conflict")
        prior = value
        result[id(node)] = value
    return result


def _burren_clocks(day, raw):
    text = plain(raw).rstrip(":").strip().lower().replace(" ", "").replace("–", "-")
    if "&" in text:
        return [_occurrence(_clock(day, x)) for x in text.split("&")]
    if "-" in text:
        first, last = text.split("-", 1)
        if not re.search(r"[ap]m$", first):
            suffix = re.search(r"([ap]m)$", last)
            if not suffix:
                raise ValueError("boston_additional_schedule_conflict")
            first += suffix[1]
        start, end = _clock(day, first), _clock(day, last)
        if end <= start:
            raise ValueError("boston_additional_schedule_conflict")
        return [_occurrence(start, end)]
    return [_occurrence(_clock(day, text))]


def _burren_manifest(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    if not re.search(r"247\s+ELM\s+ST\.?\s+D[aA][vV][iI][sS]\s+SQ\.?\s+SOMERVILLE\s+MA\s+02144", soup.get_text(" "), re.I):
        raise ValueError("boston_additional_venue_unresolved")
    days = _burren_dates(soup, now)
    grouped = {}
    for node in soup.select("span.BAND"):
        box = node.find_parent("table")
        header = node.find_previous(class_="HEADER")
        clock = box.select_one(".Time")
        room = box.select_one(".Room")
        body = box.select_one(".Text")
        if not header or id(header) not in days or not clock or not room or not body:
            raise ValueError("boston_additional_calendar_changed")
        title = plain(node.get_text())
        prose = body.get_text(" ", strip=True)
        if NONPUBLIC.search(title) or re.search(r"\b(?:closed|private) session\b", prose, re.I):
            continue
        venue = {"THE FRONT ROOM": "burren_front", "THE BACK ROOM": "burren_back"}.get(plain(room.get_text()).upper())
        if not venue:
            raise ValueError("boston_additional_venue_unresolved")
        occurrences = [x for x in _burren_clocks(days[id(header)], clock.get_text())
                       if _within(timestamp(x["start"]), timestamp(x["end"]), now)]
        if not occurrences:
            continue
        links = {urljoin(SOURCES[BURREN][0], a["href"]) for a in box.select("a[href]")
                 if urlsplit(urljoin(SOURCES[BURREN][0], a["href"])).hostname == "tickets.24hourmusic.com"}
        if len(links) > 1:
            raise ValueError("boston_additional_calendar_changed")
        url = links.pop() if links else SOURCES[BURREN][0]
        identity = _hash([url, title, venue])
        group_key = (url, title, venue, prose)
        if group_key not in grouped:
            grouped[group_key] = _packet(BURREN, url, title, identity, occurrences, venue=venue,
                body=str(body), needs_detail=url != SOURCES[BURREN][0])
        else:
            grouped[group_key]["occurrences"].extend(x for x in occurrences if x not in grouped[group_key]["occurrences"])
    return list(grouped.values())


def _burren_detail(item, payload):
    soup = BeautifulSoup(payload, "html.parser")
    title = soup.select_one("h2.event-page-head")
    content = soup.select_one(".event-performances-description")
    identity = parse_qs(urlsplit(item["url"]).query)["evt"][0]
    if (not title or not plain(title.get_text()) or not content
            or not re.search(r"iEvent\s*:\s*" + re.escape(identity) + r"\b", payload)):
        raise ValueError("boston_additional_detail_changed")
    if NONPUBLIC.search(plain(title.get_text())) or "'TicketingHasActivePerformances': 'False'" in payload:
        raise ValueError("boston_additional_schedule_conflict")
    body = _body(content)
    native_short = item.get("body", "")
    if native_short and plain(native_short) not in plain(body):
        body = _validated_body(native_short + "\n" + body)
    return dict(body=body, venue_key=item["venue_key"])


def _long_live_manifest(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    visible = plain(soup.get_text(" "))
    if not re.search(r"152 Hampden St,? Boston MA 02119", visible):
        raise ValueError("boston_additional_venue_unresolved")
    rules = [re.match(r"Every Thursday\s*//\s*Live Jazz in the taproom\s*//\s*6[–-]9pm\b", plain(x.get_text(" ")), re.I) for x in soup.select("p")]
    rule = next((x[0] for x in rules if x), None)
    if not rule:
        raise ValueError("boston_additional_calendar_changed")
    agenda = [x for x in soup.select(".sqs-html-content") if len(re.findall(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\b", x.get_text(" "))) >= 3]
    narratives = [x for x in soup.select(".sqs-html-content") if x.get_text(" ", strip=True).startswith("Join us for Thursday Jazz Nights")]
    if len(agenda) != 1 or len(narratives) != 1:
        raise ValueError("boston_additional_calendar_changed")
    paragraphs = []
    for node in narratives[0].find_all("p", recursive=False):
        if "Recent Press:" in node.get_text():
            break
        paragraphs.append(str(node))
    body = _body("".join(paragraphs))
    text = plain(agenda[0].get_text(" "))
    dates = list(re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b", text))
    queue = []
    for i, match in enumerate(dates):
        artist = text[match.end():dates[i + 1].start() if i + 1 < len(dates) else len(text)].strip()
        if not artist or NONPUBLIC.search(artist) or re.search(r"\bno (?:jazz|performance)\b", artist, re.I):
            continue
        candidates = []
        for year in range(now.year - 1, now.year + 2):
            day = date(year, MONTHS[match[1].lower()], int(match[2]))
            start, end = _clock(day, "6pm"), _clock(day, "9pm")
            if start < now + timedelta(days=28) and end > now:
                candidates.append((start, end))
        if not candidates:
            continue
        if len(candidates) != 1:
            raise ValueError("boston_additional_schedule_conflict")
        start, end = candidates[0]
        item = _packet(LONG_LIVE, SOURCES[LONG_LIVE][0], "Jazz Night — " + artist,
                       "jazz-night", [_occurrence(start, end)], venue="long_live", body=body,
                       published_schedule=rule + " | " + match[0] + " " + artist)
        if start.weekday() != 3:
            item["held"] = "boston_additional_schedule_conflict"
        queue.append(item)
    return queue


def _validate_queue(key, queue):
    if not isinstance(queue, list) or len(queue) > MAX_RECORDS:
        raise ValueError("boston_additional_record_limit")
    identities = set()
    for item in queue:
        _packet(key, item["url"], item["title"], item["native_id"], item["occurrences"], venue=item.get("venue_key"))
        if item.get("body") is not None and _validated_body(item["body"]) != item["body"]:
            raise ValueError("boston_additional_calendar_changed")
        if item.get("held") is not None and item["held"] not in HOLD_CODES:
            raise ValueError("boston_additional_calendar_changed")
        for occurrence in item["occurrences"]:
            identity = _identity(key, dict(item, **occurrence))
            if identity in identities:
                raise ValueError("boston_additional_calendar_changed")
            identities.add(identity)
    if len(identities) > MAX_RECORDS:
        raise ValueError("boston_additional_record_limit")
    return queue


def _seed(key, calendar, fetch, now, deadline_at):
    if key == LIZARD:
        if "tribe-events" not in calendar:
            raise ValueError("boston_additional_calendar_changed")
        if deadline_at is not None and monotonic() + MIN_SECONDS >= deadline_at:
            raise ValueError("collection_deadline")
        first = _tec_url(now)
        queue, count = _lizard_listing(fetch(first, "application/json"), now)
        pages = [_tec_url(now, page) for page in range(1, count + 1)]
    elif key in COMEDY_API:
        if deadline_at is not None and monotonic() + MIN_SECONDS >= deadline_at:
            raise ValueError("collection_deadline")
        queue = _comedy_listing(key, calendar, fetch(COMEDY_API[key], "application/json"), now)
        pages = [SOURCES[key][0]]
    else:
        queue = (_passim_manifest(calendar, now) if key == PASSIM else
                 _burren_manifest(calendar, now) if key == BURREN else _long_live_manifest(calendar, now))
        pages = [SOURCES[key][0]]
    queue = sorted(_validate_queue(key, queue), key=lambda x: (x["occurrences"][0]["start"], x["url"], x["native_id"]))
    return pages, queue


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        started_text = value["started_at"]
        started = timestamp(started_text)
        if (not isinstance(value, dict) or type(value["version"]) is not int or value["version"] != 1
                or value["source_key"] != key or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", started_text)
                or started > now + timedelta(seconds=60)
                or value["window_start"] != started.astimezone(ZoneInfo(ZONE)).date().isoformat()
                or not isinstance(value["pages"], list) or not 1 <= len(value["pages"]) <= MAX_PAGES
                or type(value["manifest_count"]) is not int or value["manifest_count"] != len(value["pages"])
                or type(value["cursor"]) is not int or not 0 <= value["cursor"] <= len(value["pages"])
                or value["manifest_hash"] != _hash({"pages": value["pages"], "seed": value["seed"]})
                or not isinstance(value["pending"], list) or value["pending_hash"] != _hash(value["pending"])
                or type(value["pending_cursor"]) is not int or not 0 <= value["pending_cursor"] <= len(value["pending"])
                or not isinstance(value["events"], list) or len(value["events"]) > MAX_RECORDS
                or not isinstance(value["diagnostics"], list) or len(value["diagnostics"]) > 400
                or len(value["row_hashes"]) != len(value["events"])):
            raise ValueError
        if now - started > timedelta(hours=4):
            return None
        expected_pages = ([_tec_url(started, page) for page in range(1, len(value["pages"]) + 1)]
                          if key == LIZARD else [SOURCES[key][0]])
        if value["pages"] != expected_pages:
            raise ValueError
        _validate_queue(key, value["seed"])
        _validate_queue(key, value["pending"])
        loaded = value["loaded_page"]
        if loaded is not None and (value["cursor"] >= len(value["pages"]) or loaded != value["pages"][value["cursor"]]):
            raise ValueError
        if loaded is None and (value["pending"] or value["pending_cursor"]):
            raise ValueError
        if loaded == value["pages"][0] and value["pending"] != value["seed"]:
            raise ValueError
        places = {VENUES[k] for k in VENUE_KEYS[key]}
        seen = set()
        for row in value["events"]:
            place = (row["venue_name"], row["venue_address"], row["venue_city"])
            if (row["id"] in seen or value["row_hashes"].get(row["id"]) != _hash(row)
                    or not re.fullmatch(r"boston:[a-f0-9]{64}", row["id"])
                    or not event_url(key, row["event_url"]) or place not in places
                    or _validated_body(row["description"]) != row["description"]
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or row.get("location_evidence_url") not in {VENUE_EVIDENCE[k] for k in VENUE_KEYS[key] if VENUES[k] == place}
                    or (row.get("lat"), row.get("lng")) != (reviewed_venue_location(key, *place[:2]) or (None, None))):
                raise ValueError
            seen.add(row["id"])
        if any(x.get("reason") not in HOLD_CODES or x.get("disposition") != "held" or not event_url(key, x.get("event_url")) for x in value["diagnostics"]):
            raise ValueError
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError("boston_additional_checkpoint_invalid") from None
    return deepcopy(value)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_FETCHES):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("boston_additional_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    anchor = timestamp(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() + MIN_SECONDS >= deadline_at:
        raise ValueError("collection_deadline")
    listing = fetch(SOURCES[key][0], "text/html")
    pages, seed = _seed(key, listing, fetch, anchor, deadline_at)
    digest = _hash({"pages": pages, "seed": seed})
    if state is None or state["manifest_hash"] != digest or state["pages"] != pages or state["seed"] != seed:
        if state is not None and current != anchor:
            # Keep the immutable original clock if still the same local date;
            # the current listing is the evidence for this reset, never old rows.
            anchor = current
            pages, seed = _seed(key, listing, fetch, anchor, deadline_at)
            digest = _hash({"pages": pages, "seed": seed})
        state = dict(version=1, source_key=key, started_at=anchor.isoformat(),
            window_start=anchor.astimezone(ZoneInfo(ZONE)).date().isoformat(),
            manifest_hash=digest, manifest_count=len(pages), cursor=0, pages=pages, seed=seed,
            pending=[], pending_hash=_hash([]), pending_cursor=0, loaded_page=None,
            events=[], row_hashes={}, diagnostics=[])
    prior = (state["cursor"], state["pending_cursor"], len(state["events"]), len(state["diagnostics"]))
    fetched, cap = 0, min(MAX_FETCHES, max(1, int(max_details)))
    def can_fetch():
        return fetched < cap and (deadline_at is None or monotonic() + MIN_SECONDS < deadline_at)
    while state["cursor"] < len(pages):
        page_url = pages[state["cursor"]]
        if state["loaded_page"] != page_url:
            if state["cursor"] == 0:
                queue = deepcopy(seed)
            else:
                if not can_fetch():
                    break
                fetched += 1
                queue, count = _lizard_listing(fetch(page_url, "application/json"), anchor)
                if count != len(pages):
                    raise ValueError("boston_additional_calendar_changed")
                _validate_queue(key, queue)
            state.update(pending=queue, pending_hash=_hash(queue), pending_cursor=0, loaded_page=page_url)
        queue = state["pending"]
        if state["pending_cursor"] == len(queue):
            state.update(cursor=state["cursor"] + 1, pending=[], pending_hash=_hash([]), pending_cursor=0, loaded_page=None)
            continue
        item = deepcopy(queue[state["pending_cursor"]])
        needs_detail = not item.get("held") and (key == PASSIM or key == BURREN and item.get("needs_detail"))
        if needs_detail and not can_fetch():
            break
        try:
            if item.get("held"):
                raise ValueError(item["held"])
            if needs_detail:
                fetched += 1
                detail = fetch(item["url"], "text/html")
                item.update(_passim_detail(item, detail) if key == PASSIM else _burren_detail(item, detail))
            for occurrence in item["occurrences"]:
                native = dict(item, **occurrence)
                try:
                    row = _row(key, native)
                    if row["id"] not in state["row_hashes"]:
                        state["events"].append(row)
                        state["row_hashes"][row["id"]] = _hash(row)
                except ValueError as exc:
                    if str(exc) not in HOLD_CODES:
                        raise
                    state["diagnostics"].append(dict(id=_identity(key, native), event_url=item["url"],
                        title=item["title"], starts_at=occurrence["start"], reason=str(exc), disposition="held"))
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            for occurrence in item["occurrences"]:
                state["diagnostics"].append(dict(id=_identity(key, dict(item, **occurrence)), event_url=item["url"],
                    title=item["title"], starts_at=occurrence["start"], reason=str(exc), disposition="held"))
        state["pending_cursor"] += 1
        if len(state["events"]) > MAX_RECORDS or len(state["diagnostics"]) > 400:
            raise ValueError("boston_additional_record_limit")
    complete = state["cursor"] == len(pages)
    after = (state["cursor"], state["pending_cursor"], len(state["events"]), len(state["diagnostics"]))
    if not complete and after == prior:
        raise ValueError("collection_deadline")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("boston_additional_checkpoint_size_limit")
    return dict(complete=complete, events=deepcopy(sorted(state["events"], key=lambda x: (x["starts_at"], x["id"]))) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now)
    if not result["complete"]:
        raise ValueError("boston_additional_checkpoint_required")
    return result["events"]
