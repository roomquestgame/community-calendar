"""Exact publisher calendars reviewed for URL-only feed registration."""
import calendar
from datetime import datetime, timedelta
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record
from roomquest.registration_formats import source_key
from roomquest import registered_schedule_calendars as schedules
from roomquest import liberty_calendar, uk_registered_listings, wix_embedded_calendar

BOPLEX = 'https://www.boplex.com/events'
BROADWAY = 'https://www.broadwaycomedyclub.com/'
RESIDENT = 'https://residentculturebrewing.com/events/'
PLAZA = RESIDENT + '?fwp_event_location=plaza-midwood'
INDY = 'https://www.indywinterfarmersmarket.org/'
URLS = ((BOPLEX, BROADWAY, RESIDENT, PLAZA, INDY) + schedules.URLS
        + uk_registered_listings.URLS + wix_embedded_calendar.URLS + (liberty_calendar.ORIGINAL,))
EASTERN = ZoneInfo('America/New_York')
CLOCK = r'(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*[ap]m'


def allowed_hosts(url):
    """Keep reviewed listing transport scoped to its verified publisher."""
    if url not in URLS:
        raise ValueError('unregistered_html_source')
    if url in uk_registered_listings.URLS:
        return uk_registered_listings.allowed_hosts(url)
    return (urlsplit(url).hostname,)


def content(node, selector):
    element = node.select_one(selector)
    return element.get_text(' ', strip=True) if element else ''


def clock(label):
    value = label.replace(' ', '').upper()
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def broadway(soup):
    footer = soup.find(string=re.compile(r'318 W\. 53rd St'))
    address = '318 W. 53rd St, New York, NY 10019'
    if not footer or 'New York, NY 10019' not in footer.parent.get_text(' ', strip=True):
        raise ValueError('club_address_unverified')
    for card in soup.select('.tessera-show-card[data-fulldate]'):
        room = content(card, '.tessera-venue')
        title = card.select_one('a:has(.card-title)')
        label = re.fullmatch(r'Show\s+(' + CLOCK + ')', content(card, '.tessera-showTimes'), re.I)
        if not (label and title and room and card.get('data-venue') == 'Broadway Comedy Club'):
            continue
        url = title.get('href', '')
        if not url.startswith(BROADWAY + 'shows/'):
            continue
        day = datetime.strptime(card['data-fulldate'], '%B %d, %Y').date()
        start = datetime.combine(day, clock(label[1]))
        yield record(title.get_text(' ', strip=True), start, None, 'Broadway Comedy Club – ' + room,
                     address, 'New York', url, url, tz=EASTERN.key)


def boplex(listing, fetch, today):
    home = 'https://www.boplex.com/'
    if not any(urljoin(BOPLEX, a['href']) == home for a in listing.select('a[href]')):
        raise ValueError('boplex_listing_changed')
    soup = BeautifulSoup(fetch(home, 'text/html'), 'html.parser')
    dates = {(today + timedelta(days=i)).strftime('%a, %b %d').upper().replace(' 0', ' '):
             today + timedelta(days=i) for i in range(61)}
    locations = {}
    for card in soup.select('article.bp-card-carousel__card'):
        title = card.select_one('a:has(.bp-card-carousel-card__title)')
        venue = content(card, '.bp-card-carousel-card__location')
        when = content(card, '.bp-card-carousel-card__time-line')
        day = dates.get(content(card, '.bp-card-carousel-card__date-line').upper().replace(' 0', ' '))
        if not (title and day and re.fullmatch(CLOCK, when, re.I)
                and venue in ('Bojangles Coliseum', 'Ovens Auditorium')):
            continue
        url = urljoin(home, title.get('href', ''))
        if not url.startswith(BOPLEX + '/'):
            continue
        venue_url = urljoin(home, card.select_one('.bp-card-carousel-card__location').get('href', ''))
        if venue_url != home + 'our-venues/' + venue.lower().replace(' ', '-'):
            continue
        if venue not in locations:
            page = BeautifulSoup(fetch(venue_url, 'text/html'), 'html.parser')
            pins = set()
            for link in page.select('a[href]'):
                maps = urlsplit(link['href'])
                if maps.hostname == 'www.google.com' and maps.path.startswith('/maps/place/' + venue.replace(' ', '+') + '/'):
                    pin = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', maps.path)
                    if pin:
                        pins.add((float(pin[1]), float(pin[2])))
            if len(pins) != 1:
                raise ValueError('boplex_venue_pin_unverified')
            locations[venue] = pins.pop()
        yield record(title.get_text(' ', strip=True), datetime.combine(day, clock(when)), None,
                     venue, '2700 East Independence Blvd, Charlotte, NC 28205', 'Charlotte',
                     url, url, content(card, '.bp-card-carousel-card__category'), *locations[venue], tz=EASTERN.key)


