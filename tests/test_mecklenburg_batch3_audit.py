"""The manual audit stays source-scoped, bounded and read-only under failures."""
import json

import pytest

from scripts import capture_mecklenburg_batch3 as audit


def success(events=None):
    return {'p_error': None, 'p_parser_capability': 'publisher_event_candidates_v1',
            'p_events': events if events is not None else []}


def test_injected_success_calls_only_the_three_reviewed_sources_with_deadlines(monkeypatch, capsys):
    now, calls = [100.0], []
    monkeypatch.setattr(audit, 'monotonic', lambda: now[0])
    def preview(source, *, deadline_at):
        calls.append((dict(source), deadline_at))
        now[0] += 2
        return success([{'id': 'test', 'title': 'PUBLIC_BODY_SENTINEL', 'image_url': 'https://publisher.example/event.jpg'}])
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    result = audit.audit()
    assert result['read_only'] and result['complete']
    assert [(s['source_key'], s['feed_url']) for s, _ in calls] == list(audit.SOURCES)
    assert len(calls) == 3
    assert all(s['kind'] == s['platform_adapter'] == 'html' and s['timezone'] == 'America/New_York'
               and set(s) == {'source_key', 'feed_url', 'kind', 'platform_adapter', 'timezone'} for s, _ in calls)
    assert [deadline for _, deadline in calls] == [141.0, 143.0, 145.0]
    assert all(row['candidate_count'] == row['candidate_image_count'] == 1 for row in result['sources'])
    stdout = capsys.readouterr().out
    assert 'PUBLIC_BODY_SENTINEL' not in stdout
    assert len(stdout.splitlines()) == 3


def test_failure_is_sanitized_and_other_sources_are_still_checked(monkeypatch, capsys):
    calls = []
    def preview(source, **kwargs):
        calls.append(source['source_key'])
        if len(calls) == 1:
            raise OSError('SENSITIVE_SENTINEL https://private.example/token')
        if len(calls) == 2:
            return {'p_error': 'robots_denied'}
        return success()
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    result = audit.audit()
    assert not result['complete'] and len(calls) == 3
    assert [r.get('error') for r in result['sources']] == ['source_audit_failed', 'robots_denied', None]
    assert result['sources'][-1]['candidate_count'] == 0
    assert 'SENSITIVE_SENTINEL' not in json.dumps(result) + capsys.readouterr().out


def test_overall_exhaustion_does_not_start_more_requests_or_keep_late_results(monkeypatch):
    now, calls = [0.0], []
    monkeypatch.setattr(audit, 'monotonic', lambda: now[0])
    def preview(source, *, deadline_at):
        calls.append(deadline_at)
        now[0] = 136.0
        return success([{'id': 'late'}])
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    result = audit.audit()
    assert calls == [41.0]
    assert not result['complete']
    assert all(r['error'] == 'collection_deadline' and 'events' not in r for r in result['sources'])


@pytest.mark.parametrize('result,code', [
    ({}, 'snapshot_shape_missing'),
    ({'p_error': None, 'p_events': []}, 'snapshot_capability_missing'),
    (success('invalid'), 'snapshot_records_invalid'),
    (success([None]), 'snapshot_records_invalid'),
    (success([{}] * (audit.MAX_RECORDS + 1)), 'snapshot_records_invalid'),
    ({'p_error': 'SENSITIVE_SENTINEL https://private.example'}, 'source_audit_failed'),
])
def test_partial_or_unrecognized_output_cannot_claim_complete(monkeypatch, capsys, result, code):
    monkeypatch.setattr(audit.preview_worker, 'preview_source', lambda *args, **kwargs: result)
    report = audit.audit()
    assert not report['complete']
    assert all(row['error'] == code for row in report['sources'])
    assert 'SENSITIVE_SENTINEL' not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('complete,exit_code', [(True, 0), (False, 1)])
def test_cli_writes_reviewable_receipt_and_returns_failure_status(monkeypatch, tmp_path, complete, exit_code):
    report = {'read_only': True, 'complete': complete, 'sources': []}
    target = tmp_path / 'audit.json'
    monkeypatch.setattr(audit, 'audit', lambda: report)
    monkeypatch.setattr(audit.sys, 'argv', ['capture_mecklenburg_batch3.py', '--output', str(target)])
    assert audit.main() == exit_code
    assert json.loads(target.read_text()) == report
