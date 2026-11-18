"""AIGA Alaska: RSS + exact official event details, no guessed venue point."""
from datetime import datetime, timezone
import pytest

from roomquest import anchorage_batch20_aiga as aiga
from roomquest import preview_worker

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)
DETAIL_URL="https://alaska.aiga.org/event/after-hours-by-design-18/"
OTHER_URL="https://alaska.aiga.org/event/monthly-open-board-meeting-21/"

def source():
    return dict(source_key=aiga.KEY,feed_url=aiga.FEED,kind="rss",
                platform_adapter="wordpress",timezone=aiga.ZONE)

def feed():
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>After Hours by Design</title><link>{DETAIL_URL}</link>
<description><![CDATA[<div>We're designers connecting with the Alaska design community.</div>
<p>Come meet other creative people.</p>]]></description></item>
<item><title>Monthly Open Board Meeting</title><link>{OTHER_URL}</link>
<description>Committee meeting - not a general event.</description></item>
</channel></rss>'''

def html_event(address="310 West 36th Avenue",place="W xyz Lounge",
               start="2026-12-09 17:30:00",end="2026-12-09 19:00:00",
               tz="America/Anchorage"):
    return f'''<html><body>
    <var class="atc_date_start">{start}</var>
    <var class="atc_date_end">{end}</var>
    <var class="atc_timezone">{tz}</var>
    <var class="atc_title">After Hours by Design</var>
    <div class="event-location-name">{place}</div>
    <div class="event-location-address1">{address}</div>
    <div class="event-location-city-state-zip">Anchorage,  AK 99503</div>
    </body></html>'''

def guarded(url,accept):
    if url==aiga.FEED:
        assert accept=="text/xml"
        return feed()
    assert url==DETAIL_URL and accept=="text/html"
    return html_event()

def test_aiga_one_public_meetup_and_disallows_board_items():
    rows=aiga.collect(source(),guarded,now=NOW)
    assert len(rows)==1
    item=rows[0]
    assert item["venue_address"]=="310 West 36th Avenue, Anchorage, AK 99503"
    assert item["category"]=="hang_out"
    assert item["starts_at"]=="2026-12-10T02:30:00+00:00"
    assert item["lat"] is None and item["lng"] is None
    assert "<" not in item["description"] and "community" in item["description"]

def test_invalid_offsite_missing_times_or_non_anchorage_zone_held():
    for value in [
       html_event(address="1 Unverified Street"),
       html_event(place="Different bar"),
       html_event(end="2026-12-09 14:00:00"),
       html_event(tz="America/New_York"),
    ]:
        def fetch(url,accept):
            return feed() if url==aiga.FEED else value
        assert aiga.collect(source(),fetch,now=NOW)==[]

def test_unreviewed_feed_identity_and_external_urls_rejected():
    bad=dict(source(),feed_url="https://other.example.com/rss.xml")
    with pytest.raises(ValueError,match="unregistered_anchorage_aiga_source"):
        aiga.collect(bad,guarded,now=NOW)
    assert not aiga.event_url(aiga.KEY,DETAIL_URL+"?promo=true")
    assert not aiga.event_url(aiga.KEY,DETAIL_URL.replace("alaska.aiga.org","other.example.com"))
    assert aiga.photo_url(aiga.KEY,"https://alaska.aiga.org/picture.jpg") is None

def test_preview_never_bypasses_robots_or_allowed_host(monkeypatch):
    def fetch(url,accept,**kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("alaska.aiga.org",)
        return guarded(url,accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",fetch)
    result=preview_worker.preview_source(source())
    assert result["p_future_count"]==1
    assert result["p_events"][0]["category"]=="hang_out"
    assert result["p_venue_count"]==0
