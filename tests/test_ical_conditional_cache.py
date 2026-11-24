"""Focused no-network tests for approved iCalendar conditional body cache."""
from hashlib import sha256
from types import SimpleNamespace

import pytest

from roomquest import ical_conditional_cache as cache


URL = "https://calendar.example.org/public-events.ics"
BODY = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:example-1\r\nDTSTART:20261201T130000Z\r\n"
        "SUMMARY:Community art workshop\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
MODIFIED = "Mon, 23 Nov 2026 13:00:00 GMT"


class Snapshot:
    policy_context = "a" * 64
    context_hash = "b" * 64

    def __init__(self):
        self.recorded = []

    def record_body(self, *args, **kwargs):
        self.recorded.append((args, kwargs))


def source():
    return {"kind": "ical", "platform_adapter": "ical",
            "ical_optimization_enabled": True,
            "source_key": "municipal_mapsee_48489e8f5c906f7610d30197", "feed_url": URL}


def context():
    return {"p_category": "ical", "p_ticket": "lease-ticket"}


def saved(*, etag='"v1"', modified=MODIFIED, body=BODY):
    return {"enabled": True, "etag": etag, "last_modified": modified,
            "body": body, "body_hash": sha256(body.encode("utf-8")).hexdigest(),
            "content_type": "text/calendar; charset=utf-8"}


class RPC:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, name, args, **kwargs):
        self.calls.append((name, args))
        if name == "community_collector_read_ical_cache":
            return self.response
        if name == "community_collector_touch_ical_cache":
            return {"touched": True}
        return {"cached": True}


def make_state(response=None):
    snapshot = Snapshot()
    rpc = RPC({"enabled": True} if response is None else response)
    state = cache.ConditionalCache(source(), snapshot, context(), rpc)
    state.initialize()
    return state, snapshot, rpc


def test_etag_precedes_last_modified_and_304_replays_complete_body():
    state, snapshot, rpc = make_state(saved())
    assert state.headers(URL, "text/calendar") == {"If-None-Match": '"v1"'}
    assert state.not_modified(URL, "text/calendar", {}) == BODY
    assert len(snapshot.recorded) == 1
    args, kwargs = snapshot.recorded[0]
    assert args[2] == BODY.encode("utf-8")
    assert kwargs["encoding"] == "utf-8"
    # A reusable iCalendar source is still reparsed by the normal collector;
    # no previous recurrence/occurrence list is returned by this cache.
    assert "RRULE" not in state.candidate["body"]
    state.save_after_success()
    assert rpc.calls[-2][0] == "community_collector_touch_ical_cache"
    assert rpc.calls[-2][1]["p_body_hash"] == sha256(BODY.encode()).hexdigest()
    assert "p_body" not in rpc.calls[-2][1]
    assert rpc.calls[-1][0] == "community_collector_record_ical_http_metric"
    assert rpc.calls[-1][1]["p_outcome"] == "reused_304"


def test_last_modified_fallback():
    state, snapshot, _ = make_state(saved(etag=None))
    assert state.headers(URL, "text/calendar") == {"If-Modified-Since": MODIFIED}
    assert state.not_modified(URL, "text/calendar", {}) == BODY
    assert len(snapshot.recorded) == 1


@pytest.mark.parametrize("headers", [
    {"ETag": '"different"'},
    {"Last-Modified": "Tue, 24 Nov 2026 13:00:00 GMT"},
    {"Content-Type": "application/json"},
    {"Cache-Control": "no-store"},
    {"Vary": "Authorization"},
])
def test_contradictory_304_reverts_to_full_fetch(headers):
    state, snapshot, _ = make_state(saved())
    assert state.not_modified(URL, "text/calendar", headers) is None
    assert snapshot.recorded == []


def test_malformed_or_missing_body_never_sends_conditional_headers():
    for response in ({"enabled": False}, {"enabled": True},
                     saved(body="not calendar content"),
                     dict(saved(), body_hash="0" * 64)):
        state, _, _ = make_state(response)
        assert state.headers(URL, "text/calendar") == {}


def test_exact_url_and_accept_guard():
    state, snapshot, _ = make_state(saved())
    assert state.headers(URL + "?other=1", "text/calendar") == {}
    assert state.headers(URL, "application/json") == {}
    assert state.not_modified(URL + "?other=1", "text/calendar", {}) is None
    assert snapshot.recorded == []


