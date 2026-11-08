"""Only the observed anonymous RecDesk program display action is admitted."""
from copy import deepcopy
from unittest.mock import ANY, MagicMock, Mock

import pytest

from roomquest import preview_worker as worker


URL = 'https://oldsanteecanal.recdesk.com/Community/Program/FilterPrograms'
HOST = 'oldsanteecanal.recdesk.com'
BODY = {'ProgramName': '', 'Code': '', 'ProgramNameXS': '',
        'DateRangeSelection': '', 'DateRangeFrom': '', 'DateRangeTo': '',
        'ProgramType': '0', 'Age': '', 'Facility': '0', 'Days': '0',
        'Pagination': {'CurrentPageIndex': 1, 'LoadMore': False}}


def fake_transport(monkeypatch, *, status=200, body=b'<p>Displaying 1-5 of 5</p>', headers=None):
    response = MagicMock(status_code=status, encoding='utf-8',
                         headers=headers or {'Content-Type': 'text/html; charset=utf-8'})
    response.iter_content.return_value = [body]
    session = MagicMock()
    session.__enter__.return_value = session
    session.post.return_value = response
    monkeypatch.setattr(worker.requests, 'Session', lambda: session)
    dns, robots, pacing = Mock(), Mock(return_value=True), Mock()
    monkeypatch.setattr(worker, 'validate_public_dns', dns)
    monkeypatch.setattr(worker, 'robots_allowed', robots)
    monkeypatch.setattr(worker, 'pace_publisher', pacing)
    monkeypatch.setattr(worker, '_observe_retry_after', Mock())
    return session, response, dns, robots, pacing


def test_exact_public_display_body_and_guards(monkeypatch):
    session, response, dns, robots, pacing = fake_transport(monkeypatch)
    assert worker.render_old_santee_programs() == '<p>Displaying 1-5 of 5</p>'
    session.get.assert_not_called()
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == (URL,) and kwargs['json'] == BODY and 'data' not in kwargs
    assert kwargs['stream'] is True and kwargs['allow_redirects'] is False
    assert kwargs['headers']['Accept'] == 'text/html'
    assert kwargs['headers']['Content-Type'] == 'application/json; charset=utf-8'
    assert kwargs['headers']['Referer'] == 'https://oldsanteecanal.recdesk.com/Community/Program'
    assert kwargs['headers']['User-Agent'].startswith('RoomQuestCommunityCalendar/')
    assert not {'Authorization', 'Cookie'} & kwargs['headers'].keys()
    dns.assert_called_once_with(HOST)
    robots.assert_called_once_with(HOST, '/Community/Program/FilterPrograms', deadline_at=ANY)
    pacing.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize('change', [
    {'url': 'https://oldsanteecanal.recdesk.com/Community/Cart/Add'},
    {'url': URL+'?page=2'}, {'url': URL.replace(HOST, 'other.example')},
    {'accept': 'application/json'}, {'respect_robots': False},
    {'allowed_hosts': (HOST, 'other.example')}, {'calendar_form': BODY},
    {'calendar_json': {}}, {'calendar_json': []},
    {'calendar_json': {**BODY, 'ProgramName': 'other'}},
    {'calendar_json': {**BODY, 'action': 'register'}},
    {'calendar_json': {**BODY, 'Pagination': {'CurrentPageIndex': True, 'LoadMore': False}}},
    {'calendar_json': {**BODY, 'Pagination': {'CurrentPageIndex': 1, 'LoadMore': 0}}},
    {'calendar_json': {**BODY, 'Pagination': {'CurrentPageIndex': 2, 'LoadMore': False}}},
    {'calendar_json': {**BODY, 'Pagination': {'CurrentPageIndex': 1, 'LoadMore': False, 'PageSize': 1000}}},
])
def test_boundary_rejects_other_requests_without_network(monkeypatch, change):
    session, _, dns, _, _ = fake_transport(monkeypatch)
    request = dict(url=URL, accept='text/html', respect_robots=True,
                   allowed_hosts=(HOST,), calendar_json=deepcopy(BODY))
    request.update(change)
    with pytest.raises(worker.PreviewError, match='^invalid_calendar_render_parameters$'):
        worker._fetch_publisher_request(**request)
    session.post.assert_not_called()
    session.get.assert_not_called()
    dns.assert_not_called()


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_post_never_replays_on_redirect(monkeypatch, status):
    session, response, *_ = fake_transport(monkeypatch, status=status,
                                          headers={'Location': '/Community/Program'})
    with pytest.raises(worker.PreviewError, match='^calendar_render_redirect_blocked$'):
        worker.render_old_santee_programs()
    session.post.assert_called_once()
    session.get.assert_not_called()
    response.close.assert_called_once()


@pytest.mark.parametrize('gate,code', [
    ('dns', 'non_public_dns'), ('dns', 'dns_unavailable'),
    ('robots', 'robots_denied'), ('pacing', 'publisher_pacing_deferred'),
])
def test_post_preserves_access_and_pacing_guards(monkeypatch, gate, code):
    session, _, dns, robots, pacing = fake_transport(monkeypatch)
    if gate == 'robots':
        robots.return_value = False
    else:
        (dns if gate == 'dns' else pacing).side_effect = worker.PreviewError(code)
    with pytest.raises(worker.PreviewError, match='^'+code+'$'):
        worker.render_old_santee_programs()
    session.post.assert_not_called()


@pytest.mark.parametrize('status,headers,body,code', [
    (403, {'Content-Type': 'text/html'}, b'denied', 'publisher_http_403'),
    (429, {'Content-Type': 'text/html'}, b'wait', 'publisher_http_429'),
    (200, {'Content-Type': 'application/json'}, b'{}', 'invalid_calendar_render_content_type'),
    (200, {'Content-Type': 'text/html', 'Content-Length': str(worker.MAX_BODY+1)}, b'x', 'source_unavailable_or_oversized'),
    (200, {'Content-Type': 'text/html'}, b'x'*(worker.MAX_BODY+1), 'source_too_large'),
    (200, {'Content-Type': 'text/html'}, b'\xff', 'invalid_source_encoding'),
])
def test_response_bounds_preserve_failure_reason(monkeypatch, status, headers, body, code):
    _, response, *_ = fake_transport(monkeypatch, status=status, headers=headers, body=body)
    with pytest.raises(worker.PreviewError, match='^'+code+'$'):
        worker.render_old_santee_programs()
    response.close.assert_called_once()


def test_expired_deadline_sends_no_post(monkeypatch):
    session, *_ = fake_transport(monkeypatch)
    with pytest.raises(worker.PreviewError, match='^source_fetch_deadline$'):
        worker.render_old_santee_programs(deadline_at=worker.monotonic()-1)
    session.post.assert_not_called()
