"""No network or Supabase calls: HTML collector parsing, source isolation, route."""
import io
import json
from datetime import date, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
import pytest
from roomquest import virginia_state_parks as va
from roomquest import preview_worker as worker
from api.html_demand import handler as HtmlHandler

ID = "2026-10-17-16-00-48-597528-s8b"
PAGE = """<html><body><main><h1>Plantation Discovery Hike</h1>
<h2>Where</h2><div>Program Location:</div><div>Terrace Gardens</div>
<div>Main Park Address:</div><div>Occoneechee State Park, 1192 Occoneechee Park Rd., Clarksville, VA 23927.</div>
<h2>When</h2><div>Nov. 7, 2026. 11:00 a.m. - 12:30 p.m.</div>
<div id="event_description"><p>Explore the history of the Occoneechee Plantation on this one-mile guided hike around the Plantation Trail and natural history.</p>
<!-- event_photo_fixture --></div>
</main></body></html>"""
PARK = va.catalog()["oc"]
CAL_LINK = va.ROOT + "/state-parks/event?id=" + ID
SOURCE = {"source_key":"virginia_state_parks_oc", "kind":"html",
          "platform_adapter":"html",
          "feed_url":va.registered_calendar_url(PARK)}

# Synthetic DOM cases exercise the selection contract. These are not a saved
# production page; production preview evidence is a separate release check.
PHOTO = va.ROOT + "/state-parks/blog/volunteers-trail.jpg"
PHOTO_TAG = '<img src="/state-parks/blog/volunteers-trail.jpg" alt="Three volunteers maintaining a trail together" width="900" height="600">'
MAP_TAG = '<img src="/state-parks/images/ww.png" alt="Location of Widewater State Park in Virginia">'
# This exact asset was incorrectly selected in production; this surrounding
# regression markup is synthetic until the permitted publisher audit is read.
PLATE_URL = va.ROOT + "/state-parks/image/vsp-plate.jpg"
PLATE_TAG = '<img src="/state-parks/image/vsp-plate.jpg" alt="Get a Virginia State Parks license plate">'
CAPTURED_FIXTURES = Path(__file__).parent / "fixtures" / "virginia_state_parks"
WIDEWATER_PHOTO = "https://www.flickr.com/photo_download.gne?id=55197366730&secret=a76ef0bacd&size=w&source=photoPageEngagement"


def photo_record(content="", *, page=PAGE):
    with patch.object(va, "record", return_value={"id": "fixture"}):
        return va.parse_event(page.replace("<!-- event_photo_fixture -->", content), CAL_LINK, PARK)


def test_event_content_photo_excludes_the_generic_park_location_map():
    item = photo_record(MAP_TAG + PHOTO_TAG)
    assert item["image_url"] == PHOTO
    assert item["image_provenance"] == "publisher_event_html_v2"
    assert item["image_extractor_version"] == "publisher_event_html_v2"
    assert item["image_evidence_url"] == CAL_LINK


def test_live_observed_license_plate_asset_is_never_an_event_photo():
    assert "image_url" not in photo_record(PLATE_TAG)
    assert photo_record(PHOTO_TAG + PLATE_TAG)["image_url"] == PHOTO
    event = {"@type": "Event", "name": "Plantation Discovery Hike", "url": CAL_LINK, "image": PLATE_URL}
    markup = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
    assert "image_url" not in photo_record(markup)


@pytest.mark.parametrize("heading", ["Documents", "Other details", "Event types", "Additional dates", "Add to calendar"])
def test_event_details_boundary_excludes_unrelated_page_tail_artwork(heading):
    assert "image_url" not in photo_record('<h2>' + heading + '</h2>' + PHOTO_TAG)
    assert photo_record(PHOTO_TAG + '<h2>' + heading + '</h2>' + PLATE_TAG)["image_url"] == PHOTO


@pytest.mark.parametrize("name,park_code,expected", [
    ("archery-club", "bc", None), ("widewater-volunteers", "ww", WIDEWATER_PHOTO),
])
def test_captured_publisher_dom_selects_only_the_real_event_photo(name, park_code, expected):
    provenance = json.loads((CAPTURED_FIXTURES / "provenance.json").read_text())
    evidence = next(page for page in provenance["pages"] if page["fixture"] == name + ".html")
    html = (CAPTURED_FIXTURES / evidence["fixture"]).read_text()
    with patch.object(va, "record", return_value={"id": "captured-event"}):
        item = va.parse_event(html, evidence["source_url"], va.catalog()[park_code])
    assert item.get("image_url") == expected
    assert item["image_extractor_version"] == "publisher_event_html_v2"
    if expected:
        assert item["image_evidence_url"] == evidence["source_url"]
    else:
        assert "image_provenance" not in item