def resident(soup, url, fetch, today):
    addresses = {}
    for node in soup.select('address.location-address'):
        heading = node.find_previous('h2')
        parts = list(node.stripped_strings)
        if heading and len(parts) >= 2:
            addresses[heading.get_text(' ', strip=True).lower()] = ', '.join(parts[-2:])
    horizon = today + timedelta(days=60)
    def occurrences(title, link, venue, narrative, weekday, start, end, first, last):
        name = venue.lower()
        if name not in addresses or (url == PLAZA and name != 'plaza midwood'):
            return
        day = max(first, today)
        day += timedelta(days=(weekday - day.weekday()) % 7)
        while day <= min(last, horizon):
            row = record(title, datetime.combine(day, start), datetime.combine(day, end) if end else None,
                         'Resident Culture – ' + ('7th Street' if name == '7th street' else venue.title()), addresses[name], 'Charlotte', link,
                         link + '|' + day.isoformat(), tz=EASTERN.key)
            if row:
                row['description'] = description(narrative)
                yield row
            day += timedelta(days=7)
    for modal in soup.select('.modal[id]:has(.modal-heading)'):
        heading = modal.find_previous('h3')
        narrative = content(modal, '.modal-content')
        schedule = re.search(r'\bevery (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
                             r'(?: night)? (?:at |from )?(' + CLOCK + r')(?:\s*[-–]\s*(' + CLOCK + r'))?', narrative, re.I)
        if not schedule:
            # The publisher also abbreviates ranges such as "every Tuesday from 6-9PM".
            short = re.search(r'\bevery (\w+)(?: night)? from (\d{1,2})[-–](\d{1,2})([ap]m)\b', narrative, re.I)
            if short and short[1].title() in calendar.day_name and 0 < int(short[2]) < int(short[3]) < 12:
                schedule = (None, short[1], short[2] + short[4], short[3] + short[4])
        if not schedule or not heading or not re.fullmatch(r'action-modal-\d+', modal['id']):
            continue
        yield from occurrences(content(modal, '.modal-heading'), RESIDENT + '#' + modal['id'],
                               heading.get_text(' ', strip=True), narrative, list(calendar.day_name).index(schedule[1].title()),
                               clock(schedule[2]), clock(schedule[3]) if schedule[3] else None, today, horizon)
    # Dated archive entries are separate from the weekly panels. In particular the
    # Food Truck Friday season ends on a Saturday; only Fridays have performances.
    for card in soup.select('a.excerpt-box.type--post[href]'):
        link = card['href']
        match = re.fullmatch(re.escape('https://residentculturebrewing.com/event/food-truck-friday-') +
                             r'(\d{4}-\d\d-\d\d)/', link)
        venue = content(card, '.excerpt-box-location')
        if not match or (url == PLAZA and venue.lower() != 'plaza midwood'):
            continue
        detail = BeautifulSoup(fetch(link, 'text/html'), 'html.parser')
        span = content(detail, '.meta-entry')
        bounds = re.fullmatch(r'([A-Za-z]+ \d+) (' + CLOCK + r') - ([A-Za-z]+ \d+) (' + CLOCK + ')', span, re.I)
        narrative = content(detail, '.layout-content')
        if not bounds or not re.search(r'Fridays\s*\|\s*5[–-]9\s*pm', narrative, re.I):
            continue
        first = datetime.fromisoformat(match[1]).date()
        last = datetime.strptime(f'{bounds[3]} {first.year}', '%B %d %Y').date()
        if first.strftime('%B %d').replace(' 0',' ') == bounds[1] and bounds[2].lower() == '5:00 pm' and bounds[4].lower() == '9:00 pm':
            yield from occurrences(content(card, '.excerpt-box-title'), link, venue, narrative, 4,
                                   clock(bounds[2]), clock(bounds[4]), first, last)



