"""Santa Cruz Public Libraries publisher's native iCalendar with full event details.

Each dated VEVENT is independently verified against its own Communico detail page.
Never extrapolate recurrence, use a fake location point, or publish an excerpt.
"""
from __future__ import annotations
from base64 import b64encode
from datetime import datetime, timedelta, timezone
import json
import math
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from icalendar import Calendar
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import plain, record
from roomquest.event_description import description

KEY = "santa_cruz_public_libraries_libnet_ca"
ZONE = "America/Los_Angeles"
HOST = "santacruzpl.libnet.info"
FILTERS = {"feedType":"ical","filters":{"location":["all"],"ages":["all"],
           "types":["all"],"tags":[],"term":"","days":1}}
URL = "https://" + HOST + "/feeds?data=" + b64encode(
    json.dumps(FILTERS, separators=(",", ":")).encode("utf-8")
).decode("ascii")
SOURCES = {KEY:(URL,"ical","ical")}
ALLOWED_HOSTS = {KEY:(HOST,)}
MAX_FEED = 500
MAX_DETAILS = 26
MAX_EVENTS = 20
WINDOW_DAYS = 10
MAX_DESCRIPTION = 12000

# Verified from the publisher's own santacruzpl.org/branches directory.
# These are addresses of actual named branches, not inferred event coordinates.
BRANCHES = {
 "Aptos":("Aptos Branch Library","7695 Soquel Drive, Aptos, CA 95003","Aptos"),
 "Boulder Creek":("Boulder Creek Branch Library","13390 West Park Avenue, Boulder Creek, CA 95006","Boulder Creek"),
 "Branciforte":("Branciforte Branch Library","230 Gault Street, Santa Cruz, CA 95062","Santa Cruz"),
 "Capitola":("Capitola Branch Library","2005 Wharf Road, Capitola, CA 95010","Capitola"),
 "Downtown":("Downtown Santa Cruz Branch Library","224 Church Street, Santa Cruz, CA 95060","Santa Cruz"),
 "Felton":("Felton Branch Library","6121 Gushee Street, Felton, CA 95018","Felton"),
 "Garfield Park":("Garfield Park Branch Library","705 Woodrow Avenue, Santa Cruz, CA 95060","Santa Cruz"),
 "La Selva Beach":("La Selva Beach Branch Library","316 Estrella Avenue, La Selva Beach, CA 95076","La Selva Beach"),
 "Live Oak":("Live Oak Branch Library","2380 Portola Drive, Santa Cruz, CA 95062","Santa Cruz"),
 "Scotts Valley":("Scotts Valley Branch Library","251 Kings Village Road, Scotts Valley, CA 95066","Scotts Valley"),
}
NONPUBLIC = re.compile(r"\b(?:cancelled|canceled|postponed|private event|members.only|virtual|online.only|zoom.only)\b",re.I)
OFFSITE = re.compile(r"\b(?:offsite|off-site|at another location|different location|off campus)\b",re.I)
STREET = re.compile(r"\b\d{1,6}\s+(?:[\w.#'-]+\s+){1,8}(?:street|st|avenue|ave|road|rd|drive|dr|way|boulevard|blvd)\b",re.I)
UID = re.compile(r"[1-9]\d{4,9}")


def event_url(value):
    if not isinstance(value,str) or len(value)>130:return False
    u=urlsplit(value)
    return (u.scheme=="https" and u.hostname==HOST and u.port in (None,443)
            and not u.username and not u.password and not u.query and not u.fragment
            and bool(re.fullmatch(r"/event/[1-9]\d{4,9}",u.path)))


def _geo(prop):
    # icalendar.prop.vGeo has typed latitude and longitude properties; it
    # is not iterable.  Ignore native (0, 0) placeholders and nonlocal points.
    try:
        lat,lon=float(prop.latitude),float(prop.longitude)
        if (math.isfinite(lat) and math.isfinite(lon)
                and 36.8<=lat<=37.4 and -122.5<=lon<=-121.5):
            return lat,lon
    except (TypeError,ValueError,OverflowError,AttributeError):
        pass
    return None,None


