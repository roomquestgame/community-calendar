"""Santa Cruz Public Libraries: native feed identity, detail, addresses and geo."""
from datetime import datetime,timezone
import pytest
from icalendar import Calendar,Event
from roomquest import santa_cruz_libnet as lib

NOW=datetime(2026,11,18,18,0,tzinfo=timezone.utc)
START=datetime(2026,11,21,20,0,tzinfo=timezone.utc)
END=datetime(2026,11,21,22,0,tzinfo=timezone.utc)
SOURCE={"source_key":lib.KEY,"feed_url":lib.URL,"kind":"ical",
        "platform_adapter":"ical","timezone":lib.ZONE}
LONG_PROSE=("Join other community members for a guided arts and crafts workshop at "
 "the library. Volunteers will introduce hands-on projects, demonstrate a range "
 "of techniques, and help participants make original pieces to take home.")

def feed(*,location="Scotts Valley Branch - Study Room A",geo=(37.0495679,-122.0286499)):
 c=Calendar();c.add("version","2.0");c.add("prodid","-//SCPL//Event Calendar//EN")
 e=Event();e.add("uid","17823456");e.add("summary","Craft Workshop")
 e.add("dtstart",START);e.add("dtend",END);e.add("status","CONFIRMED")
 e.add("description","Join us at the library for crafts.")
 e.add("location",location);e.add("geo",geo);c.add_component(e)
 return c.to_ical().decode()

def page(*,title="Craft Workshop",start="2026-11-21 12:00:00",prose=LONG_PROSE):
 def block(t):return '<div class="amh-block amh-text"><div class="amh-content">'+t+'</div></div>'
 return ("<html><body>"+block(title)
   +block(start+" 2026-11-21 14:00:00 America/Los_Angeles "+title)
   +block("Scotts Valley Branch Study Room A")+block("Join us for crafts")
   +block(prose)+block("AGE GROUP: | All Ages | EVENT TYPE: | Arts & Crafts | Workshops |")
   +"</body></html>")

def fetch_fixture(url,accept):
 if url==lib.URL:
  assert accept=="text/calendar";return feed()
 assert lib.event_url(url) and accept=="text/html"
 return page()

def test_native_feed_exact_identity():
 assert lib.URL.startswith("https://santacruzpl.libnet.info/feeds?data=")
 assert lib.event_url("https://santacruzpl.libnet.info/event/17823456")
 for u in ("https://fake.libnet.info/event/17823456",
           "http://santacruzpl.libnet.info/event/17823456",
           "https://santacruzpl.libnet.info/event/17823456?x=1"):
  assert not lib.event_url(u)
 with pytest.raises(ValueError,match="unregistered"):
  lib.collect({**SOURCE,"feed_url":lib.URL+"f"},fetch_fixture,now=NOW)

def test_full_publisher_detail_location_category_and_geo():
 rows=lib.collect(SOURCE,fetch_fixture,now=NOW)
 assert len(rows)==1
 x=rows[0]
 assert x["starts_at"]==START.isoformat()
 assert x["venue_address"]=="251 Kings Village Road, Scotts Valley, CA 95066"
 assert "guided arts and crafts workshop" in x["description"]
 assert x["publisher_categories"]==["Arts & Crafts","Workshops"]
 assert x["location_provenance"]=="official_scpl_branch_directory"
 assert x["details_evidence_url"]=="https://santacruzpl.libnet.info/event/17823456"
 assert x.get("lat")==pytest.approx(37.0495679)
 assert "image_url" not in x

def test_hold_virtual_missing_narrative_or_time_mismatch():
 def virtual(url,accept):
  if url==lib.URL:return feed(location="Virtual Branch - Zoom")
  raise AssertionError("virtual listings must not fetch detail")
 assert lib.collect(SOURCE,virtual,now=NOW)==[]
 assert lib.collect(SOURCE,lambda u,a:feed() if u==lib.URL else page(prose="Short."),now=NOW)==[]
 assert lib.collect(SOURCE,lambda u,a:feed() if u==lib.URL else page(start="2026-11-21 11:00:00"),now=NOW)==[]

def test_zero_coordinates_are_not_map_pins():
 rows=lib.collect(SOURCE,lambda u,a:feed(geo=(0,0)) if u==lib.URL else page(),now=NOW)
 assert len(rows)==1 and rows[0].get("lat") is None and rows[0].get("lng") is None

def test_publisher_evidence_and_preview_route(monkeypatch):
 from roomquest.publisher_evidence import family
 from roomquest import preview_worker
 assert family(lib.KEY,"https://santacruzpl.libnet.info/event/17823456")=="santa_cruz_libnet"
 assert family(lib.KEY,"https://fake.example/event/17823456") is None
 monkeypatch.setattr(preview_worker,"fetch_publisher",lambda url,accept,**kw:fetch_fixture(url,accept))
 out=preview_worker.preview_source(SOURCE)
 assert out["p_future_count"]==1 and out["p_error"] is None
