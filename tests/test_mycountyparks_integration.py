"""Publication-shape and collector-dispatch regressions for MyCountyParks."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from roomquest import preview_worker as worker
from roomquest.mapsee_adapter import record


def normalized(start, end, *, retain_until_end=False):
    return record(
        "Nature program", start.isoformat(), end.isoformat() if end else None,
        "Lake Iowa Nature Center", "2550 G Ave, Ladora, IA 52251", "Ladora",
        "https://www.mycountyparks.com/County/Iowa/Park/Lake-Iowa-Park/Events/29872/Open-Nature-Center-Saturday",
        "mycountyparks:29872", tz="America/Chicago", retain_until_end=retain_until_end,
    )


def test_opt_in_retains_event_with_less_than_an_hour_remaining():
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(hours=1), now + timedelta(minutes=5)
    assert normalized(start, end) is None
    row = normalized(start, end, retain_until_end=True)
    assert row["starts_at"] == start.isoformat()
    assert row["ends_at"] == end.isoformat()


def test_missing_end_visibility_is_three_hours_without_fabricated_end():
    now = datetime.now(timezone.utc)
    row = normalized(now - timedelta(hours=2), None, retain_until_end=True)
    assert row["ends_at"] is None
    assert row["lat"] is None and row["lng"] is None
    assert normalized(now - timedelta(hours=4), None, retain_until_end=True) is None


def test_explicit_end_takes_precedence_over_three_hour_fallback():
    now = datetime.now(timezone.utc)
    assert normalized(now - timedelta(minutes=15), now - timedelta(minutes=1),
                      retain_until_end=True) is None


def test_future_events_keep_existing_normalization():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    assert normalized(start, None) == normalized(start, None, retain_until_end=True)


@pytest.mark.parametrize("county", ["iowa", "mahaska", "black_hawk", "obrien"])
def test_mycountyparks_dispatch_uses_its_own_host_and_common_shape(county):
    from roomquest import mycountyparks as adapter
    source = adapter.source_for_county(county)
    row = normalized(datetime.now(timezone.utc) + timedelta(days=1), None)
    outer_deadline = worker.monotonic() + 35

    def collect(source_arg, fetch, *, deadline_at):
        assert source_arg == source
        assert deadline_at > worker.monotonic()
        assert deadline_at <= outer_deadline - 5
        fetch(source_arg["feed_url"], "text/html")
        return [row]

    with patch.object(adapter, "collect", side_effect=collect), \
            patch.object(worker, "fetch_publisher", return_value="html") as fetch:
        result = worker.preview_source(source, deadline_at=outer_deadline)
    assert result["p_events"] == [row]
    assert result["p_future_count"] == 1 and result["p_venue_count"] == 0
    assert result["p_error"] is None
    assert fetch.call_args.kwargs["allowed_hosts"] == ("www.mycountyparks.com",)
    assert fetch.call_args.kwargs["respect_robots"] is True


def test_unknown_html_source_cannot_dispatch_to_publisher():
    with patch.object(worker, "fetch_publisher") as fetch:
        with pytest.raises(worker.PreviewError, match="unregistered_html_source"):
            worker.preview_source({"kind": "html", "platform_adapter": "html", "source_key": "unregistered"})
    fetch.assert_not_called()


@pytest.mark.parametrize("source_key,url", [
    ("mycountyparks_ia_unknown", "https://www.mycountyparks.com/County/Unknown/Events"),
    ("mycountyparks_ia_mahaska", "https://www.mycountyparks.com/County/Marion/Events"),
    ("mycountyparks_ia_mahaska", "https://www.mycountyparks.com/County/Mahaska/Events?redirect=1"),
    ("mycountyparks_ia_mahaska", "https://example.org/County/Mahaska/Events"),
])
def test_expanded_dispatch_still_validates_catalog_identity_before_network(source_key, url):
    source = {"kind": "html", "platform_adapter": "html", "source_key": source_key, "feed_url": url}
    with patch.object(worker, "fetch_publisher") as fetch:
        with pytest.raises(worker.PreviewError, match="county_unregistered|unregistered_html_calendar"):
            worker.preview_source(source)
    fetch.assert_not_called()


def test_transport_failure_keeps_explicit_error_and_never_stages():
    from roomquest import mycountyparks as adapter
    source = {**adapter.source_for_county("iowa"), "id": 1}
    with patch.object(adapter, "collect", side_effect=worker.PreviewError("publisher_http_403")), \
            patch.object(worker, "supabase_rpc", return_value=True) as rpc:
        result = worker._process_claimed_source(source)
    assert result["failed"] == 1
    assert all(call.args[0] != "community_collector_record_staged_events" for call in rpc.call_args_list)
    preview = next(call.args[1] for call in rpc.call_args_list if call.args[0] == "community_collector_record_preview_v2")
    assert preview["p_error"] == "publisher_http_403"
