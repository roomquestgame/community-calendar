"""Capability-bound facts from a registered calendar's already-fetched response.

This is an extraction/evidence contract, never permission to fetch another URL,
infer a venue, publish an image directly, or release a held source.
"""
import re
from urllib.parse import urlsplit

VERSION = 'registered_native_content_v1'
HTML_VERSION = 'registered_html_jsonld_v1'
HTML_SPEKTRIX_VERSION = 'registered_html_spektrix_v2'
HTML_CAPABILITY = 'registered_html_calendar_version'
HTML_DESCRIPTION_FIELD = 'rockhouse_event_description'
from roomquest.event_description import MAX_EVENT_DESCRIPTION_CHARACTERS as MAX_DESCRIPTION
CAPABILITY = 'registered_native_content_version'


def html_details(source):
    """The separately negotiated HTML adapter carries per-detail evidence."""
    return (source.get('kind') == 'html' and source.get('platform_adapter') == 'html'
            and type(source.get(HTML_CAPABILITY)) is int
            and source[HTML_CAPABILITY] == 1)


def enabled(source, *, adapter=None):
    """Only an exact backend capability enables the new contract.

    Fixed-table legacy claims and older backends omit it. A positive capability
    with inconsistent source identity is an error, not a legacy fallback.
    """
    if type(source.get(CAPABILITY)) is not int or source[CAPABILITY] != 1:
        return False
    from roomquest.registration_formats import source_key
    feed = source.get('feed_url')
    from roomquest import wildlife_trusts
    wildlife = (source.get('kind') == 'html' and source.get('platform_adapter') == 'html'
                and source.get('feed_url') in wildlife_trusts.URLS)
    from roomquest.spektrix_provider import family as spektrix_family
    spektrix = (source.get('kind') == 'json'
                and source.get('platform_adapter') == 'spektrix'
                and spektrix_family(feed))
    family = ((source.get('kind') == 'json'
               and source.get('platform_adapter') in ('wordpress', 'jsonld'))
              or html_details(source) or wildlife or spektrix)
    if (not family
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
    from roomquest import openactive, wildlife_trusts, failte_ireland
    if openactive.enabled(source):
        return openactive.event_url(source, link)
    if source.get('feed_url') in wildlife_trusts.URLS:
        return wildlife_trusts.event_url_matches(source, link)
    if failte_ireland.is_source(source.get('feed_url')):
        return failte_ireland.enabled(source) and failte_ireland.event_url_allowed(link)
    if html_details(source):
        # Detail pages were actually fetched under the exact listing host.
        # A www alias is not implicit permission to crawl another origin.
        return (link != source['feed_url']
                and urlsplit(link).netloc == urlsplit(source['feed_url']).netloc)
    if (urlsplit(link).hostname.lower().removeprefix('www.')
            == urlsplit(source['feed_url']).hostname.lower().removeprefix('www.')):
        return True
    if (source.get('kind') == 'json' and source.get('platform_adapter') == 'spektrix'
            and enabled(source)):
        # Match the provider's original API webUrl contract through staging.
        # This accepts link evidence only; publisher fetch hosts stay unchanged.
        from roomquest.spektrix_provider import profile
        return urlsplit(link).hostname in profile(source['feed_url']).get('verified_event_hosts', ())
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


def description_field_allowed(source, field):
    if field == 'description':
        return True
    if not html_details(source):
        return False
    if field == HTML_DESCRIPTION_FIELD:
        return True
    if field == 'forestry_event_description':
        from roomquest.forestry_england import owns_url
        return owns_url(source.get('feed_url'))
    return False


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


def attach(row, source, *, description_value=None, image_value=None, evidence_url=None,
           description_field='description'):
    if not enabled(source):
        raise ValueError('registered_native_capability_required')
    if not event_identity(source, row):
        raise ValueError('registered_native_event_identity_invalid')
    detail = html_details(source)
    if not description_field_allowed(source, description_field):
        raise ValueError('registered_native_evidence_invalid')
    if ((detail and evidence_url != row['event_url'])
            or (not detail and evidence_url not in (None, source['feed_url']))):
        raise ValueError('registered_native_evidence_invalid')
    evidence = evidence_url if detail else source['feed_url']
    from roomquest.event_description import description
    # Bound authentic text rather than rejecting the entire calendar.
    text = description(description_value, limit=MAX_DESCRIPTION)
    candidate = image_candidate(image_value, evidence)
    row['description'] = text
    row['registered_native_content'] = {
        'version': 1, 'source_key': source['source_key'],
        'feed_url': source['feed_url'], 'adapter': source['platform_adapter'],
        'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': description_field if text else None,
        'image_field': 'image' if candidate else None,
    }
    if detail:
        row['registered_native_content'].update(
            evidence_url=evidence, extraction=HTML_VERSION)
    row['image_extractor_version'] = VERSION
    for field in ('image_url', 'image_provenance', 'image_evidence_url'):
        row.pop(field, None)
    if candidate:
        row.update(image_url=candidate, image_provenance=VERSION,
                   image_evidence_url=evidence)
    return row


def attach_spektrix(row, source, *, client, api_base, description_value=None,
                    image_value=None):
    """Attach API-native fields without pretending they came from Event JSON-LD."""
    if not enabled(source) or not html_details(source) or not event_identity(source, row):
        raise ValueError('registered_native_event_identity_invalid')
    from roomquest.spektrix_v3 import api_base as validate_base
    base = validate_base(client, api_base)
    from roomquest.spektrix_discovery import _organization_domain, THIRD_PARTY
    publisher, api_host = urlsplit(source['feed_url']), urlsplit(base)
    if (api_host.hostname in THIRD_PARTY
            or _organization_domain(api_host.hostname) != _organization_domain(publisher.hostname)):
        raise ValueError('registered_native_evidence_invalid')
    from roomquest.event_description import description
    text = description(description_value, limit=MAX_DESCRIPTION)
    candidate = image_candidate(image_value, row['event_url'])
    row['description'] = text
    row['registered_native_content'] = {
        'version': 1, 'source_key': source['source_key'],
        'feed_url': source['feed_url'], 'adapter': source['platform_adapter'],
        'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': 'description' if text else None,
        'image_field': 'image' if candidate else None,
        'evidence_url': base, 'extraction': HTML_SPEKTRIX_VERSION,
        'client': client,
    }
    row['image_extractor_version'] = VERSION
    for field in ('image_url', 'image_provenance', 'image_evidence_url'):
        row.pop(field, None)
    if candidate:
        row.update(image_url=candidate, image_provenance=VERSION,
                   image_evidence_url=base)
    return row


def validate_record(row, source):
    """Reject missing or inconsistent proof before the first staging batch."""
    if not enabled(source):
        raise ValueError('registered_native_capability_required')
    from roomquest import openactive, wildlife_trusts, failte_ireland
    if openactive.enabled(source):
        openactive.validate_native(row, source)
        return
    if source.get('feed_url') in wildlife_trusts.URLS:
        wildlife_trusts.validate_native(row, source)
        return
    if failte_ireland.is_source(source.get('feed_url')):
        failte_ireland.validate_native(row, source)
        return
    if not isinstance(row, dict) or not event_identity(source, row):
        raise ValueError('registered_native_evidence_invalid')
    text, candidate = row.get('description'), row.get('image_url')
    proof = row.get('registered_native_content')
    field = proof.get('description_field') if isinstance(proof, dict) else None
    if text and not description_field_allowed(source, field):
        raise ValueError('registered_native_evidence_invalid')
    expected = {
        'version': 1, 'source_key': source['source_key'],
        'feed_url': source['feed_url'], 'adapter': source['platform_adapter'],
        'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': field if text else None,
        'image_field': 'image' if candidate else None,
    }
    evidence = source['feed_url']
    if html_details(source):
        if isinstance(proof, dict) and proof.get('extraction') == HTML_SPEKTRIX_VERSION:
            evidence = proof.get('evidence_url')
            client = proof.get('client')
            try:
                from roomquest.spektrix_v3 import api_base as validate_base
                from roomquest.spektrix_discovery import _organization_domain, THIRD_PARTY
                evidence = validate_base(client, evidence)
                publisher, api_host = urlsplit(source['feed_url']), urlsplit(evidence)
                if (api_host.hostname in THIRD_PARTY
                        or _organization_domain(api_host.hostname)
                        != _organization_domain(publisher.hostname)):
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                raise ValueError('registered_native_evidence_invalid')
            expected.update(evidence_url=evidence,
                            extraction=HTML_SPEKTRIX_VERSION, client=client)
        else:
            evidence = row['event_url']
            expected.update(evidence_url=evidence, extraction=HTML_VERSION)
    if (not isinstance(text, str) or len(text) > MAX_DESCRIPTION
            or re.search(r'<[^>]+>', text)
            or not isinstance(proof, dict) or type(proof.get('version')) is not int
            or proof != expected or row.get('image_extractor_version') != VERSION
            or (candidate is not None and (
                not isinstance(candidate, str) or not candidate
                or image_candidate(candidate) != candidate
                or row.get('image_provenance') != VERSION
                or row.get('image_evidence_url') != evidence))
            or (candidate is None and any(row.get(field) is not None
                for field in ('image_provenance', 'image_evidence_url')))):
        raise ValueError('registered_native_evidence_invalid')


def media_claim(claim):
    """A native media claim authorizes only its staged candidate, never a crawl."""
    try:
        from roomquest import openactive, wildlife_trusts, failte_ireland
        if openactive.enabled(claim):
            return (claim.get('candidate_only') is True and enabled(claim)
                    and openactive.evidence_url(claim, claim.get('extraction_url'))
                    and event_url_matches(claim, claim.get('event_url')))
        if claim.get('feed_url') in wildlife_trusts.URLS:
            return (claim.get('candidate_only') is True and enabled(claim)
                    and claim.get('extraction_url') == claim.get('event_url')
                    and event_url_matches(claim, claim.get('event_url')))
        if failte_ireland.is_source(claim.get('feed_url')):
            return False  # The published CSV has no licensed native image field.
        if (claim.get('candidate_only') is not True or not enabled(claim)
                or claim.get('extraction_url') != (
                    claim.get('event_url') if html_details(claim) else claim['feed_url'])):
            return False
        # Media claims identify the same event URL; the backend owns occurrence
        # identity and the media lease, which this helper does not manufacture.
        return event_url_matches(claim, claim.get('event_url'))
    except (ValueError, TypeError, KeyError):
        return False
