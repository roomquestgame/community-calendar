from datetime import datetime, timezone
from json import dumps
import pytest
from roomquest import anchorage_four_valleys as m
from roomquest import preview_worker

NOW=datetime(2026,11,20,tzinfo=timezone.utc)
SRC={"source_key":m.KEY,"timezone":m.ZONE,"feed_url":m.FEED,"kind":"html","platform_adapter":"html"}
def fixture(title=m.TITLE, start="2026-11-22T22:00:00.000Z",address="102 Heavenly Valley Drive",desc=None):
    e={"@type":"Event","name":title,"startDate":start,"endDate":"2026-11-23T00:00:00.000Z",
       "eventStatus":"https://schema.org/EventScheduled","eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
       "url":m.DETAIL.rstrip("/"),"organizer":{"name":"Four Valleys Community School","url":m.ROOT},
       "location":{"@type":"Place","name":"Girdwood Chapel","address":{"streetAddress":address,"addressLocality":"Girdwood","addressRegion":"AK","postalCode":"99587","addressCountry":"US"}},
       "description": desc if desc is not None else "The Girdwood community holiday wreath making class is open to everyone. Neighbors and families create wreaths to support Girdwood Chapel. The workshop supplies wreath rings, wire and bows. Instructors guide the participants throughout the activity.",
       "image":m.EXPECTED_IMAGE}
    h='<html><body><h1>'+title+'</h1><script type="application/ld+json">'+dumps(e)+'</script></body></html>'
    return h+' ' * max(0,1101-len(h))
def index(is_community="false",date=None,href=None,repeats=1):
    s='<li class="event-item" data-community="'+is_community+'" data-title="holiday wreath making class" data-timestamp="'+str(date or int(m.START.timestamp()*1000))+'"><a href="'+(href or m.SOURCE_SLUG)+'">Holiday Wreath Making Class</a></li>'
    x='<html>'+s*repeats+'</html>'
    return x+' ' * max(0,1200-len(x))
def collect(i=None,p=None,source=None,now=NOW):
    return m.collect(source or SRC, lambda url,accept: i or index() if url==m.FEED else p or fixture(),now=now)
def test_original():
    a=collect()
    assert len(a)==1
    e=a[0]
    assert e["id"]=="fourvalleys:holiday-wreath-making:2026-11-22"
    assert e["event_url"]==m.DETAIL and e["category"]=="create"
    assert e["venue_address"]==m.VENUE[1] and (e["lat"],e["lng"])==m.POINT
    assert len(e["description"])>=200 and not e.get("image_url")
@pytest.mark.parametrize("change",[{"source_key":"impostor"},{"timezone":"UTC"},{"kind":"ics"},{"feed_url":"https://wrong.invalid"}])
def test_source_identity(change):
    with pytest.raises(ValueError,match="fvcs_source_mismatch"):collect(source={**SRC,**change})
@pytest.mark.parametrize("bad",[index(is_community="true"),index(date=111),index(repeats=2),index(href="/events/impostor")])
def test_index_changes(bad):
    with pytest.raises(ValueError,match="fvcs_original_dated_listing_changed"):collect(i=bad)
@pytest.mark.parametrize("bad",[fixture(title="Wrong"),fixture(start="2025-11-22T22:00:00.000Z"),fixture(address="Unknown Ave"),fixture(desc="Tiny")])
def test_detail_changes(bad):
    with pytest.raises(ValueError):collect(p=bad)
def test_expired():
    assert collect(now=datetime(2026,11,24,tzinfo=timezone.utc))==[]
def test_urls_media():
    assert m.event_url(m.KEY,m.DETAIL)
    assert not m.event_url(m.KEY,m.DETAIL+"?bad=1")
    assert not m.event_url(m.KEY,"https://other.invalid/x")
    assert m.photo_url(m.KEY,m.EXPECTED_IMAGE) is None
def test_preview_respects_robots(monkeypatch):
    seen=[]
    def get(url,accept,**kwargs):
        seen.append((url,kwargs))
        return index() if url==m.FEED else fixture()
    monkeypatch.setattr(preview_worker,"fetch_publisher",get)
    ans=preview_worker.preview_source(SRC)
    assert ans["p_error"] is None and ans["p_future_count"]==1
    assert len(seen)==2 and all(v["respect_robots"] is True and v["allowed_hosts"]==m.ALLOWED_HOSTS[m.KEY] for _,v in seen)
