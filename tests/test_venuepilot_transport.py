from copy import deepcopy
from datetime import date
from unittest.mock import ANY, MagicMock, Mock

import pytest

from roomquest import preview_worker as worker
from roomquest import venuepilot_provider as venuepilot


BODY = venuepilot.request((2535,), date(2026, 11, 26), date(2027, 1, 26))


def transport(monkeypatch, *, status=200, headers=None, body=b'{"data":{"publicEvents":[]}}'):
    response = MagicMock(status_code=status, encoding='utf-8',
                         headers=headers or {'Content-Type': 'application/json'})
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


def request(**changes):
    values = dict(url=venuepilot.API, accept='application/json', respect_robots=True,
                  allowed_hosts=(venuepilot.HOST,), calendar_json=deepcopy(BODY))
    values.update(changes)
    return values


def test_exact_graphql_query_uses_guarded_post(monkeypatch):
    session, response, dns, robots, pacing = transport(monkeypatch)
    assert worker.fetch_publisher(**request()) == '{"data":{"publicEvents":[]}}'
    session.get.assert_not_called()
    args, kwargs = session.post.call_args
    assert args == (venuepilot.API,)
    assert kwargs['json'] == BODY and kwargs['allow_redirects'] is False
    assert kwargs['headers']['Content-Type'] == 'application/json'
    assert kwargs['headers']['Referer'] == 'https://www.venuepilot.co/'
    assert not {'Authorization', 'Cookie'} & kwargs['headers'].keys()
    dns.assert_called_once_with(venuepilot.HOST)
    robots.assert_called_once_with(venuepilot.HOST, '/graphql', deadline_at=ANY)
    pacing.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize('change', [
    {'url': venuepilot.API + '?write=true'}, {'url': 'https://evil.example/graphql'},
    {'accept': 'text/html'}, {'respect_robots': False},
    {'allowed_hosts': (venuepilot.HOST, 'evil.example')}, {'calendar_form': {}},
    {'calendar_json': {}},
    {'calendar_json': {**BODY, 'query': BODY['query'] + ' mutation'}},
    {'calendar_json': {**BODY, 'variables': {**BODY['variables'], 'limit': 1000}}},
])
def test_other_requests_are_rejected_before_network(monkeypatch, change):
    session, _, dns, *_ = transport(monkeypatch)
    with pytest.raises(worker.PreviewError, match='^invalid_calendar_render_parameters$'):
        worker.fetch_publisher(**request(**change))
    session.post.assert_not_called()
    dns.assert_not_called()


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_post_is_never_replayed_on_redirect(monkeypatch, status):
    session, response, *_ = transport(monkeypatch, status=status,
                                      headers={'Location': venuepilot.API})
    with pytest.raises(worker.PreviewError, match='^calendar_render_redirect_blocked$'):
        worker.fetch_publisher(**request())
    session.post.assert_called_once()
    response.close.assert_called_once()


def test_robots_denial_prevents_post(monkeypatch):
    session, _, _, robots, _ = transport(monkeypatch)
    robots.return_value = False
    with pytest.raises(worker.PreviewError, match='^robots_denied$'):
        worker.fetch_publisher(**request())
    session.post.assert_not_called()
