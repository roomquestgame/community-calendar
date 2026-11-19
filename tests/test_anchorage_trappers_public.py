"""Alaska Trappers Eagle River original events: strict first-party safety tests."""
from datetime import datetime,timezone
import json
import pytest
from roomquest import anchorage_trappers_public as t

NOW=datetime(2026,11,19,22,0,tzinfo=timezone.utc)
SRC={"source_key":t.KEY,"feed_url":t.FEED,"kind":"html","platform_adapter":"html","timezone":t.ZONE}
def item(id=1377319):
    title,path=t.EVENTS[id]
    return {"id":id,"title":title,"url":t.ROOT+path,"timezone":t.ZONE,
      "start_date":"2026-12-05 12:30:00","end_date":"2026-12-05 17:00:00",
      "utc_start_date":"2026-12-05 21:30:00","utc_end_date":"2026-12-06 02:00:00",
      "description":"<p>A public winter survival workshop in Eagle River with winter travel safety and emergency shelter planning.</p>",
      "venue":{"venue":"VFW Post 9785","address":"10527 VFW Road","city":"Eagle River","state":"AK","zip":"99577"}}
def fetcher(events):
    def fetch(url,accept):
        if "/wp-json/" in url: return json.dumps({"events":events,"total_pages":1})
        assert t.event_url(t.KEY,url)
        ident=next(i for i,(_,path) in t.EVENTS.items() if t.ROOT+path==url)
        return "<h1 class='tribe-events-single-event-title'>"+t.EVENTS[ident][0]+"</h1>"
    return fetch
def test_public_event():
    rows=t.collect(SRC,fetcher([item()]),now=NOW)
    assert len(rows)==1
    r=rows[0]
    assert r["category"]=="learn" and r["timezone"]==t.ZONE and r["venue_address"]==t.VENUE[1]
    assert (r["lat"],r["lng"])==t.POINT and r["description"].startswith("A public")
    assert r.get("image_url") is None
def test_registration_rejected():
    with pytest.raises(ValueError,match="trappers_source_mismatch"):
        t.collect({**SRC,"timezone":"UTC"},fetcher([]),now=NOW)
@pytest.mark.parametrize("url",["https://example.org/event/bad",t.ROOT+"/event/missing/",
       t.ROOT+t.EVENTS[1377319][1]+"?evil=1"])
def test_bad_link(url):assert not t.event_url(t.KEY,url)
@pytest.mark.parametrize("field,value",[
 ("timezone","UTC"),("utc_start_date","2026-12-05 22:30:00"),
 ("title","Unverified Event"),("url","https://example.org/event/no"),
 ("start_date","2026-12-06 12:30:00")])
def test_reject_identity_and_time(field,value):
    e=item();e[field]=value
    with pytest.raises(ValueError): t.collect(SRC,fetcher([e]),now=NOW)
def test_hold_missing_description():
    e=item();e["description"]=""
    assert t.collect(SRC,fetcher([e]),now=NOW)==[]
def test_bad_venue():
    e=item();e["venue"]["address"]="10527 Fake Road"
    with pytest.raises(ValueError,match="trappers_venue_unverified"):
        t.collect(SRC,fetcher([e]),now=NOW)
def test_exclude_other_publisher_ids():
    e=item();e["id"]=1377323
    assert t.collect(SRC,fetcher([e]),now=NOW)==[]
def test_no_invented_recurrence():
    assert t.collect(SRC,fetcher([item()]),now=datetime(2027,2,1,tzinfo=timezone.utc))==[]
def test_no_truncation():
    e=item();e["description"]="<p>"+("Official original workshop details. "*150)+"</p>"
    assert len(t.collect(SRC,fetcher([e]),now=NOW)[0]["description"])>3000