@pytest.mark.parametrize("change", ["missing_container", "duplicate_container", "outside_container"])
def test_real_photo_requires_the_unique_captured_event_description_container(change):
    html = (CAPTURED_FIXTURES / "widewater-volunteers.html").read_text()
    soup = va.BeautifulSoup(html, "html.parser")
    description = soup.select_one("#event_description")
    if change == "missing_container":
        description["id"] = "unrecognized_description"
    elif change == "duplicate_container":
        description.insert_after(va.BeautifulSoup(str(description), "html.parser"))
    else:
        description.insert_after(description.find("img").extract())
    with patch.object(va, "record", return_value={"id": "captured-event"}):
        item = va.parse_event(str(soup), CAL_LINK, va.catalog()["ww"])
    assert "image_url" not in item


@pytest.mark.parametrize("content", ["", MAP_TAG,
    '<img src="/images/park-map.jpg" alt="Find our trails and campground amenities">',
    '<img src="/images/state-logo.jpg" alt="Virginia State Parks official brand artwork">',
    '<img src="/images/photo.jpg" alt="Park">',
    PHOTO_TAG.replace('width="900"', 'width="1"'),
    '<nav>' + PHOTO_TAG + '</nav>', '<header>' + PHOTO_TAG + '</header>',
    '<aside>' + PHOTO_TAG + '</aside>', '<footer>' + PHOTO_TAG + '</footer>',
    '<div class="related-events">' + PHOTO_TAG + '</div>',
    '<div hidden>' + PHOTO_TAG + '</div>',
    '<h2>Know Before You Go</h2>' + PHOTO_TAG,
    '<h2>Other Events</h2>' + PHOTO_TAG,
    '<meta property="og:image" content="' + PHOTO + '">',
])
def test_missing_map_and_boilerplate_images_have_version_but_no_candidate(content):
    item = photo_record(content)
    assert item["image_extractor_version"] == "publisher_event_html_v2"
    assert not {"image_url", "image_provenance", "image_evidence_url"}.intersection(item)


@pytest.mark.parametrize("image_url", ["http://example.org/photo.jpg", "https://127.0.0.1/photo.jpg",
    "https://user:password@example.org/photo.jpg", "data:image/jpeg;base64,AAAA", "/images/photo.svg"])
def test_inline_candidate_keeps_shared_safe_url_validation(image_url):
    assert "image_url" not in photo_record(PHOTO_TAG.replace("/state-parks/blog/volunteers-trail.jpg", image_url))


def test_inline_images_must_belong_to_event_body_and_are_not_first_image_fallback():
    before = PAGE.replace("<h2>When</h2>", PHOTO_TAG + "<h2>When</h2>")
    assert "image_url" not in photo_record(page=before)
    assert "image_url" not in photo_record(page=before.replace('<img ', '<img itemprop="image" '))
    assert photo_record(PHOTO_TAG.replace('<img ', '<img itemprop="image" '))["image_url"] == PHOTO
    ambiguous = PHOTO_TAG + PHOTO_TAG.replace("volunteers-trail.jpg", "other-photo.jpg")
    assert "image_url" not in photo_record(ambiguous)
    assert photo_record(PHOTO_TAG + PHOTO_TAG)["image_url"] == PHOTO


@pytest.mark.parametrize("href", ["event?id=2026-01-01-unrelated", "/state-parks/event?id=2026-01-01-unrelated",
    "/state-parks//event?id=2026-01-01-unrelated", "//state-parks/event?id=2026-01-01-unrelated"])
def test_inline_photo_linked_to_a_different_event_is_rejected(href):
    assert "image_url" not in photo_record('<a href="' + href + '">' + PHOTO_TAG + '</a>')


def test_map_caption_is_checked_even_when_alt_looks_descriptive():
    assert "image_url" not in photo_record('<figure>' + PHOTO_TAG +
        '<figcaption>Location of Widewater State Park in Virginia</figcaption></figure>')


