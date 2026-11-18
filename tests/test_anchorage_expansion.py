"""New Anchorage source adapters: bounded months, strict street + narrative."""
from datetime import datetime, timezone
import json

import pytest

from roomquest import anchorage_expansion as ak2
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(preview_worker, '_future_datetime',
                        lambda value: value.astimezone(timezone.utc))


def source(key):
    url, kind, adapter = ak2.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind,
                platform_adapter=adapter, timezone=ak2.ZONE)


def millis(date):
    return int(datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp() * 1000)


def zoo_event(title="Weekly Community Storytime", **kwargs):
    record = dict(
        id="zoo-001", workflowState=1, title=title,
        startDate=millis("2026-12-02T19:30:00Z"),
        endDate=millis("2026-12-02T20:00:00Z"),
        body="<section><p>Stories &amp; wildlife education at the zoo.</p></section>",
        categories=[],
        location={"addressTitle": "The Alaska Zoo",
                  "addressLine1": "4731 O&#39;Malley Road",
                  "addressLine2": "Anchorage, AK, 99507",
                  "mapLat": 61.1236344, "mapLng": -149.7908746},
        fullUrl="/event-calendar/2026/december-30-weekly-community-storytime",
        assetUrl=("https://images.squarespace-cdn.com/content/v1/"
                  "59b9ecdabebafb8293096530/1791001020304-ABCDE/Zoo+Walk.jpg"))
    record.update(kwargs)
    return record


def zoo_fetch(data):
    def fetch(url, accept):
        assert accept == "application/json"
        assert url.startswith(ak2.SOURCES[ak2.ZOO][0] + "?month=")
        month = url.split("month=", 1)[1].split("&", 1)[0]
        return json.dumps({"website": {"timeZone": ak2.ZONE}, "items": data.get(month, [])})
    return fetch


def history_event(**kwargs):
    e = dict(
        id="history-001", workflowState=1,
        title="Celebrating America250: Alaska's Year of Dreams",
        startDate=millis("2026-11-20T04:00:00Z"),
        endDate=millis("2026-11-20T05:30:00Z"),
        body="<p>" + ("An Alaska history lecture. " * 120) + " &amp; questions.</p>",
        categories=[],
        fullUrl="/lecture-series/celebrating-america250-alaskas-year-of-dreams",
        location={"addressTitle": "Anchorage Museum",
                  "addressLine1": "625 C Street",
                  "addressLine2": "Anchorage, AK 99508",
                  "mapLat": 61.215893, "mapLng": -149.8846999},
        assetUrl=("https://images.squarespace-cdn.com/content/v1/"
                  "5d1d16338ed08b0001ebc5c8/1791242636317-ABCDE/Lecture.jpg"))
    e.update(kwargs)
    return e


def history_fetch(*events, **extra):
    data = {"website": {"timeZone": ak2.ZONE}, "upcoming": list(events),
            "pagination": {"nextPage": False}}
    data.update(extra)
    def fetch(url, accept):
        assert url == ak2.SOURCES[ak2.HISTORY][0] + "?format=json"
        assert accept == "application/json"
        return json.dumps(data)
    return fetch


def test_zoo_bounded_month_pages_with_all_three_permalinks():
    story = zoo_event()
    tour = zoo_event(
        id="zoo-002", title="Alaska's Wild Icons Winter Tour",
        fullUrl="/event-calendar/2026/12/28/alaskas-wild-icons-winter-tour")
    lights = zoo_event(
        id="zoo-003", title="Zoo Lights",
        fullUrl="/event-calendar/2026/winter-break/zoo-lights")
    rows = ak2.collect(source(ak2.ZOO), zoo_fetch({
        "november-2026": [story],
        "december-2026": [story, tour, lights],
        "january-2027": [lights]}), now=NOW)
    assert len(rows) == 3  # same publisher identities across months deduplicated
    assert {x["category"] for x in rows} == {"learn", "gardens_nature", "festival"}
    assert all(x["venue_address"] == ak2.ZOO_VENUE[1] for x in rows)
    assert all(x["lat"] == 61.1236344 and x["lng"] == -149.7908746 for x in rows)
    assert all("<" not in x["description"] and x["description"].strip() for x in rows)
    assert all(x.get("image_url", "").endswith(".jpg") for x in rows)


