#!/usr/bin/env python3
"""Read-only audit of the eight reviewed Raleigh HTML calendars.

Uses preview_source and its unchanged publisher/robots/DNS/deadline guards.
Never authenticates to the database, claims work, creates demand, stages or
publishes an event. Candidate counts are not public EventQuest event counts.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomquest import preview_worker
from roomquest.raleigh_html import SOURCES

HELD = {'black_chamber_raleigh_nc': 'publisher_event_evidence_conflict'}


def audit():
    deadline = monotonic() + 340
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'read_only': True, 'sources': []}
    for key, (url, _, _) in SOURCES.items():
        receipt = {'source_key': key, 'intended_active': key not in HELD}
        if key in HELD:
            receipt.update(outcome='held', reason=HELD[key], network_skipped=True)
        else:
            started = monotonic()
            try:
                if started >= deadline:
                    raise preview_worker.PreviewError('collection_deadline')
                output = preview_worker.preview_source(dict(source_key=key, feed_url=url,
                    kind='html', platform_adapter='html', timezone='America/New_York'),
                    deadline_at=min(deadline, started + 41))
                if output.get('p_error') or output.get('p_parser_capability') != 'publisher_event_candidates_v1':
                    raise preview_worker.PreviewError('snapshot_incomplete')
                rows = output['p_events']
                receipt.update(outcome='complete', candidate_count=len(rows),
                    candidate_image_count=sum(bool(x.get('image_url')) for x in rows), events=rows)
            except Exception as error:
                value = error.args[0] if isinstance(error, preview_worker.PreviewError) and len(error.args)==1 else ''
                receipt.update(outcome='failed', reason=value if isinstance(value,str)
                    and re.fullmatch(r'[a-z_0-9]{3,100}',value) else 'source_audit_failed')
            receipt['duration_seconds'] = round(monotonic()-started,2)
        result['sources'].append(receipt)
        print(json.dumps({k:v for k,v in receipt.items() if k!='events'}),flush=True)
    result['active_complete'] = all(x['outcome']=='complete' for x in result['sources'] if x['intended_active'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=audit()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    return 0 if result['active_complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
