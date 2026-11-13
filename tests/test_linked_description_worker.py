"""The leased worker publishes linked-page prose only after every URL is read."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from roomquest import category_worker as category
from roomquest import linked_event_descriptions as linked
from roomquest import preview_worker as worker
from roomquest.publisher_pacing import observe_crawl_delay

READ = "community_collector_read_fetch_checkpoint"
WRITE = "community_collector_write_fetch_checkpoint"
STAGE = "community_collector_record_staged_events"
RECORD = "community_collector_record_preview_v2"
PUBLISH = "community_collector_publish_category"
FINISH = "community_collector_finish_category"


class Harness:
    def __init__(self, monkeypatch, key, count=8, capability=1):
        listing, zone, host = linked.PROFILES[key]
        self.source = dict(source_key=key, feed_url=listing, timezone=zone,
                           kind="html", platform_adapter="html", source_id=123,
                           action="collect", fetch_checkpoint_version=capability)
        self.time = 100.0
        self.calls, self.fetched, self.staged = [], [], []
        self.state, self.revision = None, 0
        self.fail_stage = False
        begins = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        self.rows = [dict(id=f"event-{i}", title=f"Event {i}", starts_at=begins,
                          ends_at=None, event_url=f"https://{host}/event/{i}",
                          venue_name="Venue", venue_address="123 Main St", venue_city="City",
                          lat=None, lng=None) for i in range(count)]

        def collect(source, fetch, **kwargs):
            assert source == self.source
            fetch(listing, "text/html")
            return deepcopy(self.rows)

        def extract(payload, row):
            assert payload == row["event_url"]
            return "Publisher prose for " + row["title"]

        def fetch(url, accept, **kwargs):
            assert kwargs["respect_robots"] is True
            assert kwargs["allowed_hosts"] == (host,)
            assert self.time < kwargs["deadline_at"]
            observe_crawl_delay(1)
            self.time += 0.1
            self.fetched.append(url)
            return url

        monkeypatch.setattr(linked, "_adapter", lambda key: (collect, extract))
        monkeypatch.setattr(linked, "monotonic", lambda: self.time)
        monkeypatch.setattr(worker, "monotonic", lambda: self.time)
        monkeypatch.setattr(category, "monotonic", lambda: self.time)
        monkeypatch.setattr(category, "sleep", lambda seconds: None)
        monkeypatch.setattr(worker, "fetch_publisher", fetch)
        monkeypatch.setattr(worker, "supabase_rpc", self.rpc)
        monkeypatch.setattr(category, "supabase_rpc", self.rpc)

    def rpc(self, operation, payload, **kwargs):
        self.calls.append((operation, deepcopy(payload)))
        if operation == "community_collector_claim_category":
            return deepcopy(self.source)
        if operation in (READ, WRITE):
            assert payload["p_category"] == "html"
            assert payload["p_ticket"] == "fixture-ticket"
            assert payload["p_source_key"] == self.source["source_key"]
        if operation == READ:
            return {"checkpoint": deepcopy(self.state), "revision": self.revision}
        if operation == WRITE:
            assert payload["p_expected_revision"] == self.revision
            self.state = deepcopy(payload["p_checkpoint"])
            self.revision += 1
            return {"checkpoint_saved": True, "revision": self.revision}
        if operation == STAGE:
            assert self.state["cursor"] == self.state["manifest_count"]
            if self.fail_stage:
                self.fail_stage = False
                raise worker.PreviewError("database_unavailable")
            self.staged.extend(deepcopy(payload["p_events"]))
            return len(payload["p_events"])
        if operation == RECORD:
            if payload["p_error"] is None:
                assert self.state["cursor"] == self.state["manifest_count"]
                self.state, self.revision = None, 0
            return None
        if operation == PUBLISH:
            assert self.state is None
            return {"outcome": "complete"}
        if operation == FINISH:
            return True
        raise AssertionError(operation)

    def run(self):
        return category.collect_category("html", "fixture-ticket")


@pytest.mark.parametrize("key", linked.PROFILES)
def test_each_registered_source_uses_fenced_chunks_and_only_publishes_the_full_calendar(monkeypatch, key):
    state = Harness(monkeypatch, key)
    result = state.run()
    assert result["fetch_pending"] and result["staged"] == 0
    assert state.state["cursor"] == 6
    assert [op for op, _ in state.calls] == ["community_collector_claim_category", READ, WRITE, FINISH]
    assert state.calls[-1][1]["p_outcome"] == "fetch_pending"
    result = state.run()
    assert result["complete"] == 1 and result["staged"] == 8 and result["failed"] == 0
    assert all(row["description"].startswith("Publisher prose for ") for row in state.staged)
    assert len({(row["id"], row["starts_at"]) for row in state.staged}) == 8
    assert [op for op, _ in state.calls].count(RECORD) == 1
    assert [op for op, _ in state.calls].count(PUBLISH) == 1
    assert all(state.fetched.count(row["event_url"]) == 1 for row in state.rows)


def test_completed_details_survive_staging_retry_without_refetching(monkeypatch):
    state = Harness(monkeypatch, "omaha_reverb_lounge_events", count=2)
    state.fail_stage = True
    result = state.run()
    assert result["failed"] == 1 and state.state["cursor"] == 2
    assert not any(op == PUBLISH for op, _ in state.calls)
    assert state.run()["staged"] == 2
    assert all(state.fetched.count(row["event_url"]) == 1 for row in state.rows)


@pytest.mark.parametrize("capability", [None, False, True, "1", 0, 2])
def test_unadvertised_checkpoint_capability_retains_the_legacy_path(monkeypatch, capability):
    state = Harness(monkeypatch, "omaha_reverb_lounge_events", capability=capability)
    reached = []

    def legacy(source, **kwargs):
        reached.append(kwargs)
        return {"complete": 1, "failed": 0, "staged": 0}

    monkeypatch.setattr(category, "_process_claimed_source", legacy)
    assert state.run()["complete"] == 1
    assert "collection_context" not in reached[0]
    assert not any(op in (READ, WRITE) for op, _ in state.calls)
