"""Publisher-labeled detail facts when Event JSON-LD and microdata are absent.

Only read an actual, individual same-publisher detail page that the complete
calendar listing linked. The date, clock, physical location and title must
all be explicit and unambiguous; do not infer recurrences, event years, time
zones from the server, or locations from unrelated recommendation cards.
This extractor is intentionally narrower than general natural-language dates.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import record
from roomquest.registered_native_content import attach

LABELS = {
    'date': 'date', 'dates': 'date',
    'time': 'time', 'times': 'time',
    'where': 'where', 'location': 'where',
}
MONTH_DAY = r'(?:[A-Za-z]+,?\s+)?([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})'
DAY_MONTH = r'(?:[A-Za-z]+,?\s+)?(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})'
CLOCK = r'(?:0?[1-9]|1[0-2])(?::[0-5]\d)?\s*[ap]m'
UK_POSTCODE = re.compile(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', re.I)
CONTAMINATION = re.compile(
    r'\b(?:online[- ]only|private event|invite[- ]only|members[- ]only|'
    r'dates? (?:tbc|vary)|times? (?:tbc|vary)|to be confirmed|'
    r'select (?:a )?(?:date|time)|various times)\b', re.I)


def _plain(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def _title(soup, main):
    names = [_plain(n.get_text(' ', strip=True)) for n in main.select('h1')]
    names = [n for n in names if n and len(n) <= 240]
    if len(names) == 1:
        return names[0]
    if names:
        return None
    # Some older WordPress themes use H2 for the actual event title. Require
    # its exact agreement with the document's publisher-provided social title
    # (minus the separate site suffix), not arbitrary page prose.
    metas = soup.select('meta[property="og:title"][content]')
    if len(metas) != 1:
        return None
    heading = _plain(metas[0]['content']).split(' - ', 1)[0]
    matches = [_plain(n.get_text(' ', strip=True)) for n in main.select('h2')
               if _plain(n.get_text(' ', strip=True)).casefold() == heading.casefold()]
    return heading if len(matches) == 1 and len(heading) <= 240 else None


def _labeled(main):
    """Extract exact field labels from one fact block; no global body mining."""
    found = {}
    def add(label, raw):
        key = LABELS.get(_plain(label).rstrip(':').casefold())
        if key is None:
            return
        value = _plain(raw)
        if not value:
            return
        found.setdefault(key, []).append(value)

    for node in main.select('p,li'):
        if node.find(['p', 'li']):
            continue
        first = next((c for c in node.children if getattr(c, 'name', None)), None)
        if first is None or first.name not in ('strong', 'b'):
            continue
        label = _plain(first.get_text(' ', strip=True))
        full = _plain(node.get_text(' ', strip=True))
        if label and full.casefold().startswith(label.casefold()):
            add(label, full[len(label):].lstrip(': -–'))
    for dt in main.select('dt'):
        next_node = dt.find_next_sibling('dd')
        if next_node is not None:
            add(dt.get_text(' ', strip=True), next_node.get_text(' ', strip=True))
    for heading in main.select('h2,h3,h4,h5'):
        label = _plain(heading.get_text(' ', strip=True))
        if label.rstrip(':').casefold() not in LABELS:
            continue
        next_node = heading.find_next_sibling(['p', 'div'])
        if next_node is not None and not next_node.find(['h2', 'h3', 'h4', 'h5']):
            add(label, next_node.get_text(' ', strip=True))

    result = {}
    for key, values in found.items():
        unique = set(values)
        if len(unique) != 1:
            return None
        result[key] = values[0]
    return result


def _date_piece(text):
    text = _plain(text)
    for pattern, fmt in ((MONTH_DAY, '%B %d %Y'), (DAY_MONTH, '%d %B %Y')):
        match = re.fullmatch(pattern, text, re.I)
        if not match:
            continue
        try:
            value = (f'{match[1]} {match[2]} {match[3]}'
                     if fmt == '%B %d %Y' else f'{match[1]} {match[2]} {match[3]}')
            return datetime.strptime(value, fmt).date()
        except ValueError:
            return None
    return None


def _day(text):
    # A two-date field is acceptable only if both dates agree. Date ranges,
    # month-wide exhibitions and multi-performance schedules remain held.
    text = _plain(text)
    date = _date_piece(text)
    if date:
        return date
    # Only a fully repeated explicit date (not a short range) is eligible.
    for sep in (' - ', ' – ', ' — '):
        if sep in text:
            first, second = text.split(sep, 1)
            a, b = _date_piece(first), _date_piece(second)
            if a is not None and a == b:
                return a
    return None


def _time_range(text, day):
    match = re.fullmatch(r'(' + CLOCK + r')\s*[-–—]\s*(' + CLOCK + r')', _plain(text), re.I)
    if not match:
        return None
    try:
        def parse(raw):
            compact = _plain(raw).replace(' ', '').upper()
            return datetime.strptime(compact, '%I:%M%p' if ':' in compact else '%I%p').time()
        zone = ZoneInfo('Europe/London')
        starts = datetime.combine(day, parse(match[1])).replace(tzinfo=zone)
        ends = datetime.combine(day, parse(match[2])).replace(tzinfo=zone)
        for item in (starts, ends):
            if (item.utcoffset() != item.replace(fold=1).utcoffset()
                    or item.astimezone(timezone.utc).astimezone(zone) != item):
                return None
        return (starts, ends) if ends > starts else None
    except (ValueError, OverflowError):
        return None


def _physical_place(soup, where):
    """Use this detail's physical address or one agreeing publisher footer."""
    if CONTAMINATION.search(where):
        return None
    postal = UK_POSTCODE.search(where)
    site = soup.select('meta[property="og:site_name"][content]')
    site_name = _plain(site[0]['content']) if len(site) == 1 else ''
    candidates = []
    if postal:
        candidates.append(where)
    # The footer can complete a room-only location label, but must identify
    # that exact publisher/venue by name and state London + a UK postcode.
    if not postal and site_name and site_name.casefold() in where.casefold():
        for node in soup.select('footer address,footer [itemprop="address"],footer .contact-address'):
            value = _plain(node.get_text(' ', strip=True))
            if (site_name.casefold() in value.casefold() and UK_POSTCODE.search(value)
                    and re.search(r'\bLondon\b', value, re.I)):
                candidates.append(value)
    if len(candidates) != 1:
        return None
    value = candidates[0]
    postal = UK_POSTCODE.search(value)
    if not postal:
        return None
    # The main detail or the verified footer must also prove which city the
    # postcode belongs to. Never silently assign an arbitrary UK town to London.
    if not re.search(r'\bLondon\b', value, re.I):
        footer = _plain(' '.join(n.get_text(' ', strip=True) for n in soup.select('footer')))
        if 'London' not in footer or postal.group().casefold() not in footer.casefold():
            return None
    # Require a published physical street, not merely a postcode or venue brand.
    if not re.search(r'\b(?:\d{1,5}\s+[A-Za-z]|[A-Za-z]+\s+(?:Road|Street|Lane|Square|Drive|Way))\b',
                     value, re.I):
        return None
    venue = where.split(' - ', 1)[0].strip().rstrip(',')
    if not venue or len(venue) > 180:
        return None
    return venue, _plain(value + (', London' if not re.search(r'\bLondon\b', value, re.I) else '')
                         + ', United Kingdom')


