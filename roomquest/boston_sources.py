"""Exact reviewed Boston source profiles and shared completeness boundary.

The source modules reuse existing feed parsers. This module only selects the
reviewed adapters and protects full narratives/addresses at the worker boundary.
No publisher transport, classifier, scheduler or global default is replaced.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ZONE = 'America/New_York'
MAX_DESCRIPTION = 12000
MAX_RECORDS = 500


def adapters():
    from roomquest import (
        boston_arts, boston_nightlife, boston_community,
        boston_arts_remaining, boston_nightlife_remaining, boston_community_remaining,
    )
    return (boston_arts, boston_nightlife, boston_community,
            boston_arts_remaining, boston_nightlife_remaining, boston_community_remaining)


def adapter_for(key):
    return next((module for module in adapters() if key in module.SOURCES), None)


def checkpoint_keys():
    return set().union(*(getattr(module, 'CHECKPOINT_KEYS', set()) for module in adapters()))


def validate_source(source):
    key = source.get('source_key')
    module = adapter_for(key)
    if module is None or (source.get('feed_url'), source.get('kind'),
            source.get('platform_adapter'), source.get('timezone')) != (*module.SOURCES[key], ZONE):
        raise ValueError('unregistered_boston_source')
    return module


def reviewed_intersection(source, row):
    """Accept only the exact reviewed street intersection and its actual point."""
    if not source or not isinstance(row, dict):
        return False
    module = adapter_for(source.get('source_key'))
    reviewed = getattr(module, 'REVIEWED_INTERSECTIONS', ())
    for venue in reviewed:
        if (venue['source_key'], venue['venue_name'], venue['venue_address']) != (
                source.get('source_key'), row.get('venue_name'), row.get('venue_address')):
            continue
        try:
            return all(math.isfinite(float(row[field])) and
                       abs(float(row[field]) - float(venue[field])) < 1e-7
                       for field in ('lat', 'lng'))
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
    return False


def validate_records(records, source=None):
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError('boston_record_limit')
    for row in records:
        if (not isinstance(row, dict)
                or not isinstance(row.get('description'), str)
                or not row['description'].strip()
                or len(row['description']) > MAX_DESCRIPTION
                or not isinstance(row.get('venue_name'), str)
                or not row['venue_name'].strip()
                or not isinstance(row.get('venue_address'), str)
                or (not re.match(r'^\d{1,6}(?:-\d{1,6})?\s+\S', row['venue_address'])
                    and not reviewed_intersection(source, row))
                or not re.search(r'\bMA\s+\d{5}(?:-\d{4})?\s*$', row['venue_address'])):
            raise ValueError('boston_incomplete_event')
    return records


def validate_checkpoint(source, checkpoint, *, now=None):
    """Match the durable database wire contract before attempting an RPC write."""
    module = validate_source(source)
    key = source['source_key']
    current = now or datetime.now(timezone.utc)
    manifest_limit = getattr(module, 'CHECKPOINT_MANIFEST_LIMITS', {}).get(key, 200)
    event_limit = getattr(module, 'CHECKPOINT_EVENT_LIMITS', {}).get(key, 201)
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
            and -60 <= (current - started).total_seconds() <= 4*60*60
            and checkpoint['window_start'] == started.astimezone(ZoneInfo(ZONE)).date().isoformat())
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('boston_checkpoint_invalid')
    return checkpoint


def diagnostic_codes():
    codes = {'unregistered_boston_source', 'boston_incomplete_event',
             'boston_record_limit', 'invalid_boston_payload', 'boston_checkpoint_invalid'}
    for module in adapters():
        codes.update(getattr(module, 'ERROR_CODES', set()))
    return codes
