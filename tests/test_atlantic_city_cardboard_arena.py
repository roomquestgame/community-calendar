from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_cardboard_arena as c


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)
SOURCE = {"source_key": c.KEY, "feed_url": c.FEED_URL, "kind": "html",
          "platform_adapter": "html", "timezone": c.ZONE}
BODY = "1v1 and 2v2 Casual games. New players welcome. Learn to play and dive into the net!"


def uid(number):
    return "00000000-0000-0000-0000-" + format(number, "012x")


def native(number=1, *, body=BODY, **changes):
    start = NOW.replace(hour=23) + timedelta(days=number)
    start_text = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": uid(number), "name": "Casual Neuroscape", "public": True, "status": "published",
            "startsAt": start_text, "endsAt": (start + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ownerId": c.OWNER, "ownerType": "Establishment", "owner": {"id": c.OWNER, "name": "Cardboard Arena"},
            "configuration": {"timezone": c.ZONE, "playSetting": "inPerson", "recurring": True,
                              "recurringAmount": 15, "recurringInterval": "weekly"},
            "address": {"name": None, "address1": "15, 8th St", "address2": "", "address3": None,
                        "city": "Hammonton", "state": "NJ", "zip": "08037", "country": "US",
                        "geo": {"lat": 39.616767, "lng": -74.7754785}},
            "activities": [{"id": uid(number + 1000), "name": "Meetup", "status": "published",
                            "startsAt": start_text, "descriptionHtml": "<p>" + body + "</p>"}], **changes}


def flight(value, extra_frames=""):
    stream = '1:' + json.dumps(value) + '\n' + extra_frames
    encoded = json.dumps([1, stream]).replace("<", "\\u003c")
    return '<script>self.__next_f.push(' + encoded + ')</script>'


def store_page(owner=c.OWNER, game=c.PUBLIC_GAME):
    return flight({"params": {"storeId": owner}, "game": {"pgGame": {
        "id": game, "slug": "play", "name": "Generic Events", "isLive": True}}})


def listing(*events, **pagination):
    return json.dumps({"data": list(events), "pagination": {"activePage": 1, "nextPage": None,
        "totalPages": 1 if events else 0, "resultsThisPage": len(events), "totalResults": len(events), **pagination}})


def preview(title, start, end, venue, address, city, url, identity, *args, **kwargs):
    return {"id": identity, "title": title, "starts_at": start, "ends_at": end,
            "venue_name": venue, "venue_address": address, "venue_city": city, "event_url": url,
            "lat": kwargs.get("lat"), "lng": kwargs.get("lng")}


def callbacks(events):
    pages = {c.FEED_URL: store_page(), **{"https://play.carde.io/events/" + e["id"]: flight({"event": e}) for e in events}}
    def fetch(url, accept):
        if accept != "text/html":
            raise AssertionError("detail requests use the normal HTML transport")
        return pages[url]
    return Mock(side_effect=fetch), Mock(return_value=listing(*events))


