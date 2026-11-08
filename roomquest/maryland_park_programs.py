"""Bounded PDF extraction from the Maryland DNR park pages."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.maryland_sources import md_address, require_source
from roomquest.maryland_public_calendars import TZ, make_row

PATAPSCO = 'patapsco_soldiers_delight_md'
PATUXENT = 'patuxent_freedmans_programs_md'
HOST = 'dnr.maryland.gov'
ROOT = f'https://{HOST}/publiclands'
SOURCES = {
    PATAPSCO: ROOT + '/Pages/central/patapsco.aspx',
    PATUXENT: ROOT + '/Pages/central/patuxentriver.aspx',
}
PDFS = {
    PATAPSCO: {ROOT + '/Documents/Patapsco/' + f for f in
              ('PVSP-calendar-events.pdf', 'PVSP-SD-sneak-peek.pdf')},
    PATUXENT: {ROOT + '/Documents/Patuxent-River/Patuxent_programs.pdf'},
}
MONTH = re.compile(r'(?m)^\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b')
CANCELLED = re.compile(r'\b(?:cancelled|canceled|postponed)\b', re.I)
ADDRESS = re.compile(r'^\d{1,6} [^,]+,\s*[A-Za-z .\'-]+,\s*MD \d{5}$', re.I)
HOUR = r'(?:[1-9]|1[0-2])(?::[0-5]\d)?'
PATUXENT_ADDRESS = md_address('23222 Georgia Avenue, Brookeville, MD 20833')


def _local_time(day, clock, meridiem):
    t = datetime.strptime(clock + meridiem, '%I:%M%p' if ':' in clock else '%I%p').time()
    return datetime.combine(day, t, TZ)


def _range(day, start, end, end_ampm=None, start_ampm=None):
    choices = []
    for a in ([start_ampm] if start_ampm else ['AM', 'PM']):
        for b in ([end_ampm] if end_ampm else ['AM', 'PM']):
            begins, finishes = _local_time(day, start, a), _local_time(day, end, b)
            if timedelta() < finishes - begins <= timedelta(hours=8):
                if end_ampm or 8 <= begins.hour <= finishes.hour <= 19:
                    choices.append((begins, finishes))
    return choices[0] if len(choices) == 1 else (None, None)


def _patapsco(pages, month, url, now):
    text = '\n'.join(page.extract_text() for page in pages[1:])
    # Pair a dated program heading with its immediately adjacent time and street.
    detail = re.compile(r'(?mi)^\s*([A-Za-z]+)\s+(\d{1,2}):\s*([^\n]+)\n'
                        r'\s*([^\n]+)\n\s*([^\n]+)')
    rows = []
    for name, day, title, schedule, address in detail.findall(text):
        if name.casefold() != month.strftime('%B').casefold() or CANCELLED.search(title):
            continue
        time = re.fullmatch(rf'({HOUR})\s*(?:([ap])\.?m\.?\s*)?[-–]\s*({HOUR})\s*([ap])\.?m\.?\s+at\s+(.+?)\s*',
                            schedule, re.I)
        address = address.strip()
        if not time or not ADDRESS.fullmatch(address):
            continue
        first, am, last, pm, venue = time.groups()
        date = month.replace(day=int(day))
        starts, ends = _range(date, first, last, pm.upper()+'M', am.upper()+'M' if am else None)
        row = make_row(title.strip(), starts, ends, venue, md_address(address), url, now)
        if row:
            rows.append(row)
    return rows


def _patuxent(layout, month, url, now):
    if not re.search(r'23222 Georgia Avenue\s*\|\s*Brookeville, Maryland 20833', layout):
        raise ValueError('publisher_venue_address_changed')
    days = next((line for line in layout.splitlines() if 'Sunday' in line and 'Saturday' in line), '')
    if not days:
        raise ValueError('publisher_calendar_structure_changed')
    calendar_lines = layout.splitlines()[layout.splitlines().index(days) + 1:]
    # Day numbers sit at the right edge of each cell. Anchor the column
    # boundaries to a complete week rather than centered weekday labels.
    full_week = next((line for line in calendar_lines if
                      re.fullmatch(r'\s*\d{1,2}(?:\s{12,}\d{1,2}){6}\s*', line)), '')
    edges = [number.end() for number in re.finditer(r'\d{1,2}', full_week)]
    if len(edges) != 7 or any(not 20 <= b - a <= 36 for a, b in zip(edges, edges[1:])):
        raise ValueError('publisher_calendar_structure_changed')
    starts = [0, *edges[:-1]]
    cells = {}
    rows = []
    for line in calendar_lines:
        if 'For more information' in line:
            break
        split = [line[a:b].strip() for a,b in zip(starts, starts[1:]+[None])]
        numbered = {col: int(part) for col, part in enumerate(split)
                    if re.fullmatch(r'\d{1,2}', part)}
        if numbered and list(numbered.values()) == list(range(min(numbered.values()), max(numbered.values()) + 1)):
            cells = numbered
            continue
        if cells:
            rows.append((cells.copy(), split))
    programs = {}
    for day_map, fields in rows:
        for col, day in day_map.items():
            if fields[col]:
                programs.setdefault(day, []).append(fields[col])
    out = []
    for day, lines in programs.items():
        date = month.replace(day=day)
        heading = re.fullmatch(rf'Nature Center\s*\(({HOUR})\s*(?:-|to)\s*({HOUR})\):', lines[0], re.I)
        if not heading or len(lines) != 2 or CANCELLED.search(lines[1]):
            continue
        title = lines[1]
        if re.search(r'\b(?:open|self.guided|scavenger hunt)\b', title, re.I):
            continue
        start, end = _range(date, *heading.groups())
        row = make_row(title, start, end, 'Patuxent River State Park Nature Center',
                       PATUXENT_ADDRESS, url, now)
        if row:
            out.append(row)
    return out


def collect(source, fetch, *, deadline_at=None, now=None):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    now = now or datetime.now(timezone.utc)
    key = source['source_key']
    base = SOURCES[key]
    require_source(source, base, 'html', 'html')
    soup = BeautifulSoup(fetch(base, 'text/html'), 'html.parser')
    links = {urljoin(base, a['href']) for a in soup.select('a[href]')} & PDFS[key]
    if not links:
        raise ValueError('publisher_calendar_structure_changed')
    rows = {}
    for url in sorted(links):
        payload = fetch(url, 'application/pdf')
        try:
            pdf = PdfReader(BytesIO(payload), strict=True)
            if not 1 <= len(pdf.pages) <= 6:
                raise ValueError('publisher_calendar_page_limit')
            layout = pdf.pages[0].extract_text(extraction_mode='layout')
            match = MONTH.search(layout)
            if not match:
                raise ValueError('publisher_calendar_month_unresolved')
            month = datetime.strptime(' '.join(match.groups()), '%B %Y')
            if (month.year, month.month) < (now.astimezone(TZ).year, now.astimezone(TZ).month):
                continue
            parsed = (_patapsco(pdf.pages, month, url, now) if key == PATAPSCO
                      else _patuxent(layout, month, url, now))
        except (PdfReadError, TypeError, OverflowError) as exc:
            raise ValueError('invalid_publisher_pdf') from exc
        for row in parsed:
            rows.setdefault((row['title'], row['starts_at'], row['venue_address']), row)
    return list(rows.values())
