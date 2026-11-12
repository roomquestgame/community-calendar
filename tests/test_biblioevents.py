import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from roomquest import biblioevents

SOURCE = {
    "source_key": "omaha_public_library_biblioevents_ne",
    "feed_url": "https://omaha.bibliocommons.com/v2/events",
    "timezone": "America/Chicago",
    "kind": "html",
    "platform_adapter": "html",
}


class BiblioEventsTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 12, 18, tzinfo=timezone.utc)
        self.start = (self.now + timedelta(days=1)).isoformat()

    def page(self, definition, locations):
        return json.dumps({
            "events": {"items": ["abc123"]},
            "entities": {
                "events": {"abc123": {
                    "indexStart": self.start,
                    "definition": {"title": "Family Storytime", **definition},
                }},
                "locations": locations,
            },
        })

    def collect(self, payload):
        calls = []
        def fetch(url, accept):
            calls.append((url, accept))
            if len(calls) == 1:
                return payload
            return '{"events":{"items":[]}}'
        with patch.object(biblioevents, "record", side_effect=lambda *a, **k: {
            "starts_at": a[1], "venue": a[3], "address": a[4], "url": a[6], "id": a[7],
        }):
            result = biblioevents.collect(SOURCE, fetch, now=self.now)
        self.assertEqual(len(calls), 2)
        self.assertIn("/v2/libraries/omaha/events?limit=100&page=1", calls[0][0])
        return result

    def test_branch_address_and_link(self):
        row, = self.collect(self.page(
            {"branchLocationId": "branch"}, {"branch": {"name": "Benson Branch"}},
        ))
        self.assertEqual(row["address"], "6015 Binney St, Omaha, NE 68104")
        self.assertEqual(row["url"], SOURCE["feed_url"] + "/abc123")

    def test_offsite_address_is_not_replaced_by_branch(self):
        row, = self.collect(self.page(
            {"branchLocationId": "branch", "nonBranchLocationId": "off"},
            {"branch": {"name": "Benson Branch"}, "off": {"name": "Partner Venue"}},
        ))
        self.assertEqual(row["venue"], "Partner Venue")
        self.assertEqual(row["address"], "")

    def test_offsite_structured_address(self):
        row, = self.collect(self.page(
            {"branchLocationId": "branch", "nonBranchLocationId": "off"},
            {"branch": {"name": "Benson Branch"}, "off": {
                "name": "Partner Venue", "address": {
                    "streetAddress": "101 Test St", "addressLocality": "Omaha",
                    "addressRegion": "NE", "postalCode": "68104",
                },
            }},
        ))
        self.assertEqual(row["address"], "101 Test St, Omaha, NE 68104")

    def test_cancelled_event_is_skipped(self):
        self.assertEqual(self.collect(self.page(
            {"branchLocationId": "branch", "isCancelled": True},
            {"branch": {"name": "Benson Branch"}},
        )), [])

    def test_repeated_page_fails_closed(self):
        payload = self.page({"branchLocationId": "branch"}, {"branch": {"name": "Benson Branch"}})
        with patch.object(biblioevents, "record", return_value=None):
            with self.assertRaisesRegex(ValueError, "invalid_biblioevents_pagination"):
                biblioevents.collect(SOURCE, lambda *_: payload, now=self.now)

    def test_mismatched_source_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unregistered_biblioevents_source"):
            biblioevents.collect({**SOURCE, "feed_url": "https://another.example/v2/events"},
                                lambda *_: self.fail("unexpected fetch"))
