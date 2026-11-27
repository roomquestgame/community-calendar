"""Santa Cruz tabletop events: only Game Night Collective's publisher-verified venues.

The public iCalendar feed syndicates other organizers and sometimes contains
contradictory library or moved-venue addresses. Admit only the four venues
listed on the Collective's own venue page and whose exact event LOCATION also
matches that address. Do not fabricate recurrence, event URLs, or a venue pin.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import plain, record
from roomquest.event_description import description

KEY='santa_cruz_game_night_collective_ca'
ZONE='America/Los_Angeles'
FEED='https://vpvkznkdczmtsmizxkbl.supabase.co/functions/v1/santa-cruz-calendar'
SOURCES={KEY:(FEED,'ical','ical')}
ALLOWED_HOSTS={KEY:('vpvkznkdczmtsmizxkbl.supabase.co',)}
MAX_RECORDS=100
MAX_DESCRIPTION=12000
VERIFIED=[
 ('Gilman Brewing','gilman brewing','817 soquel ave','817 Soquel Ave, Santa Cruz, CA 95062','Santa Cruz'),
 ('The Cruz Room','the cruz room','1520 mission st','1520 Mission St, Santa Cruz, CA 95060','Santa Cruz'),
 ('Peoples Coffee','peoples coffee','1200 17th ave','1200 17th Ave #130, Santa Cruz, CA 95062','Santa Cruz'),
 ('11th Hour Coffee','11th hour coffee','1001 center st','1001 Center St #1, Santa Cruz, CA 95060','Santa Cruz'),
]

def event_url(value):
 if not isinstance(value,str) or len(value)>1600:return False
 u=urlsplit(value)
 if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.fragment:return False
 if u.hostname=='luma.com':
  return bool(re.fullmatch(r'/[a-z0-9]{6,40}',u.path) and not u.query)
 if u.hostname in ('www.meetup.com','meetup.com'):
  return bool(re.fullmatch(r'/[a-zA-Z0-9-]+/events/[1-9][0-9]{5,12}/?',u.path) and not u.query)
 return False

def _venue(location):
 s=plain(location).casefold()
 matches=[(name,street,city) for name,venue,addr,street,city in VERIFIED
          if venue in s and addr in s]
 # A mixed venue string is suspicious even when it contains one recognized street.
 if len(matches)!=1:return None
 for name,venue,addr,street,city in VERIFIED:
  if name != matches[0][0] and venue in s:return None
 return matches[0]

def collect(source,fetch,*,deadline_at=None,now=None):
 from icalendar import Calendar
 if (source.get('source_key') != KEY or
     (source.get('feed_url'),source.get('kind'),source.get('platform_adapter')) != SOURCES[KEY]
     or source.get('timezone')!=ZONE):
  raise ValueError('unregistered_game_night_source')
 raw=fetch(FEED,'text/calendar')
 if isinstance(raw,str):raw=raw.encode('utf-8')
 cal=Calendar.from_ical(raw)
 events=cal.walk('VEVENT')
 if len(events)>500:raise ValueError('source_record_limit')
 now=calendar_anchor(now or datetime.now(timezone.utc))
 result={}
 for event in events:
  if event.errors:continue
  if str(event.get('STATUS','')).upper() in ('CANCELLED','TENTATIVE'):continue
  if event.get('RRULE') or event.get('RECURRENCE-ID'):
   # No guessed recurrence; publisher must publish an individual occurrence.
   continue
  start=event.decoded('DTSTART') if event.get('DTSTART') else None
  end=event.decoded('DTEND') if event.get('DTEND') else None
  if not isinstance(start,datetime) or not isinstance(end,datetime):continue
  if not start.tzinfo or not end.tzinfo or end<=start:continue
  if not now-timedelta(hours=3)<=start<=now+timedelta(days=60) or end<=now:continue
  name=plain(event.get('SUMMARY'))
  if not name or re.search(r'\b(cancelled|postponed|private)\b',name,re.I):continue
  venue=_venue(str(event.get('LOCATION','')))
  if venue is None:continue
  narrative=description(str(event.get('DESCRIPTION','')),limit=MAX_DESCRIPTION+1)
  if not narrative or len(narrative)>MAX_DESCRIPTION:continue
  uid=str(event.get('UID',''))
  if not uid.endswith('@gamenightcollective.com') or not (8<len(uid)<180):continue
  url=str(event.get('URL',''))
  if not event_url(url):continue
  organizer_label = ('Board games and tabletop gaming' if
                     re.search(r'\b(game|games|board|rpg|playtest|designer)\b',name,re.I)
                     else '')
  row=record(name,start.isoformat(),end.isoformat(),venue[0],venue[1],venue[2],
             url,uid,organizer_label,None,None,ZONE,retain_until_end=True)
  if row:
   row.update(description=narrative,timezone=ZONE,
              publisher_categories=[organizer_label] if organizer_label else [],
              location_provenance='publisher_event_venue')
   ident=(row['id'],row['starts_at'])
   if ident in result and result[ident]!=row:
    raise ValueError('conflicting_game_night_occurrence')
   result[ident]=row
 if len(result)>MAX_RECORDS:raise ValueError('source_record_limit')
 return sorted(result.values(),key=lambda x:(x['starts_at'],x['title'],x['id']))
