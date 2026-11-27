"""Actual category-worker completion, publication and response-budget boundaries."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

import pytest

from roomquest import boston_nightlife_additional as b, boston_sources as common
from roomquest import preview_worker as worker
from tests.test_atlantic_city_worker import Harness, RECORD, STAGE, PUBLISH, WRITE
from tests.test_boston_nightlife_additional import passim_pages, source


def replay(key, pages, now, *, cap=None, checkpoint=None, duration=0.1, one_claim=False,
           fail_stage=False, reject_write=False):
    testcase = TestCase()
    state = Harness(testcase, {**source(key), "fetch_checkpoint_version": 1}, pages=pages)
    state.checkpoint = deepcopy(checkpoint)
    state.revision = 1 if checkpoint else 0
    state.fail_stage, state.reject_write = fail_stage, reject_write
    original, original_fetch = b.collect_chunk, state.fetch
    adapters = common.adapters()
    starts, snapshots, results = [], [], []

    def fetch(url, accept, **kwargs):
        starts.append((url, state.clock, kwargs["deadline_at"]))
        assert state.clock + b.MIN_SECONDS < kwargs["deadline_at"]
        result = original_fetch(url, accept, **kwargs)
        state.clock += duration - 0.1
        return result

    try:
        with patch.object(common, "adapters", lambda: adapters if b in adapters else adapters + (b,)), \
             patch.object(b, "MAX_FETCHES", cap or b.MAX_FETCHES), \
             patch.object(b, "monotonic", lambda: state.clock), \
             patch.object(worker, "fetch_publisher", fetch), \
             patch.object(b, "collect_chunk", side_effect=lambda *args, **kw: original(*args, **kw, now=now)):
            for claim in range(1, 80):
                result = state.run()
                results.append(result)
                if result.get("fetch_pending"):
                    assert not state.staged
                    assert not any(op in (STAGE, RECORD, PUBLISH) for op, _ in state.calls)
                    common.validate_checkpoint(state.source, state.checkpoint, now=now)
                    snapshots.append(deepcopy(state.checkpoint))
                if one_claim or result.get("failed") or result.get("complete"):
                    break
            else:
                raise AssertionError("Source did not complete within bounded worker replay")
        return dict(claims=claim, rows=state.staged, checkpoint=state.checkpoint,
                    snapshots=snapshots, fetched=state.fetched, calls=state.calls, starts=starts, results=results)
    finally:
        testcase.doCleanups()


def current_pages(count=17):
    now = datetime.now(timezone.utc)
    start = (now + timedelta(days=2)).astimezone(b.ZoneInfo(b.ZONE)).replace(hour=19, minute=30, second=0, microsecond=0)
    return now, passim_pages(count, start=start)


def test_complete_only_worker_replay_matches_one_detail_reference_and_preserves_every_body():
    now, pages = current_pages()
    baseline = replay(b.PASSIM, pages, now, cap=1)
    bounded = replay(b.PASSIM, pages, now)
    assert baseline["claims"] == 17 and bounded["claims"] == 2
    assert bounded["rows"] == baseline["rows"] and len(bounded["rows"]) == 17
    assert all(len(row["description"]) > 2000 and row["description"].endswith("The final native participation condition.") for row in bounded["rows"])
    assert all("collector_event_content_v1" in row for row in bounded["rows"])
    previews = [payload for operation, payload in bounded["calls"] if operation == RECORD]
    assert len(previews) == 1
    assert all("collector_event_content_v1" not in row for row in previews[0]["p_samples"])
    assert sum(op == PUBLISH for op, _ in bounded["calls"]) == 1
    assert all(bounded["fetched"].count(url) == 1 for url in pages if url != b.SOURCES[b.PASSIM][0])


def test_slow_publisher_yields_within_reserve_and_checkpoint_resumes_without_duplicate_details():
    now, pages = current_pages()
    partial = replay(b.PASSIM, pages, now, duration=8, one_claim=True)
    assert partial["results"][0]["fetch_pending"] and not partial["rows"]
    assert len(partial["fetched"]) < b.MAX_FETCHES
    assert sum(op == WRITE for op, _ in partial["calls"]) == 1
    saved = deepcopy(partial["checkpoint"])
    resumed = replay(b.PASSIM, pages, now, checkpoint=saved)
    assert saved == partial["checkpoint"]
    expected = replay(b.PASSIM, pages, now)
    assert resumed["rows"] == expected["rows"]
    prior_details = set(partial["fetched"]) - {b.SOURCES[b.PASSIM][0]}
    assert prior_details.isdisjoint(set(resumed["fetched"]))
    assert all(x["started_at"] == saved["started_at"] for x in resumed["snapshots"])


def test_publisher_denial_stops_source_without_an_alternative_route_or_staging():
    now, pages = current_pages(3)
    first_detail = sorted(url for url in pages if url != b.SOURCES[b.PASSIM][0])[0]
    pages[first_detail] = worker.PreviewError("publisher_http_403")
    result = replay(b.PASSIM, pages, now)
    assert result["results"][0]["failed"] == 1
    assert result["fetched"] == [b.SOURCES[b.PASSIM][0], first_detail]
    assert not result["rows"] and not any(op in (STAGE, PUBLISH) for op, _ in result["calls"])


def test_rejected_checkpoint_write_never_reaches_staging_or_publication():
    now, pages = current_pages(3)
    result = replay(b.PASSIM, pages, now, reject_write=True)
    assert result["results"][0]["failed"] == 1
    assert not result["rows"] and not any(op in (STAGE, PUBLISH) for op, _ in result["calls"])


def test_complete_checkpoint_survives_staging_failure_without_reloading_details():
    now, pages = current_pages(3)
    failed = replay(b.PASSIM, pages, now, fail_stage=True)
    assert failed["results"][0]["failed"] == 1 and failed["checkpoint"]
    assert not failed["rows"] and not any(op == PUBLISH for op, _ in failed["calls"])
    resumed = replay(b.PASSIM, pages, now, checkpoint=failed["checkpoint"])
    assert resumed["results"][-1]["complete"] == 1 and len(resumed["rows"]) == 3
    assert resumed["fetched"] == [b.SOURCES[b.PASSIM][0]]
