"""Reviewed Hilton Head area direct calendars; no guessed streets or source-center pins.

Use the existing ICS recurrence/description parser and Squarespace JSON facts.
Each retained event has its OWN observed physical street. Publisher images are
candidates subject to the receiving database's separate rights/byte gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import plain, record
from roomquest.event_description import description

ZONE = "America/New_York"
HHSO = "hilton_head_symphony_sc"
CULTURE = "culture_hhi_events_sc"
ISLAND = "island_recreation_hhi_sc"
SHELTER = "shelter_cove_harbour_events_sc"
LINCOLN = "lincoln_south_brewing_hhi_sc"
SOURCES = {
    HHSO: ("https://hhso.org/events/?ical=1", "ical", "ical"),
    CULTURE: ("https://culturehhi.org/events/?ical=1", "ical", "ical"),
    ISLAND: ("https://www.islandreccenter.org/events?format=json", "json", "squarespace"),
    SHELTER: ("https://www.welcometosheltercove.com/calendar-of-events?format=json", "json", "squarespace"),
    LINCOLN: ("https://www.lincolnandsouth.com/events?format=json", "json", "squarespace"),
}
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
MAX_DESCRIPTION = 12000
MAX_ITEMS = 500
LOCALITIES = ("Hilton Head Island", "Bluffton", "Port Royal", "Beaufort")
SOURCE_PATHS = {
    HHSO: r"/events/[a-z0-9][a-z0-9-]*/?",
    CULTURE: r"/event/[a-z0-9][a-z0-9-]*/?",
    ISLAND: r"/events/[a-z0-9][a-z0-9-]*/?",
    SHELTER: r"/calendar-of-events/(?:20[0-9]{2}/[0-9]{2}/[0-9]{2}/)?[a-z0-9][a-z0-9-]*/?",
    LINCOLN: r"/events/[a-z0-9][a-z0-9-]*/?",
}
ADDRESS_IN_LOCATION = re.compile(
    r"^(?P<venue>.+?)(?:,\s*|\s+)"
    r"(?P<street>[0-9]{1,6}\s+[^,]{3,100}),\s*"
    r"(?P<city>Hilton Head Island|Bluffton|Port Royal|Beaufort),\s*"
    r"SC\b", re.I)
STREET = re.compile(r"^[0-9]{1,6}\s+[A-Za-z][A-Za-z0-9 .#'\-/]{2,120}$")
LOGGER = logging.getLogger(__name__)


def source_valid(source):
    if not isinstance(source, dict):
        return False
    key = source.get("source_key")
    return (key in SOURCES and
            (source.get("feed_url"), source.get("kind"),
             source.get("platform_adapter"), source.get("timezone")) ==
            (*SOURCES[key], ZONE))


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        return bool(p.scheme == "https" and p.username is None and p.password is None
                    and p.port in (None, 443) and not p.query and not p.fragment
                    and p.hostname == urlsplit(SOURCES[key][0]).hostname
                    and re.fullmatch(SOURCE_PATHS[key], p.path, re.I))
    except (ValueError, TypeError):
        return False


def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return None
        if p.query or p.fragment or re.search(r"\s|[<>]|(?:^|/)[.][.](/|$)", value):
            return None
        if re.search(r"(^|[-_/])(logo|icon|favicon|placeholder|avatar|pixel)([-_.]|$)",p.path,re.I):
            return None
        if re.search(r"-[0-9]{2,3}x[0-9]{2,3}\.", p.path, re.I):
            return None
        if key in (HHSO,CULTURE):
            if (p.hostname == urlsplit(SOURCES[key][0]).hostname
                and re.fullmatch(r"/wp-content/uploads/20[0-9]{2}/(?:0[1-9]|1[0-2])/"
                                 r"[^/\s?#]+\.(?:jpg|jpeg|png|webp)",p.path,re.I)):
                return value
        else:
            if (p.hostname == "images.squarespace-cdn.com"
                and p.path.startswith("/content/v1/") and len(p.path)>30):
                return value
    except (ValueError,TypeError):
        return None
    return None


def _narrative(value):
    result=description(value,limit=MAX_DESCRIPTION+1)
    if len(result)>MAX_DESCRIPTION:
        raise ValueError("publisher_description_over_limit")
    return result


def _address(venue, street, locality):
    """Require the publisher's event-specific numbered street, city, and state."""
    street=plain(street).strip(" ,")
    city=plain(locality).split(",")[0].strip()
    if not STREET.fullmatch(street) or city.casefold() not in {
            name.casefold() for name in LOCALITIES}:
        return None
    return f"{street}, {city}, SC"


