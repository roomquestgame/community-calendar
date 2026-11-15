"""Native narratives, dated schedules and venue bindings for six new calendars."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from roomquest import boston_nightlife_additional as b
from roomquest import preview_worker as worker

NOW = datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
START = datetime(2026, 11, 20, 19, 30, tzinfo=b.ZoneInfo(b.ZONE))
FULL = "Complete publisher narrative. " * 100 + "The final native participation condition."


@pytest.fixture(autouse=True)
def frozen_record_clock(monkeypatch):
    monkeypatch.setattr(worker, "_future_datetime", lambda value: value.astimezone(timezone.utc))


def source(key):
    feed, kind, adapter = b.SOURCES[key]
    return dict(source_key=key, feed_url=feed, kind=kind, platform_adapter=adapter, timezone=b.ZONE)


def tec_event(**changes):
    event = dict(id=123, status="publish", title="A Native Concert", url="https://lizardloungeclub.com/event/native-concert/",
        timezone=b.ZONE, start_date=START.replace(tzinfo=None).isoformat(" "),
        end_date=(START + timedelta(hours=2)).replace(tzinfo=None).isoformat(" "),
        utc_start_date=START.astimezone(timezone.utc).replace(tzinfo=None).isoformat(" "),
        utc_end_date=(START + timedelta(hours=2)).astimezone(timezone.utc).replace(tzinfo=None).isoformat(" "),
        all_day=False, is_virtual=False, hide_from_listings=False, description="<p>" + FULL + "</p>",
        venue=dict(venue="Lizard Lounge", address="1667 Massachusetts Avenue", city="Cambridge", state="MA", zip="02138"))
    return dict(event, **changes)


def tec_payload(events, *, total=None, pages=1):
    return json.dumps(dict(events=events, total=len(events) if total is None else total, total_pages=pages))


def comedy_fixture(key=b.IMPROV, **changes):
    venue = b.VENUES["improv" if key == b.IMPROV else "laugh"]
    group = "improvasylum" if key == b.IMPROV else "laughboston"
    url = f"https://www.tixr.com/groups/{group}/events/native-comedy-12345"
    event = dict(id="12345678-1234-1234-1234-123456789abc", title="Native Comedy", description="<p>" + FULL + "</p>",
        start=START.astimezone(timezone.utc).isoformat(), end=(START + timedelta(hours=1)).astimezone(timezone.utc).isoformat(),
        venue=venue[0], ticketUrl=url, status="available", timezone=b.ZONE)
    event.update(changes)
    schema = dict(**{"@type": "Event", "@id": url}, url=url, name=event["title"], startDate=START.isoformat(),
        endDate=(START + timedelta(hours=1)).isoformat(), description="Truncated teaser...",
        eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode", eventStatus="https://schema.org/EventScheduled",
        location=dict(name=venue[0], address=dict(streetAddress=venue[1].split(",")[0], addressLocality="boston",
            addressRegion="MA", postalCode=venue[1][-5:])))
    calendar = '<script type="application/ld+json">' + json.dumps({"@graph": [schema]}) + '</script>'
    payload = json.dumps(dict(events=[event], total=1, timezone=b.ZONE))
    return calendar, payload, schema


def passim_literal(number=1, *, title=None, start=START):
    title = title or f"Concert {number}"
    return dict(title=title, postID=str(number), imageurl="", link=f"https://www.passim.org/live-music/events/concert-{number}/",
        start=start.replace(tzinfo=None).isoformat() + "+0000", year=str(start.year), month=f"{start.month:02d}",
        date=start.date().isoformat(), showtime=start.strftime("%I:%M%p").lstrip("0"))


def passim_calendar(literals):
    objects = ["{" + ",".join(k + ": " + json.dumps(v) for k, v in item.items()) + "}" for item in literals]
    return "<script>jQuery('#calendar').fullCalendar({events: [" + ",".join(objects) + "]});</script>"


def passim_detail(item, *, body=FULL, title=None, date_header=None, show=None, venue_lead=""):
    start = b.timestamp(item["occurrences"][0]["start"])
    title = title or item["title"]
    date_header = date_header or start.strftime("%A, %B %d, %Y")
    show = show if show is not None else start.strftime("%I:%M%p").lstrip("0")
    schema = {"@type": "Event", "name": title, "startDate": start.replace(tzinfo=None).isoformat() + "+00:00",
        "location": {"name": "Passim", "address": {"streetAddress": "47 Palmer St", "addressLocality": "Cambridge", "addressRegion": "MA", "postalCode": "02138"}}}
    return (f'<article class="event" id="post-{item["native_id"]}"><header><h1 class="entry-title">{title}</h1>'
        f'<h3 class="event-time">{date_header}</h3><div class="doors_show"><span class="doors">Doors 6:30PM</span><span class="show">Show {show}</span></div></header>'
        f'<div class="entry-content"><h2 class="entry-title">{title}</h2>{venue_lead}'
        '<p>All tickets have a $3 processing fee and a $2 preservation fee. The $3 processing fee is waived for tickets purchased at our box office.</p>'
        f'<div class="artist"><div class="artist-content"><p>{body}</p></div><div class="artist-sidebar">Visit Artist\'s Website</div></div></div></article>'
        '<script type="application/ld+json">' + json.dumps(schema) + '</script>')


def passim_pages(count=14):
    literals = [passim_literal(i) for i in range(1, count + 1)]
    listing = passim_calendar(literals)
    items = b._passim_manifest(listing, NOW)
    return {b.SOURCES[b.PASSIM][0]: listing, **{item["url"]: passim_detail(item) for item in items}}


def burren_calendar(cards):
    result = ['<p>247 ELM ST. DAVIS SQ. SOMERVILLE MA 02144</p>']
    for day, title, clocks, prose, target, room in cards:
        result.append(f'<table><tr><td class="HEADER">{day}</td></tr></table>'
            f'<table><tr><td class="Room">{room}</td></tr><tr><td><span class="Time">{clocks}</span></td></tr>'
            f'<tr><td><span class="BAND">{title}</span></td></tr><tr><td class="Text">{prose}</td></tr>'
            + (f'<tr><td><a href="{target}">More info</a></td></tr>' if target else '') + '</table>')
    return "".join(result)


def long_live_page(agenda="Nov 19 Wes Wirth &amp; Fwd<br>Dec 3 Samuel Batista<br>Dec 10 Fernando Brandao", *, rule="Every Thursday // Live Jazz in the taproom // 6–9pm"):
    return (f'<p>{rule}</p><p>152 Hampden St, Boston MA 02119</p>'
            f'<div class="sqs-html-content"><p>{agenda}</p></div>'
            '<div class="sqs-html-content"><p>Join us for Thursday Jazz Nights as we celebrate Boston’s vibrant music scene!</p>'
            '<p>Every complete native program detail remains here.</p><p>Performances are free to the public.</p>'
            '<p>Recent Press:</p><p>Unrelated press links.</p></div>'
            '<script type="application/ld+json">{"@type":"Organization","address":{"streetAddress":"40R Sprague Street","addressLocality":"Providence"}}</script>')


def test_lizard_native_full_body_and_local_utc_agreement():
    queue, pages = b._lizard_listing(tec_payload([tec_event()]), NOW)
    item = queue[0]
    assert pages == 1 and item["body"] == FULL and len(item["body"]) > 2000
    row = b._row(b.LIZARD, dict(item, **item["occurrences"][0]))
    assert row["description"] == FULL and row["venue_address"] == b.VENUES["lizard"][1]
    bad = tec_event(utc_start_date="2026-11-20 19:30:00")
    with pytest.raises(ValueError, match="schedule_conflict"):
        b._lizard_listing(tec_payload([bad]), NOW)


def test_closures_and_private_events_are_not_fake_concerts():
    queue, _ = b._lizard_listing(tec_payload([tec_event(title="No Event Tonight - Happy Thanksgiving!", description=""),
        tec_event(id=124, status="cancelled"), tec_event(id=125, hide_from_listings=True)]), NOW)
    assert not queue


@pytest.mark.parametrize("body,reason", [(None, "description_missing"), ("", "description_missing"), ("<p>" + "n" * 12001 + "</p>", "description_limit")])
def test_no_blank_or_clipped_upstream_narrative(body, reason):
    queue, _ = b._lizard_listing(tec_payload([tec_event(description=body)]), NOW)
    assert queue[0]["held"].endswith(reason) and "body" not in queue[0]


@pytest.mark.parametrize("key", [b.IMPROV, b.LAUGH])
def test_comedy_reads_complete_api_body_not_jsonld_teaser(key):
    calendar, payload, _ = comedy_fixture(key)
    item = b._comedy_listing(key, calendar, payload, NOW)[0]
    assert item["body"] == FULL and "held" not in item
    assert b._row(key, dict(item, **item["occurrences"][0]))["venue_city"] == "Boston"


def test_comedy_offsite_address_conflict_and_missing_schema_are_explicit_holds():
    calendar, payload, schema = comedy_fixture()
    schema["location"]["address"]["streetAddress"] = "A different site"
    changed = '<script type="application/ld+json">' + json.dumps(schema) + '</script>'
    assert b._comedy_listing(b.IMPROV, changed, payload, NOW)[0]["held"] == "boston_additional_venue_unresolved"
    assert b._comedy_listing(b.IMPROV, "<main></main>", payload, NOW)[0]["held"] == "boston_additional_schema_missing"


def test_passim_reads_whole_inert_calendar_and_show_clock_as_local():
    literal = passim_literal()
    item = b._passim_manifest(passim_calendar([literal]), NOW)[0]
    assert b.timestamp(item["occurrences"][0]["start"]) == START
    full = b._passim_detail(item, passim_detail(item))
    assert full["body"].endswith(FULL) and len(full["body"]) > len(FULL)
    assert "Visit Artist's Website" not in full["body"] and full["venue_key"] == "passim"
    row = b._row(b.PASSIM, dict(item, **item["occurrences"][0], **full))
    assert row["starts_at"] == START.astimezone(timezone.utc).isoformat()
    assert row["ends_at"] is None
    assert (row["lat"], row["lng"]) == (42.3741826, -71.11964540000002)


def test_inert_calendar_rejects_expressions_and_unsupported_date_reinterpretation():
    raw = passim_calendar([passim_literal()]).replace('postID: "1"', 'postID: fetch("https://unexpected.invalid")')
    with pytest.raises(ValueError, match="calendar_changed"):
        b._passim_manifest(raw, NOW)
    literal = passim_literal()
    literal["showtime"] = "8:30PM"
    with pytest.raises(ValueError, match="schedule_conflict"):
        b._passim_manifest(passim_calendar([literal]), NOW)


def test_passim_multi_showtime_date_checks_and_never_uses_doors_as_show():
    first = passim_literal(start=START.replace(hour=17, minute=0))
    second = passim_literal(start=START.replace(hour=20, minute=0))
    item = b._passim_manifest(passim_calendar([first, second]), NOW)[0]
    assert len(item["occurrences"]) == 2
    full = b._passim_detail(item, passim_detail(item, show="2 Shows! 5:00PM and 8:00PM"))
    assert full["venue_key"] == "passim"
    with pytest.raises(ValueError, match="schedule_conflict"):
        b._passim_detail(item, passim_detail(item, show="6:30PM"))


def test_passim_actual_offsite_beats_default_club_schema_and_old_artist_venues():
    item = b._passim_manifest(passim_calendar([passim_literal(title="Fiddle Festival at The Armory")]), NOW)[0]
    lead = '<p>This event takes place at <a href="https://artsatthearmory.org/">Arts at the Armory</a> in Somerville.</p>'
    full = b._passim_detail(item, passim_detail(item, venue_lead=lead))
    assert full["venue_key"] == "armory"
    row = b._row(b.PASSIM, dict(item, **item["occurrences"][0], **full))
    assert row["venue_address"] == "191 Highland Avenue, Somerville, MA 02143"
    assert row["lat"] is None and row["lng"] is None
    ordinary = b._passim_manifest(passim_calendar([passim_literal()]), NOW)[0]
    assert b._passim_detail(ordinary, passim_detail(ordinary, body=FULL + " Previously performed at Carnegie Hall."))["venue_key"] == "passim"


def test_passim_generic_ticket_fee_only_is_not_synthesized_event_description():
    item = b._passim_manifest(passim_calendar([passim_literal()]), NOW)[0]
    with pytest.raises(ValueError, match="description_missing"):
        b._passim_detail(item, passim_detail(item, body=""))


def test_burren_explicit_year_anchor_rollover_rooms_and_multiple_shows():
    now = datetime(2026, 12, 28, tzinfo=timezone.utc)
    rows = [("WEDNESDAY DECEMBER 30", "Two Performances", "5pm & 7:30pm:", "Full published welcome.", None, "THE BACK ROOM"),
            ("WEDNESDAY JANUARY 13, 2027", "Bluegrass Jam", "2-5pm:", "A complete jam invitation.", None, "THE FRONT ROOM")]
    queue = b._burren_manifest(burren_calendar(rows), now)
    assert len(queue) == 2 and len(queue[0]["occurrences"]) == 2
    assert queue[0]["occurrences"][0]["start"].startswith("2026-12-30T17:00")
    assert queue[1]["occurrences"][0]["end"].startswith("2027-01-13T17:00")
    assert queue[0]["venue_key"] == "burren_back" and queue[1]["venue_key"] == "burren_front"


def test_burren_weekday_conflict_and_closed_session_suppression():
    cards = [("FRIDAY NOVEMBER 20, 2026", "Irish Session", "9:30pm:", "Weekly closed session with our musicians.", None, "THE FRONT ROOM")]
    assert b._burren_manifest(burren_calendar(cards), NOW) == []
    wrong = [("THURSDAY NOVEMBER 20, 2026", *cards[0][1:])]
    with pytest.raises(ValueError, match="schedule_conflict"):
        b._burren_manifest(burren_calendar(wrong), NOW)


def test_burren_linked_native_description_is_complete_and_preserves_calendar_context():
    target = "https://tickets.24hourmusic.com/eventperformances.asp?evt=1890"
    card = ("SUNDAY NOVEMBER 22, 2026", "Hollow Harvest", "5pm:", "Published food-bank benefit context.", target, "THE BACK ROOM")
    item = b._burren_manifest(burren_calendar([card]), NOW)[0]
    payload = '<h2 class="event-page-head">Hollow Harvest</h2><div class="event-performances-description"><p>' + FULL + '</p></div><script>display({iEvent:1890});</script>'
    full = b._burren_detail(item, payload)
    assert full["body"] == item["body"] + "\n" + FULL
    changed = deepcopy(item)
    changed["body"] = "Updated native narrative."
    assert b._identity(b.BURREN, dict(item, **item["occurrences"][0])) == b._identity(b.BURREN, dict(changed, **changed["occurrences"][0]))


def test_long_live_named_dates_only_preserve_holiday_omissions_and_boston_location():
    items = b._long_live_manifest(long_live_page(), NOW)
    assert [x["occurrences"][0]["start"][:10] for x in items] == ["2026-11-19", "2026-12-03", "2026-12-10"]
    assert all("2026-11-26" not in json.dumps(x) for x in items)
    row = b._row(b.LONG_LIVE, dict(items[0], **items[0]["occurrences"][0]))
    assert row["venue_address"] == "152 Hampden Street, Boston, MA 02119"
    assert row["schedule_window_days"] == 28 and "Recent Press" not in row["description"]


def test_long_live_changed_rule_and_wrong_weekday_do_not_create_assumed_dates():
    with pytest.raises(ValueError, match="calendar_changed"):
        b._long_live_manifest(long_live_page(rule="Every Friday 7–10pm"), NOW)
    items = b._long_live_manifest(long_live_page(agenda="Nov 18 An Unconfirmed Wednesday<br>Dec 3 Samuel Batista<br>Dec 10 Fernando Brandao"), NOW)
    assert items[0]["held"] == "boston_additional_schedule_conflict"


@pytest.mark.parametrize("key,url", [(b.PASSIM, "https://www.passim.org/wp-admin/"),
    (b.BURREN, "https://tickets.24hourmusic.com/eventperformances.asp?evt=1890&showHidden=1"),
    (b.BURREN, "https://tickets.24hourmusic.com/basket.asp"),
    (b.IMPROV, "https://www.tixr.com/groups/laughboston/events/other-123"),
    (b.LIZARD, "https://lizardloungeclub.com/event/native/?redirect=https://elsewhere.invalid"),
    (b.LONG_LIVE, "https://www.longlivebeerworks.com/providence")])
def test_event_links_do_not_expand_network_or_venue_scope(key, url):
    assert not b.event_url(key, url)


def test_source_record_limits_fail_without_publishing_a_prefix():
    with pytest.raises(ValueError, match="record_limit"):
        b._lizard_listing(tec_payload([], total=201, pages=5), NOW)
    items = b._passim_manifest(passim_calendar([passim_literal(i) for i in range(1, 202)]), NOW)
    with pytest.raises(ValueError, match="record_limit"):
        b._validate_queue(b.PASSIM, items)


def test_durable_complete_only_collection_and_immutable_start():
    pages = passim_pages(3)
    calls = []
    def fetch(url, accept):
        calls.append(url)
        return pages[url]
    first = b.collect_chunk(source(b.PASSIM), fetch, now=NOW, max_details=1)
    assert not first["complete"] and first["events"] == []
    saved = deepcopy(first["checkpoint"])
    second = b.collect_chunk(source(b.PASSIM), fetch, checkpoint=saved, now=NOW + timedelta(minutes=30), max_details=1)
    final = b.collect_chunk(source(b.PASSIM), fetch, checkpoint=second["checkpoint"], now=NOW + timedelta(minutes=50), max_details=1)
    assert final["complete"] and len(final["events"]) == 3
    assert final["checkpoint"]["started_at"] == saved["started_at"] and saved == first["checkpoint"]
    assert all(calls.count(url) == 1 for url in pages if url != b.SOURCES[b.PASSIM][0])


def test_checkpoint_rejects_tampering_and_aligns_to_four_hour_common_ttl():
    pages = passim_pages(3)
    saved = b.collect_chunk(source(b.PASSIM), lambda url, accept: pages[url], now=NOW, max_details=1)["checkpoint"]
    assert b._checkpoint(saved, b.PASSIM, NOW + timedelta(hours=4)) is not None
    assert b._checkpoint(saved, b.PASSIM, NOW + timedelta(hours=4, microseconds=1)) is None
    bad = deepcopy(saved)
    bad["events"][0]["description"] = "A replacement short body."
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b._checkpoint(bad, b.PASSIM, NOW)
    bad = deepcopy(saved)
    bad["pending"][1]["url"] = "https://www.passim.org/live-music/events/different-event/"
    bad["pending_hash"] = b._hash(bad["pending"])
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b._checkpoint(bad, b.PASSIM, NOW)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        b._checkpoint(saved, b.PASSIM, NOW - timedelta(seconds=61))


def test_no_request_starts_inside_deadline_reserve(monkeypatch):
    monkeypatch.setattr(b, "monotonic", lambda: 27)
    calls = []
    with pytest.raises(ValueError, match="collection_deadline"):
        b.collect_chunk(source(b.PASSIM), lambda *args: calls.append(args), now=NOW, deadline_at=36)
    assert not calls
