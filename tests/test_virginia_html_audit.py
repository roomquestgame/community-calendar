"""Read-only diagnostics preserve publisher guards and reviewed identity bounds."""
import gzip
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from scripts import capture_virginia_event_html as audit
from roomquest import preview_worker as worker
from roomquest.preview_worker import PreviewError

FIXTURES = Path(__file__).parent / "fixtures" / "virginia_state_parks"
ARCHERY = (FIXTURES / "archery-club.html").read_text(encoding="utf-8")


def manifest_event(number=1):
    return {
        "event_id": str(UUID(int=number)), "source_key": "virginia_state_parks_bc",
        "event_url": audit.PAGES[0][1] if number == 1 else audit.ROOT + "/state-parks/event?id=2026-11-08-example-" + str(number),
        "title": "Archery Club", "starts_at": "2026-11-08T18:00:00+00:00",
        "ends_at": "2026-11-08T19:30:00+00:00", "baseline_fingerprint": "a" * 32,
    }


def manifest(events=None):
    return {"version": audit.MANIFEST_VERSION, "observed_at": "2026-11-05T02:16:27Z",
            "events": events if events is not None else [manifest_event()]}


def save_manifest(tmp_path, value):
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def forbid(*_args, **_kwargs):
    raise AssertionError("No additional network, database, image or registration request is permitted.")


@pytest.fixture
def mocked_transport(monkeypatch):
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append((url, accept, kwargs))
        return ARCHERY
    monkeypatch.setattr(audit, "fetch_publisher", fetch)
    monkeypatch.setattr(worker, "fetch_publisher", forbid)
    monkeypatch.setattr(worker, "supabase_rpc", forbid)
    monkeypatch.setattr(worker.requests, "Session", forbid)
    # Keep this captured 2026 fixture deterministic without changing its
    # schedule, production parsing, or the diagnostic's identity comparison.
    monkeypatch.setattr(worker, "_future_datetime", lambda start: start)
    return calls


def test_audit_captures_only_reviewed_pages_with_existing_guards(tmp_path, monkeypatch):
    calls = []
    def fetch(url, accept, **kwargs):
        calls.append((url, accept, kwargs))
        return '<html><body><main><h1>Example</h1><h2>When</h2><p>Details</p></main></body></html>'
    monkeypatch.setattr(audit, "fetch_publisher", fetch)
    report = audit.capture(tmp_path)
    assert [call[0] for call in calls] == [url for _, url in audit.PAGES]
    assert all(call[1] == "text/html" and call[2]["respect_robots"] is True
               and call[2]["allowed_hosts"] == ("www.dcr.virginia.gov",)
               and call[2]["deadline_at"] > 0 for call in calls)
    assert all(page["status"] == "complete" and page["sha256"] for page in report["pages"])
    assert len(list(tmp_path.glob("*.html"))) == 2
    assert (tmp_path / "audit.json").exists()


def test_audit_stops_on_publisher_denial_without_fallback(tmp_path, monkeypatch):
    calls = []
    def deny(url, *_args, **_kwargs):
        calls.append(url)
        raise PreviewError("publisher_http_403")
    monkeypatch.setattr(audit, "fetch_publisher", deny)
    report = audit.capture(tmp_path)
    assert len(calls) == 1
    assert [page["status"] for page in report["pages"]] == ["failed", "not_attempted"]
    assert report["pages"][0]["error"] == "publisher_http_403"
    assert not list(tmp_path.glob("*.html"))


