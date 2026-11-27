from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from roomquest import new_york_arts as ny
from roomquest.mapsee_adapter import timestamp


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ny.SOURCES[key][0], kind="html", platform_adapter="html", timezone=ny.ZONE)


def fake_record(title, start, end, venue, address, city, url, identity, category="", lat=None, lng=None, tz=None, **kwargs):
    return dict(id=str(identity), title=title, starts_at=timestamp(start, tz).isoformat(),
                ends_at=timestamp(end, tz).isoformat() if end else None, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, lat=lat, lng=lng,
                reason=None if lat is not None else "missing_verified_venue_geo", category_hint=category)


def event(key=ny.CMOM, identity=1234, body="Build a collage and explore color together.", venue=None, **overrides):
    item = dict(id=identity, status="publish", title="Family art workshop", description=body,
                start_date="2026-11-18 10:00:00", end_date="2026-11-18 11:00:00",
                utc_start_date="2026-11-18 15:00:00", utc_end_date="2026-11-18 16:00:00",
                timezone=ny.ZONE, all_day=False, hide_from_listings=False, is_virtual=False,
                url="https://" + ny.ALLOWED_HOSTS[key][0] + "/event/family-art/",
                categories=[{"name": "Drop-in Programs"}], venue=venue or [])
    item.update(overrides)
    return item


def payload(*events, **values):
    return json.dumps(dict(events=list(events), total_pages=1, **values))


def square_link(prefix, title="Family workshop", location="34-41 137th Street, Queens, NY, 11354, United States"):
    return (f'<a class="{prefix}-meta-export-google" href="http://www.google.com/calendar/event?'
            f'action=TEMPLATE&amp;text={title}&amp;dates=20261212T160000Z/20261212T200000Z&amp;location={location}">Calendar</a>')


def square_listing():
    return ('<div class="eventlist"><article class="eventlist-event eventlist-event--upcoming">'
            '<h1><a class="eventlist-title-link" href="/events/family-workshop">Family workshop</a></h1>'
            + square_link("eventlist") + '<div class="eventlist-excerpt">Truncated excerpt.</div>'
            '</article></div>')


def square_detail(body):
    url = "https://www.lewislatimerhouse.org/events/family-workshop"
    return (f'<link rel="canonical" href="{url}"><h1 class="eventitem-title">Family workshop</h1>'
            + square_link("eventitem") + '<div class="eventitem-meta-address">Lewis Latimer House 34-41 137th Street Queens, NY, 11354</div>'
            '<div class="eventitem-column-content"><div class="sqs-layout" id="item-6ae7acec920c5d3ed2c4e6c6">'
            f'<p>{body}</p><script>bad();</script><style>.bad{{}}</style></div></div>')


def bazaar_listing(count=7):
    return "".join(f'<a href="https://grandbazaarnyc.org/events/market-{i}/"><h3>Market {i}</h3><p>Excerpt...</p></a>' for i in range(count))


def bazaar_detail(index=0, body="Meet local makers, find vintage treasures, and enjoy neighborhood food."):
    return (f'<h1>Market {index}</h1><div class="content"><p>{body}</p>'
            '<div class="addeventatc"><span class="start">11/22/2026 10:00 am</span>'
            '<span class="end">11/22/2026 5:00 pm</span><span class="timezone">America/New_York</span>'
            f'<span class="title">Market {index}</span><span class="description">TRUNCATED EXCERPT</span>'
            '<span class="location">Grand Bazaar NYC, 100 West 77th St., NY, NY 10024, (At Columbus Avenue)</span></div></div>')


class NewYorkArtsTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch("roomquest.mapsee_adapter.record", side_effect=fake_record),
                        patch.object(ny, "record", side_effect=fake_record)]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in self.patches])

    def collect(self, key, data):
        return ny.collect(source(key), Mock(return_value=data), now=NOW)

    def test_complete_native_prose_survives_legacy_preview_limit(self):
        body = "Full workshop details. " * 150 + "Bring &lt;your art&gt; &amp; friends."
        rows = self.collect(ny.CMOM, payload(event(body='<p>' + body + '</p><script>not prose</script>')))
        self.assertEqual(len(rows), 1)
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertTrue(rows[0]["description"].endswith("Bring <your art> & friends."))
        self.assertNotIn("not prose", rows[0]["description"])

    def test_blank_and_oversize_are_held_without_invented_or_clipped_text(self):
        data = payload(event(identity=1, body=""), event(identity=2, body="x" * 12001), event(identity=3, body="x" * 12000))
        with self.assertLogs(ny.log, level="WARNING"):
            rows = self.collect(ny.CMOM, data)
        self.assertEqual([row["id"] for row in rows], ["3"])
        self.assertEqual(len(rows[0]["description"]), 12000)

    def test_cmoms_reviewed_room_keeps_room_name_and_exact_street(self):
        rows = self.collect(ny.CMOM, payload(event(venue={"id": 1006, "venue": "PlayWorks"})))
        self.assertEqual(rows[0]["venue_name"], "Children's Museum of Manhattan (PlayWorks)")
        self.assertEqual(rows[0]["venue_address"], "212 West 83rd Street, New York, NY 10024")
        with self.assertLogs(ny.log, level="WARNING"):
            unknown = self.collect(ny.CMOM, payload(event(venue={"id": 2222, "venue": "Off-site school"})))
        self.assertEqual(unknown, [])

    def test_event_content_uses_original_facts_not_reviewed_source_enrichment(self):
        item = event(venue={"id": 1006, "venue": "PlayWorks"})
        first = self.collect(ny.CMOM, payload(item))[0]
        facts = first["collector_event_content_v1"]["facts"]
        self.assertEqual(facts["venue_name"], "PlayWorks")
        self.assertNotIn("venue_address", facts)
        self.assertEqual(first["venue_name"], "Children's Museum of Manhattan (PlayWorks)")
        self.assertEqual(first["venue_address"], "212 West 83rd Street, New York, NY 10024")

        renamed_source = source(ny.CMOM)
        renamed_source["publisher_name"] = "A provider label that changed"
        second = ny.collect(renamed_source, Mock(return_value=payload(item)), now=NOW)[0]
        self.assertEqual(second["collector_event_content_v1"], first["collector_event_content_v1"])

        changed = event(venue={"id": 1006, "venue": "PlayWorks"},
                        body="The publisher changed this event's own details.")
        third = self.collect(ny.CMOM, payload(changed))[0]
        self.assertNotEqual(third["collector_event_content_v1"], first["collector_event_content_v1"])

    def test_closed_virtual_and_members_only_not_assigned_museum_address(self):
        data = payload(event(identity=1, title="Museum Closed", body="", all_day=True),
                       event(identity=2, title="Virtual art workshop"),
                       event(identity=3, title="Members-only event"), event(identity=4))
        self.assertEqual([r["id"] for r in self.collect(ny.CMOM, data)], ["4"])

    def test_poster_virtual_category_works_when_native_virtual_flag_is_false(self):
        virtual = event(ny.POSTER, categories=[{"name": "Virtual"}], title="Verbal description tour")
        onsite = event(ny.POSTER, identity=2, categories=[{"name": "In-Person"}], title="Verbal description tour")
        rows = self.collect(ny.POSTER, payload(virtual, onsite))
        self.assertEqual([r["id"] for r in rows], ["2"])
        self.assertEqual(rows[0]["venue_address"], "119 West 23rd Street, New York, NY 10011")

    def test_staten_childrens_building_comma_does_not_break_address(self):
        venue = dict(id=82, venue="Staten Island Children&#8217;s Museum", address="1000 Richmond Terrace, Building M",
                     city="Staten Island", state="NY", zip="10301", geo_lat=40.644743798098, geo_lng=-74.102321811388)
        row = self.collect(ny.SI_CHILDREN, payload(event(ny.SI_CHILDREN, venue=venue)))[0]
        self.assertEqual(row["venue_address"], "1000 Richmond Terrace Building M, Staten Island, NY 10301")
        self.assertEqual((row["lat"], row["lng"]), (40.644743798098, -74.102321811388))
        self.assertIsNone(row["reason"])

    def test_queens_hyphenated_street_and_offsite_park_are_preserved(self):
        venue = dict(id=4279, venue="Queens County Farm Museum", address="73-50 Little Neck Parkway", city="Queens", state="NY", zip="11004")
        row = self.collect(ny.QUEENS_FARM, payload(event(ny.QUEENS_FARM, venue=venue)))[0]
        self.assertEqual(row["venue_address"], "73-50 Little Neck Parkway, Queens, NY 11004")
        self.assertEqual((row["lat"], row["lng"]), (40.748426, -73.720186))
        self.assertEqual(row["location_provenance"], "reviewed_nyc_pad_address_point")
        self.assertIsNone(row["reason"])
        self.assertIsNone(ny.reviewed_venue_location(ny.QUEENS_FARM, row["venue_name"], "73-70 Little Neck Parkway, Queens, NY 11004"))
        park = self.collect(ny.SI_MUSEUM, payload(event(ny.SI_MUSEUM, venue={"id": 4741, "venue": "Great Kills Park"})))[0]
        self.assertEqual(park["venue_address"], "3270 Hylan Boulevard, Staten Island, NY 10306")
        self.assertIn("park entrance", park["venue_name"])
        self.assertNotIn("Richmond Terrace", park["venue_address"])

    def test_moving_image_exact_pad_point_never_follows_an_offsite_address(self):
        row = self.collect(ny.MOVING_IMAGE, payload(event(ny.MOVING_IMAGE, categories=[{"name": "Screening"}])))[0]
        self.assertEqual((row["lat"], row["lng"]), (40.756305, -73.923916))
        self.assertEqual(row["venue_address"], "36-01 35th Avenue, Astoria, NY 11106")
        self.assertEqual(row["location_provenance"], "reviewed_nyc_pad_address_point")
        self.assertIsNone(row["reason"])
        self.assertIsNone(ny.reviewed_venue_location(ny.MOVING_IMAGE, "Off-site cinema", row["venue_address"]))
        self.assertIsNone(ny.reviewed_venue_location(ny.MOVING_IMAGE, row["venue_name"], "35-01 35th Avenue, Astoria, NY 11106"))

    def test_remaining_museum_point_and_park_approximation_are_venue_bound(self):
        museum = dict(id=28, venue="Staten Island Museum at Snug Harbor", address="1000 Richmond Terrace, Building A",
                      city="Staten Island", state="NY", zip="10301")
        row = self.collect(ny.SI_MUSEUM, payload(event(ny.SI_MUSEUM, venue=museum)))[0]
        self.assertEqual((row["lat"], row["lng"]), (40.6444768, -74.1027563))
        self.assertEqual(row["venue_address"], "1000 Richmond Terrace Building A, Staten Island, NY 10301")
        park = dict(id=5184, venue="Wolfe&#8217;s Pond Park", address="420 Cornelia Ave.", city="Staten Island", state="NY", zip="10312")
        body = "Meet in the parking lot near the Parks Dept. buildings."
        row = self.collect(ny.SI_MUSEUM, payload(event(ny.SI_MUSEUM, venue=park, body=body)))[0]
        self.assertEqual(row["venue_name"], "Wolfe’s Pond Park (approximate meeting point)")
        self.assertEqual(row["venue_address"], "420 Cornelia Ave., Staten Island, NY 10312")
        self.assertEqual((row["lat"], row["lng"]), (40.51806, -74.19006))
        self.assertEqual(row["description"], body)
        self.assertEqual(row["location_provenance"], "reviewed_named_park_approximate_meeting_point")
        self.assertIsNone(ny.reviewed_venue_location(ny.SI_MUSEUM, "Wolfe’s Pond Park", row["venue_address"]))

    def test_columbus_circle_point_does_not_replace_published_dumbo_venue(self):
        self.assertEqual(ny.reviewed_venue_location(ny.POWERHOUSE, "Powerhouse at Columbus Circle",
                         "10 Columbus Circle #304, New York, NY 10019"), (40.768554, -73.983181))
        self.assertIsNone(ny.reviewed_venue_location(ny.POWERHOUSE, "POWERHOUSE Arena", "28 Adams Street, Brooklyn, NY 11201"))
        self.assertIsNone(ny.reviewed_venue_location(ny.POWERHOUSE, "Powerhouse at Columbus Circle",
                          "10 Columbus Circle #303, New York, NY 10019"))

    def test_unknown_or_conflicting_timezone_fails_instead_of_shifting_clock(self):
        for changes in ({"timezone": "UTC+0"}, {"utc_start_date": "2026-11-18 10:00:00"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "timezone_changed|schedule_conflict"):
                self.collect(ny.CMOM, payload(event(**changes)))

    def test_pagination_rebuilds_registered_endpoint_and_detects_duplicate_change(self):
        pages = [payload(event(identity=1), total=2, next_rest_url="https://untrusted.example/", **{}),
                 payload(event(identity=2))]
        first = json.loads(pages[0]); first["total_pages"] = 2; pages[0] = json.dumps(first)
        fetch = Mock(side_effect=pages)
        rows = ny.collect(source(ny.CMOM), fetch, now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(urlsplit(call.args[0]).netloc == "cmom.org" for call in fetch.call_args_list))
        self.assertEqual(parse_qs(urlsplit(fetch.call_args_list[1].args[0]).query)["page"], ["2"])
        with self.assertRaisesRegex(ValueError, "conflicting_occurrence"):
            self.collect(ny.CMOM, payload(event(), event(body="A changed duplicate.")))

    def test_wrong_source_contract_never_fetches(self):
        for field, value in (("feed_url", "https://evil.example"), ("kind", "json"), ("timezone", "America/Chicago"), ("source_key", "unknown")):
            profile = source(ny.CMOM); profile[field] = value; fetch = Mock()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unregistered"):
                ny.collect(profile, fetch, now=NOW)
            fetch.assert_not_called()

    def test_squarespace_fetches_permitted_html_full_body_and_own_venue(self):
        tail = "Complete native details. " * 130 + "THE LAST PARAGRAPH."
        fetch = Mock(side_effect=[square_listing(), square_detail(tail)])
        row = ny.collect(source(ny.LATIMER), fetch, now=NOW)[0]
        self.assertGreater(len(row["description"]), 2000)
        self.assertTrue(row["description"].endswith("THE LAST PARAGRAPH."))
        self.assertNotIn("Truncated excerpt", row["description"])
        self.assertTrue(all("format=" not in call.args[0] for call in fetch.call_args_list))
        self.assertEqual(row["venue_address"], "34-41 137th Street, Flushing, NY 11354")
        facts = row["collector_event_content_v1"]["facts"]
        self.assertEqual(facts["venue_address"], "34-41 137th Street, Queens, NY, 11354, United States")
        self.assertNotIn("venue_name", facts)

    def test_squarespace_offsite_does_not_inherit_host_address(self):
        fetch = Mock(side_effect=[square_listing(), square_detail("Bring your family.").replace("Lewis Latimer House 34-41 137th Street", "Queens Museum Flushing Meadows Corona Park")])
        with self.assertLogs(ny.log, level="WARNING"):
            self.assertEqual(ny.collect(source(ny.LATIMER), fetch, now=NOW), [])

    def test_bazaar_uses_complete_paragraph_not_export_excerpt(self):
        row = ny._bazaar_detail("https://grandbazaarnyc.org/events/market-0/", bazaar_detail(body="A " * 1800 + "Complete ending."), NOW)
        self.assertTrue(row["description"].endswith("Complete ending."))
        self.assertNotIn("TRUNCATED EXCERPT", row["description"])
        self.assertEqual(row["venue_address"], "100 West 77th Street, New York, NY 10024")

    def test_checkpoint_publishes_only_complete_batch_and_reuses_completion(self):
        def fetch(url, accept):
            if url == ny.SOURCES[ny.BAZAAR][0]:
                return bazaar_listing()
            return bazaar_detail(int(urlsplit(url).path.rstrip("/").rsplit("-", 1)[1]))
        callback = Mock(side_effect=fetch)
        first = ny.collect_chunk(source(ny.BAZAAR), callback, now=NOW)
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        self.assertEqual(first["checkpoint"]["cursor"], 3)
        second = ny.collect_chunk(source(ny.BAZAAR), callback, checkpoint=first["checkpoint"], now=NOW)
        final = ny.collect_chunk(source(ny.BAZAAR), callback, checkpoint=second["checkpoint"], now=NOW)
        self.assertTrue(final["complete"])
        self.assertEqual(len(final["events"]), 7)
        no_fetch = Mock(side_effect=AssertionError("complete checkpoint must not fetch"))
        retry = ny.collect_chunk(source(ny.BAZAAR), no_fetch, checkpoint=final["checkpoint"], now=NOW)
        self.assertEqual(retry["events"], final["checkpoint"]["events"])

    def test_checkpoint_rejects_tampered_description_location_and_cross_host(self):
        callback = lambda url, accept: bazaar_listing(4) if url == ny.SOURCES[ny.BAZAAR][0] else bazaar_detail(int(urlsplit(url).path.rstrip("/").rsplit("-", 1)[1]))
        initial = ny.collect_chunk(source(ny.BAZAAR), callback, now=NOW)["checkpoint"]
        for field, value in (("venue_address", "999 Elsewhere Street, New York, NY 10001"), ("description", "x" * 12001), ("lat", 40.7), ("event_url", "https://evil.example/events/market-0/")):
            data = deepcopy(initial); data["events"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ny.collect_chunk(source(ny.BAZAAR), Mock(), checkpoint=data, now=NOW)

    def test_photo_and_event_scope_cannot_cross_publisher(self):
        self.assertTrue(ny.event_url(ny.CMOM, "https://cmom.org/event/story-blanket-collage/2026-11-15/1/"))
        self.assertFalse(ny.event_url(ny.CMOM, "https://cmom.org.evil.example/event/family-art/"))
        self.assertFalse(ny.event_url(ny.CMOM, "https://cmom.org/event/family-art/?redirect=elsewhere"))
        self.assertIsNone(ny.photo_url(ny.POSTER, "https://unreviewed.example/image.jpg"))
        self.assertIsNotNone(ny.photo_url(ny.POSTER, "https://posterhouse.org/wp-content/uploads/2026/11/art.jpg"))


if __name__ == "__main__":
    unittest.main()
