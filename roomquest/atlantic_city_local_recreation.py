"""Brigantine's published drop-in season and NJShoreRun's dated meetups.

The current CER page must still link the reviewed PDF. Its hash binds native
course prose, drop-in eligibility, clocks and holiday exceptions to one edition.
Weekly classes stop at the end of their stated calendar-week term; closures do
not generate guessed makeup sessions. Explicit art dates remain explicit dates.
Two contradictory publisher schedules are documented holds, not repaired dates.

NJShoreRun contributes only the explicitly dated meetup and save-the-date item.
The dated weekly heading supplies the year context for the latter; its published
weekday must agree. Neither run gets an invented end time or recurring rule.
All requests go through the supplied guarded fetch callback.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import logging
import re
from time import monotonic
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.mapsee_adapter import record, timestamp


log = logging.getLogger(__name__)
ZONE = 'America/New_York'
BRIGANTINE = 'brigantine_community_recreation_nj'
RUN = 'nj_shore_run_nj'
SOURCES = {
    BRIGANTINE: ('https://brigantinebeach.org/municipal/departments/community-education-recreation/',
                 'html', 'html'),
    RUN: ('https://www.njshorerun.com/running-club/run', 'html', 'html'),
}
ALLOWED_HOSTS = {BRIGANTINE: ('brigantinebeach.org',), RUN: ('www.njshorerun.com',)}
CHECKPOINT_KEYS = set()
MAX_RECORDS = 500
MAX_DESCRIPTION = 12000
MAX_HTML = 1_000_000
MAX_PDF = 3_000_000
BRIGANTINE_DOCUMENT = 'https://brigantinebeach.org/wp-content/uploads/Fall-Brochure-2026-green.pdf'
BRIGANTINE_SHA256 = '7d727ba806414dfc1b31198356f6757a660c9b452fa637124614145e40f6f365'
BRIGANTINE_CLOSED = {date(2026, 10, 12), date(2026, 11, 3), date(2026, 11, 11),
                     date(2026, 11, 26), date(2026, 11, 27)}

# All 39 starred (explicitly drop-in) headings were visually reviewed on pages
# 4-12. The two contradictory entries remain in the manifest and fail no other
# classes; their exact reasons are surfaced in logs and the source audit.
BRIGANTINE_PROGRAMS = (
    (4, 'TAI CHI/QIGONG I*'), (4, 'TAI CHI/QIGONG II*'), (4, 'SENIOR LITE*'),
    (5, 'STEP CLASS*'), (5, 'LOW IMPACT STEP CLASS*'),
    (5, 'MORNING YOGA I – ALL LEVELS*'), (5, 'MORNING YOGA II – ALL LEVELS*'),
    (6, 'MORNING YOGA III – ALL LEVELS*'), (6, 'CHAIR YOGA I – ALL LEVELS*'),
    (6, 'CHAIR YOGA III – ALL LEVELS*'), (6, 'YOGA FUSION*'),
    (6, 'STRETCH & FLEX*'), (6, 'BELLY DANCING*'),
    (7, 'MORNING ZUMBA*'), (7, 'ZUMBA TONING*'), (7, 'MORNING POUND*'),
    (7, 'SLOW/BEGINNER ZUMBA*'), (7, 'PILATES II*'),
    (8, 'PILATES SCULPT I*'), (8, 'PILATES SCULPT II*'), (8, 'PILATES SCULPT III*'),
    (8, 'PILATES CORE & STRETCH*'), (8, 'PILATES CORE & STRETCH PLUS*'),
    (8, 'PILATES W/ FAYE (NEW)*'), (8, 'CARDIO STRONG*'),
    (9, 'BODY SCULPT I*'), (9, 'BODY SCULPT II*'), (9, 'MOVE STRONG/BALANCE I*'),
    (9, 'MOVE STRONG/BALANCE II*'), (9, 'MOVE STRONG/BALANCE III*'),
    (9, 'SWEAT & SCULPT*'), (9, 'TOTAL BODY STRENGTH & CONDITIONING I*'),
    (10, 'TOTAL BODY STRENGTH & CONDITIONING II*'), (10, 'DANCE FITNESS*'),
    (11, 'ABS & GLUTES*'), (11, 'FLEX APPEAL WITH ROBIN*'),
    (11, 'MIXED MEDIA*'), (11, 'ACRYLIC & OTHER MEDIUMS*'),
    (12, 'DRAWING FIGURES*'),
)
BRIGANTINE_HELD = {
    'CARDIO STRONG*': 'published_begin_date_Tuesday_conflicts_with_Monday_Wednesday_schedule',
    'ACRYLIC & OTHER MEDIUMS*': 'published_Friday_conflicts_with_explicit_Tuesday_dates',
}
BRIGANTINE_ART_DATES = {
    'MIXED MEDIA*': ('2026-10-13', '2026-10-20', '2026-10-27', '2026-11-10',
                    '2026-11-17', '2026-12-01', '2026-12-08', '2026-12-15'),
    'DRAWING FIGURES*': ('2026-10-16', '2026-10-23', '2026-10-30', '2026-11-06',
                        '2026-11-13', '2026-11-20', '2026-12-04', '2026-12-11'),
}
DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
DAY_TOKEN = r'Mon(?:day)?\.?|Tues?(?:day)?\.?|Wed(?:nesday)?\.?|Thurs?(?:day)?\.?|Fri(?:day)?\.?|Sat(?:urday)?\.?|Sun(?:day)?\.?'
CLOCK = r'\d{1,2}(?::\d{2})?\s*(?:am|pm)'

# Exact source + meeting-place + resolved-street mappings only. CER's state
# geocoder result is interpolated. Linwood uses the publisher's own intersection
# (StreetInt), with a separately labelled park-level street estimate. Music Pier
# has primary municipal Place/GeoCoordinates at its exact postal address.
LOCATIONS = {
    'brigantine': (
        'Brigantine Beach Community Center (approximate map location)',
        '265 42nd Street, Brigantine, NJ 08203', 'Brigantine',
        39.391450603496, -74.395619930205, 'reviewed_nj_ogis_street_address'),
    'linwood': (
        'Linwood Bike Path — hockey rink parking (address estimated; approximate map location)',
        '1210 Wabash Avenue, Linwood, NJ 08221', 'Linwood',
        39.346137000003, -74.573842500001,
        'reviewed_publisher_meeting_intersection_and_estimated_park_street'),
    'music_pier': (
        'Ocean City Music Pier', '825 Boardwalk, Ocean City, NJ 08226', 'Ocean City',
        39.275278, -74.570425, 'reviewed_municipal_venue_jsonld'),
}


def _check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def _complete(value):
    """Validate once-normalized plain prose without reparsing literal markup."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('publisher_description_missing')
    if len(value) > MAX_DESCRIPTION:
        raise ValueError('publisher_description_limit')
    return value


