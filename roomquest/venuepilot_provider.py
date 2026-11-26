"""Collect the read-only public event collection behind VenuePilot's widget."""
from datetime import date, datetime, timedelta
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest.event_description import description
from roomquest.mapsee_adapter import record


API = 'https://www.venuepilot.co/graphql'
HOST = 'www.venuepilot.co'
WIDGET = 'widget.staging.venuepilot.com/'
QUERY = (
    'query PublicEvents($accountIds: [Int!]!, $startDate: String!, '
    '$endDate: String!, $search: String!, $searchScope: String!, $limit: Int!) {'
    ' publicEvents(accountIds: $accountIds, startDate: $startDate, endDate: $endDate, '
    'search: $search, searchScope: $searchScope, limit: $limit) {'
    ' id name date doorTime startTime endTime minimumAge promoter support description '
    'websiteUrl twitterUrl instagramUrl images status venue { name } footerContent '
    'highlightedImage ticketsUrl } }'
)
SOURCE = re.compile(r'https://www\.venuepilot\.co/graphql\?accountIds=([1-9][0-9]{0,9}(?:,[1-9][0-9]{0,9}){0,19})')

# Reviewed publisher facts for the first ordinary VenuePilot source. Additional
# accounts can use the same provider after receiving an equally reviewed profile.
PROFILES = {
    (2535,): {
        'timezone': 'America/New_York',
        'publisher_url': 'https://standupny.com/upcoming-shows/',
        'venues': {
            'Stand Up NY at Bond 45': {
                'address': '221 W 46th St, New York, NY 10036', 'city': 'New York'},
            'Hotel Edison': {
                'address': '228 W 47th St, New York, NY 10036', 'city': 'New York'},
            'Joanne Trattoria': {
                'address': '70 W 68th St, New York, NY 10023', 'city': 'New York'},
            'Arc Beverly': {
                'address': '121 S Spalding Dr, Beverly Hills, CA 90212', 'city': 'Beverly Hills'},
        },
    },
}


def _fail(reason):
    raise ValueError('venuepilot_' + reason)


def accounts(url):
    match = SOURCE.fullmatch(url) if isinstance(url, str) else None
    if not match:
        _fail('source_invalid')
    values = tuple(int(value) for value in match[1].split(','))
    if values != tuple(sorted(set(values))):
        _fail('source_invalid')
    return values


def family(url):
    try:
        accounts(url)
        return True
    except (ValueError, TypeError):
        return False


def subscription(page):
    """Recover identity only from VenuePilot's own complete widget contract."""
    if not isinstance(page, str) or len(page) > 5_000_000 or WIDGET not in page:
        return None
    # The documented embed is JavaScript configuration, not necessarily JSON:
    # ordinary examples use unquoted keys, single-quoted values and comments.
    # Extract only two scalar identity fields from the non-nested `general`
    # block; do not evaluate JavaScript or accept a marker elsewhere on a page.
    settings = re.search(
        r'window\.venuepilotSettings\s*=\s*\{\s*general\s*:\s*\{([^{}]{1,20000})\}\s*,\s*widgets\s*:',
        page, re.S)
    if settings is None:
        return None
    account_matches = re.findall(
        r'^\s*accountIds\s*:\s*\[([0-9\s,]{1,300})\]\s*,?\s*(?://.*)?$',
        settings[1], re.M)
    server_matches = re.findall(
        r'''^\s*server\s*:\s*(['"])(https://www\.venuepilot\.co/)\1\s*,?\s*(?://.*)?$''',
        settings[1], re.M)
    if len(account_matches) != 1 or len(server_matches) != 1:
        return None
    raw = account_matches[0]
    if not re.fullmatch(r'\s*[1-9][0-9]{0,9}(?:\s*,\s*[1-9][0-9]{0,9}){0,19}\s*', raw):
        return None
    values = [int(value.strip()) for value in raw.split(',')]
    if values != sorted(set(values)):
        return None
    # Feed registration intentionally strips fragments. Keep the provider
    # account scope in one exact canonical query parameter so source identity
    # survives registration while the outgoing GraphQL POST still targets API.
    return API + '?accountIds=' + ','.join(str(item) for item in values)


def request(account_ids, start, end):
    return {'query': QUERY, 'variables': {
        'accountIds': list(account_ids), 'startDate': start.isoformat(),
        'endDate': end.isoformat(), 'search': '', 'searchScope': '', 'limit': 500,
    }}


