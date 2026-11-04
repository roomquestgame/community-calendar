from unittest.mock import patch
import pytest
from roomquest import category_worker as w
from roomquest.preview_worker import PreviewError


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    from roomquest import preview_worker as preview

    class Clock:
        now = 100.0

        def __init__(self):
            self.waits = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.waits.append(seconds)
            self.now += seconds

    value = Clock()
    monkeypatch.setattr(w, 'monotonic', value.monotonic)
    monkeypatch.setattr(preview, 'monotonic', value.monotonic)
    monkeypatch.setattr(w, 'sleep', value.sleep)
    return value


@pytest.mark.parametrize('category', sorted(w.CATEGORIES))
def test_categories_claim_only_own_ticket(category):
    with patch.object(w, 'supabase_rpc', side_effect=[None, True]) as rpc:
        assert w.collect_category(category, 'ticket') == {'outcome': 'idle'}
        assert rpc.call_args_list[0].args == ('community_collector_claim_category', {'p_category': category, 'p_ticket': 'ticket'})

def test_collection_publishes_then_finishes():
    with patch.object(w, 'supabase_rpc', side_effect=[{'action':'collect'}, {'outcome':'continued'}, True]) as rpc, patch.object(w, '_process_claimed_source', return_value={'complete':1,'failed':0,'staged':100}) as process:
        result=w.collect_category('wordpress','ticket')
        assert result['publication']['outcome']=='continued'
        assert process.call_args.kwargs['deadline_at'] > 0
        assert rpc.call_args_list[-1].args[1]['p_outcome']=='complete'

def test_failed_snapshot_is_not_published():
    with patch.object(w, 'supabase_rpc', side_effect=[{'action':'collect'}, True]) as rpc, patch.object(w, '_process_claimed_source', return_value={'failed':1}):
        w.collect_category('ical','ticket')
        assert len(rpc.call_args_list)==2
        assert rpc.call_args_list[-1].args[1]['p_outcome']=='failed'


@pytest.mark.parametrize('code,kind', [
    ('event_schedule_missing', 'parse'),
    ('bellevue_times_listing_count_mismatch', 'parse'),
    ('robots_denied', 'access'),
    ('publisher_http_403', 'access'),
    ('non_public_dns', 'access'),
    ('publisher_http_429', 'transient'),
    ('publisher_http_503', 'transient'),
    ('robots_unavailable', 'transient'),
    ('dns_unavailable', 'transient'),
    ('source_network_error', 'transient'),
    ('collection_deadline', 'transient'),
    ('unregistered_html_calendar', 'configuration'),
])
def test_recorded_html_source_failure_releases_slot_without_publishing(code, kind):
    from roomquest import preview_worker as preview
    calls = []
    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'virginia_state_parks_nb',
                    'kind': 'html', 'platform_adapter': 'html'}
        return True
    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=PreviewError(code)):
        result = w.collect_category('html', 'ticket')
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    assert result['failure_scope'] == 'source' and result['error_kind'] == kind
    assert result['error_code'] == code
    assert [path for path, _ in calls] == [
        'community_collector_claim_category', 'community_collector_record_preview_v3',
        'community_collector_finish_category']
    assert calls[1][1]['p_error'] == code
    assert calls[-1][1]['p_outcome'] == 'source_error'


@pytest.mark.parametrize('category', ['ical', 'wordpress', 'jsonld', 'parks'])
def test_other_categories_keep_failed_outcome_for_source_failures(category):
    failure = {'complete': 0, 'failed': 1, 'staged': 0, 'failure_scope': 'source',
               'error_kind': 'access', 'error_code': 'robots_denied'}
    with patch.object(w, 'supabase_rpc', side_effect=[{'action': 'collect'}, True]) as rpc, \
            patch.object(w, '_process_claimed_source', return_value=failure):
        result = w.collect_category(category, 'ticket')
    assert result['failed'] == 1
    assert rpc.call_args_list[-1].args[1]['p_outcome'] == 'failed'


