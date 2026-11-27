"""Reviewed UK HTML calendars, using only publisher-visible dates and venues.

Transport remains the registration/preview worker's robots-aware fetch. Linked
public booking data uses exact source adapters; image OCR, inferred weekly
schedules and geocoder calls are not used.
"""
from roomquest.collection_window import calendar_anchor
from datetime import datetime, timedelta
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest import battersea_bloem, designmynight_listing, eventin_listing, sustainable_ow
from roomquest.mapsee_adapter import record
from roomquest.registration_formats import source_key

WINE = 'https://www.cambridgewineacademy.com/wine-tastings/'
MILTON = 'https://www.miltoncountrypark.org/whats-on'
URLS = (WINE, MILTON, eventin_listing.URL, designmynight_listing.URL, battersea_bloem.URL, sustainable_ow.URL)
LONDON = ZoneInfo('Europe/London')
MAX_DETAILS = 12
MAX_CARDS = 100
WINE_DETAIL = re.compile(r'/wine-tastings/[a-z0-9-]+/[a-z0-9-]+/\d{2}-\d{2}-\d{4}/')
WIX_DETAIL = re.compile(r'/event-details/[a-z0-9]+(?:-[a-z0-9]+)*/?')
WINE_VENUES = {
    'The Wine Rooms Cambridge, 57 Hills Rd, Cambridge CB2 1NT':
        ('The Wine Rooms Cambridge', '57 Hills Rd, Cambridge CB2 1NT, United Kingdom'),
    'The Wine Rooms, Cambridge, 57 Hills Rd, Cambridge CB2 1NT':
        ('The Wine Rooms Cambridge', '57 Hills Rd, Cambridge CB2 1NT, United Kingdom'),
    # Reviewed Nov 22: the event names this exact branch/street/postcode, and
    # https://www.cambridgewine.com/our-stores/ supplies its street number.
    # This exact match cannot transfer to the merchant's other Cambridge shops.
    'Cambridge Wine Merchants, Cherry Hinton Road, CB1 7BX':
        ('Cambridge Wine Merchants', '163 Cherry Hinton Road, Cambridge CB1 7BX, United Kingdom'),
}


def text(node, selector):
    item = node.select_one(selector)
    return item.get_text(' ', strip=True) if item else ''


def same_host_detail(url, listing, pattern):
    parts, parent = urlsplit(url), urlsplit(listing)
    return (parts.scheme == 'https' and parts.netloc == parent.netloc
            and pattern.fullmatch(parts.path) and not parts.query and not parts.fragment)


def deadline_check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def allowed_hosts(url):
    if url not in URLS:
        raise ValueError('unregistered_html_source')
    hosts = (urlsplit(url).hostname,)
    if url == battersea_bloem.URL:
        return hosts + (urlsplit(battersea_bloem.STORE).hostname,)
    return hosts + ('www.designmynight.com',) if url == designmynight_listing.URL else hosts


