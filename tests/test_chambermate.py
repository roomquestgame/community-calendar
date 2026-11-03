"""Public ChamberMate contract: bounded complete snapshots and factual fields."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

import pytest

from roomquest import chambermate as cm


def source(**changes):
    return {
        "source_key": "chambermate_clarksville_va", "platform_adapter": "chambermate", "kind": "json",
        "feed_url": cm.API_URL + "?websiteShorthand=clarksvillelakecountrychamber&"
                    "websiteDomain=clarksvillelakecountrychamber.chambermate.com",
        "timezone": "America/New_York", **changes,
    }


def observed():
    return json.loads((Path(__file__).parent / "fixtures/chambermate_clarksville_public.json").read_text())


def event(index=0, **changes):
    item = deepcopy(observed()["data"]["events"][index])
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0, tzinfo=None)
    item.update(startDateTime=start.isoformat(), endDateTime=(start + timedelta(hours=2)).isoformat())
    item.update(changes)
    if "activityKey" in changes and "eventDetailUrl" not in changes:
        item["eventDetailUrl"] = "https://clarksvillelakecountrychamber.chambermate.com/event-detail?e=" + quote(item["activityKey"], safe="")
    return item


def snapshot(*events, total=None, options=None):
    return {"status": True, "error": None, "data": {
        "events": list(events), "eventsCount": len(events) if total is None else total,
        "timeZoneIANAId": "EST5EDT",
        "eventCategories": {"systemFieldLabel": "Event Categories", "systemFieldOptions": options or []},
    }}


def test_observed_fixture_preserves_ids_utc_and_the_shared_sixty_day_window():
    data = observed()
    assert data["data"]["eventsCount"] == len(data["data"]["events"]) == 9
    # Keep the captured relative dates deterministic as this test runs later.
    anchor = (datetime.now(timezone.utc) + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    shift = anchor - datetime(2026, 11, 10, tzinfo=timezone.utc)
    for item in data["data"]["events"]:
        for key in ("startDateTime", "endDateTime"):
            item[key] = (cm.utc_timestamp(item[key]) + shift).replace(tzinfo=None).isoformat()
    rows = cm.parse(data, source())
    # January 12 is 63 days after the first captured event: outside intake's
    # normal horizon, while all eight November/December events are retained.
    assert len(rows) == 8
    original = data["data"]["events"][0]
    row = next(row for row in rows if row["id"] == original["activityKey"])
    assert row["starts_at"] == original["startDateTime"] + "+00:00"
    assert row["event_url"] == original["eventDetailUrl"]
    assert row["timezone"] == "America/New_York"
    assert row["publisher_categories"] == [] and row["category"] == ""
    assert row["publisher_event_type"] == "MBR"
    assert {row["attendance_mode"] for row in rows} == {"in_person", "online"}


def test_utc_without_z_is_not_misread_as_eastern_wall_time():
    winter = cm.utc_timestamp("2026-11-10T14:00:00")
    summer = cm.utc_timestamp("2026-07-10T14:00:00Z")
    assert winter.isoformat() == "2026-11-10T14:00:00+00:00"
    assert winter.astimezone(ZoneInfo("America/New_York")).hour == 9
    assert summer.astimezone(ZoneInfo("America/New_York")).hour == 10


def test_one_public_request_includes_all_host_groups_and_a_bounded_row_count():
    fetch = Mock(return_value=json.dumps(snapshot(event())))
    rows = cm.collect(source(), fetch)
    assert len(rows) == 1 and fetch.call_count == 1
    url, accept = fetch.call_args.args
    assert urlsplit(url).hostname == cm.API_HOST
    assert urlsplit(url).path == "/core/biz/webPresence/getEventsInfo"
    assert accept == "application/json"
    fields = parse_qs(urlsplit(url).query)
    assert fields["eventTypeCodes"] == ["CHMBR", "MBR", "COMM"]
    assert fields["isPortal"] == ["false"]
    assert fields["includeCategories"] == ["true"]
    assert fields["includePastEvents"] == ["true"]
    start = datetime.fromisoformat(fields["startDateTime"][0])
    end = datetime.fromisoformat(fields["endDateTime"][0])
    assert end - start == timedelta(days=60)
    assert abs((datetime.now(timezone.utc) - start).total_seconds()) < 5
    assert fields["rowCount"] == [str(cm.MAX_RECORDS + 1)]
    assert set(fields) == {"websiteShorthand", "websiteDomain", "isPortal", "eventTypeCodes",
                           "includeCategories", "includePastEvents", "startDateTime", "endDateTime", "rowCount"}


@pytest.mark.parametrize("changes", [
    {"platform_adapter": "growthzone"}, {"kind": "html"}, {"timezone": None},
    {"timezone": "not/a/timezone"}, {"feed_url": "http://api.chambermate.com/core/biz/webPresence/getEventsInfo"},
    {"feed_url": source()["feed_url"].replace("api.chambermate.com", "api.chambermate.com.evil.example")},
    {"feed_url": source()["feed_url"].replace("https://", "https://user:pass@")},
    {"feed_url": source()["feed_url"].replace("api.chambermate.com/", "api.chambermate.com:444/")},
    {"feed_url": source()["feed_url"].replace("getEventsInfo", "getEventInfo")},
    {"feed_url": source()["feed_url"] + "#another-tenant"},
    {"feed_url": source()["feed_url"] + "&isPortal=true"},
    {"feed_url": source()["feed_url"] + "&websiteShorthand=other"},
    {"feed_url": source()["feed_url"].replace("websiteShorthand=clarksvillelakecountrychamber", "websiteShorthand=other")},
    {"publisher_url": "https://different.chambermate.com/standalone?id=test"},
])
def test_unregistered_endpoint_or_tenant_fails_before_fetch(changes):
    fetch = Mock()
    with pytest.raises(ValueError):
        cm.collect(source(**changes), fetch)
    fetch.assert_not_called()


def test_another_reviewed_tenant_uses_the_same_adapter_without_source_key_rules():
    other = source(source_key="owner_registered_chamber", feed_url=cm.API_URL +
                   "?websiteShorthand=otherchamber&websiteDomain=otherchamber.chambermate.com")
    item = event()
    item["eventDetailUrl"] = item["eventDetailUrl"].replace("clarksvillelakecountrychamber", "otherchamber")
    rows = cm.parse(snapshot(item), other)
    assert rows[0]["id"] == item["activityKey"]
    assert urlsplit(rows[0]["event_url"]).hostname == "otherchamber.chambermate.com"


@pytest.mark.parametrize("total", [0, 2, 9])
def test_truncated_or_filtered_snapshot_never_reports_success(total):
    with pytest.raises(ValueError, match="incomplete_chambermate_snapshot"):
        cm.parse(snapshot(event(), total=total), source())


def test_oversized_snapshot_fails_instead_of_slicing():
    with pytest.raises(ValueError, match="source_record_limit"):
        cm.parse(snapshot(*([event()] * 501)), source())
    with pytest.raises(ValueError, match="source_record_limit"):
        cm.parse(snapshot(event(), total=501), source())


def test_valid_empty_snapshot_and_invalid_responses_are_distinct():
    assert cm.parse(snapshot(), source()) == []
    for invalid in ({}, {"status": False, "error": "upstream"}, {"status": True, "data": []}):
        with pytest.raises(ValueError, match="invalid_chambermate_payload"):
            cm.parse(invalid, source())
    for total in (None, True, "1", -1):
        data = snapshot(event())
        data["data"]["eventsCount"] = total
        with pytest.raises(ValueError, match="invalid_chambermate_snapshot"):
            cm.parse(data, source())
    with pytest.raises(ValueError, match="invalid_chambermate_payload"):
        cm.collect(source(), Mock(return_value="<html>Unavailable</html>"))


def test_timezone_change_requires_review():
    data = snapshot(event())
    data["data"]["timeZoneIANAId"] = "America/Chicago"
    with pytest.raises(ValueError, match="chambermate_timezone_mismatch"):
        cm.parse(data, source())


@pytest.mark.parametrize("url", [
    "https://different.chambermate.com/event-detail?e=other",
    "https://clarksvillelakecountrychamber.chambermate.com/event-detail?e=other",
    "https://clarksvillelakecountrychamber.chambermate.com/event-detail?e=sample&e=sample",
    "https://clarksvillelakecountrychamber.chambermate.com/event-detail?e=sample#other",
    "https://clarksvillelakecountrychamber.chambermate.com/standalone?e=sample",
    "https://user@clarksvillelakecountrychamber.chambermate.com/event-detail?e=sample",
    "http://clarksvillelakecountrychamber.chambermate.com/event-detail?e=sample",
    "https://127.0.0.1/event-detail?e=sample",
])
def test_event_links_are_tenant_and_identity_bound(url):
    with pytest.raises(ValueError, match="event_link|identity_mismatch"):
        cm.parse(snapshot(event(activityKey="sample", eventDetailUrl=url)), source())


def test_actual_event_address_is_preserved_without_organizer_or_source_pin():
    item = event()
    item["associations"] = [{"company": {"companyName": "Organizer Office", "address": {
        "street1": "999 Wrong Road", "city": "Clarksville", "stateCode": "VA"}}}]
    item["address"].update(latitude=36.62, longitude=-78.56)
    row = cm.parse(snapshot(item), source(lat=36.62, lng=-78.56, city="Clarksville"))[0]
    assert row["venue_address"] == "715 Wilborn Ave, South Boston, VA, 24592"
    assert row["venue_city"] == "South Boston"
    assert row["lat"] is None and row["lng"] is None
    assert "Organizer Office" not in row["venue_name"]


@pytest.mark.parametrize("contact,mode", [("Online", "online"), ("Phone", "phone")])
def test_remote_event_stays_unlocated_even_with_an_address_and_organizer_office(contact, mode):
    item = event(4, contactTypeCode=contact)
    assert item["associations"][0]["company"]["address"]["street1"] == "715 Wilborn Ave"
    item["address"] = event()["address"]
    row = cm.parse(snapshot(item), source())[0]
    assert row["attendance_mode"] == mode and row["reason"] == mode + "_event"
    assert row["venue_name"] == row["venue_address"] == row["venue_city"] == ""
    assert row["lat"] is None and row["lng"] is None
    assert row["event_url"] == item["eventDetailUrl"]


def test_hybrid_event_uses_only_its_actual_physical_address():
    row = cm.parse(snapshot(event(contactTypeCode="Hybrid")), source())[0]
    assert row["attendance_mode"] == "hybrid"
    assert row["venue_address"] == "715 Wilborn Ave, South Boston, VA, 24592"
    assert row["lat"] is None and row["lng"] is None


def test_freeform_event_location_overrides_stale_structured_address_without_guesses():
    item = event(addressCode="Freeform Custom Text",
                 customAddress="<p>Community room at Lakeside Center; see event directions.</p>")
    assert item["address"]["street1"] == "715 Wilborn Ave"
    row = cm.parse(snapshot(item), source())[0]
    assert row["venue_address"] == "Community room at Lakeside Center; see event directions."
    assert row["venue_name"] == row["venue_city"] == ""
    assert row["lat"] is None and row["lng"] is None
    with pytest.raises(ValueError, match="chambermate_custom_address_missing"):
        cm.parse(snapshot(event(addressCode="Freeform Custom Text", customAddress=None)), source())


def test_missing_physical_address_is_retained_for_existing_location_review():
    row = cm.parse(snapshot(event(address=None)), source())[0]
    assert row["attendance_mode"] == "in_person"
    assert row["venue_name"] == row["venue_address"] == ""
    assert row["reason"] == "missing_verified_venue_geo"


def test_category_labels_remain_individual_and_unmapped():
    options = [
        {"systemFieldOptionKey": "arts", "systemFieldOptionLabel": "Arts, Culture & Music"},
        {"systemFieldOptionKey": "learn", "systemFieldOptionLabel": "Professional Learning"},
    ]
    item = event(eventCategoriesSystemFieldOptionKeys=["arts", "learn"])
    row = cm.parse(snapshot(item, options=options), source())[0]
    assert row["publisher_categories"] == ["Arts, Culture & Music", "Professional Learning"]
    assert row["category"] == "Arts, Culture & Music, Professional Learning"
    assert row["publisher_event_type"] == "MBR"
    assert not any(key in row for key in ("category_id", "classification", "canonical_category"))


def test_description_preserves_bounded_plain_classifier_evidence():
    item = event(eventFullDescription="<p>Full workshop &amp; discussion.</p>",
                 eventDescription="Short description")
    assert cm.parse(snapshot(item), source())[0]["description"] == "Full workshop & discussion."
    item = event(eventFullDescription=None, eventDescription="<p>Practical learning.</p> " * 200)
    text = cm.parse(snapshot(item), source())[0]["description"]
    assert text.startswith("Practical learning.") and "<p>" not in text
    assert len(text) == 2000
    item = event(eventFullDescription="<p></p>",
                 eventDescription="<script>tracking()</script><style>p{color:red}</style><p>Public workshop.</p>")
    assert cm.parse(snapshot(item), source())[0]["description"] == "Public workshop."


def test_missing_or_conflicting_category_evidence_is_not_silently_dropped():
    with pytest.raises(ValueError, match="unresolved_publisher_category"):
        cm.parse(snapshot(event(eventCategoriesSystemFieldOptionKeys=["missing"])), source())
    options = [{"systemFieldOptionKey": "one", "systemFieldOptionLabel": label} for label in ("Music", "Learning")]
    with pytest.raises(ValueError, match="conflicting_publisher_category"):
        cm.parse(snapshot(event(), options=options), source())
    with pytest.raises(ValueError, match="source_category_limit"):
        cm.parse(snapshot(event(eventCategoriesSystemFieldOptionKeys=["one"] * 21)), source())


@pytest.mark.parametrize("changes,reason", [
    ({"noTimes": True}, "unsupported_all_day_time"),
    ({"noTimes": "false"}, "invalid_chambermate_flags"),
    ({"startDateTime": "2026-11-10"}, "invalid_chambermate_time"),
    ({"startDateTime": "2026-11-10T14:00:00-05:00"}, "invalid_chambermate_time"),
    ({"daySchedules": {}}, "invalid_chambermate_schedule"),
    ({"contactTypeCode": "Unknown"}, "unsupported_chambermate_attendance"),
    ({"eventTypeCode": "PRIVATE"}, "unsupported_chambermate_event_type"),
])
def test_unsupported_or_ambiguous_shapes_fail_explicitly(changes, reason):
    with pytest.raises(ValueError, match=reason):
        cm.parse(snapshot(event(**changes)), source())


def test_end_flags_and_ongoing_events_keep_shared_lifetime_semantics():
    item = event(noEndTime=True, endDateTime="not-a-displayed-end")
    assert cm.parse(snapshot(item), source())[0]["ends_at"] is None
    item = event()
    item["endDateTime"] = item["startDateTime"]
    with pytest.raises(ValueError, match="invalid_chambermate_end"):
        cm.parse(snapshot(item), source())
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    item = event(startDateTime=(now - timedelta(hours=1)).isoformat(),
                 endDateTime=(now + timedelta(minutes=5)).isoformat())
    assert len(cm.parse(snapshot(item), source())) == 1
    item["endDateTime"] = (now - timedelta(minutes=1)).isoformat()
    assert cm.parse(snapshot(item), source()) == []


def test_duplicate_conflict_cannot_replace_an_occurrence_silently():
    item = event()
    assert len(cm.parse(snapshot(item, deepcopy(item)), source())) == 1
    conflict = {**item, "eventName": "Different event"}
    with pytest.raises(ValueError, match="conflicting_event_occurrence"):
        cm.parse(snapshot(item, conflict), source())


def test_explicit_schedules_preserve_each_interval_without_parent_range_or_end_flag():
    first, second = event(), event()
    second["startDateTime"] = (cm.utc_timestamp(first["startDateTime"]) + timedelta(days=3)).replace(tzinfo=None).isoformat()
    second["endDateTime"] = (cm.utc_timestamp(second["startDateTime"]) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    schedules = [{key: item[key] for key in ("startDateTime", "endDateTime")} for item in (first, second)]
    item = event(startDateTime="parent-summary-not-an-occurrence", endDateTime=None,
                 noEndTime=True, daySchedules=[schedules[0], schedules[1], deepcopy(schedules[0])])
    rows = cm.parse(snapshot(item), source())
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {item["activityKey"]}
    assert [row["starts_at"] for row in rows] == [part["startDateTime"] + "+00:00" for part in schedules]
    assert [row["ends_at"] for row in rows] == [part["endDateTime"] + "+00:00" for part in schedules]


def test_schedule_same_start_with_conflicting_end_fails():
    item = event()
    first = {key: item[key] for key in ("startDateTime", "endDateTime")}
    second = {**first, "endDateTime": (cm.utc_timestamp(first["endDateTime"]) + timedelta(hours=1)).replace(tzinfo=None).isoformat()}
    item["daySchedules"] = [first, second]
    with pytest.raises(ValueError, match="conflicting_event_occurrence"):
        cm.parse(snapshot(item), source())


def test_each_explicit_occurrence_obeys_the_shared_window():
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    intervals = [{"startDateTime": (now + timedelta(days=days)).isoformat(),
                  "endDateTime": (now + timedelta(days=days, hours=1)).isoformat()} for days in (-2, 2, 70)]
    rows = cm.parse(snapshot(event(daySchedules=intervals)), source())
    assert len(rows) == 1 and rows[0]["starts_at"] == intervals[1]["startDateTime"] + "+00:00"


def test_total_explicit_occurrences_are_bounded_even_with_only_two_parent_events():
    item = event()
    interval = {key: item[key] for key in ("startDateTime", "endDateTime")}
    first = event(activityKey="first", daySchedules=[interval] * 251)
    second = event(activityKey="second", daySchedules=[interval] * 251)
    with pytest.raises(ValueError, match="source_record_limit"):
        cm.parse(snapshot(first, second), source())


def test_image_is_a_public_event_candidate_with_no_fallback_and_no_fetch():
    item = event()
    row = cm.parse(snapshot(item), source())[0]
    image = urlsplit(row["image_url"])
    assert image.hostname == cm.API_HOST and image.path == "/core/app/storage/directView"
    assert parse_qs(image.query) == {"k": [item["avatarStorageKey"]]}
    assert "image_url" not in cm.parse(snapshot(event(avatarStorageKey="EVENT/../../secret?url=https://evil.example")), source())[0]


def test_expired_deadline_does_not_start_a_request():
    fetch = Mock()
    with pytest.raises(ValueError, match="collection_deadline"):
        cm.collect(source(), fetch, deadline_at=-1)
    fetch.assert_not_called()


def test_fetch_consuming_deadline_cannot_return_a_successful_snapshot(monkeypatch):
    monkeypatch.setattr(cm, "monotonic", Mock(side_effect=[0, 1, 21]))
    with pytest.raises(ValueError, match="collection_deadline"):
        cm.collect(source(), Mock(return_value=json.dumps(snapshot(event()))), deadline_at=30)
