"""Bounded public Eventin HTML extraction for a reviewed Cambridge calendar.

The site's Eventin REST API requires authentication and is never requested.
Repeated display cards are coalesced, and only publicly listed dates are used.
"""
import calendar
from datetime import datetime, timedelta
import re
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import record

URL = 'https://cambridgeppf.org/events-list/'
DETAIL = re.compile(r'/etn/[a-z0-9-]+(?:/[a-z0-9-]+)?/')
CLOCK = r'(?:1[0-2]|0?[1-9])(?:[.:][0-5]\d)?\s*[ap]m'
PAIR = CLOCK + r'\s*[–-]\s*' + CLOCK
DAY = r'([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]+)'
TIMED = re.compile(r'^' + DAY + r'\s*,?\s*(' + PAIR + r'(?:\s*(?:&|,)\s*' + PAIR + r')*)', re.I)
VENUES = {
    'Coton Reserve, Grantchester Rd, Cambridge CB23 7PY':
        ('Coton Reserve', 'Grantchester Rd, Cambridge CB23 7PY, United Kingdom'),
    'Leper Chapel, Newmarket Road, Cambridge, CB5 8JJ':
        ('Leper Chapel', 'Newmarket Road, Cambridge CB5 8JJ, United Kingdom'),
    # The event supplies the park and postcode. Its own publisher contact block
    # and /wandlebury-country-park/ locate it at Wandlebury Ring, Gog Magog Hills.
    'Wandlebury Country Park, Cambridge, CB22 3AE':
        ('Wandlebury Country Park', 'Wandlebury Ring, Gog Magog Hills, Cambridge CB22 3AE, United Kingdom'),
}
MAX_CARDS = 500
MAX_DETAILS = 8


def text(node, selector):
    item = node.select_one(selector)
    return item.get_text(' ', strip=True) if item else ''


def clock(label):
    value = label.replace(' ', '').replace('.', ':').upper()
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def card_date_matches(day, weekday, number, month):
    months = {name.casefold(): i for i, name in enumerate(calendar.month_name) if name}
    months.update({name.casefold(): i for i, name in enumerate(calendar.month_abbr) if name})
    return (day.day == int(number) and day.month == months.get(month.casefold())
            and day.strftime('%a').lower() == weekday[:3].lower())


def timed_ranges(day, narrative):
    schedule = TIMED.match(narrative)
    if not schedule or not card_date_matches(day, *schedule.groups()[:3]):
        return None
    # Do not consume only the first part of a more complex schedule.
    remaining = narrative[schedule.end():].lstrip()
    if remaining.startswith(('&', ',')):
        return None
    result = []
    for pair in re.finditer(r'(' + CLOCK + r')\s*[–-]\s*(' + CLOCK + r')', schedule[4], re.I):
        start = datetime.combine(day, clock(pair[1]))
        end = datetime.combine(day, clock(pair[2]))
        if end <= start:
            end += timedelta(days=1)
        if not timedelta(0) < end - start <= timedelta(hours=12):
            raise ValueError('eventin_schedule_unverified')
        result.append((start, end, ''))
    return result


def cards(soup, today):
    elements = soup.select('.etn-event-item')
    if len(elements) > MAX_CARDS:
        raise ValueError('eventin_calendar_card_limit')
    result = {}
    for card in elements:
        link = card.select_one('.etn-event-title a[href]')
        if not link:
            continue
        url = link['href']
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'cambridgeppf.org'
                or not DETAIL.fullmatch(parts.path) or parts.query or parts.fragment):
            raise ValueError('eventin_event_identity_unverified')
        title = link.get_text(' ', strip=True)
        location = text(card, '.etn-event-location')
        narrative = text(card, '.etn-event-content > p')
        day = datetime.strptime(text(card, '.etn-event-date'), '%B %d, %Y').date()
        multiple_days = re.match(r'^' + DAY + r'\s*[–&-]\s*' + DAY, narrative, re.I)
        earliest = today - timedelta(days=60) if multiple_days else today
        if not earliest <= day <= today + timedelta(days=60):
            continue
        if not title:
            raise ValueError('eventin_event_identity_unverified')
        old = result.get(url)
        if old:
            if (old['title'] != title or old['day'] != day
                    or (old['location'] and location and old['location'] != location)
                    or not (old['narrative'].startswith(narrative) or narrative.startswith(old['narrative']))):
                raise ValueError('eventin_conflicting_cards')
            location = location or old['location']
            narrative = max(old['narrative'], narrative, key=len)
        result[url] = {'day': day, 'title': title, 'location': location, 'narrative': narrative}
    return result



