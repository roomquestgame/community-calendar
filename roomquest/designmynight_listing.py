"""Box Room's reviewed, publicly linked DesignMyNight ticket pages.

Only the exact venue prefix linked by the submitted calendar is traversed.
The ticket API is robots-disallowed and is never used. Explicit written weekly
and monthly rules are bounded to 60 days; calendar images are not interpreted.
"""
import calendar
from datetime import datetime, timedelta
import json
import logging
import re
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record

URL = 'https://theboxroombgc.co.uk/events-1'
TICKET_PREFIX = 'https://www.designmynight.com/cambridge/restaurants/the-box-room-board-game-cafe/'
MAX_DETAILS = 12
MAX_SECONDS = 30
LONDON = ZoneInfo('Europe/London')
VENUE = 'The Box Room Board Game Café'
STREET = '58 Regent Street, Cambridge, CB2 1DP, United Kingdom'
HOURS = r'([0-2]\d:[0-5]\d)\s*-\s*([0-2]\d:[0-5]\d)'
DAY = r'([A-Za-z]+),? (\d{1,2})(?:st|nd|rd|th) ([A-Za-z]+) (\d{4})'
log = logging.getLogger(__name__)


def text(soup, selector):
    element = soup.select_one(selector)
    return re.sub(r'\s+', ' ', element.get_text(' ', strip=True)) if element else ''


def canonical_ticket(url):
    """A narrow reviewed prefix, one slug, and the publisher's ticket selector."""
    parts = urlsplit(url)
    base = urlsplit(TICKET_PREFIX)
    if (parts.scheme != 'https' or parts.netloc != base.netloc
            or not re.fullmatch(re.escape(base.path) + r'[a-z0-9]+(?:-[a-z0-9]+)*', parts.path)
            or parts.query not in ('', 't=tickets') or parts.fragment):
        return None
    return 'https://' + parts.netloc + parts.path


def linked_tickets(soup):
    links = {}
    for anchor in soup.select('a[href]'):
        url = anchor['href']
        parts = urlsplit(url)
        if parts.hostname != 'www.designmynight.com':
            continue
        canonical = canonical_ticket(url)
        if canonical is None:
            # Another venue or a changed ticket route needs its own review.
            raise ValueError('box_ticket_url_unreviewed')
        links.setdefault(canonical, url)
    if not links:
        raise ValueError('box_ticket_links_missing')
    if len(links) > MAX_DETAILS:
        raise ValueError('box_calendar_detail_limit')
    return links


def event_identity(soup, url):
    events = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or node.get_text())
        except (TypeError, ValueError):
            continue
        for value in data if isinstance(data, list) else [data]:
            if isinstance(value, dict) and value.get('@type') == 'Event':
                events.append(value)
    if len(events) != 1:
        raise ValueError('box_event_identity_unverified')
    event = events[0]
    organizer, location = event.get('organizer', {}), event.get('location', {})
    address = location.get('address', {})
    if (event.get('url') != url or not canonical_ticket(url)
            or event.get('name') != text(soup, 'h1')
            or organizer.get('name') != 'The Box Room Board Game Cafe'
            or organizer.get('url') not in ('http://theboxroombgc.co.uk', 'https://theboxroombgc.co.uk')
            or location.get('name') != VENUE
            or address.get('streetAddress') != VENUE + ', 58 Regent St'
            or address.get('postalCode') != 'CB2 1DP' or address.get('addressCountry') != 'GB'
            or event.get('eventAttendanceMode') != 'https://schema.org/OfflineEventAttendanceMode'):
        raise ValueError('box_event_identity_unverified')
    # The linked ticket page and publisher homepage independently identify this
    # exact street/postcode. Coordinates are left to normal geocoder handling.
    return event


def date_value(weekday, number, month, year):
    months = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name}
    months.update({name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name})
    try:
        day = datetime(int(year), months[month.casefold()], int(number)).date()
    except (KeyError, TypeError, ValueError):
        raise ValueError('box_event_schedule_unverified') from None
    if weekday.lower() not in (day.strftime('%A').lower(), day.strftime('%a').lower()):
        raise ValueError('box_event_schedule_conflict')
    return day


def clocks(label):
    match = re.fullmatch(HOURS, label)
    if not match:
        raise ValueError('box_event_schedule_unverified')
    try:
        return tuple(datetime.strptime(match[i], '%H:%M').time() for i in (1, 2))
    except ValueError:
        raise ValueError('box_event_schedule_unverified') from None


