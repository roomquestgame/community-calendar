"""Reviewed Gulf Coast calendars, using only public publisher event facts.

Wix indexes carry their event records in public SSR JSON. Squarespace details
are read as ordinary HTML: Rapahope forbids its JSON/ICS query endpoints.
The two plain HTML schedules use explicit published dates, never projected
weekly/annual recurrence. Transport, robots and publication remain shared.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.event_description import description
from roomquest.mapsee_adapter import address, plain, record, timestamp
from roomquest.publisher_evidence import attach
from scrapers.lib.jsonld import extract_events_from_blocks, extract_jsonld_blocks

log = logging.getLogger(__name__)
ZONE = 'America/Chicago'
WAMA = 'gulf_walter_anderson_ms'
NOTC = 'gulf_new_orleans_track_club_la'
RAPA = 'gulf_rapahope_al'
MARKETS = 'gulf_crescent_city_markets_la'
GALLERY = 'gulf_gallery_night_fl'
MAPLE = 'gulf_maple_leaf_la'
SOURCES = {
    WAMA: 'https://www.walterandersonmuseum.org/events',
    NOTC: 'https://www.runnotc.org/event-list',
    RAPA: 'https://www.rapahope.org/fundraising',
    MARKETS: 'https://crescentcityfarmersmarket.org/our-markets',
    GALLERY: 'https://gallerynightpensacola.org/2025-dates/',
    MAPLE: 'https://www.mapleleafbar.com/calendar',
}
ABOUT = 'https://gallerynightpensacola.org/about/'
WIX_APP = '140603ad-af8d-84a5-2c80-a0f60cb47351'
WIX_PREFIXES = {WAMA: '/events-1/', NOTC: '/event-details/', MAPLE: '/events/'}
WIX_OWNERS = {WAMA: 'bd9989', NOTC: '7abcb1', MAPLE: '13df8d'}
SLUG = r'[a-z0-9]+(?:-[a-z0-9]+)*'
MAX_EVENTS = 100
MAX_DETAILS = 12
EXCLUDED = re.compile(r'\b(?:cancelled|canceled|postponed)\b', re.I)
DONATION = re.compile(r'\b(?:holiday cards?|preorders?|pre-orders?|mail.orders?)\b', re.I)
MARKET_PAGES = {
    'Uptown': 'https://crescentcityfarmersmarket.org/our-markets/uptown-tuesday-market',
    'Mid-City': 'https://crescentcityfarmersmarket.org/our-markets/mid-city-thursday-market',
    'City Park': 'https://crescentcityfarmersmarket.org/our-markets/city-park-sunday',
}
# Reviewed publisher addresses, not source/headquarters centroids. Only the
# Batture has a current publisher-linked place coordinate; others use the
# existing venue resolver. The Uptown page also contains a stale embedded map.
MARKET_PLACES = {
    'Uptown': ('The Batture', '25 Walnut Street', 29.9256225, -90.1345546),
    'Mid-City': ('Lafitte Greenway Plaza', '500 N. Norman C. Francis Parkway at the Bayou', None, None),
    'City Park': ('City Putt Parking Lot', '33 Dreyfous Drive', None, None),
}


def allowed_hosts(key):
    return {urlsplit(SOURCES[key]).hostname} if key in SOURCES else set()


def _own_url(key, url):
    if key not in SOURCES or not isinstance(url, str) or len(url) > 2000:
        return False
    try:
        p = urlsplit(url)
        return bool(p.scheme == 'https' and p.netloc == urlsplit(SOURCES[key]).netloc
                    and not p.query and not p.fragment
                    and not re.search(r'[\s\\<>]|%2e|%2f|%5c', url, re.I))
    except ValueError:
        return False


def event_url(key, url):
    if not _own_url(key, url):
        return False
    if key in WIX_PREFIXES:
        return bool(re.fullmatch(re.escape(WIX_PREFIXES[key]) + SLUG, urlsplit(url).path))
    if key == RAPA:
        return bool(re.fullmatch('/fundraising/' + SLUG, urlsplit(url).path))
    if key == MARKETS:
        return url in MARKET_PAGES.values()
    return key == GALLERY and url == SOURCES[GALLERY]


def photo_url(key, url):
    """Only event-selected images from the reviewed publisher account."""
    if not isinstance(url, str) or len(url) > 2000:
        return None
    if key in WIX_OWNERS:
        pattern = (r'https://static[.]wixstatic[.]com/media/' + WIX_OWNERS[key]
                   + r'_[a-f0-9]{32}(?:~|%7E)mv2[.](?:jpe?g|png|webp)')
    elif key == RAPA:
        pattern = (r'https://images[.]squarespace-cdn[.]com/content/v1/'
                   r'5e7d112f9b046e73144336fd/[A-Za-z0-9-]+/'
                   r'[A-Za-z0-9_+.%-]+[.](?:jpe?g|png|webp)')
    else:
        return None
    if re.search(r'%2e|%2f|%5c', url, re.I):
        return None
    return url if re.fullmatch(pattern, url, re.I) else None


def _fetch_page(key, url, fetch, deadline_at):
    permitted = url == SOURCES[key] or event_url(key, url) or key == GALLERY and url == ABOUT
    if not permitted or not _own_url(key, url):
        raise ValueError('gulf_recurring_fetch_url_unverified')
    if deadline_at is not None and monotonic() >= deadline_at:
        raise ValueError('collection_deadline')
    payload = fetch(url, 'text/html')
    soup = BeautifulSoup(payload, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"]')
    if key == MARKETS:
        base = soup.select_one('base[href]')
        if not base or base['href'] != 'https://crescentcityfarmersmarket.org/':
            raise ValueError('gulf_recurring_publisher_unverified')
    elif not canonical or canonical.get('href') != url:
        raise ValueError('gulf_recurring_publisher_unverified')
    return soup, payload


def _text(node):
    return plain(node.get_text(' ', strip=True)) if node else ''


def _hold(key, identity, reason):
    log.warning('publisher_event_held source=%s occurrence=%r reason=%s', key, identity, reason)


def _dated(value):
    if not isinstance(value, str) or not re.match(r'20\d{2}-\d{2}-\d{2}T', value):
        raise ValueError('gulf_recurring_schedule_unverified')
    result = timestamp(value)
    if result is None or result.utcoffset() is None:
        raise ValueError('gulf_recurring_schedule_unverified')
    return result


def _clock(day, text):
    value = re.sub(r'\s+', '', text).upper().replace('.', '')
    fmt = '%I:%M%p' if ':' in value else '%I%p'
    return timestamp(datetime.combine(day, datetime.strptime(value, fmt).time()), ZONE)


def _window(start, end, now):
    if end is not None and end <= start:
        raise ValueError('gulf_recurring_invalid_schedule')
    return start < now + timedelta(days=60) and (end or start + timedelta(hours=3)) > now


def _row(key, identity, title, start, end, venue, street, city, url, now,
         *, lat=None, lng=None, narrative='', image=None, facts=None):
    if not event_url(key, url):
        raise ValueError('gulf_recurring_event_identity_unverified')
    if EXCLUDED.search(title + ' ' + narrative) or not _window(start, end, now):
        return None
    row = record(title, start, end, venue, street, city, url, identity,
                 lat=lat, lng=lng, tz=ZONE, retain_until_end=True)
    if row is not None:
        row.update(description=description(narrative), timezone=ZONE, attendance_mode='in_person')
        attach(row, key, facts=facts, candidate=image, evidence_url=SOURCES[key])
    return row


def _street_words(value):
    aliases = {'street': 'st', 'avenue': 'ave', 'drive': 'dr', 'road': 'rd',
               'boulevard': 'blvd', 'lane': 'ln', 'parkway': 'pkwy'}
    return [aliases.get(word, word) for word in re.findall(r'[a-z0-9]+', value.lower())]


def _wix_location(key, item):
    loc = item.get('location')
    if not isinstance(loc, dict) or loc.get('tbd') is not False or loc.get('type') != 0:
        return None
    full = loc.get('fullAddress')
    if not isinstance(full, dict):
        return None
    venue, street, city = plain(loc.get('name')), plain(loc.get('address')), plain(full.get('city'))
    expected_region = 'MS' if key == WAMA else 'LA'
    if (not venue or not city or full.get('country') != 'US'
            or full.get('subdivision') != expected_region
            or street != plain(full.get('formattedAddress'))
            or not re.search(r',\s*' + re.escape(city) + r',\s*' + expected_region + r'\s+\d{5}\b', street)):
        return None
    structured_street = full.get('streetAddress') or {}
    number = str(structured_street.get('number') or '')
    if not number:
        # Reviewed NOTC Rivertown is a district, not an exact race start pin.
        if key == NOTC and venue == 'Rivertown' and city == 'Kenner':
            return venue, street, city, None, None
        return None
    if (not re.match(re.escape(number) + r'\s+', street)
            or _street_words(street.split(',')[0])
            != _street_words(number + ' ' + plain(structured_street.get('name')))):
        return None
    coords, geocode = loc.get('coordinates') or {}, full.get('geocode') or {}
    try:
        lat, lng = float(coords['lat']), float(coords['lng'])
        if (not math.isfinite(lat) or not math.isfinite(lng)
                or not 25 < lat < 36 or not -95 < lng < -85
                or abs(lat - float(geocode['latitude'])) > 0.00001
                or abs(lng - float(geocode['longitude'])) > 0.00001):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if key == MAPLE and (venue != 'Maple Leaf Bar' or not street.startswith('8316 Oak St,')):
        return None
    return venue, street, city, lat, lng


def _maple_audience(soup):
    visible = _text(soup)
    if (not re.search(r'\bALL\s+SHOWS\s+21\s*\+(?=\s|$)', visible, re.I)
            or not re.search(r'Everyone must show a valid form of ID at the door\.', visible, re.I)):
        raise ValueError('gulf_maple_audience_unverified')
    # This is the calendar-wide policy, not text on an individual event page.
    # Name its evidence in the fact while retaining the event identity envelope.
    return '21+; valid ID required at the door. Calendar policy: ' + SOURCES[MAPLE]


def _wix(key, soup, now):
    audience = _maple_audience(soup) if key == MAPLE else None
    script = soup.select_one('script#wix-warmup-data[type="application/json"]')
    if script is None:
        raise ValueError('gulf_wix_calendar_missing')
    try:
        widgets = json.loads(script.string or script.get_text())['appsWarmupData'][WIX_APP]
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('gulf_wix_calendar_invalid') from exc
    if not isinstance(widgets, dict):
        raise ValueError('gulf_wix_calendar_invalid')
    complete, events = 0, {}
    for widget in widgets.values():
        envelope = widget.get('events') if isinstance(widget, dict) else None
        if not isinstance(envelope, dict):
            continue
        if envelope.get('hasMore') is True or envelope.get('moreLoading') is True:
            raise ValueError('gulf_wix_pagination_requires_review')
        if envelope.get('hasMore') is not False:
            # A separate featured-event widget is not the complete calendar.
            continue
        complete += 1
        items = envelope.get('events')
        if not isinstance(items, list) or len(items) > MAX_EVENTS:
            raise ValueError('gulf_wix_calendar_limit')
        for item in items:
            if not isinstance(item, dict) or not re.fullmatch(
                    r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', str(item.get('id', ''))):
                raise ValueError('gulf_wix_event_identity_unverified')
            identity = item['id']
            if identity in events and events[identity] != item:
                raise ValueError('gulf_wix_event_identity_conflict')
            events[identity] = item
    if not complete or len(events) > MAX_EVENTS:
        raise ValueError('gulf_wix_calendar_incomplete')
    for identity, item in events.items():
        config = (item.get('scheduling') or {}).get('config') or {}
        title, slug = plain(item.get('title')), item.get('slug')
        if (item.get('status') != 0 or config.get('scheduleTbd') is not False
                or config.get('timeZoneId') != ZONE or not item.get('publishedDate')):
            _hold(key, identity, 'unverified_status_or_schedule')
            continue
        if not title or not isinstance(slug, str) or not re.fullmatch(SLUG, slug):
            raise ValueError('gulf_wix_event_identity_unverified')
        start = _dated(config.get('startDate'))
        end = None if config.get('endDateHidden') else _dated(config.get('endDate'))
        if not _window(start, end, now):
            continue
        location = _wix_location(key, item)
        if location is None:
            _hold(key, identity, 'conflicting_or_missing_venue')
            continue
        venue, street, city, lat, lng = location
        url = 'https://' + urlsplit(SOURCES[key]).netloc + WIX_PREFIXES[key] + slug
        image = (item.get('mainImage') or {}).get('url')
        narrative = item.get('description') or item.get('about') or ''
        facts = {'audience': audience} if audience else {}
        if lat is None:
            facts['meeting_location'] = 'Rivertown district; exact starting point is not supplied.'
        row = _row(key, identity, title, start, end, venue, street, city, url, now,
                   lat=lat, lng=lng, narrative=narrative, image=image, facts=facts)
        if row:
            yield row


def _rapahope(soup, fetch, now, deadline_at):
    cards = soup.select('article.eventlist-event--upcoming')
    if not cards and not soup.select_one('.eventlist'):
        raise ValueError('gulf_rapahope_calendar_missing')
    if soup.select_one('.eventlist-pagination a[href]'):
        raise ValueError('gulf_rapahope_pagination_requires_review')
    if len(cards) > MAX_EVENTS:
        raise ValueError('gulf_rapahope_calendar_limit')
    seen = set()
    for card in cards:
        link = card.select_one('a.eventlist-title-link[href]')
        if not link:
            raise ValueError('gulf_rapahope_event_identity_unverified')
        title = _text(link)
        if DONATION.search(title) or EXCLUDED.search(_text(card)):
            continue
        first = card.select_one('time.event-time-localized-start[datetime]')
        last = card.select_one('time.event-time-localized-end[datetime]')
        if not first or not last:
            _hold(RAPA, title, 'missing_explicit_attendance_hours')
            continue
        start = _clock(datetime.fromisoformat(first['datetime']).date(), _text(first))
        end = _clock(datetime.fromisoformat(last['datetime']).date(), _text(last))
        if not _window(start, end, now):
            continue
        url = urljoin(SOURCES[RAPA], link['href'])
        if not event_url(RAPA, url):
            raise ValueError('gulf_rapahope_event_url_unverified')
        if url in seen:
            continue
        seen.add(url)
        if len(seen) > MAX_DETAILS:
            raise ValueError('gulf_rapahope_detail_limit')
        detail, payload = _fetch_page(RAPA, url, fetch, deadline_at)
        items = extract_events_from_blocks(extract_jsonld_blocks(payload))
        if len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError('gulf_rapahope_event_data_missing')
        item = items[0]
        visible_title = _text(detail.select_one('h1.eventitem-title'))
        schema_title = re.sub(r'\s+[—–-]\s+Rapahope$', '', plain(item.get('name')))
        if (title != visible_title or title != schema_title
                or _dated(item.get('startDate')) != start or _dated(item.get('endDate')) != end):
            raise ValueError('gulf_rapahope_event_identity_conflict')
        if EXCLUDED.search(str(item.get('eventStatus', ''))):
            continue
        loc = item.get('location') or {}
        street = address(loc.get('address'))
        venue = plain(loc.get('name'))
        metadata = {m.get('property'): m.get('content') for m in detail.select('meta[property][content]')}
        city, region = metadata.get('og:locality'), metadata.get('og:region')
        if (not venue or region != 'AL' or not city
                or not street.startswith(str(metadata.get('og:street-address') or '\0'))
                or not re.search(re.escape(city) + r',?\s+AL,?\s+' + re.escape(metadata.get('og:postal-code') or '\0'), street)):
            _hold(RAPA, url, 'conflicting_or_missing_venue')
            continue
        # The Event PostalAddress is a newline-delimited string. Normalize its
        # verified event-specific fields without losing the street/city boundary.
        street = f"{metadata['og:street-address']}, {city}, AL {metadata['og:postal-code']}"
        body = detail.select_one('body[id^="item-"]')
        identity = (body.get('id', '') if body else '').removeprefix('item-')
        if not re.fullmatch(r'[a-f0-9]{24}', identity):
            raise ValueError('gulf_rapahope_event_identity_unverified')
        image = card.select_one('img.eventlist-thumbnail')
        narrative = description(str(detail.select_one('.eventitem-column-content') or ''))
        row = _row(RAPA, identity, title, start, end, venue, street, city, url, now,
                   lat=metadata.get('og:latitude'), lng=metadata.get('og:longitude'), narrative=narrative,
                   image=image.get('src') if image else None)
        if row:
            yield row


def _markets(soup, now):
    cards = [node for node in soup.select('.card') if node.select_one('.card-divider .text-uc')]
    if len(cards) != 3:
        raise ValueError('gulf_markets_schedule_incomplete')
    seen = set()
    for card in cards:
        name = _text(card.select_one('.card-divider .text-uc'))
        section = card.select_one('.card-section')
        if name not in MARKET_PLACES or name in seen or section is None:
            raise ValueError('gulf_markets_identity_unverified')
        seen.add(name)
        venue, raw_street, lat, lng = MARKET_PLACES[name]
        if _text(section.select_one('p')) != f'{venue} {raw_street}':
            raise ValueError('gulf_markets_venue_changed')
        day = datetime.strptime(_text(section.select_one('h4')), '%B %d, %Y').date()
        times = re.split(r'\s*[-–—]\s*', _text(section.select_one('h5')))
        if len(times) != 2:
            raise ValueError('gulf_markets_schedule_unverified')
        start, end = [_clock(day, value) for value in times]
        # City Park's own calendar supplies the complete explicitly dated market
        # series. Its title/URL differ from this summary card, so shared identity
        # cannot deduplicate the overlap. Validate all three cards, but emit this
        # source's distinct Uptown and Mid-City markets only.
        if name == 'City Park':
            continue
        street = raw_street.removesuffix(' at the Bayou') + ', New Orleans, LA'
        yield _row(MARKETS, name.lower().replace(' ', '-') + ':' + day.isoformat(),
                   'Crescent City Farmers Market — ' + name, start, end, venue,
                   street, 'New Orleans', MARKET_PAGES[name], now, lat=lat, lng=lng)


def _gallery(soup, fetch, now, deadline_at):
    heading = re.fullmatch(r'(20\d{2}) Dates', _text(soup.select_one('h1.entry-title')))
    content = soup.select_one('.entry-content')
    if not heading or content is None:
        raise ValueError('gulf_gallery_season_unverified')
    about, _ = _fetch_page(GALLERY, ABOUT, fetch, deadline_at)
    about_text = _text(about)
    if not re.search(r'third Friday of each month from 5[–-]9 p\.m\.', about_text):
        raise ValueError('gulf_gallery_hours_changed')
    if 'downtown Palafox between Main Street and Garden Street' not in about_text:
        raise ValueError('gulf_gallery_venue_changed')
    entries = []
    for paragraph in content.select('p'):
        for line in paragraph.get_text('\n', strip=True).splitlines():
            match = re.fullmatch(r'([A-Z][a-z]+) (\d{1,2})\s*[–—-]\s*(.+)', plain(line))
            if match:
                day = datetime.strptime(f'{match[1]} {match[2]} {heading[1]}', '%B %d %Y').date()
                entries.append((day, match[3].strip('“”"')))
    if not entries or len(entries) > 24 or len({d for d, _ in entries}) != len(entries):
        raise ValueError('gulf_gallery_schedule_unverified')
    # This reviewed local-hours rule intentionally ignores the erroneous UTC
    # suffix on the homepage countdown. The publisher's visible hours govern.
    for day, theme in entries:
        yield _row(GALLERY, 'gallery-night:' + day.isoformat(), 'Gallery Night Pensacola — ' + theme,
                   _clock(day, '5 PM'), _clock(day, '9 PM'), 'Palafox Place',
                   'Palafox Place between Main Street and Garden Street, Pensacola, FL 32502',
                   'Pensacola', SOURCES[GALLERY], now,
                   narrative='Gallery Night takes place from 5–9 p.m. local time on Palafox '
                             'between Main Street and Garden Street.',
                   facts={'meeting_location': 'Palafox between Main Street and Garden Street.'})


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    if (key not in SOURCES or tuple(source.get(k) for k in ('feed_url', 'kind', 'platform_adapter', 'timezone'))
            != (SOURCES[key], 'html', 'html', ZONE)):
        raise ValueError('unregistered_gulf_recurring_source')
    now = now or datetime.now(ZoneInfo(ZONE))
    if now.tzinfo is None:
        raise ValueError('gulf_recurring_timezone_unresolved')
    now = now.astimezone(ZoneInfo(ZONE))
    soup, _ = _fetch_page(key, SOURCES[key], fetch, deadline_at)
    if key in WIX_PREFIXES:
        rows = _wix(key, soup, now)
    elif key == RAPA:
        rows = _rapahope(soup, fetch, now, deadline_at)
    elif key == MARKETS:
        rows = _markets(soup, now)
    else:
        rows = _gallery(soup, fetch, now, deadline_at)
    result = {}
    for row in rows:
        if row is None:
            continue
        if row['id'] in result and result[row['id']] != row:
            raise ValueError('gulf_recurring_occurrence_conflict')
        result[row['id']] = row
    return sorted(result.values(), key=lambda row: (row['starts_at'], row['id']))
