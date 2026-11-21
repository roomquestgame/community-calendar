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



def test_mapsee_ics_prunes_only_provably_expired_standalone_uids():
    from icalendar import Calendar, Event
    from roomquest.ics_adapter import _prune_mapsee_historical_singles
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    calendar = Calendar()
    calendar.add("version", "2.0")

    def add(uid, start, end=None, recurring=False):
        event = Event()
        event.add("uid", uid)
        event.add("dtstart", start)
        if end is not None:
            event.add("dtend", end)
        if recurring:
            event.add("rrule", {"freq": ["DAILY"], "count": [3]})
        calendar.add_component(event)

    add("old", now - timedelta(days=30), now - timedelta(days=29))
    add("future", now + timedelta(days=1), now + timedelta(days=2))
    add("old-recurring", now - timedelta(days=30), now - timedelta(days=29), True)
    add("missing-end", now - timedelta(days=30))
    add("date-only", (now - timedelta(days=30)).date(), (now - timedelta(days=29)).date())
    add("duplicate", now - timedelta(days=30), now - timedelta(days=29))
    add("duplicate", now + timedelta(days=1), now + timedelta(days=2))
    trimmed = _prune_mapsee_historical_singles(calendar, now)
    uids = [str(event.get("UID")) for event in trimmed.walk("VEVENT")]
    assert "old" not in uids
    assert uids.count("duplicate") == 2
    assert set(uids) == {"future", "old-recurring", "missing-end", "date-only", "duplicate"}
    assert len(calendar.walk("VEVENT")) == 7



def test_mapsee_horizon_rejects_reversed_time_range():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid_event_end"):
        within_collection_horizon([{
            "starts_at": (now + timedelta(days=2)).isoformat(),
            "ends_at": (now + timedelta(days=1)).isoformat(),
        }], now)



def test_mapsee_detail_page_does_not_enter_reusable_jsonld_collection():
    from roomquest.mapsee_adapter import collect, is_single_event_page
    from unittest.mock import Mock
    url = "https://mdpls.org/event/17225435"
    assert is_single_event_page(url)
    assert not is_single_event_page("https://mdpls.org/events")
    assert not is_single_event_page("https://another.example.org/event/17225435")
    fetch = Mock()
    with pytest.raises(ValueError, match="single_event_page"):
        collect({"source_key": "municipal_mapsee_8c4025191da3db8cbb82946e",
                 "feed_url": url}, {"type": "jsonld"}, fetch)
    fetch.assert_not_called()
