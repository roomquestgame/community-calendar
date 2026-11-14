"""Focused coverage for the observed Simpleview sitemap/detail contract."""
from copy import deepcopy
from datetime import date, datetime, timezone
import html
import json
import unittest
from unittest.mock import patch

from roomquest import visit_atlantic_city as ac


NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
SOURCE = {"source_key": ac.SOURCE_KEY, "feed_url": ac.CALENDAR, "kind": "html",
          "platform_adapter": "html", "timezone": ac.ZONE.key}


def url(n=1):
    return f"https://{ac.HOST}/event/official-program/{n}/"


def sitemap(urls):
    return '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f"<url><loc>{html.escape(item)}</loc></url>" for item in urls) + "</urlset>"


def detail(n=1, *, start="2026-11-20", end="2026-11-20", clock="8:00 PM",
           recurrence=None, prose="<p>Official event narrative.</p><p>Full final paragraph.</p>",
           street="1000 Boardwalk"):
    event = {"@type": "MusicEvent", "url": url(n), "name": "Official Program",
             "startDate": start, "eventStatus": "https://schema.org/EventScheduled",
             "location": {"@type": "LocalBusiness", "name": "Official Venue",
                          "address": {"streetAddress": street, "addressLocality": "Atlantic City",
                                      "addressRegion": "NJ", "postalCode": "08401"},
                          "geo": {"latitude": 39.3599884, "longitude": -74.4212353}},
             "image": {"url": "https://assets.simpleviewinc.com/official-event.jpg"}}
    if end:
        event["endDate"] = end
    data = {"recid": str(n), "title": event["name"], "description": prose,
            "expired": False, "past": False,
            "categories": [{"catName": "Concerts", "catId": "3"}]}
    if recurrence:
        data["recurrence"] = recurrence
    return (f'<link rel="canonical" href="{url(n)}">'
            f'<script type="application/ld+json">{json.dumps({"@graph": [event]})}</script>'
            f'<script>var data = {json.dumps(data)};\nvar time = {json.dumps(clock)};</script>')


