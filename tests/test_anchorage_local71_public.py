"""Guarded Local71 original public source and disallowed near-misses."""
import json
from datetime import datetime, timezone
import pytest
from roomquest import anchorage_local71_public as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 19, 19, 45, tzinfo=timezone.utc)
EVENT = {
 "id":10834,"title":"🏈 Thursday Night Football with Tradeswomen of Alaska! (12/10/26)",
 "status":"publish","hide_from_listings":False,"all_day":False,
 "timezone":"America/Anchorage","start_date":"2026-12-10 16:00:00",
 "end_date":"2026-12-10 18:00:00","utc_start_date":"2026-12-11 01:00:00",
 "utc_end_date":"2026-12-11 03:00:00",
 "url":ak.REVIEWED[10834]["url"],
 "description":"<p>Come join Tradeswomen of Alaska for Thursday Night Football at The Peanut Farm! Enjoy food, company and football.</p>",
 "venue":{"id":7877,"venue":"The Peanut Farm","address":"5227 Old Seward Hwy","city":"Anchorage","state":"AK","zip":"99518"},
}
DETAIL="<html><head><title>Thursday Night Football with Tradeswomen of Alaska</title></head><body>Thursday Night Football at The Peanut Farm, 5227 Old Seward Hwy Anchorage Alaska</body></html>"

def source():
 return {"source_key":ak.KEY, "feed_url":ak.FEED,
         "kind":"json","platform_adapter":"wordpress","timezone":ak.ZONE}

def fetch(e=None, detail=DETAIL):
 e = EVENT if e is None else e
 def _f(url, accept):
  if url==ak.FEED:
   assert accept == "application/json"
   return json.dumps({"events":[e]})
  assert url==ak.REVIEWED[10834]["url"] and accept=="text/html"
  return detail
 return _f

def test_verified_one_future_event_complete_original_and_geo():
 rows=ak.collect(source(),fetch(),now=NOW)
 assert len(rows)==1
 r=rows[0]
 assert r["id"]=="local71:10834"
 assert r["category"]=="hang_out"
 assert r["venue_address"]==ak.PEANUT_FARM[1]
 assert r["lat"]==ak.PEANUT_FARM[3] and r["lng"]==ak.PEANUT_FARM[4]
 assert r["timezone"]==ak.ZONE
 assert "Tradeswomen of Alaska" in r["description"]
 assert r["event_url"]==ak.REVIEWED[10834]["url"]
 assert r.get("image_url") is None

@pytest.mark.parametrize("change",[
 {"hide_from_listings":True},{"all_day":True},
 {"status":"private"},{"timezone":"America/New_York"},
 {"start_date":"2026-12-11 16:00:00"},
 {"utc_start_date":"2026-12-11 02:00:00"},
 {"description":""},{"description":"members only event at The Peanut Farm for Tradeswomen of Alaska"},
 {"venue":{"id":7877,"venue":"The Peanut Farm","address":"no street","city":"Anchorage","state":"AK","zip":"99518"}},
])
def test_fail_closed_for_unverified_changes(change):
 with pytest.raises(ValueError):
  ak.collect(source(),fetch({**EVENT,**change}),now=NOW)

def test_fail_closed_for_missing_event_page_venue():
 with pytest.raises(ValueError,match="detail_does_not_confirm_venue"):
  ak.collect(source(),fetch(detail="<html><body>Thursday Night Football</body></html>"),now=NOW)

def test_other_organizers_and_outside_area_not_transformed():
 other=dict(EVENT,id=11166,url="https://local71.com/event/fairbanks-meeting/")
 assert ak.collect(source(),fetch(other),now=NOW)==[]

def test_event_urls_and_photos_require_reviewed_identity():
 assert ak.event_url(ak.KEY,EVENT["url"])
 assert not ak.event_url(ak.KEY,"https://local71.com/event/some-other-event/")
 assert not ak.event_url(ak.KEY,EVENT["url"]+"?x=1")
 assert ak.photo_url(ak.KEY,"https://local71.com/wp-content/uploads/abc.jpg") is None

def test_unauthorized_source_not_scraped():
 with pytest.raises(ValueError,match="unregistered_local71_source"):
  ak.collect({**source(),"timezone":"America/New_York"},fetch(),now=NOW)

def test_preview_stays_robots_aware_and_host_scoped(monkeypatch):
 def guarded(url,accept,**kwargs):
  assert kwargs["respect_robots"] is True
  assert kwargs["allowed_hosts"]==("local71.com",)
  return fetch()(url,accept)
 monkeypatch.setattr(preview_worker,"fetch_publisher",guarded)
 result=preview_worker.preview_source(source())
 assert result["p_future_count"]==result["p_venue_count"]==1
