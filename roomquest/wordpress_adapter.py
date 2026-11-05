"""Shared Events Calendar collection, independent of catalog provenance.

Uses the existing factual parser, SSRF/robots transport and downstream staging.
No venue search, source-wide pin, extra scheduler or provider identity change.
"""
from datetime import datetime, timedelta, timezone
import json
from time import monotonic
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

MAX_PAGES = 5
MAX_RECORDS = 500
MAX_MADISON_TIME_REVIEWS = 5


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
    from roomquest.mapsee_adapter import parse_tribe
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
    for page in range(1, MAX_PAGES + 1):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        params['page'] = page
        payload = json.loads(fetch(urlunsplit((root.scheme, root.netloc, path,
                                               urlencode(params), '')), 'application/json'))
        if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
            raise ValueError('unsupported_wordpress_payload')
        if len(payload['events']) > 100:
            raise ValueError('source_record_limit')
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
        rows.extend(parse_tribe(payload, strict_public=source.get("source_key") in
                                  ("madison_county_parks_ia", "nebraska_game_parks"),
                               retain_description=source.get("source_key") == "madison_county_parks_ia"))
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
    if result and not any(e.get('venue_name') or e.get('venue_address') for e in result):
        raise ValueError('venue_extraction_unavailable')
    return result

