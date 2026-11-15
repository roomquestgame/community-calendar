"""Exact show dates, complete performance narratives and resumable manifests."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from roomquest import preview_worker as worker
from roomquest import raleigh_direct_performance as p

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
START = datetime(2026, 11, 20, 19, 30, tzinfo=p.ZoneInfo(p.ZONE))
FULL = "The complete native artist and program narrative. " * 65 + "Final publisher participation condition."


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(worker, "_future_datetime", lambda value: value.astimezone(timezone.utc))


def source(key):
    return dict(source_key=key, feed_url=p.SOURCES[key][0], kind="html", platform_adapter="html", timezone=p.ZONE)


def card(key, number=1, start=START, title=None):
    title = title or f"Public Concert {number}"
    return (f'<div class="eventItem"><div class="date"><span class="m-date__month">{start:%b}</span>'
        f'<span class="m-date__day">{start.day}</span><span class="m-date__year">{start.year}</span></div>'
        f'<h3 class="title"><a href="https://{p.ALLOWED_HOSTS[key][0]}/events/detail/concert-{number}">{title}</a></h3>'
        + ('<div class="location">Raleigh Memorial Auditorium</div>' if key == p.MMC else '') + '</div>')


def load_more():
    return '<button id="loadMoreEvents" data-offset="12" data-increment="12" data-category="0" data-venue="0" data-team="0"></button>'


def arena_detail(item, dates=(START,), body=FULL, explicit_year=True):
    rows = []
    for n, start in enumerate(dates):
        year = f'<span class="m-date__year">{start.year}</span>' if explicit_year else ''
        rows.append(f'<li id="showing_{n}"><span class="showings_date"><span class="m-date__month">{start:%b}</span>'
            f'<span class="m-date__day">{start.day}</span>{year}<span class="m-date__weekday">{start:%A}</span></span>'
            f'<span class="time cell">{start:%I:%M %p}</span>'
            f'<a title="Buy Tickets for {start:%B} {start.day} {start.year} at {start:%I:%M %p}">Tickets</a></li>')
    return (f'<h1>{item["title"]}</h1><p>Doors open 6:00 PM.</p><div class="event_description"><p>{body}</p></div>'
            '<div class="event_showings">' + ''.join(rows) + '</div>')


def improv_event(start=START, **changes):
    return dict({"@type": "Event", "name": "Native Comic", "startDate": start.isoformat(),
        "description": "Native Comic Performing at Raleigh Improv", "image": "https://i.ticketweb.com/i/native/photo.jpg?v=2",
        "location": {"name": "Raleigh Improv", "address": {"streetAddress": "1224 Parkside Main Street",
            "addressLocality": "Cary", "addressRegion": "NC", "postalCode": "27519"}}}, **changes)


def improv_detail(item, events, body=FULL, canonical=None):
    return ('<link rel="canonical" href="' + (canonical or item["url"]) + '">' +
        '<script type="application/ld+json">' + json.dumps(events) + '</script>' +
        '<div class="bio-text"><p>' + body + '</p></div>')


def festival_page(*, hours="6–10 PM", closed="Christmas Day: Closed", body=FULL):
    return ('<div data-elementor-type="wp-page"><div class="elementor-widget-text-editor">'
        '<p>Experience the magic of the North Carolina Chinese Lantern Festival, '
        'November 21, 2026 through January 10, 2027.</p><p>Normal Business Hours: Open daily, ' + hours +
        ' (Closed Christmas Day)</p></div><h2>Ticket Types</h2><p>' + body + '</p>'
        '<h2>Know Before You Go</h2><div class="e-n-accordion"><details><summary>Venue Policy</summary>'
        '<p>Unrelated generic venue FAQ.</p></details><details><summary>Holiday Hours</summary>'
        '<p>Thanksgiving Day and Christmas Eve: Gates: 6 – 9 PM. No Twilight Session. ' + closed +
        ' New Years Eve and New Years Day: Normal Business Hours</p></details></div></div>')


def test_exact_sources_and_improv_native_encoded_slugs():
    assert p._source(source(p.LENOVO)) == p.LENOVO
    with pytest.raises(ValueError, match="unregistered"):
        p._source(dict(source(p.MMC), feed_url="https://www.martinmariettacenter.com/other"))
    assert p.event_url(p.IMPROV, "https://improv.com/raleigh/event/english%2fspanish/14335764/")
    for url in ["http://improv.com/raleigh/comic/native/", "https://evil.test/raleigh/comic/native/",
                "https://improv.com/raleigh/event/%2e%2e/123/", "https://improv.com/raleigh/comic/native/?redirect=private"]:
        assert not p.event_url(p.IMPROV, url)


def test_listing_ranges_only_discover_actual_showing_dates():
    raw = card(p.MMC).replace('<span class="m-date__day">20</span>', '<span class="m-date__day">20</span><span class="m-date__day">24</span>')
    item = p._arena_listing(p.MMC, raw, NOW)[0][0]
    shows = [START, START + timedelta(days=2), START + timedelta(days=2, hours=3)]
    rows = p._arena_detail(p.MMC, item, arena_detail(item, shows), NOW)
    assert len(rows) == 3
    assert {p.timestamp(row["starts_at"]).day for row in rows} == {21, 23}
    assert all(row["ends_at"] is None for row in rows)
    assert all(row["description"] == FULL for row in rows)
    assert all(row["venue_address"] == "2 East South Street, Raleigh, NC 27601" for row in rows)
    assert all(row["venue_room"] == "Raleigh Memorial Auditorium" for row in rows)


def test_lenovo_year_comes_from_explicit_ticket_label_and_show_clock_not_doors():
    item = p._arena_listing(p.LENOVO, card(p.LENOVO), NOW)[0][0]
    item["span"] = None
    rows = p._arena_detail(p.LENOVO, item, arena_detail(item, explicit_year=False), NOW)
    assert rows[0]["starts_at"] == START.astimezone(timezone.utc).isoformat()
    assert rows[0]["ends_at"] is None
    assert rows[0]["lat"] is rows[0]["lng"] is None


def test_native_weekday_contradiction_is_held_without_inventing_year_or_clock():
    item = p._arena_listing(p.LENOVO, card(p.LENOVO), NOW)[0][0]
    with pytest.raises(ValueError, match="schedule_unresolved"):
        p._arena_detail(p.LENOVO, item, arena_detail(item).replace('>Friday<', '>Saturday<'), NOW)


def test_full_arena_description_not_teaser_and_no_missing_prose_substitution():
    item = p._arena_listing(p.LENOVO, card(p.LENOVO), NOW)[0][0]
    assert p._arena_detail(p.LENOVO, item, arena_detail(item), NOW)[0]["description"] == FULL
    for body, reason in [("", "description_missing"), ("x" * 12001, "description_limit")]:
        with pytest.raises(ValueError, match=reason):
            p._arena_detail(p.LENOVO, item, arena_detail(item, body=body), NOW)


def test_generic_team_homepage_link_is_not_a_full_event_narrative():
    item = p._arena_listing(p.LENOVO, card(p.LENOVO), NOW)[0][0]
    for body in ['For more information, visit <a href="https://gopack.com/">GoPack.com</a>.',
                 'For more information, visit <a href="https://carolinahurricanes.com/">CarolinaHurricanes.com</a>.']:
        with pytest.raises(ValueError, match="description_missing"):
            p._arena_detail(p.LENOVO, item, arena_detail(item, body=body), NOW)


def test_conflicting_mmc_room_and_changed_detail_identity_fail_closed():
    item = p._arena_listing(p.MMC, card(p.MMC), NOW)[0][0]
    with pytest.raises(ValueError, match="venue_unresolved"):
        p._arena_detail(p.MMC, dict(item, room="Another City Arena"), arena_detail(item), NOW)
    with pytest.raises(ValueError, match="detail_changed"):
        p._arena_detail(p.MMC, item, arena_detail(dict(item, title="Another Concert")), NOW)


def test_improv_all_schema_shows_use_complete_bio_and_actual_street():
    item = p._packet(p.IMPROV, "https://improv.com/raleigh/comic/native+comic/", "Native Comic")
    item["published_show_count"] = 2
    rows = p._improv_detail(item, improv_detail(item, [improv_event(), improv_event(START + timedelta(hours=3))]), NOW)
    assert len(rows) == 2 and all(row["description"] == FULL for row in rows)
    assert all(row["ends_at"] is None for row in rows)
    assert all(row["venue_address"] == "1224 Parkside Main Street, Cary, NC 27519" for row in rows)
    assert all(row["lat"] is row["lng"] is None for row in rows)


def test_improv_canonical_percent_case_equivalence_keeps_exact_native_identity():
    item = p._packet(p.IMPROV, "https://improv.com/raleigh/event/english%2fspanish/14335764/", "Native Comic")
    assert len(p._improv_detail(item, improv_detail(item, [improv_event()], canonical=item["url"].replace('%2f','%2F')), NOW)) == 1


def test_improv_changed_show_count_or_offsite_venue_is_not_silently_partial():
    item = p._packet(p.IMPROV, "https://improv.com/raleigh/comic/native+comic/", "Native Comic")
    with pytest.raises(ValueError, match="detail_changed"):
        p._improv_detail(dict(item, published_show_count=2), improv_detail(item, [improv_event()]), NOW)
    with pytest.raises(ValueError, match="venue_unresolved"):
        p._improv_detail(item, improv_detail(item, [improv_event(location={"name": "Another Improv"})]), NOW)


def test_comic_detail_separate_holiday_engagement_stays_with_its_own_calendar_card():
    start = datetime(2027, 1, 1, 18, 30, tzinfo=p.ZoneInfo(p.ZONE))
    item = p._packet(p.IMPROV, "https://improv.com/raleigh/comic/native+comic/", "Native Comic", ["2027-01-01", "2027-01-02"])
    item["published_show_count"] = 2
    schemas = [improv_event(start - timedelta(days=1), name="Native Comic New Year's Eve"),
               improv_event(start), improv_event(start + timedelta(days=1))]
    rows = p._improv_detail(item, improv_detail(item, schemas), NOW)
    assert len(rows) == 2 and all(row["title"] == "Native Comic" for row in rows)


def test_improv_listing_binds_year_to_native_month_navigation():
    html = ('<a class="month" href="/raleigh/calendar/dec-2026/">Dec</a>'
        '<a class="month" href="/raleigh/calendar/jan-2027/">Jan</a><div class="cal-list">'
        '<a class="item" href="/raleigh/comic/native+comic/"><div class="dates"><dt>Jan</dt><dd>1-2 Fri-Sat</dd></div>'
        '<h3>Native Comic</h3><div class="times">4 shows</div></a></div>')
    queue = p._improv_listing(html, NOW)
    assert queue[0]["span"] == ["2027-01-01", "2027-01-02"]
    assert queue[0]["published_show_count"] == 4


def test_festival_uses_full_actual_overview_and_exact_holiday_hours():
    item = p._packet(p.KOKA, p.FESTIVAL_URL, "NC Chinese Lantern Festival")
    rows = p._festival_detail(item, festival_page(), NOW)
    assert len(rows) == 50
    by_day = {p.timestamp(row["starts_at"]).astimezone(p.ZoneInfo(p.ZONE)).date().isoformat(): row for row in rows}
    assert "2026-12-25" not in by_day
    assert min(by_day) == "2026-11-21" and max(by_day) == "2027-01-10"
    assert p.timestamp(by_day["2026-11-26"]["ends_at"]).hour == 2
    assert p.timestamp(by_day["2026-12-24"]["ends_at"]).hour == 2
    assert p.timestamp(by_day["2026-11-27"]["ends_at"]).hour == 3
    assert all(FULL in row["description"] and "No Twilight Session" in row["description"] for row in rows)
    assert all("Unrelated generic venue FAQ" not in row["description"] for row in rows)


def test_festival_changed_hours_or_missing_closure_is_held():
    item = p._packet(p.KOKA, p.FESTIVAL_URL, "NC Chinese Lantern Festival")
    for payload in [festival_page(hours="5–10 PM"), festival_page(closed="Christmas hours unknown")]:
        with pytest.raises(ValueError, match="schedule_unresolved"):
            p._festival_detail(item, payload, NOW)


def test_koka_placeholder_midnight_range_never_becomes_a_continuous_event():
    item = p._packet(p.KOKA, "https://www.boothamphitheatre.com/event/native-event/", "Native Event")
    payload = '<a href="https://calendar.google.com/calendar/render?action=TEMPLATE&amp;dates=20261121T050000Z/20270110T050000Z">Calendar</a>'
    with pytest.raises(ValueError, match="schedule_unresolved"):
        p._koka_detail(item, payload, NOW)


def test_mmc_listing_phase_zero_queue_is_incomplete_even_when_cursor_equals_count():
    first = ''.join(card(p.MMC, n, title=f"Cancelled Concert {n}") for n in range(12)) + load_more()
    result = p.collect_chunk(source(p.MMC), lambda *_: first, now=NOW, max_fetches=1)
    state = result["checkpoint"]
    assert not result["complete"] and not result["events"]
    assert state["cursor"] == state["manifest_count"] == 0
    assert state["phase"] == "listing" and state["listing_complete"] is False
    assert p._checkpoint(state, p.MMC, NOW)["phase"] == "listing"


def test_mmc_paging_and_detail_resume_finish_before_emitting_events():
    first = card(p.MMC, 1) + ''.join(card(p.MMC, n, title=f"Cancelled Concert {n}") for n in range(2, 13)) + load_more()
    second = card(p.MMC, 13, start=START + timedelta(days=1))
    item1 = p._arena_listing(p.MMC, first, NOW)[0][0]
    item2 = p._arena_listing(p.MMC, second, NOW)[0][0]
    pages = {p.SOURCES[p.MMC][0]: first, p._mmc_page(12): json.dumps(second), p._mmc_page(24): json.dumps(""),
             item1["url"]: arena_detail(item1), item2["url"]: arena_detail(item2, [START + timedelta(days=1)])}
    calls = []
    def fetch(url, accept):calls.append(url);return pages[url]
    one = p.collect_chunk(source(p.MMC), fetch, now=NOW, max_fetches=2)
    assert not one["complete"] and not one["events"] and len(one["checkpoint"]["queue"]) == 2
    two = p.collect_chunk(source(p.MMC), fetch, checkpoint=one["checkpoint"], now=NOW + timedelta(minutes=1), max_fetches=2)
    assert not two["complete"] and not two["events"] and len(two["checkpoint"]["events"]) == 1
    three = p.collect_chunk(source(p.MMC), fetch, checkpoint=two["checkpoint"], now=NOW + timedelta(minutes=2))
    assert three["complete"] and len(three["events"]) == 2
    assert three["checkpoint"]["listing_complete"] and three["checkpoint"]["phase"] == "details"
    assert three["checkpoint"]["cursor"] == three["checkpoint"]["manifest_count"] == 2
    assert len(calls) == len(set(calls)) == 5


def test_changed_or_duplicate_mmc_pages_stop_capture():
    first = ''.join(card(p.MMC, n) for n in range(1, 13)) + load_more()
    with pytest.raises(ValueError, match="calendar_changed"):
        p.collect_chunk(source(p.MMC), lambda url, accept: first if url == p.SOURCES[p.MMC][0] else json.dumps(card(p.MMC, 1)), now=NOW)


def test_checkpoint_hash_scope_and_expiry():
    listing = card(p.LENOVO)
    item = p._arena_listing(p.LENOVO, listing, NOW)[0][0]
    result = p.collect_chunk(source(p.LENOVO), lambda url, accept: listing if url == p.SOURCES[p.LENOVO][0] else arena_detail(item), now=NOW)
    state = result["checkpoint"]
    assert p._checkpoint(state, p.LENOVO, NOW)
    changed = deepcopy(state)
    changed["events"][0]["description"] = "Altered."
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        p._checkpoint(changed, p.LENOVO, NOW)
    changed = deepcopy(state)
    changed["events"][0]["venue_address"] = "1 Wrong Street, Raleigh, NC 27601"
    p._seal(changed)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        p._checkpoint(changed, p.LENOVO, NOW)
    assert p._checkpoint(state, p.LENOVO, NOW + timedelta(hours=5)) is None


def test_record_limit_is_visible_without_losing_tail_occurrences():
    listing = card(p.LENOVO)
    item = p._arena_listing(p.LENOVO, listing, NOW)[0][0]
    detail = arena_detail(item, [START + timedelta(minutes=n) for n in range(201)])
    with pytest.raises(ValueError, match="record_limit"):
        p.collect_chunk(source(p.LENOVO), lambda url, accept: listing if url == p.SOURCES[p.LENOVO][0] else detail, now=NOW)
