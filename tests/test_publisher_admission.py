"""Elapsed robots TTL and local pacing preserve complete, guarded requests."""
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from roomquest import preview_worker as worker
from roomquest.collector_errors import failure_details
from roomquest.publisher_pacing import capture_publisher_pacing


HOST = 'publisher.example'
URL = 'https://' + HOST + '/events'


@pytest.fixture(autouse=True)
def isolated_publisher_state():
    fields = ('_robots_cache', '_robots_delays', '_publisher_next', '_publisher_retry_after')
    saved = {field: getattr(worker, field).copy() for field in fields}
    for field in fields:
        getattr(worker, field).clear()
    yield
    for field in fields:
        getattr(worker, field).clear()
        getattr(worker, field).update(saved[field])


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(now=100.0, sleeps=[])

    def sleep(seconds):
        value.sleeps.append(seconds)
        value.now += seconds

    monkeypatch.setattr(worker, 'monotonic', lambda: value.now)
    monkeypatch.setattr(worker, 'sleep', sleep)
    return value


def robots_origin(monkeypatch, *bodies, on_read=None):
    responses = iter(bodies)
    calls = []

    def open_request(request, timeout):
        calls.append((request.full_url, timeout))
        body = next(responses)
        response = MagicMock(status=200, headers={})
        response.__enter__.return_value = response

        def read(limit):
            if on_read:
                on_read()
            return body[:limit]

        response.read.side_effect = read
        return response

    monkeypatch.setattr(worker, 'validate_public_dns', Mock())
    monkeypatch.setattr(worker, 'build_opener', lambda *_: SimpleNamespace(open=open_request))
    return calls


def calendar_origin(monkeypatch, *, chunks=None):
    response = MagicMock(status_code=200,
                         headers={'Content-Type': 'text/html; charset=UTF-8'}, encoding='utf-8')
    if chunks:
        response.iter_content.side_effect = lambda **_: chunks()
    else:
        response.iter_content.return_value = [b'<p>public calendar</p>']
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    monkeypatch.setattr(worker.requests, 'Session', lambda: session)
    return session, response


def test_robots_ttl_does_not_expire_at_a_shared_bucket_boundary(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\nCrawl-delay: 10\n',
                          b'User-agent: *\nDisallow: /events\n')
    clock.now = 299.0
    assert worker.robots_allowed(HOST, '/events') is True
    clock.now = 301.0
    assert worker.robots_allowed(HOST, '/events') is True
    clock.now = 598.9
    assert worker.robots_allowed(HOST, '/events') is True
    assert len(calls) == 1
    clock.now = 599.0
    assert worker.robots_allowed(HOST, '/events') is False
    assert len(calls) == 2


def test_policy_age_starts_after_response_and_cache_hits_do_not_extend_it(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\n',
                          b'User-agent: *\nDisallow: /events\n',
                          on_read=lambda: setattr(clock, 'now', clock.now + 4))
    assert worker.robots_allowed(HOST, '/events') is True
    assert clock.now == 104
    clock.now = 403.9
    assert worker.robots_allowed(HOST, '/events') is True
    assert len(calls) == 1
    clock.now = 404
    assert worker.robots_allowed(HOST, '/events') is False
    assert len(calls) == 2