def _complete_ics_location(value):
    source=plain(value).strip(" ,")
    m=ADDRESS_IN_LOCATION.match(source)
    if not m:
        return None
    name=plain(m.group("venue")).strip(" ,")
    street=plain(m.group("street"))
    city=plain(m.group("city"))
    if not name:
        return None
    # HHSO's First Presbyterian listing drops 'Hilton' from its officially
    # documented 540 William Hilton Parkway. Correct only this exact venue.
    if name == "First Presbyterian Church" and street == "540 William Parkway" and city == "Hilton Head Island":
        street="540 William Hilton Pkwy"
    address=_address(name, street, city)
    return (name,address,city) if address else None


def _ics_images(key, payload):
    """Use the same already-downloaded VCALENDAR; no detail-page crawling."""
    from icalendar import Calendar
    result={}
    for e in Calendar.from_ical(payload).walk("VEVENT"):
        uid=str(e.get("UID") or "")
        value=e.get("ATTACH")
        attachments=value if isinstance(value,list) else [value] if value is not None else []
        for item in attachments:
            url=str(item)
            if photo_url(key,url):
                result[uid]=url
                break
    return result


def _ics(key, payload):
    from roomquest.ics_adapter import parse
    from roomquest.publisher_evidence import attach
    base=SOURCES[key][0]
    data=payload.decode("utf-8","replace") if isinstance(payload,bytes) else payload
    if not isinstance(data,str):
        raise ValueError("invalid_ical_payload")
    rows=parse(data, {"source_key":key,"url":base,"feed_url":base,"timezone":ZONE},
               legacy=False,include_description=True)
    if len(rows)>MAX_ITEMS:
        raise ValueError("source_record_limit")
    imgs=_ics_images(key,data)
    accepted=[]
    for row in rows:
        if not event_url(key,row.get("event_url")):
            LOGGER.info("hilton_head_hold source=%s reason=event_url id=%s",key,row.get("id"))
            continue
        place=_complete_ics_location(row.get("venue_address") or row.get("venue_name"))
        if place is None:
            LOGGER.info("hilton_head_hold source=%s reason=street_missing id=%s",key,row.get("id"))
            continue
        venue,address,city=place
        narrative=_narrative(row.get("description"))
        if not narrative:
            LOGGER.info("hilton_head_hold source=%s reason=description_missing id=%s",key,row.get("id"))
            continue
        row.update(title=plain(row["title"]),venue_name=venue,venue_address=address,
                   venue_city=city,description=narrative,timezone=ZONE,
                   location_provenance="publisher_event_location")
        uid=str(row.get("id") or "").split("__",1)[0]
        accepted.append(attach(row,key,candidate=imgs.get(uid)))
    return accepted


