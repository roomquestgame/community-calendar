"""Fail-closed, no-network tests for the approved event HTML paths."""
import unittest
from datetime import datetime,timezone
from roomquest import lowcountry_michael_anthonys as s

NOW=datetime(2026,11,19,23,tzinfo=timezone.utc)
TITLE="Tuesday, December 8th | Dinner with Friends Hands-On"
D="https://www.michael-anthonys.com/cooking-school/dinner-with-friends-cooking-class-hilton-head-island-sc"
PROSE="Join our hands-on culinary workshop! Learn delicious recipes with our chefs. Prepare seasonal Italian dinner recipes, work together with new friends, and enjoy the completed menu."

def source():
    return dict(source_key=s.KEY,feed_url=s.FEED,kind="html",platform_adapter="html",timezone=s.ZONE)
def detail(*,addr="37 New Orleans Road",title=TITLE,start="11:30 AM",end="2:30 PM",prose=PROSE):
    return f"""<html><article class="eventitem" data-item-id="6afdfb38f9305a2904e7abf9">
       <h1 class="eventitem-title">{title}</h1>
       <time class="event-date" datetime="2026-12-08">Tuesday, December 8, 2026</time>
       <time class="event-time-localized-start" datetime="2026-12-08">{start}</time>
       <time class="event-time-localized-end" datetime="2026-12-08">{end}</time>
       <span class="eventitem-meta-address-line eventitem-meta-address-line--title">{s.VENUE}</span>
       <span class="eventitem-meta-address-line">{addr}</span>
       <span class="eventitem-meta-address-line">Hilton Head Island, SC, 29928</span>
       <div class="eventitem-column-content"><div class="sqs-layout"><p>{prose}</p></div></div>
       </article></html>"""
def listing():
    return f"""<html><article class="eventlist-event eventlist-event--upcoming">
       <a class="eventlist-title-link" href="{D}">{TITLE}</a>
       <time class="event-date" datetime="2026-12-08">Tuesday, December 8, 2026</time>
       <time class="event-time-localized-start" datetime="2026-12-08">11:30 AM</time>
       <time class="event-time-localized-end" datetime="2026-12-08">2:30 PM</time>
       </article></html>"""
def collect(**kwargs):
    pages={s.FEED:listing(),D:detail(**kwargs)}
    return s.collect(source(),lambda url,accept:pages[url],now=NOW)
class CookingTests(unittest.TestCase):
    def test_correct_venue_and_time(self):
        rows=collect()
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["venue_address"],s.ADDRESS)
        self.assertEqual(row["category"],"learn")
        self.assertEqual(row["starts_at"],datetime(2026,12,8,16,30,tzinfo=timezone.utc).isoformat())
        self.assertEqual(row["ends_at"],datetime(2026,12,8,19,30,tzinfo=timezone.utc).isoformat())
        self.assertEqual(row["lat"],s.LAT)
        self.assertGreater(len(row["description"]),100)
        self.assertNotIn("image_url",row)
    def test_reject_robots_disallowed_endpoints(self):
        self.assertFalse(s.source_valid({**source(),"feed_url":s.FEED+"?format=json"}))
        self.assertFalse(s.event_url(D+"?format=ical"))
        self.assertFalse(s.event_url(D.replace(s.HOST,"evil.example")))
        self.assertTrue(s.event_url(D))
    def test_reject_wrong_venue_and_time(self):
        for value in ("39 New Orleans Road","37 New Orleans Avenue"):
            with self.assertRaisesRegex(ValueError,"michael_no_verified_events"):collect(addr=value)
        with self.assertRaisesRegex(ValueError,"michael_no_verified_events"):collect(start="12:30 PM")
    def test_reject_cancelled_and_private(self):
        with self.assertRaisesRegex(ValueError,"michael_no_verified_events"):collect(prose="Private event, members only. "+PROSE)
    def test_reject_detail_identity(self):
        with self.assertRaisesRegex(ValueError,"michael_no_verified_events"):collect(title="Different Event")
