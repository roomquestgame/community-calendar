"""Cold invocations retain authentic policy age, path rules, and publisher waits."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from roomquest import new_york_arts_final as arts, new_york_social_final as social
from roomquest import new_york_sources, preview_worker as worker
from roomquest import publisher_robots_checkpoint as cache
from roomquest.publisher_pacing import capture_publisher_pacing

SECRET = "test-only-private-collector-key".ljust(64, "x")
NOW = datetime(2026, 11, 14, 23, tzinfo=timezone.utc)


def source(key=social.RADEGAST):
    return dict(source_key=key, feed_url=cache.PROFILES[key][0], kind="html",
                platform_adapter="html", timezone="America/New_York")


@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch):
    fields = ("_robots_cache", "_robots_delays", "_publisher_next", "_publisher_retry_after")
    previous = {field: getattr(worker, field).copy() for field in fields}
    for field in fields:
        getattr(worker, field).clear()
    monkeypatch.setenv("ROOMQUEST_COLLECTOR_TOKEN", SECRET)
    yield
    for field in fields:
        getattr(worker, field).clear()
        getattr(worker, field).update(previous[field])


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=100.0, sleeps=[])
    def sleep(seconds):
        current.sleeps.append(seconds)
        current.now += seconds
    monkeypatch.setattr(worker, "monotonic", lambda: current.now)
    monkeypatch.setattr(worker, "sleep", sleep)
    monkeypatch.setattr(worker, "_robots_utc_now", lambda: NOW + timedelta(seconds=current.now - 100))
    monkeypatch.setattr(social, "monotonic", lambda: current.now)
    monkeypatch.setattr(arts, "monotonic", lambda: current.now)
    return current


def cold_process():
    for field in ("_robots_cache", "_robots_delays", "_publisher_next", "_publisher_retry_after"):
        getattr(worker, field).clear()


def origin(monkeypatch, clock, *policies, payload='{"data":{"count":0,"events":[]}}'):
    pending = iter(policies)
    calls, dns = [], []
    def open_request(request, timeout):
        calls.append(("robots", request.full_url, clock.now, request.get_header("User-agent")))
        answer = next(pending)
        if isinstance(answer, Exception):
            raise answer
        response = MagicMock(status=200, headers={})
        response.__enter__.return_value = response
        response.read.side_effect = lambda limit: answer[:limit]
        return response
    session = MagicMock()
    session.__enter__.return_value = session
    def get(url, **kwargs):
        calls.append(("calendar", url, clock.now, kwargs["headers"]["User-Agent"]))
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        response = MagicMock(status_code=200, headers={"Content-Type": "application/json; charset=utf-8"}, encoding="utf-8")
        response.iter_content.return_value = [payload.encode()]
        return response
    session.get.side_effect = get
    monkeypatch.setattr(worker, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    monkeypatch.setattr(worker.requests, "Session", lambda: session)
    monkeypatch.setattr(worker, "validate_public_dns", dns.append)
    return calls, dns, session


def ordinary_fetch(src, url, clock):
    return worker.fetch_publisher(url, "application/json", respect_robots=True,
        allowed_hosts=(cache.profile(src),), deadline_at=clock.now + 36)


def signed_snapshot(src=None, *, raw=b"User-agent: *\nDisallow: /private/\nCrawl-delay: 60\n", status=200,
                    now=NOW, delay=60, retry=None):
    src = src or source()
    evidence = cache.response_evidence(cache.profile(src), raw, status, now=now)
    return cache.seal(src, evidence, secret=SECRET, now=now,
        not_before=now + timedelta(seconds=delay),
        retry_after_until=now + timedelta(seconds=retry) if retry else None)


def test_three_profiles_are_exact_and_match_existing_adapters():
    assert set(cache.PROFILES) == {social.RADEGAST, arts.TRANSIT, arts.FLUSHING}
    for key, (url, host) in cache.PROFILES.items():
        module = social if key == social.RADEGAST else arts
        assert module.SOURCES[key] == (url, "html", "html")
        assert module.ALLOWED_HOSTS[key] == (host,)
        assert cache.profile(source(key), (host,)) == host
        for change in ({"feed_url": url + "?other=1"}, {"kind": "json"},
                       {"timezone": "UTC"}, {"source_key": "another_source"}):
            assert cache.profile({**source(key), **change}) is None
        assert cache.profile(source(key), (host, "other.example")) is None


def test_cold_resume_after_sixty_seconds_keeps_original_policy_expiry(monkeypatch, clock):
    src, host = source(), cache.profile(source())
    calls, dns, session = origin(monkeypatch, clock, b"User-agent: *\nDisallow: /private/\nCrawl-delay: 60\n")
    with capture_publisher_pacing() as first:
        assert worker._checkpoint_publisher_ready(src, social.RADEGAST_API + "1", 136) is False
    assert first["crawl_delay_seconds"] == 60
    assert session.get.call_count == 0 and len(calls) == 1
    snapshot = worker._checkpoint_robots_snapshot(src)
    assert snapshot["expires_at"] == (NOW + timedelta(seconds=300)).isoformat()
    cold_process()
    clock.now = 161
    assert worker._restore_checkpoint_robots(src, snapshot)
    assert worker._robots_cache[host][0] == 400
    with capture_publisher_pacing() as resumed:
        assert worker._checkpoint_publisher_ready(src, social.RADEGAST_API + "1", 197)
        ordinary_fetch(src, social.RADEGAST_API + "1", clock)
    assert resumed["crawl_delay_seconds"] == 60
    next_snapshot = worker._checkpoint_robots_snapshot(src)
    assert next_snapshot["fetched_at"] == snapshot["fetched_at"]
    assert next_snapshot["expires_at"] == snapshot["expires_at"]
    cold_process()
    clock.now = 222
    assert worker._restore_checkpoint_robots(src, next_snapshot)
    ordinary_fetch(src, social.RADEGAST_API + "2", clock)
    assert [call[0] for call in calls] == ["robots", "calendar", "calendar"]
    assert calls[1][2] - calls[0][2] >= 60 and calls[2][2] - calls[1][2] >= 60
    assert calls[0][3] == cache.ROBOTS_USER_AGENT
    assert all(call[3] == cache.PUBLISHER_USER_AGENT for call in calls[1:])
    assert len(dns) >= 4 and set(dns) == {host}
    assert clock.sleeps == []


def test_restored_policy_still_decides_every_path(monkeypatch, clock):
    calls, _, session = origin(monkeypatch, clock)
    clock.now = 161
    assert worker._restore_checkpoint_robots(source(), signed_snapshot())
    assert worker.robots_allowed(cache.profile(source()), "/public/event")
    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
        ordinary_fetch(source(), "https://radegasthall.com/private/event", clock)
    assert calls == [] and session.get.call_count == 0


@pytest.mark.parametrize("elapsed", [300, 301, 3600])
def test_expired_snapshot_fetches_changed_native_rules_and_denies(monkeypatch, clock, elapsed):
    snapshot = signed_snapshot()
    clock.now = 100 + elapsed
    calls, _, session = origin(monkeypatch, clock, b"User-agent: *\nDisallow: /wp-admin/\nCrawl-delay: 60\n")
    assert worker._restore_checkpoint_robots(source(), snapshot) is False
    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
        ordinary_fetch(source(), social.RADEGAST_API + "1", clock)
    assert len(calls) == 1 and calls[0][0] == "robots" and session.get.call_count == 0


@pytest.mark.parametrize("field,value", [
    ("body_b64", base64.b64encode(b"User-agent: *\nAllow: /\n").decode()),
    ("host", "other.example"), ("source_key", arts.TRANSIT),
    ("feed_url", "https://radegasthall.com/events"), ("response_status", 404),
    ("permission_user_agent", "AnotherCrawler"), ("robots_user_agent", "Mozilla/5.0"),
    ("publisher_user_agent", "Mozilla/5.0"), ("signature", "0" * 64),
    ("expires_at", (NOW + timedelta(seconds=301)).isoformat()),
    ("not_before", NOW.isoformat()), ("extra", "publisher supplied policy"),
])
def test_tampered_or_foreign_metadata_never_restores(field, value):
    snapshot = signed_snapshot()
    snapshot[field] = value
    assert cache.restore(source(), snapshot, secret=SECRET, now=NOW + timedelta(seconds=61)) is None


def test_cross_source_and_rotated_key_do_not_grant_policy():
    snapshot = signed_snapshot()
    assert cache.restore(source(arts.TRANSIT), snapshot, secret=SECRET, now=NOW) is None
    assert cache.restore(source(), snapshot, secret="y" * 64, now=NOW) is None
    assert cache.restore(source(), snapshot, secret="", now=NOW) is None
    assert cache.restore(source(), None, secret=SECRET, now=NOW) is None
    assert SECRET not in json.dumps(snapshot)


def test_invalid_snapshot_falls_back_to_normal_fetch_without_stale_allow(monkeypatch, clock):
    snapshot = signed_snapshot()
    snapshot["signature"] = "0" * 64
    calls, _, session = origin(monkeypatch, clock, b"User-agent: *\nDisallow: /\n")
    assert worker._restore_checkpoint_robots(source(), snapshot) is False
    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
        ordinary_fetch(source(), social.RADEGAST_API + "1", clock)
    assert len(calls) == 1 and session.get.call_count == 0


def test_future_timestamps_oversized_and_error_policies_are_not_cacheable():
    assert cache.restore(source(), signed_snapshot(now=NOW + timedelta(seconds=1)), secret=SECRET, now=NOW) is None
    for status in (401, 403, 429, 500):
        assert signed_snapshot(status=status) is None
    assert signed_snapshot(raw=b"#" * 128001) is None
    assert cache.response_evidence("unreviewed.example", b"", 200, now=NOW) is None


@pytest.mark.parametrize("status", [404, 410])
def test_authenticated_missing_robots_response_has_same_short_ttl(status, monkeypatch, clock):
    snapshot = signed_snapshot(status=status, raw=b"", delay=1)
    clock.now = 102
    assert worker._restore_checkpoint_robots(source(), snapshot)
    assert worker.robots_allowed(cache.profile(source()), "/public")
    assert worker._robots_delays[cache.profile(source())] == 1
    assert worker._robots_cache[cache.profile(source())][0] == 400


def test_existing_stronger_wait_and_newer_deny_policy_survive_restore(monkeypatch, clock):
    host = cache.profile(source())
    calls, _, session = origin(monkeypatch, clock, b"User-agent: *\nDisallow: /wp-admin/\nCrawl-delay: 90\n")
    clock.now = 161
    assert worker.robots_allowed(host, "/wp-admin/example") is False
    worker._publisher_next[host] = 500
    worker._publisher_retry_after[host] = 500
    assert worker._restore_checkpoint_robots(source(), signed_snapshot())
    assert worker._publisher_next[host] == worker._publisher_retry_after[host] == 500
    assert worker._robots_delays[host] == 90
    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
        ordinary_fetch(source(), social.RADEGAST_API + "1", clock)
    assert len(calls) == 1 and session.get.call_count == 0


def test_newer_authenticated_deny_replaces_older_local_allow_without_shortening_wait(monkeypatch, clock):
    src, host = source(), cache.profile(source())
    calls, _, session = origin(monkeypatch, clock, b"User-agent: *\nAllow: /\nCrawl-delay: 1\n")
    assert worker.robots_allowed(host, "/wp-admin/example") is True
    original_expiry = worker._robots_cache[host][0]
    snapshot = signed_snapshot(raw=b"User-agent: *\nDisallow: /wp-admin/\nCrawl-delay: 60\n",
                               now=NOW + timedelta(seconds=30))
    clock.now = 161
    worker._publisher_next[host] = worker._publisher_retry_after[host] = 500
    assert worker._restore_checkpoint_robots(src, snapshot)
    assert worker._publisher_next[host] == worker._publisher_retry_after[host] == 500
    assert worker._robots_delays[host] == 60
    assert original_expiry == 400 and worker._robots_cache[host][0] == 430
    with pytest.raises(worker.PreviewError, match="^robots_denied$"):
        ordinary_fetch(src, social.RADEGAST_API + "1", clock)
    assert len(calls) == 1 and session.get.call_count == 0


def test_transit_orphan_delay_survives_cold_restore(monkeypatch, clock):
    src = source(arts.TRANSIT)
    snapshot = signed_snapshot(src, raw=b"Crawl-delay: 10\nUser-agent: *\nDisallow: /private/\n", delay=10)
    clock.now = 111
    assert worker._restore_checkpoint_robots(src, snapshot)
    assert worker._robots_delays[cache.profile(src)] == 10
    assert worker.robots_allowed(cache.profile(src), "/program/safe")
    assert not worker.robots_allowed(cache.profile(src), "/private/event")


def test_adapter_data_cannot_inject_or_retain_cache_authority():
    original = {"cursor": 3, cache.FIELD: {"body_b64": "publisher-supplied"}}
    detached, found = cache.detach(original)
    assert cache.FIELD not in detached and found == original[cache.FIELD]
    assert cache.attach(original, None) == {"cursor": 3}
    trusted = signed_snapshot()
    attached = cache.attach(original, trusted)
    assert attached[cache.FIELD] == trusted and original[cache.FIELD] != trusted
    attached[cache.FIELD]["signature"] = "x"
    assert trusted["signature"] != "x"
    large = {"body": "x" * (cache.MAX_CHECKPOINT_BYTES - 30)}
    assert cache.FIELD not in cache.attach(large, trusted)


def test_zero_event_bootstrap_is_pending_and_preserves_generation_on_resume(clock):
    fetch = Mock()
    first = social.collect_chunk(source(), fetch, now=NOW, deadline_at=136, prepare_publisher=lambda _: False)
    state = first["checkpoint"]
    assert first["complete"] is False and first["events"] == []
    assert state["phase"] == "robots" and state["cursor"] == state["manifest_count"] == 0
    fetch.assert_not_called()
    new_york_sources.validate_checkpoint(source(), state, now=NOW)
    social._radegast_checkpoint(state, NOW)
    clock.now = 161
    second = social.collect_chunk(source(), Mock(return_value='{"data":{"count":0,"events":[]}}'),
        now=NOW + timedelta(seconds=61), deadline_at=197, checkpoint=state, prepare_publisher=lambda _: True)
    assert second["complete"] is True and second["checkpoint"]["phase"] == "events"
    assert second["checkpoint"]["started_at"] == state["started_at"]
    assert second["checkpoint"]["window_start"] == state["window_start"]


@pytest.mark.parametrize("change", [{"phase": "events"}, {"phase": "unknown"},
    {"cursor": 1}, {"next_page": 2}, {"restarts": 1}, {"seen_ids": [5]}, {"events": [{}]}, {"diagnostics": [{}]}])
def test_bootstrap_tampering_is_rejected_before_admission_or_fetch(clock, change):
    first = social.collect_chunk(source(), Mock(), now=NOW, deadline_at=136, prepare_publisher=lambda _: False)
    changed = {**first["checkpoint"], **change}
    fetch, prepare = Mock(), Mock()
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        social.collect_chunk(source(), fetch, now=NOW, deadline_at=136, checkpoint=changed, prepare_publisher=prepare)
    fetch.assert_not_called()
    prepare.assert_not_called()


def test_worker_persists_transport_bootstrap_and_cold_resume_through_existing_rpc(monkeypatch, clock):
    calls, _, session = origin(monkeypatch, clock, b"User-agent: *\nDisallow: /private/\nCrawl-delay: 60\n")
    state = {"revision": 0, "checkpoint": None}
    written = []
    def rpc(operation, payload):
        if operation.endswith("read_fetch_checkpoint"):
            return deepcopy(state)
        assert operation.endswith("write_fetch_checkpoint")
        assert payload["p_expected_revision"] == state["revision"]
        assert payload["p_publisher_crawl_delay_seconds"] == 60
        assert payload["p_publisher_wait_unbounded"] is False
        state["revision"] += 1
        state["checkpoint"] = deepcopy(payload["p_checkpoint"])
        written.append(deepcopy(payload))
        return {"revision": state["revision"], "checkpoint_saved": True}
    monkeypatch.setattr(worker, "supabase_rpc", rpc)
    with capture_publisher_pacing() as pacing:
        first = worker._preview_new_york_chunk(source(), pacing, deadline_at=145,
            collection_context={"p_category": "html", "p_ticket": "lease-bound-test-ticket"})
    assert first == {"fetch_pending": True}
    assert state["checkpoint"]["phase"] == "robots" and cache.FIELD in state["checkpoint"]
    assert state["checkpoint"]["events"] == [] and session.get.call_count == 0
    original_start = state["checkpoint"]["started_at"]
    cold_process()
    clock.now = 161
    with capture_publisher_pacing() as pacing:
        second = worker._preview_new_york_chunk(source(), pacing, deadline_at=206,
            collection_context={"p_category": "html", "p_ticket": "next-lease-bound-test-ticket"})
    assert second["p_error"] is None and second["p_future_count"] == 0
    assert state["checkpoint"]["phase"] == "events" and state["checkpoint"]["started_at"] == original_start
    assert state["revision"] == 2 and [item[0] for item in calls] == ["robots", "calendar"]
    assert written[0]["p_checkpoint"][cache.FIELD]["expires_at"] == written[1]["p_checkpoint"][cache.FIELD]["expires_at"]


def test_existing_radegast_prefix_without_metadata_survives_robots_only_deferral(monkeypatch, clock):
    current = datetime.now(timezone.utc)
    start = (current + timedelta(days=4)).astimezone(social.ZoneInfo(social.ZONE))
    def normalized(title, start, end, venue, address, city, url, identity, **kwargs):
        return dict(id=identity, title=title, starts_at=start.isoformat(), ends_at=end.isoformat(),
            venue_name=venue, venue_address=address, venue_city=city, event_url=url,
            lat=kwargs["lat"], lng=kwargs["lng"])
    monkeypatch.setattr(social, "record", normalized)
    native = [dict(id=index, name="Band " + str(index), status="approved", show=index <= 9,
        description="Complete artist biography. " * 120, locationId=4, customLocation=None, timeZone=None,
        periods=[dict(id=index + 1000, eventId=index, periodStart=start.strftime("%Y-%m-%d %H:%M:%S"),
                      periodEnd=(start + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"))])
        for index in range(1, 13)]
    first = social.collect_chunk(source(), Mock(return_value=json.dumps({"data": {"count": 13, "events": native}})), now=current)
    legacy = first["checkpoint"]
    legacy.pop("phase")
    assert legacy["cursor"] == 12 and len(legacy["events"]) == 9
    before = deepcopy(legacy)
    calls, _, session = origin(monkeypatch, clock, b"User-agent: *\nDisallow:\nCrawl-delay: 60\n")
    writes = []
    def rpc(operation, payload):
        if operation.endswith("read_fetch_checkpoint"):
            return {"revision": 7, "checkpoint": deepcopy(legacy)}
        writes.append(payload)
        return {"revision": 8, "checkpoint_saved": True}
    monkeypatch.setattr(worker, "supabase_rpc", rpc)
    with capture_publisher_pacing() as pacing:
        result = worker._preview_new_york_chunk(source(), pacing, deadline_at=145,
            collection_context={"p_category": "html", "p_ticket": "existing-generation-lease"})
    assert result == {"fetch_pending": True} and session.get.call_count == 0
    assert len(calls) == 1 and calls[0][0] == "robots"
    after, snapshot = cache.detach(writes[0]["p_checkpoint"])
    assert after == before and legacy == before
    assert cache.restore(source(), snapshot, secret=SECRET, now=worker._robots_utc_now())


@pytest.mark.parametrize("key", [arts.TRANSIT, arts.FLUSHING])
def test_existing_detail_chunks_strip_then_reseal_only_transport_cache(monkeypatch, clock, key):
    src = source(key)
    snapshot = signed_snapshot(src, raw=b"User-agent: *\nDisallow: /private/\nCrawl-delay: 10\n", delay=10)
    current = datetime.now(timezone.utc)
    state = dict(version=1, source_key=key, started_at=current.isoformat(),
        window_start=current.astimezone(arts.ZoneInfo(arts.ZONE)).date().isoformat(),
        manifest_hash="a" * 64, manifest_count=2, cursor=0, events=[], diagnostics=[], **{cache.FIELD: snapshot})
    calls, _, _ = origin(monkeypatch, clock)
    clock.now = 111
    writes = []
    def rpc(operation, payload):
        if operation.endswith("read_fetch_checkpoint"):
            return {"revision": 2, "checkpoint": deepcopy(state)}
        writes.append(payload)
        return {"revision": 3, "checkpoint_saved": True}
    def adapter(source_arg, fetch, *, checkpoint, deadline_at):
        assert cache.FIELD not in checkpoint
        fetch(src["feed_url"], "text/html")
        checkpoint[cache.FIELD] = {"body_b64": "publisher-injection", "signature": "0" * 64}
        return dict(complete=False, events=[], checkpoint=checkpoint)
    monkeypatch.setattr(worker, "supabase_rpc", rpc)
    monkeypatch.setattr(arts, "collect_chunk", adapter)
    with capture_publisher_pacing() as pacing:
        result = worker._preview_new_york_chunk(src, pacing, deadline_at=156,
            collection_context={"p_category": "html", "p_ticket": "lease-bound-test-ticket"})
    assert result == {"fetch_pending": True} and [call[0] for call in calls] == ["calendar"]
    stored = writes[0]["p_checkpoint"][cache.FIELD]
    assert cache.restore(src, stored, secret=SECRET, now=worker._robots_utc_now()) is not None
    assert stored["fetched_at"] == snapshot["fetched_at"] and stored["expires_at"] == snapshot["expires_at"]


def slow_calendar_fixture(key):
    from tests.test_new_york_arts_final import transit_fetch, fth_detail
    if key == arts.TRANSIT:
        fetch, events = transit_fetch(2)
        return fetch, events[1]["url"], lambda url: url.startswith(arts.TRANSIT_API)
    items = [(f"program-{index}", f"Family program {index}") for index in (1, 2)]
    listing = "".join('<div class="show-item"><div class="show-title">' + title +
        '</div><div class="show-time">Dec 5, 2026</div><div class="show-buttons"><a href="' +
        'https://www.flushingtownhall.org/show-details/' + slug + '">Details</a></div></div>'
        for slug, title in items)
    details = {'https://www.flushingtownhall.org/show-details/' + slug: fth_detail(title=title) for slug, title in items}
    def fetch(url, accept):
        return listing if url == arts.SOURCES[key][0] else details[url]
    return fetch, list(details)[1], lambda url: url == arts.SOURCES[key][0]


@pytest.mark.parametrize("key", [arts.TRANSIT, arts.FLUSHING])
@pytest.mark.parametrize("stage", ["detail", "final_manifest"])
@pytest.mark.parametrize("code", ["publisher_pacing_deferred", "source_fetch_deadline"])
def test_policy_refresh_budget_pause_retains_private_native_progress_then_rechecks(monkeypatch, clock, key, stage, code):
    from tests.test_new_york_arts import fake_record
    monkeypatch.setattr(arts, "record", fake_record)
    implementation, second_detail, is_manifest = slow_calendar_fixture(key)
    manifests = [0]
    def interrupted(url, accept):
        if is_manifest(url):
            manifests[0] += 1
        if (stage == "detail" and url == second_detail) or (stage == "final_manifest" and is_manifest(url) and manifests[0] > 1):
            raise worker.PreviewError(code)
        return implementation(url, accept)
    first = arts.collect_chunk(source(key), interrupted, now=NOW, deadline_at=1000)
    state = first["checkpoint"]
    assert first["complete"] is False and first["events"] == [] and state["manifest_verified"] is False
    assert state["cursor"] == len(state["events"]) == (1 if stage == "detail" else 2)
    arts._checkpoint(key, state, NOW)
    before = deepcopy(state)
    resumed = arts.collect_chunk(source(key), implementation, checkpoint=state, now=NOW, deadline_at=1000)
    assert resumed["complete"] is True and len(resumed["events"]) == 2
    assert resumed["checkpoint"]["manifest_verified"] is True and state == before
    assert resumed["checkpoint"]["started_at"] == before["started_at"]
    assert all(row["description"] and row["venue_address"] for row in resumed["events"])
    for old in before["events"]:
        assert old == next(row for row in resumed["events"] if row["id"] == old["id"])


@pytest.mark.parametrize("key", [arts.TRANSIT, arts.FLUSHING])
@pytest.mark.parametrize("code", ["robots_denied", "publisher_http_403", "publisher_rate_limited"])
def test_access_and_http_failures_are_never_reclassified_as_checkpoint_pauses(monkeypatch, clock, key, code):
    from tests.test_new_york_arts import fake_record
    monkeypatch.setattr(arts, "record", fake_record)
    implementation, second_detail, _ = slow_calendar_fixture(key)
    def blocked(url, accept):
        if url == second_detail:
            raise worker.PreviewError(code)
        return implementation(url, accept)
    with pytest.raises(worker.PreviewError, match="^" + code + "$"):
        arts.collect_chunk(source(key), blocked, now=NOW, deadline_at=1000)


def test_transport_pause_scope_does_not_change_other_calendar_collectors():
    for key in (arts.MAKER, arts.BPL):
        for code in ("publisher_pacing_deferred", "source_fetch_deadline"):
            assert not arts._bounded_transport_pause(key, worker.PreviewError(code))
    assert not arts._bounded_transport_pause(arts.TRANSIT, ValueError("publisher_pacing_deferred"))
