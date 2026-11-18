"""Anchorage batch20: direct TEC API, exact venues, full calendar narratives."""
from datetime import datetime, timezone
import json
import pytest

from roomquest import anchorage_batch20_tec as ak
from roomquest import preview_worker

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
VENUE_PALMER = {"venue":"Palmer Train Depot", "address":"610 S. Valley Way",
                "city":"Palmer","state":"AK","zip":"99645",
                "geo_lat":None,"geo_lng":None}
VENUE_AWCC = {"venue":"Alaska Wildlife Conservation Center",
              "address":"Mile 79 Seward Highway","city":"Portage",
              "state":"AK","zip":"99587","geo_lat":None,"geo_lng":None}
VENUE_APU = {"venue":"Grant Hall, Student Lounge Room 125",
             "address":"4101 University Drive","city":"Anchorage",
             "state":None,"zip":None,"geo_lat":61.18949,"geo_lng":-149.8066265}


def source(k):
    u,kind,adapter=ak.SOURCES[k]
    return dict(source_key=k,feed_url=u,kind=kind,platform_adapter=adapter,timezone=ak.ZONE)

def event(key="palmer", title="Crochet Workshop", **kw):
    base=dict(id=2581,title=title,
              status="publish",event_status=None,all_day=False,
              start_date="2026-12-04 18:00:00",
              utc_start_date="2026-12-05 03:00:00",
              end_date="2026-12-04 20:00:00",
              utc_end_date="2026-12-05 05:00:00",
              timezone=ak.ZONE,
              description="<p>A full <strong>community</strong> workshop description.</p>",
              url=ak.SOURCES[ak.VISIT_PALMER][0].split("/wp-json/")[0]+"/event/crochet-workshop/",
              venue=VENUE_PALMER,categories=[{"name":"Workshops"}],image=None)
    if key=="awcc":
        base.update(title="Portage Christmas Bird Count 2026",
                    url="https://alaskawildlife.org/event/portage-christmas-bird-count-2026/",
                    venue=VENUE_AWCC)
    if key=="apu":
        base.update(title="Elder Tea",
                    url="https://www.alaskapacific.edu/event/elder-tea/",
                    venue=VENUE_APU)
    base.update(kw)
    return base

def fetch(*pages):
    def _fetch(u,accept):
        assert "per_page=50&page=" in u and accept=="application/json"
        page=int(u.split("page=")[-1])
        return json.dumps({"events": list(pages[page-1]),
                           "total": sum(map(len,pages)),
                           "total_pages": len(pages)})
    return _fetch

def test_visit_palmer_source_venue_and_pagination():
    first=event(title="Crochet Workshop")
    second=event(title="Live Music Concert",
                 id=2582,url="https://visitpalmer.com/event/live-music-concert/",
                 venue=dict(VENUE_PALMER,address="320 E Dahlia Ave",
                            venue="Palmer Alehouse",geo_lat=61.599,geo_lng=-149.117))
    records=ak.collect(source(ak.VISIT_PALMER),fetch([first],[second]),now=NOW)
    assert len(records)==2
    assert {r["category"] for r in records}=={"learn","music"} or {r["category"] for r in records}=={"create","music"}
    assert all(r["description"] and "<" not in r["description"] for r in records)
    assert records[0]["venue_address"].startswith("610 S. Valley Way")
    assert {r["lat"] is not None for r in records}=={True,False}

def test_awcc_official_numbered_street_from_exact_milepost():
    item=event("awcc")
    rows=ak.collect(source(ak.AWCC),fetch([item]),now=NOW)
    assert len(rows)==1
    assert rows[0]["category"]=="gardens_nature"
    assert rows[0]["venue_address"]=="43520 Seward Highway, Portage, AK 99587"
    assert rows[0]["lat"]==60.821359136434815
    assert not ak.collect(source(ak.AWCC),
        fetch([dict(item,venue=dict(VENUE_AWCC,venue="Unrelated Shop"))]),now=NOW)
    assert not ak.collect(source(ak.AWCC),
        fetch([dict(item,title="Special 2026 Holiday Hours")]),now=NOW)
    assert not ak.collect(source(ak.AWCC),
        fetch([dict(item,title="December Military Monday")]),now=NOW)

