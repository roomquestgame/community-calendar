"""Reviewed public recreation programs in Egg Harbor Township and Ocean City.

MyRec contributes individual dated reservations, matched to the complete program
description and its explicit drop-in policy.  No dates are inferred from the
seasonal registration range.  Ocean City's current winter PDF explicitly gives
a weekly grid.  Its visually reviewed cells are bound to the document hash;
each class keeps its complete native definition.  The annual closure document
limits the reviewed occurrence horizon to 2026, rather than projecting last
year's holiday exceptions into January 2027.

Every request uses the caller's existing guarded transport.  Changed PDF
editions, incomplete descriptions and oversized snapshots fail, never truncate.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import logging
import re
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_venues import narrative
from roomquest.mapsee_adapter import record, timestamp


log = logging.getLogger(__name__)
ZONE = 'America/New_York'
EHT = 'egg_harbor_township_recreation_nj'
OC = 'ocean_city_aquatic_fitness_nj'
SOURCES = {
    EHT: ('https://eggharbornj.myrec.com/info/calendar/list.aspx?FacilityID=14784&AreaID=0',
          'html', 'html'),
    OC: ('https://www.ocnj.us/departments/CommunityServices/Aquatic-and-Fitness-Center',
         'html', 'html'),
}
ALLOWED_HOSTS = {EHT: ('eggharbornj.myrec.com',), OC: ('www.ocnj.us',)}
MAX_RECORDS = 500
MAX_DESCRIPTION = 12000
MAX_HTML = 1_000_000
MAX_PDF = 1_000_000
EHT_PROGRAMS = {
    '30031': 'Adult Open Gym Programs',
    '30076': 'Mindful Chair and Standing Yoga',
}
EHT_PROGRAM_BASE = 'https://eggharbornj.myrec.com/info/activities/program_details.aspx?ProgramID='
OC_PROGRAMS = 'https://www.ocnj.us/AnF-Programs'
OC_DOCUMENT = 'https://www.ocnj.us/media/Aquatic%20Fitness/2026-27%20Winter%20Group-Ex%20Schedule.pdf'
OC_DOCUMENT_SHA256 = 'dae55ff30cd3b9704490eec574fc2bce68961ce9b9c2d705d6d4ab72c8c834cc'
OC_CLOSURES = 'https://www.ocnj.us/media/Aquatic%20Fitness/2026%20AFC%20Holidays%20Early%20Closings.pdf'
OC_CLOSURES_SHA256 = '188d9396ca99c7f245c287688363002977fe40200ac3ad8929984dca2f2862fa'
OC_SEASON_START = date(2026, 11, 9)
OC_SEASON_END = date(2027, 3, 7)
OC_REVIEWED_THROUGH = date(2026, 12, 31)
OC_CLOSED = {date(2026, 11, 26), date(2026, 12, 25)}
OC_EARLY_CLOSE = {date(2026, 12, 24): time(13), date(2026, 12, 31): time(13)}

# Publisher facility identities and full streets, independently matched against
# NJ OGIS on 2026-11-14.  Evidence includes the exact queries and full responses.
# EHT is a PointAddress.  OC is interpolated StreetAddress, so its visible venue
# qualifier identifies the approximate map position.  These pins cannot be
# reused for another source/venue/street or another room's address.
VENUES = {
    EHT: ('EHT Community Center',
          '5045 English Creek Avenue, Egg Harbor Township, NJ 08234', 'Egg Harbor Township'),
    OC: ('Ocean City Aquatic & Fitness Center',
         '1735 Simpson Avenue, Ocean City, NJ 08226', 'Ocean City'),
}
REVIEWED_LOCATIONS = {
    EHT: ('EHT Community Center', '5045 English Creek Avenue, Egg Harbor Township, NJ 08234',
          39.399948000003, -74.633616000001, 'reviewed_nj_ogis_point_address'),
    OC: ('Ocean City Aquatic & Fitness Center', '1735 Simpson Avenue, Ocean City, NJ 08226',
         39.271761871741, -74.59048756658, 'reviewed_nj_ogis_street_address'),
}
EXCLUDED = re.compile(r'\b(?:cancell?ed|postponed|private|members?[- ]only|sold[- ]out)\b', re.I)

# Monday=0.  Exact current PDF cells; an unknown end stays unknown.  One-hour
# markers are present only on the four indicated land classes.  Water Exercise
# ends come from the publisher's complete current HTML description.
# Pilates/Core is the publisher's combined definition for Pilates.  A named
# Barre/Pilates combination retains both complete definitions, without inventing
# a combined narrative.  Other undefined class variants remain explicit holds.
OC_GRID = (
    (0, '06:00', 'Strength', ('Strength',), None, 'Marissa', 'Group Ex'),
    (0, '09:00', 'Cardio-Sculpt', ('Cardio-Sculpt',), None, 'Bonnie', 'Group Ex'),
    (0, '10:00', 'Zumba Toning', ('Zumba Toning',), None, 'Aggie/Joan', 'Group Ex'),
    (0, '11:05', 'Water Exercise', (), 45, 'TBA', 'Pool'),
    (0, '12:00', 'Water Exercise', (), 45, 'TBA', 'Pool'),
    (0, '17:30', 'TBW', ('T B W',), None, 'Brielle', 'Group Ex'),
    (1, '05:15', 'TBW', ('T B W',), None, 'Sue', 'Group Ex'),
    (1, '07:00', 'Functional Fitness', ('Functional Fitness',), None, 'Chrissy/Josh', 'Group Ex'),
    (1, '08:00', 'Functional Stretch', ('Functional Stretch',), None, 'Chrissy', 'Group Ex'),
    (1, '09:00', 'TBW', ('T B W',), None, 'Erica', 'Group Ex'),
    (1, '10:00', 'Strength', ('Strength',), None, 'Bonnie', 'Group Ex'),
    (1, '11:05', 'Water Exercise', (), 45, 'Jenny S', 'Pool'),
    (1, '12:00', 'Water Exercise', (), 45, 'Mary', 'Pool'),
    (1, '12:00', 'Chair Yoga', ('Chair Yoga',), None, 'Marissa', 'Group Ex'),
    (1, '15:45', 'Zumba Gold', ('Zumba Gold',), None, 'Mark', 'Group Ex'),
    (1, '16:45', 'Zumba', ('Zumba',), 60, 'Mark', 'Group Ex'),
    (1, '18:00', 'Gentle Yoga', ('Gentle Yoga',), None, 'Deb M', 'Group Ex'),
    (2, '06:00', 'Yoga', ('Yoga',), None, 'Sharon', 'Group Ex'),
    (2, '07:00', 'Pilates', ('Pilates/Core',), None, 'Sharon', 'Group Ex'),
    (2, '08:00', 'TBW', ('T B W',), None, 'Aggie', 'Group Ex'),
    (2, '10:00', 'Strength', ('Strength',), None, 'Shelley', 'Group Ex'),
    (2, '11:05', 'Water Exercise', (), 45, 'Bonnie', 'Pool'),
    (2, '12:00', 'Water Exercise', (), 45, 'Jenny S', 'Pool'),
    (2, '17:30', 'TBW', ('T B W',), None, 'Jen N/Shannon', 'Group Ex'),
    (3, '08:00', 'Yoga', ('Yoga',), None, 'Nancy', 'Group Ex'),
    (3, '09:00', 'Barre/Pilates', ('Barre', 'Pilates/Core'), None, 'Lisa', 'Group Ex'),
    (3, '10:00', 'Strength', ('Strength',), None, 'Bonnie', 'Group Ex'),
    (3, '11:05', 'Water Exercise', (), 45, 'Bonnie', 'Pool'),
    (3, '12:00', 'Water Exercise', (), 45, 'Bonnie', 'Pool'),
    (3, '12:00', 'Smooth Weights', ('Smooth Weights',), None, 'Shelley', 'Group Ex'),
    (3, '17:30', 'Wheels & Steel', ('Wheels & Steel',), None, 'Brielle', 'Cycle Rm'),
    (4, '06:00', 'Yoga', ('Yoga',), None, 'Sharon', 'Group Ex'),
    (4, '07:00', 'Strength', ('Strength',), None, 'Brad', 'Group Ex'),
    (4, '08:00', 'Barre', ('Barre',), None, 'Erica', 'Group Ex'),
    (4, '09:00', 'Zumba', ('Zumba',), None, 'Mark', 'Group Ex'),
    (4, '10:00', 'Cardio-Sculpt', ('Cardio-Sculpt',), None, 'Deb M', 'Group Ex'),
    (4, '11:00', 'Yoga', ('Yoga',), None, 'Deb M', 'Group Ex'),
    (4, '11:05', 'Water Exercise', (), 45, 'TBA', 'Pool'),
    (4, '12:00', 'Smooth Moves', ('Smooth Moves',), None, 'Deb M', 'Group Ex'),
    (5, '07:15', 'Yoga', ('Yoga',), 60, 'Nancy', 'Group Ex'),
    (5, '07:15', 'Barre', ('Barre',), None, 'Marissa', 'Art Ctr'),
    (5, '08:15', 'Zumba', ('Zumba',), 60, 'Aggie', 'Art Ctr'),
    (5, '09:30', 'Step & Sculpt', ('Step & Sculpt',), None, 'Shelley', 'Group Ex'),
    (5, '11:05', 'Water Exercise', (), 45, 'Chris', 'Pool'),
    (6, '09:30', 'Yoga', ('Yoga',), 60, 'TBA', 'Group Ex'),
    (6, '11:05', 'Water Exercise', (), 45, 'Jenny M', 'Pool'),
)
OC_UNDEFINED = ('Cycle', 'Pilates Sculpt', 'Body Sculpt Yoga', 'Drum & Tone',
                'Stretch & Tone', 'Special Needs Drum Fit', 'Barrelates',
                'Interval Step', 'Yin Yoga', 'Chair Pilates/Barre', 'Tabata',
                'Special Needs Dance/Fitness', 'Strength & Sculpt')
OC_DEFINITION_LABELS = (
    'Balance & Flow', 'Barre', 'Boot Camp/Circuit', 'Cardio-Kick', 'Cardio-Sculpt',
    'Chair Yoga', 'Drum Fit', 'Functional Fitness', 'Functional Stretch',
    'Gentle Yoga', 'H I I T', 'Meditation', 'Pilates/Core', 'Power Flow Yoga',
    'Smooth Moves', 'Smooth Weights', 'Step & Sculpt', 'Strength', 'T B W',
    'Wheels & Steel', 'Yoga', 'Zumba', 'Zumba Gold', 'Zumba Toning',
)


def _check(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _complete(text):
    """Validate already-normalized text without parsing literal markup twice."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('publisher_description_missing')
    if len(text) > MAX_DESCRIPTION:
        raise ValueError('publisher_description_limit')
    return text


