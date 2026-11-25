"""Classify a publisher calendar using the same bounded transport as its collector."""
from html.parser import HTMLParser
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from icalendar import Calendar
from roomquest import localist_registration, provider_registration, openactive, wildlife_trusts, failte_ireland
from roomquest.registration_formats import collection_evidence, document_kind, probe, scoped_endpoint

from roomquest.preview_worker import PreviewError, fetch_publisher, public_source_url, supabase_rpc
from roomquest.publisher_pacing import capture_publisher_pacing
from roomquest.registration_auto_defer import auto_defer_nonactionable
from roomquest.wordpress_capabilities import publisher_linked_ical_subscription

ACCEPT = 'text/calendar, application/json, application/xml, text/xml, text/html;q=0.8'
DENIALS = {'robots_denied', 'publisher_http_401', 'publisher_http_403'}
RETRYABLE = {'dns_unavailable', 'robots_unavailable', 'source_fetch_deadline', 'source_network_error',
             'publisher_pacing_deferred', 'publisher_rate_limited', 'publisher_http_408', 'publisher_http_429'}

# Reviewed publisher navigation, not a guess based on a shared domain suffix.
# Each destination must still occur in the submitted page and pass the normal
# robots-aware fetch, collection detection and independent endpoint registration.
PUBLISHER_CALENDAR_PAGES = {
    'https://www.algonquinarts.org/': 'https://www.algonquinarts.org/calendar.php',
    'https://www.boplex.com/our-venues/bojangles-coliseum': 'https://www.boplex.com/events',
    'https://www.boplex.com/our-venues/ovens-auditorium': 'https://www.boplex.com/events',
    'https://www.morgan.edu/': 'https://events.morgan.edu/',
    'https://residentculturebrewing.com/location/plaza-midwood/':
        'https://residentculturebrewing.com/events/?fwp_event_location=plaza-midwood',
}


def is_tec_collection(url):
    parts = urlsplit(url)
    route = parse_qs(parts.query).get('rest_route', [''])[0]
    return parts.path.rstrip('/').endswith('/wp-json/tribe/events/v1/events') or route.rstrip('/') == '/tribe/events/v1/events'


def is_event_export(url):
    parts = urlsplit(url)
    keys = {key.lower() for key in parse_qs(parts.query)}
    return bool({'eventid', 'event_id', 'eid', 'tribe_event_id'} & keys or
                re.search(r'/(?:event|events/(?:event|detail)|wp-json/tribe/events/v1/events)/[^/]+', parts.path, re.I)
                or ('ical' in keys and re.search(r'/events/[1-9][0-9]{2,}/?$', parts.path, re.I)))

def _wrapped_ical_subscription(page_url, wrapper):
    """Decode a publisher-linked Google Calendar subscription, not an event.

    Google Calendar's public subscribe URL contains the publisher's original
    webcal:// URL in the cid query parameter. It is *not* the feed itself.
    Only an exact single value hosted by the current publisher may be used.
    Existing robots/SSRF/collection checks still apply to the recovered URL.
    """
    try:
        parts = urlsplit(wrapper)
        if parts.hostname not in ('calendar.google.com', 'www.google.com') or parts.path != '/calendar/render':
            return None
        values = parse_qs(parts.query).get('cid', [])
        if len(values) != 1:
            return None
        raw = values[0]
        if not raw.lower().startswith('webcal://') or len(raw) > 1000:
            return None
        candidate = 'https://' + raw[len('webcal://'):]
        parsed = urlsplit(candidate)
        if (parsed.hostname != urlsplit(page_url).hostname or parsed.username or parsed.password
                or not public_source_url(candidate) or is_event_export(candidate)):
            return None
        return candidate
    except ValueError:
        return None


