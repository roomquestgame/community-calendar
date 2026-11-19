"""Beaufort Library: exact branch/ICS provenance and core categorization tests."""
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from icalendar import Calendar,Event

from roomquest import beaufort_library_branches as b


def source(key):
    return dict(source_key=key,feed_url=b.feed_url(key),kind="ical",
                platform_adapter="ical",timezone=b.ZONE)


def fixture(key, *, title="Teen Dungeons and Dragons", narrative="Join us for a game night.",
            venue=None,lat=None,lng=None,url="https://beaufort.librarycalendar.com/event/teen-dnd",
            label="Games & Activities"):
    info=b.SOURCES[key]
    lat=info[5] if lat is None else lat
    lng=info[6] if lng is None else lng
    venue=info[7] if venue is None else venue
    dt=datetime.now(timezone.utc)+timedelta(days=2)
    dt=dt.replace(microsecond=0)
    cal=Calendar()
    cal.add("prodid","-//EventQuest source tests//")
    cal.add("version","2.0")
    e=Event()
    e.add("uid","fixture-10")
    e.add("dtstart",dt)
    e.add("dtend",dt+timedelta(hours=1))
    e.add("summary",title)
    e.add("location",venue)
    e.add("url",url)
    if narrative is not None:
        e.add("description",narrative)
    if label:
        e.add("categories",[label])
    e.add("geo",(lat,lng))
    cal.add_component(e)
    row=dict(id="fixture-10",title=title,event_url=url,
             venue_name=venue,venue_address=venue,venue_city=info[3],
             starts_at=dt.isoformat(),ends_at=(dt+timedelta(hours=1)).isoformat(),
             description=narrative or "",publisher_categories=[label] if label else [],
             category=label,lat=lat,lng=lng)
    return cal.to_ical().decode(),row


def collect(key, *args, **kwargs):
    payload,row=fixture(key,*args,**kwargs)
    with patch("roomquest.ics_adapter.parse",return_value=[row]):
        return b.collect(source(key),lambda url,accept:payload)


class BeaufortDirectLibraryTests(unittest.TestCase):
    def test_five_unique_exact_branch_sources(self):
        self.assertEqual(len(b.SOURCES),6)
        self.assertEqual(set(x[0] for x in b.SOURCES.values()),{72,74,77,78,79,80})
        self.assertEqual(len(set(b.feed_url(k) for k in b.SOURCES)),6)
        for key in b.SOURCES:
            self.assertTrue(b.source_valid(source(key)))
            self.assertFalse(b.source_valid({**source(key),"timezone":"UTC"}))
            self.assertFalse(b.source_valid({**source(key),"feed_url":b.BASE}))
            with self.assertRaisesRegex(ValueError,"unregistered_beaufort_library_source"):
                b.collect({**source(key),"feed_url":"https://evil.example/ical"},
                          lambda *_:"BEGIN:VCALENDAR\nEND:VCALENDAR")

    def test_five_event_sources_preserve_full_description_street_coords(self):
        for key in b.SOURCES:
            with self.subTest(key=key):
                prose="<p>"+"Long &amp; helpful event details. "*110+"</p>"
                rows=collect(key,narrative=prose)
                self.assertEqual(len(rows),1)
                row=rows[0]
                self.assertGreater(len(row["description"]),2000)
                self.assertNotIn("<p>",row["description"])
                self.assertIn("& helpful",row["description"])
                self.assertEqual(row["venue_name"],b.SOURCES[key][1])
                self.assertEqual(row["lat"],b.SOURCES[key][5])
                self.assertEqual(row["lng"],b.SOURCES[key][6])
                self.assertTrue(row["venue_address"].startswith(b.SOURCES[key][2]+", "))
                self.assertEqual(row["timezone"],b.ZONE)
                self.assertEqual(row["category"],"hang_out")
                self.assertIn(row["category"],b.CORE_CATEGORIES)
                self.assertEqual(row["details_evidence_url"],row["event_url"])

    def test_refuse_bad_street_or_publisher_geo(self):
        key="beaufort_library_hilton_head_sc"
        self.assertEqual(collect(key,venue="1 Random Rd, Hilton Head Island, SC"),[])
        self.assertEqual(collect(key,lat=40.7207559,lng=-74.0007613),[])
        self.assertEqual(collect(key,url="https://evil.example/event/teen-dnd"),[])
        self.assertEqual(collect(key,url="https://beaufort.librarycalendar.com/events/upcoming"),[])

    def test_refuse_blank_oversize_or_private(self):
        key="beaufort_library_bluffton_sc"
        self.assertEqual(collect(key,narrative=None),[])
        self.assertEqual(collect(key,narrative="a"*12001),[])
        self.assertEqual(collect(key,title="Staff event"),[])
        self.assertEqual(collect(key,title="Unspecified Gathering",label="Unrecognized"),[])

    def test_blank_publisher_label_exact_title_triggers(self):
        positive=[
            ("Library Board of Trustees Meeting","civic"),
            ("SC Works: United States Post Office Job Fair","civic"),
            ("C.R.E.A.T.E Theatre Taster Workshop Ages 8-12","create"),
            ("Write-in at the Lobeco Library","create"),
            ("Watercolor Wednesday","create"),
            ("Beaufort Strummers: Community Jam","music"),
            ("Little Red Hen Harvest Festival","festival"),
            ("Silly New Year's Eve Fun for ages 4 and older","party"),
            ("Farmers Market","food_drink"),
            ("Baby and Toddler Storytime","learn"),
            ("Teens Dungeons and Dragons","hang_out"),
        ]
        for title,category in positive:
            with self.subTest(title=title):
                self.assertEqual(b.category_for(title,[]),category)
                self.assertIn(category,b.CORE_CATEGORIES)
        self.assertIsNone(b.category_for("Staff event",["Arts & Crafts"]))
        self.assertIsNone(b.category_for("Completely Unknown",[]))

    def test_single_branch_location_mapping_and_no_phantom_images(self):
        self.assertFalse(b.event_url("beaufort_library_bluffton_sc","https://other.example/event/book-club"))
        self.assertFalse(b.event_url("beaufort_library_bluffton_sc","https://beaufort.librarycalendar.com/events/upcoming"))
        self.assertTrue(b.event_url("beaufort_library_bluffton_sc","https://beaufort.librarycalendar.com/event/teens-dnd"))
        self.assertIsNone(b.photo_url("beaufort_library_bluffton_sc","https://other.example/images/photo.jpg"))
        self.assertIsNone(b.photo_url("beaufort_library_bluffton_sc","https://beaufort.librarycalendar.com/sites/default/files/icon.jpg"))
        self.assertIsNone(b.photo_url("beaufort_library_bluffton_sc","https://beaufort.librarycalendar.com/sites/default/files/../photo.jpg"))
        self.assertTrue(b.photo_url("beaufort_library_bluffton_sc","https://beaufort.librarycalendar.com/sites/default/files/2026/event_photo.jpg"))

    def test_publisher_evidence_accepts_only_registered_detail_urls(self):
        from roomquest.publisher_evidence import family
        key="beaufort_library_port_royal_sc"
        self.assertEqual(family(key,"https://beaufort.librarycalendar.com/event/puzzle-swap"),
                         "beaufort_library:"+key)
        self.assertIsNone(family(key,"https://evil.example/event/puzzle-swap"))


if __name__=="__main__":
    unittest.main()
