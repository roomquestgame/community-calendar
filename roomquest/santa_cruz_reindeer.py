"""Boulder Creek Reindeer Run: one publisher-confirmed Christmas Eve event.

The organizer gives a genuine 9 AM–noon local event window, not an invented
timed 5K gun start. Junction Park's street is independently checked against
its operator, Boulder Creek Recreation & Park District, on each preview.
"""
from __future__ import annotations
import re
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record

KEY='boulder_creek_reindeer_run_ca'
URL='https://www.bouldercreekreindeerrun.com/'
PARK_URL='https://www.bcrpd.org/rentals'
ZONE='America/Los_Angeles'
ADDRESS='13264 Middleton Ave, Boulder Creek, CA 95006'
SOURCES={KEY:(URL,'html','html')}
ALLOWED_HOSTS={KEY:('www.bouldercreekreindeerrun.com','www.bcrpd.org')}
MAX_RECORDS=1
MAX_DESCRIPTION=12000

def event_url(value):
    return value==URL

def _text(body):
    if not isinstance(body,str) or len(body)>2_500_000:
        raise ValueError('reindeer_invalid_publisher_html')
    doc=BeautifulSoup(body,'html.parser')
    if not doc.body:raise ValueError('reindeer_invalid_publisher_html')
    return doc.body.get_text(' ',strip=True).replace('\xa0',' ')

def collect(source,fetch,*,now=None,deadline_at=None):
    if (source.get('source_key')!=KEY or
        (source.get('feed_url'),source.get('kind'),source.get('platform_adapter'))!=SOURCES[KEY] or
        source.get('timezone')!=ZONE):
        raise ValueError('reindeer_unregistered_source')
    t=_text(fetch(URL,'text/html'))
    if not ('2026 Reindeer Run' in t and
            '10th Annual Reindeer Run 5k run/walk' in t and
            re.search(r'Between\s+9am\s+and\s+Noon,\s+on\s+December\s+24th',t,re.I) and
            'Junction Park' in t and 'Highway 9 and Irwin Way' in t):
        raise ValueError('reindeer_date_or_location_changed')
    a=t.find('Watch out, Boulder Creek!')
    b=t.find('© 2026 Boulder Creek Reindeer Run',a)
    if a<0 or b<=a:
        raise ValueError('reindeer_description_missing')
    narrative=t[a:b].strip()
    if len(narrative)<250 or len(narrative)>MAX_DESCRIPTION:
        raise ValueError('reindeer_description_length')
    if re.search(r'\b(?:cancelled|canceled|postponed|sold out)\b',narrative,re.I):
        return []
    start=datetime(2026,12,24,9,tzinfo=ZoneInfo(ZONE))
    end=datetime(2026,12,24,12,tzinfo=ZoneInfo(ZONE))
    now=now or datetime.now(timezone.utc)
    if start.astimezone(timezone.utc)<now-timedelta(hours=3) or start.astimezone(timezone.utc)>now+timedelta(days=60):
        return []
    park=_text(fetch(PARK_URL,'text/html'))
    if not re.search(r'Junction\s+Park\s+13264\s+Middleton\s+Ave\.?',park,re.I):
        raise ValueError('reindeer_park_street_changed')
    row=record('10th Annual Boulder Creek Reindeer Run',start.isoformat(),end.isoformat(),
               'Junction Park',ADDRESS,'Boulder Creek',URL,'2026-12-24-reindeer-5k',
               'Running, Walking, Community Fundraiser',None,None,ZONE,retain_until_end=True)
    if row is None:return []
    row.update(description=narrative,timezone=ZONE,
               publisher_categories=['5K Run/Walk','Holiday Fundraiser'],
               location_provenance='boulder_creek_park_district_official_street',
               location_evidence_url=PARK_URL)
    from roomquest.publisher_evidence import attach
    return [attach(row,KEY)]
