"""Publisher rules are cached by host while permissions remain path-specific."""
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest

from roomquest import preview_worker as worker
from roomquest.publisher_pacing import (capture_publisher_pacing, observe_retry_after,
                                       pacing_rpc_fields)


HOST = "www.mycountyparks.com"
ROBOTS_URL = "https://" + HOST + "/robots.txt"


class RobotsResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        return self.body[:limit]


@pytest.fixture(autouse=True)
def isolated_rules(monkeypatch):
    # All HTTP and clocks in this suite are controlled; record pacing without
    # introducing real sleeps into fake-origin tests.
    monkeypatch.setattr(worker, "sleep", Mock())
    worker._robots_rules.cache_clear()
    saved_delays = dict(worker._robots_delays)
    saved_next = dict(worker._publisher_next)
    saved_retry = dict(worker._publisher_retry_after)
    worker._robots_delays.clear()
    worker._publisher_next.clear()
    worker._publisher_retry_after.clear()
    yield
    worker._robots_rules.cache_clear()
    worker._robots_delays.clear()
    worker._robots_delays.update(saved_delays)
    worker._publisher_next.clear()
    worker._publisher_next.update(saved_next)
    worker._publisher_retry_after.clear()
    worker._publisher_retry_after.update(saved_retry)


def transport(monkeypatch, *answers):
    """Install a bounded fake origin; every unexpected fetch fails the test."""
    replies = iter(answers)
    calls = []
    dns_checks = []

    def open_request(request, timeout):
        calls.append((request.full_url, timeout))
        answer = next(replies)
        if isinstance(answer, Exception):
            raise answer
        return RobotsResponse(answer)

    monkeypatch.setattr(worker, "build_opener", lambda *_args: SimpleNamespace(open=open_request))
    monkeypatch.setattr(worker, "validate_public_dns", dns_checks.append)
    return calls, dns_checks


def test_one_rules_download_checks_each_path_and_accepts_utf8_bom(monkeypatch):
    calls, dns_checks = transport(
        monkeypatch,
        b"\xef\xbb\xbfUser-agent: *\nDisallow: /private/\nAllow: /public/\nCrawl-delay: 2\n",
    )
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)

    assert worker.robots_allowed(HOST, "/public/event-1") is True
    assert worker.robots_allowed(HOST, "/private/event-2") is False
    assert worker.robots_allowed(HOST, "/public/event-3?day=tomorrow") is True
    assert [url for url, _timeout in calls] == [ROBOTS_URL]
    assert dns_checks == [HOST]
    assert worker._robots_delays[HOST] == 2


def test_rules_refresh_after_five_minutes_changes_path_decision(monkeypatch):
    calls, _dns_checks = transport(
        monkeypatch,
        b"User-agent: *\nDisallow: /private/\n",
        b"User-agent: *\nDisallow: /public/\n",
    )
    now = [0.0]
    monkeypatch.setattr(worker, "monotonic", lambda: now[0])

    assert worker.robots_allowed(HOST, "/public/event") is True
    now[0] = 299.0
    assert worker.robots_allowed(HOST, "/private/event") is False
    assert len(calls) == 1
    now[0] = 300.0
    assert worker.robots_allowed(HOST, "/public/event") is False
    assert worker.robots_allowed(HOST, "/private/event") is True
    assert len(calls) == 2


@pytest.mark.parametrize("code,reason", [
    (401, "robots_denied"), (403, "robots_denied"),
    (429, "publisher_rate_limited"), (500, "robots_unavailable"),
    (503, "robots_unavailable"),
])
def test_http_failure_fails_closed_without_mislabeling_transient_as_denied(monkeypatch, code, reason):
    failure = HTTPError(ROBOTS_URL, code, "publisher failure", {}, None)
    calls, _dns_checks = transport(monkeypatch, failure, b"User-agent: *\nDisallow: /private/\n")
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)

    with pytest.raises(worker.PreviewError, match="^" + reason + "$"):
        worker.robots_allowed(HOST, "/public/event")
    assert worker.robots_allowed(HOST, "/private/event") is False
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [URLError("unavailable"), TimeoutError("timeout")])
def test_network_failure_fails_closed(monkeypatch, failure):
    transport(monkeypatch, failure)
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)

    with pytest.raises(worker.PreviewError, match="^robots_unavailable$"):
        worker.robots_allowed(HOST, "/public/event")


