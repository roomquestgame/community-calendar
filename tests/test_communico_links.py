"""Communico download regressions using observed publisher IDs and synthetic facts."""
from base64 import b64encode
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from roomquest.communico_links import detail_url
from roomquest.ics_adapter import parse
from roomquest.preview_worker import parse_ics_preview, preview_source


FEED = ("https://events.thelibrarydistrict.org/feeds?data="
        "eyJmZWVkVHlwZSI6ImljYWwiLCJmaWx0ZXJzIjp7ImxvY2F0aW9uIjpbIjE2NSIsIjE2NiIsIjM1MzEiXSwi"
        "YWdlcyI6WyJhbGwiXSwidHlwZXMiOlsiYWxsIl0sInRhZ3MiOltdLCJ0ZXJtIjoiIiwiZGF5cyI6OTB9fQ==")
KEY = "municipal_mapsee_31a9e5bbfb8129a494d7b883"
UIDS = ["17130479", "17083237", "17001105", "17153378", "16551743", "17039812", "17161960"]
PAGE = "https://events.thelibrarydistrict.org/event/17130479"


def fixture_feed(*, current_url=None, uids=("17130479",), recurring=False):
    """Future synthetic VEVENT facts; live IDs/shape do not imply a live refetch."""
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    rows = []
    for index, uid in enumerate(uids):
        when = start + timedelta(hours=index)
        url = "" if current_url is None else "URL:" + current_url + "\r\n"
        recurrence = "RRULE:FREQ=DAILY;COUNT=2\r\n" if recurring else ""
        rows.append(
            "BEGIN:VEVENT\r\nUID:" + uid + "\r\n"
            "SUMMARY:Kid's Cafe\r\n"
            "DTSTART:" + when.strftime("%Y%m%dT%H%M%SZ") + "\r\n"
            "DTEND:" + (when + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ") + "\r\n"
            "LOCATION:Whitney Library -\r\nGEO:36.1005;-115.0591\r\n"
            "DESCRIPTION:Join the library for free meals for children ages 3-18.\r\n"
            "CATEGORIES:Community Events\r\n" + url + recurrence + "END:VEVENT\r\n"
        )
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(rows) + "END:VCALENDAR\r\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Communico link normalization must not make a request")
    monkeypatch.setattr("socket.getaddrinfo", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("current_url", [None, "", FEED, FEED.replace("==", "%3D%3D")])
def test_all_occurrences_get_native_event_pages_and_keep_facts(legacy, current_url):
    payload = fixture_feed(current_url=current_url, uids=UIDS)
    before = parse_ics_preview(payload, allow_ongoing=True, include_images=legacy,
                               include_description=True)
    after = parse(payload, {"url": FEED}, legacy=legacy, include_description=True)
    assert len(after) == len(UIDS)
    for old, new, uid in zip(before, after, UIDS):
        assert new["event_url"] == "https://events.thelibrarydistrict.org/event/" + uid
        for field in ("id", "title", "starts_at", "ends_at", "venue_name", "lat", "lng", "description"):
            assert new[field] == old[field]
        assert new["publisher_categories"] == ["Community Events"]


@pytest.mark.parametrize("page", [PAGE, "https://tickets.example.org/meal-program"])
def test_real_explicit_urls_keep_precedence(page):
    assert detail_url(FEED, UIDS[0], page) is None
    assert parse(fixture_feed(current_url=page), {"url": FEED})[0]["event_url"] == page


def test_exact_mapsee_dispatch_stages_page_without_a_detail_fetch():
    source = {"source_key": KEY, "feed_url": FEED, "kind": "ical", "platform_adapter": "ical"}
    with patch("roomquest.preview_worker.fetch_publisher", return_value=fixture_feed()) as fetch:
        result = preview_source(source)
    assert result["p_error"] is None and result["p_future_count"] == 1
    assert result["p_events"][0]["event_url"] == PAGE
    assert result["p_events"][0]["id"] == UIDS[0]
    fetch.assert_called_once()
    assert fetch.call_args.args == (FEED, "text/calendar")
    assert fetch.call_args.kwargs["respect_robots"] is True
    assert fetch.call_args.kwargs["deadline_at"] is not None


def test_all_eleven_registered_library_feed_groups_use_same_contract():
    document = json.loads((Path(__file__).parents[1] / "roomquest/mapsee_sources.json").read_text())
    sources = document["sources"] if isinstance(document, dict) else document
    district = [s for s in sources if s.get("url", "").startswith("https://events.thelibrarydistrict.org/feeds?")]
    assert len(district) == 11
    for source in district:
        assert detail_url(source["url"], UIDS[0]) == PAGE
        assert detail_url(source["canonical_url"], UIDS[0]) == PAGE


def test_hosted_communico_tenant_has_same_native_identity_contract():
    feed = FEED.replace("events.thelibrarydistrict.org", "santacruzpl.libnet.info")
    assert detail_url(feed, "17823456") == "https://santacruzpl.libnet.info/event/17823456"


@pytest.mark.parametrize("uid", [None, 17130479, "", "017130479", "17130479__20261123", "17130479@library", "../17130479", "1234", "1" * 11])
def test_non_native_identifiers_are_never_guessed(uid):
    assert detail_url(FEED, uid) is None


@pytest.mark.parametrize("feed", [
    FEED.replace("https:", "http:"),
    FEED.replace("events.thelibrarydistrict.org", "library.example.org"),
    FEED.replace("events.thelibrarydistrict.org", "evil.libnet.info.attacker.org"),
    FEED.replace("events.thelibrarydistrict.org", "libnet.info"),
    FEED.replace("events.thelibrarydistrict.org", "user@events.thelibrarydistrict.org"),
    FEED.replace("events.thelibrarydistrict.org", "events.thelibrarydistrict.org:8443"),
    FEED.replace("/feeds?", "/feed?"),
    FEED + "#untrusted", FEED + "&data=second", FEED + "&redirect=elsewhere",
    FEED.split("?")[0] + "?data=not-base64",
    FEED.split("?")[0] + "?data=" + b64encode(b'{"feedType":"rss","filters":{}}').decode(),
    FEED.split("?")[0] + "?data=" + b64encode(b'{"feedType":"ical","filters":[]}').decode(),
    FEED.split("?")[0] + "?data=" + b64encode(b'[]').decode(),
])
def test_unproven_feed_shapes_never_synthesize_a_detail_link(feed):
    assert detail_url(feed, UIDS[0]) is None


def test_other_ics_sources_keep_existing_fallback():
    other = "https://calendar.duke.edu/events/index.ics?future_days=90"
    assert parse(fixture_feed(), {"url": other})[0]["event_url"] == other


def test_recurrence_expansion_preserves_occurrence_ids():
    payload = fixture_feed(recurring=True)
    before = parse_ics_preview(payload, allow_ongoing=True)
    after = parse(payload, {"url": FEED})
    assert len(after) == 2
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert {row["event_url"] for row in after} == {PAGE}