def event_photo(soup, title, event_url):
    """Select one event-specific Eventin photograph from the fetched detail.

    The caller has already verified title, venue, timezone and calendar-link
    identity. Avoid branding/related-event photos and do not fetch extra URLs.
    """
    from roomquest.registered_native_content import image_candidate
    from urllib.parse import urljoin
    expected = [part for part in re.findall(r'[a-z0-9]+', title.casefold())
                if len(part) >= 4 and part not in ('with', 'from', 'this', 'that')]
    if len(expected) < 2:
        return None

    def candidate(raw):
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = urljoin(event_url, raw.strip())
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.netloc != 'cambridgeppf.org'
                or '/wp-content/uploads/' not in parsed.path
                or not re.search(r'\.(?:jpe?g|png|webp)(?:$)', parsed.path, re.I)
                or image_candidate(value) != value):
            return None
        stem = parsed.path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        parts = [part for part in re.findall(r'[a-z0-9]+', stem.casefold())
                 if len(part) >= 4]
        # "Healthy Walking" may appear as "healthy-walkers-square.jpg".
        return value if sum(any(part[:4] == term[:4] for part in parts)
                            for term in expected) >= 2 else None

    matches = set()
    for node in soup.select('meta[property="og:image"],meta[name="twitter:image"]')[:3]:
        if value := candidate(node.get('content')):
            matches.add(value)
    for node in soup.select('.etn-event-thumb img[src],.etn-event-image img[src],'
                            '.etn-event-content-body img[src],'
                            '.etn-event-single-content img[src],'
                            'img.wp-post-image[src]')[:12]:
        if node.find_parent(['nav', 'aside', 'footer', 'header']):
            continue
        if value := candidate(node.get('src')):
            matches.add(value)
    # Eventin templates can render the event's featured image in an ordinary
    # WordPress figure outside the plugin's known image wrappers. Fall back to
    # the actual fetched detail's images, never a different page or a new fetch.
    # The same exact publisher host, upload path, title stems and unique
    # candidate rules above still apply. Exclude related/suggested event cards.
    if not matches:
        for node in soup.select('img[src]')[:60]:
            if node.find_parent(['nav', 'aside', 'footer', 'header']):
                continue
            if any(
                'related' in ' '.join(parent.get('class') or []).casefold()
                or 'sidebar' in ' '.join(parent.get('class') or []).casefold()
                or 'recommend' in ' '.join(parent.get('class') or []).casefold()
                for parent in node.parents if getattr(parent, 'attrs', None)
            ):
                continue
            if value := candidate(node.get('src')):
                matches.add(value)
    return next(iter(matches)) if len(matches) == 1 else None


def detail(payload, expected):
    soup = BeautifulSoup(payload, 'html.parser')
    if (text(soup, '.etn-event-entry-title') != expected['title']
            or text(soup, '.etn-event-timezone') != '(Europe/London)'):
        raise ValueError('eventin_event_identity_unverified')
    fields = {}
    for item in soup.select('.etn-event-meta-info li'):
        label = item.select_one('span')
        if label:
            key = label.get_text(' ', strip=True).rstrip(' :')
            label.extract()
            for zone in item.select('.etn-event-timezone'):
                zone.extract()
            fields[key] = item.get_text(' ', strip=True)
    if fields.get('Venue') != expected['location']:
        raise ValueError('eventin_venue_conflict')
    values = set()
    for anchor in soup.select('a[href]'):
        parts = urlsplit(anchor['href'])
        if parts.scheme == 'https' and parts.netloc == 'calendar.google.com' and parts.path == '/calendar/r/eventedit':
            params = parse_qs(parts.query)
            if params.get('text') != [expected['title']] or params.get('location') != [expected['location']]:
                raise ValueError('eventin_event_identity_unverified')
            values.update(params.get('dates', []))
    if len(values) != 1:
        raise ValueError('eventin_schedule_unverified')
    match = re.fullmatch(r'(\d{8}T\d{6})/(\d{8}T\d{6})', values.pop())
    if not match:
        raise ValueError('eventin_schedule_unverified')
    start, end = [datetime.strptime(match[i], '%Y%m%dT%H%M%S') for i in (1, 2)]
    dates = [datetime.strptime(value.strip(), '%B %d, %Y').date() for value in fields.get('Date', '').split(' - ')]
    hours = re.fullmatch(r'(' + CLOCK + r')\s*-\s*(' + CLOCK + ')', fields.get('Time', ''), re.I)
    if (dates != ([start.date()] if start.date() == end.date() else [start.date(), end.date()])
            or start.date() != expected['day'] or not hours
            or (clock(hours[1]), clock(hours[2])) != (start.time(), end.time())
            or not timedelta(0) < end - start <= timedelta(days=60)):
        raise ValueError('eventin_schedule_conflict')
    return start, end, text(soup, '.etn-event-content-body'), event_photo(soup, expected['title'], expected['url'])


