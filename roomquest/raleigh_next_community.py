"""Dose Yoga's complete public Raleigh event calendar, with bounded checkpoints.

Native event pages supply dates, prose and named venues. Exact publisher/landlord
street bindings supply the three reviewed venues; they never supply map points.
Durham-only cards are outside this source's explicitly Raleigh scope.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

SOURCE = 'dose_yoga_raleigh_nc'
ZONE = 'America/New_York'
ORIGIN = 'https://www.doseyogastudios.com'
CALENDAR = ORIGIN + '/events-list'
DOWNTOWN = ORIGIN + '/location/downtown-raleigh'
NORTH_HILLS = ORIGIN + '/location/north-hills'
PLANS = [CALENDAR, DOWNTOWN, NORTH_HILLS]
SOURCES = {SOURCE: (CALENDAR, 'html', 'html')}
LABELS = {SOURCE: 'Dose Yoga — Raleigh Community Events'}
ALLOWED_HOSTS = {SOURCE: ('www.doseyogastudios.com',)}
CHECKPOINT_KEYS = {SOURCE}
CHECKPOINT_MANIFEST_LIMITS = {SOURCE: 100}
CHECKPOINT_EVENT_LIMITS = {SOURCE: 300}
MAX_BYTES = 850000
PREFIX = 'raleigh_dose_'
HOLD_CODES = {PREFIX + s for s in ('outside_window', 'outside_scope', 'not_public',
    'schedule_unresolved', 'street_unresolved', 'description_missing')}
ERROR_CODES = HOLD_CODES | {PREFIX + s for s in ('source_unregistered', 'calendar_changed',
    'detail_identity', 'description_limit', 'manifest_limit', 'record_limit',
    'checkpoint_invalid', 'checkpoint_size_limit')}
ERROR_CODES |= {'collection_deadline', 'publisher_checkpoint_required'}

VENUES = {
    'Dose Downtown Raleigh': ('Dose Downtown Raleigh', '415 N Harrington St, Raleigh, NC 27603',
        'publisher_venue_street_pending_geocode', DOWNTOWN),
    'Dose North Hills Raleigh, 540 St. Albans': ('Dose North Hills Raleigh',
        '540 St. Albans Drive Suite 100, Raleigh, NC 27609',
        'reviewed_publisher_street_pending_geocode', 'https://www.visitnorthhills.com/directory/dose-yoga'),
    'Sixty Vines, North Hills': ('Sixty Vines, North Hills',
        '4000 Center at North Hills Street Suite 110, Raleigh, NC 27609',
        'reviewed_publisher_street_pending_geocode', 'https://www.sixtyvines.com/locations/raleigh-nc'),
}
VENUE_PAGES = {
    DOWNTOWN: ('Downtown Raleigh', '415 N Harrington St, Raleigh, NC 27603'),
    NORTH_HILLS: ('North Hills Raleigh', '540 St. Albans, Suite 100, Raleigh, NC 27609'),
}
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS = {datetime(2000, n, 1).strftime('%B'): n for n in range(1, 13)}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def _window(anchor):
    first = anchor.astimezone(ZoneInfo(ZONE)).date()
    return first, first + timedelta(days=60)


def _source(source):
    if (source.get('source_key') != SOURCE or (source.get('feed_url'), source.get('kind'),
        source.get('platform_adapter'), source.get('timezone')) != (*SOURCES[SOURCE], ZONE)):
        raise ValueError(PREFIX + 'source_unregistered')


def event_url(key, value):
    return key == SOURCE and isinstance(value, str) and bool(re.fullmatch(
        r'https://www[.]doseyogastudios[.]com/events/[a-z0-9]+(?:-[a-z0-9]+)*', value))


def photo_url(value):
    if not isinstance(value, str) or re.search(r'(?:%2e|%2f|%5c|\.\.)', value, re.I):
        return None
    return value if re.fullmatch(r'https://cdn[.]prod[.]website-files[.]com/'
        r'6a6cc6aad2c72a2f2cf13480/[A-Za-z0-9._% -]+[.](?:png|jpg|jpeg|webp)', value, re.I) else None


def _day(value):
    value = plain(value)
    try:
        day = datetime.strptime(value, '%A, %B %d, %Y').date()
    except ValueError:
        raise ValueError(PREFIX + 'schedule_unresolved') from None
    if not value.startswith(day.strftime('%A,')):
        raise ValueError(PREFIX + 'schedule_unresolved')
    return day


def _clock(value):
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', plain(value), re.I)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return time(int(match[1]) % 12 + (12 if match[3].lower() == 'pm' else 0), int(match[2] or 0))


def _listing_span(label):
    try:
        if re.fullmatch(r'Every (?:' + '|'.join(WEEKDAYS) + r')(?: Morning)?', label):
            return None
        pieces = re.split(r'\s+[–—-]\s+', label)
        if len(pieces) == 1:
            return _day(label), _day(label)
        if len(pieces) == 2 and re.search(r', 20\d{2}$', pieces[1]):
            left = pieces[0] if re.search(r', 20\d{2}$', pieces[0]) else pieces[0] + pieces[1][-6:]
            first, last = _day(left), _day(pieces[1])
            if last >= first:
                return first, last
    except ValueError:
        pass
    return None


def _listing(payload, anchor):
    soup = BeautifulSoup(payload, 'html.parser')
    headings = soup.select('h1.class-visual-name')
    lists = soup.select('.w-dyn-items')
    if (len(headings) != 1 or plain(headings[0].get_text()) != 'Events'
        or soup.select('[class*="pagination"]') or len(lists) != 1):
        raise ValueError(PREFIX + 'calendar_changed')
    cards = lists[0].find_all(class_='w-dyn-item', recursive=False)
    if not cards or len(cards) > 100:
        raise ValueError(PREFIX + ('manifest_limit' if cards else 'calendar_changed'))
    first, end = _window(anchor)
    queue, excluded, seen = [], [], set()
    for card in cards:
        links = card.select('a[href]')
        titles = card.select('h3.journal-card-title')
        meta = card.select('.journal-meta-row .journal-meta-item')
        if len(links) != 1 or len(titles) != 1 or len(meta) != 3:
            raise ValueError(PREFIX + 'calendar_changed')
        url = urljoin(CALENDAR, links[0]['href'])
        title = plain(titles[0].get_text(' ', strip=True))
        if not event_url(SOURCE, url) or url in seen or not 0 < len(title) <= 180:
            raise ValueError(PREFIX + 'calendar_changed')
        seen.add(url)
        label, bullet, clock = [plain(n.get_text(' ', strip=True)) for n in meta]
        if bullet != '•':
            raise ValueError(PREFIX + 'calendar_changed')
        item = {'id':url.rsplit('/',1)[-1], 'url':url, 'title':title, 'label':label, 'clock':clock}
        span = _listing_span(label)
        if re.search(r'\bDurham\b', title, re.I) and not re.search(r'\bRaleigh\b', title, re.I):
            excluded.append(dict(item, reason='outside_scope'))
        elif span and (span[1] < first or span[0] >= end):
            excluded.append(dict(item, reason='outside_window'))
        else:
            queue.append(item)
    return queue, excluded, len(cards)


def _venue_page(payload, url):
    soup = BeautifulSoup(payload, 'html.parser')
    headings = soup.select('h1.class-visual-name')
    addresses = soup.select('.class-visual-bottom .class-visual-tagline')
    expected = VENUE_PAGES[url]
    if len(headings) != 1 or len(addresses) != 1 or (
        plain(headings[0].get_text(' ', strip=True)), plain(addresses[0].get_text(' ', strip=True))) != expected:
        raise ValueError(PREFIX + 'street_unresolved')
    return {'title':expected[0], 'address':expected[1]}


def _body(content):
    rich = content.select('.class-description.w-richtext')
    if not rich or not any(len(plain(n.get_text(' ', strip=True))) >= 40 for n in rich):
        raise ValueError(PREFIX + 'description_missing')
    node = BeautifulSoup(str(content), 'html.parser')
    for n in node.select('.journal-meta-row, .class-content-bottom, .w-dyn-bind-empty'):
        n.decompose()
    for n in node.select('.class-content-eyebrow'):
        following = n.find_next_sibling()
        if following is None or not plain(following.get_text(' ', strip=True)):
            n.decompose()
    body = description(str(node), limit=12001)
    if len(body) > 12000:
        raise ValueError(PREFIX + 'description_limit')
    if len(body) < 40:
        raise ValueError(PREFIX + 'description_missing')
    return body


def _exceptions(content, anchor):
    """Only explicit named month/day exception lists; unknown wording is held."""
    first, end = _window(anchor)
    marker = re.compile(r'\b(?:no walk(?: club)?|not meeting|cancell?ed|closed|skipping|except|rescheduled|relocated|moved)\b', re.I)
    prefix = re.compile(r'^(?:No walk(?: club)?|(?:Walk(?: club)? )?cancell?ed|Closed|Not meeting|Skipping|Except)(?: on)?\s+', re.I)
    date_pattern = re.compile(r'(?:(?P<weekday>'+'|'.join(WEEKDAYS)+r'),?\s+)?(?P<month>'
        +'|'.join(MONTHS)+r')\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>20\d{2}))?', re.I)
    excluded = set()
    for node in content.select('.w-richtext p, .w-richtext li'):
        text = plain(node.get_text(' ', strip=True))
        if not marker.search(text):
            continue
        # A mixed or conditional paragraph must not silently become a closure.
        lead = prefix.match(text)
        if not lead:
            raise ValueError(PREFIX + 'schedule_unresolved')
        value = text[lead.end():].rstrip('. ')
        matches = list(date_pattern.finditer(value))
        residual = date_pattern.sub('', value)
        if not matches or re.sub(r'\b(?:and)\b|[,/&\s]', '', residual, flags=re.I):
            raise ValueError(PREFIX + 'schedule_unresolved')
        for match in matches:
            month = MONTHS[match['month'].title()]
            year = int(match['year']) if match['year'] else first.year + int(end.year > first.year and month < first.month)
            try:
                day = date(year,month,int(match['day']))
            except ValueError:
                raise ValueError(PREFIX + 'schedule_unresolved') from None
            if match['weekday'] and day.strftime('%A').lower() != match['weekday'].lower():
                raise ValueError(PREFIX + 'schedule_unresolved')
            excluded.add(day)
    return excluded


def _spans(item, event, content, anchor, label, clock):
    if (label,clock) != (item['label'],item['clock']):
        raise ValueError(PREFIX + 'schedule_unresolved')
    weekly = re.fullmatch(r'Every ('+'|'.join(WEEKDAYS)+r')(?: Morning)?', label)
    first, stop = _window(anchor)
    if weekly:
        if clock:
            raise ValueError(PREFIX + 'schedule_unresolved')
        text = plain(content.get_text(' ', strip=True))
        starts = re.findall(r'\bStart at (\d{1,2}(?::\d{2})?\s*(?:am|pm))\b', text, re.I)
        ends = re.findall(r'\bcafé hang until (\d{1,2}(?::\d{2})?\s*(?:am|pm))\b', text, re.I)
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError(PREFIX + 'schedule_unresolved')
        opens, closes = _clock(starts[0]), _clock(ends[0])
        if not time(5) <= opens < closes <= time(23):
            raise ValueError(PREFIX + 'schedule_unresolved')
        not_before = None
        if event.get('startDate'):
            native = timestamp(event['startDate'],ZONE).astimezone(ZoneInfo(ZONE))
            if native.weekday()!=WEEKDAYS.index(weekly[1]) or native.time()!=opens:
                raise ValueError(PREFIX + 'schedule_unresolved')
            not_before = native.date()
        beginnings = re.findall(r'\bStarting ('+'|'.join(MONTHS)+r') (\d{1,2})(?:st|nd|rd|th)?(?:,? (20\d{2}))?',text,re.I)
        if re.search(r'\b(?:starting|begins on|first walk)\b',text,re.I):
            if len(beginnings)!=1:
                raise ValueError(PREFIX+'schedule_unresolved')
            month,number,year=beginnings[0]
            years=[int(year)] if year else [first.year-1,first.year,first.year+1]
            candidates=[]
            for proposed_year in years:
                try: day=date(proposed_year,MONTHS[month.title()],int(number))
                except ValueError: continue
                if day.weekday()==WEEKDAYS.index(weekly[1]): candidates.append(day)
            if len(candidates)!=1 or (not_before is not None and candidates[0]!=not_before):
                raise ValueError(PREFIX+'schedule_unresolved')
            not_before=candidates[0]
        exceptions = _exceptions(content,anchor)
        spans=[]
        for n in range(60):
            day=first+timedelta(days=n)
            if day.weekday()==WEEKDAYS.index(weekly[1]) and day not in exceptions and (not_before is None or day>=not_before):
                spans.append((datetime.combine(day,opens,ZoneInfo(ZONE)),datetime.combine(day,closes,ZoneInfo(ZONE))))
        return spans
    day, wall = _day(label), _clock(clock)
    native=timestamp(event.get('startDate'),ZONE)
    if native is None:
        raise ValueError(PREFIX + 'schedule_unresolved')
    local=native.astimezone(ZoneInfo(ZONE))
    if local.date()!=day or local.time()!=wall:
        raise ValueError(PREFIX + 'schedule_unresolved')
    end=timestamp(event.get('endDate'),ZONE)
    if end and not native < end <= native+timedelta(hours=24):
        raise ValueError(PREFIX + 'schedule_unresolved')
    return [(native,end)] if first <= day < stop else []


def _detail(item, payload, anchor):
    soup=BeautifulSoup(payload,'html.parser')
    events=[]
    for script in soup.find_all('script',type='application/ld+json'):
        try:
            data=json.loads(script.get_text())
        except (ValueError,TypeError):
            raise ValueError(PREFIX+'detail_identity') from None
        nodes=data if isinstance(data,list) else data.get('@graph',[data]) if isinstance(data,dict) else []
        events.extend(n for n in nodes if isinstance(n,dict) and n.get('@type')=='Event')
    titles=soup.select('h1.class-visual-name')
    contents=soup.select('.event-content-col')
    if len(events)!=1 or len(titles)!=1 or len(contents)!=1:
        raise ValueError(PREFIX+'detail_identity')
    event,content=events[0],contents[0]
    if (plain(event.get('name'))!=item['title'] or plain(titles[0].get_text(' ',strip=True))!=item['title']
        or urljoin(CALENDAR,event.get('url',''))!=item['url']):
        raise ValueError(PREFIX+'detail_identity')
    if not str(event.get('eventStatus','')).endswith('/EventScheduled') or not str(event.get('eventAttendanceMode','')).endswith('/OfflineEventAttendanceMode'):
        raise ValueError(PREFIX+'not_public')
    meta=content.select('.journal-meta-row .journal-meta-item')
    if len(meta)!=5:
        raise ValueError(PREFIX+'schedule_unresolved')
    label,bullet,clock,bullet2,place=[plain(n.get_text(' ',strip=True)) for n in meta]
    if (bullet,bullet2)!=('•','•') or not isinstance(event.get('location'),dict) or plain(event['location'].get('name'))!=place:
        raise ValueError(PREFIX+'detail_identity')
    if re.search(r'\b(?:moved|relocated|new location)\b',content.get_text(' ',strip=True),re.I):
        raise ValueError(PREFIX+'street_unresolved')
    if place not in VENUES:
        raise ValueError(PREFIX+'street_unresolved')
    venue,street,provenance,evidence=VENUES[place]
    body=_body(content)
    spans=_spans(item,event,content,anchor,label,clock)
    lat=lng=None
    geo=event['location'].get('geo')
    if geo:
        try:
            if not isinstance(geo,dict) or isinstance(geo.get('latitude'),bool) or isinstance(geo.get('longitude'),bool):
                raise ValueError
            lat,lng=float(geo['latitude']),float(geo['longitude'])
            if not 33.7 <= lat <= 36.7 or not -84.4 <= lng <= -75.3:
                raise ValueError
        except (ValueError,TypeError,KeyError):
            raise ValueError(PREFIX+'street_unresolved') from None
        provenance,evidence='publisher_event_geo',item['url']
    photo=photo_url(event.get('image'))
    rows=[]
    for start,end in spans:
        if (end or start+timedelta(hours=3))<=anchor:
            continue
        identity='raleigh-dose:'+sha256(f'{item["id"]}|{start.astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()
        row=record(item['title'],start.isoformat(),end.isoformat() if end else None,
            venue,street,'Raleigh',item['url'],identity,lat=lat,lng=lng,tz=ZONE,retain_until_end=True)
        if row:
            row.update(description=body,timezone=ZONE,attendance_mode='in_person',
                location_provenance=provenance,location_evidence_url=evidence)
            if photo:
                row['image_url']=photo
            rows.append(row)
    return rows


def _seal(state):
    state['manifest_count']=len(state['queue'])
    state['manifest_hash']=_hash(state['queue'])
    state['state_hash']=_hash({k:v for k,v in state.items() if k!='state_hash'})
    if len(state['events'])>300:
        raise ValueError(PREFIX+'record_limit')
    if len(json.dumps(state,ensure_ascii=False).encode())>MAX_BYTES:
        raise ValueError(PREFIX+'checkpoint_size_limit')


def checkpoint_complete(state):
    try:
        return (state.get('source_key')==SOURCE and state.get('listing_complete') is True
            and state.get('pending_pages')==[] and state.get('listed_pages')==PLANS
            and set(state.get('venue_proof',{}))==set(VENUE_PAGES)
            and state['cursor']==state['manifest_count']==len(state['queue'])==len(state['outcomes'])
            and state['listing_total']==len(state['queue'])+state['outside_scope_count']+state['outside_window_count'])
    except (KeyError,TypeError,AttributeError):
        return False


def _checkpoint(value,current):
    if value is None:
        return None
    try:
        anchor=timestamp(value['started_at'])
        n=len(value['listed_pages'])
        valid=(type(value['version']) is int and value['version']==1 and value['source_key']==SOURCE
            and anchor.utcoffset()==timedelta(0) and anchor<=current+timedelta(seconds=60)
            and value['window_start']==_window(anchor)[0].isoformat()
            and value['listed_pages']==PLANS[:n] and value['pending_pages']==PLANS[n:] and 0<=n<=3
            and value['listing_complete'] is (not value['pending_pages'])
            and isinstance(value['queue'],list) and len(value['queue'])<=100
            and type(value['manifest_count']) is int and value['manifest_count']==len(value['queue'])
            and value['manifest_hash']==_hash(value['queue'])
            and type(value['cursor']) is int and 0<=value['cursor']<=len(value['queue'])
            and len(value['outcomes'])==value['cursor'] and len(value['events'])<=300
            and (value['listing_complete'] or value['cursor']==0 and value['events']==[])
            and value['state_hash']==_hash({k:v for k,v in value.items() if k!='state_hash'})
            and len(json.dumps(value,ensure_ascii=False).encode())<=MAX_BYTES
            and type(value['listing_total']) is int and 0<=value['listing_total']<=100
            and type(value['outside_scope_count']) is int and type(value['outside_window_count']) is int
            and value['listing_total']==len(value['queue'])+len(value['listing_exclusions'])
            and value['outside_scope_count']==sum(x['reason']=='outside_scope' for x in value['listing_exclusions'])
            and value['outside_window_count']==sum(x['reason']=='outside_window' for x in value['listing_exclusions']))
        seen=set()
        for item in value['queue']+value['listing_exclusions']:
            valid=(valid and event_url(SOURCE,item['url']) and item['url'].endswith('/'+item['id'])
                and item['id'] not in seen and isinstance(item['title'],str) and 0<len(item['title'])<=180
                and isinstance(item['label'],str) and len(item['label'])<=160
                and isinstance(item['clock'],str) and len(item['clock'])<=40)
            seen.add(item['id'])
        valid=valid and set(value['venue_proof'])==set(PLANS[1:n])
        for url,proof in value['venue_proof'].items():
            valid=valid and proof=={'title':VENUE_PAGES[url][0],'address':VENUE_PAGES[url][1]}
        proofs,diagnostics={},[]
        for item,outcome in zip(value['queue'],value['outcomes']):
            valid=valid and outcome['item_hash']==_hash(item)
            if outcome['reason']:
                valid=valid and outcome['reason'] in HOLD_CODES and outcome['rows']==[]
                diagnostics.append({'id':item['id'],'event_url':item['url'],'disposition':'held','reason':outcome['reason']})
            else:
                for proof in outcome['rows']:
                    valid=valid and proof['id'] not in proofs
                    proofs[proof['id']]={'hash':proof['hash'],'url':item['url'],'title':item['title']}
        valid=valid and value['diagnostics']==diagnostics and len(proofs)==len(value['events'])
        first,end=_window(anchor)
        for row in value['events']:
            proof=proofs.get(row['id'],{})
            start=timestamp(row['starts_at'])
            expected_id='raleigh-dose:'+sha256(f'{row["event_url"].rsplit("/",1)[-1]}|{start.astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()
            valid=(valid and proof.get('hash')==_hash(row) and proof.get('url')==row['event_url']
                and proof.get('title')==row['title'] and row['id']==expected_id and event_url(SOURCE,row['event_url'])
                and (row['venue_name'],row['venue_address']) in {(x[0],x[1]) for x in VENUES.values()}
                and row['venue_city']=='Raleigh' and row['timezone']==ZONE
                and isinstance(row['description'],str) and 40<=len(row['description'])<=12000
                and first<=timestamp(row['starts_at']).astimezone(ZoneInfo(ZONE)).date()<end
                and (not row.get('ends_at') or timestamp(row['ends_at'])>timestamp(row['starts_at']))
                and (not row.get('image_url') or photo_url(row['image_url'])==row['image_url']))
            if row.get('lat') is None and row.get('lng') is None:
                matches=[v for v in VENUES.values() if (v[0],v[1])==(row['venue_name'],row['venue_address'])]
                valid=valid and len(matches)==1 and (row.get('location_provenance'),row.get('location_evidence_url'))==matches[0][2:]
            else:
                valid=(valid and type(row.get('lat')) in (int,float) and type(row.get('lng')) in (int,float)
                    and 33.7<=row['lat']<=36.7 and -84.4<=row['lng']<=-75.3
                    and row.get('location_provenance')=='publisher_event_geo' and row.get('location_evidence_url')==row['event_url'])
        if not valid:
            raise ValueError
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError):
        raise ValueError(PREFIX+'checkpoint_invalid') from None
    return None if current-anchor>timedelta(hours=4) else deepcopy(value)


def collect_chunk(source,fetch,*,checkpoint=None,deadline_at=None,now=None,max_fetches=3):
    _source(source)
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None or type(max_fetches) is not int or not 1<=max_fetches<=3:
        raise ValueError(PREFIX+'checkpoint_invalid')
    current=current.astimezone(timezone.utc)
    state=_checkpoint(checkpoint,current)
    if state is None:
        state={'version':1,'source_key':SOURCE,'started_at':current.isoformat(),
            'window_start':_window(current)[0].isoformat(),'pending_pages':PLANS.copy(),'listed_pages':[],
            'listing_complete':False,'queue':[],'listing_exclusions':[],'listing_total':0,
            'outside_scope_count':0,'outside_window_count':0,'venue_proof':{},
            'manifest_count':0,'manifest_hash':_hash([]),'cursor':0,'events':[],'diagnostics':[],'outcomes':[]}
    if checkpoint_complete(state):
        return {'complete':True,'events':deepcopy(state['events']),'checkpoint':state}
    anchor=timestamp(state['started_at'])
    fetched,before=0,(len(state['listed_pages']),state['cursor'])
    while fetched<max_fetches and (deadline_at is None or monotonic()+12<deadline_at):
        if state['pending_pages']:
            url=state['pending_pages'][0]
            payload=fetch(url,'text/html');fetched+=1
            if url==CALENDAR:
                state['queue'],state['listing_exclusions'],state['listing_total']=_listing(payload,anchor)
                state['outside_scope_count']=sum(x['reason']=='outside_scope' for x in state['listing_exclusions'])
                state['outside_window_count']=sum(x['reason']=='outside_window' for x in state['listing_exclusions'])
            else:
                state['venue_proof'][url]=_venue_page(payload,url)
            state['listed_pages'].append(url);state['pending_pages'].pop(0)
            state['listing_complete']=not state['pending_pages']
            continue
        if state['cursor']==len(state['queue']):
            break
        item=state['queue'][state['cursor']]
        reason,rows=None,[]
        try:
            payload=fetch(item['url'],'text/html');fetched+=1
            rows=_detail(item,payload,anchor)
            if not rows:
                reason=PREFIX+'outside_window'
        except ValueError as exc:
            if str(exc) not in HOLD_CODES:
                raise
            reason=str(exc)
        if reason:
            state['diagnostics'].append({'id':item['id'],'event_url':item['url'],'disposition':'held','reason':reason})
        state['events'].extend(rows)
        state['outcomes'].append({'item_hash':_hash(item),'reason':reason,
            'rows':[{'id':row['id'],'hash':_hash(row)} for row in rows]})
        state['cursor']+=1
    if before==(len(state['listed_pages']),state['cursor']):
        raise ValueError('collection_deadline')
    _seal(state)
    complete=checkpoint_complete(state)
    return {'complete':complete,'events':deepcopy(state['events']) if complete else [],'checkpoint':state}


def collect(source,fetch,*,deadline_at=None,now=None):
    result=collect_chunk(source,fetch,deadline_at=deadline_at,now=now)
    if not result['complete']:
        raise ValueError('publisher_checkpoint_required')
    return result['events']
