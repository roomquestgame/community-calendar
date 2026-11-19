"""A publisher's explicit per-event start address overrides park headquarters."""
from unittest.mock import patch

from roomquest import oc_parks_partial as oc
from test_oc_parks_partial import NOW, SOURCE, detail, event, listing, fake_record


def _run(title, event_path, published_street, published_city, published_zip, narrative):
    listing_html = listing([event(n=5, title=title, path=event_path)])
    detail_html = detail(title=title, street=published_street,
                         city=published_city, postal=published_zip,
                         narrative="<p>"+narrative+"</p>")
    def fetch(url, _):
        return listing_html if url == oc.CALENDAR else detail_html
    with patch.object(oc, "record", side_effect=fake_record):
        rows = oc.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 1
    return rows[0]


def test_willow_staging_area_is_not_the_generic_18751_park_address():
    row = _run(
        "Fitness Hike - Willow", "/events/fitness-hike-willow-4",
        "18751 Laguna Canyon Road", "Laguna Beach", "92651",
        "*This program begins at the Willow Staging Area, 20070 Laguna Canyon Road, Laguna Beach, CA 92651*\n"
        "This is a brisk hike through Irvine Ranch Open Space.")
    assert row["venue_name"] == "Willow Staging Area"
    assert row["venue_address"] == "20070 Laguna Canyon Road, Laguna Beach, CA 92651"
    assert row["lat"] is None and row["lng"] is None
    assert row["publisher_status"] == "scheduled"
    assert row["timezone"] == "America/Los_Angeles"
    assert "20070 Laguna" in row["description"]
    assert "image_url" not in row


def test_land_tending_starts_at_aliso_viejo_community_park_not_other_park_pin():
    row = _run(
        "Land Tending with LCF – Aliso Creek", "/events/land-tending-lcf-aliso-creek-2",
        "28373 Alicia Parkway", "Laguna Niguel", "92677",
        "*This program begins at Aliso Viejo Community Park, 150 Cedarbrook, Aliso Viejo, CA 92656*\n"
        "Park volunteers learn and work together in nature.")
    assert row["venue_name"] == "Aliso Viejo Community Park"
    assert row["venue_address"] == "150 Cedarbrook, Aliso Viejo, CA 92656"
    assert row["lat"] is None and row["lng"] is None
    assert row["publisher_status"] == "scheduled"
    assert "150 Cedarbrook" in row["description"]
    assert "image_candidate_url" not in row


def test_matching_exact_source_start_keeps_the_original_reviewed_park_point():
    row = _run(
        "Oak Woodland Bird Walk", "/events/oak-woodland-bird-walk-2",
        "2145 N. Windes Drive", "Orange", "92869",
        "This program begins at Santiago Oaks Regional Park, 2145 N. Windes Drive, Orange, CA 92869. "
        "Bring binoculars and water.")
    assert row["venue_name"] == "Santiago Oaks Regional Park"
    assert row["lat"] == 33.816145 and row["lng"] == -117.779097
    assert row["venue_address"] == "2145 N. Windes Drive, Orange, CA 92869"


def test_non_specific_staging_note_cannot_invent_a_new_street_or_pin():
    row = _run(
        "Saturday Restoration: Habitat Adventure Trail", "/events/habitat-adventure-trail",
        "1 Irvine Park Rd.", "Orange", "92869",
        "The program will begin at the Habitat Adventure Trail trailhead near parking lot G. "
        "Wear sturdy shoes and bring drinking water.")
    assert row["venue_address"] == "1 Irvine Park Rd., Orange, CA 92869"
    assert row["lat"] == 33.796935


def test_description_original_html_is_kept_without_inserted_or_fabricated_prose():
    body = ("*This program begins at Willow Staging Area, 20070 Laguna Canyon Road, Laguna Beach, CA 92651* "
            + "A challenging hike through the canyon. " * 12)
    row = _run("Fitness Hike - Willow", "/events/fitness-hike-willow-4",
               "18751 Laguna Canyon Road", "Laguna Beach", "92651", body)
    assert row["description"] == body.strip()
    assert len(row["description"]) > 150