def schedule(soup, event, today):
    dates = text(soup, 'li[title="Dates"]')
    if (dates == 'This event has taken place.'
            or event.get('eventStatus') == 'https://schema.org/EventCancelled'):
        return []
    if event.get('eventStatus') != 'https://schema.org/EventScheduled':
        raise ValueError('box_event_schedule_unverified')
    if dates != text(soup, 'table.table-borderless.table-condensed.margin-none tbody tr td:nth-of-type(2)'):
        raise ValueError('box_event_schedule_conflict')
    horizon = today + timedelta(days=60)
    # Multi-date tickets currently lie beyond the window. Their nonuniform
    # sessions require review once relevant; do not manufacture a single span.
    multi = re.fullmatch(r'([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th) and ([A-Za-z]+) '
                         r'(\d{1,2})(?:st|nd|rd|th) ([A-Za-z]+) (\d{4})', dates)
    if multi:
        days = [date_value(multi[1], multi[2], multi[5], multi[6]),
                date_value(multi[3], multi[4], multi[5], multi[6])]
        if min(days) > horizon or max(days) < today:
            return []
        raise ValueError('box_event_schedule_multiple_sessions_requires_review')
    every = re.fullmatch(r'Every (?:(1st) )?(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
                         r'( of the month)?', dates)
    dated = re.fullmatch(DAY + r'(?: @ ' + HOURS + r'| and (\d+) other ([A-Za-z]+)s)?', dates)
    if not every and not dated:
        raise ValueError('box_event_schedule_unverified')
    if every and bool(every[1]) != bool(every[3]):
        raise ValueError('box_event_schedule_unverified')
    day = date_value(*dated.groups()[:4]) if dated else None
    if day and not today <= day <= horizon:
        return []
    hours = clocks(text(soup, 'li[title="Time"]'))
    ticket_times = []
    for table in soup.select('table.table-condensed.table-striped'):
        if [cell.get_text(' ', strip=True) for cell in table.select('thead th')] != ['Ticket', 'Event time', 'Cost']:
            continue
        for row in table.select('tbody tr'):
            cells = row.find_all('td', recursive=False)
            if len(cells) != 3:
                raise ValueError('box_event_schedule_unverified')
            ticket_times.append(clocks(re.sub(r'\s+', ' ', cells[1].get_text(' ', strip=True))))
    if not ticket_times or any(value != hours for value in ticket_times):
        raise ValueError('box_event_schedule_conflict')
    if dated and dated[5] and (clocks(dated[5] + ' - ' + dated[6]) != hours):
        raise ValueError('box_event_schedule_conflict')
    try:
        anchor, anchor_end = (datetime.fromisoformat(event[field]) for field in ('startDate', 'endDate'))
    except (KeyError, TypeError, ValueError):
        raise ValueError('box_event_schedule_unverified') from None
    for stamp in (anchor, anchor_end):
        if stamp.tzinfo is None or stamp.utcoffset() != stamp.replace(tzinfo=LONDON).utcoffset():
            raise ValueError('box_event_schedule_conflict')
    if anchor.date() != anchor_end.date():
        raise ValueError('box_event_schedule_conflict')
    # Reviewed platform defect: these pages serialize both dates as the end
    # instant. Correct it only when the visible summary and ticket table agree,
    # and the schema's identical instants match that exact end on the same day.
    actual_schema_times = (anchor.time(), anchor_end.time())
    if actual_schema_times != hours and not (anchor == anchor_end and anchor.time() == hours[1]):
        raise ValueError('box_event_schedule_conflict')
    if dated:
        if anchor.date() != day:
            raise ValueError('box_event_schedule_conflict')
        if dated[7]:
            if dated[8] != day.strftime('%A'):
                raise ValueError('box_event_schedule_conflict')
            log.warning('Box Room lists %s additional undated occurrences; retaining only %s: %s',
                        dated[7], day, event['url'])
        days = [day]
    else:
        narrative = text(soup, '#tab-description div.tabs__description')
        if re.search(r'\b(?:except(?:ing)?|excluding|closures?|closed|cancell?ed|not running|no (?:event|session)s?)\b',
                     narrative, re.I):
            raise ValueError('box_event_schedule_exceptions_require_review')
        weekday = list(calendar.day_name).index(every[2])
        if anchor.weekday() != weekday or (every[1] and anchor.day > 7):
            raise ValueError('box_event_schedule_conflict')
        days = [today + timedelta(days=offset) for offset in range(61)]
        days = [value for value in days if value >= anchor.date() and value.weekday() == weekday
                and (not every[1] or value.day <= 7)]
    result = []
    for day in days:
        start, end = (datetime.combine(day, value) for value in hours)
        if not timedelta(0) < end - start <= timedelta(hours=12):
            raise ValueError('box_event_schedule_conflict')
        result.append((start, end))
    return result


def rows(soup, fetch, today, deadline_at):
    links = linked_tickets(soup)  # Preflight the full batch; never truncate it.
    deadline = min(deadline_at, monotonic() + MAX_SECONDS) if deadline_at is not None else monotonic() + MAX_SECONDS
    for canonical, linked_url in links.items():
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        detail = BeautifulSoup(fetch(linked_url, 'text/html'), 'html.parser')
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        event = event_identity(detail, canonical)
        try:
            intervals = schedule(detail, event, today)
        except ValueError as exc:
            if not str(exc).startswith('box_event_schedule_'):
                raise
            log.warning('Box Room occurrence held (%s): %s', exc, canonical)
            continue
        narrative = description(str(detail.select_one('#tab-description div.tabs__description') or ''))
        for start, end in intervals:
            row = record(event['name'], start, end, VENUE, STREET, 'Cambridge', canonical, canonical,
                         'Games', tz=LONDON.key)
            if row:
                row['description'] = narrative
                yield row
    if monotonic() >= deadline:
        raise ValueError('collection_deadline')
