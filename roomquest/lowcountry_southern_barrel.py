"""Guarded first-party Southern Barrel public trivia events, Bluffton, SC.

Official calendar and event detail pages are allowed for search indexing by
publisher robots (search=yes, ai-train=no, use=reference). Nothing is used for AI
training; no images are ingested. Coordinates are an exact-numbered-address
match from the public U.S. Census geocoder, not publisher-provided GEO.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from roomquest.event_description import description
from roomquest.mapsee_adapter import record, plain

KEY = "southern_barrel_bluffton_sc"
URL = "https://southernbarrel.com/music-events"
HOST = "southernbarrel.com"
ZONE = "America/New_York"
VENUE = "Southern Barrel Brewing Co."
STREET = "375 Buckwalter Place Blvd, Bluffton, SC 29910"
LAT, LNG = 32.271693851895, -80.918827729347  # Census Public_AR_Current exact 375 street match, 2026-11-19
SOURCE = (URL, "html", "html", ZONE)
ALLOWED_HOSTS = {KEY: (HOST,)}
MAX_ITEMS = 24
MAX_DESCRIPTION = 12000
PATH = re.compile(r"/event/wednesday-night-trivia-(20\d{2}-\d{2}-\d{2})/?", re.I)
DETAIL = re.compile(r'<h3\b[^>]*>(.*?)</h3>\s*<h1\b[^>]*>(.*?)</h1>(.*?)<script\b[^>]*type=["\']application/ld\+json["\']', re.I | re.S)
SCRIPT = re.compile(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
TIME = re.compile(r"\bfrom\s+(\d{1,2})\s*(am|pm)\s*[-–]\s*(\d{1,2})\s*(am|pm)\b", re.I)

def source_valid(source):
    return isinstance(source, dict) and source.get("source_key") == KEY and (
        source.get("feed_url"), source.get("kind"), source.get("platform_adapter"),
        source.get("timezone")) == SOURCE

def event_url(url):
    if not isinstance(url, str) or len(url)>2000:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme=="https" and p.hostname==HOST and p.port in (None,443)
                and not p.username and not p.password and not p.query and not p.fragment
                and PATH.fullmatch(p.path) is not None)
    except ValueError:
        return False

def _str(value):
    return plain(unescape(value)).strip()

def _links(markup):
    if not isinstance(markup, str) or len(markup)>650000:
        raise ValueError("southern_barrel_listing_size")
    matches = re.findall(r'<a\b[^>]*href=["\'](?:https://southernbarrel\.com/|/)?(event/wednesday-night-trivia-20\d{2}-\d{2}-\d{2})/?["\']', markup, re.I)
    links = []
    for path in matches:
        url = "https://" + HOST + "/" + path
        if event_url(url) and url not in links:
            links.append(url)
        if len(links) >= MAX_ITEMS:
            break
    if not links:
        raise ValueError("southern_barrel_no_publisher_links")
    return links

def _hour(number, ampm):
    hour=int(number)
    if not 1<=hour<=12:
        raise ValueError("southern_barrel_time_range")
    return (hour%12)+(12 if ampm.lower()=="pm" else 0)

def _parse(url, markup, now):
    if not event_url(url) or not isinstance(markup, str) or len(markup)>650000:
        return None
    slug_date = PATH.fullmatch(urlsplit(url).path).group(1)
    try:
        on_day = datetime.strptime(slug_date,"%Y-%m-%d").date()
    except ValueError:
        return None
    if on_day.weekday()!=2:  # Trivia specifically published each Wednesday
        return None
    m = DETAIL.search(markup)
    if not m or _str(m.group(2))!="Wednesday Night Trivia":
        return None
    label = _str(m.group(1))
    if not re.fullmatch(r"[A-Za-z]+ \d{1,2}(?:st|nd|rd|th), 20\d{2}",label):
        return None
    try:
        published = datetime.strptime(re.sub(r"(\d{1,2})(?:st|nd|rd|th)",r"\1",label), "%B %d, %Y").date()
    except ValueError:
        return None
    if published!=on_day:
        return None
    scripts = SCRIPT.findall(markup)
    events=[]
    for raw in scripts[:16]:
        try:
            item = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(item,dict) and item.get("@type")=="Event":
            events.append(item)
    if len(events)!=1:
        return None
    item=events[0]
    if (item.get("name")!="Wednesday Night Trivia"
        or item.get("startDate")!=slug_date
        or item.get("endDate")!=slug_date
        or item.get("eventStatus")!="https://schema.org/EventScheduled"
        or item.get("eventAttendanceMode")!="https://schema.org/OfflineEventAttendanceMode"):
        return None
    loc=item.get("location")
    address=loc.get("address") if isinstance(loc,dict) else None
    if not isinstance(address,dict) or (
        str(address.get("streetAddress","")).strip().rstrip(".")!="375 Buckwalter Place Blvd"
        or address.get("addressLocality")!="Bluffton"
        or address.get("addressRegion")!="SC"
        or str(address.get("postalCode"))!="29910"
        or address.get("addressCountry")!="US"):
        return None
    prose_blocks=re.findall(r"<p\b[^>]*>(.*?)</p>",m.group(3),re.I|re.S)
    prose = description("\n".join(prose_blocks),limit=MAX_DESCRIPTION+1)
    if len(prose)<85 or len(prose)>MAX_DESCRIPTION:
        return None
    times = TIME.search(prose)
    if not times:
        return None
    sh,eh=_hour(times.group(1),times.group(2)),_hour(times.group(3),times.group(4))
    if eh<=sh or eh-sh>8 or (sh,eh)!=(19,21):
        return None
    begins=datetime(on_day.year,on_day.month,on_day.day,sh,tzinfo=ZoneInfo(ZONE))
    ends=datetime(on_day.year,on_day.month,on_day.day,eh,tzinfo=ZoneInfo(ZONE))
    if not (now<begins.astimezone(timezone.utc)<now+timedelta(days=75)):
        return None
    row=record("Wednesday Night Trivia",int(begins.timestamp()*1000),int(ends.timestamp()*1000),
               VENUE,STREET,"Bluffton",url,slug_date,"hang_out",LAT,LNG,ZONE,
               publisher_geo=False,retain_until_end=True)
    if row is None:
        return None
    row.update(description=prose,category="hang_out",venue_name=VENUE,venue_address=STREET,
               venue_city="Bluffton",lat=LAT,lng=LNG,timezone=ZONE,
               location_provenance="census_exact_numbered_address_match_20261119",
               category_provenance="publisher_trivia_event",publisher_categories=["hang_out"])
    return row

def collect(source,fetch,*,deadline_at=None,now=None):
    if not source_valid(source):
        raise ValueError("unregistered_southern_barrel_source")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("southern_barrel_unaware_now")
    listing=fetch(URL,"text/html")
    if isinstance(listing,bytes):listing=listing.decode("utf-8","replace")
    result={}
    for url in _links(listing):
        raw=fetch(url,"text/html")
        if isinstance(raw,bytes):raw=raw.decode("utf-8","replace")
        row=_parse(url,raw,now)
        if row is not None:
            identity=(row["id"],row["starts_at"])
            if identity in result and result[identity]!=row:
                raise ValueError("southern_barrel_conflicting_event")
            result[identity]=row
    return sorted(result.values(),key=lambda x:(x["starts_at"],x["id"]))