def test_200_stages_cache_metadata_without_committing_before_success():
    state, _, rpc = make_state()
    state.record_body(URL, "text/calendar", BODY.encode("utf-8"), {
        "ETag": '"v2"', "Content-Type": "text/calendar; charset=utf-8",
    }, encoding="utf-8")
    assert state.candidate is not None
    assert len(rpc.calls) == 1  # Only the first read, no premature write
    state.save_after_success()
    assert len(rpc.calls) == 3
    assert rpc.calls[-2][1]["p_etag"] == '"v2"'
    assert rpc.calls[-1][0] == "community_collector_record_ical_http_metric"
    assert rpc.calls[-1][1]["p_outcome"] == "full_200"


def test_unusable_body_and_unsupported_cache_control_stay_uncached():
    state, _, rpc = make_state()
    state.record_body(URL, "text/calendar", BODY.encode("utf-8"),
                      {"ETag": '"v2"', "Cache-Control": "no-store",
                       "Content-Type": "text/calendar"}, encoding="utf-8")
    assert state.candidate is None
    state.save_after_success()
    # A successful full download can be counted even if Cache-Control
    # prevents storage of its body. No cache-save RPC should be attempted.
    assert len(rpc.calls) == 2
    assert rpc.calls[-1][0] == "community_collector_record_ical_http_metric"
    assert rpc.calls[-1][1]["p_outcome"] == "full_200"
    state.record_body(URL, "text/calendar", b"\xff\xfe",
                      {"ETag": '"v2"', "Content-Type": "text/calendar"},
                      encoding="utf-8")
    assert state.candidate is None



def test_conditional_200_is_download_not_a_304():
    state, _, rpc = make_state(saved())
    assert state.headers(URL, "text/calendar") == {"If-None-Match": '"v1"'}
    state.record_body(URL, "text/calendar", BODY.encode("utf-8"), {
        "ETag": '"v2"', "Content-Type": "text/calendar; charset=utf-8",
    }, encoding="utf-8")
    state.save_after_success()
    assert rpc.calls[-1][1]["p_outcome"] == "conditional_200"


def test_unusable_304_then_full_200_counts_only_fallback():
    state, _, rpc = make_state(saved())
    assert state.headers(URL, "text/calendar") == {"If-None-Match": '"v1"'}
    assert state.not_modified(URL, "text/calendar", {"ETag": '"changed"'}) is None
    state.record_body(URL, "text/calendar", BODY.encode("utf-8"), {
        "ETag": '"changed"', "Content-Type": "text/calendar; charset=utf-8",
    }, encoding="utf-8")
    state.save_after_success()
    assert rpc.calls[-1][0] == "community_collector_record_ical_http_metric"
    assert rpc.calls[-1][1]["p_outcome"] == "fallback_200"


def test_no_http_response_is_not_falsely_counted():
    state, _, rpc = make_state(saved())
    state.save_after_success()
    assert len(rpc.calls) == 1


def test_metric_rpc_failures_do_not_change_accepted_collection():
    snapshot = Snapshot()
    class MetricFails(RPC):
        def __call__(self, name, args, **kwargs):
            if name == "community_collector_record_ical_http_metric":
                raise RuntimeError("metrics temporarily unavailable")
            return super().__call__(name, args, **kwargs)
    rpc = MetricFails({"enabled": True})
    state = cache.ConditionalCache(source(), snapshot, context(), rpc)
    state.initialize()
    state.record_body(URL, "text/calendar", BODY.encode("utf-8"), {
        "ETag": '"v1"', "Content-Type": "text/calendar; charset=utf-8",
    }, encoding="utf-8")
    state.save_after_success()
    assert any(name == "community_collector_save_ical_cache" for name, _ in rpc.calls)



def test_identical_200_refreshes_validator_without_resending_body():
    state, _, rpc = make_state(saved())
    assert state.headers(URL, "text/calendar") == {"If-None-Match": '"v1"'}
    state.record_body(URL, "text/calendar", BODY.encode("utf-8"), {
        "ETag": '"v2"', "Content-Type": "text/calendar; charset=utf-8",
    }, encoding="utf-8")
    state.save_after_success()
    assert [name for name, _ in rpc.calls] == [
        "community_collector_read_ical_cache",
        "community_collector_touch_ical_cache",
        "community_collector_record_ical_http_metric",
    ]
    assert rpc.calls[1][1]["p_etag"] == '"v2"'
    assert "p_body" not in rpc.calls[1][1]


