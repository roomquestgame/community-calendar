"""Prepare the official ODU school-wide CampusGroups iCalendar snapshot."""
from datetime import datetime, timedelta, timezone
import re

KEY = 'municipal_2f700480d7f18ef5e8866885'
URL = 'https://odu.campusgroups.com/ical/odu/ical_odu.ics'
BUILDINGS = {
    'batten arts and letters': '4401 Hampton Blvd, Norfolk, VA 23508',
    'chartway arena': '4320 Hampton Blvd, Norfolk, VA 23508',
    'constant hall': '1221 W. 49th Street, Norfolk, VA 23508',
    'webb center': '1301 W. 49th Street, Norfolk, VA 23508',
}
STREET = re.compile(r'(?:^|,\s*)\d{1,6}\s+[A-Za-z][^,]+,\s*[^,]+,\s*VA\s+\d{5}\b', re.I)
RESTRICTED = re.compile(r'\b(?:students?\s+only|members?\s+only|invitation\s+only|private\s+event)\b', re.I)
RECURRENCE = ('RRULE', 'RDATE', 'EXDATE', 'EXRULE', 'RECURRENCE-ID')


def filter_snapshot(calendar, source, *, now=None):
    if source.get('url') != URL or source.get('timezone') != 'America/New_York':
        raise ValueError('unregistered_odu_campusgroups_source')
    now = now or datetime.now(timezone.utc)
    stop = now + timedelta(days=60)
    addresses = {}
    keep = []
    events = calendar.walk('VEVENT')
    if len(events) > 5000:
        raise ValueError('source_record_limit')
    for event in events:
        if event.errors or any(event.get(key) for key in RECURRENCE):
            raise ValueError('unsupported_odu_campusgroups_occurrence')
        if str(event.get('STATUS', '')).upper() in {'CANCELLED', 'CANCELED'}:
            continue
        start = event.decoded('DTSTART')
        if not isinstance(start, datetime) or start.tzinfo is None or not now <= start < stop:
            continue
        venue = str(event.get('LOCATION', '')).strip()
        if RESTRICTED.search(str(event.get('DESCRIPTION', ''))) or 'sign in to download' in venue.casefold():
            continue
        address = venue if STREET.search(venue) else next(
            (address for name, address in BUILDINGS.items()
             if re.match(re.escape(name) + r'\b', venue, re.I)), '')
        if address and event.get('UID'):
            identity = str(event['UID'])
            if identity in addresses:
                raise ValueError('conflicting_odu_campusgroups_occurrence')
            addresses[identity] = address
            keep.append(event)
    calendar.subcomponents = [part for part in calendar.subcomponents if part.name != 'VEVENT'] + keep
    return addresses
