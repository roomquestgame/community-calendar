"""South Carolina's custom JSON catalog and factual detail-page schedules.

One registered park per claim. This is not a WordPress/Tribe adapter.
No guessed times, park-wide pins, generic artwork, or cancellation inference.
"""
from collections import Counter
from datetime import datetime, timedelta
import json
import re
from time import monotonic
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach, image_url

ROOT = 'https://southcarolinaparks.com'
TIMEZONE = 'America/New_York'
MAX_EVENTS = 16
DATE = r'[A-Z][a-z]+ \d{1,2}, \d{4}'
TIME = r'\d{1,2}:\d{2} [AP]M'
SCHEDULE = re.compile(rf'^({DATE})(?: - ({DATE}))?, ({TIME}) - ({TIME})(?: Every Week on (.+))?$')
DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


def details(event, page):
    """Only the event's narrative/factual headings, never sidebar park prose."""
    soup = BeautifulSoup(page, 'html.parser')
    heading = soup.select_one('.event-heading__title')
    if heading and plain(heading.get_text(' ', strip=True)) != plain(event['name']):
        raise ValueError('park_detail_identity_mismatch')
    section = heading.find_parent(class_='copy') if heading else None
    narrative = section.select_one('.description') if section else None
    description = plain(narrative.get_text(' ', strip=True)) if narrative else plain(event.get('description'))
    facts, topics = {}, []
    if section:
        for title in section.select('h3'):
            key = plain(title.get_text(' ', strip=True)).casefold()
            value = title.find_next_sibling('p')
            # Do not let a missing field borrow the next heading's paragraph.
            sibling = title.find_next_sibling()
            if value is None or sibling is not value:
                continue
            text = plain(value.get_text(' ', strip=True))[:300]
            field = {'price': 'cost', 'ages': 'audience', 'age': 'audience',
                     'meeting place': 'meeting_location', 'registration deadline': 'registration'}.get(key)
            if field and text:
                facts[field] = text
            if key == 'civil war' and text.casefold() == 'yes':
                topics.append('Civil War')
    # Only explicit event-identity JSON-LD or an inline narrative image qualifies.
    candidate = None
    for script in soup.select('script[type="application/ld+json"]')[:20]:
        try:
            data = json.loads(script.string or script.get_text())
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                types = node.get('@type', [])
                if isinstance(types, str):
                    types = [types]
                if ('Event' in types and plain(node.get('name')) == plain(event['name'])
                        and isinstance(node.get('image'), str)):
                    candidate = image_url(urljoin(ROOT, node['image']), 'south_carolina_parks')
        except (TypeError, ValueError):
            continue
    if not candidate and narrative:
        image = narrative.select_one('img[src]')
        if image:
            candidate = image_url(urljoin(ROOT, image['src']), 'south_carolina_parks')
    suffix = '\n\n'.join(f'{label}: {facts[field]}' for label, field in
                         [('Price', 'cost'), ('Ages', 'audience'), ('Registration', 'registration'),
                          ('Meeting Place', 'meeting_location')] if field in facts)
    limit = max(0, 2000 - len(suffix) - (2 if suffix else 0))
    description = description[:limit].rstrip() + ('\n\n' + suffix if suffix else '')
    return description, facts, topics, candidate


