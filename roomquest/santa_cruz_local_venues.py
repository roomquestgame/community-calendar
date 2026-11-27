"""Direct Santa Cruz venue calendars: Woodhouse, Discretion, Agricultural History Project.

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
from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.event_description import description

ZONE='America/Los_Angeles'
WOODHOUSE='woodhouse_brewing_santa_cruz_ca'
DISCRETION='discretion_brewing_soquel_ca'
AG_HISTORY='agricultural_history_project_watsonville_ca'
MAKER='santa_cruz_maker_studios_fall_workshops_ca'
TANNERY='tannery_arts_center_winter_market_2026_ca'
SCCMOD='santa_cruz_childrens_museum_craft_fair_2026_ca'
SCMAC='santa_cruz_mountains_art_center_gift_art_2026_ca'
SOURCES={
 WOODHOUSE:('https://www.woodhousebrews.com/api/events','json','squarespace'),
 DISCRETION:('https://www.discretionbrewing.com/events/','html','html'),
 AG_HISTORY:('https://aghistoryproject.org/2nd-saturday-on-the-farm/','html','html'),
 MAKER:('https://scmakerstudios.com/fall-events-2026/','html','html'),
 TANNERY:('https://www.tanneryartscenter.org/winter-art-market','html','html'),
 SCCMOD:('https://www.sccmod.org/learn-more/childrenscraftfair','html','html'),
 SCMAC:('https://www.mountainartcenter.org/call-for-artists-gift-of-art-2026/','html','html'),
}
ALLOWED_HOSTS={k:(urlsplit(v[0]).hostname,) for k,v in SOURCES.items()}
VENUE={
 WOODHOUSE:('Woodhouse Blending & Brewing','119 Madrone St, Santa Cruz, CA 95060','Santa Cruz'),
 DISCRETION:('Discretion Brewing','2703 41st Ave Ste A, Soquel, CA 95073','Soquel'),
 AG_HISTORY:('Agricultural History Project Center & Museum','2601 East Lake Avenue, Watsonville, CA 95076','Watsonville'),
 MAKER:('Santa Cruz Maker Studios','427 A. Swift Street, Santa Cruz, CA 95060','Santa Cruz'),
 TANNERY:('Tannery Arts Center','1050-1060 River Street, Santa Cruz, CA 95060','Santa Cruz'),
 SCCMOD:('Capitola Mall, outside MOD and Macy’s','1855 41st Ave, Capitola, CA','Capitola'),
 SCMAC:('Santa Cruz Mountains Art Center','9341 Mill Street, Ben Lomond, CA 95005','Ben Lomond'),
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
 if key==AG_HISTORY:
  return bool(p.hostname=='aghistoryproject.org' and p.path=='/2nd-saturday-on-the-farm/' and not p.fragment)
 if key==MAKER:
  return bool(p.hostname=='scmakerstudios.com' and p.path=='/fall-events-2026/' and not p.fragment)
 if key==TANNERY:
  return bool(p.hostname=='www.tanneryartscenter.org' and p.path=='/winter-art-market' and not p.fragment)
 if key==SCCMOD:
  return bool(p.hostname=='www.sccmod.org' and p.path=='/learn-more/childrenscraftfair' and not p.fragment)
 if key==SCMAC:
  return bool(p.hostname=='www.mountainartcenter.org' and p.path=='/call-for-artists-gift-of-art-2026/' and not p.fragment)
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
   r'/content/v1/[a-zA-Z0-9]+/[^/?#]+/[^/?#]+\.(?:jpe?g|png|webp)',p.path,re.I):
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
 row['collector_event_content_v1'] = {'version': 1, 'event_id': uid, 'facts': {
     'title': title, 'description': prose, 'is_all_day': False,
     'starts_at_utc': start.isoformat(), 'ends_at_utc': end.isoformat(),
     'event_url': link, 'source_image_url': photo_url(WOODHOUSE,item.get('image')),
     'publisher_categories': [plain(value) for value in item.get('categories') or [] if isinstance(value,str)],
 }}
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

def ag_history(page,official_hours,now):
 """One explicitly dated 2026 program, not a year-round guessed recurrence."""
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(page,'html.parser')
 proof=BeautifulSoup(official_hours,'html.parser')
 heading=[h for h in soup.find_all('h2') if re.fullmatch(
   r'2026\s+2nd\s+Saturdays,\s*11:00am\s*[-–—]\s*2:00pm',
   h.get_text(' ',strip=True),re.I)]
 dated=[h for h in soup.find_all('h4') if re.fullmatch(
   r'December\s+12th\s*[-–—]\s*Holidays\s+on\s+the\s+Farm',
   h.get_text(' ',strip=True),re.I)]
 if len(heading)!=1 or len(dated)!=1 or dated[0].find_previous('h2')!=heading[0]:
  raise ValueError('ag_history_schedule_unverified')
 address_pattern=r'\b2601\s+East\s+Lake\s+Avenue\b'
 if not all(re.search(address_pattern,doc.get_text(' ',strip=True),re.I)
            for doc in (soup,proof)):
  raise ValueError('ag_history_street_unverified')
 if 'Agricultural History Project' not in proof.get_text(' ',strip=True):
  raise ValueError('ag_history_venue_unverified')
 paragraphs=[]
 for node in soup.find_all('p'):
  value=node.get_text(' ',strip=True)
  if ('Every month we produce a 2nd Saturday on the Farm' in value or
      'We have created some unique interactive educational activities' in value):
   paragraphs.append(value)
 if len(paragraphs)!=2 or any(len(t)<90 for t in paragraphs):
  raise ValueError('ag_history_narrative_unverified')
 # Dated owner's own heading is a full event identity. No inferred future dates.
 start=datetime(2026,12,12,11,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 end=datetime(2026,12,12,14,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 if start.weekday()!=5 and datetime(2026,12,12).weekday()!=5:
  raise ValueError('ag_history_date_mismatch')
 if not within(start,end,now):return []
 title='Holidays on the Farm'
 venue,street,city=VENUE[AG_HISTORY]
 row=record(title,start.isoformat(),end.isoformat(),venue,street,city,
            SOURCES[AG_HISTORY][0], 'aghistoryproject-2026-12-12-holidays',
            'Family Event, Agricultural Heritage',None,None,ZONE,retain_until_end=True)
 if not row:return []
 prose=full_description(' '.join(paragraphs+[dated[0].get_text(' ',strip=True)]))
 if not prose:raise ValueError('ag_history_narrative_unverified')
 row.update(description=prose,timezone=ZONE,publisher_categories=['Family Event','Agricultural Heritage'],
            location_provenance='publisher_venue_verified_entrance_street')
 from roomquest.publisher_evidence import attach
 return [attach(row,AG_HISTORY)]


def maker_studios(page,official_about,now):
 """Original dated Sunday maker sign-ups; no extrapolated weekly recurrence."""
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(page,'html.parser')
 about=BeautifulSoup(official_about,'html.parser')
 h1=[n.get_text(' ',strip=True) for n in soup.select('h1')]
 if h1.count('Fall Events 2026')!=1:
  raise ValueError('maker_2026_calendar_unverified')
 address='427 A. Swift Street, Santa Cruz, CA 95060'
 if ('Santa Cruz Maker Studios' not in about.get_text(' ',strip=True)
     or 'Visit us at '+address not in about.get_text(' ',strip=True)):
  raise ValueError('maker_official_street_unverified')
 body=soup.get_text(' ',strip=True)
 try:
  a=body.index('Fall 2026 Event Registration')
  b=body.index('Signing up a second family member',a)
 except ValueError as exc:
  raise ValueError('maker_registration_sections_unverified') from exc
 block=body[a:b]
 intros=[
  'Join us for our seasonal Sunday workshops! Each event features a unique hands-on project designed to inspire creativity and celebrate the season.',
  'Planning to join us throughout the season? Our Maker Sundays Semester Pass includes all Sunday Maker classes and special events, offering the best value while reserving your spot for the entire semester.',
  'Please note: Registering through the Maker Sundays Registration Form or purchasing a Semester Pass includes these special event dates, so there is no need to register for them separately.'
 ]
 if any(block.count(t)!=1 for t in intros):
  raise ValueError('maker_original_narrative_unverified')
 dates=[
  ('2026-11-29','Fall Wreath Making','November',29),
  ('2026-12-06','Holiday Wreath Making','December',6),
  ('2026-12-13','Holiday Gift Making','December',13),
  ('2026-12-20','Holiday Gift Making','December',20),
 ]
 headings=[f'{label}: Sunday, {month} {day}' for _,label,month,day in dates]
 if any(block.count(h)!=1 for h in headings):
  raise ValueError('maker_dated_event_unverified')
 rows=[]
 for idx,(day,label,month,num) in enumerate(dates):
  if datetime.fromisoformat(day).weekday()!=6:
   raise ValueError('maker_sunday_date_unverified')
  head=headings[idx]
  start=block.index(head)
  end=block.index(headings[idx+1],start) if idx+1<len(dates) else len(block)
  excerpt=block[start:end]
  abbrev='Nov' if month=='November' else 'Dec'
  for session,first,last,start_time,end_time in (
    ('youth',7,12,'10:00am','12:00pm'),
    ('advanced',10,15,'12:30pm','2:30pm'),
  ):
   pat=(rf'{abbrev}\.\s*{num}\s*\({session.title()} Ages\s*{first}\s*[–-]\s*{last}\)'
        rf'\s*{re.escape(start_time)}-{re.escape(end_time)}\s*[–-]\s*\$45\.00')
   # Registration labels are event-specific and must not be guessed from open hours.
   match=re.search(pat,excerpt,re.I)
   if not match or len(re.findall(pat,excerpt,re.I))!=1:
    raise ValueError('maker_session_time_unverified')
   sh,sm=map(int,re.search(r'(\d{1,2}):(\d{2})',start_time).groups())
   eh,em=map(int,re.search(r'(\d{1,2}):(\d{2})',end_time).groups())
   sh=(sh%12)+(12 if start_time.endswith('pm') else 0)
   eh=(eh%12)+(12 if end_time.endswith('pm') else 0)
   begin=datetime(2026,int(day[5:7]),num,sh,sm,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
   finish=datetime(2026,int(day[5:7]),num,eh,em,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
   if not within(begin,finish,now):continue
   venue,street,city=VENUE[MAKER]
   uid=f'scmaker-{day}-{session}'
   title=f'{label} — {session.title()} Maker Sunday'
   row=record(title,begin.isoformat(),finish.isoformat(),venue,street,city,
              SOURCES[MAKER][0],uid,'Maker Workshop, Youth Program',None,None,ZONE,
              retain_until_end=True)
   if not row:continue
   # Every segment is the publisher's own complete text; no synthetic activity prose.
   prose=full_description(' '.join((head,match.group(0),*intros)))
   if not prose or len(prose)<300:
    raise ValueError('maker_original_narrative_unverified')
   row.update(description=prose,timezone=ZONE,
              publisher_categories=['Maker Workshop','Youth Program'],
              location_provenance='publisher_verified_studio_street')
   from roomquest.publisher_evidence import attach
   rows.append(attach(row,MAKER))
 if len(rows)!=len({(r['id'],r['starts_at']) for r in rows}):
  raise ValueError('maker_duplicate_occurrence')
 return sorted(rows,key=lambda r:(r['starts_at'],r['id']))


def tannery_market(page,now):
 """One original first-party 2026 winter art market; retain the full published event text.

 Original venue is a 1050-1060 River Street CAMPUS RANGE, not a fabricated
 one-building address, publisher office, geocode or coverage centroid.
 Downstream Geocodio must resolve the exact ASCII-equivalent published range.
 """
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(page,'html.parser')
 for tag in soup(['script','style','nav','footer','header']):
  tag.decompose()
 titles=[v.get_text(' ',strip=True) for v in soup.find_all('h1')]
 dates=[v.get_text(' ',strip=True) for v in soup.find_all('h2')]
 body=soup.get_text(' ',strip=True)
 actual=[
  'WINTER ART MARKET 2026',
  'Saturday, Dec. 12, 2026',
  'When: Saturday, December 12, 2026 | 10am–5pm',
  'Where: Tannery Arts Center, 1050–1060 River Street, Santa Cruz',
  'Admission: Free and open to the public',
 ]
 if titles.count(actual[0])!=1 or dates.count(actual[1])!=1:
  raise ValueError('tannery_event_heading_or_date_unverified')
 if any(body.count(t)!=1 for t in actual[2:]):
  raise ValueError('tannery_official_clocks_venue_or_admission_unverified')
 if re.search(r'\b(?:cancelled|canceled|postponed|private event)\b',body,re.I):
  raise ValueError('tannery_market_status_requires_review')
 begin=datetime(2026,12,12,10,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 finish=datetime(2026,12,12,17,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 if datetime(2026,12,12).weekday()!=5:
  raise ValueError('tannery_event_day_mismatch')
 if not within(begin,finish,now):return []
 venue,street,city=VENUE[TANNERY]
 description_text=full_description('. '.join(actual)+'.')
 if not description_text or len(description_text)<140:
  raise ValueError('tannery_original_narrative_missing')
 url=SOURCES[TANNERY][0]
 row=record('Winter Art Market 2026',begin.isoformat(),finish.isoformat(),
            venue,street,city,url,'tannery-2026-12-12-winter-art-market',
            'Winter Art Market',None,None,ZONE,retain_until_end=True)
 if not row:raise ValueError('tannery_record_unexpectedly_rejected')
 row.update(description=description_text,timezone=ZONE,
            publisher_categories=['Winter Art Market'],
            location_provenance='publisher_official_event_campus_street_range')
 from roomquest.publisher_evidence import attach
 return [attach(row,TANNERY)]

def sccmod_craft_fair(page,now):
 """One exact publisher-owned Small Business Saturday 2026 fair, not a monthly recurrence."""
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(page,'html.parser')
 for node in soup(['script','style','nav','footer','header']):
  node.decompose()
 titles=[node.get_text(' ',strip=True) for node in soup.find_all('h1')]
 details=[node.get_text(' ',strip=True) for node in soup.find_all('h2')]
 expected_title="Small Business Saturday Children's Craft Fair"
 expected_schedule="Saturday, November 28, 2026 | 2:00 to 5:00 PM"
 expected_venue="Capitola Mall, outside MOD and Macy’s | 1855 41st Ave, Capitola, CA"
 if titles.count(expected_title)!=1 or sum(expected_schedule in s and expected_venue in s and 'Free Admission' in s for s in details)!=1:
  raise ValueError('sccmod_original_schedule_street_unverified')
 if datetime(2026,11,28).weekday()!=5:
  raise ValueError('sccmod_saturday_conflict')
 parts=[
  'Looking for unique holiday gifts in Santa Cruz County?',
  'Skip the big-box crowds and find one-of-a-kind gifts',
  'Kids can browse, budget, and pick out holiday gifts',
 ]
 texts=[node.get_text(' ',strip=True) for node in soup.find_all('p')]
 narrative=[]
 for prefix in parts:
  matches=[s for s in texts if s.startswith(prefix) and len(s)>=150]
  if len(matches)!=1:
   raise ValueError('sccmod_original_narrative_unverified')
  narrative.append(matches[0])
 body=' '.join(narrative)
 if NOT_PUBLIC.search(body+' '+' '.join(details)):
  raise ValueError('sccmod_nonpublic_event')
 prose=full_description('\n\n'.join(narrative))
 if not prose or len(prose)<550:
  raise ValueError('sccmod_original_narrative_unverified')
 begin=datetime(2026,11,28,14,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 finish=datetime(2026,11,28,17,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 if not within(begin,finish,now):return []
 venue,street,city=VENUE[SCCMOD]
 row=record(expected_title,begin.isoformat(),finish.isoformat(),venue,street,city,
            SOURCES[SCCMOD][0],'sccmod-2026-11-28-childrens-craft-fair',
            'Children’s Craft Fair, Small Business Saturday',None,None,ZONE,retain_until_end=True)
 if not row:return []
 row.update(description=prose,timezone=ZONE,
            publisher_categories=['Children’s Craft Fair','Small Business Saturday'],
            location_provenance='exact_original_publisher_mall_event_street')
 from roomquest.publisher_evidence import attach
 return [attach(row,SCCMOD)]


def mountain_art_center_gift_art(page,now):
 """Two explicitly timed 2026 original gallery holiday events.

 The primary original page is an artist call; the other deadlines, studio opening
 hours and exhibit period are NOT individual public-event occurrences.
 """
 from bs4 import BeautifulSoup
 soup=BeautifulSoup(page,'html.parser')
 for tag in soup(['script','style','nav','header']):
  tag.decompose()
 h1=[n.get_text(' ',strip=True) for n in soup.find_all('h1')]
 if h1.count('Call for Artists: The Gift of Art')!=1:
  raise ValueError('scmac_original_2026_identity_unverified')
 text=soup.get_text(' ',strip=True)
 if 'Exhibit Dates: November 5 – December 22, 2026' not in text:
  raise ValueError('scmac_original_year_unverified')
 address='9341 Mill Street, Ben Lomond, CA 95005'
 if len([p for p in soup.select('p') if p.get_text(' ',strip=True)==address])!=1:
  raise ValueError('scmac_original_venue_street_unverified')
 related=[h for h in soup.find_all('h3') if h.get_text(' ',strip=True)=='Related Events for this exhibit:']
 if len(related)!=1:
  raise ValueError('scmac_original_related_events_unverified')
 segment=related[0].find_next_sibling('p')
 if segment is None:
  raise ValueError('scmac_original_event_schedule_unverified')
 events=segment.get_text(' ',strip=True)
 # The page provides a 2026 exhibition year and separate related-event clocks.
 expected=[
  ('2026-12-04','First Friday Open House',17,19,'scmac-2026-12-04-first-friday'),
  ('2026-12-19','Annual Holiday Sale',12,17,'scmac-2026-12-19-holiday-sale'),
 ]
 patterns=[
  r'First Friday Open House,\s*December\s*4\s*\|\s*5\s*[–—-]\s*7\s*pm',
  r'Annual Holiday Sale,\s*December\s*19\s*\|\s*12\s*[–—-]\s*5\s*pm',
 ]
 if any(len(re.findall(p,events,re.I))!=1 for p in patterns):
  raise ValueError('scmac_original_dates_and_clocks_unverified')
 paragraphs=[p.get_text(' ',strip=True) for p in soup.select('p')]
 original=[p for p in paragraphs if p.startswith('Once again we will have our popular holiday gift exhibit.')]
 if len(original)!=1 or len(original[0])<240 or not all(s in original[0] for s in (
     'functional ceramics','jewelry','All mediums are welcome','But all submissions must be for sale')):
  raise ValueError('scmac_original_full_narrative_unverified')
 if any(re.search(r'\b(?:cancelled|canceled|postponed|private event)\b',e,re.I)
        for e in (events,original[0])):
  raise ValueError('scmac_original_event_status_review')
 rows=[]
 venue,street,city=VENUE[SCMAC]
 for (day,title,hour,finish,uid),pattern in zip(expected,patterns):
  if day=='2026-12-04' and datetime.fromisoformat(day).weekday()!=4:
   raise ValueError('scmac_friday_calendar_conflict')
  if day=='2026-12-19' and datetime.fromisoformat(day).weekday()!=5:
   raise ValueError('scmac_saturday_calendar_conflict')
  start=datetime.fromisoformat(day).replace(hour=hour,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
  end=datetime.fromisoformat(day).replace(hour=finish,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
  if not within(start,end,now):continue
  row=record('The Gift of Art — '+title,start.isoformat(),end.isoformat(),
             venue,street,city,SOURCES[SCMAC][0],uid,
             'Art Gallery, Holiday Event',None,None,ZONE,retain_until_end=True)
  if not row:raise ValueError('scmac_event_record_unexpectedly_rejected')
  date_clock=re.search(pattern,events,re.I).group(0)
  prose=full_description(original[0]+'\n\n'+date_clock)
  if not prose or len(prose)<270:
   raise ValueError('scmac_original_narrative_unverified')
  row.update(description=prose,timezone=ZONE,
             publisher_categories=['Art Gallery','Holiday Event'],
             location_provenance='publisher_verified_gallery_street')
  from roomquest.publisher_evidence import attach
  rows.append(attach(row,SCMAC))
 if len(rows)!=len({(r['id'],r['starts_at']) for r in rows}):
  raise ValueError('scmac_duplicate_original_occurrence')
 return sorted(rows,key=lambda r:(r['starts_at'],r['id']))

def collect(source,fetch,*,deadline_at=None,now=None):
 key=source.get('source_key')
 if key not in SOURCES or (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[key] or source.get('timezone')!=ZONE:
  raise ValueError('unregistered_santa_cruz_local_source')
 if deadline_at and monotonic()>=deadline_at:raise ValueError('collection_deadline')
 now=calendar_anchor(now or datetime.now(timezone.utc))
 if key==TANNERY:
  return tannery_market(fetch(SOURCES[key][0],'text/html'),now)
 if key==SCCMOD:
  return sccmod_craft_fair(fetch(SOURCES[key][0],'text/html'),now)
 if key==SCMAC:
  return mountain_art_center_gift_art(fetch(SOURCES[key][0],'text/html'),now)
 if key==MAKER:
  return maker_studios(fetch(SOURCES[key][0],'text/html'),
                       fetch('https://scmakerstudios.com/about/','text/html'),now)
 if key==AG_HISTORY:
  return ag_history(fetch(SOURCES[key][0],'text/html'),
                    fetch('https://aghistoryproject.org/hours-admission/','text/html'),now)
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
