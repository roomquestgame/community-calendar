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

def test_dance_two_public_upcoming_shows_with_exact_studio():
    location=dict(addressTitle="Alaska Dance Promotions",
                  addressLine1="300 E. Dimond Blvd, Ste 11A",
                  addressLine2="Anch, AK, 99515",
                  mapLat=61.1439843,mapLng=-149.8759416)
    thanksgiving=event(ak.DANCE,"Thanksgiving Dance Party",
                       "/events/thanksgiving-dance-party",location,
                       startDate=ms("2026-11-28T02:00:00Z"),endDate=ms("2026-11-28T04:00:00Z"))
    xmas=event(ak.DANCE,"Christmas Collection 2026",
               "/events/christmas",
               dict(location,addressLine1="300 East Dimond Blvd, Ste 11A",
                    addressLine2="Anchorage",mapLat=61.1444086,mapLng=-149.875721),
               startDate=ms("2026-12-19T02:00:00Z"),endDate=ms("2026-12-19T04:00:00Z"))
    result=ak.collect(source(ak.DANCE),fetch(thanksgiving,xmas),now=NOW)
    assert len(result)==2
    assert {e["category"] for e in result}=={"party","movies_theater"}
    assert all(e["venue_address"]==ak.VENUES[ak.DANCE][1] for e in result)
    assert all(e["lat"] is not None for e in result)
    assert not ak.collect(source(ak.DANCE),
                          fetch(dict(thanksgiving,location=dict(location,addressLine1="1 Wrong St"))),
                          now=NOW)


def test_dance_publisher_canonical_www_host_no_unsafe_redirect():
    assert ak.SOURCES[ak.DANCE][0] == "https://www.alaskadancepromotions.com/events"
    assert ak.ALLOWED_HOSTS[ak.DANCE] == ("www.alaskadancepromotions.com",)
    assert ak.event_url(ak.DANCE, "https://www.alaskadancepromotions.com/events/christmas")
    assert not ak.event_url(ak.DANCE, "https://alaskadancepromotions.com/events/christmas")


def test_dance_unexpanded_multi_month_series_held_and_suite_street_normalized():
    # Publisher sends FNDL as one October--June interval, not true weekly
    # occurrences. Do not invent dates or publish a 224-day dance "event".
    location=dict(addressTitle="Alaska Dance Promotions",
                  addressLine1="300 East Dimond Boulevard",
                  addressLine2="Anchorage, AK, 99515",
                  mapLat=61.1446067,mapLng=-149.881492)
    series=event(ak.DANCE,"FNDL Friday Night Dance Lounge",
                 "/events/fndl",location,
                 startDate=ms("2026-10-31T05:00:00Z"),
                 endDate=ms("2027-06-12T09:00:00Z"))
    one_night=event(ak.DANCE,"Thanksgiving Dance Party",
                    "/events/thanksgiving-dance-party",location,
                    startDate=ms("2026-11-28T06:00:00Z"),
                    endDate=ms("2026-11-28T10:00:00Z"))
    rows=ak.collect(source(ak.DANCE),fetch(series,one_night),now=NOW)
    assert len(rows)==1
    assert rows[0]["title"]=="Thanksgiving Dance Party"
    assert rows[0]["venue_address"]=="300 East Dimond Boulevard #11A, Anchorage, AK 99515"
    assert rows[0]["category"]=="party"
    assert rows[0]["lat"]==61.1446067
