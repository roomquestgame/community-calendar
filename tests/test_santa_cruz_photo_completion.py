"""Offline completion-contract regressions for six already enrolled publishers.

Run the real dedicated parsers and worker against their existing HTML fixtures.
The RPC double models the deployed v3 photo receipt's count/observation checks;
it performs no network requests, database writes, or publication.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from roomquest import preview_worker as worker
from roomquest.publisher_evidence import IMAGE_VERSION, family, image_url
import test_santa_cruz_dante as dante
import test_santa_cruz_downtown as downtown
import test_santa_cruz_fabrica as fabrica
import test_santa_cruz_goat_fitness as goat
import test_santa_cruz_hotel_holidays as hotels


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
STAGE = "community_collector_record_staged_events"
COMPLETE = "community_collector_record_preview_v3"
CASES = [
    pytest.param(5859, fabrica.f, fabrica.SOURCE, fabrica.fixtures, 1, id="fabrica"),
    pytest.param(5861, hotels.h, hotels.src(hotels.h.CHAMINADE), hotels.fetch, 3,
                 id="chaminade"),
    pytest.param(5862, hotels.h, hotels.src(hotels.h.DREAM_INN), hotels.fetch, 1,
                 id="dream-inn"),
    pytest.param(5863, downtown.m, downtown.SOURCE, lambda: downtown.fetch, 1,
                 id="downtown"),
    pytest.param(5874, goat.m, goat.SOURCE, goat._fetch, 1, id="goat"),
    pytest.param(5878, dante.m, dante.SOURCE, dante.fixture, 2, id="dante"),
]


class PhotoReceiptGateway:
    """Relevant non-native checks from rq_curator_gateway.record_preview_v3.

    Staging supplies observation timestamps on the server, not in parser rows.
    The capability alone cannot certify an absent, stale or incomplete stage.
    """

    def __init__(self, source_key, *, omit_capability=False, corrupt=None, now=NOW):
        self.source_key = source_key
        self.now = now
        self.omit_capability = omit_capability
        self.corrupt = corrupt
        self.calls = []
        self.rows = []
        self.started = now
        self.checked = None
        self.stage_count = 0
        self.completed = False

    def __call__(self, name, payload):
        payload = deepcopy(payload)
        assert payload["p_source_key"] == self.source_key
        self.calls.append((name, payload))
        if name == STAGE:
            self.checked = self.now + timedelta(seconds=1)
            for row in payload["p_events"]:
                publisher = family(self.source_key, row["event_url"])
                assert publisher
                assert row["image_extractor_version"] == IMAGE_VERSION
                assert "image_observed_at" not in row  # Database-owned clock.
                if row.get("image_url"):
                    assert image_url(row["image_url"], publisher) == row["image_url"]
                    assert row["image_provenance"] == IMAGE_VERSION
                    assert row["image_evidence_url"]
                self.rows.append({**row, "last_seen_at": self.checked,
                                  "image_observed_at": self.checked})
            self.stage_count += len(payload["p_events"])
            return len(payload["p_events"])
        assert name == COMPLETE
        if payload["p_error"] is not None:
            assert "p_parser_capability" not in payload
            return None
        if self.omit_capability:
            # Reproduce the old wire payload while retaining the same valid rows.
            payload.pop("p_parser_capability", None)
        if self.corrupt:
            self.corrupt(self, payload)
        if (payload.get("p_parser_capability") != IMAGE_VERSION
                or self.checked is None or self.checked < self.started
                or self.checked < self.now - timedelta(minutes=5)
                or self.stage_count != payload["p_future_count"]):
            raise worker.PreviewError("Incomplete Virginia photo extraction")
        observed = sum(row["last_seen_at"] >= self.started
                       and row["image_observed_at"] == row["last_seen_at"]
                       and row["image_extractor_version"] == IMAGE_VERSION
                       for row in self.rows)
        if observed != payload["p_future_count"]:
            raise worker.PreviewError("Incomplete Virginia photo staging")
        self.completed = True


def prepare(monkeypatch, source_id, module, profile, fetch_factory, *, now=NOW):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", Clock)
    # The shared preview has its own clock; retain its real 60-day check.
    monkeypatch.setattr(worker, "_future_datetime", lambda value:
                        value.astimezone(timezone.utc)
                        if now <= value.astimezone(timezone.utc)
                        <= now + timedelta(days=worker.LOOKAHEAD_DAYS) else None)
    fetch = fetch_factory()
    requests = []

    def fetch_fixture(url, accept, **options):
        requests.append(url)
        assert options["respect_robots"] is True
        assert options["allowed_hosts"] == module.ALLOWED_HOSTS[profile["source_key"]]
        assert options["deadline_at"] > 0
        return fetch(url, accept)

    monkeypatch.setattr(worker, "fetch_publisher", fetch_fixture)
    return {**profile, "id": source_id}, requests


@pytest.mark.parametrize("source_id,module,profile,fetch_factory,count", CASES)
def test_complete_scoped_extraction_reaches_v3_with_photo_evidence(
        monkeypatch, source_id, module, profile, fetch_factory, count):
    source, requests = prepare(monkeypatch, source_id, module, profile, fetch_factory)
    gateway = PhotoReceiptGateway(source["source_key"])
    monkeypatch.setattr(worker, "supabase_rpc", gateway)
    assert worker._process_claimed_source(source) == {
        "complete": 1, "failed": 0, "staged": count}
    assert requests and gateway.completed
    completion = gateway.calls[-1][1]
    assert gateway.calls[-1][0] == COMPLETE
    assert completion["p_parser_capability"] == "publisher_event_candidates_v1"
    assert completion["p_future_count"] == len(gateway.rows) == count
    assert completion["p_venue_count"] == 0
    assert completion["p_samples"] == gateway.calls[0][1]["p_events"]
    assert all(row["image_observed_at"] == row["last_seen_at"] for row in gateway.rows)
    assert all(row["lat"] is None and row["lng"] is None for row in gateway.rows)
    # Fábrica supplies an approved photo candidate; the other handlers honestly
    # report no candidate and still attest that each occurrence was inspected.
    assert sum(bool(row.get("image_url")) for row in gateway.rows) == (source_id == 5859)


@pytest.mark.parametrize("source_id,module,profile,fetch_factory,count", CASES)
def test_historical_missing_marker_rejects_otherwise_complete_stage(
        monkeypatch, source_id, module, profile, fetch_factory, count):
    source, _ = prepare(monkeypatch, source_id, module, profile, fetch_factory)
    gateway = PhotoReceiptGateway(source["source_key"], omit_capability=True)
    monkeypatch.setattr(worker, "supabase_rpc", gateway)
    with pytest.raises(worker.PreviewError, match="Incomplete Virginia photo extraction"):
        worker._process_claimed_source(source)
    assert len(gateway.rows) == count and not gateway.completed


@pytest.mark.parametrize("source_id,module,profile,fetch_factory,count", CASES)
def test_failed_or_invalid_extraction_never_certifies_a_snapshot(
        monkeypatch, source_id, module, profile, fetch_factory, count):
    source, _ = prepare(monkeypatch, source_id, module, profile, fetch_factory)
    for failure in ("parser", "invalid_row"):
        gateway = PhotoReceiptGateway(source["source_key"])
        monkeypatch.setattr(worker, "supabase_rpc", gateway)

        def broken(*args, **kwargs):
            if failure == "parser":
                raise ValueError("publisher_narrative_missing")
            return [{"description": "", "venue_address": ""}]

        monkeypatch.setattr(module, "collect", broken)
        result = worker._process_claimed_source(source)
        assert result["complete"] == 0 and result["failed"] == 1 and result["staged"] == 0
        assert [name for name, _ in gateway.calls] == [COMPLETE]
        assert gateway.calls[0][1]["p_error"]
        assert "p_parser_capability" not in gateway.calls[0][1]
        assert not gateway.completed


@pytest.mark.parametrize("source_id,module,profile,fetch_factory,count", CASES)
def test_genuine_empty_extraction_still_performs_an_empty_stage(
        monkeypatch, source_id, module, profile, fetch_factory, count):
    now = datetime(2027, 2, 1, tzinfo=timezone.utc)
    source, requests = prepare(monkeypatch, source_id, module, profile, fetch_factory,
                               now=now)
    gateway = PhotoReceiptGateway(source["source_key"], now=now)
    monkeypatch.setattr(worker, "supabase_rpc", gateway)
    assert worker._process_claimed_source(source) == {"complete": 1, "failed": 0, "staged": 0}
    assert requests and gateway.completed
    assert gateway.calls[0] == (STAGE, {"p_source_key": source["source_key"], "p_events": []})
    assert gateway.calls[-1][1]["p_parser_capability"] == IMAGE_VERSION
    assert gateway.calls[-1][1]["p_future_count"] == 0


@pytest.mark.parametrize("corrupt,reason", [
    (lambda g, p: setattr(g, "stage_count", g.stage_count - 1), "extraction"),
    (lambda g, p: setattr(g, "checked", NOW - timedelta(minutes=6)), "extraction"),
    (lambda g, p: g.rows[0].update(image_observed_at=NOW - timedelta(hours=1)), "staging"),
    (lambda g, p: g.rows[0].update(image_extractor_version="unrecognized"), "staging"),
])
def test_capability_does_not_override_incomplete_or_stale_staging(monkeypatch, corrupt, reason):
    source, _ = prepare(monkeypatch, 5859, fabrica.f, fabrica.SOURCE, fabrica.fixtures)
    gateway = PhotoReceiptGateway(source["source_key"], corrupt=corrupt)
    monkeypatch.setattr(worker, "supabase_rpc", gateway)
    with pytest.raises(worker.PreviewError, match="Incomplete Virginia photo " + reason):
        worker._process_claimed_source(source)
    assert not gateway.completed


def test_staging_failure_discards_success_capability(monkeypatch):
    source, _ = prepare(monkeypatch, 5859, fabrica.f, fabrica.SOURCE, fabrica.fixtures)
    gateway = PhotoReceiptGateway(source["source_key"])

    def rpc(name, payload):
        if name == STAGE:
            raise worker.PreviewError("database_unavailable")
        return gateway(name, payload)

    monkeypatch.setattr(worker, "supabase_rpc", rpc)
    result = worker._process_claimed_source(source)
    assert result["complete"] == 0 and result["failed"] == 1 and result["staged"] == 0
    assert gateway.calls[-1][1]["p_error"] == "database_unavailable"
    assert "p_parser_capability" not in gateway.calls[-1][1]
    assert not gateway.completed
