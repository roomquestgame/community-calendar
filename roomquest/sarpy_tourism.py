"""Normalize the official Sarpy Tourism CivicPlus calendar."""
import re

from bs4 import BeautifulSoup

from roomquest.ics_adapter import civicplus_detail_url, parse
from roomquest.mapsee_adapter import plain
from roomquest.mycountyparks import cancelled
from roomquest.reviewed_chambers import address_from_location

KEY = 'sarpy_tourism_ne'
URL = 'https://www.gosarpy.com/common/modules/iCalendar/iCalendar.aspx?catID=34&feed=calendar'


def collect(source, payload):
    if (source.get('source_key'), source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (
            KEY, URL, 'ical', 'ical', 'America/Chicago'):
        raise ValueError('unregistered_sarpy_tourism')
    records = parse(payload, {'source_key': KEY, 'url': URL}, legacy=True, include_description=True)
    result = []
    for row in records:
        uid = row['id'].split('__', 1)[0]
        if not re.fullmatch(r'[1-9][0-9]*', uid):
            continue
        description = row['description']
        detail_url = civicplus_detail_url(description, uid, URL)
        location = BeautifulSoup(row['venue_address'], 'html.parser')
        label = location.find('p')
        if not detail_url or not label:
            continue
        venue = plain(label.get_text())
        label.extract()
        address = address_from_location(plain(location.get_text(' ', strip=True)).lstrip(' -'))
        if not venue or not address or cancelled(row['title'], description):
            continue
        postal_address, city = address
        row.update(venue_name=venue, venue_address=postal_address, venue_city=city,
                   event_url=detail_url, description=plain(description.replace(detail_url, ''))[:2000],
                   lat=None, lng=None)
        result.append(row)
    return result
