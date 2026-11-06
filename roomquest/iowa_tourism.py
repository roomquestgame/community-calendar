"""Reviewed Iowa calendars: publisher occurrences, never inferred opening hours."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlencode
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString
from icalendar import Calendar

from roomquest.mapsee_adapter import record, timestamp, plain
from roomquest.publisher_evidence import attach
from roomquest.mycountyparks import cancelled

TZ = ZoneInfo('America/Chicago')
SOURCES = {
    'unleashcb_ia': 'https://www.unleashcb.com/events/calendar/',
    'visit_mason_city_ia': 'https://www.visitmasoncityiowa.com/calendar/',
}
log = logging.getLogger(__name__)


def text(node, limit=2000):
    if node is None:
        return ''
    soup = BeautifulSoup(str(node), 'html.parser')
    for tag in soup.select('script,style,template,noscript,[hidden]'):
        tag.decompose()
    return '\n'.join(x.strip() for x in soup.get_text('\n').splitlines() if x.strip())[:limit]


def withheld(key, identity, reason):
    log.warning('iowa_record_withheld source=%s id=%s reason=%s', key, identity, reason)


def clock(value):
    value = re.sub(r'\s+', '', value).upper()
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def council_times(day, value):
    value = re.sub(r'\s+', '', value).lower()
    parts = re.split(r'to|[–-]', value)
    if len(parts) not in (1, 2):
        raise ValueError('publisher_time_unresolved')
    if len(parts) == 1:
        return datetime.combine(day, clock(parts[0]), TZ), None
    a, b = parts
    if not re.search('[ap]m$', b):
        raise ValueError('publisher_time_unresolved')
    finish = datetime.combine(day, clock(b), TZ)
    choices = [a] if re.search('[ap]m$', a) else [a + 'am', a + 'pm']
    matches = []
    for choice in choices:
        start = datetime.combine(day, clock(choice), TZ)
        end = finish + (timedelta(days=1) if finish <= start and len(choices) == 1 else timedelta())
        if timedelta() < end - start <= timedelta(hours=12):
            matches.append((start, end))
    if len(matches) != 1:
        raise ValueError('publisher_time_unresolved')
    return matches[0]


def parse_council(html, *, now=None, expected_month=None):
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, 'html.parser')
    headings = [h.get_text(' ', strip=True) for h in soup.select('h1,h2')
                if re.fullmatch(r'Events for [A-Za-z]+ 20\d{2}', h.get_text(' ', strip=True))]
    if expected_month and (len(headings) != 1 or
            datetime.strptime(headings[0], 'Events for %B %Y').strftime('%Y-%m') != expected_month):
        raise ValueError('publisher_calendar_month_conflict')
    cards = soup.select('div.event-overlay[id]')
    if (not cards and len(headings) != 1) or len(cards) > 500:
        raise ValueError('publisher_calendar_structure_changed')
    rows = []
    for card in cards:
        identity = card['id']
        title = card.select_one('h3 a[href]')
        day, times = card.select_one('.eventOverlayDate'), card.select_one('.eventOverlayTime')
        if not title or not day:
            raise ValueError('publisher_calendar_structure_changed')
        try:
            date = datetime.strptime(day.get_text(' ', strip=True), '%B %d, %Y').date()
            if date < now.astimezone(TZ).date() or date > (now + timedelta(days=60)).astimezone(TZ).date():
                continue
            url = urljoin(SOURCES['unleashcb_ia'], title['href'])
            if not re.fullmatch(r'https://www\.unleashcb\.com/events/detail/[a-z0-9_\-]+/\d{4}-\d{2}-\d{2}/', url):
                raise ValueError('publisher_event_link_unresolved')
            if url.rstrip('/').rsplit('/', 1)[-1] != date.isoformat():
                raise ValueError('publisher_calendar_date_conflict')
            if not times:
                raise ValueError('publisher_time_unresolved')
            start, end = council_times(date, times.get_text(' ', strip=True))
            labels = []
            for sibling in title.parent.next_siblings:
                if getattr(sibling, 'name', None) == 'div':
                    break
                if isinstance(sibling, NavigableString) and sibling.strip():
                    labels.append(plain(sibling))
            venue = labels[0] if labels else ''
            if re.search(r'\b(online|virtual|zoom)\b', venue, re.I):
                raise ValueError('remote_event')
            map_link = next((a for a in card.select('a[href]')
                             if a['href'].startswith('https://www.google.com/maps/?q=')), None)
            address = parse_qs(urlsplit(map_link['href']).query).get('q', [''])[0] if map_link else ''
            # Only the event's own map-address evidence; not the tourism office.
            if not re.search(r',\s*[A-Z]{2}(?:\s+\d{5})?$', address):
                address = ''
            section = BeautifulSoup('<div></div>', 'html.parser').div
            divider = next((d for d in card.select('div[style]') if 'border-bottom' in d.get('style', '')), None)
            if divider:
                for sibling in divider.next_siblings:
                    if getattr(sibling, 'name', None) in ('p', 'ul', 'ol', 'h3'):
                        fragment = BeautifulSoup(str(sibling), 'html.parser')
                        for button in fragment.select('a.button,script,style'):
                            button.decompose()
                        section.append(fragment)
            narrative = text(section)
            if cancelled(title.get_text(), narrative):
                raise ValueError('publisher_cancelled')
            row = record(title.get_text(), start.isoformat(), end.isoformat() if end else None,
                         venue, address, labels[2] if len(labels) > 2 else '', url,
                         'unleashcb:' + identity + ':' + date.isoformat(), tz=TZ.key,
                         retain_until_end=True)
            if not row:
                continue
            if not narrative:
                raise ValueError('publisher_description_missing')
            row['description'] = narrative
            image = card.select_one('a[href] > img[src]')
            candidate = urljoin(url, image['src']) if image else None
            rows.append(attach(row, 'unleashcb_ia', candidate=candidate))
        except (ValueError, TypeError, KeyError) as exc:
            withheld('unleashcb_ia', identity, str(exc))
    return rows


def mason_links(html):
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    for a in soup.select('a[href]'):
        u = urljoin(SOURCES['visit_mason_city_ia'], a['href'])
        if re.fullmatch(r'https://www\.visitmasoncityiowa\.com/20\d{2}/\d{1,2}/\d{1,2}/[1-9]\d*/[a-z0-9-]+/', u) and u not in links:
            links.append(u)
    if not links or len(links) > 20:
        raise ValueError('publisher_calendar_structure_changed')
    return links


def parse_mason(html, url, *, now=None):
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, 'html.parser')
    containers = soup.select('[itemtype="http://schema.org/Event"]')
    if len(containers) != 1:
        raise ValueError('publisher_event_structure_changed')
    section = containers[0]
    name = section.select_one('h1[itemprop="name"]')
    day = section.select_one('[itemprop="startDate"]')
    displayed = section.select_one('[itemprop="doorTime"]')
    calendars = {a['href'] for a in section.select('a[href]') if a['href'].startswith('data:text/calendar')}
    if not name or not day or not displayed or len(calendars) != 1:
        raise ValueError('publisher_event_structure_changed')
    encoded = next(iter(calendars)).split(',', 1)[1]
    if len(encoded) > 100000:
        raise ValueError('source_record_limit')
    events = Calendar.from_ical(unquote(encoded)).walk('VEVENT')
    if len(events) != 1:
        raise ValueError('publisher_calendar_identity_conflict')
    event = events[0]
    title = plain(name.get_text())
    if plain(event.get('SUMMARY')) != title:
        raise ValueError('publisher_calendar_identity_conflict')
    start, end = event.decoded('DTSTART'), event.decoded('DTEND') if event.get('DTEND') else None
    if not isinstance(start, datetime) or start.tzinfo is None or (end and (not isinstance(end, datetime) or end.tzinfo is None)):
        raise ValueError('publisher_time_unresolved')
    local = start.astimezone(TZ)
    date = datetime.strptime(day.get_text(' ', strip=True), '%b %d, %Y').date()
    path = urlsplit(url).path.strip('/').split('/')
    if date != datetime(int(path[0]), int(path[1]), int(path[2])).date():
        raise ValueError('publisher_calendar_date_conflict')
    visible = re.fullmatch(r'(\d{1,2}:\d{2}\s*[AP]M)\s+(C[DS]T)', displayed.get_text(' ', strip=True))
    if not visible or date != local.date() or clock(visible[1]) != local.time() or visible[2] != local.tzname():
        raise ValueError('publisher_timezone_review_required')
    if end and (end <= start or end - start > timedelta(hours=16)):
        raise ValueError('publisher_occurrence_schedule_unresolved')
    # Locable's calendar export defaults a one-hour end even for start-only
    # listings. Only an explicitly displayed end can be called verified.
    end_text = displayed.parent.get_text(' ', strip=True)
    explicit_end = re.search(r'\bto\s*(\d{1,2}:\d{2}\s*[AP]M)\s+(C[DS]T)', end_text)
    if explicit_end:
        ending = end.astimezone(TZ) if end else None
        if not ending or ending.time() != clock(explicit_end[1]) or ending.tzname() != explicit_end[2]:
            raise ValueError('publisher_calendar_end_conflict')
    else:
        end = None
    location, address = section.select_one('[itemprop="location"]'), section.select_one('[itemprop="address"]')
    narrative = text(section.select_one('[itemprop="description"]'))
    if not location or not address or not narrative:
        raise ValueError('publisher_event_facts_missing')
    if cancelled(title, narrative):
        raise ValueError('publisher_cancelled')
    if re.search(r'\b(online|virtual|zoom)\b', location.get_text(), re.I):
        raise ValueError('remote_event')
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 location.get_text(), address.get_text(), '', url,
                 'locable:' + path[3], tz=TZ.key, retain_until_end=True)
    if not row:
        return None
    row['description'] = narrative
    photo = section.select_one('.blog-show-image img[itemprop="image"][src]')
    return attach(row, 'visit_mason_city_ia', candidate=photo['src'] if photo else None)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if (key not in SOURCES or source.get('feed_url') != SOURCES[key]
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone') not in (None, '', TZ.key)):
        raise ValueError('unregistered_iowa_tourism_source')
    now = now or datetime.now(timezone.utc)
    deadline = min(monotonic() + 34, deadline_at or float('inf'))
    if key == 'unleashcb_ia':
        # Three calendar months cover a rolling sixty-day window. Every event
        # overlay already contains its factual detail: no per-event requests.
        months = []
        day = now.astimezone(TZ).date().replace(day=1)
        while day <= (now + timedelta(days=60)).astimezone(TZ).date():
            months.append(day.strftime('%Y-%m'))
            day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
        rows = []
        for month in months:
            if monotonic() >= deadline:
                raise ValueError('collection_deadline')
            rows.extend(parse_council(fetch(SOURCES[key] + 'mo/' + month + '/', 'text/html'),
                                      now=now, expected_month=month))
    else:
        # Explicit first-page scope. Absence never means cancellation; the
        # backend must preserve previously collected occurrences as pages move.
        links = mason_links(fetch(SOURCES[key], 'text/html'))
        def detail(url):
            if monotonic() >= deadline:
                raise ValueError('collection_deadline')
            html = fetch(url, 'text/html')
            try:
                return parse_mason(html, url, now=now)
            except (ValueError, TypeError, KeyError) as exc:
                withheld(key, url, str(exc))
                return None
        with ThreadPoolExecutor(max_workers=3) as pool:
            rows = [row for row in pool.map(detail, links) if row]
    unique = {}
    for row in rows:
        identity = (row['id'], row['starts_at'])
        if identity in unique and unique[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        unique[identity] = row
    if len(unique) > 500:
        raise ValueError('source_record_limit')
    return sorted(unique.values(), key=lambda r: (r['starts_at'], r['id']))


def collect_think(source, fetch, *, deadline_at=None):
    from roomquest.mapsee_adapter import parse_tribe
    key = 'think_iowa_city_ia'
    endpoint = 'https://thinkiowacity.com/wp-json/tribe/events/v1/events'
    if (source.get('source_key') != key or source.get('feed_url') != endpoint
            or source.get('kind') != 'json' or source.get('platform_adapter') != 'wordpress'
            or source.get('timezone') != TZ.key):
        raise ValueError('unregistered_iowa_tourism_source')
    now = datetime.now(timezone.utc)
    deadline = min(monotonic() + 30, deadline_at or float('inf'))
    rows = []
    for page in range(1, 6):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        params = {'per_page': 100, 'page': page, 'start_date': now.date().isoformat(),
                  'end_date': (now + timedelta(days=60)).date().isoformat()}
        data = json.loads(fetch(endpoint + '?' + urlencode(params), 'application/json'))
        if not isinstance(data, dict) or not isinstance(data.get('events'), list) or len(data['events']) > 100:
            raise ValueError('unsupported_wordpress_payload')
        pages = data.get('total_pages', 1)
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 0 or pages > 5:
            raise ValueError('pagination_limit')
        for item in data['events']:
            if not isinstance(item, dict):
                raise ValueError('unsupported_wordpress_payload')
            try:
                if item.get('status') != 'publish' or item.get('all_day') is True:
                    continue
                if item.get('timezone') != TZ.key:
                    raise ValueError('publisher_timezone_review_required')
                start = timestamp(item.get('start_date'), TZ.key)
                end = timestamp(item.get('end_date'), TZ.key)
                if not start or not end or end <= start or end - start > timedelta(hours=16):
                    raise ValueError('publisher_occurrence_schedule_unresolved')
                if (timestamp(item.get('utc_start_date'), 'UTC') != start
                        or timestamp(item.get('utc_end_date'), 'UTC') != end):
                    raise ValueError('publisher_schedule_conflict')
                parsed = parse_tribe({'events': [item]}, strict_public=True, retain_description=True)
                if not parsed:
                    continue
                row = parsed[0]
                if cancelled(row['title'], row.get('description', '')):
                    raise ValueError('publisher_cancelled')
                if not row.get('description'):
                    raise ValueError('publisher_description_missing')
                venue = item.get('venue') or {}
                if not re.search(r'\d+\s+\S+', plain(venue.get('address'))):
                    row['venue_address'] = ''
                image = item.get('image')
                image = image.get('url') if isinstance(image, dict) else None
                cost = item.get('cost')
                facts = {'cost': plain(cost)[:400]} if isinstance(cost, str) and plain(cost) else {}
                row['publisher_categories'] = [plain(c.get('name'))[:100] for c in item.get('categories', [])
                                               if isinstance(c, dict) and plain(c.get('name'))][:20]
                rows.append(attach(row, key, candidate=image, facts=facts))
            except (ValueError, TypeError, KeyError) as exc:
                withheld(key, item.get('id'), str(exc))
        if page >= pages and not data.get('next_rest_url'):
            break
        if page == 5:
            raise ValueError('pagination_limit')
    if len(rows) > 500:
        raise ValueError('source_record_limit')
    result = {}
    for row in rows:
        identity = (row['id'], row['starts_at'])
        if identity in result and result[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        result[identity] = row
    return sorted(result.values(), key=lambda r: (r['starts_at'], r['id']))
