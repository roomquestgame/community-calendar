"""Public first-party Palmetto Bluff Conservancy activities with actual event venue evidence.

Uses the publisher's bounded The Events Calendar JSON endpoint, not an unbounded
crawl. Only events physically at the independently verified numbered Conservancy
Classroom address are admitted. Others are held rather than pinned to a centroid.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from roomquest.event_description import description
from roomquest.mapsee_adapter import record, plain

KEY = "palmetto_bluff_conservancy_sc"
URL = "https://www.palmettobluff.com/events/"
API = "https://www.palmettobluff.com/wp-json/tribe/events/v1/events"
HOST = "www.palmettobluff.com"
ZONE = "America/New_York"
VENUE = "Conservancy Classroom"
STREET = "655 Old Moreland Road, Bluffton, SC 29910"
# Independent exact-address U.S. Census Public_AR_Current, 2026-11-19.
LAT, LNG = 32.178086450464, -80.897273890865
SOURCE = (URL, "html", "html", ZONE)
ALLOWED_HOSTS = {KEY: (HOST,)}
MAX_BYTES = 1_000_000
MAX_ITEMS = 50
MAX_DESCRIPTION = 12000
DAYS = 65
EVENT_PATH = re.compile(r"/event/[a-z0-9][a-z0-9-]{2,110}/?", re.I)
PRIVATE = re.compile(r"\b(residents? only|members? only|private event|closed to the public|owner-exclusive|restricted to residents?)\b", re.I)
CANCEL = re.compile(r"\b(cancelled|canceled|postponed)\b", re.I)

def source_valid(s):
    return isinstance(s,dict) and s.get("source_key")==KEY and (
        s.get("feed_url"),s.get("kind"),s.get("platform_adapter"),s.get("timezone"))==SOURCE

def event_url(u):
    if not isinstance(u,str) or len(u)>350:
        return False
    try:
        p=urlsplit(u)
        return (p.scheme=="https" and p.hostname==HOST and p.port in (None,443)
                and not p.username and not p.password and not p.query and not p.fragment
                and EVENT_PATH.fullmatch(p.path) is not None)
    except ValueError:
        return False

def category(title, terms):
    t=title.lower()
    if "pop-up shop" in t or "pop up shop" in t:
        return "festival"
    if "nature outings" in terms or "outings" in terms or "track and sign" in t:
        return "gardens_nature"
    if "talks" in terms or "lecture" in t or "brown bag lunch" in t:
        return "learn"
    if "workshops" in terms or "workshop" in t:
        return "learn"
    return None

def collect(source,fetch,*,deadline_at=None,now=None):
    if not source_valid(source):
        raise ValueError("unregistered_palmetto_bluff_conservancy")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("unaware_now")
    today=now.astimezone(ZoneInfo(ZONE)).date()
    params=urlencode({"start_date":today.isoformat(),
                      "end_date":(today+timedelta(days=DAYS)).isoformat(),
                      "per_page":MAX_ITEMS})
    body=fetch(API+"?"+params,"application/json")
    if isinstance(body,bytes):
        body=body.decode("utf-8","replace")
    if not isinstance(body,str) or len(body.encode("utf-8"))>MAX_BYTES:
        raise ValueError("palmetto_bluff_json_size")
    try:
        obj=json.loads(body)
    except (ValueError,TypeError) as exc:
        raise ValueError("palmetto_bluff_json_invalid") from exc
    if (not isinstance(obj,dict) or not isinstance(obj.get("events"),list)
            or not isinstance(obj.get("total_pages"),int)
            or obj["total_pages"]>1 or len(obj["events"])>MAX_ITEMS):
        raise ValueError("palmetto_bluff_pagination_overflow")
    out={}
    for e in obj["events"]:
        if not isinstance(e,dict) or e.get("status")!="publish":
            continue
        u=e.get("url")
        v=e.get("venue")
        if not event_url(u) or not isinstance(v,dict):
            continue
        if (plain(v.get("venue"))!=VENUE or plain(v.get("address"))!="655 Old Moreland Road"
            or plain(v.get("city"))!="Bluffton" or v.get("state")!="SC"
            or str(v.get("zip"))!="29910"):
            continue
        cats=e.get("categories",[])
        if not isinstance(cats,list) or not any(
                isinstance(c,dict) and c.get("slug")=="conservancy" for c in cats):
            continue
        title=plain(e.get("title",""))
        terms={str(c.get("slug","")).lower() for c in cats if isinstance(c,dict)}
        cat=category(title,terms)
        if not cat or CANCEL.search(title):
            continue
        narrative=description(e.get("description",""),limit=MAX_DESCRIPTION+1)
        if not 65<=len(narrative)<=MAX_DESCRIPTION or PRIVATE.search(narrative):
            continue
        try:
            start=datetime.fromisoformat(e["start_date"])
            end=datetime.fromisoformat(e["end_date"])
            event_id=int(e["id"])
        except (ValueError,KeyError,TypeError,OverflowError):
            continue
        if start.tzinfo is not None or end.tzinfo is not None or event_id<1:
            continue
        start=start.replace(tzinfo=ZoneInfo(ZONE))
        end=end.replace(tzinfo=ZoneInfo(ZONE))
        if not (now<start.astimezone(timezone.utc)<now+timedelta(days=DAYS)):
            continue
        if end<=start or end-start>timedelta(days=1):
            continue
        identity=f"palmetto-bluff-{event_id}:{start.date().isoformat()}"
        row=record(title,int(start.timestamp()*1000),int(end.timestamp()*1000),
                   VENUE,STREET,"Bluffton",u,identity,cat,LAT,LNG,ZONE)
        if row is None:
            continue
        row.update(description=narrative,category=cat,venue_name=VENUE,
                   venue_address=STREET,venue_city="Bluffton",
                   lat=LAT,lng=LNG,timezone=ZONE,
                   location_provenance="census_exact_numbered_address_match_20261119",
                   category_provenance="publisher_event_category_and_title",
                   publisher_categories=sorted(terms),end_time_verified=True)
        if identity in out and out[identity]!=row:
            raise ValueError("palmetto_bluff_conflicting_occurrence")
        out[identity]=row
    return sorted(out.values(),key=lambda x:(x["starts_at"],x["id"]))
