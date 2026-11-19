"""Anchorage Chamber GrowthZone original event validation tests."""
from datetime import datetime, timezone
import pytest
from bs4 import BeautifulSoup
from roomquest import anchorage_chamber_public as ch
NOW = datetime(2026,11,19,20,40,tzinfo=timezone.utc)

def _calendar(title,slug):
    return ('<html><title>Events Calendar - Anchorage Chamber</title>'
            '<a href="/events/details/'+slug+'">'+title+'</a></html>')

def _detail(title, desc, when, loc, fees="FREE for Members $20 for non-members"):
    return ('<html><div class="gz-event-details"><h1>'+title+'</h1>'
            '<div class="gz-details-links"><div class="col-sm-7">'
            '<div class="gz-event-description">'+desc+'</div></div>'
            '<div class="col-sm-5">Date and Time '+when+
            ' Location '+loc+' Fees/Admission '+fees+'</div></div></div></html>')

MIXER = "2026 Holiday Member Mixer Hosted by Anchorage Convention Centers"
SLUG = "2026-holiday-member-mixer-hosted-by-anchorage-convention-centers-15145"
PAGE = _detail(MIXER, "A public Anchorage Chamber holiday mixer at the Dena'ina Center with local networking, festive food and a celebration of the community.",
               "Thursday Dec 17, 2026 4:30 PM - 7:30 PM AKST",
               "Dena'ina Center, Third-floor")
SOURCE = {"source_key":ch.KEY,"feed_url":ch.FEED,"kind":"html",
          "platform_adapter":"html","timezone":ch.ZONE}

def _fetch(url, accept):
    if "?m=" in url:
        return _calendar(MIXER,SLUG)
    assert ch.event_url(ch.KEY,url)
    return PAGE

def test_public_mixer_complete_and_no_photo():
    rows=ch.collect(SOURCE,_fetch,now=NOW)
    assert len(rows)==1
    r=rows[0]
    assert r["category"]=="hang_out" and r["timezone"]=="America/Anchorage"
    assert r["venue_address"]=="600 W 7th Ave, Anchorage, AK 99501"
    assert "holiday mixer" in r["description"]
    assert r["starts_at"].startswith("2026-12-18T01:30")
    assert r.get("image_url") is None
    assert len(r["description"]) > 30

def test_wrong_registration_fails():
    with pytest.raises(ValueError,match="chamber_source_mismatch"):
        ch.collect({**SOURCE,"timezone":"UTC"},_fetch,now=NOW)

@pytest.mark.parametrize("bad",["", "https://evil.com/events/details/holiday-15145",
                                ch.ROOT+"/events/details/holiday-15145?redirect=1"])
def test_reject_event_link(bad):
    assert not ch.event_url(ch.KEY,bad)

def test_hold_missing_details_and_wrong_venue():
    url=ch.ROOT+"/events/details/"+SLUG
    assert ch._parse_detail(url,MIXER,_detail(MIXER,"","Thursday Dec 17, 2026 4:30 PM - 7:30 PM AKST","Dena'ina Center, Third-floor"),NOW) is None
    assert ch._parse_detail(url,MIXER,_detail(MIXER,"Public event","Thursday Dec 17, 2026 4:30 PM - 7:30 PM AKST","Unverified Hotel"),NOW) is None

def test_hold_invalid_date_and_private_meeting():
    url=ch.ROOT+"/events/details/"+SLUG
    assert ch._parse_detail(url,MIXER,_detail(MIXER,"Public event","Thursday Dec 17, 2026 4:30 PM - 7:30 PM AKDT","Dena'ina Center, Third-floor"),NOW) is None
    assert ch._parse_detail(url,MIXER,_detail(MIXER,"Members only","Thursday Dec 17, 2026 4:30 PM - 7:30 PM AKST","Dena'ina Center, Third-floor"),NOW) is None

def test_expired_no_synthetic_recurrence():
    assert ch.collect(SOURCE,_fetch,now=datetime(2027,2,1,tzinfo=timezone.utc))==[]

def test_original_publisher_geolocation():
    assert ch.VENUES["denaina"][3:] == (61.215542722741,-149.893601953117)
    assert ch.photo_url(ch.KEY,"https://example.com/image.jpg") is None

def test_full_description_not_truncated():
    long="Real public information. "*200
    url=ch.ROOT+"/events/details/"+SLUG
    page=_detail(MIXER,long,"Thursday Dec 17, 2026 4:30 PM - 7:30 PM AKST","Dena'ina Center, Third-floor")
    r=ch._parse_detail(url,MIXER,page,NOW)
    assert r and r["description"]==long.strip()
