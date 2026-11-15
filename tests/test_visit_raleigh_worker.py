"""Raleigh's acknowledged cursor resumes safely through the actual worker."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from roomquest import category_worker as category
from roomquest import preview_worker as worker
from roomquest import visit_raleigh as r
from roomquest.publisher_pacing import observe_crawl_delay
from tests.test_visit_raleigh import NOW, PAGE, SOURCE, item

READ = "community_collector_read_fetch_checkpoint"
WRITE = "community_collector_write_fetch_checkpoint"
STAGE = "community_collector_record_staged_events"
RECORD = "community_collector_record_preview_v2"


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz or timezone.utc)


class Harness:
    def __init__(self, test, count=405):
        self.test, self.count = test, count
        self.source = {**SOURCE, "source_id": 7001, "action": "collect"}
        self.clock, self.revision, self.checkpoint = 100.0, 0, None
        self.calls, self.fetched, self.staged = [], [], {}
        self.stage_attempts = []
        self.lose_stage_checkpoint = False
        self.short_stage_ack = False
        self.fail_page = None
        for target, name, value in (
            (worker, "monotonic", lambda: self.clock), (r, "monotonic", lambda: self.clock),
            (category, "monotonic", lambda: self.clock), (category, "sleep", self.sleep),
            (worker, "datetime", FixedDatetime), (r, "datetime", FixedDatetime),
            (worker, "supabase_rpc", self.rpc), (category, "supabase_rpc", self.rpc),
            (worker, "fetch_publisher", self.fetch),
            (worker, "fetch_visit_raleigh_page", lambda url, **kwargs: self.fetch(
                url, "application/json", respect_robots=True, allowed_hosts=(r.HOST,), **kwargs)),
            (worker, "_future_datetime", lambda value: value.astimezone(timezone.utc)),
            (worker, "_checkpoint_robots_snapshot", lambda source: None),
            (worker, "_restore_checkpoint_robots", lambda source, snapshot: None),
        ):
            active = patch.object(target, name, value); active.start(); test.addCleanup(active.stop)

    def sleep(self, seconds):
        self.clock += seconds

    def fetch(self, target, accept, **kwargs):
        self.test.assertTrue(kwargs["respect_robots"])
        self.test.assertEqual(kwargs["allowed_hosts"], (r.HOST,))
        self.test.assertLess(self.clock, kwargs["deadline_at"])
        observe_crawl_delay(2)
        self.clock += 0.1
        self.fetched.append(target)
        if target == r.CALENDAR:
            return PAGE
        query = parse_qs(urlsplit(target).query)
        offset = int(query["options[skip]"][0])
        if offset == self.fail_page:
            raise worker.PreviewError("publisher_http_403")
        return json.dumps(dict(total=self.count, docs=[item(n + 1) for n in range(offset, min(offset + 100, self.count))]))

    def rpc(self, operation, payload, **kwargs):
        self.calls.append((operation, deepcopy(payload)))
        self.clock += 0.05
        if operation == "community_collector_claim_category":
            return deepcopy(self.source)
        if operation == READ:
            return dict(checkpoint=deepcopy(self.checkpoint), revision=self.revision)
        if operation == WRITE:
            self.test.assertEqual(payload["p_expected_revision"], self.revision)
            new = payload["p_checkpoint"]
            if self.lose_stage_checkpoint and new["stage_cursor"] > 0:
                self.lose_stage_checkpoint = False
                raise worker.PreviewError("database_unavailable")
            self.checkpoint = deepcopy(new)
            self.revision += 1
            return dict(checkpoint_saved=True, revision=self.revision)
        if operation == STAGE:
            self.test.assertEqual(self.checkpoint["phase"], "stage")
            self.test.assertEqual(self.checkpoint["cursor"], self.checkpoint["manifest_count"])
            self.test.assertLessEqual(len(payload["p_events"]), 20)
            self.stage_attempts.append(deepcopy(payload["p_events"]))
            for row in payload["p_events"]:
                self.staged[row["id"], row["starts_at"]] = deepcopy(row)
            return len(payload["p_events"]) - int(self.short_stage_ack)
        if operation == RECORD:
            self.test.assertNotIn("p_parser_capability", payload)
            if payload["p_error"] is None:
                self.test.assertEqual(self.checkpoint["stage_cursor"], self.checkpoint["record_count"])
                self.test.assertEqual(payload["p_future_count"], len(self.staged))
                self.checkpoint, self.revision = None, 0
            return None
        if operation == "community_collector_publish_category":
            self.test.assertIsNone(self.checkpoint)
            self.test.assertTrue(any(op == RECORD and body["p_error"] is None for op, body in self.calls))
            return dict(outcome="completed")
        if operation == "community_collector_finish_category":
            return True
        raise AssertionError(operation)

    def run(self):
        return category.collect_category("html", "raleigh-fixture-ticket")


class RaleighWorkerTests(unittest.TestCase):
    def test_complete_fetch_precedes_staging_and_final_preview_follows_all_acks(self):
        state = Harness(self)
        first = state.run()
        self.assertTrue(first["fetch_pending"])
        self.assertEqual(state.checkpoint["stage_cursor"], 240)
        self.assertFalse(any(op == RECORD for op, _ in state.calls))
        fetches = len(state.fetched)
        final = state.run()
        self.assertEqual(final["complete"], 1)
        self.assertEqual(len(state.staged), 405)
        self.assertEqual(len(state.fetched), fetches)
        self.assertIsNone(state.checkpoint)
        self.assertEqual(sum(op == RECORD and body["p_error"] is None for op, body in state.calls), 1)
        self.assertEqual([body["p_outcome"] for op, body in state.calls if op == "community_collector_finish_category"], ["fetch_pending", "complete"])

    def test_lost_checkpoint_after_ack_replays_idempotently(self):
        state = Harness(self, 25)
        state.lose_stage_checkpoint = True
        with self.assertRaisesRegex(worker.PreviewError, "database_unavailable"):
            state.run()
        self.assertEqual(state.checkpoint["stage_cursor"], 0)
        self.assertEqual(len(state.staged), 20)
        result = state.run()
        self.assertEqual(result["complete"], 1)
        self.assertEqual(len(state.staged), 25)
        self.assertEqual(state.stage_attempts[0], state.stage_attempts[1])

    def test_short_ack_does_not_advance_or_certify(self):
        state = Harness(self, 25)
        state.short_stage_ack = True
        with self.assertRaisesRegex(worker.PreviewError, "database_unavailable"):
            state.run()
        self.assertEqual(state.checkpoint["stage_cursor"], 0)
        self.assertFalse(any(op == RECORD for op, _ in state.calls))

    def test_source_block_stops_without_staging_partial_pages(self):
        state = Harness(self, 205)
        state.fail_page = 100
        result = state.run()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(state.staged, {})
        errors = [body["p_error"] for op, body in state.calls if op == RECORD]
        self.assertEqual(errors, ["publisher_http_403"])

    def test_legacy_preview_requires_checkpoint_and_empty_snapshot_completes(self):
        with self.assertRaisesRegex(worker.PreviewError, "publisher_checkpoint_required"):
            worker.preview_source(SOURCE)
        state = Harness(self, 0)
        result = state.run()
        self.assertEqual(result["complete"], 1)
        self.assertEqual(state.stage_attempts, [])


if __name__ == "__main__":
    unittest.main()
