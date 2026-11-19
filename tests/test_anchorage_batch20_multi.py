"""Anchorage batch20 multi-venue comedy and Audubon publisher gates."""
from datetime import datetime, timezone
import json

import pytest

from roomquest import anchorage_batch20_multi as ak
from roomquest import preview_worker

NOW = datetime(2026,11,18,12,tzinfo=timezone.utc)

def source(key):
    base,kind,adapter=ak.SOURCES[key]
    return dict(source_key=key,feed_url=base,kind=kind,platform_adapter=adapter,timezone=ak.ZONE)

def msec(raw):
    return int(datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp()*1000)

def ev(key,title,location,url,**changes):
    x=dict(id="id-"+title[:20].replace(" ","-"),workflowState=1,title=title,
           startDate=msec("2026-12-11T03:00:00Z"),endDate=msec("2026-12-11T05:00:00Z"),
           body="<p>A full local evening with stand-up comedy and community learning.</p>",
           fullUrl=url,location=location,categories=[],assetUrl=(
               "https://images.squarespace-cdn.com/content/v1/5d1d16338ed08b0001ebc5c8/"
               "1791242636317-ABCDE/Event.jpg"))
    x.update(changes)
    return x

BEAR = dict(addressTitle="Bear Tooth Theatrepub",addressLine1="1230 West 27th Avenue",
            addressLine2="Anchorage, AK, 99503",mapLat=61.1959291,mapLng=-149.907323)
SITKA = dict(addressTitle="Mean Queen",addressLine1="205 Harbor Drive",
             addressLine2="Sitka, Alaska, 99835",mapLat=57.049353,mapLng=-135.336341)
AUDUBON = dict(addressTitle="",addressLine1="1014 Energy Court",
               addressLine2="Anchorage, Alaska, 99508",
               mapLat=61.1902270,mapLng=-149.863681)

def fetch(*events, zone=ak.ZONE):
    def _f(url,accept):
        assert url.endswith("?format=json")
        assert accept=="application/json"
        return json.dumps(dict(website=dict(timeZone=zone),
                               upcoming=list(events),pagination=dict(nextPage=False)))
    return _f

def test_comedy_venues_are_event_specific_and_nearby_only():
    bear=ev(ak.COMEDY,"Vitamin Come(D)y with Sam Miller @ Bear Tooth Theatrepub",
            BEAR,"/events/vitamin-comedy-with-sam-miller-bear-tooth")
    bad=ev(ak.COMEDY,"Sam Miller @ Mean Queen",SITKA,"/events/sam-miller-mean-queen")
    one=ak.collect(source(ak.COMEDY),fetch(bear,bad),now=NOW)
    assert len(one)==1
    assert one[0]["category"]=="movies_theater"
    assert one[0]["lat"]==61.1959291
    assert one[0]["venue_name"]=="Bear Tooth Theatrepub"
    assert one[0]["venue_address"].startswith("1230 West 27th Avenue")
    assert "comedy" in one[0]["description"]

def test_audubon_public_program_not_nyc_location():
    good=ev(ak.AUDUBON,"December Evening Program",AUDUBON,
            "/annual-events-1/december-evening-program",
            body="<p>Join Anchorage Audubon for birding education and community.</p>")
    wrong=ev(ak.AUDUBON,"Winter Walk at Campbell Creek Science Center",
             dict(AUDUBON,addressLine1="",mapLat=40.7207559,mapLng=-74.0007613),
             "/annual-events-1/winter-walk-at-campbell-creek-science-center")
    out=ak.collect(source(ak.AUDUBON),fetch(good,wrong),now=NOW)
    assert len(out)==1
    assert out[0]["venue_address"]=="1014 Energy Court, Anchorage, AK 99508"
    assert out[0]["category"]=="hang_out"
    assert out[0]["lat"]==61.190227

def test_ambiguous_event_address_incomplete_descriptions_and_other_hosts_held():
    base=ev(ak.COMEDY,"Live Stand-up Comedy Night",BEAR,"/events/live-standup-comedy-night")
    variants=[
        dict(base,location=dict(BEAR,addressLine1="No street")),
        dict(base,location=dict(BEAR,mapLat=40.7207559)),
        dict(base,location=dict(BEAR,addressLine2="Sitka, Alaska, 99835")),
        dict(base,title="Private Event"),
        dict(base,title="Mystery Party",body="<p>No activity description.</p>"),
        dict(base,body="<p></p>"),
        dict(base,body="x"*12001),
        dict(base,fullUrl="https://other.example.com/events/comedy-night"),
    ]
    for item in variants:
        assert ak.collect(source(ak.COMEDY),fetch(item),now=NOW)==[]

