"""Infrastructure errors must remain retryable and partial snapshots unpublished."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from roomquest import preview_worker as w
from roomquest import category_worker


def output(count=45):
    return {'p_source_key':'fixture', 'p_samples':[], 'p_future_count':count,
            'p_venue_count':0, 'p_error':None,
            'p_events':[{'id':str(i), 'title':'Fixture'} for i in range(count)]}


@pytest.mark.parametrize('count,expected_batches', [(45, [20, 20, 5]), (28, [20, 8])])
def test_staging_uses_small_transactions_and_completes_only_at_end(count, expected_batches):
    calls=[]
    def rpc(path, data, **kwargs):
        calls.append((path, deepcopy(data)))
        return len(data['p_events']) if 'p_events' in data else None
    with patch.object(w,'preview_source',return_value=output(count)), patch.object(w,'supabase_rpc',side_effect=rpc):
        result=w._process_claimed_source({'source_key':'fixture'})
    assert [len(data['p_events']) for _,data in calls[:-1]]==expected_batches
    assert calls[-1][0]=='community_collector_record_preview'
    assert calls[-1][1]['p_error'] is None
    assert result=={'complete':1,'failed':0,'staged':count}


def test_partial_staging_reports_infrastructure_failure_without_completion():
    with patch.object(w,'preview_source',return_value=output()), patch.object(w,'supabase_rpc',side_effect=[20,w.PreviewError('database_unavailable'),None]) as rpc:
        result=w._process_claimed_source({'source_key':'fixture'})
    assert result['failed']==1 and result['complete']==0
    assert result['failure_scope']=='worker' and result['error_kind']=='infrastructure'
    assert result['error_code']=='database_unavailable'
    assert rpc.call_args.args[0]=='community_collector_record_preview'
    assert rpc.call_args.args[1]['p_error']=='database_unavailable'
    assert rpc.call_count==3


def test_staging_deadline_is_not_a_parser_error():
    with patch.object(w,'preview_source',return_value=output()), patch.object(w,'monotonic',side_effect=[0,100]), patch.object(w,'supabase_rpc') as rpc:
        result=w._process_claimed_source({'source_key':'fixture'},deadline_at=40)
    assert result['failed']==1
    assert result['failure_scope']=='worker' and result['error_code']=='staging_deadline'
    rpc.assert_called_once()
    assert rpc.call_args.args[1]['p_error']=='staging_deadline'


@pytest.mark.parametrize('error',[TimeoutError('private transport text'), OSError('private transport text')])
def test_rpc_socket_failures_are_classified_as_database_failures(error):
    env={'SUPABASE_URL':w.ROOMQUEST_DB,'SUPABASE_PUBLISHABLE_KEY':'fixture','ROOMQUEST_COLLECTOR_TOKEN':'a'*64}
    with patch.dict(w.os.environ,env),patch('urllib.request.urlopen',side_effect=error):
        with pytest.raises(w.PreviewError,match='^database_unavailable$'):
            w.supabase_rpc('community_collector_record_staged_events',{})


@pytest.mark.parametrize('category', ['wordpress', 'html'])
def test_category_never_publishes_partial_staging_and_finishes_ticket(category):
    calls=[]
    def rpc(path,data,**kwargs):
        calls.append((path,deepcopy(data)))
        if path=='community_collector_claim_category': return {'action':'collect','source_key':'fixture'}
        if path=='community_collector_record_staged_events': raise w.PreviewError('database_unavailable')
        return True
    with patch.object(category_worker,'supabase_rpc',side_effect=rpc),patch.object(w,'supabase_rpc',side_effect=rpc),patch.object(w,'preview_source',return_value=output()):
        result=category_worker.collect_category(category,'fixture-ticket')
    assert result['failed']==1
    assert result['failure_scope']=='worker' and result['error_kind']=='infrastructure'
    assert not any(p=='community_collector_publish_category' for p,_ in calls)
    assert calls[-1][0]=='community_collector_finish_category'
    assert calls[-1][1]['p_outcome']=='failed'


def test_publisher_denial_remains_a_publisher_denial():
    with patch.object(w,'preview_source',side_effect=w.PreviewError('robots_denied')),patch.object(w,'supabase_rpc') as rpc:
        w._process_claimed_source({'source_key':'fixture'})
    assert rpc.call_args.args[1]['p_error']=='robots_denied'


def test_unexpected_local_failure_is_not_reclassified_as_publisher_success():
    with patch.object(w, 'preview_source', side_effect=OSError('private path or socket text')), \
            patch.object(w, 'supabase_rpc') as rpc:
        result = w._process_claimed_source({'source_key': 'fixture'})
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    assert result['failure_scope'] == 'worker' and result['error_kind'] == 'unexpected'
    assert result['error_code'] == 'source_parse_error'
    assert 'private' not in repr(result)
    assert rpc.call_args.args[1]['p_error'] == 'source_parse_error'


def test_html_success_persists_pacing_atomically_with_preview_and_no_legacy_rpc():
    from roomquest.publisher_pacing import observe_crawl_delay, observe_retry_after
    source = {'source_key': 'fixture', 'kind': 'html', 'platform_adapter': 'html'}
    def collect(*_args, **_kwargs):
        observe_crawl_delay(2.1)
        observe_retry_after('60')
        return output(1)
    with patch.object(w, 'preview_source', side_effect=collect), patch.object(w, 'supabase_rpc', side_effect=[1, None]) as rpc:
        result = w._process_claimed_source(source)
    assert result == {'complete': 1, 'failed': 0, 'staged': 1}
    assert rpc.call_args.args[0] == 'community_collector_record_preview_v2'
    payload = rpc.call_args.args[1]
    assert payload['p_error'] is None
    assert payload['p_publisher_crawl_delay_seconds'] == 3
    assert payload['p_publisher_retry_after_seconds'] == 60
    assert payload['p_publisher_wait_unbounded'] is False


def test_unbounded_wait_is_review_failure_before_staging_even_if_parser_returned_records():
    from roomquest.publisher_pacing import observe_retry_after
    source = {'source_key': 'fixture', 'kind': 'html', 'platform_adapter': 'html'}
    def collect(*_args, **_kwargs):
        observe_retry_after('86401')
        return output(28)
    with patch.object(w, 'preview_source', side_effect=collect), patch.object(w, 'supabase_rpc') as rpc:
        result = w._process_claimed_source(source)
    assert result['complete'] == 0 and result['failed'] == 1 and result['staged'] == 0
    assert result['failure_scope'] == 'source' and result['error_code'] == 'publisher_wait_requires_review'
    rpc.assert_called_once()
    assert rpc.call_args.args[0] == 'community_collector_record_preview_v2'
    payload = rpc.call_args.args[1]
    assert payload['p_error'] == 'publisher_wait_requires_review'
    assert payload['p_publisher_crawl_delay_seconds'] == payload['p_publisher_retry_after_seconds'] == 0
    assert payload['p_publisher_wait_unbounded'] is True


def test_separate_collection_does_not_inherit_another_publishers_wait():
    from roomquest.publisher_pacing import observe_retry_after
    source = {'source_key': 'fixture', 'kind': 'html', 'platform_adapter': 'html'}
    def first(*_args, **_kwargs):
        observe_retry_after('600')
        raise w.PreviewError('publisher_http_429')
    with patch.object(w, 'preview_source', side_effect=first), patch.object(w, 'supabase_rpc') as rpc:
        w._process_claimed_source(source)
    assert rpc.call_args.args[1]['p_publisher_retry_after_seconds'] == 600
    with patch.object(w, 'preview_source', return_value=output(0)), patch.object(w, 'supabase_rpc') as rpc:
        w._process_claimed_source(source)
    assert rpc.call_args.args[1]['p_publisher_retry_after_seconds'] == 0
    assert rpc.call_args.args[1]['p_publisher_wait_unbounded'] is False
