"""MyCountyParks' observed markup, represented with small synthetic fixtures.

No network or database calls. The shared record converter is isolated here;
its opt-in ongoing-event behavior has separate integration coverage.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from roomquest import mycountyparks as mcp

NOW = datetime(2026, 11, 3, 9, tzinfo=mcp.TZ)
LIVE_CASES = json.loads((Path(__file__).parent / "fixtures/mycountyparks_live_compatibility.json").read_text())["events"]
TIME_CONFLICT_CASES = [case for case in LIVE_CASES if case["issue"] == "midnight_noon"]
HYPHENATED_ADDRESS_CASES = [case for case in LIVE_CASES if case["issue"] == "hyphenated_street"]


def entry(event_id="1001", *, title="Nature Walk", county="Linn", when="NOV 14 2026 10:00 AM - 2:00 PM"):
    slug = county.replace("'", "").replace(" ", "-")
    return {"id": event_id, "title": title, "county": county, "date": when,
            "url": mcp.ROOT + f"/County/{slug}/Park/Parent-Park/Events/{event_id}/Nature-Walk"}


def listing(*entries, total=None, county=None):
    total = len(entries) if total is None else total
    county = county or (entries[0]["county"] if entries else "Linn")
    cards = []
    for item in entries:
        cards.append('<div class="swiper-slide scroll-item">'
            f'<a class="event-link" data-county="{escape(item["county"])}" href="{escape(item["url"])}">'
            '<figure><img src="https://content.mycountyparks.com/Production/RelatedItem/Content/example-image"></figure>'
            f'<p class="date">{escape(item["date"])}</p><h3>{escape(item["title"])}</h3></a></div>')
    return f'<div id="countyData" data-countyname="{escape(county)}"></div>' + \
        '<div id="partialViewContainer"><div class="auto-grid-4">' + ''.join(cards) + \
        f'</div><input id="hdnTotalCount" type="hidden" value="{total}"></div>'


def detail(item=None, *, title=None, event_id=None, county=None,
           summary="Explore local wildlife during this guided public program.",
           venue="Bender Pool", street="940 14th Avenue SE", city="Cedar Rapids IA 52403",
           registration="Reservations are not required for this event.", cost="", when=None,
           location_html=None):
    item = item or entry()
    title, event_id, county = title or item["title"], event_id or item["id"], county or item["county"]
    when = when or item["date"].split(" - ")[0]
    price = f'<hr><h3>Cost</h3><p>{escape(cost)}</p>' if cost else ''
    if location_html is None:
        location_html = (f'<p><strong>{escape(venue)}</strong><br>{escape(street)}<br>'
                         f'{escape(city)}<br>Parent Park<br>Contact staff</p>')
    return ('<html><main id="main-content"><header class="detail-header">'
            f'<h1>{escape(title)}</h1><p class="date">{escape(when)}</p>'
            f'<a id="print" data-county="{escape(county)}" data-event-id="{event_id}">Print</a>'
            f'<a id="lnkOutlook" href="/Event/AddToOutLook?eventId={event_id}">Add to Outlook</a>'
            '</header><section><div id="sidebar-affix"><div class="small-type">'
            '<h2>Location</h2><div id="map">Parent park map</div><br>'
            + location_html +
            '</div><div>' + registration + '</div></div>'
            '<div class="col small-type"><h2>Event Summary</h2><p>' + escape(summary) + '</p>'
            + price + '<hr><h2>Category</h2><p>Programs</p><hr></div></section>'
            '<script>window.latitude="42.08289";window.longitude="-91.76340";</script>'
            '<section><h3>Related Events</h3><h1>Unrelated title</h1>'
            '<p class="date">JAN 01 2099 12:00 AM</p></section></main></html>')


def normalized(title, start, end, venue, street, city, url, identity, **kwargs):
    return {"id": identity, "title": title, "starts_at": datetime.fromisoformat(start).astimezone(timezone.utc).isoformat(),
            "ends_at": datetime.fromisoformat(end).astimezone(timezone.utc).isoformat() if end else None,
            "venue_name": venue, "venue_address": street, "venue_city": city,
            "event_url": url, "lat": kwargs.get("lat"), "lng": kwargs.get("lng"),
            "category": kwargs.get("category"), "reason": "missing_verified_venue_geo"}


@pytest.fixture(autouse=True)
def record_spy(monkeypatch):
    spy = Mock(side_effect=normalized)
    monkeypatch.setattr(mcp, "record", spy)
    return spy


def parsed(item=None):
    item = item or entry()
    return mcp.parse_listing(listing(item), item["county"])[0][0]


def live_entry(case):
    return {"id": case["id"], "title": case["title"], "county": case["county"],
            "date": case["listing_date"], "url": case["url"]}


def test_all_county_sources_have_exact_registered_identities():
    assert len(mcp.COUNTIES) == 99
    sources = []
    for county in mcp.COUNTIES:
        source = mcp.source_for_county(county)
        assert mcp.source_county(source) == county
        assert source["source_key"] == "mycountyparks_ia_" + county
        assert source["kind"] == source["platform_adapter"] == "html"
        sources.append(source)
    assert len({source["feed_url"] for source in sources}) == 99
    with pytest.raises(ValueError, match="county_unregistered"):
        mcp.source_for_county("not_an_iowa_county")


@pytest.mark.parametrize("county,slug", [
    ("iowa", "Iowa"), ("madison", "Madison"), ("floyd", "Floyd"),
    ("obrien", "OBrien"), ("black_hawk", "Black-Hawk"),
    ("buena_vista", "Buena-Vista"), ("cerro_gordo", "Cerro-Gordo"),
    ("des_moines", "Des-Moines"), ("palo_alto", "Palo-Alto"),
    ("van_buren", "Van-Buren"),
])
def test_verified_calendar_route_spellings(county, slug):
    assert mcp.source_for_county(county)["feed_url"] == mcp.ROOT + f"/County/{slug}/Events"


@pytest.mark.parametrize("updates", [
    {"source_key": "arbitrary_linn"}, {"source_key": "mycountyparks_ia_unknown"},
    {"source_key": "mycountyparks_ia_o_brien", "feed_url": mcp.ROOT + "/County/OBrien/Events"},
    {"source_key": "mycountyparks_ia_blackhawk", "feed_url": mcp.ROOT + "/County/Black-Hawk/Events"},
    {"kind": "json"}, {"platform_adapter": "wordpress"},
    {"feed_url": "https://evil.example/County/Linn/Events"},
    {"feed_url": mcp.ROOT + "/County/Story/Events"},
    {"feed_url": mcp.ROOT + "/County/Linn/Events?anything=1"},
    {"feed_url": mcp.ROOT + "/County/Linn/Events/"},
    {"feed_url": mcp.ROOT + "/County/Linn/Events#calendar"},
    {"feed_url": "http://www.mycountyparks.com/County/Linn/Events"},
])
def test_source_scope_rejected_before_fetch(updates):
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    with pytest.raises(ValueError):
        mcp.collect({**mcp.source_for_county("linn"), **updates}, fetch, now=NOW)
    fetch.assert_not_called()


def test_listing_query_is_county_scoped_and_sixty_days():
    url = mcp.listing_url("iowa", today=NOW.date(), page_number=2)
    assert urlsplit(url).path == "/County/Iowa/Events"
    fields = parse_qs(urlsplit(url).query)
    assert fields["EventSearchModel.CountyName"] == ["Iowa"]
    assert fields["EventSearchModel.StartDate"] == ["2026-11-03"]
    assert fields["EventSearchModel.EndDate"] == ["2027-01-02"]
    assert fields["EventSearchModel.PageNumber"] == ["2"]
    assert "__RequestVerificationToken" not in fields


def test_schedule_uses_listing_wall_time_and_chicago_dst():
    event = parsed()
    assert event.start.isoformat() == "2026-11-14T10:00:00-06:00"
    assert event.end.isoformat() == "2026-11-14T14:00:00-06:00"
    summer_start, summer_end = mcp.parse_schedule("JUL 04 2027 6:00 PM - 8:00 PM")
    assert summer_start.utcoffset() == timedelta(hours=-5)
    assert summer_end.utcoffset() == timedelta(hours=-5)


@pytest.mark.parametrize("when,reason", [
    ("MAR 08 2026 2:30 AM", "timezone_nonexistent"),
    ("NOV 01 2026 1:30 AM", "timezone_ambiguous"),
    ("FEB 30 2027 10:00 AM", "schedule_invalid"),
    ("NOV 14 2026 25:00 PM", "schedule_invalid"),
    ("NOV 14 2026", "schedule_invalid"),
    ("NOV 14 2026 11:00 PM - 1:00 AM", "end_invalid"),
    ("NOV 14 2026 10:00 AM - NOV 15 2026 2:00 PM", "schedule_invalid"),
])
def test_ambiguous_missing_and_malformed_schedules_are_not_guessed(when, reason):
    with pytest.raises(ValueError, match=reason):
        mcp.parse_schedule(when)


def test_floyd_repeated_end_time_retains_published_start_and_unknown_end():
    # Observed listing and detail header on 2026-11-03; the detail has no end.
    item = entry("29962", county="Floyd", title="Evergreen Wreath & Porch Pot Workshop",
                 when="NOV 29 2026 2:00 PM\r\n - 2:00 PM")
    item["url"] = (mcp.ROOT + "/County/Floyd/Park/Tosanak-Recreation-Area/Events/29962/"
                   "Evergreen-Wreath-Porch-Pot-Workshop")
    html = detail(item, when="NOV 29 2026 2:00 PM",
                  venue="Learning Center - Tosanak Recreation Area",
                  street="2543 Glass Road", city="Marble Rock IA 50468")
    event = parsed(item)
    assert event.start.isoformat() == "2026-11-29T14:00:00-06:00" and event.end is None
    result = mcp.parse_event(html, event, now=datetime(2026, 11, 29, 16, tzinfo=mcp.TZ))
    assert result["starts_at"] == "2026-11-29T20:00:00+00:00"
    assert result["ends_at"] is None
    assert result["venue_address"] == "2543 Glass Road, Marble Rock, IA 50468"
    assert result["lat"] is None and result["lng"] is None
    assert mcp.parse_event(html, event, now=datetime(2026, 11, 29, 17, tzinfo=mcp.TZ)) is None


def test_only_zero_duration_end_is_treated_as_missing():
    start, end = mcp.parse_schedule("NOV 29 2026 2:00 PM - 3:00 PM")
    assert end - start == timedelta(hours=1)
    with pytest.raises(ValueError, match="end_invalid"):
        mcp.parse_schedule("NOV 29 2026 2:00 PM - 1:00 PM")


@pytest.mark.parametrize("case", TIME_CONFLICT_CASES, ids=lambda case: case["county_key"] + case["id"])
def test_observed_midnight_noon_conflicts_are_never_normalized(case, record_spy):
    events, total = mcp.parse_listing(case["listing_html"], case["county_key"])
    assert total == 1 and events[0].end is None
    assert events[0].start.time().isoformat() == "00:00:00"
    with pytest.raises(ValueError, match="^mycountyparks_event_midnight_noon_conflict$"):
        mcp.parse_event(case["detail_html"], events[0], now=NOW)
    record_spy.assert_not_called()


@pytest.mark.parametrize("case", TIME_CONFLICT_CASES, ids=lambda case: case["county_key"] + case["id"])
def test_observed_conflict_is_withheld_while_verified_county_record_is_kept(case, capsys, record_spy):
    valid = entry("9991", county=case["county"])
    fetch = Mock(side_effect=[listing(live_entry(case), valid), case["detail_html"], detail(valid)])
    rows = mcp.collect(mcp.source_for_county(case["county_key"]), fetch, now=NOW)
    assert len(rows) == 1 and rows[0]["id"] == f"mycountyparks:{case['county_key']}:9991"
    assert rows[0]["starts_at"] == "2026-11-14T16:00:00+00:00"
    assert rows[0]["ends_at"] == "2026-11-14T20:00:00+00:00"
    assert fetch.call_count == 3 and record_spy.call_count == 1
    assert (f"mycountyparks_time_unresolved {case['county_key']} {case['id']} "
            "mycountyparks_event_midnight_noon_conflict") in capsys.readouterr().err


def test_all_conflicted_source_is_not_a_healthy_empty_result(record_spy):
    case = TIME_CONFLICT_CASES[0]
    fetch = Mock(side_effect=[case["listing_html"], case["detail_html"]])
    with pytest.raises(ValueError, match="^mycountyparks_event_evidence_unavailable$"):
        mcp.collect(mcp.source_for_county(case["county_key"]), fetch, now=NOW)
    assert fetch.call_count == 2
    record_spy.assert_not_called()


def test_mixed_conflicted_and_missing_address_source_is_not_healthy_empty(record_spy, capsys):
    case = TIME_CONFLICT_CASES[0]
    missing = entry("9992", county=case["county"])
    fetch = Mock(side_effect=[listing(live_entry(case), missing), case["detail_html"],
                             detail(missing, street="P.O. Box 123")])
    with pytest.raises(ValueError, match="^mycountyparks_event_evidence_unavailable$"):
        mcp.collect(mcp.source_for_county(case["county_key"]), fetch, now=NOW)
    errors = capsys.readouterr().err
    assert "mycountyparks_time_unresolved mahaska 29691" in errors
    assert "mycountyparks_address_unresolved mahaska 9992" in errors
    record_spy.assert_not_called()


@pytest.mark.parametrize("updates,reason", [
    (None, "event_structure_unverified"),
    ({"event_id": "9999"}, "event_identity_mismatch"),
    ({"title": "Unrelated public program"}, "event_title_mismatch"),
    ({"when": "NOV 14 2026 11:00 AM"}, "event_schedule_mismatch"),
    ({"summary": ""}, "event_summary_missing"),
])
def test_unknown_detail_errors_still_abort_after_verified_and_withheld_items(updates, reason, record_spy):
    case = TIME_CONFLICT_CASES[0]
    valid, broken = entry("9991", county=case["county"]), entry("9992", county=case["county"])
    broken_html = "<html>Unrecognized structure</html>" if updates is None else detail(broken, **updates)
    fetch = Mock(side_effect=[listing(valid, live_entry(case), broken), detail(valid),
                             case["detail_html"], broken_html])
    with pytest.raises(ValueError, match=reason):
        mcp.collect(mcp.source_for_county(case["county_key"]), fetch, now=NOW)
    assert record_spy.call_count == 1


@pytest.mark.parametrize("reason", ["publisher_http_503", "mycountyparks_event_midnight_noon_conflict"])
def test_transport_errors_cannot_be_classified_as_verified_record_exclusions(reason):
    case = TIME_CONFLICT_CASES[0]
    valid = entry("9991", county=case["county"])
    fetch = Mock(side_effect=[listing(valid, live_entry(case)), detail(valid), ValueError(reason)])
    with pytest.raises(ValueError, match="^" + reason + "$"):
        mcp.collect(mcp.source_for_county(case["county_key"]), fetch, now=NOW)


@pytest.mark.parametrize("listing_time,detail_time", [
    ("DEC 01 2026 12:00 AM", "DEC 01 2026 1:00 PM"),
    ("DEC 01 2026 12:00 AM - 1:00 AM", "DEC 01 2026 12:00 PM"),
    ("DEC 01 2026 12:00 AM", "DEC 01 2026 12:00 PM - 1:00 PM"),
    ("DEC 01 2026 12:00 PM", "DEC 01 2026 12:00 AM"),
    ("DEC 01 2026 12:00 AM", "DEC 02 2026 12:00 PM"),
    ("DEC 01 2026 12:01 AM", "DEC 01 2026 12:00 PM"),
    ("DEC 01 2026 12:00 AM", "DEC 01 2026 12:01 PM"),
])
def test_other_schedule_mismatches_remain_fatal(listing_time, detail_time, record_spy):
    item = entry(when=listing_time)
    with pytest.raises(ValueError, match="^mycountyparks_event_schedule_mismatch$"):
        mcp.parse_event(detail(item, when=detail_time), parsed(item), now=NOW)
    record_spy.assert_not_called()


@pytest.mark.parametrize("clock,utc_hour", [("12:00 AM", "06"), ("12:00 PM", "18")])
def test_matching_midnight_or_noon_evidence_keeps_its_published_start(clock, utc_hour):
    item = entry(when="NOV 14 2026 " + clock)
    result = mcp.parse_event(detail(item, when=item["date"]), parsed(item), now=NOW)
    assert result["starts_at"] == f"2026-11-14T{utc_hour}:00:00+00:00"
    assert result["ends_at"] is None


@pytest.mark.parametrize("county,key", [
    ("Mahaska", "mahaska"), ("Buena Vista", "buena_vista"),
    ("O'Brien", "obrien"), ("Des Moines", "des_moines"),
])
def test_nonpilot_counties_use_the_same_address_and_time_contract(county, key):
    item = entry(county=county)
    fetch = Mock(side_effect=[listing(item), detail(item)])
    result = mcp.collect(mcp.source_for_county(key), fetch, now=NOW)
    assert len(result) == 1 and result[0]["id"] == f"mycountyparks:{key}:1001"
    assert result[0]["starts_at"] == "2026-11-14T16:00:00+00:00"
    assert result[0]["venue_address"] == "940 14th Avenue SE, Cedar Rapids, IA 52403"
    assert result[0]["timezone"] == "America/Chicago"
    assert result[0]["lat"] is None and result[0]["lng"] is None
    assert fetch.call_count == 2


@pytest.mark.parametrize("url", [
    "https://evil.example/County/Linn/Park/Test/Events/1001/Walk",
    "//evil.example/County/Linn/Park/Test/Events/1001/Walk",
    "http://www.mycountyparks.com/County/Linn/Park/Test/Events/1001/Walk",
    "https://user@www.mycountyparks.com/County/Linn/Park/Test/Events/1001/Walk",
    "https://www.mycountyparks.com:444/County/Linn/Park/Test/Events/1001/Walk",
    "https://www.mycountyparks.com:bad/County/Linn/Park/Test/Events/1001/Walk",
    "https://www.mycountyparks.com.evil.example/County/Linn/Park/Test/Events/1001/Walk",
    "/County/Story/Park/Test/Events/1001/Walk",
    "/County/Linn/Park/Test/Events/1001/Walk?redirect=elsewhere",
    "/County/Linn/Park/Test/Events/1001/Walk#location",
    "/County/Linn/Park/%2e%2e/Events/1001/Walk",
    "/County/Linn/Park/Test/Events/not-an-id/Walk",
    "javascript:alert(1)",
])
def test_event_links_cannot_expand_source_scope(url):
    with pytest.raises(ValueError, match="event_url_unverified"):
        mcp.event_identity(url, "linn")


def test_detail_keeps_actual_address_and_never_parent_coordinates(record_spy):
    result = mcp.parse_event(detail(), parsed(), now=NOW)
    assert result["venue_name"] == "Bender Pool"
    assert result["venue_address"] == "940 14th Avenue SE, Cedar Rapids, IA 52403"
    assert result["venue_city"] == "Cedar Rapids"
    assert result["lat"] is None and result["lng"] is None
    assert result["starts_at"] == "2026-11-14T16:00:00+00:00"
    assert result["ends_at"] == "2026-11-14T20:00:00+00:00"
    assert result["timezone"] == "America/Chicago"
    assert result["location_provenance"] == "publisher_event_street_pending_geocode"
    assert record_spy.call_args.kwargs["publisher_geo"] is False
    assert record_spy.call_args.kwargs["retain_until_end"] is True
    assert "Unrelated title" not in result["description"]


@pytest.mark.parametrize("case", HYPHENATED_ADDRESS_CASES, ids=lambda case: case["id"])
def test_observed_mitchell_hyphenated_address_is_preserved_without_coordinates(case, record_spy):
    events, total = mcp.parse_listing(case["listing_html"], "mitchell")
    result = mcp.parse_event(case["detail_html"], events[0], now=NOW)
    assert total == 1
    assert result["venue_name"] == "Milton R. Owen Nature Center"
    assert result["venue_address"] == "1879-3 Highway 9, Osage, IA 50461"
    assert result["venue_city"] == "Osage"
    assert result["lat"] is None and result["lng"] is None
    assert result["ends_at"] is None
    assert result["starts_at"] == events[0].start.astimezone(timezone.utc).isoformat()
    assert result["location_provenance"] == "publisher_event_street_pending_geocode"
    assert record_spy.call_args.kwargs["publisher_geo"] is False


def test_both_observed_mitchell_events_can_complete_collection():
    fetch = Mock(side_effect=[listing(*(live_entry(case) for case in HYPHENATED_ADDRESS_CASES))]
                            + [case["detail_html"] for case in HYPHENATED_ADDRESS_CASES])
    rows = mcp.collect(mcp.source_for_county("mitchell"), fetch, now=NOW)
    assert {row["id"] for row in rows} == {"mycountyparks:mitchell:29817", "mycountyparks:mitchell:29815"}
    assert all(row["venue_address"] == "1879-3 Highway 9, Osage, IA 50461" for row in rows)
    assert all(row["lat"] is None and row["lng"] is None for row in rows)
    assert fetch.call_count == 3


@pytest.mark.parametrize("street", ["1-2 Main Street", "123456-123456 Main Street", "1879A Highway 9"])
def test_supported_numeric_house_number_bounds_and_existing_letter_suffix_are_preserved(street):
    result = mcp.parse_event(detail(street=street, city="Osage IA 50461"), parsed(), now=NOW)
    assert result["venue_address"] == street + ", Osage, IA 50461"


@pytest.mark.parametrize("street", [
    "1234567-3 Highway 9", "1879-1234567 Highway 9", "1879--3 Highway 9",
    "1879-3-2 Highway 9", "1879 -3 Highway 9", "1879-3",
])
def test_malformed_or_unbounded_hyphenated_numbers_are_not_addresses(street, record_spy):
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(detail(street=street, city="Osage IA 50461"), parsed(), now=NOW)
    record_spy.assert_not_called()


@pytest.mark.parametrize("street,city", [
    ("1879-3 Highway 9", "Osage IA"),
    ("1879-3 Highway 9", "Osage MN 50461"),
    ("1879-3 Highway 9, St. Ansgar, IA 50461", "Osage IA 50461"),
    ("1879-3 Highway 9, Osage, IA 50462", "Osage IA 50461"),
])
def test_hyphenated_numbers_still_require_complete_consistent_city_state_and_zip(street, city):
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(detail(street=street, city=city), parsed(), now=NOW)


@pytest.mark.parametrize("event_id,county,location_html,venue,address,city", [
    ("29917", "Story", '<p><strong>McFarland Park Conservation Center</strong><br/>'
     '56461 180th St   Ames, IA 50010 <br/>Ames, IA 50010 <br/>McFarland Park <br/></p>',
     "McFarland Park Conservation Center", "56461 180th St, Ames, IA 50010", "Ames"),
    ("29919", "Story", '<p><strong>McFarland Park Conservation Center</strong><br/>'
     '56461 180th St   Ames, IA 50010 <br/>Ames, IA 50010 <br/>McFarland Park <br/></p>',
     "McFarland Park Conservation Center", "56461 180th St, Ames, IA 50010", "Ames"),
    ("29428", "Linn", '<p><strong>Pinicon Ridge Park - Eagle View Shelter</strong><br/>'
     '4729 Horseshoe Falls Rd, , IA 52214 <br/>Central City IA 52214 <br/>Pinicon Ridge Park <br/>'
     'Conservation Education Team Naturalist, Chuck Ungs 319-892-6485</p>',
     "Pinicon Ridge Park - Eagle View Shelter", "4729 Horseshoe Falls Rd, Central City, IA 52214", "Central City"),
])
def test_published_repeated_address_layouts(event_id, county, location_html, venue, address, city, record_spy):
    # Location paragraphs observed on these publisher event pages on 2026-11-03.
    item = entry(event_id, county=county)
    result = mcp.parse_event(detail(item, location_html=location_html), parsed(item), now=NOW)
    assert result["venue_name"] == venue
    assert result["venue_address"] == address
    assert result["venue_city"] == city
    assert result["lat"] is None and result["lng"] is None
    assert record_spy.call_args.kwargs["publisher_geo"] is False


@pytest.mark.parametrize("street", [
    "56461 180th St Nevada, IA 50010",
    "56461 180th St, West Ames, IA 50010",
    "56461 180th St Ames, IA 50011",
    "56461 180th St, , IA 50011",
])
def test_conflicting_repeated_city_or_postal_code_is_not_combined(street, record_spy):
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(detail(street=street, city="Ames, IA 50010"), parsed(), now=NOW)
    record_spy.assert_not_called()


def test_normalized_address_cannot_lose_its_street_name(record_spy):
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(detail(street="56461 Ames, IA 50010", city="Ames, IA 50010"), parsed(), now=NOW)
    record_spy.assert_not_called()


def test_matching_comma_delimited_city_is_normalized():
    result = mcp.parse_event(detail(street="56461 180th St, Ames, IA 50010", city="Ames, IA 50010"),
                             parsed(), now=NOW)
    assert result["venue_address"] == "56461 180th St, Ames, IA 50010"


def test_conflicting_separate_city_lines_are_not_chosen_arbitrarily(record_spy):
    location_html = ('<p><strong>Event Center</strong><br>56461 180th St<br>'
                     'Ames, IA 50010<br>Nevada, IA 50201<br>Parent Park</p>')
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(detail(location_html=location_html), parsed(), now=NOW)
    record_spy.assert_not_called()


def test_multiline_street_directions_are_preserved():
    location_html = ('<p><strong>Event Center</strong><br>56461 180th St<br>'
                     'Use the south entrance<br>Ames, IA 50010<br>Parent Park</p>')
    result = mcp.parse_event(detail(location_html=location_html), parsed(), now=NOW)
    assert result["venue_address"] == "56461 180th St, Use the south entrance, Ames, IA 50010"


@pytest.mark.parametrize("event_id,location_html", [
    ("29738", '<p><strong>Knight Prairie Pavilion</strong><br/>F.W. Kent Park<br/>'
     'Oxford IA 52245<br/>JOHNSON COUNTY EDUCATION PROGRAMS<br/>'
     'Email kmorrow@johnsoncountyiowa.gov for questions.</p>'),
    ("29805", '<p>F. W. Kent Park<br/>Oxford IA 52322<br/>'
     'JOHNSON COUNTY EDUCATION PROGRAMS<br/>Michelle Wiegand<br/>'
     'mwiegand@johnsoncountyiowa.gov<br/>319-645-2315</p>'),
])
def test_published_johnson_locations_without_streets_remain_skipped(event_id, location_html):
    item, verified = entry(event_id, county="Johnson"), entry("9999", county="Johnson")
    unresolved = detail(item, location_html=location_html)
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(unresolved, parsed(item), now=NOW)
    fetch = Mock(side_effect=[listing(item, verified), unresolved, detail(verified)])
    result = mcp.collect(mcp.source_for_county("johnson"), fetch, now=NOW)
    assert len(result) == 1 and result[0]["id"].endswith(":9999")


def test_current_missing_end_is_retained_for_three_hours_without_inventing_end():
    item = entry(when="NOV 03 2026 8:00 AM")
    event = parsed(item)
    result = mcp.parse_event(detail(item), event, now=NOW)
    assert result["ends_at"] is None
    assert mcp.parse_event(detail(item), event, now=NOW + timedelta(hours=2)) is None


def test_event_ending_in_ten_minutes_is_retained_until_its_end():
    item = entry(when="NOV 03 2026 8:00 AM - 9:10 AM")
    assert mcp.parse_event(detail(item), parsed(item), now=NOW) is not None
    assert mcp.parse_event(detail(item), parsed(item), now=NOW + timedelta(minutes=10)) is None


@pytest.mark.parametrize("overrides,reason", [
    ({"event_id": "9999"}, "identity_mismatch"),
    ({"county": "Story"}, "identity_mismatch"),
    ({"title": "Different Event"}, "title_mismatch"),
    ({"when": "NOV 15 2026 10:00 AM"}, "schedule_mismatch"),
])
def test_unrelated_or_changed_detail_is_not_published(overrides, reason):
    with pytest.raises(ValueError, match=reason):
        mcp.parse_event(detail(**overrides), parsed(), now=NOW)


@pytest.mark.parametrize("summary", [
    "This program has been canceled due to low enrollment.",
    "Due to a scheduling issue, this camp has been cancelled.",
    "Sorry, Cancelled! The original program was a nature walk.",
    "Update: this event is postponed until a new date is announced.",
])
def test_description_cancellation_is_detected_with_unchanged_title(summary):
    assert mcp.parse_event(detail(summary=summary), parsed(), now=NOW) is None


@pytest.mark.parametrize("summary", [
    "Refunds are issued for cancellations before the registration deadline.",
    "If this program is cancelled by the county, a full refund will be issued.",
    "This event will be canceled if unsafe weather develops.",
    "Participants who need to cancel their registration should call the office.",
])
def test_cancellation_policies_are_not_cancellations(summary):
    assert mcp.parse_event(detail(summary=summary), parsed(), now=NOW) is not None


@pytest.mark.parametrize("status,expected", [
    ("This event is no longer accepting registrations. <a>Join Waiting List</a>", "Waitlist"),
    ("Registration is no longer available", "Closed"),
    ("<a>Register Now</a>", "Available"),
])
def test_registration_closed_and_waitlist_are_not_cancelled(status, expected):
    result = mcp.parse_event(detail(registration=status), parsed(), now=NOW)
    assert f"Registration: {expected}" in result["description"]


def test_permit_products_are_excluded_but_permit_workshops_remain():
    assert mcp.excluded_product("Matsell Bridge Shooting Range Permit (2026)")
    assert mcp.excluded_product("2027 IAN Membership")
    assert not mcp.excluded_product("Fishing Permit Workshop")
    assert not mcp.excluded_product("Food Donation Drive")


def test_tool_options_merge_only_with_exact_matching_venue_and_session():
    includes = entry("29729", title="Intro to Print Making - INCLUDES CARVING TOOL")
    without = entry("29730", title="Intro to Print Making - NO CARVING TOOL")
    records = [mcp.parse_event(detail(item, cost=cost, registration="<a>Register Now</a>"), parsed(item), now=NOW)
               for item, cost in [(includes, "Adults - $25.00"), (without, "Adults - $10.00")]]
    merged = mcp.combine_registration_options(records)
    assert len(merged) == 1
    assert merged[0]["title"] == "Intro to Print Making"
    assert "$25.00" in merged[0]["description"] and "$10.00" in merged[0]["description"]
    assert includes["url"] in merged[0]["description"] and without["url"] in merged[0]["description"]
    assert len(merged[0]["description"]) <= 2000
    assert all(not key.startswith("_") for key in merged[0])
    assert mcp.combine_registration_options([records[1]])[0]["id"] == merged[0]["id"]
    different_venue = mcp.parse_event(detail(without, venue="Other Venue", street="100 Main Street"), parsed(without), now=NOW)
    assert len(mcp.combine_registration_options([records[0], different_venue])) == 2


def test_morning_afternoon_and_separate_source_ids_are_preserved():
    a = entry("1001", title="Nature Workshop (Morning Session)", when="NOV 14 2026 10:00 AM - 12:00 PM")
    b = entry("1002", title="Nature Workshop (Afternoon Session)", when="NOV 14 2026 1:00 PM - 3:00 PM")
    c = entry("1003", title=a["title"], when=a["date"])
    records = [mcp.parse_event(detail(item), parsed(item), now=NOW) for item in (a, b, c)]
    assert len(mcp.combine_registration_options(records)) == 3
    assert len({item["id"] for item in records}) == 3


@pytest.mark.parametrize("html,reason", [
    ("<html>Access denied</html>", "structure_unverified"),
    ("<h1>Events</h1>", "structure_unverified"),
    (listing(total=3), "count_mismatch"),
    (listing(entry(), total=0), "count_mismatch"),
    (listing(entry()).replace('value="1"', 'value="missing"'), "count_unverified"),
    (listing(entry(), entry()), "identity_repeated"),
    (listing(entry(county="Story")), "county_mismatch"),
])
def test_missing_markup_wrong_count_and_foreign_county_are_not_healthy_empty(html, reason):
    with pytest.raises(ValueError, match=reason):
        mcp.parse_listing(html, "linn")


def test_explicit_zero_count_is_empty_and_does_not_fetch_another_page():
    fetch = Mock(return_value=listing())
    assert mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW) == []
    assert fetch.call_count == 1
    # The county GET route returns total zero beyond its last page. Collect
    # stops using the first total instead of making that unnecessary request.
    assert mcp.parse_listing(listing(), "linn", page_number=2) == ([], 0)
    with pytest.raises(ValueError, match="county_unverified"):
        mcp.parse_listing('<div id="partialViewContainer"><input id="hdnTotalCount" value="0"></div>', "linn")
    with pytest.raises(ValueError, match="county_mismatch"):
        mcp.parse_listing(listing(county="Story"), "linn")


def test_all_counties_can_report_a_verified_empty_calendar_without_detail_fetches():
    for county, name in mcp.COUNTIES.items():
        fetch = Mock(return_value=listing(county=name))
        assert mcp.collect(mcp.source_for_county(county), fetch, now=NOW) == []
        assert fetch.call_count == 1
        assert parse_qs(urlsplit(fetch.call_args.args[0]).query)["EventSearchModel.CountyName"] == [name]


def test_collection_paginates_without_losing_sessions_or_fetching_expired_details():
    expired = [entry(str(2000 + n), when="NOV 02 2026 10:00 AM - 12:00 PM") for n in range(23)]
    current = [entry(str(3000 + n)) for n in range(3)]
    pages = {1: listing(*(expired + current[:2]), total=26), 2: listing(current[2], total=26)}
    requests = []
    def fetch(url, accept):
        requests.append(url)
        if "?" in url:
            return pages[int(parse_qs(urlsplit(url).query)["EventSearchModel.PageNumber"][0])]
        return detail(next(item for item in current if item["url"] == url))
    result = mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)
    assert len(result) == 3 and len(requests) == 5
    assert [item["id"] for item in result] == ["mycountyparks:linn:" + item["id"] for item in current]


def test_list_order_is_not_assumed_to_be_time_sorted():
    afternoon = entry("1001", when="NOV 03 2026 1:00 PM - 2:30 PM")
    morning = entry("1002", when="NOV 03 2026 10:00 AM - 11:30 AM")
    pages = listing(afternoon, morning)
    def fetch(url, accept):
        return pages if "?" in url else detail(afternoon if url == afternoon["url"] else morning)
    result = mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)
    assert len(result) == 2
    assert result[0]["id"].endswith(":1002")


def test_products_expired_and_outside_window_are_filtered_before_fetch():
    items = [entry("1001", title="Annual Range Permit"),
             entry("1002", when="NOV 02 2026 10:00 AM - 12:00 PM"),
             entry("1003", when="MAR 01 2027 10:00 AM - 12:00 PM"), entry("1004")]
    fetch = Mock(side_effect=lambda url, accept: listing(*items) if "?" in url else detail(items[-1]))
    result = mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)
    assert len(result) == 1 and fetch.call_count == 2


def test_detail_budget_fails_before_any_detail_and_never_returns_truncated_success():
    items = [entry(str(1000 + n)) for n in range(26)]
    fetch = Mock(side_effect=[listing(*items[:25], total=26), listing(items[25], total=26)])
    with pytest.raises(ValueError, match="detail_limit"):
        mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)
    assert fetch.call_count == 2


def test_listing_pagination_limit_and_repeated_page_fail_closed():
    items = [entry(str(1000 + n)) for n in range(25)]
    with pytest.raises(ValueError, match="pagination_limit"):
        mcp.collect(mcp.source_for_county("linn"), lambda *_: listing(*items, total=101), now=NOW)
    with pytest.raises(ValueError, match="page_repeated"):
        mcp.collect(mcp.source_for_county("linn"), lambda *_: listing(*items, total=50), now=NOW)


def test_changed_total_is_not_a_complete_snapshot():
    first = [entry(str(1000 + n)) for n in range(25)]
    second = [entry(str(2000 + n)) for n in range(25)]
    fetch = Mock(side_effect=[listing(*first, total=26), listing(*second, total=50)])
    with pytest.raises(ValueError, match="total_changed"):
        mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)


def test_deadline_and_broken_detail_do_not_publish_partial_results():
    fetch = Mock()
    with pytest.raises(ValueError, match="collection_deadline"):
        mcp.collect(mcp.source_for_county("linn"), fetch, deadline_at=0, now=NOW)
    fetch.assert_not_called()
    items = [entry("1001"), entry("1002")]
    fetch = Mock(side_effect=[listing(*items), detail(items[0]), "<html>Temporarily unavailable</html>"])
    with pytest.raises(ValueError, match="event_structure_unverified"):
        mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)


def test_unresolved_street_is_never_replaced_with_parent_park():
    with pytest.raises(ValueError, match="venue_requires_address"):
        mcp.parse_event(detail(street="P.O. Box 123"), parsed(), now=NOW)
    fetch = Mock(side_effect=[listing(entry()), detail(street="P.O. Box 123")])
    with pytest.raises(ValueError, match="venue_extraction_unavailable"):
        mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)


def test_one_unresolved_address_does_not_block_other_verified_addresses():
    first, second = entry("1001"), entry("1002")
    fetch = Mock(side_effect=[listing(first, second), detail(first, street="P.O. Box 123"), detail(second)])
    result = mcp.collect(mcp.source_for_county("linn"), fetch, now=NOW)
    assert len(result) == 1 and result[0]["id"].endswith(":1002")


def test_description_does_not_expand_unverified_future_dates_into_sessions():
    summary = "The center opens monthly. December 5 and January 9 have separate programs."
    result = mcp.parse_event(detail(summary=summary), parsed(), now=NOW)
    assert isinstance(result, dict)
    assert result["starts_at"] == "2026-11-14T16:00:00+00:00"


def test_cost_absence_never_becomes_free_and_invalid_images_are_ignored():
    result = mcp.parse_event(detail(), replace(parsed(), image_url=None), now=NOW)
    assert "Cost:" not in result["description"]
    assert "free" not in result["description"].lower()
    assert mcp._image_url("https://evil.example/image.jpg") is None
    assert mcp._image_url("https://content.mycountyparks.com/Production/Assets/image/logo.svg") is None


def test_long_cost_section_cannot_exceed_staging_description_limit():
    cost = "Adults - $25.00; " + "Additional publisher cost notes. " * 100
    result = mcp.parse_event(detail(cost=cost, summary="Program details. " * 300,
                                    registration="<a>Register Now</a>"), parsed(), now=NOW)
    assert len(result["description"]) <= 2000
    assert "$25.00" in result["description"]
    assert "…" in result["description"]
    assert result["description"].endswith("Registration: Available")


@pytest.mark.parametrize("slug_length", [20, 760])
def test_long_cost_options_reserve_complete_registration_links_and_statuses(slug_length):
    includes = entry("29729", title="Intro to Print Making - INCLUDES CARVING TOOL")
    without = entry("29730", title="Intro to Print Making - NO CARVING TOOL")
    for item in (includes, without):
        item["url"] = item["url"].rsplit("/", 1)[0] + "/" + "A" * slug_length
    records = [mcp.parse_event(detail(item, summary="Program details. " * 300,
                    cost=cost + "; " + "Publisher fee notes. " * 150,
                    registration=status), parsed(item), now=NOW)
               for item, cost, status in [(includes, "Adults - $25.00", "Registration is no longer available"),
                                         (without, "Adults - $10.00", "<a>Register Now</a>")]]
    result = mcp.combine_registration_options(records)[0]
    assert len(result["description"]) <= 2000
    assert includes["url"] in result["description"]
    assert without["url"] in result["description"]
    assert "Closed" in result["description"] and "Available" in result["description"]
    assert "$25.00" in result["description"] and "$10.00" in result["description"]


def test_irreducible_option_links_fail_instead_of_truncating_or_overflowing():
    entries = [entry("29729", title="Intro to Print Making - INCLUDES CARVING TOOL"),
               entry("29730", title="Intro to Print Making - NO CARVING TOOL")]
    for item in entries:
        item["url"] = item["url"].rsplit("/", 1)[0] + "/" + "A" * 1300
    records = [mcp.parse_event(detail(item, cost="Adults - $25.00"), parsed(item), now=NOW) for item in entries]
    with pytest.raises(ValueError, match="mycountyparks_registration_details_too_large"):
        mcp.combine_registration_options(records)
