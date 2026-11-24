"""Bind a publisher CMS event page to Spektrix by exact performance evidence.

Craft CMS, WordPress and Wix may each expose official show pages while
Spektrix's public Event.webUrl is blank. A title alone is insufficient to
claim an event URL: require a real publisher page and at least one matching
individual start instant; ambiguous or conflicting matches stay held.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit


def _fail(reason):
    raise ValueError('spektrix_page_' + reason)


def _title(raw):
    if not isinstance(raw, str):
        return ''
    return re.sub(r'\s+', ' ', raw).strip().casefold()


def _instant(raw):
    if not isinstance(raw, str) or len(raw) > 50:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def resolve(publisher_url, events, instances, pages):
    """Return {Spektrix event_id: exact official event page URL}.

    Every supplied publisher page must have a trusted https URL and explicit
    timezone-aware occurrence times; no date-only recurrence guesses.
    A page is eligible only when one matching Spektrix performance exists.
    """
    origin = urlsplit(publisher_url)
    if origin.scheme != 'https' or not origin.hostname or not isinstance(pages, list):
        _fail('source_invalid')
    schedules = {}
    for item in instances:
        parent = item.get('event') if isinstance(item, dict) else None
        event_id = parent.get('id') if isinstance(parent, dict) else None
        instant = _instant(item.get('startUtc') + 'Z' if (
            isinstance(item.get('startUtc'), str) and
            not re.search(r'(?:Z|[+-]\d{2}:\d{2})$', item['startUtc'])
        ) else item.get('startUtc')) if isinstance(item, dict) else None
        if item.get('cancelled') is True or item.get('isOnSale') is False:
            continue
        if not isinstance(event_id, str) or instant is None:
            _fail('instance_invalid')
        schedules.setdefault(event_id, set()).add(instant)
    candidates = {}
    pages_by_url = {}
    for page in pages:
        if not isinstance(page, dict):
            _fail('identity_invalid')
        url = page.get('url')
        parts = urlsplit(url) if isinstance(url, str) else None
        if (not parts or parts.scheme != 'https' or parts.hostname != origin.hostname
                or not parts.path or parts.username or parts.password or parts.fragment):
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
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get('id'), str):
                _fail('event_invalid')
            key = event['id']
            if (_title(event.get('name')) == label
                    and key in schedules
                    and observed.intersection(schedules[key])):
                candidates.setdefault(key, set()).add(url)
    result = {}
    for key, links in candidates.items():
        if len(links) != 1:
            _fail('link_ambiguous')
        result[key] = next(iter(links))
    if len(result.values()) != len(set(result.values())):
        _fail('event_identity_conflict')
    return result
