"""Exact reviewed profiles for the Raleigh direct-calendar expansion."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

ZONE = 'America/New_York'
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500


def adapters():
    from roomquest import raleigh_direct_community, raleigh_direct_nightlife, raleigh_direct_arts
    from roomquest import raleigh_direct_performance, raleigh_direct_additional
    from roomquest import raleigh_followup_performance, raleigh_direct_jcra
    from roomquest import raleigh_next_culture, raleigh_next_community, raleigh_next_social
    return (raleigh_direct_community, raleigh_direct_nightlife, raleigh_direct_arts,
            raleigh_direct_performance, raleigh_direct_additional,
            raleigh_followup_performance, raleigh_direct_jcra,
            raleigh_next_culture, raleigh_next_community, raleigh_next_social)


def adapter_for(key):
    return next((module for module in adapters() if key in module.SOURCES), None)


def checkpoint_keys():
    return set().union(*(getattr(module, 'CHECKPOINT_KEYS', set()) for module in adapters()))


def validate_source(source):
    key = source.get('source_key')
    module = adapter_for(key)
    if module is None or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*module.SOURCES[key], ZONE):
        raise ValueError('unregistered_raleigh_direct_source')
    return module


def validate_records(records, source=None):
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError('raleigh_direct_record_limit')
    seen = set()
    module = validate_source(source) if source else None
    for row in records:
        if (not isinstance(row, dict)
                or not isinstance(row.get('description'), str) or not row['description'].strip()
                or len(row['description']) > MAX_DESCRIPTION
                or not isinstance(row.get('venue_name'), str) or not row['venue_name'].strip()
                or not isinstance(row.get('venue_address'), str)
                or not re.match(r'^\d{1,6}(?:-\d{1,6})?\s+\S', row['venue_address'])
                or not re.search(r'\bNC\s+\d{5}(?:-\d{4})?\s*$', row['venue_address'])
                or not isinstance(row.get('id'), str) or not row['id']
                or not isinstance(row.get('starts_at'), str)
                or (module is not None and hasattr(module, 'event_url')
                    and not module.event_url(source['source_key'], row.get('event_url')))):
            raise ValueError('raleigh_direct_incomplete_event')
        identity = row['id'], row['starts_at']
        if identity in seen:
            raise ValueError('raleigh_direct_duplicate_occurrence')
        seen.add(identity)
    return records


def validate_checkpoint(source, checkpoint, *, now=None):
    module = validate_source(source)
    key = source['source_key']
    current = now or datetime.now(timezone.utc)
    manifest_limit = getattr(module, 'CHECKPOINT_MANIFEST_LIMITS', {}).get(key, 200)
    event_limit = getattr(module, 'CHECKPOINT_EVENT_LIMITS', {}).get(key, 500)
    try:
        started_text = checkpoint['started_at']
        started = datetime.fromisoformat(started_text.replace('Z', '+00:00'))
        valid = (isinstance(checkpoint, dict)
            and type(checkpoint['version']) is int and checkpoint['version'] == 1
            and checkpoint['source_key'] == key
            and isinstance(checkpoint['manifest_hash'], str)
            and re.fullmatch(r'[a-f0-9]{64}', checkpoint['manifest_hash'])
            and type(checkpoint['manifest_count']) is int
            and 0 <= checkpoint['manifest_count'] <= manifest_limit
            and type(checkpoint['cursor']) is int
            and 0 <= checkpoint['cursor'] <= checkpoint['manifest_count']
            and isinstance(checkpoint['events'], list) and len(checkpoint['events']) <= event_limit
            and isinstance(checkpoint['diagnostics'], list) and len(checkpoint['diagnostics']) <= 400
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', started_text)
            and -60 <= (current-started).total_seconds() <= 4*60*60
            and checkpoint['window_start'] == started.astimezone(ZoneInfo(ZONE)).date().isoformat())
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('raleigh_direct_checkpoint_invalid')
    return checkpoint


def checkpoint_complete(source, checkpoint):
    """Require completed listing discovery as well as all detail outcomes.

    A newly started paginated capture can legitimately have an empty detail
    manifest. Its 0/0 cursor is not proof that the calendar was exhausted.
    """
    module = validate_source(source)
    if checkpoint.get('cursor') != checkpoint.get('manifest_count'):
        return False
    family = module.__name__.rsplit('.', 1)[-1]
    if family == 'raleigh_direct_arts':
        return (checkpoint.get('listing_complete') is True and checkpoint.get('pending_pages') == []
                and len(checkpoint.get('queue', [])) == checkpoint['manifest_count'])
    if family == 'raleigh_direct_nightlife':
        return (checkpoint.get('pending') == [] and checkpoint.get('pending_cursor') == 0
                and checkpoint.get('loaded_page') is None and checkpoint.get('seeds') == {}
                and len(checkpoint.get('pages', [])) == checkpoint['manifest_count'])
    if family == 'raleigh_direct_community':
        return len(checkpoint.get('queue') or checkpoint.get('seed_proof', [])) == checkpoint['manifest_count']
    if family == 'raleigh_direct_performance':
        return (checkpoint.get('phase') == 'details' and checkpoint.get('listing_complete') is True
                and len(checkpoint.get('queue', [])) == checkpoint['manifest_count'])
    predicate = getattr(module, 'checkpoint_complete', None)
    return bool(predicate and predicate(checkpoint))


def diagnostic_codes():
    codes = {'unregistered_raleigh_direct_source', 'raleigh_direct_incomplete_event',
        'raleigh_direct_record_limit', 'invalid_raleigh_direct_payload',
        'raleigh_direct_checkpoint_invalid', 'raleigh_direct_duplicate_occurrence'}
    for module in adapters():
        codes.update(getattr(module, 'ERROR_CODES', set()))
    return codes
