"""Read-only inventory coverage, bounded live calls, and honest audit outcomes."""
from contextlib import nullcontext
import json
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from scripts import capture_holly_hill_batch as audit


def event(index=1):
    return {'id': str(index), 'title': 'Public event ' + str(index),
            'starts_at': '2026-12-12T09:00:00-05:00',
            'ends_at': '2026-12-12T12:00:00-05:00',
            'venue_name': 'Publisher venue', 'venue_city': 'Holly Hill',
            'event_url': 'https://publisher.example/event/' + str(index),
            'description': 'DO_NOT_LOG_OR_RETAIN_FULL_BODY',
            'image_url': 'https://publisher.example/do-not-probe.jpg'}


def success(source, events=None, count=None):
    records = events if events is not None else []
    # MapSee and institution ICS legitimately omit p_parser_capability.
    return {'p_source_key': source['source_key'], 'p_error': None,
            'p_future_count': len(records) if count is None else count,
            'p_events': records}


@pytest.fixture
def no_real_io(monkeypatch):
    monkeypatch.setattr(audit.preview_worker, 'supabase_rpc',
                        Mock(side_effect=AssertionError('database must not be used')))
    monkeypatch.setattr(audit.preview_worker, 'fetch_publisher',
                        Mock(side_effect=AssertionError('test must mock preview interface')))
    monkeypatch.setattr(audit, '_hard_timeout', lambda seconds: nullcontext())


def test_inventory_includes_every_supported_source_and_all_existing_rows():
    inventory = audit.build_inventory(manifest=None)
    entries = inventory['entries']
    new = [row for row in entries if row['group'] == 'new_holly_hill']
    assert {row['source']['source_key'] for row in new} == set(audit.holly_hill_sources.SOURCES)
    assert [row['source'] for row in new] == [audit.holly_hill_sources.source_payload(key)
                                           for key in sorted(audit.holly_hill_sources.SOURCES)]
    mapsee = [row for row in entries if row['group'] == 'existing_mapsee_broader_charleston']
    assert {row['registry_snapshot']['id'] for row in mapsee} == audit.MAPSEE_IDS
    assert len(mapsee) == 19
    assert {row['registry_snapshot']['id'] for row in mapsee if 'hold' in row} == {4347, 4403, 4682}
    local = {row['registry_snapshot']['id']: row['source']
             for row in entries if row['group'] == 'existing_local'}
    assert set(local) == {4897, 4915, 4920, 4949}
    assert local[4915]['source_key'] == 'south_carolina_parks_725'
    assert local[4915]['feed_url'].endswith('#park=725')
    assert 4912 not in local
    assert inventory['retained_inventory']['counts']['catalog_business_holds'] == 10
    assert inventory['retained_inventory']['counts']['catalog_name_only_leads'] == 3


def test_live_interface_calls_exact_inventory_skips_holds_and_limits_samples(no_real_io, monkeypatch, capsys):
    calls, clock = [], [100.0]
    monkeypatch.setattr(audit, 'monotonic', lambda: clock[0])

    def preview(source, *, deadline_at):
        calls.append((dict(source), deadline_at, clock[0]))
        clock[0] += 1
        return success(source, [event(n) for n in range(5)])

    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit(manifest=None)
    eligible = [row for row in audit.build_inventory(manifest=None)['entries'] if 'hold' not in row]
    assert [source for source, _, _ in calls] == [row['source'] for row in eligible]
    assert all(deadline == start + 45 for _, deadline, start in calls)
    assert report['read_only'] and report['active_complete'] and not report['complete']
    assert report['counts']['attempted_sources'] == len(eligible)
    assert report['counts']['held'] == 3
    assert report['counts']['candidate_count_across_sources'] == len(eligible) * 5
    for row in report['sources']:
        if row['intended_active']:
            assert row['outcome'] == 'success' and row['candidate_count'] == 5
            assert len(row['samples']) == 3
            assert not row['network_skipped'] and row['source_preview_attempted']
        else:
            assert row['outcome'] == 'held' and row['network_skipped']
            assert not row['source_preview_attempted'] and row['candidate_count'] is None
            assert row['registry_snapshot']['approval'] == 'paused'
    output = capsys.readouterr().out
    assert len(output.splitlines()) == len(report['sources'])
    assert 'Public event' not in output
    assert 'DO_NOT_LOG_OR_RETAIN_FULL_BODY' not in json.dumps(report) + output
    assert 'do-not-probe.jpg' not in json.dumps(report) + output


