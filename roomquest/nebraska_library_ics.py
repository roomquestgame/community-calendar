"""Normalize public programs from two reviewed Nebraska LibCal feeds."""
import re
from urllib.parse import urlsplit

from icalendar import Calendar

from roomquest.ics_adapter import parse
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


def collect(source, payload):
    url = validate(source)
    source_key = source['source_key']
    private_ids = {
        str(event.get('UID', ''))
        for event in Calendar.from_ical(payload).walk('VEVENT')
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
        row.update(venue_name=name, venue_address=address, venue_city=city, lat=None, lng=None)
        result.append(row)
    return result
