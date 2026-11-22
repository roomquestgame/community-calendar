"""Collect public linked Wix Events already rendered in a reviewed listing.

No Wix API, visitor token, per-event export, or private widget state is fetched.
The caller retains the exact reviewed URL/source contract and normal transport.
"""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.preview_worker import event_image

MYTHIC = 'https://www.mythichall.com/games'
URLS = (MYTHIC,)
WIX_EVENTS = '140603ad-af8d-84a5-2c80-a0f60cb47351'
PRIVATE = re.compile(r'\bprivate\b|\binvite[ -]only\b|\bmembers[ -]only\b', re.I)


def rows(soup, url, today):
    block = soup.find('script', id='wix-warmup-data', type='application/json')
    if block is None:
        raise ValueError('wix_public_schedule_unverified')
    try:
        state = json.loads(block.string or block.get_text())
        app = state['appsWarmupData'][WIX_EVENTS]
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise ValueError('wix_public_schedule_unverified') from exc
    if not isinstance(app, dict):
        raise ValueError('wix_public_schedule_unverified')
    origin = urlsplit(url)
    linked = {}
    for anchor in soup.select('a[href]'):
        target = urlsplit(urljoin(url, anchor['href']))
        if (target.scheme != 'https' or target.netloc != origin.netloc or target.query
                or target.fragment or not re.fullmatch(r'/event-details/[a-z0-9-]+', target.path)):
            continue
        linked.setdefault(target.path.rsplit('/', 1)[-1], set()).add(plain(anchor.get_text(' ', strip=True)))
    events = []
    for name, widget in app.items():
        if not name.startswith('widget') or not isinstance(widget, dict):
            continue
        envelope = widget.get('events')
        if isinstance(envelope, dict) and isinstance(envelope.get('events'), list):
            events.extend(envelope['events'])
    if len(events) > 250:
        raise ValueError('wix_schedule_limit_exceeded')
    seen = {}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('wix_public_schedule_unverified')
        title = plain(event.get('title'))
        narrative = plain(event.get('description'))
        slug = event.get('slug')
        registration = event.get('registration') or {}
        if (not title or not isinstance(slug, str) or title not in linked.get(slug, set())
                or event.get('status') != 0 or not event.get('publishedDate')
                or not isinstance(registration, dict) or registration.get('restrictedTo') != 1
                or PRIVATE.search(title + ' ' + narrative)):
            continue
        schedule = event.get('scheduling') or {}
        config = schedule.get('config') if isinstance(schedule, dict) else None
        location = event.get('location') or {}
        if not isinstance(config, dict) or not isinstance(location, dict):
            continue
        if config.get('scheduleTbd') is not False or location.get('tbd') is not False:
            continue
        address = location.get('fullAddress') or {}
        street = plain(location.get('address'))
        venue = plain(location.get('name'))
        if (not isinstance(address, dict) or address.get('country') != 'US' or not venue
                or not street or street != plain(address.get('formattedAddress'))
                or not re.search(r'\b\d+\s+[A-Za-z]', street)
                or not address.get('city') or not address.get('postalCode')):
            continue
        try:
            zone = ZoneInfo(config['timeZoneId'])
            start = datetime.fromisoformat(config['startDate'].replace('Z', '+00:00'))
            end_raw = config.get('endDate')
            end = datetime.fromisoformat(end_raw.replace('Z', '+00:00')) if end_raw else None
        except (ValueError, KeyError, TypeError, AttributeError, ZoneInfoNotFoundError):
            continue
        if start.tzinfo is None or (end is not None and (end.tzinfo is None or end <= start)):
            continue
        if not today <= start.astimezone(zone).date() <= today + timedelta(days=60):
            continue
        # The independent public add-calendar parameters must agree with the
        # embedded UTC schedule and the record's own title and street address.
        calendar = event.get('calendarLinks') or {}
        calendar_url = calendar.get('google') if isinstance(calendar, dict) else None
        if not isinstance(calendar_url, str):
            continue
        google = urlsplit(calendar_url)
        query = parse_qs(google.query)
        dates = start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        dates += '/' + (end or start).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        if (google.hostname != 'calendar.google.com' or google.path != '/calendar/render'
                or query.get('action') != ['TEMPLATE'] or query.get('dates') != [dates]
                or query.get('text') != [title] or query.get('location') != [street]):
            continue
        identity = event.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9-]{36}', identity):
            continue
        event_url = origin._replace(path='/event-details/' + slug, query='', fragment='').geturl()
        row = record(title, start, None if config.get('endDateHidden') else end,
                     venue, street, address['city'], event_url, identity)
        if row is None:
            continue
        row['timezone'] = zone.key
        row['description'] = description(narrative)
        ticketing = registration.get('ticketing') or {}
        if isinstance(ticketing, dict) and ticketing.get('soldOut') is True:
            row['description'] = (row['description'] + '\nTickets sold out.').strip()
        main_image = event.get('mainImage') or {}
        if isinstance(main_image, dict):
            picture = event_image(main_image.get('url'), event_url)
            if picture:
                row['image_url'] = picture
        if identity in seen and seen[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        seen[identity] = row
    yield from seen.values()
