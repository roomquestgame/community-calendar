"""Winegrowers Association's own primary upcoming event calendar, Santa Cruz.

The publisher has a multi-venue wine walk. Only its *explicitly numbered*
registration/check-in venue is used as the map anchor; do not pretend other
participating businesses share that street. Other events need independent
venue evidence and are held by exact-event approval.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from roomquest.mapsee_adapter import record, plain
from roomquest.event_description import description

KEY='wines_santa_cruz_mountains_ca'
URL='https://winesofthesantacruzmountains.com/events/'
ZONE='America/Los_Angeles'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('winesofthesantacruzmountains.com',)}
MAX_RECORDS=30
MAX_DESCRIPTION=12000
STROLL='https://winesofthesantacruzmountains.com/events/surfcitystroll/'
STREET='334 Ingalls St Suite A, Santa Cruz, CA 95060'
VENUE='Swift Street Courtyard — Surf City Stroll check-in'
HOST='winesofthesantacruzmountains.com'
NONPUBLIC=re.compile(r'\b(?:cancelled|canceled|postponed|private event|sold out)\b',re.I)
TIME=re.compile(r'^(\d{1,2}):(\d{2})\s*(am|pm)\s*[-–—]\s*(\d{1,2}):(\d{2})\s*(am|pm)$',re.I)
REVIEWED={STROLL:('Surf City Stroll',STREET,VENUE)}

def event_url(value):
    if value not in REVIEWED:return False
    u=urlsplit(value)
    return bool(u.scheme=='https' and u.hostname==HOST and u.port in (None,443)
      and not u.query and not u.fragment and not u.username and not u.password
      and re.fullmatch(r'/events/[a-z0-9]+(?:-[a-z0-9]+)*/',u.path))

def _parse(day,raw):
    try:
        d=datetime.strptime(' '.join(day.split()),'%B %d, %Y').date()
        m=TIME.fullmatch(' '.join(raw.split()))
        if not m:return None
        sh,sm,sa,eh,em,ea=m.groups()
        def dt(h,m,amp):
            hour=int(h)
            if hour not in range(1,13) or int(m)>59:return None
            return datetime(d.year,d.month,d.day,(hour%12)+(12 if amp.lower()=='pm' else 0),
                            int(m),tzinfo=ZoneInfo(ZONE)).astimezone(timezone.utc)
        a,b=dt(sh,sm,sa),dt(eh,em,ea)
        return (a,b) if a and b and b>a else None
    except ValueError:return None

def collect(source,fetch,*,deadline_at=None,now=None):
    from bs4 import BeautifulSoup
    if (source.get('source_key')!=KEY or
        (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY]
        or source.get('timezone')!=ZONE):
        raise ValueError('unregistered_scmwa_source')
    soup=BeautifulSoup(fetch(URL,'text/html'),'html.parser')
    cards=soup.select('article.grid-card.events')
    if not cards or len(cards)>MAX_RECORDS:
        raise ValueError('scmwa_manifest_invalid')
    now=now or datetime.now(timezone.utc)
    rows={}
    for card in cards:
        link=card.select_one('a.main-link[href]')
        title=card.select_one('.info h2')
        date=card.select_one('.info h3')
        if not link or not title or not date:continue
        url=link.get('href')
        title_text=plain(title.get_text(' ',strip=True))
        if not event_url(url) or title_text!=REVIEWED[url][0] or NONPUBLIC.search(title_text):
            continue
        if deadline_at is not None and monotonic()>=deadline_at:
            raise ValueError('scmwa_deadline')
        page=BeautifulSoup(fetch(url,'text/html'),'html.parser')
        head=page.select_one('main.site-main.events section.event-header h1')
        dates=page.select('main.site-main.events section.event-header .event-meta h3')
        body=page.select_one('main.site-main.events section.events-body .event-body-text')
        if not head or len(dates)<2 or not body:
            raise ValueError('scmwa_detail_missing')
        if plain(head.get_text(' ',strip=True))!=title_text:
            raise ValueError('scmwa_detail_title_drift')
        listed=' '.join(date.get_text(' ',strip=True).split())
        detailed=' '.join(dates[0].get_text(' ',strip=True).split())
        if listed!=detailed:
            raise ValueError('scmwa_detail_date_drift')
        times=_parse(detailed,dates[1].get_text(' ',strip=True))
        if not times:
            raise ValueError('scmwa_detail_clock_invalid')
        start,end=times
        if not (now-timedelta(hours=3)<=start<=now+timedelta(days=60) and end>now):
            continue
        text=description(str(body),limit=max(len(str(body)),MAX_DESCRIPTION+1))
        if not text or len(text)>MAX_DESCRIPTION or NONPUBLIC.search(text):
            continue
        # This explicit registration line is the *only* currently verified
        # check-in address. Multi-venue stops are NOT assigned this coordinate.
        if not re.search(r'334\s+Ingalls\s+St(?:reet)?\s+Suite\s+A\b',text,re.I):
            continue
        if not re.search(r'Swift Street Courtyard',text,re.I):
            continue
        venue=REVIEWED[url][2]
        row=record(title_text,start.isoformat(),end.isoformat(),venue,REVIEWED[url][1],
                   'Santa Cruz',url,'surfcitystroll-'+start.date().isoformat(),
                   'Wine Walk',None,None,ZONE,retain_until_end=True)
        if row is None:continue
        row.update(description=text,timezone=ZONE,publisher_categories=['Wine Walk'],
                   location_provenance='official_publisher_numbered_checkin_street')
        ident=(row['id'],row['starts_at'])
        if ident in rows and rows[ident]!=row:
            raise ValueError('scmwa_duplicate_conflict')
        rows[ident]=row
    return sorted(rows.values(),key=lambda r:(r['starts_at'],r['title'],r['id']))

