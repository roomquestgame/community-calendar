"""Santa Cruz Museum of Art & History: exact public occurrence and venue pages.

A single first-party 17-card calendar, plus only linked event details.
Every event detail publishes its own <address>; Evergreen Cemetery is never
assigned the museum's 705 Front St pin. Use publisher body, not card excerpt.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re
from roomquest.mapsee_adapter import plain,record
from roomquest.event_description import description

KEY='santa_cruz_mah_calendar_ca'
URL='https://www.santacruzmah.org/events'
ZONE='America/Los_Angeles'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('www.santacruzmah.org',)}
MAX_RECORDS=50
MAX_DESCRIPTION=12000
DAYTIME=re.compile(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+\s+\d{1,2},\s+20\d{2}),\s+(\d{1,2}(?::\d{2})?\s*[ap]m)\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*[ap]m)$',re.I)
STREET=re.compile(r'^(\d{1,6}\s+[A-Za-z0-9 .#-]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Way|Blvd|Boulevard))\s+(Santa Cruz),\s+CA\s+(\d{5})(?:-\d{4})?$',re.I)
NONPUBLIC=re.compile(r'\b(?:postponed|cancelled|canceled|private event|members[- ]only)\b',re.I)
OTHER_VENUES={'705 front street':'Santa Cruz Museum of Art & History',
              '261 evergreen st':'Evergreen Cemetery'}

def event_url(value):
 if not isinstance(value,str):return False
 u=urlsplit(value)
 return bool(u.scheme=='https' and u.hostname=='www.santacruzmah.org' and not u.username
  and not u.password and u.port in (None,443) and not u.query and not u.fragment
  and re.fullmatch(r'/events/[a-z0-9]+(?:-[a-z0-9]+)*/20\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/?',u.path))

def _datetime(value):
 m=DAYTIME.fullmatch(' '.join(value.split()))
 if not m:return None
 try:
  date=datetime.strptime(m.group(2),'%B %d, %Y').date()
  if date.strftime('%A').lower()!=m.group(1).lower():return None
  def parse_clock(raw):
   raw=re.sub(r'\s+','',raw.lower())
   dt=datetime.strptime(raw,'%I:%M%p' if ':' in raw else '%I%p').time()
   return datetime.combine(date,dt,ZoneInfo(ZONE)).astimezone(timezone.utc)
  start,end=parse_clock(m.group(3)),parse_clock(m.group(4))
  return (start,end) if end>start else None
 except ValueError:return None

def _street(value):
 m=STREET.fullmatch(' '.join(value.split()))
 if not m:return None
 street=plain(m.group(1))
 key=street.casefold().rstrip(' .')
 name=OTHER_VENUES.get(key)
 if not name:return None
 return name,f'{street}, {m.group(2)}, CA {m.group(3)}',m.group(2)

def _detail(url,title,fetch,now,deadline):
 from bs4 import BeautifulSoup
 if deadline is not None and monotonic()>=deadline:raise ValueError('mah_deadline')
 doc=BeautifulSoup(fetch(url,'text/html'),'html.parser')
 main=doc.find('main')
 if not main:raise ValueError('mah_detail_missing')
 h=main.select_one('h1')
 if not h or plain(h.get_text(' ',strip=True))!=title:raise ValueError('mah_event_identity_changed')
 date_node=main.select_one('p.text-lg')
 address=main.find('address')
 body=main.select_one('div.copy.max-w-lg.mx-auto')
 if not date_node or not address or not body:raise ValueError('mah_detail_incomplete')
 times=_datetime(date_node.get_text(' ',strip=True))
 own=_street(address.get_text(' ',strip=True))
 if not times or not own:return None
 start,end=times
 if not (now-timedelta(hours=3)<=start<=now+timedelta(days=60) and end>now):return None
 text=description(str(body),limit=max(len(str(body)),MAX_DESCRIPTION+1))
 if not text or len(text)>MAX_DESCRIPTION:return None
 venue,street,city=own
 row=record(title,start.isoformat(),end.isoformat(),venue,street,city,url,
            urlsplit(url).path,'',None,None,ZONE,retain_until_end=True)
 if row:
  row.update(description=text,timezone=ZONE,publisher_categories=[],
             location_provenance='publisher_event_address')
 return row

def collect(source,fetch,*,deadline_at=None,now=None):
 from bs4 import BeautifulSoup
 if (source.get('source_key')!=KEY or
     (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY]
     or source.get('timezone')!=ZONE):
  raise ValueError('unregistered_mah_source')
 now=now or datetime.now(timezone.utc)
 soup=BeautifulSoup(fetch(URL,'text/html'),'html.parser')
 cards=soup.select('article')
 if not cards or len(cards)>MAX_RECORDS:raise ValueError('mah_manifest_changed')
 out={}
 for card in cards:
  link=card.select_one('h3 a[href]')
  if not link:link=card.select_one('a[href*="/events/"] h3')
  if link and link.name=='h3':link=link.parent
  if not link:continue
  url=link.get('href')
  title=plain(link.get_text(' ',strip=True))
  if not title or NONPUBLIC.search(title) or not event_url(url):continue
  row=_detail(url,title,fetch,now,deadline_at)
  if row is None:continue
  ident=(row['id'],row['starts_at'])
  if ident in out and out[ident]!=row:raise ValueError('mah_duplicate_conflict')
  out[ident]=row
 return sorted(out.values(),key=lambda x:(x['starts_at'],x['title'],x['id']))
