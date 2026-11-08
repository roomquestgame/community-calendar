"""One reviewed intake batch; actual parsers remain in their shared families."""
from __future__ import annotations

from urllib.parse import urlsplit

from roomquest import holly_hill_businesses as businesses
from roomquest import holly_hill_civic as civic
from roomquest import holly_hill_institutions as institutions

ZONE = 'America/New_York'
ORANGEBURG_LIBRARY = 'orangeburg_county_library_sc'
SOURCES = dict(civic.SOURCES)
SOURCES.update({key: {'url': url, 'kind': 'html', 'adapter': 'html', 'hosts': businesses.HOSTS[key]}
                for key, url in businesses.SOURCES.items()})
SOURCES.update({key: {'url': url, 'kind': 'ical' if key in institutions.ICS else 'html',
                     'adapter': 'ical' if key in institutions.ICS else 'html',
                     'hosts': (urlsplit(url).hostname,)}
                for key, url in institutions.SOURCES.items()})
SOURCES[ORANGEBURG_LIBRARY] = {
    'url': 'https://www.orangeburgcounty.org/common/modules/iCalendar/iCalendar.aspx?catID=23&feed=calendar',
    'kind': 'ical', 'adapter': 'ical', 'hosts': ('www.orangeburgcounty.org',)}


def source_payload(key):
    spec = SOURCES[key]
    return {'source_key': key, 'feed_url': spec['url'], 'kind': spec['kind'],
            'platform_adapter': spec['adapter'], 'timezone': ZONE}


def validate(source):
    key = source.get('source_key')
    if key not in SOURCES or any(source.get(field) != value for field, value in source_payload(key).items()):
        raise ValueError('unregistered_holly_hill_source')
    return SOURCES[key]


def publisher_media(source):
    try:
        spec = validate(source)
        return source['source_key'] == civic.SC250 or (
            spec['kind'] != 'ical' and source['source_key'] not in institutions.SOURCES)
    except ValueError:
        return False


def collect(source, fetch, *, deadline_at=None, fetch_elloree=None):
    validate(source)
    key = source['source_key']
    if key in institutions.SOURCES:
        return institutions.collect(source, fetch, deadline_at=deadline_at)
    if key in businesses.SOURCES:
        return businesses.collect(source, fetch, deadline_at=deadline_at)
    if key == ORANGEBURG_LIBRARY:
        from roomquest.ics_adapter import parse
        return parse(fetch(source['feed_url'], 'text/calendar'),
                     {'url': source['feed_url'], 'source_key': key},
                     legacy=True, include_description=True)
    if key == civic.SANTEE:
        return civic.collect_santee(source, fetch, deadline_at=deadline_at)
    if key == civic.BEIDLER:
        return civic.collect_beidler(source, fetch, deadline_at=deadline_at)
    if key == civic.SC250:
        return civic.collect_sc250_ics(source, fetch, deadline_at=deadline_at)
    if key == civic.EUTAWVILLE:
        return civic.collect_tec(source, fetch, deadline_at=deadline_at)
    if key == civic.ELLOREE:
        return civic.collect_elloree(source, fetch, fetch_json=fetch_elloree, deadline_at=deadline_at)
    raise ValueError('unregistered_holly_hill_source')
