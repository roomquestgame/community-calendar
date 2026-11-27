"""Anchorage rolling 20-source intake: verified primary Squarespace event calendars.

This is a bounded *collector-only* branch. Do NOT enroll any of these sources
until the full batch of 20 publishers passes all release gates in issue #1192.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit
from time import monotonic
import json
import logging
import math
import re

from roomquest.collection_window import calendar_anchor
from roomquest.anchorage_sources import ZONE, _description, NONPUBLIC, VIRTUAL
from roomquest.mapsee_adapter import plain, record, timestamp

MAGNETIC = "magnetic_north_brewing_ak"
WINERY = "61_degrees_north_winery_ak"
ACEH = "anchorage_coalition_homelessness_ak"
AWAKEN = "awaken_church_anchorage_ak"
MAKING = "making_space_art_therapy_ak"
ART = "the_art_lounge_anchorage_ak"
JOULE = "joule_wellness_sound_bath_ak"
DANCE = "alaska_dance_promotions_ak"
MATSU_SOCIAL = "matsu_community_social_ak"

SOURCES = {
    MAGNETIC: ("https://magneticnorthbrewingco.com/events", "json", "squarespace"),
    WINERY: ("https://www.61degreesnorthwinery.com/calendar", "json", "squarespace"),
    ACEH: ("https://aceh.squarespace.com/events", "json", "squarespace"),
    AWAKEN: ("https://www.awakenalaska.com/events", "json", "squarespace"),
    MAKING: ("https://www.makingspacetogether.com/events", "json", "squarespace"),
    ART: ("https://www.theartloungeak.com/classes-events", "json", "squarespace"),
    JOULE: ("https://www.joulewellness.co/events", "json", "squarespace"),
    DANCE: ("https://www.alaskadancepromotions.com/events", "json", "squarespace"),
    MATSU_SOCIAL: ("https://www.matsudems.org/events", "json", "squarespace"),
}
ALLOWED_HOSTS = {key: (urlsplit(tup[0]).hostname,) for key, tup in SOURCES.items()}
VENUES = {
    MAGNETIC: ("Magnetic North Brewing Company",
               "8861 Golovin Street, Anchorage, AK 99507", "Anchorage",
               (61.1405217, -149.8371101)),
    WINERY: ("61 Degrees North Winery",
             "5001 Arctic Blvd Suite 101, Anchorage, AK 99503", "Anchorage",
             None),  # publisher JSON contains generic NYC pin: geocode must occur downstream
    ACEH: ("Anchorage Coalition to End Homelessness",
           "3427 East Tudor Road Suite A, Anchorage, AK 99507", "Anchorage",
           None),  # use each event's own legitimate map coordinates, not a source pin
    AWAKEN: ("Awaken Church",
             "5295 Juneau Street, Anchorage, AK 99518", "Anchorage",
             (61.1723554, -149.862599)),
    MAKING: ("Making Space | Art Therapy & Community",
             "1441 West Northern Lights Boulevard, Anchorage, AK 99503", "Anchorage",
             (61.1956075, -149.9109034)),
    ART: ("The Art Lounge AK",
          "300 East Dimond Boulevard, Anchorage, AK 99515", "Anchorage",
          (61.1443709, -149.8757727)),
    JOULE: ("Thrive Integrative Medicine",
            "3835 Spenard Road, Anchorage, AK", "Anchorage",
            (61.1857685, -149.9185543)),
    DANCE: ("Alaska Dance Promotions",
            "300 East Dimond Boulevard, Suite 11A, Anchorage, AK 99515", "Anchorage",
            (61.1444086, -149.875721)),
    MATSU_SOCIAL: ("Chepo's", "3001 Sun Mountain Avenue, Wasilla, AK 99654", "Wasilla",
                   (61.5723678, -149.3880472)),
}
logger = logging.getLogger(__name__)
MAX_DESCRIPTION = 12000
MAX_EVENTS = 500
WINDOW_DAYS = 60
URL_BY_KEY = {
    MAGNETIC: re.compile(r"/events/20[0-9]{2}/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    WINERY: re.compile(r"/calendar/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    ACEH: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    AWAKEN: re.compile(r"/events/(?:20[0-9]{2}/[0-9]{1,2}/[0-9]{1,2}/)?[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    MAKING: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    ART: re.compile(r"/classes-events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    JOULE: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    DANCE: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    MATSU_SOCIAL: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
}
PHOTO_PATH = re.compile(r"/content/v1/[A-Za-z0-9]+/[A-Za-z0-9_-]+/[^?#]+\.(?:jpe?g|png|webp)", re.I)
PHOTO_BAD = re.compile(r"(?:^|[-_/])(?:favicon|logo|icon|avatar|pixel|placeholder)(?:[-_.]|$)", re.I)


def _hold(key, identity, reason):
    logger.warning("anchorage_batch20_held source=%s event=%s reason=%s", key, str(identity)[:80], reason)


def event_url(key, url):
    if key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == urlsplit(SOURCES[key][0]).hostname
                and not p.username and not p.password and p.port in (None, 443)
                and not p.query and not p.fragment and bool(URL_BY_KEY[key].fullmatch(p.path)))
    except ValueError:
        return False


def photo_url(key, url):
    if key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        p = urlsplit(url)
        return (url if p.scheme == "https" and p.netloc == "images.squarespace-cdn.com"
                and not p.query and not p.fragment and PHOTO_PATH.fullmatch(p.path)
                and not PHOTO_BAD.search(p.path) else None)
    except ValueError:
        return None


def _publisher_point(location):
    if not isinstance(location, dict):
        return None
    try:
        point = float(location.get("mapLat")), float(location.get("mapLng"))
    except (ValueError, TypeError, OverflowError):
        return None
    if not all(math.isfinite(x) for x in point):
        return None
    if not (59.0 < point[0] < 63.0 and -152.0 < point[1] < -147.0):
        return None  # Never trust Squarespace's generic NYC marker.
    return point


def _official_site_venue(key, title, desc, location):
    """Source-wide street is allowed only after specific onsite evidence.

    Winery's publisher JSON has no venue location and a false NYC map marker.
    Only original event bodies explicitly identifying the Winery can inherit
    its independently verified address; coordinates remain absent for geocoding.
    All other sources require the event's own venue street.
    """
    venue, street, city, reviewed_point = VENUES[key]
    if key == WINERY:
        if (any(plain(location.get(field)) for field in ("addressTitle", "addressLine1", "addressLine2"))
                or not re.search(r"61(?:\s*Degrees|\s*°)?\s*North|61°\s*N", desc, re.I)
                or re.search(r"\b(?:offsite|off-site|different venue|other location)\b", title+" "+desc, re.I)):
            return None
        return venue, street, city, None
    loc_street = plain(location.get("addressLine1"))
    loc_city = plain(location.get("addressLine2"))
    point = _publisher_point(location)
    if key == MATSU_SOCIAL:
        if (plain(location.get("addressTitle")).strip().casefold() not in {"chepo's", "chepo’s"}
                or not re.fullmatch(r"3001 Sun Mountain Avenue", loc_street, re.I)
                or not re.fullmatch(r"Wasilla,\s*(?:AK|Alaska),\s*99654", loc_city, re.I)
                or point is None
                or abs(point[0] - reviewed_point[0]) > 0.004
                or abs(point[1] - reviewed_point[1]) > 0.004):
            return None
        return venue, street, city, point
    if key == DANCE:
        if (plain(location.get("addressTitle")).casefold() != "alaska dance promotions"
                or loc_street.casefold() not in {
                    "300 east dimond boulevard",
                    "300 e. dimond blvd, ste 11a",
                    "300 east dimond blvd, ste 11a"}
                or loc_city.casefold() not in {
                    "anchorage, ak, 99515", "anch, ak, 99515", "anchorage"}
                or point is None or abs(point[0] - reviewed_point[0]) > 0.004
                or abs(point[1] - reviewed_point[1]) > 0.008):
            return None
        return venue, street, city, point
    if key in (MAKING, ART, JOULE):
        expected = {
            MAKING: (r"1441 West Northern Lights Boulevard", r"Anchorage,\s*AK,\s*99503",
                     {"making space | art therapy & community"}),
            ART: (r"300 East Dimond Boulevard", r"Anchorage,\s*AK,\s*99515",
                  {"the art lounge ak - suite 3", "the art lounge ak - suite 300"}),
            JOULE: (r"3835 Spenard Road", r"Anchorage,\s*AK",
                    {"thrive integrative medicine"}),
        }[key]
        if (not re.fullmatch(expected[0], loc_street, re.I)
                or not re.fullmatch(expected[1], loc_city, re.I)
                or plain(location.get("addressTitle")).casefold() not in expected[2]
                or point is None
                or abs(point[0] - reviewed_point[0]) > 0.004
                or abs(point[1] - reviewed_point[1]) > 0.004):
            return None
        return venue, street, city, point
    if key == MAGNETIC:
        if (not re.fullmatch(r"8861 Golovin Street", loc_street, re.I)
                or not re.fullmatch(r"Anchorage,\s*AK,\s*99507", loc_city, re.I)
                or plain(location.get("addressTitle")).casefold() not in
                    {"magnetic north brewing company", "magnetic north brewing co.", "magnetic north brewing co", ""}):
            return None
    elif key == AWAKEN:
        if (not re.fullmatch(r"5295 Juneau Street", loc_street, re.I)
                or not re.fullmatch(r"Anchorage,\s*AK,\s*99518", loc_city, re.I)):
            return None
    elif key == ACEH:
        if (not re.fullmatch(r"3427 East Tudor Road(?:,? Suite A)?", loc_street, re.I)
                or not re.fullmatch(r"Anchorage,\s*AK,\s*99507", loc_city, re.I)):
            return None
    if point is None:
        return None
    if reviewed_point is not None and (
            abs(point[0] - reviewed_point[0]) > 0.004
            or abs(point[1] - reviewed_point[1]) > 0.004):
        return None
    return venue, street, city, point


def _category(key, title):
    t = title.casefold()
    if key == MAGNETIC:
        if "sweater" in t and "ornament" in t:
            return "create"
        if "stoplight night" in t:
            return "hang_out"
        if "carol" in t or "sing-along" in t:
            return "music"
    elif key == WINERY:
        if any(x in t for x in ("beaded", "kinusaiga", "workshop", "art class")):
            return "create"
    elif key == ACEH:
        if "volunteer opportunity" in t or "outreach kit" in t:
            return "give_back"
    elif key == AWAKEN:
        if "wreath" in t or "craft" in t:
            return "create"
        if "breakfast" in t or "cookie" in t:
            return "food_drink"
        if "christmas party" in t:
            return "party"
    elif key == MAKING:
        if "studio art sale" in t:
            return "arts_culture"
        if "art therapy" in t or "open studio" in t:
            return "create"
    elif key == ART:
        if re.search(r"book club|lecture|creative writing", t):
            return "learn"
        if re.search(r"market|bazaar|fair", t):
            return "festival"
        if re.search(r"moon gathering|solstice gathering|blessing ball|social hour", t):
            return "hang_out"
        if re.search(
            r"paint|watercolor|felt|sew|stitch|macrame|bead|craft|candle|cyanotype|"
            r"embroid|bow|workshop|class|ornament|clay|crochet|hat|charcuterie|"
            r"wood|wool|needle|slipper|pour|lantern|trucker|mushroom", t
        ):
            return "create"
    elif key == JOULE:
        if "sound bath" in t or "meditation" in t:
            return "health"
    elif key == MATSU_SOCIAL:
        if t == "mat-su dems northern lights social":
            return "hang_out"  # Neutral public social gathering, no political categorization or advocacy.
    elif key == DANCE:
        if "festival" in t:
            return "festival"
        if "christmas collection" in t:
            return "movies_theater"
        if "dance party" in t or "friday night dance lounge" in t:
            return "party"
    return None


def _row(key, event, now):
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise ValueError("invalid_batch20_publisher_event")
    if event.get("workflowState") != 1 or event.get("cancelled") or event.get("allDay") or event.get("allDayEvent"):
        return None
    identity = event["id"]
    title = plain(event.get("title"))
    if (not title or NONPUBLIC.search(title) or VIRTUAL.search(title)
            or re.search(r"\b(?:no sunday|closed|canceled|cancelled|postponed|rental)\b", title, re.I)):
        return None
    category = _category(key, title)
    if category is None:
        _hold(key, identity, "core_category_unverified")
        return None
    start_raw, end_raw = event.get("startDate"), event.get("endDate")
    if (any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in (start_raw, end_raw))):
        _hold(key, identity, "event_times_missing")
        return None
    starts, ends = timestamp(start_raw), timestamp(end_raw)
    # The publisher labels a 224-day FNDL listing as one "upcoming" event.
    # It describes recurring Friday dance nights but supplies no distinct
    # occurrence times; never invent weekly recurrences or publish a months-long
    # party as a continuous event. Genuine Dance events last a few hours.
    if key == DANCE and ends - starts > timedelta(days=1):
        _hold(key, identity, "recurring_program_without_dated_occurrences")
        return None
    if ends <= starts or ends <= now or starts > now + timedelta(days=WINDOW_DAYS):
        return None
    desc = _description(event.get("body") or event.get("excerpt"))
    if not desc:
        _hold(key, identity, "description_missing_oversized_or_truncated")
        return None
    location = event.get("location") if isinstance(event.get("location"), dict) else {}
    reviewed = _official_site_venue(key, title, desc, location)
    if reviewed is None:
        _hold(key, identity, "publisher_specific_venue_unverified")
        return None
    original = event.get("fullUrl")
    link = urljoin(SOURCES[key][0], original) if isinstance(original, str) else ""
    if not event_url(key, link):
        _hold(key, identity, "publisher_event_permalink_unverified")
        return None
    venue, street, city, gps = reviewed
    row = record(title, starts.isoformat(), ends.isoformat(), venue, street, city,
                 link, identity, category,
                 lat=gps[0] if gps else None, lng=gps[1] if gps else None,
                 tz=ZONE, publisher_geo=bool(gps), retain_until_end=True)
    if row is None:
        return None
    row.update(description=desc, category=category, timezone=ZONE,
               location_provenance=("publisher_exact_event_venue" if gps else
                                    "publisher_event_venue_official_street_needs_geocode"),
               publisher_categories=[plain(x) for x in event.get("categories", []) if isinstance(x, str)])
    if gps is None:
        row.update(reason="missing_verified_venue_geo")
    from roomquest.publisher_evidence import attach
    return attach(row, key, candidate=event.get("assetUrl"))


def collect(source, fetch, *, deadline_at=None, now=None, retain_original=False):
    key = source.get("source_key")
    if (key not in SOURCES or
            (source.get("feed_url"), source.get("kind"), source.get("platform_adapter")) != SOURCES[key]
            or source.get("timezone") != ZONE):
        raise ValueError("unregistered_anchorage_batch20_source")
    now = calendar_anchor(now or datetime.now(timezone.utc))
    deadline = min(monotonic() + 36, deadline_at if deadline_at is not None else float("inf"))
    if monotonic() >= deadline:
        raise ValueError("collection_deadline")
    data = json.loads(fetch(SOURCES[key][0] + "?format=json", "application/json"))
    if not isinstance(data, dict) or not isinstance(data.get("upcoming"), list):
        raise ValueError("invalid_batch20_squarespace_payload")
    if (data.get("website") or {}).get("timeZone") != ZONE:
        raise ValueError("publisher_timezone_changed")
    from roomquest.squarespace import check_pagination, original_content
    check_pagination(data, upcoming=True)
    if len(data["upcoming"]) > MAX_EVENTS:
        raise ValueError("source_record_limit")
    results = {}
    for event in data["upcoming"]:
        if monotonic() >= deadline:
            raise ValueError("collection_deadline")
        row = _row(key, event, now)
        if row is None:
            continue
        if retain_original:
            row["collector_event_content_v1"] = original_content(event, row, source["feed_url"], row["description"])
        identity = (row["id"], row["starts_at"])
        if identity in results and results[identity] != row:
            raise ValueError("conflicting_publisher_occurrence")
        results[identity] = row
    return sorted(results.values(), key=lambda row: (row["starts_at"], row["id"]))
