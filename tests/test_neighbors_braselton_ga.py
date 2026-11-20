"""Neighbors Bar: first-party detail schema.org, not a made-up recurrence."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from roomquest.neighbors_braselton_ga import (
    KEY, URL, ZONE, parse, collect, event_url
)

NOW = datetime(2026, 11, 19, 21, tzinfo=timezone.utc)
DETAIL = "https://neighborsbraselton.com/events/matt-roper-2026-11-20"
SCHEMA = {
    "@context": "https://schema.org",
    "@graph": [{
        "@type": "MusicEvent",
        "name": "Matt Roper at Neighbors Bar",
        "startDate": "2026-11-20T20:00:00-05:00",
        "endDate": "2026-11-20T23:00:00-05:00",
        "url": DETAIL,
        "description": "Live on the Neighbors stage. Bring your people and make a night of it.",
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "organizer": {"@type": "Organization", "name": "Neighbors Bar", "url": "https://neighborsbraselton.com"},
        "location": {"@type": "BarOrPub", "name": "Neighbors Bar", "address": {
            "@type": "PostalAddress", "streetAddress": "6323 Grand Hickory Dr, Suite 200D",
            "addressLocality": "Braselton", "addressRegion": "GA",
            "postalCode": "30517", "addressCountry": "US"
        }}
    }]
}
INDEX = '<a href="/events/matt-roper-2026-11-20">Matt Roper</a>'
def detail(item=None):
    item = SCHEMA if item is None else item
    return '<script type="application/ld+json">' + json.dumps(item) + '</script>'
SOURCE = {"source_key": KEY, "feed_url": URL, "kind": "html", "platform_adapter": "html", "timezone": ZONE}


class NeighborsTests(unittest.TestCase):
    def test_real_upcoming_show(self):
        result = parse(INDEX, lambda u,a:detail(), now=NOW)
        self.assertEqual(len(result), 1)
        event = result[0]
        self.assertEqual(event["event_url"], DETAIL)
        self.assertEqual(event["timezone"], ZONE)
        self.assertIn("6323 Grand Hickory", event["venue_address"])
        self.assertIn("Live on the Neighbors stage", event["description"])
        self.assertEqual(event["category"], "Music")
        self.assertIsNone(event.get("lat"))
        self.assertIsNone(event.get("lng"))

    def test_other_city_and_template_geo_rejected(self):
        j = json.loads(json.dumps(SCHEMA))
        j["@graph"][0]["location"]["address"]["addressLocality"] = "New York"
        self.assertEqual(parse(INDEX, lambda u,a:detail(j), now=NOW), [])
        j["@graph"][0]["location"]["address"]["addressLocality"] = "Braselton"
        j["@graph"][0]["location"]["address"]["streetAddress"] = ""
        self.assertEqual(parse(INDEX, lambda u,a:detail(j), now=NOW), [])

    def test_missing_clock_and_cancelled_or_virtual_are_held(self):
        for key,value in [("startDate","2026-11-20"),("eventStatus","https://schema.org/EventCancelled"),
                          ("eventAttendanceMode","https://schema.org/OnlineEventAttendanceMode")]:
            j = json.loads(json.dumps(SCHEMA))
            j["@graph"][0][key] = value
            self.assertEqual(parse(INDEX, lambda u,a:detail(j), now=NOW), [])

    def test_link_mismatch_and_host_change(self):
        j = json.loads(json.dumps(SCHEMA))
        j["@graph"][0]["url"] = "https://otherhost.example/events/matt-roper-2026-11-20"
        self.assertEqual(parse(INDEX, lambda u,a:detail(j), now=NOW), [])
        self.assertFalse(event_url("https://neighborsbraselton.com/api/events"))
        self.assertFalse(event_url("https://anotherbraselton.com/events/matt-roper-2026-11-20"))

    def test_duplicate_index_link_is_not_double_fetched(self):
        urls = []
        self.assertEqual(len(parse(INDEX+INDEX,lambda u,a:(urls.append(u),detail())[1],now=NOW)),1)
        self.assertEqual(urls,[DETAIL])

    def test_wrong_source_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"unregistered_neighbors_source"):
            collect({**SOURCE,"timezone":"UTC"},lambda u,a:detail(),now=NOW)

    def test_registered_html_dispatch_robots_and_events(self):
        from roomquest.preview_worker import preview_source
        calls = []
        def publisher(url, accept, **kwargs):
            calls.append((url, kwargs))
            return INDEX if url == URL else detail()
        with patch("roomquest.preview_worker.fetch_publisher", side_effect=publisher):
            got = preview_source(SOURCE)
        self.assertGreaterEqual(got["p_future_count"],1)
        self.assertTrue(all(k.get("respect_robots") is True for u,k in calls))
        self.assertTrue(all(k.get("allowed_hosts") == ("neighborsbraselton.com",) for u,k in calls))


if __name__ == "__main__":
    unittest.main()
