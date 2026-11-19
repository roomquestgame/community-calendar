"""Original Resource Center for Nonviolence Santa Cruz public-event calendar.

Publisher-specific, robots-safe HTML intake; a source-owned public occurrence,
full owner narrative and original named venue street are mandatory. Does not
manufacture coordinates, event times, recurring instances or image permissions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from bs4 import BeautifulSoup
from roomquest.mapsee_adapter import record

KEY = 'resource_center_nonviolence_santa_cruz_ca'
CALENDAR = 'https://rcnv.org/events/'
EVENT = ('https://rcnv.org/events/'
         'korea-is-not-a-war-base-dispatches-from-the-2026-jaju-solidarity-brigade/')
CONTACT = 'https://rcnv.org/about/contact/'
SOURCES = {KEY: (CALENDAR, 'html', 'html')}
ALLOWED_HOSTS = {KEY: ('rcnv.org',)}
ZONE = 'America/Los_Angeles'
TITLE = 'Korea Is Not a War Base: Dispatches from the 2026 Jaju Solidarity Brigade'
STREET = '612 Ocean Street, Santa Cruz, CA 95060'
MAX_RECORDS = 1
MAX_DESCRIPTION = 12000

def event_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'rcnv.org'
            and parsed.path == urlsplit(EVENT).path and not
            (parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port))

def _exact_text(soup, selector, *, missing):
    nodes = soup.select(selector)
    if len(nodes) != 1:
        raise ValueError(missing)
    return nodes[0].get_text(' ', strip=True)

def _parse_event(html, now):
    soup = BeautifulSoup(html, 'html.parser')
    if _exact_text(soup, 'article h1.entry-title', missing='rcnv_event_title_missing') != TITLE:
        raise ValueError('rcnv_event_title_changed')
    date_text = _exact_text(soup, '.em-event-single .em-event-date',
                            missing='rcnv_event_date_missing')
    times = _exact_text(soup, '.em-event-single .em-event-time',
                        missing='rcnv_event_time_missing')
    match = re.fullmatch(r'\s*(\d{1,2}:\d{2}\s*[aApP][mM])\s*[-–]\s*'
                         r'(\d{1,2}:\d{2}\s*[aApP][mM])\s*', times)
    if not match:
        raise ValueError('rcnv_event_full_times_missing')
    try:
        day = datetime.strptime(date_text, '%b %d, %Y')
        start_local = datetime.strptime(date_text + ' ' + match.group(1).upper().replace(' ', ''),
                                        '%b %d, %Y %I:%M%p').replace(tzinfo=ZoneInfo(ZONE))
        end_local = datetime.strptime(date_text + ' ' + match.group(2).upper().replace(' ', ''),
                                      '%b %d, %Y %I:%M%p').replace(tzinfo=ZoneInfo(ZONE))
    except (ValueError, OverflowError) as exc:
        raise ValueError('rcnv_event_timestamp_invalid') from exc
    if (day.year, day.month, day.day) != (2026, 11, 22) or end_local <= start_local:
        raise ValueError('rcnv_event_date_or_end_invalid')
    start = start_local.astimezone(timezone.utc)
    end = end_local.astimezone(timezone.utc)
    if not now - timedelta(hours=3) <= start <= now + timedelta(days=60):
        return []
    venues = [e.get_text(' ', strip=True) for e in soup.select('.em-event-single .em-event-location')
              if e.get_text(' ', strip=True)]
    if len(venues) != 1:
        raise ValueError('rcnv_event_venue_missing')
    venue = venues[0]
    if (not re.search(r'Resource Center for Nonviolence', venue, re.I) or
        not re.search(r'612\s+Ocean\s+St\.?,?\s*Santa\s+Cruz,?\s*CA,?\s*95060', venue, re.I)):
        raise ValueError('rcnv_event_venue_changed')
    categories = _exact_text(soup, '.em-event-single .em-event-categories',
                             missing='rcnv_event_categories_missing')
    if not ('Antiracism' in categories and 'Resisting Militarism' in categories):
        raise ValueError('rcnv_event_category_evidence_changed')
    blocks = soup.select('.em-event-single .em-event-content')
    if len(blocks) != 1:
        raise ValueError('rcnv_event_full_narrative_missing')
    description = blocks[0].get_text('\n', strip=True)
    if not (250 <= len(description) <= MAX_DESCRIPTION and
            'Jaju Solidarity Brigade' in description and
            'Everyone is welcome.' in description):
        raise ValueError('rcnv_event_full_narrative_missing')
    if re.search(r'\b(EVENT CANCELLED|EVENT CANCELED|EVENT POSTPONED)\b',
                 TITLE + ' ' + description, re.I):
        raise ValueError('rcnv_event_cancelled')
    row = record(TITLE, start.isoformat(), end.isoformat(),
                 'Resource Center for Nonviolence', STREET, 'Santa Cruz', EVENT,
                 'rcnv-jaju-solidarity-brigade-2026-11-22',
                 'Community, Education', None, None, ZONE, retain_until_end=True)
    if not row:
        raise ValueError('rcnv_original_event_record_rejected')
    row.update(description=description, timezone=ZONE,
               publisher_categories=['Antiracism', 'Resisting Militarism'],
               location_provenance='original_rcnv_event_venue_and_owner_contact')
    from roomquest.publisher_evidence import attach
    return [attach(row, KEY)]

def collect(source, fetch, *, deadline_at=None, now=None):
    if (source.get('source_key') != KEY or
        (source.get('feed_url'),source.get('kind'),source.get('platform_adapter')) != SOURCES[KEY]
        or source.get('timezone') != ZONE):
        raise ValueError('rcnv_wrong_source_identity')
    if deadline_at and monotonic() >= deadline_at:
        raise ValueError('rcnv_preview_deadline')
    calendar = BeautifulSoup(fetch(CALENDAR,'text/html'), 'html.parser')
    event_links = [tag.get('href','') for tag in calendar.select('a[href]')]
    if EVENT not in event_links:
        raise ValueError('rcnv_event_missing_from_owner_calendar')
    contact = BeautifulSoup(fetch(CONTACT,'text/html'),'html.parser').get_text(' ',strip=True)
    if not re.search(r'612\s+Ocean\s+(?:Street|St\.?)\s*,?\s*Santa\s+Cruz,?\s+CA\s+95060',
                     contact,re.I):
        raise ValueError('rcnv_official_street_missing')
    return _parse_event(fetch(EVENT,'text/html'), now or datetime.now(timezone.utc))

