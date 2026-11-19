"""Direct first-party 2026 Sparky's Holiday Lights annual event schedule.

Only publisher-explicit day groups, clocks and the actual Fairgrounds street
are used. A coarse county/city GPS default is never substituted for the venue.
The separate Krampus promotion has no complete own narrative and is withheld.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from roomquest.event_description import description
from roomquest.mapsee_adapter import record

KEY = 'sparkys_holiday_lights_watsonville_ca'
URL = 'https://www.sparkysholidaylights.com/'
ZONE = 'America/Los_Angeles'
VENUE = 'Santa Cruz County Fairgrounds'
ADDRESS = '2601 East Lake Avenue, Watsonville, CA 95076'
SOURCES = {KEY: (URL, 'html', 'html')}
ALLOWED_HOSTS = {KEY: ('www.sparkysholidaylights.com',)}
MAX_RECORDS = 24
MAX_DESCRIPTION = 12000
DATE_LABEL = re.compile(r'^(November|December)\s+(.+)$', re.I)
DATE_RANGE = re.compile(r'^(\d{1,2})(?:st|nd|rd|th)?\s+(?:thru|through)\s+(\d{1,2})(?:st|nd|rd|th)?$', re.I)
DAY = re.compile(r'(?<!\d)(\d{1,2})(?:st|nd|rd|th)?(?!\d)', re.I)
CLOCK = re.compile(r'^(.+?)\s+(\d{1,2}(?::\d{2})?\s*[ap]m)\s*-\s*(\d{1,2}(?::\d{2})?\s*[ap]m)$', re.I)
YEAR = re.compile(r'Community-Display-Spaces-(20\d{2})', re.I)
MODES = {'drive-thru': ('Drive-Through', 'drive'),
         'walk-thru/heritage holiday fair': ('Walk-Through & Holiday Fair', 'walk')}


def event_url(value):
    return value == URL


def _local_time(date, clock):
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*([ap])m', clock.strip(), re.I)
    if not m:
        raise ValueError('sparkys_invalid_event_clock')
    hour, minute, suffix = int(m[1]), int(m[2] or 0), m[3].lower()
    if hour not in range(1, 13) or minute > 59:
        raise ValueError('sparkys_invalid_event_clock')
    hour = (hour % 12) + (12 if suffix == 'p' else 0)
    return datetime(date.year, date.month, date.day, hour, minute, tzinfo=ZoneInfo(ZONE))


def _dates(label, year):
    match = DATE_LABEL.fullmatch(' '.join(label.split()))
    if not match:
        raise ValueError('sparkys_invalid_date_group')
    month = 11 if match[1].lower() == 'november' else 12
    spec = match[2].strip()
    range_match = DATE_RANGE.fullmatch(spec)
    if range_match:
        start, end = int(range_match[1]), int(range_match[2])
        if end < start or end - start > 16:
            raise ValueError('sparkys_invalid_date_range')
        days = list(range(start, end + 1))
    elif re.fullmatch(r'[\d\s,&a-z]+', spec, re.I):
        days = [int(x) for x in DAY.findall(spec)]
        if not days or len(days) > 7 or len(days) != len(set(days)):
            raise ValueError('sparkys_invalid_date_group')
    else:
        raise ValueError('sparkys_invalid_date_group')
    from datetime import date
    try:
        return [date(year, month, day) for day in days]
    except ValueError as exc:
        raise ValueError('sparkys_invalid_date_group') from exc


def _narrative(soup, phrase):
    for block in soup.select('div.sqs-html-content'):
        txt = block.get_text(' ', strip=True)
        if phrase.lower() in txt.lower():
            prose = description(str(block), limit=MAX_DESCRIPTION + 1)
            if prose and len(prose) >= 100 and len(prose) <= MAX_DESCRIPTION:
                return prose
    raise ValueError('sparkys_incomplete_publisher_description')


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != KEY
            or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != SOURCES[KEY]
            or source.get('timezone') != ZONE):
        raise ValueError('unregistered_sparkys_source')
    text = fetch(URL, 'text/html')
    soup = BeautifulSoup(text, 'html.parser')
    visible = soup.get_text(' ', strip=True)
    if ('2601 E Lake Ave, Watsonville, CA 95076' not in visible
            or 'Sparky' not in visible or 'Upcoming Events' not in visible):
        raise ValueError('sparkys_venue_or_schedule_changed')
    # The same publisher's current-season identity is in its community
    # display PDF, not guessed from the collector's clock. Prior-year files
    # remain linked on this site, so use only the current calendar year.
    years = {int(x) for a in soup.find_all('a', href=True)
             for x in YEAR.findall(a['href'])}
    now = now or datetime.now(timezone.utc)
    year = max(years) if years else 0
    if year != now.astimezone(ZoneInfo(ZONE)).year:
        raise ValueError('sparkys_season_year_missing_or_ambiguous')
    narratives = {
        'drive': _narrative(soup, 'Experience the magic of the season from the comfort of your car'),
        'walk': _narrative(soup, 'Wander through a dazzling winter wonderland'),
    }
    rows = {}
    recognized_groups = 0
    for block in soup.select('div.sqs-html-content'):
        heading = block.select_one('p.sqsrte-large strong')
        link = block.find('a')
        if not heading or not link:
            continue
        raw = ' '.join(link.get_text(' ', strip=True).split())
        clock = CLOCK.fullmatch(raw)
        if not clock:
            continue
        kind = clock[1].strip().lower()
        # Krampus has only a short teaser and no complete original narrative.
        if 'krampus' in kind:
            continue
        if kind not in MODES:
            continue
        title_mode, mode = MODES[kind]
        recognized_groups += 1
        for day in _dates(heading.get_text(' ', strip=True), year):
            start = _local_time(day, clock[2])
            end = _local_time(day, clock[3])
            if end <= start or not now - timedelta(hours=3) <= start.astimezone(timezone.utc) <= now + timedelta(days=60):
                continue
            key = f'{mode}:{day.isoformat()}'
            row = record(f"Sparky's Holiday Lights — {title_mode}", start.isoformat(), end.isoformat(),
                         VENUE, ADDRESS, 'Watsonville', URL, key,
                         'Holiday Lights', None, None, ZONE, retain_until_end=True)
            if row is None:
                continue
            row.update(description=narratives[mode], timezone=ZONE,
                       publisher_categories=['Holiday Lights', title_mode],
                       location_provenance='official_publisher_venue_street',
                       occurrence_identity=key)
            from roomquest.publisher_evidence import attach
            row = attach(row, KEY)
            if key in rows and rows[key] != row:
                raise ValueError('sparkys_conflicting_occurrence')
            rows[key] = row
    if recognized_groups < 5 or len(rows) > MAX_RECORDS:
        raise ValueError('sparkys_schedule_incomplete_or_overlimit')
    return sorted(rows.values(), key=lambda r: (r['starts_at'], r['id']))
