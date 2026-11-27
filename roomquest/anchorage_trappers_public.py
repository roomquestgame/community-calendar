"""Strict first-party Eagle River wilderness education workshops; no inferred occurrences.

Location: Alaska Trappers Association original venue VFW Post 9785,
10527 VFW Road, Eagle River AK 99577; Census Public_AR_Current 2026-11-19
street-interpolated match (NOT rooftop GPS).
"""
from datetime import datetime, timedelta, timezone
from html import unescape
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
import re
from bs4 import BeautifulSoup
from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import record, plain

KEY = "alaska_trappers_eagle_river_workshops_ak"
ROOT = "https://www.alaskatrappers.org"
FEED = ROOT + "/wp-json/tribe/events/v1/events"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.alaskatrappers.org",)}
ZONE = "America/Anchorage"
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
POINT = (61.314540270427, -149.573896438591)
VENUE = ("VFW Post 9785", "10527 VFW Road, Eagle River, AK 99577", "Eagle River")
GEO_EVIDENCE = ("Verified original VFW Post 9785 and Census Public_AR_Current exact "
                "10527 VFW RD EAGLE RIVER AK 99577, 2026-11-19; street interpolation, not rooftop GPS")
# Original publisher TEC event identities individually checked. No guessed repeats.
EVENTS = {
  1377315: ("Snow Machine Winter Survival Workshop – Eagle River",
            "/event/snow-machine-winter-survival-workshop-eagle-river/"),
  1377319: ("Snow Machine Winter Survival Workshop-FREE – Eagle River",
            "/event/snow-machine-winter-survival-workshop-free-eagle-river/"),
  1377321: ("Predator Hunting/ Calling/ Night Vision/ Thermals Workshop – Eagle River",
            "/event/predator-hunting-calling-night-vision-thermals-workshop-eagle-river/"),
}

def event_url(source_key, value):
    if source_key != KEY or not isinstance(value, str) or len(value)>1300:
        return False
    try:
        p=urlsplit(value)
        return (p.scheme=="https" and p.hostname=="www.alaskatrappers.org"
                and p.port in (None,443) and not p.username and not p.password
                and not p.query and not p.fragment
                and p.path in {path for _,path in EVENTS.values()})
    except ValueError:
        return False

def photo_url(source_key, value):
    return None # Only original publisher candidate; image rights not cleared.

def _time(raw):
    if not isinstance(raw,str): raise ValueError("trappers_missing_date")
    try: return datetime.strptime(raw,"%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(ZONE))
    except ValueError as exc: raise ValueError("trappers_invalid_date") from exc

def _one(item, fetch, now, deadline):
    if not isinstance(item,dict) or type(item.get("id")) is not int:
        raise ValueError("trappers_invalid_event")
    ident=item["id"]
    if ident not in EVENTS: return None
    expected,path=EVENTS[ident]
    title=plain(unescape(item.get("title") or ""))
    link=ROOT+path
    if title!=expected or item.get("timezone")!=ZONE or item.get("url")!=link or not event_url(KEY,link):
        raise ValueError("trappers_identity_mismatch")
    venue=item.get("venue")
    if (not isinstance(venue,dict) or venue.get("venue")!=VENUE[0]
        or venue.get("address")!="10527 VFW Road" or venue.get("city")!="Eagle River"
        or venue.get("state") not in ("AK","Alaska") or str(venue.get("zip"))!="99577"):
        raise ValueError("trappers_venue_unverified")
    start,end=_time(item.get("start_date")),_time(item.get("end_date"))
    if not start<end<=start+timedelta(hours=8):
        raise ValueError("trappers_duration_invalid")
    for field,local in (("utc_start_date",start),("utc_end_date",end)):
        stated=datetime.strptime(item[field],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if stated!=local.astimezone(timezone.utc):
            raise ValueError("trappers_utc_mismatch")
    if end.astimezone(timezone.utc)<=now or start.astimezone(timezone.utc)>now+timedelta(days=WINDOW_DAYS):
        return None
    raw=item.get("description")
    if not isinstance(raw,str) or len(raw)>200000:
        raise ValueError("trappers_description_invalid")
    description=plain(BeautifulSoup(raw,"html.parser").get_text(" ",strip=True))
    if (not description or len(description)>MAX_DESCRIPTION or
        re.search(r"\b(private event|members only|cancelled|canceled|postponed)\b",title+" "+description,re.I)):
        return None
    if monotonic()>=deadline: raise ValueError("collection_deadline")
    page=fetch(link,"text/html")
    if not isinstance(page,str) or not page or len(page)>500000:
        raise ValueError("trappers_detail_unreadable")
    soup=BeautifulSoup(page,"html.parser")
    heading=soup.select_one("h1.tribe-events-single-event-title") or soup.find("h1")
    if not heading or plain(heading.get_text(" ",strip=True))!=title:
        raise ValueError("trappers_detail_identity_mismatch")
    row=record(title,start.isoformat(),end.isoformat(),VENUE[0],VENUE[1],VENUE[2],
               link,"alaska_trappers:"+str(ident),"learn",lat=POINT[0],lng=POINT[1],
               tz=ZONE,retain_until_end=True)
    if row is None: return None
    row.update(description=description,category="learn",timezone=ZONE,
               lat=POINT[0],lng=POINT[1],location_provenance=GEO_EVIDENCE,
               publisher_categories=["Wilderness education","Classes"],image_rights="unreviewed")
    row.pop("image_url",None)
    return row

def collect(source,fetch,*,deadline_at=None,now=None):
    if (source.get("source_key")!=KEY or source.get("timezone")!=ZONE or
        (source.get("feed_url"),source.get("kind"),source.get("platform_adapter"))!=SOURCES[KEY]):
        raise ValueError("trappers_source_mismatch")
    now=calendar_anchor(now or datetime.now(timezone.utc))
    deadline=min(monotonic()+38,deadline_at if deadline_at is not None else float("inf"))
    api=(FEED+"?start_date="+now.astimezone(ZoneInfo(ZONE)).date().isoformat()+
         "&end_date="+(now+timedelta(days=WINDOW_DAYS)).astimezone(ZoneInfo(ZONE)).date().isoformat()+
         "&per_page=50")
    payload=fetch(api,"application/json")
    if not isinstance(payload,str) or not payload or len(payload)>500000:
        raise ValueError("trappers_api_unreadable")
    parsed=json.loads(payload)
    if (not isinstance(parsed,dict) or not isinstance(parsed.get("events"),list)
        or parsed.get("total_pages")!=1 or len(parsed["events"])>50):
        raise ValueError("trappers_api_invalid")
    rows={}
    for item in parsed["events"]:
        row=_one(item,fetch,now,deadline)
        if row is not None:
            key=(row["id"],row["starts_at"])
            if key in rows and rows[key]!=row: raise ValueError("trappers_identity_conflict")
            rows[key]=row
    return sorted(rows.values(),key=lambda row:(row["starts_at"],row["id"]))
