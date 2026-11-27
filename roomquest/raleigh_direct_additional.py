"""Tin Roof's exact public Gigwell calendar, with complete native narratives.

The widget's public settings and API are read through injected guarded GETs.
Fortnight was inspected separately and is held: its calendars omit event prose.
"""
from __future__ import annotations

from roomquest.collection_window import calendar_anchor
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
TIN_ROOF = 'tin_roof_raleigh_nc'
SOURCES = {TIN_ROOF: ('https://tinroofraleigh.com/calendar/', 'html', 'html')}
LABELS = {TIN_ROOF: 'Tin Roof Raleigh'}
VENUES = {TIN_ROOF: ('Tin Roof Raleigh', '300 Glenwood Ave, Raleigh, NC 27603', 'Raleigh')}
ALLOWED_HOSTS = {TIN_ROOF: ('tinroofraleigh.com', 'api.gigwell.com')}
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {TIN_ROOF: 200}
CHECKPOINT_EVENT_LIMITS = {TIN_ROOF: 500}
SETTINGS_URL = 'https://api.gigwell.com/api/agency/315632/booknow/presets/gigstreamSettings'
GIGS_API = 'https://api.gigwell.com/api/gigs'
MAX_BYTES = 850000
PREFIX = 'raleigh_additional_'
PROVENANCE = 'reviewed_publisher_street_pending_geocode'
HOLD_CODES = {PREFIX+s for s in ('description_missing', 'schedule_unresolved', 'street_unresolved',
                                'outside_window', 'not_public')}
ERROR_CODES = HOLD_CODES | {PREFIX+s for s in ('source_unregistered', 'calendar_changed', 'identity_changed',
    'description_limit', 'manifest_limit', 'checkpoint_invalid', 'checkpoint_size_limit')}
ERROR_CODES |= {'collection_deadline', 'publisher_checkpoint_required'}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _source(source):
    if (source.get('source_key') != TIN_ROOF
            or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'), source.get('timezone'))
            != (*SOURCES[TIN_ROOF], ZONE)):
        raise ValueError(PREFIX+'source_unregistered')
    return TIN_ROOF


def event_url(key, value):
    return key == TIN_ROOF and value == SOURCES[TIN_ROOF][0]


def photo_url(value):
    if not isinstance(value, str) or len(value) > 1500 or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I):
        return None
    try:
        p = urlsplit(value)
        return value if (p.scheme == 'https' and not p.query and not p.fragment and not p.username and not p.password
            and re.fullmatch(r'resources\d*[.]gigwell[.]com',p.netloc)
            and re.fullmatch(r'/prod/\d+/images/[^/]+',p.path)) else None
    except ValueError:
        return None


def _body(value):
    text = description(value, limit=12001)
    if len(text) > 12000:
        raise ValueError(PREFIX+'description_limit')
    if not text or not re.search(r'[A-Za-z]{2}',text):
        raise ValueError(PREFIX+'description_missing')
    return text


def _plans(anchor):
    first = calendar_anchor(anchor).astimezone(ZoneInfo(ZONE)).date()
    end = first + timedelta(days=60)
    def utc(day):
        return datetime.combine(day,time(),ZoneInfo(ZONE)).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    query = urlencode(dict(startDate=utc(first),endDate=utc(end),artists='',venues='',agencies='315647',limit='1000',direction='ASC'))
    return [SOURCES[TIN_ROOF][0],SETTINGS_URL,GIGS_API+'?'+query]


def _json(payload):
    try:
        return json.loads(payload)
    except (ValueError,TypeError):
        raise ValueError(PREFIX+'calendar_changed') from None


