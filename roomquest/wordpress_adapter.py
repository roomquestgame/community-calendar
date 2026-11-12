"""Shared Events Calendar collection, independent of catalog provenance.

Uses the existing factual parser, SSRF/robots transport and downstream staging.
No venue search, source-wide pin, extra scheduler or provider identity change.
"""
from datetime import datetime, timedelta, timezone
import json
import re
import sys
from time import monotonic
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

MAX_PAGES = 5
MAX_RECORDS = 500
MAX_MADISON_TIME_REVIEWS = 5
ROSEMONT_KEY = 'rosemont_of_virginia'
ROSEMONT_URL = 'https://rosemontofvirginia.com/wp-json/tribe/events/v1/events'
ROSEMONT_TIMEZONE = 'America/New_York'
HAMPTON_TRIBE_SOURCES = {
    'municipal_e3269f28ac6baa042d42de36': 'https://beacheventsvb.com/wp-json/tribe/events/v1/events',
    'municipal_2ec2b4eebdf3998055908a82': 'https://virginiamoca.org/wp-json/tribe/events/v1/events',
}
BEACH_EVENTS = 'municipal_e3269f28ac6baa042d42de36'
VIRGINIA_MOCA = 'municipal_2ec2b4eebdf3998055908a82'


def _hampton_venue(source_key, row):
    """Fill missing street addresses only for named venues reviewed on the publisher sites."""
    from roomquest.mapsee_adapter import plain
    venue = plain(row.get('venue_name')).casefold()
    address = row.get('venue_address') or ''
    if re.search(r'\b\d{1,6}\s+[A-Za-z]', address):
        return row
    if source_key == VIRGINIA_MOCA and venue in {'virginia moca', 'virginia museum of contemporary art'}:
        address = '5811 Wesleyan Drive, Virginia Beach, VA 23455'
    elif source_key == BEACH_EVENTS and venue == '31st street park oceanfront':
        # Neptune statue is the park's street-addressed landmark.
        address = '3001 Atlantic Avenue, Virginia Beach, VA 23451'
    return dict(row, venue_address=address) if address else row


def _rosemont_log(kind, **fields):
    print(json.dumps({'event': 'rosemont_' + kind, 'source_key': ROSEMONT_KEY,
                      **fields}, sort_keys=True), file=sys.stderr)


def _rosemont_review(payload):
    """Review only this publisher's records; missing venues never inherit the winery.

    The reviewed November 21 occurrence has an unresolved header/body conflict.
    Keep it out of publication until reviewed, without changing either time.
    Holds are diagnostic exclusions, not inferred event cancellations.
    """
    from roomquest.mapsee_adapter import plain, timestamp
    accepted, held, excluded = [], 0, 0
    for item in payload['events']:
        if not isinstance(item, dict):
            raise ValueError('invalid_calendar_record')
        flags = (True, 1, '1', 'true')
        labels = [plain(c.get('name')).casefold() for c in item.get('categories', [])
                  if isinstance(c, dict)]
        title = plain(item.get('title'))
        narrative = plain(item.get('description'))
        if (item.get('status') != 'publish'
                or item.get('event_status') in ('cancelled', 'canceled', 'postponed')
                or any(item.get(k) in flags for k in
                       ('hide_from_listings', 'all_day', 'is_virtual', 'virtual'))
                or any(label in ('closings', 'closing', 'closures') for label in labels)
                or re.search(r'\b(?:winery closed|holiday hours|christmas day hours)\b', title, re.I)
                or re.search(r'\b(?:members?[\s-]+only|private\s+(?:event|party|function)|'
                             r'invitation[\s-]+only)\b', title + ' ' + narrative, re.I)):
            excluded += 1
            continue
        identity = str(item.get('id') or '')
        if not identity.isdigit():
            raise ValueError('event_identity_missing')
        if item.get('timezone') != ROSEMONT_TIMEZONE:
            raise ValueError('publisher_timezone_review_required')
        for field in ('start_date', 'end_date'):
            local, utc = item.get(field), item.get('utc_' + field)
            if field == 'end_date' and not local and not utc:
                continue
            if (not local or not utc
                    or timestamp(local, ROSEMONT_TIMEZONE) != timestamp(utc, 'UTC')):
                raise ValueError('publisher_schedule_conflict')
        reason = None
        if (identity == '7956'
                and item.get('url') == 'https://rosemontofvirginia.com/event/wine-dine-w-beer-fed-beef-6/'
                and str(item.get('start_date', '')).startswith('2026-11-21')):
            reason = 'publisher_header_body_time_conflict'
        venue = item.get('venue')
        if not reason and (not isinstance(venue, dict)
                or not plain(venue.get('venue'))
                or not re.search(r'\b\d{1,6}\s+[A-Za-z]', plain(venue.get('address')))
                or not plain(venue.get('city'))
                or not plain(venue.get('state') or venue.get('stateprovince') or venue.get('province'))):
            reason = 'event_venue_unreviewed'
        if reason:
            held += 1
            _rosemont_log('event_held', event_id=identity, reason=reason)
            continue
        accepted.append(item)
    return dict(payload, events=accepted), held, excluded


