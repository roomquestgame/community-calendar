"""Official Tampa City Council and Howard County Council public calendars."""
from datetime import date, datetime, timedelta, timezone
import json
import re
from time import monotonic

from roomquest.civic_notices import date_notice, metadata
from roomquest.mapsee_adapter import plain, record, timestamp


ZONE = 'America/New_York'
TAMPA = 'tampa_city_council_fl'
HOWARD = 'howard_county_council_md'
TAMPA_AGENDAS = 'https://www.tampa.gov/agendas'
HOWARD_FEED = 'https://cc.howardcountymd.gov/events/feed-index'
SOURCES = {
    TAMPA: {
        'url': 'https://tampagov.hylandcloud.com/251agendaonline/',
        'hosts': ('tampagov.hylandcloud.com',),
        'jurisdiction': ('us-fl-tampa', 'Tampa, Florida'),
        'scope': 'published_regular_council_agenda_at_reviewed_chambers',
    },
    HOWARD: {
        'url': 'https://cc.howardcountymd.gov/calendar',
        'hosts': ('cc.howardcountymd.gov',),
        'jurisdiction': ('us-md-howard', 'Howard County, Maryland'),
        'scope': 'current_public_council_feed_named_county_building_and_council_closures',
    },
}
TAMPA_CHAMBERS = 'Tampa City Council Chambers, Old City Hall'
TAMPA_ADDRESS = '315 E. Kennedy Blvd., Tampa, FL 33602'
HOWARD_BUILDING = 'George Howard Building'
HOWARD_ADDRESS = '3430 Court House Drive, Ellicott City, MD 21043'
_TAMPA_REGULAR = re.compile(r'^City Council Regular\s*[-–,]\s*[A-Za-z]+ \d{1,2}, \d{4}$', re.I)
_CANCELLATION = re.compile(r'\b(cancelled|canceled|postponed)\b', re.I)
_PRIVATE = re.compile(r'\b(executive session|closed session|private meeting|tentative)\b', re.I)
_HOWARD_BODIES = {
    'county-council', 'board-of-appeals', 'hearing-examiner', 'zoning-board',
    'alcoholic-beverage-hearing-board', 'liquor-board',
}


def source_payload(key):
    spec = SOURCES[key]
    return {'source_key': key, 'feed_url': spec['url'], 'kind': 'html',
            'platform_adapter': 'html', 'timezone': ZONE, 'civic_contract_version': 1,
            'civic_jurisdiction_id': spec['jurisdiction'][0]}


def validate(source):
    key = source.get('source_key')
    if (key not in SOURCES or type(source.get('civic_contract_version')) is not int
            or any(source.get(k) != value for k, value in source_payload(key).items())):
        raise ValueError('unregistered_local_civic_source')
    return SOURCES[key]


def _status(title):
    match = _CANCELLATION.search(title)
    if match:
        return 'postponed' if match[1].casefold() == 'postponed' else 'cancelled'
    return 'scheduled'


def _meeting(key, title, start, location, url, identity, now, description, status):
    if start <= now or start >= now + timedelta(days=60):
        return None
    jurisdiction_id, jurisdiction_name = SOURCES[key]['jurisdiction']
    row = record(title, start.isoformat(), None, *location, url, identity, 'Civic', tz=ZONE)
    if row is not None:
        row.update(
            description=description, publisher_status=status,
            civic=metadata(kind='meeting', topic='government', jurisdiction_id=jurisdiction_id,
                           jurisdiction_name=jurisdiction_name, source_url=url, verified_at=now,
                           valid_until=start + timedelta(hours=3), precision='timed', tz=ZONE),
        )
    return row


def _unique(rows):
    by_id = {}
    for row in rows:
        if row is None:
            continue
        previous = by_id.setdefault(row['id'], row)
        if previous != row:
            raise ValueError('conflicting_local_civic_identity')
    return sorted(by_id.values(), key=lambda row: (row.get('starts_on') or row['starts_at'], row['id']))