def _calendar(payload):
    soup = BeautifulSoup(payload,'html.parser')
    canonical = soup.select('link[rel="canonical"]')
    widgets = soup.select('main gigwell-gigstream')
    if (len(canonical) != 1 or canonical[0].get('href') != SOURCES[TIN_ROOF][0] or len(widgets) != 1
            or {k:widgets[0].get(k) for k in ('agency','identity-id','settings')} !=
               {'agency':'315647','identity-id':'315632','settings':'b8txja'}
            or widgets[0].get('token') or widgets[0].get('callback') or widgets[0].get('venues') or widgets[0].get('artists')
            or not soup.select_one('script[src="https://connect.gigwell.com/gigstream/gigstream.js"]')):
        raise ValueError(PREFIX+'calendar_changed')
    footer = soup.select_one('footer')
    if not footer or not re.search(r'300 Glenwood Ave\s+Raleigh, NC 27603\b',plain(footer.get_text(' ',strip=True))):
        raise ValueError(PREFIX+'street_unresolved')


def _settings(payload):
    data = _json(payload)
    try:
        options = data['data']['gigstreamSettings']['options']
        selected = [value['value'] for value in options if value['id']=='b8txja']
        if len(selected) != 1:
            raise ValueError
        config = selected[0]
        if config['filter'] != {'range':'custom','customRangeStart':{'relative':'before','unit':'weeks','value':0},
            'customRangeEnd':{'relative':'after','unit':'months','value':2},'limit':1000,
            'sorting':{'by':'eventDate','direction':'ASC'}}:
            raise ValueError
        fields = config['theme']['fields']
        if len([v for v in fields if v.get('path')=='description' and v.get('enabled') is True]) != 1:
            raise ValueError
    except (ValueError,TypeError,KeyError):
        raise ValueError(PREFIX+'calendar_changed') from None


def _listing(payload):
    data = _json(payload)
    if (not isinstance(data,dict) or not isinstance(data.get('results'),list)
            or type(data.get('hits')) is not int or data['hits'] != len(data['results'])
            or not 0 <= data['hits'] <= 200 or not isinstance(data.get('profiles'),list)):
        raise ValueError(PREFIX+'manifest_limit')
    profile_map = {}
    for profile in data['profiles']:
        if not isinstance(profile,dict) or not re.fullmatch(r'[1-9]\d*',str(profile.get('id',''))):
            raise ValueError(PREFIX+'calendar_changed')
        identity = str(profile['id'])
        if identity in profile_map:
            raise ValueError(PREFIX+'calendar_changed')
        profile_map[identity] = photo_url(profile.get('profileImageUrl'))
    rows, ids = [], set()
    for value in data['results']:
        if (not isinstance(value,dict) or not re.fullmatch(r'[1-9]\d*',str(value.get('id','')))
                or str(value['id']) in ids or value.get('agencyEntityIds') != ['315647']
                or str(value.get('venueEntityId')) != '315647' or value.get('venueTitle') != 'Raleigh'):
            raise ValueError(PREFIX+'identity_changed')
        ids.add(str(value['id']))
        fields = ('id','artistTitle','description','startDateTime','endDateTime','localDate','localEndDate',
                  'eventTimeZone','eventAddress','eventCity','eventState','eventZipCode','eventCountry')
        item = {k:value.get(k) for k in fields}
        item['id'] = str(item['id'])
        item['image'] = next((profile_map.get(str(identity)) for identity in value.get('artistEntityIds',[])
                              if profile_map.get(str(identity))),None)
        rows.append(item)
    return rows


