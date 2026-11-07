"""Owner-reviewed ChamberMaster XML: public records, no inherited recurrence facts."""
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import quote, urlparse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record, timestamp, plain
from roomquest.publisher_evidence import attach
from roomquest.mycountyparks import cancelled

SIOUXLAND = 'municipal_chambermaster_siouxland_ia'

SOURCES = {
 'municipal_chambermaster_bellevue_ne': ('https://business.bellevuenebraska.com/api/events', 'America/Chicago'),
 'municipal_chambermaster_clear_lake_ia': ('https://members.clearlakeiowa.com/api/events', 'America/Chicago'),
 SIOUXLAND: ('https://business.siouxlandchamber.com/api/events', 'America/Chicago'),
}


STREET_SUFFIX = r'(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Court|Ct|Circle|Cir|Highway|Hwy|Parkway|Pkwy|Place|Pl|Way|Terrace|Ter|Loop|Trail|Trl)'


def own_address(element, location):
    """Format only explicit event-local street/city/state for the shared resolver.

    Suites/rooms stay in meeting_location evidence; they are not a different
    physical building and are not invented components of its geocoding query.
    """
    states = {'ia': 'IA', 'iowa': 'IA', 'ne': 'NE', 'nebraska': 'NE'}
    street = plain(element.findtext('MapAddr1'))
    city = plain(element.findtext('MapCity'))
    state = states.get(plain(element.findtext('MapState')).lower())
    if (street and city and state and re.match(r'^\d{1,6}\s', street)
            and re.search(r'\b' + STREET_SUFFIX + r'\b', street, re.I)):
        return f'{street}, {city}, {state}', city
    return address_from_location(location)


def address_from_location(location):
    """Return explicit street, city and state, without inheriting source locality."""
    states = {'ia': 'IA', 'iowa': 'IA', 'ne': 'NE', 'nebraska': 'NE'}
    # Remove only a final parenthesized directions note, not arbitrary text.
    text = re.sub(r'\s*\([^()]*\)\s*$', '', location).strip()
    locality = re.search(r'\b(IA|Iowa|NE|Nebraska)\b[,. ]*(\d{4,5}(?:-\d{4})?)?[. ]*$', text, re.I)
    if not locality:
        return None
    state = states[locality.group(1).lower()]
    body = text[:locality.start()].strip(' ,')
    numbered = re.search(r'\b\d{1,6}\s+\S', body)
    if not numbered:
        return None
    body = body[numbered.start():]
    address = re.fullmatch(
        r'(?P<street>\d{1,6}\s+.+?\b' + STREET_SUFFIX +
        r'\.?(?:\s+(?:N|S|E|W|NE|NW|SE|SW)\.?)?)'
        r'(?:,?\s+(?:Suite|Ste|Unit|#)\s*[A-Za-z0-9-]+)?'
        r',?\s+(?P<city>[A-Za-z][A-Za-z .\x27-]+)', body, re.I)
    if not address:
        return None
    city = address.group('city').strip(' ,')
    street = address.group('street').strip(' ,')
    postal = locality.group(2) or ''
    # A malformed four-digit publisher ZIP is not silently corrected.
    if not re.fullmatch(r'\d{5}(?:-\d{4})?', postal):
        postal = ''
    return f'{street}, {city}, {state}' + (' ' + postal if postal else ''), city


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
        if key == SIOUXLAND and e.findtext('VisibilityFlags') != 'Public':
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
        resolved_address = own_address(e, location)
        if not resolved_address:
            continue
        address, event_city = resolved_address
        if key == SIOUXLAND and re.match(r'^\d+\s*(?:&|and|/)\s*\d+', address, re.I):
            continue
        soup = BeautifulSoup(location_html, 'html.parser')
        label = soup.find(['strong', 'b'])
        venue = plain(label.get_text()) if label else re.split(r'\b\d{1,6}\s', location, maxsplit=1)[0].strip(' ,.-')
        # Publisher's own URL and complete address corroborate this named venue.
        # Do not infer a venue from an act name or a city-wide default.
        if (not venue and key == 'municipal_chambermaster_clear_lake_ia'
                and urlparse(plain(e.findtext('URL'))).hostname in {'surfballroom.com', 'www.surfballroom.com'}
                and re.fullmatch(r'460 (?:N|North) Shore Drive, Clear Lake, IA 50428', address, re.I)):
            venue = 'Surf Ballroom & Museum'
        if not venue:
            venue = address  # an address-only publisher label stays explicit, never invented
        url=base+'/events/details/'+quote(slug if slug.endswith('-'+ident) else slug+'-'+ident,safe='-')
        row=record(title,starts.isoformat(),ends.isoformat() if ends else None,venue,address,event_city,url,ident,tz=identity[1],retain_until_end=True)
        if not row:continue
        row['description']=description
        # Numeric category IDs are not human-readable activity evidence.
        row['publisher_categories']=[]
        costs=plain(e.findtext('AdmissionDesc'))[:400]
        pictures={x.get('src') for x in BeautifulSoup(e.findtext('Description') or '', 'html.parser').select('img[src]')}
        candidate=next(iter(pictures)) if key != SIOUXLAND and len(pictures)==1 else None
        row=attach(row,key,facts={'cost':costs,'meeting_location':location[:400]},candidate=candidate)
        uid=(row['id'],row['starts_at'])
        if uid in rows and rows[uid]!=row:raise ValueError('conflicting_event_occurrence')
        rows[uid]=row
    return sorted(rows.values(),key=lambda x:(x['starts_at'],x['id']))
