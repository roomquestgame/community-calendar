"""Reviewed Wildlife Trusts RSS manifests and first-party Drupal event details.

RSS pubDate is a date/range hint, never a session clock. National feed entries
may point to regional Trusts; transport is restricted to the publisher network
actually observed in the national feed. No arbitrary RSS host is fetched.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record, timestamp
from roomquest import national_feed_checkpoint as snapshot
from roomquest.registration_formats import source_key

NATIONAL = 'https://www.wildlifetrusts.org/events'
BCN = 'https://www.wildlifebcn.org/events'
LONDON = ZoneInfo('Europe/London')
MAX_ITEMS = 2000
MAX_PAGES = 10
MAX_DETAILS = 8
MAX_DESCRIPTION = 12000
EXTRACTION = 'wildlife_event_detail_v1'
NETWORK_HOSTS = (
    'www.wildlifetrusts.org', 'www.wildlifebcn.org', 'www.ywt.org.uk',
    'www.norfolkwildlifetrust.org.uk', 'www.cumbriawildlifetrust.org.uk',
    'www.suffolkwildlifetrust.org', 'www.bbowt.org.uk', 'www.essexwt.org.uk',
    'www.devonwildlifetrust.org', 'www.wildlondon.org.uk',
    'www.nottinghamshirewildlife.org', 'www.herefordshirewt.org',
    'www.hiwwt.org.uk', 'www.lrwt.org.uk', 'www.staffs-wildlife.org.uk',
    'www.nwt.org.uk', 'www.lincstrust.org.uk', 'www.worcswildlifetrust.co.uk',
    'www.shropshirewildlifetrust.org.uk', 'www.lancswt.org.uk',
    'www.avonwildlifetrust.org.uk', 'www.gloucestershirewildlifetrust.co.uk',
    'www.warwickshirewildlifetrust.org.uk', 'www.surreywildlifetrust.org',
    'www.wemburymarinecentre.org', 'www.northwaleswildlifetrust.org.uk',
    'www.derbyshirewildlifetrust.org.uk', 'www.thebay.org.uk', 'www.mwt.im',
    'www.alderneywildlife.org', 'www.somersetwildlife.org',
    'www.cornwallwildlifetrust.org.uk', 'www.dorsetwildlifetrust.org.uk',
)
# The national aggregate is a discovery catalog, not a source to refresh for
# every local search. Regional sources retain independently configured coverage.
REGIONAL_HOSTS = tuple(host for host in NETWORK_HOSTS if host not in (
    'www.wildlifetrusts.org', 'www.mwt.im', 'www.alderneywildlife.org'))
URLS = tuple('https://' + host + '/events' + suffix
             for host in REGIONAL_HOSTS for suffix in ('', '/rss.xml'))
CATALOG_URLS = (NATIONAL, NATIONAL + '/rss.xml')


def validate_source(source):
    if source.get('feed_url') in CATALOG_URLS:
        raise ValueError('national_catalog_requires_regional_sources')
    if (source.get('feed_url') not in URLS
            or source.get('source_key') != source_key(source['feed_url'])
            or source.get('kind', 'html') != 'html'
            or source.get('platform_adapter', 'html') != 'html'):
        raise ValueError('wildlife_source_identity')


def allowed_hosts(url):
    if url not in URLS:
        raise ValueError('wildlife_source_identity')
    return (urlsplit(url).hostname,)


def rss_url(url):
    return url if url.endswith('/rss.xml') else url + '/rss.xml'


def _safe_url(value, hosts):
    from roomquest.registered_native_content import native_url
    return native_url(value) and urlsplit(value).hostname in hosts


def event_url_matches(source, value):
    if source.get('feed_url') not in URLS:
        return False
    return bool(_safe_url(value, allowed_hosts(source['feed_url']))
                and urlsplit(value).path.startswith('/events/')
                and not urlsplit(value).path.endswith('/rss.xml') and not urlsplit(value).query)


def _attach_native(row, source, node):
    from roomquest.registered_native_content import VERSION, image_candidate
    if type(source.get('registered_native_content_version')) is not int or source['registered_native_content_version'] != 1:
        return row
    if not event_url_matches(source, row['event_url']):
        raise ValueError('registered_native_evidence_invalid')
    hero = node.select_one('.field--name-field-event-photos [itemprop="image"] img[src]')
    candidate = image_candidate(hero['src'], row['event_url']) if hero else None
    row['image_extractor_version'] = VERSION
    row['registered_native_content'] = {
        'version': 1, 'source_key': source['source_key'], 'feed_url': source['feed_url'],
        'adapter': 'html', 'event_id': row['id'], 'event_url': row['event_url'],
        'description_field': 'wildlife_event_description' if row['description'] else None,
        'image_field': 'image' if candidate else None, 'extraction': EXTRACTION,
        'evidence_url': row['event_url'],
    }
    if candidate:
        row.update(image_url=candidate, image_provenance=VERSION, image_evidence_url=row['event_url'])
    return row


def validate_native(row, source):
    from roomquest.registered_native_content import VERSION, image_candidate
    validate_source(source)
    proof = row.get('registered_native_content') if isinstance(row, dict) else None
    if (not isinstance(proof, dict) or not event_url_matches(source, row.get('event_url'))
            or not isinstance(row.get('id'), str) or not 1 <= len(row['id']) <= 180
            or row['id'] != row['id'].strip()):
        raise ValueError('registered_native_evidence_invalid')
    text, image = row.get('description'), row.get('image_url')
    expected = {'version': 1, 'source_key': source['source_key'], 'feed_url': source['feed_url'],
                'adapter': 'html', 'event_id': row['id'], 'event_url': row['event_url'],
                'description_field': 'wildlife_event_description' if text else None,
                'image_field': 'image' if image else None, 'extraction': EXTRACTION,
                'evidence_url': row['event_url']}
    if (proof != expected or not isinstance(text, str) or len(text) > MAX_DESCRIPTION
            or re.search(r'<[^>]+>', text) or row.get('image_extractor_version') != VERSION
            or image and (image_candidate(image) != image or row.get('image_provenance') != VERSION
                          or row.get('image_evidence_url') != row['event_url'])
            or not image and any(row.get(key) is not None for key in ('image_provenance', 'image_evidence_url'))):
        raise ValueError('registered_native_evidence_invalid')


def _dates(value):
    try:
        pieces = value.split(' - ')
        if len(pieces) not in (1, 2):
            raise ValueError
        dates = [parsedate_to_datetime(v).date().isoformat() for v in pieces]
        if dates[-1] < dates[0]:
            raise ValueError
        return dates[0], dates[-1]
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('wildlife_rss_date_invalid') from exc


def parse_feed(payload, url, source):
    if '<!DOCTYPE' in payload.upper() or '<!ENTITY' in payload.upper():
        raise ValueError('wildlife_rss_invalid')
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError('wildlife_rss_invalid') from exc
    channel = root.find('channel')
    home = 'https://' + urlsplit(source['feed_url']).netloc + '/'
    if (root.tag != 'rss' or channel is None or channel.findtext('link') != home
            or channel.findtext('description') != 'Upcoming events'):
        raise ValueError('wildlife_rss_identity')
    result = []
    for item in channel.findall('item'):
        link, title = item.findtext('link'), item.findtext('title')
        if not isinstance(link, str) or not title:
            raise ValueError('wildlife_rss_invalid')
        start, end = _dates(item.findtext('pubDate') or '')
        # Membership in the manifest is evidence, not permission for any host.
        result.append({'url': link, 'title': title, 'start': start, 'end': end})
    next_links = [node.get('href') for node in channel.findall('{http://www.w3.org/2005/Atom}link')
                  if node.get('rel') == 'next']
    if len(next_links) > 1:
        raise ValueError('wildlife_rss_pagination_invalid')
    next_url = urljoin(url, next_links[0]) if next_links else None
    if next_url:
        base, parsed = urlsplit(rss_url(source['feed_url'])), urlsplit(next_url)
        if (not _safe_url(next_url, (base.hostname,)) or parsed.path != base.path
                or not re.fullmatch(r'page=[0-9]{1,4}', parsed.query)):
            raise ValueError('wildlife_rss_pagination_invalid')
    return result, next_url


def _field(node, name):
    found = node.select_one('.field--name-field-' + name)
    if found is None:
        return ''
    clone = BeautifulSoup(str(found), 'html.parser')
    for label in clone.select('.field__label'):
        label.decompose()
    return clone.get_text(' ', strip=True).strip(' ,')


def _clock(value):
    cleaned = re.sub(r'\s+', '', value.lower())
    # Lincolnshire publishes minute separators such as "1.30pm". Keep those
    # minutes distinct from the punctuation in "p.m." before normalizing it.
    cleaned = re.sub(r'(?<=\d)\.(?=\d)', ':', cleaned).replace('.', '')
    for fmt in ('%I:%M%p', '%I%p', '%H:%M'):
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            pass
    raise ValueError('wildlife_event_clock_unresolved')


def _event_clocks(node):
    """Read only the two observed native fields and reject disagreement."""
    values = []
    clock = r'([0-9]{1,2}(?:[.:][0-9]{2})?\s*(?:[ap]\.?m\.?)?)'
    for field in node.select('.field--name-field-event-time-value, .field--name-field-event-time'):
        clone = BeautifulSoup(str(field), 'html.parser')
        for label in clone.select('.field__label'):
            label.decompose()
        match = re.fullmatch(r'\s*' + clock + r'\s*(?:(?:[-–—]|to)\s*' + clock + r')?\s*',
                             clone.get_text(' ', strip=True), re.I)
        if not match:
            raise ValueError('wildlife_event_clock_unresolved')
        values.append((_clock(match[1]), _clock(match[2]) if match[2] else None))
    if not values or any(value != values[0] for value in values[1:]):
        raise ValueError('wildlife_event_clock_unresolved')
    return values[0]


def _place_fields(place):
    """Read one native Place's observed location or reserve address template."""
    reserve = 'node--type-reserve' in place.get('class', [])
    if reserve:
        if ('node--view-mode-address-string' not in place.get('class', [])
                or place.get('itemtype') not in ('http://schema.org/Place', 'https://schema.org/Place')):
            raise ValueError('wildlife_event_location_unresolved')
        names = place.select('[itemprop="name"]')
        addresses = place.select('[itemprop="address"]')
        if (len(names) != 1 or names[0].name != 'h3' or 'node__title' not in names[0].get('class', [])
                or len(addresses) != 1 or addresses[0].get('itemtype') not in (
                    'http://schema.org/PostalAddress', 'https://schema.org/PostalAddress')):
            raise ValueError('wildlife_event_location_unresolved')
        venue = names[0].get_text(' ', strip=True).strip(' ,')
        field_root, prefix = addresses[0], 'reserve'
    else:
        if len(place.select('.field--name-field-location-name')) != 1:
            raise ValueError('wildlife_event_location_unresolved')
        venue = _field(place, 'location-name')
        field_root, prefix = place, 'location'
    values = {}
    for suffix in ('address', 'town', 'county', 'postcode'):
        name = prefix + '-' + suffix
        if len(field_root.select('.field--name-field-' + name)) > 1:
            raise ValueError('wildlife_event_location_unresolved')
        values[suffix] = _field(field_root, name)
    street = ', '.join(value for value in values.values() if value)
    return venue, street, values['town'], reserve


