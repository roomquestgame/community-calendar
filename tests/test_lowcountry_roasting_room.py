"""Roasting Room fail-closed original JSON-LD and anchor-detail validations."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import unittest
import json
from roomquest import lowcountry_roasting_room as s

def source():
    return {"source_key":s.KEY,"feed_url":s.URL,"kind":"html",
            "platform_adapter":"html","timezone":s.ZONE}

def fixture(*,venue_address="1297 May River Road",event_status="https://schema.org/EventScheduled",
            missing_detail=False,date_disagrees=False):
    when=datetime.now(ZoneInfo(s.ZONE))+timedelta(days=7)
    when=when.replace(hour=20,minute=0,second=0,microsecond=0)
    day=when.date().isoformat()
    url=s.URL+"#show-plump"
    graph={"@context":"https://schema.org","@graph":[
        {"@type":["MusicVenue","LocalBusiness"],"@id":s.URL+"#venue","name":s.VENUE,
         "address":{"streetAddress":venue_address,"addressLocality":"Bluffton","addressRegion":"SC","postalCode":"29910","addressCountry":"US"}},
        {"@type":"MusicEvent","name":"Plump","startDate":when.isoformat(),"eventStatus":event_status,
         "eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
         "location":{"@id":s.URL+"#venue"},"url":url,
         "offers":{"@type":"Offer","url":url,"price":"35.00"}}]}
    detail="" if missing_detail else ('<article class="artist-page" id="show-plump" data-show-date="'+
          (day if not date_disagrees else "2026-01-01")+'"><h1>Plump</h1>'+
          '<p class="bio">An original publisher-provided concert night bringing electric funk, soul, and more to the stage.</p></article>')
    return '<script type="application/ld+json">'+json.dumps(graph)+'</script>'+detail

class RoastingRoomTests(unittest.TestCase):
    def test_event_validation_and_original_narrative(self):
        out=s.collect(source(),lambda u,a:fixture())
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["venue_address"],s.STREET)
        self.assertEqual(out[0]["lat"],s.LAT)
        self.assertEqual(out[0]["lng"],s.LNG)
        self.assertEqual(out[0]["ends_at"],None)
        self.assertIn("original publisher-provided",out[0]["description"])
        self.assertEqual(out[0]["category"],"music")
        self.assertTrue(s.event_url(out[0]["event_url"]))
    def test_fail_closed_venue(self):
        with self.assertRaisesRegex(ValueError,"address_drift"):
            s.collect(source(),lambda u,a:fixture(venue_address="12 Other Rd"))
    def test_fail_closed_cancelled(self):
        with self.assertRaisesRegex(ValueError,"no_valid_future"):
            s.collect(source(),lambda u,a:fixture(event_status="https://schema.org/EventCancelled"))
    def test_fail_closed_mismatched_date(self):
        with self.assertRaisesRegex(ValueError,"no_valid_future"):
            s.collect(source(),lambda u,a:fixture(date_disagrees=True))
    def test_fail_closed_missing_detail(self):
        with self.assertRaisesRegex(ValueError,"no_valid_future"):
            s.collect(source(),lambda u,a:fixture(missing_detail=True))
    def test_url_guard(self):
        for url in ("http://roastingroom.live/#show-plump","https://evil.example/#show-plump",
                    "https://roastingroom.live/admin#show-plump","https://roastingroom.live/#not-show",
                    "https://roastingroom.live/?format=json#show-plump"):
            self.assertFalse(s.event_url(url))
    def test_source_identity(self):
        self.assertFalse(s.source_valid({**source(),"feed_url":"https://evil.example/"}))

if __name__=="__main__":
    unittest.main()
