"""Reviewed public schedules with explicit dates, behind normal HTML intake.

No requests are made here outside the injected, robots-aware publisher fetch.
The market's year headings and the theatre's per-performance rows are the date
authority. Neither an advertised season nor generic weekly prose creates dates.
"""
import calendar
from datetime import datetime, timedelta
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record

FOREST = 'https://www.forestfarmersmarket.com/'
ALGONQUIN = 'https://www.algonquinarts.org/calendar.php'
GRAVEGARDEN = 'https://www.gravegarden.org/occevents/'
URLS = (FOREST, ALGONQUIN, GRAVEGARDEN)
MONTH = '(?:' + '|'.join(calendar.month_name[1:]) + ')'
DAY = MONTH + r' \d{1,2}'
CLOCK = r'(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*[ap]m'
MAX_DETAILS = 12


def text(node):
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).strip() if node else ''


def clock(label):
    if label.lower() == 'noon':
        label = '12pm'
    value = label.replace(' ', '').upper()
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def explicit_year_schedule(label):
    """Parse a complete year-heading/date/time schedule; never infer recurrence."""
    token = re.compile(r'(?P<year>20\d{2}) SEASON|(?P<day>' + DAY + r')\s+'
                       r'(?P<start>' + CLOCK + r') to (?P<end>noon|' + CLOCK + ')', re.I)
    year, position, result = None, 0, {}
    for match in token.finditer(label):
        if label[position:match.start()].strip():
            raise ValueError('market_schedule_unverified')
        position = match.end()
        if match['year']:
            year = int(match['year'])
            continue
        if year is None:
            raise ValueError('market_year_unverified')
        day = datetime.strptime(match['day'] + ' ' + str(year), '%B %d %Y').date()
        times = (clock(match['start']), clock(match['end']))
        if times[1] <= times[0] or (day in result and result[day] != times):
            raise ValueError('market_schedule_conflict')
        result[day] = times
    if label[position:].strip() or not result:
        raise ValueError('market_schedule_unverified')
    return result


def forest(soup, today):
    schedules = [explicit_year_schedule(text(node)) for node in
                 soup.select('[data-testid="richTextElement"]')
                 if re.search(r'\b20\d{2} SEASON\b', text(node))]
    if not schedules or any(schedule != schedules[0] for schedule in schedules[1:]):
        raise ValueError('market_schedule_conflict')
    # Both responsive schedules currently repeat this exact publisher location.
    if not re.search(r'\b15583 Forest Road,? Forest,? VA 24551\b', text(soup)):
        raise ValueError('market_address_unverified')
    for day, (start, end) in sorted(schedules[0].items()):
        if today <= day <= today + timedelta(days=60):
            row = record('Forest Farmers Market', datetime.combine(day, start),
                         datetime.combine(day, end), 'Forest Farmers Market',
                         '15583 Forest Road, Forest, VA 24551', 'Forest', FOREST,
                         FOREST, 'Food & Coffee', tz='America/New_York')
            if row:
                row['timezone'] = 'America/New_York'
                yield row


def dated_span(label, *, optional_year=False):
    """A publisher range names its year; it is only a bound on actual rows."""
    weekdays = '(?:' + '|'.join(calendar.day_name) + ')'
    label = re.sub('^' + weekdays + r',\s+', '', label)
    match = re.fullmatch('(' + DAY + r')(?: - (' + DAY + r'))?(?:, (20\d{2}))?', label)
    if not match or (not match[3] and not optional_year):
        raise ValueError('theatre_date_range_unverified')
    if not match[3]:
        return None
    first, last = (datetime.strptime(day + ' ' + match[3], '%B %d %Y').date()
                   for day in (match[1], match[2] or match[1]))
    if last < first or (last - first).days > 370:
        raise ValueError('theatre_date_range_unverified')
    return first, last


def theatre_performances(soup, url, expected_title, today, expected_span=None):
    address = text(soup.select_one('.footer-contact'))
    if not re.match(r'^60 Abe Voorhees Drive Manasquan, NJ 08736(?:\s|$)', address):
        raise ValueError('theatre_address_unverified')
    title = text(soup.select_one('.calendar-show-main-title'))
    if not title or title != expected_title:
        raise ValueError('theatre_title_conflict')
    first, last = dated_span(text(soup.select_one('.calendar-show-date')))
    if expected_span is not None and expected_span != (first, last):
        raise ValueError('theatre_date_range_conflict')
    narrative = text(soup.select_one('.calendar-show-synopsis')) or text(soup.select_one('.calendar-show-description'))
    notice = text(soup.select_one('.calendar-show-notice'))
    if notice:
        narrative += ' ' + notice
    cards = soup.select('.calendar-show-performances .calendar-performances-container')
    if not cards or len(cards) > 120:
        raise ValueError('theatre_performances_unverified')
    for card in cards:
        day_label = text(card.select_one('.calendar-performances-col1'))
        time_label = text(card.select_one('.calendar-performances-col2'))
        if not re.fullmatch(CLOCK, time_label, re.I):
            raise ValueError('theatre_performance_time_unverified')
        try:
            day = datetime.strptime(day_label + ', ' + str(first.year), '%A, %B %d, %Y').date()
        except ValueError as exc:
            raise ValueError('theatre_performance_date_unverified') from exc
        expected_day = day.strftime('%A, %B ') + str(day.day)
        if not first <= day <= last or day_label != expected_day:
            raise ValueError('theatre_performance_date_conflict')
        if not today <= day <= today + timedelta(days=60):
            continue
        start = datetime.combine(day, clock(time_label))
        row = record(title, start, None, 'Algonquin Arts Theatre',
                     '60 Abe Voorhees Drive, Manasquan, NJ 08736', 'Manasquan', url,
                     url + '|' + start.isoformat(), text(soup.select_one('.calendar-show-series')),
                     tz='America/New_York')
        if row:
            row['timezone'] = 'America/New_York'
            row['description'] = description(narrative)
            yield row


