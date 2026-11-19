"""Fail-closed first-party PRC source parser tests (no network)."""
import json
import unittest
from datetime import datetime,timezone,timedelta
from roomquest import lowcountry_palmetto_running as s

def source():
    return dict(source_key=s.KEY,feed_url=s.URL,kind="html",platform_adapter="html",timezone=s.ZONE)

def bodies(*, geo=None, description=None, addr=None, status="https://schema.org/EventScheduled", time="at 7:30 AM", canonical=True):
    geo = geo or dict(latitude=s.VENUES["94 pope ave."][3],longitude=s.VENUES["94 pope ave."][4])
    addr = addr or dict(streetAddress="94 Pope Ave.",addressLocality="Hilton Head Island",addressRegion="SC",postalCode="29928",addressCountry="US")
    desc = description or "Join the public running club for a friendly 5K and light exercises in Celebration Park. All ages and paces welcome. Check in at the park at the announced time."
    item = dict(**{"@type":"Event"},name="Friendsgiving Group Run/Walk",
                startDate="2026-11-21T07:30:00.000Z",
                eventStatus=status,eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode",
                location=dict(name="Celebration Park",address=addr,geo=geo))
    listing = '<div id="EventList"><a href="/event/31336/FriendsgivingGroupRunWalk"><div class="date">Nov 21st <span class="gray">07:30 AM EST</span></div></a></div>'
    detail = ('<h1>Friendsgiving Group Run/Walk</h1><h3><span class="date">November 21st, 2026</span> '
              '<span class="time">'+time+'</span></h3><div id="EventContent"><p>'+desc+'</p></div>'
              '<script type="application/ld+json">'+json.dumps(item)+'</script>')
    return {s.URL:listing,"https://"+s.HOST+"/event/31336/FriendsgivingGroupRunWalk":detail}

class PRCTests(unittest.TestCase):
    def run_source(self, **kwargs):
        b = bodies(**kwargs)
        return s.collect(source(),lambda u,a:b[u],now=datetime(2026,11,19,20,tzinfo=timezone.utc))
    def test_valid_full_prose_and_local_walltime(self):
        rows=self.run_source()
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["venue_address"],"94 Pope Ave., Hilton Head Island, SC 29928")
        self.assertEqual(row["category"],"sports")
        self.assertIsNone(row["ends_at"])
        self.assertFalse(row["end_time_verified"])
        self.assertEqual(row["starts_at"],datetime(2026,11,21,12,30,tzinfo=timezone.utc).isoformat())
        self.assertGreater(len(row["description"]),100)
    def test_reject_unsafe_geo_or_venue(self):
        self.assertRaisesRegex(ValueError,"prc_no_valid_future",self.run_source,geo=dict(latitude=0,longitude=0))
        self.assertRaisesRegex(ValueError,"prc_no_valid_future",self.run_source,addr=dict(streetAddress="No street",addressLocality="Hilton Head Island",addressRegion="SC",postalCode="29928",addressCountry="US"))
    def test_reject_cancelled_private_and_time_drift(self):
        self.assertRaisesRegex(ValueError,"prc_no_valid_future",self.run_source,status="https://schema.org/EventCancelled")
        self.assertRaisesRegex(ValueError,"prc_no_valid_future",self.run_source,description="This is a private event, residents only, no public.")
        self.assertRaisesRegex(ValueError,"prc_no_valid_future",self.run_source,time="at 8:30 AM")
    def test_source_and_url_guard(self):
        self.assertFalse(s.source_valid({**source(),"timezone":"UTC"}))
        for x in ("https://evil.example/event/31336/FriendsgivingGroupRunWalk",
                  "https://"+s.HOST+"/event/31336/abc?x=1",
                  "http://"+s.HOST+"/event/31336/abc"):
            self.assertFalse(s.event_url(x))

if __name__=="__main__": unittest.main()
