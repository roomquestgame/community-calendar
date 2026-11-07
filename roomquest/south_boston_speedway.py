"""Confirm timed race links against South Boston Speedway's current schedule."""
from datetime import datetime
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach

KEY = 'south_boston_speedway_va'
HOST = 'www.southbostonspeedway.com'
URL = f'https://{HOST}/schedule'
ZONE = 'America/New_York'
VENUE = 'South Boston Speedway'
ADDRESS = '1188 James D. Hagood Highway, South Boston, VA 24592'
EVENT_URL = re.compile(r'https://www[.]southbostonspeedway[.]com/(?!schedule$)[a-z0-9]+(?:-[a-z0-9]+)*')
PHOTO_URL = re.compile(
    r'https://static[.]wixstatic[.]com/media/(18b5ae_[a-f0-9]{32}(?:~|%7E)mv2[.](?:jpe?g|png|webp))'
    r'(?:/v1/fill/[A-Za-z0-9_,]+/\1)?', re.I)
_FLAG = re.compile(r'GREEN FLAG:\s*(\d{1,2})(?::(\d{2}))?\s*([AP]M)', re.I)
_DAY = re.compile(r'([A-Z]+), ([A-Z]+ \d{1,2})', re.I)


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split())


def _canonical(page):
    tag = page.select_one('link[rel="canonical"]')
    return tag.get('href') if tag else None


def _flag(match):
    return datetime.strptime(f'{match[1]}:{match[2] or "00"} {match[3].upper()}', '%I:%M %p').time()


def _listed_races(page, year):
    races = {}
    for anchor in page.select('a[href]'):
        if _text(anchor).upper() != 'EVENT INFO':
            continue
        url = urljoin(URL, anchor['href'])
        if not EVENT_URL.fullmatch(url):
            raise ValueError('speedway_race_link_unverified')
        for parent in list(anchor.parents)[:10]:
            headings = [_text(h) for h in parent.select('h2')]
            days = [m for label in headings if (m := _DAY.fullmatch(label))]
            flags = [m for label in headings if (m := _FLAG.fullmatch(label))]
            if len(days) > 1 or len(flags) > 1:
                break
            if len(days) == len(flags) == 1:
                day = datetime.strptime(f'{days[0][2].title()} {year}', '%B %d %Y').date()
                if day.strftime('%A').casefold() != days[0][1].casefold():
                    raise ValueError('speedway_listing_weekday_mismatch')
                start = timestamp(datetime.combine(day, _flag(flags[0])), ZONE)
                if url in races and races[url] != start:
                    raise ValueError('speedway_race_schedule_conflict')
                races[url] = start
                break
    return races


def _race(payload, url, start):
    page = BeautifulSoup(payload, 'html.parser')
    title = _text(page.title) if page.title else ''
    match = re.fullmatch(r'(.+?)\s*\|\s*([A-Za-z]+ \d{1,2}, 20\d{2})', title)
    if not match or _canonical(page) != url:
        raise ValueError('speedway_race_identity_unverified')
    detail_day = datetime.strptime(match[2], '%B %d, %Y').date()
    flags = {_flag(m) for h in page.select('h2,h3,h4,h5,p') if (m := _FLAG.fullmatch(_text(h)))}
    address = _text(page.select_one('footer')) if page.select_one('footer') else _text(page)
    if (detail_day != start.date() or flags != {start.time()} or
        '1188 James D. Hagood Highway South Boston, VA 24592' not in address):
        raise ValueError('speedway_race_detail_mismatch')
    if re.search(r'\b(?:postponed|cancelled|canceled)\b', _text(page.select_one('main') or page), re.I):
        return None
    row = record(match[1], start, None, VENUE, ADDRESS, 'South Boston', url, url, 'Motorsports')
    if row:
        description = page.select_one('meta[name="description"]')
        row['description'] = description.get('content', '')[:2000] if description else ''
        row['attendance_mode'] = 'in_person'
        image = page.select_one('meta[property="og:image"]')
        attach(row, KEY, candidate=image.get('content') if image else None)
    return row


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone'),
        source.get('kind'), source.get('platform_adapter')) != (KEY, URL, ZONE, 'html', 'html'):
        raise ValueError('unregistered_south_boston_speedway')
    page = BeautifulSoup(fetch(URL, 'text/html'), 'html.parser')
    years = {m[1] for h in page.select('h1') if (m := re.fullmatch(r'FULL (20\d{2}) SCHEDULE', _text(h)))}
    if _canonical(page) != URL or len(years) != 1:
        raise ValueError('speedway_current_schedule_unverified')
    races = _listed_races(page, next(iter(years)))
    if len(races) > 20:
        raise ValueError('speedway_detail_limit')
    if not races and any(_text(a).upper() == 'EVENT INFO' for a in page.select('a[href]')):
        raise ValueError('speedway_race_listing_unverified')
    result = []
    for url, start in sorted(races.items(), key=lambda race: race[1]):
        if start <= datetime.now(start.tzinfo):
            continue
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        if row := _race(fetch(url, 'text/html'), url, start):
            result.append(row)
    return result