def test_malformed_optional_image_url_does_not_discard_event_facts():
    item = photo_record(PHOTO_TAG.replace("/state-parks/blog/volunteers-trail.jpg", "https://["))
    assert item["id"] == "fixture" and "image_url" not in item
    event = {"@type": "Event", "name": "Plantation Discovery Hike", "url": "https://[", "image": PHOTO}
    markup = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
    assert "image_url" not in photo_record(markup)


def test_matching_structured_event_image_has_priority_over_inline_images():
    event = {"@type": "Event", "name": "Plantation Discovery Hike", "url": CAL_LINK,
             "image": {"@type": "ImageObject", "contentUrl": PHOTO}}
    markup = '<script type="application/ld+json">' + json.dumps({"@graph": [event]}) + '</script>'
    item = photo_record(markup + PHOTO_TAG.replace("volunteers-trail.jpg", "other-photo.jpg"))
    assert item["image_url"] == PHOTO


@pytest.mark.parametrize("changes", [{"name": "A different event"},
    {"url": CAL_LINK + "-different"}, {"@id": "https://example.org/unrelated"},
    {"image": [PHOTO, PHOTO.replace("volunteers-trail.jpg", "other-photo.jpg")]},
    {"image": {"url": PHOTO, "caption": "Location of Widewater State Park in Virginia"}}])
def test_mismatched_or_ambiguous_structured_images_are_not_used(changes):
    event = {"@type": "Event", "name": "Plantation Discovery Hike", "url": CAL_LINK, "image": PHOTO, **changes}
    markup = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
    assert "image_url" not in photo_record(markup)


def test_photo_extraction_reuses_exact_listing_and_detail_fetches():
    listing = f'<h3>Park: Occoneechee State Park</h3><a href="/state-parks/event?id={ID}">View Details</a>'
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return listing if "/events?" in url else PAGE.replace("<!-- event_photo_fixture -->", MAP_TAG + PHOTO_TAG)
    with patch.object(va, "record", return_value={"id": "fixture"}), patch("roomquest.event_media.probe_image") as probe:
        items = va.collect(SOURCE, fetch)
    assert calls == [va.listing_url(PARK), CAL_LINK]
    assert items[0]["image_url"] == PHOTO
    probe.assert_not_called()


def test_empty_successful_va_preview_carries_parser_capability():
    with patch.object(va, "collect", return_value=[]):
        output = worker.preview_source(SOURCE)
    assert output["p_events"] == []
    assert output["p_future_count"] == 0
    assert output["p_parser_capability"] == "publisher_event_html_v2"


def test_va_completion_uses_v3_and_does_not_certify_failed_staging():
    output = {"p_source_key": SOURCE["source_key"], "p_samples": [], "p_future_count": 0,
              "p_venue_count": 0, "p_error": None, "p_events": [],
              "p_parser_capability": "publisher_event_html_v2"}
    with patch.object(worker, "preview_source", return_value=dict(output)), \
         patch.object(worker, "supabase_rpc", return_value=0) as rpc:
        assert worker._process_claimed_source(SOURCE)["complete"] == 1
    assert rpc.call_args.args[0] == "community_collector_record_preview_v3"
    assert rpc.call_args.args[1]["p_parser_capability"] == "publisher_event_html_v2"

    def fail_staging(path, payload):
        if path == "community_collector_record_staged_events":
            raise worker.PreviewError("staging_rejected")
        assert path == "community_collector_record_preview_v3"
        assert payload["p_error"] == "staging_rejected"
        assert "p_parser_capability" not in payload
    with patch.object(worker, "preview_source", return_value=dict(output)), \
         patch.object(worker, "supabase_rpc", side_effect=fail_staging):
        assert worker._process_claimed_source(SOURCE)["failed"] == 1


def test_registered_pilot_calendar_uses_official_guid_and_60_day_window():
    official_id = "2013-10-18-21-10-41-00019"
    assert va.registered_calendar_url(PARK) == va.CALENDAR + "?park=" + official_id
    query = parse_qs(urlparse(va.listing_url(PARK, today=date(2026, 11, 3))).query)
    assert query == {"park": [official_id], "start": ["11/03/2026"], "end": ["01/02/2027"]}
    assert "srchloc" not in query
    other = va.catalog()["do"]
    assert va.registered_calendar_url(other) == va.CALENDAR + "?eventtype=all&srchloc=DO"
    with pytest.raises(ValueError, match="unverified_park_calendar_identifier"):
        va.listing_url(other)


