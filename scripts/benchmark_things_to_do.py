"""Run the approved twenty search-only queries through the durable shared ledger.

Requires server credentials and the database search switch; never activates a
publisher canary, changes billing, fetches publisher URLs, or publishes a card.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomquest.things_to_do_coordinator import discovery_rpc  # noqa: E402
from roomquest.things_to_do_search import run_search  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Execute up to 20 budgeted Basic requests')
    args = parser.parse_args()
    if not args.execute:
        from roomquest.things_to_do_search import benchmark_queries
        print(json.dumps({'status': 'dry_run', 'queries': benchmark_queries()}, indent=2))
        return 0
    key = os.environ.get('TAVILY_API_KEY', '')
    if not key:
        print(json.dumps({'status': 'search_credentials_missing', 'requests': 0}))
        return 2
    discovery_rpc('seed_benchmark', {})
    receipts = []
    for _ in range(20):
        job = discovery_rpc('next_search', {})
        if job.get('status') != 'ready' or job.get('planner') != 'benchmark':
            receipts.append({'status': job.get('status'), 'reason': 'no_pending_benchmark'})
            break
        result = run_search(key=key, job=job, database=discovery_rpc)
        receipts.append(result)
        if result.get('status') != 'finished' or result.get('outcome') != 'success':
            break
    print(json.dumps({'receipts': receipts}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