def _identity(item,start):
    return 'raleigh-additional:'+sha256(f'{TIN_ROOF}|{item["id"]}|{start.astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()


def _row(item,anchor):
    window_start = calendar_anchor(anchor)
    title = plain(item.get('artistTitle'))
    if not title or len(title)>180:
        raise ValueError(PREFIX+'identity_changed')
    if re.search(r'\b(?:cancelled|canceled|postponed|closed|private (?:event|party))\b',title,re.I):
        raise ValueError(PREFIX+'not_public')
    if item.get('eventTimeZone') != ZONE or not re.search(r'T\d{2}:\d{2}:\d{2}(?:[.]\d+)?(?:Z|[+-]\d{2}:\d{2})$',item.get('startDateTime') or ''):
        raise ValueError(PREFIX+'schedule_unresolved')
    start,end = timestamp(item['startDateTime']),timestamp(item.get('endDateTime'))
    local = start.astimezone(ZoneInfo(ZONE))
    if (item.get('localDate') != local.date().isoformat()
            or end and (end<=start or end-start>timedelta(days=1)
                        or item.get('localEndDate') not in {None,end.astimezone(ZoneInfo(ZONE)).date().isoformat()})):
        raise ValueError(PREFIX+'schedule_unresolved')
    first = window_start.astimezone(ZoneInfo(ZONE)).date()
    if not first <= local.date() < first+timedelta(days=60) or (end or start+timedelta(hours=3))<=window_start:
        raise ValueError(PREFIX+'outside_window')
    if ((item.get('eventCity'),item.get('eventState'),item.get('eventZipCode'),item.get('eventCountry'))
            != ('Raleigh','NC','27603','US') or item.get('eventAddress') not in {None,'','300 Glenwood Ave'}):
        raise ValueError(PREFIX+'street_unresolved')
    body = _body(item.get('description'))
    # startDateTime is the actual time displayed by the native widget. It is
    # often its door-opening field; no performance clock or duration is inferred.
    row = record(title,start.isoformat(),end.isoformat() if end else None,*VENUES[TIN_ROOF],
                 SOURCES[TIN_ROOF][0],_identity(item,start),tz=ZONE,retain_until_end=True)
    if row:
        row.update(description=body,timezone=ZONE,attendance_mode='in_person',location_provenance=PROVENANCE,
                   location_evidence_url=SOURCES[TIN_ROOF][0])
        if item.get('image'):
            row['image_url'] = item['image']
    return row


def _seal(state):
    state['manifest_count'],state['manifest_hash'] = len(state['queue']),_hash(state['queue'])
    state['state_hash'] = _hash({k:v for k,v in state.items() if k!='state_hash'})
    if len(json.dumps(state,ensure_ascii=False).encode())>MAX_BYTES:
        raise ValueError(PREFIX+'checkpoint_size_limit')


def checkpoint_complete(state):
    """Exact completion boundary used by the shared wrapper and SQL contract."""
    return (isinstance(state,dict) and state.get('version')==1 and state.get('source_key')==TIN_ROOF
            and state.get('listing_complete') is True and state.get('pending_pages')==[]
            and isinstance(state.get('queue'),list) and isinstance(state.get('listed_pages'),list)
            and len(state['listed_pages'])==3 and type(state.get('cursor')) is int
            and type(state.get('manifest_count')) is int
            and state['cursor']==state['manifest_count']==len(state['queue']))


def _checkpoint(value,now):
    if value is None:
        return None
    try:
        anchor=timestamp(value['started_at']);plans=_plans(anchor)
        valid=(type(value['version']) is int and value['version']==1 and value['source_key']==TIN_ROOF
            and anchor.utcoffset()==timedelta(0) and anchor<=now+timedelta(seconds=60)
            and value['window_start']==calendar_anchor(anchor).astimezone(ZoneInfo(ZONE)).date().isoformat()
            and isinstance(value['listed_pages'],list) and 1<=len(value['listed_pages'])<=3
            and value['listed_pages']==plans[:len(value['listed_pages'])]
            and value['pending_pages']==plans[len(value['listed_pages']):]
            and value['listing_complete'] is (not value['pending_pages'])
            and isinstance(value['queue'],list) and len(value['queue'])<=200
            and value['manifest_count']==len(value['queue']) and value['manifest_hash']==_hash(value['queue'])
            and type(value['cursor']) is int and 0<=value['cursor']<=len(value['queue'])
            and (value['listing_complete'] or value['cursor']==0 and value['queue']==[] and value['events']==[])
            and value['state_hash']==_hash({k:v for k,v in value.items() if k!='state_hash'})
            and len(value['outcomes'])==value['cursor'] and len(value['events'])<=500
            and len(json.dumps(value,ensure_ascii=False).encode())<=MAX_BYTES)
        proofs,diagnostics={},[]
        for item,outcome in zip(value['queue'],value['outcomes']):
            valid=valid and outcome['item_hash']==_hash(item)
            if outcome['reason']:
                valid=valid and outcome['reason'] in HOLD_CODES and outcome['row'] is None
                diagnostics.append(dict(id=item['id'],event_url=SOURCES[TIN_ROOF][0],disposition='held',reason=outcome['reason']))
            else:
                valid=valid and outcome['row']['id'] not in proofs
                proofs[outcome['row']['id']]=outcome['row']['hash']
        valid=valid and diagnostics==value['diagnostics'] and len(proofs)==len(value['events'])
        for row in value['events']:
            valid=(valid and proofs.get(row['id'])==_hash(row) and event_url(TIN_ROOF,row['event_url'])
                and (row['venue_name'],row['venue_address'],row['venue_city'])==VENUES[TIN_ROOF]
                and row.get('lat') is None and row.get('lng') is None and _body(row['description'])==row['description']
                and row.get('timezone')==ZONE and row.get('location_provenance')==PROVENANCE
                and row.get('location_evidence_url')==SOURCES[TIN_ROOF][0]
                and (not row.get('image_url') or photo_url(row['image_url'])==row['image_url']))
        if not valid:
            raise ValueError
    except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError):
        raise ValueError(PREFIX+'checkpoint_invalid') from None
    if now-anchor>timedelta(hours=4):
        return None
    return deepcopy(value)


