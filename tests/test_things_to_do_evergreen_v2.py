"""evergreen-v2 claims, robots diagnostics and the reviewed South Hill redirect."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from roomquest import preview_worker as worker
from roomquest.things_to_do_worker import run_batch

KEY = 'web:' + 'b' * 64
URL = 'https://www.fairfaxcounty.gov/parks/hidden-pond'
BODY = '''## Hidden Pond Nature Center

8511 Greeley Boulevard
Springfield, VA 22152

The center features a pond and woodland trails for visitors to explore.
'''


def claim(policy='evergreen-v2'):
    return dict(status='claimed', job_id='11111111-1111-1111-1111-111111111111',
                lease_token='22222222-2222-2222-2222-222222222222', source_key=KEY,
                page_url=URL, park_context={}, policy_version=policy,
                scope=dict(parser='general', source_key=KEY, city='Fairfax County', state='VA',
                           url_prefixes=[URL, 'https://www.fairfaxcounty.gov/parks/']))


def run(policy='evergreen-v2', fetch=None, retained=None):
    payloads = []

    def database(action, payload):
        if action == 'claim':
            return claim(policy)
        payloads.append(payload)
        return dict(status='finished', outcome=payload['status'])

    result = run_batch(database=database, fetch=fetch,
                       request_database=lambda *args: retained or dict(status='missing'))
    return result, payloads


def test_v2_claim_uses_retained_content_without_network():
    with patch('roomquest.things_to_do_worker.fetch_publisher', side_effect=AssertionError('network')):
        result, payloads = run(retained=dict(status='ready', metadata=dict(raw_content=BODY)))
    assert result['outcome'] == 'success'
    assert payloads[0]['activities'][0]['location_text'] == '8511 Greeley Boulevard, Springfield, VA 22152'


def test_unknown_policy_is_not_autonomous_and_never_fetches():
    fetch = Mock(side_effect=AssertionError('network'))
    result, payloads = run(policy='evergreen-v3', fetch=fetch)
    assert result == {'status': 'invalid_claim'}
    assert payloads == [] and not fetch.called


@pytest.mark.parametrize('detail', ['access_http_401', 'access_http_403', 'path_disallowed'])
def test_robots_detail_is_forwarded_with_shared_code(detail):
    def fetch(url, *, deadline_at):
        raise worker._robots_denied(detail)
    result, payloads = run(fetch=fetch)
    assert payloads[0]['status'] == 'held'
    assert payloads[0]['error_code'] == 'robots_denied'
    assert payloads[0]['robots_detail'] == detail


def test_unknown_robots_detail_is_dropped():
    def fetch(url, *, deadline_at):
        error = worker.PreviewError('robots_denied')
        error.robots_detail = 'free text'
        raise error
    result, payloads = run(fetch=fetch)
    assert payloads[0]['error_code'] == 'robots_denied'
    assert 'robots_detail' not in payloads[0]


@pytest.mark.parametrize('status', [401, 403])
def test_robots_access_denial_carries_http_detail(monkeypatch, status):
    host = 'robots-detail.example'
    monkeypatch.setattr(worker, 'validate_public_dns', Mock())
    monkeypatch.setattr(worker, 'pace_publisher', Mock())
    monkeypatch.setattr(worker, '_reserve_known_crawl_delay', Mock())
    monkeypatch.setattr(worker, 'activity_before_request', Mock())
    worker._robots_cache.pop(host, None)

    def opener(handler):
        def open_request(request, timeout):
            raise HTTPError(request.full_url, status, 'fixture', {}, None)
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(worker, 'build_opener', opener)
    with pytest.raises(worker.PreviewError, match='robots_denied') as caught:
        worker.robots_allowed(host, '/parks/')
    assert caught.value.robots_detail == 'access_http_%d' % status


def test_robots_disallow_carries_path_detail_before_any_page_request(monkeypatch):
    monkeypatch.setattr(worker, 'validate_public_dns', Mock())
    monkeypatch.setattr(worker, 'robots_allowed', Mock(return_value=False))
    monkeypatch.setattr(worker, 'build_opener', Mock(side_effect=AssertionError('page request')))
    with pytest.raises(worker.PreviewError, match='robots_denied') as caught:
        worker.fetch_publisher(URL, 'text/html', respect_robots=True,
                               allowed_hosts=('www.fairfaxcounty.gov',), follow_redirects=False)
    assert caught.value.robots_detail == 'path_disallowed'


SOUTH_HILL_ORIGIN = 'https://www.southhillva.org/robots.txt'
SOUTH_HILL_DESTINATION = 'https://www.southhillva.gov/robots.txt'


def test_reviewed_south_hill_robots_redirect_checks_destination_dns(monkeypatch):
    check = Mock()
    monkeypatch.setattr(worker, 'validate_public_dns', check)
    monkeypatch.setattr(worker, 'activity_before_request', Mock())
    redirected = worker.ReviewedRobotsRedirects().redirect_request(
        Request(SOUTH_HILL_ORIGIN, headers={'Cookie': 'fixture'}), None, 301, '', {}, SOUTH_HILL_DESTINATION)
    check.assert_called_once_with('www.southhillva.gov')
    assert redirected.full_url == SOUTH_HILL_DESTINATION
    assert redirected.get_header('Cookie') is None


@pytest.mark.parametrize('origin,destination,method,code', [
    (SOUTH_HILL_ORIGIN, SOUTH_HILL_DESTINATION, 'POST', 301),
    (SOUTH_HILL_ORIGIN, SOUTH_HILL_DESTINATION, 'GET', 302),
    (SOUTH_HILL_ORIGIN, SOUTH_HILL_DESTINATION + '?x=1', 'GET', 301),
    (SOUTH_HILL_ORIGIN, 'https://www.southhillva.gov/parks.php', 'GET', 301),
    (SOUTH_HILL_DESTINATION, SOUTH_HILL_ORIGIN, 'GET', 301),
    ('https://www.southhillva.org/parks.php', SOUTH_HILL_DESTINATION, 'GET', 301),
])
def test_other_south_hill_redirects_remain_blocked(monkeypatch, origin, destination, method, code):
    monkeypatch.setattr(worker, 'activity_before_request', Mock())
    with pytest.raises(worker.PreviewError, match='redirect_blocked'):
        worker.ReviewedRobotsRedirects().redirect_request(
            Request(origin, method=method), None, code, '', {}, destination)
