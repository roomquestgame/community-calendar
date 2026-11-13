"""Exact-link checkpoints expose only complete, identity-validated snapshots."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from roomquest import linked_event_descriptions as linked


NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
REVERB = "omaha_reverb_lounge_events"
SANDLER = "municipal_12c58b8068db81adc4284433"


def source(key=REVERB):
    feed, zone, _ = linked.PROFILES[key]
    return {"source_key": key, "feed_url": feed, "timezone": zone,
            "kind": "html", "platform_adapter": "html"}


def event(number, *, url=None, starts_at=None):
    url = url or f"https://reverblounge.com/event/show-{number:02d}/reverb-lounge/"
    return {"id": url, "event_url": url, "title": f"Show {number:02d}",
            "starts_at": starts_at or f"2026-11-{20 + number % 8:02d}T20:00:00-06:00",
            "venue_name": "Reverb Lounge", "venue_address": "6121 Military Ave, Omaha, NE 68104",
            "description": "Old listing prose."}


class Publisher:
    """One listing and exact event pages; any unplanned navigation is an error."""

    def __init__(self, rows, *, key=REVERB):
        self.rows = deepcopy(rows)
        self.source = source(key)
        self.calls = []
        self.extractions = []
        self.preloaded = []
        self.narratives = {}
        self.broken_url = None
        self.rejected_occurrence = None

    def fetch(self, url, accept):
        assert accept == "text/html"
        self.calls.append(url)
        if url == self.source["feed_url"]:
            return "The complete publisher calendar."
        assert url in {row["event_url"] for row in self.rows}, "Followed another page beyond an event link"
        if url == self.broken_url:
            raise OSError("Publisher connection interrupted")
        return json.dumps({"url": url, "description": self.narratives.get(url, f"Publisher prose for {url}"),
                           "more_info_url": "https://other.example/another-page"})

    def collect(self, requested_source, fetch, **kwargs):
        assert requested_source == self.source
        fetch(self.source["feed_url"], "text/html")
        for url in self.preloaded:
            fetch(url, "text/html")
        return deepcopy(self.rows)

    def extract(self, payload, row):
        data = json.loads(payload)
        assert data["url"] == row["event_url"]
        occurrence = (row["id"], row["starts_at"])
        self.extractions.append(occurrence)
        if occurrence == self.rejected_occurrence:
            raise ValueError("fixture_event_identity_mismatch")
        return data["description"]

    def install(self, monkeypatch):
        monkeypatch.setattr(linked, "_adapter", lambda key: (self.collect, self.extract))
        return self

    def chunk(self, checkpoint=None, **kwargs):
        return linked.collect_chunk(self.source, self.fetch, checkpoint=checkpoint, now=kwargs.pop("now", NOW), **kwargs)


def test_chunks_fetch_six_exact_urls_and_never_expose_a_partial_snapshot(monkeypatch):
    publisher = Publisher([event(i) for i in range(13)]).install(monkeypatch)
    checkpoint = None
    for cursor, new_requests in [(6, 6), (12, 6), (13, 1)]:
        publisher.calls.clear()
        result = publisher.chunk(checkpoint, max_details=100)
        checkpoint = json.loads(json.dumps(result["checkpoint"]))
        assert checkpoint["cursor"] == cursor
        assert len(publisher.calls) == new_requests + 1
        assert publisher.calls[0] == publisher.source["feed_url"]
        assert len(set(publisher.calls[1:])) == new_requests
        if cursor < 13:
            assert result["complete"] is False
            assert result["events"] == []
        else:
            assert result["complete"] is True
            assert len(result["events"]) == 13
            assert {(row["id"], row["starts_at"]) for row in result["events"]} == {
                (row["id"], row["starts_at"]) for row in publisher.rows}
            assert all(row["description"].startswith("Publisher prose") for row in result["events"])
    assert len(publisher.extractions) == 13


def test_shared_url_is_fetched_once_and_each_occurrence_is_validated(monkeypatch):
    first = event(0)
    second = {**first, "starts_at": "2026-11-21T20:00:00-06:00"}
    publisher = Publisher([first, second]).install(monkeypatch)
    result = publisher.chunk()
    assert result["complete"] is True
    assert result["checkpoint"]["manifest_count"] == 1
    assert publisher.calls == [publisher.source["feed_url"], first["event_url"]]
    assert publisher.extractions == [(first["id"], first["starts_at"]), (second["id"], second["starts_at"])]
    assert len(result["events"]) == 2
    publisher.rejected_occurrence = (second["id"], second["starts_at"])
    with pytest.raises(ValueError, match="fixture_event_identity_mismatch"):
        publisher.chunk()


def test_reordered_listing_resumes_cached_progress(monkeypatch):
    publisher = Publisher([event(i) for i in range(8)]).install(monkeypatch)
    first = publisher.chunk()["checkpoint"]
    publisher.rows.reverse()
    publisher.calls.clear()
    final = publisher.chunk(first)
    assert final["complete"] is True
    assert final["checkpoint"]["manifest_hash"] == first["manifest_hash"]
    assert publisher.calls == [publisher.source["feed_url"], event(6)["event_url"], event(7)["event_url"]]
    assert len(final["events"]) == 8


def test_changed_manifest_restarts_instead_of_combining_old_facts(monkeypatch):
    publisher = Publisher([event(i) for i in range(8)]).install(monkeypatch)
    first = publisher.chunk()["checkpoint"]
    publisher.rows[0]["title"] = "The publisher changed this performance"
    publisher.calls.clear()
    restarted = publisher.chunk(first)
    assert restarted["complete"] is False
    assert restarted["events"] == []
    assert restarted["checkpoint"]["cursor"] == 6
    assert restarted["checkpoint"]["manifest_hash"] != first["manifest_hash"]
    assert publisher.calls[1:] == [event(i)["event_url"] for i in range(6)]
    assert restarted["checkpoint"]["events"][0]["title"] == publisher.rows[0]["title"]


def test_expired_checkpoint_restarts_exact_page_collection(monkeypatch):
    publisher = Publisher([event(i) for i in range(8)]).install(monkeypatch)
    first = publisher.chunk()["checkpoint"]
    publisher.calls.clear()
    later = NOW + timedelta(hours=4, seconds=1)
    restarted = publisher.chunk(first, now=later)
    assert restarted["complete"] is False
    assert restarted["checkpoint"]["cursor"] == 6
    assert restarted["checkpoint"]["started_at"] == later.isoformat()
    assert publisher.calls[1:] == [event(i)["event_url"] for i in range(6)]


@pytest.mark.parametrize("tamper", [
    "skip_cursor", "past_end", "changed_fact", "changed_url", "missing_row",
    "duplicate_row", "long_description", "wrong_source", "wrong_window", "boolean_cursor", "unhashable_id",
])
def test_tampered_checkpoint_cannot_skip_or_inject_occurrences(monkeypatch, tamper):
    publisher = Publisher([event(i) for i in range(8)]).install(monkeypatch)
    checkpoint = publisher.chunk()["checkpoint"]
    if tamper == "skip_cursor":
        checkpoint["cursor"] += 1
    elif tamper == "past_end":
        checkpoint["cursor"] = checkpoint["manifest_count"] + 1
    elif tamper == "changed_fact":
        checkpoint["events"][0]["venue_address"] = "Another location"
    elif tamper == "changed_url":
        checkpoint["events"][0]["event_url"] = event(7)["event_url"]
    elif tamper == "missing_row":
        checkpoint["events"].pop()
    elif tamper == "duplicate_row":
        checkpoint["events"].append(deepcopy(checkpoint["events"][0]))
    elif tamper == "long_description":
        checkpoint["events"][0]["description"] = "x" * 2001
    elif tamper == "wrong_source":
        checkpoint["source_key"] = SANDLER
    elif tamper == "wrong_window":
        checkpoint["window_start"] = "2020-01-01"
    elif tamper == "unhashable_id":
        checkpoint["events"][0]["id"] = []
    else:
        checkpoint["cursor"] = True
    publisher.calls.clear()
    with pytest.raises(ValueError, match="linked_description_checkpoint_invalid"):
        publisher.chunk(checkpoint)
    assert publisher.calls == [publisher.source["feed_url"]]


def test_transport_failure_leaves_the_input_checkpoint_unchanged(monkeypatch):
    publisher = Publisher([event(i) for i in range(8)]).install(monkeypatch)
    checkpoint = publisher.chunk()["checkpoint"]
    saved = deepcopy(checkpoint)
    publisher.broken_url = event(7)["event_url"]
    with pytest.raises(OSError, match="connection interrupted"):
        publisher.chunk(checkpoint)
    assert checkpoint == saved
    publisher.broken_url = None
    publisher.calls.clear()
    final = publisher.chunk(checkpoint)
    assert final["complete"] is True and len(final["events"]) == 8
    assert publisher.calls[1:] == [event(6)["event_url"], event(7)["event_url"]]


@pytest.mark.parametrize("narrative", ["", "  SHOW   00  "])
def test_valid_empty_or_title_only_description_removes_old_copy(monkeypatch, narrative):
    publisher = Publisher([event(0)]).install(monkeypatch)
    publisher.narratives[event(0)["event_url"]] = narrative
    result = publisher.chunk()
    assert result["complete"] is True
    assert result["events"][0]["description"] == ""
    assert {key: value for key, value in result["events"][0].items() if key != "description"} == {
        key: value for key, value in publisher.rows[0].items() if key != "description"}
    assert publisher.calls == [publisher.source["feed_url"], event(0)["event_url"]]


def test_deadline_before_collection_or_before_detail_does_not_fetch_a_detail(monkeypatch):
    publisher = Publisher([event(0)]).install(monkeypatch)
    monkeypatch.setattr(linked, "monotonic", lambda: 100)
    with pytest.raises(ValueError, match="collection_deadline"):
        publisher.chunk(deadline_at=100)
    assert publisher.calls == []
    with pytest.raises(ValueError, match="collection_deadline"):
        publisher.chunk(deadline_at=117)
    assert publisher.calls == [publisher.source["feed_url"]]


def test_deadline_after_progress_preserves_completed_pages_for_next_chunk(monkeypatch):
    publisher = Publisher([event(i) for i in range(8)]).install(monkeypatch)
    clock = iter([0, 1, 2, 20])
    monkeypatch.setattr(linked, "monotonic", lambda: next(clock))
    result = publisher.chunk(deadline_at=35)
    assert result["complete"] is False and result["events"] == []
    assert result["checkpoint"]["cursor"] == 2
    assert publisher.calls == [publisher.source["feed_url"], event(0)["event_url"], event(1)["event_url"]]


def test_empty_listing_is_a_complete_empty_snapshot(monkeypatch):
    publisher = Publisher([]).install(monkeypatch)
    result = publisher.chunk()
    assert result["complete"] is True and result["events"] == []
    assert result["checkpoint"]["manifest_count"] == result["checkpoint"]["cursor"] == 0
    assert publisher.calls == [publisher.source["feed_url"]]


@pytest.mark.parametrize("url", [
    "https://other.example/event/elsewhere", "https://reverblounge.com/event/show/?next=elsewhere",
    "https://name:secret@reverblounge.com/event/show/",
])
def test_invalid_manifest_links_are_rejected_before_detail_navigation(monkeypatch, url):
    publisher = Publisher([event(0, url=url)]).install(monkeypatch)
    with pytest.raises(ValueError, match="linked_description_manifest_invalid"):
        publisher.chunk()
    assert publisher.calls == [publisher.source["feed_url"]]


def test_real_sandler_multishow_page_is_reused_and_both_occurrences_keep_their_identity(monkeypatch):
    from roomquest import preview_worker

    monkeypatch.setattr(preview_worker, "_future_datetime", lambda value: value.astimezone(timezone.utc))
    requested_source = source(SANDLER)
    url = "https://www.sandlercenter.org/events/detail/fixture-ensemble"
    listing = f'<div class="eventItem"><div class="info"><h3 class="title"><a href="{url}">Fixture Ensemble</a></h3></div></div>'
    showings = "".join(
        f'<li id="showing_{hour}"><span class="showings_date"><span class="m-date__singleDate">Nov 20 / 2026</span></span>'
        f'<span class="wrapper"><span class="time">Friday at {hour}:00pm</span></span></li>'
        for hour in (7, 9))
    narrative = "A touring ensemble performs two evening concerts."
    page = f'''<head><meta property="og:url" content="{url}"></head>
      <div id="content" role="main"><div class="event_detail"><h1 class="title">Fixture Ensemble</h1>
      <div id="column_1"><div class="leftColumn"><div class="event_description"><p>{narrative}</p></div></div></div>
      <div class="event_showings"><ul>{showings}</ul></div>
      <a href="https://tickets.example/checkout">Buy tickets</a></div></div>'''
    pages, calls = {requested_source["feed_url"]: listing, url: page}, []

    def fetch(requested, accept):
        assert accept == "text/html"
        calls.append(requested)
        return pages[requested]

    result = linked.collect_chunk(requested_source, fetch, now=NOW)
    assert result["complete"] is True
    assert result["checkpoint"]["manifest_count"] == 1
    assert calls == [requested_source["feed_url"], url]
    assert len(result["events"]) == 2
    assert {row["id"] for row in result["events"]} == {url}
    assert {datetime.fromisoformat(row["starts_at"]).astimezone(timezone.utc) for row in result["events"]} == {
        datetime(2026, 11, 21, 0, tzinfo=timezone.utc), datetime(2026, 11, 21, 2, tzinfo=timezone.utc)}
    assert {row["description"] for row in result["events"]} == {narrative}
