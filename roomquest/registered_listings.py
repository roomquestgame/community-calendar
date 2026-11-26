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
from roomquest import liberty_calendar, uk_registered_listings, wix_embedded_calendar, wildlife_trusts

BOPLEX = 'https://www.boplex.com/events'
BROADWAY = 'https://www.broadwaycomedyclub.com/'
RESIDENT = 'https://residentculturebrewing.com/events/'
PLAZA = RESIDENT + '?fwp_event_location=plaza-midwood'
INDY = 'https://www.indywinterfarmersmarket.org/'
LYNCHBURG = 'https://www.lynchburgparksandrec.com/programs-and-activities/'
STATE_THEATRE = 'https://statetheatreportland.com/calendar/'
SHANK = 'https://shankhall.com/'
MAINE_JEWISH = 'https://mainejewishmuseum.org/programs-and-events/'
URLS = ((BOPLEX, BROADWAY, RESIDENT, PLAZA, INDY) + schedules.URLS
        + uk_registered_listings.URLS + wix_embedded_calendar.URLS + wildlife_trusts.URLS
        + (liberty_calendar.ORIGINAL, LYNCHBURG, STATE_THEATRE, SHANK, MAINE_JEWISH))
EASTERN = ZoneInfo('America/New_York')
CLOCK = r'(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*[ap]m'


def allowed_hosts(url):
    """Keep reviewed listing transport scoped to its verified publisher."""
    if url not in URLS:
        raise ValueError('unregistered_html_source')
    if url in uk_registered_listings.URLS:
        return uk_registered_listings.allowed_hosts(url)
    if url in wildlife_trusts.URLS:
        return wildlife_trusts.allowed_hosts(url)
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


def lynchburg(soup, today):
    """Read the publisher's WordPress activity archive, not its WebTrac link.

    WebTrac is only the checkout/registration destination on this site.  The
    authoritative public inventory and dates are first-party `cl_and_activ`
    cards.  Rows with `Varies` or a multi-day range are intentionally withheld
    because the archive does not publish an occurrence clock for them.
    """
    classes = set((soup.body or {}).get('class', ())) if soup.body else set()
    if not {'post-type-archive', 'post-type-archive-cl_and_activ'} <= classes:
        raise ValueError('lynchburg_activity_archive_changed')
    addresses = {
        'Miller Center': '301 Grove Street, Lynchburg, VA 24501',
        'City Armory': '1200 Church Street, Lynchburg, VA 24504',
        'Lynchburg Community Market': '1219 Main Street, Lynchburg, VA 24504',
        'Meet at Lynchburg Community Market': '1219 Main Street, Lynchburg, VA 24504',
    }
    for card in soup.select('.pna-item'):
        title = card.select_one('.pna-title a[href]')
        venue = content(card, '.pna-location')
        dates = content(card, '.pna-dates')
        starts = content(card, '.pna-times')
        if not title or venue not in addresses:
            continue
        url = urljoin(LYNCHBURG, title.get('href', ''))
        if (urlsplit(url).hostname != urlsplit(LYNCHBURG).hostname
                or not url.startswith(LYNCHBURG) or url == LYNCHBURG):
            continue
        day_match = re.fullmatch(r'(\d{2}/\d{2}/\d{4})\s*-?', dates)
        time_match = re.fullmatch(r'Start:\s*(' + CLOCK + ')', starts, re.I)
        if not day_match or not time_match:
            continue
        day = datetime.strptime(day_match[1], '%m/%d/%Y').date()
        if not today <= day <= today + timedelta(days=60):
            continue
        yield record(title.get_text(' ', strip=True), datetime.combine(day, clock(time_match[1])),
                     None, venue, addresses[venue], 'Lynchburg', url, url,
                     tz=EASTERN.key)


