from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
import unittest
from unittest.mock import patch

from roomquest import atlantic_city_library_chamber as ac


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ac.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ac.ZONE)


def row_record(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, lat=None, lng=None)


def rss_item(title="Tai-Chi", slug="tai-chi-49", body="Inside MCPL", start="Fri, 20 Nov 2026 09:00:00 -0500", end="Fri, 20 Nov 2026 10:00:00 -0500", location="Margate City Public Library"):
    return ("<item><title>" + escape(title) + "</title><description>" + escape(body) + "</description>"
            + "<pubDate>" + start + "</pubDate><ev:endDate>" + end + "</ev:endDate>"
            + "<link>https://www.margatelibrary.org/" + slug + "</link>"
            + ("<ev:location>" + escape(location) + "</ev:location>" if location else "") + "</item>")


def rss(*items):
    return '<rss xmlns:ev="http://purl.org/rss/1.0/modules/event/"><channel><title>Upcoming Events RSS Feed</title>' + "".join(items) + "</channel></rss>"


def chamber_item(identity="1", body="A public program with full details.", location="Host<br>100 Main Street<br>Margate, NJ 08402", start="2026-11-19T17:30:00", flags="Public MemberOnly"):
    values = dict(EventID=identity, CCID="2391", Name="Public program", Slug="public-program", Status="APPROVED",
                  VisibilityFlags=flags, IsAllDayEvent="false", StartDate=start, EndDate="2026-11-19T18:30:00",
                  Description=body, LocationDesc=location)
    return "<EventDisplay>" + "".join(f"<{k}>{escape(v)}</{k}>" for k, v in values.items()) + "</EventDisplay>"


def fed_item(identity="100", **overrides):
    value = dict(id=int(identity), url=f"https://jewishbytheshore.org/event/public-program-{identity}/",
                 status="publish", title="Public cultural program", description="<p>Everyone is welcome.</p>",
                 timezone=ac.ZONE, start_date="2026-11-19 17:00:00", end_date="2026-11-19 18:00:00",
                 utc_start_date="2026-11-19 22:00:00", utc_end_date="2026-11-19 23:00:00",
                 venue=dict(venue="Katz JCC", address="501 N Jerome Avenue", city="Margate City", state="NJ", zip="08402"))
    value.update(overrides)
    return value


def fed_page(items, page=1, total=None):
    total = len(items) if total is None else total
    return json.dumps(dict(events=items, total=total, total_pages=(total + 49) // 50,
                           rest_url=ac.SOURCES[ac.FED][0] + f"?page={page}&per_page=50"))


def jfs_item(slug="musical-connections", **kwargs):
    item = {"@type": "Event", "url": f"https://www.jfsatlantic.org/events/{slug}/",
            "name": "Musical Connections", "description": "Truncated teaser...",
            "startDate": "2026-11-17T10:30:00-05:00", "endDate": "2026-11-17T12:00:00-05:00"}
    item.update(kwargs)
    return item


def jfs_html(items, body=None):
    return ('<div class="tribe-events"></div><script type="application/ld+json">' + json.dumps(items) + '</script>'
            + ('<div class="tribe-events-single-event-description">' + body + '</div>' if body is not None else ''))


class AtlanticLibraryChamberTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ac, "record", side_effect=row_record)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rss_closures_override_recurring_library_dates(self):
        raw = rss(rss_item(), rss_item(slug="closed", title="Library Closed- Holiday", body="",
            start="Fri, 20 Nov 2026 00:00:00 -0500", end="Fri, 20 Nov 2026 00:00:00 -0500"))
        self.assertEqual(ac._margate(raw, NOW), [])

    def test_library_and_explicit_pavilion_venues_stay_distinct(self):
        rows = ac._margate(rss(rss_item(), rss_item(slug="tai-chi-17", body="Starting Wednesday Oct.7 2026, Tai Chi will be moved to inside the Bloom Pavilion.")), NOW)
        self.assertEqual({r["venue_address"] for r in rows}, {ac.LIBRARY[1], ac.BLOOM[1]})
        self.assertTrue(all(r["lat"] is None and r["lng"] is None for r in rows))

    def test_closure_later_midnight_does_not_suppress_reopening_date(self):
        raw = rss(rss_item(), rss_item(slug="closed", title="Library Closed- Holiday", body="",
            start="Thu, 19 Nov 2026 00:00:00 -0500", end="Fri, 20 Nov 2026 00:00:00 -0500"))
        self.assertEqual(len(ac._margate(raw, NOW)), 1)

    def test_blank_film_description_and_tbd_clock_remain_held(self):
        raw = rss(rss_item(body="&nbsp;"), rss_item(slug="time-tbd", title="Time TBD: Film", body="Contact the library for time."))
        self.assertEqual(ac._margate(raw, NOW), [])

    def test_explicit_library_room_resolves_absent_rss_location(self):
        body = "Story Time held every Wednesday from 11:30AM-12:00PM in the Children's Room at the library."
        rows = ac._margate(rss(rss_item(body=body, location=None)), NOW)
        self.assertEqual(rows[0]["venue_address"], ac.LIBRARY[1])
        self.assertEqual(rows[0]["description"], body)

    def test_reversed_publisher_end_is_not_invented_overnight(self):
        self.assertEqual(ac._margate(rss(rss_item(end="Fri, 20 Nov 2026 08:00:00 -0500")), NOW), [])

    def test_chamber_public_visibility_accepts_nonmember_ticket_program(self):
        rows = ac._chamber("<ArrayOfEventDisplay>" + chamber_item(flags="ChamberInternal Public MemberOnly Featured") + "</ArrayOfEventDisplay>", NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["venue_address"], "100 Main Street, Margate, NJ 08402")

    def test_chamber_native_full_body_and_suite_preserved(self):
        body = "<p>Event information and participation instructions. </p>" * 100 + "<p>Final sentence.</p>"
        raw = "<ArrayOfEventDisplay>" + chamber_item(body=body, location="Dave &amp; Buster's<br>2120 Atlantic Avenue, Suite 912<br>Atlantic City, NJ 08401<p>Parking elsewhere.</p>") + "</ArrayOfEventDisplay>"
        row = ac._chamber(raw, NOW)[0]
        self.assertEqual(row["description"], ac.narrative(body))
        self.assertGreater(len(row["description"]), 4000)
        self.assertEqual(row["venue_address"], "2120 Atlantic Avenue Suite 912, Atlantic City, NJ 08401")

    def test_chamber_stale_weekday_copy_is_held(self):
        raw = "<ArrayOfEventDisplay>" + chamber_item(body="Wednesday, November 19 at 5:30 PM. Public program.") + "</ArrayOfEventDisplay>"
        self.assertEqual(ac._chamber(raw, NOW), [])  # November 19, 2026 is Thursday.

    def test_public_religious_program_retained_private_and_virtual_excluded(self):
        row, reason = ac._fed_item(fed_item(title="Public Shabbat program"), NOW)
        self.assertIsNotNone(row)
        self.assertIsNone(reason)
        self.assertIsNone(ac._fed_item(fed_item(description="This event is invite only."), NOW)[0])
        self.assertIsNone(ac._fed_item(fed_item(venue=dict(venue="Zoom")), NOW)[0])

    def test_federation_utc_conflict_and_unresolved_venue_are_held(self):
        self.assertEqual(ac._fed_item(fed_item(utc_start_date="2026-11-19 21:00:00"), NOW)[1], "publisher_schedule_conflict")
        self.assertEqual(ac._fed_item(fed_item(venue=[]), NOW)[1], "publisher_venue_unresolved")

    def test_federation_pagination_publishes_only_after_complete(self):
        first_items = [fed_item(str(i)) for i in range(1, 51)]
        first = ac.collect_chunk(source(ac.FED), lambda *args: fed_page(first_items, total=51), now=NOW)
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        second = ac.collect_chunk(source(ac.FED), lambda *args: fed_page([fed_item("51")], page=2, total=51), checkpoint=first["checkpoint"], now=NOW)
        self.assertFalse(second["complete"])
        self.assertEqual(second["events"], [])
        third = ac.collect_chunk(source(ac.FED), lambda *args: fed_page(first_items, total=51), checkpoint=second["checkpoint"], now=NOW)
        fourth = ac.collect_chunk(source(ac.FED), lambda *args: fed_page([fed_item("51")], page=2, total=51), checkpoint=third["checkpoint"], now=NOW)
        self.assertTrue(fourth["complete"])
        self.assertEqual(len(fourth["events"]), 51)
        self.assertEqual(first["checkpoint"]["cursor"], 1)

    def test_same_total_changed_page_discards_snapshot_before_publication(self):
        first = ac.collect_chunk(source(ac.FED), lambda *args: fed_page([fed_item()]), now=NOW)
        changed = fed_item(description="A changed complete body.")
        second = ac.collect_chunk(source(ac.FED), lambda *args: fed_page([changed]), checkpoint=first["checkpoint"], now=NOW)
        self.assertFalse(second["complete"])
        self.assertEqual(second["events"], [])
        self.assertEqual(second["checkpoint"]["cursor"], 0)
        self.assertEqual(second["checkpoint"]["events"], [])

    def test_completed_federation_snapshot_survives_staging_retry(self):
        fetch = lambda *args: fed_page([fed_item()])
        first = ac.collect_chunk(source(ac.FED), fetch, now=NOW)
        complete = ac.collect_chunk(source(ac.FED), fetch, checkpoint=first["checkpoint"], now=NOW)
        self.assertTrue(complete["complete"])
        def no_network(*args):
            self.fail("Completed, validated checkpoint should be reused for a staging retry")
        retry = ac.collect_chunk(source(ac.FED), no_network, checkpoint=complete["checkpoint"], now=NOW)
        self.assertEqual(retry["events"], complete["events"])

    def test_repeated_api_page_is_rejected(self):
        items = [fed_item(str(i)) for i in range(1, 51)]
        first = ac.collect_chunk(source(ac.FED), lambda *args: fed_page(items, total=51), now=NOW)
        with self.assertRaisesRegex(ValueError, "pagination_identity_changed"):
            ac.collect_chunk(source(ac.FED), lambda *args: fed_page([fed_item("1")], page=1, total=51), checkpoint=first["checkpoint"], now=NOW)

    def test_checkpoint_injected_gps_or_cursor_is_rejected(self):
        items = [fed_item(str(i)) for i in range(1, 51)]
        first = ac.collect_chunk(source(ac.FED), lambda *args: fed_page(items, total=51), now=NOW)
        for field in ("gps", "cursor"):
            tampered = deepcopy(first["checkpoint"])
            if field == "gps":
                tampered["events"][0]["lat"] = 39.3
            else:
                tampered["cursor"] = 2
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ac.collect_chunk(source(ac.FED), lambda *args: "{}", checkpoint=tampered, now=NOW)

    def test_jfs_full_detail_and_actual_named_venue_replace_excerpt(self):
        item = jfs_item()
        body = "<p>Everyone is welcome. Attend in-person at Shirat Hayam, 700 North Swarthmore Avenue, Ventnor.</p>" + "<p>All participation instructions. </p>" * 100
        fetch = lambda url, accept: jfs_html([item], body if url == item["url"] else None)
        row = ac.collect_chunk(source(ac.JFS), fetch, now=NOW)["events"][0]
        self.assertEqual(row["description"], ac.narrative(body))
        self.assertNotIn("Truncated teaser", row["description"])
        self.assertEqual(row["venue_address"], "700 North Swarthmore Avenue, Ventnor City, NJ 08406")

    def test_jfs_durable_detail_chunk_never_stages_partial(self):
        items = [jfs_item("one"), jfs_item("two")]
        body = "Attend in-person at Shirat Hayam, 700 North Swarthmore Avenue, Ventnor. Public program."
        def fetch(url, accept):
            return jfs_html(items) if url == ac.SOURCES[ac.JFS][0] else jfs_html([next(i for i in items if i["url"] == url)], body)
        first = ac.collect_chunk(source(ac.JFS), fetch, now=NOW, max_details=1)
        self.assertEqual(first["events"], [])
        second = ac.collect_chunk(source(ac.JFS), fetch, now=NOW, max_details=1, checkpoint=first["checkpoint"])
        self.assertTrue(second["complete"])
        self.assertEqual(len(second["events"]), 2)

    def test_foreign_source_and_event_urls_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ac.collect({**source(ac.MARGATE), "feed_url": "https://example.com/"}, lambda *a: "")
        self.assertFalse(ac.event_url(ac.FED, "https://jewishbytheshore.org.evil.example/event/foo/"))
        self.assertFalse(ac.event_url(ac.JFS, "https://www.jfsatlantic.org/events/foo/?redirect=1"))


if __name__ == "__main__":
    unittest.main()
