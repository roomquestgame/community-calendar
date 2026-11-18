"""Rio Theatre original Squarespace event JSON; complete event narrative and street."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

KEY = 'rio_theatre_santa_cruz_ca'
ZONE = 'America/Los_Angeles'
URL = 'https://www.riotheatre.com/events-2?format=json'
SOURCES = {KEY: (URL, 'json', 'squarespace')}
ALLOWED_HOSTS = {KEY: ('www.riotheatre.com',)}
MAX_RECORDS = 160
MAX_DESCRIPTION = 12000
VENUE_STREET = re.compile(r'^1205\s+Soquel\s+(?:Avenue|Ave)\.?$', re.I)
CITY_STATE = re.compile(r'^Santa Cruz,\s*CA,\s*95062$', re.I)
EVENT_PATH = re.compile(r'/events-2/20\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/[a-z0-9]+(?:-[a-z0-9]+)*/?')
PHOTO_PATH = re.compile(r'/content/v1/[A-Za-z0-9]+/[^/?#]+/[^/?#]+\.(?:jpe?g|png|webp)$', re.I)
NO_IMAGE = re.compile(r'(?:^|[-_/])(?:logo|favicon|avatar|placeholder|icon|pixel)(?:[-_.]|$)',re.I)
NONPUBLIC = re.compile(r'\b(?:postponed|cancelled|canceled|private event|members only)\b',re.I)

def event_url(value):
    if not isinstance(value,str):
        return False
    u=urlsplit(value)
    return bool(u.scheme=='https' and u.hostname=='www.riotheatre.com' and not u.query and not u.fragment
                and not u.username and not u.password and u.port in (None,443)
                and EVENT_PATH.fullmatch(u.path))

def photo_url(value):
    if not isinstance(value,str) or len(value)>2000:
        return None
    u=urlsplit(value)
    if (u.scheme!='https' or u.hostname!='images.squarespace-cdn.com'
            or u.username or u.password or u.fragment or not PHOTO_PATH.fullmatch(u.path)
            or NO_IMAGE.search(u.path)):
        return None
    # Only the original asset; formats like ?format=750w are resized.
    return urlunsplit((u.scheme,u.netloc,u.path,'',''))

def _narrative(value):
    if not isinstance(value,str) or not value.strip():
        return None
    text=description(value,limit=max(len(value),MAX_DESCRIPTION+1))
    return text if text and len(text)<=MAX_DESCRIPTION else None

def _coordinates(loc):
    try:
        lat,lng=float(loc.get('markerLat')),float(loc.get('markerLng'))
        if (math.isfinite(lat) and math.isfinite(lng) and
                36.9<=lat<=37.1 and -122.2<=lng<=-121.9):
            return lat,lng
    except (TypeError,ValueError,OverflowError):
        pass
    return None,None

def _row(item,now):
    if not isinstance(item,dict) or not isinstance(item.get('id'),str):
        raise ValueError('invalid_rio_event_record')
    if item.get('workflowState') != 1 or item.get('cancelled') or item.get('allDay') or item.get('allDayEvent'):
        return None
    title=plain(item.get('title'))
    if not title or NONPUBLIC.search(title):
        return None
    start=timestamp(item.get('startDate'))
    end=timestamp(item.get('endDate'))
    if not start or not end or end<=start or start<now-timedelta(hours=24) or start>now+timedelta(days=60):
        return None
    loc=item.get('location') if isinstance(item.get('location'),dict) else {}
    name=plain(loc.get('addressTitle'))
    addr=plain(loc.get('addressLine1'))
    cityline=plain(loc.get('addressLine2'))
    if name.casefold()!='rio theatre for the performing' or not VENUE_STREET.fullmatch(addr) or not CITY_STATE.fullmatch(cityline):
        return None
    prose=_narrative(item.get('body'))
    if prose is None:
        return None
    link=urljoin('https://www.riotheatre.com',item.get('fullUrl') or '')
    if not event_url(link):
        return None
    lat,lng=_coordinates(loc)
    labels=[plain(x) for x in (item.get('categories') or []) if isinstance(x,str)][:20]
    row=record(title,start.isoformat(),end.isoformat(),name,'1205 Soquel Ave, Santa Cruz, CA 95062',
               'Santa Cruz',link,item['id'],', '.join(labels),lat,lng,ZONE,retain_until_end=True)
    if not row:
        return None
    row.update(description=prose,timezone=ZONE,publisher_categories=labels,
               location_provenance='publisher_event_venue')
    from roomquest.publisher_evidence import attach
    return attach(row,KEY,candidate=item.get('assetUrl'))

def collect(source,fetch,*,deadline_at=None,now=None):
    if (source.get('source_key') != KEY or
       (source.get('feed_url'),source.get('kind'),source.get('platform_adapter')) != SOURCES[KEY]
       or source.get('timezone') != ZONE):
        raise ValueError('unregistered_rio_source')
    payload=json.loads(fetch(URL,'application/json'))
    if not isinstance(payload,dict) or not isinstance(payload.get('upcoming'),list):
        raise ValueError('invalid_rio_payload')
    if (payload.get('website') or {}).get('timeZone')!=ZONE:
        raise ValueError('publisher_timezone_changed')
    from roomquest.squarespace import check_pagination
    check_pagination(payload,upcoming=True)
    if len(payload['upcoming'])>MAX_RECORDS:
        raise ValueError('source_record_limit')
    now=now or datetime.now(timezone.utc)
    result={}
    for item in payload['upcoming']:
        row=_row(item,now)
        if not row:
            continue
        ident=(row['id'],row['starts_at'])
        if ident in result and result[ident]!=row:
            raise ValueError('conflicting_rio_occurrence')
        result[ident]=row
    return sorted(result.values(),key=lambda x:(x['starts_at'],x['title'],x['id']))