class CardboardArenaTest(unittest.TestCase):
    def test_source_fence_and_public_event_url(self):
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, "unregistered_cardboard"):
            c.collect_chunk({**SOURCE, "feed_url": "https://play.carde.io/stores/other"}, fetch)
        with self.assertRaisesRegex(ValueError, "publisher_checkpoint_required"):
            c.collect(SOURCE, fetch)
        with self.assertRaisesRegex(ValueError, "public_renderer_required"):
            c.collect_chunk(SOURCE, fetch)
        fetch.assert_not_called()
        self.assertTrue(c.event_url(c.KEY, "https://play.carde.io/events/" + uid(1)))
        for url in ["https://play.carde.io.evil.example/events/" + uid(1), c.FEED_URL,
                    "https://play.carde.io/events/" + uid(1) + "?other=1"]:
            self.assertFalse(c.event_url(c.KEY, url))

    def test_current_store_routing_identity_required_before_renderer(self):
        c._store_context(store_page())
        for page in [store_page(owner=uid(2)), store_page(game=uid(3)), "<html>No public calendar context</html>"]:
            fetch, render = Mock(return_value=page), Mock()
            with self.assertRaisesRegex(ValueError, "identity_changed|shape_changed"):
                c.collect_chunk(SOURCE, fetch, render_calendar=render, now=NOW)
            render.assert_not_called()

    def test_complete_pagination_is_required_and_never_sliced(self):
        for extra, error in [({"nextPage": 2, "totalPages": 2}, "source_record_limit"),
                             ({"totalResults": 2}, "manifest_incomplete"),
                             ({"activePage": True}, "shape_changed")]:
            with self.assertRaisesRegex(ValueError, error):
                c._manifest(listing(native(), **extra), NOW)
        with self.assertRaisesRegex(ValueError, "source_record_limit"):
            c._manifest(listing(*(native(i) for i in range(1, 102))), NOW)
        self.assertEqual(c._manifest(listing(), NOW), [])

    def test_private_canceled_and_outside_window_records_are_not_projected(self):
        rows = c._manifest(listing(native(1), native(2, public=False), native(3, status="canceled"), native(70)), NOW)
        self.assertEqual([row["id"] for row in rows], [uid(1)])
        self.assertEqual(len(rows), 1)  # recurringAmount=15 is never expanded.
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            c._manifest(listing(native(ownerId=uid(9))), NOW)
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            c._manifest(listing(native(), native()), NOW)

    @patch.object(c, "record", side_effect=preview)
    def test_full_long_prose_and_literal_angle_text_survive(self, _):
        text = "Read <bring a deck>.\n" + "Complete café tournament instructions. " * 90 + "Final prize condition."
        markup = ('<p>Read &lt;bring a deck&gt;.</p><span data-layout="' + 'x' * 12000
                  + '"></span><p>' + "Complete café tournament instructions. " * 90 + "Final prize condition.</p>")
        e = native()
        e["activities"][0]["descriptionHtml"] = markup
        item = c._manifest(listing(e), NOW)[0]
        row, reason = c._detail(item, flight({"event": e}))
        self.assertIsNone(reason)
        self.assertEqual(row["description"], text)
        self.assertGreater(len(row["description"]), 2000)
        e["activities"][0]["descriptionHtml"] = "x" * 12001
        with self.assertRaisesRegex(ValueError, "description_limit"):
            c._detail(item, flight({"event": e}))

    @patch.object(c, "record", side_effect=preview)
    def test_referenced_utf8_text_frame_keeps_complete_description(self, _):
        html = "<p>Café &lt;keep this instruction&gt;.</p><p>" + "Full native condition. " * 120 + "LAST.</p>"
        e = native()
        e["activities"][0]["descriptionHtml"] = "$a"
        e["address"]["geo"] = "$b"
        frames = 'a:T' + format(len(html.encode()), 'x') + ',' + html + '\n' + 'b:{"lat":39.616767,"lng":-74.7754785}\n'
        item = c._manifest(listing(native()), NOW)[0]
        row, _ = c._detail(item, flight({"event": e}, frames))
        self.assertIn("Café <keep this instruction>.", row["description"])
        self.assertTrue(row["description"].endswith("LAST."))
        self.assertGreater(len(row["description"]), 2000)

    def test_missing_description_never_uses_game_or_title_fallback(self):
        e = native(body="")
        item = c._manifest(listing(e), NOW)[0]
        row, reason = c._detail(item, flight({"event": e, "genericGameDescription": "Generic game fallback is prohibited."}))
        self.assertIsNone(row)
        self.assertEqual(reason, "description_unavailable")

    @patch.object(c, "record", side_effect=preview)
    def test_all_activity_descriptions_preserved_or_whole_event_held(self, _):
        e = native()
        e["activities"].append({"id": uid(2000), "name": "Learn to play", "status": "published",
                                "startsAt": e["startsAt"], "descriptionHtml": "<p>All beginner instructions.</p>"})
        item = c._manifest(listing(e), NOW)[0]
        row, _ = c._detail(item, flight({"event": e}))
        self.assertEqual(row["description"], "Meetup\n" + BODY + "\n\nLearn to play\nAll beginner instructions.")
        e["activities"][1]["descriptionHtml"] = ""
        self.assertEqual(c._detail(item, flight({"event": e})), (None, "description_unavailable"))

    def test_detail_changes_and_conflicting_native_copies_fail_closed(self):
        e = native()
        item = c._manifest(listing(e), NOW)[0]
        moved = deepcopy(e)
        moved["startsAt"] = "2026-11-22T23:00:00Z"
        moved["endsAt"] = "2026-11-23T03:00:00Z"
        with self.assertRaisesRegex(ValueError, "detail_changed"):
            c._detail(item, flight({"event": moved}))
        changed = deepcopy(e)
        changed["activities"][0]["descriptionHtml"] = "<p>Conflicting full description.</p>"
        with self.assertRaisesRegex(ValueError, "detail_changed"):
            c._detail(item, flight({"events": [e, changed]}))
        with self.assertRaisesRegex(ValueError, "detail_changed"):
            c._detail(item, flight({"event": {**e, "status": "canceled"}}))

    def test_in_person_timezone_and_positive_duration_required(self):
        for e in [native(configuration={"timezone": "America/Chicago", "playSetting": "inPerson"}),
                  native(configuration={"timezone": c.ZONE, "playSetting": "online"}),
                  native(endsAt=native()["startsAt"])]:
            with self.assertRaisesRegex(ValueError, "identity_changed|schedule_changed"):
                c._manifest(listing(e), NOW)

    def test_actual_record_keeps_verified_numeric_street_and_native_point(self):
        e = native(7)
        row, reason = c._detail(c._manifest(listing(e), NOW)[0], flight({"event": e}))
        self.assertIsNone(reason)
        self.assertEqual(row["venue_address"], c.STREET)
        self.assertEqual((row["lat"], row["lng"]), (39.616767, -74.7754785))

    @patch.object(c, "record", side_effect=preview)
    def test_explicit_offsite_and_missing_zip_do_not_inherit_store_location(self, _):
        e = native()
        e["address"].update(name="Community Hall", address1="123 Main Street", city="Absecon", zip="08201")
        row, _ = c._detail(c._manifest(listing(e), NOW)[0], flight({"event": e}))
        self.assertEqual(row["venue_address"], "123 Main Street, Absecon, NJ 08201")
        self.assertEqual(row["venue_name"], "Community Hall")
        self.assertIsNone(row["lat"])
        e["address"]["zip"] = ""
        self.assertEqual(c._detail(c._manifest(listing(e), NOW)[0], flight({"event": e})), (None, "venue_street_unresolved"))
        home = native()
        home["address"]["zip"] = ""
        self.assertEqual(c._location(home)[1], c.STREET)
        home["address"]["geo"] = {"lat": 40.7128, "lng": -74.006}
        self.assertEqual(c._location(home)[3:], (None, None))

    @patch.object(c, "record", side_effect=preview)
    def test_checkpoint_publishes_only_after_complete_manifest(self, _):
        events = [native(i) for i in range(1, 4)]
        fetch, render = callbacks(events)
        first = c.collect_chunk(SOURCE, fetch, render_calendar=render, now=NOW, max_details=100)
        self.assertFalse(first["complete"])
        self.assertEqual(first["events"], [])
        self.assertEqual(first["checkpoint"]["cursor"], 2)
        second = c.collect_chunk(SOURCE, fetch, render_calendar=render, checkpoint=first["checkpoint"], now=NOW)
        self.assertTrue(second["complete"])
        self.assertEqual(len(second["events"]), 3)
        self.assertEqual(render.call_args.kwargs, {"starts_at": "2026-11-13T00:00:00Z", "ends_at": "2027-01-13T22:00:00Z"})
        self.assertTrue(all(call.args[1] == "text/html" for call in fetch.call_args_list))

    @patch.object(c, "record", side_effect=preview)
    def test_checkpoint_rejects_tampered_identity_prose_geo_and_partition(self, _):
        fetch, render = callbacks([native(i) for i in range(1, 4)])
        checkpoint = c.collect_chunk(SOURCE, fetch, render_calendar=render, now=NOW)["checkpoint"]
        for field, value in [("title", "Other"), ("venue_name", "Other"), ("venue_address", "123 Main Street, Absecon, NJ 08201"),
                             ("lat", 40.7128), ("timezone", "America/Chicago"), ("attendance_mode", "online"), ("description", "")]:
            forged = deepcopy(checkpoint)
            forged["events"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                c._checkpoint(forged, NOW)
        forged = deepcopy(checkpoint)
        forged["events"].pop()
        with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
            c._checkpoint(forged, NOW)

    @patch.object(c, "record", side_effect=preview)
    def test_changed_manifest_resets_and_expired_checkpoint_restarts(self, _):
        events = [native(i) for i in range(1, 4)]
        fetch, render = callbacks(events)
        checkpoint = c.collect_chunk(SOURCE, fetch, render_calendar=render, now=NOW)["checkpoint"]
        render.return_value = listing(events[1], events[2])
        result = c.collect_chunk(SOURCE, fetch, render_calendar=render, checkpoint=checkpoint, now=NOW)
        self.assertTrue(result["complete"])
        self.assertEqual({r["id"] for r in result["events"]}, {"cardboard-arena:" + uid(2), "cardboard-arena:" + uid(3)})
        self.assertIsNone(c._checkpoint(checkpoint, NOW + timedelta(hours=5)))

    @patch.object(c, "record", side_effect=preview)
    def test_completion_removes_an_event_that_ended_during_earlier_chunk(self, _):
        events = [native(1, startsAt="2026-11-14T22:15:00Z", endsAt="2026-11-14T22:45:00Z"), native(2), native(3)]
        events[0]["activities"][0]["startsAt"] = events[0]["startsAt"]
        fetch, render = callbacks(events)
        first = c.collect_chunk(SOURCE, fetch, render_calendar=render, now=NOW)
        final = c.collect_chunk(SOURCE, fetch, render_calendar=render, checkpoint=first["checkpoint"], now=NOW + timedelta(hours=1))
        self.assertTrue(final["complete"])
        self.assertEqual(len(final["events"]), 2)
        self.assertEqual(final["checkpoint"]["diagnostics"][0]["reason"], "event_ended_during_collection")
        self.assertIsNotNone(c._checkpoint(final["checkpoint"], NOW + timedelta(hours=1)))

    def test_deadline_prevents_io(self):
        fetch, render = callbacks([native()])
        with self.assertRaisesRegex(ValueError, "collection_deadline"):
            c.collect_chunk(SOURCE, fetch, render_calendar=render, now=NOW, deadline_at=0)
        fetch.assert_not_called()
        render.assert_not_called()

    def test_cyclic_references_and_wrong_text_byte_lengths_rejected(self):
        with self.assertRaisesRegex(ValueError, "shape_changed"):
            c._deref("$a", {"a": "$b", "b": "$a"})
        with self.assertRaisesRegex(ValueError, "shape_changed"):
            c._flight_models(flight({}, "a:Tffff,short"))


if __name__ == "__main__":
    unittest.main()
