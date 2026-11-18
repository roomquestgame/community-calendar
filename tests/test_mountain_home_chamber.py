import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from roomquest import mountain_home_chamber as module

SOURCE = {
    "source_key": module.SOURCE_KEY, "feed_url": module.CALENDAR,
    "kind": "html", "platform_adapter": "html", "timezone": module.ZONE,
}
def card(title="A SHERLOCK CAROL", day="20", url="20261120-a-sherlock-carol",
         when="7:00 pm", place="600 West 6th Street Mountain Home"):
    return f"""<a class="link primary" href="https://enjoymountainhome.com/events/{url}/">
      <div><div class="f300">Nov</div><h3 class="main">{day}</h3></div>
      <div><div class="lead"><strong>{title}</strong></div>
      <div class="text-sm-set"><i class="fa-clock"></i>{when}</div>
      <div class="text-sm-set"><i class="fa-map-marker-alt"></i>{place}</div></div>
    </a>"""
def printed(text="Publisher-supplied original narrative, not a generated description.",
            heading="11/20/26 - A SHERLOCK CAROL"):
    return f'<div id="print_cont"><div><h3>{heading}</h3></div><div>{text}</div><hr/></div>'

class MountainHomeSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,11,18,20,tzinfo=timezone.utc)

    def parse(self, html=None, print_html=None):
        with patch.object(module, "record", side_effect=lambda *a, **kw: {
            "title":a[0], "starts_at":a[1], "venue_address":a[4],
            "id":a[7], "image_url":None, "event_url":a[6]}):
            return module.parse_calendar(html or card(), print_html or printed(), now=self.now)

    def test_original_description_and_event_street(self):
        rows=self.parse()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["venue_address"], "600 West 6th Street, Mountain Home, AR")
        self.assertEqual(rows[0]["starts_at"],"2026-11-20T19:00:00-06:00")
        self.assertIn("original narrative", rows[0]["description"])
        self.assertIsNone(rows[0]["image_url"])

    def test_full_source_description_is_not_silently_shortened(self):
        desc="Paragraph with publisher facts. "*55
        rows=self.parse(print_html=printed(desc))
        self.assertEqual(rows[0]["description"],desc.strip())

    def test_inexact_time_is_not_invented(self):
        self.assertEqual(self.parse(html=card(when="TBD")),[])

    def test_city_center_not_used_for_missing_event_street(self):
        self.assertEqual(self.parse(html=card(place="Baxter County Library")),[])

    def test_bad_date_rejected(self):
        with self.assertRaisesRegex(ValueError,"mountain_home_card_date_mismatch"):
            self.parse(html=card(day="21"))

    def test_ambiguous_print_match_does_not_publish(self):
        self.assertEqual(self.parse(print_html=printed(heading="11/21/26 - A SHERLOCK CAROL")),[])

    def test_reject_unregistered_source_before_network(self):
        with self.assertRaisesRegex(ValueError,"unregistered_mountain_home_source"):
            module.collect({**SOURCE,"feed_url":"https://example.com/events"},
                           lambda *_:self.fail("no fetch expected"))

    def test_exact_source_fetches_only_public_list_and_print_page(self):
        calls=[]
        def fetch(url,accept):
            calls.append((url,accept))
            return card() if url==module.CALENDAR else printed()
        with patch.object(module,"record",side_effect=lambda *a,**kw:{
            "starts_at":a[1], "id":a[7]}):
            rows=module.collect(SOURCE,fetch)
        self.assertEqual(len(rows),1)
        self.assertEqual(calls,[(module.CALENDAR,"text/html"),(module.PRINT,"text/html")])
if __name__ == "__main__":unittest.main()
