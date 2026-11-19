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
<div class="field--name-field-when">When Sat, Nov 28 2026, 5:30 - to 7:30pm</div>
<div class="node__content"><div class="field--name-body"><div class="field__item">
JOIN US ON NOVEMBER 28TH AT 5:30 PM FOR OUR ANNUAL CHRISTMAS PARADE AND TREE LIGHTING
TO FOLLOW IN THE PARK. CHATTAHOOCHEE PARK - 639 MAIN STREET. FREE HOT CHOCOLATE.
</div></div></div>
<div class="field--name-field-location-name"><div class="field__item">Clermont Chattahoochee Park</div></div>"""


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
        self.assertEqual(parse(html([EVENT]), lambda u,a: DETAIL.replace("Nov 28","Nov 29"), now=NOW),[])
        with self.assertRaisesRegex(ValueError,"timezone_changed"):
            parse(html([EVENT],zone="America/Chicago"), lambda u,a: DETAIL, now=NOW)

    def test_wrong_identity_time_and_unregistered_profile_held(self):
        self.assertEqual(parse(html([dict(EVENT,url="/event/../secret")]),lambda u,a: DETAIL,now=NOW),[])
        self.assertEqual(parse(html([dict(EVENT,start="2026-11-28")]),lambda u,a: DETAIL,now=NOW),[])
        with self.assertRaisesRegex(ValueError,"unregistered_clermont_source"):
            collect({"source_key":KEY,"feed_url":URL,"kind":"html",
                     "platform_adapter":"clermont_drupal_calendar","timezone":"UTC"},
                    lambda u,a: DETAIL)

    def test_identical_duplicate_collapses(self):
        self.assertEqual(len(parse(html([EVENT,EVENT]),lambda u,a: DETAIL,now=NOW)),1)


if __name__ == "__main__":
    unittest.main()
