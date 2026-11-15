"""Full narratives, publisher clocks and complete-only primary-feed capture."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from roomquest import preview_worker as worker
from roomquest import raleigh_direct_nightlife as r

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
START = datetime(2026, 11, 20, 19, 30, tzinfo=r.ZoneInfo(r.ZONE))
FULL = "The complete native event narrative. " * 90 + "Final publisher participation condition."


@pytest.fixture(autouse=True)
def frozen_record_clock(monkeypatch):
    monkeypatch.setattr(worker, "_future_datetime", lambda value: value.astimezone(timezone.utc))


def source(key):
    return dict(source_key=key, feed_url=r.SOURCES[key][0], kind="html", platform_adapter="html", timezone=r.ZONE)


def tec_event(key=r.SLIMS, number=1, **changes):
    prefix = {r.SLIMS: "https://slimsraleigh.com/calendar/", r.HONE: "https://hone-sharpen.com/event/",
              r.SPORTS: "https://sportsandsocial.com/cary/event/"}[key]
    venue, address, city = r.VENUES[key]
    event = dict(id=number, status="publish", title=f"Native Show {number}", url=prefix + f"show-{number}/",
        timezone=r.ZONE, start_date=START.replace(tzinfo=None).isoformat(" "),
        end_date=(START + timedelta(hours=2)).replace(tzinfo=None).isoformat(" "),
        utc_start_date=START.astimezone(timezone.utc).replace(tzinfo=None).isoformat(" "),
        utc_end_date=(START + timedelta(hours=2)).astimezone(timezone.utc).replace(tzinfo=None).isoformat(" "),
        all_day=False, is_virtual=False, hide_from_listings=False, description="<p>" + FULL + "</p>",
        venue=dict(venue="SLIMS" if key == r.SLIMS else venue, address=address.split(",")[0], city=city,
                   state="NC", zip=address[-5:]))
    return dict(event, **changes)


def tec_payload(events, total=None, pages=1):
    return json.dumps(dict(events=events, total=len(events) if total is None else total, total_pages=pages))


def tec_detail(event, body=FULL):
    schema = {"@type": "Event", "name": event["title"], "url": event["url"],
              "startDate": r.timestamp(event["start_date"], r.ZONE).isoformat()}
    return ('<h1 class="tribe-events-single-event-title">' + event["title"] + '</h1>'
        '<div class="tribe-events-single-event-description tribe-events-content"><p>' + body + '</p></div>'
        '<script type="application/ld+json">' + json.dumps(schema) + '</script>')


def square_event(**changes):
    item = dict(id="a-native-id", recordType=12, workflowState=1, title="A Public Concert",
        fullUrl="/events/public-concert", startDate=int(START.timestamp() * 1000),
        endDate=int((START + timedelta(hours=2)).timestamp() * 1000), body="<p>" + FULL + "</p>",
        location=dict(mapLat=40.7207559, mapLng=-74.0007613, markerLat=40.7207559, markerLng=-74.0007613,
                      addressTitle="", addressLine1=""),
        assetUrl="https://images.squarespace-cdn.com/content/v1/native/concert.jpg")
    return dict(item, **changes)


def square_payload(events):
    return json.dumps(dict(collection=dict(urlId="events"), upcoming=events, past=[],
        pagination=dict(nextPage=True, nextPageUrl="/events?offset=1778082204213", pageSize=30)))


def hx_schema(start=START, **changes):
    schema = {"@type": "Event", "name": "An Original Concert", "url": "https://events.humanitix.com/original-concert",
        "startDate": start.isoformat(), "endDate": (start + timedelta(hours=2)).isoformat(),
        "description": "A short listing teaser.", "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"name": "Cannonball Music Hall", "address": {"streetAddress": "2304 Atlantic Ave, Raleigh, NC 27604, USA",
             "addressLocality": "Raleigh", "addressRegion": "NC", "postalCode": "27604"}},
        "image": "https://images.humanitix.com/i/native/concert.jpg"}
    return dict(schema, **changes)


def schema_page(schemas, body=None):
    return '<script type="application/ld+json">' + json.dumps(schemas) + '</script>' + (
        '<div class="EventModuleRichText"><h2>Description</h2><div class="RichContent"><p>' + body + '</p></div></div>' if body is not None else "")


def test_exact_source_contract_and_url_scope():
    assert r._source(source(r.HONE)) == r.HONE
    with pytest.raises(ValueError, match="unregistered"):
        r._source(dict(source(r.HONE), feed_url="https://hone-sharpen.com/another-calendar/"))
    assert r.event_url(r.SLIMS, "https://slimsraleigh.com/calendar/native-show/2026-11-20/1/")
    for value in ("http://slimsraleigh.com/calendar/native/", "https://slimsraleigh.com.evil.test/calendar/native/",
                  "https://user@slimsraleigh.com/calendar/native/", "https://slimsraleigh.com/calendar/../native/",
                  "https://slimsraleigh.com/calendar/native/?next=private"):
        assert not r.event_url(r.SLIMS, value)


def test_tribe_retains_full_narrative_and_exact_publisher_clocks():
    queue, total, pages, ids = r._tec_listing(r.SLIMS, tec_payload([tec_event()]), NOW)
    assert total == pages == 1 and ids == ["1"]
    row = r._row(r.SLIMS, queue[0], queue[0]["occurrences"][0])
    assert row["description"] == FULL and len(row["description"]) > 2000
    assert row["starts_at"] == START.astimezone(timezone.utc).isoformat()
    assert row["venue_address"] == "227 S Wilmington St, Raleigh, NC 27601"
    assert row["lat"] is row["lng"] is None
    assert row["location_provenance"] == r.PROVENANCE
    with pytest.raises(ValueError, match="calendar_changed"):
        r._tec_listing(r.SLIMS, tec_payload([tec_event(utc_start_date="2026-11-20 19:30:00")]), NOW)


def test_private_classes_cancelled_events_and_hidden_rows_are_excluded():
    events = [tec_event(r.HONE, 1, title="Private Event: A Company Dinner"),
              tec_event(r.HONE, 2, status="cancelled"), tec_event(r.HONE, 3, hide_from_listings=True),
              tec_event(r.HONE, 4, title="Public Cooking Class")]
    queue, _, _, raw = r._tec_listing(r.HONE, tec_payload(events), NOW)
    assert len(raw) == 4 and [item["title"] for item in queue] == ["Public Cooking Class"]


def test_reviewed_home_venue_does_not_replace_conflicting_event_address():
    queue, *_ = r._tec_listing(r.HONE, tec_payload([tec_event(r.HONE, venue=dict(venue="A Different Place", address="1 Other Street"))]), NOW)
    assert queue[0]["held"] == "raleigh_direct_venue_unresolved"
    queue, *_ = r._tec_listing(r.HONE, tec_payload([tec_event(r.HONE, venue=dict(venue="Demonstration Kitchen"))]), NOW)
    assert not queue[0].get("held")


@pytest.mark.parametrize("body,reason", [("", None), ("<p>" + "n" * 12001 + "</p>", "raleigh_direct_description_limit")])
def test_blank_prose_requires_real_detail_read_and_large_prose_is_never_clipped(body, reason):
    queue, *_ = r._tec_listing(r.SLIMS, tec_payload([tec_event(description=body)]), NOW)
    assert queue[0].get("held") == reason
    assert queue[0]["detail"] == (reason is None)
    assert "body" not in queue[0]


def test_actual_detail_hydrates_missing_tribe_description():
    event = tec_event(description="")
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return tec_payload([event]) if "/wp-json/" in url else tec_detail(event)
    result = r.collect_chunk(source(r.SLIMS), fetch, now=NOW)
    assert result["complete"] and result["events"][0]["description"] == FULL
    assert calls == [r._tec_url(r.SLIMS, NOW), event["url"]]


def test_genuinely_empty_detail_is_a_reviewable_hold():
    event = tec_event(description="")
    result = r.collect_chunk(source(r.SLIMS), lambda url, accept: tec_payload([event]) if "/wp-json/" in url else tec_detail(event, ""), now=NOW)
    assert result["complete"] and not result["events"]
    assert result["checkpoint"]["diagnostics"][0]["reason"] == "raleigh_direct_description_missing"


def test_hone_divi_event_title_with_no_native_description_is_held():
    event = tec_event(r.HONE, description="")
    item = r._tec_listing(r.HONE, tec_payload([event]), NOW)[0][0]
    page = tec_detail(event, "").replace('class="tribe-events-single-event-title"', 'class="entry-title"')
    with pytest.raises(ValueError, match="description_missing"):
        r._tec_detail(r.HONE, item, page)


def test_changed_detail_identity_is_not_used_as_description():
    event = tec_event(description="")
    item = r._tec_listing(r.SLIMS, tec_payload([event]), NOW)[0][0]
    with pytest.raises(ValueError, match="detail_changed"):
        r._tec_detail(r.SLIMS, item, tec_detail(dict(event, title="Another Show")))


def test_slims_artist_schema_url_requires_exact_native_page_identity():
    event = tec_event(description="")
    item = r._tec_listing(r.SLIMS, tec_payload([event]), NOW)[0][0]
    def page(body=FULL):
        detail = tec_detail(event, body).replace(event["url"], "https://artist.example/album")
        return ('<html><head><link rel="canonical" href="' + event["url"] + '"></head>'
                '<body class="single-tribe_events postid-1">' + detail + '</body></html>')
    assert r._tec_detail(r.SLIMS, item, page()) == FULL
    with pytest.raises(ValueError, match="description_missing"):
        r._tec_detail(r.SLIMS, item, page(""))
    for changed in (page().replace(event["url"], "https://slimsraleigh.com/calendar/other/"),
                    page().replace("postid-1", "postid-2"),
                    page().replace('"name": "Native Show 1"', '"name": "Other Show"'),
                    page().replace('"startDate": "2026-11-20T19:30:00-05:00"',
                                   '"startDate": "2026-11-21T19:30:00-05:00"')):
        with pytest.raises(ValueError, match="detail_changed"):
            r._tec_detail(r.SLIMS, item, changed)


def test_neptunes_uses_complete_upcoming_array_and_rejects_default_nyc_point():
    item = r._neptunes(square_payload([square_event()]), NOW)[0]
    row = r._row(r.NEPTUNES, item, item["occurrences"][0])
    assert row["description"] == FULL and row["image_url"].startswith("https://images.squarespace-cdn.com/")
    assert row["lat"] is row["lng"] is None
    assert row["venue_address"] == "14 W Martin St, Raleigh, NC 27601"
    calls = []
    result = r.collect_chunk(source(r.NEPTUNES), lambda url, accept: calls.append(url) or square_payload([square_event()]), now=NOW)
    assert result["complete"] and calls == [r.SOURCES[r.NEPTUNES][0] + "?format=json"]


def test_cannonball_all_explicit_dates_get_full_visible_body():
    schemas = [hx_schema(), hx_schema(START + timedelta(days=7)), hx_schema(START + timedelta(days=14))]
    item = r._humanitix_manifest(schema_page({"@type": "ItemList", "itemListElement": [schemas[0]]}), NOW)[0]
    hydrated = r._humanitix_detail(item, schema_page(schemas, FULL), NOW)
    assert len(hydrated["occurrences"]) == 3 and hydrated["body"] == FULL
    assert all(r._row(r.CANNONBALL, hydrated, occurrence)["description"] == FULL for occurrence in hydrated["occurrences"])


def test_cannonball_never_uses_short_schema_teaser_as_full_description():
    item = r._humanitix_manifest(schema_page(hx_schema()), NOW)[0]
    with pytest.raises(ValueError, match="description_missing"):
        r._humanitix_detail(item, schema_page(hx_schema()), NOW)


def test_cannonball_conflicting_venue_and_unseen_series_pagination_fail_closed():
    item = r._humanitix_manifest(schema_page(hx_schema()), NOW)[0]
    changed = hx_schema(location=dict(name="Elsewhere", address=dict(streetAddress="1 Other St")))
    with pytest.raises(ValueError, match="venue_unresolved"):
        r._humanitix_detail(item, schema_page(changed, FULL), NOW)
    with pytest.raises(ValueError, match="calendar_changed"):
        r._humanitix_manifest(schema_page(hx_schema()) + '<button>Load more</button>', NOW)


def test_tribe_queries_include_ongoing_series_without_inventing_recurrence():
    upcoming = parse_qs(urlsplit(r._tec_url(r.SPORTS, NOW)).query)
    overlap = parse_qs(urlsplit(r._tec_url(r.SPORTS, NOW, overlap=True)).query)
    assert upcoming["start_date"] == ["2026-11-14 00:00:00"]
    assert overlap["start_date"] == ["1970-01-02 00:00:00"]
    assert overlap["ends_after"] == ["2026-11-14 00:00:00"]
    assert "end_date" not in overlap  # A January end bound drops ongoing trivia ending in June.
    event = tec_event(r.SPORTS, all_day=True)
    queue, *_ = r._tec_listing(r.SPORTS, tec_payload([event]), NOW)
    assert queue[0]["held"] == "raleigh_direct_schedule_unresolved"


def test_explicit_weekly_brunch_and_bingo_do_not_gain_unpublished_ends():
    start = datetime(2026, 11, 1, tzinfo=r.ZoneInfo(r.ZONE))
    end = datetime(2026, 11, 30, 23, 59, tzinfo=r.ZoneInfo(r.ZONE))
    brunch = r._sports_occurrences(dict(title="Weekend Brunch"), start, end, NOW,
        "Available every Saturday and Sunday from 11am-3pm.")
    assert brunch and all(r.timestamp(x["start"]).astimezone(r.ZoneInfo(r.ZONE)).weekday() in {5, 6} for x in brunch)
    bingo = r._sports_occurrences(dict(title="Monday Night Music Bingo"), start, end, NOW, "Every Monday, 7:00 PM")
    assert bingo and all(x["end"] is None for x in bingo)


def test_tinsel_holiday_closures_and_eve_overrides():
    start = datetime(2026, 11, 12, 12, tzinfo=r.ZoneInfo(r.ZONE))
    end = datetime(2026, 12, 27, 22, tzinfo=r.ZoneInfo(r.ZONE))
    body = ("Hours of Operation: Monday: CLOSED Tuesday-Thursday: 12pm-10pm Friday-Saturday: 12pm-12am "
        "Sunday: 12pm-10pm Note: All ages Sunday. Holiday Hours: Thanksgiving Eve (Nov. 25): 4pm-10pm "
        "Thanksgiving Day (Nov. 26): CLOSED Christmas Eve (Dec. 24): 4pm-12am Christmas Day (Dec. 25): CLOSED "
        "Visit the ultimate holiday pop-up.")
    occurrences = r._sports_occurrences(dict(title="Tinsel Tavern Holiday Pop-Up Bar"), start, end, NOW, body)
    by_day = {r.timestamp(x["start"]).astimezone(r.ZoneInfo(r.ZONE)).date().isoformat(): x for x in occurrences}
    assert "2026-11-26" not in by_day and "2026-12-25" not in by_day
    assert all(r.timestamp(x["start"]).astimezone(r.ZoneInfo(r.ZONE)).weekday() != 0 for x in occurrences)
    assert r.timestamp(by_day["2026-11-25"]["start"]).hour == 21
    assert r.timestamp(by_day["2026-12-24"]["end"]).isoformat() == "2026-12-25T05:00:00+00:00"
    with pytest.raises(ValueError, match="schedule_unresolved"):
        r._sports_occurrences(dict(title="Tinsel Tavern Holiday Pop-Up Bar"), start, end, NOW,
                             body.replace("Christmas Day (Dec. 25): CLOSED", "Additional holiday hours vary"))


def test_one_day_pregame_uses_main_venue_clock_and_not_later_pbr_clock():
    start = datetime(2026, 11, 25, tzinfo=r.ZoneInfo(r.ZONE))
    end = start + timedelta(hours=23, minutes=59)
    occurrences = r._sports_occurrences(dict(title="Thanksgiving Eve Pre-Game"), start, end, NOW,
        "We’ll be open from 4pm to midnight on Thanksgiving Eve. PBR will be open 7pm.")
    assert len(occurrences) == 1 and r.timestamp(occurrences[0]["start"]).hour == 21


def test_resumable_detail_capture_never_returns_partial_events_and_skips_accepted_prefix_reads():
    events = [tec_event(number=n, description="") for n in (1, 2)]
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return tec_payload(events) if "/wp-json/" in url else tec_detail(next(x for x in events if x["url"] == url))
    first = r.collect_chunk(source(r.SLIMS), fetch, now=NOW, max_fetches=2)
    assert not first["complete"] and not first["events"] and len(first["checkpoint"]["events"]) == 1
    before = len(calls)
    second = r.collect_chunk(source(r.SLIMS), fetch, checkpoint=first["checkpoint"], now=NOW + timedelta(minutes=1))
    assert second["complete"] and len(second["events"]) == 2
    assert calls[before:] == [events[1]["url"]]
    assert second["checkpoint"]["started_at"] == NOW.isoformat()
    assert len(json.dumps(second["checkpoint"]).encode()) < r.MAX_BYTES


def test_checkpoint_hash_or_scope_mutation_is_rejected_and_expiry_restarts():
    payload = square_payload([square_event()])
    result = r.collect_chunk(source(r.NEPTUNES), lambda *_: payload, now=NOW)
    state = result["checkpoint"]
    changed = deepcopy(state)
    changed["events"][0]["description"] = "Mutated prose."
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        r._checkpoint(changed, r.NEPTUNES, NOW)
    changed = deepcopy(state)
    changed["events"][0]["venue_address"] = "1 Wrong St, Raleigh, NC 27601"
    r._seal(changed)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        r._checkpoint(changed, r.NEPTUNES, NOW)
    assert r._checkpoint(state, r.NEPTUNES, NOW + timedelta(hours=5)) is None


def test_missing_pages_changed_totals_and_native_duplicates_never_complete():
    events = [tec_event(number=n) for n in range(1, 51)]
    first = tec_payload(events, total=51, pages=2)
    for second in (tec_payload([tec_event(number=51)], total=52, pages=2),
                   tec_payload([tec_event(number=1)], total=51, pages=2),
                   tec_payload([], total=51, pages=2)):
        with pytest.raises(ValueError, match="calendar_changed"):
            r.collect_chunk(source(r.SLIMS), lambda url, accept: first if parse_qs(urlsplit(url).query)["page"] == ["1"] else second, now=NOW)


def test_record_overflow_is_visible_instead_of_silent_truncation():
    schemas = [hx_schema(START + timedelta(minutes=n)) for n in range(201)]
    item = r._humanitix_manifest(schema_page(hx_schema()), NOW)[0]
    detail = schema_page(schemas, "A complete publisher narrative.")
    calendar = '<iframe data-collection="cannonball-calendar"></iframe>'
    def fetch(url, accept):
        return calendar if url == r.SOURCES[r.CANNONBALL][0] else schema_page(hx_schema()) if url == r.HUMANITIX_HOST else detail
    with pytest.raises(ValueError, match="record_limit"):
        r.collect_chunk(source(r.CANNONBALL), fetch, now=NOW)
