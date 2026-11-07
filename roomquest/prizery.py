"""Collect explicitly timed public programs from The Prizery."""
from datetime import datetime, timedelta
import re
from time import monotonic
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach

SOURCE_KEY = 'prizery_va'
SOURCE_URL = 'https://prizery.org/events/'
TIMEZONE = 'America/New_York'
VENUE = 'The Prizery'
ADDRESS = '700 Bruce Street, South Boston, VA 24592'
MAX_DETAILS = 12
EVENT_URL = r'https://prizery\.org/(?!events/)[a-z0-9]+(?:-[a-z0-9]+)*/'
PHOTO_URL = r'https://prizery\.org/site/wp-content/uploads/20[0-9]{2}/[01][0-9]/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)'
_SINGLE = re.compile(
    r'([A-Za-z]+), ([A-Za-z]+ [0-9]{1,2})(?:, (20[0-9]{2}))? at '
    r'([0-9]{1,2}:[0-9]{2} [ap]m)(?:, Tickets \$[0-9]+(?:\.[0-9]{2})?)?\.?', re.I)
_RECEPTION = re.compile(
    r'Opening reception ([A-Za-z]+ [0-9]{1,2}), from '
    r'([0-9]{1,2}(?::[0-9]{2})?)-([0-9]{1,2}:[0-9]{2}) ([ap]m)\. '
    r'Show runs through ([A-Za-z]+ [0-9]{1,2}), (20[0-9]{2})\. Free to the public\.', re.I)


def _local(day, clock):
    if ':' not in clock:
        clock = clock.replace(' ', ':00 ', 1)
    wall = datetime.combine(day, datetime.strptime(clock.upper(), '%I:%M %p').time())
    return timestamp(wall, TIMEZONE)


def _schedule(excerpt, published):
    if match := _SINGLE.fullmatch(excerpt):
        weekday, month_day, year, clock = match.groups()
        # Posts without a printed year must have a matching weekday and be
        # close to the publisher's own dated announcement.
        years = (int(year),) if year else (published.year, published.year + 1)
        days = [datetime.strptime(f'{month_day} {y}', '%B %d %Y').date() for y in years]
        days = [d for d in days if d.strftime('%A').casefold() == weekday.casefold()
                and (year or timedelta(0) <= d - published.date() <= timedelta(days=180))]
        if len(days) == 1:
            return _local(days[0], clock), None, False
    if match := _RECEPTION.fullmatch(excerpt):
        month_day, start, end, meridiem, closing, year = match.groups()
        day = datetime.strptime(f'{month_day} {year}', '%B %d %Y').date()
        close_day = datetime.strptime(f'{closing} {year}', '%B %d %Y').date()
        starts, ends = _local(day, f'{start} {meridiem}'), _local(day, f'{end} {meridiem}')
        if starts < ends and day <= close_day:
            return starts, ends, True
    return None


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone'),
        source.get('kind'), source.get('platform_adapter')) != (
            SOURCE_KEY, SOURCE_URL, TIMEZONE, 'html', 'html'):
        raise ValueError('unregistered_prizery_calendar')
    listing = BeautifulSoup(fetch(SOURCE_URL, 'text/html'), 'html.parser')
    if listing.select_one('[rel="next"], .elementor-pagination, .e-load-more-anchor'):
        raise ValueError('pagination_requires_review')
    cards = listing.select('article.category-events')
    if not 1 <= len(cards) <= MAX_DETAILS:
        raise ValueError('prizery_listing_count_unverified')
    rows, seen = [], set()
    for card in cards:
        link = card.select_one('.elementor-post__title a[href]')
        summary = card.select_one('.elementor-post__excerpt')
        if not link or not summary or not re.fullmatch(EVENT_URL, link['href']) or link['href'] in seen:
            raise ValueError('prizery_event_identity_unverified')
        url = link['href']
        seen.add(url)
        excerpt = summary.get_text(' ', strip=True)
        # An exhibition range or theatre run supplies no individual showtime.
        if not (_SINGLE.fullmatch(excerpt) or _RECEPTION.fullmatch(excerpt)):
            continue
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        canonical = detail.select_one('link[rel="canonical"]')
        heading = detail.select_one('h1')
        published = detail.select_one('meta[property="article:published_time"]')
        title = link.get_text(' ', strip=True)
        if (not canonical or canonical.get('href') != url or not heading
                or heading.get_text(' ', strip=True) != title or not published
                or excerpt not in detail.get_text(' ', strip=True)):
            raise ValueError('prizery_event_detail_mismatch')
        announcement = timestamp(published['content']).astimezone(ZoneInfo(TIMEZONE))
        schedule = _schedule(excerpt, announcement)
        if not schedule:
            continue
        starts, ends, reception = schedule
        if re.search(r'\b(cancelled|canceled|postponed|virtual|off-site)\b', detail.get_text(' ', strip=True), re.I):
            continue
        if reception:
            title += ' — Opening Reception'
        row = record(title, starts, ends, VENUE, ADDRESS, 'South Boston', url, url,
                     'Arts & Culture' if reception else '')
        if row:
            row['description'] = excerpt
            row['attendance_mode'] = 'in_person'
            image = detail.select_one('meta[property="og:image"]')
            attach(row, SOURCE_KEY, candidate=image.get('content') if image else None)
            rows.append(row)
    return rows
