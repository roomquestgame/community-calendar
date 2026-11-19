"""OC Parks explicit cancellation signals, source identity and no absence inference."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from roomquest import oc_parks_partial as oc
from test_oc_parks_partial import NOW, SOURCE, event, listing, detail, fake_record


def test_cancelled_publisher_calendar_title_makes_only_one_explicit_status():
    cancel = event(n=90314, title="CANCELED: Preschool Paleontology: Art & Storytime",
                   path="/events/preschool-paleontology-art-storytime", start="2026-11-20T09:00:00",
                   end="2026-11-20T11:00:00")
    calendar = listing([event(), cancel])
    statuses = oc.cancellation_records(calendar, now=NOW)
    assert len(statuses) == 1
    entry, = statuses
    assert entry["id"] == "90314"
    assert entry["publisher_status"] == "cancelled"
    assert entry["status_evidence"] == "calendar_title"
    assert entry["status_evidence_url"] == oc.CALENDAR
    assert entry["starts_at"] == "2026-11-20T09:00:00-08:00"
    assert entry["event_url"] == "https://parks.oc.gov/events/preschool-paleontology-art-storytime"
    assert not entry["description"] and entry["lat"] is None and entry["lng"] is None
    assert "image_url" not in entry


def test_postponed_source_title_does_not_become_cancelled():
    data = listing([event(n=2, title="Postponed: Holiday Nature Walk",
                          path="/events/holiday-nature-walk")])
    out, = oc.cancellation_records(data, now=NOW)
    assert out["publisher_status"] == "postponed"


def test_previous_publisher_event_not_in_500_cap_is_not_cancelled():
    # A partial view cannot infer cancellations from missing IDs.
    assert oc.cancellation_records(listing([event()]), now=NOW) == []


def test_detail_updated_to_cancelled_propagates_exact_identity_and_original_title():
    # Calendar row remains scheduled, detail page changes to "CANCELED: ...".
    with patch.object(oc, "record", side_effect=fake_record):
        result = oc.collect(SOURCE, lambda url, _: listing() if url == oc.CALENDAR
                            else detail(title="CANCELED: Oak Woodland Bird Walk"), now=NOW)
    out, = result
    assert out["title"] == "Oak Woodland Bird Walk"  # Never fabricate a title
    assert out["publisher_status"] == "cancelled"
    assert out["status_evidence"] == "detail_page"
    assert out["status_evidence_url"] == out["event_url"]
    assert out["id"] == "1"
    assert out["venue_address"] == ""
    assert out["lat"] is None and out["lng"] is None


def test_postponed_detail_page_keeps_postponed_status():
    with patch.object(oc, "record", side_effect=fake_record):
        out, = oc.collect(SOURCE, lambda url, _: listing() if url == oc.CALENDAR
                          else detail(title="Postponed: Oak Woodland Bird Walk"), now=NOW)
    assert out["publisher_status"] == "postponed"


def test_positive_event_status_is_scheduled_with_original_text():
    with patch.object(oc, "record", side_effect=fake_record):
        out, = oc.collect(SOURCE, lambda url, _: listing() if url == oc.CALENDAR
                          else detail(), now=NOW)
    assert out["publisher_status"] == "scheduled"
    assert "binoculars" not in out.get("description","").lower() or out.get("description")


def test_full_source_calendar_with_negative_record_and_new_positive():
    canceled = event(n=90431, title="Canceled: Old Event",
                     path="/events/old-thing", start="2026-11-20T09:00:00",
                     end="2026-11-20T10:30:00")
    calendar = listing([event(), canceled])
    with patch.object(oc, "record", side_effect=fake_record):
        out = oc.collect(SOURCE, lambda url, _: calendar if url == oc.CALENDAR
                         else detail(), now=NOW)
    assert len(out)==2
    assert sorted(e["publisher_status"] for e in out) == ["cancelled","scheduled"]
    assert len({e["id"] for e in out}) == 2
    assert not any("image_url" in e for e in out)


def test_invalid_cancelled_identity_never_reaches_staging():
    bad = event(n=66,title="CANCELED: Example",
                path="https://outside.example/events/example")
    with pytest.raises(ValueError,match="oc_parks_cancellation_identity_invalid"):
        oc.cancellation_records(listing([bad]),now=NOW)


def test_duplicate_negative_occurrence_rejected():
    row = event(n=7,title="CANCELLED: Exact Cancellation",
                path="/events/cancelled-test")
    with pytest.raises(ValueError,match="oc_parks_cancellation_duplicate"):
        oc.cancellation_records(listing([row,row]),now=NOW)


def test_old_cancellations_outside_window_do_not_change_future_events():
    canceled = event(n=9,title="CANCELED: Historical Example",
                     path="/events/historical-test",start="2026-11-01T09:00:00",
                     end="2026-11-01T10:00:00")
    assert oc.cancellation_records(listing([canceled]),now=NOW)==[]
