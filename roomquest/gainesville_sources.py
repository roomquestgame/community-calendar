"""Gainesville GA first-party calendar adapters. Uses shared JSON, evidence and geocoder lanes.

No guessed street number, source-wide pin, HTML scrape, or invented description.
Images are candidates only; the receiving backend owns publication rights.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlencode, urlsplit, urljoin
from zoneinfo import ZoneInfo
import json
import math
import re
import logging

from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
EXPLORE = 'explore_gainesville_ga'
BLACKSTRAP = 'blackstrap_rock_hall_ga'
ARTS = 'gainesville_arts_council_ga'
SOURCES = {
    EXPLORE: ('https://www.exploregainesville.org/wp-json/tribe/events/v1/events', 'json', 'wordpress'),
    BLACKSTRAP: ('https://www.blackstraprockhall.com/events?format=json', 'json', 'squarespace'),
    ARTS: ('https://www.theartscouncil.net/events?format=json', 'json', 'squarespace'),
}
ALLOWED_HOSTS = {key: (urlsplit(t[0]).hostname,) for key, t in SOURCES.items()}
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500
WINDOW_DAYS = 30
STREET = re.compile(r'^\d{1,6}[A-Za-z]?\s+.{2,140}\b(?:street|st|road|rd|avenue|ave|drive|dr|blvd|boulevard|lane|ln|court|ct|way|parkway|pkwy|place|pl|plaza|circle|cir|hwy|highway|trail|trl)(?:\s+(?:north|south|east|west|ne|nw|se|sw|n|s|e|w|northeast|southwest))?\.?$', re.I)
NONPUBLIC = re.compile(r'\b(?:private event|members? only|invitation only|cancelled|postponed|online only|virtual event)\b', re.I)
NO_IMAGE = re.compile(r'(?:^|[-_/])(?:logo|favicon|icon|avatar|placeholder|pixel)(?:[-_.]|$)', re.I)
logger = logging.getLogger(__name__)

def _hold(key, identity, reason):
    logger.info('gainesville_held source=%s id=%s reason=%s', key, str(identity)[:100], reason)

def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str):
        return False
    u, root = urlsplit(value), urlsplit(SOURCES[key][0])
    prefix = '/event/' if key == EXPLORE else '/events/'
    return bool(u.scheme == 'https' and u.hostname == root.hostname
                and not u.username and not u.password and not u.query and not u.fragment
                and re.fullmatch(prefix + r'[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?', u.path)
                if key == EXPLORE else
                u.scheme == 'https' and u.hostname == root.hostname and not u.query and not u.fragment
                and not u.username and not u.password
                and re.fullmatch(prefix + r'[a-z0-9-]+/?', u.path))

def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    u = urlsplit(value)
    host = 'www.exploregainesville.org' if key == EXPLORE else 'images.squarespace-cdn.com'
    if (u.scheme != 'https' or u.hostname != host or u.username or u.password or u.fragment
            or NO_IMAGE.search(u.path) or not re.search(r'\.(?:jpe?g|png|webp)$', u.path, re.I)
            or re.search(r'-\d{2,3}x\d{2,3}\.', u.path)):
        return None
    if key == EXPLORE and (u.query or not re.fullmatch(r'/wp-content/uploads/20\d{2}/(?:0?[1-9]|1[0-2])/.+',u.path)):
        return None
    if key != EXPLORE and (not u.path.startswith('/content/v1/') or u.query):
        return None
    return value

def _narrative(value):
    from roomquest.event_description import description
    if not isinstance(value, str):
        return None
    text = description(value, limit=max(len(value), MAX_DESCRIPTION + 1))
    return text if text and len(text) <= MAX_DESCRIPTION else None

def _street(street, city, state, postal=''):
    street, city, state, postal = map(plain, (street, city, state, postal))
    if state.casefold() == 'georgia':
        state = 'GA'
    if not STREET.fullmatch(street) or not city or state.upper() != 'GA':
        return None
    if postal and not re.fullmatch(r'\d{5}(?:-\d{4})?', postal):
        postal = ''
    return f'{street}, {city}, GA' + (f' {postal}' if postal else '')

def _point(location):
    lat, lon = location.get('geo_lat', location.get('markerLat')), location.get('geo_lng', location.get('markerLng'))
    try:
        a, b = float(lat), float(lon)
        return (a, b) if math.isfinite(a) and math.isfinite(b) and 32.5 <= a <= 35.3 and -85 <= b <= -82 else (None, None)
    except (ValueError, TypeError):
        return None, None

def _wordpress(item):
    if not isinstance(item, dict) or item.get('id') in (None,''):
        raise ValueError('invalid_wordpress_payload')
    identity = str(item['id'])
    if item.get('status') != 'publish' or item.get('hide_from_listings') or item.get('all_day'):
        return None
    title = plain(item.get('title'))
    venue = item.get('venue') if isinstance(item.get('venue'),dict) else {}
    name = plain(venue.get('venue'))
    if not title or NONPUBLIC.search(title + ' ' + name):
        return None
    address = _street(venue.get('address'),venue.get('city'),venue.get('state') or venue.get('stateprovince'),venue.get('zip'))
    if not address or not name:
        _hold(EXPLORE,identity,'street_unverified');return None
    if item.get('timezone') != ZONE:
        _hold(EXPLORE,identity,'timezone_unverified');return None
    start = timestamp(item.get('utc_start_date'),'UTC')
    end = timestamp(item.get('utc_end_date'),'UTC')
    if start is None or (end and end < start):
        _hold(EXPLORE,identity,'invalid_date');return None
    try:
        wall = datetime.fromisoformat(item['start_date'])
        if wall.tzinfo is not None:
            valid = wall.astimezone(timezone.utc) == start.astimezone(timezone.utc)
        else:
            zone=ZoneInfo(ZONE)
            valid=any(wall.replace(tzinfo=zone,fold=f).astimezone(timezone.utc)==start.astimezone(timezone.utc) for f in (0,1))
        if not valid:raise ValueError()
    except (ValueError,TypeError,KeyError):
        _hold(EXPLORE,identity,'date_conflict');return None
    narrative = _narrative(item.get('description'))
    if not narrative:
        _hold(EXPLORE,identity,'description_missing');return None
    link=item.get('url')
    if not event_url(EXPLORE,link):
        _hold(EXPLORE,identity,'event_url_invalid');return None
    labels=[plain(v['name']) for v in (item.get('categories') or []) if isinstance(v,dict) and isinstance(v.get('name'),str)]
    lat,lon=_point(venue)
    row=record(title,start.isoformat(),end.isoformat() if end and end > start else None,name,address,plain(venue.get('city')),link,identity,', '.join(labels),lat,lon,ZONE,retain_until_end=True)
    if row is None:return None
    row.update(description=narrative,timezone=ZONE,publisher_categories=labels,location_provenance='publisher_event_venue')
    picture=item.get('image') if isinstance(item.get('image'),dict) else {}
    candidate=picture.get('url')
    if isinstance(picture.get('width'), (int,float)) and picture['width'] < 600:
        candidate=None
    from roomquest.publisher_evidence import attach
    return attach(row,EXPLORE,candidate=candidate)

def _squarespace(key,item,now):
    if not isinstance(item,dict) or not isinstance(item.get('id'),str):
        raise ValueError('invalid_squarespace_record')
    identity=item['id']
    if item.get('workflowState') != 1 or item.get('cancelled') or item.get('allDay') or item.get('allDayEvent'):
        return None
    title=plain(item.get('title'))
    loc=item.get('location') if isinstance(item.get('location'),dict) else {}
    name=plain(loc.get('addressTitle'))
    if not title or NONPUBLIC.search(title+' '+name):return None
    line2=plain(loc.get('addressLine2'))
    m=re.fullmatch(r'([^,]+),\s*(GA|Georgia)(?:,?\s*(\d{5}))?',line2,re.I)
    address=_street(loc.get('addressLine1'),m[1],m[2],m[3] or '') if m else None
    if not name or not address:
        _hold(key,identity,'street_unverified');return None
    b,e=item.get('startDate'),item.get('endDate')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (b,e)):
        _hold(key,identity,'time_missing');return None
    start,end=timestamp(b),timestamp(e)
    if end < start:
        _hold(key,identity,'end_conflict');return None
    if not now-timedelta(hours=24)<=start<=now+timedelta(days=WINDOW_DAYS):
        return None
    narrative=_narrative(item.get('body')) or _narrative(item.get('excerpt'))
    if not narrative:
        _hold(key,identity,'description_missing');return None
    link=urljoin(SOURCES[key][0],item.get('fullUrl') or '')
    if not event_url(key,link):
        _hold(key,identity,'event_url_invalid');return None
    lat,lon=_point(loc)
    labels=[plain(x) for x in item.get('categories') or [] if isinstance(x,str)]
    row=record(title,start.isoformat(),end.isoformat(),name,address,m[1],link,identity,', '.join(labels),lat,lon,ZONE,retain_until_end=True)
    if row is None:return None
    row.update(description=narrative,timezone=ZONE,publisher_categories=labels,location_provenance='publisher_event_venue')
    from roomquest.publisher_evidence import attach
    return attach(row,key,candidate=item.get('assetUrl'))

def collect(source, fetch, *, deadline_at=None, now=None):
    key=source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'),source.get('kind'),source.get('platform_adapter')) != SOURCES[key] or source.get('timezone') != ZONE:
        raise ValueError('unregistered_gainesville_source')
    now=now or datetime.now(timezone.utc)
    deadline=min(monotonic()+38,deadline_at or float('inf'))
    rows={}
    if key == EXPLORE:
        current=now.astimezone(ZoneInfo(ZONE))
        query={'per_page':50,'start_date':current.date().isoformat(),'end_date':(current+timedelta(days=WINDOW_DAYS)).date().isoformat()}
        for page in range(1,5):
            if monotonic() >= deadline:raise ValueError('collection_deadline')
            payload=json.loads(fetch(SOURCES[key][0]+'?'+urlencode(dict(query,page=page)),'application/json'))
            if not isinstance(payload,dict) or not isinstance(payload.get('events'),list):
                raise ValueError('invalid_wordpress_payload')
            total=payload.get('total_pages',1)
            if type(total) is not int or total<1 or total>4 or len(payload['events'])>100:
                raise ValueError('pagination_limit')
            for item in payload['events']:
                row=_wordpress(item)
                if row is not None:rows[(row['id'],row['starts_at'])]=row
            if page >= total:break
    else:
        payload=json.loads(fetch(SOURCES[key][0],'application/json'))
        if not isinstance(payload,dict) or not isinstance(payload.get('upcoming'),list):
            raise ValueError('invalid_squarespace_payload')
        if (payload.get('website') or {}).get('timeZone') != ZONE:
            raise ValueError('publisher_timezone_changed')
        from roomquest.squarespace import check_pagination
        check_pagination(payload,upcoming=True)
        for item in payload['upcoming']:
            row=_squarespace(key,item,now)
            if row is not None:rows[(row['id'],row['starts_at'])]=row
    if len(rows)>MAX_RECORDS:raise ValueError('source_record_limit')
    return sorted(rows.values(),key=lambda e:(e['starts_at'],e['title'],e['id']))
