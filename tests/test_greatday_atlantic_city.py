from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from roomquest import greatday_atlantic_city as gd


NOW = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)
SOURCE = dict(source_key=gd.KEY, feed_url=gd.URL, kind="html", platform_adapter="html", timezone=gd.ZONE)


def card(slug, title, day="11/21/2026", address="108 N. Pennsylvania Ave."):
    return f'''<div class="home_event_item"><div class="home_event_item-content-top">
      <h3>{title}</h3><div class="card-detail-icon-text">{day}</div>
      <div class="card-detail-icon-text">{address}</div></div>
      <div class="tag-red">COMMUNITY</div><a class="card-link" href="/events/{slug}"></a></div>'''


def listing(cards, next_page=None):
    pagination = f'<a class="w-pagination-next" href="{next_page}">Next</a>' if next_page else ""
    # The large past collection must not enter either the manifest or queue.
    return ('<section><h2>All Upcoming Area Events</h2>' + cards + pagination + '</section>'
            '<section><h2>All Past Events</h2>' + card('past-copy', 'Old event', '11/1/2026')
            + '<a class="w-pagination-next" href="?99df7b3b_page=2">Past next</a></section>')


def detail(title, body, day="Nov 21, 2026", address="108 N. Pennsylvania Ave."):
    return f'''<h1>{title}</h1><div class="blog-post-info-detail">
      <div class="card-detail-icon-text">{day}</div><div class="card-detail-icon-text">{address}</div>
      </div><div class="blog-rich-text w-richtext">{body}</div>'''


