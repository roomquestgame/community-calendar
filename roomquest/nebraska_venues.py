"""Public schedules for three reviewed Bellevue-area venues."""
from datetime import date, datetime
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import attach

ZONE = 'America/Chicago'
PINT = 'pint_nine_la_vista_ne'
KROS = 'kros_strain_la_vista_ne'
FROSTY = 'falconwood_frosty_nights_ne'
SOURCES = {
    PINT: 'https://pintninebrewing.com/events',
    KROS: 'https://krosstrainbrewing.com/events/',
    FROSTY: 'https://christmasomaha.com/hours/',
}
EVENT_URLS = {
    PINT: r'https://pintninebrewing[.]com/events/(?:20\d{2}/\d{1,2}/\d{1,2}/)?[a-z0-9-]+',
    KROS: r'https://krosstrainbrewing[.]com/events/[a-z0-9-]+/',
    FROSTY: re.escape(SOURCES[FROSTY]),
}
PHOTO_URLS = {
    PINT: r'https://images[.]squarespace-cdn[.]com/content/v1/58d7c6c69f7456928ccd343a/[A-Za-z0-9-]+/[A-Za-z0-9_+.-]+[.](?:jpe?g|png|webp)',
    KROS: r'https://krosstrainbrewing[.]com/wp-content/uploads/20\d{2}/[01]\d/[A-Za-z0-9_.-]+[.](?:jpe?g|png|webp)',
}
VENUES = {
    PINT: ('Pint Nine Brewing Company', '10411 Portal Road Ste 104, La Vista, NE 68128', 'La Vista'),
    KROS: ('Kros Strain Brewing', '10411 Portal Road Ste 102, La Vista, NE 68128', 'La Vista'),
    FROSTY: ('Falconwood Park', '905 Allied Road, Bellevue, NE 68123', 'Bellevue'),
}


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def _page(payload, url):
    soup = BeautifulSoup(payload, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"]')
    if not canonical or canonical.get('href') != url:
        raise ValueError('nebraska_venue_publisher_unverified')
    return soup


def _clock(day, value):
    clock = re.sub(r'\s+', '', value).upper()
    fmt = '%I:%M%p' if ':' in clock else '%I%p'
    return timestamp(datetime.combine(day, datetime.strptime(clock, fmt).time()), ZONE)


def _row(key, title, starts, ends, url, identity, description='', image=None):
    if cancelled(title, description):
        return None
    if ends and ends <= starts:
        raise ValueError('nebraska_venue_invalid_schedule')
    venue, address, city = VENUES[key]
    row = record(title, starts, ends, venue, address, city, url, identity, tz=ZONE)
    if row:
        row.update(description=description[:2000], attendance_mode='in_person', timezone=ZONE)
        attach(row, key, candidate=image)
    return row


def _pint(soup):
    cards = soup.select('article.eventlist-event--upcoming')
    if not cards and not soup.select_one('.eventlist'):
        raise ValueError('pint_nine_calendar_unverified')
    for card in cards:
        link = card.select_one('a.eventlist-title-link')
        date_node = card.select_one('time.event-date[datetime]')
        start_node = card.select_one('time.event-time-localized-start[datetime]')
        end_node = card.select_one('time.event-time-localized-end[datetime]')
        venue = card.select_one('.eventlist-meta-address')
        map_link = venue.select_one('a[href]') if venue else None
        if (not link or not date_node or not start_node or not end_node or not map_link
                or not _text(venue).startswith(VENUES[PINT][0])
                or not re.search(r'10411 Portal (?:Road|Rd) Ste 104 (?:La Vista|Papillion), (?:NE|Nebraska),? 68128',
                                 map_link['href'], re.I)):
            continue
        href = urljoin(SOURCES[PINT], link['href'])
        if not re.fullmatch(EVENT_URLS[PINT], href):
            continue
        start_day = date.fromisoformat(start_node['datetime'])
        end_day = date.fromisoformat(end_node['datetime'])
        if start_day != date.fromisoformat(date_node['datetime']):
            raise ValueError('pint_nine_schedule_conflict')
        img = card.select_one('img.eventlist-thumbnail')
        yield _row(PINT, _text(link), _clock(start_day, _text(start_node)), _clock(end_day, _text(end_node)),
                   href, urlsplit(href).path, _text(card.select_one('.eventlist-description')),
                   img.get('src') if img else None)


def _kros(soup, fetch):
    cards = soup.select('.section_home_upcoming_events .section_home_upcoming_event_item')
    if not soup.select_one('.section_events_archive_wrapper') or len(cards) > 24:
        raise ValueError('kros_strain_calendar_unverified')
    for card in cards:
        if _text(card.select_one('.location')) != 'La Vista':
            continue
        label = card.select_one('a[href] > h4')
        if not label:
            raise ValueError('kros_strain_event_link_missing')
        href = label.parent['href']
        if not re.fullmatch(EVENT_URLS[KROS], href):
            continue
        day = datetime.strptime(_text(card.select_one('.date')), '%A, %B %d, %Y').date()
        starts = _clock(day, _text(card.select_one('.time')))
        if day < datetime.now(starts.tzinfo).date():
            continue
        detail = _page(fetch(href, 'text/html'), href).select_one('.single_event_wrapper')
        if (not detail or _text(detail.select_one('.location')) != 'La Vista'
                or _text(detail.select_one('h2')) != _text(label)
                or datetime.strptime(_text(detail.select_one('.date')), '%B %d, %Y').date() != day):
            raise ValueError('kros_strain_event_identity_conflict')
        times = re.split(r'\s+[-–—]\s+', _text(detail.select_one('.time')))
        if _clock(day, times[0]) != starts or len(times) > 2:
            raise ValueError('kros_strain_schedule_conflict')
        ends = _clock(day, times[1]) if len(times) == 2 else None
        img = card.select_one('.section_home_upcoming_event_item_image_wrapper img')
        yield _row(KROS, _text(label), starts, ends, href, urlsplit(href).path,
                   _text(detail.select_one('.rte')), img.get('src') if img else None)


def _frosty(soup):
    schedule = soup.select_one('.fn-nights')
    if not schedule or '905 Allied Road' not in _text(soup):
        raise ValueError('falconwood_schedule_unverified')
    count = re.search(r'All (\d+) nights', _text(soup), re.I)
    season = re.search(r'Frosty Nights (20\d{2}) Hours', _text(soup.select_one('h1')))
    nights = schedule.select('.month li')
    if not count or not season or len(nights) != int(count[1]) or not 1 <= len(nights) <= 60:
        raise ValueError('falconwood_schedule_unverified')
    visible_weather_closure = any(
        not any({'elementor-hidden-desktop', 'elementor-hidden-tablet', 'elementor-hidden-mobile'}
                .issubset(parent.get('class', [])) for parent in notice.parents)
        for notice in soup.find_all(string=re.compile(r'WEATHER CLOSURE:.*Closed tonight', re.I))
    )
    seen = set()
    for night in nights:
        day_node = night.find('span', recursive=False)
        hours = night.find('b', recursive=False)
        if not day_node or not hours:
            raise ValueError('falconwood_schedule_unverified')
        day_text = ' '.join(s.strip() for s in day_node.find_all(string=True, recursive=False)).strip()
        day = datetime.strptime(f'{day_text} {season[1]}', '%a, %b %d %Y').date()
        if day in seen or not day_text.startswith(day.strftime('%a') + ','):
            raise ValueError('falconwood_schedule_conflict')
        seen.add(day)
        if ('closed' in _text(night).casefold()
                or visible_weather_closure and day == datetime.now(ZoneInfo(ZONE)).date()):
            continue
        first, last = _text(hours).split(' to ')
        yield _row(FROSTY, 'Falconwood Frosty Nights', _clock(day, first), _clock(day, last),
                   SOURCES[FROSTY], day.isoformat(), 'Walk-through Christmas lights and Christmas village.')


def collect(source, fetch, *, deadline_at=None):
    key = source.get('source_key')
    url = SOURCES.get(key)
    if not url or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
                   source.get('timezone')) != (url, 'html', 'html', ZONE):
        raise ValueError('unregistered_nebraska_venue')
    soup = _page(fetch(url, 'text/html'), url)
    rows = _kros(soup, fetch) if key == KROS else {PINT: _pint, FROSTY: _frosty}[key](soup)
    return [row for row in rows if row]
