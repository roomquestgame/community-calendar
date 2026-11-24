"""Config-driven public WordPress custom post type event extraction.

The REST index and event-specific fields must be independently verified.
The WordPress post's publication/modified date is NOT an event date. This
module cannot register arbitrary custom post types as calendar sources or
publish a partial paginated listing.
"""
from datetime import date, datetime, timedelta, timezone
from html import unescape
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_DAYS = 60
MAX_PAGES = 120
MAX_POSTS = 4500
FIELD = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*){0,5}$')
NON_EVENT_FIELDS = frozenset({'date', 'date_gmt', 'modified', 'modified_gmt'})


def _fail(code):
    raise ValueError('wordpress_custom_' + code)


def _text(value):
    if isinstance(value, dict):
        value = value.get('rendered', '')
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


def _path(value, field):
    if not isinstance(field, str) or not FIELD.fullmatch(field):
        _fail('mapping_invalid')
    for part in field.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _date(value):
    try:
        result = date.fromisoformat(str(value))
        return result
    except (TypeError, ValueError):
        _fail('window_invalid')


def windows(start, end):
    start, end = _date(start), _date(end)
    if end < start or (end - start).days >= MAX_DAYS:
        _fail('window_invalid')
    return start, end


def _route(url):
    """Accept only an explicitly discovered WP public v2 custom event route."""
    if not isinstance(url, str):
        _fail('route_invalid')
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment:
            _fail('route_invalid')
        args = parse_qsl(p.query, keep_blank_values=True)
        if any(k.lower() in ('page', 'per_page') for k, _ in args):
            _fail('route_invalid')
        segments = p.path.rstrip('/').split('/')
        standard = len(segments) >= 4 and segments[-3:-1] == ['wp', 'v2']
        legacy = any(k == 'rest_route' and re.fullmatch(r'/wp/v2/[a-z0-9_-]+', v)
                     for k, v in args)
        if not ((standard and segments[-4] == 'wp-json'
                 and re.fullmatch(r'[a-z0-9_-]+', segments[-1])) or legacy):
            _fail('route_invalid')
        return p
    except (ValueError, TypeError):
        _fail('route_invalid')


def page_url(route_url, page, *, per_page=100):
    original = _route(route_url)
    if (type(page) is not int or not 1 <= page <= MAX_PAGES
            or type(per_page) is not int or not 1 <= per_page <= 100):
        _fail('page_invalid')
    query = parse_qsl(original.query, keep_blank_values=True)
    query += [('page', str(page)), ('per_page', str(per_page))]
    return urlunsplit(original._replace(query=urlencode(query, safe='/')))


def _instant(value, zone):
    if not isinstance(value, str) or not re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?'
            r'(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?', value):
        _fail('event_time_missing')
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _fail('event_time_missing')
    if moment.tzinfo is None:
        try:
            tz = ZoneInfo(zone)
        except (TypeError, ZoneInfoNotFoundError):
            _fail('timezone_invalid')
        moment = moment.replace(tzinfo=tz)
        if (moment.utcoffset() != moment.replace(fold=1).utcoffset()
                or moment.astimezone(timezone.utc).astimezone(tz)
                   .replace(tzinfo=None) != moment.replace(tzinfo=None)):
            _fail('time_ambiguous')
    return moment.astimezone(timezone.utc)


def extract(profile, pages, total_pages, start, end):
    """Project only a fully paginated, publisher-reviewed custom event route."""
    first, last = windows(start, end)
    route = profile.get('route_url')
    root = _route(route)
    source = urlsplit(profile.get('publisher_url', ''))
    config = profile.get('fields')
    if (source.scheme != 'https' or not source.hostname
            or root.hostname != source.hostname
            or not isinstance(config, dict)
            or not isinstance(profile.get('timezone'), str)
            or not isinstance(profile.get('country'), str)
            or not re.fullmatch(r'[A-Z]{2}', profile['country'])
            or not isinstance(profile.get('post_type'), str)
            or not re.fullmatch(r'[a-z0-9_-]{1,60}', profile['post_type'])
            or type(total_pages) is not int or not 1 <= total_pages <= MAX_PAGES
            or not isinstance(pages, list) or len(pages) != total_pages):
        _fail('source_or_pagination_invalid')
    required = ('start', 'venue', 'address')
    if any(not isinstance(config.get(k), str) or not FIELD.fullmatch(config[k])
           for k in required) or config['start'].casefold() in NON_EVENT_FIELDS:
        _fail('mapping_invalid')
    try:
        venue_zone = ZoneInfo(profile['timezone'])
    except (TypeError, ZoneInfoNotFoundError):
        _fail('timezone_invalid')
    if any(not isinstance(page, list) or len(page) > 100 for page in pages):
        _fail('page_invalid')
    posts = {}
    for page in pages:
        for post in page:
            if not isinstance(post, dict) or type(post.get('id')) is not int or post['id'] <= 0:
                _fail('post_invalid')
            previous = posts.get(post['id'])
            if previous is not None and previous != post:
                _fail('post_conflict')
            posts[post['id']] = post
            if len(posts) > MAX_POSTS:
                _fail('post_limit')
    if (len(posts) == MAX_POSTS or
            any(len(page) == 100 for page in pages) and total_pages == MAX_PAGES):
        _fail('pagination_limit')
    rows = {}
    for post in posts.values():
        if post.get('status') != 'publish':
            continue
        if post.get('type') != profile['post_type']:
            _fail('post_type_mismatch')
        title = _text(post.get('title'))
        page_link = post.get('link')
        parts = urlsplit(page_link) if isinstance(page_link, str) else None
        if (not title or not parts or parts.scheme != 'https'
                or parts.hostname != source.hostname or not parts.path or parts.username
                or parts.password):
            _fail('event_identity_invalid')
        occurrences = _path(post, config['occurrences']) if config.get('occurrences') else [post]
        if not isinstance(occurrences, list) or not 1 <= len(occurrences) <= 300:
            _fail('occurrences_invalid')
        for item in occurrences:
            if not isinstance(item, dict):
                _fail('occurrences_invalid')
            starts = _instant(_path(item, config['start']), profile['timezone'])
            # The *local* publisher date controls the 60-day inclusion test.
            local = starts.astimezone(venue_zone)
            if not first <= local.date() <= last:
                continue
            end_value = _path(item, config['end']) if config.get('end') else None
            finish = _instant(end_value, profile['timezone']) if end_value else None
            if finish is not None and finish < starts:
                _fail('end_before_start')
            name = _text(_path(item, config['venue']))
            address = _text(_path(item, config['address']))
            town = _text(_path(item, config['city'])) if config.get('city') else ''
            if not town and profile.get('home_city') and re.search(
                    r'\b' + re.escape(profile['home_city']) + r'\b', address, re.I):
                town = profile['home_city']
            if (not name or not address or not town or len(address) > 400
                    or len(title) > 200):
                _fail('venue_unresolved')
            rid = 'wordpress:' + profile['post_type'] + ':' + str(post['id']) + ':' + starts.isoformat()
            if rid in rows:
                _fail('occurrence_conflict')
            rows[rid] = {'id': rid, 'title': title, 'starts_at': starts.isoformat(),
                         'ends_at': finish.isoformat() if finish else None,
                         'event_url': page_link,
                         'venue_name': name, 'venue_address': address, 'venue_city': town,
                         'timezone': profile['timezone'],
                         'description': _text(post.get('content'))[:12000],
                         'wordpress_custom_adapter_version': 1}
    return {'complete': True, 'page_count': total_pages, 'post_count': len(posts),
            'events': sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))}