def test_failure_to_record_source_error_remains_a_worker_failure():
    from roomquest import preview_worker as preview
    calls = []
    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'virginia_state_parks_nb',
                    'kind': 'html', 'platform_adapter': 'html'}
        if path == 'community_collector_record_preview_v3':
            raise PreviewError('database_unavailable')
        return True
    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=PreviewError('event_schedule_missing')):
        with pytest.raises(PreviewError, match='database_unavailable'):
            w.collect_category('html', 'ticket')
    assert calls[-1][1]['p_outcome'] == 'failed'
    assert not any(path == 'community_collector_publish_category' for path, _ in calls)


def test_html_records_pacing_before_releasing_a_source_error_slot():
    from roomquest import preview_worker as preview
    from roomquest.publisher_pacing import observe_crawl_delay, observe_retry_after
    calls = []
    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'virginia_state_parks_nb',
                    'kind': 'html', 'platform_adapter': 'html'}
        return True
    def collect(*_args, **_kwargs):
        observe_crawl_delay(10)
        observe_retry_after('600')
        raise PreviewError('publisher_http_429')
    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=collect):
        result = w.collect_category('html', 'ticket')
    assert result['failure_scope'] == 'source' and result['error_kind'] == 'transient'
    assert calls[1][0] == 'community_collector_record_preview_v3'
    assert calls[1][1]['p_publisher_crawl_delay_seconds'] == 10
    assert calls[1][1]['p_publisher_retry_after_seconds'] == 600
    assert calls[1][1]['p_publisher_wait_unbounded'] is False
    assert calls[-1][1]['p_outcome'] == 'source_error'


def test_html_publication_rpc_failure_keeps_worker_recovery():
    with patch.object(w, 'supabase_rpc', side_effect=[
        {'action': 'publish'}, PreviewError('database_unavailable'), True]) as rpc:
        with pytest.raises(PreviewError, match='database_unavailable'):
            w.collect_category('html', 'ticket')
    assert rpc.call_args_list[-1].args[1]['p_outcome'] == 'failed'

def test_publication_continuation_does_not_refetch():
    with patch.object(w, 'supabase_rpc', side_effect=[{'action':'publish'}, {'outcome':'busy'}, True]) as rpc, patch.object(w, '_process_claimed_source') as process:
        w.collect_category('jsonld','ticket')
        process.assert_not_called()
        assert rpc.call_args_list[-1].args[1]['p_outcome']=='busy'

def test_failure_releases_ticket_for_bounded_retry():
    with patch.object(w, 'supabase_rpc', side_effect=[{'action':'publish'}, PreviewError('database_unavailable'), True]) as rpc:
        with pytest.raises(PreviewError): w.collect_category('squarespace','ticket')
        assert rpc.call_args_list[-1].args[1]['p_outcome']=='failed'

def test_unsupported_category_rejected_before_database():
    with patch.object(w, 'supabase_rpc') as rpc:
        with pytest.raises(PreviewError): w.collect_category('arbitrary','ticket')
        rpc.assert_not_called()

