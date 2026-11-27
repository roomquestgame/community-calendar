"""Dated event sections in Sustainable Oakington and Westwick's public RSS.

The reviewed rolling feed carries complete HTML articles, including repeated
monthly updates. Read only those articles; do not crawl referrals, expand a
programme or manufacture occurrences from publication dates and generic prose.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
import re
from time import monotonic
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.collection_window import calendar_anchor
from roomquest.event_description import description
from roomquest.mapsee_adapter import plain, record
from roomquest.registration_formats import source_key

URL = 'https://sustainableow.co.uk/feed/'
HOME = 'https://sustainableow.co.uk'
SITE_ID = '106953790'
ZONE = 'Europe/London'
VENUE = "St Andrew's Church Hall"
ADDRESS = 'High Street, Oakington, Cambridge CB24 3AG, United Kingdom'
ATOM = '{http://www.w3.org/2005/Atom}'
CONTENT = '{http://purl.org/rss/1.0/modules/content/}'
WP = '{com-wordpress:feed-additions:1}'
MAX_BYTES = 3_000_000
FEED_ITEMS = 10  # Reviewed publisher setting; a changed/truncated feed needs review.
MAX_NODES = 500
MAX_SECTIONS = 100
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December')
MONTH = r'(?:' + '|'.join(name + '|' + name[:3] for name in MONTHS) + r')'
WEEKDAY = r'(?:Mon(?:day)?|Tue(?:s(?:day)?)?|Wed(?:s|nesday)?|Thu(?:rs(?:day)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)'
DATE = re.compile(r'(?<!\w)(?:(?P<weekday>' + WEEKDAY + r')\s*,?\s+)?'
                  r'(?P<day>\d{1,2})(?:\s*(?:st|nd|rd|th))?\s+(?P<month>' + MONTH + r')\b'
                  r'(?:\s*,?\s+(?P<year>20\d{2}|next year|this year)\b)?', re.I)
CLOCK = r'\d{1,2}(?:[:.]\d{2})?'
RANGE = re.compile(r'(?<![\w.£€$])(?P<first>' + CLOCK + r')\s*(?P<fm>[ap]m)?\s*'
                   r'(?:[–—-]|\bto\b)\s*(?:about\s+)?(?P<last>' + CLOCK + r')\s*(?P<lm>[ap]m)?\b', re.I)
SINGLE = re.compile(r'(?<![\w.£€$])(?:\d{1,2}(?:[:.]\d{2})?\s*[ap]m\b|\d{1,2}:\d{2}\b)', re.I)
EVENT_WORD = re.compile(r'\b(?:workshop|session|meeting|event|cafe|café|film|conference|festival|swish|feast|planting|pressing|talk|training)\b', re.I)
TBC = re.compile(r'\b(?:TBC|TBA|to be (?:confirmed|announced)|details to follow|save.the.date)\b', re.I)


def _fail(reason):
    raise ValueError('sow_' + reason)


def _deadline(deadline_at):
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')


def _field(node, name):
    values = node.findall(name)
    if len(values) != 1 or not isinstance(values[0].text, str) or not values[0].text.strip():
        _fail('feed_incomplete')
    return values[0].text.strip()


@dataclass
class Post:
    title: str
    url: str
    published: datetime
    content: str


def _posts(payload):
    if (not isinstance(payload, str) or len(payload.encode('utf-8')) > MAX_BYTES
            or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', payload, re.I)):
        _fail('feed_payload_unverified')
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError('sow_feed_payload_unverified') from exc
    channels = root.findall('channel')
    if root.tag != 'rss' or root.get('version') != '2.0' or len(channels) != 1:
        _fail('feed_identity_unverified')
    channel = channels[0]
    self_links = [node for node in channel.findall(ATOM + 'link') if node.get('rel') == 'self']
    if (_field(channel, 'title') != 'Sustainable Oakington and Westwick'
            or _field(channel, 'link').rstrip('/') != HOME
            or _field(channel, WP + 'site') != SITE_ID
            or len(self_links) != 1 or self_links[0].get('href') != URL
            or self_links[0].get('type') != 'application/rss+xml'):
        _fail('feed_identity_unverified')
    if any(node.get('rel') in {'next', 'previous', 'prev', 'first', 'last'} for node in root.iter()):
        _fail('feed_pagination_unverified')
    items = channel.findall('item')
    if len(items) != FEED_ITEMS:
        _fail('feed_incomplete')
    posts, seen = [], set()
    for item in items:
        link = _field(item, 'link')
        match = re.fullmatch(re.escape(HOME) + r'/(20\d{2})/(\d{2})/(\d{2})/[a-z0-9-]+/', link)
        identity = _field(item, WP + 'post-id')
        if (not match or len(link) > 1000 or not re.fullmatch(r'[1-9]\d{0,9}', identity)
                or _field(item, 'guid') != HOME.replace('https:', 'http:') + '/?p=' + identity
                or link in seen or identity in seen):
            _fail('post_identity_unverified')
        seen.update((link, identity))
        try:
            published = parsedate_to_datetime(_field(item, 'pubDate'))
            if published.tzinfo is None:
                _fail('post_year_unverified')
            published = published.astimezone(ZoneInfo(ZONE))
            permalink_day = datetime(*(int(value) for value in match.groups())).date()
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('sow_post_year_unverified') from exc
        if published.date() != permalink_day or (posts and published > posts[-1].published):
            _fail('post_year_unverified')
        body, excerpt = _field(item, CONTENT + 'encoded'), _field(item, 'description')
        if (len(body) <= len(excerpt) or not re.search(r'<(?:p|h[234])(?:\s|>)', body)
                or re.search(r'class=["\'][^"\']*\bmore-link\b', body, re.I)):
            _fail('post_full_content_required')
        title = plain(_field(item, 'title'))
        if not 1 <= len(title) <= 300:
            _fail('post_identity_unverified')
        posts.append(Post(title, link, published, body))
    return posts


def _notice(text):
    # These explicitly describe a deadline, referral or unscheduled save-the-date,
    # including the parenthetical Repair Cafe reminder. No attendance time is implied.
    return bool(re.search(r'\b(?:deadline|expression of interest|make a diary note|save.the.date)\b', text, re.I))


def _dates(text, post):
    if _notice(text):
        return []
    result = []
    for match in DATE.finditer(text):
        given = (match['year'] or '').lower()
        year = (post.published.year + 1 if given == 'next year' else
                post.published.year if given in ('', 'this year') else int(given))
        month = next(index for index, name in enumerate(MONTHS, 1)
                     if name.lower().startswith(match['month'].lower()))
        try:
            day = datetime(year, month, int(match['day'])).date()
        except ValueError as exc:
            raise ValueError('sow_event_date_unverified') from exc
        if match['weekday'] and day.strftime('%A')[:3].casefold() != match['weekday'][:3].casefold():
            _fail('event_weekday_conflict')
        result.append((day, match))
    return result


@dataclass
class Section:
    title: str
    nodes: list


def _sections(post):
    soup = BeautifulSoup(post.content, 'html.parser')
    for node in soup.select('script,style,template,noscript,nav,footer,form,figure,img,.wp-block-image,.sharedaddy'):
        node.decompose()
    nodes = [node for node in soup.find_all(['h2', 'h3', 'h4', 'p', 'li'])
             if not any(parent.name in {'p', 'li'} for parent in node.parents)]
    if not nodes or len(nodes) > MAX_NODES:
        _fail('post_sections_unverified')
    sections, current = [], Section(post.title, [])
    for node in nodes:
        label = plain(node.get_text(' ', strip=True))
        if not label:
            continue
        dates = _dates(label, post)
        # Most h4 elements supply the preceding h3's schedule. A named h4
        # event under "Other Notices" is a separate section, not another clock
        # or venue for its neighbour.
        named_h4 = node.name == 'h4' and dates and dates[0][1].start() > 10
        if node.name in {'h2', 'h3'} or named_h4:
            if current.nodes:
                sections.append(current)
            current = Section(label, [])
        else:
            current.nodes.append((node.name, label))
    if current.nodes:
        sections.append(current)
    if len(sections) > MAX_SECTIONS:
        _fail('post_sections_limit')
    return sections


def _title(label, dates):
    if dates:
        match = dates[0][1]
        label = label[:match.start()] if match.start() else label[match.end():]
        label = re.sub(r'\b(?:on|at)\s*$', '', label, flags=re.I)
    value = plain(label).strip(' ,–—-:()')
    if not 1 <= len(value) <= 180:
        _fail('event_title_unverified')
    return value


def _clock(label, meridiem=None):
    pieces = label.replace('.', ':').split(':')
    hour, minute = int(pieces[0]), int(pieces[1]) if len(pieces) == 2 else 0
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        _fail('event_time_unverified')
    if meridiem:
        if not 1 <= hour <= 12:
            _fail('event_time_unverified')
        hour = hour % 12 + (12 if meridiem.lower() == 'pm' else 0)
    return datetime(2000, 1, 1, hour, minute).time()


def _times(text):
    # An optional morning activity in parentheses is not the main event's clock.
    value = re.sub(r'\([^)]*\)', '', DATE.sub(' ', text))
    begins = re.search(r'\b(?:screening|event|session|workshop|meeting)\s+(?:begins|starts)\s+(.+)', value, re.I)
    if begins:
        value = begins[1]
    ranges = [match for match in RANGE.finditer(value)
              if match['fm'] or match['lm'] or ':' in match[0]]
    if ranges:
        if len(ranges) != 1:
            _fail('event_time_conflict')
        match = ranges[0]
        first = _clock(match['first'], match['fm'] or match['lm'])
        last = _clock(match['last'], match['lm'] or match['fm'])
        outside = value[:match.start()] + value[match.end():]
        if SINGLE.search(outside) or last <= first:
            _fail('event_time_conflict')
        return first, last
    clocks = SINGLE.findall(value)
    if not clocks:
        return None
    values = set()
    for clock in clocks:
        match = re.fullmatch(r'(' + CLOCK + r')\s*([ap]m)?', clock, re.I)
        values.add(_clock(match[1], match[2]))
    if len(values) != 1:
        _fail('event_time_conflict')
    return values.pop(), None


@dataclass
class Announcement:
    post: Post
    title: str
    day: date
    context: list
    scheduled: bool = True


def _announcements(post, today):
    last = today + timedelta(days=60)
    for section in _sections(post):
        lines = [('heading', section.title), *section.nodes]
        unscheduled = bool(TBC.search(section.title) or any(
            TBC.search(text) for kind, text in section.nodes if kind == 'h4'))
        refs = [(index, day, match) for index, (_, text) in enumerate(lines)
                for day, match in _dates(text, post)]
        if not refs:
            if unscheduled:
                continue
            if (EVENT_WORD.search(section.title)
                    and any(re.search(r'\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b(?:tomorrow|next week)\b', text, re.I)
                            for _, text in lines)):
                _fail('event_date_unverified')
            continue
        primary = refs[0][1]
        for day in dict.fromkeys(ref[1] for ref in refs):
            if not today <= day <= last:
                continue
            if day == primary:
                title = _title(section.title, _dates(section.title, post))
                context = []
                for index, line in enumerate(lines):
                    if _notice(line[1]):
                        continue
                    days = {value for value, _ in _dates(line[1], post)}
                    if days and days != {day}:
                        break  # a different inline event cannot lend this event a time/venue
                    context.append(line)
            else:
                # Inline dated notices have their own sentence and never borrow
                # the enclosing workshop's clock, title or location.
                selected = [lines[index] for index, value, _ in refs if value == day]
                context = list(dict.fromkeys(selected))
                title = _title(context[0][1], _dates(context[0][1], post))
            yield Announcement(post, title, day, context, scheduled=not unscheduled)


def _location(text):
    # Verify every explicit schedule's venue, not just the first matching hall
    # substring. A similarly named hall in another town is not this location.
    if re.search(r'\bnot\s+(?:in|at)\s+(?:the\s+)?', text, re.I):
        _fail('event_venue_unverified')
    value = re.sub(r'\([^)]*\)', '', DATE.sub(' ', text))
    value = SINGLE.sub(' ', RANGE.sub(' ', value))
    value = re.sub(r'\b(?:at|in)[\s,]+(?=(?:at|in)\b)', '', value, flags=re.I)
    named = re.findall(r'\b(?:at|in)\s+(?!\d)([^.!?;]+)', value, re.I)
    if not named:
        return False
    aliases = {'oakington church hall', "st andrew's church hall, oakington",
               "st andrew's church hall oakington"}
    for name in named:
        name = plain(name).replace('’', "'").strip(' ,').casefold()
        if name not in aliases:
            _fail('event_venue_unverified')
    return True


def _event(item):
    if not item.scheduled:
        return None  # a newer explicit TBC notice supersedes the old timed announcement
    lines = item.context
    # Prefer an explicit schedule heading, then a paragraph that repeats its
    # date, then the opening time/location paragraph of a dated heading.
    ordered = ([line for line in lines if line[0] in {'heading', 'h4'}]
               + [line for line in lines if line[0] not in {'heading', 'h4'} and _dates(line[1], item.post)]
               + [line for line in lines[1:3] if line[0] not in {'heading', 'h4'}])
    stated = [(line, times) for line in ordered if (times := _times(line[1])) is not None]
    if not stated:
        _fail('event_time_unverified')
    explicit = [(line, times) for line, times in stated
                if line[0] in {'heading', 'h4'} or _dates(line[1], item.post)]
    if len({times for _, times in explicit}) > 1:
        _fail('event_time_conflict')
    line, (start, end) = stated[0]
    venue_seen = False
    for schedule, _ in explicit or stated[:1]:
        venue_seen = _location(schedule[1]) or venue_seen
        index = lines.index(schedule)
        if index + 1 < len(lines) and re.match(r'^(?:at|in)\s+', lines[index + 1][1], re.I):
            venue_seen = _location(lines[index + 1][1]) or venue_seen
    if not venue_seen:
        _fail('event_venue_unverified')
    if any(re.search(r'\b(?:cancelled|canceled|postponed|rescheduled)\b', text, re.I) for _, text in lines):
        _fail('event_status_requires_review')
    begins = datetime.combine(item.day, start)
    finishes = datetime.combine(item.day, end) if end else None
    # Stable across duplicated/replaced articles; same-day separate sessions
    # retain separate identities. Never use a post URL as occurrence identity.
    identity = '|'.join((item.title.casefold(), begins.isoformat(), VENUE.casefold()))
    row = record(item.title, begins, finishes, VENUE, ADDRESS, 'Oakington', item.post.url,
                 'sow:' + sha256(identity.encode()).hexdigest()[:24], tz=ZONE)
    if row:
        row['timezone'] = ZONE
        row['description'] = description('\n'.join(text for kind, text in lines if kind not in {'heading', 'h4'}))
    return row


def parse(payload, *, deadline_at=None):
    _deadline(deadline_at)
    today = calendar_anchor(datetime.now(ZoneInfo(ZONE))).date()
    selected = {}
    for post in _posts(payload):
        _deadline(deadline_at)
        for item in _announcements(post, today):
            key = (item.title.casefold(), item.day)
            existing = selected.get(key, [])
            if not existing or post.published > existing[0].post.published:
                selected[key] = [item]
            elif post.published == existing[0].post.published:
                existing.append(item)
    rows = {}
    for items in selected.values():
        for item in items:
            _deadline(deadline_at)
            row = _event(item)
            if row:
                if row['id'] in rows and rows[row['id']] != row:
                    _fail('event_occurrence_conflict')
                rows[row['id']] = row
    _deadline(deadline_at)
    return sorted(rows.values(), key=lambda row: (row['starts_at'], row['id']))


def collect(source, fetch, *, deadline_at=None, listing=None):
    if source.get('feed_url') != URL or source.get('source_key') != source_key(URL):
        raise ValueError('unregistered_html_source')
    _deadline(deadline_at)
    payload = listing if listing is not None else fetch(URL, 'application/rss+xml,application/xml')
    return parse(payload, deadline_at=deadline_at)
