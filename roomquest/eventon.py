"""Read publisher-advertised EventON calendars through a bounded contract."""
from datetime import datetime
import json
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record

HOST = 'jamesriverpark.org'
CALENDAR = f'https://{HOST}/events/'
ENDPOINT = f'https://{HOST}/?evo-ajax=eventon_init_load'
CALENDAR_ID = 'evcal_calendar_277'
REEDY_CREEK = '4001 Riverside Dr, Richmond, VA 23225'


def _calendar_id(document):
    ids = {node.get('id') for node in document.select('[id^="evcal_calendar_"]')
           if re.fullmatch(r'evcal_calendar_[1-9][0-9]{0,9}', node.get('id', ''))}
    if len(ids) != 1:
        raise ValueError('eventon_calendar_missing')
    return next(iter(ids))


def calendar_form(page, calendar_id=CALENDAR_ID):
    document = BeautifulSoup(page, 'html.parser')
    calendar = document.find(id=calendar_id)
    global_data = document.select_one('#evo_global_data[data-d]')
    nonce = re.search(r'var evo_general_params = (\{[^\n]+?\});', page)
    if calendar is None or global_data is None or nonce is None:
        raise ValueError('eventon_calendar_missing')
    settings = calendar.select_one('.evo_cal_data[data-sc]')
    if settings is None:
        raise ValueError('eventon_calendar_missing')
    token = json.loads(nonce[1]).get('n', '')
    if not re.fullmatch(r'[a-zA-Z0-9]{8,24}', token):
        raise ValueError('invalid_eventon_calendar_nonce')

    def fields(value, name):
        if isinstance(value, dict):
            for key, item in value.items():
                if not re.fullmatch(r'[a-zA-Z0-9_-]+', key):
                    raise ValueError('invalid_eventon_calendar_settings')
                yield from fields(item, f'{name}[{key}]')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from fields(item, f'{name}[{index}]')
        else:
            yield name, '' if value is None else str(value)

    return dict([('nonce', token), *fields(json.loads(global_data['data-d']), 'global'),
                 *fields(json.loads(settings['data-sc']), f'cals[{calendar_id}][sc]')])


def contract(url, page):
    """Return only an exact same-host public EventON request advertised by HTML."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('invalid_eventon_calendar')
    document = BeautifulSoup(page, 'html.parser')
    calendar_id = _calendar_id(document)
    match = re.search(r'var evo_general_params = (\{[^\n]+?\});', page)
    if match is None:
        raise ValueError('eventon_calendar_missing')
    try:
        params = json.loads(match[1])
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('invalid_eventon_calendar') from exc
    origin = urlunsplit((parts.scheme, parts.netloc, '/', '', ''))
    if (not isinstance(params, dict)
            or params.get('evo_ajax_url') != '/?evo-ajax=%%endpoint%%'
            or params.get('ajaxurl') != origin + 'wp-admin/admin-ajax.php'):
        raise ValueError('invalid_eventon_calendar')
    return {
        'calendar_id': calendar_id,
        'endpoint': origin + '?evo-ajax=eventon_init_load',
        'form': calendar_form(page, calendar_id),
    }


def supports_listing(url, page):
    try:
        contract(url, page)
        return True
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def parse(payload, *, host=HOST, calendar=CALENDAR, calendar_id=CALENDAR_ID, city='Richmond'):
    document = json.loads(payload)
    if isinstance(document, dict) and document.get('status') == 'bad':
        message = str(document.get('msg', '')).casefold()
        if 'nonce' in message and ('fail' in message or 'invalid' in message):
            raise ValueError('eventon_nonce_unavailable')
        raise ValueError('invalid_eventon_calendar')
    data = document['cals'][calendar_id]
    if not isinstance(data['json'], list) or len(data['json']) > 100:
        raise ValueError('invalid_eventon_calendar')
    page = BeautifulSoup(data['html'], 'html.parser')
    cards = page.select('.eventon_list_event[data-event_id][data-time]')
    if len(cards) != len(data['json']):
        raise ValueError('incomplete_eventon_calendar')
    result = []
    for card in cards:
        def value(name):
            node = card.select_one(f'[itemprop="{name}"]')
            if node is None:
                raise ValueError('invalid_eventon_occurrence')
            return node.get('content') or node.get('href') or node.get_text(' ', strip=True)

        if not value('eventStatus').endswith('/EventScheduled'):
            continue
        url = value('url')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != host or parsed.username or parsed.password:
            raise ValueError('invalid_eventon_occurrence')
        times = []
        for field in ('startDate', 'endDate'):
            iso = re.sub(r'(?<=[T+-])(\d)(?=:)', r'0\1', value(field))
            iso = re.sub(r'^(\d{4})-(\d{1,2})-(\d{1,2})T',
                         lambda m: f'{m[1]}-{int(m[2]):02}-{int(m[3]):02}T', iso)
            timestamp = datetime.fromisoformat(iso)
            if timestamp.utcoffset() is None:
                raise ValueError('invalid_eventon_occurrence')
            times.append(iso)
        title = card.select_one('.evcal_event_title')
        place = card.select_one('[itemprop="location"] [itemprop="name"]')
        if title is None:
            raise ValueError('invalid_eventon_occurrence')
        title_text = title.get_text(' ', strip=True)
        street = value('streetAddress') if card.select_one('[itemprop="streetAddress"]') else ''
        venue = place.get_text(' ', strip=True) if place else ''
        lat = lng = None
        if host == HOST and (street.casefold() == '4001 riverside dr' or
                (not street and title_text == 'Invasive Plant Removal at Reedy Creek')):
            venue = venue or 'Reedy Creek Parking Lot'
            street, lat, lng = REEDY_CREEK, 37.523206968014, -77.470957654180
        event = record(title_text, *times, venue,
                       street, city, url, f'{card["data-event_id"]}:{times[0]}',
                       'Helping', lat, lng)
        if event:
            result.append(event)
    return result


def collect(source, fetch, *, body=None, deadline_at=None):
    """Collect one complete EventON response from its publisher-advertised form."""
    listing = source.get('feed_url')
    parts = urlsplit(listing or '')
    if (source.get('platform_adapter') != 'eventon' or source.get('kind') != 'json'
            or parts.scheme != 'https' or not parts.hostname):
        raise ValueError('unregistered_eventon_source')
    page = body if body is not None else fetch(listing, 'text/html,application/xhtml+xml')
    spec = contract(listing, page)
    payload = fetch(spec['endpoint'], 'application/json', calendar_form=spec['form'])
    return parse(payload, host=parts.netloc, calendar=listing,
                 calendar_id=spec['calendar_id'], city='')
