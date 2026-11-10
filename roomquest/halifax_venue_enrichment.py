"""Reviewed named-venue associations for the existing Discover Halifax source.

The owner authorized educated venue associations on 2026-11-10. These are
bounded matches to current publisher venue fields and official street-address
evidence, not a town/ZIP default. They never supply coordinates, fetch another
publisher, or replace an explicit different street. The backend capability
gate remains in discover_halifax; this module has no transport or database I/O.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from roomquest.mapsee_adapter import timestamp

METHOD = 'owner_authorized_inferred_venue_association'
ZONE = 'America/New_York'
HOLIDAY_URL = 'https://gohalifaxva.com/directory/holiday-living-show/'
LIGHTS_PREFIX = 'https://gohalifaxva.com/directory/lights-for-hope-drive-thru-holiday-light-show'
EVENT_URL = re.compile(r'https://gohalifaxva[.]com/directory/[a-z0-9]+(?:-[a-z0-9]+)*/')
_OFFSITE = re.compile(r'\b(?:off[ -]?site|relocat(?:ed|ion)|moved to|new location|venue changed)\b|\b(?:Location|Venue)\s*:', re.I)
_CLOCK = r'(?:[1-9]|1[0-2]):[0-5]\d\s*[ap]\.?m\.?'
_HOLIDAY_SESSION = re.compile(
    r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+'
    r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+from\s+'
    r'(' + _CLOCK + r')\s+to\s+(' + _CLOCK + r')', re.I)
_LIGHTS_SESSIONS = re.compile(
    r'\b([A-Za-z]+)\s+(\d{1,2}(?:\s*[-,]\s*\d{1,2}){1,6})\s*&\s*'
    r'([A-Za-z]+)\s+(\d{1,2}(?:\s*[-,]\s*\d{1,2}){1,6})\s+'
    r'(' + _CLOCK + r')\s*[–—-]\s*(' + _CLOCK + r')', re.I)


class SessionHold(ValueError):
    """An identified event family has unaccounted or conflicting sessions."""


def enabled(source):
    value = source.get('venue_association_contract_version')
    return type(value) is int and value == 1


def _normal(value):
    return ' '.join(str(value or '').replace('.', '').casefold().split())


def _parts(value):
    return [_normal(part) for part in str(value or '').split(',') if part.strip()]


def _address_is(value, names, extra):
    parts = _parts(value)
    return (bool(parts) and len(parts) <= 12 and parts[0] in {_normal(name) for name in names}
            and all(part in {_normal(item) for item in extra} for part in parts[1:]))


def _website(value, host, path=None):
    raw = str(value or '').strip()
    if '://' not in raw:
        raw = 'https://' + raw
    try:
        parsed = urlsplit(raw)
        return (parsed.scheme in ('https', 'http') and parsed.hostname in (host, 'www.' + host)
                and not parsed.username and not parsed.password and parsed.port in (None, 80, 443)
                and not parsed.fragment and (path is None or parsed.path.rstrip('/') == path))
    except ValueError:
        return False


def _venue(key, name, street, city, evidence):
    return {'key': key, 'venue_name': name, 'venue_address': street,
            'venue_city': city, 'evidence_url': evidence}


def resolve(fields, url, title, day, description):
    """Resolve only reviewed incomplete address shapes and named venues.

    The caller first tries its ordinary explicit-street parser. Consequently
    this never replaces a complete publisher address, even a different one.
    Every residual address token must be part of the reviewed venue shape.
    """
    if (not isinstance(fields, dict) or not EVENT_URL.fullmatch(str(url))
            or not isinstance(day, date) or not isinstance(description, str)
            or len(description) > 30_000 or _OFFSITE.search(description)
            or len(str(fields.get('Address', ''))) > 800):
        return None
    raw, website = fields.get('Address', ''), fields.get('Website', '')
    common = ('VA', 'Virginia', 'United States', 'USA')
    sobo = common + ('South Boston', 'Halifax County', '24592')
    if (_address_is(raw, ('Downtown South Boston Farmers Market',), sobo + (
            'Arch Street', '300', 'Broad Street', '300 Broad Street'))
            and (_normal(fields.get('Email')) == 'manager@sobofmcom'
                 or _website(website, 'sobofm.com')
                 or _normal(title) == 'downtown south boston farmers market')):
        return _venue('farmers_market', 'Downtown South Boston Farmers Market',
                      '300 Broad Street, South Boston, VA 24592', 'South Boston',
                      'https://sobofm.com/about/')
    if _address_is(raw, ('Halifax County Fairgrounds',), sobo + (
            '1188', 'James D Hagood Highway', 'James D Hagood Hwy',
            '1188 James D Hagood Highway', '1188 James D Hagood Hwy')):
        return _venue('fairgrounds', 'Halifax County Fairgrounds',
                      '1188 James D. Hagood Highway, South Boston, VA 24592', 'South Boston',
                      'https://halifaxcountyfair.com/directions/')
    park_names = ('Staunton River Battlefield State Park', 'Staunton River Bridge')
    park_tokens = common + ('1035', 'Fort Hill Trail', '1035 Fort Hill Trail', 'Battlefield Trail',
                            'Randolph', 'Charlotte County', 'Halifax County', '23962')
    if (_address_is(raw, park_names, park_tokens)
            and _website(website, 'dcr.virginia.gov', '/state-parks/staunton-river-battlefield')):
        known = _normal(title)
        if known in ('walk the battlefield', 'fall scavenger hunt', 'hardtack & coffee'):
            # A title reused at another park access point does not inherit the
            # Clover address, even when nobody writes "relocated" explicitly.
            if re.search(r'\b(?:Roanoke Station|Mulberry Hill|north(?:ern)? (?:entrance|trailhead)|picnic shelter)\b',
                         description, re.I):
                return None
            name = 'Staunton River Battlefield State Park — Clover Visitor Center'
            evidence = 'https://www.dcr.virginia.gov/state-parks/staunton-river-battlefield'
        elif known == 'gobble gobble' and (day == date(2026, 11, 22)
                                         or 'picnic shelter' in description.casefold()):
            name = 'Staunton River Battlefield State Park — Picnic Shelter'
            evidence = 'https://www.dcr.virginia.gov/state-parks/event?id=2026-10-21-15-15-45-611984-n4h'
        else:
            return None
        return _venue('battlefield', name, '1035 Fort Hill Trail, Randolph, VA 23962',
                      'Randolph', evidence)
    if (_address_is(raw, ('The Light Spiritual Wellness', 'The Light Spiritual Wellness Center'),
                    sobo + ('435', 'Main Street', 'Main St', '435 Main Street', '435 Main St'))
            and _website(website, 'thelightspiritualwellness.com')):
        return _venue('the_light', 'The Light Spiritual Wellness Center',
                      '435 Main Street, South Boston, VA 24592', 'South Boston',
                      'https://www.thelightspiritualwellness.com/ourevents')
    if (_address_is(raw, ('1011', '1011 Middle School Circle', 'Halifax County Middle School'),
                    sobo + ('1011', 'Middle School Circle', '1011 Middle School Circle'))
            and re.search(r'Halifax County Middle School,?\s+1011 Middle School Circle\s+South Boston,?\s+VA\b', description, re.I)):
        return _venue('middle_school', 'Halifax County Middle School',
                      '1011 Middle School Circle, South Boston, VA 24592', 'South Boston',
                      'https://www.halifax.k12.va.us/o/middleschool')
    if _address_is(raw, ('South Boston Speedway',), sobo + (
            '1188', 'James D Hagood Highway', 'James D Hagood Hwy',
            '1188 James D Hagood Highway', '1188 James D Hagood Hwy', 'Five Forks')):
        return _venue('speedway', 'South Boston Speedway',
                      '1188 James D. Hagood Highway, South Boston, VA 24592', 'South Boston',
                      'https://www.southbostonspeedway.com/contact')
    if (_address_is(raw, ('Virginia International Raceway',), common + (
            '1245', 'Pine Tree Road', 'Pine Tree Rd', '1245 Pine Tree Road', '1245 Pine Tree Rd',
            'Alton', 'Halifax County', '24520')) and _website(website, 'virnow.com')):
        return _venue('vir', 'VIRginia International Raceway',
                      '1245 Pine Tree Road, Alton, VA 24520', 'Alton',
                      'https://gohalifaxva.com/directory/virginia-international-raceway/')
    if (_address_is(raw, ('Lake Front Winery',), common + (
            '3655', 'Highway 58', '3655 Highway 58', 'Buffalo Junction', 'Mecklenburg County', '24529'))
            and re.search(r'3655\s+Highway\s+58,?\s+Buffalo Junction,?\s+VA\b', description, re.I)):
        return _venue('lake_front', 'Lake Front Winery',
                      '3655 Highway 58, Buffalo Junction, VA 24529', 'Buffalo Junction', url)
    return None


def associate(row, venue):
    """Attach the backend's bounded receipt without an unverified map point."""
    urls = list(dict.fromkeys((row['event_url'], venue['evidence_url'])))
    row['venue_association'] = {
        'method': METHOD, 'evidence_urls': urls, 'matched_activity': row['title'],
        'venue_name': row['venue_name'], 'venue_address': row['venue_address'],
    }
    row['lat'] = row['lng'] = None
    row['location_provenance'] = METHOD
    sentence = f"Venue inferred from the publisher's named {venue['venue_name']} and its published street address."
    row['description'] = (sentence + '\n\n' + (row.get('description') or ''))[:3000]
    return row


