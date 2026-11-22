from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from roomquest import preview_worker as worker

HOST = 'cambridgesouthhockeyclub.co.uk'
ORIGIN = 'https://' + HOST + '/robots.txt'
DESTINATION = ORIGIN + '/'


def test_exact_get_redirect_checks_dns_and_drops_credentials(monkeypatch):
    check = Mock()
    monkeypatch.setattr(worker, 'validate_public_dns', check)
    request = Request(ORIGIN, headers={'Authorization': 'fixture', 'Cookie': 'fixture'})
    redirected = worker.ReviewedRobotsRedirects().redirect_request(request, None, 301, '', {}, DESTINATION)
    check.assert_called_once_with(HOST)
    assert redirected.full_url == DESTINATION
    assert redirected.get_header('Authorization') is None
    assert redirected.get_header('Cookie') is None
    with pytest.raises(worker.PreviewError, match='redirect_blocked'):
        worker.ReviewedRobotsRedirects().redirect_request(redirected, None, 301, '', {}, ORIGIN)


@pytest.mark.parametrize('origin,destination,method,code', [
    (ORIGIN, DESTINATION, 'POST', 301), (ORIGIN, DESTINATION, 'GET', 302),
    (ORIGIN, DESTINATION + '?q=x', 'GET', 301),
    (ORIGIN, DESTINATION.replace(HOST, '127.0.0.1'), 'GET', 301),
    (ORIGIN, DESTINATION.replace('https:', 'http:'), 'GET', 301),
    (ORIGIN, DESTINATION.replace(HOST, 'user:pass@' + HOST), 'GET', 301),
    (ORIGIN.replace(HOST, 'other.example'), DESTINATION, 'GET', 301),
])
def test_other_redirects_remain_blocked(origin, destination, method, code):
    with pytest.raises(worker.PreviewError, match='redirect_blocked'):
        worker.ReviewedRobotsRedirects().redirect_request(Request(origin, method=method), None, code, '', {}, destination)


def test_private_dns_still_fails_before_redirect_request(monkeypatch):
    monkeypatch.setattr(worker, 'validate_public_dns', Mock(side_effect=worker.PreviewError('non_public_dns')))
    with pytest.raises(worker.PreviewError, match='non_public_dns'):
        worker.ReviewedRobotsRedirects().redirect_request(Request(ORIGIN), None, 301, '', {}, DESTINATION)


@pytest.mark.parametrize('status,outcome', [(404, True), (410, True), (403, 'robots_denied'), (503, 'robots_unavailable')])
def test_redirect_destination_uses_normal_robots_policy(monkeypatch, status, outcome):
    monkeypatch.setattr(worker, 'validate_public_dns', Mock())
    monkeypatch.setattr(worker, 'pace_publisher', Mock())
    monkeypatch.setattr(worker, '_reserve_known_crawl_delay', Mock())
    worker._robots_cache.pop(HOST, None)
    def opener(handler):
        def open_request(request, timeout):
            redirected = handler.redirect_request(request, None, 301, '', {}, DESTINATION)
            raise HTTPError(redirected.full_url, status, 'fixture', {}, None)
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(worker, 'build_opener', opener)
    if outcome is True:
        assert worker.robots_allowed(HOST, '/matches/cshc_matches.ics') is True
    else:
        with pytest.raises(worker.PreviewError, match=outcome):
            worker.robots_allowed(HOST, '/matches/cshc_matches.ics')
    worker._robots_cache.pop(HOST, None)
