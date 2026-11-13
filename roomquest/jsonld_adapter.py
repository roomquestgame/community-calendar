"""Bounded JSON-LD collection; catalog names remain provenance, not routing.

Only embedded facts are read. No JS execution, page crawl, remote @context,
geocoding, guessed timezone or publisher-wide location is introduced.
"""
from datetime import date, datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
from roomquest.mapsee_adapter import record, address

COALITION_KEY = 'municipal_mapsee_8000fb8c18bf23f709b53465'
COALITION_URL = 'https://calendar.richmondcultureworks.org/organizations/coalition-theater/'
COALITION_VENUE = '8 W Broad St, Richmond, VA, 23220'

SCRAP_RVA_URL = 'https://events.humanitix.com/host/scrap-rva'
SCRAP_RVA_LOCATIONS = {
    '322 W Brookland Park Blvd, Richmond, VA 23222, USA': (
        '322 W Brookland Park Blvd, Richmond, VA 23222', 37.571723815738, -77.436572103988),
    '1621 W Broad St, Richmond, VA 23220, USA': (
        '1621 W Broad St, Richmond, VA 23220', 37.554492788162, -77.457006423537),
}

def decode(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        from scrapers.lib.jsonld import fix_malformed_description
        return json.loads(fix_malformed_description(raw))


class Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            mime = (dict(attrs).get('type') or '').split(';')[0].strip().lower()
            self.active = mime == 'application/ld+json'
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.blocks.append(decode(''.join(self.parts)))
            self.active = False


def types(node):
    raw = node.get('@type', [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise ValueError('unsupported_jsonld_event_shape')
    return {v.rsplit('/', 1)[-1].rsplit('#', 1)[-1] for v in raw}


def parse(payload, base=''):
    if payload.lstrip().startswith(('{', '[')):
        blocks = [decode(payload)]
    else:
        reader = Blocks()
        reader.feed(payload)
        reader.close()
        if reader.active:
            raise ValueError('invalid_jsonld_block')
        blocks = reader.blocks
    if not blocks:
        raise ValueError('unsupported_jsonld_payload')
    nodes = []
    def visit(value, depth=0):
        if depth > 30 or len(nodes) > 5000:
            raise ValueError('source_record_limit')
        if isinstance(value, dict):
            nodes.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child, depth+1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth+1)
    visit(blocks)
    def is_event(node):
        return any(t.endswith('Event') or t in {'Festival', 'Hackathon', 'CourseInstance', 'EventSeries'} for t in types(node))
    refs = {}
    for node in nodes:
        identity = node.get('@id')
        if isinstance(identity, str) and len(node) > 1 and not is_event(node):
            # Conflicting definitions must not silently attach a different venue.
            if identity in refs and refs[identity] != node:
                raise ValueError('conflicting_jsonld_reference')
            refs[identity] = node
    def resolve(value):
        if isinstance(value, dict) and set(value) == {'@id'}:
            return refs.get(value['@id'], value)
        return value
    events = [n for n in nodes if is_event(n)]
    if len(events) > 500:
        raise ValueError('source_record_limit')
    if not events:
        if any('ItemList' in types(n) and not isinstance(n.get('numberOfItems'), bool) and n.get('numberOfItems') == 0
               and isinstance(n.get('itemListElement'), list) and not n['itemListElement'] for n in nodes):
            return []
        raise ValueError('unsupported_jsonld_event_shape')
    out = {}
    for e in events:
        if str(e.get('eventStatus', '')).endswith(('EventCancelled', 'EventPostponed')):
            continue
        if str(e.get('eventAttendanceMode', '')).endswith('OnlineEventAttendanceMode'):
            continue
        v = resolve(e.get('location') or {})
        if isinstance(v, list):
            physical = [resolve(x) for x in v if isinstance(resolve(x), dict)
                        and 'VirtualLocation' not in types(resolve(x))]
            if len(physical) > 1:
                raise ValueError('ambiguous_event_location')
            v = physical[0] if physical else {}
        if isinstance(v, str):
            v = {'name': v}
        if not isinstance(v, dict) or 'VirtualLocation' in types(v):
            continue
        a = resolve(v.get('address') or {})
        g = resolve(v.get('geo') or {})
        g = g if isinstance(g, dict) else {}
        link = e.get('url') or e.get('@id')
        if not isinstance(link, str) or not link:
            raise ValueError('event_link_missing')
        street = address(a)
        lat, lng = g.get('latitude'), g.get('longitude')
        if base == SCRAP_RVA_URL and isinstance(a, dict):
            reviewed = SCRAP_RVA_LOCATIONS.get(a.get('streetAddress'))
            if reviewed:
                street, lat, lng = reviewed
        row = record(e.get('name'), e.get('startDate'), e.get('endDate'), v.get('name'),
            street, a.get('addressLocality', '') if isinstance(a, dict) else '',
            urljoin(base, link), e.get('@id') or e.get('url'), e.get('keywords', ''),
            lat, lng)
        if row:
            key = (row['id'], row['starts_at'])
            if key in out and out[key] != row:
                raise ValueError('conflicting_event_occurrence')
            out[key] = row
    result = sorted(out.values(), key=lambda r: (r['starts_at'], r['title']))
    if result and not any(r.get('venue_name') or r.get('venue_address') for r in result):
        raise ValueError('venue_extraction_unavailable')
    return result


def collect(source, fetch):
    if source.get('source_key') == COALITION_KEY:
        if source['feed_url'] != COALITION_URL or source.get('timezone') != 'America/New_York':
            raise ValueError('unregistered_coalition_calendar')
        return collect_coalition(fetch)
    return parse(fetch(source['feed_url'], 'text/html,application/ld+json'), source['feed_url'])


def collect_coalition(fetch):
    from bs4 import BeautifulSoup

    snapshot = BeautifulSoup(fetch(COALITION_URL, 'text/html'), 'html.parser')
    section = snapshot.select_one('section.ao-assoc-events')
    if section is None:
        raise ValueError('coalition_event_list_missing')
    cards = section.select('a.ao-event-card[href]')
    if not cards or len(cards) > 12:
        raise ValueError('coalition_event_list_invalid')
    today = datetime.now(ZoneInfo('America/New_York')).date()
    links = set()
    for card in cards:
        day = card.select_one('time[datetime]')
        link = card['href']
        parts = urlsplit(link)
        if (day is None or parts.scheme != 'https' or parts.netloc != urlsplit(COALITION_URL).netloc
                or not re.fullmatch(r'/events/[a-z0-9-]+/', parts.path) or parts.query or parts.fragment):
            raise ValueError('coalition_event_link_invalid')
        if date.fromisoformat(day['datetime']) >= today:
            links.add(link)
    rows = []
    for link in sorted(links):
        for row in parse(fetch(link, 'text/html,application/ld+json'), link):
            if row['event_url'] != link:
                raise ValueError('coalition_event_identity_conflict')
            if row['venue_name'] == 'Coalition Theater' and row['venue_address'] == COALITION_VENUE:
                row.update(lat=37.545791754629, lng=-77.441952646962)
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
