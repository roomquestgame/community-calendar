#!/usr/bin/env python3
"""Read-only live audit of the reviewed Holly Hill intake and existing feeds.

Every eligible source uses preview_worker.preview_source and its normal DNS,
robots, pacing and publisher guards. There is no database/authentication lookup,
registration, staging, demand creation or publication. The three documented
paused MapSee sources are retained without contacting their publishers.

Run on POSIX in the main thread: a hard per-source alarm supplements the normal
collector deadline. The optional batch manifest contributes inventory only; it
cannot add an arbitrary runnable URL or release a known hold.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import signal
import sys
from threading import current_thread, main_thread
from time import monotonic
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from roomquest import holly_hill_sources, mapsee_adapter, preview_worker

DEFAULT_CATALOG_AUDIT = ROOT / 'docs/evidence/holly_hill_catalog_audit_20261108.json'
DEFAULT_MANIFEST = ROOT / 'docs/evidence/holly_hill_batch_20261108.json'
PER_SOURCE_SECONDS = 45
OVERALL_SECONDS = 1200
MAX_RECORDS = 500
MAX_SAMPLES = 3
MAX_INVENTORY_BYTES = 2_000_000
ZONE = 'America/New_York'
SCHEMA_VERSION = 'holly_hill_read_only_audit_v1'
MAPSEE_IDS = frozenset((*range(2556, 2568), 3304, 3894, 4263, 4347, 4403, 4446, 4682))
KNOWN_HOLDS = {
    4347: 'source_network_error',
    4403: 'invalid_event_end',
    4682: 'robots_denied',
}
REGISTRY_FIELDS = ('id', 'publisher_name', 'approval', 'health', 'intake_state',
                   'preview_status', 'preview_future_count', 'catalog_origin')
TRANSPORT_CODES = {
    'dns_unavailable', 'source_network_error', 'source_fetch_deadline',
    'source_audit_timeout', 'collection_deadline', 'overall_audit_deadline',
    'source_unavailable_or_oversized', 'source_too_large', 'robots_unavailable',
    'publisher_rate_limited',
}
GUARD_CODES = {
    'robots_denied', 'non_public_dns', 'invalid_source_url', 'invalid_redirect_url',
    'redirect_blocked', 'redirect_host_not_approved', 'redirect_missing_location',
    'too_many_redirects', 'publisher_wait_requires_review', 'calendar_render_redirect_blocked',
}

# Read-only registry snapshot, 2026-11-08. Colonial Dorchester is 4915/725;
# 4912 is Cheraw and is deliberately outside this local batch.
EXISTING_LOCAL = (
    {'id': 4897, 'source_key': 'municipal_chambermaster_orangeburg_sc',
     'publisher_name': 'Orangeburg County Chamber of Commerce',
     'feed_url': 'https://business.orangeburgchamber.com/api/events',
     'kind': 'xml', 'platform_adapter': 'growthzone',
     'approval': 'approved', 'health': 'ok', 'intake_state': 'ready',
     'preview_status': 'complete', 'preview_future_count': 18},
    {'id': 4915, 'source_key': 'south_carolina_parks_725',
     'publisher_name': 'Colonial Dorchester State Historic Site',
     'feed_url': 'https://southcarolinaparks.com/api/events#park=725',
     'kind': 'json', 'platform_adapter': 'south_carolina_parks',
     'approval': 'approved', 'health': 'unchecked', 'intake_state': None},
    {'id': 4920, 'source_key': 'south_carolina_parks_1219',
     'publisher_name': 'Givhans Ferry State Park',
     'feed_url': 'https://southcarolinaparks.com/api/events#park=1219',
     'kind': 'json', 'platform_adapter': 'south_carolina_parks',
     'approval': 'approved', 'health': 'unchecked', 'intake_state': None,
     'preview_status': 'idle', 'preview_future_count': 0},
    {'id': 4949, 'source_key': 'south_carolina_parks_535',
     'publisher_name': 'Santee State Park',
     'feed_url': 'https://southcarolinaparks.com/api/events#park=535',
     'kind': 'json', 'platform_adapter': 'south_carolina_parks',
     'approval': 'approved', 'health': 'empty', 'intake_state': 'ready',
     'preview_status': 'complete', 'preview_future_count': 0},
)


def _read_json(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_INVENTORY_BYTES:
        raise ValueError('audit_inventory_too_large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('audit_inventory_invalid')
    return value, hashlib.sha256(raw).hexdigest()


def _inventory_rows(document, field):
    rows = document.get(field, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('audit_inventory_invalid')
    fields = ('source_key', 'publisher_name', 'name', 'feed_url', 'url', 'town',
              'reason', 'hold_status', 'status', 'evidence_url')
    result = []
    for row in rows:
        clean = {key: value[:3000] for key in fields
                 if isinstance((value := row.get(key)), str)}
        links = row.get('evidence_urls', [])
        if isinstance(links, list):
            clean['evidence_urls'] = [url[:2048] for url in links[:10] if isinstance(url, str)]
        result.append(clean)
    return result


def build_inventory(catalog_audit=DEFAULT_CATALOG_AUDIT, manifest=DEFAULT_MANIFEST):
    """Bind the audit's 19 identities to the current checked-in MapSee catalog."""
    catalog, catalog_hash = _read_json(catalog_audit)
    rows = catalog.get('read_only_audit', {}).get('broader_charleston_existing_registry_rows')
    if (not isinstance(rows, list) or len(rows) != len(MAPSEE_IDS)
            or any(not isinstance(row, dict) for row in rows)
            or {row.get('id') for row in rows} != MAPSEE_IDS):
        raise ValueError('audit_mapsee_inventory_incomplete')

    batch, batch_hash = {}, None
    if manifest is not None and Path(manifest).exists():
        batch, batch_hash = _read_json(manifest)
    manifest_holds = _inventory_rows(batch, 'held_sources')
    holds_by_key = {row['source_key']: row for row in manifest_holds if row.get('source_key')}
    manifest_names = {row.get('source_key'): row.get('publisher_name')
                      for row in _inventory_rows(batch, 'supported_sources')}
    entries = []
    for key in sorted(holly_hill_sources.SOURCES):
        entry = {'source': holly_hill_sources.source_payload(key),
                 'group': 'new_holly_hill', 'registry_snapshot': None}
        if manifest_names.get(key):
            entry['publisher_name'] = manifest_names[key]
        if key in holds_by_key:
            entry['hold'] = {'reason': 'batch_manifest_hold',
                             'evidence': holds_by_key[key]}
        entries.append(entry)

    profiles = mapsee_adapter.profiles()
    signatures = {'ics': ('ical', 'ical'), 'tribe': ('json', 'wordpress'),
                  'squarespace': ('json', 'squarespace')}
    for row in sorted(rows, key=lambda item: item['id']):
        profile = profiles.get(row.get('source_key'), {})
        signature = signatures.get(profile.get('type'))
        if (profile.get('url') != row.get('feed_url')
                or signature != (row.get('kind'), row.get('platform_adapter'))
                or profile.get('platform_adapter') != row.get('platform_adapter')):
            raise ValueError('audit_mapsee_identity_changed')
        source = {'source_key': profile['source_key'], 'feed_url': profile['url'],
                  'kind': signature[0], 'platform_adapter': signature[1],
                  'timezone': profile.get('timezone') or ZONE}
        entry = {'source': source, 'group': 'existing_mapsee_broader_charleston',
                 'publisher_name': row['publisher_name'],
                 'registry_snapshot': {k: row[k] for k in REGISTRY_FIELDS if k in row}}
        if row['id'] in KNOWN_HOLDS:
            entry['hold'] = {'reason': KNOWN_HOLDS[row['id']],
                             'evidence': 'paused_mapsee_recheck in catalog audit'}
        elif row.get('approval') != 'approved' or row.get('health') == 'disabled':
            entry['hold'] = {'reason': 'registry_not_active'}
        elif source['source_key'] in holds_by_key:
            entry['hold'] = {'reason': 'batch_manifest_hold',
                             'evidence': holds_by_key[source['source_key']]}
        entries.append(entry)

    for row in EXISTING_LOCAL:
        source = {k: row[k] for k in ('source_key', 'feed_url', 'kind', 'platform_adapter')}
        source['timezone'] = ZONE
        entry = {'source': source, 'group': 'existing_local',
                 'publisher_name': row['publisher_name'],
                 'registry_snapshot': {k: row[k] for k in REGISTRY_FIELDS if k in row}}
        if source['source_key'] in holds_by_key:
            entry['hold'] = {'reason': 'batch_manifest_hold',
                             'evidence': holds_by_key[source['source_key']]}
        entries.append(entry)
    if len({item['source']['source_key'] for item in entries}) != len(entries):
        raise ValueError('audit_duplicate_source_key')

    retained = {
        'catalog_business_holds': _inventory_rows(catalog, 'business_holds'),
        'catalog_name_only_leads': _inventory_rows(catalog, 'name_only_inventory'),
        'batch_manifest_held_sources': manifest_holds,
        'batch_manifest_name_only_leads': _inventory_rows(batch, 'name_only_leads'),
    }
    retained['counts'] = {key: len(value) for key, value in retained.items()}
    retained['counts_note'] = 'Inventory lists may overlap; their counts must not be added together.'
    return {
        'entries': entries, 'retained_inventory': retained,
        'registry_snapshot_as_of': catalog.get('checked_at'),
        'source_versions': {
            'catalog_audit_sha256': catalog_hash, 'batch_manifest_sha256': batch_hash,
            'source_identity_sha256': hashlib.sha256(json.dumps(
                [entry['source'] for entry in entries], sort_keys=True).encode()).hexdigest(),
        },
    }


