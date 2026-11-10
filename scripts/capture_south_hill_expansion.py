#!/usr/bin/env python3
"""Read-only acceptance audit for exactly three publishers and Town markets.

Each source runs through preview_source and the ordinary publisher transport.
No credentials, database RPC, queue claim, demand, image probe, activation or
publication is used. Successful HTTP responses are hashed; an optional local
directory preserves those same public documents for parser review. A fetched
document is never a substitute for a complete normalized source snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic
from urllib.parse import urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomquest.revize import FEED_URL as TOWN_FEED

SOURCES = {
    'mcgregor_hall_henderson_nc': ('https://www.mcgregorhall.org/shows-events', 'html', 'html'),
    'victoria_town_calendar_va': ('https://victoriava.net/calendar-of-events', 'html', 'html'),
    'vance_county_arts_council_nc': ('https://vanceartscouncil.com/events/', 'html', 'html'),
    'south_hill_town_va': (TOWN_FEED, 'json', 'revize'),
}
PER_SOURCE_SECONDS = 40
OVERALL_SECONDS = 180
MAX_DOCUMENTS = 20
MAX_DOCUMENT_BYTES = 3_000_000
MAX_SOURCE_BYTES = 16_000_000
MAX_RECORDS = 500
MAX_LOG_BYTES = 200_000
FILES = (
    'roomquest/mcgregor_hall.py', 'roomquest/victoria_calendar.py',
    'roomquest/vance_arts.py', 'roomquest/south_hill_markets.py',
    'roomquest/preview_worker.py', 'roomquest/publisher_evidence.py',
    'roomquest/revize.py', 'roomquest/mapsee_adapter.py',
    'scripts/capture_south_hill_expansion.py', 'pyproject.toml',
)


class BoundedLog(io.StringIO):
    def write(self, text):
        if self.tell() + len(text) > MAX_LOG_BYTES:
            raise ValueError('audit_diagnostic_limit')
        return super().write(text)


def source(key):
    url, kind, adapter = SOURCES[key]
    return {'source_key': key, 'feed_url': url, 'kind': kind,
            'platform_adapter': adapter, 'timezone': 'America/New_York',
            **({'civic_contract_version': 1, 'civic_jurisdiction_id': 'us-va-south-hill',
                'south_hill_market_contract_version': 1}
               if key == 'south_hill_town_va' else {})}


def _code(error):
    value = str(error)
    return value if re.fullmatch(r'[a-z_0-9]{3,100}', value) else 'source_audit_failed'


def _candidate(event):
    fields = ('id', 'title', 'starts_at', 'ends_at', 'timezone', 'venue_name',
              'venue_address', 'venue_city', 'event_url', 'image_url',
              'publisher_status', 'publisher_details', 'location_provenance',
              'publisher_document', 'details_extractor_version',
              'details_evidence_url', 'image_extractor_version', 'image_evidence_url',
              'civic')
    return {key: event[key] for key in fields if key in event}


def _diagnostics(log, key):
    items = []
    for line in log.getvalue().splitlines():
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue  # Do not copy arbitrary exception text or full prose.
        if not isinstance(item, dict) or item.get('source_key') != key:
            continue
        fields = ('event', 'source_key', 'id', 'event_id', 'event_url', 'reason',
                  'disposition', 'held', 'excluded', 'records', 'cards',
                  'schedule_cards', 'accounted_count', 'document_url',
                  'source_card_id', 'starts_at', 'ends_at')
        items.append({name: item[name] for name in fields if name in item})
        if len(items) > MAX_RECORDS * 2:
            raise ValueError('audit_diagnostic_limit')
    return items


def audit(keys=None, *, documents_dir=None):
    from roomquest import preview_worker

    keys = list(dict.fromkeys(SOURCES if keys is None else keys))
    if not keys or any(key not in SOURCES for key in keys):
        raise ValueError('unreviewed_audit_source')
    root = Path(__file__).resolve().parents[1]
    sha = os.environ.get('GITHUB_SHA', '')
    report = {
        'schema_version': 1,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'read_only': True, 'authoritative_state_unchanged': True,
        'collection_ready': False,
        'collector_sha': sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        'collector_files_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                   for name in FILES if (root / name).is_file()},
        'limits': {'per_source_seconds': PER_SOURCE_SECONDS,
                   'overall_seconds': OVERALL_SECONDS,
                   'max_documents_per_source': MAX_DOCUMENTS,
                   'max_document_bytes': MAX_DOCUMENT_BYTES,
                   'max_source_bytes': MAX_SOURCE_BYTES,
                   'max_records': MAX_RECORDS},
        'sources': [],
    }
    overall = monotonic() + OVERALL_SECONDS
    real_fetch = preview_worker.fetch_publisher
    for key in keys:
        definition = source(key)
        started = monotonic()
        deadline = min(overall, started + PER_SOURCE_SECONDS)
        row = {**definition, 'hold_cleared': False, 'documents': []}
        log = BoundedLog()
        total_bytes = 0

        def capture(url, accept, **kwargs):
            nonlocal total_bytes
            host = urlsplit(definition['feed_url']).hostname
            if (kwargs.get('respect_robots') is not True
                    or kwargs.get('allowed_hosts') != (host,)
                    or kwargs.get('deadline_at') is None
                    or kwargs['deadline_at'] > deadline
                    or urlsplit(url).hostname != host
                    or accept not in ('text/html', 'application/json', 'application/pdf')):
                raise ValueError('audit_publisher_scope_changed')
            if len(row['documents']) >= MAX_DOCUMENTS:
                raise ValueError('audit_document_limit')
            body = real_fetch(url, accept, **kwargs)
            encoded = body.encode('utf-8') if isinstance(body, str) else body
            if not isinstance(encoded, bytes) or len(encoded) > MAX_DOCUMENT_BYTES:
                raise ValueError('audit_document_limit')
            total_bytes += len(encoded)
            if total_bytes > MAX_SOURCE_BYTES:
                raise ValueError('audit_document_limit')
            receipt = {'url': url, 'accept': accept, 'bytes': len(encoded),
                       'sha256': hashlib.sha256(encoded).hexdigest()}
            if documents_dir is not None:
                suffix = {'text/html': 'html', 'application/json': 'json', 'application/pdf': 'pdf'}[accept]
                filename = f'{key}-{len(row["documents"]) + 1:02d}.{suffix}'
                directory = Path(documents_dir)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / filename).write_bytes(encoded)
                receipt['artifact_file'] = filename
            row['documents'].append(receipt)
            return body

        try:
            if started >= overall:
                raise ValueError('collection_deadline')
            # This guard fails before any RPC implementation could read a key or
            # contact a database, even if a future preview route regresses.
            with (patch.object(preview_worker, 'fetch_publisher', side_effect=capture),
                  patch.object(preview_worker, 'supabase_rpc',
                               side_effect=AssertionError('read_only_audit_rpc_forbidden')),
                  redirect_stderr(log)):
                result = preview_worker.preview_source(definition, deadline_at=deadline)
            if monotonic() >= deadline:
                raise ValueError('collection_deadline')
            if (not isinstance(result, dict) or result.get('p_error', 'missing') is not None
                    or result.get('p_source_key') != key
                    or result.get('p_parser_capability') != 'publisher_event_candidates_v1'
                    or not isinstance(result.get('p_events'), list)):
                raise ValueError('audit_snapshot_incomplete')
            events = result['p_events']
            if len(events) > MAX_RECORDS or any(not isinstance(event, dict) for event in events):
                raise ValueError('audit_snapshot_incomplete')
            if (type(result.get('p_future_count')) is not int
                    or result['p_future_count'] != len(events)
                    or any(not isinstance(event.get('id'), str) or not event['id'].strip() for event in events)
                    or len({event['id'] for event in events}) != len(events)):
                raise ValueError('audit_snapshot_identity_mismatch')
            if not row['documents']:
                raise ValueError('audit_publisher_evidence_missing')
            row.update(outcome='parsed', complete=True, candidate_count=len(events),
                       candidate_image_count=sum(bool(event.get('image_url')) for event in events),
                       candidates=[_candidate(event) for event in events])
        except Exception as error:
            code = _code(error)
            row.update(outcome='blocked', complete=False, error=code)
            row['failure_category'] = (
                'environment_dns' if code == 'dns_unavailable' else
                'publisher_policy' if code == 'robots_denied' else
                'publisher_access' if code.startswith('publisher_http_') else
                'publisher_rate_limit' if code == 'publisher_rate_limited' else
                'deadline' if code in ('collection_deadline', 'source_fetch_deadline') else
                'parser_or_runtime')
        row['diagnostics'] = _diagnostics(log, key)
        row['duration_seconds'] = round(monotonic() - started, 3)
        report['sources'].append(row)
        print(json.dumps({field: row[field] for field in (
            'source_key', 'outcome', 'complete', 'candidate_count', 'candidate_image_count',
            'error', 'failure_category', 'duration_seconds') if field in row}), flush=True)
    report['complete'] = all(row['complete'] for row in report['sources'])
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    report['counts'] = {
        'parsed': sum(row['outcome'] == 'parsed' for row in report['sources']),
        'blocked': sum(row['outcome'] == 'blocked' for row in report['sources']),
        'candidates': sum(row.get('candidate_count', 0) for row in report['sources']),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', choices=tuple(SOURCES))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--documents-dir', type=Path)
    args = parser.parse_args()
    result = audit(args.source, documents_dir=args.documents_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(result, indent=2) + '\n').encode('utf-8')
    args.output.write_bytes(raw)
    print(json.dumps({'collector_sha': result['collector_sha'],
                      'audit_sha256': hashlib.sha256(raw).hexdigest(),
                      'complete': result['complete'], 'counts': result['counts']}), flush=True)
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