def test_empty_is_only_a_completed_zero_count_and_stored_counts_are_separate(no_real_io, monkeypatch):
    monkeypatch.setattr(audit.preview_worker, 'preview_source', lambda source, **_: success(source))
    report = audit.audit(manifest=None)
    chamber = next(row for row in report['sources'] if row.get('registry_snapshot', {})
                   and row['registry_snapshot']['id'] == 4897)
    assert chamber['outcome'] == 'empty' and chamber['candidate_count'] == 0
    assert chamber['registry_snapshot']['preview_future_count'] == 18
    assert report['counts']['success'] == 0
    assert report['counts']['empty'] == report['counts']['intended_active_sources']


def test_manifest_retains_unsupported_leads_without_expanding_network_scope(no_real_io, monkeypatch, tmp_path):
    path = tmp_path / 'batch.json'
    supported = next(iter(audit.holly_hill_sources.SOURCES))
    path.write_text(json.dumps({
        'supported_sources': [{'source_key': 'arbitrary', 'feed_url': 'https://arbitrary.example/',
                               'publisher_name': 'Arbitrary'}],
        'held_sources': [
            {'source_key': supported, 'publisher_name': 'Reviewed source', 'reason': 'Pending check'},
            {'source_key': 'unsupported', 'feed_url': 'https://unsupported.example/', 'reason': 'No adapter'},
        ],
        'name_only_leads': [{'name': 'Venue without a feed'}],
    }))
    calls = []

    def preview(source, **_):
        calls.append(source['source_key'])
        return success(source)

    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit(manifest=path)
    assert supported not in calls and 'arbitrary' not in calls and 'unsupported' not in calls
    row = next(row for row in report['sources'] if row['source_key'] == supported)
    assert row['outcome'] == 'held' and row['error'] == 'batch_manifest_hold'
    assert report['retained_inventory']['counts']['batch_manifest_held_sources'] == 2
    assert report['retained_inventory']['counts']['batch_manifest_name_only_leads'] == 1


def test_changed_catalog_identity_fails_closed_before_any_call(no_real_io, monkeypatch):
    profiles = {key: dict(value) for key, value in audit.mapsee_adapter.profiles().items()}
    key = next(row['source']['source_key'] for row in audit.build_inventory(manifest=None)['entries']
               if row['group'] == 'existing_mapsee_broader_charleston')
    profiles[key]['url'] = 'https://changed.example/'
    monkeypatch.setattr(audit.mapsee_adapter, 'profiles', lambda: profiles)
    preview = Mock()
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    with pytest.raises(ValueError, match='audit_mapsee_identity_changed'):
        audit.audit(manifest=None)
    preview.assert_not_called()


def test_transport_guard_validation_and_unknown_errors_are_not_empty(no_real_io, monkeypatch, capsys):
    failures = iter([
        audit.preview_worker.PreviewError('dns_unavailable'),
        audit.preview_worker.PreviewError('robots_denied'),
        audit.preview_worker.PreviewError('invalid_event_end'),
        OSError('SENSITIVE_SECRET https://private.example/token'),
    ])

    def preview(source, **_):
        error = next(failures, None)
        if error:
            raise error
        return success(source)

    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit(manifest=None)
    assert [(row['outcome'], row.get('error_category')) for row in report['sources'][:4]] == [
        ('transport_error', 'transport'), ('held', 'guard'),
        ('held', 'collector_validation'), ('held', 'collector_validation')]
    assert not report['active_complete']
    assert all(row['candidate_count'] is None for row in report['sources'][:4])
    assert 'SENSITIVE_SECRET' not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('code', ['source_http_403', 'publisher_http_403'])