class _SourceTimeout(BaseException):
    """Escape broad collector exception handlers when the hard deadline fires."""


@contextmanager
def _hard_timeout(seconds):
    if not hasattr(signal, 'setitimer') or current_thread() is not main_thread():
        raise preview_worker.PreviewError('audit_hard_timeout_unavailable')
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise preview_worker.PreviewError('audit_timer_in_use')
    previous = signal.getsignal(signal.SIGALRM)

    def expire(_signum, _frame):
        raise _SourceTimeout()

    signal.signal(signal.SIGALRM, expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _safe_error(error):
    if isinstance(error, _SourceTimeout):
        return 'source_audit_timeout'
    value = error.args[0] if isinstance(error, preview_worker.PreviewError) and len(error.args) == 1 else ''
    return value if isinstance(value, str) and re.fullmatch(r'[a-z_0-9]{3,100}', value) else 'source_audit_failed'


def _error_category(code):
    if code in TRANSPORT_CODES or re.fullmatch(r'(?:source|publisher)_http_[1-5][0-9]{2}', code):
        return 'transport_error', 'timeout' if 'deadline' in code or 'timeout' in code else 'transport'
    return 'held', 'guard' if code in GUARD_CODES else 'collector_validation'


def _http_status(error):
    seen = set()
    for _ in range(6):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, HTTPError) and isinstance(error.code, int) and 100 <= error.code <= 599:
            return error.code
        error = error.__cause__
    return None


