"""Performances published in Virginia Rep's WordPress month calendar."""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record


KEY = 'municipal_mapsee_aa77c4b1e09ccc6dfb9d1bba'
URL = 'https://va-rep.org/calendar/'
ZONE = 'America/New_York'
VENUES = {
    '114 west broad street richmond, virginia 23220': (
        '114 West Broad Street, Richmond, VA 23220', 37.546371674448, -77.442921234224),
    '23 w. broad st. richmond va 23220': (
        '23 West Broad Street, Richmond, VA 23220', 37.545683315831, -77.442259118522),
    '13181 hanover courthouse road hanover, virginia 23069': (
        '13181 Hanover Courthouse Road, Hanover, VA 23069', 37.76254613865, -77.367227201631),
}


def parse_month(payload, month, now):
    zone = ZoneInfo(ZONE)
    soup = BeautifulSoup(payload, 'html.parser')
    days = soup.select('main.month .day[id^="day-"]:not(.adj-month)')
    dated = [(datetime.fromtimestamp(int(day['id'][4:]), zone).date(), day) for day in days]
    expected = [month.replace(day=n) for n in range(1, monthrange(month.year, month.month)[1] + 1)]
    if [day for day, _ in dated] != expected:
        raise ValueError('invalid_performance_calendar_month')
    rows = {}
    for day, cell in dated:
        for event in cell.select('ul.events > li.event'):
            heading = event.select_one('.event__title')
            detail = event.select_one('a[href^="https://va-rep.org/events/"]')
            if not heading or not detail or urlsplit(detail['href']).netloc != 'va-rep.org':
                raise ValueError('invalid_performance_event')
            performances = event.select('ul.performances > li.performance')
            if not performances:
                raise ValueError('performance_schedule_missing')
            for performance in performances:
                time = performance.select_one('.action__time a[href]')
                venue = performance.select_one('.venue__title')
                address = performance.select_one('.venue__address')
                if not all((time, venue, address)):
                    continue
                ticket = urlsplit(time['href'])
                if ticket.scheme != 'https' or ticket.netloc != 'tickets.va-rep.org':
                    continue
                if not re.fullmatch(r'/[0-9]+/[0-9]+/?', ticket.path):
                    continue
                begins = datetime.combine(day, datetime.strptime(
                    time.get_text(strip=True).upper(), '%I:%M%p').time(), zone)
                if not now <= begins < now + timedelta(days=60):
                    continue
                published_address = ' '.join(address.get_text(' ', strip=True).split())
                street, lat, lng = VENUES.get(published_address.lower(), (published_address, None, None))
                identity = 'va-rep-' + ticket.path.strip('/').replace('/', '-')
                row = record(heading.get_text(' ', strip=True), begins, None,
                             venue.get_text(' ', strip=True), street, '', detail['href'],
                             identity, 'theater', lat, lng)
                if row is not None:
                    if identity in rows and rows[identity] != row:
                        raise ValueError('conflicting_event_occurrence')
                    rows[identity] = row
    return list(rows.values())


def collect(source, fetch, *, now=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone')) != (KEY, URL, ZONE):
        raise ValueError('unregistered_performance_calendar')
    now = now or datetime.now(ZoneInfo(ZONE))
    month = now.date().replace(day=1)
    following_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    next_url = URL + '?' + urlencode({'month': following_month.strftime('%B %Y')})
    rows = parse_month(fetch(URL, 'text/html'), month, now)
    rows.extend(parse_month(fetch(next_url, 'text/html'), following_month, now))
    return sorted(rows, key=lambda row: (row['starts_at'], row['id']))
