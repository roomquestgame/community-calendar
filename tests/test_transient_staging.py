"""Infrastructure errors must remain retryable and partial snapshots unpublished."""
from copy import deepcopy
from unittest.mock import Mock, patch
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


@pytest.mark.parametrize('crawl_delay,retry_after,wait', [(0, None, 1), (2.1, None, 3), (1, '60', 60)])
def test_html_handoff_starts_only_after_pacing_is_persisted(crawl_delay, retry_after, wait):
    from roomquest.publisher_pacing import observe_crawl_delay, observe_retry_after
    source = {'source_key': 'fixture', 'kind': 'html', 'platform_adapter': 'html'}
    clock, handoff = [100.0], {}

    def collect(*_args, **_kwargs):
        observe_crawl_delay(crawl_delay)
        observe_retry_after(retry_after)
        return output(0)

    def rpc(path, data, **_kwargs):
        assert handoff == {}
        assert 'publisher_handoff' not in data and 'ready_at' not in data
        if path == 'community_collector_record_preview_v2':
            clock[0] = 103.0  # Recording and its response consumed time.
        return 0

    with patch.object(w, 'monotonic', side_effect=lambda: clock[0]), \
            patch.object(w, 'preview_source', side_effect=collect), \
            patch.object(w, 'supabase_rpc', side_effect=rpc):
        result = w._process_claimed_source(source, publisher_handoff=handoff)
    assert handoff == {'ready_at': 103.0 + wait}
    assert result == {'complete': 1, 'failed': 0, 'staged': 0}


def test_failed_pacing_record_cannot_supply_a_handoff():
    source = {'source_key': 'fixture', 'kind': 'html', 'platform_adapter': 'html'}
    handoff = {}
    with patch.object(w, 'preview_source', return_value=output(0)), \
            patch.object(w, 'supabase_rpc', side_effect=[0, w.PreviewError('database_unavailable')]):
        with pytest.raises(w.PreviewError, match='database_unavailable'):
            w._process_claimed_source(source, publisher_handoff=handoff)
    assert handoff == {}


def test_unbounded_publisher_wait_has_no_short_handoff():
    from roomquest.publisher_pacing import observe_retry_after
    source = {'source_key': 'fixture', 'kind': 'html', 'platform_adapter': 'html'}
    handoff = {}

    def collect(*_args, **_kwargs):
        observe_retry_after('86401')
        return output(0)

    with patch.object(w, 'preview_source', side_effect=collect), \
            patch.object(w, 'supabase_rpc') as rpc:
        result = w._process_claimed_source(source, publisher_handoff=handoff)
    assert handoff == {}
    assert result['failed'] == 1 and result['error_code'] == 'publisher_wait_requires_review'
    assert rpc.call_args.args[1]['p_publisher_wait_unbounded'] is True


def test_non_html_preview_does_not_create_a_publisher_handoff():
    handoff = {}
    with patch.object(w, 'preview_source', return_value=output(0)), \
            patch.object(w, 'supabase_rpc', return_value=0) as rpc:
        result = w._process_claimed_source({'source_key': 'fixture'}, publisher_handoff=handoff)
    assert handoff == {}
    assert result == {'complete': 1, 'failed': 0, 'staged': 0}
    assert rpc.call_args.args[0] == 'community_collector_record_preview'


def test_optional_phase_observer_distinguishes_fetch_stage_and_record():
    phases = []
    with patch.object(w, 'preview_source', return_value=output(1)), \
            patch.object(w, 'supabase_rpc', side_effect=[1, None]):
        result = w._process_claimed_source({'source_key': 'fixture'},
            observe_phase=lambda phase, **details: phases.append((phase, details)))
    assert result == {'complete': 1, 'failed': 0, 'staged': 1}
    assert phases[0] == ('fetch', {'operation': None, 'error': None})
    assert ('stage', {'operation': 'community_collector_record_staged_events', 'error': None}) in phases
    assert phases[-1] == ('record', {'operation': 'community_collector_record_preview', 'error': None})


@pytest.mark.parametrize('source_error', [None, w.PreviewError('robots_denied')])
def test_broken_observer_cannot_change_staging_or_recorded_source_outcome(source_error):
    observer = Mock(side_effect=RuntimeError('diagnostic sink failure'))
    with patch.object(w, 'preview_source', return_value=output(1), side_effect=source_error), \
            patch.object(w, 'supabase_rpc', side_effect=[1, None] if source_error is None else [None]) as rpc:
        result = w._process_claimed_source({'source_key': 'fixture'}, observe_phase=observer)
    assert result['complete'] == int(source_error is None)
    assert result['failed'] == int(source_error is not None)
    assert rpc.call_args.args[0] == 'community_collector_record_preview'
    assert rpc.call_args.args[1]['p_error'] == (None if source_error is None else 'robots_denied')
    observer.assert_called()
