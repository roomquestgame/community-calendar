"""Reviewed Raleigh calendars through bounded public HTML, never export URLs.

Squarespace list cards and IndieCommerce calendar views share factual downstream
records. The publisher's own event URL/date/venue remains authoritative. Source
centers only discover calendars and are never event map pins.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sys
from time import monotonic
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.mapsee_adapter import plain, record
from roomquest.publisher_evidence import attach

TIMEZONE = 'America/New_York'
SOURCES = {
 'ponysaurus_raleigh_nc': ('https://www.ponysaurusbrewing.com/raleigh-events', '66e3b05ac3ea9d0760211ac9', '51683440e4b0e454d76df936'),
 'black_chamber_raleigh_nc': ('https://blackchamberraleigh.com/calendar', '69f37180ad6e221b457071cf', '67c620eff89a9127d2a4e200'),
 'volumes_vices_nc': ('https://www.volumesandvices.com/calendar', '695b03fd6f2cb91fb3b0f137', '68d46fbeab4210251e6677fc'),
 'makrs_society_nc': ('https://makrs.com/events', '6ae4faef62dd293d3300533f', '604d36e422e44a51184c5f42'),
 'triangle_popup_nc': ('https://trianglepopup.squarespace.com/events', '5f3d7c98782b8b752dd11339', '5f072928729b3758e7804da8'),
 'raleigh_city_farm_nc': ('https://raleighcityfarm.org/events', '5d00095a7fc15e0001b2ddf4', '5d00093c5af1640001549cb4'),
 'quail_ridge_books_nc': ('https://quailridgebooks.com/events', None, None),
 'blackbird_books_nc': ('https://www.blackbirdbooksandcoffee.com/upcoming-events', None, None),
}
MAX_PAGES = 5
MAX_CARDS = 250
MAX_DETAILS = 4
MAX_DESCRIPTION = 2000


class EventHold(ValueError):
    pass


def event_url(key, value):
    if key not in SOURCES or not isinstance(value, str):
        return False
    base = urlsplit(SOURCES[key][0]); p = urlsplit(value)
    prefix = '/event/' if SOURCES[key][1] is None else base.path.rstrip('/') + '/'
    return (p.scheme == 'https' and p.netloc == base.netloc and p.path.startswith(prefix)
            and len(p.path) > len(prefix) and len(value) <= 2000
            and not p.query and not p.fragment and not p.username and not p.password
            and not re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)
            and '..' not in p.path.split('/'))


def page_url(key, value):
    if key not in SOURCES or not isinstance(value, str):
        return False
    base = urlsplit(SOURCES[key][0]); p = urlsplit(value)
    if p.scheme != 'https' or p.netloc != base.netloc or p.fragment:
        return False
    if p.path == base.path:
        return not p.query or (SOURCES[key][1] is None and bool(re.fullmatch(r'page=[0-4]', p.query)))
    return (key == 'quail_ridge_books_nc' and not p.query
            and bool(re.fullmatch(r'/events/20[0-9]{2}/(?:0?[1-9]|1[0-2])', p.path)))


def photo_url(key, value):
    if key not in SOURCES or not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        port = p.port
    except ValueError:
        return None
    if (p.scheme != 'https' or p.username or p.password or port not in (None, 443)
            or p.netloc != p.hostname or p.fragment or '..' in p.path.split('/')
            or re.search(r'[\s\\<>]|%2e|%2f|%5c', value, re.I)
            or re.search(r'(?:^|[-_/])(?:logo|favicon|avatar|pixel)(?:[-_.]|$)', p.path, re.I)):
        return None
    website = SOURCES[key][2]
    if website:
        valid = (p.hostname == 'images.squarespace-cdn.com' and not p.query
                 and p.path.startswith('/content/v1/' + website + '/'))
    else:
        valid = (p.hostname == urlsplit(SOURCES[key][0]).hostname
                 and p.path.startswith('/sites/default/files/')
                 and (not p.query or bool(re.fullmatch(r'itok=[A-Za-z0-9_-]{1,64}', p.query))))
    return value if valid and re.search(r'\.(?:jpe?g|png|webp|gif)$', p.path, re.I) else None


def narrative(node):
    s = BeautifulSoup(str(node or ''), 'html.parser')
    for tag in s.select('script,style,template,noscript'):
        tag.decompose()
    return '\n'.join(line.strip() for line in s.get_text('\n').splitlines() if line.strip())[:MAX_DESCRIPTION]


def facts_from_text(text):
    facts = {}
    # A free drink/product is not free admission. Preserve bounded publisher
    # sentences only when they explicitly describe attendance or registration.
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', text):
        if re.search(r'\b(?:free (?:to attend|admission|entry|event)|(?:admission|tickets?|cost|price)\b[^.!?]{0,60}\$)', sentence, re.I):
            facts.setdefault('cost', sentence[:400])
        if re.search(r'\b(?:RSVP|registration|required to register|register (?:here|now|online))\b', sentence, re.I):
            facts.setdefault('registration', sentence[:400])
        if re.search(r'\b(?:all ages|ages?\s+\d|adults? only|21\+|18\+)\b', sentence, re.I):
            facts.setdefault('audience', sentence[:400])
    return facts


def address(raw):
    raw = plain(raw)
    raw = re.sub(r',?\s*United States\s*$', '', raw, flags=re.I)
    raw = re.sub(r'\bNorth Carolina\b', 'NC', raw)
    # Keep the actual street, city, state and ZIP. A named district or an
    # organization's street-free location is held for review, never geocoded
    # as though its publisher's office were the venue.
    m = re.fullmatch(r'(.+?),\s*([^,]+),\s*([A-Z]{2})(?:\s*,?\s*(\d{5}(?:-\d{4})?))?', raw)
    if not m or not re.match(r'\d{1,6}(?:[-/]\d+)?\s+[A-Za-z]', m[1]):
        raise EventHold('event_venue_unreviewed')
    street, city, state, postal = m.groups()
    return ', '.join(v for v in (street.strip(), city.strip(), state + (' ' + postal if postal else '')) if v), city.strip()


def _row(key, title, start, end, venue, raw_address, url, body, topics, image, evidence):
    street, city = address(raw_address)
    if not venue:
        venue = street
    identity = 'publisher:' + sha256(url.encode()).hexdigest()[:32]
    row = record(title, start.isoformat(), end.isoformat() if end else None,
                 venue, street, city, url, identity, ', '.join(topics),
                 tz=TIMEZONE, retain_until_end=True)
    if row:
        row.update(timezone=TIMEZONE, description=body, publisher_categories=topics,
                   location_provenance='publisher_event_address_pending_geocode')
        attach(row, key, facts=facts_from_text(body), candidate=image, evidence_url=evidence)
    return row


def _description_schedule(body, start):
    """Do not publish a card whose explicit Event Times section contradicts it."""
    if not re.search(r'\bEvent Times\s*:', body, re.I):
        return
    local = start.astimezone(ZoneInfo(TIMEZONE))
    found = []
    for weekday, month, day in re.findall(
            r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\b', body, re.I):
        m = datetime.strptime(month.title(), '%B').month
        found.append((m, int(day)))
        # These dates describe this occurrence's schedule, not a guessed year.
        if m == local.month and int(day) == local.day and weekday.casefold() != local.strftime('%A').casefold():
            raise EventHold('publisher_schedule_conflict')
    if found and (local.month, local.day) not in found:
        raise EventHold('publisher_schedule_conflict')


def _visible_time(card, start, end):
    for label, instant in (('start', start), ('end', end)):
        node = card.select_one('time.event-time-localized-' + label)
        if node is None:
            node = card.select_one('.eventlist-meta-time .event-time-12hr time.event-time-12hr-' + label)
        if node is None:
            raise EventHold('publisher_schedule_missing')
        local = instant.astimezone(ZoneInfo(TIMEZONE))
        try:
            shown = datetime.strptime(plain(node.get_text()), '%I:%M %p').time()
        except ValueError:
            raise EventHold('publisher_schedule_conflict') from None
        if node.get('datetime') != local.date().isoformat() or shown != local.time():
            raise EventHold('publisher_schedule_conflict')


def squarespace(payload, key, *, now):
    from roomquest.chase_city_chamber import _times
    s = BeautifulSoup(payload, 'html.parser')
    contexts = []
    for script in s.select('script'):
        m = re.search(r'\bStatic\.SQUARESPACE_CONTEXT\s*=\s*', script.get_text())
        if m:
            contexts.append(json.JSONDecoder().raw_decode(script.get_text()[m.end():])[0])
    if len(contexts) != 1:
        raise ValueError('publisher_calendar_identity_changed')
    c = contexts[0]; collection = c.get('collection') or {}
    if (collection.get('id') != SOURCES[key][1] or collection.get('permissionType') != 1
            or collection.get('fullUrl') != urlsplit(SOURCES[key][0]).path
            or (c.get('website') or {}).get('timeZone') != TIMEZONE):
        raise ValueError('publisher_calendar_identity_changed')
    if s.select_one('.eventlist--upcoming') is None:
        raise ValueError('unsupported_squarespace_html')
    for anchor in s.select('a[href]'):
        p = urlsplit(urljoin(SOURCES[key][0], anchor['href']))
        if p.netloc == urlsplit(SOURCES[key][0]).netloc and p.path == urlsplit(SOURCES[key][0]).path and any(k in parse_qs(p.query) for k in ('offset', 'page', 'reversePaginate')):
            raise ValueError('pagination_requires_review')
    cards = s.select('.eventlist--upcoming article.eventlist-event')
    if len(cards) > MAX_CARDS:
        raise ValueError('source_record_limit')
    rows, held = [], []
    for card in cards:
        a = card.select_one('.eventlist-title-link[href]')
        if a is None:
            raise ValueError('event_identity_missing')
        title = plain(a.get_text())
        raw_url = urljoin(SOURCES[key][0], a['href'])
        parsed_url = urlsplit(raw_url)
        if parsed_url.query or parsed_url.fragment:
            raise ValueError('invalid_event_link')
        # A reviewed Triangle Pop-Up slug contains literal spaces. Encode only
        # the path; never turn a rejected query or fragment into an event path.
        url = parsed_url._replace(path=quote(parsed_url.path, safe='/%+@-._~')).geturl()
        if not event_url(key, url):
            raise ValueError('invalid_event_link')
        body = narrative(card.select_one('.eventlist-description') or card.select_one('.eventlist-excerpt'))
        if re.search(r'\b(?:cancell?ed|postponed|members?[- ]only|private (?:event|party))\b', title, re.I):
            continue
        try:
            try:
                start, end, query = _times(card)
            except ValueError as e:
                raise EventHold(str(e)) from e
            if start is None or start >= now + timedelta(days=60) or end <= now:
                continue
            if not title or plain((query.get('text') or [''])[0]) != title:
                raise EventHold('publisher_event_identity_conflict')
            _visible_time(card, start, end)
            _description_schedule(body, start)
            locations = query.get('location') or []
            if len(locations) != 1:
                raise EventHold('event_venue_unreviewed')
            node = card.select_one('.eventlist-meta-address')
            venue = re.sub(r'\s*\(map\)\s*$', '', plain(node.get_text(' ', strip=True))) if node else ''
            topics = list(dict.fromkeys(plain(x.get_text()) for x in card.select('.eventlist-cats a') if plain(x.get_text())))[:20]
            image = card.select_one('.eventlist-column-thumbnail img')
            candidate = photo_url(key, (image.get('data-src') or image.get('src')) if image else None)
            row = _row(key, title, start, end, venue, locations[0], url, body, topics, candidate, SOURCES[key][0])
            if row:
                rows.append(row)
        except EventHold as e:
            held.append({'url': url, 'reason': str(e)})
    return _finish(rows, held, key, len(cards))


def _label(card, label):
    nodes = [x for x in card.select('.event-list__details--item')
             if (x.select_one('.event-list__details--label') is not None
                 and plain(x.select_one('.event-list__details--label').get_text()).rstrip(':') == label)]
    if len(nodes) != 1:
        raise EventHold('publisher_schedule_missing')
    return plain(nodes[0].get_text(' ', strip=True))[len(label)+1:].strip()


def _book_location(card):
    node = card.select_one('.event-details__location--location')
    if node is None:
        raise EventHold('event_venue_unreviewed')
    rich = node.select_one('.address')
    if rich:
        parts = [plain(x.get_text()) for x in rich.select('.address-line1,.address-line2')]
        city = rich.select_one('.locality'); state = rich.select_one('.administrative-area'); postal = rich.select_one('.postal-code')
        if city is None or state is None:
            raise EventHold('event_venue_unreviewed')
        street_index = next((i for i, p in enumerate(parts) if re.match(r'\d', p)), None)
        if street_index is None:
            raise EventHold('event_venue_unreviewed')
        return ' '.join(parts[:street_index]), ', '.join([*parts[street_index:], plain(city.get_text()), plain(state.get_text()) + (' ' + plain(postal.get_text()) if postal else '')])
    address_node = node.select_one('address')
    if address_node:
        parts = [plain(x) for x in address_node.stripped_strings if plain(x)]
        index = next((i for i, p in enumerate(parts) if re.match(r'\d', p)), None)
        if index is not None:
            return ' '.join(parts[:index]), ', '.join(parts[index:])
    raise EventHold('event_venue_unreviewed')


def indiecommerce(payload, key, page, *, now):
    s = BeautifulSoup(payload, 'html.parser')
    views = s.select('.view-indiecommerce-event-list')
    if len(views) != 1:
        raise ValueError('publisher_calendar_identity_changed')
    view = views[0]; cards = view.select('article.event-list')
    if not cards and view.select_one('.view-empty') is None:
        raise ValueError('unproven_empty_calendar')
    if len(cards) > MAX_CARDS:
        raise ValueError('source_record_limit')
    rows, held, dates = [], [], []
    for card in cards:
        a = card.select_one('.event-list__title a[href]')
        if a is None or not re.fullmatch(r'event-[1-9][0-9]*', card.get('id', '')):
            raise ValueError('event_identity_missing')
        url = urljoin(page, a['href']); title = plain(a.get_text())
        if not event_url(key, url):
            raise ValueError('invalid_event_link')
        try:
            date_text = _label(card, 'Date'); times = _label(card, 'Time')
            if times.casefold() == 'all day':
                continue
            if len(re.findall(r'\d{1,2}/\d{1,2}/20\d{2}', date_text)) != 1:
                raise EventHold('publisher_multiday_schedule_requires_review')
            day = datetime.strptime(re.search(r'\d{1,2}/\d{1,2}/20\d{2}', date_text)[0], '%m/%d/%Y').date()
            dates.append(day)
            clock = r'(?:1[0-2]|0?[1-9]):[0-5][0-9]\s*(?:am|pm)'
            match = re.fullmatch('('+clock+r')(?:\s*[-–]\s*('+clock+'))?', times, re.I)
            if not match:
                raise EventHold('event_time_missing')
            from roomquest.mapsee_adapter import timestamp
            def instant(v):
                wall = datetime.combine(day, datetime.strptime(re.sub(r'\s+', '', v).lower(), '%I:%M%p').time())
                return timestamp(wall.isoformat(), TIMEZONE)
            start = instant(match[1]); end = instant(match[2]) if match[2] else None
            if end and end <= start:
                raise EventHold('invalid_event_end')
            if start >= now + timedelta(days=60) or (end or start + timedelta(hours=3)) <= now:
                continue
            venue, street = _book_location(card)
            body = narrative(card.select_one('.event-list__body'))
            topics = list(dict.fromkeys(plain(x.get_text()) for x in card.select('.event-tag__term')))[:20]
            image = card.select_one('.event-list__image img')
            candidate = photo_url(key, urljoin(page, image.get('src', ''))) if image else None
            row = _row(key, title, start, end, venue, street, url, body, topics, candidate, page)
            if row:
                rows.append(row)
        except (EventHold, ValueError) as e:
            held.append({'url': url, 'reason': str(e)})
    next_links = [urljoin(page, a['href']) for a in view.select('.pager a[rel~=next][href]')]
    if key == 'quail_ridge_books_nc':
        next_links += [urljoin(page, a['href']) for a in s.select('a[href]') if plain(a.get_text()).casefold() == 'next month']
    next_links = list(dict.fromkeys(next_links))
    if len(next_links) > 1 or any(not page_url(key, u) for u in next_links):
        raise ValueError('pagination_requires_review')
    next_page = next_links[0] if next_links else None
    if next_page and key == 'quail_ridge_books_nc':
        m = re.search(r'/events/(20\d{2})/(\d{1,2})$', next_page)
        if m and datetime(int(m[1]), int(m[2]), 1, tzinfo=ZoneInfo(TIMEZONE)) >= now + timedelta(days=60):
            next_page = None
    if dates and min(dates) >= (now + timedelta(days=60)).astimezone(ZoneInfo(TIMEZONE)).date():
        next_page = None
    return _finish(rows, held, key, len(cards), allow_empty_hold=True), next_page, held


def _finish(rows, held, key, count, *, allow_empty_hold=False):
    seen = {}
    for row in rows:
        identity = (row['id'], row['starts_at'])
        if identity in seen and seen[identity] != row:
            raise ValueError('conflicting_event_occurrence')
        seen[identity] = row
    print(json.dumps({'event': 'reviewed_calendar_normalized', 'source_key': key,
                      'cards': count, 'records': len(seen), 'held': held}), file=sys.stderr)
    if not seen and held and not allow_empty_hold:
        raise ValueError('publisher_event_evidence_unavailable')
    return sorted(seen.values(), key=lambda r: (r['starts_at'], r['id']))


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key'); config = SOURCES.get(key)
    if not config or source.get('feed_url') != config[0] or source.get('kind') != 'html' or source.get('platform_adapter') != 'html':
        raise ValueError('unregistered_raleigh_source')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('calendar_now_timezone_missing')
    deadline = min(monotonic() + 36, deadline_at if deadline_at is not None else float('inf'))
    page = config[0]; visited = set(); rows = []; held = []
    for _ in range(MAX_PAGES):
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        if page in visited or not page_url(key, page):
            raise ValueError('pagination_requires_review')
        visited.add(page); payload = fetch(page, 'text/html')
        if monotonic() >= deadline:
            raise ValueError('collection_deadline')
        if config[1]:
            result = squarespace(payload, key, now=now)
            if monotonic() >= deadline:
                raise ValueError('collection_deadline')
            return result
        items, page, page_holds = indiecommerce(payload, key, page, now=now)
        rows.extend(items); held.extend(page_holds)
        if page is None:
            rows = _finish(rows, held, key, len(rows))
            return _enrich_books(rows, key, fetch, deadline)
    raise ValueError('pagination_requires_review')


def _enrich_books(rows, key, fetch, deadline):
    """Bound optional detail enrichment; all dated listing records remain usable.

    Exact canonical URL/title/start must match. Malformed publisher JSON-LD
    addresses are not used: the visible event address remains authoritative.
    A missing detail never fabricates an end time or discards valid list facts.
    """
    for row in rows[:MAX_DETAILS]:
        if monotonic() >= deadline - 8:
            break
        try:
            payload = fetch(row['event_url'], 'text/html')
            soup = BeautifulSoup(payload, 'html.parser')
            article = soup.select_one('article.eventinstance-full')
            canonical = soup.select_one('link[rel=canonical][href]')
            title = article.select_one('.event-details__info--title') if article else None
            if canonical is None or canonical['href'] != row['event_url'] or title is None or plain(title.get_text()) != row['title']:
                raise ValueError('publisher_event_identity_conflict')
            events = []
            for script in soup.select('script[type="application/ld+json"]'):
                data = json.loads(script.get_text())
                events.extend(x for x in data.get('@graph', []) if isinstance(x, dict) and x.get('@type') == 'Event' and x.get('url') == row['event_url'])
            from roomquest.mapsee_adapter import timestamp
            if len(events) != 1 or timestamp(events[0].get('startDate')) != timestamp(row['starts_at']):
                raise ValueError('publisher_event_identity_conflict')
            end = timestamp(events[0].get('endDate'))
            if end is not None and end <= timestamp(row['starts_at']):
                raise ValueError('invalid_event_end')
            body = narrative(article.select_one('.event-details__info--body'))
            if body:
                row['description'] = body
                row['publisher_details'] = facts_from_text(body)
            if end:
                row['ends_at'] = end.isoformat()
            picture = article.select_one('.event-details__image img[src]')
            candidate = photo_url(key, urljoin(row['event_url'], picture['src'])) if picture else None
            if candidate:
                attach(row, key, facts=row['publisher_details'], candidate=candidate)
        except (ValueError, TypeError, KeyError, OSError) as e:
            print(json.dumps({'event': 'reviewed_calendar_optional_detail_unavailable',
                              'source_key': key, 'event_url': row['event_url'],
                              'reason': str(e) if re.fullmatch(r'[a-z_]{3,100}', str(e)) else 'invalid_publisher_detail'}), file=sys.stderr)
    return rows