def state_theatre(soup, fetch, today):
    """Read State Theatre's real ``goo-calendar`` and its exact event pages.

    The publisher's ``/events/`` page is an unrelated, empty Events Manager
    shell.  Its complete inventory is rendered by one first-party calendar.
    The calendar supplies occurrence scope and detail URLs; the event pages
    supply the authoritative show time and corrected venue name.  Every
    occurrence in the 60-day intake horizon must verify, so a template or
    venue change cannot silently publish a partial snapshot.
    """
    classes = set((soup.body or {}).get('class', ())) if soup.body else set()
    calendars = soup.select('.goo_calendar_container.goo_calendar_active[data-post_id]')
    if 'page-calendar' not in classes or not calendars:
        raise ValueError('state_theatre_calendar_changed')
    if (any(not node.get('data-post_id', '').isdigit() for node in calendars)
            or any(len(node.select(':scope > table.goo_table_scheduler')) != 1 for node in calendars)):
        raise ValueError('state_theatre_calendar_ambiguous')

    horizon = today + timedelta(days=60)
    occurrences = []
    months = set()
    for table in soup.select('.goo_calendar_container table.goo_table_scheduler'):
        calendar_node = table.find_parent(
            class_=lambda value: value and 'goo_calendar_container' in value.split())
        calendar_id = calendar_node.get('data-post_id', '') if calendar_node else ''
        if not calendar_id.isdigit():
            raise ValueError('state_theatre_calendar_ambiguous')
        heading = content(table, '.goo_month_name')
        try:
            first = datetime.strptime(heading, '%B %Y').date().replace(day=1)
        except ValueError as exc:
            raise ValueError('state_theatre_month_unverified') from exc
        if first in months:
            raise ValueError('state_theatre_month_duplicated')
        months.add(first)
        for cell in table.select('td.goo_TD'):
            label = content(cell, '.scheduler_heading')
            if not re.fullmatch(r'(?:0?[1-9]|[12]\d|3[01])', label):
                continue
            try:
                day = first.replace(day=int(label))
            except ValueError as exc:
                raise ValueError('state_theatre_day_invalid') from exc
            if not today <= day <= horizon:
                continue
            for anchor in cell.select('.cal-entry-headliner > a[href]:has(.goo_cal_link[data-post_id][data-calendar_id])'):
                marker = anchor.select_one('.goo_cal_link[data-post_id][data-calendar_id]')
                url = urljoin(STATE_THEATRE, anchor.get('href', ''))
                if (urlsplit(url).hostname != urlsplit(STATE_THEATRE).hostname
                        or not re.fullmatch(re.escape('https://statetheatreportland.com/events/')
                                            + r'[a-z0-9][a-z0-9-]*/', url)
                        or marker.get('data-calendar_id') != calendar_id
                        or not marker.get('data-post_id', '').isdigit()):
                    raise ValueError('state_theatre_event_link_unverified')
                occurrences.append((day, url, marker.get_text(' ', strip=True)))
    if not occurrences:
        raise ValueError('no_extractable_events')

    addresses = {
        'State Theatre': '609 Congress Street, Portland, ME 04101',
        'Portland House of Music and Events': '25 Temple Street, Portland, ME 04101',
        "Mechanics' Hall": '519 Congress Street, Portland, ME 04101',
        "Live at Madrid's": '144 Fore Street, Portland, ME 04103',
        "Thompson's Point": '207 Thompsons Point, Portland, ME 04102',
    }
    seen = set()
    for listed_day, url, listed_title in occurrences:
        if (listed_day, url) in seen:
            raise ValueError('state_theatre_occurrence_duplicated')
        seen.add((listed_day, url))
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        article = detail.select_one('article.tm_event.type-tm_event .edp-view-details.vevent')
        title = content(article, '.headliners.summary') if article else ''
        venue = content(article, '.venue.location') if article else ''
        date_label = content(article, '.edp-dates') if article else ''
        time_label = content(article, '.edp-times') if article else ''
        day_match = re.fullmatch(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Za-z]+ \d{1,2}, \d{4})', date_label)
        show_match = re.search(r'\bShow:\s*(' + CLOCK + r')\b', time_label, re.I)
        if (not title or title != listed_title or venue not in addresses
                or not day_match or not show_match):
            raise ValueError('state_theatre_event_detail_changed')
        day = datetime.strptime(day_match[1], '%B %d, %Y').date()
        if day != listed_day:
            raise ValueError('state_theatre_occurrence_mismatch')
        row = record(title, datetime.combine(day, clock(show_match[1])), None,
                     venue, addresses[venue], 'Portland', url, url,
                     tz=EASTERN.key)
        if not row:
            continue
        narrative = content(detail, '.edp-bio-content')
        if narrative:
            row['description'] = description(narrative)
        image = detail.select_one('article.tm_event img.wp-post-image[src]')
        if image:
            candidate = urljoin(url, image.get('src', ''))
            if urlsplit(candidate).hostname == urlsplit(STATE_THEATRE).hostname:
                row['image_url'] = candidate
        yield row


