#!/usr/bin/env python3
"""Read-only, bounded audit through the five sources' real shared transport.

This calls preview_source only. It does not authenticate to the database, stage,
publish, request source demand, register sources or probe images. Public source
facts and bounded diagnostic codes are the only output.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomquest import preview_worker
from roomquest import revize, south_hill_chamber

SOURCES = (
    ('south_hill_town_va', 'json', 'revize', revize.FEED_URL),
    ('south_hill_chamber_va', 'html', 'html', south_hill_chamber.CALENDAR),
    ('clarksville_community_players_va', 'html', 'html', 'https://clarksvilleplayers.org/'),
    ('maccallum_more_va', 'html', 'html', 'https://maccallummore.org/'),
    ('mecklenburg_ymca_programs_va', 'html', 'html', 'https://mecklenburg.recliquecore.com/programs/'),
)
PER_SOURCE_SECONDS = 39
OVERALL_SECONDS = 210


def audit():
    overall = monotonic() + OVERALL_SECONDS
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'read_only': True, 'sources': []}
    for key, kind, adapter, url in SOURCES:
        started = monotonic()
        receipt = {'source_key': key, 'kind': kind, 'platform_adapter': adapter}
        try:
            if started >= overall:
                raise preview_worker.PreviewError('collection_deadline')
            source = {'source_key': key, 'kind': kind, 'platform_adapter': adapter,
                      'feed_url': url, 'timezone': 'America/New_York'}
            output = preview_worker.preview_source(
                source, deadline_at=min(overall, started + PER_SOURCE_SECONDS))
            if output['p_error'] is not None:
                raise preview_worker.PreviewError(output['p_error'])
            if output.get('p_parser_capability') != 'publisher_event_candidates_v1':
                raise preview_worker.PreviewError('snapshot_capability_missing')
            records = output['p_events']
            receipt.update(outcome='complete', candidate_count=len(records),
                           candidate_image_count=sum(bool(e.get('image_url')) for e in records),
                           parser_capability=output['p_parser_capability'], events=records)
        except Exception as error:
            # Never report transport URLs/headers, raw exception text or credentials.
            value = error.args[0] if isinstance(error, preview_worker.PreviewError) and len(error.args) == 1 else ''
            code = value if isinstance(value, str) and re.fullmatch(r'[a-z_0-9]{3,100}', value) else 'source_audit_failed'
            receipt.update(outcome='failed', error=code)
        receipt['duration_seconds'] = round(monotonic() - started, 2)
        result['sources'].append(receipt)
        print(json.dumps({k: v for k, v in receipt.items() if k != 'events'}), flush=True)
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