def test_http_rejects_untrusted_payload_before_claim():
    import importlib.util
    import io
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('category_endpoint', Path(__file__).parents[1]/'api/category_demand.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for payload in ({'category':'wordpress','ticket':'bad'}, {'category':'wordpress','ticket':'00000000-0000-0000-0000-000000000000','url':'https://example.org'}, [], {'category':[],'ticket':'x'}):
        raw=json.dumps(payload).encode()
        h=object.__new__(module.handler);h.path='/api/category-demand';h.headers={'Content-Length':str(len(raw))};h.rfile=io.BytesIO(raw)
        with patch.object(h,'reply') as reply, patch.object(module,'collect_category') as collect:
            h.do_POST();assert reply.call_args.args[0]==400;collect.assert_not_called()


@pytest.mark.parametrize('remaining', [0.036, 0.525])
@pytest.mark.parametrize('crawl_delay', [0, 1, 2])
def test_html_finishes_after_the_publisher_is_runnable(clock, remaining, crawl_delay):
    """A subsecond gap must not defer a ready host to minute recovery."""
    from roomquest import preview_worker as preview
    from roomquest.publisher_pacing import observe_crawl_delay
    calls, host_ready = [], []
    interval = max(1, crawl_delay)

    def rpc(path, data, **kwargs):
        calls.append((path, dict(data), clock.now))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'fixture',
                    'kind': 'html', 'platform_adapter': 'html'}
        if path == 'community_collector_record_staged_events':
            return 0
        if path == 'community_collector_record_preview_v2':
            # Model both the durable publisher wait and the independent
            # one-second recent-preview guard, using server record time.
            host_ready.append(clock.now + interval)
            assert data['p_publisher_crawl_delay_seconds'] == crawl_delay
            return None
        if path == 'community_collector_publish_category':
            clock.now += interval - remaining
            return {'outcome': 'complete'}
        assert path == 'community_collector_finish_category'
        assert clock.now >= host_ready[0]
        assert kwargs['timeout'] == 5
        return True

    def collect(*_args, **_kwargs):
        observe_crawl_delay(crawl_delay)
        return {'p_source_key': 'fixture', 'p_samples': [], 'p_future_count': 0,
                'p_venue_count': 0, 'p_error': None, 'p_events': []}

    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=collect):
        result = w.collect_category('html', 'ticket')

    assert clock.waits == pytest.approx([remaining])
    assert result == {'category': 'html', 'claimed': 1, 'complete': 1,
                      'failed': 0, 'staged': 0, 'publication': {'outcome': 'complete'}}
    assert [path for path, _, _ in calls] == [
        'community_collector_claim_category', 'community_collector_record_staged_events',
        'community_collector_record_preview_v2', 'community_collector_publish_category',
        'community_collector_finish_category']
    assert all('ready_at' not in data and 'publisher_handoff' not in data
               for _, data, _ in calls)


@pytest.mark.parametrize('recorded_wait,publication_seconds,expected_wait', [
    (1, 1.5, None),   # Publication already consumed the whole pause.
    (2, 0, 2),       # The full short-wait cap still fits the invocation.
    (3, 0, None),    # Never shorten a longer interval into the two-second cap.
    (60, 0.5, None),
    (3, 2.5, 0.5),   # Most of a longer pause may have elapsed during publication.
])
def test_html_waits_only_for_short_remaining_intervals(
        clock, recorded_wait, publication_seconds, expected_wait):
    def process(_source, *, publisher_handoff, **_kwargs):
        publisher_handoff['ready_at'] = clock.now + recorded_wait
        return {'complete': 1, 'failed': 0, 'staged': 0}

    def rpc(path, _data, **_kwargs):
        if path == 'community_collector_claim_category':
            return {'action': 'collect'}
        if path == 'community_collector_publish_category':
            clock.now += publication_seconds
            return {'outcome': 'complete'}
        return True

    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(w, '_process_claimed_source', side_effect=process):
        w.collect_category('html', 'ticket')
    assert clock.waits == ([] if expected_wait is None else [expected_wait])


def test_html_reserves_finish_and_response_budget_before_waiting(clock):
    calls = []

    def process(_source, *, publisher_handoff, **_kwargs):
        clock.now += 52
        publisher_handoff['ready_at'] = clock.now + 1
        return {'complete': 1, 'failed': 0, 'staged': 0}

    def rpc(path, data, **kwargs):
        calls.append((path, data, kwargs))
        if path == 'community_collector_claim_category':
            return {'action': 'collect'}
        return {'outcome': 'complete'}

    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(w, '_process_claimed_source', side_effect=process):
        w.collect_category('html', 'ticket')
    assert clock.waits == []
    assert calls[-1] == ('community_collector_finish_category',
                         {'p_category': 'html', 'p_ticket': 'ticket', 'p_outcome': 'complete'},
                         {'timeout': 5})


def test_recorded_source_error_handoff_keeps_error_outcome(clock):
    from roomquest import preview_worker as preview
    calls = []

    def rpc(path, data, **_kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'fixture',
                    'kind': 'html', 'platform_adapter': 'html'}
        return True

    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=PreviewError('event_schedule_missing')):
        result = w.collect_category('html', 'ticket')
    assert clock.waits == [1]
    assert result['failed'] == 1
    assert calls[-1][1]['p_outcome'] == 'source_error'
    assert not any(path == 'community_collector_publish_category' for path, _ in calls)


