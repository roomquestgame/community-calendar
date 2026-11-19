"""First-party Skinny Raven event validation and fail-closed tests."""
from datetime import datetime, timezone
import pytest
from roomquest import anchorage_skinny_raven as sk

NOW = datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)
SOURCE = {"source_key": sk.KEY, "feed_url": sk.FEED,
          "kind": "html", "platform_adapter": "html", "timezone": sk.ZONE}

def _html(title="Trot and Give Thanks!", date="Nov. 26, 2026",
          clock="In-Person 5k 10:30am 2 Mile 10:40am",
          location="Our in-person event will be staged from the Dena’ina Civic & Convention Center in Downtown Anchorage.",
          narrative="Join friends and family for a 5K and two-mile Thanksgiving run that raises donations for the Food Bank of Alaska."):
    return ('<html><head><title>Turkey Trot | Skinny Raven Sports</title>'
            '<meta property="og:image" content="https://skinnyraven.com/wp-content/uploads/2026/11/trot.jpg"></head>'
            '<article><h1>'+date+'</h1><h1>'+clock+'</h1>'
            '<h1>'+title+'</h1><h1>In-Person</h1><p>'+narrative+'</p>'
            '<h2>In-Person Location</h2><p>'+location+'</p></article></html>')

def test_complete_valid_event_no_photo():
    row = sk.collect(SOURCE, lambda u, a: _html(), now=NOW)[0]
    assert row["category"] == "sports"
    assert row["timezone"] == "America/Anchorage"
    assert row["venue_address"] == sk.VENUE[1]
    assert row["lat"] == sk.POINT[0] and row["lng"] == sk.POINT[1]
    assert row["starts_at"].startswith("2026-11-26T19:30")
    assert row.get("image_url") is None
    assert "image_candidate_only" in row["publisher_details"]
    assert "Food Bank of Alaska" in row["description"]
    assert row["ends_at"] is None

def test_no_early_or_late_virtual_event():
    rows = sk.collect(SOURCE, lambda u, a: _html(), now=NOW)
    assert len(rows) == 1

@pytest.mark.parametrize("bad", ["", "http://skinnyraven.com/events/turkey-trot/",
                                 "https://skinnyraven.com/events/turkey-trot/?test=x",
                                 "https://example.com/events/turkey-trot/"])
def test_strict_event_url(bad):
    assert not sk.event_url(sk.KEY, bad)

def test_invalid_registration():
    with pytest.raises(ValueError, match="source_mismatch"):
        sk.collect({**SOURCE, "timezone": "UTC"}, lambda u, a: _html(), now=NOW)

@pytest.mark.parametrize("item,part", [
    ({"title":"Private event"},"turkey_trot_identity_changed"),
    ({"date":"Nov. 27, 2026"},"turkey_trot_local_time_unverified"),
    ({"clock":"In-Person 5k 9:30am 2 Mile 8:40am"},"turkey_trot_disordered_starts"),
    ({"location":"Unknown stadium"},"turkey_trot_onsite_venue_missing"),
    ({"narrative":"Private event"},"turkey_trot_description_invalid")])
def test_bad_payload_held(item, part):
    with pytest.raises(ValueError, match=part):
        sk.collect(SOURCE,lambda u,a:_html(**item),now=NOW)

def test_unexpired_ends_are_not_invented():
    assert sk.collect(SOURCE,lambda u,a:_html(),now=datetime(2026,12,1,tzinfo=timezone.utc))==[]

def test_long_full_description_preserved_or_held():
    message = "Runners celebrate together at the event. " * 100
    row = sk.collect(SOURCE,lambda u,a:_html(narrative=message),now=NOW)[0]
    assert message.strip() in row["description"]
    with pytest.raises(ValueError,match="turkey_trot_description_invalid"):
        sk.collect(SOURCE,lambda u,a:_html(narrative=message*4),now=NOW)