def _rosemont_evidence(row, item):
    from roomquest.publisher_evidence import attach
    row['publisher_categories'] = [c['name'] for c in item.get('categories', [])
                                   if isinstance(c, dict) and isinstance(c.get('name'), str)]
    row['location_provenance'] = 'publisher_event_address_pending_geocode'
    featured = item.get('image')
    candidate = featured.get('url') if isinstance(featured, dict) else None
    cost = item.get('cost')
    facts = {'cost': cost.strip()[:400]} if isinstance(cost, str) and cost.strip() else {}
    return attach(row, ROSEMONT_KEY, facts=facts, candidate=candidate)


def _madison_evidence(row, item):
    """Use only this event's API content; optional images never add a fetch."""
    from bs4 import BeautifulSoup
    from roomquest.publisher_evidence import attach, family, image_url
    if family('madison_county_parks_ia', row['event_url']) != 'madison':
        return row
    soup = BeautifulSoup(item.get('description') or '', 'html.parser')
    for tag in soup.select('script, style, template, noscript'):
        tag.decompose()
    candidates = {u for tag in soup.select('img[src]')
                  if (u := image_url(tag.get('src'), 'madison'))}
    featured = item.get('image')
    if isinstance(featured, dict) and (u := image_url(featured.get('url'), 'madison')):
        candidates.add(u)
    # More than one publisher image is ambiguous; do not choose arbitrarily.
    candidate = next(iter(candidates)) if len(candidates) == 1 else None
    narrative = row.get('description', '')
    # Only explicit introductory scheduling prose, never a historical date in
    # a talk's subject. A warning preserves the publisher's original wording.
    mention = re.search(r'\bJoin us\b[^.\n]{0,160}?\bon\s+([A-Za-z]+)\s+(\d{1,2})\b', narrative, re.I)
    months = {name.lower(): number for number, name in enumerate(
        ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
         'September', 'October', 'November', 'December'), 1)}
    months.update({name[:3]: number for name, number in list(months.items())})
    if mention and item.get('start_date'):
        day = datetime.fromisoformat(item['start_date']).date()
        month = months.get(mention[1].lower())
        if month and (month, int(mention[2])) != (day.month, day.day):
            note = ('Schedule note: The date in the publisher description conflicts with its calendar. '
                    'Use the event date shown above and confirm with the organizer.\n\n')
            row['description'] = note + narrative[:2000 - len(note)]
    cost = item.get('cost')
    facts = {'cost': cost.strip()[:400]} if isinstance(cost, str) and cost.strip() else {}
    return attach(row, 'madison_county_parks_ia', facts=facts, candidate=candidate)


def _madison_display_schedule(item, source, fetch):
    """Resolve only a misconfigured publisher zone with same-event HTML proof."""
    from bs4 import BeautifulSoup
    from roomquest.mapsee_adapter import plain, timestamp
    root, link = urlsplit(source['feed_url']), urlsplit(item.get('url', ''))
    if (link.scheme != 'https' or link.netloc != root.netloc or link.query or link.fragment
            or not link.path.startswith('/calendar/') or '..' in link.path.split('/')):
        raise ValueError('publisher_timezone_review_required')
    soup = BeautifulSoup(fetch(item['url'], 'text/html'), 'html.parser')
    title = soup.select_one('.tribe-events-single-event-title')
    start = soup.select_one('.tribe-event-date-start')
    end = soup.select_one('.tribe-events-schedule .tribe-event-time')
    day = soup.select_one('.tribe-events-start-time[title]')
    if not all((title, start, end, day)) or plain(title.get_text()) != plain(item.get('title')):
        raise ValueError('publisher_timezone_review_required')
    try:
        local_start = datetime.fromisoformat(item['start_date'])
        local_end = datetime.fromisoformat(item['end_date'])
        displayed_start = datetime.strptime(start.get_text(' ', strip=True).split('@')[-1].strip(), '%I:%M %p').time()
        displayed_end = datetime.strptime(end.get_text(' ', strip=True), '%I:%M %p').time()
        if (local_start.tzinfo or local_end.tzinfo or local_start.date() != local_end.date()
                or day['title'] != local_start.date().isoformat()
                or local_start.time() != displayed_start or local_end.time() != displayed_end):
            raise ValueError('publisher_timezone_review_required')
        begins = timestamp(item['start_date'], source['timezone'])
        ends = timestamp(item['end_date'], source['timezone'])
        if ends <= begins:
            raise ValueError('publisher_timezone_review_required')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('publisher_timezone_review_required') from exc
    return dict(item, timezone=source['timezone'],
                utc_start_date=begins.astimezone(timezone.utc).isoformat(),
                utc_end_date=ends.astimezone(timezone.utc).isoformat())