def algonquin(soup, fetch, today, deadline_at=None):
    cards = soup.select('.calendar-full-container')
    if not cards or len(cards) > 120:
        raise ValueError('theatre_listing_unverified')
    targets = {}
    for card in cards:
        anchor = card.select_one('.calendar-full-title a[href]')
        url = urljoin(ALGONQUIN, anchor.get('href', '')) if anchor else ''
        if not re.fullmatch(re.escape(ALGONQUIN) + r'\?id=[1-9]\d{0,6}', url):
            raise ValueError('theatre_detail_url_unverified')
        span = dated_span(text(card.select_one('.calendar-full-dates')), optional_year=True)
        # Only explicit listing years can rule out a detail request. Missing
        # years are resolved from the detail header, never from the current year.
        if span and (span[1] < today or span[0] > today + timedelta(days=60)):
            continue
        title = text(anchor)
        if not title or (url in targets and targets[url] != (title, span)):
            raise ValueError('theatre_title_conflict')
        targets[url] = (title, span)
    if len(targets) > MAX_DETAILS:
        raise ValueError('theatre_detail_limit')
    for url, (title, span) in targets.items():
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('source_fetch_deadline')
        detail = BeautifulSoup(fetch(url, 'text/html'), 'html.parser')
        yield from theatre_performances(detail, url, title, today, span)


def bounded_nightly_dates(first, last, today):
    """Used only after the publisher explicitly states nightly and both bounds."""
    if last < first or (last - first).days > 90:
        raise ValueError('nightly_season_unverified')
    day = max(first, today)
    while day <= min(last, today + timedelta(days=60)):
        yield day
        day += timedelta(days=1)


def gravegarden(soup, today):
    if (text(soup.select_one('.page-banner__title')) != 'Events at Old City Cemetery'
            or not re.match(r'^401 Taylor Street Lynchburg, VA 24501(?:\s|$)', text(soup.select_one('.address')))):
        raise ValueError('cemetery_location_unverified')
    section = None
    found = False
    for paragraph in soup.select('.entry-content > p'):
        label = text(paragraph)
        heading = re.fullmatch('(' + MONTH + r') (20\d{2})', label)
        if heading:
            section = datetime.strptime(label, '%B %Y').date()
            continue
        if not label or not re.match(DAY, label):
            continue
        if section is None:
            raise ValueError('cemetery_year_unverified')
        month_end = section.replace(day=calendar.monthrange(section.year, section.month)[1])
        # A December heading can contain an explicitly bounded January finish.
        # Do not discard that final night merely because its heading is old.
        explicit_range = re.match('(' + DAY + r') [–-] (' + DAY + r'):', label)
        last_listed = month_end
        if explicit_range:
            first_listed = datetime.strptime(explicit_range[1] + ' ' + str(section.year), '%B %d %Y').date()
            last_listed = datetime.strptime(explicit_range[2] + ' ' + str(section.year), '%B %d %Y').date()
            if last_listed.month < first_listed.month:
                last_listed = last_listed.replace(year=last_listed.year + 1)
        if last_listed < today or section > today + timedelta(days=60):
            continue
        if re.search(r'\b(?:cancelled|canceled|postponed)\b', label, re.I):
            raise ValueError('cemetery_schedule_unverified')
        nightly = re.fullmatch('(' + DAY + r') [–-] (' + DAY + r'): (?:NEW! )?'
                               r'(Grand Illumination: [^.]+)\. (.+) (' + CLOCK +
                               r') [–-] (' + CLOCK + r') nightly\. (.+)', label, re.I)
        ceremony = re.fullmatch('(' + DAY + r'): (Wreaths Across America Ceremony) at the Chapel\. Noon\. (.+)', label)
        if nightly:
            first = datetime.strptime(nightly[1] + ' ' + str(section.year), '%B %d %Y').date()
            last = datetime.strptime(nightly[2] + ' ' + str(section.year), '%B %d %Y').date()
            if last.month < first.month:
                last = last.replace(year=last.year + 1)
            if first.month != section.month or clock(nightly[6]) <= clock(nightly[5]):
                raise ValueError('cemetery_schedule_unverified')
            occurrences = [(day, clock(nightly[5]), clock(nightly[6]))
                           for day in bounded_nightly_dates(first, last, today)]
            title, venue = nightly[3], 'Old City Cemetery'
        elif ceremony:
            day = datetime.strptime(ceremony[1] + ' ' + str(section.year), '%B %d %Y').date()
            if day.month != section.month:
                raise ValueError('cemetery_schedule_unverified')
            occurrences = [(day, clock('noon'), None)] if today <= day <= today + timedelta(days=60) else []
            title, venue = ceremony[2], 'Old City Cemetery Chapel'
        else:
            raise ValueError('cemetery_schedule_unverified')
        found = True
        for day, start, end in occurrences:
            row = record(title, datetime.combine(day, start), datetime.combine(day, end) if end else None,
                         venue, '401 Taylor Street, Lynchburg, VA 24501', 'Lynchburg',
                         GRAVEGARDEN, GRAVEGARDEN + '|' + title, tz='America/New_York')
            if row:
                row['timezone'] = 'America/New_York'
                row['description'] = description(label)
                yield row
    if not found:
        raise ValueError('cemetery_schedule_unverified')
