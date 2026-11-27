"""Remaining NYC games and social programs from reviewed public publisher pages.

Normal HTML preserves complete native program bodies. Freshly revalidated weekly
schedules are materialized only inside a finite rolling 28-day window, with the
publisher's season and holiday exclusions retained. All requests use the
caller's normal guarded publisher transport.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import parse_tribe, plain, record, timestamp
from roomquest.new_york_nightlife import _square_clock

ZONE = "America/New_York"
WILD = "wild_east_brooklyn_ny"
SIP = "sip_and_play_brooklyn_ny"
PAUPER = "nyc_pauper_league_ny"
BRONX = "bronx_alehouse_bronx_ny"
OSNYC = "os_nyc_new_york_ny"
RADEGAST = "radegast_hall_brooklyn_ny"
GREENBELT = "greenbelt_conservancy_staten_island_ny"
SOURCES = {
    WILD: ("https://www.wildeastbrewing.com/", "html", "html"),
    SIP: ("https://www.sipnplaynyc.com/general-5", "html", "html"),
    PAUPER: ("https://www.decksandthecity.org/schedule", "html", "html"),
    BRONX: ("https://letsgotrivia.com/venue/bronx-alehouse/", "html", "html"),
    OSNYC: ("https://www.os-nyc.com/events", "html", "html"),
    RADEGAST: ("https://radegasthall.com/", "html", "html"),
    GREENBELT: ("https://www.eventbrite.com/o/greenbelt-conservancy-10628899098", "html", "html"),
}
ALLOWED_HOSTS = {key: (urlsplit(value[0]).hostname,) for key, value in SOURCES.items()}
CHECKPOINT_KEYS = {RADEGAST, GREENBELT}
REVIEWED_AT = datetime(2026, 11, 14, 23, 0, tzinfo=timezone.utc)
MAX_DESCRIPTION = 12000
MAX_RECORDS = 200
TRIVIA_API = "https://letsgotrivia.com/wp-json/tribe/events/v1/events/"
# Public frontend request from the site's own Amelia v9.10 event widget.
# Each chunk makes one GET; the normal transport retains its 60-second floor.
RADEGAST_API = "https://radegasthall.com/wp-admin/admin-ajax.php?action=wpamelia_api&call=/events&bookings=false&range=future&page="
RADEGAST_PAGE_SIZE = 12
MAX_CHECKPOINT_BYTES = 900_000
RADEGAST_VENUES = {
    None: ("Radegast Hall", "113 North 3rd Street, Brooklyn, NY 11249", "Brooklyn"),
    2: ("Radegast Hall — Garden", "113 North 3rd Street, Brooklyn, NY 11249", "Brooklyn"),
    3: ("Radegast Hall — The Bier Haus", "186 Berry Street, Brooklyn, NY 11249", "Brooklyn"),
    4: ("Radegast Hall — Bar Stage", "113 North 3rd Street, Brooklyn, NY 11249", "Brooklyn"),
}
# NYC CB1's 2025 licensing notice explicitly identifies 113–115 North 3rd
# Street AKA 186 Berry Street as the same premises. NYC PAD verifies the
# 113 North 3rd address point; no generic Amelia location coordinates are used.
RADEGAST_POINT = (40.716671, -73.961386)
VENUES = {
    WILD: ("Wild East Brewing Co.", "623 Sackett Street, Brooklyn, NY 11217", "Brooklyn"),
    SIP: ("Sip & Play", "471 5th Avenue, Brooklyn, NY 11215", "Brooklyn"),
    BRONX: ("Bronx Alehouse", "216 West 238th Street, Bronx, NY 10463", "Bronx"),
    OSNYC: ("OS NYC", "50 Bowery, New York, NY 10013", "New York"),
}
PAUPER_VENUES = {
    "Hex & Co. Upper West Side": ("2911 Broadway, New York, NY 10025", "New York"),
    "Hex & Co. Union Square": ("801 Broadway, New York, NY 10003", "New York"),
    "Brooklyn Strategist": ("148 Pierrepont Street, Brooklyn, NY 11201", "Brooklyn"),
}
# Exact publisher addresses matched to NYC Planning PAD on 2026-11-14.
POINTS = {
    WILD: (40.678617, -73.983416), SIP: (40.668103, -73.986879),
    BRONX: (40.884600, -73.899646), OSNYC: (40.715969, -73.996746),
}
PAUPER_POINTS = {
    "Hex & Co. Upper West Side": (40.806512, -73.965505),
    "Hex & Co. Union Square": (40.732847, -73.991801),
    "Brooklyn Strategist": (40.694456, -73.991584),
}
# Publisher event-specific streets are matched to the same official NYC Parks
# named facilities used by the broad Parks source. High Rock's parking lot and
# its distinct gate are not interchangeable meeting points.
GREENBELT_VENUES = {
    "Greenbelt Nature Center": (
        "Greenbelt Nature Center (in Blood Root Valley)",
        "700 Rockland Avenue, Staten Island, NY 10314", "Staten Island",
        40.588401794434, -74.139099121094),
    "High Rock Park: Nevada Ave parking lot": (
        "Nevada Avenue Parking Lot (in High Rock Park)",
        "200 Nevada Avenue, Staten Island, NY 10306", "Staten Island",
        40.584556817034, -74.124981164932),
}
GREENBELT_ORGANIZER = "10628899098"
GREENBELT_ORGANIZATION = "170711247025"
SQUARE_SITES = {WILD: "5784fb8829687fbea45f08d1", OSNYC: "5d695110f8d59d0001fd289b"}
DAYS = {name.casefold(): number for number, name in enumerate(
    ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))}
ERROR_CODES = {
    "unregistered_new_york_social_final_source", "new_york_social_final_calendar_changed",
    "new_york_social_final_description_missing", "new_york_social_final_description_limit",
    "new_york_social_final_identity", "new_york_social_final_location_unresolved",
    "new_york_social_final_schedule_conflict", "new_york_social_final_record_limit",
    "new_york_social_final_manifest_limit", "collection_deadline",
    "new_york_social_final_checkpoint_required", "new_york_social_final_checkpoint_invalid",
    "new_york_social_final_checkpoint_size_limit", "new_york_social_final_manifest_changed",
    "new_york_social_final_description_shape_changed",
}
RADEGAST_HELD_REASONS = {
    "publisher_nonpublic", "publisher_venue_changed", "publisher_schedule_conflict",
    "no_available_future_occurrence", "new_york_social_final_description_missing",
    "new_york_social_final_description_limit",
}
GREENBELT_HELD_REASONS = {
    "publisher_nonpublic", "publisher_venue_changed", "publisher_schedule_conflict",
    "no_available_future_occurrence", "new_york_social_final_description_missing",
    "new_york_social_final_description_limit", "new_york_social_final_description_shape_changed",
}


def _source(source):
    key = source.get("source_key")
    if key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE):
        raise ValueError("unregistered_new_york_social_final_source")
    return key


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or p.netloc not in ALLOWED_HOSTS[key] or (p.query and key != RADEGAST) or p.fragment
                or re.search(r"[\s\\<>]|%2e|%2f|%5c", value, re.I)
                or ".." in p.path.split("/")):
            return False
        if key == OSNYC:
            return bool(re.fullmatch(r"/events/[a-z0-9-]+", p.path))
        if key == BRONX:
            return bool(re.fullmatch(r"/find-a-trivia/bronx-alehouse/20\d{2}-\d{2}-\d{2}/", p.path))
        if key == RADEGAST:
            return p.path == "/" and bool(re.fullmatch(r"ameliaEventPopup=[1-9]\d{0,8}", p.query))
        if key == GREENBELT:
            return bool(re.fullmatch(r"/e/[a-z0-9-]+-tickets-[1-9]\d{9,15}", p.path))
        return value == SOURCES[key][0]
    except ValueError:
        return False


def photo_url(key, value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.fragment or ".." in p.path.split("/"):
            return None
        site = SQUARE_SITES.get(key)
        if site and p.netloc == "images.squarespace-cdn.com" and p.path.startswith("/content/v1/" + site + "/") and set(parse_qs(p.query)) <= {"format"}:
            return value
        if key == SIP and p.netloc == "static.wixstatic.com" and not p.query and re.fullmatch(r"/media/3683c8_[a-f0-9]{32}(?:~|%7E)mv2\.(?:png|jpe?g|webp)(?:/v1/[^?#]+)?", p.path, re.I):
            return value
        if key == BRONX and p.netloc == "letsgotrivia.com" and not p.query and re.fullmatch(r"/wp-content/uploads/20\d{2}/\d{2}/trivia-venue_bronx-alehouse(?:-\d+x\d+)?\.png", p.path):
            return value
        if key == RADEGAST and p.netloc == "radegasthall.com" and not p.query and re.fullmatch(r"/wp-content/uploads/20\d{2}/\d{2}/[^/?#]+\.(?:jpe?g|png|webp)", p.path, re.I):
            return value
        if key == GREENBELT:
            nested = urlsplit(unquote(p.path.lstrip("/"))) if p.netloc == "img.evbuc.com" else p
            if (nested.scheme == "https" and nested.netloc == "cdn.evbuc.com" and not nested.query
                    and re.fullmatch(r"/images/[1-9]\d*/2819827011031/1/original\.\d{8}-\d{6}", nested.path)):
                return nested.geturl()
    except ValueError:
        pass
    return None


def reviewed_venue_location(key, venue, street):
    if key in VENUES and (venue, street) == VENUES[key][:2]:
        return POINTS[key]
    if key == PAUPER and venue in PAUPER_VENUES and street == PAUPER_VENUES[venue][0]:
        return PAUPER_POINTS[venue]
    if key == RADEGAST and (venue, street) in {place[:2] for place in RADEGAST_VENUES.values()}:
        return RADEGAST_POINT
    if key == GREENBELT:
        return next((place[3:] for place in GREENBELT_VENUES.values() if (venue, street) == place[:2]), None)
    return None


def _body(value):
    body = description(str(value or "").replace("\u200b", "").replace("\ufeff", ""), limit=MAX_DESCRIPTION + 1)
    if not body or not any(char.isalpha() for char in body) or body.casefold() in {"undefined", "null", "none", "n/a", "tbd", "tba", "coming soon", "details coming soon"}:
        raise ValueError("new_york_social_final_description_missing")
    if len(body) > MAX_DESCRIPTION:
        raise ValueError("new_york_social_final_description_limit")
    return body


def _text(node):
    return plain(node.get_text(" ").replace("\u200b", "").replace("\ufeff", ""))


def _within(start, end, now):
    if not isinstance(start, datetime) or start.tzinfo is None or end and (end.tzinfo is None or end <= start):
        raise ValueError("new_york_social_final_schedule_conflict")
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _identity(key, url, start, native):
    return "nyc-final:" + sha256(f"{key}:{url}:{start.astimezone(timezone.utc).isoformat()}:{native}".encode()).hexdigest()


def _content_venue(**values):
    allowed = {"venue_name", "venue_address", "venue_city", "venue_region",
               "venue_postal_code", "venue_country"}
    result = {}
    for name, value in values.items():
        if name not in allowed or value not in (None, "") and not isinstance(value, (str, int)):
            raise ValueError("new_york_social_final_location_unresolved")
        if value not in (None, ""):
            result[name] = plain(str(value))
    return result


def _attach_content(row, body, *, content_venue=None, image=None, labels=(),
                    provider_venue_id=None):
    start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
    if start is None or start.tzinfo is None or end is not None and end.tzinfo is None:
        raise ValueError("new_york_social_final_schedule_conflict")
    facts = {
        "title": row["title"], "description": body, "is_all_day": False,
        "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
        "ends_at_utc": end.astimezone(timezone.utc).isoformat() if end else None,
        "source_timezone": ZONE, "event_url": row["event_url"],
        "provider_venue_id": str(provider_venue_id) if provider_venue_id is not None else None,
        "source_image_url": image,
        "publisher_categories": sorted({plain(value) for value in labels if plain(value)}),
        "attendance_mode": "in_person", **(content_venue or {}),
    }
    facts = {name: value for name, value in facts.items()
             if value is not None and value != "" and value != [] and value != {}}
    row["collector_event_content_v1"] = {"version": 1, "event_id": row["id"], "facts": facts}
    return row


def _content_envelope_valid(row):
    value = row.get("collector_event_content_v1")
    if value is None:
        return True
    if (not isinstance(value, dict) or set(value) != {"version", "event_id", "facts"}
            or value.get("version") != 1 or value.get("event_id") != row.get("id")
            or not isinstance(value.get("facts"), dict)):
        return False
    facts = value["facts"]
    allowed = {"title", "description", "is_all_day", "starts_at_utc", "ends_at_utc",
               "source_timezone", "event_url", "provider_venue_id", "venue_name",
               "venue_address", "venue_city", "venue_region", "venue_postal_code",
               "venue_country", "source_image_url", "publisher_categories", "attendance_mode"}
    if not set(facts) <= allowed:
        return False
    try:
        start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
        expected = {"title": row.get("title"), "description": row.get("description"),
                    "is_all_day": False, "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
                    "source_timezone": ZONE, "event_url": row.get("event_url"),
                    "attendance_mode": "in_person"}
        if end is not None:
            expected["ends_at_utc"] = end.astimezone(timezone.utc).isoformat()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    if (facts.get("source_image_url") != row.get("image_url")
            or facts.get("publisher_categories", []) != sorted(set(row.get("publisher_categories") or []))
            or not all(facts.get(name) == expected_value for name, expected_value in expected.items())):
        return False
    if "radegasthall.com" in str(row.get("event_url")):
        locations = [str(location_id) if location_id is not None else None
                     for location_id, place in RADEGAST_VENUES.items()
                     if (row.get("venue_name"), row.get("venue_address")) == place[:2]]
        return len(locations) == 1 and facts.get("provider_venue_id") == locations[0]
    return True


def _row(key, title, start, end, body, place, *, native, url=None, image=None, category="", schedule_window=None,
         content_venue=None, provider_venue_id=None, labels=()):
    url = url or SOURCES[key][0]
    if not event_url(key, url) or not isinstance(title, str) or not 1 <= len(title) <= 180:
        raise ValueError("new_york_social_final_identity")
    body = _body(body)
    point = reviewed_venue_location(key, *place[:2])
    if point is None:
        raise ValueError("new_york_social_final_location_unresolved")
    row = record(title, start, end, *place, url, _identity(key, url, start, native),
                 category=category, lat=point[0], lng=point[1], tz=ZONE, retain_until_end=True)
    if row is not None:
        row.update(description=body, timezone=ZONE, attendance_mode="in_person",
                   lat=point[0], lng=point[1], reason=None,
                   location_provenance="reviewed_nyc_pad_address_point")
        photo = photo_url(key, image)
        if photo:
            row["image_url"] = photo
        if labels:
            row["publisher_categories"] = list(dict.fromkeys(labels))
        if schedule_window:
            row.update(schedule_provenance="reviewed_publisher_weekly_schedule",
                       schedule_policy_reviewed_at=REVIEWED_AT.isoformat(),
                       schedule_reviewed_at=schedule_window[0].astimezone(timezone.utc).isoformat(),
                       schedule_materialized_until=schedule_window[1].astimezone(timezone.utc).isoformat())
        _attach_content(row, body, content_venue=content_venue, image=photo,
                        labels=labels, provider_venue_id=provider_venue_id)
    return row


def _hold(diagnostics, label, reason, *, url=None):
    diagnostics.append(dict(event_url=url, publisher_label=label, disposition="held", reason=reason))


def _meridian(hour, minute, suffix):
    hour, minute = int(hour), int(minute or 0)
    if not 1 <= hour <= 12 or not 0 <= minute <= 59 or suffix.casefold() not in {"am", "pm"}:
        raise ValueError("new_york_social_final_schedule_conflict")
    return time(hour % 12 + (12 if suffix.casefold() == "pm" else 0), minute)


def _schedule_window(now, season=None):
    until = now + timedelta(days=28)
    if season:
        until = min(until, datetime.combine(season[1] + timedelta(days=1), time(), ZoneInfo(ZONE)))
    return now, until


def _weekly(weekday, clock, now, *, season=None, breaks=()):
    anchor, until = _schedule_window(now, season)
    day = anchor.astimezone(ZoneInfo(ZONE)).date()
    last = until.astimezone(ZoneInfo(ZONE)).date()
    while day <= last:
        start = datetime.combine(day, clock, ZoneInfo(ZONE))
        if (day.weekday() == weekday and anchor <= start < until
                and (season is None or season[0] <= day <= season[1])
                and not any(first <= day <= final for first, final in breaks)):
            yield start
        day += timedelta(days=1)


def _wild(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    blocks = [node for node in soup.select(".sqs-html-content") if node.find("h3") and re.search(r"\b20\d{2}\b", _text(node.find("h3")))]
    if not blocks or "TAPROOM EVENTS" not in soup.get_text(" "):
        raise ValueError("new_york_social_final_calendar_changed")
    rows, diagnostics = [], []
    for block in blocks:
        heading = _text(block.find("h3"))
        try:
            month = datetime.strptime(heading, "%B %Y")
        except ValueError:
            raise ValueError("new_york_social_final_calendar_changed") from None
        for paragraph in block.find_all("p", recursive=False):
            native = _text(paragraph)
            match = re.match(r"([A-Za-z]+),\s*([A-Za-z]+)\.?\s*(\d{1,2})(?:st|nd|rd|th)?\s*:\s*(.+)", native)
            if not match:
                continue
            weekday, mon, number, title_body = match.groups()
            if mon.casefold()[:3] != month.strftime("%b").casefold():
                raise ValueError("new_york_social_final_schedule_conflict")
            day = date(month.year, month.month, int(number))
            if day < now.astimezone(ZoneInfo(ZONE)).date():
                continue
            if weekday.casefold()[:3] != day.strftime("%a").casefold():
                _hold(diagnostics, native, "publisher_schedule_conflict")
                continue
            if re.search(r"closed to the public|private (?:event|party)|cancell?ed|postponed", title_body, re.I):
                _hold(diagnostics, native, "publisher_nonpublic")
                continue
            clock = re.search(r"\bfrom\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*[-–]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", title_body, re.I)
            if not clock:
                _hold(diagnostics, native, "publisher_clock_missing")
                continue
            a, b, c, d, e, f = clock.groups()
            start = datetime.combine(day, _meridian(a, b, c or f), ZoneInfo(ZONE))
            end = datetime.combine(day, _meridian(d, e, f), ZoneInfo(ZONE))
            if not _within(start, end, now):
                continue
            title = title_body[:clock.start()].strip(" .-")
            row = _row(WILD, title, start, end, str(paragraph), VENUES[WILD], native=title.casefold(), category="Taproom events")
            if row:
                rows.append(row)
    return rows, diagnostics


_SIP_HEADERS = re.compile(r"^(Park Slope Chess Club|MTG DRAFT|Bi-weekly writing meetup|Riftbound|Bi-weekly boardgame meetup|Commander night!|Flesh and Blood|Lorcana|Family Fridays|MTG Draft|Bi-weekly Queer Commander night!)", re.I)


def _sip(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    blocks = [node for node in soup.select('[data-testid="richTextElement"]')
              if any(re.fullmatch(r"(?:Monday|Thursday):", _text(p)) for p in node.find_all("p"))]
    if len(blocks) != 2:
        raise ValueError("new_york_social_final_calendar_changed")
    programs, current, weekday = [], None, None
    for block in blocks:
        for paragraph in block.find_all("p", recursive=False):
            text = _text(paragraph)
            if not text:
                continue
            if (day := text.removesuffix(":" ).casefold()) in DAYS:
                weekday = DAYS[day]
                current = None
            elif (match := _SIP_HEADERS.match(text)) and text != "Park Slope Chess Club":
                if weekday is None:
                    raise ValueError("new_york_social_final_calendar_changed")
                current = dict(weekday=weekday, title=match.group(1), header=text, paragraphs=[str(paragraph)])
                programs.append(current)
            elif current is not None:
                current["paragraphs"].append(str(paragraph))
    if len(programs) < 7 or len(programs) > 30:
        raise ValueError("new_york_social_final_calendar_changed")
    rows, diagnostics = [], []
    for program in programs:
        title, header = program["title"], program["header"]
        body = "\n".join(program["paragraphs"])
        if title.casefold().startswith("bi-weekly"):
            _hold(diagnostics, title, "publisher_biweekly_anchor_missing")
            continue
        if title.casefold().startswith("family fridays"):
            _hold(diagnostics, title, "retail_promotion_without_program")
            continue
        if title.casefold().startswith("commander night"):
            _hold(diagnostics, title, "publisher_schedule_conflict")
            continue
        match = re.search(r"(?:@| at )\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", header, re.I)
        if match:
            clock = _meridian(*match.groups())
        elif program["weekday"] == 0 and re.fullmatch(r"MTG DRAFT\s*@\s*6:30!", header, re.I):
            # Native Monday header omits the meridian. Current official Monday
            # opening hours are 11am-11pm, which rules out 06:30.
            clock = time(18, 30)
        else:
            _hold(diagnostics, title, "publisher_clock_missing")
            continue
        for start in _weekly(program["weekday"], clock, now):
            row = _row(SIP, title, start, None, body, VENUES[SIP],
                       native=f"{program['weekday']}:{title.casefold()}", category="Board games and card games", schedule_window=_schedule_window(now))
            if row:
                rows.append(row)
    return rows, diagnostics


def _pauper(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    main = soup.find("main")
    if main is None or "Pauper League Schedule" not in main.get_text(" "):
        raise ValueError("new_york_social_final_calendar_changed")
    sections = main.find_all("section")
    if len(sections) != 2:
        raise ValueError("new_york_social_final_calendar_changed")
    summary = sections[1]
    dates = [plain(x.get_text()) for x in summary.find_all("strong")]
    expected = ["October 5, 2026", "February 21, 2027", "November 23 - December 6, 2026", "December 21, 2026 - January 3, 2027"]
    if dates[:4] != expected:
        raise ValueError("new_york_social_final_schedule_conflict")
    season = (date(2026, 10, 5), date(2027, 2, 21))
    breaks = ((date(2026, 11, 23), date(2026, 12, 6)), (date(2026, 12, 21), date(2027, 1, 3)))
    paragraphs = summary.find_all("p", recursive=False)
    if len(paragraphs) != 6:
        raise ValueError("new_york_social_final_calendar_changed")
    rows, diagnostics = [], []
    cards = sections[0].find_all("div", recursive=False)
    if len(cards) != 4:
        raise ValueError("new_york_social_final_calendar_changed")
    for card in cards:
        heading, venue_node = card.find("h5"), card.select_one("h6 a")
        if heading is None or venue_node is None:
            raise ValueError("new_york_social_final_calendar_changed")
        venue = _text(venue_node)
        if venue not in PAUPER_VENUES:
            _hold(diagnostics, venue, "outside_new_york_city")
            continue
        day = _text(heading).split(" ", 1)[0].casefold()
        lines = card.find_all("p")
        if day not in DAYS or len(lines) != 2:
            raise ValueError("new_york_social_final_calendar_changed")
        native_street = re.sub(r"^Address:\s*", "", _text(lines[0]))
        street = native_street.replace("Pierrepont St,", "Pierrepont Street,")
        if street != PAUPER_VENUES[venue][0]:
            _hold(diagnostics, venue, "publisher_venue_changed")
            continue
        match = re.fullmatch(r"Time:\s*(\d{1,2}):(\d{2})\s*(AM|PM)", _text(lines[1]), re.I)
        if not match:
            raise ValueError("new_york_social_final_schedule_conflict")
        clock = _meridian(*match.groups())
        included = paragraphs if venue == "Hex & Co. Union Square" else paragraphs[:-1]
        body = str(heading) + "\n" + "\n".join(str(p) for p in lines + included)
        for start in _weekly(DAYS[day], clock, now, season=season, breaks=breaks):
            row = _row(PAUPER, "NYC Pauper League at " + venue, start, None, body,
                       (venue, *PAUPER_VENUES[venue]), native=venue, category="Magic: The Gathering Pauper",
                       schedule_window=_schedule_window(now, season),
                       content_venue=_content_venue(venue_name=venue, venue_address=native_street))
            if row:
                rows.append(row)
    return rows, diagnostics


def _trivia_api_url(now):
    day = now.astimezone(ZoneInfo(ZONE)).date()
    return TRIVIA_API + "?" + urlencode(dict(venue=230356, start_date=day.isoformat(),
        end_date=(day + timedelta(days=60)).isoformat(), per_page=100))


def _bronx(payload, now):
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        raise ValueError("new_york_social_final_calendar_changed") from None
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list) or data.get("total") != len(events) or data.get("total_pages") not in (0, 1):
        raise ValueError("new_york_social_final_manifest_limit")
    if len(events) > 100:
        raise ValueError("new_york_social_final_manifest_limit")
    rows, diagnostics = [], []
    for native in events:
        venue = native.get("venue") or {}
        if (venue.get("id") != 230356 or venue.get("venue") != "Bronx Alehouse"
                or not re.fullmatch(r"216 W(?:est)? 238(?:th)? St(?:reet)?", plain(venue.get("address")), re.I)):
            _hold(diagnostics, str(native.get("id")), "publisher_venue_changed", url=native.get("url"))
            continue
        body = _body(native.get("description"))
        if "Bronx, NY 10463" not in body:
            _hold(diagnostics, str(native.get("id")), "publisher_venue_changed", url=native.get("url"))
            continue
        copy = deepcopy(native)
        copy["venue"].update(address="216 West 238th Street", city="Bronx", state="NY", zip="10463")
        parsed = parse_tribe({"events": [copy]}, strict_public=True, retain_description=True)
        if not parsed:
            _hold(diagnostics, str(native.get("id")), "publisher_nonpublic_or_expired", url=native.get("url"))
            continue
        start, end = timestamp(parsed[0]["starts_at"]), timestamp(parsed[0].get("ends_at"))
        if not _within(start, end, now):
            continue
        row = _row(BRONX, "Let's Go Trivia at Bronx Alehouse", start, end, body, VENUES[BRONX],
                   native=str(native["id"]), url=native["url"], category="Trivia", image=(venue.get("image") or {}).get("url"),
                   content_venue=_content_venue(venue_name=venue.get("venue"), venue_address=venue.get("address"),
                                                venue_city=venue.get("city"), venue_region=venue.get("state"),
                                                venue_postal_code=venue.get("zip"), venue_country="US"))
        if row:
            rows.append(row)
    return rows, diagnostics


def _osnyc(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    if soup.select_one(".eventlist") is None:
        raise ValueError("new_york_social_final_calendar_changed")
    rows, diagnostics = [], []
    for node in soup.select("article.eventlist-event--upcoming"):
        link = node.select_one("a.eventlist-title-link[href]")
        if link is None:
            raise ValueError("new_york_social_final_identity")
        title, url = _text(link), urljoin(SOURCES[OSNYC][0], link["href"])
        if re.search(r"\bclosed\b|private (?:event|party)|cancell?ed|postponed", title, re.I):
            _hold(diagnostics, title, "publisher_nonpublic", url=url)
            continue
        body_node = node.select_one('.eventlist-description [data-layout-label="Post Body"]')
        if body_node is None:
            raise ValueError("new_york_social_final_description_missing")
        body = _body(str(body_node))
        if re.search(r"tickets are sold out|private booking|event (?:is|has been) cancell?ed|event (?:is|has been) postponed", body, re.I):
            _hold(diagnostics, title, "publisher_nonpublic", url=url)
            continue
        start, end = _square_clock(node, "start"), _square_clock(node, "end")
        if not _within(start, end, now):
            continue
        location = node.select_one(".eventlist-meta-address")
        supplied = _text(location).removesuffix("(map)").strip() if location else ""
        if supplied not in {"50 Bowery Street", "50 Bowery", "OS NYC"}:
            _hold(diagnostics, title, "publisher_venue_changed", url=url)
            continue
        conflicting_map = False
        for anchor in location.select("a[href]") if location else []:
            target = urlsplit(anchor["href"])
            if target.hostname not in {"maps.google.com", "www.google.com"}:
                continue
            for value in parse_qs(target.query).get("q", []):
                compact = re.sub(r"[^a-z0-9]", "", value.casefold())
                if compact and compact != "newyorkcity10013usa" and not re.fullmatch(
                        r"50bowery(?:street)?newyork(?:city)?(?:ny|newyork)?10013(?:usa|unitedstates)?", compact):
                    conflicting_map = True
        if conflicting_map:
            _hold(diagnostics, title, "publisher_venue_changed", url=url)
            continue
        image = node.select_one("img.eventlist-thumbnail")
        row = _row(OSNYC, title, start, end, body, VENUES[OSNYC], native=url,
                   url=url, image=image.get("data-image") if image else None, category="Gaming and social events",
                   content_venue=_content_venue(venue_name=supplied))
        if row:
            rows.append(row)
    return rows, diagnostics


def _radegast_page(payload, page):
    try:
        data = json.loads(payload)["data"]
        count, events = data["count"], data["events"]
    except (TypeError, KeyError, ValueError):
        raise ValueError("new_york_social_final_calendar_changed") from None
    if type(count) is not int or not 0 <= count <= MAX_RECORDS or not isinstance(events, list):
        raise ValueError("new_york_social_final_manifest_limit")
    expected = min(RADEGAST_PAGE_SIZE, max(0, count - (page - 1) * RADEGAST_PAGE_SIZE))
    if len(events) != expected:
        raise ValueError("new_york_social_final_manifest_changed")
    ids = [event.get("id") for event in events if isinstance(event, dict)]
    if len(ids) != len(events) or any(type(identity) is not int or not 0 < identity < 10**9 for identity in ids) or len(set(ids)) != len(ids):
        raise ValueError("new_york_social_final_identity")
    return count, events


def _radegast_event(event, now):
    identity, title = event["id"], plain(event.get("name"))
    url = SOURCES[RADEGAST][0] + "?ameliaEventPopup=" + str(identity)
    diagnostics, rows = [], []

    def hold(reason):
        diagnostics.append(dict(event_url=url, publisher_label=title, publisher_native_id=identity,
                                disposition="held", reason=reason))

    if event.get("status") != "approved" or event.get("show") is not True or re.search(
            r"\bclosed\b|private (?:event|party)|cancell?ed|postponed", title, re.I):
        hold("publisher_nonpublic")
        return rows, diagnostics
    location = event.get("locationId")
    if location not in RADEGAST_VENUES or event.get("customLocation") not in (None, ""):
        hold("publisher_venue_changed")
        return rows, diagnostics
    place = RADEGAST_VENUES[location]
    try:
        body = _body(event.get("description"))
    except ValueError as exc:
        if str(exc) not in RADEGAST_HELD_REASONS:
            raise
        hold(str(exc))
        return rows, diagnostics
    if body.casefold() in {title.casefold(), "bar stage", "garden", "main bar", "the bier haus", "radegast hall", "radegast on berry"}:
        hold("new_york_social_final_description_missing")
        return rows, diagnostics
    periods = event.get("periods")
    if event.get("timeZone") not in (None, "", ZONE) or not isinstance(periods, list) or not periods or len(periods) > 30:
        hold("publisher_schedule_conflict")
        return rows, diagnostics
    image = None
    for item in sorted(event.get("gallery") or [], key=lambda x: x.get("position", 0)):
        p = urlsplit(item.get("pictureFullPath") or "")
        if p.scheme in {"http", "https"} and p.netloc == "radegasthall.com":
            candidate = "https://radegasthall.com" + quote(p.path, safe="/%")
            if image := photo_url(RADEGAST, candidate):
                break
    for period in periods:
        native_period = period.get("id") if isinstance(period, dict) else None
        if type(native_period) is not int or native_period <= 0 or period.get("eventId") != identity:
            raise ValueError("new_york_social_final_identity")
        try:
            # The native widget prints these local wall clocks with client-zone
            # conversion disabled. Its global UTC default is not an event zone;
            # current official rendered programs corroborate the NYC clocks.
            start = timestamp(period.get("periodStart"), ZONE)
            end = timestamp(period.get("periodEnd"), ZONE)
            if start is None or end is None:
                raise ValueError("new_york_social_final_schedule_conflict")
            if not _within(start, end, now):
                hold("no_available_future_occurrence")
                continue
        except (TypeError, ValueError):
            hold("publisher_schedule_conflict")
            continue
        row = _row(RADEGAST, title, start, end, body, place,
                   native=f"{identity}:{native_period}", url=url, image=image, category="Live music and social events",
                   provider_venue_id=location)
        if row:
            row.update(publisher_native_id=identity, publisher_period_id=native_period,
                       schedule_provenance="reviewed_publisher_local_wall_clock")
            rows.append(row)
        else:
            hold("no_available_future_occurrence")
    return rows, diagnostics


def _radegast_digest(count, started_at, *, bootstrap=False):
    manifest = dict(source_key=RADEGAST, feed_url=SOURCES[RADEGAST][0], range="future",
                    publisher_count=count, page_size=RADEGAST_PAGE_SIZE, started_at=started_at)
    if bootstrap:
        manifest["phase"] = "robots"
    return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _new_radegast_state(count, current, restarts=0, *, bootstrap=False):
    started = current.astimezone(timezone.utc).isoformat()
    return dict(version=1, source_key=RADEGAST, started_at=started,
                window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                manifest_hash=_radegast_digest(count, started, bootstrap=bootstrap), manifest_count=count,
                cursor=0, next_page=1, restarts=restarts, seen_ids=[], events=[], diagnostics=[],
                phase="robots" if bootstrap else "events")


def _radegast_checkpoint(value, current):
    if value is None:
        return None
    try:
        started = timestamp(value["started_at"])
        count, cursor, page = value["manifest_count"], value["cursor"], value["next_page"]
        phase = value.get("phase", "events")
        valid = (isinstance(value, dict) and type(value["version"]) is int and value["version"] == 1
            and value["source_key"] == RADEGAST and type(count) is int and 0 <= count <= MAX_RECORDS
            and type(cursor) is int and 0 <= cursor <= count and type(page) is int and page >= 1
            and cursor == min((page - 1) * RADEGAST_PAGE_SIZE, count)
            and type(value["restarts"]) is int and 0 <= value["restarts"] <= 2
            and isinstance(value["seen_ids"], list) and len(value["seen_ids"]) == cursor
            and all(type(x) is int and 0 < x < 10**9 for x in value["seen_ids"])
            and len(set(value["seen_ids"])) == cursor
            and isinstance(value["events"], list) and len(value["events"]) <= MAX_RECORDS
            and isinstance(value["diagnostics"], list) and len(value["diagnostics"]) <= 400
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value["started_at"])
            and -60 <= (current - started).total_seconds() <= 4 * 60 * 60
            and value["window_start"] == started.astimezone(ZoneInfo(ZONE)).date().isoformat()
            and phase in {"robots", "events"}
            and (phase != "robots" or (count == cursor == value["restarts"] == 0 and page == 1
                                      and value["events"] == value["diagnostics"] == value["seen_ids"] == []))
            and value["manifest_hash"] == _radegast_digest(count, value["started_at"], bootstrap=phase == "robots"))
        if not valid:
            raise ValueError
        covered, row_ids = set(), set()
        for row in value["events"]:
            native, period = row["publisher_native_id"], row["publisher_period_id"]
            start, end = timestamp(row["starts_at"]), timestamp(row.get("ends_at"))
            point = reviewed_venue_location(RADEGAST, row["venue_name"], row["venue_address"])
            if (type(native) is not int or native not in value["seen_ids"] or type(period) is not int or period <= 0
                    or row["event_url"] != SOURCES[RADEGAST][0] + "?ameliaEventPopup=" + str(native)
                    or start is None or start.tzinfo is None or end is None or end <= start
                    or row["id"] != _identity(RADEGAST, row["event_url"], start, f"{native}:{period}")
                    or row["id"] in row_ids or point != (row.get("lat"), row.get("lng"))
                    or _body(row["description"]) != row["description"]
                    or not _content_envelope_valid(row)
                    or row.get("attendance_mode") != "in_person" or row.get("timezone") != ZONE
                    or row.get("location_provenance") != "reviewed_nyc_pad_address_point"
                    or not isinstance(row.get("title"), str) or not 1 <= len(row["title"]) <= 180):
                raise ValueError
            covered.add(native)
            row_ids.add(row["id"])
        for item in value["diagnostics"]:
            native = item["publisher_native_id"]
            if (native not in value["seen_ids"] or item["disposition"] != "held"
                    or item["reason"] not in RADEGAST_HELD_REASONS
                    or item["event_url"] != SOURCES[RADEGAST][0] + "?ameliaEventPopup=" + str(native)):
                raise ValueError
            covered.add(native)
        if covered != set(value["seen_ids"]):
            raise ValueError
    except (TypeError, KeyError, ValueError, AttributeError, OverflowError):
        raise ValueError("new_york_social_final_checkpoint_invalid") from None
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_social_final_checkpoint_size_limit")
    return deepcopy(value)


def _radegast_result(state, current):
    complete = state.get("phase", "events") != "robots" and state["cursor"] == state["manifest_count"]
    if complete:
        active = []
        for row in state["events"]:
            if timestamp(row["ends_at"]) > current:
                active.append(row)
            else:
                state["diagnostics"].append(dict(event_url=row["event_url"], publisher_label=row["title"],
                    publisher_native_id=row["publisher_native_id"], disposition="held", reason="no_available_future_occurrence"))
        state["events"] = active
    if len(state["events"]) > MAX_RECORDS or len(state["diagnostics"]) > 400:
        raise ValueError("new_york_social_final_record_limit")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_social_final_checkpoint_size_limit")
    state["events"].sort(key=lambda row: (row["starts_at"], row["id"]))
    return dict(complete=complete, events=deepcopy(state["events"]) if complete else [], checkpoint=state)


def _greenbelt_manifest(payload):
    """Only the organizer's complete public HTML manifest; no Eventbrite API."""
    soup = BeautifulSoup(payload, "html.parser")
    script = soup.select_one("script#__NEXT_DATA__")
    try:
        page = json.loads(script.get_text())["props"]["pageProps"]
        organizer, events, count = page["organizer"], page["upcomingEvents"], page["upcomingEventsTotal"]
        if (organizer.get("id") != GREENBELT_ORGANIZER
                or organizer.get("profilePageUrl") != SOURCES[GREENBELT][0]
                or page.get("hasMoreUpcoming") is not False or page.get("upcomingEventsFailed") is not False
                or type(count) is not int or not 0 <= count <= MAX_RECORDS
                or not isinstance(events, list) or len(events) != count):
            raise ValueError
        queue = []
        for event in events:
            identity, url = event["id"], event["url"]
            title = plain(event.get("name"))
            start = timestamp(event["start_date"] + "T" + event["start_time"], ZONE)
            if (not isinstance(identity, str) or not re.fullmatch(r"[1-9]\d{9,15}", identity)
                    or not event_url(GREENBELT, url) or not url.endswith("-" + identity)
                    or event.get("primary_organizer_id") != GREENBELT_ORGANIZER
                    or event.get("timezone") != ZONE or start is None
                    or not 0 < len(title) <= 180):
                raise ValueError
            queue.append(dict(id=identity, url=url, title=title, starts_at=start.isoformat()))
        if len({item["id"] for item in queue}) != count or len({item["url"] for item in queue}) != count:
            raise ValueError
        return sorted(queue, key=lambda item: item["url"])
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError("new_york_social_final_manifest_limit") from None


