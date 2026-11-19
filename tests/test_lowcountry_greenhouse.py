"""Source-bound publisher HTML/ICS evidence checks for Greenhouse Bluffton."""
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo
import json
import unittest
from icalendar import Calendar, Event
from roomquest import lowcountry_greenhouse as h

URL = "https://www.greenhousebluffton.com/events/karaoke-night-bluffton"
UID = "6af6353a3efafe1fdc8a029d@squarespace.com"


def source():
    return dict(source_key=h.KEY,feed_url=h.URL,kind="html",
                platform_adapter="html",timezone=h.ZONE)


def fixture(*,bad_geo=False,bad_date=False):
    start=(datetime.now(ZoneInfo(h.ZONE))+timedelta(days=2)).replace(
        hour=21,minute=0,second=0,microsecond=0)
    end=start+timedelta(hours=3)
    date_text="November 1" if bad_date else start.strftime("%B %-d")
    ld={"@type":"Event","name":"Karaoke Night","startDate":start.isoformat(),
        "endDate":end.isoformat(),"location":{"name":h.VENUE,
        "address":"1260 May River Road\nBluffton, South Carolina, 29910\nUnited States"}}
    meta=''.join('<meta property="og:%s" content="%s"/>' % (k,v) for k,v in [
        ("latitude",str(h.LAT)),("longitude",str(h.LNG)),
        ("street-address","1260 May River Road"),("locality","Bluffton"),
        ("region","South Carolina"),("postal-code","29910")])
    html=(meta+'<script type="application/ld+json">'+json.dumps(ld)+'</script>'+
          '<article class="eventitem eventitem--multiday"><h1 class="eventitem-title">'
          'Karaoke Night</h1><div class="sqs-html-content"><p>Join us for karaoke on '
          +date_text+' at our restaurant. Bring your friends and enjoy music all night.</p>'
          '<p>Meet at the Main Dining Room at 1260 May River Road, Bluffton, SC.</p>'
          '</div></article>')
    cal=Calendar()
    e=Event()
    e.add('uid',UID)
    e.add('dtstart',start.astimezone(timezone.utc))
    e.add('dtend',end.astimezone(timezone.utc))
    e.add('geo',(1.0,1.0) if bad_geo else (h.LAT,h.LNG))
    e.add('location','Greenhouse Restaurant Bluffton, 1260 May River Road, Bluffton, South Carolina, 29910, United States')
    cal.add_component(e)
    pages={h.URL:'<a class="eventlist-title-link" href="/events/karaoke-night-bluffton">Karaoke</a>',
           URL:html,URL+'?format=ical':cal.to_ical()}
    def fetch(url,_accept):
        if url not in pages:
            raise AssertionError('unexpected publisher request '+url)
        return pages[url]
    return fetch


class GreenhouseTests(unittest.TestCase):
    def test_original_first_party_canary_full_prose_street_geo_category(self):
        rows=h.collect(source(),fixture())
        self.assertEqual(len(rows),1)
        e=rows[0]
        self.assertEqual(e['title'],'Karaoke Night')
        self.assertEqual(e['venue_address'],h.STREET)
        self.assertEqual((e['lat'],e['lng']),(h.LAT,h.LNG))
        self.assertEqual(e['category'],'music')
        self.assertIn('Bring your friends',e['description'])
        self.assertEqual(e['event_url'],URL)
        self.assertFalse(e.get('image_url'))
        self.assertIn('squarespace.com:',e['id'])

    def test_hold_different_publisher_date_or_coordinates(self):
        self.assertEqual(h.collect(source(),fixture(bad_geo=True)),[])
        self.assertEqual(h.collect(source(),fixture(bad_date=True)),[])

    def test_reject_other_publisher_hosts_or_feed_config(self):
        self.assertFalse(h.event_url('https://evil.example/events/karaoke-night-bluffton'))
        self.assertFalse(h.event_url(URL+'?format=json'))
        self.assertFalse(h.source_valid({**source(),'feed_url':URL}))
        with self.assertRaisesRegex(ValueError,'unregistered_greenhouse_source'):
            h.collect({**source(),'timezone':'UTC'},lambda *_:'') 


if __name__=='__main__':
    unittest.main()