def family_slots(start, end, narrative):
    match = re.match(r'^' + DAY + r' & ' + DAY + r',\s*(' + PAIR + r'),\s*(' + PAIR + r') &\s*('
                     + PAIR + r') \(Adults/Older Teens\)', narrative, re.I)
    if (not match or not card_date_matches(start.date(), *match.groups()[:3])
            or not card_date_matches(end.date(), *match.groups()[3:6])
            or end.date() - start.date() != timedelta(days=1)):
        return None
    result = []
    for day in (start.date(), end.date()):
        for index, pair in enumerate(match.groups()[6:]):
            hours = re.fullmatch(r'(' + CLOCK + r')\s*[–-]\s*(' + CLOCK + ')', pair, re.I)
            begins, ends = (datetime.combine(day, clock(hours[i])) for i in (1, 2))
            if not start <= begins < ends <= end or ends - begins != timedelta(hours=2):
                raise ValueError('eventin_schedule_conflict')
            result.append((begins, ends, ' (Adults/Older Teens)' if index == 2 else ''))
    return result


def rows(soup, fetch, today, deadline_at):
    entries = cards(soup, today)
    details, series = {}, None
    for url, item in entries.items():
        if item['location'] not in VENUES:
            continue  # Includes the publisher's explicitly undecided location.
        venue, street = VENUES[item['location']]
        narrative = item['narrative']
        photo = None
        intervals = timed_ranges(item['day'], narrative)
        walking = (item['title'] == 'Healthy Walking at Wandlebury'
                   and item['location'] == 'Wandlebury Country Park, Cambridge, CB22 3AE'
                   and narrative.startswith('Every Thursday at Wandlebury, come rain or shine,')
                   and re.fullmatch(r'https://cambridgeppf.org/etn/healthy-walking-at-wandlebury-2/'
                                    r'healthy-walking-at-wandlebury-\d+/', url))
        if walking and series is not None:
            if item['day'].weekday() != 3:
                raise ValueError('eventin_series_date_conflict')
            intervals = [(datetime.combine(item['day'], first), datetime.combine(item['day'], last), '')
                         for first, last in series[0]]
            narrative = series[1]
            photo = series[2]
        elif intervals is None:
            if len(details) >= MAX_DETAILS:
                raise ValueError('eventin_calendar_detail_limit')
            if deadline_at is not None and monotonic() >= deadline_at:
                raise ValueError('collection_deadline')
            start, end, narrative, photo = detail(fetch(url, 'text/html'), {**item, 'url': url})
            details[url] = True
            if walking:
                # The detail explicitly says EVERY Thursday and names both
                # sessions. We apply those hours only to dates already present
                # in this fetched listing; no new recurrence dates are created.
                if (not narrative.startswith('Every Thursday at Wandlebury, come rain or shine,')
                        or 'Meet at 10am for a one hour walk' not in narrative
                        or 'meet at 10.30am for a slower 30 min walk' not in narrative
                        or (start.time(), end.time()) != (clock('10am'), clock('11am'))
                        or item['day'].weekday() != 3):
                    raise ValueError('eventin_series_schedule_unverified')
                series = ([(clock('10am'), clock('11am')), (clock('10.30am'), clock('11am'))], narrative, photo)
                intervals = [(datetime.combine(item['day'], first), datetime.combine(item['day'], last), '')
                             for first, last in series[0]]
            else:
                intervals = family_slots(start, end, narrative)
                if item['title'] == 'Winter Wreath Making for Families' and intervals is None:
                    raise ValueError('eventin_family_schedule_unverified')
                intervals = intervals or [(start, end, '')]
        for start, end, suffix in intervals:
            row = record(item['title'] + suffix, start, end, venue, street, 'Cambridge', url, url,
                         tz='Europe/London', retain_until_end=True)
            if row:
                row['description'] = description(narrative)
                if intervals is not None and (walking or url in details) and photo:
                    row.update(image_url=photo,
                               image_extractor_version='publisher_event_candidates_v1',
                               image_provenance='publisher_event_candidates_v1',
                               image_evidence_url=url)
                yield row