def _greenbelt_detail(item, payload, current):
    # The existing Eventbrite scraper discovers normal organizer/detail HTML.
    # As in the MakerSpace repair, use the shipped full structured text modules
    # instead of JSON-LD's short description or the older scraper's 500-char cap.
    soup = BeautifulSoup(payload, "html.parser")
    try:
        page = json.loads(soup.select_one("script#__NEXT_DATA__").get_text())["props"]["pageProps"]
        context, basic = page["context"], page["context"]["basicInfo"]
        if (page.get("error") or basic.get("id") != item["id"] or basic.get("url") != item["url"]
                or basic.get("name") != item["title"]
                or (basic.get("organizer") or {}).get("id") != GREENBELT_ORGANIZER
                or basic.get("organizationId") != GREENBELT_ORGANIZATION):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError("new_york_social_final_identity") from None
    if (basic.get("status") not in {"live", "started"} or basic.get("isOnline")
            or basic.get("isProtected") or basic.get("isListed") is not True
            or re.search(r"\b(?:cancell?ed|postponed|private event)\b", item["title"], re.I)):
        return None, "publisher_nonpublic"
    try:
        start_data, end_data = basic["startDate"], basic["endDate"]
        start, end = timestamp(start_data.get("local"), ZONE), timestamp(end_data.get("local"), ZONE)
        if (start_data.get("timezone") != ZONE or end_data.get("timezone") != ZONE
                or not start or not end or end <= start or start != timestamp(item["starts_at"])
                or timestamp(start_data.get("utc")) != start or timestamp(end_data.get("utc")) != end
                or basic.get("hideStartDate") or basic.get("hideEndDate") or basic.get("isParentEvent")):
            return None, "publisher_schedule_conflict"
        if not _within(start, end, current):
            return None, "no_available_future_occurrence"
    except (KeyError, TypeError, ValueError):
        return None, "publisher_schedule_conflict"
    native_venue = basic.get("venue") or {}
    address = native_venue.get("address") or {}
    place = GREENBELT_VENUES.get(plain(native_venue.get("name")))
    lines = address.get("localizedMultiLineAddressDisplay")
    if (not place or not isinstance(lines, list) or len(lines) != 2
            or address.get("country") != "US" or address.get("region") != "NY"
            or address.get("city") != "Staten Island"):
        return None, "publisher_venue_changed"
    expected = {"700rocklandave", "700rocklandavenue"} if place[1].startswith("700 ") else {"200nevadaave", "200nevadaavenue"}
    if (re.sub(r"[^a-z0-9]", "", plain(lines[0]).casefold()) not in expected
            or plain(lines[1]) != place[1].split(", ", 1)[1]):
        return None, "publisher_venue_changed"
    structured = context.get("structuredContent")
    if (not isinstance(structured, dict) or not isinstance(structured.get("modules"), list)
            or not isinstance(structured.get("widgets"), dict)
            or any(structured["widgets"].values())):
        return None, "new_york_social_final_description_shape_changed"
    modules = structured["modules"]
    if any(not isinstance(module, dict) or module.get("type") != "text"
           or not isinstance(module.get("text"), str) for module in modules):
        return None, "new_york_social_final_description_shape_changed"
    summary = str(basic.get("summary") or "")
    # An empty module list is legitimate when the publisher supplied only the
    # complete Overview sentence (the reviewed Orienteering class). Do not
    # replace missing prose with the title or the organizer's generic biography.
    raw_body = "<p>" + summary + "</p>\n" + "\n".join(module["text"] for module in modules)
    try:
        body = _body(raw_body)
    except ValueError as exc:
        if str(exc) not in GREENBELT_HELD_REASONS:
            raise
        return None, str(exc)
    if body.casefold() == item["title"].casefold() or (not modules and re.search(r"(?:\.\.\.|…)$", body)):
        return None, "new_york_social_final_description_missing"
    images = (context.get("gallery") or {}).get("images") or []
    image = next((photo_url(GREENBELT, image.get("url") or image.get("croppedLogoUrl600"))
                  for image in images if isinstance(image, dict)
                  and photo_url(GREENBELT, image.get("url") or image.get("croppedLogoUrl600"))), None)
    labels = [str(label) for label in (context.get("taxonomies") or {}).values() if isinstance(label, str)]
    native_address = " ".join(plain(value) for value in lines)
    postal = re.search(r"\b\d{5}(?:-\d{4})?\b", native_address)
    row = _row(GREENBELT, item["title"], start, end, body, place[:3], native=item["id"],
               url=item["url"], image=image, category="; ".join(labels), labels=labels,
               content_venue=_content_venue(venue_name=native_venue.get("name"),
                                            venue_address=plain(lines[0]), venue_city=address.get("city"),
                                            venue_region=address.get("region"),
                                            venue_postal_code=postal[0] if postal else None,
                                            venue_country=address.get("country")))
    if row:
        row.update(publisher_native_id=item["id"], publisher_organizer_id=GREENBELT_ORGANIZER,
                   description_provenance="publisher_overview_and_all_structured_text_modules",
                   native_text_module_count=len(modules),
                   location_provenance="reviewed_official_nyc_parks_named_facility_point")
    return row, None if row else "no_available_future_occurrence"


