"""Dirty Apron: two first-party cooking calendars, no invented photo or geo."""
from datetime import datetime, timezone
import json
import pytest

from roomquest import anchorage_batch20_dirty_apron as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)

def source():
    base, kind, adapter = ak.SOURCES[ak.KEY]
    return dict(source_key=ak.KEY, feed_url=base, kind=kind,
                platform_adapter=adapter, timezone=ak.ZONE)

def ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)

def event(group, name, slug, n):
    return dict(id="publisher-" + str(n), workflowState=1,
                title=name, fullUrl="/" + group + "/" + slug,
                startDate=ms("2026-12-05T21:00:00Z"),
                endDate=ms("2026-12-06T00:00:00Z"),
                body="<p>Learn with Chef Amy in a hands-on cooking class with delicious pies and baked breads.</p>",
                location=dict(mapLat=61.1883351, mapLng=-149.8975481,
                              addressTitle="", addressLine1="", addressLine2=""),
                categories=[], assetUrl="https://images.squarespace-cdn.com/unused.jpg")

def page(title, street="3565 Arctic Blvd, Ste D3"):
    return ('<html><head><title>' + title + ' — The Dirty Apron</title></head>'
            '<body><article>Join our chef for a hands-on cooking class in our kitchen.</article>'
            '<footer>Stay Posted ' + street
            + ' | Anchorage, Alaska 99503 The Dirty Apron</footer></body></html>')

def fetch_map(events_adult, events_kids, *, site_title=None, timezone=ak.ZONE):
    maps = {}
    for group, events in ((ak.ADULT, events_adult), (ak.KIDS, events_kids)):
        maps[group+"?format=json"] = json.dumps(dict(
            website=dict(timeZone=timezone), upcoming=events,
            pagination=dict(nextPage=False)))
        for e in events:
            url=ak.ROOT+e["fullUrl"]
            maps[url]=page(site_title or e["title"])
    def _fetch(url, accept):
        if url.endswith("?format=json"):
            assert accept=="application/json"
        else:
            assert accept=="text/html"
        return maps[url]
    return _fetch

def test_two_calendars_are_one_publisher_with_street_but_no_guessed_gps():
    adult = event("adult-cooking-classes", "Flavors of Nepal with Chef Kristen",
                  "nepalese-momos-with-chef-kristen", 1)
    family = event("kids-cooking-classes", "Family Class: Taco Teamwork with Chef Amy",
                   "u6nu6aw0wpmdnxvb0i86vx9snrjzrj", 2)
    rows=ak.collect(source(), fetch_map([adult],[family]),now=NOW)
    assert len(rows)==2
    assert {row["id"] for row in rows}=={"publisher-1","publisher-2"}
    assert all(row["venue_address"]==ak.VENUE[1] and row["lat"] is None
               and row["lng"] is None for row in rows)
    assert all(row["category"]=="create" and row["timezone"]==ak.ZONE for row in rows)
    assert all(row.get("image_candidate_url") is None for row in rows)
    assert all(row["reason"]=="missing_verified_venue_geo" for row in rows)
    assert all("hands-on" in row["description"] for row in rows)

def test_excludes_sold_out_closed_offsite_or_mismatched_venue():
    base=event("adult-cooking-classes","Flavors of Nepal with Chef Kristen",
               "nepalese-momos-with-chef-kristen",3)
    for change in (
        dict(title="SOLD OUT: Flavors of Nepal with Chef Kristen"),
        dict(title="Closed For Christmas Holiday"),
        dict(location=dict(base["location"],addressLine1="123 Other Street")),
        dict(body="<p>Hosted at another venue by Chef Kristen. Off-site.</p>"),
        dict(fullUrl="https://unrelated.com/adult-cooking-classes/chef"),
        dict(fullUrl="/kids-cooking-classes/a-different-event"),
        dict(endDate=ms("2026-12-10T00:00:00Z")),
    ):
        x=dict(base,**change)
        if x["fullUrl"] != base["fullUrl"]:
            assert ak.collect(source(),fetch_map([x],[]),now=NOW)==[]
        else:
            assert ak.collect(source(),fetch_map([x],[]),now=NOW)==[]
    assert ak._verified_page(ak.ROOT+base["fullUrl"],base["title"],page(base["title"],street="12 Other Street")) is False

def test_source_tuple_edition_and_wrong_timezone_fail_closed():
    base=event("adult-cooking-classes","Flavors of Nepal with Chef Kristen",
               "nepalese-momos-with-chef-kristen",3)
    with pytest.raises(ValueError,match="unregistered_dirty_apron_source"):
        ak.collect(dict(source(),feed_url="https://evil.example/"),fetch_map([base],[]),now=NOW)
    with pytest.raises(ValueError,match="publisher_timezone_changed"):
        ak.collect(source(),fetch_map([base],[],timezone="America/New_York"),now=NOW)

def test_guarded_preview_checks_both_calendars_and_original_detail_pages(monkeypatch):
    base=event("adult-cooking-classes","Flavors of Nepal with Chef Kristen",
               "nepalese-momos-with-chef-kristen",4)
    fixture=fetch_map([base],[])
    urls=[]
    def guarded(url, accept, **kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("www.thedirtyapron.com",)
        urls.append(url)
        return fixture(url,accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",guarded)
    out=preview_worker.preview_source(source())
    assert out["p_future_count"]==1 and out["p_venue_count"]==0
    assert out["p_events"][0]["event_url"].startswith(ak.ROOT)
    assert ak.ADULT+"?format=json" in urls and ak.KIDS+"?format=json" in urls
    assert ak.ROOT+base["fullUrl"] in urls