def parse_detail(payload, item, *, source):
    """Return a dated occurrence or a specific reason to hold this item."""
    soup = BeautifulSoup(payload, 'html.parser')
    roots = soup.select('[itemtype="http://schema.org/Event"], [itemtype="https://schema.org/Event"]')
    if len(roots) != 1:
        return [], 'wildlife_detail_template_unreviewed'
    node = roots[0]
    # Lincoln embeds separately linked event cards without Event microdata
    # scopes. Exclude only their observed "further content" boundary; true
    # duplicate primary fields and unreviewed nested events still hold.
    for card in node.select(
            ':scope > .node__content > .field--name-field-further-content > '
            '.paragraph--card-feed.paragraph--type--event-feed.paragraph--view-mode--default '
            '.node__related__wrapper > article.node.node--type-event.node--view-mode-event-card.card'):
        card.decompose()
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical and canonical['href'].rstrip('/') != item['url'].rstrip('/'):
        return [], 'wildlife_detail_identity_changed'
    title_node = node.select_one('[itemprop="name"].page-title, h1 [itemprop="name"], h1')
    title_node = title_node or soup.select_one('h1.page-title, h1')
    title = title_node.get_text(' ', strip=True) if title_node else ''
    if not title:
        return [], 'wildlife_detail_title_missing'
    status = node.select_one('[itemprop="eventStatus"]')
    status_value = (status.get('content') or status.get('href') or status.get_text()) if status else ''
    if re.search(r'\bcancel(?:led|ed)\b', title, re.I) or status_value.endswith(('EventCancelled', 'EventPostponed')):
        return [], 'cancelled'
    date_nodes = node.select('.field--name-field-event-date time[datetime]')
    starts = [x for x in date_nodes if x.get('itemprop') == 'startDate']
    ends = [x for x in date_nodes if x.get('itemprop') == 'endDate']
    if len(starts) != 1 or len(ends) > 1:
        return [], 'wildlife_event_dates_unresolved'
    try:
        start_clock, end_clock = _event_clocks(node)
        start_value = starts[0]['datetime']
        # NWT publishes a calendar date plus a separate explicit native clock.
        # Only strict date-only metadata may be composed; an aware datetime
        # remains independent evidence and must agree with the visible clock.
        if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', start_value):
            start = timestamp(start_value + 'T' + start_clock.isoformat(), LONDON.key)
        else:
            start = timestamp(start_value)
        if start is None or start.tzinfo is None:
            raise ValueError
        local = start.astimezone(LONDON)
        end_value = ends[0]['datetime'] if ends else None
        if end_value and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', end_value):
            end_date = datetime.fromisoformat(end_value).date()
            if end_date != local.date():
                return [], 'wildlife_multiple_dates_unresolved'
            if end_clock is None:
                raise ValueError
            end = timestamp(datetime.combine(end_date, end_clock).isoformat(), LONDON.key)
        else:
            end = timestamp(end_value)
        if end is not None and end.tzinfo is None:
            raise ValueError
        if not item['start'] <= local.date().isoformat() <= item['end']:
            return [], 'wildlife_detail_date_conflict'
        if start_clock != local.time().replace(tzinfo=None):
            return [], 'wildlife_event_clock_unresolved'
        if end and end.astimezone(LONDON).date() != local.date():
            # A date span may describe separate sessions. Never turn it into a
            # continuous multi-day event, or infer a weekly/daily recurrence.
            return [], 'wildlife_multiple_dates_unresolved'
        if item['start'] != item['end']:
            return [], 'wildlife_multiple_dates_unresolved'
        if end_clock is not None:
            declared_end = timestamp(datetime.combine(local.date(), end_clock).isoformat(), LONDON.key)
            if declared_end <= start or end and declared_end != end:
                return [], 'wildlife_detail_time_conflict'
            end = declared_end
    except (ValueError, TypeError, KeyError):
        return [], 'wildlife_event_clock_unresolved'
    places = node.select('.field--name-field-event-location [itemprop="location"]')
    if len(places) != 1:
        return [], 'wildlife_event_location_unresolved'
    place = places[0]
    try:
        venue, street, city, reserve = _place_fields(place)
        lat_nodes, lng_nodes = place.select('[itemprop="latitude"]'), place.select('[itemprop="longitude"]')
        if (len(lat_nodes) > 1 or len(lng_nodes) > 1
                or reserve and (len(lat_nodes) != 1 or len(lng_nodes) != 1)):
            raise ValueError
        lat = float(lat_nodes[0]['content']) if lat_nodes else None
        lng = float(lng_nodes[0]['content']) if lng_nodes else None
    except (ValueError, TypeError, KeyError):
        return [], 'wildlife_event_location_unresolved'
    if not venue or not street or (lat is not None and not -90 <= lat <= 90) or (lng is not None and not -180 <= lng <= 180):
        return [], 'wildlife_event_location_unresolved'
    texts = []
    for selector in ('.field--name-field-event-summary', '.field--name-field-event-about'):
        section = node.select_one(selector)
        if section:
            clone = BeautifulSoup(str(section), 'html.parser')
            for label in clone.select('.field__label'):
                label.decompose()
            value = description(str(clone), limit=MAX_DESCRIPTION + 1)
            if value and value not in texts:
                texts.append(value)
    narrative = '\n\n'.join(texts)
    if not narrative:
        return [], 'wildlife_event_description_missing'
    if len(narrative) > MAX_DESCRIPTION:
        raise ValueError('wildlife_event_description_limit')
    row = record(title, start, end, venue, street, city, item['url'],
                 'wildlife:' + hashlib.sha256(item['url'].encode()).hexdigest()[:32],
                 'Nature', lat, lng, publisher_geo=True)
    if row is None:
        return [], 'outside_window'
    row.update(description=narrative, timezone=LONDON.key)
    return [_attach_native(row, source, node)], 'included'


