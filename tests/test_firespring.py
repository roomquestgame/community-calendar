import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from roomquest import firespring


class FirespringTest(unittest.TestCase):
    def setUp(self):
        self.base, self.root = firespring.SOURCES["plantnebraska_events_ne"]
        self.detail = "https://plantnebraska.org" + self.root + "/event/2026/11/13/plant-talk/123"
        self.export = self.detail.replace("/event/", "/ical/", 1)
        self.source = {
            "source_key": "plantnebraska_events_ne", "feed_url": self.base,
            "timezone": "America/Chicago", "kind": "html", "platform_adapter": "html",
        }
        self.now = datetime(2026, 11, 12, 18, tzinfo=timezone.utc)

    def test_only_exact_publisher_links_in_window(self):
        page = (f'<a href="{self.detail}">Event</a>'
                f'<a href="{self.detail.replace("plantnebraska.org", "other.example")}">Other</a>'
                f'<a href="{self.detail.replace("/13/", "/10/")}">Past</a>'
                '<a href="#">Go to Next</a>')
        self.assertEqual(firespring.listing_events(
            page, self.base, self.root, date(2026, 11, 12), date(2027, 1, 11)), {self.detail})

    def test_unrecognized_calendar_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid_firespring_calendar"):
            firespring.listing_events("<title>Unavailable</title>", self.base, self.root,
                                      date(2026, 11, 12), date(2027, 1, 11))

    def test_publisher_export_is_required(self):
        def fetch(url, _):
            if "/calendar/" in url:
                return f'<a href="{self.detail}">Event</a><a href="#">Go to Next</a>'
            return '<a href="https://other.example/export.ics">Calendar</a>'
        with self.assertRaisesRegex(ValueError, "missing_firespring_icalendar_link"):
            firespring.collect(self.source, fetch, now=self.now)

    def test_export_uses_canonical_detail_for_attribution(self):
        alternate_export = self.export.replace("/13/", "/12/") + "/"
        missing = self.detail.replace("/123", "/124")

        def fetch(url, _):
            if "/calendar/" in url:
                return f'<a href="{self.detail}">Event</a><a href="{missing}">Other</a><a href="#">Go to Next</a>'
            if url == self.detail:
                return f'<a href="{alternate_export}">Add To My Calendar</a>'
            if url == missing:
                return '<p>No publisher export</p>'
            self.assertEqual(url, alternate_export)
            return "publisher export"
        with patch.object(firespring, "event_record", return_value={
            "starts_at": "2026-11-13T18:00:00+00:00", "id": "123",
        }) as parser:
            self.assertEqual(len(firespring.collect(self.source, fetch, now=self.now)), 1)
        parser.assert_called_once_with("publisher export", self.detail, "123")

    def test_venue_address_extraction(self):
        self.assertEqual(firespring.venue_fields("Nature Center\n3201 S Coddington Ave\nLincoln, NE 68522"),
                         ("Nature Center", "3201 S Coddington Ave, Lincoln, NE 68522", "Lincoln"))
        self.assertEqual(firespring.venue_fields("A Venue"), ("A Venue", "", ""))
