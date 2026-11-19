"""Santa Cruz Symphony official season calendar; exact published January performances.

The season page contains wall-clock concert schedules and duration (unlike
its thin JSON-LD). Venue addresses are verified on the symphony's *own*
Civic/Mello pages each preview. No invented GEO or image licence.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record

KEY = 'santa_cruz_symphony_season_ca'
URL = 'https://santacruzsymphony.org/2026-27-concert-season-overview'
ZONE = 'America/Los_Angeles'
SOURCES = {KEY: (URL, 'html', 'html')}
ALLOWED_HOSTS = {KEY: ('santacruzsymphony.org',)}
MAX_RECORDS = 4
MAX_DESCRIPTION = 12000
HOST_URLS = {
    'Civic Auditorium': (
        'https://santacruzsymphony.org/civicseatingmap',
        'Santa Cruz Civic Auditorium',
        '307 Church St., Santa Cruz, CA 95060',
        r'307\s+Church\s+St\.,?\s+Santa\s+Cruz,\s+CA\s+95060',
        'Santa Cruz',
    ),
    'Henry J. Mello Center': (
        'https://santacruzsymphony.org/venue-map-mello',
        'Henry J. Mello Center',
        '250 E. Beach St., Watsonville, CA 95076',
        r'250\s+E\.\s+Beach\s+St\.\s+at\s+Lincoln,\s+Watsonville,\s+CA\s+95076',
        'Watsonville',
    ),
}
CONCERT = re.compile(
    r'(SATURDAY|SUNDAY),\s+January\s+(\d{1,2})\s+at\s+'
    r'(\d{1,2}:\d{2})\s*(AM|PM),\s*'
    r'(Civic Auditorium|Henry J\. Mello Center)\s+'
    r'Doors\s+open\s+at\s+.*?Concert\s+duration:\s*'
    r'(\d+)\s+hour(?:s)?\s+(\d+)\s+minutes',
    re.I,
)

def event_url(value):
    return value == URL

def _text(html):
    if not isinstance(html, str) or len(html) > 1_500_000:
        raise ValueError('symphony_invalid_html')
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.body:
        raise ValueError('symphony_invalid_html')
    return soup.body.get_text(' ', strip=True)

def collect(source, fetch, *, now=None, deadline_at=None):
    if (source.get('source_key') != KEY or
        (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != SOURCES[KEY] or
        source.get('timezone') != ZONE):
        raise ValueError('symphony_unregistered_source')
    t = _text(fetch(URL, 'text/html'))
    if '2026-27 Concert Season Overview' not in t:
        raise ValueError('symphony_season_changed')
    start = t.find('Classical Series Concert 3 RACHMANINOFF’S 3RD')
    end = t.find('Classical Series Concert 4', start)
    if start == -1 or end <= start:
        raise ValueError('symphony_calendar_format_changed')
    segment = t[start:end]
    programme = segment.split('FEATURED SOLOIST')[0].strip()
    if not all(x in programme for x in (
        'Jaron Lanier: Singularity Variations',
        'Sergei Rachmaninoff:',
        'Piano Concerto No. 3',
    )):
        raise ValueError('symphony_programme_changed')
    summary = re.search(r'Our January concerts feature\s+(.{40,550}?)\.', t[:start])
    if not summary:
        raise ValueError('symphony_description_missing')
    narrative = 'Our January concerts feature ' + summary.group(1) + '. ' + programme
    if len(narrative) < 120 or len(narrative) > MAX_DESCRIPTION:
        raise ValueError('symphony_description_length')
    matches = list(CONCERT.finditer(segment))
    if len(matches) != 2:
        raise ValueError('symphony_concert_schedule_changed')
    now = now or datetime.now(timezone.utc)
    verified = {}
    rows = []
    for m in matches:
        weekday, day, clock, ampm, venue_key, hours, minutes = m.groups()
        if (day, weekday.upper()) not in (('16','SATURDAY'),('17','SUNDAY')):
            raise ValueError('symphony_date_changed')
        when = datetime.strptime(f'2027-01-{int(day):02d} {clock} {ampm.upper()}',
                                 '%Y-%m-%d %I:%M %p').replace(tzinfo=ZoneInfo(ZONE))
        if when.strftime('%A').upper() != weekday.upper():
            raise ValueError('symphony_weekday_mismatch')
        end_when = when + timedelta(hours=int(hours), minutes=int(minutes))
        if not (60 <= (end_when - when).total_seconds()/60 <= 240):
            raise ValueError('symphony_duration_invalid')
        if when.astimezone(timezone.utc) < now - timedelta(hours=3) or when.astimezone(timezone.utc) > now + timedelta(days=65):
            continue
        official, venue, address, pattern, city = HOST_URLS[venue_key]
        if venue_key not in verified:
            place = _text(fetch(official, 'text/html'))
            if not re.search(pattern, place, re.I):
                raise ValueError('symphony_official_venue_address_changed')
            verified[venue_key] = True
        row = record('Rachmaninoff’s 3rd', when.isoformat(), end_when.isoformat(),
                     venue, address, city, URL, 'symphony-2027-01-'+day+'-'+venue_key.lower().replace(' ', '-'),
                     'Classical Series, Symphony, Live Music', None, None, ZONE,
                     retain_until_end=True)
        if row is None: continue
        row.update(description=narrative, timezone=ZONE,
                   publisher_categories=['Classical Series', 'Symphony', 'Live Music'],
                   location_provenance='symphony_official_venue_page',
                   location_evidence_url=official)
        from roomquest.publisher_evidence import attach
        rows.append(attach(row, KEY))
    return sorted(rows, key=lambda row: (row['starts_at'],row['id']))