def collect(source, fetch, *, deadline_at=None):
    source_key = source.get('source_key')
    hampton_url = HAMPTON_TRIBE_SOURCES.get(source_key)
    if hampton_url and (source.get('feed_url'), source.get('timezone')) != (hampton_url, 'America/New_York'):
        raise ValueError('unregistered_hampton_wordpress_source')
    if source.get('source_key') == 'think_iowa_city_ia':
        from roomquest.iowa_tourism import collect_think
        return collect_think(source, fetch, deadline_at=deadline_at)
    from roomquest.mapsee_adapter import TRIBE_UTC_DEFAULT_ZONES, parse_tribe
    from roomquest import ncma_calendar
    ncma = source.get('source_key') == ncma_calendar.KEY
    if ncma and source.get('feed_url') != ncma_calendar.ROOT:
        raise ValueError('unregistered_ncma_calendar')
    from roomquest import hurrdat_calendar, jpb_basketball
    hurrdat = source.get('source_key') == hurrdat_calendar.KEY
    if hurrdat and (source.get('feed_url'), source.get('timezone')) != (hurrdat_calendar.URL, hurrdat_calendar.ZONE):
        raise ValueError('unregistered_hurrdat_source')
    jpb = source.get('source_key') == jpb_basketball.KEY
    if jpb and (source.get('feed_url'), source.get('timezone')) != (jpb_basketball.URL, jpb_basketball.ZONE):
        raise ValueError('unregistered_jpb_calendar')
    rosemont = source.get('source_key') == ROSEMONT_KEY
    if rosemont and (source.get('feed_url') != ROSEMONT_URL
                     or source.get('timezone', ROSEMONT_TIMEZONE) != ROSEMONT_TIMEZONE):
        raise ValueError('unregistered_rosemont_source')
    root = urlsplit(source['feed_url'])
    if '/wp-json/tribe/events/v1/events' in root.path:
        if root.path.rstrip('/').split('/wp-json/', 1)[1] != 'tribe/events/v1/events':
            raise ValueError('unsupported_wordpress_endpoint')
        path = root.path
    else:
        path = root.path.rstrip('/') + '/wp-json/tribe/events/v1/events'
    params = dict(parse_qsl(root.query, keep_blank_values=True))
    now = datetime.now(timezone.utc)
    params.update(per_page=100, start_date=now.date().isoformat(),
                  end_date=(now + timedelta(days=60)).date().isoformat())
    deadline = min(monotonic() + 35, deadline_at or float('inf'))
    rows = []
    time_reviews = 0
    rosemont_held = rosemont_excluded = ncma_held = 0
    for page in range(1, MAX_PAGES + 1):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        params['page'] = page
        page_params = params
        if source_key == BEACH_EVENTS:
            # This publisher exposes the default upcoming list on its public API.
            # Keep later pages on the same endpoint and use its default page size.
            page_params = {} if page == 1 else {'page': page}
        url = urlunsplit((root.scheme, root.netloc, path, urlencode(page_params), ''))
        payload = json.loads(fetch(url, 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
            raise ValueError('unsupported_wordpress_payload')
        if len(payload['events']) > 100:
            raise ValueError('source_record_limit')
        if rosemont:
            payload, held, excluded = _rosemont_review(payload)
            rosemont_held += held
            rosemont_excluded += excluded
        if ncma:
            payload, held = ncma_calendar.review(payload)
            ncma_held += held
        if jpb:
            payload = jpb_basketball.review(payload)
        if hurrdat:
            payload = hurrdat_calendar.review(payload)
        if source.get('source_key') == 'madison_county_parks_ia':
            # Compare two representations from the same response. Never repair
            # publisher conflicts by guessing an offset or reading prose dates.
            from roomquest.mapsee_adapter import timestamp, tribe_timezone
            for index, item in enumerate(payload['events']):
                if not isinstance(item, dict) or item.get('status') != 'publish':
                    continue
                if item.get('timezone') and source.get('timezone'):
                    zone, _ = tribe_timezone(item['timezone'])
                    expected_zone, _ = tribe_timezone(source['timezone'])
                    instant = timestamp(item.get('utc_start_date'), 'UTC')
                    if instant and instant.astimezone(zone).utcoffset() != instant.astimezone(expected_zone).utcoffset():
                        time_reviews += 1
                        if time_reviews > MAX_MADISON_TIME_REVIEWS or monotonic() >= deadline:
                            raise ValueError('publisher_timezone_review_required')
                        item = _madison_display_schedule(item, source, fetch)
                        payload['events'][index] = item
                for field in ('start_date', 'end_date'):
                    local, utc = item.get(field), item.get('utc_' + field)
                    if local and utc and item.get('timezone'):
                        zone, _ = tribe_timezone(item['timezone'])
                        wall = datetime.fromisoformat(local.replace('Z', '+00:00'))
                        # Preserve explicit offsets; reject ambiguous IANA wall
                        # times through the existing strict timestamp helper.
                        if wall.tzinfo is None:
                            wall = (wall.replace(tzinfo=zone) if item['timezone'].startswith('UTC')
                                    else timestamp(local, item['timezone']))
                        if wall != timestamp(utc, 'UTC'):
                            raise ValueError('publisher_schedule_conflict')
        # Never follow response next links; rebuild only this registered URL.
        utc_default_zone = 'America/New_York' if source_key == VIRGINIA_MOCA else TRIBE_UTC_DEFAULT_ZONES.get(source_key)
        parsed_rows = parse_tribe(payload, strict_public=bool(hampton_url) or ncma or source.get("source_key") in
                                  ("madison_county_parks_ia", "nebraska_game_parks", ROSEMONT_KEY, jpb_basketball.KEY, hurrdat_calendar.KEY),
                                retain_description=bool(hampton_url) or ncma or source.get("source_key") in
                                  ("madison_county_parks_ia", ROSEMONT_KEY, jpb_basketball.KEY, hurrdat_calendar.KEY),
                                utc_default_zone=utc_default_zone)
        if hampton_url:
            parsed_rows = [_hampton_venue(source_key, row) for row in parsed_rows]
        if rosemont:
            by_id = {str(item['id']): item for item in payload['events']}
            parsed_rows = [_rosemont_evidence(row, by_id[row['id']]) for row in parsed_rows]
        if jpb:
            by_id = {str(item['id']): item for item in payload['events']}
            parsed_rows = [jpb_basketball.evidence(row, by_id[row['id']]) for row in parsed_rows]
        if hurrdat:
            by_id = {str(item['id']): item for item in payload['events']}
            parsed_rows = [hurrdat_calendar.evidence(row, by_id[row['id']]) for row in parsed_rows]
        if source.get('source_key') == 'madison_county_parks_ia':
            by_id = {str(item.get('id')): item for item in payload['events'] if isinstance(item, dict)}
            parsed_rows = [_madison_evidence(row, by_id[row['id']]) for row in parsed_rows]
        rows.extend(parsed_rows)
        if len(rows) > MAX_RECORDS:
            raise ValueError('source_record_limit')
        total_pages = payload.get('total_pages', 1)
        if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 0:
            raise ValueError('invalid_wordpress_pagination')
        if not payload.get('next_rest_url') and page >= total_pages:
            break
        if page == MAX_PAGES:
            raise ValueError('pagination_limit')
    unique = {}
    for row in rows:
        key = (row.get('id') or row['title'], row['starts_at'])
        if key in unique and any(unique[key].get(k) != row.get(k)
                                for k in ('title', 'venue_name', 'venue_address', 'lat', 'lng')):
            raise ValueError('conflicting_event_occurrence')
        unique[key] = row
    result = sorted(unique.values(), key=lambda e: (e['starts_at'], e['title']))
    if rosemont:
        _rosemont_log('normalized', held=rosemont_held, excluded=rosemont_excluded, records=len(result))
        if not result and rosemont_held:
            raise ValueError('rosemont_event_evidence_unavailable')
    if not result and ncma_held:
        raise ValueError('ncma_event_venue_unreviewed')
    if result and not any(e.get('venue_name') or e.get('venue_address') for e in result):
        raise ValueError('venue_extraction_unavailable')
    return result