def wix_list_rows(soup, listing, today):
    """Use Wix's server-rendered complete date/location panel, not the short badge.

    A repeated event ribbon does not authorize recurrence expansion. Each card
    contributes only its explicitly displayed dated occurrence.
    """
    cards = soup.select('[data-hook="event-list-item"]')
    if len(cards) > MAX_CARDS:
        raise ValueError('wix_calendar_card_limit')
    if soup.select_one('[data-hook="load-more-button"], [data-hook="pagination"]'):
        raise ValueError('pagination_requires_review')
    for card in cards:
        label = text(card, '[data-hook="ev-full-date-location"] [data-hook="date"]')
        dates = re.fullmatch(r'(\d{1,2} [A-Za-z]{3} \d{4}), (\d{1,2}:\d{2})\s*[–-]\s*'
                            r'(?:(\d{1,2} [A-Za-z]{3} \d{4}), )?(\d{1,2}:\d{2})', label)
        if not dates:
            # Date-only, TBA and unbounded schedules are not timed occurrences.
            continue
        start = datetime.strptime(dates[1] + ' ' + dates[2], '%d %b %Y %H:%M')
        end = datetime.strptime((dates[3] or dates[1]) + ' ' + dates[4], '%d %b %Y %H:%M')
        if not today <= start.date() <= today + timedelta(days=60):
            continue
        if end <= start:
            raise ValueError('wix_event_schedule_unverified')
        link = card.select_one('a[data-hook="ev-rsvp-button"][href]')
        title = text(card, '[data-hook="ev-list-item-title"]')
        url = urljoin(listing, link['href']) if link else ''
        if not title or not same_host_detail(url, listing, WIX_DETAIL):
            raise ValueError('wix_event_identity_unverified')
        location = text(card, '[data-hook="ev-full-date-location"] [data-hook="location"]')
        # The publisher uses both these labels for this exact park address.
        venue, separator, street = location.partition(', ')
        if (venue not in ('Milton', 'Milton Country Park') or not separator
                or not re.fullmatch(r'(?:Cambridge Road Industrial Estate, )?Cambridge (?:Rd|Road), '
                                    r'Milton, Cambridge CB24 6AZ, (?:UK|United Kingdom)', street)):
            raise ValueError('wix_event_venue_unverified')
        row = record(title, start, end, 'Milton Country Park', street, 'Milton', url, url,
                     tz=LONDON.key)
        if row:
            row['description'] = description(text(card, '[data-hook="ev-list-item-description"]'))
            yield row


def wine_schedule(label):
    label = re.sub(r'(\d)\s*(?:st|nd|rd|th)\b', r'\1', label, flags=re.I)
    match = re.fullmatch(r'([A-Za-z]+) (\d{1,2})(?:\s*,\s*(\d{4}))?\s*-\s*'
                         r'(\d{1,2}:\d{2}[ap]m)', label, re.I)
    if not match:
        raise ValueError('wine_event_schedule_unverified')
    clock = datetime.strptime(match[4].upper(), '%I:%M%p').time()
    # A leap year permits validation of February 29 before its explicit year
    # is verified on the detail page; it does not assign an event year.
    day = datetime.strptime(f'{match[1]} {match[2]} 2000', '%B %d %Y')
    return day.month, day.day, int(match[3]) if match[3] else None, clock


def wine_card_label(card):
    node = card.select_one('.when')
    if node is None:
        raise ValueError('wine_event_schedule_unverified')
    # ProcessWire emits unclosed paragraphs, nesting price/button divs inside
    # .when under html.parser. Strip those controls before reading its date.
    copy = BeautifulSoup(str(node), 'html.parser')
    for child in copy.select('div'):
        child.decompose()
    return copy.get_text(' ', strip=True)