@pytest.mark.parametrize('publication_outcome', ['busy', 'idle'])
def test_html_busy_publication_keeps_existing_finish_behavior(clock, publication_outcome):
    def process(_source, *, publisher_handoff, **_kwargs):
        publisher_handoff['ready_at'] = clock.now + 1
        return {'complete': 1, 'failed': 0, 'staged': 0}

    with patch.object(w, 'supabase_rpc', side_effect=[
            {'action': 'collect'}, {'outcome': publication_outcome}, True]) as rpc, \
            patch.object(w, '_process_claimed_source', side_effect=process):
        w.collect_category('html', 'ticket')
    assert clock.waits == []
    assert rpc.call_args.args[1]['p_outcome'] == 'busy'


def test_html_publication_failure_does_not_wait_and_finishes_once(clock):
    def process(_source, *, publisher_handoff, **_kwargs):
        publisher_handoff['ready_at'] = clock.now + 1
        return {'complete': 1, 'failed': 0, 'staged': 0}

    with patch.object(w, 'supabase_rpc', side_effect=[
            {'action': 'collect'}, PreviewError('database_unavailable'), True]) as rpc, \
            patch.object(w, '_process_claimed_source', side_effect=process):
        with pytest.raises(PreviewError, match='database_unavailable'):
            w.collect_category('html', 'ticket')
    assert clock.waits == []
    assert sum(call.args[0] == 'community_collector_finish_category'
               for call in rpc.call_args_list) == 1
    assert rpc.call_args.args[1]['p_outcome'] == 'failed'


def test_interrupted_html_wait_still_finishes_once(clock):
    def process(_source, *, publisher_handoff, **_kwargs):
        publisher_handoff['ready_at'] = clock.now + 1
        return {'complete': 1, 'failed': 0, 'staged': 0}

    with patch.object(w, 'supabase_rpc', side_effect=[
            {'action': 'collect'}, {'outcome': 'complete'}, True]) as rpc, \
            patch.object(w, '_process_claimed_source', side_effect=process), \
            patch.object(w, 'sleep', side_effect=RuntimeError('interrupted')):
        with pytest.raises(RuntimeError, match='interrupted'):
            w.collect_category('html', 'ticket')
    assert sum(call.args[0] == 'community_collector_finish_category'
               for call in rpc.call_args_list) == 1


@pytest.mark.parametrize('category', ['html', 'wordpress'])
def test_publish_continuation_has_no_collection_handoff(clock, category):
    with patch.object(w, 'supabase_rpc', side_effect=[
            {'action': 'publish'}, {'outcome': 'continued'}, True]) as rpc, \
            patch.object(w, '_process_claimed_source') as process:
        w.collect_category(category, 'ticket')
    process.assert_not_called()
    assert clock.waits == []
    assert rpc.call_args.args[1]['p_outcome'] == 'complete'


def diagnostic_records(caplog):
    import json
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == 'roomquest.category_worker']


