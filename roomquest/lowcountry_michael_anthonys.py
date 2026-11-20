"""Robots-permitted HTML-only, bounded first-party Michael Anthony cooking calendar."""
from datetime import datetime,timedelta,timezone
from time import monotonic
from urllib.parse import urljoin,urlsplit
from zoneinfo import ZoneInfo
import re
from lxml import html
from lxml.html import tostring
from roomquest.mapsee_adapter import plain,record
from roomquest.event_description import description

KEY="michael_anthonys_cooking_school_hhi_sc"
HOST="www.michael-anthonys.com"
FEED=f"https://{HOST}/cooking-school"
ZONE="America/New_York"
SOURCE=(FEED,"html","html",ZONE)
ALLOWED_HOSTS={KEY:(HOST,)}
VENUE="Michael Anthony's Cucina Italiana"
ADDRESS="37 New Orleans Road, Hilton Head Island, SC 29928"
CITY="Hilton Head Island"
LAT,LNG=32.156240644051,-80.757117879495
MAX_DETAILS=12
MAX_INDEX_BYTES=850000
MAX_DETAIL_BYTES=550000
MAX_DESCRIPTION=12000
WINDOW=timedelta(days=62)
PATTERN=re.compile(r"/cooking-school/[a-z0-9-]{8,110}/?")
PRIVATE=re.compile(r"\b(cancelled|canceled|postponed|private event|members only|residents only)\b",re.I)
CLS="contains(concat(' ', normalize-space(@class), ' '), $c)"
def nodes(n,k,tag="*"):return n.xpath(f".//{tag}[{CLS}]",c=f" {k} ")
def source_valid(s):return isinstance(s,dict) and s.get("source_key")==KEY and tuple(s.get(k) for k in ("feed_url","kind","platform_adapter","timezone"))==SOURCE
def event_url(u):
    if not isinstance(u,str) or len(u)>350:return False
    try:
        p=urlsplit(u)
        return p.scheme=="https" and p.hostname==HOST and p.port in (None,443) and not p.username and not p.password and not p.query and not p.fragment and bool(PATTERN.fullmatch(p.path))
    except ValueError:return False
def page(fetch,u,maxsize):
    b=fetch(u,"text/html")
    if isinstance(b,bytes):b=b.decode("utf-8","replace")
    if not isinstance(b,str) or not b or len(b.encode())>maxsize:raise ValueError("michael_html_bounds")
    return html.fromstring(b)
def dtime(n,k):
    v=nodes(n,k,"time")
    if len(v)!=1:return None
    val=plain(v[0].text_content()).replace("\u202f"," ").replace("\xa0"," ")
    m=re.fullmatch(r"(\d{1,2}):(\d{2})\s*([AP]M)",val,re.I)
    if not m:return None
    return (int(m[1])%12+(12 if m[3].upper()=="PM" else 0),int(m[2]))
def day(n):
    v=nodes(n,"event-date","time")
    if len(v)!=1:return None
    try:return datetime.strptime(v[0].get("datetime",""),"%Y-%m-%d").date()
    except (TypeError,ValueError):return None
def parse_detail(u,title,dayval,st,en,document,now):
    art=nodes(document,"eventitem","article")
    if len(art)!=1:return None
    a=art[0]; heads=nodes(a,"eventitem-title","h1")
    if len(heads)!=1 or plain(heads[0].text_content())!=title or PRIVATE.search(title):return None
    if day(a)!=dayval or dtime(a,"event-time-localized-start")!=st or dtime(a,"event-time-localized-end")!=en:return None
    addresses=[plain(n.text_content()) for n in nodes(a,"eventitem-meta-address-line","span")]
    if len(addresses)<3 or addresses[0]!=VENUE or not re.fullmatch(r"37 New Orleans (?:Road|Rd\.?)",addresses[1],re.I) or not re.fullmatch(r"Hilton Head Island,\s*SC,?\s*29928",addresses[2],re.I):return None
    bodies=nodes(a,"sqs-layout","div")
    if not bodies:return None
    narrative=description(tostring(bodies[0],encoding="unicode"),limit=MAX_DESCRIPTION+1)
    if not 100<=len(narrative)<=MAX_DESCRIPTION or PRIVATE.search(narrative[:120]):return None
    eid=a.get("data-item-id","")
    if not re.fullmatch(r"[a-f0-9]{24}",eid):return None
    zone=ZoneInfo(ZONE)
    start=datetime.combine(dayval,datetime.min.time(),zone).replace(hour=st[0],minute=st[1])
    end=datetime.combine(dayval,datetime.min.time(),zone).replace(hour=en[0],minute=en[1])
    if not now<start.astimezone(timezone.utc)<now+WINDOW or not start<end<=start+timedelta(hours=7):return None
    r=record(title,start.isoformat(),end.isoformat(),VENUE,ADDRESS,CITY,u,"michael_anthonys:"+eid+":"+dayval.isoformat(),"learn",lat=LAT,lng=LNG,tz=ZONE,retain_until_end=True)
    if r is None:return None
    r.update(description=narrative,category="learn",timezone=ZONE,venue_name=VENUE,venue_address=ADDRESS,venue_city=CITY,lat=LAT,lng=LNG,location_provenance="Original event venue + independent U.S. Census Public_AR_Current street address 2026-11-19",end_time_verified=True,publisher_categories=["Cooking Class","Food & Drink"],image_rights="unreviewed")
    r.pop("image_url",None)
    return r
def collect(source,fetch,*,deadline_at=None,now=None):
    if not source_valid(source):raise ValueError("michael_unregistered_source")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("michael_unaware_now")
    deadline=min(monotonic()+38,deadline_at if deadline_at is not None else float("inf"))
    listing=page(fetch,FEED,MAX_INDEX_BYTES)
    cards=nodes(listing,"eventlist-event--upcoming","article")
    if not 1<=len(cards)<=70:raise ValueError("michael_index_bounds")
    prospects=[]
    for c in cards:
        titles=nodes(c,"eventlist-title-link","a")
        if len(titles)!=1:continue
        title=plain(titles[0].text_content());dd=day(c)
        if not dd or PRIVATE.search(title) or not now.date()<=dd<=(now+WINDOW).date():continue
        st=dtime(c,"event-time-localized-start");en=dtime(c,"event-time-localized-end")
        if st is None or en is None:continue
        u=urljoin(FEED,titles[0].get("href",""))
        if not event_url(u):raise ValueError("michael_invalid_link")
        prospects.append((u,title,dd,st,en))
    if not prospects:raise ValueError("michael_no_future_cards")
    rows={}
    for u,title,dd,st,en in prospects[:MAX_DETAILS]:
        if monotonic()>=deadline:raise ValueError("michael_deadline")
        r=parse_detail(u,title,dd,st,en,page(fetch,u,MAX_DETAIL_BYTES),now)
        if r:
            ident=(r["id"],r["starts_at"])
            if ident in rows and rows[ident]!=r:raise ValueError("michael_duplicate_conflict")
            rows[ident]=r
    if not rows:raise ValueError("michael_no_verified_events")
    return sorted(rows.values(),key=lambda r:(r["starts_at"],r["id"]))