def _hnm_theme_event(source, soup, main, url, title):
    """Read finite HNM-theme events and classify non-discrete schedules.

    The same theme contract owns pagination and its public detail widget.
    Only fully dated, timed ranges become rows. Explicit daily/weekly or
    variable-time programs complete as intentional non-discrete exclusions.
    """
    scripts = []
    for node in soup.select('script[src]'):
        target = urljoin(url, node.get('src', ''))
        if urlsplit(target).path.endswith(
                '/wp-content/themes/horniman-theme/assets/js/main.min.js'):
            scripts.append(target)
    widgets = main.select('.event-details-widget')
    if (len(scripts) != 1 or len(widgets) != 1
            or not re.fullmatch(r'/event/[^/]+/', urlsplit(url).path)):
        return None
    fields = {}
    for row in widgets[0].select(':scope > .event-details-row'):
        labels = row.select(':scope > .h3')
        values = row.select(':scope > .event-details-line')
        if len(labels) != 1 or len(values) != 1:
            continue
        label = _plain(labels[0].get_text(' ', strip=True)).casefold()
        value = _plain(values[0].get_text(' ', strip=True))
        if label not in ('dates', 'times', 'location'):
            continue
        if label in fields or not value:
            return None
        fields[label] = value
    if not all(fields.get(key) for key in ('dates', 'times', 'location')):
        return None
    dates, times = fields['dates'], fields['times']
    # These are genuine programs/displays, but not one safely enumerable
    # occurrence. Complete them explicitly instead of inventing recurrence.
    if (CONTAMINATION.search(dates) or CONTAMINATION.search(times)
            or not re.search(r'\b20\d{2}\b', dates)
            or re.search(r'\b(?:daily|weekly|monthly|every|sundays?|mondays?|tuesdays?'
                         r'|wednesdays?|thursdays?|fridays?|saturdays?)\b', dates, re.I)):
        return []
    start_day = end_day = _date_piece(dates)
    if start_day is None:
        pairs = []
        for separator in (' - ', ' – ', ' — '):
            if separator in dates:
                left, right = dates.split(separator, 1)
                pairs.append((_date_piece(left), _date_piece(right)))
        if len(pairs) != 1 or None in pairs[0]:
            return None
        start_day, end_day = pairs[0]
    normalized_times = times.replace('.', ':')
    match = re.fullmatch(r'(' + CLOCK + r')\s*[-–—]\s*(' + CLOCK + r')',
                         normalized_times, re.I)
    if not match:
        return None
    try:
        def clock(raw):
            compact = _plain(raw).replace(' ', '').upper()
            return datetime.strptime(compact, '%I:%M%p' if ':' in compact else '%I%p').time()
        zone = ZoneInfo('Europe/London')
        start = datetime.combine(start_day, clock(match[1])).replace(tzinfo=zone)
        end = datetime.combine(end_day, clock(match[2])).replace(tzinfo=zone)
    except (ValueError, OverflowError):
        return None
    if end <= start:
        return None
    for item in (start, end):
        if (item.utcoffset() != item.replace(fold=1).utcoffset()
                or item.astimezone(timezone.utc).astimezone(zone) != item):
            return None

    sites = soup.select('meta[property="og:site_name"][content]')
    if len(sites) != 1:
        return None
    site = _plain(sites[0]['content'])
    venue_candidates = []
    for column in soup.select('footer .footer-col'):
        names = column.select(':scope > .h5')
        addresses = column.select(':scope > .footer-address')
        if len(names) != 1 or len(addresses) != 1:
            continue
        published_name = _plain(names[0].get_text(' ', strip=True))
        comparable = lambda value: _plain(value).replace('&', 'and').casefold()
        if comparable(published_name) == comparable(site):
            venue_candidates.append(_plain(addresses[0].get_text(' ', strip=True)))
    if len(venue_candidates) != 1:
        return None
    address = venue_candidates[0]
    if (not UK_POSTCODE.search(address) or not re.search(r'\bLondon\b', address, re.I)
            or not re.search(r'\b\d{1,5}\s+[A-Za-z].*\b(?:Road|Street|Lane|Square|Drive|Way)\b',
                             address, re.I)):
        return None
    location = fields['location']
    if len(location) > 160 or CONTAMINATION.search(location):
        return None
    venue = site + ' — ' + location
    row = record(title, start.isoformat(), end.isoformat(), venue,
                 address + ', United Kingdom', 'London', url,
                 url + '#visible-event', tz='Europe/London')
    if row is None:
        return []
    row['timezone'] = 'Europe/London'
    attach(row, source, evidence_url=url)
    return [row]


def read(source, soup, url):
    main = soup.find('main') or soup.find(attrs={'role': 'main'})
    if main is None:
        return None
    title = _title(soup, main)
    if title is None:
        return None
    hnm = _hnm_theme_event(source, soup, main, url, title)
    if hnm is not None:
        return hnm
    fields = _labeled(main)
    if not fields or not all(fields.get(key) for key in ('date', 'time', 'where')):
        return None
    if any(CONTAMINATION.search(fields[key]) for key in ('date', 'time', 'where')):
        return None
    day = _day(fields['date'])
    if day is None:
        return None
    clock = _time_range(fields['time'], day)
    place = _physical_place(soup, fields['where'])
    if clock is None or place is None:
        return None
    start, end = clock
    venue, address = place
    row = record(title, start.isoformat(), end.isoformat(), venue, address,
                 'London', url, url + '#visible-event', tz='Europe/London')
    if row is None:
        return []
    row['timezone'] = 'Europe/London'
    attach(row, source, evidence_url=url)
    return [row]
