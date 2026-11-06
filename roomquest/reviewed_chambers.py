"""Owner-reviewed ChamberMaster XML: public records, no inherited recurrence facts."""
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record, timestamp, plain
from roomquest.publisher_evidence import attach
from roomquest.mycountyparks import cancelled

SOURCES = {
 'municipal_chambermaster_bellevue_ne': ('https://business.bellevuenebraska.com/api/events', 'America/Chicago'),
 'municipal_chambermaster_clear_lake_ia': ('https://members.clearlakeiowa.com/api/events', 'America/Chicago'),
}


def collect(source, payload, *, now=None):
    key=source.get('source_key');identity=SOURCES.get(key)
    if (not identity or source.get('feed_url')!=identity[0] or source.get('timezone')!=identity[1]
            or source.get('kind')!='xml' or source.get('platform_adapter')!='growthzone'):
        raise ValueError('unregistered_reviewed_chamber')
    root=ET.fromstring(payload)
    if root.tag!='ArrayOfEventDisplay' or len(root)>500:
        raise ValueError('publisher_record_limit')
    now=now or datetime.now(timezone.utc);rows={}
    base=identity[0].removesuffix('/api/events')
    for e in root:
        if e.tag!='EventDisplay':raise ValueError('publisher_payload_changed')
        if (e.findtext('Status')!='APPROVED' or 'Public' not in (e.findtext('VisibilityFlags') or '').split()
                or e.findtext('IsAllDayEvent')!='false'):
            continue
        ident=e.findtext('EventID') or '';slug=e.findtext('Slug') or ''
        if not re.fullmatch(r'[1-9][0-9]{0,19}',ident) or not slug or len(slug)>300 or not all(c.isalnum() or c=='-' for c in slug):
            raise ValueError('publisher_identity_changed')
        title=plain(e.findtext('Name'));description=plain(e.findtext('Description'))[:2000]
        if not title or not description or cancelled(title,description):continue
        starts=timestamp(e.findtext('StartDate'),identity[1]);ends=timestamp(e.findtext('EndDate'),identity[1])
        if not starts or starts>=now+timedelta(days=60):continue
        if ends and not starts<ends<=starts+timedelta(hours=16):continue
        if (ends or starts+timedelta(hours=3))<=now:continue
        hours=plain(e.findtext('HoursDesc'))
        # The common 23:55/23:59 export defaults are not verified attendance ends.
        local_end=ends.astimezone(ZoneInfo(identity[1])) if ends else None
        if local_end and local_end.hour==23 and local_end.minute in (55,59):ends=None
        location_html=e.findtext('LocationDesc') or ''
        location=plain(location_html)
        if re.search(r'\b(zoom|online|virtual)\b',location,re.I):continue
        # Do not turn chamber office/source-city fields into a venue point.
        map_street=plain(e.findtext('MapAddr1'))
        map_city=plain(e.findtext('MapCity'));map_state=plain(e.findtext('MapState'))
        address=', '.join(x for x in (map_street,map_city,map_state) if x) if map_street and map_city and map_state else location
        soup=BeautifulSoup(location_html,'html.parser')
        label=soup.find(['strong','b'])
        venue=plain(label.get_text()) if label else re.split(r'\b\d{1,6}\s',location,maxsplit=1)[0].strip(' ,.-')
        if not venue:venue=location
        # The source city is not attendance evidence. Incomplete local addresses
        # remain withheld until the publisher supplies a complete locality.
        if (not venue or not re.search(r'\d+\s+\S+',address)
                or not re.search(r'\b(?:IA|Iowa|NE|Nebraska)\b',address,re.I)):
            continue
        url=base+'/events/details/'+quote(slug if slug.endswith('-'+ident) else slug+'-'+ident,safe='-')
        row=record(title,starts.isoformat(),ends.isoformat() if ends else None,venue,address,map_city,url,ident,tz=identity[1],retain_until_end=True)
        if not row:continue
        row['description']=description
        # Numeric category IDs are not human-readable activity evidence.
        row['publisher_categories']=[]
        costs=plain(e.findtext('AdmissionDesc'))[:400]
        pictures={x.get('src') for x in BeautifulSoup(e.findtext('Description') or '', 'html.parser').select('img[src]')}
        candidate=next(iter(pictures)) if len(pictures)==1 else None
        row=attach(row,key,facts={'cost':costs},candidate=candidate)
        uid=(row['id'],row['starts_at'])
        if uid in rows and rows[uid]!=row:raise ValueError('conflicting_event_occurrence')
        rows[uid]=row
    return sorted(rows.values(),key=lambda x:(x['starts_at'],x['id']))