def test_all_46_parks_have_a_registered_on_demand_bootstrap_url():
    parks = va.catalog()
    assert len(parks) == 46
    assert sum("dcr_calendar_id" in park for park in parks.values()) == 1
    assert all(va.registered_calendar_url(park).startswith(va.CALENDAR + "?")
               for park in parks.values())
    assert len(set(va.registered_calendar_url(park) for park in parks.values())) == 46


def test_unverified_park_guid_uses_only_official_selector_and_per_park_listing():
    park = va.catalog()["do"]
    guid = "2013-10-18-21-10-41-00002"
    listing = ('<select name="park"><option value="all">All parks</option>'
        f'<option value="{guid}">Douthat State Park</option>'
        '<option value="2013-10-18-21-10-41-00019">Occoneechee State Park</option></select>')
    event_id = "2026-10-22-12-01-31-000002-abc"
    filtered = (f'<h3>Park: Douthat State Park</h3><article>'
        f'<a href="/state-parks/event?id={event_id}">View Details</a></article>')
    details = PAGE.replace("Occoneechee State Park", "Douthat State Park")
    calls = []
    def fetch(url, accept):
        calls.append(url)
        if url == va.CALENDAR + "?park=all":
            return listing
        if "/events?" in url:
            return filtered
        return details
    source = {"source_key": "virginia_state_parks_do", "kind": "html",
              "platform_adapter": "html", "feed_url": va.registered_calendar_url(park)}
    with patch.object(va, "record", return_value={"title": "Douthat hike"}):
        result = va.collect(source, fetch)
    assert len(result) == 1
    assert len(calls) == 3
    assert calls[0] == va.CALENDAR + "?park=all"
    assert "park=" + guid in calls[1]
    assert calls[2].endswith("id=" + event_id)


def test_missing_ambiguous_or_wrong_park_picker_fails_closed():
    park = va.catalog()["do"]
    guid = "2013-10-18-21-10-41-00002"
    with pytest.raises(ValueError, match="missing_or_ambiguous"):
        va.discover_calendar_id("<select name='park'><option value='all'>All</option></select>", park)
    with pytest.raises(ValueError, match="missing_or_ambiguous"):
        va.discover_calendar_id(
            f'<select name="park"><option value="{guid}">Pocahontas State Park</option></select>',
            park)
    with pytest.raises(ValueError, match="missing_or_ambiguous"):
        va.discover_calendar_id(
            f'<select name="park"><option value="{guid}">Douthat State Park</option></select>'
            f'<select id="park"><option value="2013-10-18-21-10-41-00003">Douthat State Park</option></select>',
            park)
    with pytest.raises(ValueError, match="missing_or_ambiguous"):
        va.discover_calendar_id(
            '<select name="park"><option value="javascript:alert(1)">Douthat State Park</option></select>',
            park)


def test_park_filtered_heading_allows_cards_without_repeated_park_name():
    alt = "2026-10-21-10-44-02-561449-03v"
    html = (f'<h3>Park: Occoneechee State Park</h3>'
        f'<article><a href="/state-parks/event?id={ID}">View Details</a></article>'
        f'<article><a href="/state-parks/event?id={alt}">View Details</a></article>')
    links, total = va.discover(html, PARK)
    assert links == [CAL_LINK, va.ROOT + "/state-parks/event?id=" + alt]
    assert total == 2


def test_out_of_park_meeting_does_not_block_park_events():
    offsite_id = "2026-10-10-15-06-23-053520-hfq"
    calendar_html = (
        '<h3>Park: Occoneechee State Park</h3>'
        f'<article><a href="/state-parks/event?id={offsite_id}">Meeting</a></article>'
        f'<article><a href="/state-parks/event?id={ID}">Hike</a></article>')
    seen = []
    def fake_fetch(url, accept):
        seen.append(url)
        if "/events?" in url:
            return calendar_html
        return PAGE.replace("Terrace Gardens", "Clarksville Town Hall") if offsite_id in url else PAGE
    with patch.object(va, "record", return_value={"id": "hike", "title": "Plantation Discovery Hike"}):
        records = va.collect(SOURCE, fake_fetch)
    assert len(records) == 1
    assert records[0]["title"] == "Plantation Discovery Hike"
    assert len(seen) == 3
    assert "park=2013-10-18-21-10-41-00019" in seen[0]


