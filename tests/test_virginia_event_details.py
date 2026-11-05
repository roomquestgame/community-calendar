"""Virginia descriptions and explicit publisher facts, without network or writes."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from roomquest import preview_worker as worker
from roomquest import virginia_state_parks as va

FIXTURES = Path(__file__).parent / "fixtures" / "virginia_state_parks"
URL = va.ROOT + "/state-parks/event?id=2026-10-17-16-00-48-597528-s8b"
PARK = va.catalog()["oc"]
NARRATIVE = "Explore the plantation history with a ranger on a one-mile guided hike."
TYPE_BASE = "/state-parks/events?type=2021-08-23-20-46-46-872664-"


def page(description=None, *, details="", types="", tail=""):
    description = description if description is not None else "<p>" + NARRATIVE + "</p>"
    return (
        "<main><h1>Plantation Discovery Hike</h1><h2>Where</h2>"
        "<p><b>Program Location:</b> Terrace Gardens<br>"
        "<b>Main Park Address:</b> Occoneechee State Park, "
        "1192 Occoneechee Park Rd., Clarksville, VA 23927.</p>"
        "<h2>When</h2><p>Nov. 7, 2026. 11:00 a.m. - 12:30 p.m.</p>"
        '<div id="event_description">' + description + "</div>"
        + ('<h2>Other details</h2><p>' + details + '</p>' if details else "")
        + ('<h2>Event types</h2><p>' + types + '</p>' if types else "")
        + tail + "</main>"
    )


def parse(html, *, url=URL, park=PARK):
    with patch.object(va, "record", return_value={"id": "test", "lat": park["lat"], "lng": park["lng"]}):
        return va.parse_event(html, url, park)


def type_link(label, number=1):
    return '<a href="' + TYPE_BASE + str(number) + '">' + label + "</a>"


def test_narrative_replaces_address_and_preserves_meeting_point():
    event = parse(page())
    assert event["description"] == NARRATIVE + "\n\nMeeting Location: Terrace Gardens"
    assert "Main Park Address" not in event["description"]
    assert "1192 Occoneechee Park" not in event["description"]
    assert event["publisher_details"] == {"meeting_location": "Terrace Gardens"}
    assert event["details_extractor_version"] == "virginia_event_details_v1"
    assert event["details_evidence_url"] == URL
    assert event["image_extractor_version"] == "publisher_event_html_v2"


def test_paragraphs_lists_and_inline_emphasis_remain_readable():
    html = page("<p>Learn <strong>local history</strong> with a ranger.</p>"
                "<p>Bring the following:</p><ul><li>Water &amp; snacks.</li><li>Walking shoes.</li></ul>"
                "<ol><li>Meet at the garden.</li><li>Follow the ranger.</li></ol>")
    text = parse(html)["description"]
    assert text.startswith("Learn local history with a ranger.\n\nBring the following:")
    assert "- Water & snacks." in text and "- Walking shoes." in text
    assert "1. Meet at the garden." in text and "2. Follow the ranger." in text
    assert not any(tag in text for tag in ("<strong>", "<li>", "</p>"))


@pytest.mark.parametrize("wrapper", [
    '<nav>{}</nav>', '<aside>{}</aside>', '<header>{}</header>', '<footer>{}</footer>',
    '<div hidden>{}</div>', '<div aria-hidden="true">{}</div>',
    '<div role="complementary">{}</div>', '<div class="related-events">{}</div>',
    '<div id="event_default_text">{}</div>', '<div class="event-default-text">{}</div>',
    '<template>{}</template>', '<form>{}</form>',
])
def test_description_excludes_hidden_and_unrelated_content(wrapper):
    event = parse(page("<p>" + NARRATIVE + "</p>" + wrapper.format("<p>Unrelated paid concert.</p>")))
    assert event["description"].startswith(NARRATIVE)
    assert "Unrelated paid concert" not in event["description"]


@pytest.mark.parametrize("heading", [
    "Documents", "Other details", "Event types", "Additional dates",
    "Add to calendar", "Know Before You Go", "Related events",
])
def test_description_stops_at_embedded_page_tail_heading(heading):
    text = parse(page("<p>" + NARRATIVE + "</p><h2>" + heading + "</h2>"
                      "<p>Unrelated seasonal promotion.</p>"))["description"]
    assert text.startswith(NARRATIVE)
    assert "Unrelated seasonal promotion" not in text
    assert heading not in text


@pytest.mark.parametrize("mode", ["missing", "duplicate", "empty"])
def test_absent_ambiguous_or_empty_narrative_never_uses_address_fallback(mode):
    html = page()
    if mode == "missing":
        html = html.replace('id="event_description"', 'id="unrecognized_description"')
    elif mode == "duplicate":
        html = html.replace("</main>", '<div id="event_description"><p>Another description.</p></div></main>')
    else:
        html = html.replace(NARRATIVE, "")
    event = parse(html)
    assert event["description"] is None
    assert event["publisher_details"]["meeting_location"] == "Terrace Gardens"
    assert event["details_evidence_url"] == URL


def test_long_description_reserves_meeting_location_and_never_splits_the_cap():
    body = "<p>First meaningful paragraph.</p><p>" + "Trail interpretation and geology. " * 500 + "</p>"
    event = parse(page(body))
    assert len(event["description"]) <= va.MAX_DESCRIPTION
    assert event["description"].startswith("First meaningful paragraph.\n\n")
    assert "…\n\nMeeting Location: Terrace Gardens" in event["description"]
    assert event["publisher_details"]["meeting_location"] == "Terrace Gardens"


def test_meeting_point_in_narrative_is_not_duplicated():
    text = parse(page("<p>Meet at Terrace Gardens for " + NARRATIVE.lower() + "</p>"))["description"]
    assert text.count("Terrace Gardens") == 1
    assert "Meeting Location:" not in text


def test_meeting_point_at_the_clipping_boundary_is_still_retained():
    prefix = "Walk " * 2397
    body = prefix + "Terrace Gardens" + " with the ranger for an interpretive program."
    assert "Terrace Gardens" in body[:va.MAX_DESCRIPTION]
    text = parse(page("<p>" + body + "</p>"))["description"]
    assert len(text) <= va.MAX_DESCRIPTION
    assert text.endswith("\n\nMeeting Location: Terrace Gardens")
    assert text.count("Terrace Gardens") == 1


def test_raw_publisher_types_are_bounded_unique_and_not_guessed_activities():
    html = page(types=type_link("Kids/Family") + " | " + type_link("Outdoor/Nature/Natural History", 2)
                + " | " + type_link("kids/family", 3) + " | " + type_link("Volunteer Events", 4))
    event = parse(html)
    assert event["publisher_categories"] == ["Kids/Family", "Outdoor/Nature/Natural History", "Volunteer Events"]
    assert "category" not in event  # record() is mocked; the collector adds no inferred category.


def test_publisher_types_require_the_explicit_unambiguous_type_section():
    wrong = '<h2>Other events</h2><p>' + type_link("Music") + '</p>'
    assert parse(page(tail=wrong))["publisher_categories"] == []
    duplicate = '<h2>Event types</h2><p>' + type_link("Music") + '</p>'
    assert parse(page(types=type_link("Kids/Family"), tail=duplicate))["publisher_categories"] == []


def test_publisher_type_links_do_not_accept_unrelated_urls_or_overlong_labels():
    types = (type_link("x" * 101) + '<a href="https://example.org/event">Sports</a>'
             '<a href="javascript:alert(1)">Music</a>'
             '<a href="/state-parks/event?id=2026-01-01-unrelated">Concert</a>'
             + "".join(type_link("Label " + str(i), i) for i in range(25)))
    labels = parse(page(types=types))["publisher_categories"]
    assert len(labels) == 20
    assert labels == ["Label " + str(i) for i in range(20)]


def test_explicit_fee_and_children_facts_survive_as_raw_evidence():
    details = ("Standard parking or admission fee applies: <b>No</b>.<br>"
               "Extra fee: <b>$20 for five sessions.</b><br>"
               "Registration required: <b>Yes.</b><br>"
               "Children welcome: <b>No</b>.<br>"
               "Phone: <b>804-492-4410</b>")
    event = parse(page(details=details))
    assert event["publisher_details"] == {
        "meeting_location": "Terrace Gardens", "standard_fee": "No.",
        "extra_fee": "$20 for five sessions.", "registration_required": "Yes.",
        "children_welcome": "No.",
    }
    assert "is_free" not in event and "is_kid_friendly" not in event


def test_conditional_raw_fee_is_not_truncated_or_promoted_to_free():
    conditional = "Free for members only; $10 for nonmembers."
    event = parse(page(details="Extra fee: <b>" + conditional + "</b>"))
    assert event["publisher_details"]["extra_fee"] == conditional
    assert "is_free" not in event
    oversized = "No " + "only for registered participants " * 20
    event = parse(page(details="Extra fee: <b>" + oversized + "</b>"))
    assert "extra_fee" not in event["publisher_details"]


def test_conflicting_and_oversized_metadata_does_not_become_a_short_positive():
    details = ("Children welcome: <b>Yes</b><br>Children welcome: <b>No</b><br>"
               "Extra fee: No<br>Extra fee: " + "conditions " * 40)
    result = parse(page(details=details))["publisher_details"]
    assert "children_welcome" not in result and "extra_fee" not in result
    same = parse(page(details="Children welcome: Yes.<br>Children welcome: Yes"))["publisher_details"]
    assert same["children_welcome"] == "Yes"


def test_duplicate_metadata_headings_fail_closed_for_optional_facts():
    result = parse(page(details="Children welcome: Yes",
                        tail="<h2>Other details</h2><p>Children welcome: No</p>"))["publisher_details"]
    assert "children_welcome" not in result


@pytest.mark.parametrize("details", [
    "<div><p>Children welcome: <b>No</b></p><p>Extra fee: <b>$20</b></p></div>",
    "<ul><li>Children welcome: <b>No</b></li><li>Extra fee: <b>$20</b></li></ul>",
    "<table><tr><th>Children welcome:</th><td>No</td></tr><tr><th>Extra fee:</th><td>$20</td></tr></table>",
    "<dl><dt>Children welcome:</dt><dd>No</dd><dt>Extra fee:</dt><dd>$20</dd></dl>",
])
def test_metadata_block_rows_keep_negative_audience_and_fee_facts_separate(details):
    html = page(types=type_link("Kids/Family"), tail="<h2>Other details</h2>" + details)
    event = parse(html)
    assert event["publisher_details"]["children_welcome"] == "No"
    assert event["publisher_details"]["extra_fee"] == "$20"
    assert event["publisher_categories"] == ["Kids/Family"]


def test_registration_references_keep_safe_original_links_without_requesting_them(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Parsing publisher HTML must not fetch registration URLs.")
    monkeypatch.setattr(worker, "fetch_publisher", forbidden)
    text = ('<p>Register here: <a href="https://registration.example.org/program?a=1&amp;b=2">Program form</a>.</p>'
            '<p><a href="https://forms.example.org/apply">Volunteer registration</a></p>')
    event = parse(page(text))
    assert event["publisher_details"]["registration_urls"] == [
        "https://registration.example.org/program?a=1&b=2", "https://forms.example.org/apply",
    ]
    assert "Program form" in event["description"]


@pytest.mark.parametrize("url", [
    "http://example.org/register", "https://127.0.0.1/register",
    "https://localhost/register", "https://192.168.1.1/register",
    "https://user:password@example.org/register", "https://example.org:8080/register",
    "javascript:alert(1)", "data:text/html,register", "mailto:register@example.org",
    "https://example.org/a\nb", "https://[", "https://example.org/" + "a" * 500,
])
def test_registration_links_reject_nonpublic_ambiguous_or_oversized_urls(url):
    result = parse(page('<p><a href="' + url + '">Register</a></p>'))["publisher_details"]
    assert "registration_urls" not in result


@pytest.mark.parametrize("content", [
    '<aside><a href="https://example.org/register">Register</a></aside>',
    '<div hidden><a href="https://example.org/register">Register</a></div>',
    '<div class="related-events"><a href="https://example.org/register">Register</a></div>',
    '<h2>Additional dates</h2><a href="https://example.org/register">Register</a>',
])
def test_registration_does_not_collect_hidden_or_unrelated_event_links(content):
    assert "registration_urls" not in parse(page(content))["publisher_details"]


def test_registration_count_and_total_encoded_details_are_bounded():
    links = "".join('<p><a href="https://example.org/register/' + str(n) + '">Register</a></p>' for n in range(6))
    details = ("Standard parking or admission fee applies: " + "é" * 300 + "<br>"
               "Extra fee: " + "é" * 300 + "<br>"
               "Children welcome: " + "é" * 300 + "<br>"
               "Registration required: " + "é" * 300)
    result = parse(page(links, details=details))["publisher_details"]
    assert len(result.get("registration_urls", [])) <= 3
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= va.MAX_PUBLISHER_DETAILS_BYTES


@pytest.mark.parametrize("name,park_code", [
    ("archery-club", "bc"), ("widewater-volunteers", "ww"),
])
def test_captured_real_publisher_description_and_labels(name, park_code):
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    evidence = next(p for p in provenance["pages"] if p["fixture"] == name + ".html")
    raw = (FIXTURES / evidence["fixture"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == evidence["fixture_sha256"]
    event = parse(raw.decode(), url=evidence["source_url"], park=va.catalog()[park_code])
    assert "Program Location:" not in event["description"] and "Main Park Address:" not in event["description"]
    assert event["details_evidence_url"] == evidence["source_url"]
    assert "Outdoor/Nature/Natural History" in event["publisher_categories"]
    assert event["publisher_details"]["standard_fee"] == "No."
    if name == "archery-club":
        assert event["description"].startswith("Interested in learning about archery in an adult setting?")
        assert "18 years old and up" in event["description"]
        assert "$20" in event["description"]
        assert "Water and restrooms are not available" in event["description"]
        assert event["publisher_details"]["children_welcome"] == "No."
        assert event["publisher_details"]["extra_fee"] == "$20 for five sessions."
        assert event["publisher_categories"] == ["Competition", "Outdoor/Nature/Natural History"]
        assert event.get("image_url") is None  # Preserve the photo-v2 generic-logo exclusion.
    else:
        assert event["description"].startswith("Enjoy the Autumn days")
        assert "Beaver Dam Trail Maintenance" in event["description"]
        assert "With 44 parks" not in event["description"]
        assert "license plate" not in event["description"]
        assert event["publisher_details"]["children_welcome"] == "Yes."
        assert event["publisher_details"]["extra_fee"] == "No."
        assert "Volunteer Events" in event["publisher_categories"]
        assert event["image_url"].startswith("https://www.flickr.com/photo_download.gne?")
        assert len(event["publisher_details"]["registration_urls"]) == 2


def test_details_staging_preserves_photo_capability_and_existing_completion_rpc():
    source = {"source_key": "virginia_state_parks_oc", "kind": "html", "platform_adapter": "html"}
    event = parse(page(details="Children welcome: Yes"))
    output = {"p_source_key": source["source_key"], "p_samples": [event], "p_future_count": 1,
              "p_venue_count": 1, "p_error": None, "p_events": [event],
              "p_parser_capability": "publisher_event_html_v2"}
    calls = []
    def rpc(path, payload):
        calls.append((path, payload))
        return 1
    with patch.object(worker, "preview_source", return_value=output), patch.object(worker, "supabase_rpc", side_effect=rpc):
        assert worker._process_claimed_source(source)["complete"] == 1
    assert calls[0][0] == "community_collector_record_staged_events"
    staged = calls[0][1]["p_events"][0]
    assert staged["details_extractor_version"] == "virginia_event_details_v1"
    assert staged["publisher_details"]["children_welcome"] == "Yes"
    assert calls[1][0] == "community_collector_record_preview_v3"
    assert calls[1][1]["p_parser_capability"] == "publisher_event_html_v2"


def test_meaningful_evidence_after_old_cap_is_preserved():
    text = "Trail information. " * 140 + " Adults only. Program fee is $20. Archery instruction follows."
    event = parse(page("<p>" + text + "</p>"))
    assert "Adults only. Program fee is $20. Archery instruction follows." in event["description"]