def _snapshot(output, source_key):
    if not isinstance(output, dict) or 'p_error' not in output:
        raise preview_worker.PreviewError('snapshot_shape_missing')
    if output['p_error'] is not None:
        raise preview_worker.PreviewError(output['p_error'])
    if output.get('p_source_key') != source_key:
        raise preview_worker.PreviewError('snapshot_source_mismatch')
    records, count = output.get('p_events'), output.get('p_future_count')
    if (not isinstance(records, list) or len(records) > MAX_RECORDS
            or any(not isinstance(row, dict) for row in records)):
        raise preview_worker.PreviewError('snapshot_records_invalid')
    if (type(count) is not int or not 0 <= count <= MAX_RECORDS or count < len(records)
            or bool(count) != bool(records)):
        raise preview_worker.PreviewError('snapshot_count_invalid')
    samples = []
    fields = {'id': 256, 'title': 500, 'starts_at': 64, 'ends_at': 64,
              'venue_name': 500, 'venue_address': 700, 'venue_city': 100, 'event_url': 2048}
    for row in records:
        if any(not isinstance(row.get(key), str) or not row[key].strip()
               for key in ('title', 'starts_at', 'event_url')):
            raise preview_worker.PreviewError('snapshot_records_invalid')
    for row in records[:MAX_SAMPLES]:
        samples.append({key: value[:limit] for key, limit in fields.items()
                        if isinstance((value := row.get(key)), str)})
    return {'outcome': 'success' if count else 'empty', 'complete': True,
            'candidate_count': count, 'returned_event_count': len(records),
            'returned_events_truncated': count > len(records), 'samples': samples}


