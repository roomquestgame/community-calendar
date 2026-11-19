"""SCCMOD original 2026 Small Business Saturday event, official event location only."""
from datetime import datetime, timezone
import pytest
from roomquest import preview_worker
from roomquest import santa_cruz_local_venues as mod

NOW=datetime(2026,11,19,17,tzinfo=timezone.utc)
URL="https://www.sccmod.org/learn-more/childrenscraftfair"
def source():
 return dict(source_key=mod.SCCMOD,feed_url=URL,kind="html",
             platform_adapter="html",timezone=mod.ZONE)
def fixture():
 return """<html><main>
 <h1>Small Business Saturday Children's Craft Fair</h1>
 <h2>Saturday, November 28, 2026 | 2:00 to 5:00 PM Capitola Mall, outside MOD and Macy’s | 1855 41st Ave, Capitola, CA Free Admission</h2>
 <p>Looking for unique holiday gifts in Santa Cruz County? Shop the smallest businesses in town at MOD’s 3rd Annual Children’s Craft Fair this Small Business Saturday. Explore over 30 booths of art, crafts, and handmade goods, all designed, made, and sold by local kids.</p>
 <h2>Handmade Holiday Gifts, Made by Kids</h2>
 <p>Skip the big-box crowds and find one-of-a-kind gifts you won’t see anywhere else: handmade jewelry, artwork, ornaments, crafts, and more. Every purchase supports a young entrepreneur in our community.</p>
 <h2>The Perfect Place for Kids to Shop for Their Parents</h2>
 <p>Kids can browse, budget, and pick out holiday gifts for the grown-ups in their lives, with prices made for small wallets. It’s one of the most fun family things to do in Santa Cruz over Thanksgiving weekend.</p>
 </main></html>"""
def fetch(doc):
 def inner(url,accept):
  assert url==URL and accept=="text/html"
  return doc
 return inner
def test_one_exact_original_event_full_prose_real_street_and_time():
 rows=mod.collect(source(),fetch(fixture()),now=NOW)
 assert len(rows)==1
 x=rows[0]
 assert x["event_url"]==URL
 assert x["id"]=="sccmod-2026-11-28-childrens-craft-fair"
 assert x["starts_at"]=="2026-11-28T22:00:00+00:00"
 assert x["ends_at"]=="2026-11-29T01:00:00+00:00"
 assert x["venue_address"]=="1855 41st Ave, Capitola, CA"
 assert x["timezone"]=="America/Los_Angeles"
 assert x.get("lat") is None and x.get("lng") is None
 assert len(x["description"])>=550
 assert "Every purchase supports a young entrepreneur" in x["description"]
 assert "It’s one of the most fun family things" in x["description"]
 assert not x.get("image_url")
@pytest.mark.parametrize("change",[
 lambda s:s.replace("November 28, 2026","November 28, 2025"),
 lambda s:s.replace("2:00 to 5:00 PM","2:00 to 6:00 PM"),
 lambda s:s.replace("1855 41st Ave","1200 Pacific Ave"),
 lambda s:s.replace("Free Admission","Tickets Required"),
 lambda s:s.replace("Small Business Saturday Children's Craft Fair","Private Craft Fair"),
 lambda s:s.replace("Looking for unique holiday gifts in Santa Cruz County?",""),
 lambda s:s.replace("Every purchase supports a young entrepreneur in our community.",""),
])
def test_schedule_venue_or_description_drift_fails_closed(change):
 with pytest.raises(ValueError):
  mod.collect(source(),fetch(change(fixture())),now=NOW)
def test_no_fake_recurrence_after_date():
 assert mod.collect(source(),fetch(fixture()),now=datetime(2027,1,15,tzinfo=timezone.utc))==[]
def test_exact_source_and_url_identity():
 with pytest.raises(ValueError,match="unregistered_santa_cruz_local_source"):
  mod.collect(dict(source(),feed_url="https://www.other.org/"),fetch(fixture()),now=NOW)
 assert mod.event_url(mod.SCCMOD,URL)
 assert not mod.event_url(mod.SCCMOD,URL+"?ref=third-party")
def test_guarded_preview_dispatch(monkeypatch):
 def guarded(url,accept,**kwargs):
  assert kwargs.get("respect_robots") is True
  assert kwargs.get("allowed_hosts")==("www.sccmod.org",)
  return fetch(fixture())(url,accept)
 monkeypatch.setattr(preview_worker,"fetch_publisher",guarded)
 result=preview_worker.preview_source(source())
 assert result["p_error"] is None
 assert result["p_future_count"]==1
 assert len(result["p_events"])==1