def test_identity_rights_timezone_are_source_scoped():
    photo=("https://images.squarespace-cdn.com/content/v1/5d1d16338ed08b0001ebc5c8/"
           "1791242636317-ABCDE/Event.jpg")
    assert ak.photo_url(ak.COMEDY,photo)==photo
    assert ak.photo_url(ak.COMEDY,photo+"?format=150w") is None
    assert ak.photo_url(ak.COMEDY,photo.replace("Event.jpg","favicon.jpg")) is None
    assert ak.photo_url(ak.COMEDY,photo.replace("images.squarespace-cdn.com","evil.example")) is None
    with pytest.raises(ValueError,match="unregistered_anchorage_batch20_multi_source"):
        ak.collect(dict(source(ak.COMEDY),feed_url="https://wrong.example.com/events"),
                   fetch(),now=NOW)
    with pytest.raises(ValueError,match="publisher_timezone_changed"):
        ak.collect(source(ak.COMEDY),fetch(zone="America/New_York"),now=NOW)

def test_source_preview_honors_robots_and_host(monkeypatch):
    item=ev(ak.AUDUBON,"November Evening Program",AUDUBON,
            "/annual-events-1/november-evening-program")
    def mocked(url,accept,**kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("www.anchorageaudubon.org",)
        return fetch(item)(url,accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",mocked)
    row=preview_worker.preview_source(source(ak.AUDUBON))
    assert row["p_future_count"]==1
    assert len(row["p_events"])==1
    assert row["p_venue_count"]==1


REFUGE = dict(addressTitle="Refuge Coffee",addressLine1="3309 Spenard Road",
              addressLine2="Anchorage, Alaska, 99503",
              mapLat=61.1901288,mapLng=-149.9058736)
REFUGE_BODY = "<p>Join us for an Open Mic Night at Refuge Coffee hosted by our dear friend Yody! All ages and talents welcome, this is a family friendly event.</p>"

def refuge_event(date, suffix):
    # Publisher source records: separate original IDs, URLs and dated occurrences.
    return ev(ak.REFUGE,"Open Mic Night ",REFUGE,
              "/events/open-mic-night-"+suffix,
              id="publisher-refuge-"+suffix,
              body=REFUGE_BODY,
              startDate=msec(date+"T02:00:00Z"),
              endDate=msec(date+"T05:00:00Z"))

def test_refuge_three_original_occurrences_are_music_with_real_site_points():
    rows=ak.collect(source(ak.REFUGE),fetch(
        refuge_event("2026-11-21","nov20"),
        refuge_event("2026-12-05","dec04"),
        refuge_event("2026-12-19","dec18")),now=NOW)
    assert len(rows)==3
    assert len({(x["id"],x["starts_at"]) for x in rows})==3
    assert all(x["category"]=="music" for x in rows)
    assert all(x["venue_address"]=="3309 Spenard Road, Anchorage, AK 99503" for x in rows)
    assert all(x["lat"]==61.1901288 and x["lng"]==-149.9058736 for x in rows)
    assert all("All ages and talents welcome" in x["description"] for x in rows)
    assert all(x.get("image_candidate_url") is None for x in rows)
    assert all(x["timezone"]=="America/Anchorage" for x in rows)

def test_refuge_requires_first_party_street_gps_tz_and_event_perm_link():
    base=refuge_event("2026-11-21","nov20")
    cases=[
        dict(base,location=dict(REFUGE,addressLine1="")),
        dict(base,location=dict(REFUGE,addressLine1="3300 Spenard Road")),
        dict(base,location=dict(REFUGE,mapLat=40.7207559,mapLng=-74.0007613)),
        dict(base,location=dict(REFUGE,addressLine2="Milwaukee, WI, 99503")),
        dict(base,location=dict(REFUGE,addressTitle="Other Cafe")),
        dict(base,title="Private Booking"),
        dict(base,title="Unspecified Gathering"),
        dict(base,body="<p></p>"),
        dict(base,fullUrl="https://evil.example/events/open-mic-night-nov20"),
        dict(base,fullUrl="/unrelated/event/open-mic-night-nov20"),
        dict(base,startDate=msec("2026-11-21T05:00:00Z")),
    ]
    for item in cases:
        assert ak.collect(source(ak.REFUGE),fetch(item),now=NOW)==[]
    with pytest.raises(ValueError,match="publisher_timezone_changed"):
        ak.collect(source(ak.REFUGE),fetch(base,zone="America/New_York"),now=NOW)

def test_refuge_preview_uses_robots_guard_and_exact_host(monkeypatch):
    item=refuge_event("2026-11-21","nov20")
    def guarded_fetch(url,accept,**kwargs):
        assert url=="https://www.refugecoffeeak.com/events/?format=json"
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("www.refugecoffeeak.com",)
        return fetch(item)(url,accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",guarded_fetch)
    row=preview_worker.preview_source(source(ak.REFUGE))
    assert row["p_future_count"]==1
    assert row["p_venue_count"]==1
    assert row["p_events"][0]["category"]=="music"
