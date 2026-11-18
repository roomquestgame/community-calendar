"""Anchorage batch20 first four first-party Squarespace collectors; no release."""
from datetime import datetime, timezone
import json

import pytest
from roomquest import anchorage_batch20 as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)

def millis(s):
    return int(datetime.fromisoformat(s.replace("Z","+00:00")).timestamp() * 1000)

def source(key):
    url, kind, adapter = ak.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind,
                platform_adapter=adapter, timezone=ak.ZONE)

MAGLOC = {"addressTitle":"Magnetic North Brewing Company",
          "addressLine1":"8861 Golovin Street","addressLine2":"Anchorage, AK, 99507",
          "mapLat":61.1405217,"mapLng":-149.8371101}
ACEHLOC = {"addressTitle":"ACEH Office","addressLine1":"3427 East Tudor Road, Suite A",
           "addressLine2":"Anchorage, AK, 99507",
           "mapLat":61.1816948,"mapLng":-149.8163217}
AWAKENLOC = {"addressTitle":"Awaken Church",
             "addressLine1":"5295 Juneau Street","addressLine2":"Anchorage, AK, 99518",
             "mapLat":61.1723554,"mapLng":-149.862599}
WINLOC = {"addressLine1":"","addressLine2":"",
          "mapLat":40.7207559,"mapLng":-74.0007613}
PHOTO = "https://images.squarespace-cdn.com/content/v1/59b9ecdabebafb8293096530/1791001020304-ABCDE/Sweater.jpg"

def event(title, location, full, **updates):
    row=dict(id=title.replace(" ","-")[:24], title=title, workflowState=1,
             startDate=millis("2026-12-03T03:30:00Z"),
             endDate=millis("2026-12-03T05:30:00Z"),
             body="<p>Join us for this <strong>celebration</strong> and a fun evening.</p>",
             categories=[], location=location, fullUrl=full, assetUrl=PHOTO)
    row.update(updates)
    return row

def fetch(*events, tz=ak.ZONE):
    def _f(url, accept):
        assert url in [prof[0] + "?format=json" for prof in ak.SOURCES.values()]
        assert accept=="application/json"
        return json.dumps({"website":{"timeZone":tz},
                           "upcoming":list(events), "pagination":{"nextPage":False}})
    return _f

def test_magnetic_three_categories_and_exact_venue():
    events=[
        event("Annual Ugly Christmas Sweater and Ornament Making Party",MAGLOC,
              "/events/2026/ugly-sweater-and-ornament-making-party"),
        event("December Stoplight Night",MAGLOC,"/events/2026/decemberstoplightnight"),
        event("Christmas Carol Sing-Along",MAGLOC,"/events/2026/christmas-carol-sing-along")]
    rows=ak.collect(source(ak.MAGNETIC),fetch(*events),now=NOW)
    assert len(rows)==3
    assert {r["category"] for r in rows}=={"create","hang_out","music"}
    assert all(r["venue_address"]==ak.VENUES[ak.MAGNETIC][1] for r in rows)
    assert all(r["lat"]==61.1405217 and r["lng"]==-149.8371101 for r in rows)
    assert all("<" not in r["description"] and r["description"].strip() for r in rows)

def test_winery_needs_onsite_text_and_never_nyc_point():
    good=event("Beaded Plant Sculpture",WINLOC,"/calendar/beaded-plant-sculpture",
               body="<p>Join us at 61 Degrees North Winery at the Anchorage studio for beaded art.</p>")
    rows=ak.collect(source(ak.WINERY),fetch(good),now=NOW)
    assert len(rows)==1 and rows[0]["category"]=="create"
    assert rows[0]["lat"] is None and rows[0]["lng"] is None
    assert rows[0]["venue_address"]=="5001 Arctic Blvd Suite 101, Anchorage, AK 99503"
    assert ak.collect(source(ak.WINERY),fetch(dict(good,body="<p>Unspecified studio in town.</p>")),now=NOW)==[]
    assert ak.collect(source(ak.WINERY),fetch(dict(good,location=dict(WINLOC,addressLine1="1 Unverified Lane"))),now=NOW)==[]

