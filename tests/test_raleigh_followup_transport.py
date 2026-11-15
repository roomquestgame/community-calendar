"""The two new anonymous display transports keep all shared access guards."""
import base64
import json
from unittest.mock import Mock, patch

import pytest

from roomquest import preview_worker as w
from roomquest import raleigh_followup_performance as p


def instance():
    data = dict(instanceId=p.WIX_INSTANCE_ID, appDefId=p.WIX_APP_ID,
        metaSiteId=p.WIX_METASITE_ID, demoMode=False)
    return 'S'*43 + '.' + base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')


def response(status=200, **headers):
    result = Mock(status_code=status, encoding='utf-8')
    result.headers = {'Content-Type': 'application/json', **headers}
    result.iter_content.return_value = [b'{"events":[]}']
    return result


def network(reply, allowed=True):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = reply
    session.post.return_value = reply
    return session, [patch.object(w.requests, 'Session', return_value=session),
        patch.object(w, 'validate_public_dns'), patch.object(w, 'robots_allowed', return_value=allowed),
        patch.object(w, 'pace_publisher')]


def read(kind):
    return w.read_raleigh_followup_events(request_kind=kind, **(
        {'offset':18, 'public_instance':instance()} if kind == 'comedyworx_page' else {'page':1}))


@pytest.mark.parametrize('kind,host,method', [('chapel_bootstrap','www.tickpick.com','post'),
    ('chapel_page','www.tickpick.com','post'), ('comedyworx_page','www.comedyworx.com','get')])
def test_exact_display_reads_retain_robots_dns_pacing_and_ordinary_identity(kind,host,method):
    session, patches = network(response())
    with patches[0], patches[1] as dns, patches[2] as robots, patches[3] as pace:
        assert read(kind) == '{"events":[]}'
    dns.assert_called_once_with(host)
    robots.assert_called_once()
    pace.assert_called_once()
    assert session.get.call_count + session.post.call_count == 1
    args, kwargs = getattr(session,method).call_args
    assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
    assert kwargs['headers']['User-Agent'] == w.robots_checkpoint.PUBLISHER_USER_AGENT
    assert kwargs['headers']['Accept'] == 'application/json'
    if method == 'post':
        assert p.valid_chapel_calendar_request(args[0], kwargs['data'])
        assert kwargs['headers']['Content-Type'] == 'application/json'
        assert 'Authorization' not in kwargs['headers']
        assert 'json' not in kwargs
    else:
        assert p.valid_comedyworx_calendar_request(args[0], kwargs['headers']['Authorization'])
        assert 'data' not in kwargs and 'json' not in kwargs


@pytest.mark.parametrize('kind', ['chapel_bootstrap','chapel_page','comedyworx_page'])
def test_no_content_request_after_robots_denial(kind):
    session, patches = network(response(), allowed=False)
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(w.PreviewError, match='^robots_denied$'):
            read(kind)
    session.get.assert_not_called()
    session.post.assert_not_called()


@pytest.mark.parametrize('kind', ['chapel_bootstrap','comedyworx_page'])
@pytest.mark.parametrize('reply,reason', [(response(403),'publisher_http_403'),
    (response(302,Location='https://example.com/other'),'calendar_render_redirect_blocked'),
    (response(**{'Content-Type':'text/html'}),'invalid_calendar_render_content_type')])
def test_rejections_never_replay_with_another_route_or_identity(kind,reply,reason):
    session, patches = network(reply)
    with patches[0], patches[1], patches[2], patches[3]:
        with pytest.raises(w.PreviewError, match=reason):
            read(kind)
    assert session.get.call_count + session.post.call_count == 1


@pytest.mark.parametrize('mutation', ['host','body','operation','robots','media','mixed'])
def test_chapel_body_cannot_turn_into_an_arbitrary_post(mutation):
    url, body = p.chapel_calendar_request(page=1,bootstrap=True)
    options = dict(respect_robots=True,allowed_hosts=('www.tickpick.com',),chapel_calendar_body=body)
    accept = 'application/json'
    if mutation == 'host':url=url.replace('www.tickpick.com','evil.test')
    if mutation == 'body':options['chapel_calendar_body']=body.replace(b'chapel-of-bones',b'other-organizer')
    if mutation == 'operation':url=url.replace('get_organizer_page_bootstrap','purchase')
    if mutation == 'robots':options['respect_robots']=False
    if mutation == 'media':accept='text/html'
    if mutation == 'mixed':options['comedyworx_instance']=instance()
    with patch.object(w.requests,'Session') as session:
        with pytest.raises(w.PreviewError,match='invalid_chapel_calendar_request'):
            w._fetch_publisher_request(url,accept,**options)
    session.assert_not_called()


@pytest.mark.parametrize('mutation', ['host','route','token','robots','media','post'])
def test_wix_public_instance_cannot_authorize_other_reads_or_writes(mutation):
    url=p.comedyworx_calendar_url(18)
    options=dict(respect_robots=True,allowed_hosts=('www.comedyworx.com',),comedyworx_instance=instance())
    accept='application/json'
    if mutation == 'host':url=url.replace('www.comedyworx.com','evil.test')
    if mutation == 'route':url=url.replace('/paginated-events/viewer','/private-users')
    if mutation == 'token':options['comedyworx_instance']='private-token'
    if mutation == 'robots':options['respect_robots']=False
    if mutation == 'media':accept='text/html'
    if mutation == 'post':options['calendar_json']={'delete':1}
    with patch.object(w.requests,'Session') as session:
        with pytest.raises(w.PreviewError,match='invalid_comedyworx_calendar_request'):
            w._fetch_publisher_request(url,accept,**options)
    session.assert_not_called()


def test_missing_wix_instance_and_unsupported_operation_fail_before_transport():
    with patch.object(w.requests,'Session') as session:
        with pytest.raises(w.PreviewError,match='invalid_comedyworx_calendar_request'):
            w.read_raleigh_followup_events(request_kind='comedyworx_page',offset=18)
        with pytest.raises(w.PreviewError,match='unregistered_raleigh_followup_source'):
            w.read_raleigh_followup_events(request_kind='register_attendee')
    session.assert_not_called()
