"""Follow-on Anchorage batch20 calendars: original event data, venue, activity."""
from datetime import datetime, timezone
import json
import pytest

from roomquest import anchorage_batch20 as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
PHOTO = ("https://images.squarespace-cdn.com/content/v1/5d1d16338ed08b0001ebc5c8/"
         "1791242636317-ABCDE/Event.jpg")

def source(key):
    url, kind, adapter = ak.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind, platform_adapter=adapter, timezone=ak.ZONE)

def ms(value):
    return int(datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()*1000)

LOC_MAKING = dict(addressTitle="Making Space | Art Therapy &amp; Community",
                  addressLine1="1441 West Northern Lights Boulevard",
                  addressLine2="Anchorage, AK, 99503",
                  mapLat=61.1956075,mapLng=-149.9109034)
LOC_ART = dict(addressTitle="The Art Lounge AK - Suite 3",
               addressLine1="300 East Dimond Boulevard",
               addressLine2="Anchorage, AK, 99515",
               mapLat=61.1443709,mapLng=-149.8757727)
LOC_JOULE = dict(addressTitle="Thrive Integrative Medicine",
                 addressLine1="3835 Spenard Road",addressLine2="Anchorage, AK",
                 mapLat=61.1857685,mapLng=-149.9185543)

def event(key,title,url,location,**kw):
    x=dict(id="event-"+title[:23].lower().replace(" ","-"),
           workflowState=1,title=title,
           startDate=ms("2026-12-02T03:00:00Z"),
           endDate=ms("2026-12-02T05:00:00Z"),
           body="<p>A rich <strong>community</strong> activity with artist instruction.</p>",
           fullUrl=url,location=location,categories=[],assetUrl=PHOTO)
    x.update(kw)
    return x

def fetch(*rows,timezone_name=ak.ZONE):
    def _fetch(url,accept):
        assert url.endswith("?format=json") and accept=="application/json"
        return json.dumps(dict(website=dict(timeZone=timezone_name),
                               upcoming=list(rows),pagination=dict(nextPage=False)))
    return _fetch

def test_making_space_art_therapy_and_studio_sale():
    a=event(ak.MAKING,"Art as Hope: Open Studio Art Therapy",
            "/events/equinox-open-studio-art-therapy-kszkr-59a76-yx8sz-4ffzp",LOC_MAKING)
    b=event(ak.MAKING,"Studio Art Sale","/events/art-sale",LOC_MAKING)
    rows=ak.collect(source(ak.MAKING),fetch(a,b),now=NOW)
    assert [r["category"] for r in rows]==["create","arts_culture"]
    assert all(r["venue_address"]==ak.VENUES[ak.MAKING][1] for r in rows)
    assert all(r["lat"]==61.1956075 for r in rows)
    assert all("<" not in r["description"] for r in rows)

def test_art_lounge_full_categories_and_venue_variant():
    rows=[
        event(ak.ART,"Needle Felted Mushrooms for Beginners",
              "/classes-events/needle-felted-mushrooms-for-beginners",LOC_ART),
        event(ak.ART,"Witchy (Adjacent) Book Club",
              "/classes-events/witchy-adjacent-book-club-ah4bc-xyz",LOC_ART),
        event(ak.ART,"Beaver Moon: Full Moon Gathering with Stag & Moon",
              "/classes-events/beaver-moon",dict(LOC_ART,addressTitle="The Art Lounge AK - Suite 300")),
        event(ak.ART,"Mistletoe & Mirrorballs: A Disco Christmas Market",
              "/classes-events/mistletoe-mirrorballs-a-disco-christmas-market",LOC_ART),
    ]
    a=ak.collect(source(ak.ART),fetch(*rows),now=NOW)
    assert len(a)==4
    assert {r["category"] for r in a}=={"create","learn","hang_out","festival"}
    assert all(r["venue_address"]==ak.VENUES[ak.ART][1] for r in a)

def test_joule_bath_at_exact_publisher_facility_no_guess_zip():
    url=("/events/event-one-a6zdk-58wgg-wta8m-7nwlp-9g5pm-"
         "b66ck-92nb2-naxxc-trlbt-yh6g4-wztkg-xsg8t")
    row=event(ak.JOULE,"WAXING MOON SOUND BATH",url,LOC_JOULE)
    rows=ak.collect(source(ak.JOULE),fetch(row),now=NOW)
    assert len(rows)==1
    assert rows[0]["category"]=="health"
    assert rows[0]["venue_address"]=="3835 Spenard Road, Anchorage, AK"
    assert rows[0]["lat"]==61.1857685

def test_squarespace_nyc_offsite_truncation_and_missing_text_held():
    e=event(ak.ART,"Winter Candles Workshop with Stag & Moon",
            "/classes-events/winter-candles-workshop-with-stag-moon",LOC_ART)
    bad=[
        dict(e,location=dict(LOC_ART,mapLat=40.7207559)),
        dict(e,location=dict(LOC_ART,addressLine1="Unverified Street")),
        dict(e,body="<p></p>"),
        dict(e,body="x"*12001),
        dict(e,title="Mystery activity"),
        dict(e,fullUrl="https://attacker.example.com/events/mystery")
    ]
    for item in bad:
        assert ak.collect(source(ak.ART),fetch(item),now=NOW)==[]

def test_preview_uses_approved_hosts_and_full_event_description(monkeypatch):
    item=event(ak.MAKING,"Studio Art Sale","/events/art-sale",LOC_MAKING,
               body="<p>" + ("Learn and create art with community. "*100)+"</p>")
    def guarded(url,accept,**kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("www.makingspacetogether.com",)
        return fetch(item)(url,accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",guarded)
    result=preview_worker.preview_source(source(ak.MAKING))
    assert result["p_future_count"]==1
    assert result["p_venue_count"]==1
    assert len(result["p_events"][0]["description"])>2000