def _shank_detail(link):
    url = urljoin(SHANK, link or '')
    parts = urlsplit(url)
    if (parts.hostname != urlsplit(SHANK).hostname
            or not re.fullmatch(r'/shows/[1-9][0-9]*/', parts.path)
            or parts.query or parts.fragment):
        raise ValueError('shank_event_identity_changed')
    return url


def _shank_inventory(home, today):
    """Read the complete ordered identity list from the allowed home page."""
    rows = []
    year = today.year
    previous_month = today.month
    for anchor in home.select('.quick-cal > a[href]:has(> h3)'):
        heading = anchor.select_one(':scope > h3')
        try:
            partial = datetime.strptime(heading.get_text(' ', strip=True), '%B %d')
        except (AttributeError, ValueError) as exc:
            raise ValueError('shank_quick_calendar_changed') from exc
        if partial.month < previous_month:
            year += 1
        previous_month = partial.month
        day = partial.replace(year=year).date()
        title = re.sub(r'\s+([,;:])', r'\1', ''.join(
            str(node) for node in anchor.contents if node is not heading).strip())
        title = BeautifulSoup(title, 'html.parser').get_text(' ', strip=True)
        if not title:
            raise ValueError('shank_quick_calendar_changed')
        rows.append((day, title, _shank_detail(anchor.get('href'))))
    if not rows or len(rows) != len({url for _, _, url in rows}):
        raise ValueError('shank_quick_calendar_incomplete')
    return rows


def _shank_fact(facts, day, title, show_time):
    key = (day, re.sub(r'\s+([,;:])', r'\1', title))
    prior = facts.get(key)
    if prior is not None and prior != show_time:
        raise ValueError('shank_schedule_fact_conflict')
    facts[key] = show_time


def _shank_home_facts(home, facts):
    for card in home.select('#page-content .playbox'):
        title = content(card, 'h3')
        label = content(card, 'h4')
        detail = card.select_one('a[href][aria-label^="Show details for "]')
        match = re.search(r'([A-Za-z]+ \d{1,2}, \d{4})', label)
        times = re.findall(r'\b' + CLOCK + r'\b', label, re.I)
        if not (title and detail and match and len(times) == 1):
            raise ValueError('shank_home_event_changed')
        _shank_detail(detail.get('href'))
        _shank_fact(facts, datetime.strptime(match[1], '%B %d, %Y').date(), title, times[0])