def _month(value):
    for pattern in ('%B', '%b'):
        try:
            return datetime.strptime(value, pattern).month
        except ValueError:
            pass
    raise SessionHold('publisher_session_schedule_unresolved')


def _instant(day, value):
    try:
        clock = datetime.strptime(re.sub(r'\s+', '', value.replace('.', '')).upper(), '%I:%M%p').time()
        return timestamp(datetime.combine(day, clock).isoformat(), ZONE)
    except (ValueError, OverflowError) as error:
        raise SessionHold('publisher_session_schedule_unresolved') from error


def holiday_plan(day, description):
    matches = list(_HOLIDAY_SESSION.finditer(description))
    if len(matches) != 2:
        raise SessionHold('publisher_session_schedule_unresolved')
    result = []
    for match in matches:
        try:
            current = date(day.year, _month(match[2]), int(match[3]))
        except ValueError as error:
            raise SessionHold('publisher_session_schedule_unresolved') from error
        if current.strftime('%A').casefold() != match[1].casefold():
            raise SessionHold('publisher_session_schedule_unresolved')
        start, end = _instant(current, match[4]), _instant(current, match[5])
        if not start < end <= start + timedelta(hours=12):
            raise SessionHold('publisher_session_schedule_unresolved')
        result.append((start, end))
    if [start.date() for start, _ in result] != [day, day + timedelta(days=1)]:
        raise SessionHold('publisher_session_schedule_unresolved')
    return result


