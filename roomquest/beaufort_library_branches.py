"""Beaufort County Library first-party branch ICS for Hilton Head/Lowcountry.

Only the original publisher iCalendar feed is fetched. Every event is
street-verified against the actual official branch directory, with publisher
GPS screened against that branch. Offsite, closure, private, incomplete,
overlength or unclassified records are held; never mapped to source centers.
Existing ICS recurrence/time and 60-day bounded collection are reused.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit
import logging
import re

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain

ZONE = "America/New_York"
BASE = "https://beaufort.librarycalendar.com/events/feed/ical"
HOST = "beaufort.librarycalendar.com"
MAX_DESCRIPTION = 12000
MAX_ITEMS = 500
CORE_CATEGORIES = frozenset({
    "hang_out","food_drink","get_active","outdoors","create","learn","give_back",
    "new_here","party","music","sports","festival","movies_theater","arts_culture",
    "health","civic","playgrounds","trails","gardens_nature","museums_discovery",
    "sports_recreation","swimming_water_play","climbing_adventure",
    "picnic_gathering","dogs_pets",
})
LOGGER = logging.getLogger(__name__)

# Branch identifiers from publisher's own public branch-select form (2026-11-18).
# Street numbers from the library's official locations directory.
# Locations and native GEO in the dated first-party branch ICS snapshots.
SOURCES = {
    "beaufort_library_hilton_head_sc": (
        77, "Hilton Head Branch Library", "11 Beach City Rd",
        "Hilton Head Island", "29926", 32.2188014, -80.7135683,
        "11 Beach City Rd, Hilton Head Island, SC, 29926, US"),
    "beaufort_library_bluffton_sc": (
        74, "Bluffton Branch Library", "120 Palmetto Way",
        "Bluffton", "29910", 32.2412511, -80.8572539,
        "120 Palmetto Way, Bluffton, SC, 29910, US"),
    "beaufort_library_beaufort_sc": (
        72, "Beaufort Library", "311 Scott St",
        "Beaufort", "29902", 32.4322104, -80.6703374,
        "311 Scott St, Beaufort, SC, 29902, US"),
    "beaufort_library_port_royal_sc": (
        79, "Port Royal Branch Library", "1408 Paris Ave",
        "Port Royal", "29935", 32.3794219, -80.6923446,
        "1408 Paris Ave, Port Royal, SC, 29935, US"),
    "beaufort_library_lobeco_sc": (
        78, "Lobeco Branch Library", "1862 Trask Pkwy",
        "Lobeco", "29931", 32.5552852, -80.7448265,
        "1862 Trask Parkway, (Hwy 17), Lobeco, SC, 29931, US"),
}
ALLOWED_HOSTS = {key: (HOST,) for key in SOURCES}


def feed_url(key):
    if key not in SOURCES:
        raise ValueError("unregistered_beaufort_library_source")
    code = SOURCES[key][0]
    return f"{BASE}?branches%5B{code}%5D={code}"


def source_valid(source):
    if not isinstance(source, dict):
        return False
    key = source.get("source_key")
    return (key in SOURCES and
            (source.get("feed_url"), source.get("kind"),
             source.get("platform_adapter"), source.get("timezone")) ==
            (feed_url(key), "ical", "ical", ZONE))


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value)>2000:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == HOST
                and p.username is None and p.password is None
                and p.port in (None, 443) and not p.query and not p.fragment
                and re.fullmatch(r"/event/[a-z0-9]+(?:-[a-z0-9]+)*/?",p.path,re.I) is not None)
    except (TypeError, ValueError):
        return False


def photo_url(key, value):
    """Only original first-party publisher media; no site icons or thumbnails."""
    if key not in SOURCES or not isinstance(value,str) or len(value)>2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme!="https" or p.hostname!=HOST or p.query or p.fragment
                or p.username or p.password or p.port not in (None,443)):
            return None
        if re.search(r"(^|[-_/])(icon|logo|avatar|favicon|placeholder|thumbnail)([-_.]|$)",
                     p.path,re.I):
            return None
        if re.search(r"-[0-9]{2,4}x[0-9]{2,4}[.]",p.path,re.I) or ".." in p.path:
            return None
        if re.fullmatch(r"/sites/default/files/(?:20[0-9]{2}/)?[a-z0-9_./-]+[.](?:jpg|jpeg|png|webp)",
                        p.path,re.I):
            return value
    except (ValueError, TypeError):
        return None
    return None


CATEGORY_HINTS = {
    "arts & crafts": "create",
    "games & activities": "hang_out",
    "technology": "learn",
    "storytime": "learn",
    "read to a dog": "learn",
    "book club": "learn",
    "nature & gardening": "gardens_nature",
    "talks & presentations": "learn",
    "steam/stem": "learn",
    "holiday": "party",
    "health & wellness": "health",
    "author event": "learn",
    "community showcase": "arts_culture",
    "movie": "movies_theater",
    "music": "music",
    "local history": "arts_culture",
}
PRIVATE = re.compile(r"\b(staff event|staff only|private meeting|invitation only)\b", re.I)
CIVIC = re.compile(
    r"\b(board of trustees|board meeting|advisory board|public hearing|"
    r"assessor'?s office|job fair|works:|friends of the library|fol bookstore meeting)\b", re.I)
CREATIVE = re.compile(
    r"\b(c\.?r\.?e\.?a\.?t\.?e\.? theatre|cursive lesson|watercolor|"
    r"painting class|craft workshop|write-in at|knitting|crochet|sewing class)\b", re.I)
MUSIC = re.compile(
    r"\b(concert|harp ensemble|choir|music performance|community jam|"
    r"strummers|recital|live music)\b", re.I)
PARTY = re.compile(r"\b(new year'?s eve fun|holiday festival|holiday party)\b", re.I)
LEARN = re.compile(r"\b(storytime|book club|read to a dog|writing workshop|book talk)\b", re.I)
SOCIAL = re.compile(r"\b(teen takeover|puzzle swap|mahjong|minecraft day|game club|dungeons)\b", re.I)


def category_for(title, labels):
    """Use per-event publisher evidence; no Other or catch-all library default."""
    if PRIVATE.search(title):
        return None
    for pattern, value in ((CIVIC,"civic"),(CREATIVE,"create"),(MUSIC,"music"),
                           (PARTY,"party"),(LEARN,"learn"),(SOCIAL,"hang_out")):
        if pattern.search(title):
            return value
    for label in labels:
        core = CATEGORY_HINTS.get(plain(label).casefold())
        if core:
            return core
    return None


def _raw_evidence(payload, key):
    from icalendar import Calendar
    original = {}
    calendar = Calendar.from_ical(payload)
    vevents = calendar.walk("VEVENT")
    if len(vevents) > 1000:
        raise ValueError("source_record_limit")
    for e in vevents:
        uid = str(e.get("UID") or "")
        if not uid:
            raise ValueError("event_identity_missing")
        raw = e.get("DESCRIPTION")
        prose = description(str(raw) if raw is not None else "",limit=MAX_DESCRIPTION+1)
        if uid in original and original[uid]["description"] != prose:
            raise ValueError("conflicting_publisher_ical_description")
        attachments = e.get("ATTACH")
        candidates = attachments if isinstance(attachments,list) else [attachments] if attachments is not None else []
        image = next((str(item) for item in candidates if photo_url(key,str(item))),None)
        original[uid] = {"description":prose,"image":image}
    return original


def _hold(key, event, reason):
    LOGGER.info("beaufort_library_hold source=%s event=%s reason=%s",
                key,str(event)[:100],reason)


def collect(source, fetch, *, deadline_at=None):
    if not source_valid(source):
        raise ValueError("unregistered_beaufort_library_source")
    from roomquest.ics_adapter import parse
    from roomquest.publisher_evidence import attach
    key=source["source_key"]
    code, venue, street, city, postal, ref_lat, ref_lng, expected_location = SOURCES[key]
    url=feed_url(key)
    payload=fetch(url,"text/calendar")
    if isinstance(payload,bytes):
        payload=payload.decode("utf-8","replace")
    if not isinstance(payload,str):
        raise ValueError("invalid_ical_payload")
    original=_raw_evidence(payload,key)
    events=parse(payload,{"source_key":key,"url":url,"feed_url":url,"timezone":ZONE},
                 legacy=False, include_description=True)
    if len(events)>MAX_ITEMS:
        raise ValueError("source_record_limit")
    output={}
    official=f"{street}, {city}, SC {postal}"
    for row in events:
        event_id=row.get("id")
        uid=str(event_id or "").split("__",1)[0]
        original_event=original.get(uid)
        if original_event is None:
            _hold(key,event_id,"ical_event_uid_missing")
            continue
        prose=original_event["description"]
        if not prose or len(prose)>MAX_DESCRIPTION:
            _hold(key,event_id,"description_missing_or_oversize")
            continue
        if plain(row.get("venue_address") or row.get("venue_name")).casefold() != plain(expected_location).casefold():
            _hold(key,event_id,"offsite_or_unverified_street")
            continue
        lat,lng=row.get("lat"),row.get("lng")
        if (not isinstance(lat,(int,float)) or isinstance(lat,bool)
                or not isinstance(lng,(int,float)) or isinstance(lng,bool)
                or abs(lat-ref_lat)>0.005 or abs(lng-ref_lng)>0.005):
            _hold(key,event_id,"publisher_geo_inconsistent_with_branch_street")
            continue
        if not event_url(key,row.get("event_url")):
            _hold(key,event_id,"event_url_unverified")
            continue
        title=plain(row.get("title"))
        labels=row.get("publisher_categories") or []
        if not isinstance(labels,list):
            raise ValueError("invalid_publisher_categories")
        primary=category_for(title,labels)
        if not primary:
            _hold(key,event_id,"core_category_unresolved_or_private")
            continue
        row.update(title=title,venue_name=venue,venue_address=official,
                   venue_city=city,description=prose,category=primary,
                   publisher_categories=[plain(v) for v in labels if plain(v)],
                   timezone=ZONE,lat=lat,lng=lng,
                   location_provenance="publisher_ical_event_branch_geo",
                   category_provenance="publisher_event_type_and_title")
        row=attach(row,key,candidate=original_event["image"])
        identity=(row["id"],row["starts_at"])
        if identity in output and output[identity]!=row:
            raise ValueError("conflicting_event_occurrence")
        output[identity]=row
    return sorted(output.values(),key=lambda r:(r["starts_at"],r["title"],r["id"]))