def occurrences(page):
    section = re.search(r'<h3[^>]*>\s*DETAILS\s*</h3>(.*?)(?:<h3|</main>)', page, re.S | re.I)
    if not section:
        raise ValueError('park_schedule_missing')
    items = re.findall(r'<li[^>]*>(.*?)</li>', section[1], re.S | re.I)
    if not items:
        raise ValueError('park_schedule_missing')
    result = set()
    for item in items:
        match = SCHEDULE.fullmatch(plain(item))
        if not match:
            raise ValueError('unsupported_park_schedule')
        first, last, start, end, weekdays = match.groups()
        first = datetime.strptime(first, '%B %d, %Y').date()
        last = datetime.strptime(last, '%B %d, %Y').date() if last else first
        if last < first or (last - first).days > 366:
            raise ValueError('park_schedule_range')
        allowed = set(weekdays.split(', ')) if weekdays else None
        if allowed is not None and not allowed.issubset(DAYS):
            raise ValueError('unsupported_park_recurrence')
        # A range without explicit weekly recurrence could be one continuous
        # multi-day event. Never silently turn it into daily occurrences.
        if last != first and allowed is None:
            raise ValueError('ambiguous_park_date_range')
        day = first
        while day <= last:
            if allowed is None or DAYS[day.weekday()] in allowed:
                begins = datetime.combine(day, datetime.strptime(start, '%I:%M %p').time())
                ends = datetime.combine(day, datetime.strptime(end, '%I:%M %p').time())
                if ends <= begins:
                    raise ValueError('ambiguous_park_end_time')
                result.add((begins.isoformat(), ends.isoformat()))
            day += timedelta(days=1)
    return sorted(result)


def normalize(event, park, page):
    if event.get('parkId') != park.get('productID'):
        raise ValueError('park_identity_mismatch')
    if not park.get('address1') or not park.get('cityName') or park.get('state') != 'SC':
        raise ValueError('park_address_missing')
    address = ', '.join(plain(park.get(k)) for k in ('address1', 'address2', 'cityName', 'state', 'zip') if plain(park.get(k)))
    schedule = occurrences(page)
    # Compare multiplicity as well as dates: two sessions on one date matter.
    listed = Counter(datetime.strptime(d, '%m/%d/%Y').date() for d in event['dates'])
    parsed = Counter(datetime.fromisoformat(start).date() for start, _ in schedule)
    if any(parsed[d] != count for d, count in listed.items()):
        raise ValueError('park_occurrence_mismatch')
    rows = []
    description, facts, topics, candidate = details(event, page)
    for start, end in schedule:
        row = record(event['name'], start, end, park['name'], address,
                     park['cityName'], f"{ROOT}/products/{event['id']}",
                     f"scparks:{event['id']}:{start}", tz=TIMEZONE)
        if row:
            row['timezone'] = TIMEZONE
            row['description'] = description
            # Topics are factual evidence, not a fabricated publisher taxonomy.
            row['publisher_categories'] = topics
            attach(row, 'south_carolina_parks_' + str(park['productID']),
                   facts=facts, candidate=candidate)
            rows.append(row)
    if len(rows) > 500:
        raise ValueError('source_record_limit')
    return rows


def collect(source, fetch, *, deadline_at=None):
    key = source.get('source_key', '')
    match = re.fullmatch(r'south_carolina_parks_([1-9][0-9]{0,9})', key)
    if not match or source.get('feed_url') != ROOT + '/api/events#park=' + match[1]:
        raise ValueError('unregistered_south_carolina_park')
    park_id = int(match[1])
    deadline = min(monotonic() + 30, deadline_at or float('inf'))

    def get(path, accept):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        return fetch(ROOT + path, accept)

    parks = json.loads(get('/api/parks', 'application/json'))
    events = json.loads(get('/api/events', 'application/json'))
    if not isinstance(parks, list) or not isinstance(events, list) or len(parks) > 100 or len(events) > 1000:
        raise ValueError('unsupported_park_catalog')
    matches = [p for p in parks if p.get('productID') == park_id]
    if len(matches) != 1:
        raise ValueError('park_identity_missing')
    selected = [e for e in events if e.get('parkId') == park_id]
    if len(selected) > MAX_EVENTS:
        raise ValueError('park_detail_limit')
    rows = []
    for event in selected:
        if type(event.get('id')) is not int or event['id'] <= 0:
            raise ValueError('invalid_park_event_id')
        rows.extend(normalize(event, matches[0], get(f"/products/{event['id']}", 'text/html')))
    if len(rows) > 500:
        raise ValueError('source_record_limit')
    return rows
