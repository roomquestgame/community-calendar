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
