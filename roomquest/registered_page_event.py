"""Bind one Event to its own publisher detail document.

Unidentified Events require agreeing canonical/OG metadata. An explicitly
linked Event must already name the fetched document. No foreign identity is
overwritten. Time repair requires exact independently displayed schedule facts.
"""
from copy import deepcopy
from datetime import datetime, date, timedelta, timezone
from html import unescape
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/London')
UTC_STAMP = re.compile(r'(20\d\d-\d\d-\d\d)UTC(\d\d:\d\d:\d\d)\Z')
LOCAL_STAMP = re.compile(r'20\d\d-\d\d-\d\d[ T]\d\d:\d\d:\d\d\Z')
CLOCK = r'(?:0?[1-9]|1[0-2])(?::[0-5]\d)?\s*[ap]m'
SHORT_DAY = re.compile(r'([A-Za-z]{3})\s+(\d{1,2})\s+([A-Za-z]{3})\Z')
FULL_RANGE = re.compile(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d\d)\s*·\s*('
                        + CLOCK + r')\s*[-–—]\s*(' + CLOCK + r')\Z', re.I)
UK_POSTCODE = re.compile(r'[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\Z', re.I)
TABLE_DAY = re.compile(r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d\d)\Z', re.I)


def _plain(value):
    return re.sub(r'\s+', ' ', unescape(value)).strip() if isinstance(value, str) else ''


def _title(value):
    return _plain(value).casefold()


def _page_title_matches(structured, visible):
    """Match an exact H1 or a bounded publisher season/program prefix."""
    structured_text = _plain(structured)
    visible_title = _title(visible)
    if _title(structured_text) == visible_title:
        return True
    prefix, separator, suffix = structured_text.partition(':')
    return bool(separator and len(prefix) <= 48
                and re.search(r'\b20\d\d\b', prefix)
                and _title(suffix) == visible_title)


def _clock(value):
    value = re.sub(r'\s+', '', value).upper()
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def _local(day, clock):
    local = datetime.combine(day, clock).replace(tzinfo=ZONE)
    if (local.utcoffset() != local.replace(fold=1).utcoffset()
            or local.astimezone(timezone.utc).astimezone(ZONE).replace(tzinfo=None)
            != local.replace(tzinfo=None)):
        raise ValueError('html_calendar_clock_ambiguous')
    return local


def _physical_uk(event, url):
    place = event.get('location')
    if not isinstance(place, dict):
        return None
    address = place.get('address')
    if not isinstance(address, dict):
        return None
    country = _title(address.get('addressCountry'))
    hostname = (urlsplit(url).hostname or '').casefold()
    if (not _plain(place.get('name')) or not _plain(address.get('streetAddress'))
            or not _plain(address.get('addressLocality'))
            or not UK_POSTCODE.fullmatch(_plain(address.get('postalCode')))
            or (country and country not in ('gb', 'uk', 'united kingdom'))
            or (not country and not hostname.endswith('.uk'))):
        return None
    return place


def _dated_session(day_label, anchor):
    match = SHORT_DAY.fullmatch(_plain(day_label))
    if not match:
        raise ValueError('html_calendar_clock_conflict')
    weekday, day, month = match.groups()
    matches = []
    for year in (anchor.year, anchor.year + 1):
        try:
            candidate = datetime.strptime(f'{day} {month} {year}', '%d %b %Y').date()
        except ValueError:
            continue
        if (anchor <= candidate <= anchor + timedelta(days=365)
                and candidate.strftime('%a').casefold() == weekday.casefold()):
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError('html_calendar_clock_conflict')
    return matches[0]


def _one(node, selector):
    found = node.select(selector)
    if len(found) != 1:
        raise ValueError('html_calendar_clock_conflict')
    return _plain(found[0].get_text(' ', strip=True))


