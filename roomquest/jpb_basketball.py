"""Review the Joan Perry Brock Center's The Events Calendar home games."""
import re

from roomquest.mapsee_adapter import plain, timestamp
from roomquest.publisher_evidence import attach
from roomquest.mycountyparks import cancelled

KEY = 'longwood_basketball_va'
HOST = 'www.jpbcenter.com'
URL = f'https://{HOST}/wp-json/tribe/events/v1/events'
ZONE = 'America/New_York'
EVENT_URL = re.compile(r'https://www[.]jpbcenter[.]com/event/[a-z0-9]+(?:-[a-z0-9]+)*/')
PHOTO_URL = re.compile(r'https://www[.]jpbcenter[.]com/wp-content/uploads/20\d{2}/[01]\d/[A-Za-z0-9_.-]+[.](?:jpe?g|png|webp)', re.I)
VENUE = 'Joan Perry Brock Center'
ADDRESS = '405 Spruce Street'


def review(payload):
    events = []
    for item in payload['events']:
        if not isinstance(item, dict):
            raise ValueError('jpb_calendar_record_unverified')
        title = plain(item.get('title'))
        if (not re.match(r"Longwood University (?:Men|Women)['’]s Basketball vs\b", title, re.I)
                or item.get('status') != 'publish'
                or item.get('event_status') in ('cancelled', 'canceled', 'postponed')
                or any(item.get(k) for k in ('hide_from_listings', 'all_day', 'is_virtual', 'virtual'))
                or cancelled(title, plain(item.get('description')))):
            continue
        venue = item.get('venue')
        if not isinstance(venue, dict) or (venue.get('id'), venue.get('venue')) != (
                2207, 'Farmville, Va., Joan Perry Brock Center'):
            continue
        expected = {'address': ADDRESS, 'city': 'Farmville', 'state': 'VA', 'zip': '23901'}
        if (any(venue.get(field) not in (None, '', value) for field, value in expected.items())
                or not EVENT_URL.fullmatch(item.get('url', ''))
                or not str(item.get('id', '')).isdigit()):
            raise ValueError('jpb_calendar_identity_unverified')
        if item.get('timezone') not in ('UTC', ZONE):
            raise ValueError('jpb_calendar_timezone_unverified')
        for field in ('start_date', 'end_date'):
            if (not item.get(field) or not item.get('utc_'+field)
                    or timestamp(item[field], item['timezone']) != timestamp(item['utc_'+field], 'UTC')):
                raise ValueError('jpb_calendar_schedule_conflict')
        events.append(dict(item, venue={**venue, **expected, 'venue': VENUE}))
    return dict(payload, events=events)


def evidence(row, item):
    image = item.get('image')
    row['publisher_categories'] = ['Basketball']
    return attach(row, KEY, candidate=image.get('url') if isinstance(image, dict) else None)