def _html(payload):
    if not isinstance(payload, str) or not payload or len(payload) > MAX_HTML:
        raise ValueError('invalid_atlantic_local_recreation_html')
    return BeautifulSoup(payload, 'html.parser')


def event_url(key, value):
    return key in SOURCES and value == SOURCES[key][0]


def _clock(value):
    value = re.sub(r'\s+', '', value).upper()
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def _row(key, title, day, clock, end_clock, description, location_key, identity, now,
         category='Sports & Fitness'):
    description = _complete(description)
    start = timestamp(f'{day.isoformat()}T{clock.isoformat()}', ZONE)
    end = timestamp(f'{day.isoformat()}T{end_clock.isoformat()}', ZONE) if end_clock else None
    if end is not None and end <= start:
        raise ValueError('atlantic_local_recreation_clock_conflict')
    if start >= now + timedelta(days=60) or (end or start) <= now:
        return None
    venue, street, city, lat, lng, provenance = LOCATIONS[location_key]
    result = record(title, start.isoformat(), end.isoformat() if end else None,
                    venue, street, city, SOURCES[key][0], f'{key}:{identity}:{day}',
                    category, lat=lat, lng=lng, tz=ZONE, retain_until_end=True,
                    publisher_geo=True)
    if result is not None:
        result.update(description=description, timezone=ZONE, attendance_mode='in_person',
                      location_provenance=provenance)
    return result


