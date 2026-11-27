"""Anchorage batch20: bounded official WordPress Events Calendar JSON feeds.

Use first-party TEC API with one/two-page bounded pagination. Unreviewed venues,
academic deadlines, promotional store hours, private events and missing narratives
are held, never converted into fake city points. Everything stays unpublished
until the 20-source batch gate is satisfied.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest.collection_window import calendar_anchor
from roomquest.anchorage_sources import _description, _event_category, NONPUBLIC, VIRTUAL, ZONE
from roomquest.mapsee_adapter import plain, record

VISIT_PALMER = "visit_palmer_community_calendar_ak"
AWCC = "alaska_wildlife_conservation_center_ak"
APU = "alaska_pacific_university_events_ak"
SEW = "winter_solstice_sewing_crafts_ak"

SOURCES = {
    VISIT_PALMER: ("https://visitpalmer.com/wp-json/tribe/events/v1/events", "json", "wordpress"),
    AWCC: ("https://alaskawildlife.org/wp-json/tribe/events/v1/events", "json", "wordpress"),
    APU: ("https://www.alaskapacific.edu/wp-json/tribe/events/v1/events", "json", "wordpress"),
    SEW: ("https://wintersolsticecrafts.com/wp-json/tribe/events/v1/events", "json", "wordpress"),
}
ALLOWED_HOSTS = {k: (urlsplit(v[0]).hostname,) for k, v in SOURCES.items()}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 250
MAX_PAGES = 5
WINDOW_DAYS = 60
AWCC_VENUE = ("Alaska Wildlife Conservation Center",
              "43520 Seward Highway, Portage, AK 99587", "Portage",
              (60.821359136434815, -148.97859183491985))
# APU's public calendar has many academic deadlines. These exact public
# events and own official facilities were reviewed; all others are held.
APU_REVIEWED = {
    "Elder Tea": ("Grant Hall, Student Lounge Room 125", "4101 University Drive", "hang_out"),
    "Grad Night Fall 2026": ("Carr-Gottstein Academic Center", "4225 University Drive", "hang_out"),
    "2026 Fall Commencement": ("Wendy Williamson Auditorium", "2533 Providence Dr", "arts_culture"),
}
PALMER_CITIES = {"Palmer", "Wasilla", "Big Lake", "Sutton", "Houston", "Eagle River",
                 "Anchorage", "Willow", "Chickaloon", "Girdwood", "Portage", "Butte",
                 "Chugiak", "Meadow Lakes", "Talkeetna"}
PUBLISHER_EVENT_PATH = re.compile(r"/event/[a-z0-9]+(?:-[a-z0-9]+)*/?")
STREET = re.compile(r"^\s*\d{1,6}\s+[A-Za-z]", re.I)
BAD = re.compile(r"\b(?:cancelled|canceled|postponed|private\s+(?:party|event)|"
                 r"members?\s+only|holiday hours|special hours|office closed|"
                 r"discount offer|registration closed)\b", re.I)
logger = logging.getLogger(__name__)


def _hold(key, identity, reason):
    logger.warning("anchorage_tec_event_held source=%s event=%s reason=%s",
                   key, str(identity)[:80], reason)


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == urlsplit(SOURCES[key][0]).hostname
                and not p.username and not p.password and p.port in (None, 443)
                and not p.query and not p.fragment and bool(PUBLISHER_EVENT_PATH.fullmatch(p.path)))
    except ValueError:
        return False


def photo_url(key, value):
    """Reject derived/resized thumbnails, nonpublisher hosts and badges."""
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        allowed = urlsplit(SOURCES[key][0]).hostname
        return (value if p.scheme == "https" and p.hostname == allowed
                and "/wp-content/uploads/" in p.path and
                re.search(r"\.(?:jpe?g|png|webp)$",p.path,re.I)
                and not p.query and not p.fragment
                and not re.search(r"(?:^|[/_-])(?:logo|avatar|pixel|favicon|icon)(?:$|[/_.-])",p.path,re.I)
                else None)
    except ValueError:
        return None


def _time(value):
    if not isinstance(value, str):
        raise ValueError("unverified_tec_datetime")
    try:
        return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError("unverified_tec_datetime") from e


def _times(e):
    if e.get("timezone") != ZONE:
        return None
    try:
        begin, end = _time(e.get("utc_start_date")), _time(e.get("utc_end_date"))
        local_b = datetime.fromisoformat(e["start_date"].replace(" ", "T")).replace(tzinfo=ZoneInfo(ZONE))
        local_e = datetime.fromisoformat(e["end_date"].replace(" ", "T")).replace(tzinfo=ZoneInfo(ZONE))
        if (begin != local_b.astimezone(timezone.utc)
                or end != local_e.astimezone(timezone.utc) or end <= begin):
            return None
        return begin, end
    except (ValueError, KeyError, TypeError):
        return None


def _coords(venue):
    try:
        lat,lng=float(venue.get("geo_lat")),float(venue.get("geo_lng"))
    except (ValueError,TypeError,OverflowError):
        return None
    if (not math.isfinite(lat) or not math.isfinite(lng)
            or not 59.0 < lat < 63.0 or not -153.0 < lng < -147.0):
        return None
    return lat,lng


def _venue(source_key, e):
    value=e.get("venue")
    if not isinstance(value,dict):
        return None
    name=plain(value.get("venue"))
    street=plain(value.get("address"))
    city=plain(value.get("city"))
    state=plain(value.get("state"))
    zipcode=plain(value.get("zip"))
    if source_key==SEW:
        if (name.casefold() not in {"winter solstice sewing & crafts", "winter solstice sewing and crafts"}
                or street.casefold() != "400 w potter drive"
                or city != "Anchorage" or state not in ("AK", "Alaska")
                or zipcode != "99518"):
            return None
        # Verified exact event street, never a generic point. Geocode before
        # publication, just like Visit Palmer and the Winery.
        return "Winter Solstice Sewing & Crafts", "400 W Potter Drive, Anchorage, AK 99518", city, None
    if source_key==AWCC:
        if (name.casefold()!="alaska wildlife conservation center"
                or street.casefold()!="mile 79 seward highway" or city!="Portage"
                or state not in ("AK","Alaska") or zipcode!="99587"):
            return None
        return AWCC_VENUE
    if source_key==APU:
        title=plain(e.get("title"))
        reviewed=APU_REVIEWED.get(title)
        if (reviewed is None or name!=reviewed[0] or street!=reviewed[1]
                or city!="Anchorage" or state not in ("","AK","Alaska")):
            return None
        point=_coords(value)
        if point is None:
            return None
        return name,f"{street}, Anchorage, AK",city,point
    if (not name or not STREET.search(street) or city not in PALMER_CITIES
            or state not in ("","AK","Alaska") or (zipcode and not re.fullmatch(r"99\d{3}",zipcode))):
        return None
    street_full=f"{street}, {city}, AK"+(f" {zipcode}" if zipcode else "")
    return name,street_full,city,_coords(value)


def _category(source_key, title, e, desc):
    if source_key==SEW:
        if re.search(r"sew|serg|quilt|embroider|yarn|knit|crochet|mittens?|project|maker space|fabric|fleece|tote|finishing|sewing machine|dress",title,re.I):
            return "create"
        return None
    if source_key==AWCC:
        if re.search(r"\b(?:christmas bird count|birdwatching|nature walk|guided hike)\b",title,re.I):
            return "gardens_nature"
        return None
    if source_key==APU:
        return APU_REVIEWED.get(title, (None,None,None))[2]
    labels=[plain(c.get("name")) for c in e.get("categories",[])
            if isinstance(c,dict) and c.get("name")]
    initial=_event_category(title,labels,desc)
    if initial:
        return initial
    if re.search(r"music|unplugged|concert|songwriter|live band|open mic",title,re.I):
        return "music"
    if re.search(r"market|bazaar|festival|fair|holiday expo",title,re.I):
        return "festival"
    if re.search(r"symposium|science|history|seminar|workshop|course|presentation|class|demo",title,re.I):
        return "learn"
    if re.search(r"bike|run|hike|ski|outdoor",title,re.I):
        return "get_active"
    if re.search(r"craft|crochet|paint|art|mushroom|bead|weave|sew|knit|maker",title,re.I):
        return "create"
    if re.search(r"trivia|game night|competition|tournament",title,re.I):
        return "sports"
    if re.search(r"author|book signing",title,re.I):
        return "learn"
    if re.search(r"community gathering|social|networking|open house",title,re.I):
        return "hang_out"
    return None


def _event(source_key, e, now):
    if not isinstance(e,dict):
        raise ValueError("invalid_tec_event_record")
    identity=e.get("id")
    if isinstance(identity,bool) or not isinstance(identity,(str,int)) or not str(identity).isdigit():
        raise ValueError("tec_event_id_missing")
    title=plain(e.get("title"))
    if (not title or BAD.search(title) or NONPUBLIC.search(title) or VIRTUAL.search(title)
            or e.get("status") not in (None,"publish")
            or e.get("event_status") in ("cancelled","canceled","postponed")
            or e.get("all_day") or e.get("is_virtual") or e.get("virtual")):
        return None
    if source_key==AWCC and ("military monday" in title.casefold() or "holiday hours" in title.casefold()):
        return None  # Deals, visitor notices and access promotions are not dated activities.
    dates=_times(e)
    if dates is None or dates[1] <= now or dates[0] > now+timedelta(days=WINDOW_DAYS):
        return None
    venue=_venue(source_key,e)
    if venue is None:
        _hold(source_key,identity,"event_venue_street_unverified")
        return None
    desc=_description(e.get("description"))
    if desc is None:
        _hold(source_key,identity,"description_missing_or_oversized")
        return None
    category=_category(source_key,title,e,desc)
    if not category:
        _hold(source_key,identity,"core_category_review")
        return None
    url=e.get("url")
    if not event_url(source_key,url):
        _hold(source_key,identity,"publisher_url_unverified")
        return None
    name,street,city,point=venue
    row=record(title,dates[0].isoformat(),dates[1].isoformat(),
               name,street,city,url,str(identity),category,
               lat=point[0] if point else None,lng=point[1] if point else None,
               tz=ZONE,publisher_geo=bool(point),retain_until_end=True)
    if row is None:
        return None
    row.update(description=desc,category=category,timezone=ZONE,
               publisher_categories=[plain(c.get("name")) for c in e.get("categories",[])
                 if isinstance(c,dict) and c.get("name")],
               location_provenance=("official_awcc_coordinates" if source_key==AWCC else
                 "publisher_exact_tec_event_venue" if point else "publisher_explicit_street_await_geocode"))
    if point is None:
        row["reason"]="missing_verified_venue_geo"
    from roomquest.publisher_evidence import attach
    image=e.get("image")
    return attach(row,source_key,candidate=(image.get("url") if isinstance(image,dict) else None))


def collect(source,fetch,*,deadline_at=None,now=None):
    key=source.get("source_key")
    if (key not in SOURCES
        or (source.get("feed_url"),source.get("kind"),source.get("platform_adapter")) != SOURCES[key]
        or source.get("timezone")!=ZONE):
        raise ValueError("unregistered_anchorage_batch20_tec_source")
    now=calendar_anchor(now or datetime.now(timezone.utc))
    deadline=min(monotonic()+38,deadline_at if deadline_at is not None else float("inf"))
    found={}
    page=1
    page_count=1
    while page<=page_count:
        if monotonic()>=deadline:
            raise ValueError("collection_deadline")
        url=SOURCES[key][0]+f"?per_page=50&page={page}"
        data=json.loads(fetch(url,"application/json"))
        if not isinstance(data,dict) or not isinstance(data.get("events"),list):
            raise ValueError("invalid_tec_events_response")
        total_pages=data.get("total_pages")
        if (isinstance(total_pages,bool) or not isinstance(total_pages,int)
                or not 1<=total_pages<=MAX_PAGES
                or (page>1 and total_pages!=page_count)):
            raise ValueError("tec_pagination_requires_review")
        page_count=total_pages
        if len(data["events"])>50:
            raise ValueError("tec_page_limit")
        for e in data["events"]:
            row=_event(key,e,now)
            if row is None:
                continue
            ident=row["id"],row["starts_at"]
            if ident in found and found[ident]!=row:
                raise ValueError("conflicting_tec_occurrence")
            found[ident]=row
        page+=1
    if len(found)>MAX_RECORDS:
        raise ValueError("source_record_limit")
    return sorted(found.values(),key=lambda r:(r["starts_at"],r["title"],r["id"]))
