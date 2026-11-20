#!/usr/bin/env python3
"""Refresh ten existing collectors into an isolated SQLite staging database.

Uses the normal guarded publisher transport. No production RPC or publication
path is callable here. Baseline replays the exact captured response bodies,
avoiding a second publisher crawl or a moving before/after comparison.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from time import monotonic
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roomquest.description_canary_scope import SOURCE_KEYS, full_description_scope, repair_c1
from roomquest import preview_worker as worker


def digest(value):
    if not isinstance(value, bytes):
        value = value.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def identity(row):
    return str(row.get('id')), str(row.get('starts_at'))


def review_reason(row):
    # Quarantine signals; do not infer a replacement date or rewrite the event.
    if re.search(r'\b(?:cancell?ed|rescheduled|postponed)\b', row.get('title', ''), re.I):
        return 'cancellation_or_reschedule_review'
    return ''


def record_key(url, accept, kwargs):
    # Deadline is execution-local and differs between capture and replay.
    return url, accept, repr(sorted((k, v) for k, v in kwargs.items() if k != 'deadline_at'))


def collect_pair(source):
    if source['source_key'] not in SOURCE_KEYS:
        raise ValueError('source_not_in_description_canary')
    captures = {}
    receipts = []
    original_fetch = worker._fetch_publisher_request

    def capture(url, accept, **kwargs):
        payload = original_fetch(url, accept, **kwargs)
        key = record_key(url, accept, kwargs)
        captures[key] = payload
        receipts.append({'url': url, 'sha256': digest(payload), 'characters_or_bytes': len(payload)})
        return payload

    def replay(url, accept, **kwargs):
        key = record_key(url, accept, kwargs)
        if key not in captures:
            raise ValueError('baseline_requested_uncaptured_response')
        return captures[key]

    def no_rpc(*args, **kwargs):
        raise RuntimeError('production_rpc_forbidden_in_description_canary')

    with patch.object(worker, 'supabase_rpc', no_rpc):
        with patch.object(worker, '_fetch_publisher_request', capture), full_description_scope(source['source_key']):
            after = worker.preview_source(source, deadline_at=monotonic() + 50)['p_events']
        with patch.object(worker, '_fetch_publisher_request', replay):
            before = worker.preview_source(source, deadline_at=monotonic() + 50)['p_events']
    old = {identity(row): row for row in before}
    new = {identity(row): row for row in after}
    if len(old) != len(before) or len(new) != len(after) or old.keys() != new.keys():
        raise ValueError('canary_identity_set_changed')
    for key, row in new.items():
        if {k: v for k, v in row.items() if k != 'description'} != {
                k: v for k, v in old[key].items() if k != 'description'}:
            raise ValueError('canary_non_description_field_changed')
    return before, after, receipts


def run(sources, output):
    if len(sources) != 10 or {s['source_key'] for s in sources} != SOURCE_KEYS:
        raise ValueError('exact_ten_source_manifest_required')
    if any(s.get('rights_status') != 'unreviewed' or s.get('terms_review_note') for s in sources):
        raise ValueError('source_review_changed_reassess_manifest')
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(output / 'staging.sqlite')
    db.execute('create table events(source_id integer, identity text, starts_at text, title text, before_description text, full_description text, display_description text, review_reason text, event_json text, primary key(source_id,identity,starts_at))')
    db.execute("create view display_events as select * from events where review_reason = ''")
    summaries = []
    for source in sources:
        summary = {'source_id': source['id'], 'source_key': source['source_key'],
                   'publisher': source['publisher_name'], 'started_at': datetime.now(timezone.utc).isoformat(),
                   'status': 'failed', 'production_writes': 0}
        try:
            before, after, receipts = collect_pair(source)
            old = {identity(row): row for row in before}
            gained = repaired = held = nonblank = shortened = added_chars = 0
            for row in after:
                prior = old[identity(row)].get('description') or ''
                full = row.get('description') or ''
                display = repair_c1(full)
                reason = review_reason(row)
                nonblank += bool(full.strip())
                gained += len(full) > len(prior)
                shortened += len(full) < len(prior)
                added_chars += max(0, len(full) - len(prior))
                repaired += display != full
                held += bool(reason)
                db.execute('insert into events values(?,?,?,?,?,?,?,?,?)', (
                    source['id'], str(row['id']), row['starts_at'], row['title'], prior, full,
                    display, reason, json.dumps(row, ensure_ascii=False)))
            db.commit()
            summary.update(status='captured', events=len(after), nonblank=nonblank,
                           longer=gained, shortened=shortened, additional_characters=added_chars,
                           encoding_repaired=repaired, held_for_review=held,
                           max_description=max((len(r.get('description') or '') for r in after), default=0),
                           response_receipts=receipts)
        except Exception as exc:
            db.rollback()
            summary['error'] = type(exc).__name__ + ': ' + str(exc)[:160]
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        summaries.append(summary)
        (output / 'summary.json').write_text(json.dumps(summaries, indent=2))
        print(json.dumps({k: v for k, v in summary.items() if k != 'response_receipts'}), flush=True)
    db.close()
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.sources.read_text()), args.output)
