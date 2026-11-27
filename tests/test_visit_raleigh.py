"""Observed Raleigh formats, complete pagination and bounded checkpoint data."""
from copy import deepcopy
from datetime import date, datetime, time, timezone
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from roomquest import visit_raleigh as r

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
FIRST, LAST = date(2026, 11, 15), date(2027, 1, 13)
SOURCE = dict(source_key=r.SOURCE_KEY, feed_url=r.CALENDAR, kind="html",
              platform_adapter="html", timezone=r.ZONE.key, fetch_checkpoint_version=1)
PAGE = 'var eventsApi = new EventsApi({"apiToken":"public-fixture-token"}); var moduleData = {"eventCategories":["63","59"]};'


def item(identity=1001, *, day="2026-11-20", clock="Fri., 7-9pm", **extra):
    local = datetime.combine(date.fromisoformat(day), time(23, 59, 59), r.ZONE)
    row = dict(recId=str(identity), date=local.astimezone(timezone.utc).isoformat(),
        title="Publisher Program", description="<p>Complete event narrative.</p><p>Final publisher paragraph.</p>",
        times=clock, address1="100 Main Street", city="Raleigh", state="NC", zip="27601",
        location="Publisher Venue", latitude=35.78, longitude=-78.64,
        loc={"type": "Point", "coordinates": [-78.64, 35.78]},
        url=f"/event/publisher-program/{identity}/", categories=[{"catName": "Concerts"}],
        media_raw=[{"mediatype": "Image", "mediaurl": "https://assets.simpleviewinc.com/simpleview/image/upload/crm/raleigh/event.jpg"}])
    row.update(extra)
    return row


