from roomquest.ics_adapter import _split_elizabeth_river_trail_location


def test_split_published_elizabeth_river_trail_location():
    event = {
        "venue_name": (
            "Elizabeth River Trail, The Elizabeth River Trail Foundation, "
            "715 Orapax St Ste. E, Norfolk, VA 23507, USA"
        )
    }
    _split_elizabeth_river_trail_location(event)
    assert event == {
        "venue_name": "Elizabeth River Trail, The Elizabeth River Trail Foundation",
        "venue_address": "715 Orapax St Ste. E, Norfolk, VA 23507",
    }


def test_leave_unspecified_elizabeth_river_trail_location_for_review():
    event = {"venue_name": "Norfolk, VA"}
    _split_elizabeth_river_trail_location(event)
    assert event == {"venue_name": "Norfolk, VA"}