def _bounded_seconds(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError('audit_timeout_out_of_bounds')
    return float(value)


def audit(*, catalog_audit=DEFAULT_CATALOG_AUDIT, manifest=DEFAULT_MANIFEST,
          per_source_seconds=PER_SOURCE_SECONDS, overall_seconds=OVERALL_SECONDS):
    per_source_seconds = _bounded_seconds(per_source_seconds, PER_SOURCE_SECONDS)
    overall_seconds = _bounded_seconds(overall_seconds, OVERALL_SECONDS)
    started_at = monotonic()
    overall_deadline = started_at + overall_seconds
    inventory = build_inventory(catalog_audit, manifest)
    result = {
        'schema_version': SCHEMA_VERSION, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'read_only': True, 'registry_snapshot_as_of': inventory['registry_snapshot_as_of'],
        'source_versions': inventory['source_versions'],
        'limits': {'per_source_seconds': per_source_seconds, 'overall_seconds': overall_seconds,
                   'concurrency': 1, 'samples_per_source': MAX_SAMPLES},
        'retained_inventory': inventory['retained_inventory'], 'sources': [],
        'notes': [
            'Registry approval/health/preview counts are historical snapshots, not live audit results.',
            'Broader Charleston MapSee membership does not establish event proximity to Holly Hill.',
            'Candidate counts are collector output, not published or deduplicated event counts.',
            'Held parser/guard results and failed requests are never successful empty feeds.',
        ],
    }
    for entry in inventory['entries']:
        source = entry['source']
        started = monotonic()
        deadline = min(overall_deadline, started + per_source_seconds)
        receipt = {**source, 'group': entry['group'],
                   'registry_snapshot': entry['registry_snapshot'],
                   'intended_active': 'hold' not in entry, 'source_preview_attempted': False,
                   'network_skipped': True, 'complete': False,
                   'candidate_count': None, 'samples': [],
                   'checked_at': datetime.now(timezone.utc).isoformat()}
        if entry.get('publisher_name'):
            receipt['publisher_name'] = entry['publisher_name']
        if 'hold' in entry:
            receipt.update(outcome='held', error=entry['hold']['reason'],
                           error_category='preexisting_hold', hold_evidence=entry['hold'])
        else:
            try:
                if started >= overall_deadline:
                    raise preview_worker.PreviewError('overall_audit_deadline')
                with _hard_timeout(deadline - started):
                    receipt.update(source_preview_attempted=True, network_skipped=False)
                    output = preview_worker.preview_source(dict(source), deadline_at=deadline)
                    if monotonic() >= deadline:
                        raise preview_worker.PreviewError('collection_deadline')
                    receipt.update(_snapshot(output, source['source_key']))
            except (_SourceTimeout, Exception) as error:
                code = _safe_error(error)
                outcome, category = _error_category(code)
                receipt.update(outcome=outcome, error=code, error_category=category,
                               complete=False, candidate_count=None, samples=[])
                receipt.pop('returned_event_count', None)
                receipt.pop('returned_events_truncated', None)
                status = _http_status(error)
                if status is not None:
                    receipt['caused_by_http_status'] = status
        receipt['duration_seconds'] = round(max(0, monotonic() - started), 3)
        result['sources'].append(receipt)
        # Event samples are only in the report file, never routine workflow logs.
        print(json.dumps({key: receipt[key] for key in (
            'source_key', 'outcome', 'candidate_count', 'duration_seconds')}
            | {'error': receipt.get('error')}), flush=True)

    rows = result['sources']
    result['counts'] = {
        'retained_sources': len(rows),
        'new_supported_sources': sum(row['group'] == 'new_holly_hill' for row in rows),
        'existing_mapsee_sources': sum(row['group'] == 'existing_mapsee_broader_charleston' for row in rows),
        'existing_local_sources': sum(row['group'] == 'existing_local' for row in rows),
        'intended_active_sources': sum(row['intended_active'] for row in rows),
        'attempted_sources': sum(row['source_preview_attempted'] for row in rows),
        **{outcome: sum(row['outcome'] == outcome for row in rows)
           for outcome in ('success', 'empty', 'transport_error', 'held')},
        'candidate_count_across_sources': sum(row['candidate_count'] or 0 for row in rows),
    }
    result['active_complete'] = all(row['complete'] for row in rows if row['intended_active'])
    result['complete'] = all(row['complete'] for row in rows)
    result['duration_seconds'] = round(max(0, monotonic() - started_at), 3)
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog-audit', type=Path, default=DEFAULT_CATALOG_AUDIT)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--per-source-seconds', type=float, default=PER_SOURCE_SECONDS)
    parser.add_argument('--overall-seconds', type=float, default=OVERALL_SECONDS)
    args = parser.parse_args(argv)
    try:
        report = audit(catalog_audit=args.catalog_audit, manifest=args.manifest,
                       per_source_seconds=args.per_source_seconds, overall_seconds=args.overall_seconds)
    except (ValueError, OSError):
        # Fail before any live request when a local inventory or limit is invalid.
        print('audit_configuration_invalid', file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return 0 if report['active_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
