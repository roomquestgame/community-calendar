"""Collect the public output of Tickera's standard WordPress calendar add-on."""
from ast import literal_eval
from datetime import datetime
import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record
from roomquest.registration_formats import provider_calendar_destination

PLUGIN = '/wp-content/plugins/tickera-event-calendar/'
CORE = '/wp-content/plugins/tickera/'
_STRING = r"'(?:\\.|[^'\\])*'"


def _origin(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('invalid_tickera_calendar')
    return urlunsplit((parts.scheme, parts.netloc, '/', '', ''))


def calendar_destination(url, page):
    """Follow one advertised calendar only when the page proves Tickera."""
    if CORE not in page and PLUGIN not in page:
        return None
    _origin(url)
    return provider_calendar_destination(url, page)


def _events_script(page):
    if PLUGIN not in page or 'id=\'tc_calendar\'' not in page and 'id="tc_calendar"' not in page:
        raise ValueError('tickera_calendar_missing')
    document = BeautifulSoup(page, 'html.parser')
    matches = [node.get_text() for node in document.find_all('script')
               if 'new FullCalendar.Calendar' in node.get_text() and re.search(r'\bevents\s*:\s*\[', node.get_text())]
    if len(matches) != 1:
        raise ValueError('tickera_calendar_missing')
    match = re.search(r'\bevents\s*:\s*\[(.*?)\]\s*,?\s*(?:eventDidMount|eventClick|eventMouseEnter|\}\s*\))',
                      matches[0], re.S)
    if match is None or len(match[1]) > 2_000_000:
        raise ValueError('invalid_tickera_calendar')
    return match[1]


def supports_listing(url, page):
    try:
        _origin(url)
        _events_script(page)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _value(block, name, required=True):
    match = re.search(rf'\b{re.escape(name)}\s*:\s*({_STRING})', block)
    if match is None:
        if required:
            raise ValueError('invalid_tickera_event')
        return ''
    try:
        value = literal_eval(match[1])
    except (ValueError, SyntaxError) as exc:
        raise ValueError('invalid_tickera_event') from exc
    if not isinstance(value, str) or len(value) > 20_000:
        raise ValueError('invalid_tickera_event')
    return html.unescape(value).strip()


def timezone(page, fetch, url):
    payload = fetch(urljoin(_origin(url), 'wp-json/'), 'application/json')
    try:
        zone = json.loads(payload).get('timezone_string')
        ZoneInfo(zone)
    except (ValueError, TypeError, AttributeError, ZoneInfoNotFoundError) as exc:
        raise ValueError('source_timezone_required') from exc
    return zone


def parse(page, *, url, zone):
    listing_host = urlsplit(url).hostname
    script = _events_script(page)
    if not script.strip():
        return []  # Valid empty refresh; registration still requires events.
    blocks = re.findall(r'\{([^{}]{1,100000})\}', script, re.S)
    # Collect the configured calendar array (which may be category-filtered),
    # not an assumed publisher-wide archive. Normalization drops past events.
    if not blocks or len(blocks) > 1000:
        raise ValueError('invalid_tickera_calendar')
    rows = []
    for block in blocks:
        title = _value(block, 'title')
        start = _value(block, 'start')
        end = _value(block, 'end', False) or None
        event_url = _value(block, 'url')
        image = _value(block, 'backgroundImage', False)
        parts = urlsplit(event_url)
        if parts.scheme != 'https' or parts.hostname != listing_host or parts.username or parts.password:
            raise ValueError('invalid_tickera_event')
        # Reject timestamps outside the documented local wall-time shape.
        for stamp in (start, end):
            if stamp is not None:
                datetime.strptime(stamp, '%Y-%m-%d %H:%M')
        item = record(title, start, end, '', '', '', event_url, event_url, tz=zone)
        if item is not None:
            if image:
                image_parts = urlsplit(image)
                if image_parts.scheme == 'https' and image_parts.hostname and not image_parts.username and not image_parts.password:
                    item['image_url'] = image
            rows.append(item)
    return rows


def collect(source, fetch, *, body=None, deadline_at=None):
    listing = source.get('feed_url')
    if source.get('platform_adapter') != 'tickera' or source.get('kind') != 'json':
        raise ValueError('unregistered_tickera_source')
    page = body if body is not None else fetch(listing, 'text/html,application/xhtml+xml')
    return parse(page, url=listing, zone=timezone(page, fetch, listing))
