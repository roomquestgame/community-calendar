from datetime import datetime, timedelta, timezone

import pytest

from roomquest.mapsee_adapter import within_collection_horizon


def test_mapsee_horizon_excludes_old_and_far_future_without_truncation():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    def event(days, duration=1):
        start = now + timedelta(days=days)
        return {"starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=duration)).isoformat()}
    records = [event(-90), event(-1, 48), event(1), event(60), event(61)]
    assert within_collection_horizon(records, now) == records[1:4]


def test_mapsee_horizon_does_not_accept_naive_or_unparseable_times():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    for start in ("2026-11-22T10:00:00", "bad", None):
        with pytest.raises(ValueError):
            within_collection_horizon([{"starts_at": start}], now)


def test_mapsee_horizon_keeps_all_in_window_records_for_hard_limit():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    rows = [{"starts_at": (now + timedelta(days=1)).isoformat()} for _ in range(501)]
    assert len(within_collection_horizon(rows, now)) == 501