def _session_rows(event, root, anchor, place):
    """Every actual dated row must be accounted for, not just the first."""
    blocks = root.select('.event-time-container .event-time')
    if not blocks or len(blocks) > 500 or event.get('endDate'):
        raise ValueError('html_calendar_clock_conflict')
    venue = _title(place['name'])
    # A publisher can put audience names in a nominal location column. Only
    # recognize these two explicit session labels when the independent event
    # narrative also names that session type. Retain the structured venue.
    narrative = ' '.join(_plain(p.get_text(' ', strip=True)) for p in root.select('p,li')
                         if not p.find_parent(class_='event-time-container')
                         and not p.find_parent(['footer', 'nav', 'aside', 'form']))
    audience = {'family session': 'Family session', 'adult session': 'Adult session'}
    rows = []
    for block in blocks:
        day = _dated_session(_one(block, '.date'), anchor.date())
        clock = _one(block, '.time')
        if not re.fullmatch(CLOCK, clock, re.I):
            raise ValueError('html_calendar_clock_conflict')
        site = _title(_one(block, '.location'))
        # Explicit room within the same named site is permitted, not another
        # venue's address or a substring match on an unrelated place.
        label = None
        if site != venue and not re.fullmatch(r'.+?\s*[-–—]\s*' + re.escape(venue), site):
            if site in audience and re.search(r'\b' + re.escape(site) + r's?\b', narrative, re.I):
                label = audience[site]
            else:
                raise ValueError('html_calendar_venue_conflict')
        starts = _local(day, _clock(clock))
        if (not rows and starts.astimezone(timezone.utc) != anchor.astimezone(timezone.utc)
                or rows and starts <= rows[-1][0]):
            raise ValueError('html_calendar_clock_conflict')
        rows.append((starts, label))
    return rows


def _visible_range(event, heading, place):
    """Corroborate a UK naive start/end against one title-local full range."""
    start, end = event.get('startDate'), event.get('endDate')
    if (not isinstance(start, str) or not LOCAL_STAMP.fullmatch(start)
            or not isinstance(end, str) or not LOCAL_STAMP.fullmatch(end)):
        raise ValueError('html_calendar_clock_conflict')
    begins, finishes = datetime.fromisoformat(start), datetime.fromisoformat(end)
    ranges = []
    for node in heading.parent.select('p'):
        value = _plain(node.get_text(' ', strip=True))
        if len(value) <= 160 and (match := FULL_RANGE.fullmatch(value)):
            ranges.append(match)
    if len(ranges) != 1:
        raise ValueError('html_calendar_clock_conflict')
    day, month, year, first, last = ranges[0].groups()
    visible_day = datetime.strptime(f'{day} {month} {year}', '%d %B %Y').date()
    starts = _local(visible_day, _clock(first))
    ends = _local(visible_day, _clock(last))
    if (starts.replace(tzinfo=None) != begins or ends.replace(tzinfo=None) != finishes
            or ends <= starts):
        raise ValueError('html_calendar_clock_conflict')
    return starts, ends


def _visible_occurrences(event, root):
    """Read a complete Date/Time table that corroborates a naive Event span.

    Some UK venue templates publish the first and last occurrence as the
    JSON-LD start/end, then enumerate every actual performance in one ordinary
    server-rendered table.  Retain each factual start and do not reinterpret
    the last occurrence's start as a verified duration.
    """
    candidates = []
    for table in root.select('table'):
        rows = table.select('tr')
        if not rows:
            continue
        headings = [_plain(cell.get_text(' ', strip=True)).casefold()
                    for cell in rows[0].select('th,td')]
        if headings == ['date', 'time']:
            candidates.append(rows)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError('html_calendar_clock_conflict')
    starts = []
    for row in candidates[0][1:]:
        cells = row.select('th,td')
        if len(cells) == 2:
            # A schedule date may be split across leading inline elements and
            # followed by a tooltip/popup describing accessibility features.
            # Bind only an exact leading date assembled from simple inline
            # fields; never admit arbitrary trailing prose into the clock.
            leading = []
            for child in cells[0].contents:
                if isinstance(child, str):
                    if child.strip():
                        leading.append(child)
                    continue
                if child.name not in ('span', 'time'):
                    break
                leading.append(child.get_text(' ', strip=True))
            date_value = _plain(' '.join(leading))
            if not TABLE_DAY.fullmatch(date_value):
                date_value = _plain(cells[0].get_text(' ', strip=True))
            cells = [date_value, _plain(cells[1].get_text(' ', strip=True))]
        else:
            cells = []
        if len(cells) != 2 or not (day_match := TABLE_DAY.fullmatch(cells[0])) \
                or not re.fullmatch(CLOCK, cells[1], re.I):
            raise ValueError('html_calendar_clock_conflict')
        weekday, day, month, year = day_match.groups()
        try:
            date_value = datetime.strptime(f'{day} {month} {year}', '%d %B %Y').date()
        except ValueError as exc:
            raise ValueError('html_calendar_clock_conflict') from exc
        if date_value.strftime('%A').casefold() != weekday.casefold():
            raise ValueError('html_calendar_clock_conflict')
        starts.append(_local(date_value, _clock(cells[1])))
    if not starts or len(starts) > 500 or any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError('html_calendar_clock_conflict')
    first, last = event.get('startDate'), event.get('endDate')
    if (not isinstance(first, str) or not LOCAL_STAMP.fullmatch(first)
            or not isinstance(last, str) or not LOCAL_STAMP.fullmatch(last)
            or starts[0].replace(tzinfo=None) != datetime.fromisoformat(first)
            or starts[-1].replace(tzinfo=None) != datetime.fromisoformat(last)):
        raise ValueError('html_calendar_clock_conflict')
    return starts