def test_manifest_capture_parses_each_exact_known_url_once_and_retains_evidence(tmp_path, mocked_transport):
    values = manifest([manifest_event(1), manifest_event(2)])
    path = save_manifest(tmp_path, values)
    out = tmp_path / "capture"
    report = audit.capture_manifest(out, path)
    assert [call[0] for call in mocked_transport] == [event["event_url"] for event in values["events"]]
    assert all(call[1] == "text/html" and call[2]["respect_robots"] is True
               and call[2]["allowed_hosts"] == ("www.dcr.virginia.gov",)
               for call in mocked_transport)
    assert report["read_only"] is True
    assert report["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["details_parser_version"] == "virginia_event_details_v1"
    assert report["photo_parser_version"] == "publisher_event_html_v2"
    assert report["response_bytes"] == len(ARCHERY.encode("utf-8")) * 2
    assert report == json.loads((out / "audit.json").read_text())
    for page in report["pages"]:
        assert page["status"] == "complete" and page["eligible"] is True
        assert page["identity_and_schedule_match"] is True
        assert all(page["matches"].values())
        assert page["expected"]["baseline_fingerprint"] == "a" * 32
        record = page["record"]
        assert record["title"] == "Archery Club"
        assert "18 years old and up" in record["description"]
        assert record["publisher_details"]["children_welcome"] == "No."
        assert record["publisher_categories"] == ["Competition", "Outdoor/Nature/Natural History"]
        assert record["details_evidence_url"] == page["source_url"]
        raw = gzip.decompress((out / page["html_file"]).read_bytes())
        fragment = gzip.decompress((out / page["main_file"]).read_bytes())
        assert raw == ARCHERY.encode("utf-8")
        assert len(raw) == page["bytes"] and hashlib.sha256(raw).hexdigest() == page["sha256"]
        assert len(fragment) == page["main_bytes"]
        assert hashlib.sha256(fragment).hexdigest() == page["main_sha256"]
        assert b'id="event_description"' in fragment


@pytest.mark.parametrize("field,value", [
    ("event_id", "not-a-uuid"), ("event_id", None), ("source_key", "virginia_state_parks_unknown"),
    ("source_key", "findlocal"), ("title", ""), ("title", "x" * 181),
    ("starts_at", "2026-11-08T18:00:00"), ("starts_at", "not-a-date"),
    ("ends_at", "2026-11-08T17:59:00Z"), ("ends_at", "2026-11-08T19:30:00"),
    ("baseline_fingerprint", "unbounded evidence"), ("baseline_fingerprint", "A" * 32),
])
def test_manifest_rejects_invalid_identity_and_dates_before_any_request(tmp_path, monkeypatch, field, value):
    values = manifest([manifest_event(1), manifest_event(2)])
    values["events"][1][field] = value  # Entire scope is validated before even the first valid row.
    monkeypatch.setattr(audit, "fetch_publisher", forbid)
    with pytest.raises(ValueError):
        audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, values))
    assert not (tmp_path / "capture").exists()


@pytest.mark.parametrize("url", [
    "http://www.dcr.virginia.gov/state-parks/event?id=2026-11-08-example",
    "https://dcr.virginia.gov/state-parks/event?id=2026-11-08-example",
    "https://evil.example/state-parks/event?id=2026-11-08-example",
    "https://www.dcr.virginia.gov/state-parks/events?id=2026-11-08-example",
    "https://www.dcr.virginia.gov/state-parks/event?id=2026-11-08-example&next=https://example.org",
    "https://www.dcr.virginia.gov/state-parks/event?id=2026-11-08-example&id=2026-11-08-another",
    "https://www.dcr.virginia.gov/state-parks/event?id=2026-11-08-example#other",
    "https://user@www.dcr.virginia.gov/state-parks/event?id=2026-11-08-example",
    "https://www.dcr.virginia.gov:443/state-parks/event?id=2026-11-08-example",
    "https://www.dcr.virginia.gov/state-parks/event?id=2026%2D11-08-example",
    "https://www.dcr.virginia.gov/state-parks/event?id=short",
    "https://www.dcr.virginia.gov/state-parks/event?id=" + "x" * 200,
])
def test_manifest_accepts_only_exact_reviewed_canonical_urls(tmp_path, monkeypatch, url):
    values = manifest()
    values["events"][0]["event_url"] = url
    monkeypatch.setattr(audit, "fetch_publisher", forbid)
    with pytest.raises(ValueError, match="audit_url_invalid"):
        audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, values))


