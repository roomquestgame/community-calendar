"""Source-specific work caps retain the actual worker's durable boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

import pytest

from roomquest import boston_nightlife_remaining as b, boston_sources as common
from roomquest import preview_worker as worker
from tests.test_atlantic_city_worker import Harness, RECORD, STAGE, PUBLISH, WRITE
from tests.test_boston_nightlife_remaining import catalog, future, product_fixture, source


def pages_for(key, count=17):
    if key == b.EATALY:
        products = [product_fixture(str(2000000000001 + i), f"Pasta Class {i}") for i in range(count)]
        return {b.SOURCES[key][0]: catalog([item for item, _ in products]),
                b.EATALY_EVENTS: catalog([]), **{item["url"]: body for item, body in products}}
    day = future().date()
    clocks = (f'<time class="event-time-localized-start" datetime="{day}">6:00 PM</time>'
              f'<time class="event-time-localized-end" datetime="{day}">9:00 PM</time>')
    address = ('<span class="eventitem-meta-address-line--title">Mighty Squirrel Brewing Co.</span>'
               '<a href="https://maps.google.com?q=411%20Waverley%20Oaks%20Road%20Waltham%20MA">(map)</a>')
    cards, pages = [], {}
    prose = "The publisher's complete rules and welcome for new players. " * 55 + "The final participation condition."
    for i in range(count):
        url = f"https://waverleyoakspark.com/events/crokinole-{i}"
        title = f"Crokinole Workshop {i}"
        cards.append(f'<article class="eventlist-event--upcoming"><a class="eventlist-title-link" href="{url}">{title}</a>'
                     f'{clocks}<div class="eventlist-meta-address">{address}</div><p class="eventlist-excerpt">Short excerpt.</p></article>')
        pages[url] = (f'<h1 class="eventitem-title">{title}</h1>{clocks}'
                      f'<div class="eventitem-meta-address">{address}</div>'
                      f'<div class="eventitem-column-content"><div class="sqs-layout"><p>{prose}</p></div></div>')
    pages[b.SOURCES[key][0]] = '<div class="eventlist">' + ''.join(cards) + '</div>'
    return pages


def replay(key, pages, now, *, cap=None, checkpoint=None, duration=0.1, one_claim=False):
    testcase = TestCase()
    state = Harness(testcase, {**source(key), "fetch_checkpoint_version": 1}, pages=pages)
    state.checkpoint = deepcopy(checkpoint)
    state.revision = 1 if checkpoint else 0
    original = b.collect_chunk
    original_fetch = state.fetch
    starts = []

    def fetch(url, accept, **kwargs):
        starts.append((url, state.clock, kwargs["deadline_at"]))
        if url != b.SOURCES[key][0]:
            assert state.clock + b.MIN_SECONDS < kwargs["deadline_at"]
        result = original_fetch(url, accept, **kwargs)
        state.clock += duration - 0.1
        return result

    snapshots = []
    caps = b.SOURCE_FETCH_CAPS if cap is None else {key: cap}
    try:
        with patch.object(b, "SOURCE_FETCH_CAPS", caps), patch.object(b, "monotonic", lambda: state.clock), \
             patch.object(worker, "fetch_publisher", fetch), \
             patch.object(b, "collect_chunk", side_effect=lambda *a, **kw: original(*a, **kw, now=now)):
            for claim in range(1, 20):
                result = state.run()
                assert result["failed"] == 0, result
                if result.get("fetch_pending"):
                    assert not state.staged
                    assert not any(op in (STAGE, RECORD, PUBLISH) for op, _ in state.calls)
                    common.validate_checkpoint(state.source, state.checkpoint, now=now)
                    snapshots.append(deepcopy(state.checkpoint))
                    if one_claim:
                        break
                else:
                    assert result["complete"] == 1
                    break
            else:
                raise AssertionError("Calendar did not finish within bounded replay")
        return dict(claims=claim, rows=state.staged, checkpoint=state.checkpoint,
                    snapshots=snapshots, fetched=state.fetched, calls=state.calls, starts=starts)
    finally:
        testcase.doCleanups()


@pytest.mark.parametrize("key", [b.EATALY, b.WAVERLEY])
def test_larger_cap_keeps_complete_rows_and_resumes_an_unchanged_legacy_checkpoint(key):
    now = datetime.now(timezone.utc)
    pages = pages_for(key)
    baseline = replay(key, pages, now, cap=5)
    larger = replay(key, pages, now)
    assert larger["claims"] < baseline["claims"]
    assert larger["rows"] == baseline["rows"] and len(larger["rows"]) == 17
    assert all(len(row["description"]) > 2000 for row in larger["rows"])
    assert larger["snapshots"][0]["pending_cursor"] == 12
    legacy = baseline["snapshots"][0]
    unchanged = deepcopy(legacy)
    resumed = replay(key, pages, now, checkpoint=legacy)
    assert legacy == unchanged
    assert resumed["rows"] == baseline["rows"]
    detail_urls = {url for url in pages if b.event_url(key, url)}
    previously_fetched = set(legacy["seen_urls"])
    assert previously_fetched.isdisjoint(set(resumed["fetched"]) & detail_urls)
    assert all(cp["started_at"] == legacy["started_at"] for cp in resumed["snapshots"])
    assert sum(op == PUBLISH for op, _ in resumed["calls"]) == 1


@pytest.mark.parametrize("key", [b.EATALY, b.WAVERLEY])
def test_slow_responses_yield_before_another_fetch_and_preserve_worker_checkpoint(key):
    now = datetime.now(timezone.utc)
    pages = pages_for(key)
    partial = replay(key, pages, now, duration=8, one_claim=True)
    assert partial["checkpoint"]["pending_cursor"] == 2
    assert len(partial["fetched"]) == 3  # Seed plus two details within the actual worker window.
    assert not partial["rows"]
    assert sum(op == WRITE for op, _ in partial["calls"]) == 1
    resumed = replay(key, pages, now, checkpoint=partial["checkpoint"])
    expected = replay(key, pages, now, cap=5)
    assert resumed["rows"] == expected["rows"]
    assert all(cp["started_at"] == partial["checkpoint"]["started_at"] for cp in resumed["snapshots"])


@pytest.mark.parametrize("key", [b.EATALY, b.WAVERLEY])
def test_explicit_oversized_work_request_still_stops_at_source_cap(key):
    now = datetime.now(timezone.utc)
    pages = pages_for(key)
    calls = []

    def fetch(url, accept):
        calls.append(url)
        return pages[url]

    result = b.collect_chunk(source(key), fetch, now=now, max_details=1000)
    assert not result["complete"] and not result["events"]
    assert len(calls) == 13 and result["checkpoint"]["pending_cursor"] == 12
    common.validate_checkpoint(source(key), result["checkpoint"], now=now)


def test_no_progress_near_reserve_keeps_supplied_checkpoint_unchanged(monkeypatch):
    now = datetime.now(timezone.utc)
    pages = pages_for(b.EATALY)
    original = replay(b.EATALY, pages, now, cap=5, one_claim=True)["checkpoint"]
    saved = deepcopy(original)
    calls = []
    monkeypatch.setattr(b, "monotonic", lambda: 27)

    def fetch(url, accept):
        calls.append(url)
        return pages[url]

    with pytest.raises(ValueError, match="^collection_deadline$"):
        b.collect_chunk(source(b.EATALY), fetch, checkpoint=original, now=now, deadline_at=36)
    assert calls == [b.SOURCES[b.EATALY][0]]
    assert original == saved
