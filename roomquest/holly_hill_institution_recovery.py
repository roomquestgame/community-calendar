"""Reviewed public RecDesk programs and Orangeburg YMCA occurrence evidence.

Only injected publisher transports perform I/O. RecDesk's anonymous display
POST has no caller-selected URL/body; the worker owns its fixed guarded wrapper.
The YMCA's branch RSS supplies full article content without crawling four
regional index pages. A single optional detail fetch preserves event artwork.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import logging
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record, timestamp
from roomquest.mycountyparks import cancelled
from roomquest.publisher_evidence import DETAILS_VERSION, IMAGE_VERSION

ZONE = 'America/New_York'
OLD_SANTEE = 'old_santee_canal_park_sc'
ORANGEBURG_YMCA = 'orangeburg_county_ymca_sc'
SOURCES = {
    OLD_SANTEE: 'https://oldsanteecanal.recdesk.com/Community/Program',
    ORANGEBURG_YMCA: 'https://columbiaymca.org/events/',
}
YMCA_BRANCH = 'https://columbiaymca.org/category/orangeburg-county-ymca/'
YMCA_RSS = YMCA_BRANCH + 'feed/'
EVENT_URLS = {
    OLD_SANTEE: r'https://oldsanteecanal[.]recdesk[.]com/Community/Program/Detail[?]programId=[1-9][0-9]{0,8}',
    ORANGEBURG_YMCA: r'https://columbiaymca[.]org/20[0-9]{2}/(?:0[1-9]|1[0-2])/'
                    r'(?:0[1-9]|[12][0-9]|3[01])/[a-z0-9]+(?:-[a-z0-9]+)*/',
}
PHOTO_URL = (r'https://columbiaymca[.]org/wp-content/uploads/sites/22/20[0-9]{2}/'
             r'(?:0[1-9]|1[0-2])/[A-Za-z0-9_-]+[.](?:jpe?g|png|webp|gif)')
MAX_DOCUMENT = 2_000_000
MAX_PROGRAMS = 25
MAX_FEED_ITEMS = 25
MAX_SCHEDULES = 60
MAX_RECORDS = 500
MAX_SECONDS = 30
MAX_DESCRIPTION = 2000
MAX_YMCA_DETAILS = 1
ATOM = '{http://www.w3.org/2005/Atom}'
CONTENT = '{http://purl.org/rss/1.0/modules/content/}'
PRIVATE = re.compile(r'\b(?:members?[ -]+only|invitation[ -]+only|private (?:class|event|party))\b', re.I)
MONTHS = {name.lower(): i for i, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
WEEKDAYS = {name.lower(): i for i, name in enumerate(
    'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split())}
# Public facility details reviewed 2026-11-08. An occurrence must itself name
# the matching room/facility ID and Interpretive Center; footer text is unused.
ROOMS = {
    '/Community/Facility/Detail?facilityId=2': 'Oak Room',
    '/Community/Facility/Detail?facilityId=3': 'Canal Room',
}
PARK_ADDRESS = '900 Stony Landing Road, Moncks Corner, SC 29461'
_LOG = logging.getLogger(__name__)


def validate(source):
    key = source.get('source_key')
    if key not in SOURCES or (source.get('feed_url'), source.get('kind'),
                            source.get('platform_adapter'), source.get('timezone')) != (
                                SOURCES[key], 'html', 'html', ZONE):
        raise ValueError('unregistered_holly_hill_institution_recovery')
    return key, SOURCES[key]


def event_url(key, value):
    if not isinstance(value, str) or not re.fullmatch(EVENT_URLS.get(key, r'(?!)'), value):
        return None
    if key == ORANGEBURG_YMCA:
        try:
            date.fromisoformat('-'.join(urlsplit(value).path.split('/')[1:4]))
        except ValueError:
            return None
    return value


def image_url(key, value):
    if (key != ORANGEBURG_YMCA or not isinstance(value, str)
            or not re.fullmatch(PHOTO_URL, value, re.I)
            or re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', value, re.I)):
        return None
    return value


def _document(payload, label):
    if not isinstance(payload, str) or not payload.strip() or len(payload.encode()) > MAX_DOCUMENT:
        raise ValueError(label + '_document_invalid')
    return BeautifulSoup(payload, 'html.parser')


def _text(node):
    return plain(node.get_text(' ', strip=True)) if node else ''


def _narrative(node):
    soup = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in soup.select('script,style,template,noscript,form,input,button'):
        tag.decompose()
    # Preserve full text for private/cancelled checks before display truncation.
    return '\n'.join(line.strip() for line in soup.get_text('\n').splitlines() if line.strip())


def _clock(value):
    value = re.sub(r'\s+', '', value).upper()
    if not re.fullmatch(r'(?:0?[1-9]|1[0-2])(?::[0-5][0-9])?[AP]M', value):
        raise ValueError('institution_time_unresolved')
    return datetime.strptime(value, '%I:%M%p' if ':' in value else '%I%p').time()


def _day(value):
    if not re.fullmatch(r'[0-9]{1,2}/[0-9]{1,2}/20[0-9]{2}', value):
        raise ValueError('recdesk_date_unresolved')
    try:
        return datetime.strptime(value, '%m/%d/%Y').date()
    except ValueError:
        raise ValueError('recdesk_date_unresolved') from None


def _labelled_cells(row, wanted):
    result = {}
    for cell in row.find_all(['td', 'th'], recursive=False):
        key = cell.get('data-label')
        if key in wanted:
            if key in result:
                raise ValueError('recdesk_duplicate_field')
            result[key] = cell
    if set(result) != set(wanted):
        raise ValueError('recdesk_table_structure_changed')
    return result


def parse_program_listing(payload):
    """Accept a complete first display page, never the initial GET placeholder."""
    soup = _document(payload, 'recdesk')
    tables = [t for t in soup.select('table') if _text(t.find('caption', recursive=False)) == 'Programs list']
    paging = soup.select('.paging-left')
    if len(tables) != 1 or len(paging) != 1 or soup.select_one('#data-filters'):
        raise ValueError('recdesk_listing_structure_changed')
    match = re.fullmatch(r'Displaying 1 - ([1-9][0-9]*) of ([1-9][0-9]*)', _text(paging[0]))
    if not match or match[1] != match[2] or int(match[2]) > MAX_PROGRAMS:
        raise ValueError('recdesk_incomplete_program_page')
    result, seen = [], set()
    for anchor in tables[0].select('tr.sub-category-header a[href*="Program/Detail"]'):
        url = urljoin(SOURCES[OLD_SANTEE], anchor.get('href', ''))
        title = _text(anchor)
        header = anchor.find_parent('tr')
        info = header.find_next_sibling('tr')
        fields = {}
        for cell in info.find_all('td', recursive=False) if info else []:
            label = cell.select_one('span.text-semibold')
            if label:
                key, value = _text(label), _text(cell)
                if key in fields or not value.startswith(key):
                    raise ValueError('recdesk_listing_structure_changed')
                fields[key] = value[len(key):].strip()
        if (not event_url(OLD_SANTEE, url) or not title or url in seen
                or set(fields) != {'Dates', 'Days', 'Ages', 'Grades', 'Openings', 'Remaining'}):
            raise ValueError('recdesk_listing_identity_unverified')
        day = _day(fields['Dates'])
        if fields['Days'] != day.strftime('%a'):
            raise ValueError('recdesk_listing_weekday_conflict')
        remaining = fields['Remaining']
        if remaining == 'FULL':
            availability = 'Full; waitlist available' if re.search(r'\bWait List\b', _text(info)) else 'Full'
        elif re.fullmatch(r'[0-9]+', remaining):
            availability = remaining + ' places remaining'
        elif remaining == 'n/a':
            availability = 'Registration available; remaining capacity not specified'
        else:
            raise ValueError('recdesk_availability_unresolved')
        result.append(dict(url=url, title=title, day=day, ages=fields['Ages'], availability=availability))
        seen.add(url)
    if len(result) != int(match[2]):
        raise ValueError('recdesk_incomplete_program_page')
    return result


def _program_venue(cell, body):
    # The offsite meeting statement is stronger than a host site's footer or
    # an unfilled schedule location. Only its literal address is used.
    offsite = re.search(r'We will meet at (?:the )?([^:\n]+):\s*'
                        r'([0-9]{1,6} [^,\n]+),\s*([A-Za-z .\'-]+),\s*SC ([0-9]{5})\b', body)
    if offsite:
        if _text(cell) != 'No location set':
            raise ValueError('recdesk_venue_conflict')
        return (offsite[1], f'{offsite[2]}, {offsite[3]}, SC {offsite[4]}', offsite[3])
    links = cell.select('a[href]')
    if (len(links) == 1 and links[0].get('href') in ROOMS
            and _text(links[0]) == ROOMS[links[0]['href']]
            and re.search(r'Meeting Place:\s*Interpretive Center(?:\n|$)', body)):
        return ('Old Santee Canal Park — Interpretive Center, ' + _text(links[0]), PARK_ADDRESS, 'Moncks Corner')
    if (_text(cell) == 'No location set'
            and 'Old Santee Canal Park, 900 Stony Landing Road, Moncks Corner' in body
            and re.search(r'On-site registration will be available at Old Santee Canal Park\b', body)):
        return ('Old Santee Canal Park', PARK_ADDRESS, 'Moncks Corner')
    raise ValueError('recdesk_venue_unverified')


def _program_hours(body, starts, ends):
    """Reject an explicit narrative/table conflict without inventing hours."""
    labelled = re.findall(r'^Time:\s*(.+)$', body, re.M)
    if len(labelled) > 1:
        raise ValueError('recdesk_schedule_conflict')
    if labelled:
        match = re.fullmatch(r'([0-9]{1,2}(?::[0-9]{2})?\s*[ap]m)\s*[–—-]\s*'
                            r'([0-9]{1,2}(?::[0-9]{2})?\s*[ap]m)', labelled[0], re.I)
        if not match or (_clock(match[1]), _clock(match[2])) != (starts.time(), ends.time()):
            raise ValueError('recdesk_schedule_conflict')
    course = re.search(r'The course opens at ([0-9:]+\s*[ap]m) and closes at ([0-9:]+\s*[ap]m)', body, re.I)
    if course and (_clock(course[1]), _clock(course[2])) != (starts.time(), ends.time()):
        raise ValueError('recdesk_schedule_conflict')


def _row(key, identity, title, starts, ends, venue, url, body, categories, facts, candidate=None):
    if not event_url(key, url):
        raise ValueError('institution_event_identity_changed')
    row = record(title, starts.isoformat(), ends.isoformat(), *venue, url, identity,
                 ', '.join(categories), tz=ZONE, retain_until_end=True)
    if row:
        row.update(timezone=ZONE, description=body[:MAX_DESCRIPTION],
                   publisher_categories=categories,
                   location_provenance='publisher_event_address_pending_geocode',
                   details_extractor_version=DETAILS_VERSION, details_evidence_url=url,
                   publisher_details={k: v[:400] for k, v in facts.items() if v},
                   image_extractor_version=IMAGE_VERSION)
        candidate = image_url(key, candidate)
        if candidate:
            row.update(image_url=candidate, image_provenance=IMAGE_VERSION, image_evidence_url=url)
    return row


def parse_program(payload, listed):
    soup = _document(payload, 'recdesk')
    canonical = soup.select('link[rel="canonical"]')
    titles = soup.select('#page-content .panel-title')
    wells = soup.select('#program-detail .well')
    if (len(canonical) != 1 or canonical[0].get('href') != listed['url'] or len(titles) != 1
            or _text(titles[0]) != listed['title'] or len(wells) != 1):
        raise ValueError('recdesk_detail_identity_conflict')
    body = _narrative(wells[0])
    notices = '\n'.join(_narrative(x) for x in soup.select('#page-content .alert'))
    if (PRIVATE.search(listed['title'] + '\n' + body + '\n' + notices)
            or cancelled(listed['title'], body + '\n' + notices)):
        return []
    details = {}
    for tr in soup.select('#program-detail > table > tbody > tr'):
        key, value = tr.find('th', recursive=False), tr.find('td', recursive=False)
        if key and _text(key) in ('Program Type', 'Online Registration', 'Enrollment End Date'):
            if _text(key) in details:
                raise ValueError('recdesk_detail_structure_changed')
            details[_text(key)] = _text(value)
    if not details.get('Program Type') or details.get('Online Registration') != 'Yes':
        raise ValueError('recdesk_public_registration_unverified')
    fees = [t for t in soup.select('#program-fees table') if _text(t.find('caption')) == 'Program Fees']
    if len(fees) != 1:
        raise ValueError('recdesk_fee_structure_changed')
    costs, amounts = [], set()
    for tr in fees[0].select('tbody > tr'):
        cells = _labelled_cells(tr, ('Standard Fee', 'Residency Restriction', 'Membership Restrictions', 'Amount'))
        if (_text(cells['Residency Restriction']) != '-None-'
                or _text(cells['Membership Restrictions']) != '-None-'):
            raise ValueError('recdesk_public_eligibility_unverified')
        label, amount = _text(cells['Standard Fee']), _text(cells['Amount'])
        if not label or not re.fullmatch(r'\$[0-9]+[.][0-9]{2}', amount):
            raise ValueError('recdesk_fee_unresolved')
        costs.append(label + ': ' + amount)
        amounts.add(amount)
    narrative_fee = re.search(r'^Program Fee:\s*(\$[0-9]+(?:[.][0-9]{2})?)\b', body, re.M)
    if narrative_fee:
        amount = narrative_fee[1] if '.' in narrative_fee[1] else narrative_fee[1] + '.00'
        if amount not in amounts:
            raise ValueError('recdesk_fee_conflict')
    schedules = [t for t in soup.select('#program-schedule table') if _text(t.find('caption')) == 'Program Schedule']
    if not costs or len(costs) > 10 or len(schedules) != 1:
        raise ValueError('recdesk_schedule_structure_changed')
    sessions = schedules[0].select('tbody > tr')
    if not sessions or len(sessions) > MAX_SCHEDULES:
        raise ValueError('recdesk_schedule_limit')
    age = re.search(r'^Age Limit:\s*(.+)$', body, re.M)
    facts = {'cost': '; '.join(costs),
             'registration': ('Registration required. ' + listed['availability']
                              + '. No residency or membership restrictions.'),
             'audience': age[1] if age else ''}
    if listed['ages'] and listed['ages'] != '- Not specified':
        # RecDesk's enforced registration ages and the prose audience can
        # differ (e.g. the homeschool description welcomes accompanying adults).
        facts['audience'] = (facts['audience'] + '. ' if facts['audience'] else '') + 'Registration ages: ' + listed['ages']
    if details.get('Enrollment End Date') and details['Enrollment End Date'] != '-':
        facts['registration'] += ' Registration deadline: ' + details['Enrollment End Date']
    result, seen, days = [], set(), set()
    for tr in sessions:
        cells = _labelled_cells(tr, ('Date', 'Day', 'Start Time', 'End Time', 'Location'))
        day = _day(_text(cells['Date']))
        if _text(cells['Day']) != day.strftime('%A'):
            raise ValueError('recdesk_schedule_weekday_conflict')
        starts = timestamp(datetime.combine(day, _clock(_text(cells['Start Time']))), ZONE)
        ends = timestamp(datetime.combine(day, _clock(_text(cells['End Time']))), ZONE)
        if ends <= starts or starts in seen:
            raise ValueError('recdesk_schedule_conflict')
        _program_hours(body, starts, ends)
        venue = _program_venue(cells['Location'], body)
        facts['meeting_location'] = venue[0] + ', ' + venue[1]
        identity = 'recdesk-' + listed['url'].split('programId=')[1] + '__' + starts.strftime('%Y%m%dT%H%M')
        description = body + '\nAvailability: ' + listed['availability'] + '\nFees: ' + facts['cost']
        row = _row(OLD_SANTEE, identity, listed['title'], starts, ends, venue, listed['url'],
                   description, [details['Program Type']], facts)
        if row:
            result.append(row)
        seen.add(starts)
        days.add(day)
    if days != {listed['day']}:
        raise ValueError('recdesk_listing_schedule_conflict')
    return result


def _ymca_feed(payload):
    if (not isinstance(payload, str) or len(payload.encode()) > MAX_DOCUMENT
            or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', payload, re.I)):
        raise ValueError('ymca_feed_document_invalid')
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        raise ValueError('ymca_feed_document_invalid') from None
    channels = root.findall('channel')
    if root.tag != 'rss' or len(channels) != 1:
        raise ValueError('ymca_feed_structure_changed')
    channel = channels[0]
    links = channel.findall(ATOM + 'link')
    if (channel.findtext('title') != 'Orangeburg County YMCA: Archives - Columbia YMCA'
            or channel.findtext('link') != YMCA_BRANCH
            or not any(x.get('href') == YMCA_RSS and x.get('rel') == 'self' for x in links)
            or any(x.get('rel') in ('next', 'previous') for x in links)):
        raise ValueError('ymca_feed_identity_unverified')
    items = channel.findall('item')
    if len(items) > MAX_FEED_ITEMS:
        raise ValueError('ymca_feed_item_limit')
    result, seen = [], set()
    for item in items:
        title, url = plain(item.findtext('title')), item.findtext('link')
        categories = [plain(x.text).rstrip(':') for x in item.findall('category')]
        content = item.findtext(CONTENT + 'encoded')
        if (not title or not event_url(ORANGEBURG_YMCA, url) or url in seen
                or 'Orangeburg County YMCA' not in categories or not content):
            raise ValueError('ymca_article_identity_unverified')
        try:
            published = parsedate_to_datetime(item.findtext('pubDate'))
        except (TypeError, ValueError):
            raise ValueError('ymca_publication_date_unverified') from None
        url_day = date.fromisoformat('-'.join(urlsplit(url).path.split('/')[1:4]))
        if published.tzinfo is None or published.date() != url_day:
            raise ValueError('ymca_publication_date_conflict')
        result.append(dict(title=title, url=url, published=published, categories=categories, content=content))
        seen.add(url)
    return result


def _ymca_blocks(soup):
    """Extract one literal labelled article block, not footer or generic dates."""
    text = _narrative(soup)
    labels = list(re.finditer(r'(?im)^(WHERE|WHEN|TIME|COST|QUESTIONS):\s*', text))
    blocks = {}
    for i, match in enumerate(labels):
        key = match[1].upper()
        if key in blocks:
            raise ValueError('ymca_duplicate_occurrence_field')
        blocks[key] = text[match.end():labels[i + 1].start() if i + 1 < len(labels) else len(text)].strip()
    return blocks, text


def _ymca_occurrence(item, content=None):
    soup = _document(content if content is not None else item['content'], 'ymca_article')
    # WordPress's RSS attribution is not article narrative.
    for p in soup.select('p'):
        if _text(p).startswith('The post ') and ' appeared first on ' in _text(p):
            p.decompose()
    blocks, body = _ymca_blocks(soup)
    if PRIVATE.search(item['title'] + '\n' + body) or cancelled(item['title'], body):
        return None, 'private_or_cancelled'
    # The feed also syndicates Columbia-wide events and self-paced challenges.
    # An explicit other-city venue never inherits the Orangeburg branch address.
    if re.search(r'\bColumbia,\s*SC\s*[0-9]{5}\b', body):
        return None, 'outside_orangeburg_scope'
    if re.search(r'\bat your own pace\b', body, re.I) and not blocks.get('TIME'):
        return None, 'self_paced_without_occurrence_time'
    if not all(blocks.get(k) for k in ('WHERE', 'WHEN', 'TIME', 'COST')):
        return None, 'unsupported_article_occurrence_fields'
    where = [plain(x) for x in blocks['WHERE'].splitlines() if plain(x)]
    if (len(where) != 3 or where[0] != 'Orangeburg County YMCA'
            or not re.fullmatch(r'[0-9]{1,6} [A-Za-z0-9 .-]+', where[1])
            or not re.fullmatch(r'Orangeburg, SC [0-9]{5}', where[2])):
        raise ValueError('ymca_event_venue_unverified')
    # Exact named-branch address is verified within this event, not substituted
    # from the feed category or any other article.
    if where[1:] != ['2550 St Matthews Rd NE', 'Orangeburg, SC 29118']:
        raise ValueError('ymca_event_venue_changed')
    when = re.fullmatch(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
                        r'([A-Za-z]+) ([0-9]{1,2})(?:st|nd|rd|th)?(?:,? (20[0-9]{2}))?',
                        plain(blocks['WHEN']), re.I)
    if not when:
        raise ValueError('ymca_event_date_unresolved')
    try:
        day = date(int(when[4] or item['published'].year), MONTHS[when[2].lower()], int(when[3]))
    except (KeyError, ValueError):
        raise ValueError('ymca_event_date_unresolved') from None
    if day.weekday() != WEEKDAYS[when[1].lower()] or day < item['published'].date():
        raise ValueError('ymca_event_date_conflict')
    times = re.fullmatch(r'([0-9]{1,2}(?::[0-9]{2})?\s*[AP]M)\s*[–—-]\s*'
                         r'([0-9]{1,2}(?::[0-9]{2})?\s*[AP]M)', plain(blocks['TIME']), re.I)
    if not times:
        raise ValueError('ymca_event_time_unresolved')
    starts = timestamp(datetime.combine(day, _clock(times[1])), ZONE)
    ends = timestamp(datetime.combine(day, _clock(times[2])), ZONE)
    if ends <= starts:
        raise ValueError('ymca_event_time_conflict')
    cost = plain(blocks['COST'])
    if not re.fullmatch(r'\$[0-9]+(?:[.][0-9]{2})? for Members,\s*'
                        r'\$[0-9]+(?:[.][0-9]{2})? for Non-Members', cost, re.I):
        raise ValueError('ymca_public_eligibility_unverified')
    candidates = [image_url(ORANGEBURG_YMCA, image.get('src')) for image in soup.select('img[src]')]
    candidate = next((url for url in candidates if url), None)
    facts = {'cost': cost, 'audience': 'Members and non-members', 'meeting_location': ', '.join(where)}
    if any(re.search(r'\bregister\b', _text(link), re.I) for link in soup.select('a[href]')):
        facts['registration'] = 'Registration offered on the publisher event page'
    # Remove contact-only tail from the display narrative, after safety checks.
    body = re.split(r'(?im)^QUESTIONS:', body, maxsplit=1)[0].strip()
    return dict(starts=starts, ends=ends, venue=(where[0], ', '.join(where[1:]), 'Orangeburg'),
                body=body, facts=facts, candidate=candidate), None


def _ymca_detail(payload, item, occurrence):
    soup = _document(payload, 'ymca_article')
    canonical = soup.select('link[rel="canonical"]')
    published = soup.select('meta[property="article:published_time"]')
    title = soup.select_one('main h1')
    bodies = soup.select('main .fusion-content-tb')
    if (len(canonical) != 1 or canonical[0].get('href') != item['url'] or len(published) != 1
            or _text(title) != item['title'] or len(bodies) != 1):
        raise ValueError('ymca_detail_identity_conflict')
    try:
        issued = datetime.fromisoformat(published[0].get('content', '').replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('ymca_detail_publication_conflict') from None
    if issued != item['published']:
        raise ValueError('ymca_detail_publication_conflict')
    detail, reason = _ymca_occurrence(item, str(bodies[0]))
    if reason or not detail or any(detail[k] != occurrence[k] for k in ('starts', 'ends', 'venue', 'facts')):
        raise ValueError('ymca_feed_detail_conflict')
    images = soup.select('meta[property="og:image"]')
    return image_url(ORANGEBURG_YMCA, images[0].get('content')) if len(images) == 1 else None


def collect(source, fetch, *, deadline_at=None, fetch_programs=None, diagnostics=None):
    key, _ = validate(source)
    deadline = min(monotonic() + MAX_SECONDS, deadline_at if deadline_at is not None else float('inf'))

    def check():
        if monotonic() >= deadline:
            raise TimeoutError('institution_collection_deadline_exceeded')

    def get(url, accept):
        check()
        payload = fetch(url, accept)
        check()
        return payload

    check()
    if key == OLD_SANTEE:
        if not callable(fetch_programs):
            raise ValueError('recdesk_public_display_transport_required')
        payload = fetch_programs()
        check()
        listed = parse_program_listing(payload)
        rows = []
        # Every advertised program must validate; a failed detail may not be
        # reported as a complete successful display-page collection.
        for program in listed:
            rows.extend(parse_program(get(program['url'], 'text/html'), program))
            if len(rows) > MAX_RECORDS:
                raise ValueError('source_record_limit')
        check()
        return rows

    items = _ymca_feed(get(YMCA_RSS, 'application/rss+xml'))
    rows, held, details = [], [], 0
    now = datetime.now(timezone.utc)
    for item in items:
        check()
        try:
            occurrence, reason = _ymca_occurrence(item)
        except ValueError as exc:
            occurrence, reason = None, str(exc)
        if not occurrence:
            entry = {'url': item['url'], 'reason': reason}
            if diagnostics is not None:
                diagnostics.append(entry)
            if reason not in ('private_or_cancelled', 'outside_orangeburg_scope',
                              'self_paced_without_occurrence_time'):
                held.append(entry)
                _LOG.warning('institution_article_held source=%s url=%s reason=%s', key, item['url'], reason)
            continue
        if occurrence['ends'] <= now or occurrence['starts'] > now + timedelta(days=60):
            continue
        candidate = occurrence['candidate']
        if not candidate and details < MAX_YMCA_DETAILS:
            candidate = _ymca_detail(get(item['url'], 'text/html'), item, occurrence)
            details += 1
        row = _row(key, item['url'], item['title'], occurrence['starts'], occurrence['ends'],
                   occurrence['venue'], item['url'], occurrence['body'],
                   [label for label in item['categories'] if label != 'Blog'], occurrence['facts'], candidate)
        if row:
            rows.append(row)
    if held and not rows:
        raise ValueError('ymca_all_occurrences_held')
    check()
    return rows
