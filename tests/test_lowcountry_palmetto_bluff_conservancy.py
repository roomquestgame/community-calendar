"""Guard source identity, event location, eligibility and actual original text."""
import json
import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from roomquest import lowcountry_palmetto_bluff_conservancy as s
def src():
    return {"source_key":s.KEY,"feed_url":s.URL,"kind":"html","platform_adapter":"html","timezone":s.ZONE}
def sample(**changes):
    when=(datetime.now(ZoneInfo(s.ZONE))+timedelta(days=2)).replace(hour=12,minute=0,second=0,microsecond=0)
    e={"id":1234,"status":"publish","title":"Brown Bag Lunch: Oak Island",
       "url":s.HOST.replace("www.","https://www.")+"/event/brown-bag-lunch-oak-island/",
       "description":"This public lecture explores Oak Island and the history of the Lowcountry. Walk-ins welcome at the Conservancy Classroom.",
       "start_date":when.strftime("%Y-%m-%d %H:%M:%S"),
       "end_date":(when+timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
       "venue":{"venue":s.VENUE,"address":"655 Old Moreland Road","city":"Bluffton","state":"SC","zip":"29910"},
       "categories":[{"slug":"conservancy"},{"slug":"talks"}]}
    e.update(changes)
    return json.dumps({"events":[e],"total_pages":1,"total":1})
class PalmettoBluffTests(unittest.TestCase):
    def test_valid_original_and_geocoded(self):
        rows=s.collect(src(),lambda *_:sample())
        self.assertEqual(len(rows),1)
        x=rows[0]
        self.assertEqual(x["venue_address"],s.STREET)
        self.assertEqual((x["lat"],x["lng"]),(s.LAT,s.LNG))
        self.assertEqual(x["category"],"learn")
        self.assertIn("Walk-ins welcome",x["description"])
        self.assertTrue(s.event_url(x["event_url"]))
    def test_fail_closed_on_site_or_eligibility_drift(self):
        for change in ({"venue":{"venue":"Park Gate","address":"100 Park Road","city":"Bluffton","state":"SC","zip":"29910"}},
                       {"description":"This program is residents only and requires a signed club membership."},
                       {"url":"https://outside.example/event/brown-bag/"},
                       {"status":"draft"},
                       {"title":"Canceled Brown Bag Lunch: Oak Island"}):
            with self.subTest(change=change):
                self.assertEqual(s.collect(src(),lambda *_:sample(**change)),[])
    def test_pagination_and_source_guard(self):
        with self.assertRaisesRegex(ValueError,"unregistered"):
            s.collect({**src(),"timezone":"UTC"},lambda *_:"")
        with self.assertRaisesRegex(ValueError,"pagination_overflow"):
            s.collect(src(),lambda *_:json.dumps({"events":[],"total_pages":2}))
if __name__=="__main__":
    unittest.main()