class VisitAtlanticCityTests(unittest.TestCase):
    def setUp(self):
        self.clock_patch = patch("roomquest.preview_worker._future_datetime",
                                 lambda value: value.astimezone(timezone.utc))
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)

    def parse(self, payload, n=1):
        return ac.parse_detail(payload, url(n), window_start=date(2026, 11, 14))

    def test_complete_description_and_street_timezone_publisher_geo(self):
        rows, reason = self.parse(detail())
        self.assertIsNone(reason)
        row, = rows
        self.assertEqual(row["starts_at"], "2026-11-21T01:00:00+00:00")
        self.assertIsNone(row["ends_at"])
        self.assertEqual(row["description"], "Official event narrative.\nFull final paragraph.")
        self.assertEqual(row["venue_address"], "1000 Boardwalk, Atlantic City, NJ 08401")
        self.assertEqual(row["lat"], 39.3599884)
        self.assertEqual(row["publisher_categories"], ["Concerts"])
        self.assertIn("simpleviewinc.com", row["image_url"])

    def test_narrative_over_old_cap_is_complete_and_new_cap_never_truncates(self):
        text = "First paragraph. " + "Body details. " * 350 + "COMPLETE LAST SENTENCE."
        rows, _ = self.parse(detail(prose=text))
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertTrue(rows[0]["description"].endswith("COMPLETE LAST SENTENCE."))
        with self.assertRaisesRegex(ValueError, "description_limit"):
            self.parse(detail(prose="x" * 12001))

    def test_missing_description_or_street_is_held(self):
        self.assertEqual(self.parse(detail(prose="")), ([], "event_description_missing"))
        self.assertEqual(self.parse(detail(street="Boardwalk")), ([], "venue_address_missing"))

    def test_building_prefix_does_not_hide_structured_street(self):
        rows, _ = self.parse(detail(street="The Quarter at Tropicana 2801 Pacific Ave."))
        self.assertEqual(rows[0]["venue_address"], "2801 Pacific Ave., Atlantic City, NJ 08401")

    def test_little_water_unit_and_publisher_parking_instruction_are_preserved(self):
        street = "807 Baltic Ave., Unit B (park and enter at 813 Lexington Ave.)"
        payload = detail(street=street).replace('"Official Venue"', '"Little Water Distillery"')
        rows, _ = self.parse(payload)
        self.assertEqual(rows[0]["venue_address"], "807 Baltic Avenue Unit B, Atlantic City, NJ 08401")
        self.assertEqual(rows[0]["description"],
                         "Official event narrative.\nFull final paragraph.\n"
                         "Publisher venue access note: park and enter at 813 Lexington Ave.")
        # The exception cannot normalize a different venue's ambiguous address.
        other, _ = self.parse(detail(street=street))
        self.assertEqual(other[0]["venue_address"], street + ", Atlantic City, NJ 08401")

    def test_publisher_parking_note_obeys_description_limit_and_is_not_duplicated(self):
        street = "807 Baltic Ave., Unit B (park and enter at 813 Lexington Ave.)"
        prose = "Official event narrative. Please park and enter at 813 Lexington Ave."
        payload = detail(street=street, prose=prose).replace('"Official Venue"', '"Little Water Distillery"')
        rows, _ = self.parse(payload)
        self.assertEqual(rows[0]["description"], prose)
        payload = detail(street=street, prose="x" * 11999).replace('"Official Venue"', '"Little Water Distillery"')
        with self.assertRaisesRegex(ValueError, "description_limit"):
            self.parse(payload)

    def test_midnight_rollover_requires_explicit_two_clocks(self):
        rows, _ = self.parse(detail(clock="11:00 PM - 3:00 AM"))
        self.assertEqual(rows[0]["starts_at"], "2026-11-21T04:00:00+00:00")
        self.assertEqual(rows[0]["ends_at"], "2026-11-21T08:00:00+00:00")

    def test_two_published_showtimes_remain_separate_occurrences(self):
        rows, _ = self.parse(detail(clock="6:00 PM & 9:00 PM"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({(x["id"], x["starts_at"]) for x in rows}), 2)

    def test_missing_ambiguous_or_incomplete_time_never_becomes_all_day(self):
        for clock in ("", "Varies", "See website", "7:00 PM - 9:00", "8 PM - 8 PM"):
            with self.subTest(clock=clock):
                self.assertEqual(self.parse(detail(clock=clock)), ([], "event_time_missing_or_ambiguous"))

    def test_weekly_recurrence_has_only_published_days_within_bounds(self):
        rows, _ = self.parse(detail(start="2026-02-06", end="2026-11-28", clock="11 PM - 3 AM",
                                    recurrence="Recurring weekly on Friday, Saturday"))
        self.assertEqual(len(rows), 5)
        local_days = [datetime.fromisoformat(row["starts_at"]).astimezone(ac.ZONE).date().day for row in rows]
        self.assertEqual(local_days, [14, 20, 21, 27, 28])

    def test_multiday_range_without_recurrence_is_held(self):
        self.assertEqual(self.parse(detail(end="2026-11-23")), ([], "schedule_requires_review"))

    def test_daily_recurrence_is_finite(self):
        rows, _ = self.parse(detail(end="2026-11-23", recurrence="Recurring daily"))
        self.assertEqual(len(rows), 4)

    def test_monthly_rule_and_weekday_specific_published_clocks(self):
        rows, _ = self.parse(detail(start="2026-01-01", end="2026-12-31", clock="9 PM",
                                    recurrence="Recurring monthly on the 1st Friday"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["starts_at"], "2026-12-05T02:00:00+00:00")
        rows, _ = self.parse(detail(start="2026-11-20", end="2026-11-21", clock="",
                                    recurrence="Recurring weekly on Friday, Saturday",
                                    prose="<p>Official show.</p><p>Friday: 9:00 p.m.<br>Saturday: 8:00 p.m.</p>"))
        self.assertEqual([row["starts_at"] for row in rows],
                         ["2026-11-21T02:00:00+00:00", "2026-11-22T01:00:00+00:00"])

    def test_explicit_date_list_and_date_override_never_generate_intervening_dates(self):
        payload = detail(start="2026-11-01", end="2026-11-30", clock="8 PM",
                         prose="<p>Official show.</p><p>11/27 - 8:30 p.m.<br>11/28 - 7:00 p.m. &amp; 9:00 p.m.</p>")
        payload += '<script>var dates = "11/20/2026, 11/27/2026, 11/28/2026";</script>'
        rows, _ = self.parse(payload)
        self.assertEqual([row["starts_at"] for row in rows],
                         ["2026-11-21T01:00:00+00:00", "2026-11-28T01:30:00+00:00",
                          "2026-11-29T00:00:00+00:00", "2026-11-29T02:00:00+00:00"])
        payload = detail(start="2026-02-21", end="2026-12-05", clock="1 PM")
        payload += '<script>var dates = "12/5/2026";</script>'
        rows, _ = self.parse(payload)
        self.assertEqual([row["starts_at"] for row in rows], ["2026-12-05T18:00:00+00:00"])

    def test_additional_one_day_showtime_requires_explicit_matching_prose(self):
        rows, _ = self.parse(detail(clock="4 PM", prose="Official show at 4:00 p.m. and 7:00 p.m. for the holidays."))
        self.assertEqual(len(rows), 2)
        rows, _ = self.parse(detail(clock="4 PM", prose="Doors open at 4:00 p.m. and the show begins at 7:00 p.m."))
        self.assertEqual(len(rows), 1)

    def test_weekday_prose_and_new_year_date_clocks_remain_exact(self):
        rows, _ = self.parse(detail(start="2026-11-20", end="2026-11-22", clock="",
                                    recurrence="Recurring weekly on Sunday, Friday, Saturday",
                                    prose="Catch Fridays at 7:30 p.m., Saturdays at 1:30 p.m., 5:30 p.m., and 7:30 p.m., or enjoy the Sunday Brunch Show at 1:30 p.m."))
        self.assertEqual(len(rows), 5)
        self.assertEqual([datetime.fromisoformat(row["starts_at"]).astimezone(ac.ZONE).hour for row in rows],
                         [19, 13, 17, 19, 13])
        rows, _ = self.parse(detail(start="2026-12-31", end="2027-01-01", clock="", recurrence="Recurring daily",
                                    prose="Celebrate on December 31 starting at 10:00 p.m. and January 1 starting at 8:00 p.m."))
        self.assertEqual([row["starts_at"] for row in rows], ["2027-01-01T03:00:00+00:00", "2027-01-02T01:00:00+00:00"])

    def test_detail_identity_is_verified_before_content(self):
        for payload in (detail().replace(url(), url(2)), detail().replace('"recid": "1"', '"recid": "2"')):
            with self.assertRaisesRegex(ValueError, "detail_identity"):
                self.parse(payload)

    def test_schema_festival_is_an_event_and_does_not_hide_trivia(self):
        rows, _ = self.parse(detail().replace('"@type": "MusicEvent"', '"@type": "Festival"'))
        self.assertEqual(len(rows), 1)

    def test_reviewed_parade_finish_uses_park_address_without_city_center_coordinates(self):
        payload = detail(7140, street="Atlantic Avenue",
                         prose="The parade ends at O'Donnell Memorial Park at the Holiday Market.")
        rows, _ = self.parse(payload, 7140)
        self.assertEqual(rows[0]["venue_address"], "3501 Atlantic Avenue, Atlantic City, NJ 08401")
        self.assertIn("parade finish", rows[0]["venue_name"])
        self.assertIsNone(rows[0]["lat"])
        self.assertIsNone(rows[0]["lng"])

    def test_golden_nugget_intersection_gets_published_numbered_street(self):
        payload = detail(street="Huron Ave. & Brigantine Blvd.").replace('"name": "Official Venue"',
                                                                       '"name": "Golden Nugget Atlantic City"')
        rows, _ = self.parse(payload)
        self.assertEqual(rows[0]["venue_address"], "600 Huron Avenue, Atlantic City, NJ 08401")

    def test_manifest_only_selects_reviewed_event_urls(self):
        self.assertEqual(ac.manifest(sitemap([url(), "https://outside.example/event/program/3/",
                                             f"https://{ac.HOST}/meetings/event/", url()])), [url()])
        with self.assertRaisesRegex(ValueError, "sitemap_invalid"):
            ac.manifest("<html>Access Denied</html>")

    def test_source_tuple_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "unregistered_visit"):
            ac.collect_chunk({**SOURCE, "feed_url": "https://other.example/events/"},
                             lambda *_: self.fail("Network was called"), now=NOW)

    def test_only_completed_manifest_returns_records_and_resumes_without_refetching_details(self):
        calls = []
        urls = [url(1), url(2), url(3)]
        def fetch(target, accept):
            calls.append(target)
            return sitemap(urls) if target == ac.SITEMAP else detail(int(target.rstrip("/").split("/")[-1]))
        result = ac.collect_chunk(SOURCE, fetch, max_details=1, now=NOW)
        self.assertFalse(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["cursor"], 1)
        result = ac.collect_chunk(SOURCE, fetch, checkpoint=result["checkpoint"], now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["events"]), 3)
        self.assertEqual(calls.count(url()), 1)
        self.assertEqual(calls.count(ac.SITEMAP), 2)

    def test_detail_fetch_failure_does_not_publish_partial_snapshot(self):
        def fetch(target, accept):
            if target == ac.SITEMAP:
                return sitemap([url(), url(2)])
            if target == url():
                return detail()
            raise OSError("publisher unavailable")
        with self.assertRaises(OSError):
            ac.collect_chunk(SOURCE, fetch, now=NOW)

    def test_explicit_gone_detail_is_recorded_but_other_http_errors_block(self):
        from roomquest.preview_worker import PreviewError
        def fetch(target, accept):
            if target == ac.SITEMAP:
                return sitemap([url()])
            raise PreviewError("publisher_http_410")
        result = ac.collect_chunk(SOURCE, fetch, now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["diagnostics"][0]["reason"], "publisher_page_gone")
        def blocked(target, accept):
            if target == ac.SITEMAP:
                return sitemap([url()])
            raise PreviewError("publisher_http_403")
        with self.assertRaisesRegex(PreviewError, "publisher_http_403"):
            ac.collect_chunk(SOURCE, blocked, now=NOW)

    def test_checkpoint_rejects_tampered_url_or_blank_description(self):
        fetch = lambda target, accept: sitemap([url(), url(2)]) if target == ac.SITEMAP else detail()
        result = ac.collect_chunk(SOURCE, fetch, max_details=1, now=NOW)
        for field, value in (("event_url", "https://elsewhere.example/"), ("description", "")):
            state = deepcopy(result["checkpoint"])
            state["events"][0][field] = value
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ac.collect_chunk(SOURCE, fetch, checkpoint=state, now=NOW)

    def test_manifest_change_restarts_safely_and_missing_time_is_diagnostic(self):
        fetch = lambda target, accept: sitemap([url(), url(2)]) if target == ac.SITEMAP else detail()
        first = ac.collect_chunk(SOURCE, fetch, max_details=1, now=NOW)
        calls = []
        def changed(target, accept):
            calls.append(target)
            return sitemap([url(3)]) if target == ac.SITEMAP else detail(3, clock="Varies")
        result = ac.collect_chunk(SOURCE, changed, checkpoint=first["checkpoint"], now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["checkpoint"]["diagnostics"][0]["reason"], "event_time_missing_or_ambiguous")
        self.assertEqual(calls, [ac.SITEMAP, url(3)])

    def test_plain_collect_refuses_a_partial_snapshot(self):
        urls = [url(n) for n in range(1, 8)]
        def fetch(target, accept):
            return sitemap(urls) if target == ac.SITEMAP else detail(int(target.rstrip("/").split("/")[-1]))
        with self.assertRaisesRegex(ValueError, "checkpoint_required"):
            ac.collect(SOURCE, fetch, now=NOW)


if __name__ == "__main__":
    unittest.main()
