"""Jack O'Neill Restaurant: first-party live-music cards and complete details.

The publisher provides an explicit date and show time on the index and a
same-host artist detail URL. Pair the two; never use an artist bio to invent a
performance date or geocode an offsite address.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from time import monotonic
from urllib.parse import urljoin,urlsplit,urlunsplit
from zoneinfo import ZoneInfo
import hashlib
import re
from roomquest.mapsee_adapter import plain,record
from roomquest.event_description import description

KEY='jack_oneill_live_music_santa_cruz_ca'
ZONE='America/Los_Angeles'
URL='https://www.jackoneillrestaurant.com/live-music/'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('www.jackoneillrestaurant.com',)}
VENUE='Jack O’Neill Restaurant & Lounge'
STREET='175 W Cliff Drive, Santa Cruz, CA 95060'
MAX_RECORDS=24
MAX_DESCRIPTION=12000
CARD_DATE=re.compile(r'^([A-Za-z]{3}\s+\d{1,2},\s+20\d{2})\s*\|\s*(\d{1,2}:\d{2}\s*[AP]M)\s*[-–—]\s*(\d{1,2}:\d{2}\s*[AP]M)$',re.I)
NONPUBLIC=re.compile(r'\b(?:canceled|cancelled|postponed|private event|closed for)\b',re.I)
OFFSITE=re.compile(r'\b(?:offsite|off-site|other location|at another venue)\b',re.I)
PHOTO_PATH=re.compile(r'/images/events/images/[-a-z0-9_]+\.(?:jpe?g|png|webp)$',re.I)

def event_url(value):
 if not isinstance(value,str):return False
 u=urlsplit(value)
 return bool(u.scheme=='https' and u.hostname=='www.jackoneillrestaurant.com'
  and u.port in (None,443) and not u.username and not u.password
  and not u.query and not u.fragment
  and re.fullmatch(r'/live-music/[a-z0-9]+(?:-[a-z0-9]+)*/?',u.path))

def photo_url(value):
 if not isinstance(value,str) or len(value)>1800:return None
 u=urlsplit(value)
 if (u.scheme!='https' or u.hostname!='www.jackoneillrestaurant.com'
    or u.port not in (None,443) or u.username or u.password
    or not PHOTO_PATH.fullmatch(u.path) or u.fragment):return None
 if u.query and not re.fullmatch(r'\d{5,22}',u.query):return None
 return urlunsplit((u.scheme,u.netloc,u.path,'',''))

def _times(value):
 m=CARD_DATE.fullmatch(' '.join(value.split()))
 if not m:return None
 try:
  d=datetime.strptime(m.group(1),'%b %d, %Y').date()
  def parse_time(t):
   return datetime.combine(d,datetime.strptime(t.upper().replace(' ',''),
          '%I:%M%p').time(),ZoneInfo(ZONE)).astimezone(timezone.utc)
  st,en=parse_time(m.group(2)),parse_time(m.group(3))
  if en<=st:return None
  return st,en
 except ValueError:return None

def _detail(url,title,fetch,deadline):
 from bs4 import BeautifulSoup
 if deadline and monotonic()>=deadline:raise ValueError('jack_detail_deadline')
 soup=BeautifulSoup(fetch(url,'text/html'),'html.parser')
 wrapper=soup.select_one('div.event.active div.description')
 if not wrapper:raise ValueError('jack_detail_layout_changed')
 header=wrapper.select_one('h3')
 if not header or plain(header.get_text(' ',strip=True))!=title:
  raise ValueError('jack_detail_identity_changed')
 copied=BeautifulSoup(str(wrapper),'html.parser')
 for x in copied.select('h3,.event-info'):x.decompose()
 narrative=description(str(copied),limit=max(len(str(copied)),MAX_DESCRIPTION+1))
 if not narrative or len(narrative)>MAX_DESCRIPTION:return None
 return narrative

def collect(source,fetch,*,deadline_at=None,now=None):
 from bs4 import BeautifulSoup
 if (source.get('source_key')!=KEY
   or (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY]
   or source.get('timezone')!=ZONE):
  raise ValueError('unregistered_jack_oneill_source')
 soup=BeautifulSoup(fetch(URL,'text/html'),'html.parser')
 cards=soup.select('.card.event')
 if not cards or len(cards)>MAX_RECORDS:raise ValueError('jack_calendar_layout_changed')
 now=now or datetime.now(timezone.utc)
 results={}
 for card in cards:
  h=card.select_one('h3')
  date=card.select_one('.event-info p')
  link=card.select_one('a.btn-lm[href]')
  if not h or not date or not link:continue
  title=plain(h.get_text(' ',strip=True))
  u=urljoin('https://www.jackoneillrestaurant.com',link.get('href',''))
  if not title or NONPUBLIC.search(title) or not event_url(u):continue
  pair=_times(date.get_text(' ',strip=True))
  if not pair:continue
  st,en=pair
  if not now-timedelta(hours=3)<=st<=now+timedelta(days=60) or en<=now:continue
  attr=card.get('data-date')
  try:
   stated_date=datetime.strptime(attr,'%m/%d/%Y %I:%M:%S %p').date()
   if stated_date!=st.astimezone(ZoneInfo(ZONE)).date():continue
  except (TypeError,ValueError):continue
  narrative=_detail(u,title,fetch,deadline_at)
  if not narrative or OFFSITE.search(narrative):continue
  uid=hashlib.sha256((u+'|'+st.isoformat()).encode('utf8')).hexdigest()[:24]
  row=record(title,st.isoformat(),en.isoformat(),VENUE,STREET,'Santa Cruz',u,uid,
             'Live Music',None,None,ZONE,retain_until_end=True)
  if not row:continue
  row.update(description=narrative,timezone=ZONE,publisher_categories=['Live Music'],
             location_provenance='official_publisher_venue_street')
  img=card.select_one('figure.event-img img[src]')
  candidate=urljoin('https://www.jackoneillrestaurant.com',img.get('src')) if img else None
  from roomquest.publisher_evidence import attach
  row=attach(row,KEY,candidate=candidate)
  k=(row['id'],row['starts_at'])
  if k in results and results[k]!=row:raise ValueError('jack_duplicate_occurrence')
  results[k]=row
 return sorted(results.values(),key=lambda e:(e['starts_at'],e['title'],e['id']))