def _greenbelt_digest(queue):
    return sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _greenbelt_checkpoint(value, current):
    if value is None:
        return None
    try:
        started = timestamp(value["started_at"])
        queue, cursor = value["queue"], value["cursor"]
        valid = (isinstance(value, dict) and type(value["version"]) is int and value["version"] == 1
            and value["source_key"] == GREENBELT and type(cursor) is int
            and type(value["manifest_count"]) is int and 0 <= cursor <= value["manifest_count"] <= MAX_RECORDS
            and isinstance(queue, list) and len(queue) == value["manifest_count"]
            and value["manifest_hash"] == _greenbelt_digest(queue)
            and isinstance(value["events"], list) and len(value["events"]) <= cursor
            and isinstance(value["diagnostics"], list) and len(value["diagnostics"]) == cursor
            and type(value["manifest_verified"]) is bool
            and (not value["manifest_verified"] or cursor == len(queue))
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value["started_at"])
            and started is not None and -60 <= (current - started).total_seconds() <= 4 * 60 * 60
            and value["window_start"] == started.astimezone(ZoneInfo(ZONE)).date().isoformat())
        if not valid:
            raise ValueError
        for item in queue:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not re.fullmatch(r"[1-9]\d{9,15}", item["id"])
                    or not event_url(GREENBELT, item.get("url")) or not item["url"].endswith("-" + item["id"])
                    or not isinstance(item.get("title"), str) or not 1 <= len(item["title"]) <= 180
                    or timestamp(item.get("starts_at")) is None):
                raise ValueError
        if len({item["url"] for item in queue}) != len(queue) or len({item["id"] for item in queue}) != len(queue):
            raise ValueError
        processed = {item["id"]: item for item in queue[:cursor]}
        accepted = set()
        for row in value["events"]:
            item = processed.get(row.get("publisher_native_id"))
            start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
            if (not item or row["event_url"] != item["url"] or row["title"] != item["title"]
                    or not start or start != timestamp(item["starts_at"]) or not end or end <= start
                    or row["id"] != _identity(GREENBELT, item["url"], start, item["id"])
                    or item["id"] in accepted or row.get("publisher_organizer_id") != GREENBELT_ORGANIZER
                    or reviewed_venue_location(GREENBELT, row.get("venue_name"), row.get("venue_address")) != (row.get("lat"), row.get("lng"))
                    or row.get("venue_city") != "Staten Island" or row.get("timezone") != ZONE
                    or row.get("attendance_mode") != "in_person"
                    or row.get("location_provenance") != "reviewed_official_nyc_parks_named_facility_point"
                    or _body(row["description"]) != row["description"]
                    or not _content_envelope_valid(row)
                    or type(row.get("native_text_module_count")) is not int or row["native_text_module_count"] < 0
                    or (row.get("image_url") is not None and photo_url(GREENBELT, row["image_url"]) != row["image_url"])):
                raise ValueError
            accepted.add(item["id"])
        covered = set()
        for diagnostic in value["diagnostics"]:
            native = diagnostic.get("publisher_native_id")
            item = processed.get(native)
            if (not item or native in covered or diagnostic.get("event_url") != item["url"]
                    or diagnostic.get("publisher_label") != item["title"]
                    or diagnostic.get("disposition") not in {"accepted", "held"}
                    or (diagnostic["disposition"] == "accepted") != (native in accepted)
                    or (diagnostic["disposition"] == "held" and diagnostic.get("reason") not in GREENBELT_HELD_REASONS)):
                raise ValueError
            covered.add(native)
        if covered != set(processed):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("new_york_social_final_checkpoint_invalid") from None
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_social_final_checkpoint_size_limit")
    return deepcopy(value)


