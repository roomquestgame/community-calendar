"""Exact HTML-family dispatch and no-staging guarantees for Bellevue Times."""
from datetime import datetime
from unittest.mock import patch

import pytest

from roomquest import bellevue_times as bt
from roomquest import preview_worker as worker
from tests.test_bellevue_times import CAPTURE, NOW, SOURCE, entry, listing


class FrozenMeta(type):
    def __instancecheck__(cls, instance):
        return isinstance(instance, datetime)


class FrozenDateTime(datetime, metaclass=FrozenMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def test_dispatch_uses_existing_robots_transport_own_host_and_thirty_second_limit():
    before = worker.monotonic()
    outer_deadline = before + 50
    with patch.object(worker, "datetime", FrozenDateTime), patch.object(bt, "datetime", FrozenDateTime), \
            patch.object(worker, "fetch_publisher", return_value=listing([entry()])) as fetch:
        result = worker.preview_source(SOURCE, deadline_at=outer_deadline)
    assert result["p_future_count"] == 1 and result["p_venue_count"] == 0
    assert result["p_error"] is None
    assert result["p_events"] == result["p_samples"]
    row = result["p_events"][0]
    assert row["starts_at"] == "2026-11-14T16:00:00+00:00"
    assert row["ends_at"] == "2026-11-14T17:00:00+00:00"
    assert row["venue_address"] == "2206 Longo Drive, Suite 100, Bellevue, NE 68005"
    assert row["reason"] == "missing_verified_venue_geo"
    assert row["description"] == "A library activity."
    assert row["category"] == "Kids Activities"
    assert row["publisher_categories"] == ["Kids Activities"]
    assert row["timezone"] == "America/Chicago"
    assert fetch.call_args.args == (bt.CALENDAR, "text/html")
    assert fetch.call_args.kwargs["respect_robots"] is True
    assert fetch.call_args.kwargs["allowed_hosts"] == ("bellevuetimes.com",)
    assert before < fetch.call_args.kwargs["deadline_at"] <= worker.monotonic() + 30
    assert fetch.call_args.kwargs["deadline_at"] <= outer_deadline - 5


def test_raw_publisher_evidence_survives_the_existing_staging_and_preview_contract():
    summary = "Adults 21+ only. Tickets are $10; this is a free-for-all craft session."
    html = listing([entry(labels=("Family Activity", "Adults Only", "Paid Admission"), summary=summary)])
    with patch.object(worker, "datetime", FrozenDateTime), patch.object(bt, "datetime", FrozenDateTime), \
            patch.object(worker, "fetch_publisher", return_value=html) as fetch, \
            patch.object(worker, "supabase_rpc", return_value=1) as rpc:
        result = worker._process_claimed_source({**SOURCE, "id": 123})
    assert result == {"complete": 1, "failed": 0, "staged": 1}
    fetch.assert_called_once()
    staged = next(call.args[1]["p_events"] for call in rpc.call_args_list
                  if call.args[0] == "community_collector_record_staged_events")
    preview = next(call.args[1] for call in rpc.call_args_list
                   if call.args[0] == "community_collector_record_preview_v3")
    assert preview["p_samples"] == staged
    assert staged[0]["publisher_categories"] == ["Family Activity", "Adults Only", "Paid Admission"]
    assert staged[0]["category"] == "Family Activity"
    assert staged[0]["description"] == summary


@pytest.mark.parametrize("updates", [
    {"source_key": "bellevue_times_ne_extra"},
    {"source_key": "bellevue_times_wa"},
    {"feed_url": "https://example.com/events/"},
    {"feed_url": bt.CALENDAR + "?bcc_page=2"},
])
def test_exact_registration_guard_runs_before_any_network(updates):
    with patch.object(worker, "fetch_publisher") as fetch:
        with pytest.raises(worker.PreviewError, match="unregistered_html"):
            worker.preview_source({**SOURCE, **updates})
    fetch.assert_not_called()


def test_actual_first_page_succeeds_without_attempting_blocked_later_pages():
    with patch.object(worker, "datetime", FrozenDateTime), patch.object(bt, "datetime", FrozenDateTime), \
            patch.object(worker, "fetch_publisher", side_effect=[CAPTURE, worker.PreviewError("publisher_http_403")]) as fetch:
        result = worker.preview_source(SOURCE)
    fetch.assert_called_once()
    assert fetch.call_args.args == (bt.CALENDAR, "text/html")
    assert result["p_error"] is None and result["p_future_count"] == 28
    assert len(result["p_events"]) == 28
    assert result["p_venue_count"] == 0


def test_first_page_cloudflare_failure_is_not_staged_or_marked_healthy():
    with patch.object(worker, "fetch_publisher", side_effect=worker.PreviewError("publisher_http_403")) as fetch, \
            patch.object(worker, "supabase_rpc", return_value=True) as rpc:
        result = worker._process_claimed_source({**SOURCE, "id": 123})
    assert fetch.call_count == 1
    assert result["failed"] == 1
    assert all(call.args[0] != "community_collector_record_staged_events" for call in rpc.call_args_list)
    preview = next(call.args[1] for call in rpc.call_args_list if call.args[0] == "community_collector_record_preview_v3")
    assert preview["p_error"] == "publisher_http_403"
    assert preview["p_samples"] == [] and preview["p_future_count"] == 0


@pytest.mark.parametrize("html,reason", [
    ("<h1>Just a moment...</h1>", "bellevue_times_listing_structure_unverified"),
    (CAPTURE.replace("Showing 1–30 of 61", "Showing 1–29 of 61"), "bellevue_times_listing_count_mismatch"),
])
def test_incomplete_first_page_is_named_and_never_staged(html, reason):
    with patch.object(worker, "fetch_publisher", return_value=html), \
            patch.object(worker, "supabase_rpc", return_value=True) as rpc:
        result = worker._process_claimed_source({**SOURCE, "id": 123})
    assert result["failed"] == 1
    assert all(call.args[0] != "community_collector_record_staged_events" for call in rpc.call_args_list)
    preview = next(call.args[1] for call in rpc.call_args_list if call.args[0] == "community_collector_record_preview_v3")
    assert preview["p_error"] == reason


def test_other_html_families_keep_their_original_hosts_and_budgets():
    from roomquest import mycountyparks, virginia_state_parks
    for adapter, source, host in (
        (mycountyparks, mycountyparks.source_for_county("iowa"), "www.mycountyparks.com"),
        (virginia_state_parks,
         {"source_key": "virginia_state_parks_oc", "platform_adapter": "html", "kind": "html"},
         "www.dcr.virginia.gov"),
    ):
        def collect(actual_source, fetch, *, deadline_at):
            assert actual_source == source
            assert 35 < deadline_at - worker.monotonic() <= 36
            fetch("https://" + host + "/", "text/html")
            return []
        with patch.object(adapter, "collect", side_effect=collect), patch.object(worker, "fetch_publisher") as fetch:
            assert worker.preview_source(source)["p_error"] is None
        assert fetch.call_args.kwargs["allowed_hosts"] == (host,)
        assert fetch.call_args.kwargs["respect_robots"] is True