def _bounded(rows):
    if len(rows) > MAX_RECORDS:
        raise ValueError('atlantic_local_recreation_record_limit')
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('atlantic_local_recreation_duplicate_identity')
    return rows


def discover_brigantine(payload):
    soup = _html(payload)
    links = [urljoin(SOURCES[BRIGANTINE][0], a['href']) for a in soup.select('a[href]')
             if 'brochure' in _normal(a.get_text(' ', strip=True)).lower()]
    if links != [BRIGANTINE_DOCUMENT]:
        raise ValueError('brigantine_edition_unreviewed')
    return links[0]


def _brigantine_pages(payload, deadline_at):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    _check(deadline_at)
    if (not isinstance(payload, bytes) or not payload.startswith(b'%PDF-')
            or len(payload) > MAX_PDF):
        raise ValueError('invalid_brigantine_pdf')
    if sha256(payload).hexdigest() != BRIGANTINE_SHA256:
        raise ValueError('brigantine_edition_unreviewed')
    try:
        reader = PdfReader(BytesIO(payload))
        if reader.is_encrypted or len(reader.pages) != 21:
            raise ValueError('brigantine_document_shape_changed')
        pages = {}
        for number in sorted({1, 2, *(page for page, _ in BRIGANTINE_PROGRAMS)}):
            _check(deadline_at)
            text = reader.pages[number - 1].extract_text() or ''
            if not text.strip() or len(text) > 50_000:
                raise ValueError('brigantine_native_text_missing')
            pages[number] = text
        return pages
    except PdfReadError as exc:
        raise ValueError('invalid_brigantine_pdf') from exc


def _brigantine_program(page, title):
    # A line boundary distinguishes STEP CLASS from LOW IMPACT STEP CLASS.
    matches = list(re.finditer(r'^\s*' + re.escape(title)
                              + r'\s*\n(.+?Non-Sr\.\s*\$\d+\.\d{2})',
                              page, re.M | re.S))
    if len(matches) != 1:
        raise ValueError('brigantine_program_description_changed')
    body = _normal(matches[0][1])
    parts = re.split(r'\bInstructor:\s*', body, flags=re.I)
    if len(parts) != 2 or not parts[0]:
        raise ValueError('publisher_description_missing')
    metadata = parts[1]
    clocks = list(re.finditer(r'(' + CLOCK + r')\s*[–-]\s*(' + CLOCK + ')', metadata, re.I))
    if len(clocks) != 1:
        raise ValueError('brigantine_program_clock_changed')
    start_clock, end_clock = (_clock(value) for value in clocks[0].groups())
    if end_clock <= start_clock:
        raise ValueError('brigantine_program_clock_conflict')
    tokens = re.findall(DAY_TOKEN, metadata[:clocks[0].start()], re.I)
    weekdays = {next(i for i, name in enumerate(DAY_NAMES)
                     if name[:3].lower() == token[:3].lower()) for token in tokens}
    if not weekdays:
        raise ValueError('brigantine_program_weekday_missing')
    if title in BRIGANTINE_ART_DATES:
        dates = [date.fromisoformat(value) for value in BRIGANTINE_ART_DATES[title]]
        if 'Class Dates:' not in metadata or any(day.weekday() not in weekdays for day in dates):
            raise ValueError('brigantine_program_clock_conflict')
    else:
        begins = re.findall(r'\bBegins (\d{1,2}/\d{1,2}/\d{2})\b', metadata)
        terms = re.findall(r'\b(\d+) Sessions \((\d+) Weeks\)', metadata)
        if len(begins) != 1 or len(terms) != 1:
            raise ValueError('brigantine_program_term_changed')
        first = datetime.strptime(begins[0], '%m/%d/%y').date()
        sessions, weeks = (int(value) for value in terms[0])
        if (first.year != 2026 or first.month != 10 or not 1 <= weeks <= 10
                or first.weekday() not in weekdays or sessions != weeks * len(weekdays)):
            raise ValueError('brigantine_program_clock_conflict')
        # A closure removes a date; it never extends the published term.
        dates = [first + timedelta(days=offset) for offset in range(weeks * 7)
                 if (first + timedelta(days=offset)).weekday() in weekdays]
    return body, dates, start_clock, end_clock


