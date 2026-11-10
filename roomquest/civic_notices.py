"""Factual date-only civic notices without invented attendance times or venues.

UTC bounds are transport/query bounds only. The public contract carries DATE
values and explicit precision so an all-day service never becomes a midnight
appointment. Source freshness is independent of the fact's actual end date.
"""
from datetime import date, datetime, time, timedelta, timezone
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KINDS = {'meeting', 'service', 'deadline', 'window'}
TOPICS = {'government', 'waste', 'voting', 'transport', 'public_services'}
APPLICABILITY = {'jurisdiction', 'service_area', 'address'}


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\x00-\x20]', value):
        raise ValueError('invalid_civic_source_url')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or '.' not in parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('invalid_civic_source_url')
    return value


def instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('civic_timezone_missing')
    return value.astimezone(timezone.utc)


def date_value(value):
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError('invalid_civic_date')
    return value


def metadata(*, kind, topic, jurisdiction_id, jurisdiction_name, source_url,
             verified_at, valid_until, precision='date', tz='America/New_York',
             applicability='jurisdiction', service_area_id=None,
             service_area_name=None, lookup_url=None):
    if kind not in KINDS or topic not in TOPICS or applicability not in APPLICABILITY:
        raise ValueError('invalid_civic_metadata')
    if precision not in {'timed', 'date', 'window'}:
        raise ValueError('invalid_civic_precision')
    if applicability == 'service_area' and not (service_area_id and service_area_name):
        raise ValueError('missing_civic_service_area')
    if not all(isinstance(v, str) and v.strip() and len(v) <= 160
               and not re.search(r'[\x00-\x1f]', v)
               for v in (jurisdiction_id, jurisdiction_name)):
        raise ValueError('invalid_civic_jurisdiction')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError('civic_timezone_unresolved') from exc
    verified_at, valid_until = instant(verified_at), instant(valid_until)
    result = {'version': 1, 'kind': kind, 'topic': topic,
              'jurisdiction_id': jurisdiction_id, 'jurisdiction_name': jurisdiction_name,
              'applicability': applicability, 'source_url': public_url(source_url),
              'verified_at': verified_at.isoformat(), 'valid_until': valid_until.isoformat(),
              'time_precision': precision, 'timezone': tz}
    for key, value in (('service_area_id', service_area_id), ('service_area_name', service_area_name)):
        if value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 160:
                raise ValueError('invalid_civic_service_area')
            result[key] = value
    if lookup_url is not None:
        result['lookup_url'] = public_url(lookup_url)
    return result


def date_notice(*, identity, title, starts_on, ends_on=None, description='', now=None,
                kind='service', topic='public_services', jurisdiction_id,
                jurisdiction_name, source_url, tz='America/New_York',
                applicability='jurisdiction', service_area_id=None,
                service_area_name=None, lookup_url=None, status=None, horizon_days=60,
                retain_revision=False):
    current = instant(now or datetime.now(timezone.utc))
    day = date_value(starts_on)
    last = date_value(ends_on) if ends_on is not None else day + timedelta(days=1)
    if not 0 < (last - day).days <= 60 or not 1 <= horizon_days <= 120:
        raise ValueError('invalid_civic_date_range')
    if (not isinstance(identity, str) or not identity or len(identity) > 400
            or not isinstance(title, str) or not title.strip()):
        raise ValueError('invalid_civic_identity')
    if status not in (None, 'scheduled', 'cancelled', 'postponed'):
        raise ValueError('invalid_civic_status')
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError('civic_timezone_unresolved') from exc
    today = current.astimezone(zone).date()
    if (last <= today and not retain_revision) or day >= today + timedelta(days=horizon_days):
        return None
    if retain_revision and day < today - timedelta(days=31):
        raise ValueError('civic_revision_outside_window')
    begins = datetime.combine(day, time(), zone).astimezone(timezone.utc)
    ends = datetime.combine(last, time(), zone).astimezone(timezone.utc)
    civic = metadata(kind=kind, topic=topic, jurisdiction_id=jurisdiction_id,
                     jurisdiction_name=jurisdiction_name, source_url=source_url,
                     verified_at=current, valid_until=ends,
                     precision='date' if (last - day).days == 1 else 'window', tz=tz,
                     applicability=applicability, service_area_id=service_area_id,
                     service_area_name=service_area_name, lookup_url=lookup_url)
    row = {'id': identity, 'title': title.strip()[:180],
           'description': str(description or '')[:2000],
           'starts_on': day.isoformat(), 'ends_on': last.isoformat(),
           'starts_at': begins.isoformat(), 'ends_at': ends.isoformat(),
           'venue_name': '', 'venue_address': '', 'venue_city': '',
           'lat': None, 'lng': None, 'event_url': source_url,
           'category': 'Civic & Public Services',
           'publisher_categories': ['Civic & Public Services'],
           'reason': 'missing_verified_venue_geo', 'timezone': tz,
           'civic_notice': True, 'civic': civic}
    if status:
        row['publisher_status'] = status
    return row
