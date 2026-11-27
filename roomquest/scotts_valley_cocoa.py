"""First-party Scotts Valley Recreation holiday Crafts & Cocoa 2026.

Both event time and named place are original city evidence. Event street is
corroborated by the city's independent recreation/contact address. One exact
2026 session only, with no future recurrence synthesis or invented GEO.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import record

KEY='scotts_valley_recreation_crafts_cocoa_2026_ca'
EVENT='https://scottsvalley.gov/807/Crafts-Cocoa'
ADDRESS='https://scottsvalley.gov/439/About-Us'
SOURCES={KEY:(EVENT,'html','html')}
ALLOWED_HOSTS={KEY:('scottsvalley.gov',)}
ZONE='America/Los_Angeles'
MAX_RECORDS=1
MAX_DESCRIPTION=12000
STREET='360 Kings Village Road, Scotts Valley, CA 95066'

def event_url(value):
    if not isinstance(value,str):return False
    p=urlsplit(value)
    return bool(p.scheme=='https' and p.hostname=='scottsvalley.gov' and p.path=='/807/Crafts-Cocoa'
                and not (p.query or p.fragment or p.username or p.password or p.port))

def _owner_event(page,now):
    soup=BeautifulSoup(page,'html.parser')
    h1=[e.get_text(' ',strip=True) for e in soup.select('h1')]
    if h1.count('Crafts & Cocoa')!=1:
        raise ValueError('scotts_cocoa_official_heading_changed')
    lines=[p.get_text(' ',strip=True) for p in soup.select('p')]
    intro=[p for p in lines if 'Get cozy and get crafty with Scotts Valley Recreation!' in p]
    if len(intro)!=1 or 'holiday crafts, warm cocoa, and plenty of holiday cheer' not in intro[0]:
        raise ValueError('scotts_cocoa_original_description_changed')
    price=[p for p in lines if 'price includes cookie decorating & crafts' in p]
    if len(price)!=1:
        raise ValueError('scotts_cocoa_details_changed')
    schedule=[p for p in lines if 'Friday, December 11, 5-8pm' in p and 'Scotts Valley Community Center' in p]
    if len(schedule)!=1 or datetime(2026,12,11).weekday()!=4:
        raise ValueError('scotts_cocoa_year_date_venue_conflict')
    limit=[p for p in lines if 'Space is limited, so be sure to register early!' in p]
    if len(limit)!=1:
        raise ValueError('scotts_cocoa_booking_detail_changed')
    if re.search(r'\b(cancelled|canceled|postponed|private event)\b',' '.join(intro+price+schedule+limit),re.I):
        raise ValueError('scotts_cocoa_cancelled')
    desc='\n'.join(intro+price+schedule+limit)
    if len(desc)<175 or len(desc)>MAX_DESCRIPTION:
        raise ValueError('scotts_cocoa_full_description_missing')
    start=datetime(2026,12,11,17,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
    end=datetime(2026,12,11,20,tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
    if not now-timedelta(hours=3)<=start<=now+timedelta(days=60) or end<=now:return []
    row=record('Crafts & Cocoa',start.isoformat(),end.isoformat(),
               'Scotts Valley Community Center',STREET,'Scotts Valley',
               EVENT,'scotts-valley-crafts-cocoa-2026-12-11',
               'Family Crafts, Community Event',None,None,ZONE,retain_until_end=True)
    if not row:raise ValueError('scotts_cocoa_record_rejected')
    row.update(description=desc,timezone=ZONE,
               publisher_categories=['Community Event','Family Crafts'],
               location_provenance='original_city_event_and_city_recreation_street')
    from roomquest.publisher_evidence import attach
    return [attach(row,KEY)]

def collect(source,fetch,*,deadline_at=None,now=None):
    if (source.get('source_key')!=KEY or
        (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY]
        or source.get('timezone')!=ZONE):
        raise ValueError('scotts_cocoa_wrong_original_source')
    if deadline_at and monotonic()>=deadline_at:raise ValueError('scotts_cocoa_deadline')
    event=fetch(EVENT,'text/html')
    official=fetch(ADDRESS,'text/html')
    # The city recreation office / event host's independent official address.
    text=BeautifulSoup(official,'html.parser').get_text(' ',strip=True)
    if not re.search(r'360\s+Kings\s+Village\s+Rd\.?\s+Scotts\s+Valley,?\s+Ca\s+95066',text,re.I):
        raise ValueError('scotts_cocoa_city_street_not_confirmed')
    return _owner_event(event,calendar_anchor(now or datetime.now(timezone.utc)))
