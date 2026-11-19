"""Fail-closed publisher identity, clocks, addresses and asset candidates."""
import json
import unittest
from datetime import datetime, timezone

from roomquest.hall_arts_council_ga import KEY, URL, ZONE, parse, collect, photo_url

NOW = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)


def event(**changes):
    row = dict(id="6ac79b1156b6535ca37dae3a",
               title="Jazz Goes to the Movies",
               fullUrl="/events/jazz-goes-to-the-movies-kgnc5-lc5mg",
               workflowState=1,
               startDate=1800061200227,
               endDate=1800064800227,
               categories=["Performances"],
               body="<p>A publisher-owned <strong>concert</strong> with details.</p>",
               location=dict(addressTitle="Smithgall Arts Center",
                             addressLine1="331 Spring Street Southwest",
                             addressLine2="Gainesville, Georgia, 30501",
                             addressCountry="United States",
                             markerLat=34.2975762, markerLng=-83.8282947),
               assetUrl="https://images.squarespace-cdn.com/content/v1/68653a54760bb4069e9577b0/asset/Front.png")
    row.update(changes)
    return row


def payload(events, *, zone=ZONE):
    return json.dumps({"website": {"timeZone": zone},
                       "upcoming": events, "pagination": {"nextPage": False}})


class ArtsCouncilTests(unittest.TestCase):
    def test_current_first_party_concert_retains_details_and_image_candidate(self):
        rows = parse(payload([event()]), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("publisher-owned", rows[0]["description"])
        self.assertIn("concert", rows[0]["description"])
        self.assertIn("publisher_event", rows[0]["location_provenance"])
        self.assertEqual(rows[0]["event_url"], "https://www.theartscouncil.net/events/jazz-goes-to-the-movies-kgnc5-lc5mg")
        self.assertIn("squarespace-cdn.com", rows[0].get("image_url", ""))

    def test_blank_venue_and_false_default_new_york_pin_are_held(self):
        missing = event(location=dict(markerLat=40.7207559, markerLng=-74.0007613,
                                      addressTitle="", addressLine1="", addressLine2=""))
        self.assertEqual(parse(payload([missing]), now=NOW), [])

    def test_off_area_or_incomplete_publisher_address_is_held(self):
        wrong_city = event(location=dict(event()["location"], addressLine2="Dahlonega, Georgia, 30533"))
        self.assertEqual(parse(payload([wrong_city]), now=NOW), [])
        incomplete = event(location=dict(event()["location"], addressLine2="Gainesville"))
        self.assertEqual(parse(payload([incomplete]), now=NOW), [])

    def test_changed_timezone_and_source_profile_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "publisher_timezone_changed"):
            parse(payload([event()], zone="America/Chicago"), now=NOW)
        with self.assertRaisesRegex(ValueError, "unregistered_hall_arts_source"):
            collect({"source_key": KEY, "feed_url": URL, "kind": "json",
                     "platform_adapter": "squarespace", "timezone": "UTC"},
                    lambda u, a: payload([event()]))

    def test_malformed_url_and_image_are_excluded(self):
        self.assertEqual(parse(payload([event(fullUrl="https://bad.example/events/abc")]), now=NOW), [])
        self.assertIsNone(photo_url("https://bad.example/photo.jpg"))
        self.assertIsNone(photo_url("https://images.squarespace-cdn.com/content/v1/other/photo.png"))

    def test_duplicate_occurrence_id_is_not_counted_twice(self):
        self.assertEqual(len(parse(payload([event(), event()]), now=NOW)), 1)


if __name__ == "__main__":
    unittest.main()
