"""Collect dated public workshops from SOVA's own program page."""
from datetime import datetime
import re
from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach

KEY = 'sova_innovation_hub_va'
HOST = 'sovainnovationhub.com'
URL = f'https://{HOST}/ai-programs/ai-workshops-for-business/'
ZONE = 'America/New_York'
ADDRESS = '715 Wilborn Avenue, South Boston, VA 24592'
_CLOCK = r'(\d{1,2}:\d{2}\s*[ap]m)'
_SCHEDULE = re.compile(
    r'([A-Za-z]+ \d{1,2}, 20\d{2})\s*\|\s*'+_CLOCK+r'\s*[-–—]\s*'+_CLOCK+
    r'\s*\|\s*SOVA Innovation Hub(?:\s+or)?', re.I)


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split())


def _clock(day, clock):
    value = datetime.strptime(re.sub(r'\s+', '', clock).upper(), '%I:%M%p').time()
    return timestamp(datetime.combine(day, value), ZONE)


def collect(source, fetch, *, deadline_at=None):
    if (source.get('source_key'), source.get('feed_url'), source.get('timezone'),
        source.get('kind'), source.get('platform_adapter')) != (KEY, URL, ZONE, 'html', 'html'):
        raise ValueError('unregistered_sova_workshops')
    page = BeautifulSoup(fetch(URL, 'text/html'), 'html.parser')
    canonical = page.select_one('link[rel="canonical"]')
    if not canonical or canonical.get('href') != URL or not re.search(
        r'715 Wilborn Avenue\s+South Boston, VA 24592', _text(page)):
        raise ValueError('sova_workshop_publisher_unverified')
    headings = [h for h in page.select('.et_pb_text_inner h3') if re.match(r'AI for Business:', _text(h), re.I)]
    if not 1 <= len(headings) <= 16:
        raise ValueError('sova_workshop_catalogue_unverified')
    results, seen = [], set()
    for heading in headings:
        title = _text(heading)
        column = heading.find_parent(class_='et_pb_column')
        if column is None or len(column.select('h3')) != 1:
            raise ValueError('sova_workshop_group_unverified')
        description = _text(column)
        if re.search(r'\b(cancelled|canceled|postponed|virtual only|online only)\b', description, re.I):
            continue
        # The publisher uses either separate paragraphs or a single paragraph
        # with a line break between alternative sessions.
        group = heading.parent
        schedules = _SCHEDULE.findall(_text(group))
        if not schedules:
            continue
        identity = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        for day_text, first, last in schedules:
            day = datetime.strptime(day_text, '%B %d, %Y').date()
            starts, ends = _clock(day, first), _clock(day, last)
            if ends <= starts or (identity, starts) in seen:
                raise ValueError('sova_workshop_schedule_conflict')
            seen.add((identity, starts))
            row = record(title, starts, ends, 'SOVA Innovation Hub', ADDRESS, 'South Boston',
                         URL, identity, 'Workshops')
            if row:
                row.update(description=description[:3000], attendance_mode='in_person')
                attach(row, KEY)
                results.append(row)
    return results
