"""Anchorage batch20: strict event-venue SQS feeds (comedy & Audubon).

Do not default publisher multi-city comedy tours to an Anchorage venue. Allow
only named nearby Alaska municipalities, publisher event GPS and numbered
individual streets. This source family remains preview-only until batch 20/20.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.anchorage_sources import _description, NONPUBLIC, VIRTUAL, ZONE

COMEDY = "rubber_ptarmigan_anchorage_comedy_ak"
AUDUBON = "anchorage_audubon_society_ak"
REFUGE = "refuge_coffee_collab_ak"
SOURCES = {
    COMEDY: ("https://www.rubberptarmigan.com/events", "json", "squarespace"),
    AUDUBON: ("https://www.anchorageaudubon.org/annual-events-1", "json", "squarespace"),
    REFUGE: ("https://www.refugecoffeeak.com/events/", "json", "squarespace"),
}
ALLOWED_HOSTS = {k: (urlsplit(v[0]).hostname,) for k,v in SOURCES.items()}
PATHS = {
    COMEDY: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    AUDUBON: re.compile(r"/annual-events-1/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
    REFUGE: re.compile(r"/events/[a-z0-9]+(?:-[a-z0-9]+)*/?"),
}
CITIES = {"Anchorage","Wasilla","Palmer","Girdwood","Eagle River","Chugiak","Portage"}
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
MAX_RECORDS = 500
PHOTO_PATH = re.compile(r"/content/v1/[A-Za-z0-9]+/[A-Za-z0-9_-]+/[^?#]+\.(?:jpe?g|png|webp)",re.I)
PHOTO_BAD = re.compile(r"(?:^|[-_/])(?:logo|favicon|avatar|pixel|icon|placeholder)(?:[-_.]|$)",re.I)
STREET = re.compile(r"^\d{1,6}\s+[A-Za-z]")
CITY = re.compile(r"^([A-Za-z ]+),\s*(?:AK|Alaska)(?:,\s*(\d{5}))?$",re.I)
AUDUBON_POINT=(61.1902270,-149.863681)
REFUGE_POINT=(61.1901288,-149.9058736)
logger=logging.getLogger(__name__)


def _hold(key,ident,reason):
    logger.warning("anchorage_sqs_multi_held source=%s event=%s reason=%s",key,str(ident)[:80],reason)


def event_url(key,value):
    if key not in SOURCES or not isinstance(value,str) or len(value)>2000:
        return False
    try:
        p=urlsplit(value)
        return (p.scheme=="https" and p.hostname==urlsplit(SOURCES[key][0]).hostname
                and not p.username and not p.password and p.port in (None,443)
                and not p.query and not p.fragment and bool(PATHS[key].fullmatch(p.path)))
    except ValueError:
        return False


def photo_url(key,value):
    if key not in SOURCES or not isinstance(value,str) or len(value)>2000:
        return None
    try:
        p=urlsplit(value)
        return value if (
            p.scheme=="https" and p.netloc=="images.squarespace-cdn.com"
            and not p.query and not p.fragment and PHOTO_PATH.fullmatch(p.path)
            and not PHOTO_BAD.search(p.path)) else None
    except ValueError:
        return None


def _coords(v):
    try:
        lat,lng=float(v.get("mapLat")),float(v.get("mapLng"))
    except (TypeError,ValueError,OverflowError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not(60.5<lat<62.2 and -151.0<lng<-148.3):
        return None
    return lat,lng


def _near_anchorage(point, limit_miles=100):
    alat,alon=61.2181,-149.9003
    lat,lon=point
    rlat=math.radians(lat-alat)
    rlon=math.radians(lon-alon)
    q=math.sin(rlat/2)**2+math.cos(math.radians(alat))*math.cos(math.radians(lat))*math.sin(rlon/2)**2
    return 3958.7613*2*math.asin(min(1,math.sqrt(q))) <= limit_miles


def _venue(key, e):
    location=e.get("location") if isinstance(e.get("location"),dict) else {}
    point=_coords(location)
    if not point or not _near_anchorage(point):
        return None
    street=plain(location.get("addressLine1"))
    sub=plain(location.get("addressLine2"))
    m=CITY.fullmatch(sub)
    if not m or not STREET.search(street):
        return None
    city=m.group(1)
    if city not in CITIES:
        return None
    zipcode=m.group(2)
    if key==REFUGE:
        name=plain(location.get("addressTitle"))
        if (name.casefold() != "refuge coffee"
                or street.casefold() != "3309 spenard road"
                or city != "Anchorage" or zipcode != "99503"
                or abs(point[0]-REFUGE_POINT[0])>0.004
                or abs(point[1]-REFUGE_POINT[1])>0.004):
            return None
        return "Refuge Coffee","3309 Spenard Road, Anchorage, AK 99503",city,point
    if key==AUDUBON:
        if (street!="1014 Energy Court" or city!="Anchorage" or zipcode!="99508"
                or abs(point[0]-AUDUBON_POINT[0])>0.004
                or abs(point[1]-AUDUBON_POINT[1])>0.004):
            return None
        return "BP Energy Center","1014 Energy Court, Anchorage, AK 99508",city,point
    name=plain(location.get("addressTitle"))
    if not name:
        return None
    return name, f"{street}, {city}, AK"+(f" {zipcode}" if zipcode else ""),city,point


def _category(key,title,description):
    if key==REFUGE:
        if re.fullmatch(r"Open Mic Night\s*",title,re.I) and re.search(r"\bopen mic\b",description,re.I):
            return "music"
        return None
    if key==AUDUBON:
        if title=="December Evening Program":
            return "hang_out" # Official December program is potluck/social
        if re.search(r"evening program|annual lecture|bird watching|birding|winter walk",title,re.I):
            return "learn"
        return None
    if re.search(r"comedy|comedian|stand-?up|improv|laughing|comic|comed",title+" "+description,re.I):
        return "movies_theater"
    return None


def _row(key,e,now):
    if not isinstance(e,dict) or not isinstance(e.get("id"),str):
        raise ValueError("invalid_multi_squarespace_event")
    ident=e["id"]
    if e.get("workflowState")!=1 or e.get("cancelled") or e.get("allDay") or e.get("allDayEvent"):
        return None
    title=plain(e.get("title"))
    if (not title or NONPUBLIC.search(title) or VIRTUAL.search(title)
            or re.search(r"\b(?:canceled|cancelled|postponed|members? only)\b",title,re.I)):
        return None
    start,end=e.get("startDate"),e.get("endDate")
    if any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t)
           for t in (start,end)):
        return None
    begins,ends=timestamp(start),timestamp(end)
    if ends<=begins or ends<=now or begins>now+timedelta(days=WINDOW_DAYS):
        return None
    desc=_description(e.get("body") or e.get("excerpt"))
    if desc is None:
        _hold(key,ident,"description_missing_or_unreviewable")
        return None
    category=_category(key,title,desc)
    if not category:
        _hold(key,ident,"core_category_requires_review")
        return None
    place=_venue(key,e)
    if place is None:
        _hold(key,ident,"event_publisher_location_unverified_or_outside_anchorage")
        return None
    original=e.get("fullUrl")
    url=urljoin(SOURCES[key][0],original) if isinstance(original,str) else ""
    if not event_url(key,url):
        _hold(key,ident,"canonical_event_link_invalid")
        return None
    name,addr,city,point=place
    row=record(title,begins.isoformat(),ends.isoformat(),name,addr,city,
               url,ident,category,lat=point[0],lng=point[1],
               tz=ZONE,publisher_geo=True,retain_until_end=True)
    if row is None:return None
    row.update(description=desc,category=category,timezone=ZONE,
               publisher_categories=[plain(x) for x in e.get("categories",[]) if isinstance(x,str)],
               location_provenance="publisher_event_specific_street_and_GPS")
    from roomquest.publisher_evidence import attach
    # Publisher image rights are unreviewed: no image candidates for this new source.
    from roomquest.squarespace import original_content
    row['collector_event_content_v1'] = original_content(e, row, SOURCES[key][0], desc)
    return attach(row,key,candidate=None if key==REFUGE else e.get("assetUrl"))


def collect(source,fetch,*,deadline_at=None,now=None):
    key=source.get("source_key")
    if (key not in SOURCES
            or (source.get("feed_url"),source.get("kind"),source.get("platform_adapter"))!=SOURCES[key]
            or source.get("timezone")!=ZONE):
        raise ValueError("unregistered_anchorage_batch20_multi_source")
    now=calendar_anchor(now or datetime.now(timezone.utc))
    deadline=min(monotonic()+38,deadline_at if deadline_at is not None else float("inf"))
    if monotonic()>=deadline:raise ValueError("collection_deadline")
    data=json.loads(fetch(SOURCES[key][0]+"?format=json","application/json"))
    if not isinstance(data,dict) or not isinstance(data.get("upcoming"),list):
        raise ValueError("invalid_multi_squarespace_payload")
    if (data.get("website") or {}).get("timeZone")!=ZONE:
        raise ValueError("publisher_timezone_changed")
    from roomquest.squarespace import check_pagination
    check_pagination(data,upcoming=True)
    if len(data["upcoming"])>MAX_RECORDS:
        raise ValueError("source_record_limit")
    result={}
    for e in data["upcoming"]:
        if monotonic()>=deadline:raise ValueError("collection_deadline")
        row=_row(key,e,now)
        if row is None:continue
        ident=row["id"],row["starts_at"]
        if ident in result and result[ident]!=row:
            raise ValueError("conflicting_multi_publisher_occurrence")
        result[ident]=row
    return sorted(result.values(),key=lambda x:(x["starts_at"],x["title"],x["id"]))
