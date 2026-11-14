"""Publisher PDF programs with complete native-text descriptions.

The lighthouse's annual PDF has one remaining dated program. Oceanside's
calendar places dates in a visual grid, so its reviewed date-to-cell mapping
is bound to the exact November document hash. Narratives are extracted anew
from the downloaded PDF, not substituted with card summaries or generated
text. A changed monthly document requires review; no next-month recurrence
or stale captured occurrence is projected.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp

ZONE = 'America/New_York'
LIGHTHOUSE = 'absecon_lighthouse_programs_nj'
OCEANSIDE = 'oceanside_one_family_success_nj'
OCEANSIDE_TWO = 'oceanside_two_family_success_nj'
LIGHTHOUSE_DOCUMENT = ('https://abseconlighthouse.org/__static/'
                       'jdj5jdewjglibdlvsvfqaurawvn6s3lr/2026-Calendar-of-Events.pdf')
OCEANSIDE_CALENDAR = 'https://oceanside1fsc.org/calendar%2Fevents'
OCEANSIDE_DOCUMENT = ('https://img1.wsimg.com/blobby/go/'
                      'c9c4d40f-2001-48f8-ba1f-1ae4bbb56cfa/downloads/'
                      '62733830-c145-4d87-833f-9d773edd7b8e/Nov%202026%20(1).pdf?ver=1794503710309')
OCEANSIDE_SHA256 = 'a4850a93af180ffa201b369c893d8a834b55caf2b617ba4d00476c5f2fcaaa6f'
OCEANSIDE_TWO_DOCUMENT = ('https://img1.wsimg.com/blobby/go/'
    'b354238c-dda7-4b01-8f73-d04bb1b5e705/downloads/'
    'a671afb0-5f3e-4f66-a2a8-b3fa99a46078/'
    'Oceanside%20II%20FSC%20-%20Nov%202026%20Calendar%20(3).pdf?ver=1794594895631')
OCEANSIDE_TWO_SHA256 = 'd18f380fff1573a2803e9c4037e61db9cca1afc7754bf086d4f10f9689788639'
SOURCES = {
    LIGHTHOUSE: (LIGHTHOUSE_DOCUMENT, 'html', 'html'),
    OCEANSIDE: (OCEANSIDE_CALENDAR, 'html', 'html'),
    OCEANSIDE_TWO: ('https://oceanside2fsc.org/calendar', 'html', 'html'),
}
ALLOWED_HOSTS = {
    LIGHTHOUSE: ('abseconlighthouse.org',),
    OCEANSIDE: ('oceanside1fsc.org', 'img1.wsimg.com'),
    OCEANSIDE_TWO: ('oceanside2fsc.org', 'img1.wsimg.com'),
}
MAX_PDF = 16_000_000
MAX_TEXT = 60_000
MAX_DESCRIPTION = 12000
OCEANSIDE_VENUE = ('Oceanside I Family Success Center',
                   '201 Melrose Avenue Unit 3, Atlantic City, NJ 08401')
# Noyes' own Nov24 event identifies this named center and matching street/ZIP.
# https://noyesmuseum.org/all-noyes-events/2026/oceanside-1-fall-k6lsf-aagcf
OCEANSIDE_POINT = (39.372382359281055, -74.41623991779097)
OCEANSIDE_TWO_VENUE = ('Oceanside II Family Success Center',
                       '3201 Atlantic Avenue, Atlantic City, NJ 08401')
# Publisher LocalBusiness JSON-LD on https://oceanside2fsc.org/ matches the
# exact venue/address printed on both pages of the November calendar.
OCEANSIDE_TWO_POINT = (39.353485, -74.450258)
# NJ Audubon's site361 trail entry publishes this named lighthouse arrival
# point and its matching31SouthRhodeIsland street (reviewed2026-11-14).
LIGHTHOUSE_POINT = (39.36666, -74.41391)

# Reviewed against rendered page1; page2 contains the complete descriptions.
# Duplicate Nov24 Noyes Family Paint Night is already supplied by its primary
# calendar. Office hours, closures and registration-only service hours are not
# independent public programs. Nov19's offsite campus street is an explicitly
# labeled estimate under the user's contextual-address authorization. The
# college's Nov18,2025 president report identifies its prior Oceanside dinner
# at the Atlantic City campus; the current campus directory supplies the street.
OCEANSIDE_PROGRAMS = (
    ('computers-101', 'Computers 101', '2026-11-16', '11:30', '12:30',
     'This hands-on class will introduce', 'using a computer for everyday tasks.'),
    ('unwind-align', 'Unwind & Align with Edd: Stretching Session', '2026-11-17', '13:00', '14:00',
     'Stiff back? Tight shoulders?', 'help you move better and have stress less.'),
    ('health-insurance', 'Health Insurance Open Enrollment & Assistance', '2026-11-18', '13:30', '16:00',
     'You may be eligible for health insurance', 'from Planned Parenthood to register!'),
    ('thanksgiving-dinner', 'Oceanside Friendsgiving Dinner', '2026-11-19', '16:00', '17:30',
     'Join us for a special Thanksgiving Dinner!', 'We appreciate YOU!'),
    ('employment-training', 'One Stop for Employment & Training', '2026-11-20', '12:00', '15:00',
     'Atlantic County Workforce Development Office', 'interviewing support.'),
    ('pcab-meeting', 'Parent Community Advisory Board (PCAB) Meeting', '2026-11-23', '13:00', '14:00',
     "Join Oceanside 1 Family Success Center's Parent", 'together we can make a difference!'),
)
OCEANSIDE_TWO_PROGRAMS = (
    ('teen-speak', 'Teen Speak', '2026-11-16', '12:00', '14:00',
     'A parent group focused on understanding', 'Lunch will be provided.'),
    ('thanksgiving-bingo', 'Thanksgiving Bingo', '2026-11-17', '17:00', '18:00',
     'Come and join us for a fun night of Bingo!', 'Winners will pick a prize!'),
    # The apparent1–2pm JFS conflict was stale search content: its exact Nov18
    # detail now404s and the current JFS month page has no distribution row.
    # This current publisher PDF explicitly dates the host's program12–1pm.
    ('food-distribution', 'Food Distribution with JFS', '2026-11-18', '12:00', '13:00',
     'Jewish Family Services will provide mobile food access.', '** PLEASE BRING YOUR OWN BAG **'),
    ('teen-speak', 'Teen Speak', '2026-11-23', '12:00', '14:00',
     'A parent group focused on understanding', 'Lunch will be provided.'),
    ('employment-training', 'One Stop for Employment and Training', '2026-11-30', '12:00', '15:00',
     'Atlantic County Workforce Development Office will provide', 'support as well as youth services.'),
)


def event_url(source_key, value):
    return source_key in SOURCES and value == SOURCES[source_key][0]


def reviewed_large_document(url, accept, allowed_hosts, respect_robots):
    """Bounded exceptions for two reviewed 12.8/15.9MB PDFs, not a CDN host."""
    return (respect_robots is True and accept == 'application/pdf'
            and isinstance(url, str) and any(
                allowed_hosts == ALLOWED_HOSTS[key]
                and url.replace('%28', '(').replace('%29', ')') == document
                for key, document in ((OCEANSIDE, OCEANSIDE_DOCUMENT),
                                      (OCEANSIDE_TWO, OCEANSIDE_TWO_DOCUMENT))))


def _check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _pages(payload, *, max_pages, max_bytes, deadline_at=None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    _check(deadline_at)
    if not isinstance(payload, bytes) or not payload.startswith(b'%PDF-') or len(payload) > max_bytes:
        raise ValueError('invalid_atlantic_pdf_document')
    try:
        reader = PdfReader(BytesIO(payload))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= max_pages:
            raise ValueError('atlantic_pdf_page_limit')
        texts = []
        for page in reader.pages:
            _check(deadline_at)
            text = ' '.join((page.extract_text() or '').split())
            if not text or len(text) > MAX_TEXT:
                raise ValueError('atlantic_pdf_text_unavailable')
            texts.append(text)
        return texts
    except PdfReadError as exc:
        raise ValueError('invalid_atlantic_pdf_document') from exc


def _row(key, identity, title, day, starts, ends, prose, venue, point, now):
    begin, end = (timestamp(day + 'T' + value, ZONE) for value in (starts, ends))
    if end <= now or begin >= now + timedelta(days=60):
        return None
    if not prose or len(prose) > MAX_DESCRIPTION:
        raise ValueError('publisher_description_limit')
    result = record(title, begin.isoformat(), end.isoformat(), venue[0], venue[1],
                    'Atlantic City', SOURCES[key][0], f'{key}:{identity}:{day}',
                    '', *(point or (None, None)), tz=ZONE, retain_until_end=True)
    if result is not None:
        result.update(description=prose, timezone=ZONE,
                      location_provenance='reviewed_publisher_pdf_venue')
    return result


def parse_lighthouse(payload, *, now=None, deadline_at=None):
    now = now or datetime.now(timezone.utc)
    text = _pages(payload, max_pages=1, max_bytes=1_000_000, deadline_at=deadline_at)[0]
    if not text.startswith('2026 Calendar of Events PROCEEDS BENEFIT ABSECON LIGHTHOUSE'):
        raise ValueError('atlantic_pdf_edition_unreviewed')
    matches = list(re.finditer(r'Friday, December 4\s+Luminary Light Festival\s*,\s*'
                              r'(5pm)\s+to\s+(7pm)\s+(.+)$', text))
    if len(matches) != 1 or not matches[0][3].startswith('Full Moon Climb,'):
        raise ValueError('atlantic_pdf_schedule_changed')
    prose = matches[0][3]
    if re.search(r'\b(?:cancelled|canceled|postponed|not yet confirmed)\b', prose, re.I):
        return []
    row = _row(LIGHTHOUSE, 'luminary-light-festival', 'Luminary Light Festival',
               '2026-12-04', '17:00', '19:00', prose,
               ('Absecon Lighthouse', '31 South Rhode Island Avenue, Atlantic City, NJ 08401'),
               LIGHTHOUSE_POINT, now)
    return [row] if row else []


def discover_oceanside(payload, *, source_key=OCEANSIDE):
    if not isinstance(payload, str) or len(payload) > 1_000_000:
        raise ValueError('invalid_atlantic_pdf_listing')
    soup = BeautifulSoup(payload, 'html.parser')
    text = ' '.join(soup.get_text(' ', strip=True).split())
    label = ('November Calendar 2026' if source_key == OCEANSIDE else
             'Oceanside II FSC - Nov 2026 Calendar (E)')
    if source_key not in (OCEANSIDE, OCEANSIDE_TWO) or label not in text:
        raise ValueError('atlantic_pdf_edition_unreviewed')
    urls = {urljoin(SOURCES[source_key][0], a['href']) for a in soup.select('a[href]')
            if '.pdf' in a['href'].lower() and (source_key == OCEANSIDE or
                label in ' '.join(a.parent.get_text(' ', strip=True).split()))}
    if not urls or any(not reviewed_large_document(url, 'application/pdf',
                              ALLOWED_HOSTS[source_key], True) for url in urls):
        raise ValueError('atlantic_pdf_edition_unreviewed')
    if len(urls) != 1:
        raise ValueError('atlantic_pdf_document_conflict')
    return next(iter(urls))


def parse_oceanside(payload, *, source_key=OCEANSIDE, now=None, deadline_at=None):
    now = now or datetime.now(timezone.utc)
    expected_hash = OCEANSIDE_SHA256 if source_key == OCEANSIDE else OCEANSIDE_TWO_SHA256
    if source_key not in (OCEANSIDE, OCEANSIDE_TWO) or not isinstance(payload, bytes) or sha256(payload).hexdigest() != expected_hash:
        raise ValueError('atlantic_pdf_edition_unreviewed')
    pages = _pages(payload, max_pages=2, max_bytes=MAX_PDF, deadline_at=deadline_at)
    venue, point, programs, address, condition = (
        (OCEANSIDE_VENUE, OCEANSIDE_POINT, OCEANSIDE_PROGRAMS, '201 Melrose Ave - Unit 3',
         '*Registration & Confirmation is Required for ALL Giveaways & Workshops!!*')
        if source_key == OCEANSIDE else
        (OCEANSIDE_TWO_VENUE, OCEANSIDE_TWO_POINT, OCEANSIDE_TWO_PROGRAMS,
         '3201 Atlantic Avenue, Atlantic City, NJ 08401',
         '***Registration is Required for PC appointments, Giveaways & Workshops!!***'))
    if len(pages) != 2 or address not in pages[1]:
        raise ValueError('atlantic_pdf_venue_changed')
    body = pages[1]
    if condition not in body:
        raise ValueError('atlantic_pdf_conditions_changed')
    rows = []
    for identity, title, day, starts, ends, first, last in programs:
        matches = list(re.finditer(re.escape(first) + r'.*?' + re.escape(last), body))
        if len(matches) != 1:
            raise ValueError('atlantic_pdf_description_changed')
        prose = matches[0][0] + '\n\nEverything is free & open to all!\n' + condition
        selected_venue, selected_point = venue, point
        if source_key == OCEANSIDE and identity == 'thanksgiving-dinner':
            selected_venue = (
                'Atlantic Cape Community College — Atlantic City campus (address estimated)',
                '1535 Bacharach Boulevard, Atlantic City, NJ 08401-4485')
            selected_point = None
        row = _row(source_key, identity, title, day, starts, ends, prose,
                   selected_venue, selected_point, now)
        if row:
            if source_key == OCEANSIDE and identity == 'thanksgiving-dinner':
                row['location_provenance'] = 'estimated_campus_from_prior_publisher_program_and_current_campus_directory'
            rows.append(row)
    return rows


def collect(source, fetch, *, now=None, deadline_at=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if not profile or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter')) != profile or source.get('timezone') != ZONE:
        raise ValueError('unregistered_atlantic_pdf_source')
    _check(deadline_at)
    if key == LIGHTHOUSE:
        return parse_lighthouse(fetch(profile[0], 'application/pdf'), now=now, deadline_at=deadline_at)
    document = discover_oceanside(fetch(profile[0], 'text/html'), source_key=key)
    _check(deadline_at)
    return parse_oceanside(fetch(document, 'application/pdf'), source_key=key, now=now, deadline_at=deadline_at)