def _full_description(raw,title,start,end):
    soup=BeautifulSoup(raw,"html.parser")
    blocks=[plain(b.get_text(" ",strip=True))
            for b in soup.select("div.amh-block.amh-text div.amh-content")]
    # Match original title and local wall clocks, not merely a feed teaser.
    if not any(title in b and len(b)<270 for b in blocks):return None
    local_start=start.astimezone(ZoneInfo(ZONE)).strftime("%Y-%m-%d %H:%M:%S")
    local_end=end.astimezone(ZoneInfo(ZONE)).strftime("%Y-%m-%d %H:%M:%S")
    if not any(local_start in b and local_end in b and ZONE in b for b in blocks):
        return None
    for i,value in enumerate(blocks):
        if "AGE GROUP:" not in value or "EVENT TYPE:" not in value or i<1:continue
        narrative=blocks[i-1]
        # These repeated legal disclaimers aren't part of event narratives.
        narrative=narrative.split(
            "The views and opinions expressed by presenters in Santa Cruz Public Libraries programs",1
        )[0].strip()
        cats=value.split("EVENT TYPE:",1)[-1].strip(" |")
        if (len(narrative)<100 or len(narrative)>MAX_DESCRIPTION
                or NONPUBLIC.search(title) or NONPUBLIC.search(narrative)
                or OFFSITE.search(narrative)):return None
        prose=description(narrative,limit=MAX_DESCRIPTION)
        if not prose or len(prose)<100:return None
        return prose,[plain(x) for x in cats.split("|") if plain(x)][:12]
    return None


def collect(source,fetch,*,deadline_at=None,now=None):
    if (source.get("source_key")!=KEY
            or (source.get("feed_url"),source.get("kind"),source.get("platform_adapter"))!=SOURCES[KEY]
            or source.get("timezone")!=ZONE):
        raise ValueError("unregistered_santa_cruz_library")
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ics=fetch(URL,"text/calendar")
    if not isinstance(ics,str) or len(ics)>900_000 or "BEGIN:VCALENDAR" not in ics:
        raise ValueError("invalid_santa_cruz_library_feed")
    rows=[e for e in Calendar.from_ical(ics).walk("VEVENT")]
    if not rows or len(rows)>MAX_FEED:
        raise ValueError("santa_cruz_library_feed_empty_or_oversized")
    candidates=[]
    all_dates=[]
    for e in rows:
        try:
            uid=str(e.get("UID",""))
            start=e.decoded("DTSTART")
            end=e.decoded("DTEND")
            if (not UID.fullmatch(uid) or not isinstance(start,datetime)
                    or not isinstance(end,datetime) or start.tzinfo is None or end.tzinfo is None):
                continue
            start,end=start.astimezone(timezone.utc),end.astimezone(timezone.utc)
            all_dates.append(start)
            if not now-timedelta(hours=3)<=start<=now+timedelta(days=WINDOW_DAYS):continue
            if end<=start or end<=now or str(e.get("STATUS"))!="CONFIRMED":continue
            title=plain(str(e.get("SUMMARY","")))
            loc=plain(str(e.get("LOCATION","")))
            if not title or NONPUBLIC.search(title) or OFFSITE.search(loc):continue
            branch=next((b for b in BRANCHES if loc.startswith(b+" Branch -")),None)
            if not branch or NONPUBLIC.search(loc):continue
            url="https://"+HOST+"/event/"+uid
            if not event_url(url):continue
            candidates.append((start,uid,end,title,loc,branch,_geo(e.get("GEO")),url))
        except (TypeError,ValueError,KeyError,OverflowError):
            continue
    if len(rows)==MAX_FEED and (not all_dates or max(all_dates)<now+timedelta(days=WINDOW_DAYS)):
        raise ValueError("santa_cruz_library_feed_truncated")
    result={}
    for start,uid,end,title,loc,branch,coord,url in sorted(candidates)[:MAX_DETAILS]:
        if len(result)>=MAX_EVENTS:break
        if deadline_at is not None and monotonic()>=deadline_at:
            raise ValueError("santa_cruz_library_deadline")
        full=_full_description(fetch(url,"text/html"),title,start,end)
        if full is None:continue
        narrative,cats=full
        venue,street,city=BRANCHES[branch]
        # If a description specifies a different numbered street, hold it.
        if any(not re.search(re.escape(street.split(",")[0]),x,re.I)
               for x in STREET.findall(narrative)):
            continue
        row=record(title,start.isoformat(),end.isoformat(),venue,street,city,
                   url,uid,", ".join(cats),*coord,ZONE,retain_until_end=True)
        if row is None:continue
        row.update(description=narrative,timezone=ZONE,publisher_categories=cats,
                   location_provenance="official_scpl_branch_directory",details_evidence_url=url)
        from roomquest.publisher_evidence import attach
        row=attach(row,KEY,facts={"location":loc,"categories":", ".join(cats)})
        result[(uid,row["starts_at"])]=row
    return sorted(result.values(),key=lambda r:(r["starts_at"],r["id"]))