@pytest.mark.parametrize("code", [404, 410])
def test_missing_robots_clears_stale_delay_and_caches_unrestricted_result(monkeypatch, code):
    calls, _dns_checks = transport(
        monkeypatch,
        b"User-agent: *\nDisallow: /private/\nCrawl-delay: 17\n",
        HTTPError(ROBOTS_URL, code, "missing", {}, None),
    )
    now = [0.0]
    monkeypatch.setattr(worker, "monotonic", lambda: now[0])

    assert worker.robots_allowed(HOST, "/private/event") is False
    assert worker._robots_delays[HOST] == 17
    now[0] = 300.0
    assert worker.robots_allowed(HOST, "/private/event") is True
    assert worker.robots_allowed(HOST, "/another/event") is True
    assert worker._robots_delays[HOST] == 1
    assert len(calls) == 2


def test_oversized_rules_fail_closed(monkeypatch):
    transport(monkeypatch, b"#" * 128_001)
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)

    with pytest.raises(worker.PreviewError, match="^robots_unavailable$"):
        worker.robots_allowed(HOST, "/public/event")


def test_private_dns_does_not_fetch_or_allow(monkeypatch):
    calls, _dns_checks = transport(monkeypatch)

    def deny_dns(_host):
        raise worker.PreviewError("dns_unavailable")

    monkeypatch.setattr(worker, "validate_public_dns", deny_dns)
    with pytest.raises(worker.PreviewError, match="^dns_unavailable$"):
        worker.robots_allowed(HOST, "/public/event")
    assert calls == []


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_private_dns_remains_a_policy_block_not_a_transient_outage(monkeypatch, address):
    monkeypatch.setattr(worker.socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, (address, 443))])
    with pytest.raises(worker.PreviewError, match="^non_public_dns$"):
        worker.validate_public_dns("publisher.example")


def test_dns_resolver_outage_remains_distinct(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("private resolver message")
    monkeypatch.setattr(worker.socket, "getaddrinfo", unavailable)
    with pytest.raises(worker.PreviewError, match="^dns_unavailable$"):
        worker.validate_public_dns("publisher.example")


def test_cached_rules_copy_crawl_delay_into_each_collection_receipt(monkeypatch):
    calls, _ = transport(monkeypatch, b"User-agent: *\nDisallow: /private/\nCrawl-delay: 10\n")
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)
    for _ in range(2):
        with capture_publisher_pacing() as state:
            assert worker.robots_allowed(HOST, "/public/event") is True
        assert pacing_rpc_fields(state) == {"p_publisher_crawl_delay_seconds": 10,
                                            "p_publisher_retry_after_seconds": 0,
                                            "p_publisher_wait_unbounded": False}
    assert len(calls) == 1


def test_fractional_crawl_delay_rounds_up_and_keeps_group_permissions(monkeypatch):
    raw = (b"User-agent: OtherBot\nDisallow: /\nCrawl-delay: 90000\n\n"
           b"User-agent: RoomQuestCommunityCalendar\nDisallow: /private/\nCrawl-delay: 2.1\n\n"
           b"User-agent: *\nDisallow: /\nCrawl-delay: 30\n")
    transport(monkeypatch, raw)
    with capture_publisher_pacing() as state:
        assert worker.robots_allowed(HOST, "/public/event") is True
        assert worker.robots_allowed(HOST, "/private/event") is False
    assert state["crawl_delay_seconds"] == 3 and state["wait_unbounded"] is False