def _manifest(source, fetch, *, listing=None, deadline_at=None):
    first = rss_url(source['feed_url'])
    url, seen, entries = first, set(), {}
    while url:
        if url in seen or len(seen) >= MAX_PAGES:
            raise ValueError('wildlife_rss_pagination_invalid')
        if deadline_at is not None and monotonic() + 2 >= deadline_at:
            raise ValueError('collection_deadline')
        seen.add(url)
        payload = listing if url == source['feed_url'] and listing is not None else fetch(url, 'application/rss+xml,application/xml,text/xml')
        rows, url = parse_feed(payload, url, source)
        if len(rows) >= 500 and url is None:
            # The national Drupal feed was observed capped at500. A regional
            # feed at the same ceiling needs an advertised continuation before
            # we can claim its current calendar has been completely discovered.
            raise ValueError('wildlife_rss_capacity_unverified')
        for row in rows:
            key = json.dumps(row, sort_keys=True)
            entries[key] = row
        if len(entries) > MAX_ITEMS:
            raise ValueError('wildlife_rss_item_limit')
    return sorted(entries.values(), key=lambda v: (v['url'], v['start'], v['end'], v['title']))


def probe(source, fetch, *, listing=None, deadline_at=None):
    """Validate intake, not a publication snapshot; collection starts privately."""
    validate_source(source)
    items = _manifest(source, fetch, listing=listing, deadline_at=deadline_at)
    if not items:
        raise ValueError('no_extractable_events')
    # Feed structure, exact publisher origin and complete manifest are proven.
    # Detail capture uses durable leases beyond registration's 35-second budget.
    return True


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None,
                  max_details=MAX_DETAILS, listing=None):
    validate_source(source)
    current = snapshot.now(now)
    if checkpoint is None:
        items = _manifest(source, fetch, listing=listing, deadline_at=deadline_at)
        state = {'started_at': current.isoformat(), 'items': items, 'outcomes': [], 'events': []}
        cursor, stage_cursor = 0, 0
    else:
        state = snapshot.decode(source, checkpoint, at=current)
        cursor, stage_cursor = checkpoint['cursor'], checkpoint['stage_cursor']
        if (not isinstance(state.get('items'), list) or len(state['items']) != checkpoint['manifest_count']
                or len(state.get('outcomes', [])) != cursor):
            raise ValueError('national_feed_checkpoint_invalid')
        if checkpoint['phase'] == 'stage':
            return {'complete': True, 'events': deepcopy(state['events']), 'checkpoint': checkpoint}
    first_cursor = cursor
    today = datetime.fromisoformat(state['started_at']).astimezone(LONDON).date()
    horizon = (today + timedelta(days=60)).isoformat()
    hosts = allowed_hosts(source['feed_url'])
    fetched = 0
    while cursor < len(state['items']) and fetched < min(MAX_DETAILS, max(1, max_details)):
        if deadline_at is not None and monotonic() + 6 >= deadline_at:
            break
        item = state['items'][cursor]
        url = item['url']
        if item['end'] < today.isoformat() or item['start'] > horizon:
            rows, reason = [], 'outside_window'
        elif not _safe_url(url, hosts) or not urlsplit(url).path.startswith('/events/') or urlsplit(url).query:
            rows, reason = [], 'wildlife_event_link_unreviewed'
        elif re.search(r'\bcancel(?:led|ed)\b', item['title'], re.I):
            rows, reason = [], 'cancelled'
        else:
            # Transport errors propagate and retain the last durable prefix.
            from roomquest.preview_worker import PreviewError
            try:
                rows, reason = parse_detail(fetch(url, 'text/html'), item, source=source)
            except PreviewError as exc:
                if str(exc) not in ('robots_denied', 'publisher_http_401', 'publisher_http_403',
                                    'publisher_http_404', 'publisher_http_410'):
                    raise
                rows, reason = [], str(exc)
            fetched += 1
        state['events'].extend(rows)
        state['outcomes'].append({'url': url, 'reason': reason, 'count': len(rows)})
        cursor += 1
    if first_cursor == cursor < len(state['items']):
        raise ValueError('collection_deadline')
    complete = cursor == len(state['items'])
    if complete:
        unique = {}
        for row in state['events']:
            key = (row['id'], row['starts_at'])
            if key in unique and unique[key] != row:
                raise ValueError('wildlife_conflicting_occurrence')
            unique[key] = row
        state['events'] = sorted(unique.values(), key=lambda row: (row['starts_at'], row['id']))
    encoded = snapshot.encode(source, state, phase='stage' if complete else 'fetch',
                              cursor=cursor, count=len(state['items']), stage_cursor=stage_cursor)
    return {'complete': complete, 'events': deepcopy(state['events']) if complete else [], 'checkpoint': encoded}


def collect(source, fetch, *, deadline_at=None, listing=None):
    """Legacy/manual calls can never certify a manifest prefix."""
    result = collect_chunk(source, fetch, deadline_at=deadline_at, listing=listing)
    if not result['complete']:
        raise ValueError('publisher_checkpoint_required')
    return result['events']
