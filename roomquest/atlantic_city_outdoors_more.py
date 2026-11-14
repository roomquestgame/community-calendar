"""Atlantic Cape's public campus programs, using its native Localist feed.

The API supplies complete narratives, explicit occurrence offsets and publisher
audience/venue data. The general Localist adapter intentionally omits narratives,
so this reviewed source retains them without changing unrelated source behavior.
All requests use the caller's existing guarded public transport.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from roomquest.atlantic_city_community import _full_description
from roomquest.mapsee_adapter import plain, record, timestamp


log = logging.getLogger(__name__)
ZONE = 'America/New_York'
ATLANTIC_CAPE = 'atlantic_cape_public_events_nj'
EHT_TROT = 'eht_nature_reserve_turkey_trot_nj'
EHT_ROOT = 'https://runsignup.com/Race/NJ/EggHarborTownship/EHTNatureReserveTurkeyTrot5k1Miler'
EHT_EVENTS = 'https://runsignup.com/Race/Events/NJ/EggHarborTownship/EHTNatureReserveTurkeyTrot5k1Miler'
EHT_VENUE = 'Egg Harbor Township Nature Reserve'
# The race's complete directions and reserve's own location page agree on 318;
# the terse Place box uses 317. Use the reviewed Zion Road entrance, keeping the
# separate 391 Zion Road parking/shuttle instructions in the complete narrative.
# https://sites.google.com/site/ehtnatres/location
EHT_STREET = '318 Zion Road, Egg Harbor Township, NJ 08234'
SOURCES = {ATLANTIC_CAPE: ('https://events.atlanticcape.edu/', 'html', 'html'),
           EHT_TROT: (EHT_ROOT, 'html', 'html')}
ALLOWED_HOSTS = {ATLANTIC_CAPE: ('events.atlanticcape.edu',), EHT_TROT: ('runsignup.com',)}
API = 'https://events.atlanticcape.edu/api/2/events'
MAX_PAGES = 5
MAX_RECORDS = 500
PUBLIC_AUDIENCES = {'General Public', 'Prospective Students'}

# Current official event/venue directory, reviewed November 14, 2026. These are
# campus streets, not invented room positions. A missing event point goes to the
# normal geocoder instead of borrowing another room's coordinates.
# https://events.atlanticcape.edu/pitney-gymnasium-mays-landing-campus
# https://events.atlanticcape.edu/event/star-party-2026
# https://events.atlanticcape.edu/event/atlantic-cape-clash-2026-02
MAYS_STREET = '5100 Black Horse Pike, Mays Landing, NJ 08330'
AC_STREET = '1535 Bacharach Boulevard, Atlantic City, NJ 08401'
VENUES = {
    'Mays Landing Campus': (MAYS_STREET, 'Mays Landing'),
    'Mays Landing Campus - Art Gallery': (MAYS_STREET, 'Mays Landing'),
    'Mays Landing Campus - Pitney Gymnasium': (MAYS_STREET, 'Mays Landing'),
    'Mays Landing Campus - J Building Lobby': (MAYS_STREET, 'Mays Landing'),
    'Mays Landing Campus - STEM Lobby': (MAYS_STREET, 'Mays Landing'),
    'Mays Landing Campus: G Building Lobby/Student Center': (MAYS_STREET, 'Mays Landing'),
    'Mays Landing Campus-Innovation Center': (MAYS_STREET, 'Mays Landing'),
    'Atlantic City Campus': (AC_STREET, 'Atlantic City'),
    'Atlantic City Campus - Cafeteria': (AC_STREET, 'Atlantic City'),
    'Atlantic City Campus - 1st Floor Lobby': (AC_STREET, 'Atlantic City'),
}
NONPUBLIC = re.compile(r'\b(?:invitation[- ]only|students?[- ]only|staff[- ]only|private event)\b', re.I)


def event_url(source_key, value):
    if source_key not in SOURCES or not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        if source_key == EHT_TROT:
            return (p.scheme == 'https' and p.netloc == 'runsignup.com'
                    and not p.query and not p.username and not p.password and p.port in (None, 443)
                    and p.path == urlsplit(EHT_EVENTS).path
                    and bool(re.fullmatch(r'event-[1-9][0-9]{0,9}', p.fragment)))
        return (p.scheme == 'https' and p.netloc == 'events.atlanticcape.edu'
                and not p.query and not p.fragment and not p.username and not p.password
                and p.port in (None, 443)
                and bool(re.fullmatch(r'/event/[a-z0-9][a-z0-9_-]{0,250}', p.path, re.I)))
    except ValueError:
        return False


def photo_url(source_key, value):
    if source_key not in SOURCES or not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        if source_key == EHT_TROT:
            return value if (p.scheme == 'https' and p.netloc == 'd368g9lw5ileu7.cloudfront.net'
                             and not p.query and not p.fragment and not p.username and not p.password
                             and re.fullmatch(r'/races/races-13xxx/13178/race(?:Banner|Logo)-[A-Za-z0-9-]+\.(?:jpe?g|png|webp)', p.path)) else None
        return value if (p.scheme == 'https' and p.netloc == 'localist-images.azureedge.net'
                         and not p.query and not p.fragment and not p.username and not p.password
                         and p.port in (None, 443)
                         and re.fullmatch(r'/photos/[1-9][0-9]*/huge/[a-z0-9-]+\.(?:jpe?g|png|webp)', p.path, re.I)) else None
    except ValueError:
        return None


def _hold(identity, reason):
    log.warning('atlantic_cape_record_held source=%s id=%s reason=%s', ATLANTIC_CAPE, identity, reason)


def _labels(event, key):
    values = (event.get('filters') or {}).get(key, [])
    if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
        raise ValueError('atlantic_cape_filters_changed')
    return [plain(v.get('name')) for v in values if plain(v.get('name'))]


def _public(event, body):
    if (event.get('private') is not False or event.get('rejected') is not False
            or event.get('publish_status') != 'published' or event.get('status') != 'live'
            or event.get('experience') != 'inperson' or NONPUBLIC.search(body)):
        return False
    if PUBLIC_AUDIENCES.intersection(_labels(event, 'event_audiences')):
        return True
    # The publisher marks this series Students, but explicitly opens paid entry
    # to regional players aged 13+. Require the live admission and locality text;
    # never generalize this exception to other student programs.
    return (plain(event.get('title')) == 'Esports Tournament Series: Atlantic Cape Clash'
            and 'Open to players ages 13+.' in body
            and 'Cape May, Cumberland, and Atlantic counties' in body)


def _location(event):
    venue = plain(event.get('location_name'))
    known = VENUES.get(venue)
    if not known:
        return None
    address, city = known
    geo = event.get('geo') or {}
    if not isinstance(geo, dict):
        raise ValueError('atlantic_cape_location_changed')
    # Only the two reviewed campus streets qualify. Do not repair an away
    # game's blank address into the college headquarters or move a new venue.
    def street_key(value):
        street = plain(value).split(',', 1)[0].casefold()
        street = re.sub(r'\bboulevard\b', 'blvd', street)
        return re.sub(r'[^a-z0-9]', '', street)
    expected_street = street_key(address)
    # Validate both fields independently: structured geometry must not hide a
    # conflicting visible address, even if the building number is unchanged.
    for advertised in (geo.get('street'), event.get('address')):
        if advertised and street_key(advertised) != expected_street:
            return None
    expected_zip = '08330' if address == MAYS_STREET else '08401'
    allowed_cities = {'Mays Landing', 'Hamilton'} if address == MAYS_STREET else {'Atlantic City'}
    if geo.get('city') and plain(geo['city']) not in allowed_cities:
        return None
    if geo.get('state') and plain(geo['state']) not in {'NJ', 'New Jersey'}:
        return None
    if geo.get('zip') and str(geo['zip']).zfill(5) != expected_zip:
        return None
    raw_address = plain(event.get('address'))
    if ',' in raw_address:
        locality = [part.strip() for part in raw_address.split(',')]
        if (len(locality) != 3 or locality[1] not in allowed_cities
                or not re.fullmatch(r'(?:New Jersey|NJ)\s+0?' + expected_zip.lstrip('0'), locality[2])):
            return None
    lat = lng = None
    if geo.get('latitude') is not None or geo.get('longitude') is not None:
        try:
            lat, lng = float(geo['latitude']), float(geo['longitude'])
        except (TypeError, ValueError, KeyError):
            raise ValueError('atlantic_cape_location_changed')
        if not (math.isfinite(lat) and math.isfinite(lng)
                and 39.2 < lat < 39.7 and -74.9 < lng < -74.2):
            raise ValueError('atlantic_cape_location_changed')
    room = plain(event.get('room_number'))
    return ', '.join(v for v in (venue, room) if v), address, city, lat, lng


def _instant(value):
    if not isinstance(value, str) or not re.search(r'T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$', value):
        raise ValueError('atlantic_cape_occurrence_time_unresolved')
    return timestamp(value)


def parse_events(events, now):
    """Normalize complete API event wrappers; omissions have explicit holds."""
    output = {}
    for wrapper in events:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get('event'), dict):
            raise ValueError('atlantic_cape_payload_changed')
        event = wrapper['event']
        identity = event.get('id')
        if not isinstance(identity, int) or identity <= 0:
            raise ValueError('atlantic_cape_identity_changed')
        body = _full_description(event.get('description'))
        if not body or not _public(event, body):
            _hold(identity, 'description_or_public_eligibility_unavailable')
            continue
        location = _location(event)
        if location is None:
            _hold(identity, 'outside_reviewed_local_campus_or_location_conflict')
            continue
        # Current December17 item reuses Battle by the Bay prose while its
        # structured venue is the Mays Landing gym. Leave that exact conflict
        # held until the publisher removes the contradictory event narrative.
        if identity == 54436258716731 and 'Battle by the Bay' in body:
            _hold(identity, 'battle_by_the_bay_venue_conflict')
            continue
        url = event.get('localist_url')
        if not event_url(ATLANTIC_CAPE, url):
            raise ValueError('atlantic_cape_identity_changed')
        instances = event.get('event_instances')
        if not isinstance(instances, list) or not instances:
            raise ValueError('atlantic_cape_occurrences_missing')
        for entry in instances:
            if not isinstance(entry, dict) or not isinstance(entry.get('event_instance'), dict):
                raise ValueError('atlantic_cape_occurrence_changed')
            instance = entry['event_instance']
            iid = instance.get('id')
            if not isinstance(iid, int) or iid <= 0 or instance.get('event_id') != identity:
                raise ValueError('atlantic_cape_occurrence_changed')
            if instance.get('all_day') is not False:
                _hold(iid, 'publisher_clock_missing')
                continue
            start = _instant(instance.get('start'))
            end = _instant(instance['end']) if instance.get('end') else None
            if end is not None and end <= start:
                raise ValueError('atlantic_cape_occurrence_time_conflict')
            if start >= now + timedelta(days=60) or (end or start + timedelta(hours=3)) <= now:
                continue
            venue, address, city, lat, lng = location
            categories = list(dict.fromkeys(_labels(event, 'event_types') + _labels(event, 'event_topics')))
            row = record(event.get('title'), start.isoformat(), end.isoformat() if end else None,
                         venue, address, city, url, f'atlanticcape:{identity}:{iid}',
                         ', '.join(categories), lat=lat, lng=lng, tz=ZONE,
                         publisher_geo=lat is not None, retain_until_end=True)
            if row is None:
                continue
            row.update(description=body, timezone=ZONE, attendance_mode='in_person',
                       publisher_categories=categories,
                       location_provenance=('publisher_event_geo' if lat is not None else
                                            'reviewed_campus_street_address_pending_geocode'))
            if candidate := photo_url(ATLANTIC_CAPE, event.get('photo_url')):
                row['image_url'] = candidate
            key = (row['id'], row['starts_at'])
            if key in output and output[key] != row:
                raise ValueError('atlantic_cape_conflicting_occurrence')
            output[key] = row
            if len(output) > MAX_RECORDS:
                raise ValueError('source_record_limit')
    return list(output.values())


def _race_schema(soup):
    result = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get('@type') == 'SportsEvent':
            result.append(obj)
    return result


def _race_clock(day, value):
    match = re.fullmatch(r'(\d{1,2}:\d{2})\s*([AP]M)\s+(E[DS]T)', plain(value), re.I)
    if not match:
        raise ValueError('eht_trot_clock_unresolved')
    clock = datetime.strptime(match[1] + match[2].upper(), '%I:%M%p').time()
    result = timestamp(datetime.combine(day, clock), ZONE)
    if result.tzname() != match[3].upper():
        raise ValueError('eht_trot_clock_conflict')
    return result


def _turkey_trot(main, details, now):
    """Use the native two-distance manifest and the complete HTML narrative."""
    soup, detail = BeautifulSoup(main, 'html.parser'), BeautifulSoup(details, 'html.parser')
    parent = [e for e in _race_schema(soup) if e.get('additionalType') == 'Product']
    if len(parent) != 1 or parent[0].get('url') != EHT_ROOT:
        raise ValueError('eht_trot_source_identity_changed')
    parent = parent[0]
    day = _instant(parent.get('startDate')).astimezone(ZoneInfo(ZONE)).date()
    if day < now.astimezone(ZoneInfo(ZONE)).date() or day > (now + timedelta(days=60)).date():
        return []
    full = soup.select_one('#raceFullDesc')
    if full is None or not (body := _full_description(str(full))):
        raise ValueError('eht_trot_description_missing')
    advertised = re.search(r'\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*'
                           r'([A-Z]+)\s+(\d{1,2}),\s*(20\d{2})\s+at\s+'
                           r'(\d{1,2}(?::\d{2})?\s*[AP]M)', body, re.I)
    if advertised is None:
        raise ValueError('eht_trot_clock_unresolved')
    published_day = datetime.strptime(' '.join(advertised.group(i) for i in (2, 3, 4)), '%B %d %Y').date()
    clock_text = re.sub(r'\s+', '', advertised[5]).upper()
    published_clock = datetime.strptime(clock_text, '%I:%M%p' if ':' in clock_text else '%I%p').time()
    if (published_day != day or day.strftime('%A').casefold() != advertised[1].casefold()
            or timestamp(datetime.combine(day, published_clock), ZONE) != _instant(parent['startDate'])):
        raise ValueError('eht_trot_clock_conflict')
    # Keep the current organizer's entrance rather than the different shuttle
    # parking address or a similarly named offsite race.
    if ('The EHT Nature Reserve is located at 318 Zion Road' not in body
            or parent.get('location', {}).get('address', {}).get('addressRegion') != 'NJ'):
        raise ValueError('eht_trot_venue_changed')
    manifest = {}
    for card in soup.select('.rsuEventTile__content'):
        label = card.select_one('.rsuEventTile__header a[href]')
        signup = card.select_one('a[href*="raceId="][href*="eventId="]')
        if label is None or signup is None:
            raise ValueError('eht_trot_manifest_changed')
        url = urljoin(EHT_ROOT, label['href'])
        if not event_url(EHT_TROT, url):
            raise ValueError('eht_trot_manifest_changed')
        identity = urlsplit(url).fragment.removeprefix('event-')
        q = parse_qs(urlsplit(signup['href']).query)
        if q.get('raceId') != ['13178'] or q.get('eventId') != [identity] or identity in manifest:
            raise ValueError('eht_trot_source_identity_changed')
        manifest[identity] = (plain(label.get_text()), url)
    if not 1 <= len(manifest) <= 12:
        raise ValueError('eht_trot_manifest_changed')
    rows, seen = [], set()
    for event in _race_schema(detail):
        if event.get('additionalType'):
            continue
        url = event.get('url')
        if not event_url(EHT_TROT, url):
            raise ValueError('eht_trot_event_identity_changed')
        identity = urlsplit(url).fragment.removeprefix('event-')
        if identity not in manifest or identity in seen or plain(event.get('name')) != manifest[identity][0]:
            raise ValueError('eht_trot_event_identity_changed')
        seen.add(identity)
        state = str(event.get('eventStatus') or 'EventScheduled').rsplit('/', 1)[-1]
        if state in {'EventCancelled', 'EventPostponed', 'EventRescheduled'}:
            continue
        if state != 'EventScheduled':
            raise ValueError('eht_trot_status_changed')
        card = detail.select_one('#event-' + identity)
        heading = card.select_one('h2') if card else None
        if heading is None or plain(heading.get_text()) != manifest[identity][0]:
            raise ValueError('eht_trot_event_identity_changed')
        clocks = {plain(dt.get_text()): plain(dt.find_next_sibling('dd').get_text())
                  for dt in card.select('dt') if dt.find_next_sibling('dd') is not None}
        start = _instant(event.get('startDate'))
        if start.astimezone(ZoneInfo(ZONE)).date() != day or _race_clock(day, clocks.get('Start Time:')) != start:
            raise ValueError('eht_trot_clock_conflict')
        # RunSignup synthesizes a three-hour end in JSON-LD. An end is accepted
        # only if an explicit visible End Time independently confirms it.
        end = _race_clock(day, clocks['End Time:']) if clocks.get('End Time:') else None
        if end is not None and (end <= start or end != _instant(event.get('endDate'))):
            raise ValueError('eht_trot_clock_conflict')
        if not now < (end or start + timedelta(hours=3)) or start >= now + timedelta(days=60):
            continue
        addr = (event.get('location') or {}).get('address') or {}
        if (addr.get('streetAddress'), addr.get('addressLocality'), addr.get('addressRegion'), addr.get('postalCode')) != (
                EHT_VENUE, 'Egg Harbor Township', 'NJ', '08234'):
            raise ValueError('eht_trot_venue_changed')
        notes = card.select_one('.margin-tb-10')
        narrative = body + ('\n' + _full_description(str(notes)) if notes is not None else '')
        if len(narrative) > 12000:
            raise ValueError('publisher_description_limit')
        row = record(manifest[identity][0], start.isoformat(), end.isoformat() if end else None,
                     EHT_VENUE, EHT_STREET, 'Egg Harbor Township', url,
                     f'runsignup:13178:{identity}', '', tz=ZONE, retain_until_end=True)
        if row is not None:
            row.update(description=narrative, timezone=ZONE, attendance_mode='in_person',
                       location_provenance='reviewed_reserve_entrance_pending_geocode')
            if image := photo_url(EHT_TROT, parent.get('image')):
                row['image_url'] = image
            rows.append(row)
    if seen != set(manifest):
        raise ValueError('eht_trot_snapshot_incomplete')
    return rows


def collect(source, fetch, *, deadline_at=None, now=None):
    key = source.get('source_key')
    profile = SOURCES.get(key)
    if profile is None or (source.get('feed_url'), source.get('kind'), source.get('platform_adapter'),
                           source.get('timezone')) != (*profile, ZONE):
        raise ValueError('unregistered_atlantic_cape_source')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('atlantic_cape_occurrence_time_unresolved')
    if key == EHT_TROT:
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        main = fetch(EHT_ROOT, 'text/html')
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        return _turkey_trot(main, fetch(EHT_EVENTS, 'text/html'), current)
    start = current.astimezone(ZoneInfo(ZONE)).date()
    events = []
    expected = None
    for page in range(1, MAX_PAGES + 1):
        if deadline_at is not None and monotonic() >= deadline_at:
            raise ValueError('collection_deadline')
        url = API + '?' + urlencode({'start': start.isoformat(), 'end': (start + timedelta(days=60)).isoformat(),
                                     'pp': 100, 'page': page})
        data = json.loads(fetch(url, 'application/json'))
        if not isinstance(data, dict) or not isinstance(data.get('events'), list) or not isinstance(data.get('page'), dict):
            raise ValueError('atlantic_cape_payload_changed')
        meta = data['page']
        if (meta.get('current') != page or meta.get('size') != 100
                or type(meta.get('total')) is not int or not 0 <= meta['total'] <= MAX_PAGES
                or type(meta.get('total_items')) is not int or not 0 <= meta['total_items'] <= MAX_RECORDS):
            raise ValueError('atlantic_cape_pagination_limit')
        snapshot = (meta['total'], meta['total_items'])
        if expected is not None and snapshot != expected:
            raise ValueError('atlantic_cape_pagination_changed')
        expected = snapshot
        events.extend(data['events'])
        if len(events) > MAX_RECORDS:
            raise ValueError('source_record_limit')
        if page >= meta['total']:
            if meta.get('next_page') is not None or len(events) != meta['total_items']:
                raise ValueError('atlantic_cape_snapshot_incomplete')
            return parse_events(events, current)
        if meta.get('next_page') != page + 1:
            raise ValueError('atlantic_cape_snapshot_incomplete')
    raise ValueError('atlantic_cape_pagination_limit')
