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
