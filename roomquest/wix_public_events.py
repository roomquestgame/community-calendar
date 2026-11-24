"""Generic first-party Wix Events public warmup-data extractor.

Only an explicitly complete Wix Events widget can become a snapshot. Wix CMS
custom collections, login-only Wix APIs and infinite-scroll widgets need their
own verified source contract. No guessed pages, auth tokens, client IDs or
partial list prefixes are returned.
"""
from datetime import date, datetime, timedelta, timezone
from html import unescape
import json
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup

WIX_EVENTS = '140603ad-af8d-84a5-2c80-a0f60cb47351'
MAX_HTML = 3_000_000
MAX_EVENTS = 500
MAX_DAYS = 60
UUID = re.compile(r'^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$', re.I)
SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', re.I)


def _fail(reason):
    raise ValueError('wix_public_' + reason)


def _text(value):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', value))).strip()


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        _fail('window_invalid')


def _timestamp(raw):
    if not isinstance(raw, str) or not re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?'
            r'(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', raw):
        _fail('schedule_invalid')
    try:
        result = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        _fail('schedule_invalid')
    if result.utcoffset() is None:
        _fail('schedule_invalid')
    return result.astimezone(timezone.utc)


def _observed_links(soup, base_url):
    base = urlsplit(base_url)
    links = {}
    for node in soup.select('a[href]'):
        url = urljoin(base_url, node.get('href', ''))
        p = urlsplit(url)
        if (p.scheme != 'https' or p.hostname != base.hostname or p.query
                or p.fragment or not p.path.startswith('/event-details/')):
            continue
        slug = p.path.rsplit('/', 1)[-1]
        if not SLUG.fullmatch(slug):
            continue
        title = _text(node.get_text(' ', strip=True))
        if title:
            links.setdefault(slug, set()).add((title, url))
    return links


def _widget_events(payload):
    if not isinstance(payload, str) or len(payload.encode('utf-8')) > MAX_HTML:
        _fail('payload_invalid')
    soup = BeautifulSoup(payload, 'html.parser')
    tags = soup.select('script#wix-warmup-data[type="application/json"]')
    if len(tags) != 1:
        _fail('widget_not_exposed')
    try:
        obj = json.loads(tags[0].string or tags[0].get_text())
        app = obj['appsWarmupData'][WIX_EVENTS]
    except (TypeError, ValueError, KeyError, RecursionError):
        _fail('widget_invalid')
    if not isinstance(app, dict):
        _fail('widget_invalid')
    all_events = {}
    widgets = 0
    for name, widget in app.items():
        if not name.startswith('widget') or not isinstance(widget, dict):
            continue
        box = widget.get('events')
        if not isinstance(box, dict) or not isinstance(box.get('events'), list):
            continue
        records = box['events']
        # The publisher's full count must be present and agree exactly.
        # A blank JavaScript pager or just the first 6 tiles is not a source.
        total = box.get('totalCount', box.get('total'))
        if (type(total) is not int or total < 0 or total != len(records)
                or box.get('hasMore') is True or len(records) > MAX_EVENTS):
            _fail('pagination_unverified')
        widgets += 1
        for item in records:
            if not isinstance(item, dict) or not UUID.fullmatch(str(item.get('id', ''))):
                _fail('event_identity_invalid')
            previous = all_events.get(item['id'])
            if previous is not None and previous != item:
                _fail('event_identity_conflict')
            all_events[item['id']] = item
            if len(all_events) >= MAX_EVENTS:
                _fail('event_limit')
    if not widgets:
        _fail('widget_not_exposed')
    return soup, tuple(all_events.values())


def extract(profile, html, start, end):
    """Complete source-bound Wix Events snapshot, not a Wix CMS guesser."""
    first, last = _date(start), _date(end)
    if last < first or (last - first).days >= MAX_DAYS:
        _fail('window_invalid')
    base_url = profile.get('publisher_url')
    if not isinstance(base_url, str):
        _fail('source_invalid')
    base = urlsplit(base_url)
    if (base.scheme != 'https' or not base.hostname or base.username or base.password
            or not isinstance(profile.get('country'), str)
            or not re.fullmatch(r'[A-Z]{2}', profile['country'])):
        _fail('source_invalid')
    soup, events = _widget_events(html)
    links = _observed_links(soup, base_url)
    result = {}
    for item in events:
        if item.get('status') != 0:
            continue
        title = _text(item.get('title'))
        slug = item.get('slug')
        if not title or not isinstance(slug, str) or not SLUG.fullmatch(slug):
            _fail('event_identity_invalid')
        matches = [url for label, url in links.get(slug, ())
                   if _text(label).casefold() == title.casefold()]
        if len(set(matches)) != 1:
            _fail('event_link_unverified')
        scheduling = item.get('scheduling')
        config = scheduling.get('config') if isinstance(scheduling, dict) else None
        location = item.get('location')
        address = location.get('fullAddress') if isinstance(location, dict) else None
        registration = item.get('registration')
        if (not isinstance(config, dict) or config.get('scheduleTbd') is not False
                or not isinstance(location, dict) or location.get('tbd') is not False
                or not isinstance(address, dict)
                or not isinstance(registration, dict)):
            _fail('event_facts_incomplete')
        # Public visibility is not permission to expose private/member events.
        if registration.get('restrictedTo') != 1:
            continue
        if address.get('country') != profile['country']:
            _fail('country_mismatch')
        venue = _text(location.get('name'))
        street = _text(location.get('address'))
        formatted = _text(address.get('formattedAddress'))
        city = _text(address.get('city'))
        if (not venue or not street or street != formatted or not city
                or not _text(address.get('postalCode'))):
            _fail('venue_unresolved')
        try:
            zone = ZoneInfo(config['timeZoneId'])
        except (KeyError, TypeError, ZoneInfoNotFoundError):
            _fail('timezone_invalid')
        begins = _timestamp(config.get('startDate'))
        end_raw = config.get('endDate')
        finishes = _timestamp(end_raw) if end_raw else None
        if finishes is not None and finishes < begins:
            _fail('end_before_start')
        local = begins.astimezone(zone)
        if not first <= local.date() <= last:
            continue
        event_url = matches[0]
        image = item.get('mainImage') or {}
        photo = image.get('url') if isinstance(image, dict) else None
        if not isinstance(photo, str) or not photo.startswith('https://'):
            photo = None
        row = {
            'id': 'wix:' + item['id'].lower(), 'title': title,
            'starts_at': begins.isoformat(), 'ends_at': finishes.isoformat() if finishes else None,
            'event_url': event_url, 'venue_name': venue, 'venue_address': street,
            'venue_city': city, 'timezone': zone.key,
            'description': _text(item.get('description'))[:12000],
            'image_url': photo, 'wix_public_adapter_version': 1,
        }
        result[row['id']] = row
    return {'complete': True, 'widget_count': len(events),
            'events': sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))}