def test_http_cause_keeps_only_status(no_real_io, monkeypatch, capsys, code):
    def preview(*_, **__):
        try:
            raise HTTPError('https://private.example/SECRET', 403, 'SECRET', {'Authorization': 'SECRET'}, None)
        except HTTPError as cause:
            raise audit.preview_worker.PreviewError(code) from cause

    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit(manifest=None)
    assert all(row['caused_by_http_status'] == 403 and row['outcome'] == 'transport_error'
               for row in report['sources'] if row['intended_active'])
    assert 'SECRET' not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('output,code', [
    ({}, 'snapshot_shape_missing'),
    ({'p_error': 'UNSAFE secret'}, 'source_audit_failed'),
    ({'p_error': None, 'p_source_key': 'wrong'}, 'snapshot_source_mismatch'),
    ({'p_error': None, 'p_events': None, 'p_future_count': 0}, 'snapshot_records_invalid'),
    ({'p_error': None, 'p_events': [], 'p_future_count': 5}, 'snapshot_count_invalid'),
    ({'p_error': None, 'p_events': [], 'p_future_count': True}, 'snapshot_count_invalid'),
    ({'p_error': None, 'p_events': [{}], 'p_future_count': 1}, 'snapshot_records_invalid'),
])
def test_invalid_or_partial_output_is_held(no_real_io, monkeypatch, output, code):
    def preview(source, **_):
        result = dict(output)
        if 'p_error' in result and 'p_source_key' not in result:
            result['p_source_key'] = source['source_key']
        return result

    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit(manifest=None)
    assert not report['active_complete']
    assert all(row['error'] == code and row['outcome'] == 'held'
               for row in report['sources'] if row['intended_active'])


def test_reported_count_is_preserved_when_worker_returns_a_bounded_subset():
    result = audit._snapshot(success({'source_key': 'sample'}, [event(1)], count=5), 'sample')
    assert result['candidate_count'] == 5 and result['returned_event_count'] == 1
    assert result['returned_events_truncated']


def test_overall_deadline_skips_remaining_sources_and_discards_late_result(no_real_io, monkeypatch):
    clock, calls = [0.0], []
    monkeypatch.setattr(audit, 'monotonic', lambda: clock[0])

    def preview(source, *, deadline_at):
        calls.append(deadline_at)
        clock[0] = 6
        return success(source, [event()])

    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    report = audit.audit(manifest=None, overall_seconds=5)
    assert calls == [5]
    active = [row for row in report['sources'] if row['intended_active']]
    assert active[0]['error'] == 'collection_deadline'
    assert all(row['error'] == 'overall_audit_deadline' and row['network_skipped'] for row in active[1:])
    assert all(row['candidate_count'] is None and row['samples'] == [] for row in active)
    assert report['counts']['attempted_sources'] == 1


def test_hard_timeout_is_reported_and_does_not_swallow_user_interrupt(no_real_io, monkeypatch):
    monkeypatch.setattr(audit.preview_worker, 'preview_source', Mock(side_effect=audit._SourceTimeout()))
    report = audit.audit(manifest=None)
    assert all(row['error'] == 'source_audit_timeout' for row in report['sources'] if row['intended_active'])
    monkeypatch.setattr(audit.preview_worker, 'preview_source', Mock(side_effect=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        audit.audit(manifest=None)


def test_posix_alarm_interrupts_broad_catch_and_restores_signal(monkeypatch):
    calls, handlers = [], []
    previous = object()
    monkeypatch.setattr(audit.signal, 'getitimer', lambda _: (0.0, 0.0))
    monkeypatch.setattr(audit.signal, 'getsignal', lambda _: previous)
    monkeypatch.setattr(audit.signal, 'signal', lambda signum, handler: handlers.append(handler))
    monkeypatch.setattr(audit.signal, 'setitimer', lambda timer, seconds: calls.append(seconds))
    with pytest.raises(audit._SourceTimeout):
        with audit._hard_timeout(12):
            try:
                handlers[0](audit.signal.SIGALRM, None)
            except Exception:
                pytest.fail('a broad collector handler must not consume the hard timeout')
    assert calls == [12, 0] and handlers[-1] is previous


@pytest.mark.parametrize('options', [
    {'per_source_seconds': 46}, {'overall_seconds': 1201}, {'overall_seconds': 0},
    {'per_source_seconds': -1}, {'per_source_seconds': float('nan')},
    {'overall_seconds': float('inf')}, {'overall_seconds': True},
])
def test_invalid_limits_fail_before_any_request(no_real_io, monkeypatch, options):
    preview = Mock()
    monkeypatch.setattr(audit.preview_worker, 'preview_source', preview)
    with pytest.raises(ValueError, match='audit_timeout_out_of_bounds'):
        audit.audit(manifest=None, **options)
    preview.assert_not_called()


@pytest.mark.parametrize('complete,exit_code', [(True, 0), (False, 1)])
def test_cli_writes_report_and_reports_live_completion(monkeypatch, tmp_path, complete, exit_code):
    report = {'read_only': True, 'active_complete': complete, 'sources': []}
    monkeypatch.setattr(audit, 'audit', lambda **_: report)
    path = tmp_path / 'report.json'
    assert audit.main(['--output', str(path)]) == exit_code
    assert json.loads(path.read_text()) == report