def _greenbelt_result(state, current):
    complete = state["cursor"] == state["manifest_count"] and state["manifest_verified"]
    if complete:
        expired = {row["publisher_native_id"] for row in state["events"] if timestamp(row["ends_at"]) <= current}
        state["events"] = [row for row in state["events"] if row["publisher_native_id"] not in expired]
        for diagnostic in state["diagnostics"]:
            if diagnostic["publisher_native_id"] in expired:
                diagnostic.update(disposition="held", reason="no_available_future_occurrence")
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError("new_york_social_final_checkpoint_size_limit")
    state["events"].sort(key=lambda row: (row["starts_at"], row["id"]))
    return dict(complete=complete, events=deepcopy(state["events"]) if complete else [], checkpoint=state)


def _greenbelt_chunk(fetch, checkpoint, deadline_at, current, max_details):
    state = _greenbelt_checkpoint(checkpoint, current)
    legacy_prefix = bool(state and state["events"] and
                         any("collector_event_content_v1" not in row for row in state["events"]))
    if state and state["manifest_verified"]:
        return _greenbelt_result(state, current)
    if deadline_at is not None and monotonic() + 12 >= deadline_at:
        raise ValueError("collection_deadline")
    if state is None:
        queue = _greenbelt_manifest(fetch(SOURCES[GREENBELT][0], "text/html"))
        started = current.astimezone(timezone.utc).isoformat()
        state = dict(version=1, source_key=GREENBELT, started_at=started,
                     window_start=current.astimezone(ZoneInfo(ZONE)).date().isoformat(),
                     manifest_hash=_greenbelt_digest(queue), manifest_count=len(queue), queue=queue,
                     cursor=0, events=[], diagnostics=[], manifest_verified=not queue)
        return _greenbelt_result(state, current)
    if state["cursor"] == state["manifest_count"]:
        queue = _greenbelt_manifest(fetch(SOURCES[GREENBELT][0], "text/html"))
        if queue != state["queue"]:
            raise ValueError("new_york_social_final_manifest_changed")
        state["manifest_verified"] = True
        return _greenbelt_result(state, current)
    if type(max_details) is not int or not 1 <= max_details <= 4:
        raise ValueError("new_york_social_final_record_limit")
    for _ in range(max_details):
        if state["cursor"] == state["manifest_count"] or (deadline_at is not None and monotonic() + 12 >= deadline_at):
            break
        item = state["queue"][state["cursor"]]
        row, reason = _greenbelt_detail(item, fetch(item["url"], "text/html"), current)
        if row:
            if legacy_prefix:
                row.pop("collector_event_content_v1", None)
            state["events"].append(row)
        state["diagnostics"].append(dict(event_url=item["url"], publisher_label=item["title"],
            publisher_native_id=item["id"], disposition="accepted" if row else "held", reason=reason))
        state["cursor"] += 1
    return _greenbelt_result(state, current)


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, max_details=2,
                  prepare_publisher=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if key not in CHECKPOINT_KEYS or current.tzinfo is None:
        raise ValueError("unregistered_new_york_social_final_source")
    if key == GREENBELT:
        return _greenbelt_chunk(fetch, checkpoint, deadline_at, current, max_details)
    state = _radegast_checkpoint(checkpoint, current)
    legacy_prefix = bool(state and state["events"] and
                         any("collector_event_content_v1" not in row for row in state["events"]))
    if state is not None and state.get("phase", "events") != "robots" and state["cursor"] == state["manifest_count"]:
        return _radegast_result(state, current)
    if deadline_at is not None and monotonic() + 12 >= deadline_at:
        raise ValueError("collection_deadline")
    page = state["next_page"] if state else 1
    url = RADEGAST_API + str(page)
    if prepare_publisher is not None and not prepare_publisher(url):
        # No event manifest has been requested. This explicit zero-event phase
        # is pending, never an empty successful calendar. The normal transport
        # attaches its authenticated, expiring robots cache at the RPC boundary.
        return _radegast_result(state or _new_radegast_state(0, current, bootstrap=True), current)
    count, native_events = _radegast_page(fetch(url, "application/json"), page)
    if state is None or state.get("phase") == "robots":
        # Policy bootstrap is part of this generation: retain its original
        # started_at/window anchor when the real manifest first becomes known.
        state = _new_radegast_state(count, timestamp(state["started_at"]) if state else current)
    elif count != state["manifest_count"] or set(state["seen_ids"]) & {event["id"] for event in native_events}:
        # A live pagination change invalidates the partial generation. Persist
        # a new empty generation; the next paced turn restarts with page one.
        if state["restarts"] >= 2:
            raise ValueError("new_york_social_final_manifest_changed")
        state = _new_radegast_state(count, current, state["restarts"] + 1)
        return dict(complete=count == 0, events=[], checkpoint=state)
    for native in native_events:
        rows, diagnostics = _radegast_event(native, current)
        if legacy_prefix:
            for row in rows:
                row.pop("collector_event_content_v1", None)
        state["events"].extend(rows)
        state["diagnostics"].extend(diagnostics)
        state["seen_ids"].append(native["id"])
    state["cursor"] += len(native_events)
    state["next_page"] += 1
    return _radegast_result(state, current)


def inspect_payload(key, payload, *, now=None):
    current = now or datetime.now(timezone.utc)
    if key not in SOURCES or current.tzinfo is None:
        raise ValueError("unregistered_new_york_social_final_source")
    if key in CHECKPOINT_KEYS:
        raise ValueError("new_york_social_final_checkpoint_required")
    parser = {WILD: _wild, SIP: _sip, PAUPER: _pauper, BRONX: _bronx, OSNYC: _osnyc}[key]
    rows, diagnostics = parser(payload, current)
    if len(rows) > MAX_RECORDS or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("new_york_social_final_record_limit")
    return sorted(rows, key=lambda row: (row["starts_at"], row["id"])), diagnostics


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError("collection_deadline")
    if key in CHECKPOINT_KEYS:
        result = collect_chunk(source, fetch, deadline_at=deadline_at, now=current)
        if not result["complete"]:
            raise ValueError("new_york_social_final_checkpoint_required")
        return result["events"]
    if key == BRONX:
        payload = fetch(_trivia_api_url(current), "application/json")
    else:
        payload = fetch(SOURCES[key][0], "text/html")
    return inspect_payload(key, payload, now=current)[0]
