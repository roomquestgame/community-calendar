"""Reviewed Gulf Coast venue calendars, read through the guarded transport."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import attach

ZONE = 'America/Chicago'
TIPITINAS = 'gulf_tipitinas_la'
WWII = 'gulf_national_wwii_museum_la'
SOURCES = {
    TIPITINAS: 'https://tipitinas.com/calendar/',
    WWII: 'https://www.nationalww2museum.org/events/events-calendar',
}
VENUES = {
    TIPITINAS: ("Tipitina's", '501 Napoleon Ave, New Orleans, LA 70115'),
    WWII: ('The National WWII Museum', '945 Magazine Street, New Orleans, LA 70130'),
}


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def allowed_hosts(key):
    return (urlsplit(SOURCES[key]).hostname,)


def event_url(key, value):
    if not isinstance(value, str):
        return False
    patterns = {
        TIPITINAS: r'https://tipitinas[.]com/event/[1-9][0-9]{3,12}/[a-z0-9-]+/?',
        WWII: r'https://www[.]nationalww2museum[.]org/events-programs/events/[a-z0-9-]+/?',
    }
    return bool(re.fullmatch(patterns.get(key, r'(?!)'), value))


def photo_url(key, value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.netloc != p.hostname or p.fragment:
            return None
        if re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|placeholder)(?:[-_.]|$)', p.path, re.I):
            return None
        if key == TIPITINAS and p.hostname == 'i.ticketweb.com':
            if (re.fullmatch(r'/i/(?:[0-9]{2}/){4}[0-9]{2}_(?:Listings|Original)[.]jpg', p.path)
                    and (not p.query or re.fullmatch(r'v=[0-9]+', p.query))):
                return value
        if key == WWII and p.hostname == 'www.nationalww2museum.org':
            if (re.fullmatch(r'/sites/default/files/(?:styles/[a-z_]+/public/)?20[0-9]{2}-[01][0-9]/[^/]+[.](?:jpg|jpeg|png|webp)', p.path, re.I)
                    and (not p.query or re.fullmatch(r'h=[a-f0-9]+(?:&itok=[A-Za-z0-9_-]+)?', p.query))):
                return value
    except ValueError:
        pass
    return None


def _clock(day, value):
    value = re.sub(r'\s+', '', value).upper()
    fmt = '%I:%M%p' if ':' in value else '%I%p'
    return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)


def _row(key, title, start, end, href, identity, description, category, image, facts):
    if cancelled(title, description):
        return None
    venue, street = VENUES[key]
    item = record(title, start, end, venue, street, 'New Orleans', href, identity, category, tz=ZONE)
    if item:
        item.update(description=description[:2000], timezone=ZONE, attendance_mode='in_person',
                    publisher_categories=[category] if category else [])
        attach(item, key, facts=facts, candidate=image)
    return item


def _tipitinas(payload):
    soup = BeautifulSoup(payload, 'html.parser')
    addresses = soup.select('a[href="https://tipitinas.com/location/"]')
    if not any(_text(node) == VENUES[TIPITINAS][1] for node in addresses):
        raise ValueError('tipitinas_venue_unverified')
    listing = soup.select_one('.tw-plugin-upcoming-event-list')
    cards = listing.select('.tw-section') if listing else []
    if not listing or not 1 <= len(cards) <= 150:
        raise ValueError('tipitinas_calendar_unverified')
    seen = set()
    for card in cards:
        link = card.select_one('.tw-name a[href]')
        if not link or not event_url(TIPITINAS, link['href']):
            raise ValueError('tipitinas_event_identity_missing')
        if re.search(r'\b(?:two|three|[2-9])[- ]night pass\b',
                     _text(card.select_one('.tw-prefix-text')), re.I):
            continue  # A ticket bundle is not a separate attended occurrence.
        # Mobile and desktop copies must agree; doors are not the show time.
        dates = {_text(n) for n in card.select('.tw-event-date')}
        times = {_text(n) for n in card.select('.tw-event-time')}
        titles = {_text(n) for n in card.select('.tw-name a')}
        if len(dates) != 1 or len(times) != 1 or len(titles) != 1:
            raise ValueError('tipitinas_event_schedule_conflict')
        day = datetime.strptime(next(iter(dates)), '%b %d, %Y').date()
        start = _clock(day, next(iter(times)))
        identity = urlsplit(link['href']).path.split('/')[2]
        occurrence = (identity, start.isoformat())
        if occurrence in seen:
            continue
        seen.add(occurrence)
        title = _text(link)
        age = _text(card.select_one('.tw-age-restriction'))
        support = _text(card.select_one('.tw-prefix-text'))
        doors = _text(card.select_one('.tw-event-door-time'))
        description = ' '.join(part for part in (support, age, 'Doors: ' + doors if doors else '') if part)
        image = card.select_one('.tw-image img[src]')
        item = _row(TIPITINAS, title, start, None, link['href'], identity, description, 'Music',
                    image['src'] if image else None,
                    {'audience': age})
        if item:
            yield item


def _museum(fetch, deadline_at, now):
    from roomquest.preview_worker import LOOKAHEAD_DAYS
    horizon = now + timedelta(days=LOOKAHEAD_DAYS)
    base = SOURCES[WWII]
    href = base + '?field_offsite_value=1'
    visited = set()
    seen = set()
    previous_day = None
    # The publisher's location filter explicitly selects the museum campus.
    # Virtual/date-only cards are still excluded, including its fitness challenge.
    for page in range(10):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if href in visited:
            raise ValueError('wwii_pagination_loop')
        visited.add(href)
        soup = BeautifulSoup(fetch(href, 'text/html'), 'html.parser')
        canonical = soup.select_one('link[rel="canonical"]')
        root = soup.select_one('.views-events-calendar')
        checked = root.select_one('input[name="field_offsite_value"][checked]') if root else None
        if (not canonical or canonical.get('href') != base or not checked or checked.get('value') != '1'
                or VENUES[WWII][1] not in _text(soup)):
            raise ValueError('wwii_location_filter_unverified')
        cards = root.select('article[about]')
        if len(cards) > 10 or (not cards and not root.select_one('.view-empty')):
            raise ValueError('wwii_calendar_unverified')
        days = []
        for card in cards:
            link = card.select_one('.f--title a[href]')
            url = urljoin(base, link['href']) if link else ''
            if not event_url(WWII, url) or urljoin(base, card['about']) != url:
                raise ValueError('wwii_event_identity_missing')
            schedule = _text(card.select_one('.f--date'))
            date_match = re.match(r'(\d{2}/\d{2}/20\d{2})', schedule)
            if not date_match:
                raise ValueError('wwii_event_date_missing')
            day = datetime.strptime(date_match[1], '%m/%d/%Y').date()
            if previous_day and day < previous_day:
                raise ValueError('wwii_calendar_order_unverified')
            previous_day = day
            days.append(day)
            match = re.fullmatch(r'\d{2}/\d{2}/20\d{2}\s*\|\s*(\d{1,2}:\d{2}\s*[AP]M)\s*[-–]\s*(\d{1,2}:\d{2}\s*[AP]M)', schedule, re.I)
            if not match:
                continue  # Date spans establish neither admission sessions nor continuous opening.
            title = _text(link)
            description = _text(card.select_one('.f--desc'))
            category = _text(card.select_one('.field--name-field-program-type'))
            if re.search(r'\b(?:virtual|webinar|online|off[- ]site|livestream|zoom)\b', ' '.join((title, description, category)), re.I):
                continue
            start, end = _clock(day, match[1]), _clock(day, match[2])
            if end <= start:
                raise ValueError('wwii_invalid_event_end')
            identity = card.get('id', '')
            if not re.fullmatch(r'node-[1-9][0-9]*', identity):
                raise ValueError('wwii_event_id_missing')
            occurrence = (identity, start.isoformat())
            if occurrence in seen:
                continue
            seen.add(occurrence)
            image = card.select_one('.col-image img[data-src]')
            item = _row(WWII, title, start, end, url, identity, description, category,
                        urljoin(base, image['data-src']) if image else None,
                        {'meeting_location': VENUES[WWII][0]})
            if item:
                yield item
        if days != sorted(days):
            raise ValueError('wwii_calendar_order_unverified')
        next_link = root.select_one('a[rel="next"]')
        if not next_link or (days and max(days) > horizon.date()):
            return
        next_url = urljoin(base, next_link.get('href', ''))
        p = urlsplit(next_url)
        if (p.scheme != 'https' or p.netloc != 'www.nationalww2museum.org'
                or p.path != urlsplit(base).path or p.fragment
                or parse_qs(p.query) != {'field_offsite_value': ['1'], 'page': [str(page + 1)]}):
            raise ValueError('wwii_pagination_unverified')
        href = next_url
    raise ValueError('wwii_page_budget_exceeded')


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if (key not in SOURCES or source.get('feed_url') != SOURCES[key]
            or source.get('kind') != 'html' or source.get('platform_adapter') != 'html'
            or source.get('timezone') != ZONE):
        raise ValueError('gulf_venue_source_unverified')
    if key == TIPITINAS:
        return list(_tipitinas(fetch(SOURCES[key], 'text/html')))
    return list(_museum(fetch, deadline_at, now or datetime.now(timezone.utc)))
