"""Exact Night Shift robots redirect; all policy and host boundaries remain."""
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from roomquest import preview_worker as worker

HOST = 'nightshiftbrewing.com'
ORIGIN = 'https://nightshiftbrewing.com/robots.txt'
DESTINATION = 'https://nightshiftbrewing.com/?robots=1'
USER_AGENT = 'RoomQuestCommunityCalendar/0.1 (community-event research)'
# Native canonical policy observed 2026-11-14. No calendar permission is
# hard-coded: the normal parser evaluates each path against these rules.
POLICY = b'''# START YOAST BLOCK
# ---------------------------
User-agent: *
Disallow: /wp-json/
Disallow: /?rest_route=

Sitemap: https://nightshiftbrewing.com/sitemap_index.xml
# ---------------------------
# END YOAST BLOCK'''


@pytest.fixture(autouse=True)
def isolated_nightshift_state(monkeypatch):
    monkeypatch.setattr(worker, '_robots_cache', OrderedDict())
    monkeypatch.setattr(worker, '_robots_delays', {})
    monkeypatch.setattr(worker, '_publisher_next', {})
    monkeypatch.setattr(worker, '_publisher_retry_after', {})
    monkeypatch.setattr(worker, 'monotonic', lambda: 100.0)
    monkeypatch.setattr(worker, 'sleep', Mock())


def test_nightshift_exact_get_301_revalidates_dns_and_forwards_no_credentials(monkeypatch):
    checked = []
    monkeypatch.setattr(worker, 'validate_public_dns', checked.append)
    original = Request(ORIGIN, headers={'Authorization': 'fixture', 'Cookie': 'fixture'})
    handler = worker.ReviewedRobotsRedirects()
    redirected = handler.redirect_request(original, None, 301, '', {}, DESTINATION)
    assert checked == [HOST]
    assert redirected.full_url == DESTINATION
    assert redirected.get_method() == 'GET'
    assert redirected.get_header('User-agent') == USER_AGENT
    assert redirected.get_header('Authorization') is None
    assert redirected.get_header('Cookie') is None
    with pytest.raises(worker.PreviewError, match='^redirect_blocked$'):
        handler.redirect_request(redirected, None, 301, '', {}, DESTINATION)


@pytest.mark.parametrize('origin,destination,code,method', [
    ('https://www.nightshiftbrewing.com/robots.txt', DESTINATION, 301, 'GET'),
    ('https://nightshiftbrewing.com/events/', DESTINATION, 301, 'GET'),
    (ORIGIN + '?extra=1', DESTINATION, 301, 'GET'),
    (ORIGIN, 'https://nightshiftbrewing.com/wp-json/', 301, 'GET'),
    (ORIGIN, DESTINATION + '&extra=1', 301, 'GET'),
    (ORIGIN, DESTINATION + '#fragment', 301, 'GET'),
    (ORIGIN, 'http://nightshiftbrewing.com/?robots=1', 301, 'GET'),
    (ORIGIN, 'https://other.example/?robots=1', 301, 'GET'),
    (ORIGIN, 'https://user:pass@nightshiftbrewing.com/?robots=1', 301, 'GET'),
    (ORIGIN, 'https://nightshiftbrewing.com:443/?robots=1', 301, 'GET'),
    (ORIGIN, DESTINATION, 302, 'GET'),
    (ORIGIN, DESTINATION, 307, 'GET'),
    (ORIGIN, DESTINATION, 308, 'GET'),
    (ORIGIN, DESTINATION, 301, 'POST'),
])
def test_nightshift_unreviewed_redirect_shape_remains_blocked(origin, destination, code, method):
    with pytest.raises(worker.PreviewError, match='^redirect_blocked$'):
        worker.ReviewedRobotsRedirects().redirect_request(
            Request(origin, method=method), None, code, '', {}, destination)


def test_nightshift_redirect_target_requires_public_dns(monkeypatch):
    def deny(_host):
        raise worker.PreviewError('non_public_dns')
    monkeypatch.setattr(worker, 'validate_public_dns', deny)
    with pytest.raises(worker.PreviewError, match='^non_public_dns$'):
        worker.ReviewedRobotsRedirects().redirect_request(
            Request(ORIGIN), None, 301, '', {}, DESTINATION)


def _canonical_robots_transport(monkeypatch, failure=None):
    seen, checked = [], []
    monkeypatch.setattr(worker, 'validate_public_dns', checked.append)

    class Response:
        status = 200
        headers = {'Content-Type': 'text/plain; charset=utf-8'}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            assert limit == 128_001
            return POLICY[:limit]

    def make_opener(handler):
        def open_request(request, timeout):
            assert timeout <= 5
            seen.append(request.full_url)
            redirected = handler.redirect_request(request, None, 301, '', {}, DESTINATION)
            seen.append(redirected.full_url)
            if failure is not None:
                raise HTTPError(DESTINATION, failure, 'fixture denial', {}, None)
            return Response()
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(worker, 'build_opener', make_opener)
    return seen, checked


def test_nightshift_canonical_policy_allows_events_but_denies_rest_routes(monkeypatch):
    seen, checked = _canonical_robots_transport(monkeypatch)
    assert worker.robots_allowed(HOST, '/events/') is True
    assert worker.robots_allowed(HOST, '/events/trivia-2/') is True
    assert worker.robots_allowed(HOST, '/wp-json/wp/v2/events') is False
    assert worker.robots_allowed(HOST, '/?rest_route=/wp/v2/events') is False
    assert seen == [ORIGIN, DESTINATION]
    assert checked == [HOST, HOST]
    assert worker._robots_delays[HOST] == 1


def test_nightshift_canonical_denial_remains_denied_and_uncached(monkeypatch):
    _canonical_robots_transport(monkeypatch, failure=403)
    with pytest.raises(worker.PreviewError, match='^robots_denied$'):
        worker.robots_allowed(HOST, '/events/')
    assert HOST not in worker._robots_cache