def _shank_ticket_facts(tickets, facts):
    for card in tickets.select('#page-content .playbox'):
        title = content(card, '.text strong')
        link = card.select_one('.text > a[href][aria-label^="Get tickets for "]')
        values = [node.get_text(' ', strip=True) for node in card.select('.text > div')]
        times = [value for value in values if re.fullmatch(CLOCK, value, re.I)]
        match = re.fullmatch(r'Get tickets for ([A-Za-z]+ \d{1,2}, \d{4})',
                             link.get('aria-label', '') if link else '', re.I)
        href = urlsplit(link.get('href', '')) if link else None
        if (not title or not match or len(times) != 1 or not href
                or href.hostname not in ('ticketweb.com', 'www.ticketweb.com')
                or not href.path.startswith('/event/')):
            raise ValueError('shank_ticket_event_changed')
        _shank_fact(facts, datetime.strptime(match[1], '%B %d, %Y').date(), title, times[0])


def _shank_current_schedule(schedule, facts):
    heading = content(schedule, '.calendar > .header > h2')
    try:
        expected = datetime.strptime(heading, '%B %Y')
    except ValueError as exc:
        raise ValueError('shank_calendar_month_mismatch') from exc
    for card in schedule.select('.calendar > .days > .day_num .event'):
        if card.find('strike') or re.search(r'\bcancel(?:led|ed)\b', card.get_text(' ', strip=True), re.I):
            continue
        detail = card.select_one('a.details[href][aria-label]')
        match = re.fullmatch(r'Show details for ([A-Za-z]+ \d{1,2}, \d{4})',
                             detail.get('aria-label', '') if detail else '', re.I)
        values = [node.get_text(' ', strip=True) for node in card.find_all('div', recursive=False)]
        times = [value for value in values if re.fullmatch(CLOCK, value, re.I)]
        titles = [value for value in values if value and value not in times
                  and not value.startswith('$') and not re.search(r'\b(?:advance|door)\b', value, re.I)]
        if not match or len(times) != 1 or len(titles) != 1:
            raise ValueError('shank_event_card_changed')
        _shank_detail(detail.get('href'))
        day = datetime.strptime(match[1], '%B %d, %Y').date()
        if (day.year, day.month) != (expected.year, expected.month):
            raise ValueError('shank_event_month_mismatch')
        _shank_fact(facts, day, titles[0], times[0])


def shank(home, fetch, today):
    """Reconcile allowed publisher pages without crawling disallowed routes.

    robots.txt disallows `/shows/`, `/feed/shows/`, and `/schedule/?...`.
    The allowed homepage supplies the complete event identity list; the
    allowed tickets page, homepage cards, and current schedule independently
    supply clocks. Unmatched identities are record-level holds, not a reason
    to drop the complete source.
    """
    facts = {}
    _shank_home_facts(home, facts)
    _shank_ticket_facts(BeautifulSoup(fetch(SHANK + 'tickets/', 'text/html'), 'html.parser'), facts)
    _shank_current_schedule(BeautifulSoup(fetch(SHANK + 'schedule/', 'text/html'), 'html.parser'), facts)
    inventory = [(day, title, url) for day, title, url in _shank_inventory(home, today)
                 if today <= day <= today + timedelta(days=60)]
    matched = 0
    for day, title, url in inventory:
        show_time = facts.get((day, title))
        if show_time is None:
            continue
        matched += 1
        yield record(title, datetime.combine(day, clock(show_time)), None,
                     'Shank Hall', '1434 N Farwell Ave, Milwaukee, WI 53202',
                     'Milwaukee', url, url, tz='America/Chicago')
    if not inventory or matched < max(1, len(inventory) - 3):
        raise ValueError('shank_schedule_facts_incomplete')


