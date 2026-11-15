"""Complete first-party Raleigh arts/community calendars.

All I/O is injected by the worker's paced, robots-aware transport. Calendar
navigation is bounded to the frozen 60 local dates; no partial snapshot is
returned for staging. Full publisher prose and exact venue streets survive.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import html
import json
import math
import re
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record, timestamp

ZONE = 'America/New_York'
NATURAL = 'municipal_dfbc4fd7bb8cf284b5c0856d'
CARY = 'downtown_cary_park_nc'
ARTSPACE = 'artspace_raleigh_nc'
RLT = 'raleigh_little_theatre_nc'
SOURCES = {
    NATURAL: ('https://www.naturalsciences.org/calendar/', 'html', 'html'),
    CARY: ('https://downtowncarypark.com/calendar', 'html', 'html'),
    ARTSPACE: ('https://artspacenc.org/calendar/', 'html', 'html'),
    RLT: ('https://raleighlittletheatre.org/shows-and-events/', 'html', 'html'),
}
LABELS = {NATURAL: 'North Carolina Museum of Natural Sciences', CARY: 'Downtown Cary Park',
          ARTSPACE: 'Artspace', RLT: 'Raleigh Little Theatre'}
ALLOWED_HOSTS = {key: (urlsplit(spec[0]).hostname,) for key, spec in SOURCES.items()}
CHECKPOINT_KEYS = set(SOURCES)
CHECKPOINT_MANIFEST_LIMITS = {key: 200 for key in SOURCES}
CHECKPOINT_EVENT_LIMITS = {key: 500 for key in SOURCES}
NATURAL_API = 'https://www.naturalsciences.org/calendar/wp-json/tribe/events/v1/events'
CARY_APIS = ('https://downtowncarypark.com/wp-json/nmc-feeds/v1/events',
             'https://downtowncarypark.com/wp-json/nmc/eventbrite/v1/fullcalendar')
ARTSPACE_API = 'https://artspacenc.org/wp-admin/admin-ajax.php'
ARTSPACE_POST_API = 'https://artspacenc.org/wp-json/wp/v2/mec-events/'
DAYS = 60
MAX_DESCRIPTION = 12000
MAX_CHECKPOINT_BYTES = 850000
MAX_FETCHES = 4
PREFIX = 'raleigh_arts_'
HOLD_REASONS = {PREFIX + s for s in ('not_public', 'outside_window', 'schedule_unresolved',
    'street_unresolved', 'outside_area', 'description_missing')}
ERROR_CODES = HOLD_REASONS | {PREFIX + s for s in ('source_unregistered', 'calendar_changed',
    'identity_changed', 'pagination_changed', 'manifest_limit', 'record_limit', 'checkpoint_invalid',
    'checkpoint_size_limit', 'description_limit', 'renderer_required', 'form_invalid')}
ERROR_CODES |= {'collection_deadline', 'publisher_checkpoint_required'}
VENUES = {
    CARY: ('Downtown Cary Park', '327 S. Academy St., Cary, NC 27511', 'Cary'),
    ARTSPACE: ('Artspace', '201 E Davie St, Raleigh, NC 27601', 'Raleigh'),
    RLT: ('Raleigh Little Theatre', '301 Pogue Street, Raleigh, NC 27607', 'Raleigh'),
}
STREET_PROVENANCE = 'reviewed_publisher_street_pending_geocode'
NATIVE_PROVENANCE = 'publisher_event_coordinates'
ORGANIZER_PROVENANCE = 'reviewed_primary_organizer_street_pending_geocode'
CARY_MARKET_ADDRESS = '160 E Park Street, Cary, NC 27511'
CARY_MARKET_EVIDENCE = 'https://www.caryfarmersmarket.com/plan-your-visit/'
MONTHS = {name.lower(): n for n, name in enumerate(('', 'January', 'February', 'March', 'April',
    'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')) if n}
MONTHS.update({name[:3]: value for name, value in list(MONTHS.items())})
WEEKDAYS = {name.lower(): n for n, name in enumerate(('Monday', 'Tuesday', 'Wednesday',
    'Thursday', 'Friday', 'Saturday', 'Sunday'))}
CLOCK = r'\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?'
NOT_PUBLIC = re.compile(r'\b(?:cancelled|canceled|postponed|closed|closure|private (?:event|party))\b', re.I)

# Exact relevant options published by shortcode4523. Other calendar-skin options
# are absent from the read-only form, keeping it below the transport's 8KB cap.
ARTSPACE_ATTS = {
    **{'atts[' + key + ']': '' for key in ('label', 'category', 'location', 'organizer', 'tag', 'author')},
    'atts[skin]': 'tile',
    **{'atts[sk-options][tile][' + key + ']': value for key, value in {
        'start_date_type': 'start_current_month', 'start_date': '', 'clean_date_format1': 'j',
        'clean_date_format2': 'M', 'count': '4', 'display_label': '0', 'reason_for_cancellation': '0',
        'display_categories': '0', 'display_organizer': '0', 'next_previous_button': '1',
        'limit': '', 'load_more_button': '1', 'custom_data': '0', 'sed_method': 'new', 'image_popup': '0',
    }.items()},
    **{'atts[' + key + ']': '0' for key in ('sf_status', 'sf_display_label', 'show_past_events',
        'show_only_past_events', 'show_only_ongoing_events', 'show_only_one_occurrence', 'show_ongoing_events')},
    'atts[id]': '4523',
}


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _source(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
                              source.get('timezone')) != (*SOURCES[key], ZONE):
        raise ValueError(PREFIX + 'source_unregistered')
    return key


def _window(start):
    day = start if type(start) is date else start.astimezone(ZoneInfo(ZONE)).date()
    return day, day + timedelta(days=DAYS - 1)


def _months(window_start):
    first, last = _window(window_start)
    cursor, result = first.replace(day=1), []
    while cursor <= last:
        result.append((cursor.year, cursor.month))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def artspace_calendar_form(year, month, atts, window_start):
    """Return only the published, non-mutating MEC month-render form fields."""
    try:
        day = date.fromisoformat(window_start) if isinstance(window_start, str) else window_start
        valid = (type(day) is date and type(year) is int and type(month) is int
                 and (year, month) in _months(day) and isinstance(atts, dict) and atts == ARTSPACE_ATTS)
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(PREFIX + 'form_invalid')
    form = {'action': 'mec_tile_load_month', 'mec_year': str(year), 'mec_month': str(month),
            **atts, 'apply_sf_date': '0', 'navigator_click': '1'}
    if len(urlencode(form).encode()) >= 8192:
        raise ValueError(PREFIX + 'form_invalid')
    return form


def valid_artspace_calendar_form(form, *, now=None):
    """Independent transport boundary: exact renderer fields, no arbitrary POST."""
    try:
        current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ZONE))
        valid_months = set(_months(current)) | set(_months(current - timedelta(hours=4)))
        year, month = int(form['mec_year']), int(form['mec_month'])
        expected = {'action': 'mec_tile_load_month', 'mec_year': str(year), 'mec_month': str(month),
                    **ARTSPACE_ATTS, 'apply_sf_date': '0', 'navigator_click': '1'}
        return (isinstance(form, dict) and form == expected and (year, month) in valid_months
                and len(urlencode(form).encode()) < 8192)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return False


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1800 or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I):
        return None
    try:
        p = urlsplit(value)
        return p if p.scheme == 'https' and not p.username and not p.password and p.port in (None, 443) and not p.fragment else None
    except ValueError:
        return None


def event_url(key, value):
    p = _safe_url(value)
    if not p or key not in SOURCES or p.netloc != ALLOWED_HOSTS[key][0] or p.query:
        return False
    patterns = {NATURAL: r'/calendar/event/[a-z0-9-]+(?:/20\d{2}-\d{2}-\d{2}(?:/[1-9]\d?)?)?/',
                CARY: r'/things-to-do/calendar/[a-zA-Z0-9_-]+/?',
                ARTSPACE: r'/events/[a-z0-9-]+/', RLT: r'/(?:shows|events)/[a-z0-9-]+/'}
    return bool(re.fullmatch(patterns[key], p.path))


def photo_url(key, value):
    if isinstance(value, dict):
        value = value.get('url') or value.get('src')
    if isinstance(value, str):
        value = html.unescape(value)
    p = _safe_url(value)
    if not p:
        return None
    host = ALLOWED_HOSTS[key][0]
    if p.hostname == host and '/wp-content/uploads/' in p.path:
        return value
    if key == ARTSPACE and p.hostname in {'i0.wp.com', 'i1.wp.com', 'i2.wp.com'} and p.path.startswith('/artspacenc.org/wp-content/uploads/'):
        return value
    return None


def _body(value):
    text = description(value, limit=MAX_DESCRIPTION + 1)
    if len(text) > MAX_DESCRIPTION:
        raise ValueError(PREFIX + 'description_limit')
    if not text or not re.search(r'[A-Za-z]{2}', text):
        raise ValueError(PREFIX + 'description_missing')
    return text


def _title_key(value):
    return plain(value).translate(str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"'}))


def _in_window(start, anchor, end=None):
    first, last = _window(anchor)
    return first <= start.astimezone(ZoneInfo(ZONE)).date() <= last and (end or start + timedelta(hours=3)) > anchor


def _clock(text):
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?([ap]m)', re.sub(r'[.\s]', '', text).lower())
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return int(match[1]) % 12 + (12 if match[3] == 'pm' else 0), int(match[2] or 0)


def _at(day, clock):
    h, m = _clock(clock)
    return timestamp(datetime.combine(day, time(h, m)).isoformat(), ZONE)


def _time_range(day, text):
    parts = re.split(r'\s*[–—-]\s*', text.strip())
    if len(parts) not in {1, 2}:
        raise ValueError(PREFIX + 'schedule_unresolved')
    if len(parts) == 2 and not re.search(r'[ap]\.?m\.?$', parts[0], re.I):
        suffix = re.search(r'[ap]\.?m\.?$', parts[1], re.I)
        if not suffix:
            raise ValueError(PREFIX + 'schedule_unresolved')
        parts[0] += suffix[0]
    start, end = _at(day, parts[0]), _at(day, parts[1]) if len(parts) == 2 else None
    if end is not None and end <= start:
        raise ValueError(PREFIX + 'schedule_unresolved')
    return start, end


def _identity(key, url, start):
    return 'raleigh-arts:' + sha256(f'{key}|{url}|{start.astimezone(timezone.utc).isoformat()}'.encode()).hexdigest()


def _row(key, item, body, start, end=None, *, venue=None, address=None, city=None, point=None, image=None,
         provenance=None, evidence=None):
    if not start or start.tzinfo is None or end is not None and (end.tzinfo is None or end <= start):
        raise ValueError(PREFIX + 'schedule_unresolved')
    if not event_url(key, item['url']):
        raise ValueError(PREFIX + 'identity_changed')
    if key in VENUES:
        default_venue, default_address, default_city = VENUES[key]
        venue, address, city = venue or default_venue, address or default_address, city or default_city
    if not venue or not re.search(r'^\d+\s+[A-Za-z]', address or '') or not city:
        raise ValueError(PREFIX + 'street_unresolved')
    full_body = _body(body)
    row = record(item['title'], start.isoformat(), end.isoformat() if end else None,
                 venue, address, city, item['url'], _identity(key, item['url'], start),
                 lat=point[0] if point else None, lng=point[1] if point else None,
                 tz=ZONE, publisher_geo=bool(point), retain_until_end=True)
    if row:
        row.update(description=full_body, timezone=ZONE, attendance_mode='in_person',
                   location_provenance=provenance or (NATIVE_PROVENANCE if point else STREET_PROVENANCE),
                   location_evidence_url=evidence or (item['url'] if key == NATURAL else SOURCES[key][0]))
        if photo := photo_url(key, image):
            row['image_url'] = photo
    return row


def _json(payload):
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        raise ValueError(PREFIX + 'calendar_changed') from None


def _natural_url(anchor, page):
    first, last = _window(anchor)
    return NATURAL_API + '?' + urlencode({'start_date': first.isoformat() + ' 00:00:00',
        'end_date': last.isoformat() + ' 23:59:59', 'per_page': 100, 'page': page})


def _natural_listing(payload, anchor, page):
    data = _json(payload)
    if (not isinstance(data, dict) or not isinstance(data.get('events'), list)
            or type(data.get('total')) is not int or not 0 <= data['total'] <= 200
            or type(data.get('total_pages')) is not int
            or data['total_pages'] not in {max(1, math.ceil(data['total'] / 50)), math.ceil(data['total'] / 50)}
            or len(data['events']) != min(50, max(0, data['total'] - 50 * (page - 1)))):
        raise ValueError(PREFIX + 'pagination_changed')
    queue = []
    for value in data['events']:
        if not isinstance(value, dict) or type(value.get('id')) is not int or not event_url(NATURAL, value.get('url')):
            raise ValueError(PREFIX + 'identity_changed')
        fields = ('id', 'url', 'title', 'description', 'status', 'event_status', 'hide_from_listings', 'all_day',
                  'timezone', 'start_date', 'end_date', 'utc_start_date', 'utc_end_date', 'venue', 'image')
        queue.append({'id': str(value['id']), 'url': value['url'], 'title': plain(value.get('title')),
                      'native': {k: value.get(k) for k in fields}})
    return queue, data['total'], data['total_pages']


def _natural_detail(item, anchor):
    value = item['native']
    if (value['status'] != 'publish' or value.get('event_status') in {'cancelled', 'canceled', 'postponed'}
            or value.get('hide_from_listings') in (True, 1, '1', 'true') or NOT_PUBLIC.search(item['title'])):
        raise ValueError(PREFIX + 'not_public')
    if value.get('all_day') in (True, 1, '1', 'true') or value.get('timezone') != ZONE:
        raise ValueError(PREFIX + 'schedule_unresolved')
    start, end = timestamp(value['start_date'], ZONE), timestamp(value['end_date'], ZONE)
    if (start != timestamp(value['utc_start_date'], 'UTC') or end != timestamp(value['utc_end_date'], 'UTC')
            or not start or not end or end <= start or end - start > timedelta(days=1)):
        raise ValueError(PREFIX + 'schedule_unresolved')
    if not _in_window(start, anchor, end):
        raise ValueError(PREFIX + 'outside_window')
    native = value.get('venue')
    if not isinstance(native, dict):
        raise ValueError(PREFIX + 'street_unresolved')
    city, street = plain(native.get('city')), plain(native.get('address'))
    region = plain(native.get('state') or native.get('stateprovince'))
    zipcode, venue = plain(native.get('zip')), plain(native.get('venue'))
    if city and city.lower() not in {'raleigh', 'cary', 'durham'}:
        raise ValueError(PREFIX + 'outside_area')
    # This field is absent on the museum's native NCMA venue record. It is bound
    # to the existing approved primary NCMA venue, not a city-wide default.
    if (venue, street, city, zipcode, region) == ('North Carolina Museum of Art', '2110 Blue Ridge Rd', 'Raleigh', '27607', ''):
        region = 'NC'
    if not re.search(r'^\d+\s+[A-Za-z]', street) or not city or region != 'NC' or not re.fullmatch(r'\d{5}(?:-\d{4})?', zipcode):
        raise ValueError(PREFIX + 'street_unresolved')
    point = None
    if native.get('geo_lat') is not None or native.get('geo_lng') is not None:
        try:
            point = float(native['geo_lat']), float(native['geo_lng'])
        except (KeyError, ValueError, TypeError):
            raise ValueError(PREFIX + 'street_unresolved') from None
        if not (all(math.isfinite(v) for v in point) and 35 <= point[0] <= 37 and -80 <= point[1] <= -77):
            raise ValueError(PREFIX + 'outside_area')
    image = value.get('image')
    if not photo_url(NATURAL, image):
        native_images = BeautifulSoup(value['description'] or '', 'html.parser').select('img[src]')
        image = next((n['src'] for n in native_images if photo_url(NATURAL, n['src'])), None)
    return [_row(NATURAL, item, value['description'], start, end, venue=venue,
                 address=f'{street}, {city}, NC {zipcode}', city=city, point=point, image=image)]


def _cary_urls(anchor):
    first, last = _window(anchor)
    start = datetime.combine(first, time(), ZoneInfo(ZONE))
    end = datetime.combine(last + timedelta(days=1), time(), ZoneInfo(ZONE))
    query = urlencode({'start': start.isoformat(), 'end': end.isoformat()})
    return [url + '?' + query for url in CARY_APIS]


def _cary_listing(payload, anchor):
    data = _json(payload)
    if not isinstance(data, list) or len(data) >= 200:
        raise ValueError(PREFIX + 'manifest_limit')
    items = []
    for value in data:
        if not isinstance(value, dict) or not event_url(CARY, value.get('url')) or not value.get('id') or not value.get('title'):
            raise ValueError(PREFIX + 'identity_changed')
        start, end = timestamp(value.get('start'), ZONE), timestamp(value.get('end'), ZONE)
        if not start or value.get('allDay') is True or end and (end <= start or end - start > timedelta(days=1)):
            raise ValueError(PREFIX + 'calendar_changed')
        if not _in_window(start, anchor, end):
            continue
        items.append(dict(id=str(value['id']), url=value['url'], title=plain(value['title']),
                          start=start.isoformat(), end=end.isoformat() if end else None))
    return items


def _structured(soup):
    values = []
    for node in soup.select('script[type="application/ld+json"]'):
        data = _json(node.get_text())
        values.extend(data if isinstance(data, list) else data.get('@graph', [data]))
    return values


def _cary_detail(item, payload, anchor):
    soup = BeautifulSoup(payload, 'html.parser')
    title = soup.select_one('h1.masthead_title')
    main = soup.select_one('main .gutenberg')
    if not title or _title_key(title.get_text()) != _title_key(item['title']) or not main:
        raise ValueError(PREFIX + 'identity_changed')
    locations = soup.select('.masthead_content .event-meta.location-meta .venue')
    if len(locations) != 1:
        raise ValueError(PREFIX + 'street_unresolved')
    venue = plain(locations[0].get_text())
    market = (venue == 'East Park Street' and item['title'] in {'Cary Farmers Market', 'Cary Farmers Holiday Market'}
              and re.fullmatch(r'/things-to-do/calendar/w_cary-farmers-market-[1-9]\d*', urlsplit(item['url']).path))
    if not (market or venue.startswith('DCP ') or venue.startswith('Downtown Cary Park')):
        raise ValueError(PREFIX + 'street_unresolved')
    orgs = [value for value in _structured(soup) if value.get('@type') == 'Organization' and isinstance(value.get('address'), dict)]
    addresses = [v['address'] for v in orgs]
    if not any((v.get('streetAddress'), v.get('addressLocality'), v.get('addressRegion'), v.get('postalCode')) ==
               ('327 S. Academy St.', 'Cary', 'NC', '27511') for v in addresses):
        raise ValueError(PREFIX + 'street_unresolved')
    times = [plain(n.get_text()) for n in soup.select('.masthead_content .event-meta .dates')]
    if len(times) != 2:
        raise ValueError(PREFIX + 'schedule_unresolved')
    try:
        day = datetime.strptime(times[0], '%b %d, %Y').date()
        start, end = _time_range(day, times[1])
    except ValueError:
        raise ValueError(PREFIX + 'schedule_unresolved') from None
    if start != timestamp(item['start']) or end != timestamp(item['end']):
        raise ValueError(PREFIX + 'schedule_unresolved')
    # Native recreation details put their complete narrative in masthead_intro;
    # editorial programs put it after the masthead. Preserve both, plus all
    # event-specific registration, accessibility and preparation text.
    intro = main.select_one('.masthead_intro')
    prose = [str(intro)] if intro else []
    registration = main.select_one('.event-info > ul')
    if registration:
        prose.append(str(registration))
    content = deepcopy(main)
    for node in content.select('.nmc-block--masthead, .follow-meta, .related-events, .post-meta-bar'):
        node.decompose()
    prose.append(str(content))
    body = '\n'.join(prose)
    if market:
        narrative = plain(body)
        if (not re.search(r'\balong East Park St(?:reet)?\.?[, ]', narrative, re.I)
                or re.search(r'\b(?:mov(?:ed|ing)|relocat\w*|Town Hall|off[- ]?site)\b', narrative, re.I)):
            raise ValueError(PREFIX + 'street_unresolved')
    if NOT_PUBLIC.search(item['title']):
        raise ValueError(PREFIX + 'not_public')
    image = main.select_one('.masthead_content .news-right img[src], .masthead_image img[src], .masthead-image img[src], img.wp-post-image[src]')
    return [_row(CARY, item, body, start, end,
                 venue='Cary Farmers Market — East Park Street' if market else
                       venue if venue.startswith('Downtown Cary Park') else 'Downtown Cary Park — ' + venue,
                 address=CARY_MARKET_ADDRESS if market else None,
                 provenance=ORGANIZER_PROVENANCE if market else None,
                 evidence=CARY_MARKET_EVIDENCE if market else None,
                 image=image.get('src') if image else None)]


def _rlt_range(value):
    text = plain(value).replace('–', '-').replace('—', '-')
    m = re.fullmatch(r'([A-Za-z]+) (\d{1,2})(?: - (?:(\w+) )?(\d{1,2}))?, (20\d{2})', text)
    if not m or m[1].lower() not in MONTHS or m[3] and m[3].lower() not in MONTHS:
        raise ValueError(PREFIX + 'schedule_unresolved')
    finish = date(int(m[5]), MONTHS[(m[3] or m[1]).lower()], int(m[4] or m[2]))
    begin = date(finish.year - (MONTHS[m[1].lower()] > finish.month), MONTHS[m[1].lower()], int(m[2]))
    if finish < begin or finish - begin > timedelta(days=120):
        raise ValueError(PREFIX + 'schedule_unresolved')
    return begin, finish


def _rlt_listing(payload, anchor):
    soup = BeautifulSoup(payload, 'html.parser')
    anchors = soup.select('.content h3 a[href]')
    if not anchors or '301 Pogue Street' not in soup.get_text(' ', strip=True):
        raise ValueError(PREFIX + 'calendar_changed')
    first, last = _window(anchor)
    result = []
    for a in anchors:
        native_range = a.parent.parent.select_one('p.meta')
        if not native_range or not event_url(RLT, a['href']):
            raise ValueError(PREFIX + 'calendar_changed')
        try:
            begin, finish = _rlt_range(native_range.get_text(' ', strip=True))
        except ValueError:
            # An undated archive entry cannot prove an upcoming occurrence.
            if re.search(r'\b(?:' + '|'.join(str(v) for v in {first.year, last.year}) + r')\b', native_range.get_text()):
                raise
            continue
        if finish < first or begin > last:
            continue
        result.append(dict(id=urlsplit(a['href']).path.strip('/'), url=a['href'], title=plain(a.get_text()),
                           first=begin.isoformat(), last=finish.isoformat()))
    return result


def _explicit_rlt_day(text, first, last):
    match = re.search(r'\b(' + '|'.join(MONTHS) + r')\s+(\d{1,2})(?:st|nd|rd|th)?\b', text, re.I)
    if not match:
        raise ValueError(PREFIX + 'schedule_unresolved')
    options = [date(y, MONTHS[match[1].lower()], int(match[2])) for y in {first.year, last.year}]
    options = [day for day in options if first <= day <= last]
    if len(options) != 1:
        raise ValueError(PREFIX + 'schedule_unresolved')
    day = options[0]
    weekday = re.search(r'\b(' + '|'.join(WEEKDAYS) + r')\b', text, re.I)
    if weekday and WEEKDAYS[weekday[1].lower()] != day.weekday():
        raise ValueError(PREFIX + 'schedule_unresolved')
    return day


def _rlt_detail(item, payload, anchor):
    soup = BeautifulSoup(payload, 'html.parser')
    header, content = soup.select_one('.show-header'), soup.select_one('.show-content')
    if not header or not content or not header.select_one('h2') or plain(header.select_one('h2').get_text()) != item['title']:
        raise ValueError(PREFIX + 'identity_changed')
    meta = header.select('p.meta')
    first, last = date.fromisoformat(item['first']), date.fromisoformat(item['last'])
    if len(meta) < 2 or _rlt_range(meta[0].get_text()) != (first, last):
        raise ValueError(PREFIX + 'identity_changed')
    theatre = plain(meta[1].get_text())
    venues = {'Gaddy-Goodwin Teaching Theatre': 'Gaddy-Goodwin Teaching Theatre',
              'Cantey V. Sutton Theatre': 'Cantey V. Sutton Theatre'}
    names = [value for name, value in venues.items() if theatre.startswith(name)]
    if len(names) != 1 or '301 Pogue Street' not in soup.get_text(' ', strip=True):
        raise ValueError(PREFIX + 'street_unresolved')
    tickets = content.select_one('.four.column')
    if not tickets:
        raise ValueError(PREFIX + 'schedule_unresolved')
    label = next((n for n in tickets.find_all(['p', 'h4']) if re.fullmatch(r'Show\s*Times?:', plain(n.get_text()), re.I)), None)
    schedule = label.find_next_sibling('ul') if label else None
    if not schedule:
        raise ValueError(PREFIX + 'schedule_unresolved')
    sessions, weekdays, excluded = {}, {}, set()
    for li in schedule.select('li'):
        value = plain(li.get_text())
        if value.startswith('No shows '):
            match = re.fullmatch(r'No shows ([A-Za-z]+) (\d{1,2})\s*&\s*(\d{1,2})(?: \([^)]*\))?', value)
            if not match:
                raise ValueError(PREFIX + 'schedule_unresolved')
            for d in (match[2], match[3]):
                excluded.add(_explicit_rlt_day(match[1] + ' ' + d, first, last))
            continue
        if re.search(r'\b(?:' + '|'.join(MONTHS) + r')\s+\d', value, re.I):
            day = _explicit_rlt_day(value, first, last)
            clock_range = re.search(r'(\d{1,2}:\d{2}\s*[–-]\s*' + CLOCK + r')$', value, re.I)
            if not clock_range:
                raise ValueError(PREFIX + 'schedule_unresolved')
            sessions[day] = [_time_range(day, clock_range[1])]
            continue
        parts = re.split(r'\s+at\s+', value, flags=re.I)
        if len(parts) != 2:
            raise ValueError(PREFIX + 'schedule_unresolved')
        labels = re.findall(r'\b(' + '|'.join(WEEKDAYS) + r')s?\b', parts[0], re.I)
        clocks = re.findall(CLOCK, parts[1], re.I)
        remainder = re.sub(CLOCK, '', parts[1], flags=re.I)
        if not labels or not clocks or re.sub(r'[\s,&]', '', remainder):
            raise ValueError(PREFIX + 'schedule_unresolved')
        for name in labels:
            number = WEEKDAYS[name.lower()]
            if number in weekdays:
                raise ValueError(PREFIX + 'schedule_unresolved')
            weekdays[number] = clocks
    if weekdays and sessions:
        raise ValueError(PREFIX + 'schedule_unresolved')
    if weekdays:
        for n in range((last - first).days + 1):
            day = first + timedelta(days=n)
            if day.weekday() in weekdays and day not in excluded:
                sessions[day] = [(_at(day, clock), None) for clock in weekdays[day.weekday()]]
    # Only the explicit exception changes the named day; accessibility notices
    # elsewhere describe existing sessions and never create extra performances.
    for node in tickets.select('p'):
        text = plain(node.get_text()).lstrip('*')
        if not re.search(r'\bexcept\b', text, re.I):
            continue
        match = re.fullmatch(r'except on (.+?) when shows are at (.+)', text, re.I)
        if not match:
            raise ValueError(PREFIX + 'schedule_unresolved')
        day = _explicit_rlt_day(match[1], first, last)
        clocks = re.findall(CLOCK, match[2], re.I)
        if not clocks or re.sub(r'[\s,&]|\band\b', '', re.sub(CLOCK, '', match[2], flags=re.I)):
            raise ValueError(PREFIX + 'schedule_unresolved')
        sessions[day] = [(_at(day, clock), None) for clock in clocks]
    extra = content.find_next_sibling('div', class_='pad-xl')
    body = str(content) + (str(extra) if extra else '')
    photo = re.search(r'background-image:url\((https://[^)]+)\)', str(header))
    return [_row(RLT, item, body, start, end, venue='Raleigh Little Theatre — ' + names[0],
                 image=photo[1] if photo else None)
            for day in sorted(sessions) for start, end in sessions[day] if _in_window(start, anchor, end)]


def _art_settings(payload, anchor):
    match = re.search(r'\.mecTileView\(\s*(\{.*?\})\s*\)', payload, re.S)
    if not match:
        raise ValueError(PREFIX + 'calendar_changed')
    # Parse only inert quoted literals from the published settings block; do
    # not evaluate JavaScript or attempt to turn arbitrary code into JSON.
    def literal(name):
        values = re.findall(r'\b' + re.escape(name) + r'\s*:\s*("(?:\\.|[^"\\])*")', match[1])
        if len(values) != 1:
            raise ValueError(PREFIX + 'calendar_changed')
        return _json(values[0])
    settings = {name: literal(name) for name in ('id', 'atts', 'ajax_url', 'load_method', 'limit')}
    pairs = parse_qsl(settings['atts'], keep_blank_values=True)
    all_atts = dict(pairs)
    subset = {k: v for k, v in all_atts.items() if k in ARTSPACE_ATTS}
    if (len(pairs) != len(all_atts) or subset != ARTSPACE_ATTS or settings.get('id') != '4523'
            or settings.get('ajax_url') != ARTSPACE_API or settings.get('load_method') != 'month'
            or settings.get('limit') != '80'):
        raise ValueError(PREFIX + 'calendar_changed')
    active = re.search(r'\bactive_month:\s*\{year:\s*"(20\d{2})",\s*month:\s*"(\d{1,2})"\}', match[1])
    if not active or (int(active[1]), int(active[2])) != _months(anchor)[0]:
        raise ValueError(PREFIX + 'calendar_changed')
    return subset


def _art_month(payload, anchor, year, month, *, rendered=False):
    if rendered:
        value = _json(payload)
        meta = value.get('current_month', {}) if isinstance(value, dict) else {}
        if (meta.get('id') != f'{year}{month:02d}' or meta.get('year') != str(year)
                or meta.get('month') not in {str(month), f'{month:02d}'}):
            raise ValueError(PREFIX + 'calendar_changed')
        payload = value.get('month', '')
    soup = BeautifulSoup(payload, 'html.parser')
    if not soup.select_one('.mec-event-tile-view'):
        raise ValueError(PREFIX + 'calendar_changed')
    articles = soup.select('article.mec-event-article')
    # The public renderer caps at80. Reaching its cap is incomplete and must
    # never silently publish a truncated month.
    if len(articles) >= 80 or soup.select('.mec-load-more-button:not(.mec-util-hidden)'):
        raise ValueError(PREFIX + 'pagination_changed')
    items = []
    first, last = _window(anchor)
    for article in articles:
        holder, title_node = article.select_one('[data-event-id]'), article.select_one('h4.mec-event-title')
        ld = article.parent.select_one('script[type="application/ld+json"]')
        if not holder or not title_node or not ld or not re.fullmatch(r'[1-9]\d*', holder['data-event-id']):
            raise ValueError(PREFIX + 'identity_changed')
        event = _json(ld.get_text())
        day, finish = date.fromisoformat(event['startDate']), date.fromisoformat(event['endDate'])
        if not first <= day <= last:
            continue
        node = article.select_one('.mec-event-time')
        clock = plain(node.get_text()) if node else ''
        title = plain(title_node.get_text())
        held = None
        if NOT_PUBLIC.search(title) or clock == 'All Day':
            held = PREFIX + ('not_public' if NOT_PUBLIC.search(title) else 'schedule_unresolved')
        elif finish != day:
            # A multi-date range lacks the explicit per-session clocks needed
            # to publish either a continuous session or repeated daily events.
            held = PREFIX + 'schedule_unresolved'
        if event.get('@type') != 'Event' or event.get('eventStatus') != 'https://schema.org/EventScheduled':
            held = PREFIX + 'not_public'
        body = html.unescape(event.get('description') or '')
        if re.search(r'only open to members|must have an active .* membership|members[- ]only', plain(body), re.I):
            held = PREFIX + 'not_public'
        item = dict(id=holder['data-event-id'], title=title, native_body=body, image=event.get('image'),
                    day=day.isoformat(), clock=clock, held=held, first=day.isoformat(), last=finish.isoformat())
        # Use the native WordPress identity to obtain its canonical first-party
        # page; external ticket URLs are never fetched or used as venue evidence.
        items.append(item)
    return items


def _art_detail(item, payload, anchor):
    value = _json(payload)
    if (not isinstance(value, dict) or str(value.get('id')) != item['id'] or value.get('status') != 'publish'
            or not event_url(ARTSPACE, value.get('link')) or not isinstance(value.get('content'), dict)):
        raise ValueError(PREFIX + 'identity_changed')
    native_title = plain((value.get('title') or {}).get('rendered'))
    if _title_key(native_title) != _title_key(item['title']):
        raise ValueError(PREFIX + 'identity_changed')
    item = dict(item, url=value['link'])
    if item.get('held'):
        raise ValueError(item['held'])
    full = _body(value['content'].get('rendered'))
    if plain(full) != plain(_body(item['native_body'])):
        raise ValueError(PREFIX + 'calendar_changed')
    if re.search(r'\b(?:Jobe House|off[- ]site|on the go|virtual|online only)\b', full, re.I):
        raise ValueError(PREFIX + 'street_unresolved')
    start = _at(date.fromisoformat(item['day']), item['clock'])
    if not _in_window(start, anchor):
        raise ValueError(PREFIX + 'outside_window')
    return [_row(ARTSPACE, item, full, start, image=item.get('image'))], item['url']


def _seal(state):
    state['manifest_count'], state['manifest_hash'] = len(state['queue']), _hash(state['queue'])
    state['outcome_hash'] = _hash(state['outcomes'])
    state['state_hash'] = _hash({k: v for k, v in state.items() if k != 'state_hash'})
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CHECKPOINT_BYTES:
        raise ValueError(PREFIX + 'checkpoint_size_limit')


def _task_url(key, task, anchor):
    kind = task.get('kind')
    if kind == 'root' and set(task) == {'kind'}:
        return SOURCES[key][0]
    if key == NATURAL and kind == 'tec' and set(task) == {'kind', 'page'} and type(task['page']) is int and 1 <= task['page'] <= 4:
        return _natural_url(anchor, task['page'])
    if key == CARY and kind == 'cary' and set(task) == {'kind', 'index'} and type(task['index']) is int and task['index'] in {0, 1}:
        return _cary_urls(anchor)[task['index']]
    if key == ARTSPACE and kind == 'artmonth' and set(task) == {'kind', 'year', 'month'} and (task['year'], task['month']) in _months(anchor):
        return ARTSPACE_API
    raise ValueError(PREFIX + 'checkpoint_invalid')


def _checkpoint(value, key, now):
    if value is None:
        return None
    try:
        started = timestamp(value['started_at'])
        valid = (type(value['version']) is int and value['version'] == 1 and value['source_key'] == key
                 and started is not None and started.utcoffset() == timedelta(0) and started <= now + timedelta(seconds=60)
                 and value['window_start'] == _window(started)[0].isoformat()
                 and isinstance(value['queue'], list) and len(value['queue']) <= 200
                 and value['manifest_count'] == len(value['queue']) and value['manifest_hash'] == _hash(value['queue'])
                 and type(value['cursor']) is int and 0 <= value['cursor'] <= len(value['queue'])
                 and isinstance(value['pending_pages'], list) and len(value['pending_pages']) <= 4
                 and isinstance(value['listed_pages'], list) and 1 <= len(value['listed_pages']) <= 5
                 and value['listing_complete'] is (not value['pending_pages'])
                 and (value['listing_complete'] or value['cursor'] == 0 and not value['events'])
                 and len(value['outcomes']) == value['cursor'] and value['outcome_hash'] == _hash(value['outcomes'])
                 and value['state_hash'] == _hash({k: v for k, v in value.items() if k != 'state_hash'})
                 and isinstance(value['events'], list) and len(value['events']) <= 500
                 and isinstance(value['diagnostics'], list) and len(value['diagnostics']) <= 200
                 and len(json.dumps(value, ensure_ascii=False).encode()) <= MAX_CHECKPOINT_BYTES)
        for task in value['pending_pages'] + value['listed_pages']:
            _task_url(key, task, started)
        if key == ARTSPACE:
            valid = valid and value['atts'] == ARTSPACE_ATTS
        ids = set()
        for item in value['queue']:
            identity = item['id'] + (':' + item['day'] if key == ARTSPACE else '')
            valid = valid and identity not in ids and isinstance(item['title'], str) and 0 < len(item['title']) <= 500
            if key == ARTSPACE:
                valid = valid and bool(re.fullmatch(r'[1-9]\d*', item['id'])) and item.get('held') in HOLD_REASONS | {None}
            else:
                valid = valid and event_url(key, item['url'])
            ids.add(identity)
        proofs, diagnostics = {}, []
        for item, outcome in zip(value['queue'], value['outcomes']):
            valid = valid and outcome['item_hash'] == _hash(item) and isinstance(outcome['rows'], list)
            if outcome['reason']:
                valid = valid and outcome['reason'] in HOLD_REASONS and not outcome['rows']
                diagnostics.append(dict(id=item['id'], title=item['title'], event_url=outcome['event_url'],
                                        disposition='held', reason=outcome['reason']))
            for proof in outcome['rows']:
                valid = valid and proof['id'] not in proofs
                proofs[proof['id']] = proof
        valid = valid and diagnostics == value['diagnostics'] and len(proofs) == len(value['events'])
        for row in value['events']:
            start, end = timestamp(row['starts_at']), timestamp(row.get('ends_at'))
            valid = (valid and event_url(key, row['event_url']) and row['id'] == _identity(key, row['event_url'], start)
                     and _hash(row) == proofs.get(row['id'], {}).get('hash')
                     and _body(row['description']) == row['description'] and row.get('timezone') == ZONE
                     and row.get('attendance_mode') == 'in_person' and _in_window(start, started, end)
                     and row.get('location_provenance') in {NATIVE_PROVENANCE, STREET_PROVENANCE, ORGANIZER_PROVENANCE}
                     and (not row.get('image_url') or photo_url(key, row['image_url']) == row['image_url']))
            if key in VENUES:
                market = (key == CARY and row['title'] in {'Cary Farmers Market', 'Cary Farmers Holiday Market'}
                          and row['venue_name'] == 'Cary Farmers Market — East Park Street'
                          and row['venue_address'] == CARY_MARKET_ADDRESS
                          and row.get('location_provenance') == ORGANIZER_PROVENANCE
                          and row.get('location_evidence_url') == CARY_MARKET_EVIDENCE)
                valid = (valid and (market or row['venue_address'] == VENUES[key][1])
                         and row['venue_city'] == VENUES[key][2])
        if not valid:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError):
        raise ValueError(PREFIX + 'checkpoint_invalid') from None
    if now - started > timedelta(hours=4):
        return None
    return deepcopy(value)


def _add_items(state, key, items):
    combined = state['queue'] + items
    identities = [v['id'] + (':' + v['day'] if key == ARTSPACE else '') for v in combined]
    if len(identities) != len(set(identities)):
        raise ValueError(PREFIX + 'calendar_changed')
    if len(combined) > 200:
        raise ValueError(PREFIX + 'manifest_limit')
    state['queue'] = combined


def collect_chunk(source, fetch, *, checkpoint=None, deadline_at=None, now=None, render_calendar=None,
                  max_fetches=MAX_FETCHES):
    key = _source(source)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError(PREFIX + 'checkpoint_invalid')
    current = current.astimezone(timezone.utc)
    state = _checkpoint(checkpoint, key, current)
    if state is None:
        state = dict(version=1, source_key=key, started_at=current.isoformat(), window_start=_window(current)[0].isoformat(),
                     queue=[], manifest_count=0, manifest_hash=_hash([]), cursor=0, events=[], diagnostics=[],
                     pending_pages=[{'kind': 'tec', 'page': 1}] if key == NATURAL else [{'kind': 'root'}],
                     listed_pages=[], listing_complete=False, native_total=None, native_pages=None, atts=None,
                     outcomes=[], outcome_hash=_hash([]))
    anchor = timestamp(state['started_at'])
    if state['listing_complete'] and state['cursor'] == len(state['queue']):
        return dict(complete=True, events=deepcopy(state['events']), checkpoint=state)
    fetched, before = 0, (len(state['listed_pages']), state['cursor'])
    def available():
        return fetched < max_fetches and (deadline_at is None or monotonic() + 12 < deadline_at)
    while state['pending_pages'] and available():
        task = state['pending_pages'][0]
        url = _task_url(key, task, anchor)
        if task['kind'] == 'artmonth':
            if render_calendar is None:
                raise ValueError(PREFIX + 'renderer_required')
            artspace_calendar_form(task['year'], task['month'], state['atts'], state['window_start'])
            payload = render_calendar(year=task['year'], month=task['month'], atts=state['atts'], window_start=state['window_start'])
        else:
            payload = fetch(url, 'text/html' if task['kind'] == 'root' else 'application/json')
        fetched += 1
        following, items = [], []
        if key == NATURAL:
            items, total, pages = _natural_listing(payload, anchor, task['page'])
            if state['native_total'] is not None and (total, pages) != (state['native_total'], state['native_pages']):
                raise ValueError(PREFIX + 'pagination_changed')
            state['native_total'], state['native_pages'] = total, pages
            if task['page'] < pages:
                following = [{'kind': 'tec', 'page': task['page'] + 1}]
        elif key == CARY:
            if task['kind'] == 'root':
                if not all(urlsplit(v).path in payload for v in CARY_APIS):
                    raise ValueError(PREFIX + 'calendar_changed')
                following = [{'kind': 'cary', 'index': n} for n in (0, 1)]
            else:
                items = _cary_listing(payload, anchor)
        elif key == RLT:
            items = _rlt_listing(payload, anchor)
        else:
            if task['kind'] == 'root':
                state['atts'] = _art_settings(payload, anchor)
                year, month = _months(anchor)[0]
                following = [dict(kind='artmonth', year=y, month=m) for y, m in _months(anchor)[1:]]
            else:
                year, month = task['year'], task['month']
            items = _art_month(payload, anchor, year, month, rendered=task['kind'] == 'artmonth')
        _add_items(state, key, items)
        state['listed_pages'].append(task)
        state['pending_pages'] = state['pending_pages'][1:] + following
        state['listing_complete'] = not state['pending_pages']
    if state['listing_complete'] and key == NATURAL and len(state['queue']) != state['native_total']:
        raise ValueError(PREFIX + 'pagination_changed')
    # Never begin detail processing until every native page/month has been read.
    while state['listing_complete'] and state['cursor'] < len(state['queue']):
        item = state['queue'][state['cursor']]
        if key != NATURAL and not available():
            break
        rows, reason = [], None
        event_page = item.get('url', SOURCES[key][0])
        try:
            if key == NATURAL:
                rows = _natural_detail(item, anchor)
            elif key == CARY:
                payload = fetch(item['url'], 'text/html'); fetched += 1
                rows = _cary_detail(item, payload, anchor)
            elif key == RLT:
                payload = fetch(item['url'], 'text/html'); fetched += 1
                rows = _rlt_detail(item, payload, anchor)
            else:
                payload = fetch(ARTSPACE_POST_API + item['id'], 'application/json'); fetched += 1
                value = _json(payload)
                if isinstance(value, dict) and event_url(ARTSPACE, value.get('link')):
                    event_page = value['link']
                rows, event_page = _art_detail(item, payload, anchor)
            rows = [row for row in rows if row]
            if not rows:
                reason = PREFIX + 'outside_window'
        except ValueError as exc:
            if str(exc) not in HOLD_REASONS:
                raise
            reason = str(exc)
        if reason:
            state['diagnostics'].append(dict(id=item['id'], title=item['title'], event_url=event_page,
                                            disposition='held', reason=reason))
        existing = {row['id'] for row in state['events']}
        if any(row['id'] in existing for row in rows):
            raise ValueError(PREFIX + 'calendar_changed')
        state['events'].extend(rows)
        state['outcomes'].append(dict(item_hash=_hash(item), event_url=event_page, reason=reason,
                                     rows=[dict(id=row['id'], hash=_hash(row)) for row in rows]))
        state['cursor'] += 1
        if len(state['events']) > 500:
            raise ValueError(PREFIX + 'record_limit')
    if before == (len(state['listed_pages']), state['cursor']):
        raise ValueError('collection_deadline')
    complete = state['listing_complete'] and state['cursor'] == len(state['queue'])
    _seal(state)
    return dict(complete=complete, events=deepcopy(state['events']) if complete else [], checkpoint=state)


def collect(source, fetch, *, deadline_at=None, now=None, render_calendar=None):
    result = collect_chunk(source, fetch, deadline_at=deadline_at, now=now, render_calendar=render_calendar)
    if not result['complete']:
        raise ValueError('publisher_checkpoint_required')
    return result['events']
