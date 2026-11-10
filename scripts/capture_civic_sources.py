#!/usr/bin/env python3
"""Read-only civic source receipts through the unchanged shared publisher guards.

This fixed inventory does not claim, stage, publish or authenticate to a
database. Counts describe parser candidates in each explicitly bounded source
scope, not public EventQuest events or nationwide calendar coverage.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roomquest import civic_schedule, legistar, municipal_notices, preview_worker, revize, virginia_civic
from roomquest.collector_errors import failure_details

SOURCE_SECONDS = 41
DEFAULT_OVERALL_SECONDS = 480
MAX_OVERALL_SECONDS = 600
MAX_SOURCES = 12
CODE_PATHS = (
    'scripts/capture_civic_sources.py', 'roomquest/preview_worker.py',
    'roomquest/legistar.py', 'roomquest/virginia_civic.py', 'roomquest/municipal_notices.py',
    'roomquest/civic_schedule.py', 'roomquest/civic_notices.py',
    'roomquest/revize.py', 'roomquest/ics_adapter.py',
)


def source_specs():
    sources = [(legistar.source_payload(key), 'bounded_api_window', True) for key in legistar.SOURCES]
    sources.extend((virginia_civic.source_payload(key), spec['scope'], True)
                   for key, spec in virginia_civic.SOURCES.items())
    sources.extend([
        (municipal_notices.source_payload(), 'publisher_news_first_page', True),
        (civic_schedule.public_works_source(), 'verified_request_required_monthly_rule', True),
        ({'source_key': 'south_hill_town_va', 'feed_url': revize.FEED_URL,
          'kind': 'json', 'platform_adapter': 'revize', 'timezone': 'America/New_York',
          'civic_contract_version': 1, 'civic_jurisdiction_id': 'us-va-south-hill',
          'civic_jurisdiction_name': 'Town of South Hill'},
         'publisher_calendar_with_reviewed_civic_opt_in', False),
    ])
    return sources


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def audit(*, overall_seconds=DEFAULT_OVERALL_SECONDS):
    if isinstance(overall_seconds, bool) or not isinstance(overall_seconds, int) or not 1 <= overall_seconds <= MAX_OVERALL_SECONDS:
        raise ValueError('invalid_audit_deadline')
    sources = source_specs()
    if not sources or len(sources) > MAX_SOURCES or len({source['source_key'] for source, _, _ in sources}) != len(sources):
        raise ValueError('invalid_civic_audit_inventory')
    started = monotonic()
    deadline = started + overall_seconds
    sha = os.environ.get('GITHUB_SHA', '')
    result = {
        'schema_version': 1, 'read_only': True, 'checked_at': _utc_now(),
        'collector_sha': sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        'collector_files_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in CODE_PATHS},
        'limits': {'overall_seconds': overall_seconds, 'source_seconds': SOURCE_SECONDS,
                   'max_sources': MAX_SOURCES, 'max_candidates_per_source': 500},
        'sources': [],
    }
    for source, scope, require_civic in sources:
        source_started = monotonic()
        receipt = {key: source[key] for key in ('source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone')}
        receipt.update(scope=scope, checked_at=_utc_now(), complete=False,
                       source_preview_attempted=False, network_skipped=False)
        try:
            if source_started >= deadline:
                receipt['network_skipped'] = True
                raise preview_worker.PreviewError('collection_deadline')
            receipt['source_preview_attempted'] = True
            output = preview_worker.preview_source(source, deadline_at=min(deadline, source_started + SOURCE_SECONDS))
            if output.get('p_error'):
                raise preview_worker.PreviewError(output['p_error'])
            rows = output.get('p_events')
            if (output.get('p_source_key') != source['source_key'] or not isinstance(rows, list)
                    or len(rows) > 500 or output.get('p_future_count') != len(rows)
                    or any(not isinstance(row, dict) for row in rows)):
                raise preview_worker.PreviewError('snapshot_incomplete')
            if require_civic and any(not isinstance(row.get('civic'), dict) or row['civic'].get('version') != 1 for row in rows):
                raise preview_worker.PreviewError('civic_metadata_missing')
            dated = sum(row.get('civic', {}).get('time_precision') in {'date', 'window'} for row in rows)
            receipt.update(outcome='complete', complete=True, candidate_count=len(rows),
                           dated_notice_count=dated, timed_candidate_count=len(rows) - dated,
                           timed_notice_count=sum(row.get('civic_notice') is True
                               and row.get('civic', {}).get('time_precision') == 'timed' for row in rows),
                           verified_pin_count=sum(row.get('lat') is not None and row.get('lng') is not None for row in rows),
                           explicit_cancellation_count=sum(row.get('publisher_status') in {'cancelled', 'canceled'} for row in rows),
                           events=rows)
        except Exception as error:
            expected = isinstance(error, preview_worker.PreviewError)
            value = error.args[0] if expected and len(error.args) == 1 else ''
            code = value if isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_]{2,119}', value) else 'source_audit_failed'
            details = failure_details(code, expected_source_error=expected, phase='collection')
            receipt.update(outcome='failed', error=code, **details)
            # DNS failure is a failed receipt, not evidence of publisher denial.
            receipt['error_category'] = 'dns_resolution' if code == 'dns_unavailable' else details['error_kind']
        receipt['duration_seconds'] = round(monotonic() - source_started, 2)
        result['sources'].append(receipt)
        print(json.dumps({key: value for key, value in receipt.items() if key != 'events'}, sort_keys=True), flush=True)
    result.update(finished_at=_utc_now(), duration_seconds=round(monotonic() - started, 2),
                  complete=all(source['complete'] for source in result['sources']))
    result['counts'] = {
        'sources': len(sources), 'complete': sum(source['complete'] for source in result['sources']),
        'failed': sum(not source['complete'] for source in result['sources']),
        'candidates': sum(source.get('candidate_count', 0) for source in result['sources']),
        'dated_notices': sum(source.get('dated_notice_count', 0) for source in result['sources']),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--overall-seconds', type=int, default=DEFAULT_OVERALL_SECONDS,
                        help=f'Bounded total deadline, 1–{MAX_OVERALL_SECONDS} seconds')
    args = parser.parse_args()
    if not 1 <= args.overall_seconds <= MAX_OVERALL_SECONDS:
        parser.error(f'--overall-seconds must be between 1 and {MAX_OVERALL_SECONDS}')
    result = audit(overall_seconds=args.overall_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
