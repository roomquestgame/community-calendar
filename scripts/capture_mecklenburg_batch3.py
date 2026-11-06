#!/usr/bin/env python3
"""Read-only verification of the three exact EVE-41 publisher sources.

Only preview_source is called: no database authentication, source claims,
staging, demand, publication, source registration or image probes. Publisher
facts and bounded diagnostic codes are the only artifact content.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomquest import clarksville_tourism, coopers_landing, good_shepherd, preview_worker

SOURCES = (
    ('clarksville_tourism_va', clarksville_tourism.CALENDAR),
    ('coopers_landing_clarksville_va', coopers_landing.CALENDAR),
    ('good_shepherd_food_pantry_south_hill_va', good_shepherd.CALENDAR),
)
PER_SOURCE_SECONDS = 41
OVERALL_SECONDS = 135
MAX_RECORDS = 500


def audit():
    overall = monotonic() + OVERALL_SECONDS
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'read_only': True, 'sources': []}
    for key, url in SOURCES:
        started = monotonic()
        deadline = min(overall, started + PER_SOURCE_SECONDS)
        receipt = {'source_key': key, 'kind': 'html', 'platform_adapter': 'html'}
        try:
            if started >= overall:
                raise preview_worker.PreviewError('collection_deadline')
            source = {'source_key': key, 'kind': 'html', 'platform_adapter': 'html',
                      'feed_url': url, 'timezone': 'America/New_York'}
            output = preview_worker.preview_source(source, deadline_at=deadline)
            if monotonic() >= deadline:
                raise preview_worker.PreviewError('collection_deadline')
            if not isinstance(output, dict) or 'p_error' not in output:
                raise preview_worker.PreviewError('snapshot_shape_missing')
            if output['p_error'] is not None:
                raise preview_worker.PreviewError(output['p_error'])
            if output.get('p_parser_capability') != 'publisher_event_candidates_v1':
                raise preview_worker.PreviewError('snapshot_capability_missing')
            records = output.get('p_events')
            if (not isinstance(records, list) or len(records) > MAX_RECORDS
                    or any(not isinstance(event, dict) for event in records)):
                raise preview_worker.PreviewError('snapshot_records_invalid')
            receipt.update(outcome='complete', candidate_count=len(records),
                           candidate_image_count=sum(bool(event.get('image_url')) for event in records),
                           parser_capability=output['p_parser_capability'], events=records)
        except Exception as error:
            # Raw exception messages may contain transport URLs or headers.
            # Keep only the existing collector's bounded diagnostic-code form.
            value = error.args[0] if isinstance(error, preview_worker.PreviewError) and len(error.args) == 1 else ''
            code = value if isinstance(value, str) and re.fullmatch(r'[a-z_0-9]{3,100}', value) else 'source_audit_failed'
            receipt.update(outcome='failed', error=code)
        receipt['duration_seconds'] = round(monotonic() - started, 2)
        result['sources'].append(receipt)
        print(json.dumps({key: value for key, value in receipt.items() if key != 'events'}), flush=True)
    result['complete'] = all(row['outcome'] == 'complete' for row in result['sources'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
