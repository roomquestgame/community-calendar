"""Evidence from already-fetched publisher content; never a fetch/crawl policy."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

DETAILS_VERSION = 'publisher_event_details_v1'
IMAGE_VERSION = 'publisher_event_candidates_v1'

# Reviewed 2026-11-06: TEC event 7745 explicitly features attachment 7634.
# This exact vendor artwork remains a candidate subject to the normal byte probe.
ROSEMONT_REVIEWED_FEATURED_IMAGE = (
    'https://rosemontofvirginia.com/wp-content/uploads/2026/04/ShortStacked-Logo.jpg'
)


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
        chamber_hosts = {'municipal_chambermaster_bellevue_ne': 'business.bellevuenebraska.com',
                         'municipal_chambermaster_clear_lake_ia': 'members.clearlakeiowa.com'}
        if (source_key in chamber_hosts and p.hostname == chamber_hosts[source_key]
                and re.fullmatch(r'/events/details/(?:[a-z0-9-]|%[0-9A-F]{2})+-[1-9][0-9]*', p.path) and not p.query):
            return 'reviewed_chamber'
        if (source_key == 'experience_waterloo_ia' and p.hostname == 'experiencewaterloo.com'
                and re.fullmatch(r'/events/[a-z0-9-]+/', p.path) and not p.query):
            return 'waterloo'
        if (source_key == 'bellevue_times_ne' and p.hostname == 'bellevuetimes.com'
                and p.path.startswith('/events/') and re.fullmatch(r'occurrence=20[0-9]{6}T[0-9]{6}', p.query)):
            return 'bellevue_times'
        if (source_key == 'madison_county_parks_ia' and p.hostname == 'www.madisoncountyparks.org'
                and re.fullmatch(r'/calendar/[^/?#]+/?', p.path) and not p.query):
            return 'madison'
        if (source_key == 'think_iowa_city_ia' and p.hostname == 'thinkiowacity.com'
                and re.fullmatch(r'/event/[a-z0-9-]+/(?:20\d{2}-\d{2}-\d{2}/)?', p.path)
                and not p.query):
            return 'think_iowa_city'
        if (source_key == 'unleashcb_ia' and p.hostname == 'www.unleashcb.com'
                and re.fullmatch(r'/events/detail/[a-z0-9_-]+/20\d{2}-\d{2}-\d{2}/', p.path)
                and not p.query):
            return 'unleashcb'
        if (source_key == 'visit_mason_city_ia' and p.hostname == 'www.visitmasoncityiowa.com'
                and re.fullmatch(r'/20\d{2}/\d{1,2}/\d{1,2}/[1-9]\d*/[a-z0-9-]+/', p.path)
                and not p.query):
            return 'mason_city'
        if (source_key == 'rosemont_of_virginia' and p.hostname == 'rosemontofvirginia.com'
                and re.fullmatch(r'/event/[a-z0-9-]+/?', p.path) and not p.query):
            return 'rosemont'
        if (source_key == 'chase_city_chamber_va' and p.hostname == 'chasecitychamber.com'
                and re.fullmatch(r'/upcoming-events/[a-z0-9-]+/?', p.path) and not p.query):
            return 'chase_city_chamber'
        if (source_key == 'south_hill_town_va' and p.netloc == 'www.southhillva.gov'
                and p.path == '/calendar.php' and not p.query):
            return 'south_hill_town'
        if (source_key == 'south_hill_chamber_va' and p.netloc == 'members.southhillchamber.com'
                and re.fullmatch(r'/calendar/Details/[a-z0-9-]+-[1-9][0-9]*', p.path) and not p.query):
            return 'south_hill_chamber'
        if (source_key == 'clarksville_community_players_va' and p.netloc == 'clarksvilleplayers.org'
                and p.path == '/' and not p.query):
            return 'clarksville_players'
        if (source_key == 'maccallum_more_va' and p.netloc == 'maccallummore.org'
                and re.fullmatch(r'/pages/[a-z0-9-]+', p.path) and not p.query):
            return 'maccallum_more'
        if (source_key == 'mecklenburg_ymca_programs_va' and p.netloc == 'mecklenburg.recliquecore.com'
                and re.fullmatch(r'/programs/[1-9][0-9]*/[a-z0-9-]+/', p.path)
                and p.query == 'locations=-1'):
            return 'mecklenburg_ymca'
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
        if publisher == 'waterloo':
            probe = urlsplit(value)
            if (probe.hostname == 'waterloo-ia.s3.amazonaws.com' and re.fullmatch(r'v=[0-9]+', probe.query)):
                value = value.split('?', 1)[0]
        p = urlsplit(value)
        if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
                or (p.query and publisher != 'maccallum_more')
                or p.fragment or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)
                or '..' in p.path.split('/')):
            return None
        if publisher == 'waterloo':
            return value if (p.hostname == 'waterloo-ia.s3.amazonaws.com' and p.path.startswith('/images/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'reviewed_chamber':
            return value if value == 'https://cdn.firespring.com/images/49799955-78ed-4e31-b627-8bc12eb7ffea.png' else None
        if publisher in ('clarksville_players', 'maccallum_more', 'mecklenburg_ymca'):
            if (p.netloc != p.hostname or
                    re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', p.path, re.I)):
                return None
            if publisher == 'clarksville_players':
                return value if (p.hostname == 'img1.wsimg.com' and re.fullmatch(
                    r'/isteam/ip/a33c590a-25e0-4bb6-979e-3d018e2af1b1/[^/]+\.(?:jpe?g|png|webp)'
                    r'(?:/:/(?:rs|cr)=[A-Za-z0-9:,.]+(?:/(?:rs|cr)=[A-Za-z0-9:,.]+)*)?',
                    p.path, re.I)) else None
            if publisher == 'maccallum_more':
                params = parse_qsl(p.query, keep_blank_values=True)
                if (len({key for key, _ in params}) != len(params)
                        or any(key not in ('v', 'width') or not re.fullmatch(r'[1-9][0-9]{0,12}', val)
                               for key, val in params)):
                    return None
                # Require the ordinary spelling, without escaped parameter names.
                if p.query and not re.fullmatch(r'(?:v|width)=[1-9][0-9]{0,12}(?:&(?:v|width)=[1-9][0-9]{0,12})?', p.query):
                    return None
                return value if (p.hostname == 'maccallummore.org' and re.fullmatch(
                    r'/cdn/shop/files/[^/]+\.(?:jpe?g|png|webp)', p.path, re.I)) else None
            return value if (p.hostname == 'reclique-core-mecklenburg.s3.amazonaws.com'
                             and re.fullmatch(r'/wp-content/uploads/(?:[A-Za-z0-9_-]+/)*[^/]+\.(?:jpe?g|png|webp)',
                                              p.path, re.I)) else None
        if publisher == 'mycountyparks':
            return value if (p.hostname == 'content.mycountyparks.com'
                             and p.path.startswith('/Production/RelatedItem/Content/')) else None
        if publisher in ('bellevue_times', 'madison'):
            host = 'www.madisoncountyparks.org' if publisher == 'madison' else 'bellevuetimes.com'
            return value if (p.hostname == host and p.path.startswith('/wp-content/uploads/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'rosemont':
            return value if (p.hostname == 'rosemontofvirginia.com'
                             and p.path.startswith('/wp-content/uploads/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)
                             and (value == ROSEMONT_REVIEWED_FEATURED_IMAGE
                                  or not re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', p.path, re.I))) else None
        if publisher == 'chase_city_chamber':
            return value if (p.hostname == 'images.squarespace-cdn.com'
                             and p.path.startswith('/content/v1/64921bef4a756810ab11ec54/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'south_carolina_parks':
            return value if (p.hostname == 'southcarolinaparks.com'
                             and not p.path.lower().startswith(('/images/', '/logo', '/favicon'))
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'think_iowa_city':
            return value if (p.hostname == 'thinkiowacity.com' and p.path.startswith('/wp-content/uploads/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'unleashcb':
            return value if (p.hostname == 'www.unleashcb.com' and p.path.startswith('/images/events/')
                             and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I)) else None
        if publisher == 'mason_city':
            return value if (p.hostname == 'images.locable.com'
                             and re.fullmatch(r'/[A-Za-z0-9_+=/-]{20,}', p.path)) else None
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