class RaleighParserTests(unittest.TestCase):
    def setUp(self):
        active = patch("roomquest.preview_worker._future_datetime", lambda value: value.astimezone(timezone.utc))
        active.start(); self.addCleanup(active.stop)

    def parse(self, value):
        return r.parse_occurrence(value, window_start=FIRST, window_end=LAST)

    def test_end_of_day_is_a_date_not_an_event_time(self):
        key, rows, reason = self.parse(item())
        self.assertEqual(key, "1001:2026-11-20")
        self.assertIsNone(reason)
        self.assertEqual(rows[0]["starts_at"], "2026-11-21T00:00:00+00:00")
        self.assertEqual(rows[0]["ends_at"], "2026-11-21T02:00:00+00:00")
        self.assertEqual(rows[0]["description"], "Complete event narrative.\nFinal publisher paragraph.")
        self.assertEqual(rows[0]["location_provenance"], "publisher_event_geo")
        self.assertEqual(rows[0]["lat"], 35.78)

    def test_unknown_times_and_weekday_conflicts_are_not_invented(self):
        for clock in ("", "Daily", "After dark", "Times vary with date", "Fri., all day", "Wed., 7-9pm", "Fri., 6 or 7pm"):
            with self.subTest(clock=clock):
                _, rows, reason = self.parse(item(clock=clock, pubDate="2099-01-01T12:00Z"))
                self.assertEqual(rows, [])
                self.assertEqual(reason, "event_time_missing_or_ambiguous")

    def test_weekday_clauses_multiple_showtimes_and_shared_suffixes(self):
        clock = "Wed.-Fri., 7:30pm, Sat., 2 and 7:30pm, Sun., 2pm"
        _, rows, _ = self.parse(item(day="2026-11-21", clock=clock))
        self.assertEqual([row["starts_at"] for row in rows], ["2026-11-21T19:00:00+00:00", "2026-11-22T00:30:00+00:00"])
        self.assertEqual(r.schedule_hours("Fri., early show, 6:30-8pm; late show, 9:30-11pm", date(2026, 11, 20)),
                         [(time(18, 30), time(20)), (time(21, 30), time(23))])
        self.assertEqual(r.schedule_hours("Wed., Sat., and Sun; 1-2pm", FIRST), [(time(13), time(14))])

    def test_noon_midnight_overnight_and_month_season(self):
        _, rows, _ = self.parse(item(clock="Fri., 8pm-midnight"))
        self.assertEqual(rows[0]["ends_at"], "2026-11-21T05:00:00+00:00")
        self.assertEqual(r.schedule_hours("October-March 9am-noon; April-September 8am-nopn", FIRST), [(time(9), time(12))])
        self.assertEqual(r.schedule_hours("Fri., 11-1pm", date(2026, 11, 20)), [(time(11), time(13))])

    def test_unlabelled_clocks_do_not_become_daily_after_a_weekday_clause(self):
        saturday, sunday = date(2026, 12, 26), date(2026, 12, 27)
        ambiguous = "Sat., 7 and 9:30pm; 6 and 8:30pm"
        self.assertEqual(r.schedule_hours(ambiguous, saturday), [(time(19), None), (time(21, 30), None)])
        self.assertEqual(r.schedule_hours(ambiguous, sunday), [])
        paired = "Sat., early show, 6:30-8pm; late show, 9:30-11pm"
        self.assertEqual(r.schedule_hours(paired, saturday), [(time(18, 30), time(20)), (time(21, 30), time(23))])
        self.assertEqual(r.schedule_hours(paired, sunday), [])
        self.assertEqual(r.schedule_hours("Sat., 7pm; Daily, 6pm", sunday), [(time(18), None)])
        self.assertEqual(r.schedule_hours("6pm; 8:30pm", sunday), [(time(18), None), (time(20, 30), None)])

    def test_doors_signup_and_seating_are_not_performances(self):
        for clock in ("Fri., 7pm, doors open 1 hour prior", "Fri., 7pm (Doors open 6pm)"):
            self.assertEqual(r.schedule_hours(clock, date(2026, 11, 20)), [(time(19), None)])
        self.assertEqual(r.schedule_hours("Thur. 6:30-8pm; seating starts at 5:30pm", date(2026, 11, 19)), [(time(18, 30), time(20))])
        self.assertEqual(r.schedule_hours("Sign ups, 8pm; Singing, 9pm-2am", FIRST), [(time(21), time(2))])
        self.assertEqual(r.schedule_hours("Thurs., 5:30-8pm. Sign up starts at 5pm", date(2026, 11, 19)), [(time(17, 30), time(20))])
        self.assertEqual(len(r.schedule_hours("Departure Times, 9:30am, 11am; 12:30pm, 2:15pm and 3:45pm", FIRST)), 5)

    def test_closure_and_ambiguous_first_weekday(self):
        self.assertEqual(r.schedule_hours("Daily, 6-10pm; Closed Christmas Day", date(2026, 12, 25)), [])
        self.assertEqual(r.schedule_hours("Daily, 6-10pm; Closed Christmas Day", date(2026, 12, 24)), [(time(18), time(22))])
        ambiguous = "Wed.-Sun., 10am, 11:15am, and 12:30pm (first Wednesday is only 11:15 and 12:30pm)"
        for day in (date(2026, 11, 18), date(2026, 12, 2)):
            self.assertEqual(r.schedule_hours(ambiguous, day), [(time(11, 15), None), (time(12, 30), None)])
        self.assertEqual(len(r.schedule_hours(ambiguous, date(2026, 11, 19))), 3)
        self.assertEqual(r.schedule_hours("Sun., 8pm-midnight (or 1am depending on the date)", FIRST), [(time(20), None)])

    def test_complete_narrative_and_native_admission(self):
        text = "Publisher paragraph. " * 160 + "Complete final condition."
        _, rows, _ = self.parse(item(description=text, admission="$12 advance; $15 at the door"))
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertIn("Complete final condition.", rows[0]["description"])
        self.assertTrue(rows[0]["description"].endswith("Admission: $12 advance; $15 at the door"))
        with self.assertRaisesRegex(ValueError, "description_limit"):
            self.parse(item(description="x" * 12001))

    def test_native_partial_address_retains_actual_publisher_point(self):
        _, rows, _ = self.parse(item(address1="Downtown Raleigh", zip=None))
        self.assertEqual(rows[0]["venue_address"], "Downtown Raleigh, Raleigh, NC")
        self.assertEqual(rows[0]["lat"], 35.78)
        _, rows, reason = self.parse(item(loc={"type": "Point", "coordinates": [-78.7, 35.9]}))
        self.assertEqual((rows, reason), ([], "venue_coordinates_conflict"))

    def test_linked_venue_requires_exact_identity_and_address_match(self):
        linked = dict(recid=77, title="Publisher Venue", address1="100 Main Street", city="Raleigh", state="NC",
                      zip="27601", latitude=35.79, longitude=-78.65)
        _, rows, _ = self.parse(item(latitude=40.8, longitude=-74.2, loc=None, listing_id=77, listing=linked))
        self.assertEqual(rows[0]["location_provenance"], "publisher_linked_venue_geo")
        self.assertEqual(rows[0]["lat"], 35.79)
        _, rows, _ = self.parse(item(latitude=None, longitude=None, loc=None, listing_id=78, listing=linked))
        self.assertIsNone(rows[0]["lat"])
        self.assertEqual(rows[0]["location_provenance"], "publisher_event_address_pending_geocode")


