"""Direct Santa Cruz venue calendars: Woodhouse public JSON, Discretion dated HTML.

The first-party API is authoritative for Woodhouse. Do not use its undated
JavaScript fallback. Discretion has no structured event endpoint; parse only
its matched dated event-detail cards. Hold incomplete/offsite records.
"""
from __future__ import annotations
import hashlib
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.event_description import description

ZONE='America/Los_Angeles'
WOODHOUSE='woodhouse_brewing_santa_cruz_ca'
DISCRETION='discretion_brewing_soquel_ca'
SOURCES={
 WOODHOUSE:('https://www.woodhousebrews.com/api/events','json','squarespace'),
 DISCRETION:('https://www.discretionbrewing.com/events/','html','html'),
}
ALLOWED_HOSTS={k:(urlsplit(v[0]).hostname,) for k,v in SOURCES.items()}
VENUE={
 WOODHOUSE:('Woodhouse Blending & Brewing','119 Madrone St, Santa Cruz, CA 95060','Santa Cruz'),
 DISCRETION:('Discretion Brewing','2703 41st Ave Ste A, Soquel, CA 95073','Soquel'),
}
MAX_RECORDS=180
MAX_DESCRIPTION=12000
DATE=re.compile(r'\b([01]?\d)/([0-3]?\d)/(\d{2}|20\d{2})\b')
RANGE=re.compile(r'\b(\d{1,2})(?::([0-5]\d))?\s*(am|pm)?\s*(?:-|–|—|to)\s*(\d{1,2})(?::([0-5]\d))?\s*(am|pm)\b',re.I)
CLOCK=re.compile(r'\b(\d{1,2}):([0-5]\d)\s*(am|pm)\b',re.I)
OTHER_STREET=re.compile(r'\b(\d{3,6})\s+(?:[a-z0-9]+\s+){1,5}(?:street|st|road|rd|ave|avenue|blvd|drive|dr|way)\b',re.I)
OFFSITE=re.compile(r'\b(?:offsite|off-site|another location|other venue|at the Rio Theatre)\b',re.I)
NOT_PUBLIC=re.compile(r'\b(?:cancelled|canceled|postponed|taproom closed|private event|members only)\b',re.I)
NO_IMAGE=re.compile(r'(?:^|[-_/])(?:logo|favicon|avatar|icon|placeholder|pixel)(?:[-_.]|$)',re.I)
log=logging.getLogger(__name__)

def event_url(key,value):
 if key not in SOURCES or not isinstance(value,str):return False
 p=urlsplit(value)
 if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.query:return False
 if key==WOODHOUSE:
  return bool(p.hostname=='minnow-cowbell-xynk.squarespace.com' and not p.fragment
   and re.fullmatch(r'/events/20\d{2}/\d{1,2}/\d{1,2}/[-a-z0-9]+/?',p.path))
 return bool(p.hostname=='www.discretionbrewing.com' and p.path=='/events/'
  and re.fullmatch(r'loop-item-detail-[1-9]\d{0,9}',p.fragment))

def photo_url(key,value):
 if not isinstance(value,str) or len(value)>2000:return None
 p=urlsplit(value)
 if p.scheme!='https' or p.username or p.password or p.fragment or NO_IMAGE.search(p.path):return None
 if re.search(r'-\d{2,3}x\d{2,3}\.(?:jpe?g|png|webp)$',p.path,re.I):return None
 if key==WOODHOUSE and p.hostname=='images.squarespace-cdn.com' and re.fullmatch(
   r'/content/v1/[a-zA-Z0-9]+/[^/?#]+\.(?:jpe?g|png|webp)',p.path,re.I):
  return urlunsplit((p.scheme,p.netloc,p.path,'',''))
 if key==DISCRETION and p.hostname=='www.discretionbrewing.com' and not p.query and re.fullmatch(
   r'/wp-content/uploads/20\d{2}/(?:0?[1-9]|1[0-2])/[^/?#]+\.(?:jpe?g|png|webp)',p.path,re.I):
  return value
 return None

def full_description(value):
 if not isinstance(value,str) or not value.strip():return None
 clean=description(value,limit=max(len(value),MAX_DESCRIPTION+1))
 return clean if clean and len(clean)<=MAX_DESCRIPTION else None

def within(start,end,now):
 return (start.tzinfo is not None and (end is None or (end.tzinfo is not None and end>start))
  and now-timedelta(hours=3)<=start<=now+timedelta(days=60)
  and (end is None or end>now))

def epoch(value):
 if type(value) not in (int,float) or not math.isfinite(value) or value<1000000000000:
  raise ValueError('invalid_woodhouse_epoch')
 return datetime.fromtimestamp(value/1000,timezone.utc)

def woodhouse(item,now):
 if not isinstance(item,dict) or not isinstance(item.get('title'),str) or not isinstance(item.get('url'),str):
  return None
 title=plain(item['title']);link=item['url']
 if not title or NOT_PUBLIC.search(title) or not event_url(WOODHOUSE,link):return None
 start,end=epoch(item.get('start')),epoch(item.get('end'))
 if not within(start,end,now):return None
 prose=full_description(item.get('body'))
 if not prose or OFFSITE.search(prose):return None
 other=OTHER_STREET.search(prose)
 if other and not re.search(r'119\s+Madrone',other.group(0),re.I):return None
 venue,street,city=VENUE[WOODHOUSE]
 uid=hashlib.sha256(link.encode()).hexdigest()[:24]
 labels=[plain(v) for v in (item.get('categories') or []) if isinstance(v,str)][:20]
 row=record(title,start.isoformat(),end.isoformat(),venue,street,city,link,uid,
   ', '.join(labels),None,None,ZONE,retain_until_end=True)
 if not row:return None
 row.update(description=prose,timezone=ZONE,publisher_categories=labels,
            location_provenance='reviewed_official_venue_street')
 from roomquest.publisher_evidence import attach
 return attach(row,WOODHOUSE,candidate=item.get('image'))

