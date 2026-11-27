from copy import deepcopy

from roomquest.event_content import attach_original_event_content, original_event_content


SOURCE = {
    "kind": "html", "platform_adapter": "html",
    "timezone": "America/New_York", "publisher_name": "Provider A",
}


def event():
    return {
        "id": "publisher-42", "title": "Community class",
        "description": "Bring a notebook.",
        "starts_at": "2026-12-02T14:00:00+00:00",
        "ends_at": "2026-12-02T15:00:00+00:00",
        "event_url": "https://example.org/events/42",
        "venue_name": "Town Hall", "venue_address": "1 Main St",
        "timezone": "America/New_York", "publisher_categories": ["Class", "Free"],
        "image_url": "https://example.org/events/42.jpg",
    }


def test_provider_label_is_not_part_of_common_event_facts():
    row = event()
    renamed = deepcopy(SOURCE)
    renamed["publisher_name"] = "Provider B"
    assert original_event_content(row, SOURCE) == original_event_content(row, renamed)


def test_event_detail_change_changes_common_event_facts():
    row = event()
    changed = deepcopy(row)
    changed["title"] = "Community class — updated"
    assert original_event_content(row, SOURCE) != original_event_content(changed, SOURCE)


def test_shared_writer_covers_html_json_and_wordpress_rss_only_once():
    for source in (
        SOURCE,
        {"kind": "json", "platform_adapter": "wordpress", "timezone": "UTC"},
        {"kind": "rss", "platform_adapter": "wordpress", "timezone": "UTC"},
    ):
        rows = [event()]
        attach_original_event_content(rows, source)
        first = deepcopy(rows[0]["collector_event_content_v1"])
        source["publisher_name"] = "Renamed provider"
        attach_original_event_content(rows, source)
        assert rows[0]["collector_event_content_v1"] == first


def test_local_publisher_schedule_is_preserved_without_provider_metadata():
    row = event()
    row["starts_at"] = "2026-12-02T09:00:00"
    row["ends_at"] = "2026-12-02T10:00:00"
    facts = original_event_content(row, SOURCE)["facts"]
    assert facts["starts_at_local"] == "2026-12-02T09:00:00"
    assert facts["ends_at_local"] == "2026-12-02T10:00:00"
    assert "starts_at_utc" not in facts
    assert "publisher_name" not in facts


def test_unsupported_writer_does_not_leak_unknown_envelope_to_legacy_rpc():
    rows = [event()]
    attach_original_event_content(rows, {"kind": "rss", "platform_adapter": "library"})
    assert "collector_event_content_v1" not in rows[0]
