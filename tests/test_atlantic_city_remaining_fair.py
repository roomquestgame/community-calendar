from datetime import datetime, timezone
from html import escape
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_remaining_fair as fair
from roomquest.mapsee_adapter import timestamp


NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
BOOT = f"https://img1.wsimg.com/blobby/go/{fair.SITE}/gpub/1111111111111111/script.js"
DATA = f"https://img1.wsimg.com/blobby/go/{fair.SITE}/gpub/2222222222222222/script.js"
CRAFT = "https://acfairevents.com/2026-holiday-craft-bazaar"


def source():
    return dict(source_key=fair.FAIR, feed_url=fair.SOURCES[fair.FAIR][0], kind="html",
                platform_adapter="html", timezone=fair.ZONE)


def draft(text):
    return json.dumps(dict(blocks=[dict(type="unstyled", text=line) for line in text.split("\n")], entityMap={}))


def item(n=1, **changes):
    out = dict(id=f"00000000-0000-4000-8000-{n:012d}", date="Nov 21, 2026",
               title="Electronic Recycling", desc=draft("Bring unwanted electronics. Keep the complete final condition."),
               start="9am", end="12pm", location="ATLANTIC COUNTY FAIRGROUNDS")
    out.update(changes)
    return out


def widget(items):
    return dict(id=fair.WIDGET, widgetId=fair.WIDGET, websiteId=fair.SITE, pageId=fair.PAGE,
                isManual=True, visitorMode=True, detachedMode=False, icalURL="",
                env="production", renderMode="PUBLISH", manualEvents=items,
                staticContent=dict(defaultEvents=dict(one=dict(title="Fake template event"))))


def script(obj):
    return "/* publisher literal; never executed */ JSON.parse(" + json.dumps(json.dumps(obj)) + ");"


def page(items):
    cards = []
    for entry in items:
        clock = entry["start"] + (" - " + entry["end"] if entry["end"] else "")
        cards.append('<div data-aid="CALENDAR_BIGGER_SCREEN_CONTAINER">'
                     + '<div data-aid="CALENDAR_EVENT_DATE">' + escape(entry["date"]) + '</div>'
                     + '<h4 data-aid="CALENDAR_EVENT_TITLE">' + escape(entry["title"]) + '</h4>'
                     + '<div data-aid="CALENDAR_EVENT_TIME">' + escape(clock) + '</div>'
                     + '<div data-aid="CALENDAR_DESC_TEXT">Abbreviated visible excerpt...</div></div>')
    return ('<link rel="canonical" href="https://acfairevents.com/">'
            + '<div data-ux="Widget" id="' + fair.WIDGET + '">' + ''.join(cards) + '</div>'
            + '<script src="' + BOOT + '"></script>'
            + '<script src="https://img1.wsimg.com/ceph-p3-01/website-builder-data-prod/static/widgets/UX.7.3.8.js"></script>'
            + '<script src="' + DATA + '"></script>'
            + '<a href="/2026-holiday-craft-bazaar">2026 Holiday Craft Bazaar</a>')


def craft_detail(extra="Complete vendor requirements and final contact instructions."):
    sections = [
        ("Time Date & Location", "December 5th & 6th\n9am-4pm\nAtlantic County 4H Fairgrounds\n3210 NJ-50\nMays Landing, NJ"),
        ("What to Expect", "Local craft vendors, Santa visits, holiday movies, and model trains."),
        ("2025 Vendors", "The publisher's original vendor heading is retained."),
        ("Vendor Payments", extra),
    ]
    return ('<link rel="canonical" href="' + CRAFT + '">'
            + '<h1 data-aid="CONTENT_SECTION_TITLE_RENDERED">2026 Holiday Craft Bazaar</h1>'
            + ''.join(f'<h4 data-aid="CONTENT_HEADLINE{n}_RENDERED">{escape(h)}</h4>'
                      + f'<div data-aid="CONTENT_DESCRIPTION{n}_RENDERED">'
                      + ''.join('<p>' + escape(line) + '</p>' for line in text.split('\n')) + '</div>'
                      for n, (h, text) in enumerate(sections, 1)))


def record(title, start, end, venue, address, city, url, identity, category="", lat=None, lng=None, tz=None, **kwargs):
    return dict(id=identity, title=title, starts_at=timestamp(start, tz).astimezone(timezone.utc).isoformat(),
                ends_at=timestamp(end, tz).astimezone(timezone.utc).isoformat() if end else None,
                venue_name=venue, venue_address=address, venue_city=city, event_url=url,
                lat=lat, lng=lng, category=category)


class RemainingFairTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(fair, "record", side_effect=record)
        p.start()
        self.addCleanup(p.stop)

    def run_source(self, entries=None, *, obj=None, html=None, detail=None, now=NOW):
        entries = entries if entries is not None else [item()]
        pages = {fair.SOURCES[fair.FAIR][0]: html if html is not None else page(entries),
                 DATA: script(obj if obj is not None else widget(entries)),
                 CRAFT: detail if detail is not None else craft_detail()}
        fetch = Mock(side_effect=lambda url, accept: pages[url])
        return fair.collect(source(), fetch, now=now), fetch

    def test_complete_native_manifest_and_two_distinct_bazaar_days(self):
        entries = [item(1, date="Oct 17, 2026"), item(2),
                   item(3, title="Holiday Craft Bazaar", date="Dec 5&6, 2026", start="9am - 4pm", end="")]
        rows, fetch = self.run_source(entries)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["starts_at"] for r in rows], ["2026-11-21T14:00:00+00:00", "2026-12-05T14:00:00+00:00", "2026-12-06T14:00:00+00:00"])
        self.assertEqual([r["ends_at"] for r in rows], ["2026-11-21T17:00:00+00:00", "2026-12-05T21:00:00+00:00", "2026-12-06T21:00:00+00:00"])
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([c.args[1] for c in fetch.call_args_list], ["text/html", "application/javascript", "text/html"])
        self.assertNotIn(BOOT, [c.args[0] for c in fetch.call_args_list])
        for row in rows:
            self.assertEqual(row["venue_address"], fair.ADDRESS)
            self.assertEqual((row["lat"], row["lng"]), (39.516678000003, -74.660746500001))
            self.assertEqual(row["timezone"], fair.ZONE)
            self.assertEqual(row["attendance_mode"], "in_person")
        self.assertIn("2025 Vendors", rows[1]["description"])
        self.assertEqual(rows[1]["description"], rows[2]["description"])

    def test_native_plain_long_prose_and_literal_suffix_survive(self):
        full = "Complete event information. " * 160 + "Read <literal text> & keep the final condition."
        rows, _ = self.run_source([item(desc=draft(full))])
        self.assertEqual(rows[0]["description"], full)
        self.assertGreater(len(rows[0]["description"]), 4000)
        self.assertNotIn("Abbreviated", rows[0]["description"])

    def test_full_detail_sections_and_escaped_literal_suffix_survive(self):
        final = "Every published participation condition. " * 90 + "Keep <final literal> and all vendor terms."
        rows, _ = self.run_source([item(title="Holiday Craft Bazaar", date="Dec 5&6, 2026", start="9am - 4pm", end="")],
                                  detail=craft_detail(final))
        self.assertTrue(rows[0]["description"].endswith(final))
        self.assertIn("Bring unwanted electronics.", rows[0]["description"])
        self.assertGreater(len(rows[0]["description"]), 3500)

    def test_blank_oversized_and_truncated_native_descriptions_fail(self):
        for text, error in [(" ", "description_missing"), ("x" * 12001, "description_limit"), ("Unfinished...", "description_incomplete")]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.run_source([item(desc=draft(text))])

    def test_combined_full_detail_limit_rejects_instead_of_clipping(self):
        with self.assertRaisesRegex(ValueError, "description_limit"):
            self.run_source([item(title="Holiday Craft Bazaar", date="Dec 5&6, 2026", start="9am - 4pm", end="")],
                            detail=craft_detail("x" * 11800))

    def test_atomic_and_nonliteral_description_shapes_are_rejected(self):
        for desc in ["not-json", json.dumps(dict(blocks=[dict(type="atomic", text="Poster")], entityMap={}))]:
            with self.subTest(desc=desc), self.assertRaisesRegex(ValueError, "description_shape_changed"):
                self.run_source([item(desc=desc)])

    def test_incomplete_or_duplicate_manifest_returns_no_snapshot(self):
        with self.assertRaisesRegex(ValueError, "manifest_incomplete"):
            self.run_source([item(), item(2)], html=page([item()]))
        with self.assertRaisesRegex(ValueError, "event_identity"):
            self.run_source([item(), item()])

    def test_changed_public_widget_or_calendar_mode_is_rejected(self):
        for update in [dict(websiteId="another-site"), dict(visitorMode=False), dict(isManual=False),
                       dict(icalURL="https://calendar.google.com/calendar/ical/example")]:
            obj = widget([item()]); obj.update(update)
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, "manifest_changed"):
                self.run_source(obj=obj)

    def test_wrong_script_host_or_unreviewed_script_order_fails(self):
        html = page([item()])
        for changed in [html.replace(DATA, DATA.replace("img1.wsimg.com", "unreviewed.example")),
                        html.replace(DATA, BOOT)]:
            with self.subTest(html=changed[-220:]), self.assertRaisesRegex(ValueError, "manifest_changed"):
                self.run_source(html=changed)

    def test_mismatched_visible_time_and_detail_time_fail(self):
        with self.assertRaisesRegex(ValueError, "manifest_incomplete"):
            self.run_source(html=page([item()]).replace("9am - 12pm", "10am - 12pm"))
        with self.assertRaisesRegex(ValueError, "detail_schedule_changed"):
            self.run_source([item(title="Holiday Craft Bazaar", date="Dec 5&6, 2026", start="9am - 4pm", end="")],
                            detail=craft_detail().replace("9am-4pm", "10am-4pm"))

    def test_explicit_year_and_current_detail_link_are_required(self):
        for day in ["Nov 21", "Nov 21, TBD", "Dec 6&5, 2026", "Nov 31, 2026"]:
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, "date_changed"):
                self.run_source([item(date=day)])
        entries = [item(title="Holiday Craft Bazaar", date="Dec 5&6, 2026", start="9am - 4pm", end="")]
        with self.assertRaisesRegex(ValueError, "detail_missing"):
            self.run_source(entries, html=page(entries).replace("/2026-holiday-craft-bazaar", "/2025-holiday-craft-bazaar"))

    def test_wrong_venue_or_craft_street_fails_without_rebinding_point(self):
        with self.assertRaisesRegex(ValueError, "venue_changed"):
            self.run_source([item(location="An offsite meeting venue")])
        with self.assertRaisesRegex(ValueError, "detail_schedule_changed"):
            self.run_source([item(title="Holiday Craft Bazaar", date="Dec 5&6, 2026", start="9am - 4pm", end="")],
                            detail=craft_detail().replace("3210 NJ-50", "999 Elsewhere Rd"))
        self.assertIsNone(fair.reviewed_venue_location(fair.FAIR, "Different venue", fair.ADDRESS))
        self.assertIsNone(fair.reviewed_venue_location(fair.FAIR, fair.VENUE, fair.ADDRESS.replace("08330", "08201")))

    def test_unknown_end_stays_unknown_and_no_recurrence_is_invented(self):
        rows, _ = self.run_source([item(start="9am", end="")])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["ends_at"])

    def test_cancelled_past_and_beyond_window_are_excluded(self):
        rows, _ = self.run_source([item(1, title="Cancelled event"), item(2, date="Nov 14, 2026"),
                                  item(3, date="Feb 1, 2027"), item(4)])
        self.assertEqual(len(rows), 1)
        self.assertIn("000000000004", rows[0]["id"])

    def test_source_fence_and_deadline_run_before_io(self):
        fetch = Mock()
        for changed in [dict(source(), feed_url="https://ac4hfair.org/calendar/"), dict(source(), timezone="UTC")]:
            with self.assertRaisesRegex(ValueError, "unregistered"):
                fair.collect(changed, fetch, now=NOW)
        with self.assertRaisesRegex(ValueError, "collection_deadline"):
            fair.collect(source(), fetch, now=NOW, deadline_at=0)
        with self.assertRaisesRegex(ValueError, "timezone_required"):
            fair.collect(source(), fetch, now=NOW.replace(tzinfo=None))
        fetch.assert_not_called()

    def test_event_url_rejects_unrelated_hosts_routes_and_fragments(self):
        self.assertTrue(fair.event_url(fair.FAIR, CRAFT))
        self.assertTrue(fair.event_url(fair.FAIR, fair.SOURCES[fair.FAIR][0]))
        for value in [CRAFT + "?auth=x", CRAFT + "#fragment", "https://acfairevents.com@evil.example/",
                      "https://ac4hfair.org/calendar/", "https://acfairevents.com/product-payments"]:
            self.assertFalse(fair.event_url(fair.FAIR, value))


if __name__ == "__main__":
    unittest.main()