@pytest.mark.parametrize("field", ["event_id", "event_url"])
def test_manifest_duplicate_identity_is_rejected(tmp_path, monkeypatch, field):
    values = manifest([manifest_event(1), manifest_event(2)])
    values["events"][1][field] = values["events"][0][field]
    monkeypatch.setattr(audit, "fetch_publisher", forbid)
    with pytest.raises(ValueError, match="audit_duplicate_event"):
        audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, values))


def test_manifest_size_schema_and_event_limits_are_enforced_without_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "fetch_publisher", forbid)
    invalid = [[], {**manifest(), "url": audit.PAGES[0][1]}, {**manifest(), "version": "other"},
               manifest([]), manifest([manifest_event(i) for i in range(1, 352)])]
    extra_event_field = manifest()
    extra_event_field["events"][0]["fetch_url"] = "https://example.org"
    invalid.append(extra_event_field)
    for values in invalid:
        with pytest.raises(ValueError):
            audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, values))
    path = tmp_path / "reviewed.json"
    path.write_bytes(b" " * (audit.MAX_MANIFEST_BYTES + 1))
    with pytest.raises(ValueError, match="audit_manifest_oversized"):
        audit.capture_manifest(tmp_path / "capture", path)
    valid = manifest([manifest_event(i) for i in range(1, 351)])
    assert len(audit.load_manifest(save_manifest(tmp_path, valid))[0]["events"]) == 350


def test_reviewed_production_manifest_is_valid_and_includes_screenshot_event():
    values, digest = audit.load_manifest(FIXTURES / "enrichment-manifest-20261105.json")
    assert len(values["events"]) == 299 and len(digest) == 64
    matching = [event for event in values["events"] if event["event_url"] == audit.ROOT
                + "/state-parks/event?id=2026-10-17-16-00-48-597528-s8b"]
    assert len(matching) == 1
    assert matching[0]["title"] == "Plantation Discovery Hike"
    assert matching[0]["source_key"] == "virginia_state_parks_oc"


@pytest.mark.parametrize("error", ["publisher_http_403", "robots_denied", "publisher_rate_limited", "source_network_error"])
def test_manifest_capture_stops_on_denial_or_outage_without_fallback(tmp_path, monkeypatch, error):
    calls = []
    def deny(url, *_args, **_kwargs):
        calls.append(url)
        raise PreviewError(error)
    monkeypatch.setattr(audit, "fetch_publisher", deny)
    path = save_manifest(tmp_path, manifest([manifest_event(1), manifest_event(2)]))
    report = audit.capture_manifest(tmp_path / "capture", path)
    assert len(calls) == 1
    assert [page["status"] for page in report["pages"]] == ["failed", "not_attempted"]
    assert report["pages"][0]["error"] == error
    assert report["response_bytes"] == 0


def test_manifest_capture_uses_one_global_budget_and_bounded_request_deadlines(tmp_path, monkeypatch):
    now = [100.0]
    calls = []
    monkeypatch.setattr(audit, "monotonic", lambda: now[0])
    def fetch(url, accept, **kwargs):
        calls.append(kwargs["deadline_at"])
        now[0] += 44
        return ARCHERY
    monkeypatch.setattr(audit, "fetch_publisher", fetch)
    monkeypatch.setattr(worker, "_future_datetime", lambda start: start)
    path = save_manifest(tmp_path, manifest([manifest_event(i) for i in range(1, 5)]))
    report = audit.capture_manifest(tmp_path / "capture", path, overall_timeout=90)
    assert calls == [145, 189]
    assert [page["status"] for page in report["pages"]] == ["complete", "complete", "not_attempted", "not_attempted"]
    assert report["pages"][-1]["error"] == "audit_deadline"


@pytest.mark.parametrize("timeout", [0, 29, 1201, float("inf"), float("nan"), "1200"])
def test_capture_timeout_cannot_disable_or_expand_budget(tmp_path, monkeypatch, timeout):
    monkeypatch.setattr(audit, "fetch_publisher", forbid)
    with pytest.raises(ValueError, match="audit_timeout_invalid"):
        audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, manifest()), overall_timeout=timeout)


