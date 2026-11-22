"""Source-scoped address completion; coordinates remain owned by Geocodio.

Sweet Briar campus address: https://www.sbc.edu/about/our-campus-location/maps-directions/
Named buildings: https://www.sbc.edu/live/files/2783-280224-sbc-campus-map-with-keypdf
Mills Chapel address: https://www.christthesaviourorthodox.org/contact
Prothro/Upchurch: official athletics campus map and Sports Medicine Manual.
Reviewed 2026-11-21. Ben permits educated venue-to-street address matches.
The shared campus street address is not a claim of rooftop coordinates.
"""
from hashlib import md5

SWEET_BRIAR = 'https://sbc.libcal.com/ical_subscribe.php?src=p&cid=8406'
SWEET_BRIAR_KEY = 'municipal_' + md5(('feed_registration:' + SWEET_BRIAR).encode()).hexdigest()[:24]
SWEET_BRIAR_VENUES = {
    'mills chapel',
    'upchurch field house (all)',
    'upchurch field house',
    'prothro natatorium (all lanes)',
    'prothro natatorium',
}


def complete_address(row, source):
    # CSHC publishes the complete venue/street/town/postcode in LOCATION.
    # The legacy normalizer only recognizes numbered US addresses. Retain this
    # publisher street evidence without assigning a venue point or guessing one.
    hockey = 'https://cambridgesouthhockeyclub.co.uk/matches/cshc_matches.ics'
    if (source.get('url', source.get('feed_url')) == hockey
            and source.get('source_key') == 'municipal_' + md5(('feed_registration:' + hockey).encode()).hexdigest()[:24]
            and not row.get('venue_address')):
        import re
        location = str(row.get('venue_name') or '').strip()
        if location.count(',') >= 2 and re.search(r',\s*[A-Z]{1,2}[0-9][A-Z0-9]?\s+[0-9][A-Z]{2}$', location):
            row['venue_address'] = location
        return
    if (source.get('url', source.get('feed_url')) != SWEET_BRIAR
            or source.get('source_key') != SWEET_BRIAR_KEY):
        return
    venue = ' '.join(str(row.get('venue_name') or '').split()).casefold()
    address = ' '.join(str(row.get('venue_address') or '').split()).casefold()
    # Preserve a fuller publisher address, real GEO, unknown and off-campus sites.
    if venue not in SWEET_BRIAR_VENUES or address not in ('', venue):
        return
    if row.get('lat') is not None or row.get('lng') is not None:
        return
    row['venue_address'] = '134 Chapel Road, Sweet Briar, VA 24595'
    row['venue_city'] = 'Sweet Briar'


TEC_VENUES = {
    'https://thesuperradarcade.com/wp-json/tribe/events/v1/events':
        ('The Super Rad Arcade Bar', '58 9th St.', 'Lynchburg', 'VA', '24504'),
    'https://www.lucasoilstadium.com/wp-json/tribe/events/v1/events':
        ('Lucas Oil Stadium', '500 S. Capitol Avenue', 'Indianapolis', 'IN', '46225'),
}


def complete_tec_venues(payload, source):
    """Complete reviewed on-site calendars without altering an explicit venue.

    Super Rad's event description supplies the Where? block and full address.
    Lucas Oil's official homepage labels the feed Upcoming Stadium Events and
    publishes 500 S. Capitol Avenue, Indianapolis, IN 46225 in its footer.
    These source-scoped address inferences were reviewed 2026-11-21. No GEO.
    """
    import re
    from urllib.parse import urlsplit
    from roomquest.mapsee_adapter import plain
    url = source.get('url', source.get('feed_url'))
    profile = TEC_VENUES.get(url)
    expected = 'municipal_' + md5(('feed_registration:' + str(url)).encode()).hexdigest()[:24]
    if not profile or source.get('source_key') != expected:
        return payload
    name, street, city, state, postal = profile
    events = []
    for event in payload.get('events', []):
        if not isinstance(event, dict):
            events.append(event)
            continue
        text = plain(event.get('description'))
        event_url = urlsplit(event.get('url') or '')
        eligible = (not event.get('venue') and event_url.scheme == 'https'
                    and event_url.netloc == urlsplit(url).netloc
                    and event_url.path.startswith('/event/')
                    and not re.search(r'\b(?:off[- ]?site|off[- ]?campus|virtual event|online event|webinar)\b', text, re.I))
        if city == 'Lynchburg':
            eligible = eligible and bool(re.search(
                r'Where\?\s+The Super Rad Arcade Bar\s+58 9th St\.,\s+Lynchburg,\s+Virginia 24504', text))
        if eligible:
            event = {**event, 'venue': {'venue': name, 'address': street,
                                      'city': city, 'state': state, 'zip': postal}}
        events.append(event)
    return {**payload, 'events': events}
