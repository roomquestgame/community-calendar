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
    ass...[truncated]