@pytest.mark.parametrize("field,value", [
    ("title", "New publisher title"), ("starts_at", "2026-11-08T18:30:00Z"),
    ("ends_at", "2026-11-08T20:00:00Z"), ("ends_at", None),
])
def test_changed_event_facts_are_captured_but_never_claim_an_identity_match(tmp_path, mocked_transport, field, value):
    values = manifest()
    values["events"][0][field] = value
    report = audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, values))
    page = report["pages"][0]
    assert page["status"] == "complete" and page["eligible"] is True
    assert page["matches"][field] is False
    assert page["identity_and_schedule_match"] is False


def test_parse_failure_retains_raw_evidence_and_is_distinct_from_transport_failure(tmp_path, monkeypatch):
    calls = []
    def fetch(url, *_args, **_kwargs):
        calls.append(url)
        return "<main><h1>Incomplete publisher page</h1></main>" if len(calls) == 1 else ARCHERY
    monkeypatch.setattr(audit, "fetch_publisher", fetch)
    monkeypatch.setattr(worker, "_future_datetime", lambda start: start)
    values = manifest([manifest_event(1), manifest_event(2)])
    out = tmp_path / "capture"
    report = audit.capture_manifest(out, save_manifest(tmp_path, values))
    assert len(calls) == 2
    assert [page["status"] for page in report["pages"]] == ["parse_failed", "complete"]
    assert report["pages"][0]["error"] == "event_park_mismatch"
    assert (out / report["pages"][0]["html_file"]).exists()
    assert "identity_and_schedule_match" not in report["pages"][0]


def test_out_of_window_event_is_explicitly_ineligible(tmp_path, mocked_transport, monkeypatch):
    monkeypatch.setattr(worker, "_future_datetime", lambda _start: None)
    # Date filtering is intentionally production behavior; a controlled None
    # also covers a record becoming ineligible while a capture is running.
    monkeypatch.setattr(audit, "parse_event", lambda *_args: None)
    report = audit.capture_manifest(tmp_path / "capture", save_manifest(tmp_path, manifest()))
    page = report["pages"][0]
    assert page["status"] == "complete" and page["eligible"] is False
    assert page["record"] is None and "identity_and_schedule_match" not in page


@pytest.mark.parametrize("limit", ["body", "total"])
def test_capture_body_and_total_response_limits_stop_further_requests(tmp_path, mocked_transport, monkeypatch, limit):
    if limit == "body":
        monkeypatch.setattr(audit, "MAX_BODY", len(ARCHERY.encode("utf-8")) - 1)
        expected_statuses, expected_calls = ["failed", "not_attempted", "not_attempted"], 1
    else:
        monkeypatch.setattr(audit, "MAX_CAPTURE_BYTES", len(ARCHERY.encode("utf-8")) + 1)
        expected_statuses, expected_calls = ["complete", "failed", "not_attempted"], 2
    path = save_manifest(tmp_path, manifest([manifest_event(i) for i in range(1, 4)]))
    report = audit.capture_manifest(tmp_path / "capture", path)
    assert len(mocked_transport) == expected_calls
    assert [page["status"] for page in report["pages"]] == expected_statuses
    assert any(page.get("error") == "audit_html_oversized" for page in report["pages"])


def test_cli_manifest_option_uses_bounded_capture_and_reports_failure_safely(tmp_path, monkeypatch, capsys):
    path = save_manifest(tmp_path, manifest())
    calls = []
    def capture(out, manifest_path, **kwargs):
        calls.append((out, manifest_path, kwargs))
        raise ValueError("private payload must never appear")
    monkeypatch.setattr(audit, "capture_manifest", capture)
    monkeypatch.setattr(audit.sys, "argv", ["capture", "--output-dir", str(tmp_path / "capture"),
                                           "--manifest", str(path), "--overall-timeout", "1200"])
    assert audit.main() == 1
    assert calls == [(tmp_path / "capture", path, {"overall_timeout": 1200})]
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "failed", "error": "source_parse_error"}
    assert "private payload" not in output
