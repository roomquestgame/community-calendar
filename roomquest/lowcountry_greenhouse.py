"""First-party Greenhouse Bluffton events: HTML listing, per-event JSON-LD and native ICS.

Source https://www.greenhousebluffton.com/events is permitted by robots; the
Squarespace ?format=json endpoint is explicitly DISALLOWED and is not used.
Only numbered event street plus agreeing native ICS GEO and publisher OG GEO
are accepted. Publisher image rights are unreviewed, so no images are emitted.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from html import unescape
import json
import logging
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest.event_description import description
from roomquest.mapsee_adapter import record, plain

KEY = "greenhouse_bluffton_sc"
URL = "https://www.greenhousebluffton.com/events"
HOST = "www.greenhousebluffton.com"
ZONE = "America/New_York"
VENUE = "Greenhouse Restaurant Bluffton"
STREET = "1260 May River Road, Bluffton, SC 29910"
LAT, LNG = 32.236839, -80.866556
SOURCE = (URL, "html", "html", ZONE)
ALLOWED_HOSTS = {KEY: (HOST,)}
MAX_DESCRIPTION = 12000
MAX_ITEMS = 20
LOGGER = logging.getLogger(__name__)
PATH = re.compile(r"/events/[a-z0-9][a-z0-9-]{2,100}/?", re.I)
ICS_ITEM = re.compile(r"^[a-z0-9]{12,60}@squarespace[.]com$", re.I)
CATEGORY = ((re.compile(r"\bkaraoke|live music|concert|open mic\b",re.I),"music"),
            (re.compile(r"\b(?:music )?bingo|trivia|game night\b",re.I),"hang_out"),
            (re.compile(r"\bfundraiser|charity\b",re.I),"give_back"),
            (re.compile(r"\bholiday party|new year party\b",re.I),"party"))


def source_valid(source):
    return isinstance(source,dict) and source.get("source_key")==KEY and (
        source.get("feed_url"),source.get("kind"),
        source.get("platform_adapter"),source.get("timezone")) == SOURCE


def event_url(url):
    if not isinstance(url,str) or len(url)>2000:
        return False
    try:
        p=urlsplit(url)
        return (p.scheme=="https" and p.hostname==HOST and p.port in (None,443)
                and not p.username and not p.password and not p.query and not p.fragment
                and PATH.fullmatch(p.path) is not None)
    except ValueError:
        return False


def _listing_links(html):
    # Only same-origin published listing links, not script JSON or search URLs.
    if not isinstance(html,str) or len(html)>650000:
        raise ValueError("publisher_listing_size")
    found=[]
    for match in re.finditer(r'<a\b[^>]*href="(/events/[a-z0-9-]+)"[^>]*>',html,re.I):
        path=match.group(1)
        u="https://"+HOST+path
        if event_url(u) and u not in found:
            found.append(u)
        if len(found)>=MAX_ITEMS:
            break
    return found


def _og(html,prop):
    m=re.search(r'<meta\s+property="og:'+re.escape(prop)+r'"\s+content="([^"]+)"\s*/?>',html,re.I)
    return unescape(m.group(1)).strip() if m else None


def _event_ld(html):
    for m in re.finditer(r'<script\b[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',html,re.I|re.S):
        try:
            payload=json.loads(m.group(1))
        except (ValueError,TypeError):
            continue
        for row in (payload if isinstance(payload,list) else [payload]):
            if isinstance(row,dict) and row.get("@type")=="Event":
                return row
    return None


def _narrative(html):
    # Only the event article's publisher-written prose blocks, not navigation,
    # scripts, site footer, SEO metadata or stock images.
    start=re.search(r'<article\b[^>]*class="eventitem(?:\s|")',html,re.I)
    if start is None:
        return ""
    article=html[start.start():].split("</article>",1)[0]
    blocks=re.findall(r'<div\s+class="sqs-html-content"[^>]*>(.*?)</div>',article,re.I|re.S)
    texts=[description(block,limit=MAX_DESCRIPTION+1) for block in blocks]
    prose="\n".join(t for t in texts if t)
    return prose if 80<=len(prose)<=MAX_DESCRIPTION else ""


def _category(title):
    for regex,cat in CATEGORY:
        if regex.search(title):
            return cat
    return None


def _dates_consistent(prose,start,end):
    # Reject publisher pages whose text still says a different calendar date,
    # e.g. music bingo's Nov 23 prose vs Nov 25 structured DTSTART.
    months={"nov":11,"dec":12,"jan":1,"feb":2,"mar":3,"apr":4,
            "may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10}
    allowed={(start.month,start.day),(end.month,end.day)}
    for m in re.finditer(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
                         r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
                         r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})\b",prose,re.I):
        if (months[m.group(1)[:3].lower()],int(m.group(2))) not in allowed:
            return False
    return True


def collect(source,fetch,*,deadline_at=None,now=None):
    if not source_valid(source):
        raise ValueError("unregistered_greenhouse_source")
    from icalendar import Calendar
    listing=fetch(URL,"text/html")
    if isinstance(listing,bytes):
        listing=listing.decode("utf-8","replace")
    links=_listing_links(listing)
    if not links:
        raise ValueError("publisher_event_links_missing")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("unaware_now")
    out={}
    for url in links:
        html=fetch(url,"text/html")
        if isinstance(html,bytes):
            html=html.decode("utf-8","replace")
        if not isinstance(html,str) or len(html)>650000:
            raise ValueError("publisher_detail_size")
        obj=_event_ld(html)
        if not obj:
            continue
        try:
            begins=datetime.fromisoformat(obj["startDate"])
            ends=datetime.fromisoformat(obj["endDate"])
        except (KeyError,ValueError,TypeError):
            LOGGER.info("greenhouse_hold url=%s reason=date_missing",url)
            continue
        if begins.tzinfo is None or ends.tzinfo is None or ends<=begins:
            continue
        if not (now<begins.astimezone(timezone.utc)<now+timedelta(days=60)):
            continue
        if (begins.astimezone(ZoneInfo(ZONE)).utcoffset()!=begins.utcoffset()
                or ends.astimezone(ZoneInfo(ZONE)).utcoffset()!=ends.utcoffset()):
            continue
        place=obj.get("location") or {}
        if (not isinstance(place,dict) or plain(place.get("name"))!=VENUE or
                "1260 May River Road" not in str(place.get("address")) or
                "Bluffton" not in str(place.get("address")) or
                "29910" not in str(place.get("address")) or
                _og(html,"street-address")!="1260 May River Road" or
                _og(html,"locality")!="Bluffton" or
                _og(html,"postal-code")!="29910" or
                _og(html,"region")!="South Carolina"):
            LOGGER.info("greenhouse_hold url=%s reason=event_street_unverified",url)
            continue
        try:
            lat=float(_og(html,"latitude"))
            lng=float(_og(html,"longitude"))
        except (ValueError,TypeError):
            continue
        if not (math.isfinite(lat) and math.isfinite(lng) and
                abs(lat-LAT)<0.00005 and abs(lng-LNG)<0.00005):
            continue
        title=plain(re.search(r'<h1\b[^>]*class="eventitem-title"[^>]*>(.*?)</h1>',html,re.I|re.S).group(1)) if re.search(r'<h1\b[^>]*class="eventitem-title"[^>]*>(.*?)</h1>',html,re.I|re.S) else ""
        cat=_category(title)
        prose=_narrative(html)
        if not cat or not prose or not _dates_consistent(prose,begins,ends):
            LOGGER.info("greenhouse_hold url=%s reason=category_description_or_date_conflict",url)
            continue
        # Robots allows ?format=ical, unlike ?format=json. Native publisher
        # VEVENT corroborates time, UID, venue and GPS before any pin is used.
        ics=fetch(url+"?format=ical","text/calendar")
        cal=Calendar.from_ical(ics)
        events=cal.walk("VEVENT")
        if len(events)!=1:
            continue
        evt=events[0]
        uid=str(evt.get("UID") or "")
        if not ICS_ITEM.fullmatch(uid):
            continue
        i_start=evt.get("DTSTART")
        i_end=evt.get("DTEND")
        geo=evt.get("GEO")
        if i_start is None or i_end is None or geo is None:
            continue
        try:
            i_lat,i_lng=[float(x) for x in geo.to_ical().decode().split(";")]
        except (ValueError,TypeError,AttributeError):
            continue
        if (i_start.dt.astimezone(timezone.utc)!=begins.astimezone(timezone.utc)
                or i_end.dt.astimezone(timezone.utc)!=ends.astimezone(timezone.utc)
                or abs(i_lat-lat)>0.00005 or abs(i_lng-lng)>0.00005
                or "1260 May River Road" not in str(evt.get("LOCATION"))):
            continue
        identity=uid+":"+begins.astimezone(timezone.utc).isoformat()
        row=record(title,int(begins.timestamp()*1000),int(ends.timestamp()*1000),
                   VENUE,STREET,"Bluffton",url,identity,cat,lat,lng,ZONE,
                   publisher_geo=True,retain_until_end=True)
        if row is None:
            continue
        row.update(description=prose,category=cat,lat=lat,lng=lng,
                   venue_name=VENUE,venue_address=STREET,venue_city="Bluffton",
                   timezone=ZONE,location_provenance="publisher_ical_geo_and_event_og",
                   category_provenance="publisher_event_title",publisher_categories=[cat])
        key=(row["id"],row["starts_at"])
        if key in out and out[key]!=row:
            raise ValueError("conflicting_publisher_event")
        out[key]=row
    return sorted(out.values(),key=lambda r:(r["starts_at"],r["id"]))