def _squarespace(key, payload):
    """Native Upcoming records; reject stale site coordinates and blank venue facts."""
    from roomquest.squarespace import check_pagination
    from roomquest.publisher_evidence import attach
    data=json.loads(payload)
    if not isinstance(data,dict) or not isinstance(data.get("upcoming"),list):
        raise ValueError("invalid_squarespace_payload")
    if (data.get("website") or {}).get("timeZone") != ZONE:
        raise ValueError("publisher_timezone_changed")
    items=data["upcoming"]
    if len(items)>MAX_ITEMS:
        raise ValueError("source_record_limit")
    check_pagination(data,upcoming=True)
    output={}
    for item in items:
        if not isinstance(item,dict):
            raise ValueError("invalid_squarespace_record")
        if item.get("workflowState") != 1 or item.get("cancelled") or item.get("allDay") or item.get("allDayEvent"):
            continue
        if not isinstance(item.get("id"),str) or not item["id"]:
            raise ValueError("event_identity_missing")
        path=item.get("fullUrl")
        if not isinstance(path,str) or not path.startswith(urlsplit(SOURCES[key][0]).path.rstrip("/")+"/"):
            LOGGER.info("hilton_head_hold source=%s reason=event_url id=%s",key,item["id"])
            continue
        link=urljoin(SOURCES[key][0],path)
        if not event_url(key,link):
            continue
        v=item.get("location") or {}
        if not isinstance(v,dict):
            raise ValueError("invalid_event_location")
        venue=plain(v.get("addressTitle"))
        street=plain(v.get("addressLine1"))
        locality=plain(v.get("addressLine2"))
        address=_address(venue,street,locality)
        if not address or not venue:
            LOGGER.info("hilton_head_hold source=%s reason=street_missing id=%s",key,item["id"])
            continue
        # Never use Squarespace's 40.7207/-74.0007 NYC default coordinate.
        lat,lng=v.get("markerLat"),v.get("markerLng")
        if not (isinstance(lat,(int,float)) and not isinstance(lat,bool)
                and isinstance(lng,(int,float)) and not isinstance(lng,bool)
                and math.isfinite(lat) and math.isfinite(lng)
                and 32.0<=lat<=32.7 and -81.0<=lng<=-80.4):
            lat=lng=None
        try:
            narrative=_narrative(item.get("body") or item.get("excerpt"))
        except ValueError:
            LOGGER.info("hilton_head_hold source=%s reason=description_limit id=%s",key,item["id"])
            continue
        if not narrative:
            LOGGER.info("hilton_head_hold source=%s reason=description_missing id=%s",key,item["id"])
            continue
        start,end=item.get("startDate"),item.get("endDate")
        if (isinstance(start,bool) or not isinstance(start,(int,float))
                or not math.isfinite(start)
                or (end is not None and (isinstance(end,bool) or not isinstance(end,(int,float)) or not math.isfinite(end)))):
            raise ValueError("event_time_missing")
        if end is not None and end<start:
            raise ValueError("invalid_event_end")
        local_start=datetime.fromtimestamp(start/1000,timezone.utc).astimezone(ZoneInfo(ZONE))
        if local_start.hour==0 and local_start.minute==0 and (
            end is None or datetime.fromtimestamp(end/1000,timezone.utc).astimezone(ZoneInfo(ZONE)).hour==0):
            continue
        # Deterministic occurrence ID, including recurring entries with the same base ID.
        identity=item["id"]+":"+str(int(start))
        cats=item.get("categories") or []
        cats=[plain(x) for x in cats if isinstance(x,str) and plain(x)]
        row=record(item.get("title"),start,end,venue,address,
                   plain(locality).split(",")[0],link,identity,", ".join(cats),
                   lat,lng,ZONE,publisher_geo=True,retain_until_end=True)
        if row is None:
            continue
        row.update(description=narrative,timezone=ZONE,publisher_categories=cats,
                   location_provenance="publisher_event_location")
        # Full-resolution Squarespace CDN asset URL only; never select thumbnail query.
        candidate=photo_url(key,item.get("assetUrl"))
        row=attach(row,key,candidate=candidate)
        identity=(row["id"],row["starts_at"])
        if identity in output and output[identity]!=row:
            raise ValueError("conflicting_event_occurrence")
        output[identity]=row
    return sorted(output.values(),key=lambda e:(e["starts_at"],e["title"]))


def collect(source, fetch, *, deadline_at=None):
    if not source_valid(source):
        raise ValueError("unregistered_hilton_head_source")
    key=source["source_key"]
    url,kind,adapter=SOURCES[key]
    payload=fetch(url,"text/calendar" if kind=="ical" else "application/json")
    return _ics(key,payload) if kind=="ical" else _squarespace(key,payload)
