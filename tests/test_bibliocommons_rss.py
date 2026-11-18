"""Offline contract tests for three explicitly reviewed Biblio RSS publisher feeds."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from xml.etree import ElementTree as ET

from roomquest import bibliocommons_rss as rss

NOW = datetime(2026, 11, 18, 19, tzinfo=timezone.utc)
KEY = "central_rappahannock_library_rss_va"
PROFILE = {
    "source_key": KEY,
    "feed_url": "https://gateway.bibliocommons.com/v2/libraries/librarypoint/rss/events",
    "timezone": "America/New_York", "kind": "rss", "platform_adapter": "library",
}


def make_item(index=1, *, event_local="2026-11-19T11:00",
              begin="2026-11-19T16:00:00Z", end="2026-11-19T16:15:00Z",
              venue=True, coords=True, canceled=False, virtual=False,
              narrative="<p>Publisher's complete event description.</p>",
              url=None, image=True):
    item = ET.Element("item")
    eid = f"{index:024x}"
    link = url or f"https://librarypoint.bibliocommons.com/events/{eid}"
    for k, v in (("title", "Mother Goose Time"), ("description", narrative),
                 ("link", link), ("guid", link)):
        ET.SubElement(item, k).text = v
    ET.SubElement(item, "category").text = "Kids"
    ET.SubElement(item, "category").text = "Family"
    ET.SubElement(item, "category").text = "Kids"
    if image:
        ET.SubElement(item, "enclosure", {
            "url": "http://librarypoint.bibliocommons.com/events/uploads/unlicensed.jpg",
            "type": "image/jpeg", "length": "0",
        })
    ns = rss.EVENT_NS
    for k, v in (("start_date", begin), ("start_date_local", event_local),
                 ("end_date", end), ("is_cancelled", str(canceled).lower()),
                 ("is_virtual", str(virtual).lower())):
        ET.SubElement(item, ns + k).text = v
    if venue:
        loc = ET.SubElement(item, ns + "location")
        for k, v in (("name", "Howell Branch"), ("number", "806"),
                     ("street", "Lyons Boulevard"), ("city", "Fredericksburg"),
                     ("zip", "22406"), ("state", "VA")):
            ET.SubElement(loc, ns + k).text = v
        if coords:
            ET.SubElement(loc, ns + "latitude").text = "38.36284"
            ET.SubElement(loc, ns + "longitude").text = "-77.497613"
    return item


def document(items):
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    for item in items:
        channel.append(item)
    return ET.tostring(root, encoding="utf-8")


def sample_record(*a, **kwargs):
    return {
        "title": a[0], "starts_at": a[1], "ends_at": a[2],
        "venue_name": a[3], "venue_address": a[4],
        "event_url": a[6], "id": a[7], "lat": kwargs.get("lat"),
        "lng": kwargs.get("lng"), "image_url": "publisher-photo-not-reviewed",
        "image_candidate_url": "publisher-photo-not-reviewed",
    }


class BiblioRssCanaryTest(unittest.TestCase):
    def parse(self, payload, *, state="VA"):
        with patch.object(rss, "record", side_effect=sample_record):
            return rss.parse_page(payload, slug="librarypoint", zone="America/New_York",
                                  state=state, now=NOW,
                                  horizon=NOW + rss.timedelta(days=21))

    def test_real_feed_shape_preserves_original_html_narrative_and_publisher_point(self):
        narrative = "<p>" + ("Full publisher program details. " * 85) + "</p>"
        items, rows, beyond = self.parse(document([make_item(narrative=narrative)]))
        self.assertEqual(len(items), 1)
        self.assertFalse(beyond)
        row, = rows
        self.assertIn("Full publisher program details.", row["description"])
        self.assertGreater(len(row["description"]), 2000)
        self.assertEqual(row["venue_name"], "Howell Branch")
        self.assertEqual(row["venue_address"], "806 Lyons Boulevard, Fredericksburg, VA 22406")
        self.assertEqual(row["lat"], 38.36284)
        self.assertEqual(row["lng"], -77.497613)
        self.assertEqual(row["publisher_categories"], ["Kids", "Family"])
        self.assertNotIn("image_url", row)
        self.assertNotIn("image_candidate_url", row)

    def test_missing_geo_never_invents_a_source_center(self):
        _, rows, _ = self.parse(document([make_item(coords=False)]))
        row, = rows
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lng"])

    def test_absent_event_street_is_held_not_inherited(self):
        _, rows, _ = self.parse(document([make_item(venue=False)]))
        self.assertEqual(rows, [])

    def test_date_only_all_day_cannot_be_translated_to_midnight(self):
        _, rows, _ = self.parse(document([make_item(event_local="2026-11-19",
                        begin="2026-11-19T05:00:00Z")]))
        self.assertEqual(rows, [])

    def test_online_is_not_given_a_physical_map_location(self):
        _, rows, _ = self.parse(document([make_item(virtual=True)]))
        self.assertEqual(rows, [])

    def test_cancelled_event_requires_explicit_tombstone_support(self):
        with self.assertRaisesRegex(ValueError, "bibliocommons_rss_cancellation_requires_review"):
            self.parse(document([make_item(canceled=True)]))

    def test_wrong_local_timezone_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "bibliocommons_rss_timezone_mismatch"):
            self.parse(document([make_item(event_local="2026-11-19T13:00")]))

    def test_missing_end_is_preserved_unknown_not_invented(self):
        _, rows, _ = self.parse(document([make_item(end="")]))
        self.assertIsNone(rows[0]["ends_at"])

    def test_too_long_description_is_refused_rather_than_cut(self):
        with self.assertRaisesRegex(ValueError, "bibliocommons_rss_description_oversize"):
            self.parse(document([make_item(narrative="description " * 1100)]))

    def test_broken_event_identity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "bibliocommons_rss_event_identity_invalid"):
            self.parse(document([make_item(url="https://attacker.example/events/123")]))

    def test_xml_doctype_rejected(self):
        with self.assertRaisesRegex(ValueError, "bibliocommons_rss_unsafe_xml"):
            self.parse(b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss/>')

    def test_exact_registered_profile_before_any_fetch(self):
        with self.assertRaisesRegex(ValueError, "unregistered_bibliocommons_rss_source"):
            rss.collect({**PROFILE, "feed_url": "https://another.example/"}, lambda *_: self.fail("unexpected request"), now=NOW)

    def test_one_short_page_is_a_complete_bounded_read(self):
        calls = []
        def fetch(url, accept):
            calls.append((url, accept))
            return document([make_item()])
        with patch.object(rss, "record", side_effect=sample_record):
            rows = rss.collect(PROFILE, fetch, now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(calls, [(PROFILE["feed_url"] + "?page=1", "application/rss+xml")])

    def test_repeated_full_page_never_claims_completeness(self):
        payload = document([make_item(i + 1) for i in range(rss.PAGE_SIZE)])
        with patch.object(rss, "record", side_effect=sample_record):
            with self.assertRaisesRegex(ValueError, "bibliocommons_rss_repeated_page"):
                rss.collect(PROFILE, lambda *_: payload, now=NOW)

    def test_limit_of_twenty_four_pages_refuses_unproven_tail(self):
        count = [0]
        def fetch(url, _):
            count[0] += 1
            start = count[0] * rss.PAGE_SIZE
            return document([make_item(i+start, virtual=True) for i in range(rss.PAGE_SIZE)])
        with patch.object(rss, "record", side_effect=sample_record):
            with self.assertRaisesRegex(ValueError, "bibliocommons_rss_pagination_incomplete"):
                rss.collect(PROFILE, fetch, now=NOW)
        self.assertEqual(count[0], rss.MAX_PAGES)


    def test_record_cap_fails_before_unbounded_pagination(self):
        count = [0]
        def fetch(url, _):
            count[0] += 1
            start = count[0] * rss.PAGE_SIZE
            return document([make_item(i+start) for i in range(rss.PAGE_SIZE)])
        with patch.object(rss, "record", side_effect=sample_record):
            with self.assertRaisesRegex(ValueError, "bibliocommons_rss_record_limit"):
                rss.collect(PROFILE, fetch, now=NOW)
        self.assertLess(count[0], rss.MAX_PAGES)

    def test_source_key_cannot_use_another_library_tenant(self):
        bad = {**PROFILE, "source_key": "king_county_library_rss_wa"}
        with self.assertRaisesRegex(ValueError, "unregistered_bibliocommons_rss_source"):
            rss.collect(bad, lambda *_: self.fail("unexpected request"), now=NOW)


if __name__ == "__main__":
    unittest.main()
