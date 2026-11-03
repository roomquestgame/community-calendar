"""Publisher rules are cached by host while permissions remain path-specific."""
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from roomquest import preview_worker as worker


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
def isolated_rules():
    worker._robots_rules.cache_clear()
    saved_delays = dict(worker._robots_delays)
    worker._robots_delays.clear()
    yield
    worker._robots_rules.cache_clear()
    worker._robots_delays.clear()
    worker._robots_delays.update(saved_delays)


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


@pytest.mark.parametrize("code", [401, 403, 429, 500])
def test_http_failure_denies_collection_and_does_not_cache_success(monkeypatch, code):
    failure = HTTPError(ROBOTS_URL, code, "publisher failure", {}, None)
    calls, _dns_checks = transport(monkeypatch, failure, b"User-agent: *\nDisallow: /private/\n")
    monkeypatch.setattr(worker, "monotonic", lambda: 100.0)

    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
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