def reviewed_end(fields, url, title, day, description):
    """Return a concrete corrected end only for the two reviewed session forms."""
    if url == HOLIDAY_URL and _normal(title) == 'holiday living show':
        sessions = holiday_plan(day, description)
        if (fields.get('End Date') != (day + timedelta(days=1)).strftime('%B %d, %Y').replace(' 0', ' ')
                or _instant(day, fields.get('Start Time', '')) != sessions[0][0]):
            raise SessionHold('publisher_session_schedule_unresolved')
        return sessions[0][1]
    if (url.startswith(LIGHTS_PREFIX) and EVENT_URL.fullmatch(url)
            and _normal(title) == 'lights for hope! drive-thru holiday light show'):
        matches = list(_LIGHTS_SESSIONS.finditer(description))
        if len(matches) != 1:
            raise SessionHold('publisher_session_schedule_unresolved')
        match = matches[0]
        try:
            days = [date(day.year, _month(month), int(value))
                    for month, values in ((match[1], match[2]), (match[3], match[4]))
                    for value in re.split(r'\s*[-,]\s*', values)]
        except ValueError as error:
            raise SessionHold('publisher_session_schedule_unresolved') from error
        start, end = _instant(day, match[5]), _instant(day, match[6])
        if (len(days) != len(set(days)) or not 2 <= len(days) <= 14 or day not in days
                or not start < end <= start + timedelta(hours=12)
                or _instant(day, fields.get('Start Time', '')) != start
                or _instant(day, fields.get('End Time', '')) != end
                or fields.get('End Date') not in (None, '', day.strftime('%B %d, %Y').replace(' 0', ' '),
                                                max(days).strftime('%B %d, %Y').replace(' 0', ' '))):
            raise SessionHold('publisher_session_schedule_unresolved')
        return end
    return None


def checkpoint_sessions(url, day):
    if url != HOLIDAY_URL:
        return None
    return {url + '#session-' + current.isoformat(): current
            for current in (day, day + timedelta(days=1))}