def maine_jewish(soup, today):
    """Read the museum's current first-party programs archive.

    The site still exposes stale The Events Calendar assets, but its live
    schedule is a custom WordPress page.  Cards contain the complete dated
    public facts, including off-site winter programs while the museum is
    temporarily closed.
    """
    classes = set((soup.body or {}).get('class', ())) if soup.body else set()
    cards = soup.select('ul.columns.x2 > li.p-3.align-m')
    if 'page-id-2591' not in classes or not cards:
        raise ValueError('maine_jewish_program_archive_changed')
    venues = {
        'Chanukah in New Vaudeville!': (
            'The Gem Theater', '48 Cross Street, Bethel, ME 04217', 'Bethel',
            ('The Gem Theater', '48 Cross Street, Bethel, Maine')),
        'Zlateh, Thelma & a Whole Lotta Light: Menorah Lighting at the Maine Jewish Museum': (
            'Maine Jewish Museum', '267 Congress Street, Portland, ME 04101', 'Portland',
            ('at the Maine Jewish Museum',)),
        "MJM + Hadassah + Rimon Women's Book Group: This Is Not About Us": (
            'Coffee by Design Roastery Room', '1 Diamond Street, Portland, ME 04101', 'Portland',
            ('Coffee by Design Roastery Room', '1 Diamond Street', 'Portland, Maine 04101')),
        'Happy Hour with a Historian: The Shared Journeys of Maine Irish & Jewish Immigrant Women': (
            'Maine Irish Heritage Center', '34 Gray Street, Portland, ME 04112', 'Portland',
            ('Maine Irish Heritage Center', '34 Gray Street', 'Portland, ME 04112')),
    }
    seen = set()
    for card in cards:
        title = content(card, 'h3.pb-2.uppercase')
        venue = venues.get(title)
        link = card.select('a.button.slim[href]')
        text = card.get_text(' ', strip=True)
        schedule = next((p.get_text(' ', strip=True) for p in card.select('p') if re.search(
            r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
            r'[A-Za-z]+ \d{1,2}, \d{4}\b', p.get_text(' ', strip=True))), '')
        day_match = re.search(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
                              r'([A-Za-z]+ \d{1,2}, \d{4})\b', schedule)
        times = re.findall(r'\b' + CLOCK + r'\b', schedule, re.I)
        if (not venue or len(link) != 1 or not day_match or len(times) < 1
                or not all(marker in text for marker in venue[3])):
            raise ValueError('maine_jewish_program_card_changed')
        url = urljoin(MAINE_JEWISH, link[0].get('href', ''))
        parts = urlsplit(url)
        if (parts.hostname != urlsplit(MAINE_JEWISH).hostname or parts.query or parts.fragment
                or url == MAINE_JEWISH or not parts.path.endswith('/')):
            raise ValueError('maine_jewish_program_identity_changed')
        day = datetime.strptime(day_match[1], '%B %d, %Y').date()
        if (day, url) in seen:
            raise ValueError('maine_jewish_program_duplicated')
        seen.add((day, url))
        if not today <= day <= today + timedelta(days=60):
            continue
        start = datetime.combine(day, clock(times[0]))
        end = datetime.combine(day, clock(times[-1])) if len(times) > 1 else None
        if end is not None and end <= start:
            raise ValueError('maine_jewish_program_time_invalid')
        row = record(title, start, end, venue[0], venue[1], venue[2], url, url,
                     tz=EASTERN.key)
        paragraphs = ' '.join(p.get_text(' ', strip=True) for p in card.select('p'))
        if paragraphs:
            row['description'] = description(paragraphs)
        yield row


def collect(source, fetch, *, deadline_at=None, listing=None):
    url = source['feed_url']
    if url not in URLS or source.get('source_key') != source_key(url):
        raise ValueError('unregistered_html_source')
    if url == liberty_calendar.ORIGINAL:
        return liberty_calendar.collect(source, fetch, deadline_at=deadline_at, listing=listing)
    if url in wildlife_trusts.URLS:
        return wildlife_trusts.collect(source, fetch, deadline_at=deadline_at, listing=listing)
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
    elif url == LYNCHBURG:
        rows = lynchburg(soup, today)
    elif url == STATE_THEATRE:
        rows = state_theatre(soup, fetch, today)
    elif url == SHANK:
        rows = shank(soup, fetch, today)
    elif url == MAINE_JEWISH:
        rows = maine_jewish(soup, today)
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
