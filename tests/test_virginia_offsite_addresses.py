"""Synthetic fixtures: actual-venue parsing, no network or database writes."""
from unittest.mock import patch
import pytest
from roomquest import virginia_state_parks as va

PARK = {
    "code": "OC", "name": "Occoneechee State Park",
    "address": "1192 Occoneechee Park Rd., Clarksville, VA 23927",
    "lat": 36.623813, "lng": -78.526959,
    "dcr_calendar_id": "2013-10-18-21-10-41-00019",
}
ADDRESS = "321 Virginia Ave, Clarksville, VA 23927"
URL = va.ROOT + "/state-parks/event?id=2026-11-03-10-10-10-testmeeting"
SOURCE = {
    "source_key": "virginia_state_parks_oc", "kind": "html",
    "platform_adapter": "html", "feed_url": va.registered_calendar_url(PARK),
}
INTRO = "This community group supports local park activities and welcomes people interested in its work."
VENUE = "Meet at Clarksville Town Hall (located at " + ADDRESS + ") in the Chamber Room."


def page(where="Clarksville Town Hall", paragraphs=None, title="Friends meeting"):
    paragraphs = [INTRO, VENUE] if paragraphs is None else paragraphs
    return ("<main><h1>" + title + "</h1><h2>Where</h2>"
        "<div>Program Location:</div><div>" + where + "</div>"
        "<div>Main Park Address:</div><div>" + PARK["name"] + ", " + PARK["address"] + "</div>"
        "<h2>When</h2><div>Nov. 4, 2026. 6:00 p.m. - 7:00 p.m.</div>"
        + "".join("<p>" + p + "</p>" for p in paragraphs) + "</main>")


def normalized(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(title=title, starts_at=start, ends_at=end, venue_name=venue,
        venue_address=address, venue_city=city, event_url=url, id=identity,
        lat=kwargs.get("lat"), lng=kwargs.get("lng"))


@pytest.mark.parametrize("text", [
    "Clarksville Town Hall (located at " + ADDRESS + ")",
    "Clarksville Town Hall, " + ADDRESS,
    "Clarksville Town Hall: " + ADDRESS,
    "Clarksville Town Hall at " + ADDRESS,
    "Clarksville Town Hall is located at " + ADDRESS,
    "CLARKSVILLE TOWN HALL (located at " + ADDRESS + ")",
])
def test_street_is_attached_to_named_venue(text):
    assert va.meeting_street_address([text], "Clarksville Town Hall") == ADDRESS


@pytest.mark.parametrize("text", [
    "Clarksville Town Hall meets later. Send mail to the office at " + ADDRESS,
    "Clarksville Town Hall, and organizers will stop at " + ADDRESS,
    "The unrelated visitor center is at " + ADDRESS,
    "Clarksville Town Hall (P.O. Box 7, Clarksville, VA 23927)",
    "Clarksville Town Hall (located at 321 Virginia Ave, Clarksville, TN 37040)",
])
def test_unrelated_incomplete_or_non_virginia_address_is_not_guessed(text):
    assert va.meeting_street_address([text], "Clarksville Town Hall") is None


def test_conflicting_named_addresses_are_held():
    assert va.meeting_street_address([
        "Clarksville Town Hall, " + ADDRESS,
        "Clarksville Town Hall, 322 Virginia Ave, Clarksville, VA 23927",
    ], "Clarksville Town Hall") is None


def test_actual_venue_null_gps_and_room_instructions_survive():
    with patch.object(va, "record", side_effect=normalized) as record:
        result = va.parse_event(page(), URL, PARK)
    assert result["venue_name"] == "Clarksville Town Hall"
    assert result["venue_address"] == ADDRESS
    assert result["venue_city"] == "Clarksville"
    assert result["lat"] is None and result["lng"] is None
    assert "Chamber Room" in result["description"] and INTRO in result["description"]
    assert result["location_provenance"] == "publisher_offsite_street_pending_geocode"
    assert result["starts_at"] == "2026-11-04T18:00:00-05:00"
    assert result["ends_at"] == "2026-11-04T19:00:00-05:00"
    assert record.call_args.kwargs["publisher_geo"] is False


def test_in_park_program_keeps_reviewed_coordinates():
    with patch.object(va, "record", side_effect=normalized):
        result = va.parse_event(page("Terrace Gardens", [INTRO]), URL, PARK)
    assert result["venue_name"] == PARK["name"]
    assert result["venue_address"] == PARK["address"]
    assert result["lat"] == PARK["lat"] and result["lng"] == PARK["lng"]
    assert result["description"].startswith("Meeting Location: Terrace Gardens")


def test_offsite_without_address_never_borrows_park_address():
    with pytest.raises(ValueError, match="offsite_venue_requires_address"):
        va.parse_event(page(paragraphs=[INTRO]), URL, PARK)


def test_unknown_venue_with_explicit_address_also_uses_address_resolution():
    where = "Community Meeting Room"
    with patch.object(va, "record", side_effect=normalized):
        result = va.parse_event(page(where, [where + " (located at " + ADDRESS + ")"]), URL, PARK)
    assert result["venue_name"] == where
    assert result["venue_address"] == ADDRESS
    assert result["lat"] is None


def test_one_collection_keeps_both_offsite_meeting_and_in_park_program():
    hike_url = URL.replace("testmeeting", "testhike")
    listing = ('<h3>Park: Occoneechee State Park</h3>'
        + ''.join('<article><a href="' + url + '">Details</a></article>' for url in [URL, hike_url]))
    def fetch(url, accept):
        if "/events?" in url:
            return listing
        return page() if url == URL else page("Terrace Gardens", [INTRO], "Guided hike")
    with patch.object(va, "catalog", return_value={"oc": PARK}), patch.object(va, "record", side_effect=normalized):
        result = va.collect(SOURCE, fetch)
    assert len(result) == 2
    assert result[0]["venue_name"] == "Clarksville Town Hall" and result[0]["lat"] is None
    assert result[1]["venue_name"] == PARK["name"] and result[1]["lat"] == PARK["lat"]
    assert result[0]["id"] != result[1]["id"]
