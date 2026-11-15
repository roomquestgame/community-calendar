"""Inland FSC's complete, reviewed November programs through guarded fetch.

The publisher's current two-page calendar supplies the date grid and full
program paragraphs. Its SHA-256 binds the manually reviewed grid, image header
and return-location announcement; changed editions require a new review.
There is no projected weekly recurrence or automatic future-month expansion.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.atlantic_city_pdf_programs import _pages
from roomquest.mapsee_adapter import record, timestamp

ZONE = 'America/New_York'
KEY = 'inland_family_success_nj'
SOURCES = {KEY: ('https://www.centerffs.org/our-services/community-connections/inland-fsc', 'html', 'html')}
ALLOWED_HOSTS = {KEY: ('www.centerffs.org',)}
CHECKPOINT_KEYS = frozenset()
DOCUMENT = ('https://www.centerffs.org/sites/default/files/2026-10/'
            'Inland%20English%20November%202026%20Calendar.docx.pdf')
DOCUMENT_LABEL = 'November 2026 English Calendar'
DOCUMENT_SHA256 = '45724f7e2fb3deef9527a618b1279953c0b3d71f5aba6ef796340c2555f8eb6c'
MAX_DOCUMENT_BYTES = 3_000_000
MAX_DESCRIPTION = 12000
VENUE = ('Inland Family Success Center', '3050 Spruce Avenue, Egg Harbor Township, NJ 08234',
         'Egg Harbor Township')
# November's image footer explicitly says "WE ARE BACK AT: 3050 Spruve Ave".
# The own-site contact block confirms the spelling Spruce Avenue. This dated
# return announcement supersedes its older June temporary-relocation notice
# for 3073 English Creek Avenue; that temporary point is deliberately not used.
# NJ Office of GIS: exact street/city/ZIP, score100, PointAddress (not centroid).
POINT = (39.411594000003, -74.585974500001)
LOCATION_PROVENANCE = 'reviewed_november_return_location_and_nj_ogis_point_address'
# Printed in the image header of both reviewed PDF pages, not OCR conjecture.
PUBLIC_POLICY = 'Free & Open to All of Atlantic County'
REGISTRATION_PREFIX = 'You and your family are invited to free events and activities at Inland Family Success Center.'
OLD_RELOCATION_NOTICE = ('Our location at 3050 Spruce Avenue will be closed temporarily '
                         'due to renovations beginning in June.')

# Each tuple is a visually reviewed dated cell and the complete native paragraph
# boundaries on page 2. The movie title retains the publisher's "Little Woman".
PROGRAMS = (
    ('autumn-book-club-movie', 'Autumn Book Club Movie Screening: Little Woman',
     '2026-11-16', '17:00', '19:00',
     '16 Autumn Book Club Movie Screening: Little Woman 5:00pm-7:00pm 17',
     'Autumn Book Club Movie:', 'storytelling, discussion, and community.'),
    ('paint-build-turkey', 'Paint & Build a Turkey',
     '2026-11-21', '11:00', '12:00',
     '21 Paint & Build A Turkey! 11:00am-12:00pm 23',
     'Paint & Build a Turkey:', 'while enjoying a festive hands-on activity.'),
    ('thanksgiving-dinner', 'Thanksgiving Dinner',
     '2026-11-23', '17:00', '19:00',
     '23 Thanksgiving Dinner 5:00pm-7:00pm 24',
     'Thanksgiving Dinner:', 'so be sure to register early!*'),
    ('science-stem-e', 'Science with STEM-E-NJ',
     '2026-11-24', '16:00', '17:00',
     '24 Science with STEM-E Science, Technology, Engineering & Mathematic 4:00pm-5:00pm 25',
     'Science with STEM-E-NJ:', 'Science, Technology, Engineering & Mathematic'),
    ('yoga-meditation-tarak', 'Yoga & Meditation with Tarak',
     '2026-11-30', '16:30', '18:00',
     '30 Yoga & Meditation with Tarak 4:30pm-6:00pm',
     'Yoga & Meditation with Tarak:', 'slow down, breathe, and recharge.'),
)


def _check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _text(value):
    return ' '.join(value.replace('\u200b', '').split())


def event_url(key, value):
    return key == KEY and value == SOURCES[KEY][0]


def reviewed_venue_location(key, name, address):
    return POINT if key == KEY and (name, address) == VENUE[:2] else None


def discover_document(payload):
    """Require the current English calendar and complete public participation text."""
    if not isinstance(payload, str) or len(payload) > 500_000:
        raise ValueError('inland_listing_identity_changed')
    soup = BeautifulSoup(payload, 'html.parser')
    headings = [_text(h.get_text(' ', strip=True)) for h in soup.select('h1')]
    if headings != ['Welcome to the Inland Family Success Center Neighborhood Gathering Place']:
        raise ValueError('inland_listing_identity_changed')
    links = {(urljoin(SOURCES[KEY][0], a['href']), _text(a.get_text(' ', strip=True)))
             for a in soup.select('a[href]')
             if 'calendar' in a.get_text(' ', strip=True).lower()
             and 'english' in a.get_text(' ', strip=True).lower()}
    if links != {(DOCUMENT, DOCUMENT_LABEL)}:
        raise ValueError('inland_calendar_edition_unreviewed')
    paragraphs = [_text(p.get_text(' ', strip=True)) for p in soup.select('p')]
    registration = [p for p in paragraphs if p.startswith(REGISTRATION_PREFIX)]
    if (len(registration) != 1 or 'Register for events by visiting Eventbrite or calling 609.569.0376.' not in registration[0]
            or 'All services and workshops are free.' not in paragraphs):
        raise ValueError('inland_registration_changed')
    # Reconcile the known older June notice only. A changed relocation notice
    # while the same November PDF remains linked must be reviewed explicitly.
    relocation = [p for p in paragraphs if p.startswith('Our location at 3050 Spruce Avenue')]
    contact = [p for p in paragraphs if p.startswith('Visit Inland Family Success Center')]
    if (relocation not in ([], [OLD_RELOCATION_NOTICE])
            or contact != ['Visit Inland Family Success Center 3050 Spruce Avenue Egg Harbor Township, NJ 08234']):
        raise ValueError('inland_venue_context_changed')
    if len(registration[0]) > MAX_DESCRIPTION:
        raise ValueError('inland_description_limit')
    return DOCUMENT, registration[0]


def parse_document(payload, *, registration_text, now=None, deadline_at=None):
    _check(deadline_at)
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError('inland_clock_invalid')
    current = current.astimezone(timezone.utc)
    if (not isinstance(payload, bytes) or len(payload) > MAX_DOCUMENT_BYTES
            or sha256(payload).hexdigest() != DOCUMENT_SHA256):
        raise ValueError('inland_calendar_edition_unreviewed')
    if not isinstance(registration_text, str) or not registration_text.startswith(REGISTRATION_PREFIX):
        raise ValueError('inland_registration_changed')
    pages = _pages(payload, max_pages=2, max_bytes=MAX_DOCUMENT_BYTES, deadline_at=deadline_at)
    if (len(pages) != 2 or '26 *Center Closed* Happy Thanksgiving!' not in pages[0]
            or '27 *Center Closed* Black Friday!' not in pages[0]
            or any(grid not in pages[0] for *_, grid, first, last in PROGRAMS)):
        raise ValueError('inland_program_manifest_changed')
    rows = []
    for identity, title, day, begins, ends, grid, first, last in PROGRAMS:
        _check(deadline_at)
        matches = list(re.finditer(re.escape(first) + r'.*?' + re.escape(last), pages[1]))
        if len(matches) != 1:
            raise ValueError('inland_program_description_changed')
        # _pages already normalizes native PDF whitespace. Do not HTML-parse
        # this text again: literal angle brackets must remain publisher prose.
        body = matches[0][0] + '\n\n' + PUBLIC_POLICY + '\n' + registration_text
        if not body.strip() or len(body) > MAX_DESCRIPTION:
            raise ValueError('inland_description_limit')
        start, end = (timestamp(day + 'T' + value, ZONE) for value in (begins, ends))
        if end <= current or start >= current + timedelta(days=60):
            continue
        row = record(title, start.isoformat(), end.isoformat(), *VENUE[:2], VENUE[2],
                     SOURCES[KEY][0], f'{KEY}:{identity}:{day}', '', *POINT,
                     tz=ZONE, publisher_geo=True, retain_until_end=True)
        if row is None:
            raise ValueError('inland_record_incomplete')
        row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                   location_provenance=LOCATION_PROVENANCE)
        rows.append(row)
    return rows


def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != KEY or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter')) != SOURCES[KEY] or source.get('timezone') != ZONE):
        raise ValueError('unregistered_atlantic_remaining_inland_source')
    _check(deadline_at)
    document, registration = discover_document(fetch(SOURCES[KEY][0], 'text/html'))
    _check(deadline_at)
    return parse_document(fetch(document, 'application/pdf'), registration_text=registration,
                          now=now, deadline_at=deadline_at)
