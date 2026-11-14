"""Three reviewed local venue calendars, with complete publisher descriptions.

The callback is the existing guarded PublisherHTTP transport.  Every source
uses a complete-only checkpoint: no partial Wix month or detail set may stage.
The public HTML, rather than a search excerpt, is the source of every body.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import plain, record, timestamp


ZONE = "America/New_York"
SLACK = "slack_tide_brewing_nj"
TOMASELLO = "tomasello_winery_hammonton_nj"
LIZZIE = "lizzie_rose_music_room_nj"
SOURCES = {
    SLACK: ("https://www.slacktidebrewingco.com/events", "html", "html"),
    TOMASELLO: ("https://tomasellowinery.com/events", "html", "html"),
    LIZZIE: ("https://www.lizzierosemusic.com/", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = frozenset(SOURCES)
CONTRACT = "atlantic-city-local-venues-v1-full-native-20261114"
MAX_DESCRIPTION = 12000
MAX_UNITS = 100
MAX_RECORDS = 200
MAX_CHECKPOINT_BYTES = 900_000
MAX_DETAILS_PER_CHUNK = 2
MIN_DETAIL_SECONDS = 12
VENUES = {
    SLACK: ("Slack Tide Brewing Company", "1879 US Highway 9, Clermont, NJ 08210", "Clermont"),
    TOMASELLO: ("Tomasello Winery - Hammonton", "225 North White Horse Pike, Hammonton, NJ 08037", "Hammonton"),
    LIZZIE: ("Lizzie Rose Music Room", "217 East Main Street, Tuckerton, NJ 08087", "Tuckerton"),
}
# Literal identities deliberately do not bind to the mutable VENUES constants.
# Slack's point is published in its Wix event location for this exact street;
# NJ OGIS corroborates it within 25 m.  The other two are score-100 NJ OGIS
# PointAddress results.  These are venue/address points, not entrances/rooms.
REVIEWED_VENUE_POINTS = {
    (SLACK, "Slack Tide Brewing Company", "1879 US Highway 9, Clermont, NJ 08210"):
        (39.1444625, -74.7666581),
    (TOMASELLO, "Tomasello Winery - Hammonton", "225 North White Horse Pike, Hammonton, NJ 08037"):
        (39.653451000003, -74.796021000001),
    (LIZZIE, "Lizzie Rose Music Room", "217 East Main Street, Tuckerton, NJ 08087"):
        (39.604320000003, -74.336260500001),
}
MONTHS = {name.lower(): n for n, name in enumerate(
    ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")) if name}
MONTH_RE = r"(?:January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|August|Aug|September|Sept|Sep|October|Oct|November|Nov|December|Dec)"
DAY_RE = re.compile(r"(?P<month>" + MONTH_RE + r")\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:\s*,\s*|\s+)(?P<year>20\d{2})\b", re.I)
WEEK_RE = re.compile(r"\b(Mon(?:day)?|Tue(?:s(?:day)?)?|Wed(?:nesday)?|Thu(?:rs(?:day)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\.?[\s,]*$", re.I)
CLOCK_RE = r"\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)"
NONPUBLIC = re.compile(r"\b(?:sold\s*out|cancell?ed|postponed|private\s+(?:event|party)|members?[- ]only|invitation[- ]only)\b", re.I)
SLACK_APP = "140603ad-af8d-84a5-2c80-a0f60cb47351"
SLACK_WIDGET = "widgetcomp-k54aq1hm"
SLACK_INSTANCE = "b522270d-dc0f-4579-9bdb-f0c3b6cf290a"
LIZZIE_MONTH_PATHS = {"january": "jan", **{name: name for name in MONTHS if name != "january"}}
LIZZIE_TICKETS = "https://www.lizzierosemusic.com/www-lizzierosemusic-com-purchase-tickets"
MAX_TICKET_PAGES = 10
TOM_LINKS = {"/sip---shop": "tom_shop", "/opera-gala": "tom_opera", "/sips---sounds-hammonton": "tom_music"}
# The November music card omits its year. This exact reviewed native edition is
# tied to 2026, never rolled forward when the same page remains on-line.
REVIEWED_MUSIC_YEAR = 2026
REVIEWED_MUSIC_DIGEST = "0b0c32a1ccf99582ae6557dd7f0188ad4b2632634a296b325525bc4d48cd250a"


class Hold(ValueError):
    """A publisher record cannot safely become a public occurrence."""


def _text(node):
    return re.sub(r"\s+", " ", (node.get_text(" ", strip=True) if node else "").replace("\u200b", "").replace("\ufeff", "")).strip()


def _body(node):
    value = narrative(node).replace("\u200b", "").replace("\ufeff", "")
    value = "\n".join(line.strip() for line in value.splitlines() if line.strip())
    return _full(value)


def _full(value):
    # Already normalized text must never be parsed as HTML again.
    if not isinstance(value, str) or not value.strip():
        raise Hold("local_venue_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise Hold("local_venue_description_limit")
    return value


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or p.query or p.fragment:
            return False
        if key == SLACK:
            return bool(re.fullmatch(r"/event-details/[a-z0-9-]+", p.path))
        if key == TOMASELLO:
            return p.path in {"/events", *TOM_LINKS}
        return (p.path in {"/" + path for path in LIZZIE_MONTH_PATHS.values()}
                or bool(re.fullmatch(r"/product-page/[a-z0-9-]+", p.path)))
    except ValueError:
        return False


def reviewed_venue_location(key, venue, street):
    return REVIEWED_VENUE_POINTS.get((key, venue, street))


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _clock(day, clock):
    value = re.sub(r"\s+", "", clock).upper()
    try:
        return timestamp(datetime.combine(day, datetime.strptime(value, "%I:%M%p" if ":" in value else "%I%p").time()), ZONE)
    except ValueError:
        raise Hold("local_venue_clock_invalid") from None


def _month(value):
    return next((n for name, n in MONTHS.items() if name.startswith(value.lower().rstrip("."))), None)


def _day_match(match, text, *, expected_month=None, expected_year=None):
    try:
        day = date(int(match["year"]), _month(match["month"]), int(match["day"]))
    except (ValueError, TypeError):
        raise Hold("local_venue_date_invalid") from None
    if ((expected_month is not None and day.month != expected_month)
            or (expected_year is not None and day.year != expected_year)):
        raise Hold("local_venue_calendar_date_conflict")
    weekday = WEEK_RE.search(text[:match.start()])
    if weekday and day.strftime("%a").lower() != weekday[1][:3].lower():
        raise Hold("local_venue_weekday_conflict")
    return day


def _date(text, *, expected_month=None, expected_year=None):
    matches = list(DAY_RE.finditer(text))
    if len(matches) != 1:
        raise Hold("local_venue_date_missing_or_ambiguous")
    return _day_match(matches[0], text, expected_month=expected_month, expected_year=expected_year)


def _range(day, text):
    matches = list(re.finditer(r"(?P<first>\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)\s*(?:[-–—]|\bto\b)\s*(?P<last>" + CLOCK_RE + r")", text, re.I))
    if not matches:
        return None
    ranges = set()
    for m in matches:
        first = m["first"].strip()
        if not re.search(r"[AP]M$", first, re.I):
            first += re.search(r"[AP]M$", m["last"], re.I)[0]
        start, end = _clock(day, first), _clock(day, m["last"])
        if end <= start:
            raise Hold("local_venue_clock_conflict")
        ranges.add((start, end))
    if len(ranges) != 1:
        raise Hold("local_venue_clock_conflict")
    return next(iter(ranges))


def _photo(key, value):
    # The candidate asset host static.wixstatic.com returned robots HTTP403
    # during this review. Do not enqueue it for a downstream media retry.
    return None


def _row(key, title, start, end, url, identity, body, now, image=None):
    _full(body)
    if not event_url(key, url) or not isinstance(title, str) or not title.strip() or len(title) > 180:
        raise Hold("local_venue_event_identity")
    if not start.tzinfo or (end is not None and (not end.tzinfo or end <= start)):
        raise Hold("local_venue_clock_conflict")
    if not _within(start, end, now):
        return None
    venue, street, city = VENUES[key]
    point = reviewed_venue_location(key, venue, street) or (None, None)
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue, street, city, url, sha256(identity.encode()).hexdigest(),
                 lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row:
        row.update(description=body, native_event_id=identity, attendance_mode="in_person", timezone=ZONE,
                   location_provenance=("reviewed_publisher_venue_location" if key == SLACK and point[0] is not None
                                        else "reviewed_nj_ogis_point_address" if point[0] is not None
                                        else "reviewed_venue_street_address_pending_geocode"))
        if candidate := _photo(key, image):
            row["image_url"] = candidate
    return row


def _diagnostic(unit, reason, *, identity=None, title=None):
    return {"unit_id": unit["id"], "event_url": unit["url"], "native_event_id": identity or unit["id"],
            "title": title or unit.get("title", ""), "disposition": "held", "reason": reason}


def _slack_manifest(soup, now):
    if "1879 Route 9" not in _text(soup) or "Clermont, NJ 08210" not in _text(soup):
        raise ValueError("local_venue_location_changed")
    try:
        warmup = json.loads(soup.select_one("#wix-warmup-data").get_text())
        listing = warmup["appsWarmupData"][SLACK_APP][SLACK_WIDGET]["events"]
        events = listing["events"]
    except (AttributeError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("local_venue_manifest_invalid") from None
    if (not isinstance(events, list) or len(events) > MAX_UNITS or listing.get("hasMore") is not False
            or listing.get("moreLoading") is not False):
        raise ValueError("local_venue_manifest_incomplete")
    cards = soup.select('a[data-hook="title"][href]')
    if len(cards) != len(events):
        raise ValueError("local_venue_manifest_incomplete")
    links = {}
    for card in cards:
        title = _text(card)
        if not title or title in links:
            raise ValueError("local_venue_manifest_invalid")
        links[title] = card["href"]
    units = []
    for event in events:
        title, uid = event.get("title"), event.get("id")
        if (event.get("instanceId") != SLACK_INSTANCE or not isinstance(uid, str)
                or not re.fullmatch(r"[a-f0-9-]{36}", uid) or title not in links):
            raise ValueError("local_venue_manifest_invalid")
        config = event.get("scheduling", {}).get("config", {})
        start, end = timestamp(config.get("startDate")), timestamp(config.get("endDate"))
        if config.get("timeZoneId") != ZONE or config.get("scheduleTbd") or not start:
            raise ValueError("local_venue_schedule_unverified")
        if config.get("endDateHidden"):
            end = None
        if not _within(start, end, now):
            continue
        location = event.get("location", {})
        street = location.get("fullAddress", {}).get("streetAddress", {})
        if (str(street.get("number")) != "1879" or street.get("name") not in ("U.S. 9", "US-9", "Route 9")
                or location.get("fullAddress", {}).get("subdivision") != "NJ"
                or location.get("name") not in ("Slack Tide Brewing Company", "Slack Tide Brewing Co", "Slack Tide Brewery", "Dennis")):
            raise ValueError("local_venue_location_changed")
        reg = event.get("registration", {})
        unit = {"id": uid, "url": links[title], "type": "slack", "title": title,
                "start": start.isoformat(), "end": end.isoformat() if end else None,
                "description": event.get("description", ""), "slug": event.get("slug"),
                "image": event.get("mainImage", {}).get("url"), "hold": None}
        if event.get("status") != 0 or reg.get("restrictedTo") not in (0, None):
            unit["hold"] = "local_venue_nonpublic_or_cancelled"
        elif not event_url(SLACK, unit["url"]):
            # These two events link only off-site. Toast robots timed out and
            # Square's robots returned a server error; no alternate access.
            unit["hold"] = "external_full_description_access_unavailable"
        elif urlsplit(unit["url"]).path != "/event-details/" + str(event.get("slug")):
            raise ValueError("local_venue_manifest_invalid")
        units.append(unit)
    return units


def _slack_detail(unit, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    blocks = soup.select('script[type="application/ld+json"]')
    values = [json.loads(block.get_text()) for block in blocks]
    events = [value for value in values if isinstance(value, dict) and value.get("@type") == "Event"]
    title = soup.select_one('[data-hook="event-title"]')
    if len(events) != 1 or not title or _text(title) != unit["title"]:
        raise ValueError("local_venue_detail_identity")
    event = events[0]
    try:
        native = json.loads(soup.select_one("#wix-warmup-data").get_text())["appsWarmupData"][SLACK_APP]["EventsPageInitialState"]["event"]["event"]
    except (AttributeError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("local_venue_detail_identity") from None
    if (native.get("id") != unit["id"] or native.get("title") != unit["title"]
            or native.get("instanceId") != SLACK_INSTANCE or native.get("slug") != unit["slug"]):
        raise ValueError("local_venue_detail_identity")
    location = event.get("location", {})
    if event.get("name") != unit["title"] or location.get("url") != unit["url"]:
        raise ValueError("local_venue_detail_identity")
    start, end = timestamp(event.get("startDate")), timestamp(event.get("endDate"))
    native_clock = native.get("scheduling", {}).get("config", {})
    native_end = None if native_clock.get("endDateHidden") else timestamp(native_clock.get("endDate"))
    if (start != timestamp(unit["start"]) or end != timestamp(unit["end"])
            or start != timestamp(native_clock.get("startDate")) or end != native_end
            or native_clock.get("timeZoneId") != ZONE or native_clock.get("scheduleTbd")):
        raise Hold("local_venue_schedule_conflict")
    if (event.get("eventStatus") != "https://schema.org/EventScheduled"
            or event.get("eventAttendanceMode") != "https://schema.org/OfflineEventAttendanceMode"
            or native.get("status") != 0 or native.get("registration", {}).get("restrictedTo") not in (0, None)):
        raise Hold("local_venue_nonpublic_or_cancelled")
    if not re.fullmatch(r"1879 (?:US-9|Route 9), (?:Ocean View|CAPE MAY CH|Cape May Court House), NJ (?:08210|08230), USA", str(location.get("address"))):
        raise Hold("local_venue_location_changed")
    header = soup.select_one('[data-hook="event-description"]')
    about = soup.select_one('[data-hook="about-section"] [data-id="content-viewer"]')
    # Wix's JSON-LD is only an introduction, and its server-rendered About
    # stops at the Read More boundary. The exact-identity native Ricos document
    # is the complete publisher body; map every text node, including its tail.
    def rich_text(node):
        if node is None:
            return ""
        if not isinstance(node, dict):
            raise Hold("local_venue_description_incomplete")
        if node.get("type") == "TEXT":
            text = node.get("textData", {}).get("text")
            if not isinstance(text, str):
                raise Hold("local_venue_description_incomplete")
            return text
        kind = node.get("type")
        if kind not in (None, "PARAGRAPH", "HEADING", "BULLETED_LIST", "ORDERED_LIST", "LIST_ITEM", "BLOCKQUOTE", "DIVIDER", "LINE_BREAK"):
            raise Hold("local_venue_description_incomplete")
        children = node.get("nodes", [])
        if not isinstance(children, list):
            raise Hold("local_venue_description_incomplete")
        value = "".join(rich_text(child) for child in children)
        return value + ("\n" if kind in ("PARAGRAPH", "HEADING", "LIST_ITEM", "BLOCKQUOTE", "LINE_BREAK") else "")
    def content_chars(value):
        return re.sub(r"\s+", "", value.replace("\u200b", "").replace("\ufeff", ""))
    rich = rich_text(native.get("longDescription"))
    full = "\n".join(re.sub(r"[\t\r\f\v ]+", " ", line).strip() for line in rich.splitlines() if line.strip())
    if (not content_chars(full).startswith(content_chars(_text(about)))
            or content_chars(str(event.get("description") or "")) != content_chars(_text(header))):
        raise Hold("local_venue_description_incomplete")
    parts = []
    if header and _text(header):
        short = _body(header)
        if plain(short) != plain(event.get("description")) or plain(short) != plain(unit["description"]):
            raise ValueError("local_venue_detail_identity")
        parts.append(short)
    if full:
        full = _full(full)
        if full not in parts:
            parts.append(full)
    body = _full("\n\n".join(parts))
    if NONPUBLIC.search(unit["title"]) or any(NONPUBLIC.search(_text(x)) for x in soup.select('[data-hook="rsvp-button"]')):
        raise Hold("local_venue_nonpublic_or_sold_out")
    # A current, specific event paragraph contradicts its structured date.
    # Check dates introduced as the event's own date, not preorder deadlines.
    own_dates = re.findall(r"(?:Date:\s*|on\s+)(?:Friday,?\s+|Saturday,?\s+)?(" + MONTH_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?", body, re.I)
    if any((_month(month), int(day)) != (start.astimezone(ZoneInfo(ZONE)).month, start.astimezone(ZoneInfo(ZONE)).day) for month, day in own_dates):
        raise Hold("local_venue_description_date_conflict")
    return [_row(SLACK, unit["title"], start, end, unit["url"], unit["id"], body, now, unit.get("image"))]


def _tom_sections(soup):
    sections = []
    for heading in soup.select("h2"):
        if _text(heading).casefold() != "hammonton":
            continue
        node = heading.parent
        while node.parent and len(node.parent.select("h2")) == 1:
            node = node.parent
        if not node.select("h4"):
            raise ValueError("local_venue_manifest_invalid")
        sections.append(node)
    if not sections:
        raise ValueError("local_venue_manifest_invalid")
    return sections


def _tom_manifest(soup, now):
    units = []
    for section in _tom_sections(soup):
        headings = [_text(h) for h in section.select("h4") if _text(h)]
        title = headings[0]
        clone = BeautifulSoup(str(section), "html.parser")
        for node in clone.select("h2,h4,img,button"):
            node.decompose()
        for node in clone.select("a"):
            # Keep prose-bearing inline link text, dropping only standalone
            # navigation/CTA controls outside the native paragraph widgets.
            if node.find_parent(class_="dmNewParagraph"):
                node.unwrap()
            else:
                node.decompose()
        body = _body(clone)
        links = [urljoin(SOURCES[TOMASELLO][0], a["href"]) for a in section.select("a[href]")]
        detail = next((url for url in links if urlsplit(url).hostname == ALLOWED_HOSTS[TOMASELLO][0] and urlsplit(url).path in TOM_LINKS), None)
        unit = {"id": "tomasello:" + str(section.get("id") or sha256(title.encode()).hexdigest()),
                "url": detail or SOURCES[TOMASELLO][0], "type": TOM_LINKS[urlsplit(detail).path] if detail else "tom_inline",
                "title": title, "body": body, "headings": headings, "all_text": _text(section), "hold": None}
        if NONPUBLIC.search(unit["all_text"]):
            unit["hold"] = "local_venue_nonpublic_or_sold_out"
        units.append(unit)
    return units


def _tom_inline(unit, now):
    body, title = unit["body"], unit["title"]
    date_text = "\n".join(unit["headings"][1:]) or body
    day = _date(date_text)
    clock_header = re.findall(r"\bat\s+(" + CLOCK_RE + r")", date_text, re.I)
    schedule = _range(day, body)
    if "YOGA, PILATES, MIMOSA BRUNCH" in title.upper():
        # Two explicitly offered participation options; no guessed brunch end.
        yoga = re.search(r"At\s+(" + CLOCK_RE + r"),\s+enjoy\s+Flow & Unwind", body, re.I)
        pilates = re.search(r"At\s+(" + CLOCK_RE + r"),\s+join\s+Faith Jobson for Mat Pilates", body, re.I)
        if not yoga or not pilates:
            raise Hold("local_venue_participation_changed")
        return [_row(TOMASELLO, label, _clock(day, match[1]), None, unit["url"], unit["id"] + ":" + slug + ":" + day.isoformat(), body, now)
                for label, slug, match in [("Flow & Unwind Yoga, Mimosa Brunch & Shopping", "yoga", yoga), ("Mat Pilates, Mimosa Brunch & Shopping", "pilates", pilates)]]
    if schedule:
        start, end = schedule
        if clock_header and (len(set(clock_header)) != 1 or _clock(day, clock_header[0]) != start):
            raise Hold("local_venue_clock_conflict")
    elif len(clock_header) == 1:
        start, end = _clock(day, clock_header[0]), None
    else:
        raise Hold("local_venue_clock_missing")
    return [_row(TOMASELLO, title, start, end, unit["url"], unit["id"] + ":" + start.isoformat(), body, now)]


def _tom_shop(unit, soup, now):
    nodes = [x for x in soup.select(".dmNewParagraph") if x.select_one("h2") and "Pop Up Sip & Shop" in _text(x)]
    if len(nodes) != 1:
        raise ValueError("local_venue_detail_identity")
    node = nodes[0]
    header = _text(node.select_one("h4"))
    parent = re.search(r"(" + MONTH_RE + r")\s+(\d{1,2})\s*&\s*(\d{1,2}),\s*(20\d{2})", unit["body"], re.I)
    detail = re.search(r"(" + MONTH_RE + r")\s+(\d{1,2})\s*&\s*(\d{1,2})", header, re.I)
    if not parent or not detail or tuple(x.lower() for x in parent.groups()[:3]) != tuple(x.lower() for x in detail.groups()):
        raise Hold("local_venue_schedule_conflict")
    body = _body(node)
    result = []
    for digit in parent.groups()[1:3]:
        day = date(int(parent[4]), _month(parent[1]), int(digit))
        schedule = _range(day, header)
        if not schedule:
            raise Hold("local_venue_clock_missing")
        result.append(_row(TOMASELLO, "Pop Up Sip & Shop", *schedule, unit["url"], unit["id"] + ":" + day.isoformat(), body, now))
    return result


def _tom_opera(unit, soup, now):
    rows, diagnostics = [], []
    nodes = [x for x in soup.select(".dmNewParagraph") if x.select_one("h4") and _text(x.select_one("h4")).lower() == "holiday opera gala"]
    if not nodes:
        raise ValueError("local_venue_detail_identity")
    for node in nodes:
        texts = [_text(h) for h in node.select("h4") if _text(h)]
        identity = unit["id"] + ":" + str(node.get("id"))
        try:
            day = _date(texts[1])
            clock = re.findall(CLOCK_RE, texts[1], re.I)
            if len(clock) != 1:
                raise Hold("local_venue_clock_missing")
            container = node
            while container.parent and len([h for h in container.parent.select("h4") if "holiday opera gala" == _text(h).lower()]) == 1:
                container = container.parent
            if NONPUBLIC.search(_text(container)):
                raise Hold("local_venue_nonpublic_or_sold_out")
            body = _full(unit["body"] + "\n\n" + _body(node))
            rows.append(_row(TOMASELLO, "Holiday Opera Gala", _clock(day, clock[0]), None, unit["url"], identity + ":" + day.isoformat(), body, now))
        except Hold as exc:
            diagnostics.append(_diagnostic(unit, str(exc), identity=identity, title="Holiday Opera Gala"))
    return rows, diagnostics


def _tom_music(unit, soup, now):
    heading = next((h for h in soup.select("h2") if _text(h).casefold() == "hammonton incrediblu music series"), None)
    nodes = [x for x in soup.select(".dmNewParagraph") if len(x.select("h4")) > 1]
    if not heading or len(nodes) != 1:
        raise ValueError("local_venue_detail_identity")
    listing = nodes[0]
    listing_body = _body(listing)
    if sha256(listing_body.encode()).hexdigest() != REVIEWED_MUSIC_DIGEST:
        raise Hold("local_venue_undated_edition_requires_review")
    intro = heading.parent
    while intro.parent and len(intro.parent.select("h2")) == 1 and not intro.parent.select("h4"):
        intro = intro.parent
    description = _body(intro)
    rows = []
    for h in listing.select("h4"):
        text = []
        for sibling in h.next_siblings:
            if getattr(sibling, "name", None) == "h4":
                break
            if getattr(sibling, "get_text", None) and _text(sibling):
                text.append(_text(sibling))
        detail = " ".join(text)
        match = re.search(r"(" + MONTH_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?", detail, re.I)
        if not match:
            raise Hold("local_venue_date_missing_or_ambiguous")
        day = date(REVIEWED_MUSIC_YEAR, _month(match[1]), int(match[2]))
        weekday = WEEK_RE.search(detail[:match.start()])
        if weekday and day.strftime("%a").lower() != weekday[1][:3].lower():
            raise Hold("local_venue_weekday_conflict")
        schedule = _range(day, detail)
        if not schedule:
            raise Hold("local_venue_clock_missing")
        title = "IncrediBlu Music Series: " + _text(h)
        body = _full(description + "\n\n" + _body(h) + "\n" + "\n".join(text))
        rows.append(_row(TOMASELLO, title, *schedule, unit["url"], unit["id"] + ":" + day.isoformat(), body, now))
    return rows


def _lizzie_manifest(soup, now):
    if "217 East Main Street, Tuckerton NJ" not in _text(soup):
        raise ValueError("local_venue_location_changed")
    # Only pages actually linked by an earlier native catalogue page will be
    # fetched. Reserving bounded slots makes the checkpoint queue immutable.
    units = [{"id": "lizzie:tickets:" + str(page), "url": LIZZIE_TICKETS + ("?page=" + str(page) if page > 1 else ""),
              "type": "lizzie_tickets", "page": page, "title": "Native ticket availability", "hold": None}
             for page in range(1, MAX_TICKET_PAGES + 1)]
    month_pairs = set()
    day = now.astimezone(ZoneInfo(ZONE)).date()
    end = (now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date()
    while day <= end:
        month_pairs.add((day.year, day.month))
        day += timedelta(days=1)
    for year, month in sorted(month_pairs):
        name = next(name for name, n in MONTHS.items() if n == month)
        anchors = [a for a in soup.select("a[href]") if _text(a).lower() == name]
        urls = {urljoin(SOURCES[LIZZIE][0], a["href"]) for a in anchors}
        if len(urls) != 1:
            raise ValueError("local_venue_manifest_incomplete")
        url = urls.pop()
        if url != SOURCES[LIZZIE][0] + LIZZIE_MONTH_PATHS[name]:
            raise ValueError("local_venue_manifest_invalid")
        units.append({"id": "lizzie:" + name + ":" + str(year), "url": url, "type": "lizzie_month", "month": month, "year": year, "title": name, "hold": None})
    return units


def _lizzie_tickets(soup):
    products = soup.select('[data-hook="product-list-grid-item"]')
    if not products:
        raise ValueError("local_venue_detail_identity")
    result = {}
    for product in products:
        link = product.select_one('a[data-hook="product-item-product-details-link"][href]')
        title = product.select_one('[data-hook="product-item-name"]')
        if not link or not title:
            raise ValueError("local_venue_detail_identity")
        url = link["href"]
        if not event_url(LIZZIE, url):
            continue
        if url in result:
            raise ValueError("local_venue_duplicate_identity")
        status = product.select_one('[data-hook="product-item-out-of-stock"]')
        result[url] = {"title": _text(title), "availability": _text(status) if status else ""}
    pages = set()
    for link in soup.select('[data-hook="product-list-pagination-link-seo-link"][href]'):
        match = re.fullmatch(re.escape(LIZZIE_TICKETS) + r"(?:\?page=([1-9][0-9]*))?", link["href"])
        page = int(match[1] or 1) if match else None
        if page is None or page > MAX_TICKET_PAGES:
            raise ValueError("local_venue_manifest_incomplete")
        pages.add(page)
    return result, sorted(pages)


def _catalog(state, *, require_complete=False):
    tickets, pages, fetched = {}, {1}, set()
    for result in state["results"]:
        if "tickets" in result:
            if set(tickets).intersection(result["tickets"]):
                raise ValueError("local_venue_manifest_incomplete")
            tickets.update(result["tickets"])
            pages.update(result["ticket_pages"])
            fetched.add(int(result["unit_id"].rsplit(":", 1)[-1]))
    if require_complete and pages.difference(fetched):
        raise ValueError("local_venue_manifest_incomplete")
    return tickets, pages


def _needs_fetch(unit, state):
    if unit.get("hold") or unit["type"] == "tom_inline":
        return False
    if unit["type"] == "lizzie_tickets":
        return unit["page"] in _catalog(state)[1]
    return True


def _lizzie_month(unit, soup, now, tickets):
    main = soup.select_one("main")
    expected = next(name.title() for name, n in MONTHS.items() if n == unit["month"]) + " " + str(unit["year"])
    if not main or not _text(main).startswith(expected):
        raise ValueError("local_venue_detail_identity")
    cards = main.select(".wixui-repeater__item")
    if not cards or len(cards) > MAX_RECORDS:
        raise ValueError("local_venue_manifest_incomplete")
    rows, diagnostics = [], []
    for card in cards:
        identity = unit["id"] + ":" + str(card.get("id"))
        title = ""
        try:
            texts = [n for n in card.select(".wixui-rich-text") if _text(n)]
            if len(texts) != 2:
                raise Hold("local_venue_description_container_changed")
            title, body = _text(texts[0]), _body(texts[1])
            day = _date(body, expected_month=unit["month"], expected_year=unit["year"])
            clocks = re.findall(r"SHOWTIME\s*[-:]?\s*(" + CLOCK_RE + r")", body, re.I)
            if len(clocks) != 1:
                raise Hold("local_venue_clock_missing")
            start = _clock(day, clocks[0])
            if not _within(start, None, now):
                continue
            # Wix may wrap a decorative image in a blank wix.com link. Only
            # the publisher's labelled participation action identifies a show.
            links = [a["href"] for a in card.select("a[href]")
                     if _text(a).casefold() in {"buy tickets", "rsvp"}]
            if not links and any(_text(button).casefold() == "buy tickets" for button in card.select("button")):
                # One current card's button has no href. Resolve it only from
                # this publisher's exact artist + dated product identity.
                matches = []
                for candidate, ticket in tickets.items():
                    artist = re.split(r"\s*[-–—]\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)", ticket["title"], maxsplit=1, flags=re.I)[0]
                    if artist.casefold().strip() == title.casefold():
                        try:
                            if _date(ticket["title"]) == day:
                                matches.append(candidate)
                        except Hold:
                            pass
                links = matches
            if len(links) != 1:
                raise Hold("local_venue_event_identity")
            url = links[0]
            if event_url(LIZZIE, url) and "/product-page/" in url:
                ticket = tickets.get(url)
                if not ticket:
                    raise Hold("local_venue_ticket_identity_unverified")
                ticket_day = _date(ticket["title"])
                if ticket_day != day:
                    raise Hold("local_venue_schedule_conflict")
                if NONPUBLIC.search(ticket["availability"]):
                    raise Hold("local_venue_nonpublic_or_sold_out")
                # At-door-only availability is explicitly publisher-qualified.
                if ticket["availability"]:
                    body = _full(body + "\n\n" + ticket["availability"])
            elif re.fullmatch(r"https://www\.moviesonmainstreet\.com/event-details/[a-z0-9-]+", url):
                # The venue publishes the complete film programme itself.
                # Link the page actually ingested; no off-site fetch or guess.
                url = unit["url"]
            else:
                raise Hold("local_venue_event_identity")
            if NONPUBLIC.search(title):
                raise Hold("local_venue_nonpublic_or_sold_out")
            img = card.select_one("img[src]")
            rows.append(_row(LIZZIE, title, start, None, url, identity, body, now, img.get("src") if img else None))
        except Hold as exc:
            diagnostics.append(_diagnostic(unit, str(exc), identity=identity, title=title))
    return rows, diagnostics


def _manifest(key, payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    units = (_slack_manifest(soup, now) if key == SLACK else _tom_manifest(soup, now) if key == TOMASELLO else _lizzie_manifest(soup, now))
    if len(units) > MAX_UNITS or len({unit["id"] for unit in units}) != len(units):
        raise ValueError("local_venue_manifest_invalid")
    return units


def _checkpoint(value, key, now):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != 1 or value.get("contract") != CONTRACT
            or value.get("source_key") != key or len(json.dumps(value).encode()) > MAX_CHECKPOINT_BYTES
            or type(value.get("cursor")) is not int or type(value.get("manifest_count")) is not int
            or not 0 <= value["cursor"] <= value["manifest_count"] <= MAX_UNITS
            or not isinstance(value.get("queue"), list) or len(value["queue"]) != value["manifest_count"]
            or any(not isinstance(item, str) for item in value["queue"])
            or len(set(value["queue"])) != len(value["queue"])
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("manifest_hash")))
            or not isinstance(value.get("results"), list) or len(value["results"]) != value["cursor"]
            or not isinstance(value.get("events"), list) or len(value["events"]) > MAX_RECORDS
            or not isinstance(value.get("diagnostics"), list) or len(value["diagnostics"]) > 400):
        raise ValueError("local_venue_checkpoint_invalid")
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)", value["started_at"]):
            raise ValueError
        started = datetime.fromisoformat(value["started_at"])
        anchor = date.fromisoformat(value["window_start"])
        if (not started.tzinfo or started.utcoffset() != timedelta(0)
                or anchor != started.astimezone(ZoneInfo(ZONE)).date()):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("local_venue_checkpoint_invalid") from None
    if now < started or now - started > timedelta(hours=4):
        return None
    ids = set()
    for index, result in enumerate(value["results"]):
        if (not isinstance(result, dict) or result.get("unit_id") != value["queue"][index]
                or not isinstance(result.get("events"), list) or not isinstance(result.get("diagnostics"), list)):
            raise ValueError("local_venue_checkpoint_invalid")
        for row in result["events"]:
            if (not isinstance(row, dict) or not event_url(key, row.get("event_url"))
                    or not isinstance(row.get("title"), str) or not 0 < len(row["title"].strip()) <= 180
                    or row.get("timezone") != ZONE or row.get("attendance_mode") != "in_person"
                    or row.get("category") != ""
                    or not isinstance(row.get("native_event_id"), str) or not 0 < len(row["native_event_id"]) <= 500
                    or row.get("id") != sha256(row["native_event_id"].encode()).hexdigest()
                    or row["id"] in ids or not isinstance(row.get("description"), str)
                    or not 0 < len(row["description"].strip()) <= MAX_DESCRIPTION
                    or (row.get("venue_name"), row.get("venue_address"), row.get("venue_city")) != VENUES[key]
                    or (row.get("lat"), row.get("lng")) != (reviewed_venue_location(key, *VENUES[key][:2]) or (None, None))):
                raise ValueError("local_venue_checkpoint_invalid")
            try:
                start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
                if not start or not start.tzinfo or (end and end <= start):
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("local_venue_checkpoint_invalid") from None
            ids.add(row["id"])
        for item in result["diagnostics"]:
            if not isinstance(item, dict) or item.get("unit_id") != result["unit_id"] or item.get("disposition") != "held" or not item.get("reason"):
                raise ValueError("local_venue_checkpoint_invalid")
        if "tickets" in result:
            if (key != LIZZIE or not re.fullmatch(r"lizzie:tickets:(?:[1-9]|10)", result["unit_id"])
                    or not isinstance(result["tickets"], dict) or not isinstance(result.get("ticket_pages"), list)
                    or any(type(p) is not int or not 1 <= p <= MAX_TICKET_PAGES for p in result["ticket_pages"])):
                raise ValueError("local_venue_checkpoint_invalid")
            for url, ticket in result["tickets"].items():
                if not event_url(LIZZIE, url) or not isinstance(ticket, dict) or not isinstance(ticket.get("title"), str) or not isinstance(ticket.get("availability"), str):
                    raise ValueError("local_venue_checkpoint_invalid")
    if (value["events"] != [row for result in value["results"] for row in result["events"]]
            or value["diagnostics"] != [item for result in value["results"] for item in result["diagnostics"]]):
        raise ValueError("local_venue_checkpoint_invalid")
    return deepcopy(value)


def _unit(key, unit, fetch, now, state):
    result = {"unit_id": unit["id"], "events": [], "diagnostics": []}
    try:
        if unit.get("hold"):
            raise Hold(unit["hold"])
        if unit["type"] == "lizzie_tickets" and not _needs_fetch(unit, state):
            return result
        if unit["type"] == "tom_inline":
            rows = _tom_inline(unit, now)
        else:
            payload = fetch(unit["url"], "text/html")
            if unit["type"] == "slack":
                rows = _slack_detail(unit, payload, now)
            else:
                soup = BeautifulSoup(payload, "html.parser")
                if unit["type"] == "tom_shop":
                    rows = _tom_shop(unit, soup, now)
                elif unit["type"] == "tom_opera":
                    rows, result["diagnostics"] = _tom_opera(unit, soup, now)
                elif unit["type"] == "tom_music":
                    rows = _tom_music(unit, soup, now)
                elif unit["type"] == "lizzie_tickets":
                    result["tickets"], result["ticket_pages"] = _lizzie_tickets(soup)
                    rows = []
                elif unit["type"] == "lizzie_month":
                    tickets, _ = _catalog(state, require_complete=True)
                    if not tickets:
                        raise ValueError("local_venue_checkpoint_invalid")
                    rows, result["diagnostics"] = _lizzie_month(unit, soup, now, tickets)
                else:
                    raise ValueError("local_venue_manifest_invalid")
        result["events"] = [row for row in rows if row is not None]
    except Hold as exc:
        result["diagnostics"].append(_diagnostic(unit, str(exc)))
    return result


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=MAX_DETAILS_PER_CHUNK):
    key = source.get("source_key")
    if (key not in SOURCES or (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[key]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_atlantic_city_local_venue")
    current = now or datetime.now(timezone.utc)
    if not current.tzinfo:
        raise ValueError("local_venue_checkpoint_invalid")
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    anchor = datetime.fromisoformat(state["started_at"]) if state else current
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    payload = fetch(SOURCES[key][0], "text/html")
    units = _manifest(key, payload, anchor)
    queue = [unit["id"] for unit in units]
    digest = _hash({"contract": CONTRACT, "manifest": units})
    if state is None or state["manifest_hash"] != digest or state["queue"] != queue:
        if anchor != current:
            units = _manifest(key, payload, current)
            queue = [unit["id"] for unit in units]
            digest = _hash({"contract": CONTRACT, "manifest": units})
        state = {"version": 1, "contract": CONTRACT, "source_key": key, "started_at": current.isoformat(),
                 "window_start": current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                 "manifest_hash": digest, "manifest_count": len(units), "queue": queue, "cursor": 0,
                 "results": [], "events": [], "diagnostics": []}
    previous = state["cursor"]
    limit = min(MAX_DETAILS_PER_CHUNK, max(1, int(max_details)))
    fetches = 0
    while state["cursor"] < len(units):
        unit = units[state["cursor"]]
        needs_fetch = _needs_fetch(unit, state)
        if needs_fetch and fetches >= limit:
            break
        if needs_fetch and deadline_at is not None and monotonic() + MIN_DETAIL_SECONDS >= deadline_at:
            break
        try:
            result = _unit(key, unit, fetch, current, state)
        except ValueError as exc:
            from roomquest.preview_worker import PreviewError
            if (isinstance(exc, PreviewError) and str(exc) in ("source_fetch_deadline", "publisher_pacing_deferred")
                    and state["cursor"] > previous):
                break
            raise
        state["results"].append(result)
        state["cursor"] += 1
        fetches += int(needs_fetch)
    if state["cursor"] == previous < len(units):
        raise ValueError("collection_deadline")
    complete = state["cursor"] == len(units)
    if complete:
        for result in state["results"]:
            for row in list(result["events"]):
                if not _within(timestamp(row["starts_at"]), timestamp(row.get("ends_at")), current):
                    result["events"].remove(row)
                    result["diagnostics"].append({"unit_id": result["unit_id"], "event_url": row["event_url"],
                        "native_event_id": row["native_event_id"], "title": row["title"], "disposition": "held",
                        "reason": "event_ended_during_collection"})
    state["events"] = [row for result in state["results"] for row in result["events"]]
    state["diagnostics"] = [item for result in state["results"] for item in result["diagnostics"]]
    if len(json.dumps(state).encode()) > MAX_CHECKPOINT_BYTES or len(state["diagnostics"]) > 400:
        raise ValueError("local_venue_checkpoint_size_limit")
    rows = [row for result in state["results"] for row in result["events"]]
    if len(rows) > MAX_RECORDS or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("local_venue_duplicate_identity")
    output = rows if complete else []
    return {"complete": complete, "events": sorted(deepcopy(output), key=lambda row: (row["starts_at"], row["id"])), "checkpoint": state}


def collect(source, fetch, *, now=None, deadline_at=None):
    chunk = collect_chunk(source, fetch, now=now, deadline_at=deadline_at)
    if not chunk["complete"]:
        raise ValueError("publisher_checkpoint_required")
    return chunk["events"]
