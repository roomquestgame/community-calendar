"""Catalyst and Atrium: bounded official show pages, not teaser list excerpts.

One publisher calendar and at most 25 first-party detail pages. Each accepted
show has its month/year from the publisher's list separator, show time (not
doors), full prose from its own show page, and the reviewed venue street.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re
from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import plain,record
from roomquest.event_description import description

KEY='catalyst_club_santa_cruz_ca'
URL='https://catalystclub.com/events/'
ZONE='America/Los_Angeles'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('catalystclub.com',)}
MAX_RECORDS=25
MAX_DESCRIPTION=12000
STREET='1011 Pacific Ave, Santa Cruz, CA 95060'
MONTH=re.compile(r'^([A-Za-z]+)\s+(20\d{2})$')
CARD_DATE=re.compile(r'^([A-Za-z]{3}),\s+([A-Za-z]{3})\s+(\d{1,2})$')
SHOW=re.compile(r'\bShow:\s*(\d{1,2})(?::([0-5]\d))?\s*(am|pm)\b',re.I)
NOT_PUBLIC=re.compile(r'\b(?:cancelled|canceled|postponed|private event|members only)\b',re.I)

def event_url(value):
 if not isinstance(value,str):return False
 u=urlsplit(value)
 return bool(u.scheme=='https' and u.hostname=='catalystclub.com' and not u.username
             and not u.password and u.port in (None,443) and not u.fragment and not u.query
             and re.fullmatch(r'/event/[a-z0-9]+(?:-[a-z0-9]+)*(?:/(?:the-catalyst|the-catalyst-atrium)/(?:santa-cruz-california)/)?',u.path))

def _date(day,month_header,show_text):
 header=MONTH.fullmatch(month_header)
 match=CARD_DATE.fullmatch(day)
 clock=SHOW.search(show_text)
 if not header or not match or not clock:return None
 try:
  date=datetime.strptime(f'{match.group(2)} {match.group(3)} {header.group(2)}','%b %d %Y').date()
  if date.strftime('%a')!=match.group(1) or date.strftime('%B')!=header.group(1):return None
  hh=int(clock.group(1));mm=int(clock.group(2) or 0)
  if not 1<=hh<=12:return None
  hour=hh%12+(12 if clock.group(3).lower()=='pm' else 0)
  return datetime(date.year,date.month,date.day,hour,mm,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
 except ValueError:return None

def _item(card,header,fetch,deadline,now):
 from bs4 import BeautifulSoup
 title_node=card.select_one('.rhp-event__title--list')
 link_node=card.select_one('a#eventTitle[href]')
 date_node=card.select_one('.singleEventDate')
 show_node=card.select_one('.eventDoorStartDate')
 if not (title_node and link_node and date_node and show_node):return None
 title=plain(title_node.get_text(' ',strip=True))
 url=link_node.get('href','')
 if not title or NOT_PUBLIC.search(title) or not event_url(url):return None
 start=_date(date_node.get_text(' ',strip=True),header,show_node.get_text(' ',strip=True))
 if not start or not now-timedelta(hours=3)<=start<=now+timedelta(days=60):return None
 if deadline is not None and monotonic()>=deadline:raise ValueError('catalyst_deadline')
 html=fetch(url,'text/html')
 doc=BeautifulSoup(html,'html.parser')
 detail=doc.select_one('div.singleEventDescription')
 if detail is None:raise ValueError('catalyst_description_missing')
 prose=description(str(detail),limit=max(len(str(detail)),MAX_DESCRIPTION+1))
 if not prose or len(prose)>MAX_DESCRIPTION:raise ValueError('catalyst_description_missing')
 if NOT_PUBLIC.search(prose[:120]):return None
 # The venue path and publisher's canonical 1011 Pacific contact determine
 # whether this is the downstairs Atrium or the upstairs Catalyst stage.
 if '/the-catalyst-atrium/' in url:
  venue='The Catalyst Atrium'
 elif '/the-catalyst/' in url or url.rstrip('/').count('/')==3:
  venue='The Catalyst'
 else:return None
 row=record(title,start.isoformat(),None,venue,STREET,'Santa Cruz',url,
            urlsplit(url).path,'',None,None,ZONE,retain_until_end=True)
 if row:
  row.update(description=prose,timezone=ZONE,publisher_categories=[],
             location_provenance='official_catalyst_venue_street')
 return row

def collect(source,fetch,*,deadline_at=None,now=None):
 from bs4 import BeautifulSoup
 if (source.get('source_key')!=KEY or
     (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY]
     or source.get('timezone')!=ZONE):
  raise ValueError('unregistered_catalyst_source')
 now=calendar_anchor(now or datetime.now(timezone.utc))
 html=fetch(URL,'text/html')
 soup=BeautifulSoup(html,'html.parser')
 sections=soup.select('div.rhp-mobile-list')
 if len(sections)!=1:raise ValueError('catalyst_list_layout_changed')
 section=sections[0]
 cards=section.select('div.rhpSingleEvent')
 if not cards or len(cards)>MAX_RECORDS:raise ValueError('catalyst_event_count_changed')
 rows={};month=None
 for node in section.find_all(recursive=False):
  classes=set(node.get('class') or [])
  if 'rhp-events-list-separator-month' in classes:
   text=node.get_text(' ',strip=True)
   if MONTH.fullmatch(text):month=text
   else:raise ValueError('catalyst_month_header_changed')
  elif 'rhpSingleEvent' in classes:
   if not month:raise ValueError('catalyst_month_header_missing')
   row=_item(node,month,fetch,deadline_at,now)
   if not row:continue
   key=(row['id'],row['starts_at'])
   if key in rows and rows[key]!=row:raise ValueError('conflicting_catalyst_event')
   rows[key]=row
 return sorted(rows.values(),key=lambda x:(x['starts_at'],x['title'],x['id']))
