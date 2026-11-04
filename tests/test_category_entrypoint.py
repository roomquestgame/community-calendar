"""Production uses the central Python entrypoint, not just file routes."""
import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch
import pytest
from roomquest.preview_worker import PreviewError


def test_central_entrypoint_dispatches_category_get_and_post():
    modules = {}
    for name in ('geocode', 'preview', 'chambermaster', 'provider_pilot', 'category_demand', 'html_demand'):
        module = ModuleType('api.'+name)
        module.handler = type(name+'Handler', (), {'do_GET': Mock(), 'do_POST': Mock()})
        modules[module.__name__] = module
    spec = importlib.util.spec_from_file_location('category_index_test', Path(__file__).parents[1]/'api/index.py')
    entry = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', modules):
        spec.loader.exec_module(entry)
    h=object.__new__(entry.handler);h.path='/api/category-demand'
    h.do_GET();h.do_POST()
    modules['api.category_demand'].handler.do_GET.assert_called_once_with(h)
    modules['api.category_demand'].handler.do_POST.assert_called_once_with(h)
    modules['api.preview'].handler.do_POST.assert_not_called()
    h.path='/api/html-demand';h.do_GET();h.do_POST()
    modules['api.html_demand'].handler.do_GET.assert_called_once_with(h)
    modules['api.html_demand'].handler.do_POST.assert_called_once_with(h)
    modules['api.category_demand'].handler.do_POST.assert_called_once_with(h)
    modules['api.preview'].handler.do_POST.assert_not_called()
    h.path='/api/demand-preview';h.do_POST()
    modules['api.preview'].handler.do_POST.assert_called_once_with(h)


def category_request():
    from api import category_demand
    payload = {'category': 'wordpress', 'ticket': '00000000-0000-0000-0000-000000000000'}
    raw = json.dumps(payload).encode()
    h = object.__new__(category_demand.handler)
    h.path = '/api/category-demand'
    h.headers = {'Content-Length': str(len(raw)), 'Authorization': 'private-header'}
    h.rfile = io.BytesIO(raw)
    return category_demand, h, payload


@pytest.mark.parametrize('error,body,code,family', [
    (PreviewError('database_unavailable'),
     'collector_unavailable', 'database_unavailable', 'PreviewError'),
    (PreviewError('secret_token_abc123'),
     'collector_unavailable', 'unclassified_preview_error', 'PreviewError'),
    (PreviewError(
        'private-token https://private.invalid/ Authorization: private-header user=private-user'),
     'collector_unavailable', 'unclassified_preview_error', 'PreviewError'),
    (RuntimeError('private-token https://private.invalid/ private-user'),
     'collector_failed', 'unexpected_error', 'RuntimeError'),
    (type('private_custom_exception_name', (Exception,), {})('private exception body'),
     'collector_failed', 'unexpected_error', 'Exception'),
])
def test_http_failure_status_body_and_safe_fallback_diagnostics(caplog, error, body, code, family):
    module, h, payload = category_request()
    with patch.object(h, 'reply') as reply, patch.object(module, 'collect_category', side_effect=error):
        h.do_POST()
    reply.assert_called_once_with(503, {'error': body})
    records = [json.loads(record.getMessage()) for record in caplog.records
               if record.name == 'roomquest.category_worker']
    assert len(records) == 1
    assert records[0]['phase'] == 'dispatch' and records[0]['category'] == 'wordpress'
    assert records[0]['error_code'] == code and records[0]['error_type'] == family
    assert 'source_id' not in records[0] and len(caplog.records[0].getMessage()) < 1024
    for private in ('private', 'secret_token_abc123', payload['ticket'], 'https://', 'Authorization'):
        assert private not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_real_worker_failure_is_logged_once_with_its_phase(caplog):
    from roomquest import category_worker
    module, h, _ = category_request()
    error = PreviewError('database_unavailable')
    with patch.object(h, 'reply') as reply, \
            patch.object(category_worker, 'supabase_rpc', side_effect=error) as rpc:
        h.do_POST()
    reply.assert_called_once_with(503, {'error': 'collector_unavailable'})
    rpc.assert_called_once()
    records = [json.loads(record.getMessage()) for record in caplog.records
               if record.name == 'roomquest.category_worker']
    assert len(records) == 1 and records[0]['phase'] == 'claim'
    assert records[0]['rpc_operation'] == 'community_collector_claim_category'


def test_record_http_400_remains_503_with_safe_record_phase_evidence(caplog):
    from roomquest import category_worker, preview_worker
    from urllib.error import HTTPError
    _, h, _ = category_request()
    error = PreviewError('database_unavailable')
    error.__cause__ = HTTPError('https://private.invalid/rpc?token=private-token', 400,
                                'private server error', {'Authorization': 'private-header'}, None)
    calls = []

    def rpc(path, data, **kwargs):
        calls.append((path, data))
        if path == 'community_collector_claim_category':
            return {'action': 'collect', 'source_id': 4900, 'source_key': 'fixture'}
        if path == 'community_collector_record_preview':
            raise error
        return 0 if path == 'community_collector_record_staged_events' else True

    output = {'p_source_key': 'fixture', 'p_samples': [], 'p_future_count': 0,
              'p_venue_count': 0, 'p_error': None, 'p_events': []}
    with patch.object(h, 'reply') as reply, \
            patch.object(category_worker, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview_worker, 'supabase_rpc', side_effect=rpc), \
            patch.object(preview_worker, 'preview_source', return_value=output):
        h.do_POST()
    reply.assert_called_once_with(503, {'error': 'collector_unavailable'})
    records = [json.loads(record.getMessage()) for record in caplog.records
               if record.name == 'roomquest.category_worker']
    assert len(records) == 1
    assert records[0]['phase'] == 'record' and records[0]['source_id'] == 4900
    assert records[0]['rpc_operation'] == 'community_collector_record_preview'
    assert records[0]['upstream_http_status'] == 400 and records[0]['error_code'] == 'database_unavailable'
    assert calls[-1][0] == 'community_collector_finish_category' and calls[-1][1]['p_outcome'] == 'failed'
    assert not any(path == 'community_collector_publish_category' for path, _ in calls)
    assert 'private' not in caplog.text and all(record.exc_info is None for record in caplog.records)


def test_successful_idle_request_keeps_response_and_does_not_emit_failure(caplog):
    from roomquest import category_worker
    _, h, _ = category_request()
    with patch.object(h, 'reply') as reply, \
            patch.object(category_worker, 'supabase_rpc', side_effect=[None, True]) as rpc:
        h.do_POST()
    reply.assert_called_once_with(200, {'outcome': 'idle'})
    assert len(rpc.call_args_list) == 2
    assert not [record for record in caplog.records if record.name == 'roomquest.category_worker']
