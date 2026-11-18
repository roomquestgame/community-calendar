import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from roomquest import oc_parks_partial as oc

NOW = datetime(2026, 11, 18, 21, tzinfo=timezone.utc)
SOURCE = {
    "source_key": oc.SOURCE_KEY, "feed_url": oc.CALENDAR,
    "kind": "html", "platform_adapter": "html", "timezone": oc.ZONE,
}


def event(n=1, title="Oak Woodland Bird Walk", path="/events/oak-woodland-bird-walk-2",
          start="2026-11-19T07:30:00", end="2026-11-19T09:30:00"):
    return {"title": title, "url": path, "eid": str(n), "id": f"0-{n}",
            "start": start, "end": end, "des": ""}


def listing(rows=None):
    options = {"events": rows if rows is not None else [event()]}
    settings = {"fullCalendarView": [{"calendar_options": json.dumps(options)}]}
    return ('<html><script data-drupal-selector="drupal-settings-json" type="application/json">'
            + json.dumps(settings) + '</script></html>')


def detail(title="Oak Woodland Bird Walk", date="Thu, November 19, 2026",
           hours="7:30 am - 9:30 am PST", street="2145 N. Windes Drive",
           city="Orange", postal="92869",
           narrative="<p>Official publisher describes an outdoor bird walk with binoculars.</p>"):
    return f"""<html><head><title>{title} | OC Parks</title></head><body>
       <div class="info-date-time__body">{date}<br>{hours}</div>
       <div class="info-location__body"><p class="address">
          <span class="address-line1">{street}</span>
          <span class="locality">{city}</span>
          <span class="administrative-area">CA</span>
          <span class="postal-code">{postal}</span></p></div>
       <div id="wysiwyg-body-node-na-0">
          <span class="visually-hidden">Body</span>{narrative}</div>
       <img src="https://parks.oc.gov/images/unlicensed-photo.jpg"></body></html>"""


def fake_record(*args, **kwargs):
    return {"id": args[7], "starts_at": args[1], "ends_at": args[2],
            "venue_name": args[3], "venue_address": args[4], "event_url": args[6],
            "lat": kwargs.get("lat"), "lng": kwargs.get("lng"),
            "image_url": "must_not_be_approved",
            "image_candidate_url": "must_not_be_approved"}


