"""Resolve a first-party Craft/CMS event page against Spektrix performances.

Public Spektrix events frequently omit webUrl, while an operator's CMS has
real event pages. Never infer the page from title alone: it must share at
least one timezone-aware instance clock and the event title, and belong to
the verified publisher's HTTPS host. The caller must gather source-bound
CMS evidence; this resolver never fetches or registers sources.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

MAX_PAGES = 500
MAX_INSTANCES = 4000
MAX_EVENT_TITLE = 250


def _fail(code):
    raise ValueError('spektrix_page_' + code)


def _title(value):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', value).strip().casefold()[:MAX_EVENT_TITLE]


def _instant(value, *, allow_spektrix_utc=False):
    if not isinstance(value, str) or len(value) > 50:
        return None
    if (allow_spektrix_utc and re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?', value)):
        value += 'Z'  # Spektrix's startUtc field can omit its UTC suffix.
    if not re.search(r'(?:Z|[+-]\d{2}:\d{2})$', value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except ValueError:
        return None


def resolve(publisher_url, events, instances, pages):
    """Return exact publisher page URLs keyed by Spektrix event ID.

    Each page is structured data from the publisher's own public CMS listing:
    {url, title, instances:[ISO timestamp,...]}. Page times must include a
    real offset. A show matching two URLs, or two shows matching one URL,
    remains held rather than selected heuristically.
    """
    try:
        origin = urlsplit(publisher_url)
    except (TypeError, ValueError):
        _fail('source_invalid')
    if (origin.scheme != 'https' or not origin.hostname or origin.username
            or origin.password or not isinstance(events, list)
            or not isinstance(instances, list) or len(instances) > MAX_INSTANCES
            or not isinstance(pages, list) or len(pages) > MAX_PAGES):
        _fail('source_invalid')

    names = {}
    for event in events:
        if (not isinstance(event, dict) or not isinstance(event.get('id'), str)
                or not _title(event.get('name'))):
            _fail('event_invalid')
        identifier = event['id']
        name = _title(event['name'])
        if identifier in names and names[identifier] != name:
            _fail('event_conflict')
        names[identifier] = name

    schedules = {}
    for item in instances:
        if not isinstance(item, dict):
            _fail('instance_invalid')
        if item.get('cancelled') is True or item.get('isOnSale') is False:
            continue
        if item.get('cancelled') is not False or item.get('isOnSale') is not True:
            _fail('instance_invalid')
        parent = item.get('event')
        event_id = parent.get('id') if isinstance(parent, dict) else None
        clock = _instant(item.get('startUtc'), allow_spektrix_utc=True)
        if not isinstance(event_id, str) or event_id not in names or clock is None:
            _fail('instance_invalid')
        schedules.setdefault(event_id, set()).add(clock)

    candidates = {}
    pages_by_url = {}
    for page in pages:
        if not isinstance(page, dict):
            _fail('identity_invalid')
        url = page.get('url')
        try:
            parts = urlsplit(url) if isinstance(url, str) else None
        except ValueError:
            _fail('source_conflict')
        if (not parts or parts.scheme != 'https' or parts.hostname != origin.hostname
                or not parts.path or parts.username or parts.password or parts.fragment
                or len(url) > 1200):
            _fail('source_conflict')
        label = _title(page.get('title'))
        times = page.get('instances')
        if not label or not isinstance(times, list) or not times or len(times) > 500:
            continue
        observed = {_instant(value) for value in times}
        if None in observed:
            _fail('identity_invalid')
        if url in pages_by_url and pages_by_url[url] != (label, observed):
            _fail('identity_conflict')
        pages_by_url[url] = (label, observed)
        for key, name in names.items():
            if name == label and key in schedules and observed.intersection(schedules[key]):
                candidates.setdefault(key, set()).add(url)

    result = {}
    for key, links in candidates.items():
        if len(links) != 1:
            _fail('link_ambiguous')
        result[key] = next(iter(links))
    if len(result.values()) != len(set(result.values())):
        _fail('event_identity_conflict')
    return result