def parse_brigantine(payload, *, now=None, deadline_at=None):
    now = calendar_anchor(now or datetime.now(timezone.utc))
    pages = _brigantine_pages(payload, deadline_at)
    cover = _normal(pages[1])
    if ('FALL PROGRAMS 2026' not in cover
            or 'Brigantine Community Center at 265 42nd St.' not in cover
            or 'CLOSURES THIS SESSION: 10/12, 11/3, 11/11, 11/26 & 11/27' not in cover):
        raise ValueError('brigantine_edition_unreviewed')
    # PDF headings are separate drawing objects and extract after the body.
    # The reviewed first/last sentences bind the entire visible policy instead.
    policy = re.findall(
        r'(Based on your feedback, we are excited to continue to offer the ability '
        r'to drop into a class for the fall session!.*?'
        r'Once filled, no more drop-ins will be allowed for that class that day\.)',
        _normal(pages[2]))
    if len(policy) != 1 or not all(part in policy[0] for part in (
            'Programs marked with an * will allow drop-ins', 'Late drop-ins will not be permitted.',
            'Limited drop-in spots are available.')):
        raise ValueError('brigantine_drop_in_policy_changed')
    observed = {(number, line.strip()) for number, text in pages.items() if number >= 4
                for line in text.splitlines()
                if line.strip().endswith('*') and line.strip().isupper()}
    if observed != set(BRIGANTINE_PROGRAMS):
        raise ValueError('brigantine_drop_in_manifest_changed')
    rows = []
    for page, title in BRIGANTINE_PROGRAMS:
        _check(deadline_at)
        if title in BRIGANTINE_HELD:
            log.warning('atlantic_local_recreation_held title=%s reason=%s',
                        title, BRIGANTINE_HELD[title])
            continue
        body, dates, start_clock, end_clock = _brigantine_program(pages[page], title)
        description = _complete(body + '\n\nFall drop-ins: ' + policy[0])
        identity = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        for day in dates:
            if day in BRIGANTINE_CLOSED:
                continue
            row = _row(BRIGANTINE, title.rstrip('*'), day, start_clock, end_clock,
                       description, 'brigantine', identity, now,
                       'Arts & Culture' if title in BRIGANTINE_ART_DATES else 'Sports & Fitness')
            if row:
                rows.append(row)
    _check(deadline_at)
    return _bounded(rows)


def _dated_run(value):
    match = re.fullmatch(r'1\.\s*(' + '|'.join(DAY_NAMES) + r')\s+'
                         r'(\d{1,2}/\d{1,2}/\d{2}),\s*(' + CLOCK + r'),\s*(.+)',
                         value, re.I)
    if not match:
        raise ValueError('njshorerun_dated_run_changed')
    weekday, day, clock, place = match.groups()
    day = datetime.strptime(day, '%m/%d/%y').date()
    if DAY_NAMES[day.weekday()].lower() != weekday.lower():
        raise ValueError('njshorerun_weekday_conflict')
    if not all(part in place for part in ('Linwood Bike Path', 'hockey rink parking',
                                          'Wabash Ave', 'W Essex Ave')):
        raise ValueError('njshorerun_meeting_place_unreviewed')
    return day, _clock(clock)


