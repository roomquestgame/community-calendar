"""ChamberMate uses existing ticket, staging, publication and transport gates."""
import json
from unittest.mock import patch

import pytest

from roomquest import category_worker, chambermate, preview_worker as worker
from test_chambermate import event, snapshot, source


def test_chambermate_dispatch_restricts_host_and_preserves_shared_deadline():
    current = source()
    outer = worker.monotonic() + 35
    payload = json.dumps(snapshot(event()))
    with patch.object(worker, "fetch_publisher", return_value=payload) as fetch:
        output = worker.preview_source(current, deadline_at=outer)
    assert output["p_source_key"] == current["source_key"]
    assert output["p_future_count"] == 1 and output["p_venue_count"] == 0
    assert output["p_error"] is None and len(output["p_events"]) == 1
    assert fetch.call_args.kwargs["allowed_hosts"] == (chambermate.API_HOST,)
    assert fetch.call_args.kwargs["respect_robots"] is True
    assert fetch.call_args.kwargs["deadline_at"] <= outer - 8


def test_ticket_claim_stages_all_batches_then_calls_existing_source_scoped_publisher():
    current = {**source(), "action": "collect"}
    items = [event(activityKey=f"activity-{index}") for index in range(22)]
    items[-1].update(contactTypeCode="Online", address=None)
    options = [{"systemFieldOptionKey": "category", "systemFieldOptionLabel": "Arts, Culture & Music"}]
    for item in items:
        item["eventCategoriesSystemFieldOptionKeys"] = ["category"]
    order, staged = [], []

    def staging_rpc(name, payload, **kwargs):
        order.append(name)
        if name == "community_collector_record_staged_events":
            staged.extend(payload["p_events"])
            assert len(payload["p_events"]) <= 20
            return len(payload["p_events"])
        assert name == "community_collector_record_preview" and payload["p_error"] is None
        return True

    def category_rpc(name, payload, **kwargs):
        order.append(name)
        assert payload["p_category"] == "chambermate" and payload["p_ticket"] == "one-use-ticket"
        if name == "community_collector_claim_category":
            return current
        if name == "community_collector_publish_category":
            assert len(staged) == len(items)
            return {"outcome": "continued"}
        assert name == "community_collector_finish_category" and payload["p_outcome"] == "complete"
        return True

    with patch.object(worker, "fetch_publisher", return_value=json.dumps(snapshot(*items, options=options))) as fetch, \
            patch.object(worker, "supabase_rpc", side_effect=staging_rpc), \
            patch.object(category_worker, "supabase_rpc", side_effect=category_rpc):
        result = category_worker.collect_category("chambermate", "one-use-ticket")
    assert result["complete"] == 1 and result["failed"] == 0 and result["staged"] == 22
    assert fetch.call_count == 1
    assert order == ["community_collector_claim_category", "community_collector_record_staged_events",
                     "community_collector_record_staged_events", "community_collector_record_preview",
                     "community_collector_publish_category", "community_collector_finish_category"]
    assert all(row["publisher_categories"] == ["Arts, Culture & Music"] for row in staged)
    online = next(row for row in staged if row["attendance_mode"] == "online")
    assert online["reason"] == "online_event" and online["venue_address"] == ""


@pytest.mark.parametrize("failure", ["partial_snapshot", "transport_error"])
def test_incomplete_or_failed_snapshot_never_stages_or_publishes(failure):
    current = {**source(), "action": "collect"}
    transport = (worker.PreviewError("publisher_http_403") if failure == "transport_error"
                 else None)
    with patch.object(worker, "fetch_publisher", side_effect=transport,
                      return_value=json.dumps(snapshot(event(), total=2))), \
            patch.object(worker, "supabase_rpc", return_value=True) as staging, \
            patch.object(category_worker, "supabase_rpc", side_effect=[current, True]) as category:
        result = category_worker.collect_category("chambermate", "one-use-ticket")
    assert result["failed"] == 1 and result["complete"] == 0
    assert staging.call_count == 1
    assert staging.call_args.args[0] == "community_collector_record_preview"
    expected = "publisher_http_403" if transport else "incomplete_chambermate_snapshot"
    assert staging.call_args.args[1]["p_error"] == expected
    assert [call.args[0] for call in category.call_args_list] == [
        "community_collector_claim_category", "community_collector_finish_category"]
    assert category.call_args.args[1]["p_outcome"] == "failed"


def test_publication_continuation_reuses_staged_chambermate_data_without_fetch():
    with patch.object(category_worker, "supabase_rpc", side_effect=[{"action": "publish"},
                       {"outcome": "continued"}, True]), patch.object(worker, "fetch_publisher") as fetch:
        category_worker.collect_category("chambermate", "one-use-ticket")
    fetch.assert_not_called()


def test_unregistered_chambermate_source_never_contacts_the_network():
    with patch.object(worker, "fetch_publisher") as fetch:
        with pytest.raises(worker.PreviewError, match="unregistered_chambermate_source"):
            worker.preview_source(source(feed_url="https://example.org/calendar"))
    fetch.assert_not_called()
