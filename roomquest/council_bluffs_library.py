"""Read published LibraryCalendar programs from a bounded upcoming list."""
from datetime import datetime, timedelta, timezone
import re
from time import monotonic
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import attach, optional_description

KEY = 'council_bluffs_public_library_ia'
HOST = 'www.councilbluffslibrary.org'
URL = f'https://{HOST}/events/upcoming'
VENUE = 'Council Bluffs Public Library'
ADDRESS = '400 Willow Ave, Council Bluffs, IA 51503'
TIMEZONE = 'America/Chicago'
MAX_PAGES = 10
_EVENT_PATH = re.compile(r'/event/[a-z0-9-]+-([1-9][0-9]*)')
_TIME_RANGE = re.compile(r'(\d{1,2}:\d{2}[ap]m)\s*[–—-]\s*(\d{1,2}:\d{2}[ap]m)', re.I)


def _text(node, selector):
    tag = node.select_one(selector)
    return plain(tag.get_text(' ', strip=True)) if tag else ''


def _date(card):
    parts = [_text(card, '.lc-date-icon__item--' + suffix) for suffix in ('month', 'day', 'year')]
    if not all(parts):
        raise ValueError('library_calendar_date_missing')
    return datetime.strptime(' '.join(parts), '%b %d %Y').date()


def _program(card, day, now):
    branch = _text(card, '.lc-event__branch').removeprefix('Library Branch: ').strip()
    room = _text(card, '.lc-event__room').removeprefix('Room: ').strip()
    topics = [plain(tag.get_text(' ', strip=True)) for tag in card.select('.lc-event__program-types span')]
    if (branch != VENUE or not room or re.search(r'\boff[- ]?site\b', room, re.I)
            or not topics):
        return None
    times = _TIME_RANGE.fullmatch(_text(card, '.lc-event__info .lc-event-info-item--time'))
    if not times:
        return None
    zone = ZoneInfo(TIMEZONE)
    start, end = (datetime.combine(day, datetime.strptime(part.upper(), '%I:%M%p').time(), zone)
                  for part in times.groups())
    if end <= now or not start < end <= start + timedelta(hours=16):
        return None
    link = card.select_one('.lc-event__info a.lc-event__link[href]')
    identity = _EVENT_PATH.fullmatch(link['href']) if link else None
    if not identity:
        raise ValueError('library_calendar_event_identity')
    title = plain(link.get_text(' ', strip=True))
    description = _text(card, '.lc-event__body')[:2000]
    if not title or cancelled(title, description):
        return None
    url = urljoin(URL, link['href'])
    row = record(title, start.isoformat(), end.isoformat(), VENUE, ADDRESS, 'Council Bluffs',
                 url, identity[1], ', '.join(topics), tz=TIMEZONE, retain_until_end=True)
    if row:
        row.update(description=optional_description(KEY, row['id'], description),
                   publisher_categories=topics[:20])
        audience = _text(card, '.lc-event__age-groups').removeprefix('Age Group: ').strip()
        registration = ('Registration required' if card.select_one('.lc-event__registration-icon') else '')
        attach(row, KEY, facts={'meeting_location': room, 'audience': audience, 'registration': registration})
    return row


def collect(source, fetch, *, deadline_at, now=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (KEY, URL, 'html', 'html', TIMEZONE):
        raise ValueError('unregistered_council_bluffs_library')
    now = now or datetime.now(timezone.utc)
    cutoff = now.astimezone(ZoneInfo(TIMEZONE)).date() + timedelta(days=30)
    rows = {}
    url = URL
    previous_day = None
    for page in range(MAX_PAGES):
        if monotonic() >= deadline_at:
            raise ValueError('library_calendar_deadline')
        soup = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        cards = soup.select('article.node--type-lc-event.moderation-state--published')
        if not cards or len(cards) > 30:
            raise ValueError('library_calendar_page_shape')
        for card in cards:
            day = _date(card)
            if previous_day and day < previous_day:
                raise ValueError('library_calendar_order_changed')
            previous_day = day
            if day >= cutoff:
                return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
            if row := _program(card, day, now):
                identity = (row['id'], row['starts_at'])
                if identity in rows and rows[identity] != row:
                    raise ValueError('library_calendar_occurrence_conflict')
                rows[identity] = row
        next_page = soup.select_one('.pager__item--next a[href]')
        if next_page is None:
            return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
        if next_page['href'] != f'?page={page + 1}':
            raise ValueError('library_calendar_page_identity')
        url = URL + next_page['href']
    raise ValueError('library_calendar_page_limit')
