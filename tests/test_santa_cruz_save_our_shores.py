"""Save Our Shores first-party TEC, venue proofs and safe publication holds."""
from datetime import datetime,timezone
import json
import pytest
from roomquest import santa_cruz_save_our_shores as m
from roomquest.publisher_evidence import family
NOW=datetime(2026,11,19,9,tzinfo=timezone.utc)
SOURCE={"source_key":m.KEY,"feed_url":m.FEED,"kind":"json",
        "platform_adapter":"wordpress","timezone":m.ZONE}

def event(id=26695,title="Beach Cleanup @ Hidden Beach", address="660 Cliff Dr",
          city="Aptos", zip_code="95003",start="2026-11-21 09:00:00",
          end="2026-11-21 11:00:00",utc_start="2026-11-21 17:00:00",
          utc_end="2026-11-21 19:00:00"):
    return {"id":id,"status":"publish","title":title,
       "url":"https://saveourshores.org/event/beach-cleanup-hidden-beach/",
       "all_day":False,"timezone":m.ZONE,
       "start_date":start,"end_date":end,
       "utc_start_date":utc_start,"utc_end_date":utc_end,
       "description":"<p>Join Save Our Shores for a beach cleanup at Hidden Beach!</p><p>Meet at the benches overlooking the beach near the path. Registration is required; bring sun protection, a water bottle, and comfortable shoes. Please help protect the coast.</p>",
       "categories":[{"name":"Beach Cleanup"}],
       "organizer":[{"organizer":"Save Our Shores"}],
       "venue":{"venue":"Hidden Beach","address":address,"city":city,"state":"CA","zip":zip_code},
       "image":{"url":"https://saveourshores.org/wp-content/uploads/2026/01/hidden-beach-event.jpg"}}

def fixture(events=None, qgiv=None):
    events=events if events is not None else [event()]
    def fetch(url,accept):
        if url==m.FEED:return json.dumps({"events":events,"total_pages":1})
        if url==m.QGIV:return (qgiv if qgiv is not None else
            '<p>Beach Cleanup @ Corcoran Lagoon Beach</p><p>Corcoran Lagoon Beach 112 20th Ave Santa Cruz, California 95062 United States Get Directions Date & Time Saturday, 12/12/2026 9:00am PST - 11:00am PST</p>')
        raise AssertionError(url)
    return fetch

def test_original_publisher_street_and_image_candidate_and_real_time():
    rows=m.collect(SOURCE,fixture(),now=NOW)
    assert len(rows)==1
    r=rows[0]
    assert r["venue_address"]=="660 Cliff Dr, Aptos, CA 95003"
    assert r["starts_at"]=="2026-11-21T17:00:00+00:00"
    assert r["ends_at"]=="2026-11-21T19:00:00+00:00"
    assert r["lat"] is None and r["lng"] is None
    assert len(r["description"])>120
    assert r["publisher_categories"]==["Beach Cleanup"]
    assert r["image_url"].endswith("hidden-beach-event.jpg")
    assert family(m.KEY,r["event_url"])=="save_our_shores"

def test_unresolvable_location_is_held_not_geocoded():
    x=event(address="2QQC+QR",city="Davenport")
    assert m.collect(SOURCE,fixture(events=[x]),now=NOW)==[]
    x=event(address="20th Ave",city="Santa Cruz")
    assert m.collect(SOURCE,fixture(events=[x]),now=NOW)==[]

def test_corcoran_requires_exact_original_registration_numbered_street():
    e=event(id=26706,title=m.TITLE_CORCORAN,address="20th Ave",city="Santa Cruz",zip_code="95062",
      start="2026-12-12 09:00:00",end="2026-12-12 11:00:00",
      utc_start="2026-12-12 17:00:00",utc_end="2026-12-12 19:00:00")
    e["url"]="https://saveourshores.org/event/beach-cleanup-corcoran-lagoon-beach/"
    e["description"]+=f'<p>Registration is required: <a href="{m.QGIV}">register here</a>.</p>'
    row=m.collect(SOURCE,fixture(events=[e]),now=NOW)[0]
    assert row["venue_address"]==m.CORCORAN_ADDRESS
    assert row["location_evidence_url"]==m.QGIV
    with pytest.raises(ValueError,match="save_our_shores_registration_street_unverified"):
        m.collect(SOURCE,fixture(events=[e],qgiv='<p>Corcoran Lagoon Beach 113 20th Ave Santa Cruz, California 95062 Saturday, 12/12/2026 9:00am PST - 11:00am PST</p>'*3),now=NOW)

def test_fail_on_bad_clocks_unsafe_identity_and_pages():
    bad=event(utc_start="2026-11-21 15:00:00")
    with pytest.raises(ValueError,match="save_our_shores_clock_disagreement"):
        m.collect(SOURCE,fixture(events=[bad]),now=NOW)
    with pytest.raises(ValueError,match="save_our_shores_source_identity_mismatch"):
        m.collect(SOURCE|{"feed_url":m.FEED+"?x=1"},fixture(),now=NOW)
    with pytest.raises(ValueError,match="save_our_shores_pagination_or_records_invalid"):
        m.collect(SOURCE,lambda u,a: json.dumps({"events":[],"total_pages":3}),now=NOW)
    assert not m.event_url("https://saveourshores.org/event/other/?format=json")
    assert not m.photo_url("https://evil.test/wp-content/uploads/img.jpg")

def test_expired_entries_are_not_republished():
    assert m.collect(SOURCE,fixture(),now=datetime(2027,3,1,tzinfo=timezone.utc))==[]