def candidates(nodes, soup, url, is_event, public_url, url_key):
    """Return only independently bound, normalized occurrences, or None."""
    events = [node for node in nodes if is_event(node)]
    if len(events) != 1:
        return None
    event = events[0]
    explicit = [event.get(key) for key in ('url', '@id')
                if event.get(key) not in (None, '')]
    if explicit and any(not (link := public_url(raw, url))
                        or url_key(link) != url_key(url) for raw in explicit):
        raise ValueError('html_calendar_detail_identity_conflict')
    # Both metadata families, if supplied, must agree with the actual fetch.
    # No URL is inferred from the H1 or the source's domain.
    metadata = [node.get('href') for node in soup.select('link[rel="canonical"]')]
    metadata += [node.get('content') for node in soup.select('meta[property="og:url"]')]
    if not explicit and not metadata:
        return None
    if metadata and any(not (link := public_url(raw, url)) or url_key(link) != url_key(url)
           for raw in metadata):
        raise ValueError('html_calendar_detail_identity_conflict')
    root = soup.find('main') or soup.find(attrs={'role': 'main'}) or soup.body
    if root is None:
        return None
    headings = [node for node in root.select('h1')
                if not node.find_parent(['footer', 'nav', 'aside', 'form'])]
    if (len(headings) != 1 or not _title(event.get('name'))
            or not _page_title_matches(event['name'],
                                       headings[0].get_text(' ', strip=True))):
        return None
    fixed = deepcopy(event)
    fixed['url'] = url
    fixed['@id'] = (urljoin(url, str(event['@id']).strip())
                    if event.get('@id') not in (None, '') else url + '#event')
    if len(fixed['@id']) > 180:
        raise ValueError('html_calendar_event_identity_limit')
    # Explicit cancellation/online evidence remains authoritative in the
    # ordinary parser, even where an event no longer lists a clock.
    if (str(event.get('eventStatus', '')).endswith(('EventCancelled', 'EventPostponed'))
            or str(event.get('eventAttendanceMode', '')).endswith('OnlineEventAttendanceMode')):
        return [fixed]
    raw = event.get('startDate')
    if not isinstance(raw, str):
        return None
    if match := UTC_STAMP.fullmatch(raw):
        place = _physical_uk(event, url)
        if place is None:
            raise ValueError('html_calendar_clock_conflict')
        anchor = datetime.fromisoformat(match[1] + 'T' + match[2]).replace(tzinfo=timezone.utc)
        rows = _session_rows(event, root, anchor.astimezone(ZONE), place)
        return [dict(fixed, startDate=starts.isoformat(),
                     name=f"{_plain(fixed['name'])} — {label}" if label else fixed['name'])
                for starts, label in rows]
    if LOCAL_STAMP.fullmatch(raw):
        place = _physical_uk(event, url)
        if place is None:
            raise ValueError('html_calendar_clock_conflict')
        occurrences = _visible_occurrences(event, root)
        if occurrences is not None:
            rows = []
            for starts in occurrences:
                row = dict(fixed, startDate=starts.isoformat())
                row.pop('endDate', None)
                rows.append(row)
            return rows
        starts, ends = _visible_range(event, headings[0], place)
        return [dict(fixed, startDate=starts.isoformat(), endDate=ends.isoformat())]
    # Ordinary ISO-offset facts need no additional local-time assumption.
    # A multi-session control cannot silently be reduced to its first record.
    if len(root.select('.event-time-container .event-time')) > 1:
        raise ValueError('html_calendar_clock_conflict')
    try:
        starts = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if starts.tzinfo is None or starts.utcoffset() is None:
        return None
    return [fixed]


def description_only_controls(value):
    """Relax raw JSON control characters only for narrative CR/LF/tab."""
    def visit(node, narrative=False):
        if isinstance(node, str):
            return all(ord(ch) >= 32 or (narrative and ch in '\r\n\t') for ch in node)
        if isinstance(node, dict):
            return all(visit(key) and visit(child, key == 'description' and isinstance(child, str))
                       for key, child in node.items())
        if isinstance(node, list):
            return all(visit(child) for child in node)
        return True
    return visit(value)