class CalendarLinks(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.links = {}
        self.wrapped_links = {}
        self.calendar_pages = set()
        self.publisher_calendar_pages = set()
        self.growthzone_details = set()

    def handle_starttag(self, tag, attributes):
        if tag not in ('link', 'a', 'input'):
            return
        attrs = dict(attributes)
        raw = (attrs.get('href') if tag != 'input' else attrs.get('value')) or ''
        if not raw:
            return
        webcal = raw.lower().startswith('webcal://')
        raw = 'https://' + raw[9:] if webcal else raw
        url = urldefrag(urljoin(self.url, raw)).url
        if not public_source_url(url) or url == self.url or is_event_export(url):
            return
        parts = urlsplit(url)
        if tag == 'a':
            subscription = _wrapped_ical_subscription(self.url, url)
            if subscription:
                self.wrapped_links[subscription] = 'ical'
        if (tag == 'a' and parts.hostname == urlsplit(self.url).hostname
                and not parts.query and re.fullmatch(
                    r'/events/details/[a-z0-9][a-z0-9-]*-[1-9][0-9]*', parts.path, re.I)):
            self.growthzone_details.add(url)
        query = parse_qs(parts.query)
        if tag == 'a' and PUBLISHER_CALENDAR_PAGES.get(self.url) == url:
            self.publisher_calendar_pages.add(url)
        if (tag == 'a' and parts.hostname == urlsplit(self.url).hostname and not parts.query
                and parts.path.rstrip('/').rsplit('/', 1)[-1].lower() in
                ('events', 'calendar', 'events-calendar', 'event-calendar', 'upcoming-events', 'calendar.aspx')):
            self.calendar_pages.add(url)
        if is_tec_collection(url):
            self.links[url] = 'wordpress'
        elif (webcal or attrs.get('type') == 'text/calendar' or parts.path.lower().endswith('.ics')
              or query.get('ical') == ['1']
              or publisher_linked_ical_subscription(url)
              or (parts.path.lower().endswith('/icalendar.aspx')
              and query.get('feed') == ['calendar']) or parts.path.lower().endswith('/ical_subscribe.php')):
            self.links[url] = 'ical'


def growthzone_calendar_candidate(url, body):
    """Evidence-gated, same-host native endpoint candidate; never a verified feed.

    The public Events Calendar must actually link at least two separate
    GrowthZone-style details. Its canonical unfiltered /events page alone can
    suggest /api/events; the caller must fetch and validate XML, permissions,
    source-specific timezone and the full provider collection before admitting it.
    """
    parts = urlsplit(url)
    if (parts.path.rstrip('/').lower() != '/events' or parts.query or parts.fragment
            or not re.search(r'\bEvents Calendar\b', body, re.I)):
        return None
    parser = CalendarLinks(url)
    parser.feed(body)
    if len(parser.growthzone_details) < 2:
        return None
    return urljoin(url, '/api/events')


def review(reason, collector=None):
    return {'p_outcome': 'review', 'p_reason': reason, 'p_type': collector}


def classify(url, payload, hint=None, endpoint_only=False, venue_website=False):
    if is_event_export(url) or re.search(r'/api/2/events/[^/]+', urlsplit(url).path):
        return review('single_event_page')
    body = payload.lstrip('\ufeff \t\r\n')
    if body.upper().startswith('BEGIN:VCALENDAR'):
        try:
            calendar = Calendar.from_ical(body)
            if (calendar.name != 'VCALENDAR' or str(calendar.get('VERSION')) != '2.0'
                    or not body.rstrip().upper().endswith('END:VCALENDAR')):
                return review('invalid_ical', 'ical')
        except (ValueError, KeyError, TypeError, IndexError):
            return review('invalid_ical', 'ical')
        if str(calendar.get('METHOD', '')).upper() in {'REQUEST', 'REPLY', 'CANCEL', 'COUNTER', 'DECLINECOUNTER'}:
            return review('single_event_page', 'ical')
        return {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'ical'}
    if localist_registration.is_api(url):
        try:
            canonical = localist_registration.endpoint(url)
            envelope = json.loads(body)
        except ValueError as exc:
            return review('localist_filter_unverified' if str(exc) == 'localist_filter_unverified' else 'invalid_localist_collection', 'localist')
        if not isinstance(envelope, dict) or not isinstance(envelope.get('page'), dict) or not isinstance(envelope.get('events'), list):
            return review('invalid_localist_collection', 'localist')
        return {'p_outcome': 'verified' if canonical == url else 'discovered', 'p_type':'localist', 'p_endpoint':canonical}
    if body.startswith(('{', '[')):
        try:
            obj = json.loads(body)
        except (ValueError, RecursionError):
            return review('invalid_json')
        if is_tec_collection(url) and isinstance(obj, dict) and isinstance(obj.get('events'), list):
            events = obj['events']
            if events:
                valid = all(isinstance(event, dict) and event.get('id') and event.get('title')
                            and (event.get('start_date') or event.get('utc_start_date')) for event in events)
            else:
                valid = type(obj.get('total')) is int and obj['total'] == 0
            if valid:
                return {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'wordpress'}
            return review('invalid_wordpress_calendar', 'wordpress')
        return collection_evidence(url, body, obj) or review('unrecognized_json')
    if not body.startswith('<'):
        return review('no_reusable_calendar')
    if document_kind(body) == 'xml':
        return review('xml_adapter_needed')
    parser = CalendarLinks(url)
    parser.feed(body)
    evidence = collection_evidence(url, body)
    if evidence and (evidence['p_outcome'] == 'verified' or (not endpoint_only and evidence['p_outcome'] == 'discovered') or evidence.get('p_reason') in ('single_event_page','localist_filter_unverified')):
        return evidence
    if endpoint_only:
        return evidence if evidence and evidence['p_outcome'] == 'review' else review('no_reusable_calendar')
    from roomquest.libcal_registration import subscription
    libcal = subscription(url, body)
    if libcal:
        parser.links[libcal] = 'ical'
    # A monthly/weekly/daily calendar export is not evidence of a complete
    # recurring source. Never silently choose it over a publisher-wide feed.
    # For example, a TEC /events/month/?ical=1 export can contain only past
    # records from one displayed month, even while its page shows many events.
    period_links = {target for target, kind in parser.links.items()
                    if kind == 'ical' and re.search(
                        r'/(?:month|week|day)(?:/|$)', urlsplit(target).path, re.I)}
    links = {target: kind for target, kind in parser.links.items()
             if target not in period_links and scoped_endpoint(url, target)}
    if not links and period_links:
        return review('calendar_period_scope_unverified', 'ical')
    # Prefer a first-party subscription when one is explicitly present. Google
    # Calendar links are merely subscription wrappers; never create two source
    # identities for equivalent direct and wrapped calendar choices.
    if not links:
        links = {target: kind for target, kind in parser.wrapped_links.items()
                 if scoped_endpoint(url, target)}
    if (parser.links or parser.wrapped_links) and not links:
        return evidence or review('calendar_filter_unverified', 'html')
    if len(links) > 1 and hint:
        preferred = {url: kind for url, kind in links.items() if kind == hint}
        if preferred:
            links = preferred
    if not links and len(parser.publisher_calendar_pages) == 1:
        return {'calendar_page': next(iter(parser.publisher_calendar_pages))}
    # A publisher's unfiltered /upcoming-events landing page can explicitly
    # link its one full /events index. The target is fetched and independently
    # checked; never broaden a query-filtered or venue-scoped calendar.
    if (not links and not urlsplit(url).query
            and urlsplit(url).path.rstrip('/') == '/upcoming-events'
            and len(parser.calendar_pages) == 1
            and urlsplit(next(iter(parser.calendar_pages))).path.rstrip('/') == '/events'
            and scoped_endpoint(url, next(iter(parser.calendar_pages)))):
        return {'calendar_page': next(iter(parser.calendar_pages))}
    if (not links and venue_website and urlsplit(url).path in ('', '/')
            and len(parser.calendar_pages) == 1
            and scoped_endpoint(url, next(iter(parser.calendar_pages)))):
        return {'calendar_page': next(iter(parser.calendar_pages))}
    if len(links) != 1:
        return review('multiple_calendar_links', 'html') if links else evidence or review('no_reusable_calendar')
    endpoint, kind = next(iter(links.items()))
    return {'p_outcome': 'discovered', 'p_endpoint': endpoint, 'p_type': kind}


def recover_html_feed(listing_url, listing_body, deadline):
    """Only promote an actually fetched, normalized, reusable publisher feed.

    The existing locator is capped at four extra same-host requests, observes
    robots and publisher pacing, and may probe a documented TEC route only
    when the HTML proves that CMS. It never publishes or grants source rights.
    """
    from roomquest.venue_calendar_locator import find_calendar
    from roomquest.registered_html_calendar import CALENDAR_NAMES

    if document_kind(listing_body) == 'xml':
        return None

    # A venue or department can be encoded in the path rather than a query.
    # Exploratory navigation/API recovery cannot prove that path's scope maps
    # to a publisher-wide feed. Explicit feeds and reviewed navigation were
    # already handled by classify; keep this fallback to root collections.
    path = [part for part in urlsplit(listing_url).path.split('/') if part]
    if path and (len(path) != 1 or path[0].lower() not in
                 CALENDAR_NAMES | {'calendar.aspx', 'calendar.php'}):
        return None

    responses = {}

    def fetch(target, accept, **kwargs):
        # The original submitted selectors are authoritative. An unfiltered
        # feed cannot silently replace a calendar scoped to one venue.
        if (urlsplit(target).hostname != urlsplit(listing_url).hostname
                or not scoped_endpoint(listing_url, target)):
            raise PreviewError('calendar_filter_unverified')
        body = fetch_publisher(target, accept, **kwargs)
        responses[target] = body
        return body

    endpoint, kind = find_calendar(listing_body, listing_url, None, fetch, deadline,
                                   require_unique_calendar_page=True)
    if (kind not in {'ical', 'wordpress', 'squarespace'}
            or endpoint not in responses
            or not scoped_endpoint(listing_url, endpoint)):
        return None
    checked = classify(endpoint, responses[endpoint], endpoint_only=True)
    if (checked.get('p_outcome') != 'verified' or checked.get('p_type') != kind
            or not probe(endpoint, responses[endpoint], kind)):
        return None
    return {'p_outcome': 'discovered', 'p_endpoint': endpoint, 'p_type': kind}


def verify_html_calendar(listing_url, listing_body, deadline, *, continuation=None):
    """Probe the exact same linked-detail adapter used by scheduled collection."""
    from roomquest import registered_html_calendar, forestry_england
    from roomquest.registered_native_content import CAPABILITY, HTML_CAPABILITY
    from roomquest.registration_formats import source_key, extraction_hold

    if not registered_html_calendar.supports_listing(listing_url, listing_body):
        return None
    source = {'source_key': source_key(listing_url), 'feed_url': listing_url,
              'kind': 'html', 'platform_adapter': 'html',
              CAPABILITY: 1, HTML_CAPABILITY: 1}

    def fetch_detail(target, accept):
        return fetch_publisher(target, accept, respect_robots=True,
                               deadline_at=deadline,
                               allowed_hosts=(urlsplit(listing_url).hostname,))

    try:
        if continuation is not None and not forestry_england.owns_url(listing_url):
            return continuation(listing_url, listing_body)
        records = registered_html_calendar.collect(
            source, fetch_detail, deadline_at=deadline, listing=listing_body)
        # A fully checked official Forestry venue calendar remains a reusable
        # source while empty. Other HTML publishers retain the event-evidence
        # requirement; failed/incomplete Forestry captures still reach review.
        if not records and not forestry_england.owns_url(listing_url):
            return review('no_extractable_events', 'html')
        from roomquest.registered_native_content import validate_record
        for row in records:
            validate_record(row, source)
    except PreviewError:
        raise
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        return extraction_hold('html', exc)
    return {'p_outcome': 'verified', 'p_endpoint': listing_url,
            'p_type': 'html', 'p_reason': registered_html_calendar.VERSION}


def _checkpoint_registration(candidate, ticket, pacing, deadline, *, listing=None, resume=False):
    """Use the original receipt's leased checkpoint, never create a source early."""
    from roomquest import registered_html_checkpoint as capture, registered_html_calendar
    from roomquest.registration_formats import source_key, extraction_hold
    from roomquest.registered_native_content import CAPABILITY, HTML_CAPABILITY
    url = candidate['url']
    source = {'source_key': source_key(url), 'feed_url': url, 'kind': 'html',
              'platform_adapter': 'html', CAPABILITY: 1, HTML_CAPABILITY: 1,
              capture.CAPABILITY: 1}
    from roomquest.registered_html_spektrix import transport_hosts
    try:
        saved = capture.read(source, 'registration', ticket, supabase_rpc)
        if resume and saved['checkpoint'] is None:
            return None  # Expired capture: repeat normal guarded discovery.
        if not resume and saved['checkpoint'] is not None:
            raise PreviewError('fetch_checkpoint_invalid_response')
        chunk = capture.collect_and_save(source,
            lambda target, accept: fetch_publisher(
                target, accept, respect_robots=True, deadline_at=deadline - 8,
                allowed_hosts=transport_hosts(source, target)),
            supabase_rpc, pacing, category='registration', ticket=ticket,
            deadline_at=deadline - 8, listing=listing, saved=saved)
    except PreviewError:
        raise
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        if str(exc) in ('fetch_checkpoint_context_missing', 'fetch_checkpoint_invalid_response',
                        'publisher_wait_requires_review'):
            raise PreviewError(str(exc)) from exc
        return extraction_hold('html', exc)
    if not chunk['complete']:
        return {'p_outcome': 'retry', 'p_reason': capture.PENDING,
                'p_retry_seconds': max(1, pacing['crawl_delay_seconds'],
                                       pacing['retry_after_seconds'])}
    if not chunk['events']:
        return review('no_extractable_events', 'html')
    return {'p_outcome': 'verified', 'p_endpoint': url, 'p_type': 'html',
            'p_reason': registered_html_calendar.VERSION}


def register(ticket):
    args = {'p_ticket': ticket}
    candidate = supabase_rpc('community_collector_claim_registration', args, timeout=6)
    if not candidate:
        return {'outcome': 'idle'}
    url = candidate['url']
    from roomquest import liberty_calendar, registered_listings
    from roomquest.registration_formats import source_key, extraction_hold
    with capture_publisher_pacing() as pacing:
        body = None  # Fetch failure can occur before a response was collected.
        try:
            deadline = monotonic() + 35
            from roomquest import registered_html_checkpoint as capture
            durable = capture.enabled(candidate)
            if durable and candidate.get('html_capture_pending') is True:
                result = _checkpoint_registration(candidate, ticket, pacing, deadline, resume=True)
                if result is not None:
                    result = auto_defer_nonactionable(result)
                    recorded = supabase_rpc('community_collector_finish_registration',
                        {**args, **result}, timeout=8)
                    return {'outcome': result['p_outcome'] if recorded else 'lease_expired'}
            def check(target, endpoint_only=False, venue_website=False):
                def fetch(resource, accept):
                    return fetch_publisher(resource, accept, respect_robots=True, deadline_at=deadline,
                                           allowed_hosts=(urlsplit(target).hostname,),
                                           **({'follow_redirects': False} if target == liberty_calendar.ORIGINAL else {}))
                initial_options = ({'allowed_hosts': (urlsplit(target).hostname,)}
                                   if target != candidate['url'] else {})
                if target == liberty_calendar.ORIGINAL:
                    initial_options.update(allowed_hosts=liberty_calendar.ALLOWED_HOSTS, follow_redirects=False)
                if target in wildlife_trusts.CATALOG_URLS:
                    return review('national_catalog_requires_regional_sources', 'html'), None
                if openactive.profile(target) or target in wildlife_trusts.URLS:
                    # Registration verifies protocol identity and complete RSS
                    # discovery. It does not publish an RPDE bootstrap/detail
                    # prefix as a successful event snapshot.
                    body = fetch(target, ('text/html' if target == openactive.BETTER
                                         else 'application/json' if openactive.profile(target) else ACCEPT))
                    family = 'jsonld' if openactive.profile(target) else 'html'
                    try:
                        source = {'feed_url': target, 'source_key': source_key(target)}
                        if family == 'jsonld':
                            openactive.probe(source, fetch, body=body, deadline_at=deadline)
                        else:
                            wildlife_trusts.probe(source, fetch, listing=body, deadline_at=deadline)
                        result = {'p_outcome': 'verified', 'p_endpoint': target, 'p_type': family}
                        if family == 'html':
                            from roomquest.registered_native_content import HTML_VERSION
                            result['p_reason'] = HTML_VERSION
                        return result, body
                    except (ValueError, KeyError, TypeError) as exc:
                        return extraction_hold(family, exc), body
                if failte_ireland.is_source(target):
                    body = fetch(target, failte_ireland.ACCEPT)
                    try:
                        records = failte_ireland.collect(
                            failte_ireland.registration_source(), fetch, body=body, deadline_at=deadline)
                        if records:
                            return {'p_outcome': 'verified', 'p_endpoint': target, 'p_type': 'jsonld',
                                    'p_reason': failte_ireland.VERSION}, body
                        return review('no_extractable_events', 'jsonld'), body
                    except PreviewError:
                        raise
                    except (ValueError, KeyError, TypeError, OverflowError) as exc:
                        return extraction_hold('jsonld', exc), body
                adapter = provider_registration.family(target)
                body = None if adapter else fetch_publisher(
                    target, ACCEPT, respect_robots=True, deadline_at=deadline,
                    **initial_options)
                adapter = adapter or provider_registration.family(target, body)
                if adapter:
                    try:
                        config = provider_registration.read_profile(target, adapter, supabase_rpc)
                        records = provider_registration.collect(target, adapter, fetch, deadline=deadline,
                                                                profile=config, body=body,
                                                                registration_probe=True)
                        if records:
                            return {'p_outcome':'verified', 'p_endpoint':target, 'p_type':adapter}, body
                        return review('no_extractable_events', adapter), body
                    except PreviewError:
                        raise
                    except (KeyError, ValueError, TypeError, OverflowError, AttributeError) as exc:
                        return extraction_hold(adapter, exc), body
                return classify(target, body, candidate.get('type_hint'), endpoint_only, venue_website), body

            result, body = check(url, candidate.get('endpoint_only', False),
                                 candidate.get('verified_venue_website', False))
            if (type(candidate.get('registered_html_calendar_version')) is int
                    and candidate['registered_html_calendar_version'] == 1
                    and not candidate.get('endpoint_only')
                    and result.get('p_outcome') == 'review'
                    and result.get('p_reason') in {'html_adapter_needed', 'no_reusable_calendar',
                                                  'collection_scope_unverified'}):
                from roomquest.registered_html_calendar import calendar_destination
                destination = calendar_destination(url, body)
                if destination and scoped_endpoint(url, destination):
                    result = {'calendar_page': destination}
            if 'calendar_page' in result:
                url = result['calendar_page']
                result, body = check(url)
                if result['p_outcome'] == 'verified':
                    result = (dict(result, p_outcome='discovered') if probe(url, body, result['p_type'])
                              else review('no_extractable_events', result['p_type']))
                result.setdefault('p_endpoint', url)
            if url in registered_listings.URLS and result.get('p_outcome') == 'review':
                def fetch_detail(target, accept):
                    return fetch_publisher(target, accept, respect_robots=True, deadline_at=deadline,
                                           allowed_hosts=registered_listings.allowed_hosts(url),
                                           **({'follow_redirects': False} if url == liberty_calendar.ORIGINAL else {}))
                try:
                    records = registered_listings.collect({'source_key': source_key(url), 'feed_url': url}, fetch_detail,
                                                          listing=body, deadline_at=deadline)
                    # A complete recurring snapshot can be empty after its last
                    # dated event. Initial registration still needs an event.
                    if not records:
                        raise ValueError('no_extractable_events')
                    result = {'p_outcome': 'verified' if url == candidate['url'] else 'discovered',
                              'p_type': 'html', 'p_endpoint': url}
                except PreviewError:
                    raise
                except (ValueError, KeyError, TypeError) as exc:
                    result = extraction_hold('html', exc)
            # GrowthZone calendars expose event-detail links on their public
            # listing, while the reusable XML lives at a separate first-party
            # endpoint. Verify that endpoint using the *existing* provider
            # collector, not a new HTML parser or a guessed timezone. Keep the
            # original review hold on a denied, incomplete or unprofiled feed.
            if (not candidate.get('endpoint_only') and body
                    and result.get('p_outcome') == 'review'
                    and result.get('p_reason') in {'html_adapter_needed', 'no_reusable_calendar'}
                    and body.lstrip().lstrip(chr(0xfeff)).lstrip().startswith('<')
                    and document_kind(body) != 'xml'):
                growthzone_endpoint = growthzone_calendar_candidate(url, body)
                if growthzone_endpoint:
                    try:
                        native_result, _ = check(growthzone_endpoint, endpoint_only=True)
                    except PreviewError:
                        # A blocked discovered endpoint is not an invitation to
                        # bypass publisher policy or disable the accessible page.
                        pass
                    else:
                        if (native_result.get('p_outcome') == 'verified'
                                and native_result.get('p_type') == 'growthzone'):
                            result = {'p_outcome': 'discovered',
                                      'p_endpoint': growthzone_endpoint,
                                      'p_type': 'growthzone'}
            if (not candidate.get('endpoint_only') and body
                    and (url == candidate['url'] or (
                        candidate.get('verified_venue_website')
                        and urlsplit(url).hostname == urlsplit(candidate['url']).hostname
                        and scoped_endpoint(candidate['url'], url)))
                    and body.lstrip().lstrip(chr(0xfeff)).lstrip().startswith('<')
                    and document_kind(body) != 'xml'
                    and result.get('p_outcome') == 'review'
                    and result.get('p_reason') in {
                        'html_adapter_needed', 'no_reusable_calendar',
                        'multiple_calendar_links', 'squarespace_collection_unverified',
                    }):
                recovered = recover_html_feed(url, body, deadline)
                if recovered:
                    result = recovered
            if (type(candidate.get('registered_html_calendar_version')) is int
                    and candidate['registered_html_calendar_version'] == 1
                    and body and body.lstrip().lstrip(chr(0xfeff)).lstrip().startswith('<')
                    and document_kind(body) != 'xml'
                    and result.get('p_outcome') == 'review'
                    and result.get('p_reason') in {
                        'html_adapter_needed', 'no_reusable_calendar',
                        'collection_scope_unverified',
                    }):
                continuation = (lambda target, listing: _checkpoint_registration(
                    candidate, ticket, pacing, deadline, listing=listing)
                    ) if durable and url == candidate['url'] else None
                verified_html = verify_html_calendar(url, body, deadline,
                                                     continuation=continuation)
                if verified_html:
                    result = verified_html
                    if url != candidate['url'] and result['p_outcome'] == 'verified':
                        result = dict(result, p_outcome='discovered')
            if result.get('p_type') == 'localist' and result['p_outcome'] == 'verified':
                try:
                    records = localist_registration.collect(url, lambda target, accept: fetch_publisher(
                        target, accept, respect_robots=True, deadline_at=deadline, allowed_hosts=(urlsplit(url).hostname,)))
                    if not records:
                        result = review('no_extractable_events', 'localist')
                except PreviewError:
                    raise
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    result = extraction_hold('localist', exc)
            if result['p_outcome'] == 'verified' and not probe(url, body, result['p_type']):
                result = review('no_extractable_events', result['p_type'])
        except PreviewError as exc:
            reason = str(exc)
            if reason in DENIALS:
                result = {'p_outcome': 'disabled', 'p_reason': reason}
            elif pacing['wait_unbounded']:
                result = review('publisher_wait_requires_review')
            elif reason in RETRYABLE or re.fullmatch(r'publisher_http_5[0-9]{2}', reason):
                result = {'p_outcome': 'retry', 'p_reason': reason,
                          'p_retry_seconds': max(pacing['retry_after_seconds'], pacing['crawl_delay_seconds'])}
            else:
                result = review(reason if re.fullmatch(r'[a-z0-9_]{1,100}', reason) else 'publisher_check_failed')
    if url != candidate['url']:
        result.setdefault('p_endpoint', url)
    # Annotate *only* the unsupported HTML result after all existing native,
    # subscribed-feed and complete HTML collector recovery has been attempted.
    # Fingerprints must never displace a working supported collector.
    if (not candidate.get('endpoint_only') and isinstance(body, str)
            and result.get('p_outcome') == 'review'
            and result.get('p_reason') in {'html_adapter_needed', 'no_reusable_calendar'}):
        from roomquest.calendar_profile_signals import annotate_unsupported
        result = annotate_unsupported(result, body)
    # Do not label a source as requiring human review just because it is
    # empty or lacks a supported extraction adapter today.
    result = auto_defer_nonactionable(result)
    recorded = supabase_rpc('community_collector_finish_registration', {**args, **result}, timeout=8)
    return {'outcome': result['p_outcome'] if recorded else 'lease_expired'}