def test_catalog_contains_46_reviewed_parks():
    assert len(va.catalog()) == 46
    assert PARK["name"] == "Occoneechee State Park"
    assert PARK["address"].startswith("1192 Occoneechee Park")
    assert PARK["lat"] > 36 and PARK["lng"] < -78


def test_extracts_meeting_location_and_known_park_address():
    # Mock only normalized-record conversion to avoid date-dependent test windows.
    with patch.object(va, "record", return_value={"id":"example","lat":PARK["lat"],"lng":PARK["lng"]}) as record:
        result = va.parse_event(PAGE, CAL_LINK, PARK)
    assert result["description"].startswith("Explore the history of the Occoneechee Plantation")
    assert result["description"].endswith("\n\nMeeting Location: Terrace Gardens")
    assert "Plantation" in result["description"]
    assert result["location_provenance"] == "owner_reviewed_park_cache"
    assert result["park_code"] == "OC"
    assert record.call_args.args[0] == "Plantation Discovery Hike"
    assert record.call_args.args[3] == "Occoneechee State Park"
    assert record.call_args.args[4] == PARK["address"]
    assert "2026-11-07T11:00:00-05:00" in record.call_args.args[1]
    assert "2026-11-07T12:30:00-05:00" in record.call_args.args[2]


def test_natural_bridge_published_multiday_schedule_uses_both_explicit_dates():
    # Official indexed page, retrieved 2026-11-04; direct page GET returned403.
    # https://www.dcr.virginia.gov/state-parks/event?id=2026-10-29-11-23-23-287887-qd6
    schedule = "Nov. 13, 2026 10:00 a.m. - Dec. 31, 2026 5:00 p.m."
    html = PAGE.replace("Occoneechee State Park", "Natural Bridge State Park").replace(
        "Nov. 7, 2026. 11:00 a.m. - 12:30 p.m.", schedule).replace(
        "Plantation Discovery Hike", "2026 Festival of Trees")
    with patch.object(va, "record", return_value={"id": "festival"}) as normalized:
        va.parse_event(html, va.ROOT + "/state-parks/event?id=2026-10-29-11-23-23-287887-qd6", va.catalog()["nb"])
    assert normalized.call_args.args[1] == "2026-11-13T10:00:00-05:00"
    assert normalized.call_args.args[2] == "2026-12-31T17:00:00-05:00"
    assert normalized.call_count == 1  # One published span, no invented daily sessions.


def test_explicit_multiday_schedule_preserves_dst_offset_change():
    start, end = va.parse_schedule("Oct. 31, 2026 11:00 p.m. - Nov. 1, 2026 2:30 a.m.")
    assert start.utcoffset() == timedelta(hours=-4)
    assert end.utcoffset() == timedelta(hours=-5)
    assert end.astimezone(timezone.utc) - start.astimezone(timezone.utc) == timedelta(hours=4, minutes=30)


@pytest.mark.parametrize("schedule,reason", [
    ("Nov. 13, 2026 10:00 a.m. - Nov. 12, 2026 5:00 p.m.", "event_end_invalid"),
    ("Nov. 13, 2026. 11:00 p.m. - 1:00 a.m.", "event_end_invalid"),
    ("Nov. 13, 2026. 10:00 a.m. - 10:00 a.m.", "event_end_invalid"),
    ("Feb. 30, 2026 10:00 a.m. - Mar. 1, 2026 5:00 p.m.", "event_date_invalid"),
    ("Nov. 13, 2026 25:00 a.m. - Dec. 31, 2026 5:00 p.m.", "event_time_invalid"),
    ("Nov. 13, 2026 10:00 a.m. - Dec. 31, 2026", "event_schedule_missing"),
    ("Nov. 13, 2026. All day", "event_schedule_missing"),
    ("Nov. 13, 2026. 10:00 a.m.", "event_schedule_missing"),
    ("Nov. 13, 2026 10:00 a.m. - Dec. 31, 2026 5:00 p.m. or 6:00 p.m.", "event_schedule_missing"),
    ("Nov. 1, 2026. 1:30 a.m. - 2:30 a.m.", "timezone_ambiguous"),
    ("Mar. 8, 2026. 2:30 a.m. - 3:30 a.m.", "timezone_nonexistent"),
])
def test_contradictory_or_incomplete_schedules_are_never_guessed(schedule, reason):
    with pytest.raises(ValueError, match="^" + reason + "$"):
        va.parse_schedule(schedule)


