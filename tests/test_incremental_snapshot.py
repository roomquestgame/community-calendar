"""Offline integration of complete manifests, HTTP validation and lease fallback."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from threading import Lock
from unittest.mock import Mock, patch

import pytest

from roomquest import category_worker, incremental_snapshot as inc, preview_worker as worker

TICKET = {"p_category": "ical", "p_ticket": "private-test-ticket"}
BASELINE_ID = "f994cffb-1af2-4d86-a42e-02f39e15d19c"
POLICY = "a" * 64
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def source(category="ical"):
    kind, adapter = {"ical": ("ical", "ical"), "wordpress": ("json", "wordpress"),
                     "localist": ("json", "localist"), "chambermate": ("json", "chambermate"),
                     "chambermaster": ("xml", "growthzone")}[category]
    return {"source_id": 123, "source_key": "municipal_chambermaster_fixture" if category == "chambermaster" else "fixture",
            "feed_url": "https://publisher.example/api/events", "kind": kind,
            "platform_adapter": adapter, "timezone": "UTC", "action": "collect",
            "incremental_snapshot": {"version": 1, "policy_context": POLICY,
                                     "baseline_id": None, "events": [], "requests": []}}


def event(identity, **extra):
    return {"id": str(identity), "title": "Event " + str(identity),
            "starts_at": (NOW + timedelta(days=2)).isoformat(),
            "ends_at": (NOW + timedelta(days=2, hours=1)).isoformat(),
            "venue_name": "Library", "venue_address": "1 Main St", "venue_city": "Town",
            "lat": 35.7, "lng": -78.6, "event_url": "https://publisher.example/event/" + str(identity),
            "category": "Community", "reason": None, **extra}


def preview(rows, src):
    return {"p_source_key": src["source_key"], "p_events": deepcopy(rows), "p_samples": deepcopy(rows[:10]),
            "p_future_count": len(rows), "p_venue_count": sum(r.get("lat") is not None for r in rows),
            "p_error": None}


def accepted_baseline(src, rows, category="ical", requests=None):
    with inc.capture_snapshot(src, {**TICKET, "p_category": category}) as snapshot:
        plan = snapshot.plan(rows, preview(rows, src))
        receipt = snapshot.receipt(plan)
    src = deepcopy(src)
    src["incremental_snapshot"] = {**receipt, "baseline_id": BASELINE_ID,
        "requests": requests or receipt["requests"], "window_day": NOW.date().isoformat()}
    return src


class Database:
    def __init__(self):
        self.calls = []
        self.changed = []

    def __call__(self, path, payload, **_kwargs):
        self.calls.append((path, deepcopy(payload)))
        if path == "community_collector_stage_incremental":
            self.changed.extend(payload["p_events"])
            return {"accepted": True, "staged": len(payload["p_events"])}
        if path == "community_collector_complete_incremental":
            return {"accepted": True, "publication_required": bool(self.changed),
                    "changed": len(self.changed), "confirmed": len(payload["p_receipt"]["events"]),
                    "unchanged": not self.changed}
        if path == "community_collector_record_staged_events":
            return len(payload["p_events"])
        return True

    @property
    def completions(self):
        return [payload for path, payload in self.calls if path == "community_collector_complete_incremental"]


def process(src, rows, db=None, category="ical", output=None):
    db = db or Database()
    with patch.object(worker, "preview_source", return_value=output or preview(rows, src)), \
            patch.object(worker, "supabase_rpc", side_effect=db):
        result = worker._process_claimed_source(src, collection_context={**TICKET, "p_category": category})
    return result, db


@pytest.mark.parametrize("category", ["ical", "localist", "wordpress", "chambermate", "chambermaster"])
def test_unchanged_complete_manifest_skips_staging_and_publication(category):
    rows = [event(i) for i in range(500)]
    src = accepted_baseline(source(category), rows, category)
    # A previous request day does not invalidate normalized event evidence.
    src["incremental_snapshot"]["window_day"] = (NOW - timedelta(days=4)).date().isoformat()
    result, db = process(src, rows, category=category)
    assert result == {"complete": 1, "failed": 0, "staged": 0, "publication_required": False}
    assert [path for path, _ in db.calls] == ["community_collector_complete_incremental"]
    receipt = db.completions[0]["p_receipt"]
    assert len(receipt["events"]) == 500 and receipt["not_modified"] is False


def test_first_snapshot_has_bounded_changed_batches_and_full_membership():
    rows = [event(i) for i in range(45)]
    result, db = process(source(), rows)
    assert result["staged"] == 45 and result.get("publication_required") is True
    assert [len(payload["p_events"]) for path, payload in db.calls if path.endswith("stage_incremental")] == [20, 20, 5]
    assert len(db.completions[0]["p_receipt"]["events"]) == 45
    assert all(item["hash"] == inc.fingerprint(item["event"]) for item in db.changed)
    assert all(payload["p_ticket"] == TICKET["p_ticket"] for _, payload in db.calls)


def test_edit_addition_and_withdrawal_preserve_complete_membership():
    old = [event("same"), event("edit"), event("withdrawn")]
    rows = [old[0], {**old[1], "venue_address": "2 Changed St", "description": "Updated"}, event("new")]
    result, db = process(accepted_baseline(source(), old), rows)
    assert result["staged"] == 2
    assert {item["event"]["id"] for item in db.changed} == {"edit", "new"}
    assert {item["id"] for item in db.completions[0]["p_receipt"]["events"]} == {"same", "edit", "new"}


@pytest.mark.parametrize("change", ["source", "parser"])
def test_parser_or_source_configuration_change_requires_full_bodies(change):
    rows = [event("a")]
    src = accepted_baseline(source(), rows)
    if change == "source":
        src["timezone"] = "America/New_York"
        result, db = process(src, rows)
    else:
        with patch.object(inc, "parser_context", return_value="new-parser"):
            result, db = process(src, rows)
    assert result["staged"] == 1 and len(db.changed) == 1


@pytest.mark.parametrize("invalidated_at", ["stage", "complete"])
def test_invalidation_replays_the_full_snapshot_once_via_legacy(invalidated_at):
    rows = [event(i) for i in range(45)]
    base = Database()
    stage_count = 0

    def db(path, payload, **kwargs):
        nonlocal stage_count
        result = base(path, payload, **kwargs)
        if path.endswith("stage_incremental"):
            stage_count += 1
        if ((invalidated_at == "stage" and path.endswith("stage_incremental") and stage_count == 2)
                or (invalidated_at == "complete" and path.endswith("complete_incremental"))):
            return {"accepted": False, "requires_full": True, "reason": "snapshot_invalidated"}
        return result

    result, _ = process(source(), rows, db=db)
    legacy = [payload for path, payload in base.calls if path == "community_collector_record_staged_events"]
    assert [len(payload["p_events"]) for payload in legacy] == [20, 20, 5]
    assert result == {"complete": 1, "failed": 0, "staged": 45}
    assert base.calls[-1][0] == "community_collector_record_preview_v2"
    assert base.calls[-1][1]["p_future_count"] == 45
    assert len(base.completions) == (1 if invalidated_at == "complete" else 0)


def test_transport_or_partial_stage_failure_never_certifies_complete():
    rows = [event(i) for i in range(21)]
    base = Database()

    def db(path, payload, **kwargs):
        result = base(path, payload, **kwargs)
        if path.endswith("stage_incremental") and len(base.changed) > 20:
            raise worker.PreviewError("database_unavailable")
        return result

    result, _ = process(source(), rows, db=db)
    assert result["failed"] == 1 and not base.completions
    assert base.calls[-1][1]["p_error"] == "database_unavailable"
    assert base.calls[-1][1]["p_future_count"] == 0


@pytest.mark.parametrize("flaw", ["count", "duplicate", "empty_id", "too_many", "no_capability", "checkpoint"])
def test_unprovable_manifest_uses_legacy_without_installing_receipt(flaw):
    src, rows = source(), [event("a")]
    if flaw == "duplicate": rows *= 2
    if flaw == "empty_id": rows[0]["id"] = ""
    if flaw == "too_many": rows = [event(i) for i in range(501)]
    if flaw == "no_capability": src.pop("incremental_snapshot")
    if flaw == "checkpoint": src["fetch_checkpoint_version"] = 1
    output = preview(rows, src)
    if flaw == "count": output["p_future_count"] += 1
    _, db = process(src, rows, output=output)
    assert not db.completions and not db.changed
    assert any(path == "community_collector_record_staged_events" for path, _ in db.calls)


def test_category_skips_only_explicit_no_publication_and_always_finishes():
    src = source()
    calls = []

    def rpc(path, payload, **_kwargs):
        calls.append((path, payload))
        if path.endswith("claim_category"): return src
        if path.endswith("publish_category"): return {"outcome": "complete"}
        return True

    for flag in (False, True, None):
        calls.clear()
        result = {"complete": 1, "failed": 0, "staged": 0}
        if flag is not None: result["publication_required"] = flag
        with patch.object(category_worker, "supabase_rpc", side_effect=rpc), \
                patch.object(category_worker, "_process_claimed_source", return_value=result) as collect:
            category_worker.collect_category("ical", "ticket")
        assert collect.call_args.kwargs.get("collection_context") == {"p_category": "ical", "p_ticket": "ticket"}
        assert sum(path.endswith("publish_category") for path, _ in calls) == (0 if flag is False else 1)
        assert calls[-1][0] == "community_collector_finish_category" and calls[-1][1]["p_outcome"] == "complete"


class Response:
    def __init__(self, body="", status=200, headers=None):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.status_code = status
        self.headers = {**({"Content-Type": "text/calendar; charset=utf-8"} if status == 200 else {}), **(headers or {})}
        self.encoding = "utf-8"
        self.closed = False

    def close(self): self.closed = True
    def iter_content(self, **_kwargs): return [self.body]


def network(monkeypatch, respond):
    requests, lock = [], Lock()

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def get(self, url, **kwargs):
            with lock: requests.append((url, dict(kwargs["headers"])))
            return respond(url, kwargs["headers"])

    monkeypatch.setattr(worker.requests, "Session", Session)
    monkeypatch.setattr(worker, "validate_public_dns", Mock())
    monkeypatch.setattr(worker, "robots_allowed", Mock(return_value=True))
    monkeypatch.setattr(worker, "pace_publisher", Mock())
    return requests


def detail_cache(src, row, url, *, status="scheduled", etag='"detail-v1"'):
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot:
        with inc.detail_request(url, "text/calendar", row):
            snapshot.record_body(url, "text/calendar", b"old detail", {"ETag": etag, "Content-Type": "text/calendar; charset=utf-8"})
            snapshot.remember_detail(url, "text/calendar", {
                "kind": "chambermaster_ical_v1", "id": row["id"], "starts_at": inc.utc_start(row["starts_at"]),
                "status": status, "venue_address": "1 Main St", "lat": 35.7, "lng": -78.6})
        receipt = snapshot.receipt(snapshot.plan([row], preview([row], src)))
    return {**src, "incremental_snapshot": {**receipt, "baseline_id": BASELINE_ID, "window_day": NOW.date().isoformat()}}


def test_raw_feed_validators_are_metadata_and_never_skip_moving_window(monkeypatch):
    src = source()
    url = src["feed_url"]
    with inc.capture_snapshot(src, TICKET) as snapshot:
        snapshot.record_body(url, "text/calendar", b"feed", {"ETag": '"feed-v1"'})
        receipt = snapshot.receipt(snapshot.plan([], preview([], src)))
    src["incremental_snapshot"] = {**receipt, "baseline_id": BASELINE_ID}
    calls = network(monkeypatch, lambda *_: Response("feed", headers={"ETag": '"feed-v1"'}))
    with inc.capture_snapshot(src, TICKET) as snapshot:
        assert worker.fetch_publisher(url, "text/calendar") == "feed"
        assert "If-None-Match" not in calls[0][1]
        assert snapshot.receipt(snapshot.plan([], preview([], src)))["not_modified"] is False


def test_304_without_exact_detail_evidence_fails_closed(monkeypatch):
    calls = network(monkeypatch, lambda *_: Response(status=304))
    with inc.capture_snapshot(source(), TICKET), pytest.raises(worker.PreviewError, match="publisher_http_304"):
        worker.fetch_publisher("https://publisher.example/feed", "text/calendar")
    assert "If-None-Match" not in calls[0][1]


def test_detail_304_requires_exact_url_accept_identity_and_context(monkeypatch):
    row, src = event("42"), source("chambermaster")
    url = "https://publisher.example/events/addtocalendar/fair-42?format=ICal"
    src = detail_cache(src, row, url)
    calls = network(monkeypatch, lambda *_: Response(status=304))
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot:
        with inc.detail_request(url, "text/calendar", row):
            result = worker.fetch_publisher(url, "text/calendar", respect_robots=True)
            assert isinstance(result, inc.RevalidatedDetail) and result.evidence["id"] == "42"
            assert not snapshot.conditional_headers(url + "&changed=1", "text/calendar")
            assert not snapshot.conditional_headers(url, "application/json")
        with inc.detail_request(url, "text/calendar", {**row, "starts_at": (NOW + timedelta(days=3)).isoformat()}):
            assert not snapshot.conditional_headers(url, "text/calendar")
    assert calls[0][1]["If-None-Match"] == '"detail-v1"'
    worker.robots_allowed.assert_called_once()
    worker.pace_publisher.assert_called_once()


@pytest.mark.parametrize("validator", ['bad\r\nAuthorization: secret', "not-quoted", '"' + "x" * 512 + '"'])
def test_invalid_stored_validator_never_enters_request_headers(monkeypatch, validator):
    row, src = event("42"), source("chambermaster")
    url = "https://publisher.example/detail"
    src = detail_cache(src, row, url)
    src["incremental_snapshot"]["requests"][0]["etag"] = validator
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot, inc.detail_request(url, "text/calendar", row):
        assert snapshot.conditional_headers(url, "text/calendar") == {}


def test_normalized_detail_cache_never_crosses_redirect(monkeypatch):
    row, src = event("42"), source("chambermaster")
    url = "https://publisher.example/detail"
    src = detail_cache(src, row, url)
    calls = network(monkeypatch, lambda request, _: Response(status=302, headers={"Location": "/new-detail"}) if request == url else Response("new body"))
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}), inc.detail_request(url, "text/calendar", row):
        assert worker.fetch_publisher(url, "text/calendar", respect_robots=True) == "new body"
    assert calls[0][1]["If-None-Match"] == '"detail-v1"'
    assert "If-None-Match" not in calls[1][1]


def xml_listing(ids):
    start = (NOW + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    end = (NOW + timedelta(days=2, hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    return "<ArrayOfEventDisplay>" + "".join(
        f"<EventDisplay><EventID>{i}</EventID><Name>Fair {i}</Name><Slug>fair-{i}</Slug>"
        f"<Status>APPROVED</Status><IsAllDayEvent>false</IsAllDayEvent>"
        f"<StartDate>{start}</StartDate><EndDate>{end}</EndDate></EventDisplay>" for i in ids) + "</ArrayOfEventDisplay>"


def detail_ics(identity, *, status="CONFIRMED", address="1 Main St", start=None):
    start = start or NOW + timedelta(days=2)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            f"UID:fixture.{identity}\r\nDTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"SUMMARY:Fair\r\nSTATUS:{status}\r\nLOCATION:{address}\r\nGEO:35.7;-78.6\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")


def run_chamber(monkeypatch, src, respond):
    calls = network(monkeypatch, respond)
    db = Database()
    with patch.object(worker, "supabase_rpc", side_effect=db):
        result = worker._process_claimed_source(src, collection_context={**TICKET, "p_category": "chambermaster"})
    return result, db, calls


def test_real_chambermaster_threads_revalidate_every_detail_and_retain_cancellation(monkeypatch):
    src, ids = source("chambermaster"), ["41", "42"]
    listing = xml_listing(ids)

    def first(url, _headers):
        if url == src["feed_url"]: return Response(listing, headers={"ETag": '"listing"'})
        identity = "41" if "fair-41" in url else "42"
        return Response(detail_ics(identity, status="CANCELLED" if identity == "42" else "CONFIRMED"),
                        headers={"ETag": '"detail-' + identity + '"'})

    result, db, _ = run_chamber(monkeypatch, src, first)
    assert result["staged"] == 1
    receipt = db.completions[0]["p_receipt"]
    assert len(receipt["requests"]) == 3
    assert sorted(r["detail"]["status"] for r in receipt["requests"] if "detail" in r) == ["cancelled", "scheduled"]
    src["incremental_snapshot"] = {**receipt, "baseline_id": BASELINE_ID}

    def second(url, headers):
        if url == src["feed_url"]:
            assert "If-None-Match" not in headers
            return Response(listing, headers={"ETag": '"listing"'})
        assert headers["If-None-Match"] in ('"detail-41"', '"detail-42"')
        return Response(status=304)

    with patch("roomquest.chambermaster.Calendar.from_ical", side_effect=AssertionError("304 must reuse validated detail")):
        result, db, calls = run_chamber(monkeypatch, src, second)
    assert len(calls) == 3 and result["staged"] == 0 and result["publication_required"] is False
    assert [r["id"] for r in db.completions[0]["p_receipt"]["events"]] == ["41"]
    assert len(db.completions[0]["p_receipt"]["requests"]) == 3


def test_unchanged_listing_still_detects_changed_venue_and_cancellation(monkeypatch):
    src, listing = source("chambermaster"), xml_listing(["41", "42"])

    def first(url, _headers):
        if url == src["feed_url"]: return Response(listing)
        identity = "41" if "fair-41" in url else "42"
        return Response(detail_ics(identity), headers={"ETag": '"v1"'})

    _, db, _ = run_chamber(monkeypatch, src, first)
    src["incremental_snapshot"] = {**db.completions[0]["p_receipt"], "baseline_id": BASELINE_ID}

    def second(url, _headers):
        if url == src["feed_url"]: return Response(listing)
        identity = "41" if "fair-41" in url else "42"
        return Response(detail_ics(identity, address="2 Changed St", status="CANCELLED" if identity == "42" else "CONFIRMED"),
                        headers={"ETag": '"v2"'})

    result, db, calls = run_chamber(monkeypatch, src, second)
    assert len(calls) == 3 and result["staged"] == 1
    assert db.changed[0]["event"]["venue_address"] == "2 Changed St"
    assert [r["id"] for r in db.completions[0]["p_receipt"]["events"]] == ["41"]


@pytest.mark.parametrize("wrong", ["identity", "time"])
def test_changed_detail_identity_or_time_fails_instead_of_using_old_cache(monkeypatch, wrong):
    src, listing = source("chambermaster"), xml_listing(["41"])
    def response(url, _headers):
        if url == src["feed_url"]: return Response(listing)
        return Response(detail_ics("999" if wrong == "identity" else "41",
            start=NOW + timedelta(days=3) if wrong == "time" else None))
    result, db, _ = run_chamber(monkeypatch, src, response)
    assert result["failed"] == 1 and not db.completions and not db.changed
    assert db.calls[-1][1]["p_error"] == "chambermaster_detail_" + wrong


def test_same_day_horizon_boundary_still_parses_and_adds_new_occurrence():
    initial = datetime(2027, 1, 1, 10, tzinfo=timezone.utc)
    start = initial + timedelta(days=60, hours=1)
    raw = detail_ics("boundary", start=start)

    class DatetimeType(type):
        def __instancecheck__(cls, value): return isinstance(value, datetime)

    class Clock(datetime, metaclass=DatetimeType):
        current = initial
        @classmethod
        def now(cls, tz=None): return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    src = source()
    with patch.object(worker, "datetime", Clock):
        first = worker.parse_ics_preview(raw)
        assert first == []
        src = accepted_baseline(src, first)
        Clock.current = initial + timedelta(hours=2)
        second = worker.parse_ics_preview(raw)
        assert len(second) == 1
        result, db = process(src, second)
    assert result["staged"] == 1 and db.completions[0]["p_receipt"]["not_modified"] is False


def test_request_metadata_is_bounded_and_contains_no_raw_bodies():
    src = source()
    with inc.capture_snapshot(src, TICKET) as snapshot:
        for i in range(100):
            snapshot.record_body(f"https://publisher.example/{i}", "text/calendar", b"private raw body", {"ETag": '"v1"'})
        receipt = snapshot.receipt(snapshot.plan([], preview([], src)))
    assert len(receipt["requests"]) <= 32
    assert "private raw body" not in json.dumps(receipt)
    assert all(row["body_hash"] == sha256(b"private raw body").hexdigest() for row in receipt["requests"])


def test_near_limit_metadata_accounts_for_postgres_separator_spaces():
    src = source("chambermaster")
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot:
        for i in range(32):
            row = event("i" * 77 + str(i).zfill(3), starts_at="2027-01-01T00:00:00+00:00")
            url = "https://publisher.example/detail/" + str(i)
            with inc.detail_request(url, "text/calendar", row):
                snapshot.record_body(url, "text/calendar", b"detail", {"ETag": '"' + "v" * (50 if i == 0 else 10) + '"'})
                snapshot.remember_detail(url, "text/calendar", {
                    "kind": "chambermaster_ical_v1", "id": row["id"], "starts_at": row["starts_at"],
                    "status": "cancelled", "venue_address": "a" * 400, "lat": 35.7, "lng": -78.6})
        observations = list(snapshot._observations.values())
        assert len(inc.canonical_json(observations).encode("utf-8")) <= 32_000
        assert len(json.dumps(observations, ensure_ascii=False).encode("utf-8")) > 32_768
        assert snapshot.receipt(snapshot.plan([], preview([], src)))["requests"] == []


def test_same_body_with_changed_charset_cannot_reuse_normalized_evidence(monkeypatch):
    row, src = event("42"), source("chambermaster")
    url = "https://publisher.example/detail"
    src = detail_cache(src, row, url)
    def changed(*_):
        response = Response(b"old detail", headers={"Content-Type": "text/calendar; charset=iso-8859-1", "ETag": '"v2"'})
        response.encoding = "iso-8859-1"
        return response
    network(monkeypatch, changed)
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot, inc.detail_request(url, "text/calendar", row):
        result = worker.fetch_publisher(url, "text/calendar", respect_robots=True)
        assert result == "old detail" and not isinstance(result, inc.RevalidatedDetail)
        requests = snapshot.receipt(snapshot.plan([row], preview([row], src)))["requests"]
        assert requests[0]["body_hash"] == src["incremental_snapshot"]["requests"][0]["body_hash"]
        assert requests[0]["representation_hash"] != src["incremental_snapshot"]["requests"][0]["representation_hash"]


def test_changed_representation_on_304_gets_one_unconditional_bounded_fetch(monkeypatch):
    row, src = event("42"), source("chambermaster")
    url = "https://publisher.example/detail"
    src = detail_cache(src, row, url)
    def respond(_url, headers):
        status = 304 if "If-None-Match" in headers else 200
        response = Response("changed representation", status=status,
                            headers={"Content-Type": "text/calendar; charset=iso-8859-1"})
        response.encoding = "iso-8859-1"
        return response
    calls = network(monkeypatch, respond)
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}), inc.detail_request(url, "text/calendar", row):
        assert worker.fetch_publisher(url, "text/calendar", respect_robots=True) == "changed representation"
    assert len(calls) == 2 and "If-None-Match" in calls[0][1] and "If-None-Match" not in calls[1][1]
    assert worker.robots_allowed.call_count == 2 and worker.pace_publisher.call_count == 2


@pytest.mark.parametrize("headers", [{"Cache-Control": "private, no-store"}, {"Vary": "*"}, {"Vary": "Cookie"}])
@pytest.mark.parametrize("status", [200, 304])
def test_ineligible_cache_response_clears_validators_and_detail(monkeypatch, headers, status):
    row, src = event("42"), source("chambermaster")
    url = "https://publisher.example/detail"
    src = detail_cache(src, row, url)
    old_evidence = src["incremental_snapshot"]["requests"][0]["detail"]
    network(monkeypatch, lambda *_: Response("old detail", status=status, headers=headers))
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot, inc.detail_request(url, "text/calendar", row):
        worker.fetch_publisher(url, "text/calendar", respect_robots=True)
        # The adapter's usual post-parse callback must not re-enable caching.
        snapshot.remember_detail(url, "text/calendar", old_evidence)
        receipt = snapshot.receipt(snapshot.plan([row], preview([row], src)))
    saved = receipt["requests"][0]
    assert not {"etag", "last_modified", "detail", "detail_context_hash"}.intersection(saved)
    src["incremental_snapshot"] = {**receipt, "baseline_id": BASELINE_ID}
    with inc.capture_snapshot(src, {**TICKET, "p_category": "chambermaster"}) as snapshot, inc.detail_request(url, "text/calendar", row):
        assert snapshot.conditional_headers(url, "text/calendar") == {}


@pytest.mark.parametrize("category", ["ical", "localist", "wordpress", "chambermate"])
def test_real_adapter_routes_parse_refresh_but_skip_unchanged_db_bodies(monkeypatch, category):
    from roomquest.registration_formats import source_key
    if category == "ical":
        src, body = source(), detail_ics("41")
    elif category == "localist":
        from test_localist_registration import response, URL
        src = {**source(category), "feed_url": URL, "source_key": source_key(URL)}
        body = response()
    elif category == "wordpress":
        from test_registered_native_content import source as native_source, item, payload
        src, body = native_source(), payload([item()])
        src["action"] = "collect"
        src["incremental_snapshot"] = source(category)["incremental_snapshot"]
    else:
        from test_chambermate import source as chamber_source, event as chamber_event, snapshot
        src, body = chamber_source(), json.dumps(snapshot(chamber_event()))
        src["action"] = "collect"
        src["incremental_snapshot"] = source(category)["incremental_snapshot"]
    calls = network(monkeypatch, lambda *_: Response(body, headers={"ETag": '"feed-v1"'}))
    first = Database()
    with patch.object(worker, "supabase_rpc", side_effect=first):
        result = worker._process_claimed_source(src, collection_context={**TICKET, "p_category": category})
    assert result["complete"] == 1 and result["staged"] == 1
    assert len(first.completions) == 1
    if category == "wordpress":
        stage = next(payload for path, payload in first.calls if path.endswith("stage_incremental"))
        assert stage["p_registered_native_content_version"] == 1
        assert first.completions[0]["p_preview"]["version"] == 3
        assert first.completions[0]["p_preview"]["parser_capability"] == "registered_native_content_v1"
    src["incremental_snapshot"] = {**first.completions[0]["p_receipt"], "baseline_id": BASELINE_ID,
                                  "window_day": (NOW - timedelta(days=4)).date().isoformat()}
    second = Database()
    with patch.object(worker, "supabase_rpc", side_effect=second):
        result = worker._process_claimed_source(src, collection_context={**TICKET, "p_category": category})
    assert result == {"complete": 1, "failed": 0, "staged": 0, "publication_required": False}
    assert len(calls) == 2 and all("If-None-Match" not in headers for _, headers in calls)
    assert second.completions[0]["p_receipt"]["events"] == first.completions[0]["p_receipt"]["events"]


def test_real_chambermaster_identical_200_body_reuses_validated_detail(monkeypatch):
    src, listing = source("chambermaster"), xml_listing(["41"])
    raw = detail_ics("41")
    def respond(url, _headers):
        return Response(listing if url == src["feed_url"] else raw)
    _, first, _ = run_chamber(monkeypatch, src, respond)
    src["incremental_snapshot"] = {**first.completions[0]["p_receipt"], "baseline_id": BASELINE_ID}
    with patch("roomquest.chambermaster.Calendar.from_ical", side_effect=AssertionError("identical representation must reuse detail")):
        result, _, calls = run_chamber(monkeypatch, src, respond)
    assert result["staged"] == 0 and len(calls) == 2
    assert all("If-None-Match" not in headers for _, headers in calls)