@pytest.mark.parametrize('phase,operation,escapes', [
    ('claim', 'community_collector_claim_category', True),
    ('stage', 'community_collector_record_staged_events', False),
    ('record', 'community_collector_record_preview', True),
    ('publish', 'community_collector_publish_category', True),
    ('finish', 'community_collector_finish_category', True),
])
def test_rpc_failure_diagnostics_identify_phase_without_changing_outcome(caplog, phase, operation, escapes):
    from roomquest import preview_worker as preview
    from urllib.error import HTTPError
    error = PreviewError('database_unavailable')
    error.__cause__ = HTTPError('https://private.invalid/?token=private-token', 400,
                                'private response text', {'Authorization': 'private-header'}, None)
    calls = []

    def rpc(path, data, **kwargs):
        calls.append((path, data, kwargs))
        if path == operation:
            raise error
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_id': 4900, 'source_key': 'private-source-key',
                    'feed_url': 'https://private.invalid/', 'kind': 'json', 'platform_adapter': 'wordpress'}
        if path == 'community_collector_record_staged_events':
            return 1
        if path == 'community_collector_publish_category':
            return {'outcome': 'completed', 'published': 1}
        return True

    output = {'p_source_key': 'private-source-key', 'p_samples': [], 'p_future_count': 1,
              'p_venue_count': 0, 'p_error': None, 'p_events': [{'id': 'private-event'}]}
    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', return_value=output):
        if escapes:
            with pytest.raises(PreviewError) as caught:
                w.collect_category('wordpress', 'private-ticket')
            assert caught.value is error
        else:
            result = w.collect_category('wordpress', 'private-ticket')
            assert result == {'category': 'wordpress', 'claimed': 1, 'complete': 0, 'failed': 1,
                              'staged': 0, 'failure_scope': 'worker', 'error_kind': 'infrastructure',
                              'error_code': 'database_unavailable'}
    records = diagnostic_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record['phase'] == phase and record['rpc_operation'] == operation
    assert record['category'] == 'wordpress'
    assert record['error_code'] == 'database_unavailable' and record['error_type'] == 'PreviewError'
    assert record['cause_type'] == 'HTTPError' and record['upstream_http_status'] == 400
    assert record['failure_scope'] == 'worker' and record['error_kind'] == 'infrastructure'
    assert 0 <= record['elapsed_ms'] <= 120000
    if phase == 'claim':
        assert 'source_id' not in record
    else:
        assert record['source_id'] == 4900
    assert 'private' not in caplog.text and 'https://' not in caplog.text
    assert all(entry.exc_info is None for entry in caplog.records)
    if phase == 'claim':
        assert len(calls) == 1  # No unowned ticket finish was added.
    else:
        assert calls[-1][0] == 'community_collector_finish_category'
        assert calls[-1][1]['p_outcome'] == ('complete' if phase == 'finish' else 'failed')
    if phase in ('claim', 'stage', 'record'):
        assert not any(path == 'community_collector_publish_category' for path, _, _ in calls)


def test_recorded_source_failure_keeps_its_fetch_diagnostic_and_200_result(caplog):
    from roomquest import preview_worker as preview
    calls = []

    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'fixture', 'source_id': 5003,
                    'kind': 'html', 'platform_adapter': 'html'}
        return True

    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=PreviewError('robots_denied')):
        result = w.collect_category('html', 'private-ticket')
    assert result == {'category': 'html', 'claimed': 1, 'complete': 0, 'failed': 1,
                      'staged': 0, 'failure_scope': 'source', 'error_kind': 'access',
                      'error_code': 'robots_denied'}
    records = diagnostic_records(caplog)
    assert len(records) == 1 and records[0]['phase'] == 'fetch'
    assert records[0]['source_id'] == 5003 and records[0]['error_code'] == 'robots_denied'
    assert 'rpc_operation' not in records[0]
    assert [path for path, _ in calls] == ['community_collector_claim_category',
        'community_collector_record_preview_v2', 'community_collector_finish_category']
    assert calls[-1][1]['p_outcome'] == 'source_error'


def test_record_and_cleanup_failures_cannot_erase_primary_fetch_evidence(caplog):
    from roomquest import preview_worker as preview
    cleanup = RuntimeError('private cleanup detail')
    calls = []

    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_key': 'fixture', 'source_id': 4900}
        if path == 'community_collector_record_preview':
            raise PreviewError('database_unavailable')
        if path == 'community_collector_finish_category':
            raise cleanup
        return True

    with patch.object(w, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview, 'preview_source', side_effect=PreviewError('robots_denied')):
        with pytest.raises(RuntimeError) as caught:
            w.collect_category('wordpress', 'private-ticket')
    assert caught.value is cleanup  # Existing finally/exception behavior is unchanged.
    records = diagnostic_records(caplog)
    assert [record['phase'] for record in records] == ['fetch', 'record', 'finish']
    assert [record['error_code'] for record in records] == [
        'robots_denied', 'database_unavailable', 'unexpected_error']
    assert all(record['source_id'] == 4900 for record in records)
    assert calls[-1][1]['p_outcome'] == 'failed'
    assert 'private' not in caplog.text and all(entry.exc_info is None for entry in caplog.records)


