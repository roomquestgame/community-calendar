"""Public poster bytes and Carde routing retain the guarded publisher boundary."""
from unittest.mock import MagicMock, Mock
from urllib.parse import urlencode

import pytest

from roomquest import preview_worker as worker

START, END = '2026-11-14T00:00:00Z', '2027-01-13T00:00:00Z'
API = 'https://api.carde.io/api/play/establishments/0571b1bc-5f97-40ac-bd29-b73170f3df8b/events'
URL = API + '?' + urlencode({'startsAt': START, 'endsAt': END, 'limit': '100', 'page': '1'})


def transport(monkeypatch, body=b'{}', content_type='application/json', status=200, extra=None):
    response = MagicMock(status_code=status, encoding='utf-8',
                         headers={'Content-Type': content_type, **(extra or {})})
    response.iter_content.return_value = [body]
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    monkeypatch.setattr(worker.requests, 'Session', lambda: session)
    dns, robots, pacing = Mock(), Mock(return_value=True), Mock()
    monkeypatch.setattr(worker, 'validate_public_dns', dns)
    monkeypatch.setattr(worker, 'robots_allowed', robots)
    monkeypatch.setattr(worker, 'pace_publisher', pacing)
    monkeypatch.setattr(worker, '_observe_retry_after', Mock())
    return session, response, dns, robots, pacing


def render():
    return worker.render_cardboard_arena_calendar(starts_at=START, ends_at=END)


def test_public_routing_request_is_exact_and_guarded(monkeypatch):
    session, response, dns, robots, pacing = transport(monkeypatch)
    assert render() == '{}'
    session.post.assert_not_called()
    args, kwargs = session.get.call_args
    assert args == (URL,) and kwargs['allow_redirects'] is False and kwargs['stream'] is True
    assert kwargs['headers']['game-id'] == '2f532764-e06a-494b-9ca1-3e5dfea425ec'
    assert not {'Authorization', 'Cookie'} & kwargs['headers'].keys()
    dns.assert_called_once_with('api.carde.io')
    robots.assert_called_once()
    pacing.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize('change', [
    {'url': URL.replace('0571b1bc', '0571b1bd')}, {'url': URL.replace('api.carde.io', 'example.com')},
    {'url': URL.replace('page=1', 'page=2')}, {'url': URL+'&extra=1'},
    {'url': URL+'&startsAt='+START}, {'url': URL+'#other'},
    {'accept': 'text/html'}, {'respect_robots': False},
    {'allowed_hosts': ('api.carde.io', 'play.carde.io')},
    {'calendar_form': {}}, {'calendar_json': {}}, {'localhop_app_id': 'a'*30},
    {'cardboard_arena_calendar': 1},
])
def test_public_header_cannot_escape_reviewed_request(monkeypatch, change):
    session, _, dns, *_ = transport(monkeypatch)
    request = dict(url=URL, accept='application/json', respect_robots=True,
                   allowed_hosts=('api.carde.io',), cardboard_arena_calendar=True)
    request.update(change)
    with pytest.raises(worker.PreviewError, match='^invalid_cardboard_calendar_parameters$'):
        worker._fetch_publisher_request(**request)
    session.get.assert_not_called()
    dns.assert_not_called()


@pytest.mark.parametrize('start,end', [(START,START),(END,START),
    (START,'2027-02-15T00:00:00Z'),('2026-11-14',END),('2026-99-14T00:00:00Z',END),
    (START,'2027-01-13T00:00:00+00:00')])
def test_invalid_window_rejected_before_network(monkeypatch,start,end):
    session, *_ = transport(monkeypatch)
    with pytest.raises(worker.PreviewError, match='^invalid_cardboard_calendar_parameters$'):
        worker.render_cardboard_arena_calendar(starts_at=start,ends_at=end)
    session.get.assert_not_called()


@pytest.mark.parametrize('status', [301,302,303,307,308])
def test_public_header_is_never_replayed_on_redirect(monkeypatch,status):
    session, response, *_ = transport(monkeypatch,status=status,extra={'Location':'https://play.carde.io/'})
    with pytest.raises(worker.PreviewError,match='^calendar_render_redirect_blocked$'):
        render()
    session.get.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize('gate,code', [('dns','non_public_dns'),('dns','dns_unavailable'),
    ('robots','robots_denied'),('pacing','publisher_pacing_deferred')])
def test_access_guards_apply_to_public_renderer(monkeypatch,gate,code):
    session, _, dns, robots, pacing = transport(monkeypatch)
    if gate=='robots': robots.return_value=False
    else: (dns if gate=='dns' else pacing).side_effect=worker.PreviewError(code)
    with pytest.raises(worker.PreviewError,match='^'+code+'$'): render()
    session.get.assert_not_called()


@pytest.mark.parametrize('mime,body', [('image/jpeg',b'\xff\xd8\xff\xe0\x00reviewedposter'),
    ('image/png',b'\x89PNG\r\n\x1a\nreviewedposter')])
def test_reviewed_image_bytes_are_returned_without_text_decoding(monkeypatch,mime,body):
    session,response,dns,robots,pacing=transport(monkeypatch,body=body,content_type=mime)
    result=worker.fetch_publisher('https://images.example.org/poster',mime,respect_robots=True,
                                 allowed_hosts=('images.example.org',))
    assert result==body and isinstance(result,bytes)
    assert 'game-id' not in session.get.call_args.kwargs['headers']
    dns.assert_called_once_with('images.example.org');robots.assert_called_once();pacing.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize('mime,body,actual,extra,code', [
    ('image/jpeg',b'html','text/html',{},'invalid_publisher_image_content_type'),
    ('image/png',b'html','image/jpeg',{},'invalid_publisher_image_content_type'),
    ('image/jpeg',b'html','image/jpeg',{},'invalid_publisher_image'),
    ('image/png',b'html','image/png',{},'invalid_publisher_image'),
    ('image/jpeg',b'\xff\xd8\xff','image/jpeg',{'Content-Length':str(worker.MAX_BODY+1)},'source_unavailable_or_oversized'),
    ('image/jpeg',b'\xff\xd8\xff'+b'x'*worker.MAX_BODY,'image/jpeg',{},'source_too_large'),
])
def test_wrong_or_oversized_posters_fail_closed(monkeypatch,mime,body,actual,extra,code):
    _,response,*_=transport(monkeypatch,body=body,content_type=actual,extra=extra)
    with pytest.raises(worker.PreviewError,match='^'+code+'$'):
        worker.fetch_publisher('https://images.example.org/poster',mime,respect_robots=True,
                               allowed_hosts=('images.example.org',))
    response.close.assert_called_once()


def test_public_renderer_requires_json_and_preserves_http_denial(monkeypatch):
    transport(monkeypatch,body=b'<html>denied</html>',content_type='text/html',status=403)
    with pytest.raises(worker.PreviewError,match='^publisher_http_403$'):render()
    transport(monkeypatch,body=b'<html>unexpected</html>',content_type='text/html')
    with pytest.raises(worker.PreviewError,match='^invalid_calendar_render_content_type$'):render()
