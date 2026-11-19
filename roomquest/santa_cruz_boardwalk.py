"""Santa Cruz Beach Boardwalk first-party Grove event schedule.

Select only full, individually dated original listings with their own event
details, not year-round admission offers or synthetic Winter Wonderland days.
All street evidence must match the Boardwalk's original Grove venue page.
"""
from __future__ import annotations
import re
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record

KEY='santa_cruz_beach_boardwalk_events_ca'
URL='https://beachboardwalk.com/events-and-entertainment/'
DETAIL='https://beachboardwalk.com/brunch-with-santa/'
GROVE='https://beachboardwalk.com/groups/the-grove/'
ZONE='America/Los_Angeles'
ADDRESS='400 Beach Street, Santa Cruz, CA 95060'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('beachboardwalk.com',)}
MAX_RECORDS=1
MAX_DESCRIPTION=12000
SCHEDULE=re.compile(r'Sunday,\s+December\s+13,\s+2026\s+9am\s*[-–]\s*11:30am',re.I)
SOLD_OUT=re.compile(r'\b(?:sold\s*out|cancelled|canceled|postponed)\b',re.I)

def event_url(value):
    return value==DETAIL

def _soup(payload):
    if not isinstance(payload,str) or len(payload)>1_000_000:
        raise ValueError('boardwalk_invalid_html')
    doc=BeautifulSoup(payload,'html.parser')
    if not doc.body:raise ValueError('boardwalk_invalid_html')
    return doc

def collect(source,fetch,*,deadline_at=None,now=None):
    if (source.get('source_key')!=KEY or
        (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY] or
        source.get('timezone')!=ZONE):
        raise ValueError('boardwalk_unregistered_source')
    listing=_soup(fetch(URL,'text/html'))
    card=None
    for article in listing.select('article.mec-event-article'):
        heading=article.find('h3')
        if heading and heading.get_text(' ',strip=True)=='Brunch with Santa':
            if card is not None:raise ValueError('boardwalk_duplicate_event')
            card=article
    if card is None:return []
    content=card.get_text(' ',strip=True)
    if not SCHEDULE.search(content):raise ValueError('boardwalk_date_or_clock_changed')
    if SOLD_OUT.search(content):return []
    links=[a.get('href') for a in card.select('a[href]') if a.get_text(' ',strip=True)=='More Info']
    if links!=[DETAIL]:raise ValueError('boardwalk_detail_identity_changed')
    start=datetime(2026,12,13,9,tzinfo=ZoneInfo(ZONE))
    end=datetime(2026,12,13,11,30,tzinfo=ZoneInfo(ZONE))
    now=now or datetime.now(timezone.utc)
    if start.astimezone(timezone.utc)<now-timedelta(hours=3) or start.astimezone(timezone.utc)>now+timedelta(days=60):
        return []
    detail=_soup(fetch(DETAIL,'text/html')).body.get_text(' ',strip=True)
    a=detail.find('Brunch with Santa')
    b=detail.find('Boardwalk Holiday Events',a)
    if a<0 or b<a or b-a>MAX_DESCRIPTION+500:
        raise ValueError('boardwalk_detail_format_changed')
    narrative=detail[a:b].strip()
    if ('Sunday, December 13, 2026' not in narrative or
        not re.search(r'\b9am\b',narrative,re.I) or
        'The Grove: Santa Cruz Event Center' not in narrative.replace('\xa0',' ') or
        'Schedule:' not in narrative or len(narrative)<200):
        raise ValueError('boardwalk_detail_missing')
    if SOLD_OUT.search(narrative):return []
    venue=_soup(fetch(GROVE,'text/html')).body.get_text(' ',strip=True).replace('\xa0',' ')
    if ('The Grove: Santa Cruz Event Center' not in venue or
        not re.search(r'400\s+Beach\s+Street\s*Santa\s+Cruz,\s*CA\s*95060',venue,re.I)):
        raise ValueError('boardwalk_venue_street_changed')
    row=record('Brunch with Santa',start.isoformat(),end.isoformat(),
               'The Grove: Santa Cruz Event Center',ADDRESS,'Santa Cruz',
               DETAIL,'brunch-with-santa-2026-12-13',
               'Holiday Brunch, Family Event',None,None,ZONE,retain_until_end=True)
    if row is None:return []
    row.update(description=narrative,timezone=ZONE,
               publisher_categories=['Holiday Brunch','Family Event'],
               location_provenance='boardwalk_official_grove_venue_street',
               location_evidence_url=GROVE)
    from roomquest.publisher_evidence import attach
    return [attach(row,KEY)]
