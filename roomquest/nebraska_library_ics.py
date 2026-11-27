"""Normalize public programs from two reviewed Nebraska LibCal feeds.

The display venue is reviewed enrichment.  ``collector_event_content_v1`` is
deliberately attached before that enrichment and contains only facts supplied
by the individual VEVENT, so a library/provider label change cannot churn the
event fingerprint.
"""
from datetime import datetime
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from icalendar import Calendar

from roomquest.ics_adapter import parse
from roomquest.mapsee_adapter import plain, timestamp
from roomquest.mycountyparks import cancelled

SOURCES = {
    'bellevue_public_library_ne': 'https://bellevue-lib.libcal.com/ical_subscribe.php?src=p&cid=11232',
    'papillion_public_library_ne': 'https://papillion.libcal.com/ical_subscribe.php?src=p&cid=13954',
}

BELLEVUE = ('Bellevue Public Library', '2206 Longo Drive, Bellevue, NE 68005', 'Bellevue')
SUMP = ('Sump Memorial Library', '222 N Jefferson Street, Papillion, NE 68046', 'Papillion')
LANDING = ('Digital Library at Papillion Landing', '1046 W Lincoln Street, Papillion, NE 68046', 'Papillion')
BELLEVUE_ROOMS = {'room 1', 'room 2', 'conference room', 'teen room', 'quiet reading room', 'lobby'}
NON_PROGRAM = re.compile(r'^(?:outside group|(?:private )?(?:room )?(?:booking|reservation)|closed)(?:\b|$)', re.I)
ZONE = 'America/Chicago'
MAX_DESCRIPTION = 12000


def _venue(source_key, location):
    parts = [part.strip().casefold() for part in location.split(',')]
    if source_key == 'bellevue_public_library_ne':
        return BELLEVUE if parts and all(part in BELLEVUE_ROOMS for part in parts) else None
    branches = {part for part in parts if part in {'sump memorial library', 'digital library at papillion landing'}}
    if branches == {'sump memorial library'}:
        return SUMP
    if branches == {'digital library at papillion landing'}:
        return LANDING
    return None


def validate(source):
    url = SOURCES.get(source.get('source_key'))
    if not url or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
                   source.get('timezone')) != (url, 'ical', 'ical', 'America/Chicago'):
        raise ValueError('unregistered_nebraska_library')
    return url


def _narrative(value):
    from roomquest.event_description import description
    text = description(str(value or ''), limit=MAX_DESCRIPTION + 1)
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('publisher_description_limit')
    return text


def _categories(event):
    values = event.get('CATEGORIES', [])
    values = values if isinstance(values, list) else [values]
    labels = []
    for value in values:
        for label in getattr(value, 'cats', [value]):
            label = plain(label)[:100]
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= 20:
                return labels
    return labels


def _original_events(calendar):
    """Return one immutable original-fact record per publisher UID.

    An RRULE master safely supplies the same facts to its expanded occurrences.
    If a feed starts publishing occurrence overrides with different facts, hold
    it rather than attaching the master facts to the wrong occurrence.
    """
    from roomquest.preview_worker import calendar_image

    result = {}
    for event in calendar.walk('VEVENT'):
        uid = str(event.get('UID', ''))
        if not uid:
            raise ValueError('nebraska_library_event_identity_missing')
        facts = {
            'description': _narrative(event.get('DESCRIPTION', '')),
            'meeting_location': plain(event.get('LOCATION', '')),
            'publisher_status': plain(event.get('STATUS', 'scheduled')).casefold() or 'scheduled',
            'publisher_categories': _categories(event),
            'source_image_url': calendar_image(event),
        }
        prior = result.get(uid)
        if prior is not None and prior != facts:
            raise ValueError('nebraska_library_recurrence_original_conflict')
        result[uid] = facts
    return result


def _local(value):
    parsed = timestamp(value, ZONE)
    if parsed is None or not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError('nebraska_library_schedule_conflict')
    return parsed.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None).isoformat(timespec='seconds')


def _attach_original_content(row, facts):
    original = {
        'title': row['title'], 'description': facts['description'],
        'is_all_day': False, 'starts_at_local': _local(row['starts_at']),
        'ends_at_local': _local(row['ends_at']) if row.get('ends_at') else None,
        'source_timezone': ZONE, 'event_url': row['event_url'],
        'meeting_location': facts['meeting_location'],
        'publisher_status': facts['publisher_status'],
        'attendance_mode': 'in_person',
        'publisher_categories': facts['publisher_categories'],
        'source_image_url': facts['source_image_url'],
    }
    row['collector_event_content_v1'] = {
        'version': 1, 'event_id': row['id'],
        'facts': {name: value for name, value in original.items()
                  if value is not None and value != '' and value != []},
    }


def collect(source, payload):
    url = validate(source)
    source_key = source['source_key']
    calendar = Calendar.from_ical(payload)
    original = _original_events(calendar)
    private_ids = {
        str(event.get('UID', ''))
        for event in calendar.walk('VEVENT')
        if str(event.get('CLASS', 'PUBLIC')).strip().upper() != 'PUBLIC'
    }
    event_link = re.compile(r'https://' + re.escape(urlsplit(url).netloc) + r'/event/[1-9][0-9]*')
    records = parse(payload, {'source_key': source_key, 'url': url}, legacy=True, include_description=True)
    result = []
    for row in records:
        venue = _venue(source_key, row['venue_name'])
        if (not venue or row['id'].split('__', 1)[0] in private_ids
                or not event_link.fullmatch(row['event_url'] or '')
                or NON_PROGRAM.match(row['title']) or cancelled(row['title'], row['description'])):
            continue
        name, address, city = venue
        uid = row['id'].split('__', 1)[0]
        if uid not in original:
            raise ValueError('nebraska_library_event_identity_missing')
        _attach_original_content(row, original[uid])
        row.update(venue_name=name, venue_address=address, venue_city=city,
                   description=original[uid]['description'][:2000], lat=None, lng=None)
        result.append(row)
    return result
