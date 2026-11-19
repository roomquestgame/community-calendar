"""Verify Bargetto source, two distinct daytime occurrences and provenance."""
import json
from datetime import datetime, timezone
import pytest

from roomquest import santa_cruz_bargetto as s

NOW=datetime(2026,11,18,23,tzinfo=timezone.utc)
SOURCE={"source_key":s.KEY, "feed_url":s.URL, "kind":"html", "platform_adapter":"html","timezone":s.ZONE}
EVENT={"@type":"Event","name":"Art in the Cellars","location":{"@type":"Place","name":"Historic Winery & Tasting Room"},
       "url":s.DETAIL.replace("www.",""),"startDate":"2026-12-05T19:00:00.000Z","endDate":"2026-12-07T01:00:00.000Z"}

def listing(item=None):
    page={"@type":"CollectionPage","mainEntity":{"@type":"ItemList","itemListElement":[{"item":item or EVENT}]}}
    return '<html><body><script type="application/ld+json">'+json.dumps(page)+'</script></body></html>'

def detail(street="3535 N Main Street, Soquel, CA",time="Saturday & Sunday: 11am - 5pm",closed=""):
    return f"""<html><body><main>Art in the Cellars December 5 - 6 Soquel Historic Winery {street}
    {time} {closed}<div class="prose">
    Explore a world of creativity in the heart of our historic wine cellars.
    Discover a stunning selection of unique, hand crafted gifts from over 50 talented
    artists and vendors. There are handmade pieces for every holiday shopping list.
    Admission is free and wine tastings with a Festival Glass are available.
    </div></main></body></html>"""

def run(list_html=None,detail_html=None):
    return s.collect(SOURCE,lambda u,a:(list_html or listing()) if u==s.URL else (detail_html or detail()),now=NOW)

def test_two_separate_original_daytime_occurrences():
    rows=run()
    assert len(rows)==2 and len(set(x["id"] for x in rows))==2
    assert rows[0]["starts_at"]=="2026-12-05T19:00:00+00:00"
    assert rows[0]["ends_at"]=="2026-12-06T01:00:00+00:00"
    assert rows[1]["starts_at"]=="2026-12-06T19:00:00+00:00"
    assert rows[1]["ends_at"]=="2026-12-07T01:00:00+00:00"
    assert all(x["venue_address"]==s.ADDRESS and x["lat"] is None and x["lng"] is None for x in rows)
    assert all(len(x["description"])>180 and x["event_url"]==s.DETAIL for x in rows)

def test_no_offsite_urls_and_bad_source_registration():
    from roomquest.publisher_evidence import family
    assert family(s.KEY,s.DETAIL)=="santa_cruz_bargetto"
    assert family(s.KEY,s.DETAIL.replace("www.bargetto.com","attacker.example")) is None
    with pytest.raises(ValueError,match="unregistered"):
        s.collect(SOURCE|{"source_key":"changed"},lambda u,a:listing(),now=NOW)

def test_missing_street_and_calendar_drift_are_held():
    with pytest.raises(ValueError,match="detail_drift"):
        run(detail_html=detail(street="Somewhere in Soquel"))
    with pytest.raises(ValueError,match="detail_drift"):
        run(detail_html=detail(time="Any time"))
    modified=EVENT|{"endDate":"2026-12-06T01:00:00.000Z"}
    with pytest.raises(ValueError,match="calendar_detail_date_drift"):
        run(list_html=listing(modified))

def test_no_closed_event_or_missing_narrative():
    with pytest.raises(ValueError,match="detail_drift_or_closed"):
        run(detail_html=detail(closed="CANCELLED"))
    with pytest.raises(ValueError,match="missing_original_description"):
        run(detail_html=detail().replace("Explore a world of creativity","Short notice for"))

