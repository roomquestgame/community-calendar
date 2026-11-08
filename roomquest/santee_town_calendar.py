"""Bounded official Santee calendar with an explicitly approved approximate fallback.

All I/O uses the caller's existing guarded transport. The town-center point is
owner-approved review evidence, never claimed as publisher-reported GPS.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import DETAILS_VERSION, IMAGE_VERSION

KEY = 'town_of_santee_sc'
URL = 'https://www.townofsantee-sc.org/upcoming-events-calendars'
SOURCES = {KEY: URL}
HOST = 'https://www.townofsantee-sc.org'
FEED_PATH = '/vc3-fullcalendar-events-feed'
ZONE = 'America/New_York'
MAX_RECORDS = 100
MAX_DOCUMENT = 2_000_000
MAX_SECONDS = 30
TOWN_CENTER = (33.484582, -80.48998)
TOWN_GEOID = '4563790'
CENSUS_EVIDENCE = 'https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip'
APPROXIMATE_VENUE = 'Town of Santee — approximate town center'
APPROXIMATE_DESCRIPTION = (
    'Approximate location: Santee town center. '
    'The publisher has not supplied an event address.'
)
_STREET = re.compile(
    r'\b(?P<street>[0-9]{1,6}\s+[A-Za-z0-9 .\'-]+?\s+'
    r'(?:Road|Rd|Street|St|Avenue|Ave|Way|Drive|Dr|Lane|Ln|Boulevard|Blvd|'
    r'Court|Ct|Highway|Hwy|Trail|Trl|Place|Pl|Circle|Cir|Parkway|Pkwy)'
    r'(?:\s+(?:NE|NW|SE|SW|N|S|E|W))?)\s*,\s*'
    r'(?P<city>[A-Za-z][A-Za-z .\'-]+?)\s*,\s*(?P<state>[A-Z]{2})'
    r'(?:\s+(?P<zip>[0-9]{5}(?:-[0-9]{4})?))?\b', re.I
)
_NONPUBLIC = re.compile(
    r'\b(?:members?[- ]only|invitation[- ]only|private (?:event|party)|'
    r'office (?:closed|closure)|holiday closure)\b', re.I)
_BODY_LOCATION_CUE = re.compile(
    r'(?:\b(?:meet|gather|assemble) at|'
    r'\b(?:event|parade|celebration|festival) (?:(?:takes? place|(?:will be )?held|starts?|begins?) )?at|'
    r'\b(?:event location|meeting location|venue|location)\s*:)\s*'
    r'(?:[A-Za-z][A-Za-z .\'-]*,\s*)?$', re.I)
_BODY_CONTACT_CUE = re.compile(
    r'\b(?:mail|send|submit|return|deliver)\b|'
    r'\b(?:registration|contact|ticket|administrative) (?:office|address)\b', re.I)


def validate(source):
    if any(source.get(k) != v for k, v in {
            'source_key': KEY, 'feed_url': URL, 'kind': 'html',
            'platform_adapter': 'html', 'timezone': ZONE}.items()):
        raise ValueError('unregistered_santee_town_calendar')
    return KEY, URL


def event_url(key, value):
    return value if (key == KEY and isinstance(value, str) and len(value) <= 1000
                     and re.fullmatch(r'https://www[.]townofsantee-sc[.]org/event/[a-z0-9]+(?:-[a-z0-9]+)*', value)) else None


def image_url(key, value):
    return value if (key == KEY and isinstance(value, str) and len(value) <= 2000
                     and re.fullmatch(r'https://www[.]townofsantee-sc[.]org/sites/default/files/uploads/News/[A-Za-z0-9_-]+[.](?:png|jpe?g|webp|gif)', value)
                     and not re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', value, re.I)) else None


def _document(payload):
    if not isinstance(payload, str) or not payload.strip() or len(payload.encode()) > MAX_DOCUMENT:
        raise ValueError('santee_document_invalid')
    return BeautifulSoup(payload, 'html.parser')


def _canonical(soup, expected):
    links = soup.select('link[rel="canonical"]')
    if len(links) != 1 or links[0].get('href') != expected:
        raise ValueError('santee_canonical_identity_changed')


def _now(value):
    result = value or datetime.now(timezone.utc)
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError('santee_clock_timezone_required')
    return result


def calendar_feed_url(payload, *, now=None):
    """Verify the observed Drupal contract before adding a bounded date window."""
    soup = _document(payload)
    _canonical(soup, URL)
    scripts = soup.select('script[data-drupal-selector="drupal-settings-json"]')
    if len(scripts) != 1:
        raise ValueError('santee_calendar_contract_changed')
    try:
        settings = json.loads(scripts[0].get_text())
    except (ValueError, TypeError):
        raise ValueError('santee_calendar_contract_changed') from None
    sources = []

    def visit(value, depth=0):
        if depth > 20:
            raise ValueError('santee_calendar_contract_changed')
        if isinstance(value, dict):
            if 'eventSources' in value:
                if not isinstance(value['eventSources'], list):
                    raise ValueError('santee_calendar_contract_changed')
                sources.extend(value['eventSources'])
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)

    visit(settings.get('vc3_fullcalendar') if isinstance(settings, dict) else None)
    if sources != [{'url': FEED_PATH, 'extraParams': {'id': 'events_calendar', 'display': 'all_events'}}]:
        raise ValueError('santee_calendar_contract_changed')
    current = _now(now).astimezone(ZoneInfo(ZONE))
    return HOST + FEED_PATH + '?' + urlencode({
        'id': 'events_calendar', 'display': 'all_events',
        'start': current.date().isoformat(),
        # FullCalendar's end is exclusive. Include the final calendar date,
        # then apply the exact rolling 60-day limit before fetching details.
        'end': (current + timedelta(days=61)).date().isoformat(),
    })


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2})?(?:Z|[+-][0-9]{2}:?[0-9]{2})', value):
        raise ValueError('santee_event_time_unverified')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        raise ValueError('santee_event_time_unverified') from None


def parse_feed(payload, *, now=None):
    current = _now(now)
    if not isinstance(payload, str) or len(payload.encode()) > MAX_DOCUMENT:
        raise ValueError('santee_feed_invalid')
    try:
        events = json.loads(payload)
    except (TypeError, ValueError):
        raise ValueError('santee_feed_invalid') from None
    if not isinstance(events, list) or len(events) > MAX_RECORDS:
        raise ValueError('santee_feed_invalid')
    result, seen = [], set()
    for item in events:
        if not isinstance(item, dict):
            raise ValueError('santee_feed_invalid')
        identity, title = item.get('id'), item.get('title')
        raw_url = item.get('url')
        if (not isinstance(identity, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', identity)
                or not isinstance(title, str) or not plain(title)
                or not isinstance(raw_url, str)):
            raise ValueError('santee_event_identity_changed')
        if not (re.fullmatch(r'/event/[a-z0-9]+(?:-[a-z0-9]+)*', raw_url)
                or event_url(KEY, raw_url)):
            raise ValueError('santee_event_identity_changed')
        url = urljoin(HOST, raw_url)
        if not event_url(KEY, url):
            raise ValueError('santee_event_identity_changed')
        if cancelled(title) or _NONPUBLIC.search(title):
            continue
        if item.get('allDay') is not False:
            raise ValueError('santee_event_time_unverified')
        starts = _time(item.get('start'))
        ends = _time(item['end']) if item.get('end') else None
        if ends is not None and ends <= starts:
            raise ValueError('santee_event_time_conflict')
        if starts >= current + timedelta(days=60) or (ends or starts + timedelta(hours=3)) <= current:
            continue
        key = (identity, starts)
        if key in seen:
            raise ValueError('santee_duplicate_occurrence')
        seen.add(key)
        result.append({'id': identity, 'title': plain(title), 'url': url,
                       'starts': starts, 'ends': ends,
                       'feed_location': item.get('location') or item.get('address') or item.get('venue')})
    return result


def _structured_location(soup, item):
    found = []
    exclusions = {'third_party': False, 'online': False}

    def visit(value, depth=0):
        if depth > 15:
            raise ValueError('santee_structured_event_invalid')
        if isinstance(value, dict):
            types = value.get('@type', [])
            types = [types] if isinstance(types, str) else types
            if isinstance(types, list) and 'Event' in types and value.get('url') == item['url']:
                if value.get('name') and plain(value['name']) != item['title']:
                    raise ValueError('santee_event_detail_identity_changed')
                organizer = value.get('organizer')
                if organizer:
                    organizers = organizer if isinstance(organizer, list) else [organizer]
                    names = [plain(org.get('name') if isinstance(org, dict) else org) for org in organizers]
                    exclusions['third_party'] |= any(name.lower() != 'town of santee' for name in names)
                exclusions['online'] |= str(value.get('eventAttendanceMode', '')).endswith('OnlineEventAttendanceMode')
                location = value.get('location')
                if location:
                    if not isinstance(location, dict) or location.get('@type') == 'VirtualLocation':
                        raise ValueError('santee_event_location_unverified')
                    address = location.get('address')
                    if isinstance(address, dict):
                        street, city, state = (plain(address.get(k)) for k in
                                               ('streetAddress', 'addressLocality', 'addressRegion'))
                        if not all((street, city, state)):
                            raise ValueError('santee_published_address_incomplete')
                        address = ', '.join((street, city, state))
                        if location['address'].get('postalCode'):
                            address += ' ' + plain(location['address']['postalCode'])
                    if address:
                        if not isinstance(address, str) or not _STREET.search(address):
                            raise ValueError('santee_published_address_incomplete')
                        found.append((plain(location.get('name')), plain(address)))
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            raise ValueError('santee_structured_event_invalid') from None
        visit(value)
    return found, exclusions


def _location(node, body, item, structured=(), *, third_party=False):
    """Only occurrence content is eligible; footer/hero addresses are excluded."""
    fields = node.select('.field--name-field-location, .field--name-field-address')
    texts = [plain(field.get_text(' ', strip=True)) for field in fields]
    texts.extend(address for _, address in structured)
    for field in fields:
        street = field.select_one('.street-address')
        city = field.select_one('.locality')
        state = field.select_one('.administrative-area')
        postal = field.select_one('.postal-code')
        if street is not None:
            if city is None or state is None:
                raise ValueError('santee_published_address_incomplete')
            texts.append(', '.join(plain(x.get_text()) for x in (street, city, state))
                         + (' ' + plain(postal.get_text()) if postal is not None else ''))
    candidates, ambiguous_body_address = [], False
    for text, needs_location_cue in [(text, False) for text in texts] + [(body, True)]:
        for match in _STREET.finditer(text):
            if needs_location_cue:
                # A parade-entry mailing address is not the parade venue.
                # Require an explicit occurrence-location cue for prose;
                # structured Event/Drupal location fields carry that context.
                context = re.split(r'[.!?;]', text[:match.start()])[-1][-160:]
                if not _BODY_LOCATION_CUE.search(context) or _BODY_CONTACT_CUE.search(context):
                    ambiguous_body_address = True
                    continue
            street = match['street'] + ', ' + match['city'] + ', ' + match['state'].upper()
            if match['zip']:
                street += ' ' + match['zip']
            candidates.append((street, match['city']))
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) > 1:
        raise ValueError('santee_multiple_event_addresses')
    if candidates:
        street, city = candidates[0]
        venue = next((name for name, address in structured if name and street == address), '')
        venue = venue or next((text.split(street.split(',')[0])[0].strip(' :,-')
                      for text in texts if street.split(',')[0] in text), '')
        return venue or 'Town of Santee event', street, city
    if ambiguous_body_address:
        raise ValueError('santee_event_location_context_required')
    if item.get('feed_location') or any(re.search(r'\b[0-9]{1,6}\s+[A-Za-z]', text) for text in texts):
        raise ValueError('santee_published_address_incomplete')
    if re.search(r'\b[0-9]{1,6}\s+[A-Za-z .\'-]+\s+(?:Road|Rd|Street|St|Avenue|Ave|Way|Drive|Dr|Lane|Ln)\b', body, re.I):
        raise ValueError('santee_published_address_incomplete')
    organizers = [plain(x.get_text()) for x in node.select('.field--name-field-organizer .field__item')]
    if (third_party or any(value.lower() != 'town of santee' for value in organizers)
            or re.search(r'\boff[- ]?site\b|\bout of town\b|\boutside Santee\b', body, re.I)):
        raise ValueError('santee_town_run_evidence_required')
    hosts = re.findall(r'\b(?:hosted|organized|presented) by ([^.!?\n]+)', body, re.I)
    if any(not re.fullmatch(r'(?:the )?Town of Santee', value.strip(), re.I) for value in hosts):
        raise ValueError('santee_town_run_evidence_required')
    # The fallback is for a town-run occurrence, not any guest listing the town
    # might republish. The current reviewed parade names the town explicitly.
    if not (re.search(r'\bTown of Santee\b|\bSantee Town Council\b', item['title'], re.I)
            or organizers == ['Town of Santee']
            or re.search(r'\b(?:hosted|organized|presented) by (?:the )?Town of Santee\b', body, re.I)):
        raise ValueError('santee_town_run_evidence_required')
    return None


def parse_event(payload, item):
    soup = _document(payload)
    _canonical(soup, item['url'])
    titles = soup.select('h1')
    nodes = soup.select('div.node--type-calendar-event.node--view-mode-full')
    if len(titles) != 1 or plain(titles[0].get_text()) != item['title'] or len(nodes) != 1:
        raise ValueError('santee_event_detail_identity_changed')
    node = nodes[0]
    when = node.select('.field--name-field-when')
    times = when[0].select('time[datetime]') if len(when) == 1 else []
    expected = [item['starts']] + ([item['ends']] if item['ends'] is not None else [])
    if [_time(t.get('datetime')) for t in times] != expected:
        raise ValueError('santee_feed_detail_time_conflict')
    bodies = node.select('.field--name-body')
    if len(bodies) > 1:
        raise ValueError('santee_event_body_changed')
    body_node = bodies[0] if bodies else None
    if body_node:
        for element in body_node.select('script,style,template,form,noscript'):
            element.decompose()
    body = plain(body_node.get_text(' ', strip=True)) if body_node else ''
    if cancelled(item['title'], body) or _NONPUBLIC.search(body):
        return None
    structured, exclusions = _structured_location(soup, item)
    if exclusions['online']:
        return None
    venue = _location(node, body, item, structured, third_party=exclusions['third_party'])
    labels = [plain(x.get_text())[:100] for x in node.select('.field--name-field-event-category .field__item')][:20]
    description = body or item['title']
    fallback = venue is None
    if fallback:
        venue = (APPROXIMATE_VENUE, '', 'Santee')
        description = APPROXIMATE_DESCRIPTION + ' ' + description
    row = record(item['title'], item['starts'].isoformat(),
                 item['ends'].isoformat() if item['ends'] else None,
                 *venue, item['url'], 'santee-town-' + item['id'], ', '.join(labels),
                 tz=ZONE, retain_until_end=True)
    if row is None:
        return None
    row.update(timezone=ZONE, description=description[:2000],
               publisher_categories=labels, details_extractor_version=DETAILS_VERSION,
               details_evidence_url=item['url'],
               publisher_details={} if fallback else {'meeting_location': ', '.join(venue[:2])},
               image_extractor_version=IMAGE_VERSION,
               location_provenance='publisher_event_address_pending_geocode')
    if fallback:
        # Ben's November 8 authorization. Attach after normal record() because
        # generic addressless publisher coordinates must continue to be cleared.
        row.update(lat=TOWN_CENTER[0], lng=TOWN_CENTER[1], reason=None,
                   location_provenance='reviewed_town_center_fallback',
                   location_accuracy='approximate', location_geoid=TOWN_GEOID,
                   location_evidence_url=CENSUS_EVIDENCE)
    candidates = [image_url(KEY, urljoin(HOST, image.get('src', '')))
                  for image in body_node.select('img[src]')] if body_node else []
    candidate = next((value for value in candidates if value), None)
    if candidate:
        row.update(image_url=candidate, image_provenance=IMAGE_VERSION,
                   image_evidence_url=item['url'])
    return row


def collect(source, fetch, *, deadline_at=None, now=None):
    validate(source)
    current = _now(now)
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))

    def get(url, accept):
        if monotonic() >= deadline:
            raise TimeoutError('santee_collection_deadline')
        payload = fetch(url, accept)
        if monotonic() >= deadline:
            raise TimeoutError('santee_collection_deadline')
        return payload

    feed = calendar_feed_url(get(URL, 'text/html'), now=current)
    listed = parse_feed(get(feed, 'application/json'), now=current)
    rows = []
    for item in listed:
        row = parse_event(get(item['url'], 'text/html'), item)
        if row is not None:
            rows.append(row)
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