def test_zoo_skips_promo_private_offsite_and_bad_timezone():
    kinds = [
        zoo_event(id="sale", title="CyberMonday Zoo Lights Sale"),
        zoo_event(id="members", title="Members Only ZoosGiving"),
        zoo_event(id="bad", location=dict(zoo_event()["location"], addressLine1="123 Unknown Lane")),
        zoo_event(id="blank", body="<p></p>"),
        zoo_event(id="oversize", body="x" * 12001),
        zoo_event(id="unclassified", title="Something with no event activity"),
        zoo_event(id="broken", fullUrl="https://not-the-zoo.test/event-calendar/2026/foo"),
        zoo_event(id="nyc", location=dict(zoo_event()["location"], mapLat=40.7207559)),
    ]
    assert ak2.collect(source(ak2.ZOO),
                       zoo_fetch({"november-2026": kinds}), now=NOW) == []
    with pytest.raises(ValueError, match="unregistered_anchorage_expansion_source"):
        ak2.collect(dict(source(ak2.ZOO), timezone="America/New_York"),
                    zoo_fetch({"november-2026": kinds}), now=NOW)


def test_history_keeps_long_full_story_and_fixes_verified_publisher_zip():
    rows = ak2.collect(source(ak2.HISTORY), history_fetch(history_event()), now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["venue_address"] == "625 C Street, Anchorage, AK 99501"
    assert row["category"] == "learn"
    assert row["timezone"] == "America/Anchorage"
    assert row["lat"] == 61.215893 and row["lng"] == -149.8846999
    assert len(row["description"]) > 2000
    assert "<p>" not in row["description"] and "&amp;" not in row["description"]
    assert row["image_evidence_url"] == row["event_url"]


def test_history_holds_conflicting_location_and_truncated_details():
    changes = [
        {"body": ""},
        {"body": "x" * 12001},
        {"location": dict(history_event()["location"], addressTitle="Unrelated Venue")},
        {"location": dict(history_event()["location"], mapLat=40.7207559)},
        {"fullUrl": "https://invalid.example.com/event"},
    ]
    for change in changes:
        assert ak2.collect(source(ak2.HISTORY),
                           history_fetch(history_event(**change)), now=NOW) == []


def test_photo_and_event_identity_reject_icons_thumbnails_and_other_domains():
    good = ("https://images.squarespace-cdn.com/content/v1/"
            "5d1d16338ed08b0001ebc5c8/1791242636317-ABCDE/Lecture.jpg")
    assert ak2.photo_url(ak2.HISTORY, good) == good
    for bad in (good + "?format=150w",
                good.replace("Lecture.jpg", "museum-logo.jpg"),
                good.replace("images.squarespace-cdn.com", "example.com"),
                good.replace("https:", "http:")):
        assert ak2.photo_url(ak2.HISTORY, bad) is None
    assert not ak2.event_url(ak2.ZOO, "https://www.alaskazoo.org/other-calendar/x")
    assert ak2.event_url(ak2.HISTORY,
                         "https://www.cookinlethistoricalsociety.org/lecture-series/celebrating-america250-alaskas-year-of-dreams")


def test_shared_preview_enforces_robo_safe_source_host(monkeypatch):
    def fetch(url, accept, **kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"] == ("www.cookinlethistoricalsociety.org",)
        return history_fetch(history_event())(url, accept)
    monkeypatch.setattr(preview_worker, "fetch_publisher", fetch)
    result = preview_worker.preview_source(source(ak2.HISTORY))
    assert result["p_future_count"] == len(result["p_events"]) == 1
    assert "p_parser_capability" not in result  # existing V2 gateway for Squarespace
    assert len(result["p_events"][0]["description"]) > 2000