def test_aceh_only_public_volunteer_rows_with_exact_office():
    rows=ak.collect(source(ak.ACEH),fetch(
        event("December Volunteer Opportunity!",ACEHLOC,"/events/december-volunteer-opportunity"),
        event("Compliance Committee Meeting",ACEHLOC,"/events/committee-meeting"),
        event("Special Volunteer Opportunity!",dict(ACEHLOC,addressLine1="123 Wrong Street"),"/events/special-volunteer-opportunity")),now=NOW)
    assert len(rows)==1 and rows[0]["category"]=="give_back"
    assert rows[0]["venue_address"].startswith("3427 East Tudor Road")

def test_awaken_keeps_public_community_activities_not_non_events():
    events=[
        event("Ladies' Wreath-making Night!",AWAKENLOC,"/events/wreath"),
        event("Men's Breakfast",AWAKENLOC,"/events/2022/10/29/mens-breakfast-4hprr-lgmcs-s5zys-3gkka-wjfr2"),
        event("Awaken's Christmas Party!",AWAKENLOC,"/events/christmasparty"),
        event("Cookie Sunday!",AWAKENLOC,"/events/cookie-sunday"),
        event("No Sunday Morning Services",AWAKENLOC,"/events/no-services"),
        event("Christmas Eve Services",AWAKENLOC,"/events/christmas-eve")]
    rows=ak.collect(source(ak.AWAKEN),fetch(*events),now=NOW)
    assert len(rows)==4
    assert {x["category"] for x in rows}=={"create","food_drink","party"}
    assert all(x["lat"]==61.1723554 for x in rows)

def test_unknown_categories_private_addresses_and_images_held():
    good=event("December Stoplight Night",MAGLOC,"/events/2026/decemberstoplightnight")
    variants=[
        dict(good,location=dict(MAGLOC,mapLat=40.7207559)),
        dict(good,body="<p></p>"),
        dict(good,body="<p>"+"X"*12010+"</p>"),
        dict(good,fullUrl="https://example.com/events/2026/decemberstoplightnight"),
        dict(good,title="Private event December Stoplight Night"),
        dict(good,title="Unknown occasion"),
        dict(good,location=dict(MAGLOC,addressLine1="1 Wrong Lane"))]
    for candidate in variants:
        assert ak.collect(source(ak.MAGNETIC),fetch(candidate),now=NOW)==[]
    assert ak.photo_url(ak.MAGNETIC,PHOTO)==PHOTO
    assert ak.photo_url(ak.MAGNETIC,PHOTO+"?format=150w") is None
    assert ak.photo_url(ak.MAGNETIC,PHOTO.replace("Sweater.jpg","logo.jpg")) is None
    assert ak.photo_url(ak.MAGNETIC,PHOTO.replace("images.squarespace-cdn.com","example.com")) is None

def test_source_configs_and_timezones_bound():
    s=source(ak.MAGNETIC)
    with pytest.raises(ValueError,match="unregistered_anchorage_batch20_source"):
        ak.collect(dict(s,feed_url="https://other.example.com/events"),fetch(),now=NOW)
    with pytest.raises(ValueError,match="publisher_timezone_changed"):
        ak.collect(s,fetch(tz="America/New_York"),now=NOW)

def test_preview_stays_source_scoped_and_robots_safe(monkeypatch):
    event1=event("December Stoplight Night",MAGLOC,"/events/2026/decemberstoplightnight")
    def mocked(url, accept, **kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("magneticnorthbrewingco.com",)
        return fetch(event1)(url, accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",mocked)
    result=preview_worker.preview_source(source(ak.MAGNETIC))
    assert result["p_future_count"]==len(result["p_events"])==1
    assert result["p_venue_count"]==1
