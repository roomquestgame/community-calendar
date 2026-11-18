"""Anchorage batch20 — official Wasilla Public Library CivicPlus events.

Only source-specific public library calendar EIDs. Each event is separately
confirmed on the city's own details page for actual title, AK date/time,
publisher description and the exact physical library street. City calendar
featured events, other venues, closures and unknown categories are excluded.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo
import logging
import re

from bs4 import BeautifulSoup

from roomquest.anchorage_sources import _description, ZONE
from roomquest.mapsee_adapter import plain, record

KEY = "wasilla_public_library_events_ak"
ROOT = "https://www.cityofwasilla.gov"
FEED = ROOT + "/Calendar.aspx?CID=23"
SOURCES = {KEY: (FEED, "html", "html")}
ALLOWED_HOSTS = {KEY: ("www.cityofwasilla.gov",)}
VENUE = ("Wasilla Public Library", "500 N. Crusey St., Wasilla, AK 99654", "Wasilla")
MONTHS = 3
MAX_EIDS = 110
MAX_DESCRIPTION = 12000
WINDOW_DAYS = 60
log = logging.getLogger(__name__)
EID_LINK = re.compile(r"/Calendar[.]aspx[?]EID=([0-9]{3,7})$", re.I)
PAGE_EID = re.compile(r"(?:^|/)[Cc]alendar[.]aspx$", re.I)
BAD = re.compile(r"\b(?:private event|staff only|cancelled|canceled|closed|postponed)\b",re.I)


def _hold(eid, reason):
    log.warning("wasilla_library_held eid=%s reason=%s", eid, reason)


def event_url(source_key, url):
    if source_key != KEY or not isinstance(url, str) or len(url) > 800:
        return False
    try:
        p = urlsplit(url)
        q = parse_qs(p.query)
        return (p.scheme == "https" and p.hostname == "www.cityofwasilla.gov"
                and not p.username and not p.password and p.port in (None, 443)
                and PAGE_EID.search(p.path) is not None
                and not p.fragment and len(q)==1 and len(q.get("EID",[]))==1
                and re.fullmatch(r"[0-9]{3,7}",q["EID"][0]) is not None)
    except ValueError:
        return False


def photo_url(source_key, url):
    return None


def _category(title):
    t = title.casefold()
    if re.search(r"storytime|literacy|book club|history discussion|author visit|afternoon all-stars|learn|science|lecture|reading",t):
        return "learn"
    if re.search(r"craft circle|craft|sewing|art class|paint|maker|knit",t):
        return "create"
    if re.search(r"concert|music in the library|performance",t):
        return "music"
    if re.search(r"fiber spinn|game club|community play|play lab",t):
        return "hang_out"
    return None


def _selected_calendar_months(now):
    local = now.astimezone(ZoneInfo(ZONE))
    for step in range(MONTHS):
        m = local.month-1+step
        yield local.year+m//12, m%12+1


def _ids(page):
    if not isinstance(page,str) or len(page)>500_000:
        raise ValueError("invalid_wasilla_calendar_page")
    soup = BeautifulSoup(page,"html.parser")
    ids = set()
    for a in soup.find_all("a",href=True):
        # Official CivicPlus detail links use an EID plus month/year/other
        # navigation context. We resolve ONLY the numeric EID from that path,
        # never an arbitrary href or third-party redirect.
        p = urlsplit(urljoin(ROOT,a["href"]))
        if p.scheme!="https" or p.hostname!="www.cityofwasilla.gov" or not PAGE_EID.search(p.path):
            continue
        matches = parse_qs(p.query)
        if len(matches.get("EID",[]))!=1:
            continue
        event_id=matches["EID"][0]
        if re.fullmatch(r"[0-9]{3,7}",event_id):
            ids.add(event_id)
    return ids


def _text(soup,selector):
    node=soup.select_one(selector)
    return node.get_text(" ",strip=True) if node else ""


def _event(eid, html, now):
    if not isinstance(html,str) or len(html)>500_000:
        raise ValueError("invalid_wasilla_event_page")
    soup=BeautifulSoup(html,"html.parser")
    start_raw=_text(soup, '[itemprop="startDate"]')
    title=plain(_text(soup,'.detailTitle [itemprop="name"]'))
    description_element=soup.select_one('[itemprop="description"]')
    name=plain(_text(soup,'[itemprop="location"] [itemprop="name"]'))
    street=plain(_text(soup,'[itemprop="streetAddress"]'))
    city=plain(_text(soup,'[itemprop="addressLocality"]'))
    state=plain(_text(soup,'[itemprop="addressRegion"]'))
    zipcode=plain(_text(soup,'[itemprop="postalCode"]'))
    if (not title or BAD.search(title)
            or name!="Wasilla Public Library"
            or street.casefold()!="500 n. crusey st."
            or city!="Wasilla" or state!="AK" or zipcode!="99654"):
        _hold(eid,"venue_or_title_unverified")
        return None
    category=_category(title)
    if category is None:
        _hold(eid,"category_review_required")
        return None
    text_time=None
    for block in soup.select("div.specificDetail"):
        contents=block.get_text(" ",strip=True).replace("\u2009"," ")
        if contents.startswith("Time:"):
            text_time=contents
            break
    if text_time is None:
        _hold(eid,"event_time_missing")
        return None
    times=re.search(r"Time:\s*(\d{1,2}:\d{2}\s*[AP]M)\s*[-\u2013]\s*(\d{1,2}:\d{2}\s*[AP]M)",text_time,re.I)
    if times is None:
        _hold(eid,"event_time_unverified")
        return None
    try:
        start=datetime.fromisoformat(start_raw).replace(tzinfo=ZoneInfo(ZONE))
        t_end=datetime.strptime(times.group(2).upper().replace(" ",""),"%I:%M%p").time()
        end=datetime.combine(start.date(),t_end,tzinfo=ZoneInfo(ZONE))
        if start.strftime("%I:%M%p").lstrip("0") != times.group(1).upper().replace(" ","").lstrip("0"):
            _hold(eid,"calendar_start_conflicts_with_time")
            return None
    except ValueError:
        return None
    if (end<=start or end-start>timedelta(hours=12) or
            end.astimezone(timezone.utc)<=now or
            start.astimezone(timezone.utc)>now+timedelta(days=WINDOW_DAYS)):
        return None
    desc=_description(str(description_element)) if description_element is not None else None
    if desc is None or len(desc)>MAX_DESCRIPTION:
        _hold(eid,"full_event_description_missing_or_oversized")
        return None
    url=ROOT+"/Calendar.aspx?EID="+eid
    if not event_url(KEY,url):
        raise ValueError("invalid_wasilla_event_identity")
    row=record(title,start.astimezone(timezone.utc).isoformat(),
               end.astimezone(timezone.utc).isoformat(),
               *VENUE,url,eid,category,tz=ZONE,retain_until_end=True)
    if row is None:
        return None
    row.update(description=desc,category=category,timezone=ZONE,
               publisher_categories=["Wasilla Public Library"],
               location_provenance="verified_city_published_event_street",
               lat=None,lng=None,reason="missing_verified_venue_geo")
    return row


def collect(source,fetch,*,deadline_at=None,now=None):
    if (source.get("source_key")!=KEY
            or (source.get("feed_url"),source.get("kind"),source.get("platform_adapter"))!=SOURCES[KEY]
            or source.get("timezone")!=ZONE):
        raise ValueError("unregistered_wasilla_library_source")
    now=now or datetime.now(timezone.utc)
    deadline=min(monotonic()+38,deadline_at if deadline_at is not None else float("inf"))
    ids=set()
    for year,month in _selected_calendar_months(now):
        if monotonic()>=deadline:
            raise ValueError("collection_deadline")
        url=ROOT+f"/Calendar.aspx?CID=23&month={month}&year={year}"
        ids.update(_ids(fetch(url,"text/html")))
        if len(ids)>MAX_EIDS:
            raise ValueError("wasilla_source_record_limit")
    # CivicPlus event detail pages carry complete descriptions that the month
    # view's truncated microdata does not. Use three modest concurrent requests
    # (rather than ~35 serial network round trips) within V2 worker deadline.
    # This is only a fetch fan-out; no background pagination or missing-record
    # acceptance. Any failed request invalidates the complete snapshot.
    results={}
    def load(eid):
        if monotonic()>=deadline:
            raise ValueError("collection_deadline")
        return _event(eid,fetch(ROOT+"/Calendar.aspx?EID="+eid,"text/html"),now)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(load,sorted(ids,key=int)):
            if row:
                key=(row["id"],row["starts_at"])
                if key in results and results[key]!=row:
                    raise ValueError("conflicting_wasilla_event_occurrence")
                results[key]=row
    if monotonic()>=deadline:
        raise ValueError("collection_deadline")
    return sorted(results.values(),key=lambda x:(x["starts_at"],x["id"]))
