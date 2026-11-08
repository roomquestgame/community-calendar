"""Reviewed campus locations and Raleigh wall-clock times from NCMA."""

from datetime import datetime, timezone
from html import escape
import re
from urllib.parse import urlsplit

from roomquest.mapsee_adapter import plain, timestamp

KEY = 'municipal_mapsee_42223f3cfcfe33208ed63601'
ROOT = 'https://ncartmuseum.org'
ZONE = 'America/New_York'
CAMPUS_VENUES = {
    2015: 'west-building-ncma-cafe',
    2023: 'east-building-studios',
    2025: 'west-building',
    2028: 'east-building-secu-auditorium',
    2035: 'museum-park-welcome-center',
    2048: 'east-building',
    2105: 'east-building-level-b',
    2318: 'museum-park',
    2324: 'east-building-lobby-vestibulo-del-edificio-este',
    2329: 'museum-park-ellipse',
    3167: 'west-building-lobby',
}


def review(payload):
    """Keep campus occurrences with an exact publisher venue and known time format."""
    events = []
    held = 0
    for item in payload['events']:
        if not isinstance(item, dict):
            raise ValueError('invalid_calendar_record')
        if item.get('status') != 'publish':
            continue
        venue = item.get('venue')
        venue = venue if isinstance(venue, dict) else {}
        slug = CAMPUS_VENUES.get(venue.get('id'))
        label = plain(venue.get('venue'))
        url = urlsplit(item.get('url') or '')
        if (not slug or slug != venue.get('slug') or venue.get('url') != f'{ROOT}/venue/{slug}/'
                or not label or url.scheme != 'https' or url.netloc != 'ncartmuseum.org'
                or url.query or url.fragment
                or not re.fullmatch(r'/event/[a-z0-9-]+/(?:[0-9]{4}-[0-9]{2}-[0-9]{2}/)?', url.path)
                or not str(item.get('id', '')).isdigit()):
            held += 1
            continue
        street = plain(venue.get('address'))
        if street and not re.fullmatch(r'2110 blue ridge (?:rd\.?|road)', street, re.I):
            held += 1
            continue
        schedule = {}
        for field in ('start_date', 'end_date'):
            wall = item.get(field)
            if not isinstance(wall, str) or datetime.fromisoformat(wall).tzinfo is not None:
                raise ValueError('publisher_schedule_conflict')
            instant = timestamp(wall, ZONE).astimezone(timezone.utc)
            zone = item.get('timezone')
            utc = item.get('utc_' + field)
            if not ((zone == 'UTC+0' and wall == utc)
                    or (zone == ZONE and utc and timestamp(utc, 'UTC') == instant)):
                raise ValueError('publisher_schedule_conflict')
            schedule['utc_' + field] = instant.isoformat()
        description = item.get('description') or ''
        if not isinstance(description, str):
            raise ValueError('invalid_wordpress_description')
        events.append(dict(item, **schedule, timezone=ZONE,
                           venue={'venue': 'North Carolina Museum of Art', 'address': '2110 Blue Ridge Road',
                                  'city': 'Raleigh', 'state': 'NC', 'zip': '27607'},
                           description=f'<p>Location within the museum: {escape(label)}</p>{description}'))
    return dict(payload, events=events), held