@pytest.mark.parametrize("wait", ["86401", "999999999999999999999999", "unparseable"])
def test_oversized_or_unrepresentable_crawl_wait_requires_review(monkeypatch, wait):
    transport(monkeypatch, f"User-agent: *\nAllow: /\nCrawl-delay: {wait}\n".encode())
    with capture_publisher_pacing() as state:
        with pytest.raises(worker.PreviewError, match="^publisher_wait_requires_review$"):
            worker.robots_allowed(HOST, "/public/event")
    assert pacing_rpc_fields(state) == {"p_publisher_crawl_delay_seconds": 0,
                                       "p_publisher_retry_after_seconds": 0,
                                       "p_publisher_wait_unbounded": True}


@pytest.mark.parametrize("header,expected", [
    (None, 0), ("0", 0), ("1.2", 2), ("120", 120), ("86400", 86400),
    ("Wed, 04 Nov 2026 02:32:00 GMT", 120),
    ("Wed, 04 Nov 2026 02:29:00 GMT", 0),
])
def test_retry_after_numeric_and_http_dates_preserve_full_wait(header, expected):
    now = datetime(2026, 11, 4, 2, 30, tzinfo=timezone.utc)
    with capture_publisher_pacing() as state:
        assert observe_retry_after(header, now=now) == (expected, False)
    assert state["retry_after_seconds"] == expected


@pytest.mark.parametrize("header", ["86401", "999999999999999999999999", "not a date",
                                     "Fri, 06 Nov 2026 02:30:00 GMT", "-1"])
def test_retry_after_above_bound_or_unrepresentable_is_not_clamped(header):
    now = datetime(2026, 11, 4, 2, 30, tzinfo=timezone.utc)
    with capture_publisher_pacing() as state:
        assert observe_retry_after(header, now=now) == (0, True)
    assert pacing_rpc_fields(state)["p_publisher_wait_unbounded"] is True
    assert pacing_rpc_fields(state)["p_publisher_retry_after_seconds"] == 0


def test_robots_rate_limit_retains_retry_after_without_allowing_calendar(monkeypatch):
    failure = HTTPError(ROBOTS_URL, 429, "not logged", {"Retry-After": "600"}, None)
    calls, _ = transport(monkeypatch, failure)
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)
    with capture_publisher_pacing() as state:
        with pytest.raises(worker.PreviewError, match="^publisher_rate_limited$"):
            worker.robots_allowed(HOST, "/public/event")
    assert state["retry_after_seconds"] == 600
    assert calls == [(ROBOTS_URL, 5)]


def test_robots_retry_after_protects_the_next_robots_get_too(monkeypatch):
    failure = HTTPError(ROBOTS_URL, 429, "not logged", {"Retry-After": "600"}, None)
    calls, _ = transport(monkeypatch, failure)
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)
    with capture_publisher_pacing():
        with pytest.raises(worker.PreviewError, match="^publisher_rate_limited$"):
            worker.robots_allowed(HOST, "/public/event")
    with capture_publisher_pacing() as second:
        with pytest.raises(worker.PreviewError, match="^publisher_rate_limited$"):
            worker.robots_allowed(HOST, "/public/event")
    assert second["retry_after_seconds"] == 600
    assert calls == [(ROBOTS_URL, 5)]


def test_new_crawl_delay_separates_robots_and_first_calendar_request(monkeypatch):
    transport(monkeypatch, b"User-agent: *\nAllow: /\nCrawl-delay: 10\n")
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)
    with capture_publisher_pacing() as state:
        assert worker.robots_allowed(HOST, "/public/event") is True
    assert state["crawl_delay_seconds"] == 10
    assert worker._publisher_next[HOST] >= 110
    worker.pace_publisher(HOST, 118)
    worker.sleep.assert_called_once_with(10)


def publisher_transport(monkeypatch, status, retry_after):
    response = SimpleNamespace(status_code=status, headers={"Retry-After": retry_after}, close=Mock())
    session = MagicMock()
    session.get.return_value = response
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(worker.requests, "Session", factory)
    monkeypatch.setattr(worker, "validate_public_dns", lambda *_: None)
    monkeypatch.setattr(worker, "robots_allowed", lambda *_: True)
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)
    return response, session


