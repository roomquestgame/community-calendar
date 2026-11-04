"""Offline evidence, venues and explicitly limited first-page collection."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from roomquest import bellevue_times as bt

NOW = datetime(2026, 11, 3, 20, tzinfo=bt.TZ)
CAPTURE = Path(__file__).with_name("fixtures").joinpath("bellevue_times_page1.html").read_text()
SOURCE = {"source_key": bt.SOURCE_KEY, "kind": "html", "platform_adapter": "html", "feed_url": bt.CALENDAR}


def entry(slug="test-program", occurrence="20261114T100000", title="Library program",
          schedule="Saturday, November 14, 2026 · 10:00 am–11:00 am",
          venue="Bellevue Public Library · Bellevue", summary="A library activity.", image=""):
    url = f"{bt.CALENDAR}{slug}/?occurrence={occurrence}&bcc_return_view=list&bcc_return_date=2026-11-03"
    return (f'<article class="bcc-event-card">{image}<div class="bcc-card-body">'
            f'<div class="bcc-card-date">{escape(schedule)}</div>'
            f'<h2><a href="{escape(url)}">{escape(title)}</a></h2>'
            '<div class="bcc-terms"><a class="bcc-primary-term">Kids Activities</a></div>'
            + (f'<div class="bcc-card-venue">{escape(venue)}</div>' if venue else '')
            + f'<p class="bcc-card-summary">{escape(summary)}</p></div></article>')


def listing(cards, *, total=None, page=1, next_url=None):
    total = len(cards) if total is None else total
    first = (page - 1) * 30 + 1 if total else 0
    last = min(page * 30, total)
    if page * 30 < total and next_url is None:
        next_url = f"{bt.CALENDAR}?bcc_view=list&bcc_date=2026-11-03&bcc_page={page + 1}"
    link = f'<a class="bcc-page-next" href="{escape(next_url)}">Next Events →</a>' if next_url else ''
    return ('<main class="bcc-event-list">' + ''.join(cards) + '</main>'
            '<nav class="bcc-list-pagination">'
            f'<div class="bcc-pagination-count">Showing {first}–{last} of {total} upcoming events</div>'
            f'<span class="bcc-page-number is-current" aria-current="page">{page}</span>{link}</nav>')


def batch(first, count):
    return [entry(slug=f"program-{number}", title=f"Program {number}") for number in range(first, first + count)]


def card(**kwargs):
    return bt.parse_listing(listing([entry(**kwargs)])).cards[0]


def normalized(title, start, end, venue, street, city, url, identity, **kwargs):
    return {"id": identity, "title": title,
            "starts_at": datetime.fromisoformat(start).astimezone(timezone.utc).isoformat(),
            "ends_at": datetime.fromisoformat(end).astimezone(timezone.utc).isoformat() if end else None,
            "venue_name": venue, "venue_address": street, "venue_city": city,
            "event_url": url, "lat": kwargs.get("lat"), "lng": kwargs.get("lng"),
            "category": kwargs.get("category"), "reason": "missing_verified_venue_geo"}


@pytest.fixture(autouse=True)
def record_spy(monkeypatch):
    spy = Mock(side_effect=normalized)
    monkeypatch.setattr(bt, "record", spy)
    return spy


def test_actual_first_page_is_collected_with_explicit_limited_scope(capsys):
    page = bt.parse_listing(CAPTURE)
    assert len(page.cards) == 30 and page.total == 61
    fetch = Mock(return_value=CAPTURE)
    rows = bt.collect(SOURCE, fetch, now=NOW)
    fetch.assert_called_once_with(bt.CALENDAR, "text/html")
    assert len(rows) == 28
    assert len({row["id"] for row in rows}) == 28
    assert all(row["lat"] is None and row["lng"] is None for row in rows)
    assert all(row["timezone"] == "America/Chicago" for row in rows)
    assert all("bcc_return" not in row["event_url"] for row in rows)
    logs = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert logs[-1] == {"event": "bellevue_times_normalized", "source_key": bt.SOURCE_KEY,
                        "collection_scope": "first_page", "publisher_total": 61,
                        "first_page_count": 30, "has_more": True,
                        "held": 1, "duplicates": 1, "records": 28}
    assert all(log["collection_scope"] == "first_page" for log in logs)
    assert logs[0]["reason"] == "bellevue_times_spanish_storytime_time_conflict"
    assert logs[1]["reason"] == "verified_parade_counterpart"


def test_saved_dates_and_all_venue_pairs_remain_factual():
    rows = bt.normalize_cards(bt.parse_listing(CAPTURE).cards, now=NOW)
    by_title = {row["title"]: row for row in rows}
    for title, start in (("Kids in the Kitchen", "2026-11-04T15:00:00+00:00"),
                         ("American Mahjong", "2026-11-05T23:30:00+00:00"),
                         ("Open Sew", "2026-11-06T15:00:00+00:00")):
        assert by_title[title]["starts_at"] == start and by_title[title]["ends_at"] is None
    assert by_title["Mister Mushroom Faux Stained Glass"]["starts_at"] == "2026-11-07T06:00:00+00:00"
    assert by_title["Mister Mushroom Faux Stained Glass"]["ends_at"] == "2026-11-25T05:59:00+00:00"
    assert by_title["Creature Club"]["venue_address"] == "2206 Longo Drive, Suite 100, Bellevue, NE 68005"
    assert by_title["Officer Chris Abbott Memorial Holiday Heroes Chili Cook Off"]["venue_address"] == "3750 Raynor Parkway, Bellevue, NE 68123"
    assert by_title["Avenue Q: The Musical | SNAP! Productions"]["venue_address"] == "2221 Thurston Circle, Bellevue, NE 68005"
    assert by_title["OESC Craft Bazaar"]["venue_address"] == "2825 Y Street, Omaha, NE 68107"
    assert by_title["OESC Craft Bazaar"]["venue_city"] == "Omaha"
    assert by_title["OESC Craft Bazaar"]["location_provenance"] == "publisher_event_street_reviewed_address_pending_geocode"
    parade = by_title["Nebraska’s Official Veterans Day Parade"]
    assert parade["venue_address"] == "209 West Mission Avenue, Bellevue, NE 68005"
    assert parade["venue_name"].endswith("grandstand")
    assert "-2/" not in parade["event_url"]
    assert "Spanish Storytime" not in by_title
    assert len([row for row in rows if row["title"] == "LEGO Club"]) == 4
    assert len([row for row in rows if row["title"] == "Avenue Q: The Musical | SNAP! Productions"]) == 6
    assert by_title["Bluey Bash"]["ends_at"] == "2026-11-14T21:00:00+00:00"
    for title in ("Family Book Club", "Gem Jam: Teen Pop-Up"):
        assert title in by_title and "image_url" not in by_title[title]


@pytest.mark.parametrize("updates", [
    {"source_key": "bellevue_times_wa"}, {"source_key": "bellevue_times_ne_extra"},
    {"kind": "json"}, {"platform_adapter": "wordpress"}, {"timezone": "America/New_York"},
    {"feed_url": bt.CALENDAR + "?bcc_page=2"}, {"feed_url": bt.CALENDAR.rstrip("/")},
    {"feed_url": "http://bellevuetimes.com/events/"}, {"feed_url": "https://example.com/events/"},
])
def test_unregistered_source_rejected_before_fetch(updates):
    fetch = Mock()
    with pytest.raises(ValueError):
        bt.collect({**SOURCE, **updates}, fetch, now=NOW)
    fetch.assert_not_called()


@pytest.mark.parametrize("url", [
    "https://example.com/events/one/?occurrence=20261114T100000",
    "https://bellevuetimes.com:443/events/one/?occurrence=20261114T100000",
    "https://user@bellevuetimes.com/events/one/?occurrence=20261114T100000",
    "https://bellevuetimes.com/events/one/?occurrence=20261114T100000#fragment",
    "https://bellevuetimes.com/events/one/?occurrence=20261114T100000&occurrence=20261115T100000",
    "https://bellevuetimes.com/events/one/?occurrence=20261114T100000&redirect=https://evil.example",
    "https://bellevuetimes.com/events/one/?occurrence=20260230T100000",
    "https://bellevuetimes.com/events/one/?occurrence=20261114",
    "https://bellevuetimes.com/events/../one/?occurrence=20261114T100000",
    "https://bellevuetimes.com/events/%2e%2e/one/?occurrence=20261114T100000",
    "https://bellevuetimes.com/events/one/?bcc_return_date=2026-11-03",
])
def test_unverified_occurrence_urls_rejected(url):
    with pytest.raises(ValueError, match="event_url_unverified"):
        bt.event_identity(url)


def test_recurring_occurrences_and_tracking_have_stable_distinct_ids():
    one = card(slug="recurring-program")
    same = replace(one, url=one.url + "&bcc_return_date=2026-11-04")
    slug, occurrence, url = bt.event_identity(same.url)
    assert (slug, occurrence, url) == (one.slug, one.occurrence, one.url)
    two = card(slug=one.slug, occurrence="20261115T100000", schedule="Sunday, November 15, 2026 · 10:00 am–11:00 am")
    rows = bt.normalize_cards([one, two], now=NOW)
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
    assert rows[0]["id"].endswith(":20261114T100000")
    long_one = replace(one, slug="program-" * 25 + "one")
    long_two = replace(one, slug="program-" * 25 + "two")
    assert len(long_one.identity) <= 180 and long_one.identity != long_two.identity


@pytest.mark.parametrize("schedule,occurrence,reason", [
    ("Saturday, November 14, 2026", "20261114T000000", "date_only_midnight"),
    ("Saturday, November 14, 2026 · 11:00 am–12:00 pm", "20261114T100000", "occurrence_start_conflict"),
    ("Sunday, November 15, 2026 · 10:00 am–11:00 am", "20261114T100000", "occurrence_date_conflict"),
    ("Saturday, November 14, 2026 · 10:00 am–9:00 am", "20261114T100000", "event_end_unverified"),
    ("Saturday, November 14, 2026 · 10:00 am–10:00 am", "20261114T100000", "event_end_unverified"),
    ("Sunday, March 8, 2026 · 2:30 am–3:00 am", "20260308T023000", "occurrence_time_unverified"),
    ("Sunday, November 1, 2026 · 1:30 am–2:00 am", "20261101T013000", "occurrence_time_unverified"),
])
def test_unreliable_times_are_held_not_repaired(schedule, occurrence, reason):
    with pytest.raises(bt.EventHold, match=reason):
        bt.parse_schedule(schedule, occurrence)


@pytest.mark.parametrize("schedule", [
    "Friday, November 14, 2026 · 10:00 am–11:00 am",  # wrong weekday
    "Saturday, February 30, 2026 · 10:00 am–11:00 am",
    "Saturday, November 14, 2026 · doors open at 10am",
    "Saturday, November 14, 2026 · 25:00 am–11:00 am",
])
def test_unrecognized_schedule_shapes_fail_closed(schedule):
    with pytest.raises(ValueError):
        bt.parse_schedule(schedule, "20261114T100000")


def test_chicago_dst_and_explicit_midnight_are_preserved():
    summer, end = bt.parse_schedule("Sunday, July 4, 2027 · 12:00 am–1:00 am", "20270704T000000")
    assert summer.utcoffset() == timedelta(hours=-5)
    assert end - summer == timedelta(hours=1)
    winter, end = bt.parse_schedule("Saturday, November 14, 2026", "20261114T173000")
    assert winter.utcoffset() == timedelta(hours=-6) and end is None


def test_spanish_publisher_correction_can_pass_without_inferred_dates():
    spanish = next(card for card in bt.parse_listing(CAPTURE).cards if card.slug == "spanish-storytime")
    fixed = replace(spanish, schedule=spanish.schedule.replace("11:00 pm", "11:00 am"))
    rows = bt.normalize_cards([fixed], now=NOW)
    assert rows[0]["ends_at"] == "2026-11-04T17:00:00+00:00"
    with pytest.raises(ValueError, match="event_evidence_unavailable"):
        bt.normalize_cards([spanish], now=NOW)


def test_explicit_event_street_overrides_reviewed_alias_without_using_default_geo():
    event = card(summary="This event meets at 123 Main Street, Omaha, NE 68107.")
    rows = bt.normalize_cards([event], now=NOW)
    assert rows[0]["venue_address"] == "123 Main Street, Omaha, NE 68107"
    assert rows[0]["venue_city"] == "Omaha"
    assert rows[0]["location_provenance"] == "publisher_event_street_pending_geocode"
    assert rows[0]["lat"] is None and rows[0]["lng"] is None


@pytest.mark.parametrize("venue,summary", [
    ("Other library · Bellevue", "A library event."),
    ("Bellevue Public Library · Washington", "A library event."),
    ("Mission Ave · Bellevue", "A different Mission Avenue event."),
    ("Bellevue Public Library · Bellevue", "At 123 Main Street, Bellevue."),
    ("Bellevue Public Library · Bellevue", "Off-site event at 123 Main Street, Papillion."),
    ("Bellevue Public Library · Bellevue", "Off-site event at 123 Main Street, Council Bluffs, IA 51501."),
    ("Bellevue Public Library · Bellevue", "Contact our office at 123 Main Street, Omaha, NE 68102 for questions."),
    ("Bellevue Public Library · Bellevue", "Off-site at the Senior Center."),
    ("Bellevue Public Library · Bellevue", "For information: 123 Main Street, Omaha, NE 68102."),
    ("Bellevue Public Library · Bellevue", "At 123 Main Street, Bellevue, NE 68005 or 456 Park Road, Omaha, NE 68107."),
])
def test_unknown_or_conflicting_venue_is_not_sent_to_a_default_point(venue, summary):
    with pytest.raises(ValueError, match="event_evidence_unavailable"):
        bt.normalize_cards([card(venue=venue, summary=summary)], now=NOW)


def test_missing_parade_counterpart_is_held_and_future_parade_does_not_reuse_grandstand():
    cards = bt.parse_listing(CAPTURE).cards
    missing = next(event for event in cards if event.slug == bt._PARADE_SLUG + "-2")
    populated = next(event for event in cards if event.slug == bt._PARADE_SLUG)
    with pytest.raises(ValueError, match="event_evidence_unavailable"):
        bt.normalize_cards([missing], now=NOW)
    with pytest.raises(bt.EventHold, match="venue_unreviewed"):
        bt.resolve_venue(replace(populated, occurrence="20271107T100000"))


def test_named_senior_center_without_street_does_not_borrow_library_address():
    event = card(summary="This event meets at Bellevue Senior Center.")
    with pytest.raises(bt.EventHold, match="named_alternate_venue_requires_address"):
        bt.resolve_venue(event)
    at_library = card(summary="This event meets at Bellevue Public Library.")
    venue, _ = bt.resolve_venue(at_library)
    assert venue.address == "2206 Longo Drive, Suite 100, Bellevue, NE 68005"


def test_dedupe_requires_same_title_start_end_and_reviewed_venue():
    original = card()
    duplicate = replace(original, slug="test-program-2", url=original.url.replace("test-program/", "test-program-2/"))
    other_place = replace(duplicate, slug="other-place", venue="Kroc Center · Omaha")
    other_end = replace(duplicate, slug="other-end", schedule=duplicate.schedule.replace("11:00 am", "12:00 pm"))
    rows = bt.normalize_cards([duplicate, other_place, other_end, original], now=NOW)
    assert len(rows) == 3
    assert original.identity in {row["id"] for row in rows}
    assert duplicate.identity not in {row["id"] for row in rows}


def test_no_image_cards_and_untrusted_image_urls_do_not_change_event_count():
    for image in ('<a class="bcc-card-image bcc-no-image"></a>',
                  '<a class="bcc-card-image" style="background-image:url(https://evil.example/image.jpg)"></a>'):
        rows = bt.normalize_cards([card(image=image)], now=NOW)
        assert len(rows) == 1 and "image_url" not in rows[0]


@pytest.mark.parametrize("publisher_total", [30, 31, 61, 91, 1000])
def test_first_page_bound_does_not_fetch_the_rest_of_calendar(publisher_total, record_spy, capsys):
    fetch = Mock(side_effect=[listing(batch(1, 30), total=publisher_total),
                              AssertionError("later pages are outside collection scope")])
    rows = bt.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 30 and record_spy.call_count == 30
    fetch.assert_called_once_with(bt.CALENDAR, "text/html")
    diagnostic = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert diagnostic["publisher_total"] == publisher_total
    assert diagnostic["first_page_count"] == 30
    assert diagnostic["has_more"] is (publisher_total > 30)
    assert diagnostic["collection_scope"] == "first_page"


def test_first_page_http_failure_is_an_error_not_partial_success(record_spy):
    from roomquest.preview_worker import PreviewError
    fetch = Mock(side_effect=PreviewError("publisher_http_403"))
    with pytest.raises(PreviewError, match="^publisher_http_403$"):
        bt.collect(SOURCE, fetch, now=NOW)
    fetch.assert_called_once_with(bt.CALENDAR, "text/html")
    record_spy.assert_not_called()


@pytest.mark.parametrize("next_url", [
    "https://example.com/events/?bcc_view=list&bcc_date=2026-11-03&bcc_page=2",
    bt.CALENDAR + "?bcc_view=list&bcc_date=2026-11-03&bcc_page=1",
    bt.CALENDAR + "?bcc_view=list&bcc_date=2026-11-03&bcc_page=3",
    bt.CALENDAR + "?bcc_view=month&bcc_date=2026-11-03&bcc_page=2",
    bt.CALENDAR + "?bcc_view=list&bcc_date=2026-11-03&bcc_page=2&redirect=1",
    bt.CALENDAR + "?bcc_view=list&bcc_date=2026-02-30&bcc_page=2",
])
def test_later_page_links_are_never_dereferenced_even_when_untrusted(next_url, record_spy):
    fetch = Mock(return_value=listing(batch(1, 30), total=31, next_url=next_url))
    rows = bt.collect(SOURCE, fetch, now=NOW)
    assert len(rows) == 30 and record_spy.call_count == 30
    fetch.assert_called_once_with(bt.CALENDAR, "text/html")


@pytest.mark.parametrize("payload,reason", [
    (listing(batch(1, 29), total=30), "listing_count_mismatch"),
    (listing(batch(1, 29), total=61), "listing_count_mismatch"),
    (listing(batch(1, 31), total=61), "listing_count_mismatch"),
    (listing(batch(1, 30), total=61, page=2), "listing_count_unverified"),
    (listing(batch(1, 30), total=61).replace("Showing 1–30", "Showing 2–31"), "listing_count_mismatch"),
    (listing([entry(), entry()]), "listing_identity_repeated"),
    ("<html><h1>Just a moment...</h1></html>", "listing_structure_unverified"),
    (listing([entry()]).replace("Showing 1–1 of 1 upcoming events", "No data"), "listing_count_unverified"),
    (listing(batch(1, 29) + [entry(slug="invalid-last", occurrence="20260230T100000")], total=61),
     "event_url_unverified"),
])
def test_incomplete_or_unrecognized_listing_never_looks_like_success(payload, reason, record_spy):
    with pytest.raises(ValueError, match=reason):
        bt.collect(SOURCE, Mock(return_value=payload), now=NOW)
    record_spy.assert_not_called()


def test_missing_next_link_does_not_change_complete_first_page_scope():
    html = CAPTURE.replace('class="bcc-page-next"', 'class="unrecognized-next"')
    fetch = Mock(return_value=html)
    assert len(bt.collect(SOURCE, fetch, now=NOW)) == 28
    fetch.assert_called_once_with(bt.CALENDAR, "text/html")


def test_direct_normalization_cannot_accidentally_expand_beyond_first_page(record_spy):
    with pytest.raises(ValueError, match="first_page_limit"):
        bt.normalize_cards([card()] * 31, now=NOW)
    record_spy.assert_not_called()


def test_explicit_zero_count_is_required_for_empty_success():
    assert bt.collect(SOURCE, Mock(return_value=listing([])), now=NOW) == []


def test_deadline_before_fetch_and_after_response_prevents_normalization(monkeypatch, record_spy):
    fetch = Mock(return_value=listing([entry()]))
    monkeypatch.setattr(bt, "monotonic", Mock(return_value=100))
    with pytest.raises(ValueError, match="collection_deadline"):
        bt.collect(SOURCE, fetch, deadline_at=99, now=NOW)
    fetch.assert_not_called()
    monkeypatch.setattr(bt, "monotonic", Mock(side_effect=[100, 100, 131]))
    with pytest.raises(ValueError, match="collection_deadline"):
        bt.collect(SOURCE, fetch, deadline_at=200, now=NOW)
    assert fetch.call_count == 1
    record_spy.assert_not_called()


def test_known_cancellations_and_expired_occurrences_are_omitted_without_made_up_end():
    cancelled = card(title="Cancelled: Library program")
    past = card(occurrence="20261103T090000", schedule="Tuesday, November 3, 2026")
    assert bt.normalize_cards([cancelled, past], now=NOW) == []


def test_factual_description_and_publisher_category_keep_common_contract(record_spy):
    summary = "A craft activity for ages 3–5; bring a grown-up. " + "x" * 2100
    row = bt.normalize_cards([card(summary=summary)], now=NOW)[0]
    assert row["description"] == summary[:bt.MAX_DESCRIPTION]
    assert row["category"] == "Kids Activities"
    assert record_spy.call_args.kwargs["retain_until_end"] is True
    assert record_spy.call_args.kwargs["publisher_geo"] is False
