"""Bounded MEC RSS and library feeds, independent of catalog provenance.

Only registered endpoints and explicit event facts are accepted. RSS publication
dates are never event dates. No detail crawl, venue lookup or default map pin.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from roomquest.mapsee_adapter import record, address, plain

# Existing source identities stay unchanged. Timezones describe each calendar,
# not a venue location. A publisher-supplied offset always takes precedence.
SOURCES = {
    'municipal_3ceeb945131a8a11d7e63495': ('https://choose901.com/feed/?post_type=mec-events', 'rss', 'wordpress', 'America/Chicago'),
    'municipal_dbc6ce3130dab2da69e6d57e': ('https://marignyoperahouse.org/feed/?post_type=mec-events', 'rss', 'wordpress', 'America/Chicago'),
    'municipal_f6162b4f314aa6653cfeca92': ('https://riverfront.org/feed/?post_type=mec-events', 'rss', 'wordpress', 'America/New_York'),
    'municipal_4be969ccce374519948bcf61': ('https://tucsonbirds.org/feed/?post_type=mec-events', 'rss', 'wordpress', 'America/Phoenix'),
    'municipal_f18b942eb3e39e3a547fd0d5': ('https://www.bishopmuseum.org/feed/?post_type=mec-events', 'rss', 'wordpress', 'Pacific/Honolulu'),
    'municipal_c91056bd80f24dd814016374': ('https://slcpl.libnet.info/eeventcaldata?event_type=0&req=%7B%22private%22%3Afalse%2C%22date%22%3A%222026-10-27%22%2C%22days%22%3A30%2C%22locations%22%3A%5B%5D%2C%22ages%22%3A%5B%5D%2C%22types%22%3A%5B%5D%7D', 'json', 'library', 'America/Denver'),
    'municipal_5d303aae26849421929219ee': ('https://slcls.libnet.info/eeventcaldata?event_type=0&req=%7B%22private%22%3Afalse%2C%22date%22%3A%222026-10-27%22%2C%22days%22%3A30%2C%22locations%22%3A%5B%5D%2C%22ages%22%3A%5B%5D%2C%22types%22%3A%5B%5D%7D', 'json', 'library', 'America/Denver'),
    'municipal_0c023710af802e201c31e71b': ('https://hoover.libnet.info/eeventcaldata?event_type=0&req=%7B%22private%22%3Afalse%2C%22date%22%3A%222026-10-27%22%2C%22days%22%3A30%2C%22locations%22%3A%5B%5D%2C%22ages%22%3A%5B%5D%2C%22types%22%3A%5B%5D%7D', 'json', 'library', 'America/Chicago'),
    'municipal_41dcfb1feff056779e0f0b42': ('https://pima.bibliocommons.com/events/rss/all', 'rss', 'library', 'America/Phoenix'),
}
MAX_RECORDS = 500
MEC = 'http://webnus.net/rss/mec/'
ICAL = 'urn:ietf:params:xml:ns:icalendar-2.0'
EVENT_RSS = 'http://purl.org/rss/1.0/modules/event/'


def event_time(value, time=None):
    """Reject dates lacking an event time rather than inventing midnight."""
    value = str(value or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) and time:
        clock = str(time).strip()
        if re.fullmatch(r'\d{1,2}:\d{2}\s*[AP]M', clock, re.I):
            clock = datetime.strptime(re.sub(r'\s*([AP]M)$', r' \1', clock.upper()), '%I:%M %p').strftime('%H:%M')
        value += 'T' + clock
    if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', value):
        raise ValueError('event_time_unresolved')
    return value


def unique(rows):
    out = {}
    for row in rows:
        if row is None:
            continue
        key = (row['id'], row['starts_at'])
        if key in out and out[key] != row:
            raise ValueError('conflicting_event_occurrence')
        out[key] = row
    return sorted(out.values(), key=lambda r: (r['starts_at'], r['title']))


def xml_root(payload):
    if re.search(r'<!\s*(DOCTYPE|ENTITY)', payload, re.I):
        raise ValueError('unsafe_xml_payload')
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError('invalid_rss_payload') from exc
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('unsupported_rss_payload')
    items = root.findall('./channel/item')
    if len(items) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    # Never silently consume only the first page of an explicit paginated feed.
    if any(e.get('rel') == 'next' for e in root.iter()):
        raise ValueError('rss_pagination_requires_review')
    return items


def text(node, tag):
    child = node.find(tag)
    return ''.join(child.itertext()).strip() if child is not None else ''


def parse_rss(payload, source, tz):
    rows = []
    for item in xml_root(payload):
        mec = source['platform_adapter'] == 'wordpress'
        ns = MEC if mec else ICAL
        field = lambda key: text(item, '{' + ns + '}' + key)
        start = field('startDate' if mec else 'dtstart')
        end = field('endDate' if mec else 'dtend')
        if not mec and not start:
            start = text(item, '{' + EVENT_RSS + '}startdate')
            end = text(item, '{' + EVENT_RSS + '}enddate')
        start = event_time(start, field('startTime') if mec else None)
        end = event_time(end, field('endTime') if mec else None) if end else None
        venue = field('location') or (text(item, '{' + EVENT_RSS + '}location') if not mec else '')
        street = field('address')
        # Use only event-owned address/geo; a library or organizer may use many
        # locations. Missing fields stay available for the shared cache/review.
        lat = text(item, '{http://www.w3.org/2003/01/geo/wgs84_pos#}lat')
        lng = text(item, '{http://www.w3.org/2003/01/geo/wgs84_pos#}long')
        identity = text(item, 'guid') or text(item, 'link')
        if not identity:
            raise ValueError('event_identity_missing')
        rows.append(record(text(item, 'title'), start, end, venue, street, '',
                           text(item, 'link'), identity,
                           ', '.join(plain(c.text) for c in item.findall('category')),
                           lat, lng, tz))
    return unique(rows)


def libnet_url(url, tz, now=None):
    """Retain registered filters and refresh the stale date in publisher time."""
    from zoneinfo import ZoneInfo
    root = urlsplit(url)
    pairs = parse_qsl(root.query, keep_blank_values=True)
    params = dict(pairs)
    if len(params) != len(pairs) or 'req' not in params:
        raise ValueError('unsupported_library_query')
    req = json.loads(params['req'])
    if not isinstance(req, dict) or req.get('private') is not False:
        raise ValueError('unsupported_library_query')
    req['date'] = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz)).date().isoformat()
    # Preserve the researched thirty-day window. Oversized calendars fail into
    # review, not a partial snapshot disguised as a successful empty calendar.
    if req.get('days') != 30:
        raise ValueError('unsupported_library_window')
    params['req'] = json.dumps(req, separators=(',', ':'))
    return urlunsplit((root.scheme, root.netloc, root.path, urlencode(params), ''))


def parse_libnet(payload, source, tz):
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError('unsupported_library_payload')
    if len(data) >= MAX_RECORDS:
        raise ValueError('source_record_limit')
    rows = []
    for e in data:
        if not isinstance(e, dict):
            raise ValueError('unsupported_library_event')
        if e.get('private') is True or e.get('cancelled') is True:
            continue
        start = event_time(e.get('event_start'))
        end = event_time(e['event_end']) if e.get('event_end') else None
        identity = e.get('event_id') or e.get('id')
        if not identity:
            raise ValueError('event_identity_missing')
        street = e.get('address') or e.get('location_address') or ''
        if isinstance(street, dict):
            street = address(street)
        venue = e.get('location') or e.get('branch') or ''
        if not isinstance(venue, str) or not isinstance(street, str):
            raise ValueError('unsupported_library_location')
        rows.append(record(e.get('title') or e.get('event_title'), start, end,
                           venue, street, e.get('city') or '',
                           e.get('url') or e.get('event_url'), identity,
                           e.get('event_type') or '', e.get('latitude'),
                           e.get('longitude'), tz))
    return unique(rows)


def collect(source, fetch):
    profile = SOURCES.get(source.get('source_key'))
    if not profile or (source.get('feed_url'), source.get('kind'),
                       source.get('platform_adapter')) != profile[:3]:
        raise ValueError('unregistered_community_format_source')
    url, kind, adapter, tz = profile
    if kind == 'json':
        return parse_libnet(fetch(libnet_url(url, tz), 'application/json'), source, tz)
    return parse_rss(fetch(url, 'application/rss+xml,application/xml'), source, tz)