@pytest.mark.parametrize("html,reason", [
    (PAGE.replace("<h2>When</h2>", "<h2>Other information</h2>"), "event_schedule_missing"),
    (PAGE.replace("Nov. 7, 2026. 11:00 a.m. - 12:30 p.m.", "Time to be confirmed")
         .replace("</main>", "<h2>Additional dates</h2><div>Nov. 8, 2026. 1:00 p.m. - 2:00 p.m.</div></main>"),
     "event_schedule_missing"),
    (PAGE.replace("</main>", "<h2>When</h2><div>Nov. 8, 2026. 1:00 p.m. - 2:00 p.m.</div></main>"),
     "event_schedule_ambiguous"),
])
def test_primary_when_cannot_be_replaced_by_prose_or_additional_dates(html, reason):
    with patch.object(va, "record") as normalized:
        with pytest.raises(ValueError, match="^" + reason + "$"):
            va.parse_event(html, CAL_LINK, PARK)
    normalized.assert_not_called()


def test_additional_dates_do_not_override_primary_same_day_schedule():
    html = PAGE.replace("</main>", "<h2>Additional dates</h2><div>Nov. 8, 2026. 1:00 p.m. - 2:00 p.m.</div></main>")
    with patch.object(va, "record", return_value={"id": "primary"}) as normalized:
        va.parse_event(html, CAL_LINK, PARK)
    assert normalized.call_args.args[1] == "2026-11-07T11:00:00-05:00"
    assert normalized.call_args.args[2] == "2026-11-07T12:30:00-05:00"


def test_bad_later_detail_logs_safe_identity_and_never_stages_partial_records(capsys):
    bad_id = "2026-10-29-11-23-23-287887-qd6"
    listing = ('<h3>Park: Occoneechee State Park</h3>'
               f'<a href="/state-parks/event?id={ID}">First</a>'
               f'<a href="/state-parks/event?id={bad_id}">Second</a>')
    invalid = PAGE.replace("Nov. 7, 2026. 11:00 a.m. - 12:30 p.m.", "Unspecified publisher time")
    with patch.object(worker, "fetch_publisher", side_effect=[listing, PAGE, invalid]), \
            patch.object(va, "record", return_value={"id": "first"}), \
            patch.object(worker, "supabase_rpc", return_value=True) as rpc:
        result = worker._process_claimed_source(SOURCE)
    assert result["complete"] == 0 and result["failed"] == 1 and result["staged"] == 0
    assert result["failure_scope"] == "source" and result["error_code"] == "event_schedule_missing"
    assert all(call.args[0] != "community_collector_record_staged_events" for call in rpc.call_args_list)
    error = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert error == {"event": "virginia_parks_event_error", "source_key": "virginia_state_parks_oc",
                     "event_id": bad_id, "error_code": "event_schedule_missing"}
    assert "Unspecified publisher time" not in repr(error)


def test_offsite_clarksville_town_hall_uses_actual_venue_not_park_pin():
    html = PAGE.replace("Terrace Gardens", "Clarksville Town Hall").replace(
        "Explore the history of the Occoneechee Plantation on this one-mile guided hike around the Plantation Trail and natural history.",
        "The Friends group meets at the Clarksville Town Hall (located at 321 Virginia Ave, Clarksville, VA 23927) in the Chamber Room. Everyone is welcome."
    )
    with patch.object(va, "record", return_value={"id": "townhall", "lat": None, "lng": None}) as normalized:
        result = va.parse_event(html, CAL_LINK, PARK)
    assert result["location_provenance"] == "publisher_offsite_street_pending_geocode"
    assert "321 Virginia Ave, Clarksville, VA 23927" in result["description"]
    assert normalized.call_args.args[3] == "Clarksville Town Hall"
    assert normalized.call_args.args[4] == "321 Virginia Ave, Clarksville, VA 23927"
    assert normalized.call_args.args[5] == "Clarksville"
    assert normalized.call_args.kwargs["lat"] is None
    assert normalized.call_args.kwargs["lng"] is None
    assert not normalized.call_args.kwargs["publisher_geo"]