def test_changed_200_sends_new_body_once():
    state, _, rpc = make_state(saved())
    changed = BODY.replace("Community art workshop", "Changed community workshop")
    state.record_body(URL, "text/calendar", changed.encode("utf-8"), {
        "ETag": '"v3"', "Content-Type": "text/calendar; charset=utf-8",
    }, encoding="utf-8")
    state.save_after_success()
    assert [name for name, _ in rpc.calls] == [
        "community_collector_read_ical_cache",
        "community_collector_save_ical_cache",
        "community_collector_record_ical_http_metric",
    ]
    assert rpc.calls[1][1]["p_body"] == changed


def test_rejected_metadata_touch_falls_back_to_full_save():
    class RejectedTouchRPC(RPC):
        def __call__(self, name, args, **kwargs):
            if name == "community_collector_touch_ical_cache":
                self.calls.append((name, args))
                return {"touched": False}
            return super().__call__(name, args, **kwargs)

    rpc = RejectedTouchRPC(saved())
    state = cache.ConditionalCache(source(), Snapshot(), context(), rpc)
    state.initialize()
    state.headers(URL, "text/calendar")
    assert state.not_modified(URL, "text/calendar", {}) == BODY
    state.save_after_success()
    assert [name for name, _ in rpc.calls] == [
        "community_collector_read_ical_cache",
        "community_collector_touch_ical_cache",
        "community_collector_save_ical_cache",
        "community_collector_record_ical_http_metric",
    ]
    assert rpc.calls[2][1]["p_body"] == BODY


def test_failed_metadata_touch_is_optional_and_falls_back():
    class FailingTouchRPC(RPC):
        def __call__(self, name, args, **kwargs):
            if name == "community_collector_touch_ical_cache":
                raise RuntimeError("stale metadata lease")
            return super().__call__(name, args, **kwargs)

    rpc = FailingTouchRPC(saved())
    state = cache.ConditionalCache(source(), Snapshot(), context(), rpc)
    state.initialize()
    state.headers(URL, "text/calendar")
    assert state.not_modified(URL, "text/calendar", {}) == BODY
    state.save_after_success()
    assert [name for name, _ in rpc.calls] == [
        "community_collector_read_ical_cache",
        "community_collector_save_ical_cache",
        "community_collector_record_ical_http_metric",
    ]




def test_server_rollout_flag_allows_new_approved_key_without_static_code_list():
    new = {**source(), "source_key": "municipal_mapsee_0123456789abcdef01234567"}
    snapshot = Snapshot()
    rpc = RPC({"enabled": True})
    with cache.capture(new, snapshot, context(), rpc) as state:
        assert state is not None
        assert state.enabled is True
        assert [name for name, _ in rpc.calls] == ["community_collector_read_ical_cache"]


def test_false_or_missing_server_enrollment_skips_cache_read():
    snapshot = Snapshot()
    rpc = RPC(saved())
    for value in ({**source(), "ical_optimization_enabled": False},
                  {key: value for key, value in source().items()
                   if key != "ical_optimization_enabled"}):
        with cache.capture(value, snapshot, context(), rpc) as state:
            assert state is None
    assert rpc.calls == []



def test_capture_resets_context_and_non_ical_sources_cannot_cache():
    snapshot = Snapshot()
    rpc = RPC(saved())
    assert cache.conditional_headers(URL, "text/calendar") == {}
    with cache.capture(source(), snapshot, context(), rpc) as state:
        assert state is not None
        assert cache.conditional_headers(URL, "text/calendar") == {"If-None-Match": '"v1"'}
        assert cache.not_modified(URL, "text/calendar", {}) == BODY
    assert cache.conditional_headers(URL, "text/calendar") == {}
    bad = {**source(), "platform_adapter": "html"}
    with cache.capture(bad, snapshot, context(), rpc) as state:
        assert state is None
        assert cache.conditional_headers(URL, "text/calendar") == {}
    calls_before = len(rpc.calls)
    unapproved = {**source(), "source_key": "not_an_approved_pilot",
                  "ical_optimization_enabled": False}
    with cache.capture(unapproved, snapshot, context(), rpc) as state:
        assert state is None
        assert cache.conditional_headers(URL, "text/calendar") == {}
    assert len(rpc.calls) == calls_before  # No extra DB call for non-pilot ICS


def test_optional_rpc_failure_falls_back_without_blocking_collector():
    class FailingRPC:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("temporary database issue")
    state = cache.ConditionalCache(source(), Snapshot(), context(), FailingRPC())
    state.initialize()
    assert state.headers(URL, "text/calendar") == {}
    assert state.candidate is None