def test_publisher_retry_after_blocks_a_following_request_and_survives_new_capture(monkeypatch):
    response, session = publisher_transport(monkeypatch, 429, "120")
    with capture_publisher_pacing() as first:
        with pytest.raises(worker.PreviewError, match="^publisher_http_429$"):
            worker.fetch_publisher("https://" + HOST + "/events", "text/html", respect_robots=True)
    assert first["retry_after_seconds"] == 120
    with capture_publisher_pacing() as second:
        with pytest.raises(worker.PreviewError, match="^publisher_rate_limited$"):
            worker.fetch_publisher("https://" + HOST + "/events", "text/html", respect_robots=True)
    assert second["retry_after_seconds"] == 120
    assert session.get.call_count == 1
    response.close.assert_called_once()


@pytest.mark.parametrize("status", [200, 429, 503])
def test_unbounded_publisher_wait_fails_before_payload_parsing(monkeypatch, status):
    response, session = publisher_transport(monkeypatch, status, "86401")
    with capture_publisher_pacing() as state:
        with pytest.raises(worker.PreviewError, match="^publisher_wait_requires_review$"):
            worker.fetch_publisher("https://" + HOST + "/events", "text/html", respect_robots=True)
    assert state["wait_unbounded"] is True
    assert session.get.call_count == 1
    response.close.assert_called_once()


def test_reviewed_algolia_missing_robots_route_validates_both_hosts_and_keeps_credentials_local(monkeypatch):
    from urllib.request import Request
    checked=[]
    monkeypatch.setattr(worker,'validate_public_dns',checked.append)
    handler=worker.ReviewedRobotsRedirects()
    request=Request('https://eyqhj2iy2m-dsn.algolia.net/robots.txt',headers={'Authorization':'fixture-only','Cookie':'fixture-only'})
    redirected=handler.redirect_request(request,None,301,'',{},'https://algolia.net/1/404')
    assert checked==['algolia.net']
    assert redirected.full_url=='https://algolia.net/1/404'
    assert redirected.get_method()=='GET'
    assert redirected.get_header('Authorization') is None
    assert redirected.get_header('Cookie') is None
    # A second redirect, even from that exact vendor destination, fails closed.
    with pytest.raises(worker.PreviewError,match='redirect_blocked'):
        handler.redirect_request(redirected,None,301,'',{},'https://algolia.net/elsewhere')


@pytest.mark.parametrize('origin,destination',[
    ('https://other.algolia.net/robots.txt','https://algolia.net/1/404'),
    ('https://eyqhj2iy2m-dsn.algolia.net/other','https://algolia.net/1/404'),
    ('https://eyqhj2iy2m-dsn.algolia.net/robots.txt','https://user:pass@algolia.net/1/404'),
    ('https://eyqhj2iy2m-dsn.algolia.net/robots.txt','https://algolia.net/1/404?extra=1'),
])
def test_unreviewed_robots_redirects_still_fail_closed(origin,destination):
    from urllib.request import Request
    with pytest.raises(worker.PreviewError,match='redirect_blocked'):
        worker.ReviewedRobotsRedirects().redirect_request(Request(origin),None,301,'',{},destination)


def test_vendor_redirect_destination_404_means_absent_rules_but_new_publisher_rules_win(monkeypatch):
    api='eyqhj2iy2m-dsn.algolia.net'
    checked=[]
    monkeypatch.setattr(worker,'validate_public_dns',checked.append)
    def make_opener(handler):
        assert isinstance(handler,worker.ReviewedRobotsRedirects)
        def open_request(request,timeout):
            dest=handler.redirect_request(request,None,301,'',{},'https://algolia.net/1/404')
            raise HTTPError(dest.full_url,404,'not found',{},None)
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(worker,'build_opener',make_opener)
    assert worker.robots_allowed(api,'/1/indexes/prod-experience-waterloo-listings') is True
    assert checked==[api,'algolia.net']
    worker._robots_rules.cache_clear()
    transport(monkeypatch,b'User-agent: *\nDisallow: /1/\n')
    assert worker.robots_allowed(api,'/1/indexes/prod-experience-waterloo-listings') is False
