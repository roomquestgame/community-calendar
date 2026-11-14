from copy import deepcopy
from datetime import date, datetime, timezone
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from icalendar import Calendar, Event

from roomquest import atlantic_city_nightlife_more as ac


NOW = datetime(2026, 11, 14, 21, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=ac.SOURCES[key][0], kind="html",
                platform_adapter="html", timezone=ac.ZONE)


def row_record(title, start, end, venue, address, city, url, identity, category="", **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end,
                venue_name=venue, venue_address=address, venue_city=city,
                event_url=url, category=category, lat=None, lng=None)


def spec(eventid="1234", day="2026-11-19", title="Music Bingo", start="19:00", end="21:00"):
    return dict(eventid=eventid, day=day, title=title, start=start, end=end)


def hard_rock_url(item):
    day = date.fromisoformat(item["day"])
    return ac.HARD_ROCK_URL + "?" + urlencode(dict(date=day.strftime("%m/%d/%Y"),
                                                    display="event", eventid=item["eventid"]))


def feed(items, uid="unstable-guid"):
    cal = Calendar()
    cal.add("VERSION", "2.0")
    for item in items:
        event = Event()
        event.add("UID", uid + item["eventid"])
        event.add("SUMMARY", item["title"])
        event.add("DTSTART", datetime.fromisoformat(item["day"] + "T" + item["start"]))
        event.add("DTEND", date.fromisoformat(item["end_date"]) if item.get("end_date") else
                  datetime.fromisoformat(item["day"] + "T" + item["end"]))
        event.add("DESCRIPTION", "Short excerpt only")
        event.add("LOCATION", "Hard Rock Cafe Atlantic City - Trump Taj Mahal Hotel 1000 Boardwalk Virginia Av, Atlantic City, New Jersey, 8401, United States")
        event.add("URL", hard_rock_url(item))
        cal.add_component(event)
    return cal.to_ical().decode()


def detail(item, body="Full description with every participant detail.", json_day=None):
    def clock(value):
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p")
    day = json_day or item["day"]
    data = dict({"@type": "Event"}, name=item["title"], startDate=day + "T" + item["start"],
                endDate=item.get("end_date") or day + "T" + item["end"], url=hard_rock_url(item),
                location=dict(name="Hard Rock Cafe Atlantic City", address=dict(
                    streetAddress="Trump Taj Mahal Hotel 1000 Boardwalk Virginia Av",
                    addressLocality="Atlantic City", addressRegion="New Jersey", postalCode="8401")))
    return (f'<div class="calListDayEvent" data-eventid="{item["eventid"]}">'
            f'<h4 class="calListDayEventTitle">{item["title"]}</h4>'
            f'<div class="calListDayEventTime">{clock(item["start"])} - {clock(item["end"])}</div>'
            '<div class="calListDayEventCategory">Live Events</div>'
            f'<div class="calListDayEventDescription">{body}</div></div>'
            f'<script type="application/ld+json">{json.dumps(data)}</script>')


WIDGET = "30877525-0649-43fa-b80d-82cf06be6404"
SCRIPT = f"https://img1.wsimg.com/blobby/go/{ac.GARDEN_SITE}/gpub/226339f8a50d9f20/script.js"
GARDEN_HTML = (f'<section><h2 data-aid="CALENDAR_SECTION_TITLE_RENDERED">Events</h2>'
               f'<div id="{WIDGET}-bootstrap-container">Truncated excerpt...</div></section>'
               f'<script src="{SCRIPT}"></script>')


def garden_item(day="11/22/26", title="Sunday Shop Series", body="The complete vendor list and event information."):
    return dict(id="0d1aafb7-8272-4572-8576-e40f2af0ac54", date=day, title=title,
                start="3pm", end="5pm", location="",
                desc=json.dumps(dict(blocks=[dict(text=body)], entityMap={})))


def garden_bundle(items, **overrides):
    value = dict(id=WIDGET, widgetId=WIDGET, websiteId=ac.GARDEN_SITE,
                 pageId=ac.GARDEN_PAGE, isManual=True, manualEvents=items)
    value.update(overrides)
    return "props:JSON.parse(" + json.dumps(json.dumps(value)) + ")"


