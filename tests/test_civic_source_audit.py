import json
import sys

import pytest

from scripts import capture_civic_sources as capture


def output(source):
    rows = [{'id': 'public-test-record', 'title': 'Public notice', 'lat': None, 'lng': None,
             'civic': {'version': 1, 'time_precision': 'date'}}]
    return {'p_source_key': source['source_key'], 'p_error': None, 'p_events': rows, 'p_future_count': len(rows)}


@pytest.fixture(autouse=True)
def forbid_writes(monkeypatch):
    monkeypatch.setattr(capture.preview_worker, 'supabase_rpc',
                        lambda *a, **k: pytest.fail('Read-only audit attempted a database RPC'))


def test_fixed_inventory_and_bounded_preview_receipts_do_not_claim_or_publish(monkeypatch):
    calls = []
    monkeypatch.setattr(capture, 'monotonic', lambda: 100.0)
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)

    def preview(source, *, deadline_at):
        calls.append((source, deadline_at))
        return output(source)

    monkeypatch.setattr(capture.preview_worker, 'preview_source', preview)
    result = capture.audit(overall_seconds=300)
    assert len(calls) == 7 and all(deadline == 141 for _, deadline in calls)
    assert all(type(source['civic_contract_version']) is int and source['civic_contract_version'] == 1
               and source['civic_jurisdiction_id'].startswith('us-va') for source, _ in calls)
    assert result['complete'] and result['read_only']
    assert result['collector_sha'] == 'a' * 40
    assert all(len(value) == 64 for value in result['collector_files_sha256'].values())
    assert result['counts'] == {'sources': 7, 'complete': 7, 'failed': 0, 'candidates': 7, 'dated_notices': 7}
    scopes = {source['source_key']: source['scope'] for source in result['sources']}
    assert scopes['virginia_dmv_connect'] == 'publisher_first_page'
    assert scopes['clarksville_municipal_notices_va'] == 'publisher_news_first_page'
    assert len({source['source_key'] for source, _, _ in capture.source_specs()}) == 7


@pytest.mark.parametrize('error,code,category', [
    (capture.preview_worker.PreviewError('dns_unavailable'), 'dns_unavailable', 'dns_resolution'),
    (capture.preview_worker.PreviewError('publisher_http_403'), 'publisher_http_403', 'access'),
    (RuntimeError('secret-token https://untrusted.example/private'), 'source_audit_failed', 'unexpected'),
])
def test_failures_are_safe_failed_receipts_not_healthy_empty(monkeypatch, capsys, error, code, category):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(capture.preview_worker, 'preview_source', fail)
    result = capture.audit()
    assert not result['complete'] and result['counts']['failed'] == 7
    assert all(row['error'] == code and row['error_category'] == category for row in result['sources'])
    assert 'secret-token' not in json.dumps(result) + capsys.readouterr().out
    assert all('events' not in source for source in result['sources'])


def test_incomplete_output_and_missing_civic_metadata_are_failed(monkeypatch):
    def bad(source, **kwargs):
        result = output(source)
        result['p_events'][0].pop('civic')
        return result

    monkeypatch.setattr(capture.preview_worker, 'preview_source', bad)
    result = capture.audit()
    # Existing South Hill calendar intentionally contains mixed ordinary and civic records.
    assert result['counts']['failed'] == 6
    assert all(source['error'] == 'civic_metadata_missing' for source in result['sources'][:6])


def test_overall_deadline_skips_later_requests_and_still_returns_every_inventory_receipt(monkeypatch):
    clock = iter(range(50))
    monkeypatch.setattr(capture, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(capture.preview_worker, 'preview_source', lambda *_a, **_k: pytest.fail('Expired audit fetched a source'))
    result = capture.audit(overall_seconds=1)
    assert not result['complete'] and len(result['sources']) == 7
    assert all(source['network_skipped'] and not source['source_preview_attempted'] for source in result['sources'])


def test_failed_cli_writes_complete_artifact_and_exits_nonzero(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise capture.preview_worker.PreviewError('dns_unavailable')

    path = tmp_path / 'civic-audit.json'
    monkeypatch.setattr(capture.preview_worker, 'preview_source', fail)
    monkeypatch.setattr(sys, 'argv', ['capture_civic_sources.py', '--output', str(path)])
    assert capture.main() == 1
    result = json.loads(path.read_text())
    assert not result['complete'] and result['counts']['failed'] == 7


@pytest.mark.parametrize('seconds', [0, -1, 601, True, 1.5])
def test_audit_deadline_cannot_be_unbounded(seconds):
    with pytest.raises(ValueError, match='invalid_audit_deadline'):
        capture.audit(overall_seconds=seconds)