def test_apu_only_reviewed_public_events_not_academic_deadlines():
    item=event("apu")
    records=ak.collect(source(ak.APU),fetch([
        item,dict(item,id=2582,title="Last Day to Withdraw with a W (Module)"),
        dict(item,id=2583,venue=dict(VENUE_APU,address="Invalid Address"))
    ]),now=NOW)
    assert len(records)==1 and records[0]["title"]=="Elder Tea"
    assert records[0]["lat"]==61.18949
    assert records[0]["category"]=="hang_out"

def test_utc_local_time_conflict_and_foreign_event_url_are_blocked():
    base=event()
    bad=[
        dict(base,utc_start_date="2026-12-05 05:00:00"),
        dict(base,timezone="America/Los_Angeles"),
        dict(base,url="https://other.example.org/event/crochet-workshop/"),
        dict(base,venue=dict(VENUE_PALMER,address="No street")),
        dict(base,venue=dict(VENUE_PALMER,city="Fairbanks")),
        dict(base,description="<p></p>"),
        dict(base,description="X"*12001),
        dict(base,title="Private Event"),
        dict(base,all_day=True)
    ]
    for e in bad:
        assert ak.collect(source(ak.VISIT_PALMER),fetch([e]),now=NOW)==[]

def test_tec_requires_full_pages_and_exact_source():
    with pytest.raises(ValueError,match="unregistered_anchorage_batch20_tec_source"):
        ak.collect(dict(source(ak.VISIT_PALMER),timezone="America/New_York"),
                   fetch([]),now=NOW)
    def invalid(u,accept):
        return json.dumps(dict(events=[],total_pages=99))
    with pytest.raises(ValueError,match="tec_pagination_requires_review"):
        ak.collect(source(ak.VISIT_PALMER),invalid,now=NOW)

def test_preview_respects_tec_source_robots_and_allowed_host(monkeypatch):
    item=event("awcc")
    def guarded(u,accept,**kwargs):
        assert kwargs["respect_robots"] is True
        assert kwargs["allowed_hosts"]==("alaskawildlife.org",)
        return fetch([item])(u,accept)
    monkeypatch.setattr(preview_worker,"fetch_publisher",guarded)
    result=preview_worker.preview_source(source(ak.AWCC))
    assert result["p_future_count"]==len(result["p_events"])==1
    assert result["p_venue_count"]==1

def test_image_candidate_rejects_resizes_and_wrong_hosts():
    base="https://alaskawildlife.org/wp-content/uploads/2022/10/Reindeer-with-noses.jpg"
    assert ak.photo_url(ak.AWCC,base)==base
    for candidate in [base+"?width=400",base.replace("alaskawildlife.org","example.com"),
                      base.replace("Reindeer-with-noses.jpg","logo.jpg"),base.replace("https:","http:")]:
        assert ak.photo_url(ak.AWCC,candidate) is None

def test_winter_solstice_sewing_exact_studio_full_description_and_held_notices():
    venue={"venue":"Winter Solstice Sewing & Crafts","address":"400 W Potter Drive",
           "city":"Anchorage","state":"AK","zip":"99518","geo_lat":None,"geo_lng":None}
    def sew(title,**changes):
        base=event(title=title,id=83023,
                   url="https://wintersolsticecrafts.com/event/getting-started-with-a-sewing-machine/",
                   venue=venue,categories=[{"name":"Classes"}],
                   description="<p>Spend the afternoon practicing sewing basics with a teacher. "
                               + "Bring your own materials for a hands-on course. "*38 + "</p>")
        base.update(changes)
        return base
    accepted=sew("Getting Started With A Sewing Machine")
    rows=ak.collect(source(ak.SEW),fetch([accepted]),now=NOW)
    assert len(rows)==1
    row=rows[0]
    assert row["category"]=="create"
    assert row["venue_address"]=="400 W Potter Drive, Anchorage, AK 99518"
    assert row["lat"] is None and row["lng"] is None
    assert len(row["description"])>1500 and "<" not in row["description"]
    disallowed=[
        sew("Closed to recuperate from Thanksgiving!"),
        sew("Mysterious Events"),
        sew("Getting Started With A Sewing Machine", venue=dict(venue,address="1 Unverified Lane")),
        sew("Getting Started With A Sewing Machine", description=""),
        sew("Getting Started With A Sewing Machine", description="X"*12001),
        sew("Getting Started With A Sewing Machine", all_day=True),
        sew("Getting Started With A Sewing Machine", url="https://wrong.example.org/event/other/"),
    ]
    for item in disallowed:
        assert ak.collect(source(ak.SEW),fetch([item]),now=NOW)==[]
