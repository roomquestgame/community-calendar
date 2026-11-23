"""Complete publisher date-only Event JSON-LD using an agreeing local clock.

The publisher's Event gives the date and physical address. A separately marked
start time on that same canonical detail page completes the occurrence only for
an unambiguous UK local clock. No body-prose date guessing or inferred end time.
"""
from copy import deepcopy
from datetime import datetime, date, timezone
from html import unescape
import re
from zoneinfo import ZoneInfo


def date_only_event_with_clock(nodes, soup, url, is_event):
    events = [node for node in nodes if is_event(node)]
    if len(events) != 1:
        return None
    original = events[0]
    start = original.get('startDate')
    if not isinstance(start, str) or not re.fullmatch(r'20[0-9]{2}-[01][0-9]-[0-3][0-9]', start):
        return None
    if original.get('url') or original.get('@id'):
        return None
    places = original.get('location')
    if not isinstance(places, list) or len(places) != 1 or not isinstance(places[0], dict):
        return None
    place = places[0]
    address = place.get('address')
    if not isinstance(address, dict) or not all(isinstance(address.get(key), str) and address[key].strip()
                                               for key in ('streetAddress', 'addressLocality', 'postalCode')):
        return None
    if address.get('addressCountry', '').casefold() not in {'uk', 'gb', 'united kingdom'}:
        return None
    roots = soup.select('main h1')
    if len(roots) != 1 or unescape(roots[0].get_text(' ', strip=True)).casefold() != unescape(
            str(original.get('name') or '')).strip().casefold():
        return None
    dates = soup.select('main .event-details__item--date dd')
    times = soup.select('main .event-details__item--time dd')
    if len(dates) != 1 or len(times) != 1:
        return None
    try:
        date_label = dates[0].get_text(' ', strip=True)
        jsonld_date = date.fromisoformat(start)
        # A publisher date range may describe several performances. Only its
        # independently declared JSON-LD first day has a dated identity here.
        # Never fabricate the remaining days from a shared start-time label.
        range_match = re.fullmatch(r'([0-3]?[0-9])\s*[-–]\s*([0-3]?[0-9])\s+'
                                    r'([A-Za-z]+),?\s+(20[0-9]{2})', date_label)
        first_label = (range_match[1] + ' ' + range_match[3] + ', ' + range_match[4]
                       if range_match else date_label)
        published_date = datetime.strptime(first_label, '%d %B, %Y').date()
        if published_date != jsonld_date:
            return None
        clock_label = times[0].get_text(' ', strip=True)
        if range_match and clock_label.casefold() == 'times vary by date':
            # The public page itself declines to specify an occurrence time.
            # This one detail was inspected, but no event can be timestamped.
            return []
        local_time = datetime.strptime(clock_label, '%H:%M').time()
        local = datetime.combine(jsonld_date, local_time).replace(tzinfo=ZoneInfo('Europe/London'))
        if (local.utcoffset() != local.replace(fold=1).utcoffset()
                or local.astimezone(timezone.utc).astimezone(local.tzinfo) != local):
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    if original.get('endDate'):
        # Date-only ends cannot supply a trustworthy end clock.
        return None
    corrected = deepcopy(original)
    corrected['startDate'] = local.isoformat()
    corrected['url'] = url
    corrected['@id'] = url + '#event'
    return corrected
