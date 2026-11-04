from unittest.mock import patch
import pytest
from roomquest import category_worker as w
from roomquest.preview_worker import PreviewError

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
        'community_collector_claim_category', 'community_collector_record_preview_v2',
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
        if path == 'community_collector_record_preview_v2':
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
    assert calls[1][0] == 'community_collector_record_preview_v2'
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
