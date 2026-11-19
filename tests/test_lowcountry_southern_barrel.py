"""Fail-closed publisher HTML/date/address/category tests for Southern Barrel Bluffton."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import unittest
from roomquest import lowcountry_southern_barrel as s

def fixture(*, bad_address=False, bad_date=False, bad_time=False):
    now=datetime.now(ZoneInfo(s.ZONE))
    ahead=(2-now.weekday())%7 or 7
    d=(now+timedelta(days=ahead)).date()
    slug=d.isoformat()
    url="https://southernbarrel.com/event/wednesday-night-trivia-"+slug
    shown=d+timedelta(days=1) if bad_date else d
    suffix="th" if 11<=shown.day<=13 or shown.day%10 not in (1,2,3) else {1:"st",2:"nd",3:"rd"}[shown.day%10]
    label=shown.strftime("%B ")+str(shown.day)+suffix+shown.strftime(", %Y")
    ld={"@type":"Event","name":"Wednesday Night Trivia","startDate":slug,"endDate":slug,
        "eventStatus":"https://schema.org/EventScheduled",
        "eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
        "location":{"address":{"streetAddress":"375 Buckwalter Place Blvd." if not bad_address else "300 Random St",
            "addressLocality":"Bluffton","addressRegion":"SC","postalCode":"29910","addressCountry":"US"}}}
    phrase="from 8pm-10pm" if bad_time else "from 7pm-9pm"
    long_prose="Southern Barrel brings you another reason to come down and test your knowledge, every Wednesday "+phrase+". Patrons will have several chances to win prizes and bragging rights."
    detail='<h3 class="mt-4">'+label+'</h3><h1>Wednesday Night Trivia</h1><h2></h2><p>'+long_prose+'</p><script type="application/ld+json">'+json.dumps(ld)+'</script>'
    pages={s.URL:'<a href="event/wednesday-night-trivia-'+slug+'">Details</a>',url:detail}
    return pages

def source():
    return {"source_key":s.KEY,"feed_url":s.URL,"kind":"html","platform_adapter":"html","timezone":s.ZONE}

class SouthernBarrelTests(unittest.TestCase):
    def test_original_schedule_full_description_event_street_and_census_geocode(self):
        pages=fixture()
        rows=s.collect(source(),lambda url,_:pages[url])
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["category"],"hang_out")
        self.assertEqual(row["venue_address"],s.STREET)
        self.assertEqual((row["lat"],row["lng"]),(s.LAT,s.LNG))
        self.assertIn("win prizes and bragging rights",row["description"])
        self.assertEqual(row["location_provenance"],"census_exact_numbered_address_match_20261119")
        self.assertNotIn("image_url",row)
        self.assertTrue(s.event_url(row["event_url"]))

    def test_invalid_or_conflicting_publisher_evidence_is_not_published(self):
        for param in ("bad_address","bad_date","bad_time"):
            with self.subTest(param=param):
                pages=fixture(**{param:True})
                self.assertEqual(s.collect(source(),lambda url,_:pages[url]),[])

    def test_source_and_link_scope(self):
        self.assertFalse(s.event_url("https://evil.com/event/wednesday-night-trivia-2026-11-25"))
        self.assertFalse(s.event_url("https://southernbarrel.com/event/wednesday-night-trivia-2026-11-25?redirect=1"))
        self.assertFalse(s.source_valid({**source(),"timezone":"UTC"}))
        with self.assertRaisesRegex(ValueError,"unregistered_southern_barrel_source"):
            s.collect({**source(),"kind":"json"},lambda *_:"")

if __name__=="__main__":
    unittest.main()
