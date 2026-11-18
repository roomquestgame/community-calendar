"""Publisher-owned Squarespace event calendars at Santa Cruz venues.

Never treat Squarespace's default NYC coordinates as Santa Cruz. The venue's
published street is used only for events on that venue's own calendar.
Excerpt-only, cancelled, undated and offsite records are held.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import json,math,re
from urllib.parse import urljoin,urlsplit,urlunsplit
from roomquest.mapsee_adapter import plain,record
from roomquest.event_description import description

ZONE='America/Los_Angeles'
ABBOTT='abbott_square_market_santa_cruz_ca'
CREPE='the_crepe_place_santa_cruz_ca'
MADSON='madson_wines_santa_cruz_ca'
STOCKWELL='stockwell_cellars_santa_cruz_ca'
DIVERSITY='diversity_center_santa_cruz_ca'
SOURCES={
 ABBOTT:('https://www.abbottsquaremarket.com/events?format=json','json','squarespace'),
 CREPE:('https://www.thecrepeplace.com/shows-list?format=json','json','squarespace'),
 MADSON:('https://www.madsonwines.com/events-2?format=json','json','squarespace'),
 STOCKWELL:('https://www.stockwellcellars.com/events?format=json','json','squarespace'),
 DIVERSITY:('https://www.diversitycenter.org/upcoming-events?format=json','json','squarespace')
}
OWN_HOSTS={ABBOTT:'www.abbottsquaremarket.com',CREPE:'www.thecrepeplace.com',MADSON:'www.madsonwines.com',STOCKWELL:'www.stockwellcellars.com',DIVERSITY:'www.diversitycenter.org'}
ALLOWED_HOSTS={k:(OWN_HOSTS[k],) for k in SOURCES}
VENUES={
 ABBOTT:('Abbott Square Market','725 Front Street, Santa Cruz, CA 95060','Santa Cruz'),
 CREPE:('The Crepe Place','1134 Soquel Avenue, Santa Cruz, CA 95062','Santa Cruz'),
 MADSON:('Madson Wines Tasting Room','328 Ingalls Street, Suite G, Santa Cruz, CA 95060','Santa Cruz'),
 STOCKWELL:('Stockwell Cellars','1100 Fair Avenue, Santa Cruz, CA 95060','Santa Cruz'),
 DIVERSITY:('The Diversity Center','1117 Soquel Avenue, Santa Cruz, CA 95062','Santa Cruz')
}
SQUARESPACE_SITE_IDS={ABBOTT:'63fea813188ad81e69c290b6',CREPE:'5f371a0781c3fe6a3e650a90',MADSON:'60627269ce92a3553c16edf1',STOCKWELL:'5acbe1b5b27e3910337dbee9',DIVERSITY:'52449106e4b098f57c7a9472'}
MAX_RECORDS=160
MAX_DESCRIPTION=12000
NO_IMAGE=re.compile(r'(?:^|[-_/])(?:logo|favicon|avatar|icon|placeholder|pixel)(?:[-_.]|$)',re.I)
NONPUBLIC=re.compile(r'\b(?:cancelled|canceled|postponed|closed for|private event|members[- ]only)\b',re.I)
OFFSITE=re.compile(r'\b(?:offsite|off-site|other location|another venue|away from the crepe place|away from abbott square)\b',re.I)
STREET_OTHER=re.compile(r'\b\d{3,6}\s+(?:[a-z0-9.#-]+\s+){1,7}(?:street|st|road|rd|avenue|ave|drive|dr|way|blvd)\b',re.I)

def event_url(key,value):
 if key not in SOURCES or not isinstance(value,str) or len(value)>1200:return False
 u=urlsplit(value)
 path='/events/' if key==ABBOTT else '/shows-list/' if key==CREPE else '/events-2/' if key==MADSON else '/upcoming-events/' if key==DIVERSITY else '/events/'
 return bool(u.scheme=='https' and u.hostname==OWN_HOSTS[key] and not u.query
  and not u.fragment and not u.username and not u.password and u.port in (None,443)
  and re.fullmatch(path+(r'(?:20\d{2}/\d{1,2}/\d{1,2}/)?' if key==DIVERSITY else r'20\d{2}/\d{1,2}/\d{1,2}/' if key==STOCKWELL else '')+r'[a-z0-9]+(?:-[a-z0-9]+)*/?',u.path))

def photo_url(key,value):
 if key not in SOURCES or not isinstance(value,str) or len(value)>2200:return None
 u=urlsplit(value)
 if (u.scheme!='https' or u.hostname!='images.squarespace-cdn.com'
   or u.username or u.password or u.fragment or NO_IMAGE.search(u.path)
   or not re.fullmatch(r'/content/v1/'+SQUARESPACE_SITE_IDS[key]+r'/[^/?#]+/[^/?#]+\.(?:jpe?g|png|webp)',u.path,re.I)):
  return None
 # Validate source asset identity; convert ?format=750w to the original.
 if u.query and not re.fullmatch(r'format=\d{2,4}w',u.query):return None
 return urlunsplit((u.scheme,u.netloc,u.path,'',''))

def _narrative(value):
 if not isinstance(value,str) or not value.strip():return None
 s=description(value,limit=max(len(value),MAX_DESCRIPTION+1))
 return s if s and len(s)<=MAX_DESCRIPTION else None

def _epoch(value):
 if type(value) not in (int,float) or not math.isfinite(value) or value<1000000000000:
  raise ValueError('invalid_squarespace_date')
 return datetime.fromtimestamp(value/1000,timezone.utc)

def _row(key,e,now):
 if not isinstance(e,dict) or not isinstance(e.get('id'),str):return None
 if e.get('workflowState') not in (None,1) or e.get('allDay') or e.get('allDayEvent') or e.get('cancelled'):
  return None
 title=plain(e.get('title'))
 if not title or NONPUBLIC.search(title):return None
 start,end=_epoch(e.get('startDate')),_epoch(e.get('endDate'))
 if not now-timedelta(hours=3)<=start<=now+timedelta(days=60) or end<=now or end<=start:return None
 prose=_narrative(e.get('body'))
 if not prose or OFFSITE.search(prose):return None
 if key==MADSON and (e.get('location') or {}).get('addressLine1')!='328 Ingalls Street, Suite G':return None
 if key==DIVERSITY:
  native=e.get('location') or {}
  if (native.get('addressTitle') not in ('The Diversity Center','The Diversity Center of Santa Cruz','The Diversity Center and Zoom')
      or native.get('addressLine1') not in ('1117 Soquel Ave','1117 Soquel Avenue')
      or native.get('addressLine2') not in ('Santa Cruz, California, 95062','Santa Cruz CA 95062')):
   return None
 if key==STOCKWELL:
  native=e.get('location') or {}
  if (native.get('addressTitle')!='Stockwell Cellars' or
      native.get('addressLine1')!='1100 Fair Avenue' or
      native.get('addressLine2')!='Santa Cruz, CA, 95060'):
   return None
 other=STREET_OTHER.search(prose)
 if other and not re.search(r'725\s+Front|118\s+Cooper|1134\s+Soquel|328\s+Ingalls|1100\s+Fair|1117\s+Soquel',other.group(0),re.I):
  return None
 url=urljoin('https://'+OWN_HOSTS[key],e.get('fullUrl') or '')
 if not event_url(key,url):return None
 name,street,city=VENUES[key]
 labels=[plain(x) for x in (e.get('categories') or []) if isinstance(x,str)][:15]
 lat,lng=None,None
 if key==STOCKWELL:
  native=e.get('location') or {}
  try:
   lt,ln=float(native.get('markerLat')),float(native.get('markerLng'))
   if math.isfinite(lt) and math.isfinite(ln) and 36.85<=lt<=37.2 and -122.2<=ln<=-121.8:
    lat,lng=lt,ln
  except (TypeError,ValueError,OverflowError):pass
 row=record(title,start.isoformat(),end.isoformat(),name,street,city,url,e['id'],
            ', '.join(labels),lat,lng,ZONE,retain_until_end=True)
 if row is None:return None
 row.update(description=prose,timezone=ZONE,publisher_categories=labels,
            location_provenance='official_publisher_venue_street')
 from roomquest.publisher_evidence import attach
 return attach(row,key,candidate=e.get('assetUrl'))

def collect(source,fetch,*,deadline_at=None,now=None):
 from roomquest.squarespace import check_pagination
 key=source.get('source_key')
 if key not in SOURCES or (source.get('feed_url'),source.get('kind'),source.get('platform_adapter')) != SOURCES[key] or source.get('timezone')!=ZONE:
  raise ValueError('unregistered_santa_cruz_square_source')
 payload=json.loads(fetch(SOURCES[key][0],'application/json'))
 if not isinstance(payload,dict) or not isinstance(payload.get('upcoming'),list):
  raise ValueError('invalid_santa_cruz_square_payload')
 if (payload.get('website') or {}).get('timeZone')!=ZONE:raise ValueError('publisher_timezone_changed')
 if len(payload['upcoming'])>MAX_RECORDS:raise ValueError('source_record_limit')
 check_pagination(payload,upcoming=True)
 now=now or datetime.now(timezone.utc)
 rows={}
 for e in payload['upcoming']:
  item=_row(key,e,now)
  if item is None:continue
  k=(item['id'],item['starts_at'])
  if k in rows and rows[k]!=item:raise ValueError('conflicting_event_occurrence')
  rows[k]=item
 return sorted(rows.values(),key=lambda x:(x['starts_at'],x['title'],x['id']))