def valid_request(value):
    if not isinstance(value, dict) or set(value) != {'query', 'variables'} or value.get('query') != QUERY:
        return False
    variables = value.get('variables')
    if not isinstance(variables, dict) or set(variables) != {
            'accountIds', 'startDate', 'endDate', 'search', 'searchScope', 'limit'}:
        return False
    account_ids = variables.get('accountIds')
    if (not isinstance(account_ids, list) or not 1 <= len(account_ids) <= 20
            or any(type(item) is not int or not 1 <= item <= 9_999_999_999 for item in account_ids)
            or account_ids != sorted(set(account_ids))
            or variables.get('search') != '' or variables.get('searchScope') != ''
            or variables.get('limit') != 500):
        return False
    try:
        start = date.fromisoformat(variables['startDate'])
        end = date.fromisoformat(variables['endDate'])
    except (ValueError, TypeError, KeyError):
        return False
    return timedelta(days=1) <= end - start <= timedelta(days=61)


def profile(url, stored=None):
    key = accounts(url)
    base = PROFILES.get(key, {})
    value = {**base, **(stored or {})}
    if (not isinstance(value.get('timezone'), str)
            or not isinstance(value.get('publisher_url'), str)
            or not isinstance(value.get('venues'), dict)):
        _fail('profile_required')
    try:
        ZoneInfo(value['timezone'])
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError('venuepilot_profile_invalid') from exc
    publisher = urlsplit(value['publisher_url'])
    if (publisher.scheme != 'https' or not publisher.hostname or publisher.username
            or publisher.password or publisher.fragment):
        _fail('profile_invalid')
    for name, venue in value['venues'].items():
        if (not isinstance(name, str) or not name.strip() or not isinstance(venue, dict)
                or not isinstance(venue.get('address'), str) or not venue['address'].strip()
                or not isinstance(venue.get('city'), str)):
            _fail('profile_invalid')
    return value


def _time(day, value, *, optional=False):
    if optional and value in (None, ''):
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-2][0-9]:[0-5][0-9](?::[0-5][0-9])?', value):
        _fail('event_invalid')
    try:
        return datetime.fromisoformat(day + 'T' + value)
    except ValueError as exc:
        raise ValueError('venuepilot_event_invalid') from exc


def parse(payload, *, url, config):
    try:
        envelope = json.loads(payload)
        events = envelope['data']['publicEvents']
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('venuepilot_collection_invalid') from exc
    if set(envelope) != {'data'} or not isinstance(events, list) or len(events) > 500:
        _fail('collection_invalid')
    rows, identities = [], set()
    for event in events:
        if not isinstance(event, dict):
            _fail('event_invalid')
        identity = event.get('id')
        title = event.get('name')
        day = event.get('date')
        venue = event.get('venue')
        if (not isinstance(identity, int) or identity <= 0 or identity in identities
                or not isinstance(title, str) or not title.strip()
                or not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)
                or not isinstance(venue, dict) or not isinstance(venue.get('name'), str)):
            _fail('event_invalid')
        identities.add(identity)
        details = config['venues'].get(venue['name'])
        if not details:
            _fail('venue_unreviewed')
        starts = _time(day, event.get('startTime'))
        ends = _time(day, event.get('endTime'), optional=True)
        if ends is not None and ends < starts:
            ends += timedelta(days=1)
        event_url = config['publisher_url'] + '#/events/' + str(identity)
        item = record(title, starts.isoformat(), ends.isoformat() if ends else None,
                      venue['name'], details['address'], details['city'], event_url,
                      'venuepilot:' + str(identity), tz=config['timezone'])
        if item is None:
            continue
        item['timezone'] = config['timezone']
        item['description'] = description(event.get('description') or '')
        images = event.get('images')
        images = [] if images is None else images
        if not isinstance(images, list) or len(images) > 100 or any(not isinstance(image, str) for image in images):
            _fail('event_invalid')
        image = event.get('highlightedImage') or (images[0] if images else '')
        if image:
            from roomquest.preview_worker import event_image
            normalized = event_image(image, event_url)
            if normalized:
                item['image_url'] = normalized
        rows.append(item)
    return sorted(rows, key=lambda item: (item['starts_at'], item['id']))


def collect(source, fetch, *, stored=None, today=None, deadline_at=None):
    url = source.get('feed_url')
    if (source.get('platform_adapter') != 'venuepilot' or source.get('kind') != 'json'):
        _fail('source_invalid')
    account_ids = accounts(url)
    config = profile(url, stored)
    today = today or datetime.now(ZoneInfo(config['timezone'])).date()
    payload = fetch(API, 'application/json', calendar_json=request(account_ids, today, today + timedelta(days=61)))
    return parse(payload, url=url, config=config)