def local_clock(day,h,minute,ampm):
 h=int(h);m=int(minute or 0)
 if h<1 or h>12 or m>59:raise ValueError('invalid_discretion_clock')
 hour=(h%12)+(12 if ampm.lower()=='pm' else 0)
 return timestamp(f'{day}T{hour:02d}:{m:02d}:00',ZONE)

def schedule(date_text,desc_text):
 match=DATE.search(date_text or '')
 if not match:return None
 try:
  y=int(match.group(3));y=2000+y if y<100 else y
  day=datetime(y,int(match.group(1)),int(match.group(2))).date().isoformat()
 except ValueError:return None
 t=RANGE.search(desc_text or '')
 if t:
  sh,sm,sa,eh,em,ea=t.groups()
  finish=local_clock(day,eh,em,ea)
  start=local_clock(day,sh,sm,sa) if sa else local_clock(day,sh,sm,ea)
  if start>=finish and not sa:start=local_clock(day,sh,sm,'am' if ea.lower()=='pm' else 'pm')
  return start,finish if finish>start else None
 t=CLOCK.search(desc_text or '')
 return (local_clock(day,*t.groups()),None) if t else None

def discretion(html,now):
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(html,'html.parser')
 details=soup.select('div.event-detail[id^="loop-item-detail-"]')
 if not details or len(details)>300:raise ValueError('invalid_discretion_calendar')
 records={}
 for detail in details:
  ident=detail.get('id','')
  if not re.fullmatch(r'loop-item-detail-[1-9]\d{0,9}',ident):continue
  title_node=detail.select_one('h3');date_node=detail.select_one('.event-date')
  prose_node=detail.select_one('.detail-description')
  if not title_node or not date_node or not prose_node:continue
  title=title_node.get_text(' ',strip=True)
  if not title or NOT_PUBLIC.search(title):continue
  times=schedule(date_node.get_text(' ',strip=True),prose_node.get_text(' ',strip=True))
  if not times:continue
  start,end=times
  if not within(start,end,now):continue
  copied=BeautifulSoup(str(prose_node),'html.parser')
  first=copied.select_one('.detail-description p')
  if first and re.fullmatch(r'(?:Live Music\s*)?\d{1,2}(?::\d{2})?\s*(?:-|–|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)',first.get_text(' ',strip=True),re.I):
   first.decompose()
  prose=full_description(str(copied))
  if not prose or OFFSITE.search(prose):continue
  other=OTHER_STREET.search(prose)
  if other and not re.search(r'2703\s+41st',other.group(0),re.I):continue
  link='https://www.discretionbrewing.com/events/#'+ident
  labels=[]
  if re.search(r'live.music|concert|band|musician',title+' '+prose,re.I):labels.append('Live Music')
  if re.search(r'trivia',title,re.I):labels.append('Trivia')
  if re.search(r'movie|film|screening',title,re.I):labels.append('Film Screening')
  if re.search(r'market|craft fair',title,re.I):labels.append('Craft Fair')
  if re.search(r'fundrais|benefit',title,re.I):labels.append('Fundraiser')
  venue,street,city=VENUE[DISCRETION]
  row=record(title,start.isoformat(),end.isoformat() if end else None,
             venue,street,city,link,ident,', '.join(labels),None,None,ZONE,retain_until_end=True)
  if not row:continue
  row.update(description=prose,timezone=ZONE,publisher_categories=labels,
             location_provenance='reviewed_official_venue_street')
  image=detail.select_one('img.gallery-main')
  from roomquest.publisher_evidence import attach
  row=attach(row,DISCRETION,candidate=image.get('src') if image else None)
  key=(row['id'],row['starts_at'])
  if key in records and records[key]!=row:raise ValueError('conflicting_discretion_occurrence')
  records[key]=row
 return sorted(records.values(),key=lambda v:(v['starts_at'],v['title'],v['id']))

def collect(source,fetch,*,deadline_at=None,now=None):
 key=source.get('source_key')
 if key not in SOURCES or (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[key] or source.get('timezone')!=ZONE:
  raise ValueError('unregistered_santa_cruz_local_source')
 if deadline_at and monotonic()>=deadline_at:raise ValueError('collection_deadline')
 now=now or datetime.now(timezone.utc)
 if key==WOODHOUSE:
  payload=json.loads(fetch(SOURCES[key][0],'application/json'))
  if not isinstance(payload,dict) or not isinstance(payload.get('events'),list) or len(payload['events'])>180:
   raise ValueError('invalid_woodhouse_payload')
  rows={}
  for item in payload['events']:
   row=woodhouse(item,now)
   if row:
    k=(row['id'],row['starts_at'])
    if k in rows and rows[k]!=row:raise ValueError('conflicting_woodhouse_occurrence')
    rows[k]=row
  return sorted(rows.values(),key=lambda v:(v['starts_at'],v['title'],v['id']))
 return discretion(fetch(SOURCES[key][0],'text/html'),now)
