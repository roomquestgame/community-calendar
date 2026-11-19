"""Publisher identity, timing, location and description guards for Cork It."""
import json
import unittest
from datetime import datetime, timezone

from roomquest.cork_it_ga import KEY, URL, ZONE, parse, collect

NOW = datetime(2026, 11, 19, 23, tzinfo=timezone.utc)


def event(**changes):
    record = {
        "id": "6ab58a4e6e39c913c21a0adc",
        "title": "Live Music",
        "workflowState": 1,
        "fullUrl": "/eventdates/yn7dd78mn58s7dm6gca8j234prng5c",
        "startDate": 1795219200064,
        "endDate": 1795230000064,
        "categories": [],
        "body": "<p>Live Music Featuring <strong>Andrew Lane</strong> Starting at 7:00pm.</p>",
        "location": {
            "addressTitle": "Cork It Gainesville",
            "addressLine1": "118 Main Street Southwest",
            "addressLine2": "Gainesville, GA, 30501",
            "addressCountry": "United States",
            "mapLat": 34.2988671,
            "mapLng": -83.8273478,
            "markerLat": 34.2988671,
            "markerLng": -83.8273478,
        },
    }
    record.update(changes)
    return record


def payload(items):
    return json.dumps({
        "website": {"timeZone": ZONE},
        "upcoming": items,
        "past": [{"publishOn": 1000, "endDate": 2000}],
        "pagination": {"nextPage": True, "nextPageOffset": 1000},
    })


class CorkItTests(unittest.TestCase):
    def test_verified_publisher_event_retains_complete_description_and_place(self):
        [row] = parse(payload([event()]), now=NOW)
        self.assertEqual(row["venue_address"], "118 Main Street Southwest, Gainesville, GA, 30501")
        self.assertEqual(row["lat"], 34.2988671)
        self.assertIn("Andrew Lane", row["description"])
        self.assertEqual(row["event_url"], "https://www.corkitgainesville.com/eventdates/yn7dd78mn58s7dm6gca8j234prng5c")
        self.assertIn("publisher_event_venue", row["location_provenance"])
        self.assertNotIn("image_url", row)

    def test_false_new_york_map_and_blank_event_venue_held(self):
        bad = dict(event()["location"], markerLat=40.7207559, markerLng=-74.0007613)
        self.assertEqual(parse(payload([event(location=bad)]), now=NOW), [])
        self.assertEqual(parse(payload([event(location={})]), now=NOW), [])

    def test_off_area_or_unverified_street_held(self):
        base = event()["location"]
        self.assertEqual(parse(payload([event(location={**base,"addressLine2":"Buford, GA, 30518"})]), now=NOW), [])
        self.assertEqual(parse(payload([event(location={**base,"addressLine1":"Main St"})]), now=NOW), [])

    def test_timezones_and_pagination_fail_closed(self):
        blob = json.loads(payload([event()]))
        blob["website"]["timeZone"] = "America/Los_Angeles"
        with self.assertRaisesRegex(ValueError, "publisher_timezone_changed"):
            parse(json.dumps(blob), now=NOW)
        blob["website"]["timeZone"] = ZONE
        blob["pagination"]["nextPageOffset"] = 80000
        with self.assertRaisesRegex(ValueError, "pagination_requires_review"):
            parse(json.dumps(blob), now=NOW)

    def test_identity_and_bad_clocks_held(self):
        self.assertEqual(parse(payload([event(fullUrl="https://evil.example/events/live")]), now=NOW), [])
        self.assertEqual(parse(payload([event(startDate=None)]), now=NOW), [])
        self.assertEqual(parse(payload([event(allDay=True)]), now=NOW), [])

    def test_dedup_and_profile_identity(self):
        self.assertEqual(len(parse(payload([event(), event()]), now=NOW)), 1)
        good = {"source_key": KEY, "feed_url": URL, "kind": "json",
                "platform_adapter": "squarespace", "timezone": ZONE}
        self.assertEqual(len(collect(good, lambda url, accept: payload([event()]))), 1)
        with self.assertRaisesRegex(ValueError, "unregistered_cork_it_source"):
            collect({**good, "timezone": "UTC"}, lambda url, accept: payload([event()]))


if __name__ == "__main__":
    unittest.main()
