"""Strict Santa Cruz Friends of State Parks first-party TEC source gates."""
import json

import pytest

from roomquest import wordpress_adapter


SOURCE = {
    "source_key": "friends_sc_state_parks_ca",
    "publisher_name": "Friends of Santa Cruz State Parks",
    "feed_url": "https://thatsmypark.org/wp-json/tribe/events/v1/events",
    "kind": "json",
    "platform_adapter": "wordpress",
    "timezone": "America/Los_Angeles",
}


def event(n=1, **overrides):
    row = {
        "id": str(n),
        "title": "Big Basin Redwoods State Park Guided Walk",
        "starts_at": "2026-11-21T18:00:00+00:00",
        "ends_at": "2026-11-21T20:00:00+00:00",
        "venue_name": "Big Basin Redwoods State Park",
        "venue_address": "21600 Big Basin Way, Boulder Creek, CA, 95006",
        "venue_city": "Boulder Creek",
        "lat": 37.1722714,
        "lng": -122.222453,
        "event_url": "https://thatsmypark.org/event/big-basin-walk/",
        "description": "Official guided walk through the park on its announced date. "
                       "Visitors meet at the published park entrance, bring layers, "
                       "and follow the naturalist-led program.",
        "timezone": "America/Los_Angeles",
    }
    row.update(overrides)
    return row


def collect(monkeypatch, rows, source=None):
    monkeypatch.setattr(wordpress_adapter, "parse_tribe", lambda *a, **kw: rows)
    response = json.dumps({"events": [{"id": 1}], "total_pages": 1})
    return wordpress_adapter.collect(source or SOURCE, lambda url, accept: response)


def test_source_identity_fails_closed(monkeypatch):
    for wrong in (
        {"feed_url": "https://example.com/wp-json/tribe/events/v1/events"},
        {"timezone": "UTC"},
        {"kind": "html"},
    ):
        with pytest.raises(ValueError, match="unregistered_santa_cruz_parks_source"):
            collect(monkeypatch, [event()], {**SOURCE, **wrong})


def test_missing_street_or_native_venue_point_held(monkeypatch):
    rows = [
        event(1),
        event(2, venue_address=""),
        event(3, lat=None),
        event(4, venue_address="Santa Cruz, CA"),
        event(5, event_url="https://othersite.example/event/not-owner"),
        event(6, description="short"),
        event(7, ends_at="2026-11-21T16:00:00+00:00"),
        event(8, venue_address="21600 Big Basin Way, Boulder Creek, CA, 95006", lat=39.0),
    ]
    result = collect(monkeypatch, rows)
    assert [e["id"] for e in result] == ["1"]
    assert result[0]["description"] == rows[0]["description"]
    assert result[0]["lat"] == rows[0]["lat"]


def test_batch_is_bounded_to_twenty_four(monkeypatch):
    rows = [event(i) for i in range(40)]
    result = collect(monkeypatch, rows)
    assert len(result) == 24
    assert len({r["id"] for r in result}) == 24


def test_other_wordpress_sources_untouched(monkeypatch):
    rows = [event(1, venue_address="", lat=None)]
    src = {**SOURCE, "source_key": "other_publisher_original_events_ca"}
    result = collect(monkeypatch, rows, src)
    assert len(result) == 1