class RaleighCheckpointTests(unittest.TestCase):
    def setUp(self):
        active = patch("roomquest.preview_worker._future_datetime", lambda value: value.astimezone(timezone.utc))
        active.start(); self.addCleanup(active.stop)

    def fetcher(self, count):
        self.calls = []
        def fetch(url, accept):
            self.calls.append(url)
            if url == r.CALENDAR:
                return PAGE
            self.assertTrue(url.startswith(r.API + "?"))
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["options[sort][recId]"], ["1"])
            offset = int(query["options[skip]"][0])
            return json.dumps(dict(total=count, docs=[item(n + 1) for n in range(offset, min(offset + 100, count))]))
        return fetch

    def test_future_window_uses_publisher_dates_and_real_checkpoint_age(self):
        from roomquest.collection_window import collection_scope

        window = {"version": 1, "start": "2027-01-20T05:00:00Z", "end": "2027-03-21T05:00:00Z"}
        with collection_scope({"collection_window": window}):
            result = r.collect_chunk(SOURCE, self.fetcher(0), now=NOW)
            checkpoint = result["checkpoint"]
            self.assertEqual(checkpoint["started_at"], NOW.isoformat())
            self.assertEqual((checkpoint["window_start"], checkpoint["window_end"]), ("2027-01-20", "2027-03-20"))
            query = str(parse_qs(urlsplit(self.calls[-1]).query))
            self.assertIn("2027-01-20", query)
            self.assertIn("2027-03-21", query)
            r.decode_checkpoint(checkpoint, now=NOW)
            with self.assertRaisesRegex(ValueError, "expired"):
                r.decode_checkpoint(checkpoint, now=NOW.replace(hour=17))
        with self.assertRaisesRegex(ValueError, "invalid"):
            r.decode_checkpoint(checkpoint, now=NOW)

    def test_multiple_pages_only_complete_after_all_occurrences(self):
        fetch = self.fetcher(205)
        first = r.collect_chunk(SOURCE, fetch, now=NOW, max_pages=1)
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        self.assertEqual(first["checkpoint"]["cursor"], 1)
        final = r.collect_chunk(SOURCE, fetch, checkpoint=first["checkpoint"], now=NOW, max_pages=2)
        self.assertTrue(final["complete"])
        self.assertEqual(len(final["events"]), 205)
        self.assertEqual(final["checkpoint"]["events"], [])
        self.assertEqual(final["checkpoint"]["cursor"], final["checkpoint"]["manifest_count"])
        header, state = r.decode_checkpoint(final["checkpoint"], now=NOW)
        self.assertEqual((header["record_count"], len(state["seen"])), (205, 205))
        self.assertEqual(len([url for url in self.calls if url == r.CALENDAR]), 1)
        self.assertLess(len(r._encoded(final["checkpoint"]).encode()), r.MAX_CHECKPOINT_BYTES)

    def test_changed_total_or_duplicate_page_fails_no_partial_success(self):
        fetch = self.fetcher(205)
        first = r.collect_chunk(SOURCE, fetch, now=NOW, max_pages=1)
        for response in (dict(total=206, docs=[item(n + 101) for n in range(100)]),
                         dict(total=205, docs=[item(n + 1) for n in range(100)])):
            with self.subTest(total=response["total"]), self.assertRaisesRegex(ValueError, "pagination_changed"):
                r.collect_chunk(SOURCE, lambda *args: json.dumps(response), checkpoint=first["checkpoint"], now=NOW)

    def test_empty_and_overflow_snapshots(self):
        result = r.collect_chunk(SOURCE, self.fetcher(0), now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(result["checkpoint"]["manifest_count"], 0)
        r.decode_checkpoint(result["checkpoint"], now=NOW)
        with self.assertRaisesRegex(ValueError, "record_limit"):
            r.collect_chunk(SOURCE, self.fetcher(6001), now=NOW)

    def test_checkpoint_integrity_and_bounded_decompression(self):
        checkpoint = r.collect_chunk(SOURCE, self.fetcher(1), now=NOW)["checkpoint"]
        changed = deepcopy(checkpoint); changed["payload_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            r.decode_checkpoint(changed, now=NOW)
        changed = deepcopy(checkpoint); changed["stage_cursor"] = 2
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            r.decode_checkpoint(changed, now=NOW)
        with patch.object(r, "MAX_DECODED_BYTES", 64), self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            r.decode_checkpoint(checkpoint, now=NOW)
        with self.assertRaisesRegex(ValueError, "checkpoint_expired"):
            r.decode_checkpoint(checkpoint, now=NOW.replace(hour=17))

    def test_registration_host_and_calendar_configuration_are_exact(self):
        for field, value in (("source_key", "other"), ("feed_url", "https://other.example/events/"), ("kind", "rss")):
            with self.assertRaisesRegex(ValueError, "unregistered"):
                r.collect_chunk({**SOURCE, field: value}, self.fetcher(1), now=NOW)
        self.assertFalse(r.event_url("https://evil.example/event/a/1/"))
        self.assertFalse(r.event_url("https://www.visitraleigh.com/event/a/1/?url=other"))
        with self.assertRaisesRegex(ValueError, "calendar_configuration"):
            r.calendar_configuration("<html>No public API widget</html>")


if __name__ == "__main__":
    unittest.main()