def row_record(title, start, end, venue, address, city, url, identity, category="", **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, category=category,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


class GreatDayTests(unittest.TestCase):
    def test_paginated_snapshot_only_returns_complete_full_descriptions(self):
        body = ("<p>On Saturday, November 21, from 11 a.m. to 1 p.m. neighbors are welcome.</p>"
                + "<p>All the event details and participant information. " * 100 + "Final paragraph.</p>")
        expected = gd.narrative(body)
        pages = {
            gd.URL: listing(card("one", "One"), "?81bc4a64_page=2"),
            gd.URL + "?81bc4a64_page=2": listing(card("two", "Two")),
            gd.URL + "/one": detail("One", body),
            gd.URL + "/two": detail("Two", body),
        }
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(gd, "record", side_effect=row_record):
            first = gd.collect_chunk(SOURCE, fetch, now=NOW, max_details=1)
            self.assertFalse(first["complete"])
            self.assertEqual(first["events"], [])
            self.assertEqual(first["checkpoint"]["manifest_count"], 2)
            second = gd.collect_chunk(SOURCE, fetch, now=NOW, checkpoint=first["checkpoint"], max_details=1)
        self.assertTrue(second["complete"])
        self.assertEqual(len(second["events"]), 2)
        self.assertTrue(all(r["description"] == expected for r in second["events"]))
        self.assertGreater(len(expected), 4500)
        self.assertTrue(all(r["venue_address"] == "108 N Pennsylvania Avenue, Atlantic City, NJ 08401" for r in second["events"]))
        self.assertTrue(all((r["lat"], r["lng"]) == (39.361843, -74.423196) for r in second["events"]))
        self.assertEqual(first["checkpoint"]["cursor"], 1)
        self.assertFalse(any("99df7b3b" in call.args[0] or "past-copy" in call.args[0] for call in fetch.call_args_list))

    def test_multiday_clock_selection_uses_the_dated_occurrence(self):
        body = ("Turkey distribution on Saturday, November 21, from 11:00 a.m. to 1:00 p.m. "
                "On Thursday, November 26, hot meals from 3:00 p.m. to 6:00 p.m. "
                "Volunteers work 2:00 p.m. to 4:30 p.m. or 4:30 p.m. to 7:00 p.m.")
        first = gd._schedule(date(2026, 11, 21), body)
        second = gd._schedule(date(2026, 11, 26), body)
        self.assertEqual(tuple(t.isoformat() for t in first), ("2026-11-21T16:00:00+00:00", "2026-11-21T18:00:00+00:00"))
        self.assertEqual(tuple(t.isoformat() for t in second), ("2026-11-26T20:00:00+00:00", "2026-11-26T23:00:00+00:00"))
        naca = ("From Friday, November 13, through Sunday, November 15, 2026, "
                "the event runs daily from 8 a.m. to 8 p.m.")
        self.assertEqual(gd._schedule(date(2026, 11, 14), naca)[0].hour, 13)
        self.assertIsNone(gd._schedule(date(2026, 11, 16), naca))

    def test_ceremony_and_camp_hours_do_not_use_doors_or_dropoff(self):
        ceremony = "Thursday, November 19, 2026. Doors open at 6 p.m., ceremony from 7 p.m. to 9:30 p.m."
        camp = "Friday, November 27, 2026: camp from 9 a.m. to noon, drop-off at 8:30 a.m."
        self.assertEqual(gd._schedule(date(2026, 11, 19), ceremony)[0].isoformat(), "2026-11-20T00:00:00+00:00")
        self.assertEqual(gd._schedule(date(2026, 11, 27), camp)[1].isoformat(), "2026-11-27T17:00:00+00:00")
        self.assertIsNone(gd._schedule(date(2026, 11, 18), "November 18, 2026 all night long. More information to follow."))

    def test_exact_primary_occurrence_is_held_but_new_date_is_not(self):
        url = gd.URL + "/diy-holiday-craft-fair"
        title = "DIY Holiday Craft Fair"
        address = "1 North Tennessee Ave. Atlantic City, NJ 08401"
        manifest = dict(title=title, date="2026-11-21", location=address, category="COMMUNITY", image=None)
        body = "Join the DIY Holiday Craft Fair on Saturday, November 21, from 1:00 PM to 4:00 PM. All craft supplies are free."
        with patch.object(gd, "record", side_effect=row_record):
            row, reason = gd._detail(url, manifest, detail(title, body, address=address), NOW)
            self.assertIsNone(row)
            self.assertEqual(reason, "already_covered_primary_occurrence")
            changed = {**manifest, "date": "2026-11-22"}
            row, reason = gd._detail(url, changed, detail(title, body.replace("21", "22"), "Nov 22, 2026", address), NOW)
        self.assertIsNotNone(row)
        self.assertIsNone(reason)

    def test_exact_venue_points_and_intersection_resolution(self):
        place = gd._location("123 South Indiana Avenue", "Event at The Claridge Hotel.")
        self.assertEqual(gd.VENUE_POINTS[place], (39.3575555, -74.4317609))
        self.assertIsNone(gd._location("999 South Indiana Avenue", "Event at The Claridge Hotel."))
        skate = gd._location("Massachusetts and Melrose Avenues", "Join us at Uptown Skatepark.")
        self.assertEqual(skate, ("Uptown Skatepark", "201 N Massachusetts Avenue, Atlantic City, NJ 08401"))
        self.assertIsNone(gd._location("Massachusetts and Melrose Avenues", "Unknown venue."))
        self.assertIsNone(gd._location("Atlantic Avenue", "The parade ends at O'Donnell Park."))
        for name, street, point in (
            ("Atlantic City PAL Building", "250 N New York Avenue", (39.3653551, -74.4321693)),
            ("Sister Jean's Kitchen", "108 N Pennsylvania Avenue", (39.361843, -74.423196)),
            ("Spanish Community Center", "3900 Ventnor Avenue", (39.350256, -74.457095)),
            ("Carnegie Center", "35 S Dr Martin Luther King Boulevard", (39.3593871, -74.4307969)),
            ("Pop Lloyd Stadium", "1200 N Doctor Martin Luther King Jr Boulevard", (39.3725712, -74.4398345)),
        ):
            exact = (name, street + ", Atlantic City, NJ 08401")
            self.assertEqual(gd.VENUE_POINTS[exact], point)
            self.assertIsNone(gd.VENUE_POINTS.get(("Different venue", exact[1])))
            self.assertIsNone(gd.VENUE_POINTS.get((name, "999 Unknown Avenue, Atlantic City, NJ 08401")))

    def test_reviewed_carnegie_and_stadium_points_preserve_full_details(self):
        body = ("Saturday, November 21, 2026 from 1 p.m. to 4 p.m. "
                + "Complete event and participant details are retained. " * 100 + "Final paragraph.")
        for street, point in (
            ("35 S Dr Martin Luther King Boulevard", (39.3593871, -74.4307969)),
            ("1200 N Doctor Martin Luther King Jr Boulevard", (39.3725712, -74.4398345)),
        ):
            item = dict(title="Community event", date="2026-11-21", location=street,
                        category="COMMUNITY", image=None)
            with patch.object(gd, "record", side_effect=row_record):
                row, reason = gd._detail(gd.URL + "/community-event", item,
                                         detail("Community event", body, address=street), NOW)
            self.assertIsNone(reason)
            self.assertEqual((row["lat"], row["lng"]), point)
            self.assertEqual(row["description"], body)
            self.assertGreater(len(row["description"]), 5000)
            self.assertEqual(row["starts_at"], "2026-11-21T18:00:00+00:00")
            self.assertEqual(row["ends_at"], "2026-11-21T21:00:00+00:00")

    def test_reviewed_school_conflict_holds_only_exact_occurrence(self):
        url = gd.URL + "/south-jersey-gas-energy-assistance-event"
        title = "South Jersey Gas Energy Assistance Event"
        address = "New York Avenue School, 201 North Pennsylvania Avenue"
        body = ("Thursday, November 19, 2026, from 9 a.m. to 1 p.m. at New York Avenue School, "
                "201 North Pennsylvania Avenue. Bring required energy assistance documents.")
        manifest = dict(title=title, date="2026-11-19", location=address, category="EDUCATIONAL", image=None)
        with patch.object(gd, "record", side_effect=row_record):
            row, reason = gd._detail(url, manifest, detail(title, body, "Nov 19, 2026", address), NOW)
            self.assertIsNone(row)
            self.assertEqual(reason, "publisher_venue_address_conflict")
            changed = {**manifest, "date": "2026-11-20"}
            row, reason = gd._detail(url, changed, detail(title, body.replace("19", "20"), "Nov 20, 2026", address), NOW)
            self.assertIsNotNone(row)
            self.assertIsNone(reason)

    def test_pennsylvania_school_street_uses_district_confirmed_venue_name(self):
        self.assertEqual(
            gd._location("201 N. Pennsylvania Ave.", "Pennsylvania Avenue School community event."),
            ("Pennsylvania Avenue School", "201 North Pennsylvania Avenue, Atlantic City, NJ 08401"),
        )

    def test_blank_and_oversized_body_do_not_become_card_excerpt(self):
        url = gd.URL + "/test-event"
        item = dict(title="Test", date="2026-11-21", location="108 N. Pennsylvania Ave.", category="COMMUNITY", image=None)
        row, reason = gd._detail(url, item, detail("Test", "<p>\u200d</p>"), NOW)
        self.assertIsNone(row)
        self.assertEqual(reason, "full_description_missing")
        with self.assertRaisesRegex(ValueError, "description_limit"):
            gd._detail(url, item, detail("Test", "x" * 12001), NOW)

    def test_changed_or_failed_details_do_not_advance_checkpoint(self):
        body = "Saturday, November 21, 2026 from 11 a.m. to 1 p.m. All are welcome."
        pages = {gd.URL: listing(card("one", "One") + card("two", "Two")),
                 gd.URL + "/one": detail("One", body), gd.URL + "/two": detail("Two", body)}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(gd, "record", side_effect=row_record):
            first = gd.collect_chunk(SOURCE, fetch, now=NOW, max_details=1)
            before = deepcopy(first["checkpoint"])
            pages[gd.URL + "/two"] = detail("Two", body, "Nov 22, 2026")
            with self.assertRaisesRegex(ValueError, "schedule_changed"):
                gd.collect_chunk(SOURCE, fetch, now=NOW, checkpoint=first["checkpoint"])
        self.assertEqual(first["checkpoint"], before)
        invalid = {**before, "cursor": 2}
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            gd.collect_chunk(SOURCE, fetch, now=NOW, checkpoint=invalid)

    def test_changed_manifest_resets_saved_details(self):
        body = "Saturday, November 21, 2026 from 11 a.m. to 1 p.m. All are welcome."
        pages = {gd.URL: listing(card("one", "One") + card("two", "Two")),
                 gd.URL + "/one": detail("One", body), gd.URL + "/two": detail("Two", body)}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(gd, "record", side_effect=row_record):
            first = gd.collect_chunk(SOURCE, fetch, now=NOW, max_details=1)
            pages[gd.URL] = listing(card("one", "Updated") + card("two", "Two"))
            pages[gd.URL + "/one"] = detail("Updated", body)
            second = gd.collect_chunk(SOURCE, fetch, now=NOW, checkpoint=first["checkpoint"], max_details=1)
        self.assertEqual(second["checkpoint"]["cursor"], 1)
        self.assertEqual(second["checkpoint"]["events"][0]["title"], "Updated")
        self.assertNotEqual(first["checkpoint"]["manifest_hash"], second["checkpoint"]["manifest_hash"])

    def test_identity_and_pagination_are_scoped(self):
        for value in ("https://evil.example/events/test", gd.URL + "/test?admin=1", gd.URL + "/../test",
                      gd.URL + "/%2e%2e", "https://www.greatdayatlanticcity.com:443/events/test"):
            self.assertFalse(gd.event_url(gd.KEY, value))
        with self.assertRaisesRegex(ValueError, "unregistered"):
            gd.collect_chunk({**SOURCE, "feed_url": "https://evil.example"}, Mock(), now=NOW)
        fetch = Mock(return_value=listing(card("one", "One"), "https://evil.example/events?page=2"))
        with self.assertRaisesRegex(ValueError, "pagination_invalid"):
            gd.collect_chunk(SOURCE, fetch, now=NOW)
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
