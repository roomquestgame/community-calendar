from unittest.mock import Mock, patch
from io import BytesIO
import os
from api.provider_pilot import handler
from roomquest import provider_pilot as p


def request(headers=None, path='/api/provider-pilot'):
    h=handler.__new__(handler)
    h.headers=headers or {};h.path=path;h.wfile=BytesIO()
    h.send_response=Mock();h.send_header=Mock();h.end_headers=Mock()
    return h


def test_manual_endpoint_rejects_missing_or_wrong_auth_and_get():
    with patch.dict(os.environ, {'ROOMQUEST_PREVIEW_SECRET':'fixture'}), patch('api.provider_pilot.collect_pilot') as collect:
        for headers in ({},{'Authorization':'Bearer wrong'}):
            h=request(headers);h.do_POST();h.send_response.assert_called_once_with(401)
        h=request();h.do_GET();h.send_response.assert_called_once_with(404)
        collect.assert_not_called()


def test_manual_endpoint_refuses_body_or_arbitrary_path():
    with patch.dict(os.environ, {'ROOMQUEST_PREVIEW_SECRET':'fixture'}), patch('api.provider_pilot.collect_pilot') as collect:
        for headers in ({'Content-Length':'2'},{'Transfer-Encoding':'chunked'}):
            h=request({'Authorization':'Bearer fixture',**headers});h.do_POST();h.send_response.assert_called_once_with(400)
        h=request({'Authorization':'Bearer fixture'},'/api/other');h.do_POST();h.send_response.assert_called_once_with(404)
        collect.assert_not_called()


def test_batch_uses_only_three_reviewed_sources_and_shared_deadline():
    with patch.object(p,'_process_claimed_source',return_value={'complete':1,'failed':0,'staged':2}) as process:
        result=p.collect_pilot()
    assert result['complete']==3 and result['staged']==6
    assert process.call_count==3
    calls=process.call_args_list
    assert {c.args[0]['feed_url'] for c in calls}=={
        'https://business.orangeburgchamber.com/api/events',
        'https://fraziermuseum.org/calendar?format=json',
        'https://missiongarden.org/events?format=json'}
    assert len({c.kwargs['deadline_at'] for c in calls})==1