def collect_chunk(source,fetch,*,checkpoint=None,deadline_at=None,now=None,max_fetches=3):
    _source(source)
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError(PREFIX+'checkpoint_invalid')
    current=current.astimezone(timezone.utc)
    state=_checkpoint(checkpoint,current)
    if state is None:
        state=dict(version=1,source_key=TIN_ROOF,started_at=current.isoformat(),
            window_start=calendar_anchor(current).astimezone(ZoneInfo(ZONE)).date().isoformat(),queue=[],manifest_count=0,
            manifest_hash=_hash([]),cursor=0,listing_complete=False,pending_pages=_plans(current),listed_pages=[],
            events=[],diagnostics=[],outcomes=[])
    anchor=timestamp(state['started_at'])
    if state['listing_complete'] and state['cursor']==len(state['queue']):
        return dict(complete=True,events=deepcopy(state['events']),checkpoint=state)
    fetched=0;before=len(state['listed_pages'])
    while state['pending_pages'] and fetched<max_fetches and (deadline_at is None or monotonic()+12<deadline_at):
        url=state['pending_pages'][0]
        payload=fetch(url,'text/html' if url==SOURCES[TIN_ROOF][0] else 'application/json');fetched+=1
        if url==SOURCES[TIN_ROOF][0]:_calendar(payload)
        elif url==SETTINGS_URL:_settings(payload)
        else:state['queue']=_listing(payload)
        state['listed_pages'].append(url);state['pending_pages'].pop(0)
    state['listing_complete']=not state['pending_pages']
    if state['listing_complete']:
        while state['cursor']<len(state['queue']):
            item=state['queue'][state['cursor']];row=None;reason=None
            try:
                row=_row(item,anchor)
                if row is None:reason=PREFIX+'outside_window'
            except ValueError as exc:
                if str(exc) not in HOLD_CODES:raise
                reason=str(exc)
            if reason:state['diagnostics'].append(dict(id=item['id'],event_url=SOURCES[TIN_ROOF][0],disposition='held',reason=reason))
            else:state['events'].append(row)
            state['outcomes'].append(dict(item_hash=_hash(item),reason=reason,row=dict(id=row['id'],hash=_hash(row)) if row else None))
            state['cursor']+=1
    if before==len(state['listed_pages']):raise ValueError('collection_deadline')
    _seal(state)
    complete=state['listing_complete'] and state['cursor']==len(state['queue'])
    return dict(complete=complete,events=deepcopy(state['events']) if complete else [],checkpoint=state)


def collect(source,fetch,*,deadline_at=None,now=None):
    result=collect_chunk(source,fetch,deadline_at=deadline_at,now=now)
    if not result['complete']:raise ValueError('publisher_checkpoint_required')
    return result['events']