def _text(node):
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip() if node else ''


def _html(payload):
    if not isinstance(payload, str) or not payload or len(payload) > MAX_HTML:
        raise ValueError('invalid_atlantic_recreation_html')
    return BeautifulSoup(payload, 'html.parser')


def event_url(key, value):
    if key == OC:
        return value == SOURCES[OC][0]
    if key != EHT or not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == 'https' and p.netloc == 'eggharbornj.myrec.com'
                and p.path == '/info/activities/program_details.aspx'
                and re.fullmatch(r'ProgramID=(?:30031|30076)', p.query) is not None
                and re.fullmatch(r'[1-9][0-9]{0,9}', p.fragment) is not None)
    except ValueError:
        return False


def _row(key, title, start, end, url, identity, body, now):
    body = _complete(body)
    if not event_url(key, url):
        raise ValueError('atlantic_recreation_event_identity')
    if end is not None and end <= start:
        raise ValueError('atlantic_recreation_clock_conflict')
    if start >= now + timedelta(days=60) or (end or start + timedelta(hours=3)) <= now:
        return None
    venue, street, city = VENUES[key]
    reviewed = REVIEWED_LOCATIONS.get(key)
    lat = lng = None
    provenance = 'reviewed_venue_street_address_pending_geocode'
    if reviewed and reviewed[:2] == (venue, street):
        lat, lng, provenance = reviewed[2:]
        if provenance == 'reviewed_nj_ogis_street_address':
            venue += ' (approximate map location)'
    result = record(title, start.isoformat(), end.isoformat() if end else None,
                    venue, street, city, url, identity, 'Sports & Fitness',
                    lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
    if result is not None:
        result.update(description=body, timezone=ZONE, attendance_mode='in_person',
                      location_provenance=provenance)
    return result


def _time(value):
    return datetime.strptime(re.sub(r'\s+', ' ', value.strip()).upper(), '%I:%M %p').time()


def _eht_program(pid, payload):
    soup = _html(payload)
    if _text(soup.select_one('h1')) != EHT_PROGRAMS[pid]:
        raise ValueError('eht_program_identity_changed')
    general_node = soup.select_one('#Content_lblDescription')
    if general_node is None:
        raise ValueError('publisher_description_missing')
    general = narrative(general_node)
    if not re.search(r'\bdrop[ -]in\b', general, re.I) or EXCLUDED.search(general):
        log.warning('atlantic_recreation_held program=%s reason=public_drop_in_unconfirmed', pid)
        return {}
    notes = {}
    for node in soup.select('.note-section'):
        heading = _text(node.select_one('h2'))
        if not heading or heading in notes:
            raise ValueError('eht_program_notes_changed')
        notes[heading] = narrative(node)
    catalog = {}
    for row in soup.select('tr'):
        cells = {td.get('data-title'): td for td in row.select('td[data-title]')}
        if 'Activity' not in cells:
            continue
        title = _text(cells['Activity'])
        if EXCLUDED.search(title + ' ' + _text(cells.get('Register'))):
            continue
        if pid == '30031':
            section = ('Open Gym Pickleball' if re.fullmatch(
                r'Pickleball Level [123] \((?:Tuesdays?|Thursdays?)\)', title) else
                'Open Gym Basketball' if title == 'Open Gym Basketball' else None)
            if section is None:
                log.warning('atlantic_recreation_held title=%s reason=unreviewed_open_gym_activity', title)
                continue
            if section not in notes:
                raise ValueError('publisher_description_missing')
            body = general + '\n\n' + notes[section]
        else:
            if title != EHT_PROGRAMS[pid]:
                raise ValueError('eht_activity_identity_changed')
            body = '\n\n'.join([general, *notes.values()])
        eligibility = row.select_one('a.view_availability[href]')
        if eligibility is None:
            raise ValueError('eht_activity_identity_changed')
        match = re.fullmatch(r'view_availability\.aspx\?ActivityID=([1-9]\d{0,9})', eligibility['href'])
        if not match:
            raise ValueError('eht_activity_identity_changed')
        activity_id = match[1]
        clocks = re.search(r'(\d{2}/\d{2}/\d{4})\s+-\s+(\d{2}/\d{2}/\d{4})\s+'
                           r'(\d{1,2}:\d{2}\s+[AP]M)\s+-\s+(\d{1,2}:\d{2}\s+[AP]M)',
                           _text(cells.get('Date/Time')))
        day = {'M': 0, 'Tu': 1, 'W': 2, 'Th': 3, 'F': 4, 'Sa': 5, 'Su': 6}.get(_text(cells.get('Days')))
        if clocks is None or day is None:
            raise ValueError('eht_activity_schedule_changed')
        first, last = (datetime.strptime(clocks[i], '%m/%d/%Y').date() for i in (1, 2))
        starts, ends = _time(clocks[3]), _time(clocks[4])
        if last < first or ends <= starts or title in catalog:
            raise ValueError('eht_activity_schedule_conflict')
        ages = _text(cells.get('Ages'))
        if ages and ages != 'N/A':
            body += '\n\nAges: ' + ages
        catalog[title] = dict(id=activity_id, first=first, last=last, weekday=day,
                              starts=starts, ends=ends, body=_complete(body))
    return catalog


def parse_eht(calendar_html, program_html, *, now):
    soup = _html(calendar_html)
    selected = soup.select('#Content_lstFacilityID option[selected]')
    if len(selected) != 1 or (selected[0].get('value'), _text(selected[0])) != ('14784,0', 'EHT Community Center'):
        raise ValueError('eht_calendar_venue_changed')
    try:
        first, last = (datetime.strptime(soup.select_one('#' + ident)['value'], '%m/%d/%Y').date()
                       for ident in ('Content_txtStartDate', 'Content_txtEndDate'))
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('eht_calendar_window_changed') from exc
    if last < first or (last - first).days > 62 or last < now.astimezone(ZoneInfo(ZONE)).date():
        raise ValueError('eht_calendar_window_changed')
    catalogs = {pid: _eht_program(pid, program_html[pid]) for pid in EHT_PROGRAMS}
    output = {}
    tables = soup.select('table.styled')
    dated_tables = 0
    for table in tables:
        heading = table.select_one('tr.trTitle')
        if heading is None:
            continue
        day = datetime.strptime(_text(heading), '%A %B %d, %Y').date()
        if day.strftime('%A') != _text(heading).split()[0] or not first <= day <= last:
            raise ValueError('eht_calendar_date_conflict')
        dated_tables += 1
        for link in table.select('a[href*="program_details.aspx?ProgramID="]'):
            parsed = urlsplit(urljoin(SOURCES[EHT][0], link['href']))
            pid = parse_qs(parsed.query).get('ProgramID', [''])[0]
            if pid not in EHT_PROGRAMS:
                continue
            if parsed.netloc != ALLOWED_HOSTS[EHT][0] or parsed.path != '/info/activities/program_details.aspx' or parsed.query != 'ProgramID=' + pid:
                raise ValueError('eht_activity_identity_changed')
            title = _text(link)
            prefix = EHT_PROGRAMS[pid] + ' - '
            if not title.startswith(prefix):
                raise ValueError('eht_activity_identity_changed')
            title = title[len(prefix):].strip()
            if EXCLUDED.search(title):
                continue
            activity = catalogs[pid].get(title)
            if activity is None:
                log.warning('atlantic_recreation_held title=%s reason=public_program_unresolved', title)
                continue
            cells = link.find_parent('tr').find_all('td', recursive=False)
            clock = re.fullmatch(r'(\d{1,2}:\d{2}\s+[AP]M)\s*-\s*(\d{1,2}:\d{2}\s+[AP]M)', _text(cells[0])) if cells else None
            if clock is None:
                raise ValueError('eht_occurrence_clock_missing')
            starts, ends = _time(clock[1]), _time(clock[2])
            if (not activity['first'] <= day <= activity['last'] or day.weekday() != activity['weekday']
                    or (starts, ends) != (activity['starts'], activity['ends'])):
                raise ValueError('eht_occurrence_schedule_conflict')
            start = timestamp(datetime.combine(day, starts), ZONE)
            end = timestamp(datetime.combine(day, ends), ZONE)
            identity = f"{EHT}:{pid}:{activity['id']}:{day.isoformat()}:{starts.isoformat()}"
            result = _row(EHT, title, start, end, EHT_PROGRAM_BASE + pid + '#' + activity['id'],
                          identity, activity['body'], now)
            if result:
                if identity in output and output[identity] != result:
                    raise ValueError('eht_occurrence_conflict')
                output[identity] = result
    if not dated_tables:
        raise ValueError('eht_dated_calendar_missing')
    if len(output) > MAX_RECORDS:
        raise ValueError('source_record_limit')
    return list(output.values())


def _pdf_pages(payload, *, pages, deadline_at=None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    _check(deadline_at)
    if not isinstance(payload, bytes) or not payload.startswith(b'%PDF-') or len(payload) > MAX_PDF:
        raise ValueError('invalid_recreation_pdf')
    try:
        reader = PdfReader(BytesIO(payload))
        if reader.is_encrypted or len(reader.pages) != pages:
            raise ValueError('recreation_pdf_page_limit')
        output = []
        for page in reader.pages:
            _check(deadline_at)
            text = ' '.join((page.extract_text() or '').split())
            if not text or len(text) > 60000:
                raise ValueError('recreation_pdf_text_unavailable')
            output.append(text)
        return output
    except PdfReadError as exc:
        raise ValueError('invalid_recreation_pdf') from exc


def _oc_definitions(page):
    if page.count('CLASS DESCRIPTIONS:') != 1 or page.count('How to Register for Classes') != 1:
        raise ValueError('oc_class_descriptions_changed')
    body = page.split('CLASS DESCRIPTIONS:', 1)[1].split('How to Register for Classes', 1)[0].strip()
    pattern = '|'.join(re.escape(value) for value in sorted(OC_DEFINITION_LABELS, key=len, reverse=True))
    matches = list(re.finditer(r'(?<!\w)(' + pattern + r')\s*:', body))
    if [m[1] for m in matches] != list(OC_DEFINITION_LABELS):
        raise ValueError('oc_class_descriptions_changed')
    result = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[match.end():end].strip()
        result[match[1]] = _complete(text)
    return result


def _oc_documents(index_html):
    soup = _html(index_html)
    text = _text(soup)
    if not re.search(r'1735 Simpson (?:Ave(?:nue)?\.?) Ocean City,? NJ 08226', text):
        raise ValueError('oc_venue_address_changed')
    links = {urljoin(SOURCES[OC][0], a['href']).replace(' ', '%20') for a in soup.select('a[href]')}
    if OC_DOCUMENT not in links or OC_CLOSURES not in links:
        raise ValueError('oc_schedule_edition_unreviewed')
    reservations = [p for p in soup.select('p') if _text(p).startswith('Online reservations for exercise classes')]
    if len(reservations) != 1:
        raise ValueError('oc_reservation_policy_changed')
    policy = narrative(reservations[0])
    if 'reserve a time slot' not in policy or '609-398-6900' not in policy:
        raise ValueError('oc_reservation_policy_changed')
    return policy


def parse_ocean_city(index_html, schedule_pdf, closures_pdf, programs_html, *, now, deadline_at=None):
    policy = _oc_documents(index_html)
    if (not isinstance(schedule_pdf, bytes) or sha256(schedule_pdf).hexdigest() != OC_DOCUMENT_SHA256
            or not isinstance(closures_pdf, bytes) or sha256(closures_pdf).hexdigest() != OC_CLOSURES_SHA256):
        raise ValueError('oc_schedule_edition_unreviewed')
    pages = _pdf_pages(schedule_pdf, pages=2, deadline_at=deadline_at)
    closures = _pdf_pages(closures_pdf, pages=1, deadline_at=deadline_at)[0]
    if ('OCEAN CITY AQUATIC & FITNESS CENTER WINTER Nov 9 - March 7, 2027' not in pages[0]
            or 'MATS ARE NOT PROVIDED' not in pages[0]
            or '2026 Holidays and Early Closings' not in closures):
        raise ValueError('oc_schedule_edition_unreviewed')
    for phrase in ('Thanksgiving Day CLOSED', 'Christmas Day CLOSED',
                   'Christmas Eve Open 5am – 1pm', 'New Year’s Eve Open 5am – 1pm'):
        if phrase not in closures:
            raise ValueError('oc_holiday_exceptions_changed')
    definitions = _oc_definitions(pages[1])
    soup = _html(programs_html)
    if OC_DOCUMENT not in {urljoin(OC_PROGRAMS, a['href']).replace(' ', '%20') for a in soup.select('a[href]')}:
        raise ValueError('oc_schedule_edition_unreviewed')
    water_node = soup.select_one('#faq26836entry')
    if water_node is None:
        raise ValueError('publisher_description_missing')
    water = narrative(water_node)
    for phrase in ('The water exercise class is designed', 'Non-swimmers welcome.',
                   '11:05 - 11:50AM', '12:00 – 12:45PM'):
        if phrase not in re.sub(r'\s+', ' ', water):
            raise ValueError('oc_water_description_changed')
    day = max(now.astimezone(ZoneInfo(ZONE)).date(), OC_SEASON_START)
    if day > OC_REVIEWED_THROUGH:
        raise ValueError('oc_holiday_scope_expired')
    last = min((now + timedelta(days=60)).astimezone(ZoneInfo(ZONE)).date(),
               OC_SEASON_END, OC_REVIEWED_THROUGH)
    rows = []
    while day <= last:
        _check(deadline_at)
        if day not in OC_CLOSED:
            for weekday, clock, title, labels, duration, instructor, room in OC_GRID:
                if weekday != day.weekday():
                    continue
                start = timestamp(day.isoformat() + 'T' + clock, ZONE)
                end = start + timedelta(minutes=duration) if duration is not None else None
                close = OC_EARLY_CLOSE.get(day)
                if close is not None and (start.timetz().replace(tzinfo=None) >= close
                                           or end is not None and end.timetz().replace(tzinfo=None) > close):
                    continue
                body = ('\n\n'.join(label + ': ' + definitions[label] for label in labels)
                        if labels else water)
                if labels:
                    body += '\n\nMATS ARE NOT PROVIDED'
                body += '\n\n' + policy + '\n\n' + 'Instructor: ' + instructor + '\nLocation: ' + room
                identity = f'{OC}:{weekday}:{clock}:{title}:{day.isoformat()}'
                result = _row(OC, title, start, end, SOURCES[OC][0], identity, body, now)
                if result:
                    rows.append(result)
                    if len(rows) > MAX_RECORDS:
                        raise ValueError('source_record_limit')
        day += timedelta(days=1)
    log.info('atlantic_recreation_oc_snapshot count=%s reviewed_through=%s undefined_classes=%s',
             len(rows), OC_REVIEWED_THROUGH, ','.join(OC_UNDEFINED))
    return rows


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if profile is None or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
                           source.get('timezone')) != (*profile, ZONE):
        raise ValueError('unregistered_atlantic_recreation_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('atlantic_recreation_timezone_missing')
    _check(deadline_at)
    index = fetch(profile[0], 'text/html')
    if key == EHT:
        programs = {}
        for pid in EHT_PROGRAMS:
            _check(deadline_at)
            programs[pid] = fetch(EHT_PROGRAM_BASE + pid, 'text/html')
        _check(deadline_at)
        return parse_eht(index, programs, now=current)
    # Validate the current links before requesting reviewed PDFs.  No old
    # capture or guessed document URL replaces a removed publisher edition.
    _oc_documents(index)
    _check(deadline_at)
    schedule = fetch(OC_DOCUMENT, 'application/pdf')
    _check(deadline_at)
    closures = fetch(OC_CLOSURES, 'application/pdf')
    _check(deadline_at)
    programs = fetch(OC_PROGRAMS, 'text/html')
    _check(deadline_at)
    return parse_ocean_city(index, schedule, closures, programs, now=current, deadline_at=deadline_at)