class OCParksPartialTests(unittest.TestCase):
    def setUp(self):
        self.entry = oc.parse_calendar(listing(), now=NOW)[0]

    def collect(self, first=None, second=None, source=None):
        calls = []
        def fetch(url, accept):
            calls.append((url, accept))
            return (first or listing()) if url == oc.CALENDAR else (second or detail())
        with patch.object(oc, "record", side_effect=fake_record):
            rows = oc.collect(source or SOURCE, fetch, now=NOW)
        return rows, calls

    def test_exact_source_only_and_zero_network_before_admission(self):
        with self.assertRaisesRegex(ValueError, "unregistered_oc_parks_source"):
            oc.collect({**SOURCE, "feed_url": "https://example.com"},
                       lambda *_: self.fail("network not allowed"), now=NOW)

    def test_publisher_detail_parity_street_and_reviewed_park_point(self):
        with patch.object(oc, "record", side_effect=fake_record):
            row, text = oc.parse_detail(self.entry, detail())
        self.assertEqual(row["venue_name"], "Santiago Oaks Regional Park")
        self.assertEqual(row["venue_address"], "2145 N. Windes Drive, Orange, CA 92869")
        self.assertEqual(row["lat"], 33.816145)
        self.assertEqual(row["lng"], -117.779097)
        self.assertIn("binoculars", text)
        self.assertNotIn("Body", text)
        self.assertEqual(row["ends_at"], "2026-11-19T09:30:00-08:00")

    def test_event_images_are_never_granted_from_page_presence(self):
        rows, _ = self.collect()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("image_url", rows[0])
        self.assertNotIn("image_candidate_url", rows[0])

    def test_shared_black_star_canyon_address_is_held_not_mapped(self):
        rows, _ = self.collect(second=detail(street="13333 Black Star Canyon Rd",
                                             city="Silverado", postal="92676"))
        self.assertEqual(rows, [])

    def test_missing_event_owned_street_is_held(self):
        rows, _ = self.collect(second=detail(street="Irvine Ranch Open Space"))
        self.assertEqual(rows, [])

    def test_time_mismatch_is_held(self):
        rows, _ = self.collect(second=detail(hours="8:30 am - 9:30 am PST"))
        self.assertEqual(rows, [])

    def test_changed_date_is_held(self):
        rows, _ = self.collect(second=detail(date="Fri, November 20, 2026"))
        self.assertEqual(rows, [])

    def test_changed_publisher_title_is_held(self):
        rows, _ = self.collect(second=detail(title="Not The Same Event"))
        self.assertEqual(rows, [])

    def test_full_description_is_preserved_not_cut(self):
        narrative="<p>" + "Original factual description. "*50 + "</p>"
        rows, _ = self.collect(second=detail(narrative=narrative))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], narrative[3:-4])

    def test_oversize_description_is_held_not_silently_truncated(self):
        rows, _ = self.collect(second=detail(narrative="<p>"+("Long factual details. "*150)+"</p>"))
        self.assertEqual(rows, [])

    def test_missing_reviewed_pin_stages_only_with_unknown_coordinates(self):
        with patch.object(oc, "record", side_effect=fake_record):
            row, _ = oc.parse_detail(self.entry, detail(
                street="2152 New Public Rd", city="Orange", postal="92869"))
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lng"])

    def test_limit_of_500_source_rows_is_not_a_claim_of_complete_coverage(self):
        entries = [event(n=i+1,path=f"/events/test-event-{i+1}")
                   for i in range(500)]
        result = oc.parse_calendar(listing(entries), now=NOW)
        self.assertEqual(len(result), oc.MAX_DETAIL_FETCHES)
        self.assertLess(oc.MAX_DETAIL_FETCHES, 500)

    def test_more_than_500_publisher_rows_fails(self):
        with self.assertRaisesRegex(ValueError, "oc_parks_calendar_count_invalid"):
            oc.parse_calendar(listing([event(n=i+1,path=f"/events/test-{i+1}") for i in range(501)]), now=NOW)

    def test_selected_date_window_excludes_past_and_far_future(self):
        a = event(n=1,path="/events/past",start="2026-11-10T07:30:00",end="2026-11-10T09:30:00")
        b = event(n=2,path="/events/now")
        c = event(n=3,path="/events/far-future",start="2027-12-19T07:30:00",end="2027-12-19T09:30:00")
        r = oc.parse_calendar(listing([a,b,c]),now=NOW)
        self.assertEqual([e["eid"] for e in r], ["2"])

    def test_fetch_only_calendar_and_exact_publisher_details(self):
        rows, calls = self.collect()
        self.assertEqual(len(rows), 1)
        self.assertEqual(calls, [(oc.CALENDAR,"text/html"),
                                 ("https://parks.oc.gov/events/oak-woodland-bird-walk-2","text/html")])

    def test_date_without_verified_start_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "oc_parks_calendar_time_invalid"):
            oc.parse_calendar(listing([event(start="TBD")]), now=NOW)

    def test_detail_bad_postal_is_held(self):
        rows,_ = self.collect(second=detail(postal="unknown"))
        self.assertEqual(rows, [])

    def test_unexpected_remote_calendar_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"oc_parks_calendar_url_invalid"):
            oc.parse_calendar(listing([event(path="https://other.example/events/test")]),now=NOW)

    def test_repeated_publisher_ids_are_not_duplicated(self):
        rows = [event(),event()]
        self.assertEqual(len(oc.parse_calendar(listing(rows),now=NOW)),1)


if __name__ == "__main__":
    unittest.main()
