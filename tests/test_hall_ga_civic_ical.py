"""Hall County CivicPlus ICS exact-source and event-fact contracts."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import unittest

from icalendar import Calendar, Event
from roomquest import hall_ga_civic_ical as g

LOCAL = ZoneInfo(g.ZONE)


def source(key):
    url, kind, adapter = g.SOURCES[key]
    return dict(source_key=key,feed_url=url,kind=kind,platform_adapter=adapter,timezone=g.ZONE)


def vevent(*, uid="1691",title="Board of Commissioners Voting Meeting",site=None,
           desc=None,localtime=None, all_day=False, status=None, rrule=False):
    item=Event()
    item.add("uid",uid)
    item.add("summary",title)
    start=localtime or (datetime.now(timezone.utc)+timedelta(days=5)).astimezone(LOCAL)
    if all_day:
        item.add("dtstart", start.date())
        item.add("dtend", start.date()+timedelta(days=1))
    else:
        item.add("dtstart",start)
        item.add("dtend",start+timedelta(hours=1))
    item.add("location",site or "Hall County Government Center - 2875 Browns Bridge Road  Gainesville GA 30504")
    if desc is None:
        desc=f"Open public session. https://www.hallcounty.org/calendar.aspx?EID={uid}"
    item.add("description",desc)
    if status:item.add("status",status)
    if rrule:item.add("rrule",{"freq":"weekly","count":3})
    return item


def payload(*items):
    calendar=Calendar()
    calendar.add("prodid","-//Hall County CivicPlus Validation//")
    calendar.add("version","2.0")
    for item in items:calendar.add_component(item)
    return calendar.to_ical()


class HallGaCivicCases(unittest.TestCase):
    def test_exact_profiles(self):
        self.assertEqual(g.CATEGORIES,{g.COMMISSION:63,g.TAX:71,g.OUTREACH:74})
        for k in g.SOURCES:
            self.assertTrue(g.SOURCES[k][0].endswith("catID="+str(g.CATEGORIES[k])+"&feed=calendar"))
            bad={**source(k),"feed_url":g.SOURCES[k][0]+"&wrong=1"}
            with self.assertRaisesRegex(ValueError,"unregistered_hall_ga_civic_source"):
                g.collect(bad,lambda *_:payload())

    def test_meetings_are_timed_and_publisher_linked(self):
        rows=g.collect(source(g.COMMISSION),lambda *_:payload(vevent()))
        self.assertEqual(len(rows),1)
        e=rows[0]
        self.assertEqual(e["category"],"civic")
        self.assertEqual(e["venue_name"],"Hall County Government Center")
        self.assertEqual(e["venue_address"],"2875 Browns Bridge Road, Gainesville, GA 30504")
        self.assertEqual(e["event_url"],"https://www.hallcounty.org/calendar.aspx?EID=1691")
        self.assertTrue(e["description"].startswith("Open public session."))
        self.assertEqual(e["timezone"],g.ZONE)
        self.assertIsNone(e.get("image_url"))
        self.assertIsNone(e.get("lat"))
        self.assertIsNone(e.get("lng"))
        self.assertEqual(e["publisher_details"]["jurisdiction_id"],"us-ga-hall-county")
        self.assertEqual(e["civic"]["version"],1)
        self.assertEqual(e["civic"]["kind"],"meeting")
        self.assertEqual(e["civic"]["topic"],"government")
        self.assertEqual(e["civic"]["jurisdiction_id"],"us-ga-hall-county")
        self.assertEqual(e["civic"]["timezone"],g.ZONE)
        self.assertEqual(e["civic"]["time_precision"],"timed")
        self.assertEqual(e["civic"]["source_url"],e["event_url"])
        verified=datetime.fromisoformat(e["civic"]["verified_at"])
        deadline=datetime.fromisoformat(e["civic"]["valid_until"])
        self.assertLessEqual(deadline,datetime.fromisoformat(e["ends_at"]))
        self.assertLess((datetime.now(timezone.utc)-verified).total_seconds(),60)

    def test_missing_optional_description_is_valid(self):
        e=vevent(desc="https://www.hallcounty.org/calendar.aspx?EID=1691")
        rows=g.collect(source(g.COMMISSION),lambda *_:payload(e))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["description"],"")

    def test_offsite_meeting_exact_street(self):
        meeting=vevent(uid="1756",title="Public Engagement Meeting #5",
                       site="<p>Free Chapel</p> - 3001 McEver Rd  Gainesville GA 30504")
        rows=g.collect(source(g.OUTREACH),lambda *_:payload(meeting))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["venue_name"],"Free Chapel")
        self.assertEqual(rows[0]["venue_address"],"3001 McEver Rd, Gainesville, GA 30504")

    def test_no_unapproved_place_or_wrong_eid(self):
        wrong=vevent(site="Other Venue - 111 Invented St Gainesville GA 30504")
        bad=vevent(uid="1691",desc="https://www.hallcounty.org/calendar.aspx?EID=1726")
        self.assertEqual(g.collect(source(g.COMMISSION),lambda *_:payload(wrong,bad)),[])

    def test_cancelled_and_all_day_are_held(self):
        cases=[vevent(status="CANCELLED"),vevent(all_day=True),vevent(rrule=True)]
        self.assertEqual(g.collect(source(g.COMMISSION),lambda *_:payload(*cases)),[])

    def test_protect_url_identity(self):
        self.assertTrue(g.event_url(g.COMMISSION,"https://www.hallcounty.org/calendar.aspx?EID=1691"))
        self.assertFalse(g.event_url(g.COMMISSION,"https://evil.test/calendar.aspx?EID=1691"))
        self.assertFalse(g.event_url(g.COMMISSION,"https://www.hallcounty.org/calendar.aspx?EID=1691&private=1"))
        self.assertFalse(g.event_url(g.COMMISSION,"https://www.hallcounty.org/calendar.aspx?EID=abc"))

    def test_retains_multiple_distinct_public_meetings(self):
        first=vevent(uid="1691")
        second=vevent(uid="1670",title="Board of Commissioners Work Session")
        rows=g.collect(source(g.COMMISSION),lambda *_:payload(first,second))
        self.assertEqual(len(rows),2)
        self.assertEqual(len(set(e["id"] for e in rows)),2)


if __name__=="__main__":
    unittest.main()
