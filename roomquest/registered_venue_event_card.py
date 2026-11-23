"""Bounded publisher-detail fallback for a self-contained venue/date HTML card.

Uses one exact event-title heading, a named venue linked to the publisher's
location page, a same-date clock and the matching official venue address.
The date in the permalink must agree with the displayed month/day. Multi-date
programs with no individually verifiable start are deliberately not generated.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import record
from roomquest.registered_native_content import attach


def read(source, soup, url):
    path = urlsplit(url).path
    match = re.fullmatch(r'/event/[a-z0-9-]+-(20[0-9]{2}-[01][0-9]-[0-3][0-9])/?', path)
    if not match:
        return None
    names = soup.select('main h2.fl-heading')
    venues = soup.select('main a.event-info-location[href]')
    date_widgets = [x for x in soup.select('main .fl-module-html')
                    if re.match(r'^[A-Z][a-z]+\s+\d{1,2}\b', x.get_text(' ', strip=True))]
    if len(names) != 1 or len(venues) != 1 or len(date_widgets) != 1:
        return None
    name = names[0].get_text(' ', strip=True)
    venue = venues[0].get_text(' ', strip=True)
    location_link = urlsplit(venues[0]['href'])
    if (not name or not venue or location_link.hostname != urlsplit(url).hostname
            or not location_link.path.startswith('/location/')):
        return None

    # The exact day, not merely the URL, must be written on the detail page.
    text = date_widgets[0].get_text(' ', strip=True)
    date_prefix = re.match(
        r'^([A-Z][a-z]+)\s+(\d{1,2})\s+(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*'
        r'(\d{1,2}:\d{2}\s*[ap]m)$', text, re.I)
    if not date_prefix:
        # A multi-month or recurring program does not provide individual dates.
        if re.search(r'\s-\s+[A-Z][a-z]+\s+\d{1,2}', text):
            return []
        return None
    first_day = datetime.strptime(
        match[1][:4] + ' ' + date_prefix[1] + ' ' + date_prefix[2],
        '%Y %B %d').date()
    if first_day.isoformat() != match[1]:
        return None

    # Resolve the ONE matching venue's publisher-written footer address.
    matches = []
    for heading in soup.select('h5.fl-heading'):
        if heading.get_text(' ', strip=True).casefold() != venue.casefold():
            continue
        col = heading.find_parent(class_='fl-col')
        if col:
            addresses = col.select('address.location-address')
            if len(addresses) == 1:
                matches.append(addresses[0].get_text(' ', strip=True))
    if len(matches) != 1:
        return None
    address = re.fullmatch(r'(.+?)\s+' + re.escape(venue)
                           + r',\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)',
                           matches[0], re.I)
    if not address or address[2] != 'VA':
        # Only the explicitly verified Virginia publisher clock is supported;
        # never infer another site's location from an operator-wide footer.
        return None
    clock = ZoneInfo('America/New_York')
    try:
        begins = datetime.combine(first_day, datetime.strptime(
            date_prefix[3].replace(' ', '').upper(), '%I:%M%p').time()).replace(tzinfo=clock)
        ends = datetime.combine(first_day, datetime.strptime(
            date_prefix[4].replace(' ', '').upper(), '%I:%M%p').time()).replace(tzinfo=clock)
        if (begins.utcoffset() != begins.replace(fold=1).utcoffset()
                or ends.utcoffset() != ends.replace(fold=1).utcoffset()
                or begins.astimezone(timezone.utc).astimezone(clock) != begins
                or ends.astimezone(timezone.utc).astimezone(clock) != ends
                or ends <= begins):
            return None
    except ValueError:
        return None
    row = record(name, begins.isoformat(), ends.isoformat(), venue,
                 ', '.join((address[1], venue, address[2] + ' ' + address[3])),
                 venue, url, url + '#event')
    if row is None:
        return []
    bodies = soup.select('main .fl-module-cp-content-builder')
    narrative = bodies[0].get_text(' ', strip=True) if len(bodies) == 1 else None
    attach(row, source, description_value=narrative, evidence_url=url)
    return [row]
