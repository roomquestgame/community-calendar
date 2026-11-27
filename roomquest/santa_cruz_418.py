"""The 418 Project public dated dance, class and performance calendar.

The first-party HTML contains each full description and an explicit next
occurrence in Pacific time. Capture those published occurrences only; do
not materialize 43 implied repeats or infer an end time from class duration.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain,record

KEY='the_418_project_santa_cruz_ca'
ZONE='America/Los_Angeles'
URL='https://the418project.org/upcoming'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('the418project.org',)}
VENUE='The 418 Project'
STREET='155 River St S, Santa Cruz, CA 95060'
MAX_RECORDS=80
MAX_DESCRIPTION=12000
CARD_TIME=re.compile(r'^([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+20\d{2})\s+@\s+(\d{1,2}:\d{2}\s*[AP]M)\s*[-–—]\s*(\d{1,2}:\d{2}\s*[AP]M)$',re.I)
NOT_PUBLIC=re.compile(r'\b(?:canceled|cancelled|postponed|private event|members only|event closed)\b',re.I)
OFFSITE=re.compile(r'\b(?:offsite|off-site|another venue|at a different location)\b',re.I)

def event_url(link):
 if not isinstance(link,str):return False
 u=urlsplit(link)
 return bool(u.scheme=='https' and u.hostname=='the418project.org' and not u.query
   and not u.fragment and not u.username and not u.password and u.port in (None,443)
   and re.fullmatch(r'/events/[a-z0-9]+(?:-[a-z0-9]+)*/?',u.path))

def parse_schedule(raw):
 m=CARD_TIME.fullmatch(' '.join(raw.split()))
 if not m:return None
 try:
  date=datetime.strptime(m.group(1),'%A, %B %d, %Y').date()
  def dt(s):
   time=datetime.strptime(re.sub(r'\s+',' ',s.strip()),'%I:%M %p').time()
   return datetime.combine(date,time,ZoneInfo(ZONE))
  start,end=dt(m.group(2)),dt(m.group(3))
 except ValueError:return None
 if end<=start:return None
 return start.astimezone(timezone.utc),end.astimezone(timezone.utc)

def collect(source,fetch,*,deadline_at=None,now=None):
 from bs4 import BeautifulSoup
 if (source.get('source_key')!=KEY or
     (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY]
     or source.get('timezone')!=ZONE):
  raise ValueError('unregistered_418_source')
 html=fetch(URL,'text/html')
 soup=BeautifulSoup(html,'html.parser')
 cards=soup.select('div.card.card-hover')
 if not cards or len(cards)>MAX_RECORDS:raise ValueError('invalid_418_calendar')
 now=calendar_anchor(now or datetime.now(timezone.utc))
 rows={}
 for card in cards:
  node=card.select_one('h3 a[href]')
  prose=card.select_one('div.prose.prose-sm')
  when=card.select_one('p.font-bold')
  if not node or not prose or not when:continue
  title=plain(node.get_text(' ',strip=True))
  url=node.get('href')
  if not title or NOT_PUBLIC.search(title) or not event_url(url):continue
  times=parse_schedule(when.get_text(' ',strip=True))
  if not times:continue
  start,end=times
  if not (now-timedelta(hours=3)<=start<=now+timedelta(days=60) and end>now):continue
  body=description(str(prose),limit=max(len(str(prose)),MAX_DESCRIPTION+1))
  if not body or len(body)>MAX_DESCRIPTION or OFFSITE.search(body):continue
  # The card's layout labels are publisher-defined event types, not an
  # instruction to give every event the same source-wide category.
  types=[plain(t.get_text(' ',strip=True)) for t in card.select('span')
         if plain(t.get_text(' ',strip=True)) in
         ('Class','Performance','Party','Lecture / Panel','Movie Screening','Community Meeting')]
  labels=list(dict.fromkeys(types))[:6]
  row=record(title,start.isoformat(),end.isoformat(),VENUE,STREET,'Santa Cruz',
             url,urlsplit(url).path.rsplit('/',1)[-1],', '.join(labels),
             None,None,ZONE,retain_until_end=True)
  if row is None:continue
  row.update(description=body,timezone=ZONE,publisher_categories=labels,
             location_provenance='reviewed_publisher_venue_street')
  ident=(row['id'],row['starts_at'])
  if ident in rows and rows[ident]!=row:raise ValueError('conflicting_418_occurrence')
  rows[ident]=row
 return sorted(rows.values(),key=lambda x:(x['starts_at'],x['title'],x['id']))
