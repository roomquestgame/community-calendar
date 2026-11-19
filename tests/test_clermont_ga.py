"""Clermont publisher calendar: fail-closed, no fake civic/public cards."""
import json
import unittest
from datetime import datetime, timezone
from roomquest.clermont_ga import KEY, URL, ZONE, parse, collect

NOW = datetime(2026, 11, 19, 20, tzinfo=timezone.utc)
EVENT = {"title":"Christmas Parade ", "id":"0-0","eid":"253-D-0",
         "url":"/event/christmas-parade","allDay":False,
         "start":"2026-11-28T17:30:00","end":"2026-11-28T19:30:00"}
DETAIL = """<div class="field--name-title">Christmas Parade</div>
<div class="field--name-field-when">When
<time datetime="2026-11-28T17:30:00-05:00">Sat, Nov 28 2026, 5:30</time>
<time datetime="2026-11-28T19:30:00-05:00">7:30pm</time></div>
<div class="node__content"><div class="field--name-body field__item">
JOIN US ON NOVEMBER 28TH AT 5:30 PM FOR OUR ANNUAL CHRISTMAS PARADE AND TREE LIGHTING
TO FOLLOW IN THE PARK. CHATTAHOOCHEE PARK - 639 MAIN STREET. FREE HOT CHOCOLATE.
</div></div>
<div class="field--name-field-location-name field__item">Clermont Chattahoochee Park</div>"""


def html(events, *, zone=ZONE):
    settings = {"fullCalendarView":[{"calendar_options":json.dumps({
        "timeZone":zone, "events":events})}]}
    return '<script type="application/json" data-drupal-selector="drupal-settings-json">' + json.dumps(settings) + '</script>'


class ClermontTests(unittest.TestCase):
    def test_real_timed_parade_full_first_party_description(self):
        rows = parse(html([EVENT]), lambda url, accept: DETAIL, now=NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["event_url"],"https://clermontga.com/event/christmas-parade")
        self.assertIn("639 Main Street, Clermont, GA", rows[0]["venue_address"])
        self.assertIn("FREE HOT CHOCOLATE", rows[0]["description"])
        self.assertEqual(rows[0]["timezone"],ZONE)
        self.assertEqual(rows[0]["category"],"Festival")

    def test_office_closure_civic_and_date_only_are_excluded(self):
        blank = dict(EVENT,title="Office Closed")
        civic = dict(EVENT,title="Town Council Meeting")
        all_day = dict(EVENT,allDay=True)
        self.assertEqual(parse(html([blank,civic,all_day]), lambda u,a: DETAIL, now=NOW),[])

    def test_missing_street_mismatched_detail_or_changed_zone_held(self):
        self.assertEqual(parse(html([EVENT]), lambda u,a: DETAIL.replace("639 MAIN STREET","LOCATION TBA"), now=NOW),[])
        self.assertEqual(parse(html([EVENT]), lambda u,a: DETAIL.replace("2026-11-28T17:30:00","2026-11-29T17:30:00"), now=NOW),[])
        with self.assertRaisesRegex(ValueError,"timezone_changed"):
            parse(html([EVENT],zone="America/Chicago"), lambda u,a: DETAIL, now=NOW)

    def test_wrong_identity_time_and_unregistered_profile_held(self):
        self.assertEqual(parse(html([dict(EVENT,url="/event/../secret")]),lambda u,a: DETAIL,now=NOW),[])
        self.assertEqual(parse(html([dict(EVENT,start="2026-11-28")]),lambda u,a: DETAIL,now=NOW),[])
        with self.assertRaisesRegex(ValueError,"unregistered_clermont_source"):
            collect({"source_key":KEY,"feed_url":URL,"kind":"html",
                     "platform_adapter":"html","timezone":"UTC"},
                    lambda u,a: DETAIL)

    def test_registered_html_dispatch_uses_robots_safe_first_party_fetch(self):
        # End-to-end preview route regression: previous deployment had the
        # correct parser but HTML dispatched elsewhere and failed closed.
        from unittest.mock import patch
        from roomquest.preview_worker import preview_source
        source = {"source_key": KEY, "feed_url": URL, "kind": "html",
                  "platform_adapter": "html", "timezone": ZONE}
        calls = []
        def publisher(url, accept, **kwargs):
            calls.append((url, accept, kwargs))
            if url == URL:
                return html([EVENT])
            if url == "https://clermontga.com/event/christmas-parade":
                return DETAIL
            raise AssertionError("unexpected publisher URL")
        with patch("roomquest.preview_worker.fetch_publisher", side_effect=publisher):
            result = preview_source(source)
        self.assertEqual(result["p_future_count"], 1)
        self.assertEqual(len(result["p_events"]), 1)
        self.assertEqual(result["p_events"][0]["category"], "Festival")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c[2].get("respect_robots") is True for c in calls))
        self.assertTrue(all(c[2].get("allowed_hosts") == ("clermontga.com",) for c in calls))

    def test_identical_duplicate_collapses(self):
        self.assertEqual(len(parse(html([EVENT,EVENT]),lambda u,a: DETAIL,now=NOW)),1)


if __name__ == "__main__":
    unittest.main()