def wine_rows(soup, fetch, today, deadline_at):
    candidates = {}
    horizon = today + timedelta(days=60)
    for card in soup.select('.upcoming-event'):
        anchor = card.select_one('a[href]')
        if not anchor:
            continue
        url = urljoin(WINE, anchor['href'])
        if not same_host_detail(url, WINE, WINE_DETAIL):
            continue  # The separate wine courses carousel is outside this feed.
        title = text(card, 'h3')
        schedule = wine_schedule(wine_card_label(card))
        month, day, year, _ = schedule
        years = [year] if year else range(today.year, horizon.year + 1)
        possible = []
        for candidate_year in years:
            try:
                possible.append(datetime(candidate_year, month, day).date())
            except ValueError:
                continue
        if not any(today <= candidate <= horizon for candidate in possible):
            continue
        if not title or (url in candidates and candidates[url] != (title, schedule)):
            raise ValueError('wine_event_identity_unverified')
        candidates[url] = (title, schedule)
    if len(candidates) > MAX_DETAILS:
        raise ValueError('wine_calendar_detail_limit')
    for url, (title, schedule) in candidates.items():
        deadline_check(deadline_at)
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        # Slugs can retain an old date after a reschedule. The page's own title
        # supplies the complete current date; listing and detail wall times
        # must independently agree before any occurrence is emitted.
        date_title = re.fullmatch(r'(\d{2}-\d{2}-\d{4}) \| The Cambridge Wine Academy',
                                 text(detail, 'title'))
        panel = detail.select_one('.split-right-event')
        heading = panel.select_one('h1') if panel else None
        if not date_title or not heading or next(heading.stripped_strings, '') != title:
            raise ValueError('wine_event_identity_unverified')
        day = datetime.strptime(date_title[1], '%d-%m-%Y').date()
        icon = panel.select_one('i.fa-clock')
        when = icon.find_parent('span').find_next_sibling('span') if icon else None
        if when is None:
            raise ValueError('wine_event_schedule_unverified')
        displayed = wine_schedule(when.get_text(' ', strip=True))
        for observed in (schedule, displayed):
            if (observed[:2] != (day.month, day.day) or observed[2] not in (None, day.year)
                    or observed[3] != displayed[3]):
                raise ValueError('wine_event_schedule_conflict')
        if not today <= day <= horizon:
            raise ValueError('wine_event_schedule_conflict')
        icon = panel.select_one('i.fa-map-marker-alt')
        location = icon.find_parent('span').find_next_sibling('span') if icon else None
        venue_address = WINE_VENUES.get(location.get_text(' ', strip=True) if location else '')
        if venue_address is None:
            raise ValueError('wine_event_venue_unverified')
        venue, street = venue_address
        narrative = detail.select_one('.split-right > .content-styling')
        if narrative:
            for controls in narrative.select('form, .quantity, #paypal-button-container'):
                controls.decompose()
        narrative = description(str(narrative) if narrative else '')
        start, end = datetime.combine(day, displayed[3]), None
        # A labeled arrival time is distinct from the publisher's stated start.
        # Only the exact observed wording permits this correction, and both
        # clocks must agree with the listing/detail arrival time.
        arrival = re.search(r'Please arrive at (\d{1,2}(?:[.:]\d{2})?[ap]m) for a '
                            r'(\d{1,2}(?:[.:]\d{2})?[ap]m) start\.', narrative, re.I)
        if arrival:
            def clock(value):
                value = value.replace('.', ':').upper()
                return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()
            begins = datetime.combine(day, clock(arrival[2]))
            if clock(arrival[1]) != displayed[3] or not start <= begins <= start + timedelta(hours=1):
                raise ValueError('wine_event_schedule_conflict')
            start = begins
            if 'The tasting lasts two hours' in narrative:
                end = start + timedelta(hours=2)
        row = record(title, start, end, venue, street, 'Cambridge', url, url, 'Food & Coffee', tz=LONDON.key)
        if row:
            row['description'] = narrative
            yield row


def collect(source, fetch, *, deadline_at=None, listing=None):
    url = source.get('feed_url')
    if url not in URLS or source.get('source_key') != source_key(url):
        raise ValueError('unregistered_html_source')
    deadline_check(deadline_at)
    if url == battersea_bloem.URL:
        return battersea_bloem.collect(source, fetch, deadline_at=deadline_at, listing=listing)
    if url == sustainable_ow.URL:
        return sustainable_ow.collect(source, fetch, deadline_at=deadline_at, listing=listing)
    soup = BeautifulSoup(listing if listing is not None else fetch(url, 'text/html'), 'html.parser')
    today = calendar_anchor(datetime.now(LONDON)).date()
    if url == WINE:
        rows = wine_rows(soup, fetch, today, deadline_at)
    elif url == eventin_listing.URL:
        rows = eventin_listing.rows(soup, fetch, today, deadline_at)
    elif url == designmynight_listing.URL:
        rows = designmynight_listing.rows(soup, fetch, today, deadline_at)
    else:
        rows = wix_list_rows(soup, url, today)
    result = {}
    for row in rows:
        row['timezone'] = LONDON.key
        key = (row['id'], row['starts_at'])
        if key in result and result[key] != row:
            raise ValueError('conflicting_event_occurrence')
        result[key] = row
    if not result:
        raise ValueError('no_extractable_events')
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))
