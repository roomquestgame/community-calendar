"""Review Hurrdat's public WordPress events at the La Vista sports bar."""
import re

from roomquest.mapsee_adapter import plain, timestamp
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import attach

KEY = 'hurrdat_sports_bar_ne'
URL = 'https://hurrdatsportsbar.com/wp-json/tribe/events/v1/events'
ZONE = 'America/Chicago'
EVENT_URL = r'https://hurrdatsportsbar[.]com/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?'
PHOTO_URL = r'https://hurrdatsportsbar[.]com/wp-content/uploads/20\d{2}/[01]\d/[A-Za-z0-9_.-]+[.](?:jpe?g|png|webp)'


def review(payload):
    rows = []
    for item in payload['events']:
        if not isinstance(item, dict):
            raise ValueError('hurrdat_calendar_record_unverified')
        if (item.get('status') != 'publish'
                or any(item.get(k) for k in ('all_day', 'hide_from_listings', 'virtual', 'is_virtual'))
                or item.get('event_status') in ('cancelled', 'canceled', 'postponed')
                or cancelled(plain(item.get('title')), plain(item.get('description')))):
            continue
        venue = item.get('venue')
        if (not isinstance(venue, dict) or plain(venue.get('venue')) != 'Hurrdat Sports Bar & Grill – La Vista'
                or venue.get('address') != '12744 Westport Pkwy' or venue.get('state') != 'NE'
                or str(venue.get('zip')) != '68138' or venue.get('city') not in ('Omaha', 'La Vista')):
            continue
        if (not re.fullmatch(EVENT_URL, item.get('url', ''))
                or item.get('timezone') != ZONE
                or not all(item.get(field) and item.get('utc_' + field)
                           and timestamp(item[field], ZONE) == timestamp(item['utc_' + field], 'UTC')
                           for field in ('start_date', 'end_date'))):
            raise ValueError('hurrdat_schedule_or_identity_conflict')
        rows.append(dict(item, venue={**venue, 'address': '12744 Westport Pkwy Ste 1A', 'city': 'La Vista',
                                     'geo_lat': None, 'geo_lng': None}))
    return dict(payload, events=rows)


def evidence(row, item):
    image = item.get('image')
    return attach(row, KEY, candidate=image.get('url') if isinstance(image, dict) else None)
