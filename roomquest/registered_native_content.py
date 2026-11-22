"""Capability-bound facts from a registered calendar's already-fetched response.

This is an extraction/evidence contract, never permission to fetch another URL,
infer a venue, publish an image directly, or release a held source.
"""
import re
from urllib.parse import urlsplit

VERSION = 'registered_native_content_v1'
MAX_DESCRIPTION = 12000
CAPABILITY = 'registered_native_content_version'


def enabled(source, *, adapter=None):
    """Only an exact backend capability enables the new contract.

    Fixed-table legacy claims and older backends omit it. A positive capability
    with inconsistent source identity is an error, not a legacy fallback.
    """
    if type(source.get(CAPABILITY)) is not int or source[CAPABILITY] != 1:
        return False
    from roomquest.registration_formats import source_key
    feed = source.get('feed_url')
    if (source.get('kind') != 'json'
            or source.get('platform_adapter') not in ('wordpress', 'jsonld')
            or (adapter is not None and source.get('platform_adapter') != adapter)
            or not native_url(feed)
            or source.get('source_key') != source_key(feed)):
        raise ValueError('registered_native_source_invalid')
    return True


def native_url(value):
    """Mirror the backend's native-only shape guard, plus existing URL safety."""
    from roomquest.preview_worker import public_source_url
    if not isinstance(value, str) or not public_source_url(value):
        return False
    parsed = urlsplit(value)
    return (12 <= len(value) <= 1000 and value.startswith('https://')
            and parsed.port is None and '#' not in value
            and not any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159
                        for char in value)
            and not re.search(r'^https://(?:[0-9]+\.|localhost)', value, re.I)
            and not re.search(r'\.svg(?:[?#]|$)', value, re.I))


def event_url_matches(source, link):
    if not native_url(link):
        return False
    if (urlsplit(link).hostname.lower().removeprefix('www.')
            == urlsplit(source['feed_url']).hostname.lower().removeprefix('www.')):
        return True
    # These exact calendars publish Ticketmaster URLs in their Event JSON-LD.
    # This is identity evidence from the fetched calendar, not fetch permission.
    return (source.get('platform_adapter') == 'jsonld' and enabled(source)
            and source['feed_url'] in (
                'https://www.punchlinecomedyclub.com/',
                'https://www.theechodallas.com/',
            )
            and re.fullmatch(r'https://www\.ticketmaster\.com/[^/?#]+/event/[0-9A-F]{16}', link)
            is not None)


def event_identity(source, row):
    identity = row.get('id')
    return (isinstance(identity, str) and 1 <= len(identity) <= 180
            and identity == identity.strip()
            and event_url_matches(source, row.get('event_url')))


def image_candidate(value, base_url='', *, _depth=0):
    """Select only bounded native image fields using the existing URL guard."""
    from roomquest.preview_worker import event_image
    if _depth > 3:
        return None
    if isinstance(value, list):
        return next((candidate for item in value[:5]
                     if (candidate := image_candidate(item, base_url, _depth=_depth + 1))), None)
    if isinstance(value, dict):
        for field, minimum in (('width', 160), ('height', 90)):
            if field in value:
                try:
                    if isinstance(value[field], bool) or int(value[field]) < minimum:
                        return None
                except (TypeError, ValueError, OverflowError):
                    return None
        value = value.get('contentUrl') or value.get('url') or value.get('@id')
    # An empty value or unresolved local node reference is not an image URL.
    # urljoin would otherwise turn it into the collection page itself.
    if not isinstance(value, str) or not value.strip() or value.strip().startswith('#'):
        return None
    candidate = event_image(value, base_url)
    return candidate if native_url(candidate) else None


def attach(row, source, *, description_value=None, image_value=None):
    if not enabled(source):
        raise ValueError('registered_native_capability_required')
    if not event_identity(source, row):
        raise ValueError('registered_native_event_identity_invalid')
    from roomquest.event_description import description
    # One extra character detects overflow after the existing sanitizer, without
    # silently truncating the native narrative or counting UTF-8 bytes as text.
    text = description(description_value, limit=MAX_DESCRIPTION + 1)
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('registered_native_description_too_long')
    candidate = image_candidate(image_value, source['feed_url'])
    row['description'] = text
    row['registered_native_content'] = {
        'version': 1, 'source_key': source['source_key'],
        'feed_url': source['feed_url'], 'adapter': source['platform_adapter'],
        'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': 'description' if text else None,
        'image_field': 'image' if candidate else None,
    }
    row['image_extractor_version'] = VERSION
    for field in ('image_url', 'image_provenance', 'image_evidence_url'):
        row.pop(field, None)
    if candidate:
        row.update(image_url=candidate, image_provenance=VERSION,
                   image_evidence_url=source['feed_url'])
    return row


def validate_record(row, source):
    """Reject missing or inconsistent proof before the first staging batch."""
    if not enabled(source):
        raise ValueError('registered_native_capability_required')
    if not isinstance(row, dict) or not event_identity(source, row):
        raise ValueError('registered_native_evidence_invalid')
    text, candidate = row.get('description'), row.get('image_url')
    proof = row.get('registered_native_content')
    expected = {
        'version': 1, 'source_key': source['source_key'],
        'feed_url': source['feed_url'], 'adapter': source['platform_adapter'],
        'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': 'description' if text else None,
        'image_field': 'image' if candidate else None,
    }
    if (not isinstance(text, str) or len(text) > MAX_DESCRIPTION
            or re.search(r'<[^>]+>', text)
            or not isinstance(proof, dict) or type(proof.get('version')) is not int
            or proof != expected or row.get('image_extractor_version') != VERSION
            or (candidate is not None and (
                not isinstance(candidate, str) or not candidate
                or image_candidate(candidate) != candidate
                or row.get('image_provenance') != VERSION
                or row.get('image_evidence_url') != source['feed_url']))
            or (candidate is None and any(row.get(field) is not None
                for field in ('image_provenance', 'image_evidence_url')))):
        raise ValueError('registered_native_evidence_invalid')


def media_claim(claim):
    """A native media claim authorizes only its staged candidate, never a crawl."""
    try:
        if (claim.get('candidate_only') is not True or not enabled(claim)
                or claim.get('extraction_url') != claim['feed_url']):
            return False
        # Media claims identify the same event URL; the backend owns occurrence
        # identity and the media lease, which this helper does not manufacture.
        return event_url_matches(claim, claim.get('event_url'))
    except (ValueError, TypeError, KeyError):
        return False
