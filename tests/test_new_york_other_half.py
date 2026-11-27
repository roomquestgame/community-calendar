from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from roomquest import new_york_other_half as ny


NOW = datetime(2026, 11, 15, 1, 10, tzinfo=timezone.utc)
URL = "https://otherhalfbrewing.com/event/stout-season-2026-2026-12-05/"


def source():
    return dict(source_key=ny.OTHER, feed_url=ny.SOURCES[ny.OTHER][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def record(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def card(url=URL, title="Stout Season 2026", location="Centre Street", day="Dec 5"):
    return (f'<a class="excerpt-box type--post event" href="{url}"><h2 class="excerpt-box-title">{title}</h2>'
            f'<span class="excerpt-box-date">{day} / <span class="excerpt-box-location">{location}</span></span></a>')


def detail(url=URL, title="Stout Season 2026", location="Centre Street", body="Every participating brewery, ticket tier and admission policy.", clock="December 5 2026 12:00 pm - 4:00 pm"):
    return (f'<link rel="canonical" href="{url}"><main><h2 class="fl-heading">{title}</h2>'
            f'<div class="fl-module-icon"><i class="fa-calendar-alt"></i><span class="ui-label" title="{clock}">{clock}</span></div>'
            f'<a class="event-info-location" href="{ny.LOCATION_URLS[location]}">{location}</a>'
            f'<div class="fl-module-cp-content-builder"><div class="module--content-builder"><p>{body}</p></div></div>'
            '<a href="/events/">Back to all events</a></main><footer>Other Half venue hours and beer menu.</footer>')


class NewYorkOtherHalfTests(unittest.TestCase):
    def test_original_facts_ignore_provider_label_and_reviewed_location(self):
        pages = {ny.SOURCES[ny.OTHER][0]: card(), URL: detail()}
        renamed = {**source(), "publisher_name": "Renamed provider label"}
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW)["events"][0]
            again = ny.collect_chunk(renamed, lambda url, accept: pages[url], now=NOW)["events"][0]
        facts = first["collector_event_content_v1"]["facts"]
        self.assertEqual(again["collector_event_content_v1"], first["collector_event_content_v1"])
        self.assertEqual(facts["venue_name"], "Centre Street")
        self.assertNotIn("venue_address", facts)
        self.assertNotIn("source_latitude", facts)
        self.assertEqual((first["lat"], first["lng"]), ny.POINTS["Centre Street"])

    def test_publisher_narrative_change_changes_facts_not_identity(self):
        item = ny._manifest(card(), NOW)[0]
        with patch.object(ny, "record", side_effect=record):
            first = ny._detail(item, detail(body="Original public festival details."), NOW)[0]
            changed = ny._detail(item, detail(body="Changed publisher festival details."), NOW)[0]
        self.assertEqual(changed["id"], first["id"])
        self.assertNotEqual(changed["collector_event_content_v1"], first["collector_event_content_v1"])

    def test_native_full_body_and_reviewed_address_point_survive(self):
        body = "Complete festival schedule and ticket conditions. " * 65 + "Final brewery: Xul Beer Company."
        pages = {ny.SOURCES[ny.OTHER][0]: card(), URL: detail(body=body)}
        with patch.object(ny, "record", side_effect=record):
            result = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW)
        self.assertTrue(result["complete"])
        row = result["events"][0]
        self.assertEqual(row["description"], body)
        self.assertGreater(len(body), 2000)
        self.assertEqual(row["starts_at"], "2026-12-05T12:00:00-05:00")
        self.assertEqual(row["ends_at"], "2026-12-05T16:00:00-05:00")
        self.assertEqual((row["lat"], row["lng"]), ny.POINTS["Centre Street"])
        self.assertNotIn("venue hours", row["description"])

    def test_national_multisite_and_sales_windows_are_excluded(self):
        national = card(url=URL.replace("stout-season", "dc-concert"), location="Washington D.C.")
        multisite = card(url=URL.replace("stout-season", "beer-release"), location="Centre Street</span><span class='excerpt-box-location'>Domino Park", day="Dec 5 - Dec 10")
        ranged = card(url=URL.replace("stout-season", "beer-sale"), day="Dec 5 - Dec 10")
        queue = ny._manifest(card() + national + multisite + ranged, NOW)
        self.assertEqual([item["url"] for item in queue], [URL])

    def test_blank_trivia_is_held_and_fetch_budget_includes_held_details(self):
        one = "https://otherhalfbrewing.com/event/domino-trivia-2026-12-05/"
        page = card(one, "Domino Trivia", "Domino Park") + card()
        pages = {ny.SOURCES[ny.OTHER][0]: page, one: detail(one, "Domino Trivia", "Domino Park", body=""), URL: detail()}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(), fetch, now=NOW, max_details=1)
            self.assertFalse(first["complete"])
            self.assertEqual(first["events"], [])
            self.assertEqual(first["checkpoint"]["cursor"], 1)
            self.assertEqual(len(fetch.call_args_list), 2)
            result = ny.collect_chunk(source(), fetch, now=NOW, checkpoint=first["checkpoint"])
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["checkpoint"]["diagnostics"][0]["reason"], "new_york_other_half_description_missing")
        ny._validate_checkpoint(result["checkpoint"], NOW)

    def test_unverified_domino_point_is_not_replaced_with_nearby_address(self):
        item = ny._manifest(card(location="Domino Park"), NOW)[0]
        with self.assertRaisesRegex(ValueError, "venue_unresolved"):
            ny._detail(item, detail(location="Domino Park"), NOW)
        self.assertIsNone(ny.reviewed_venue_location(ny.OTHER, *ny.VENUES["Domino Park"][:2]))

    def test_mismatched_date_and_location_fail_closed(self):
        item = ny._manifest(card(), NOW)[0]
        with self.assertRaisesRegex(ValueError, "schedule_conflict"):
            ny._detail(item, detail(clock="December 6 2026 12:00 pm - 4:00 pm"), NOW)
        with self.assertRaisesRegex(ValueError, "venue_unresolved"):
            ny._detail(item, detail(location="Domino Park"), NOW)
        with self.assertRaisesRegex(ValueError, "detail_changed"):
            ny._detail(item, detail(title="Different event"), NOW)

    def test_injected_checkpoint_location_clock_and_url_rejected(self):
        pages = {ny.SOURCES[ny.OTHER][0]: card(), URL: detail()}
        with patch.object(ny, "record", side_effect=record):
            state = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW)["checkpoint"]
        for field, value in (("lat", 0), ("starts_at", "2026-12-05T13:00:00-05:00"), ("event_url", "https://evil.invalid/event"), ("description", "")):
            altered = deepcopy(state)
            altered["events"][0][field] = value
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny._validate_checkpoint(altered, NOW)

    def test_checkpoint_rejects_tampered_facts_and_replays_legacy_prefix(self):
        second = URL.replace("stout-season-2026", "lager-festival-2026")
        page = card() + card(second, "Lager Festival")
        pages = {ny.SOURCES[ny.OTHER][0]: page, URL: detail(),
                 second: detail(second, "Lager Festival")}
        with patch.object(ny, "record", side_effect=record):
            first = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW, max_details=1)
            tampered = deepcopy(first["checkpoint"])
            tampered["events"][0]["collector_event_content_v1"]["facts"]["description"] = "Tampered facts."
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny._validate_checkpoint(tampered, NOW)
            legacy = deepcopy(first["checkpoint"])
            legacy["events"][0].pop("collector_event_content_v1")
            complete = ny.collect_chunk(source(), lambda url, accept: pages[url], now=NOW,
                                        max_details=1, checkpoint=legacy)
        self.assertTrue(complete["complete"])
        self.assertTrue(all("collector_event_content_v1" not in row for row in complete["events"]))

    def test_new_pagination_and_unregistered_source_do_not_produce_partial_publication(self):
        with self.assertRaisesRegex(ValueError, "calendar_changed"):
            ny._manifest(card() + '<a rel="next" href="/events/page/2/">More</a>', NOW)
        invalid = source()
        invalid["feed_url"] = "https://otherhalfbrewing.com/events/?format=json"
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ny.collect_chunk(invalid, fetch, now=NOW)
        fetch.assert_not_called()
        self.assertFalse(ny.event_url(ny.OTHER, URL + "?admin=1"))
        self.assertIsNone(ny.photo_url(ny.OTHER, "https://cooler-images.arryved.com/another-brewery/flyer.png"))


if __name__ == "__main__":
    unittest.main()
