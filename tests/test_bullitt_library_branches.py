"""Focused no-network Louisville / Bullitt publisher contract checks."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from roomquest import bullitt_library_branches as b


class BullittLibraryTests(unittest.TestCase):
    def test_exact_four_branch_source_profiles_and_rolling_window(self):
        self.assertEqual(len(b.SOURCES), 4)
        for key in b.SOURCES:
            source = {"source_key": key, "feed_url": b.feed_url(key),
                      "kind": "ical", "platform_adapter": "ical",
                      "timezone": "America/New_York"}
            self.assertTrue(b.source_valid(source))
            self.assertFalse(b.source_valid({**source, "feed_url": b.BASE}))
            url = b.collection_url(key, datetime(2026, 11, 19, tzinfo=timezone.utc))
            self.assertTrue(url.startswith(b.feed_url(key) + "&start=2026-11-19"))
            self.assertIn("&end=2027-01-18", url)

    def test_only_publisher_event_links_and_original_images(self):
        key = "bullitt_library_shepherdsville_ky"
        self.assertTrue(b.event_url(key, "https://bullittcounty.librarycalendar.com/event/toddler-storytime-51362"))
        for value in ("https://thirdparty.test/event/toddler-storytime-51362",
                      "https://bullittcounty.librarycalendar.com/events/feed/ical",
                      "https://bullittcounty.librarycalendar.com/event/toddler-storytime-51362?track=1"):
            self.assertFalse(b.event_url(key, value))
        self.assertIsNone(b.event_image(key, "https://bullittcounty.librarycalendar.com/sites/default/files/logo.png"))
        self.assertIsNone(b.event_image(key, "https://images.example.com/event.jpg"))

    def test_category_is_event_specific_not_library_default(self):
        self.assertEqual(b.category_for(["Early Childhood", "Games & Play"], "Toddler Storytime"), "learn")
        self.assertEqual(b.category_for(["Fandom Fun"], "Anime Club"), "hang_out")
        self.assertEqual(b.category_for(["Arts & Crafts"], "Craft Session"), "create")
        self.assertIsNone(b.category_for([], "A generic title"))
        self.assertIsNone(b.category_for(["Arts & Crafts"], "Library Closed for Renovation"))
        self.assertIsNone(b.category_for(["Music & Dance"], "Staff-only planning"))

    def test_exact_location_street_and_metadata_are_required(self):
        key = "bullitt_library_shepherdsville_ky"
        source = {"source_key": key, "feed_url": b.feed_url(key),
                  "kind": "ical", "platform_adapter": "ical",
                  "timezone": "America/New_York"}
        ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:51362\r\n"
               "DTSTART:20261119T150000Z\r\nDTEND:20261119T153000Z\r\n"
               "SUMMARY:Toddler Storytime\r\nDESCRIPTION:Explore stories and play.\r\n"
               "LOCATION:740 Conestoga Parkway\\, Shepherdsville\\, KY\\, 40165\\, US\r\n"
               "URL:https://bullittcounty.librarycalendar.com/event/toddler-storytime-51362\r\n"
               "CATEGORIES:Early Childhood,Games & Play\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        location = b.SOURCES[key][-1]
        event = {"id": "51362", "title": "Toddler Storytime",
                 "event_url": "https://bullittcounty.librarycalendar.com/event/toddler-storytime-51362",
                 "starts_at": "2026-11-19T15:00:00+00:00",
                 "venue_address": location, "venue_name": location,
                 "lat": b.SOURCES[key][5], "lng": b.SOURCES[key][6],
                 "publisher_categories": ["Early Childhood", "Games & Play"]}
        def fake_fetch(url, accept):
            self.assertIn("start=", url)
            self.assertEqual(accept, "text/calendar")
            return ics
        with patch("roomquest.ics_adapter.parse", return_value=[event.copy()]), \
             patch("roomquest.publisher_evidence.attach", side_effect=lambda row, key, candidate=None: row):
            rows = b.collect(source, fake_fetch)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["venue_address"], "740 Conestoga Parkway, Shepherdsville, KY 40165")
        self.assertEqual(rows[0]["category"], "learn")
        self.assertIn("Explore stories", rows[0]["description"])

        with patch("roomquest.ics_adapter.parse", return_value=[{**event, "venue_address": "Unknown"}]), \
             patch("roomquest.publisher_evidence.attach", side_effect=lambda row, key, candidate=None: row):
            self.assertEqual(b.collect(source, fake_fetch), [])


if __name__ == "__main__":
    unittest.main()