class AtlanticNightlifeTests(unittest.TestCase):
    def test_complete_only_chunks_keep_long_description_and_ignore_random_feed_uids(self):
        first, second = spec(), spec("1235", "2026-12-03")
        full = "Complete organizer details. " * 180 + "Final paragraph."
        pages = {ac.HARD_ROCK_URL + "?format=ical": feed([first, second]),
                 hard_rock_url(first): detail(first, full), hard_rock_url(second): detail(second, full)}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        with patch.object(ac, "record", side_effect=row_record):
            one = ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, max_details=1)
            self.assertFalse(one["complete"])
            self.assertEqual(one["events"], [])
            pages[ac.HARD_ROCK_URL + "?format=ical"] = feed([first, second], uid="different-every-request")
            two = ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW,
                                   max_details=1, checkpoint=one["checkpoint"])
        self.assertTrue(two["complete"])
        self.assertEqual(len(two["events"]), 2)
        self.assertTrue(all(r["description"] == full for r in two["events"]))
        self.assertGreater(len(two["events"][0]["description"]), 4000)
        self.assertEqual(two["events"][0]["id"], "hard-rock:1234:2026-11-19")
        self.assertEqual(two["events"][0]["venue_address"], "1000 Boardwalk, Atlantic City, NJ 08401")
        self.assertEqual(one["checkpoint"]["cursor"], 1)

    def test_midnight_date_end_requires_matching_explicit_detail_clock(self):
        item = spec(start="16:00", end="00:00")
        item["end_date"] = "2026-11-20"
        manifest = ac._hard_rock_manifest(feed([item]), NOW)[0]
        with patch.object(ac, "record", side_effect=row_record):
            row = ac._hard_rock_detail(manifest, detail(item))
        self.assertEqual(row["ends_at"], "2026-11-20T00:00:00-05:00")
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            ac._hard_rock_detail(manifest, detail(item).replace("12:00 AM", "11:00 PM"))

    def test_detail_date_and_calendar_time_must_match_manifest(self):
        item = spec()
        manifest = ac._hard_rock_manifest(feed([item]), NOW)[0]
        with self.assertRaisesRegex(ValueError, "schedule_changed"):
            ac._hard_rock_detail(manifest, detail(item, json_day="2026-11-20"))
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            ac._hard_rock_detail(manifest, detail(item).replace('data-eventid="1234"', 'data-eventid="9999"'))

    def test_detail_cancellation_cannot_publish_a_stale_scheduled_manifest(self):
        item = spec()
        manifest = ac._hard_rock_manifest(feed([item]), NOW)[0]
        for status in ("EventCancelled", "EventPostponed"):
            payload = detail(item).replace('"@type": "Event"',
                '"@type": "Event", "eventStatus": "https://schema.org/' + status + '"')
            with self.assertRaisesRegex(ValueError, "hard_rock_detail_status_changed"):
                ac._hard_rock_detail(manifest, payload)

    def test_native_recurrence_extensions_are_not_silently_dropped(self):
        for field in ("RDATE", "EXDATE", "RECURRENCE-ID"):
            cal = Calendar.from_ical(feed([spec()]))
            event = cal.walk("VEVENT")[0]
            event.add(field, datetime(2026, 11, 26, 19))
            with self.assertRaisesRegex(ValueError, "hard_rock_calendar_schedule_changed"):
                ac._hard_rock_manifest(cal.to_ical(), NOW)

    def test_unpadded_calendar_url_dates_are_equivalent(self):
        item = spec(day="2026-12-03")
        manifest = ac._hard_rock_manifest(feed([item]), NOW)[0]
        payload = detail(item).replace("12%2F03%2F2026", "12/3/2026")
        with patch.object(ac, "record", side_effect=row_record):
            self.assertIsNotNone(ac._hard_rock_detail(manifest, payload))

    def test_failed_detail_does_not_mutate_existing_checkpoint(self):
        first, second = spec(), spec("1235", "2026-12-03")
        pages = {ac.HARD_ROCK_URL + "?format=ical": feed([first, second]),
                 hard_rock_url(first): detail(first), hard_rock_url(second): detail(second, "")}
        fetch = lambda url, accept: pages[url]
        with patch.object(ac, "record", side_effect=row_record):
            initial = ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, max_details=1)
            checkpoint = deepcopy(initial["checkpoint"])
            with self.assertRaisesRegex(ValueError, "description_missing"):
                ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, checkpoint=checkpoint)
        self.assertEqual(checkpoint, initial["checkpoint"])

    def test_changed_manifest_restarts_without_returning_stale_event(self):
        first, second = spec(), spec("1235", "2026-12-03")
        pages = {ac.HARD_ROCK_URL + "?format=ical": feed([first, second]),
                 hard_rock_url(first): detail(first), hard_rock_url(second): detail(second)}
        fetch = lambda url, accept: pages[url]
        with patch.object(ac, "record", side_effect=row_record):
            one = ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, max_details=1)
            pages[ac.HARD_ROCK_URL + "?format=ical"] = feed([second])
            two = ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, checkpoint=one["checkpoint"])
        self.assertEqual([r["id"] for r in two["events"]], ["hard-rock:1235:2026-12-03"])

    def test_checkpoint_rejects_changed_venue_and_forged_geometry(self):
        first, second = spec(), spec("1235", "2026-12-03")
        pages = {ac.HARD_ROCK_URL + "?format=ical": feed([first, second]),
                 hard_rock_url(first): detail(first), hard_rock_url(second): detail(second)}
        fetch = lambda url, accept: pages[url]
        with patch.object(ac, "record", side_effect=row_record):
            chunk = ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, max_details=1)
        for field, value in (("lat", 40), ("venue_address", "999 Unknown Street, Atlantic City, NJ 08401")):
            bad = deepcopy(chunk["checkpoint"])
            bad["events"][0][field] = value
            with self.assertRaisesRegex(ValueError, "checkpoint_invalid"):
                ac.collect_chunk(source(ac.HARD_ROCK), fetch, now=NOW, checkpoint=bad)

    def test_garden_uses_complete_published_json_and_never_projects_recurring_prose(self):
        long_body = "Complete text. " * 180 + "Last vendor in the list."
        items = [garden_item(body=long_body),
                 garden_item("11/3/26", "Cornhole", "Every Tuesday and Wednesday."),
                 garden_item("11/26/26", "closed - Thanksgiving"),
                 garden_item("11/29/26", "Sunday Shop Series", "Different dated occurrence; same reused source UUID.")]
        pages = {ac.GARDEN_URL: GARDEN_HTML, SCRIPT: garden_bundle(items)}
        with patch.object(ac, "record", side_effect=row_record):
            rows = ac.collect(source(ac.GARDEN), lambda url, accept: pages[url], now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["description"], long_body)
        self.assertIn("Last vendor in the list.", rows[0]["description"])
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])
        self.assertTrue(all(r["venue_address"] == "247 E White Horse Pike, Galloway, NJ 08205" for r in rows))
        self.assertTrue(all((r["lat"], r["lng"]) == (39.446046000003, -74.527533000001) for r in rows))
        self.assertTrue(all(r["location_provenance"] == "reviewed_nj_ogis_point_address" for r in rows))

    def test_garden_refuses_missing_widget_or_foreign_site_data(self):
        for bundle in ("", garden_bundle([garden_item()], websiteId="different-site")):
            pages = {ac.GARDEN_URL: GARDEN_HTML, SCRIPT: bundle}
            with self.assertRaisesRegex(ValueError, "garden_state_calendar_(changed|incomplete)"):
                ac.collect(source(ac.GARDEN), lambda url, accept: pages[url], now=NOW)

    def test_publisher_offsite_location_requires_review(self):
        item = garden_item()
        item["location"] = "Different venue in another town"
        pages = {ac.GARDEN_URL: GARDEN_HTML, SCRIPT: garden_bundle([item])}
        with self.assertRaisesRegex(ValueError, "venue_changed"):
            ac.collect(source(ac.GARDEN), lambda url, accept: pages[url], now=NOW)

    def test_garden_equal_clocks_are_not_invented_as_a_24_hour_event(self):
        item = garden_item()
        item["end"] = item["start"]
        pages = {ac.GARDEN_URL: GARDEN_HTML, SCRIPT: garden_bundle([item])}
        with self.assertRaisesRegex(ValueError, "garden_state_calendar_time_conflict"):
            ac.collect(source(ac.GARDEN), lambda url, accept: pages[url], now=NOW)
        item.update(start="10pm", end="1am")
        pages[SCRIPT] = garden_bundle([item])
        with patch.object(ac, "record", side_effect=row_record):
            row = ac.collect(source(ac.GARDEN), lambda url, accept: pages[url], now=NOW)[0]
        self.assertEqual(row["ends_at"], "2026-11-23T01:00:00-05:00")

    def test_exact_source_url_and_asset_boundaries(self):
        bad = source(ac.GARDEN)
        bad["feed_url"] = "https://gardenstatebeerco.com/"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            ac.collect(bad, Mock())
        self.assertFalse(ac.event_url(ac.HARD_ROCK, hard_rock_url(spec()) + "&eventid=9999"))
        self.assertFalse(ac.event_url(ac.HARD_ROCK, hard_rock_url(spec()).replace("cafe.hardrock.com", "cafe.hardrock.com.evil.example")))
        self.assertFalse(ac._garden_script_url(SCRIPT.replace(ac.GARDEN_SITE, "different-site")))
        self.assertIsNone(ac.photo_url(ac.HARD_ROCK, "https://cafe.hardrock.com/atlantic-city/files/5303/../../x.jpg"))


if __name__ == "__main__":
    unittest.main()