def seasonal_weekly_dates(first, last, weekday, excluded, today, horizon=60):
    """Expand only an explicitly bounded publisher season and its closures."""
    if last < first or (last-first).days > 370:
        raise ValueError('season_bounds_unverified')
    day = max(first, today)
    day += timedelta(days=(weekday-day.weekday()) % 7)
    while day <= min(last, today+timedelta(days=horizon)):
        if day not in excluded:
            yield day
        day += timedelta(days=7)


def indy(soup, today):
    # A public HTML season, not the robots-disallowed Squarespace JSON endpoint.
    # The footer must state all dates, hours, address and exception together.
    footer = soup.find('footer')
    text = footer.get_text(' ', strip=True) if footer else ''
    season = re.search(r'EVERY SATURDAY ([A-Za-z]+ \d{1,2}, \d{4}) - ([A-Za-z]+ \d{1,2}, \d{4}) Closed on ([A-Za-z]+ \d{1,2}) 9 a\.m\. [—–-] 12:30 p\.m\.', text)
    address = '1220 Waterway Blvd, Indianapolis, IN 46202'
    if not season or ('Located at The AMP '+address) not in text:
        raise ValueError('market_season_unverified')
    first, last = [datetime.strptime(season[i], '%B %d, %Y').date() for i in (1,2)]
    closed = [datetime.strptime(season[3]+' '+str(year), '%B %d %Y').date()
              for year in range(first.year,last.year+1)]
    closed = [day for day in closed if first <= day <= last]
    if len(closed) != 1 or closed[0].weekday() != 5:
        raise ValueError('market_closure_unverified')
    for day in seasonal_weekly_dates(first,last,5,set(closed),today):
        yield record('Indy Winter Farmers Market',datetime.combine(day,clock('9am')),
                     datetime.combine(day,clock('12:30pm')),'The AMP',address,'Indianapolis',
                     INDY,INDY,'Food & Coffee',tz='America/Indiana/Indianapolis')


def collect(source, fetch, *, deadline_at=None, listing=None):
    url = source['feed_url']
    if url not in URLS or source.get('source_key') != source_key(url):
        raise ValueError('unregistered_html_source')
    if url == liberty_calendar.ORIGINAL:
        return liberty_calendar.collect(source, fetch, deadline_at=deadline_at, listing=listing)
    if url in uk_registered_listings.URLS:
        return uk_registered_listings.collect(source, fetch, deadline_at=deadline_at, listing=listing)
    soup = BeautifulSoup(listing if listing is not None else fetch(url, 'text/html'), 'html.parser')
    today = datetime.now(EASTERN).date()
    if url == BOPLEX:
        rows = boplex(soup, fetch, today)
    elif url == INDY:
        rows = indy(soup, today)
    elif url == BROADWAY:
        rows = broadway(soup)
    elif url == schedules.FOREST:
        rows = schedules.forest(soup, today)
    elif url == schedules.ALGONQUIN:
        rows = schedules.algonquin(soup, fetch, today, deadline_at)
    elif url == schedules.GRAVEGARDEN:
        rows = schedules.gravegarden(soup, today)
    elif url in wix_embedded_calendar.URLS:
        rows = wix_embedded_calendar.rows(soup, url, today)
    else:
        rows = resident(soup, url, fetch, today)
    result = {}
    for row in rows:
        if row:
            key = (row['id'], row['starts_at'])
            if key in result and result[key] != row:
                raise ValueError('conflicting_event_occurrence')
            result[key] = row
    if not result:
        raise ValueError('no_extractable_events')
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))
