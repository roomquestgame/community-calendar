"""Verify an OC Parks partial source never bypasses the shared safe collector."""
import unittest
from datetime import datetime
from time import monotonic
from unittest.mock import patch

from roomquest import oc_parks_partial, preview_worker

SOURCE = {
    "source_key": oc_parks_partial.SOURCE_KEY,
    "feed_url": oc_parks_partial.CALENDAR,
    "kind": "html", "platform_adapter": "html",
    "timezone": oc_parks_partial.ZONE,
}
PATH = "/events/oc-parks-protected-source"


class OCPartialIntegration(unittest.TestCase):
    def test_existing_safe_transport_limits_origin_and_source(self):
        calls = []
        row = {
            "title": "Actual OC Parks Event", "id": "123456",
            "starts_at": "2026-11-20T16:30:00+00:00", "ends_at": "2026-11-20T17:30:00+00:00",
            "venue_name": "OC Parks", "venue_address": "1 Irvine Park Rd., Orange, CA 92869",
            "event_url": "https://parks.oc.gov" + PATH,
            "description": "Exact actual publisher narrative.", "lat": 33.796935, "lng": -117.753463,
        }
        entry = {
            "eid": "123456", "title": "Actual OC Parks Event",
            "url": PATH, "starts_at": datetime.fromisoformat("2026-11-20T08:30:00-08:00"),
            "ends_at": datetime.fromisoformat("2026-11-20T09:30:00-08:00"),
        }
        def fetched(url, accept, **kwargs):
            calls.append((url, accept, kwargs))
            return "<html>publisher source</html>"
        with patch.object(preview_worker, "fetch_publisher", side_effect=fetched):
            with patch.object(oc_parks_partial, "parse_calendar", return_value=[entry]):
                with patch.object(oc_parks_partial, "cancellation_records", return_value=[]):
                    with patch.object(oc_parks_partial, "parse_detail", return_value=(row, row["description"])):
                        output = preview_worker.preview_source(SOURCE, deadline_at=monotonic()+40)
        self.assertEqual(output["p_future_count"], 1)
        self.assertEqual(output["p_venue_count"], 1)
        self.assertEqual(output["p_parser_capability"], "publisher_event_candidates_v1")
        self.assertEqual(output["p_events"], [row])
        self.assertEqual(len(calls), 2)
        self.assertEqual([v[0] for v in calls], [oc_parks_partial.CALENDAR, "https://parks.oc.gov" + PATH])
        self.assertTrue(all(v[2]["respect_robots"] is True for v in calls))
        self.assertTrue(all(v[2]["allowed_hosts"] == ("parks.oc.gov",) for v in calls))
        self.assertNotIn("p_publish", output)

    def test_unregistered_source_cannot_fetch_data(self):
        with patch.object(preview_worker, "fetch_publisher", side_effect=AssertionError("no requests")):
            with self.assertRaisesRegex(preview_worker.PreviewError, "unregistered_oc_parks_source"):
                preview_worker.preview_source({**SOURCE, "feed_url": "https://example.com/"},
                                              deadline_at=monotonic()+40)

if __name__ == "__main__":
    unittest.main()