@pytest.mark.parametrize('identity', [None, True, 0, -1, '4900', 9223372036854775808])
def test_old_or_malformed_claim_identity_is_not_logged(caplog, identity):
    source = {'action': 'publish', 'source_id': identity, 'source_key': 'private-source',
              'feed_url': 'https://private.invalid/?token=private-token'}
    with patch.object(w, 'supabase_rpc', side_effect=[source, PreviewError('database_unavailable'), True]):
        with pytest.raises(PreviewError):
            w.collect_category('wordpress', 'private-ticket')
    records = diagnostic_records(caplog)
    assert len(records) == 1 and 'source_id' not in records[0]
    assert 'private' not in caplog.text


def test_separate_invocations_do_not_share_source_or_error_context(caplog):
    with patch.object(w, 'supabase_rpc', side_effect=[
        {'action': 'publish', 'source_id': 4900}, PreviewError('database_unavailable'), True,
        {'action': 'publish', 'source_id': 5004}, TypeError('private event data'), True]):
        with pytest.raises(PreviewError):
            w.collect_category('wordpress', 'first-private-ticket')
        with pytest.raises(TypeError):
            w.collect_category('html', 'second-private-ticket')
    records = diagnostic_records(caplog)
    assert [(row['category'], row['source_id'], row['error_type']) for row in records] == [
        ('wordpress', 4900, 'PreviewError'), ('html', 5004, 'TypeError')]
    assert 'private' not in caplog.text


def test_logging_failure_does_not_change_error_or_prevent_finish():
    error = PreviewError('database_unavailable')
    with patch.object(w, 'supabase_rpc', side_effect=[{'action': 'publish'}, error, True]) as rpc, \
            patch.object(w._LOGGER, 'warning', side_effect=RuntimeError('logger unavailable')):
        with pytest.raises(PreviewError) as caught:
            w.collect_category('wordpress', 'private-ticket')
    assert caught.value is error
    assert rpc.call_args_list[-1].args == ('community_collector_finish_category',
        {'p_category': 'wordpress', 'p_ticket': 'private-ticket', 'p_outcome': 'failed'})


@pytest.mark.parametrize('finish_fails', [False, True])
def test_interrupted_handoff_diagnostic_preserves_finish_once(clock, caplog, finish_fails):
    interrupted = RuntimeError('private interrupted handoff detail')
    finish_error = PreviewError('database_unavailable')

    def process(_source, *, publisher_handoff, observe_phase, **_kwargs):
        observe_phase('record', operation='community_collector_record_preview_v2')
        publisher_handoff['ready_at'] = clock.now + 1
        return {'complete': 1, 'failed': 0, 'staged': 0}

    with patch.object(w, 'supabase_rpc', side_effect=[
            {'action': 'collect', 'source_id': 4900}, {'outcome': 'complete'},
            finish_error if finish_fails else True]) as rpc, \
            patch.object(w, '_process_claimed_source', side_effect=process), \
            patch.object(w, 'sleep', side_effect=interrupted):
        with pytest.raises(PreviewError if finish_fails else RuntimeError) as caught:
            w.collect_category('html', 'private-ticket')
    assert caught.value is (finish_error if finish_fails else interrupted)
    assert sum(call.args[0] == 'community_collector_finish_category'
               for call in rpc.call_args_list) == 1
    assert rpc.call_args.args[1]['p_outcome'] == 'complete'
    records = diagnostic_records(caplog)
    assert len(records) == (2 if finish_fails else 1)
    assert records[0]['phase'] == 'finish' and 'rpc_operation' not in records[0]
    assert records[0]['error_type'] == 'RuntimeError'
    if finish_fails:
        assert records[1]['phase'] == 'finish'
        assert records[1]['rpc_operation'] == 'community_collector_finish_category'
        assert records[1]['error_code'] == 'database_unavailable'
    assert all(row['source_id'] == 4900 for row in records)
    assert 'private' not in caplog.text
