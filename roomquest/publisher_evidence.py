"""Evidence from already-fetched publisher content; never a fetch/crawl policy."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

DETAILS_VERSION = 'publisher_event_details_v1'
IMAGE_VERSION = 'publisher_event_candidates_v1'


def family(source_key, event_url):
    """Bind an enrolled publisher family to its own canonical event link."""
    try:
        p = urlsplit(event_url)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.fragment:
            return None
        if (re.fullmatch(r'mycountyparks_ia_[a-z_]+', source_key or '')
                and p.hostname == 'www.mycountyparks.com'
                and re.fullmatch(r'/County/[^/]+/Park/[^/]+/Events/[1-9][0-9]{0,7}/[^/]+/?', p.path)
                and not p.query):
            return 'mycountyparks'
        if (source_key == 'bellevue_times_ne' and p.hostname == 'bellevuetimes.com'
                and p.path.startswith('/events/') and re.fullmatch(r'occurrence=20[0-9]{6}T[0-9]{6}', p.query)):
            return 'bellevue_times'
        if (source_key == 'rosemont_of_virginia' and p.hostname == 'rosemontofvirginia.com'
                and re.fullmatch(r'/event/[a-z0-9-]+/?', p.path) and not p.query):
            return 'rosemont'
        if (source_key == 'chase_city_chamber_va' and p.hostname == 'chasecitychamber.com'
                and re.fullmatch(r'/upcoming-events/[a-z0-9-]+/?', p.path) and not p.query):
            return 'chase_city_chamber'
        if (re.fullmatch(r'south_carolina_parks_[1-9][0-9]{0,9}', source_key or '')
                and p.hostname == 'southcarolinaparks.com'
                and re.fullmatch(r'/products/[1-9][0-9]{0,9}', p.path) and not p.query):
            return 'south_carolina_parks'
    except (TypeError, ValueError):
        pass
    return None


def image_url(value, publisher):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
                or p.query or p.fragment or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)
                or '..' in p.path.split('/')):
            return None
        if publisher == 'mycountyparks':
            return value if (p.hostname == 'content.mycountyparks.com'
                             and p.path.startswith('/Production/RelatedItem/Content/')) else None
        if publisher == 'bellevue_times':
            return value if (p.hostname == 'bellevuetimes.com' and p.path.startswith('/wp-content/uploads/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'rosemont':
            return value if (p.hostname == 'rosemontofvirginia.com'
                             and p.path.startswith('/wp-content/uploads/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)
                             and not re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', p.path, re.I)) else None
        if publisher == 'chase_city_chamber':
            return value if (p.hostname == 'images.squarespace-cdn.com'
                             and p.path.startswith('/content/v1/64921bef4a756810ab11ec54/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'south_carolina_parks':
            return value if (p.hostname == 'southcarolinaparks.com'
                             and not p.path.lower().startswith(('/images/', '/logo', '/favicon'))
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
    except ValueError:
        pass
    return None


def attach(item, source_key, *, facts=None, candidate=None, evidence_url=None):
    publisher = family(source_key, item['event_url'])
    if not publisher:
        raise ValueError('publisher_evidence_identity_mismatch')
    item['details_extractor_version'] = DETAILS_VERSION
    item['details_evidence_url'] = item['event_url']
    item['publisher_details'] = {key: value for key, value in (facts or {}).items() if value}
    item['image_extractor_version'] = IMAGE_VERSION
    if candidate := image_url(candidate, publisher):
        item['image_url'] = candidate
        item['image_provenance'] = IMAGE_VERSION
        item['image_evidence_url'] = evidence_url or item['event_url']
    return item