def _tampa(payload, now):
    marker = 'showSearchResults(new SearchResults('
    if payload.count(marker) != 1:
        raise ValueError('tampa_council_agenda_missing')
    manifest, _ = json.JSONDecoder().raw_decode(payload.split(marker, 1)[1].lstrip())
    meetings = manifest.get('Meetings') if isinstance(manifest, dict) else None
    if not isinstance(meetings, list) or not meetings or len(meetings) > 500:
        raise ValueError('tampa_council_agenda_invalid')
    rows = []
    for item in meetings:
        if not isinstance(item, dict):
            raise ValueError('tampa_council_agenda_invalid')
        if item.get('MeetingTypeName') != 'Council Regular':
            continue
        title = plain(item.get('Name'))
        status = _status(title)
        name = re.sub(r'^(?:cancelled|canceled|postponed)\s*[-–:]\s*', '', title, flags=re.I)
        if not _TAMPA_REGULAR.fullmatch(name) or _PRIVATE.search(title):
            continue
        location = plain(item.get('Location'))
        if location.casefold() not in {'', 'city council chambers', 'old city hall', TAMPA_CHAMBERS.casefold()}:
            continue
        start = timestamp(item.get('Time'))
        publisher_id = item.get('ID')
        if (start is None or type(publisher_id) is not int or publisher_id <= 0
                or type(item.get('TimeStamp')) is not int or start.timestamp() != item['TimeStamp']):
            raise ValueError('tampa_council_occurrence_invalid')
        rows.append(_meeting(
            TAMPA, title, start, (TAMPA_CHAMBERS, TAMPA_ADDRESS, 'Tampa'),
            TAMPA_AGENDAS, f'tampa-agenda:{publisher_id}', now,
            'Regular Tampa City Council meeting. The City lists Old City Hall as the regular meeting venue. '
            'Check the official agenda for changes.', status,
        ))
    return _unique(rows)


def _howard(payload, now):
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or manifest.get('feed_url') != HOWARD_FEED:
        raise ValueError('howard_council_feed_invalid')
    items = manifest.get('items')
    if not isinstance(items, list) or len(items) > 100 or 'next_url' in manifest:
        raise ValueError('howard_council_feed_invalid')
    rows = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('howard_council_feed_invalid')
        title = plain(item.get('title'))
        url = item.get('url')
        publisher_id = item.get('id')
        if (not re.fullmatch(r'https://cc\.howardcountymd\.gov/calendar/[a-z0-9-]+', str(url))
                or not re.fullmatch(r'[0-9]{1,12}', str(publisher_id)) or not title):
            raise ValueError('howard_council_occurrence_invalid')
        day = date.fromisoformat(item['date_published'])
        identity = f'howard-council:{publisher_id}'
        status = _status(title)
        clock = plain(item.get('content_html'))
        if ('holiday - office closed' in title.casefold() and clock == '12:00 AM'
                and item.get('summary') == 'george-howard-building'):
            rows.append(date_notice(
                identity=identity, title=title, starts_on=day, now=now, source_url=url,
                jurisdiction_id='us-md-howard', jurisdiction_name='Howard County, Maryland',
                description='The Howard County Council office is closed for the holiday.',
                status=status, horizon_days=59,
            ))
            continue
        body = item.get('content_text')
        public_body = (body in _HOWARD_BODIES or title.upper().startswith('COUNTY COUNCIL:')
                       or title.casefold() == 'inspector general advisory board')
        if not public_body or item.get('summary') != 'george-howard-building' or _PRIVATE.search(title):
            continue
        if not re.fullmatch(r'(?:0?[1-9]|1[0-2]):[0-5]\d [AP]M', clock) or clock == '12:00 AM':
            continue
        local_time = datetime.strptime(clock, '%I:%M %p').time()
        start = timestamp(datetime.combine(day, local_time).isoformat(), ZONE)
        rows.append(_meeting(
            HOWARD, title, start, (HOWARD_BUILDING, HOWARD_ADDRESS, 'Ellicott City'),
            url, identity, now, 'See the Howard County Council calendar for the agenda and participation details.',
            status,
        ))
    return _unique(rows)


def collect(source, fetch, *, deadline_at=None, now=None):
    spec = validate(source)
    current = now or datetime.now(timezone.utc)
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    if source['source_key'] == TAMPA:
        return _tampa(fetch(spec['url'], 'text/html'), current)
    return _howard(fetch(HOWARD_FEED, 'application/json'), current)
