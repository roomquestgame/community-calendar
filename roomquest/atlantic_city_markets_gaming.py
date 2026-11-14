"""Reviewed Atlantic County market and game calendars with complete prose.

The TCG Show publishes one explicitly dated show with two admission phases.
Reed's Farm uses a public Boom Calendar embedded by its own Wix page. Fetch its
normal anonymous visitor configuration, then the exact public calendar. Keep
complete event prose, explicit dates, bounded weekly rules and holiday closures.

Top Deck's captured iCalendar parser remains research-only: Google's robots
policy disallows its feed path. It is absent from active profiles and collect
rejects its source before any I/O; transport policy is never bypassed.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil.rrule import rrulestr
from icalendar import Calendar, vText

from roomquest.atlantic_city_community import _full_description, _nj_address
from roomquest.atlantic_city_venues import narrative
from roomquest.ics_adapter import _prune_expired_until_groups, parse as parse_ics
from roomquest.mapsee_adapter import plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = "America/New_York"
TCG = "atlantic_city_tcg_show_nj"
TOP_DECK = "top_deck_games_eht_nj"
REEDS = "reeds_farm_nj"
SOURCES = {
    TCG: ("https://atlanticcitytcgshow.com/", "html", "html"),
    REEDS: ("https://www.reedsorganicfarm.org/events", "html", "html"),
}
HELD_SOURCES = {
    TOP_DECK: ("https://www.topdeckgamesonline.com/", "html", "html"),
}
ALLOWED_HOSTS = {
    TCG: ("atlanticcitytcgshow.com",),
    REEDS: ("www.reedsorganicfarm.org", "calendar.apiboomtech.com"),
}
EHT_CALENDAR_ID = "c_5385067b58f27f44ae97c9f25f30663769585cc48a2299dc6f29fc5096cc4763@group.calendar.google.com"
EHT_ICS = "https://calendar.google.com/calendar/ical/" + quote(EHT_CALENDAR_ID, safe="") + "/public/basic.ics"
REEDS_COMPONENT = "comp-licdd8bx"
REEDS_CALENDAR_ID = 130306
REEDS_APP = "13b4a028-00fa-7133-242f-4628106b8c91"
REEDS_INSTANCE = "e3ad6bf3-fb7f-4dcf-a152-ee85fbea3882"
REEDS_SITE = "35120278-9c3b-4e9a-b957-8f5de1fe8b05"
REEDS_VISITOR = "https://www.reedsorganicfarm.org/_api/v1/access-tokens"
REEDS_API = "https://calendar.apiboomtech.com/api/published_calendar"
MAX_DESCRIPTION = 12_000
MAX_RAW_EVENTS = 1000
MAX_EVENTS = 500
VENUES = {
    TCG: ("Showboat Resort Atlantic City", "801 Boardwalk, Atlantic City, NJ 08401", "Atlantic City"),
    TOP_DECK: ("Top Deck Games — Egg Harbor Township", "3003 English Creek Ave, Egg Harbor Township, NJ 08234", "Egg Harbor Township"),
    REEDS: ("Reed's Farm", "5075 Spruce Ave, Egg Harbor Township, NJ 08234", "Egg Harbor Township"),
}
# The publishers confirm these exact streets on their own pages. Reviewed NJ
# Office of GIS geocoding returns score-100 PointAddress results, not ZIP/city
# centroids. Keep the tuple literals independent of VENUES so a changed venue
# can never inherit the previous point.
# https://www.showboathotelac.com/contact
# https://www.topdeckgamesonline.com/
# https://geo.nj.gov/arcgis/rest/services/Tasks/NJ_Geocode/GeocodeServer/findAddressCandidates
REVIEWED_POINTS = {
    (TCG, "Showboat Resort Atlantic City", "801 Boardwalk, Atlantic City, NJ 08401"):
        (39.361572000003, -74.418345000001),
    (TOP_DECK, "Top Deck Games — Egg Harbor Township", "3003 English Creek Ave, Egg Harbor Township, NJ 08234"):
        (39.433320000003, -74.613613500001),
}
NONPUBLIC = re.compile(r"\b(?:cancell?ed|postponed|closed|private\s+(?:event|party)|members?[- ]only)\b", re.I)


def event_url(key, value):
    return key in SOURCES and isinstance(value, str) and value == SOURCES[key][0]


def _source(source):
    key = source.get("source_key")
    if (key not in SOURCES or (source.get("feed_url"), source.get("kind"),
            source.get("platform_adapter"), source.get("timezone")) != (*SOURCES[key], ZONE)):
        raise ValueError("unregistered_atlantic_markets_gaming_source")
    return key


def _text(value):
    # Already normalized publisher text must not be parsed as HTML again:
    # escaped angle-bracket instructions are meaningful event prose.
    if not isinstance(value, str) or not value.strip():
        raise ValueError("atlantic_markets_gaming_description_missing")
    if len(value) > MAX_DESCRIPTION:
        raise ValueError("atlantic_markets_gaming_description_limit")
    return value


def _point(row, key):
    point = REVIEWED_POINTS.get((key, row.get("venue_name"), row.get("venue_address")))
    if point:
        row.update(lat=point[0], lng=point[1],
                   location_provenance="reviewed_nj_ogis_point_address")
        if row.get("reason") == "missing_verified_venue_geo":
            row["reason"] = None
    return row


def _within(start, end, now):
    return start < now + timedelta(days=60) and (end or start) > now


def _clock(day, value):
    value = re.sub(r"\s+", "", value).upper()
    fmt = "%I:%M%p" if ":" in value else "%I%p"
    try:
        return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)
    except ValueError as exc:
        raise ValueError("atlantic_markets_gaming_schedule_changed") from exc


def _tcg(payload, now):
    soup = BeautifulSoup(payload, "html.parser")
    headings = soup.select('h1[data-aid="ABOUT_HEADLINE_RENDERED0"]')
    if len(headings) != 1:
        raise ValueError("atlantic_markets_gaming_shape_changed")
    heading = plain(headings[0].get_text())
    match = re.fullmatch(r"Next Show:\s*(\w+)\s+(\w+ \d{1,2})(?:st|nd|rd|th)?,\s*(20\d{2})", heading, re.I)
    if not match:
        raise ValueError("atlantic_markets_gaming_schedule_changed")
    try:
        day = datetime.strptime(match[2] + " " + match[3], "%B %d %Y").date()
    except ValueError as exc:
        raise ValueError("atlantic_markets_gaming_schedule_changed") from exc
    if day.strftime("%A").casefold() != match[1].casefold():
        raise ValueError("atlantic_markets_gaming_schedule_changed")
    section = headings[0].find_parent("section")
    offer = section.select_one('[data-aid="ABOUT_DESCRIPTION_RENDERED0"]') if section else None
    if offer is None:
        raise ValueError("atlantic_markets_gaming_shape_changed")
    offer_text = narrative(offer)
    clocks = re.findall(r"(Early Bird|General Admission)\s+(\d{1,2}(?::\d{2})?\s*[AP]M)\s*[-–]\s*(\d{1,2}(?::\d{2})?\s*[AP]M)", offer_text, re.I)
    if len(clocks) != 2 or [c[0].casefold() for c in clocks] != ["early bird", "general admission"]:
        raise ValueError("atlantic_markets_gaming_schedule_changed")
    early_start, early_end = (_clock(day, v) for v in clocks[0][1:])
    general_start, general_end = (_clock(day, v) for v in clocks[1][1:])
    if not early_start < early_end == general_start < general_end:
        raise ValueError("atlantic_markets_gaming_schedule_changed")
    contact = soup.select_one('[data-aid="CONTACT_INFO_ADDRESS_REND"]')
    expected = "Showboat Resort Atlantic City, 801 Boardwalk, Atlantic City, NJ, USA"
    if (not contact or plain(contact.get_text()) != expected
            or "Showboat Resort Atlantic City NJ" not in plain(offer.get_text())):
        raise ValueError("atlantic_markets_gaming_venue_changed")
    titles = soup.select('[data-aid="ABOUT_SECTION_TITLE_RENDERED"]')
    about = [node.find_parent("section") for node in titles
             if plain(node.get_text()) == "About Atlantic City TCG Show"]
    if len(about) != 1:
        raise ValueError("atlantic_markets_gaming_shape_changed")
    cards = about[0].select('[data-ux="ContentCard"]')
    if not cards or len(cards) > 20:
        raise ValueError("atlantic_markets_gaming_shape_changed")
    parts = [heading, offer_text, "About Atlantic City TCG Show"]
    for card in cards:
        # GoDaddy includes invisible sizing headlines for adjacent cards.
        # data-aid marks the actual published headline and complete body.
        title = card.select('[data-aid^="ABOUT_HEADLINE_RENDERED"]')
        body = card.select('[data-aid^="ABOUT_DESCRIPTION_RENDERED"]')
        if len(title) != 1 or len(body) != 1:
            raise ValueError("atlantic_markets_gaming_shape_changed")
        parts.extend((narrative(title[0]), narrative(body[0])))
    description = _text("\n".join(parts))
    if not _within(early_start, general_end, now):
        return []
    venue, address, city = VENUES[TCG]
    row = record("Atlantic City TCG Show", early_start.isoformat(), general_end.isoformat(),
                 venue, address, city, SOURCES[TCG][0], "ac-tcg-show:" + day.isoformat(),
                 "Trading cards, markets and hobbies", tz=ZONE, retain_until_end=True)
    if row is None:
        return []
    row.update(description=description, attendance_mode="in_person", timezone=ZONE)
    return [_point(row, TCG)]


def _top_deck_calendar(payload):
    soup = BeautifulSoup(payload, "html.parser")
    matched = []
    for frame in soup.select("iframe[src]"):
        parsed = urlsplit(frame["src"])
        if parsed.scheme != "https" or parsed.netloc != "calendar.google.com" or parsed.path != "/calendar/embed":
            continue
        query = parse_qs(parsed.query)
        if query.get("title") != ["Top Deck Games - EHT Events"]:
            continue
        if query.get("ctz") != [ZONE] or len(query.get("src", [])) != 1:
            raise ValueError("atlantic_markets_gaming_calendar_changed")
        value = query["src"][0]
        try:
            identity = base64.b64decode(value + "===", validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("atlantic_markets_gaming_calendar_changed") from exc
        if identity != EHT_CALENDAR_ID:
            raise ValueError("atlantic_markets_gaming_calendar_changed")
        matched.append(identity)
    if len(matched) != 1:
        raise ValueError("atlantic_markets_gaming_calendar_changed")
    # The same multi-store page must still associate this calendar with the
    # reviewed EHT street; unrelated stores must never inherit its location.
    text = plain(soup.get_text(" "))
    if not re.search(r"egg harbor township\s+3003 English Creek Ave\s+Egg Harbor Township, NJ 08234", text, re.I):
        raise ValueError("atlantic_markets_gaming_venue_changed")
    return EHT_ICS


def _top_deck_location(value):
    raw = plain(value)
    if not raw:
        return VENUES[TOP_DECK], "explicit_eht_calendar_venue_association"
    stripped = re.sub(r"^Top Deck Games(?:\s*[-–—]\s*Egg Harbor Township)?\s*,?\s*", "", raw, flags=re.I)
    location = _nj_address(stripped)
    if location:
        address, city = location
        if address in (VENUES[TOP_DECK][1], VENUES[TOP_DECK][1].rsplit(" ", 1)[0]):
            return VENUES[TOP_DECK], "publisher_street_address"
        if not re.search(r", NJ \d{5}(?:-\d{4})?$", address):
            return None
        # An explicit offsite address remains offsite. It receives neither the
        # EHT venue name nor its reviewed map point.
        return (address.split(",", 1)[0], address, city), "publisher_street_address"
    # Preserve an explicit offsite venue prefix before its structured street.
    match = re.fullmatch(r"([^,]+),\s*(\d.*)", raw)
    location = _nj_address(match[2]) if match else None
    if location and re.search(r", NJ \d{5}(?:-\d{4})?$", location[0]):
        return (match[1].strip(), location[0], location[1]), "publisher_street_address"
    return None


def _validated_calendar(payload):
    if not payload.lstrip("\ufeff \r\n").upper().startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in payload.upper():
        raise ValueError("invalid_calendar_payload")
    cal = Calendar.from_ical(payload)
    if str(cal.get("X-WR-CALNAME", "")) != "04. EHT - Public" or str(cal.get("X-WR-TIMEZONE", "")) != ZONE:
        raise ValueError("atlantic_markets_gaming_calendar_changed")
    events = cal.walk("VEVENT")
    if len(events) > MAX_RAW_EVENTS:
        raise ValueError("source_record_limit")
    for event in events:
        if event.errors:
            if any(str(error[0]).upper() in {"RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"} for error in event.errors):
                raise ValueError("recurrence_invalid")
            raise ValueError("invalid_ical_component")
        if not str(event.get("UID", "")).strip():
            raise ValueError("atlantic_markets_gaming_event_identity")
        start = event.decoded("DTSTART", None)
        if start is None:
            raise ValueError("invalid_ical_missing_start")
        if event.get("RRULE"):
            rule = event["RRULE"]
            frequency = str((rule.get("FREQ") or [""])[0]).upper()
            density = 1
            for field in ("BYSECOND", "BYMINUTE", "BYHOUR", "BYDAY"):
                density *= max(1, len(rule.get(field) or []))
            if frequency not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"} or density > 24:
                raise ValueError("unsupported_dense_recurrence")
            try:
                rrulestr(rule.to_ical().decode(), dtstart=start)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError("recurrence_invalid") from exc
        # Normalize the complete raw description once, before the shared
        # parser's 12,000-character raw limit. Long markup cannot clip prose.
        event["DESCRIPTION"] = vText(_full_description(str(event.get("DESCRIPTION", ""))))
    return cal


def _top_deck(payload, now):
    calendar = _validated_calendar(payload)
    calendar = _prune_expired_until_groups(calendar, now)
    rows = parse_ics(calendar.to_ical().decode(),
                     {"url": HELD_SOURCES[TOP_DECK][0], "source_key": TOP_DECK},
                     legacy=False, include_description=True)
    result = []
    identities = set()
    for row in rows:
        if NONPUBLIC.search(row.get("title", "")):
            continue
        if row.get("event_url") != HELD_SOURCES[TOP_DECK][0]:
            raise ValueError("atlantic_markets_gaming_event_identity")
        start, end = timestamp(row.get("starts_at")), timestamp(row.get("ends_at"))
        if not start or end and end <= start:
            raise ValueError("atlantic_markets_gaming_schedule_changed")
        if not _within(start, end, now):
            continue
        body = _text(row.get("description"))
        resolved = _top_deck_location(row.get("venue_address"))
        if not resolved:
            log.warning("atlantic_markets_gaming_record_held source=%s id=%s reason=venue_street_unresolved",
                        TOP_DECK, row.get("id"))
            continue
        location, provenance = resolved
        identity = (row.get("id"), row.get("starts_at"))
        if not identity[0] or identity in identities:
            raise ValueError("atlantic_markets_gaming_event_identity")
        identities.add(identity)
        row.update(description=body, venue_name=location[0], venue_address=location[1],
                   venue_city=location[2], attendance_mode="in_person", timezone=ZONE,
                   location_provenance=provenance)
        result.append(_point(row, TOP_DECK))
    if len(result) > MAX_EVENTS:
        raise ValueError("source_record_limit")
    return sorted(result, key=lambda r: (r["starts_at"], r["id"]))


def _reeds_context(payload):
    soup = BeautifulSoup(payload, "html.parser")
    essential = soup.select('script#wix-essential-viewer-model[type="application/json"]')
    full = soup.select('script#wix-viewer-model[type="application/json"]')
    if len(essential) != 1 or len(full) != 1:
        raise ValueError("atlantic_markets_gaming_calendar_changed")
    try:
        first = json.loads(essential[0].get_text())
        model = json.loads(full[0].get_text())
        widget = model["siteFeaturesConfigs"]["tpaCommons"]["widgetsClientSpecMapData"]["14fcce6e-b2fe-c9dc-1831-64f837bb83f6"]
        valid = (first["accessTokensUrl"] == REEDS_VISITOR
                 and model["site"]["metaSiteId"] == REEDS_SITE
                 and widget["appDefinitionId"] == REEDS_APP
                 and widget["widgetUrl"] == "https://calendar.boomte.ch/widget")
    except (ValueError, KeyError, TypeError):
        raise ValueError("atlantic_markets_gaming_calendar_changed") from None
    canonical = soup.select_one('link[rel="canonical"]')
    if (not valid or not canonical or canonical.get("href") != SOURCES[REEDS][0]
            or not soup.select_one("#" + REEDS_COMPONENT + " iframe")):
        raise ValueError("atlantic_markets_gaming_calendar_changed")
    if not re.search(r"5075 Spruce Ave\s+Egg Harbor Township, NJ 08234", plain(soup.get_text(" "))):
        raise ValueError("atlantic_markets_gaming_venue_changed")
    return REEDS_VISITOR


def _reeds_api_url(payload):
    try:
        data = json.loads(payload)
        instance = data["apps"][REEDS_APP]["instance"]
        if (data.get("metaSiteId") != REEDS_SITE or not isinstance(instance, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{20,1500}\.[A-Za-z0-9_=-]{20,2000}", instance)):
            raise ValueError
        # These are public guest widget claims, not user account credentials.
        # Forward the unchanged server-issued instance only to its actual
        # published-calendar endpoint. Never log it or attach it to a row.
        scope = json.loads(base64.urlsafe_b64decode(instance.split(".")[1] + "==="))
        if (scope.get("instanceId") != REEDS_INSTANCE or scope.get("appDefId") != REEDS_APP
                or scope.get("siteMemberId") or scope.get("permissions")):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise ValueError("atlantic_markets_gaming_public_widget_changed") from None
    return REEDS_API + "?" + urlencode({"comp_id": REEDS_COMPONENT, "instance": instance, "time_zone": ZONE})


def _boom_datetime(value, zone):
    if zone != ZONE or not isinstance(value, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", value):
        raise ValueError("atlantic_markets_gaming_schedule_changed")
    return timestamp(value, ZONE)


def _boom_occurrences(item):
    """Match Boom's published bounded weekly expansion, including exclusions.

    The reviewed widget uses ISO weekdays (6 = Saturday). Numeric `end` is
    the number of non-excluded occurrences *per selected weekday*, not a year
    or an arbitrary search window. Its `never` weekly setting is capped at 104.
    Explicit nonrecurring additional dates retain the complete description.
    The widget repeats recurring additions separately; fail closed until that
    unobserved shape is supported rather than silently publishing one date.
    """
    start = _boom_datetime(item.get("start"), item.get("time_zone"))
    end = _boom_datetime(item.get("end"), item.get("time_zone"))
    if end <= start or end - start > timedelta(days=1):
        raise ValueError("atlantic_markets_gaming_schedule_changed")
    repeat = item.get("repeat")
    if not isinstance(repeat, dict):
        raise ValueError("atlantic_markets_gaming_recurrence_changed")
    exclusions = repeat.get("exclude", [])
    additions = repeat.get("additionalDates", [])
    if (not isinstance(exclusions, list) or len(exclusions) > 500 or not isinstance(additions, list)
            or len(additions) > 500 or any(not isinstance(v, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", v) for v in exclusions)):
        raise ValueError("atlantic_markets_gaming_recurrence_changed")
    output = []
    mode = repeat.get("type")
    if mode not in ("", None) and additions:
        raise ValueError("atlantic_markets_gaming_recurrence_changed")
    if mode in ("", None):
        output.append((start, end))
    elif mode in ("Week", "Weekly", "Weekl"):
        advanced = repeat.get("advanced")
        if (not isinstance(advanced, list) or not 1 <= len(advanced) <= 7
                or any(str(v) not in {str(i) for i in range(8)} for v in advanced)
                or not re.fullmatch(r"[1-9]\d?", str(repeat.get("interval")))):
            raise ValueError("atlantic_markets_gaming_recurrence_changed")
        weekdays = [int(v) or 7 for v in advanced]
        interval = int(repeat["interval"])
        if len(set(weekdays)) != len(weekdays) or interval > 52:
            raise ValueError("atlantic_markets_gaming_recurrence_changed")
        stop = str(repeat.get("end", ""))
        count, until = None, None
        if stop == "never":
            count = 104
        elif re.fullmatch(r"[1-9]\d{0,3}", stop):
            count = int(stop)
            if count > 1000:
                raise ValueError("atlantic_markets_gaming_recurrence_changed")
        else:
            until = _boom_datetime(stop + "T00:00" if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", stop) else stop, ZONE)
        duration = end - start
        for weekday in weekdays:
            current = start + timedelta(days=(weekday - start.isoweekday()) % 7)
            accepted = 0
            for _ in range(5000):
                if (count is not None and accepted >= count) or (until is not None and current >= until):
                    break
                if current.date().isoformat() not in exclusions:
                    output.append((current, current + duration))
                    accepted += 1
                current += timedelta(weeks=interval)
            else:
                raise ValueError("atlantic_markets_gaming_recurrence_changed")
    else:
        raise ValueError("atlantic_markets_gaming_recurrence_changed")
    for additional in additions:
        if not isinstance(additional, dict) or additional.get("allDay") not in (False, 0):
            raise ValueError("atlantic_markets_gaming_recurrence_changed")
        begins = _boom_datetime(additional.get("start"), item.get("time_zone"))
        ends = _boom_datetime(additional.get("end"), item.get("time_zone"))
        if ends <= begins or ends - begins > timedelta(days=1):
            raise ValueError("atlantic_markets_gaming_schedule_changed")
        output.append((begins, ends))
    return sorted(set(output))


def _reeds_location(item):
    venue = item.get("venue")
    if not isinstance(venue, dict) or venue.get("locationType") != "physical":
        return None
    parsed = _nj_address(venue.get("address"))
    if not parsed or not re.search(r", NJ \d{5}(?:-\d{4})?$", parsed[0]):
        return None
    address, city = parsed
    name = plain(venue.get("name")) or (VENUES[REEDS][0] if address == VENUES[REEDS][1] else address.split(",", 1)[0])
    lat, lng = None, None
    if address == VENUES[REEDS][1]:
        try:
            a, b = float(venue.get("lat")), float(venue.get("lng"))
            if math.isfinite(a) and math.isfinite(b) and 39.37 <= a <= 39.40 and -74.60 <= b <= -74.57:
                lat, lng = a, b
        except (ValueError, TypeError):
            pass
    return name, address, city, lat, lng


def _dated_expired(item, now):
    """Ignore only provably past, nonrecurring historical cards.

    Some old Boom entries have no time zone. Their two dated boundaries are
    already more than a complete calendar day before UTC collection day, so
    no valid local offset can bring them into this window. Retain any rule,
    additional date, reversed interval or unparseable clock for validation.
    """
    repeat = item.get("repeat")
    if not isinstance(repeat, dict) or repeat.get("type") or repeat.get("additionalDates"):
        return False
    try:
        start, end = (datetime.fromisoformat(item[field]) for field in ("start", "end"))
        return start <= end and end.date() < now.date() - timedelta(days=1)
    except (TypeError, ValueError, KeyError):
        return False


def _preorder_window(item):
    if not re.search(r"\bpre[- ]?orders?\b", str(item.get("title", "")), re.I):
        return False
    try:
        start, end = (datetime.fromisoformat(item[field]) for field in ("start", "end"))
        return end - start > timedelta(days=1) and not any((start.hour, start.minute, end.hour, end.minute))
    except (TypeError, ValueError, KeyError):
        return False


def _reeds(payload, now):
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        raise ValueError("atlantic_markets_gaming_calendar_changed") from None
    if (not isinstance(data, dict) or data.get("id") != REEDS_CALENDAR_ID
            or data.get("comp_id") != REEDS_COMPONENT or data.get("instance") != REEDS_INSTANCE
            or data.get("url") != SOURCES[REEDS][0] or data.get("published") != 1
            or data.get("time_zone") != ZONE or not isinstance(data.get("events"), list)
            or data.get("synced_events") not in ([], None) or data.get("tokens") not in ([], None)):
        raise ValueError("atlantic_markets_gaming_calendar_changed")
    events = data["events"]
    if len(events) > MAX_RAW_EVENTS:
        raise ValueError("source_record_limit")
    closures = []
    for item in events:
        if (not isinstance(item, dict) or item.get("comp_id") != REEDS_COMPONENT
                or item.get("instance") != REEDS_INSTANCE or not isinstance(item.get("id"), int)):
            raise ValueError("atlantic_markets_gaming_event_identity")
        # All reviewed public rows are kind 1. The widget hides some other
        # kinds; an unfamiliar kind must never leak into the public feed.
        if item.get("kind") != "1":
            raise ValueError("atlantic_markets_gaming_calendar_changed")
        if _dated_expired(item, now):
            continue
        if re.search(r"\bclosed\b", str(item.get("title", "")), re.I):
            closed_location = _reeds_location(item)
            if item.get("all_day") != 0 or not closed_location:
                raise ValueError("atlantic_markets_gaming_schedule_changed")
            closures.extend((begins, ends, closed_location[1])
                            for begins, ends in _boom_occurrences(item))
    output = {}
    for item in events:
        if _dated_expired(item, now):
            continue
        title = plain(item.get("title"))
        if not title or len(title) > 180:
            raise ValueError("atlantic_markets_gaming_event_identity")
        # All-day preorder windows and retail notices have no event clock.
        # The three explicitly published holiday closures are handled above.
        if NONPUBLIC.search(title) or item.get("all_day") != 0 or _preorder_window(item):
            continue
        occurrences = [(s, e) for s, e in _boom_occurrences(item) if _within(s, e, now)]
        if not occurrences:
            continue
        body = _full_description(item.get("desc"))
        if not body:
            log.warning("atlantic_markets_gaming_record_held source=%s id=%s reason=description_unavailable", REEDS, item["id"])
            continue
        body = _text(body)
        location = _reeds_location(item)
        if not location:
            log.warning("atlantic_markets_gaming_record_held source=%s id=%s reason=venue_street_unresolved", REEDS, item["id"])
            continue
        venue, address, city, lat, lng = location
        for start, end in occurrences:
            if any(address == closed_street and start < stop and end > begins
                   for begins, stop, closed_street in closures):
                continue
            identity = "reeds-farm:" + str(item["id"]) + ":" + start.strftime("%Y%m%dT%H%M")
            row = record(title, start.isoformat(), end.isoformat(), venue, address, city,
                         SOURCES[REEDS][0], identity, lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
            if row is not None:
                row.update(description=body, attendance_mode="in_person", timezone=ZONE,
                           location_provenance="publisher_event_venue_coordinates" if lat is not None else "publisher_street_address")
                if identity in output and output[identity] != row:
                    raise ValueError("atlantic_markets_gaming_event_identity")
                output[identity] = row
    if len(output) > MAX_EVENTS:
        raise ValueError("source_record_limit")
    return sorted(output.values(), key=lambda r: (r["starts_at"], r["id"]))


def collect(source, fetch, *, deadline_at=None, now=None):
    key = _source(source)
    now = now or datetime.now(timezone.utc)

    def get(url, accept="text/html"):
        if deadline_at is not None and monotonic() >= deadline_at - 1:
            raise ValueError("collection_deadline")
        return fetch(url, accept)

    payload = get(SOURCES[key][0])
    if key == TCG:
        return _tcg(payload, now)
    public_instance = get(_reeds_context(payload), "application/json")
    return _reeds(get(_reeds_api_url(public_instance), "application/json"), now)
