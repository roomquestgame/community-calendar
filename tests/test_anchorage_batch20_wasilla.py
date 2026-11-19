"""Fail-closed official CivicPlus Wasilla Public Library event acceptance."""
from datetime import datetime, timezone
from roomquest import anchorage_batch20_wasilla as w

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)

def detail(*, title="Toddler Storytime", street="500 N. Crusey St.",
           description="<p>Join the public library for a guided storytime with books and songs.</p>",
           start="2026-12-02T11:00:00"):
    return f"""<html><div class="detailTitle"><h1 itemprop="name">{title}</h1></div>
    <time itemprop="startDate">{start}</time>
    <div itemprop="location"><span itemprop="name">Wasilla Public Library</span>
    <span itemprop="streetAddress">{street}</span>
    <span itemprop="addressLocality">Wasilla</span>
    <span itemprop="addressRegion">AK</span>
    <span itemprop="postalCode">99654</span></div>
    <div class="specificDetail">Time: 11:00 AM - 12:00 PM</div>
    <div itemprop="description">{description}</div></html>"""

def test_census_matched_street_not_generic_town_center():
    assert w.VENUE_POINT == (61.583150999412, -149.429816984026)
    assert "street" in w.VENUE_GEO_EVIDENCE.lower()
    assert w.event_url(w.KEY, "https://www.cityofwasilla.gov/Calendar.aspx?EID=1118")
    assert not w.event_url(w.KEY, "https://www.cityofwasilla.gov/Calendar.aspx?CID=23")
    assert not w.event_url(w.KEY, "https://eagleriver.org/Calendar.aspx?EID=1118")
    assert w.photo_url(w.KEY, "https://www.cityofwasilla.gov/image.jpg") is None

def test_full_publisher_details_keep_alaska_time_and_reviewed_street_point():
    row=w._event("1118", detail(), NOW)
    assert row is not None
    assert row["starts_at"] == "2026-12-02T20:00:00+00:00"
    assert row["ends_at"] == "2026-12-02T21:00:00+00:00"
    assert row["timezone"] == "America/Anchorage"
    assert row["category"] == "learn"
    assert row["description"] == "Join the public library for a guided storytime with books and songs."
    assert row["venue_address"] == w.VENUE[1]
    assert (row["lat"],row["lng"]) == w.VENUE_POINT
    assert row["location_provenance"] == "city_published_venue_plus_reviewed_census_matched_street"
    assert row["reason"] is None
    assert row["event_url"] == "https://www.cityofwasilla.gov/Calendar.aspx?EID=1118"

def test_missing_venue_or_narrative_or_unclassified_event_is_held():
    assert w._event("1118", detail(street="500 Fake Rd"), NOW) is None
    assert w._event("1118", detail(description=""), NOW) is None
    assert w._event("1118", detail(title="Private Room Rental"), NOW) is None

def test_dated_occurrence_not_fabricated_from_old_date():
    assert w._event("1118", detail(start="2025-12-02T11:00:00"), NOW) is None