def _save_the_date(value, anchor):
    match = re.search(r'Our (\d+(?:st|nd|rd|th)) annual Ocean City Christmas Tree Run '
                      r'will be on (' + '|'.join(DAY_NAMES) + r'),\s*'
                      r'([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)?,?\s*at (' + CLOCK + ')',
                      value, re.I)
    if not match or 'starting from the OC Music Pier' not in value:
        raise ValueError('njshorerun_save_the_date_changed')
    ordinal, weekday, month, day, clock = match.groups()
    month_number = datetime.strptime(month, '%B').month
    candidates = [date(year, month_number, int(day)) for year in (anchor.year, anchor.year + 1)]
    candidates = [day for day in candidates if timedelta(0) <= day - anchor <= timedelta(days=180)
                  and DAY_NAMES[day.weekday()].lower() == weekday.lower()]
    if len(candidates) != 1:
        raise ValueError('njshorerun_context_year_unresolved')
    return f'{ordinal} Annual Ocean City Christmas Tree Run', candidates[0], _clock(clock)


def parse_njshorerun(payload, *, now=None, deadline_at=None):
    now = calendar_anchor(now or datetime.now(timezone.utc))
    _check(deadline_at)
    soup = _html(payload)
    if 'NJShoreRun Weekly Group Runs and Local Race Meetup' not in soup.get_text(' ', strip=True):
        raise ValueError('njshorerun_page_identity_changed')
    headings = [node for node in soup.select('p')
                if _normal(node.get_text(' ', strip=True)).startswith("This Week's Group Run Meetup (")]
    if len(headings) != 1:
        raise ValueError('njshorerun_weekly_manifest_changed')
    paragraphs = [_normal(node.get_text(' ', strip=True)) for node in headings[0].parent.select('p')
                  if node.get_text(strip=True)]
    anchor_match = re.fullmatch(r"This Week's Group Run Meetup \((\d{1,2}/\d{1,2}/\d{2})\):",
                               paragraphs[0])
    if not anchor_match or paragraphs.count('Race meetups:') != 1:
        raise ValueError('njshorerun_weekly_manifest_changed')
    anchor = datetime.strptime(anchor_match[1], '%m/%d/%y').date()
    race_index = paragraphs.index('Race meetups:')
    save_indexes = [i for i, value in enumerate(paragraphs) if value.startswith('Save The Date:')]
    if (len(save_indexes) != 1 or race_index < 3 or save_indexes[0] <= race_index
            or paragraphs[race_index + 1:save_indexes[0]] != ['None this week.']):
        raise ValueError('njshorerun_unreviewed_meetup_manifest')
    run_paragraphs = paragraphs[1:race_index]
    if len([value for value in run_paragraphs if re.match(r'^\d+\.', value)]) != 1:
        raise ValueError('njshorerun_unreviewed_meetup_manifest')
    run_description = _complete('\n\n'.join(run_paragraphs))
    day, clock = _dated_run(run_paragraphs[0])
    if day != anchor or not all(part in run_description for part in (
            'The Linwood Bike Path is', 'Directions to The Linwood Bike Path', 'All Are Welcome!')):
        raise ValueError('njshorerun_description_or_date_changed')
    save_description = _complete('\n\n'.join(paragraphs[save_indexes[0]:]))
    save_title, save_day, save_clock = _save_the_date(save_description, anchor)
    rows = []
    for title, event_day, event_clock, body, place, identity in (
        ('NJShoreRun Linwood Bike Path Group Run', day, clock, run_description,
         'linwood', 'linwood-bike-path'),
        (save_title, save_day, save_clock, save_description, 'music_pier', 'christmas-tree-run'),
    ):
        if re.search(r'\b(?:cancell?ed|postponed|sold[- ]out|members?[- ]only)\b', body, re.I):
            log.warning('atlantic_local_recreation_held title=%s reason=unavailable_run', title)
            continue
        row = _row(RUN, title, event_day, event_clock, None, body, place, identity, now)
        if row:
            rows.append(row)
    _check(deadline_at)
    return _bounded(rows)


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if (not profile or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != profile
            or source.get('timezone') != ZONE):
        raise ValueError('unregistered_atlantic_local_recreation_source')
    _check(deadline_at)
    payload = fetch(profile[0], 'text/html')
    _check(deadline_at)
    if key == RUN:
        return parse_njshorerun(payload, now=now, deadline_at=deadline_at)
    document = discover_brigantine(payload)
    payload = fetch(document, 'application/pdf')
    return parse_brigantine(payload, now=now, deadline_at=deadline_at)
