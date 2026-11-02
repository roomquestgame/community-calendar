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


def test_staging_uses_small_transactions_and_completes_only_at_end():
    calls=[]
    def rpc(path, data, **kwargs):
        calls.append((path, deepcopy(data)))
        return len(data['p_events']) if 'p_events' in data else None
    with patch.object(w,'preview_source',return_value=output()), patch.object(w,'supabase_rpc',side_effect=rpc):
        result=w._process_claimed_source({'source_key':'fixture'})
    assert [len(data['p_events']) for _,data in calls[:-1]]==[20,20,5]
    assert calls[-1][0]=='community_collector_record_preview'
    assert calls[-1][1]['p_error'] is None
    assert result=={'complete':1,'failed':0,'staged':45}


def test_partial_staging_reports_infrastructure_failure_without_completion():
    with patch.object(w,'preview_source',return_value=output()), patch.object(w,'supabase_rpc',side_effect=[20,w.PreviewError('database_unavailable'),None]) as rpc:
        result=w._process_claimed_source({'source_key':'fixture'})
    assert result['failed']==1 and result['complete']==0
    assert rpc.call_args.args[0]=='community_collector_record_preview'
    assert rpc.call_args.args[1]['p_error']=='database_unavailable'
    assert rpc.call_count==3


def test_staging_deadline_is_not_a_parser_error():
    with patch.object(w,'preview_source',return_value=output()), patch.object(w,'monotonic',side_effect=[0,100]), patch.object(w,'supabase_rpc') as rpc:
        result=w._process_claimed_source({'source_key':'fixture'},deadline_at=40)
    assert result['failed']==1
    rpc.assert_called_once()
    assert rpc.call_args.args[1]['p_error']=='staging_deadline'


@pytest.mark.parametrize('error',[TimeoutError('private transport text'), OSError('private transport text')])
def test_rpc_socket_failures_are_classified_as_database_failures(error):
    env={'SUPABASE_URL':w.ROOMQUEST_DB,'SUPABASE_PUBLISHABLE_KEY':'fixture','ROOMQUEST_COLLECTOR_TOKEN':'a'*64}
    with patch.dict(w.os.environ,env),patch('urllib.request.urlopen',side_effect=error):
        with pytest.raises(w.PreviewError,match='^database_unavailable$'):
            w.supabase_rpc('community_collector_record_staged_events',{})


def test_category_never_publishes_partial_staging_and_finishes_ticket():
    calls=[]
    def rpc(path,data,**kwargs):
        calls.append((path,deepcopy(data)))
        if path=='community_collector_claim_category': return {'action':'collect','source_key':'fixture'}
        if path=='community_collector_record_staged_events': raise w.PreviewError('database_unavailable')
        return True
    with patch.object(category_worker,'supabase_rpc',side_effect=rpc),patch.object(w,'supabase_rpc',side_effect=rpc),patch.object(w,'preview_source',return_value=output()):
        result=category_worker.collect_category('wordpress','fixture-ticket')
    assert result['failed']==1
    assert not any(p=='community_collector_publish_category' for p,_ in calls)
    assert calls[-1][0]=='community_collector_finish_category'
    assert calls[-1][1]['p_outcome']=='failed'


def test_publisher_denial_remains_a_publisher_denial():
    with patch.object(w,'preview_source',side_effect=w.PreviewError('robots_denied')),patch.object(w,'supabase_rpc') as rpc:
        w._process_claimed_source({'source_key':'fixture'})
    assert rpc.call_args.args[1]['p_error']=='robots_denied'