def test_unrelated_publisher_address_is_not_used_for_offsite_location():
    html = PAGE.replace("Terrace Gardens", "Clarksville Town Hall").replace(
        "Explore the history of the Occoneechee Plantation on this one-mile guided hike around the Plantation Trail and natural history.",
        "The activity meets at Clarksville Town Hall, and organizers will visit 123 Other Rd, Richmond, VA 23220 later. The venue itself has no confirmed street address."
    )
    # If the publisher's paragraph mentions the meeting location and another
    # unrelated street address, we should not borrow an arbitrary destination.
    with pytest.raises(ValueError, match="offsite_venue_requires_address"):
        va.parse_event(html, CAL_LINK, PARK)


def test_skips_offsite_meeting_with_unresolved_address():
    html=PAGE.replace("Terrace Gardens","Clarksville Town Hall")
    with pytest.raises(ValueError, match="offsite_venue_requires_address"):
        va.parse_event(html,CAL_LINK,PARK)


def test_source_must_match_registered_park_and_exact_url():
    with pytest.raises(ValueError, match="unregistered_html_calendar"):
        va.collect({**SOURCE,"feed_url":"https://evil.example/events"},lambda *_: pytest.fail("no fetch"))
    with pytest.raises(ValueError, match="unregistered_html_source"):
        va.collect({**SOURCE,"platform_adapter":"wordpress"},lambda *_: pytest.fail("no fetch"))
    with pytest.raises(ValueError, match="park_code_missing"):
        va.collect({**SOURCE,"source_key":"virginia_state_parks_zz","feed_url":va.CALENDAR+"?eventtype=all&srchloc=ZZ"},lambda *_: pytest.fail("no fetch"))


def test_discovery_uses_park_context_not_every_link_on_statewide_page():
    other = "2026-10-10-15-06-23-053520-hfq"
    html=f"""<article><h3>Occoneechee State Park</h3>
    <a href="/state-parks/event?id={ID}">View Details</a></article>
    <article><h3>Douthat State Park</h3>
    <a href="/state-parks/event?id={other}">View Details</a></article>"""
    links, total = va.discover(html,PARK)
    assert total==2
    assert links == [CAL_LINK]


def test_exact_html_adapter_dispatch_does_not_use_wordpress_or_ics():
    listing=f'<article><h3>Occoneechee State Park</h3><a href="/state-parks/event?id={ID}">View Details</a></article>'
    paths=[]
    def fetch(url,accept):
        paths.append(url)
        return listing if "/events?" in url else PAGE
    with patch.object(va,"record",return_value={"id":"vsp:oc:"+ID,"title":"Plantation Discovery Hike",
                  "lat":PARK["lat"],"lng":PARK["lng"],"event_url":CAL_LINK}) as mocked, \
         patch("roomquest.wordpress_adapter.collect") as wordpress, \
         patch.object(worker,"fetch_publisher",side_effect=lambda url,accept,**kwargs:fetch(url,accept)):
        result=worker.preview_source(SOURCE)
    assert result["p_future_count"]==1
    assert result["p_events"][0]["description"].startswith("Explore the history")
    assert result["p_events"][0]["description"].endswith("Meeting Location: Terrace Gardens")
    assert paths==[va.listing_url(PARK),CAL_LINK]
    wordpress.assert_not_called()


class FakeHandler:
    path="/api/html-demand"
    headers={"Content-Length":"0"}
    def reply(self,status,body):
        return status,body


def test_independent_html_route_does_not_accept_legacy_category():
    fake=FakeHandler()
    payload=json.dumps({"category":"ical","ticket":"01234567-0123-0123-0123-0123456789ab"}).encode()
    fake.headers={"Content-Length":str(len(payload))}
    fake.rfile=io.BytesIO(payload)
    with patch("api.html_demand.collect_category") as dispatcher:
        result=HtmlHandler.do_POST(fake)
    assert result[0]==400
    dispatcher.assert_not_called()


def test_html_route_uses_only_its_own_ticket_category():
    fake=FakeHandler()
    ticket="01234567-0123-0123-0123-0123456789ab"
    payload=json.dumps({"category":"html","ticket":ticket}).encode()
    fake.headers={"Content-Length":str(len(payload))}
    fake.rfile=io.BytesIO(payload)
    with patch("api.html_demand.collect_category",return_value={"outcome":"idle"}) as dispatcher:
        status,body=HtmlHandler.do_POST(fake)
    assert status==200
    assert body=={"outcome":"idle"}
    dispatcher.assert_called_once_with("html",ticket)
