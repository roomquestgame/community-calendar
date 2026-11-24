"""Strict bridge from one approved Spektrix provider profile to stageable rows.

This does not register any sources, discover arbitrary client names, or bypass
the database's provider-profile allowlist. The caller supplies a preverified
profile and an existing robots-aware publisher GET transport. Registration
may use a short bounded probe; a production 60-day collection requires the
durable lease/CAS checkpoint worker before this family can be enabled.
"""
from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roomquest import spektrix_v3
from roomquest.registration_formats import source_key

SOURCE = re.compile(r'^https://system\.spektrix\.com/([a-z][a-z0-9_-]{1,59})/api/v3/events$')
VALID_COUNTRIES = {'GB','IE','US','CA','AU','NZ'}
MAX_PROBE_DAYS = 14
MAX_PROBE_EVENTS = 150


def _fail(reason):
    raise ValueError('spektrix_provider_' + reason)


def family(url):
    """Exact, canonical *read-only* event collection URL only."""
    return bool(isinstance(url, str) and SOURCE.fullmatch(url))


def validate(source, profile):
    if (not isinstance(source, dict) or not isinstance(profile, dict)
            or source.get('kind') != 'json'
            or source.get('platform_adapter') != 'spektrix'):
        _fail('source_invalid')
    url = source.get('feed_url')
    match = SOURCE.fullmatch(url) if isinstance(url, str) else None
    if (not match or source.get('source_key') != source_key(url)
            or profile.get('client') != match[1]
            or profile.get('country') not in VALID_COUNTRIES
            or not isinstance(profile.get('publisher_url'), str)):
        _fail('source_invalid')
    publisher = urlsplit(profile['publisher_url'])
    if (publisher.scheme != 'https' or not publisher.hostname
            or publisher.hostname in ('system.spektrix.com', 'api.system.spektrix.com')
            or publisher.username or publisher.password or publisher.fragment
            or not publisher.path):
        _fail('publisher_invalid')
    for field in ('timezone','home_city'):
        if not isinstance(profile.get(field), str) or not profile[field].strip():
            _fail('venue_invalid')
    try:
        ZoneInfo(profile['timezone'])
    except (ValueError,TypeError,ZoneInfoNotFoundError):
        _fail('timezone_invalid')
    verified = profile.get('event_urls')
    if not isinstance(verified, dict) or len(verified) > 1000:
        _fail('event_links_missing')
    for key, value in verified.items():
        if (not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9-]{10,80}',key)
                or not isinstance(value,str)):
            _fail('event_links_invalid')
        candidate = urlsplit(value)
        if (candidate.scheme != 'https' or candidate.hostname != publisher.hostname
                or not candidate.path or candidate.username or candidate.password
                or candidate.fragment):
            _fail('event_links_invalid')
    locations = profile.get('verified_venues',{})
    if not isinstance(locations,dict) or len(locations)>150:
        _fail('venues_invalid')
    for key,value in locations.items():
        if (not isinstance(key,str) or not isinstance(value,dict)
                or not isinstance(value.get('address'),str) or not value['address'].strip()
                or not isinstance(value.get('city'),str) or not value['city'].strip()
                or not isinstance(value.get('evidence_url'),str)):
            _fail('venues_invalid')
        evidence=urlsplit(value['evidence_url'])
        if (evidence.scheme!='https' or evidence.hostname!=publisher.hostname
                or evidence.username or evidence.password):
            _fail('venues_invalid')
    return profile


def stageable(source, data):
    """Convert a completely validated v3 snapshot into legacy stage records.

    The staging/publishing RPC retains its own rights, lease, event field and
    duplicate-identity checks. We never write directly to any event table.
    """
    if not isinstance(data,dict) or data.get('complete') is not True:
        _fail('snapshot_incomplete')
    rows=data.get('events')
    if not isinstance(rows,list) or len(rows)>3000:
        _fail('snapshot_invalid')
    from roomquest.mapsee_adapter import record
    from roomquest.preview_worker import event_image
    out=[]
    for row in rows:
        if (not isinstance(row,dict) or not row.get('id')
                or not row.get('event_url') or not row.get('venue_address')
                or not row.get('venue_city') or not row.get('timezone')
                or not row.get('starts_at')):
            _fail('event_invalid')
        converted=record(
            row['title'],row['starts_at'],row.get('ends_at'),
            row['venue_name'],row['venue_address'],row['venue_city'],
            row['event_url'],row['id'],tz=row['timezone'])
        if converted is None:
            # Explicitly out of active date window: not a staged occurrence.
            continue
        converted['timezone']=row['timezone']
        from roomquest.event_description import description
        converted['description']=description(row.get('description',''))
        if row.get('image_url'):
            img=event_image(row['image_url'],row['event_url'])
            if img:
                converted['image_url']=img
        out.append(converted)
    return sorted(out,key=lambda row:(row['starts_at'],row['id']))


def probe(source, profile, fetch, *, deadline_at=None, today=None):
    """Short first-registration check; never certifies a future 60-day refresh."""
    profile=validate(source,profile)
    if today is None:
        today=datetime.now(ZoneInfo(profile['timezone'])).date()
    end=today+timedelta(days=MAX_PROBE_DAYS-1)
    # No raw network transport. Existing publisher fetch owns robots, pacing,
    # body limits, deadline and TLS/DNS policy.
    full=spektrix_v3.collect(profile,today,end,fetch,deadline_at=deadline_at)
    return stageable(source,full)
