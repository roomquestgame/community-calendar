"""Bounded JSON-LD collection; catalog names remain provenance, not routing.

Only embedded facts are read. No JS execution, page crawl, remote @context,
geocoding, guessed timezone or publisher-wide location is introduced.
"""
from datetime import date, datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo
from roomquest.mapsee_adapter import record, address

COALITION_KEY = 'municipal_mapsee_8000fb8c18bf23f709b53465'
COALITION_URL = 'https://calendar.richmondcultureworks.org/organizations/coalition-theater/'
COALITION_VENUE = '8 W Broad St, Richmond, VA, 23220'

# Venue-local schedules on these reviewed official calendars omit UTC offsets.
# Match the event's own city/region as well as the exact calendar; never apply
# the publisher's timezone to an offsite event. Reviewed 2026-11-21.
REVIEWED_CALENDAR_ZONES = {
    'https://www.punchlinecomedyclub.com/': ('San Francisco', 'CA', 'America/Los_Angeles'),
    'https://www.theechodallas.com/': ('Dallas', 'TX', 'America/Chicago'),
}


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


def definition_contains(full, partial):
    """Accept only a complete definition plus an agreeing subset of its facts.

    JSON-LD publishers repeat metadata nodes in separate script blocks. Missing
    properties are not contradictions, but a shared property's value must agree.
    Lists stay atomic: do not combine different venues, types, or coordinates.
    """
    if type(full) is not type(partial):
        return False
    if isinstance(full, dict):
        return all(key in full and definition_contains(full[key], value)
                   for key, value in partial.items())
    if isinstance(full, list):
        return len(full) == len(partial) and all(
            definition_contains(a, b) and definition_contains(b, a)
            for a, b in zip(full, partial))
    return full == partial


def parse(payload, base='', *, native_source=None):
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
            if identity in refs:
                # Keep the publisher's richer definition in either block order.
                # Complementary or contradictory definitions still need review;
                # never invent a combined venue from separate partial records.
                if definition_contains(refs[identity], node):
                    continue
                if not definition_contains(node, refs[identity]):
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
    # Humanitix supplies the map pin beside the complete address in the same
    # public location object. Ignore missing or conflicting matches.
    address_pins = {}
    if urlsplit(base).hostname == 'events.humanitix.com':
        for target, raw_address in re.findall(
                r'\bdirectionsLink:("(?:[^"\\]|\\.){1,1000}"),address:("(?:[^"\\]|\\.){1,400}")', payload):
            try:
                maps = urlsplit(json.loads(target))
                label = json.loads(raw_address)
                if maps.hostname != 'www.google.com' or maps.path.rstrip('/') != '/maps/search':
                    continue
                point = parse_qs(maps.query).get('query', [])
                if len(point) == 1 and re.fullmatch(r'-?\d{1,2}\.\d+,-?\d{1,3}\.\d+',point[0]):
                    lat, lng = map(float, point[0].split(','))
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        address_pins.setdefault(label, set()).add((lat, lng))
            except (ValueError, TypeError):
                continue
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
        # Some publishers put the complete US address in streetAddress as well
        # as supplying PostalAddress components. Join those components only once.
        if isinstance(a, dict) and all(isinstance(a.get(k), str) and a[k].strip()
                                       for k in ('streetAddress','addressLocality','addressRegion','postalCode')):
            city, region, postal = (re.escape(a[k].strip()) for k in ('addressLocality','addressRegion','postalCode'))
            full = re.fullmatch(r'(.+?,\s*' + city + r',\s*' + region + r'\s+' + postal +
                                r')(?:,\s*(?:USA|US|United States))?', a['streetAddress'].strip(), re.I)
            if full:
                street = full[1]
        lat, lng = g.get('latitude'), g.get('longitude')
        if isinstance(a, dict) and lat is None and lng is None and isinstance(a.get('streetAddress'), str):
            points = address_pins.get(a['streetAddress'], set())
            # Two event records may vary in sub-meter pin precision. Use an
            # actual publisher point only when all pins agree within ~1.1 m/axis.
            if points:
                lats, lngs = zip(*points)
                if max(lats)-min(lats) <= 0.00001 and max(lngs)-min(lngs) <= 0.00001:
                    lat, lng = min(points)
        if base == SCRAP_RVA_URL and isinstance(a, dict):
            reviewed = SCRAP_RVA_LOCATIONS.get(a.get('streetAddress'))
            if reviewed:
                street, lat, lng = reviewed
        start, end = e.get('startDate'), e.get('endDate')
        # A calendar may mix timed performances with all-day/private placeholders.
        # Do not manufacture midnight starts or let one untimed entry erase the
        # valid timed collection. Date-only ends carry no trustworthy end clock.
        if isinstance(start, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', start):
            date.fromisoformat(start)
            continue
        if isinstance(end, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', end):
            end_day = date.fromisoformat(end)
            if isinstance(start, str) and end_day < datetime.fromisoformat(start).date():
                raise ValueError('invalid_event_end')
            end = None
        zone = None
        reviewed = REVIEWED_CALENDAR_ZONES.get(base)
        if reviewed and isinstance(a, dict) and (
                a.get('addressLocality'), a.get('addressRegion')) == reviewed[:2]:
            zone = reviewed[2]
        if (base == 'https://nissis.com/shows/'
                and a == '1455 Coal Creek Dr. Lafayette, Co. 80026'):
            zone = 'America/Denver'
        if zone:
            for value in (start, end):
                if value:
                    clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    if clock.tzinfo is not None and clock.utcoffset() != clock.astimezone(ZoneInfo(zone)).utcoffset():
                        raise ValueError('publisher_schedule_conflict')
        row = record(e.get('name'), start, end, v.get('name'),
            street, a.get('addressLocality', '') if isinstance(a, dict) else '',
            urljoin(base, link), e.get('@id') or e.get('url'), e.get('keywords', ''),
            lat, lng, tz=zone)
        if row:
            if zone:
                row['timezone'] = zone
            if native_source is not None:
                from roomquest.registered_native_content import attach
                image = e.get('image')
                image = [resolve(value) for value in image[:5]] if isinstance(image, list) else resolve(image)
                attach(row, native_source, description_value=e.get('description'), image_value=image)
            else:
                from roomquest.event_description import description
                row['description'] = description(e.get('description'))
            key = (row['id'], row['starts_at'])
            if key in out and out[key] != row:
                raise ValueError('conflicting_event_occurrence')
            out[key] = row
    result = sorted(out.values(), key=lambda r: (r['starts_at'], r['title']))
    if result and not any(r.get('venue_name') or r.get('venue_address') for r in result):
        raise ValueError('venue_extraction_unavailable')
    return result


def collect(source, fetch):
    from roomquest.registered_native_content import enabled as native_enabled
    native_content = native_enabled(source, adapter='jsonld')
    if source.get('source_key') == COALITION_KEY:
        if source['feed_url'] != COALITION_URL or source.get('timezone') != 'America/New_York':
            raise ValueError('unregistered_coalition_calendar')
        return collect_coalition(fetch)
    return parse(fetch(source['feed_url'], 'text/html,application/ld+json'), source['feed_url'],
                 native_source=source if native_content else None)


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