def test_robots_admission_uses_remaining_source_budget_not_five_second_network_cap(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\nCrawl-delay: 10\n')
    worker._robots_delays[HOST] = 10
    worker._publisher_next[HOST] = 110

    assert worker.robots_allowed(HOST, '/events', deadline_at=125) is True
    assert clock.sleeps == [10]
    assert calls == [('https://' + HOST + '/robots.txt', 5)]
    assert worker._publisher_next[HOST] == 120


def test_robots_network_timeout_shrinks_to_remaining_enclosing_budget(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\n')
    worker._publisher_next[HOST] = 103
    assert worker.robots_allowed(HOST, '/events', deadline_at=106) is True
    assert calls == [('https://' + HOST + '/robots.txt', 3)]


def test_expired_source_budget_does_not_issue_a_robots_request(monkeypatch, clock):
    calls = robots_origin(monkeypatch)
    with pytest.raises(worker.PreviewError, match='^source_fetch_deadline$'):
        worker.robots_allowed(HOST, '/events', deadline_at=99)
    assert calls == []


def test_late_wakeup_cannot_start_robots_after_enclosing_deadline(monkeypatch, clock):
    calls = robots_origin(monkeypatch)
    worker._publisher_next[HOST] = 103
    monkeypatch.setattr(worker, 'sleep', lambda _: setattr(clock, 'now', 107))
    with pytest.raises(worker.PreviewError, match='^source_fetch_deadline$'):
        worker.robots_allowed(HOST, '/events', deadline_at=106)
    assert calls == []


def test_late_wakeup_cannot_start_calendar_after_enclosing_deadline(monkeypatch, clock):
    monkeypatch.setattr(worker, 'validate_public_dns', Mock())
    monkeypatch.setattr(worker, 'robots_allowed', Mock(return_value=True))
    session, _ = calendar_origin(monkeypatch)
    worker._publisher_next[HOST] = 103
    monkeypatch.setattr(worker, 'sleep', lambda _: setattr(clock, 'now', 107))
    with pytest.raises(worker.PreviewError, match='^source_fetch_deadline$'):
        worker.fetch_publisher(URL, 'text/html', respect_robots=True, deadline_at=106)
    session.get.assert_not_called()


def test_calendar_can_use_valid_source_budget_after_robots_and_pacing(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\nCrawl-delay: 10\n')
    session, _ = calendar_origin(monkeypatch)
    worker._robots_delays[HOST] = 10
    worker._publisher_next[HOST] = 110

    assert worker.fetch_publisher(URL, 'text/html', respect_robots=True, deadline_at=136) == '<p>public calendar</p>'
    assert clock.sleeps == [10, 10]
    assert clock.now == 120
    assert len(calls) == 1 and session.get.call_count == 1
    assert session.get.call_args.kwargs['timeout'] == (3, 7)


def test_network_cap_still_applies_after_admission(monkeypatch, clock):
    monkeypatch.setattr(worker, 'validate_public_dns', Mock())
    monkeypatch.setattr(worker, 'robots_allowed', Mock(return_value=True))
    worker._publisher_next[HOST] = 110

    def chunks():
        clock.now = 129  # 19 seconds after the admitted request began.
        yield b'late body'

    session, response = calendar_origin(monkeypatch, chunks=chunks)
    with pytest.raises(worker.PreviewError, match='^source_fetch_deadline$'):
        worker.fetch_publisher(URL, 'text/html', respect_robots=True, deadline_at=150)
    assert clock.sleeps == [10]
    session.get.assert_called_once()
    response.close.assert_called_once()


def test_known_delay_defers_without_request_then_warm_retry_resumes(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\nCrawl-delay: 60\n')
    session, _ = calendar_origin(monkeypatch)
    with capture_publisher_pacing() as first:
        with pytest.raises(worker.PreviewError, match='^publisher_pacing_deferred$'):
            worker.fetch_publisher(URL, 'text/html', respect_robots=True, deadline_at=136)
    assert first['crawl_delay_seconds'] == 60
    assert worker._publisher_next[HOST] == 160
    assert len(calls) == 1
    session.get.assert_not_called()
    assert clock.sleeps == []

    clock.now = 161
    with capture_publisher_pacing() as second:
        assert worker.fetch_publisher(URL, 'text/html', respect_robots=True, deadline_at=197) == '<p>public calendar</p>'
    assert second['crawl_delay_seconds'] == 60
    assert len(calls) == 1 and session.get.call_count == 1


def test_lost_policy_cache_does_not_bypass_newly_observed_long_delay(monkeypatch, clock):
    calls = robots_origin(monkeypatch, b'User-agent: *\nAllow: /\nCrawl-delay: 60\n',
                          b'User-agent: *\nAllow: /\nCrawl-delay: 60\n')
    session, _ = calendar_origin(monkeypatch)
    for now in (100, 161):
        clock.now = now
        worker._robots_cache.clear()
        with pytest.raises(worker.PreviewError, match='^publisher_pacing_deferred$'):
            worker.fetch_publisher(URL, 'text/html', respect_robots=True, deadline_at=now+36)
    assert len(calls) == 2
    session.get.assert_not_called()


def test_pacing_diagnostic_is_distinct_from_http_and_robots_rejections():
    assert failure_details('publisher_pacing_deferred', expected_source_error=True, phase='collection') == {
        'failure_scope': 'source', 'error_kind': 'pacing', 'error_code': 'publisher_pacing_deferred'}
    for code in ('publisher_rate_limited', 'publisher_http_429'):
        assert failure_details(code, expected_source_error=True, phase='collection')['error_kind'] == 'transient'
    assert failure_details('robots_denied', expected_source_error=True, phase='collection')['error_kind'] == 'access'
