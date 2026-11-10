"""South Hill's publisher-linked holiday market documents.

This supplements the existing Town Revize source; it does not create another
source, generate a market recurrence, or alter existing Revize identities.
The Town's current document links and the fetched PDFs supply every occurrence
date, explicit clock and street. Network policy belongs to the injected shared
fetcher. A PDF/link change is held instead of falling back to captured dates.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
import sys
from time import monotonic
import unicodedata
from urllib.parse import quote, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import record, timestamp
from roomquest.publisher_evidence import attach
from roomquest.publisher_schedule import earliest_published_time
from roomquest.revize import FEED_URL, SOURCE_KEY, TIMEZONE

CALENDAR = 'https://www.southhillva.gov/farmers_market.php'
HOST = 'www.southhillva.gov'
MAX_SECONDS = 24
MAX_DOCUMENTS = 4
MAX_HTML = 2_000_000
MAX_PDF = 1_500_000
MAX_PAGES = 3
MAX_TEXT = 30_000
LOOKAHEAD_DAYS = 60
TZ = ZoneInfo(TIMEZONE)

_FAMILIES = {
    'christmas open house': 'christmas_open_house',
    'hometown christmas market': 'hometown_christmas_market',
}
_FILES = {
    'christmas open house': 'christmas_open_house',
    'christmas application': 'hometown_christmas_market',
    'hometown christmas market': 'hometown_christmas_market',
}
_MONTHS = {name.lower(): number for number, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
_WEEKDAYS = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split()
_DATE = (r'(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?'
         r'(January|February|March|April|May|June|July|August|September|October|November|December)'
         r'\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(20\d{2})')
_CLOCK = r'(?:[1-9]|1[0-2])(?::[0-5]\d)?\s*[ap]\.?m\.?'
_SCHEDULE = re.compile(
    r'\b(?:Christmas Open House|Hometown Christmas Market|Christmas Market)\s+'
    r'(?:will take place\b[^!?]{0,150}?\bon|on)\s+' + _DATE +
    rf'\s*,?\s*from\s+({_CLOCK})\s*(?:to|[-–—])\s*({_CLOCK})', re.I)
_VENUE = re.compile(
    r'\b(South Hill Town Square|The Exchange Warehouse)\s+(?:at|on)\s+'
    r'([1-9]\d{0,5}\s+(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z .\'-]{0,70}?\s+'
    r'(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?))(?=\s+in\s+South Hill\b|[.,]|$)', re.I)
_STATUS = re.compile(r'\b(?:cancelled|canceled|postponed|private event|invitation[ -]only)\b', re.I)


def _check(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise ValueError('collection_deadline')


def _log(kind, **fields):
    print(json.dumps({'event': 'south_hill_market_' + kind, 'source_key': SOURCE_KEY,
                      **fields}, sort_keys=True), file=sys.stderr)


def _now(value):
    value = value or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('south_hill_market_now_timezone_missing')
    return value


def document_identity(url):
    """Recognize only reviewed, year-bearing document families on the Town host."""
    if not isinstance(url, str) or len(url) > 1500:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != HOST or parsed.fragment
                or (parsed.query and not re.fullmatch(r't=[0-9]{12,18}', parsed.query))):
            return None
        path = unquote(parsed.path)
        match = re.fullmatch(
            r'/(Christmas Open House|Christmas Application|Hometown Christmas Market) (20\d{2})\.pdf',
            path, re.I)
        if not match or parsed.path not in (path, quote(path, safe='/')):
            return None
        return _FILES[match[1].lower()], int(match[2])
    except (ValueError, UnicodeError):
        return None


def discover(payload, *, now=None):
    """Follow current publisher links; never synthesize a URL or a future year."""
    current = _now(now)
    if not isinstance(payload, str) or len(payload) > MAX_HTML:
        raise ValueError('invalid_south_hill_market_listing')
    soup = BeautifulSoup(payload, 'html.parser')
    for node in soup.select('script, style, template, noscript, [hidden], [aria-hidden=true]'):
        node.decompose()
    if (not soup.find(['h1', 'h2', 'h3'], string=re.compile(r'^\s*Farmers Market\s*$', re.I))
            or not re.search(r'\bDocument Center\b', soup.get_text(' ', strip=True), re.I)):
        raise ValueError('south_hill_market_listing_changed')
    first_year = current.astimezone(TZ).year
    last_year = (current + timedelta(days=LOOKAHEAD_DAYS)).astimezone(TZ).year
    urls = set()
    for anchor in soup.select('a[href]'):
        label = ' '.join(anchor.get_text(' ', strip=True).split())
        match = re.fullmatch(
            r'(?:South Hill Farmers Market\s+)?(Christmas Open House|Hometown Christmas Market)\s+(20\d{2})',
            label, re.I)
        if not match:
            if re.search(r'\b(?:Christmas Open House|Hometown Christmas Market)\b', label, re.I):
                raise ValueError('south_hill_market_document_label_unresolved')
            continue
        url = urljoin(CALENDAR, anchor['href'])
        identity = document_identity(url)
        if identity != (_FAMILIES[match[1].lower()], int(match[2])):
            raise ValueError('south_hill_market_document_identity_mismatch')
        parsed = urlsplit(url)
        url = parsed._replace(path=quote(unquote(parsed.path), safe='/')).geturl()
        if first_year <= identity[1] <= last_year:
            urls.add(url)
        else:
            _log('excluded', id=f'south_hill_market:{identity[0]}:{identity[1]}',
                 document_url=url, reason='document_year_outside_window')
    if len(urls) > MAX_DOCUMENTS:
        raise ValueError('south_hill_market_document_limit')
    return sorted(urls)


def _date(parts):
    weekday, month, day, year = parts
    try:
        result = date(int(year), _MONTHS[month.lower()], int(day))
    except (ValueError, KeyError):
        raise ValueError('south_hill_market_date_unresolved') from None
    if weekday and _WEEKDAYS[result.weekday()].lower() != weekday.lower():
        raise ValueError('south_hill_market_weekday_conflict')
    return result


def _clock(day, value):
    value = re.sub(r'[.\s]', '', value).upper()
    try:
        wall = datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()
        return timestamp(datetime.combine(day, wall).isoformat(), TIMEZONE)
    except ValueError:
        raise ValueError('south_hill_market_time_unresolved') from None


def parse_text(text, *, document_url, now=None):
    """Extract the two documented form layouts without memorizing their dates."""
    current = _now(now)
    identity = document_identity(document_url)
    if identity is None:
        raise ValueError('south_hill_market_document_identity_mismatch')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError('south_hill_market_pdf_text_unavailable')
    text = unicodedata.normalize('NFKC', text)
    headings = set(re.findall(
        r'(?mi)^\s*(Christmas Open House|Hometown Christmas Market)\s+(20\d{2})\s*$', text))
    if len(headings) != 1:
        raise ValueError('south_hill_market_title_unresolved')
    heading, printed_year = next(iter(headings))
    if (_FAMILIES[heading.lower()], int(printed_year)) != identity:
        raise ValueError('south_hill_market_document_year_conflict')
    flat = ' '.join(text.split())
    if _STATUS.search(flat):
        raise ValueError('south_hill_market_status_unresolved')
    dates = {_date(match.groups()) for match in re.finditer(_DATE, flat, re.I)}
    if len(dates) != 1:
        raise ValueError('south_hill_market_date_conflict')
    day = next(iter(dates))
    if day.year != identity[1]:
        raise ValueError('south_hill_market_document_year_conflict')
    schedules = list(_SCHEDULE.finditer(flat))
    if not schedules:
        raise ValueError('south_hill_market_time_unresolved')
    starts, ends = [], []
    for match in schedules:
        if _date(match.groups()[:4]) != day:
            raise ValueError('south_hill_market_date_conflict')
        start, end = _clock(day, match[5]), _clock(day, match[6])
        if not timedelta(0) < end - start <= timedelta(hours=12):
            raise ValueError('south_hill_market_time_conflict')
        starts.append(start)
        ends.append(end)
    begins, finishes = earliest_published_time(*starts), earliest_published_time(*ends)
    if finishes <= begins:
        raise ValueError('south_hill_market_time_conflict')
    if len(set(starts)) > 1 or len(set(ends)) > 1:
        _log('warning', document_url=document_url, reason='earlier_explicit_same_date_time_selected')
    if finishes <= current or begins > current + timedelta(days=LOOKAHEAD_DAYS):
        return None
    venues = {(m[1], m[2].strip().rstrip('.')) for m in _VENUE.finditer(flat)}
    if len(venues) != 1:
        raise ValueError('south_hill_market_address_unresolved')
    venue, street = next(iter(venues))
    # Both document layouts explicitly identify South Hill. State comes from
    # this exact Town source; no ZIP code, office address or coordinates added.
    address = street + ', South Hill, VA'
    occurrence = f'south_hill_market:{identity[0]}:{day.isoformat()}'
    row = record(f'{heading} {printed_year}', begins.isoformat(), finishes.isoformat(),
                 venue, address, 'South Hill', CALENDAR, occurrence, 'Events',
                 tz=TIMEZONE, retain_until_end=True)
    if row is None:
        return None
    # Keep the public schedule and venue sentences. Vendor application fields,
    # contact instructions and the $25 stall fee never become admission facts.
    public_schedule = next((m.group(0) for m in schedules
                            if 'will take place' in m.group(0).lower()), schedules[0].group(0))
    venue_sentence = re.search(r'\bCome(?: and)?\s+(?:and\s+)?join us at\s+[^!?]{1,180}?Street(?:\s+in South Hill)?\.', flat, re.I)
    description = public_schedule.rstrip('.') + '.'
    if venue_sentence:
        description += ' ' + venue_sentence.group(0)
    row.update(timezone=TIMEZONE, description=description[:2000],
               publisher_categories=['Events'],
               location_provenance='publisher_pdf_street_and_named_town_venue')
    attach(row, SOURCE_KEY, facts={})
    return row


def parse_pdf(payload, *, document_url, now=None, deadline_at=None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    _check(deadline_at)
    if not isinstance(payload, bytes) or not payload.startswith(b'%PDF-') or len(payload) > MAX_PDF:
        raise ValueError('invalid_south_hill_market_pdf')
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise ValueError('south_hill_market_pdf_encrypted')
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ValueError('south_hill_market_pdf_page_limit')
        pages = []
        for page in reader.pages:
            _check(deadline_at)
            text = page.extract_text(extraction_mode='layout')
            if not isinstance(text, str) or sum(map(len, pages)) + len(text) > MAX_TEXT:
                raise ValueError('south_hill_market_pdf_text_limit')
            pages.append(text)
    except (PdfReadError, TypeError, KeyError, OverflowError) as error:
        raise ValueError('invalid_south_hill_market_pdf') from error
    _check(deadline_at)
    row = parse_text('\n'.join(pages), document_url=document_url, now=now)
    if row is not None:
        row['publisher_document'] = {'url': document_url, 'sha256': sha256(payload).hexdigest(),
                                     'date_provenance': 'publisher_explicit_year'}
    return row


def collect(source, fetch, *, deadline_at=None, now=None):
    """Return supplemental rows only, through the caller's ordinary transport."""
    if (source.get('source_key') != SOURCE_KEY or source.get('feed_url') != FEED_URL
            or source.get('kind') != 'json' or source.get('platform_adapter') != 'revize'
            or source.get('timezone', TIMEZONE) != TIMEZONE):
        raise ValueError('unregistered_south_hill_market_source')
    current = _now(now)
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))
    _check(deadline)
    urls = discover(fetch(CALENDAR, 'text/html'), now=current)
    rows = {}
    for url in urls:
        _check(deadline)
        try:
            row = parse_pdf(fetch(url, 'application/pdf'), document_url=url,
                            now=current, deadline_at=deadline)
        except Exception as error:
            # Preserve the original transport/parse failure and prevent a
            # partial supplemental set from certifying a combined snapshot.
            family, year = document_identity(url)
            reason = str(error)
            _log('held', id=f'south_hill_market:{family}:{year}', document_url=url,
                 reason=reason if re.fullmatch(r'[a-z_0-9]{3,100}', reason)
                 else 'publisher_document_unavailable')
            raise
        if row is not None:
            previous = rows.get(row['id'])
            if previous and any(previous.get(k) != row.get(k) for k in
                                ('title', 'starts_at', 'ends_at', 'venue_name', 'venue_address')):
                raise ValueError('south_hill_market_occurrence_conflict')
            rows.setdefault(row['id'], row)
        else:
            family, year = document_identity(url)
            _log('excluded', id=f'south_hill_market:{family}:{year}',
                 document_url=url, reason='occurrence_outside_window')
    _check(deadline)
    _log('normalized', documents=len(urls), records=len(rows),
         evidence=[{'id': row['id'], **row['publisher_document']} for row in rows.values()])
    return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))
