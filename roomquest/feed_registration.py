"""Classify a publisher calendar using the same bounded transport as its collector."""
from html.parser import HTMLParser
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from icalendar import Calendar
from roomquest.registration_formats import collection_evidence, probe, scoped_endpoint

from roomquest.preview_worker import PreviewError, fetch_publisher, public_source_url, supabase_rpc
from roomquest.publisher_pacing import capture_publisher_pacing

ACCEPT = 'text/calendar, application/json, text/html;q=0.8'
DENIALS = {'robots_denied', 'publisher_http_401', 'publisher_http_403'}
RETRYABLE = {'dns_unavailable', 'robots_unavailable', 'source_fetch_deadline', 'source_network_error',
             'publisher_pacing_deferred', 'publisher_rate_limited', 'publisher_http_408', 'publisher_http_429'}


def is_tec_collection(url):
    parts = urlsplit(url)
    route = parse_qs(parts.query).get('rest_route', [''])[0]
    return parts.path.rstrip('/').endswith('/wp-json/tribe/events/v1/events') or route.rstrip('/') == '/tribe/events/v1/events'


def is_event_export(url):
    parts = urlsplit(url)
    keys = {key.lower() for key in parse_qs(parts.query)}
    return bool({'eventid', 'event_id', 'eid', 'tribe_event_id'} & keys or
                re.search(r'/(?:event|events/(?:event|detail)|wp-json/tribe/events/v1/events)/[^/]+', parts.path, re.I))


class CalendarLinks(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.links = {}
        self.calendar_pages = set()

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
        query = parse_qs(parts.query)
        if (tag == 'a' and parts.hostname == urlsplit(self.url).hostname and not parts.query
                and parts.path.rstrip('/').rsplit('/', 1)[-1].lower() in
                ('events', 'calendar', 'events-calendar', 'event-calendar', 'upcoming-events', 'calendar.aspx')):
            self.calendar_pages.add(url)
        if is_tec_collection(url):
            self.links[url] = 'wordpress'
        elif (webcal or attrs.get('type') == 'text/calendar' or parts.path.lower().endswith('.ics')
              or query.get('ical') == ['1'] or (parts.path.lower().endswith('/icalendar.aspx')
              and query.get('feed') == ['calendar']) or parts.path.lower().endswith('/ical_subscribe.php')):
            self.links[url] = 'ical'


def review(reason, collector=None):
    return {'p_outcome': 'review', 'p_reason': reason, 'p_type': collector}


def classify(url, payload, hint=None, endpoint_only=False, venue_website=False):
    if is_event_export(url):
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
    parser = CalendarLinks(url)
    parser.feed(body)
    evidence = collection_evidence(url, body)
    if evidence and (evidence['p_outcome'] == 'verified' or (not endpoint_only and evidence['p_outcome'] == 'discovered') or evidence.get('p_reason') == 'single_event_page'):
        return evidence
    if endpoint_only:
        return evidence if evidence and evidence['p_outcome'] == 'review' else review('no_reusable_calendar')
    links = {target: kind for target, kind in parser.links.items() if scoped_endpoint(url, target)}
    if parser.links and not links:
        return evidence or review('calendar_filter_unverified', 'html')
    if len(links) > 1 and hint:
        preferred = {url: kind for url, kind in links.items() if kind == hint}
        if preferred:
            links = preferred
    if not links and venue_website and len(parser.calendar_pages) == 1 and scoped_endpoint(url, next(iter(parser.calendar_pages))):
        return {'calendar_page': next(iter(parser.calendar_pages))}
    if len(links) != 1:
        return review('multiple_calendar_links', 'html') if links else evidence or review('no_reusable_calendar')
    endpoint, kind = next(iter(links.items()))
    return {'p_outcome': 'discovered', 'p_endpoint': endpoint, 'p_type': kind}


def register(ticket):
    args = {'p_ticket': ticket}
    candidate = supabase_rpc('community_collector_claim_registration', args, timeout=6)
    if not candidate:
        return {'outcome': 'idle'}
    url = candidate['url']
    from roomquest import registered_listings
    from roomquest.registration_formats import source_key, extraction_hold
    with capture_publisher_pacing() as pacing:
        try:
            deadline = monotonic() + 35
            body = fetch_publisher(url, ACCEPT, respect_robots=True, deadline_at=deadline)
            result = classify(url, body, candidate.get('type_hint'), candidate.get('endpoint_only', False),
                              candidate.get('verified_venue_website', False))
            if 'calendar_page' in result:
                url = result['calendar_page']
                body = fetch_publisher(url, ACCEPT, respect_robots=True, deadline_at=deadline,
                                       allowed_hosts=(urlsplit(url).hostname,))
                result = classify(url, body, candidate.get('type_hint'))
                if result['p_outcome'] == 'verified':
                    result = (dict(result, p_outcome='discovered') if probe(url, body, result['p_type'])
                              else review('no_extractable_events', result['p_type']))
                result.setdefault('p_endpoint', url)
            if url in registered_listings.URLS and result.get('p_outcome') == 'review':
                def fetch_detail(target, accept):
                    return fetch_publisher(target, accept, respect_robots=True, deadline_at=deadline,
                                           allowed_hosts=(urlsplit(url).hostname,))
                try:
                    registered_listings.collect({'source_key': source_key(url), 'feed_url': url}, fetch_detail, listing=body)
                    result = {'p_outcome': 'verified' if url == candidate['url'] else 'discovered',
                              'p_type': 'html', 'p_endpoint': url}
                except PreviewError:
                    raise
                except (ValueError, KeyError, TypeError) as exc:
                    result = extraction_hold('html', exc)
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
    recorded = supabase_rpc('community_collector_finish_registration', {**args, **result}, timeout=8)
    return {'outcome': result['p_outcome'] if recorded else 'lease_expired'}
