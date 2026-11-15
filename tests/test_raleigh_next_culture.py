from copy import deepcopy
from datetime import date, datetime, timezone
from html import escape
import json
from unittest.mock import patch

import pytest

from roomquest import raleigh_next_culture as c

NOW = datetime(2026, 11, 15, 13, tzinfo=timezone.utc)
SOURCE = dict(source_key=c.SOURCE, feed_url=c.CALENDAR, kind="html", platform_adapter="html", timezone=c.ZONE)
STREET = "415 Brooks Street Suite B, Wake Forest, NC 27587-2930"


def preview(title, start, end, venue, street, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
        venue_address=street, venue_city=city, event_url=url, lat=kwargs.get("lat"), lng=kwargs.get("lng"))


def place(*, structured=False):
    if structured:
        body = ('<p class="address"><span class="address-line1">203 Brooks St</span>'
            '<span class="address-line2">Norse Brewing</span><span class="address-line3">Lower Level</span>'
            '<span class="locality">Wake Forest</span><span class="administrative-area">NC</span>'
            '<span class="postal-code">27587</span><span class="country">United States</span></p>')
    else:
        body = '<address>Page 158 Books<br>415 Brooks Street<br>Suite B<br>Wake Forest, NC 27587-2930</address>'
    return '<div class="event-details__location--location">' + body + '</div>'


def item(number=1, *, day="2026-11-16", title=None, clocks="6:00pm - 7:00pm", structured=False):
    return dict(id=str(number), url=f"https://page158books.com/event/{day}/book-event-{number}",
        title=title or f"Book Event {number}", day=day, clock_text=clocks,
        place=dict(venue_name="Norse Brewing, Lower Level" if structured else "Page 158 Books",
            venue_address="203 Brooks St, Wake Forest, NC 27587" if structured else STREET,
            venue_city="Wake Forest"))


def listing(entries, *, index=0, total=1, next_index=None):
    cards = ""
    for entry in entries:
        visible_day = date.fromisoformat(entry["day"]).strftime("%a, %m/%d/%Y")
        cards += (f'<article class="event-list" id="event-{entry["id"]}">'
            f'<div class="event-list__title"><a href="{entry["url"]}">{escape(entry["title"])}</a></div>'
            f'<div><span class="event-list__details--label">Date:</span> {visible_day}</div>'
            f'<div><span class="event-list__details--label">Time:</span> {entry["clock_text"]}</div>'
            + place(structured=entry["place"]["venue_name"].startswith("Norse")) + '</article>')
    pager = f'<a aria-current="page" href="?page={index}">{index+1}</a>'
    if index + 1 < total:
        pager += f'<a rel="next" href="?page={next_index if next_index is not None else index+1}">Next</a>'
    pager += f'<span class="pager__item--last"><a href="?page={total-1}">Last</a></span>'
    return (f'<title>Upcoming Events | Page 158 Books</title><link rel="canonical" href="{c.CALENDAR}">'
        '<main><div class="view-event-carousel view-display-id-event_carousel_page_block">'
        + cards + '<nav class="pager">' + pager + '</nav></div></main>')


def detail(entry=None, *, body=None, native_change=None, visible_clocks=None, structured=False):
    entry = entry or item()
    native = {"@type": "Event", "@id": entry["url"], "url": entry["url"], "name": entry["title"],
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "startDate": entry["day"] + "T18:00:00-05:00", "endDate": entry["day"] + "T19:00:00-05:00",
        "location": {"@type": "Place", "name": "Wrong structured venue label",
            "address": {"@type": "PostalAddress", "streetAddress": "415 Brooks Street",
                "addressLocality": "Wake Forest 415 Brooks Street", "addressRegion": "NC", "postalCode": "27587"}}}
    native.update(native_change or {})
    visible_day = date.fromisoformat(entry["day"]).strftime("%a, %m/%d/%Y")
    body = "<p>Meet the writer for an open conversation about this new book and its characters.</p>" if body is None else body
    return (f'<link rel="canonical" href="{entry["url"]}">'
        '<script type="application/ld+json">' + json.dumps({"@graph": [native]}) + '</script>'
        '<main><article class="eventinstance-full">'
        f'<h1 class="event-details__info--title">{escape(entry["title"])}</h1>'
        f'<div class="event-details__location--date">{visible_day} - {visible_clocks or entry["clock_text"]}</div>'
        + place(structured=structured)
        + f'<div class="event-details__info--body">{body}</div>'
        '<div class="event-details__info--tags"><span class="event-tag__term">Author Event</span></div>'
        '<div class="event-details__image"><img src="/sites/default/files/styles/event_image_large/public/2026-11/book.png?itok=abc_123"></div>'
        '</article></main>')


@patch.object(c, "record", side_effect=preview)
def test_complete_pagination_and_every_detail_precede_staging(_):
    entries = [item(number) for number in range(1, 27)]
    pages = {c.CALENDAR: listing(entries[:25], total=2), c._page(1): listing(entries[25:], index=1, total=2)}
    pages.update({entry["url"]: detail(entry, body="" if entry["id"] == "5" else None) for entry in entries})
    checkpoint, calls = None, []
    def fetch(url, accept):
        calls.append(url)
        assert accept == "text/html"
        return pages[url]
    for _ in range(10):
        before = len(calls)
        result = c.collect_chunk(SOURCE, fetch, checkpoint=checkpoint, now=NOW)
        assert 1 <= len(calls) - before <= 3
        checkpoint = result["checkpoint"]
        c._checkpoint(checkpoint, NOW)
        if result["complete"]:
            break
        assert result["events"] == []
    assert result["complete"] and c.checkpoint_complete(checkpoint)
    assert calls[:2] == [c.CALENDAR, c._page(1)]
    assert len(calls) == 28 and len(set(calls)) == 28
    assert checkpoint["next_page"] is None and checkpoint["phase"] == "details"
    assert checkpoint["manifest_count"] == checkpoint["cursor"] == len(checkpoint["outcomes"]) == 26
    assert len(result["events"]) == 25 and checkpoint["diagnostics"][0]["id"] == "5"
    assert checkpoint["diagnostics"][0]["reason"] == "raleigh_culture_description_missing"
    assert c.collect_chunk(SOURCE, lambda *_: pytest.fail("completed capture must not refetch"), checkpoint=checkpoint, now=NOW) == result


@patch.object(c, "record", side_effect=preview)
def test_native_full_prose_suite_and_labels_are_preserved_without_invented_point(_):
    body = "The visiting writer will discuss research, characters, and the book with readers. " * 80
    row = c._detail(item(), detail(body="<p>" + body + "</p>"), NOW)
    assert row["description"] == body.strip() and len(row["description"]) > 6000
    assert row["venue_name"] == "Page 158 Books" and row["venue_address"] == STREET
    assert row["venue_city"] == "Wake Forest" and row["lat"] is row["lng"] is None
    assert row["location_provenance"] == "publisher_event_address_pending_geocode"
    assert row["publisher_categories"] == ["Author Event"]
    assert row["timezone"] == "America/New_York" and row["starts_at"] == "2026-11-16T18:00:00-05:00"
    assert row["image_url"].endswith("book.png?itok=abc_123")


@patch.object(c, "record", side_effect=preview)
def test_event_specific_other_venue_and_explicit_native_point(_):
    entry = item(structured=True)
    native = {"location": {"@type": "Place", "geo": {"@type": "GeoCoordinates", "latitude": 35.97, "longitude": -78.51}}}
    row = c._detail(entry, detail(entry, structured=True, native_change=native), NOW)
    assert row["venue_name"] == "Norse Brewing, Lower Level"
    assert row["venue_address"] == "203 Brooks St, Wake Forest, NC 27587"
    assert (row["lat"], row["lng"]) == (35.97, -78.51)
    assert row["location_provenance"] == "publisher_event_geo"
    with pytest.raises(ValueError, match="street_unresolved"):
        c._detail(item(), detail(item(), structured=True), NOW)


@pytest.mark.parametrize("body,reason", [("", "description_missing"), ("<p> </p>", "description_missing"),
    ("<p>" + "Long native narrative. " * 700 + "</p>", "description_limit")])
def test_blank_or_oversize_description_is_held_not_filled_or_truncated(body, reason):
    with pytest.raises(ValueError, match=reason):
        c._detail(item(), detail(body=body), NOW)


@pytest.mark.parametrize("native_change,visible_clocks,reason", [
    ({"startDate": "2026-11-16T19:00:00-05:00", "endDate": "2026-11-16T20:00:00-05:00"}, None, "schedule_conflict"),
    ({"startDate": "2026-11-16T18:00:00Z", "endDate": "2026-11-16T19:00:00Z"}, None, "schedule_unresolved"),
    ({"startDate": "2026-11-16T18:00:00"}, None, "schedule_unresolved"),
    ({}, "6:00am - 7:00am", "schedule_conflict"),
    ({"endDate": "2026-11-16T18:00:00-05:00"}, None, "schedule_unresolved"),
])
def test_native_visible_and_listing_schedule_must_agree(native_change, visible_clocks, reason):
    with pytest.raises(ValueError, match=reason):
        c._detail(item(), detail(native_change=native_change, visible_clocks=visible_clocks), NOW)


@patch.object(c, "record", side_effect=preview)
def test_known_early_morning_clock_is_preserved_and_missing_end_is_not_invented(_):
    entry = item(day="2027-01-03", clocks="3:45am")
    row = c._detail(entry, detail(entry, native_change={"startDate": "2027-01-03T03:45:00-05:00", "endDate": None}), NOW)
    assert row["starts_at"] == "2027-01-03T03:45:00-05:00" and row["ends_at"] is None


@patch.object(c, "record", side_effect=preview)
def test_explicit_invitation_date_conflict_is_held_but_synopsis_history_is_not(_):
    entry = item(day="2026-11-21")
    with pytest.raises(ValueError, match="schedule_conflict"):
        c._detail(entry, detail(entry, body="<p>Join us for our market on Saturday, November 7th!</p>"), NOW)
    row = c._detail(entry, detail(entry, body="<p>The novel opens on November 7, 1922. Join us for a conversation with its author.</p>"), NOW)
    assert "1922" in row["description"]


@pytest.mark.parametrize("change", [
    {"url": "https://another.example/event"}, {"@id": "https://another.example/event"}, {"name": "Different event"},
])
def test_detail_native_identity_cannot_drift_to_another_event(change):
    with pytest.raises(ValueError, match="detail_identity"):
        c._detail(item(), detail(native_change=change), NOW)


@pytest.mark.parametrize("geo", [{"latitude": 35.9}, {"latitude": True, "longitude": -78.5},
    {"latitude": "nan", "longitude": -78.5}, {"latitude": 40.7, "longitude": -74.0}])
def test_partial_invalid_or_out_of_state_native_points_are_held(geo):
    with pytest.raises(ValueError, match="native_point_unresolved"):
        c._detail(item(), detail(native_change={"location": {"@type": "Place", "geo": geo}}), NOW)


@pytest.mark.parametrize("change", [{"eventStatus": "https://schema.org/EventCancelled"},
    {"eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode"}])
def test_cancelled_or_online_native_events_are_held(change):
    with pytest.raises(ValueError, match="nonpublic"):
        c._detail(item(), detail(native_change=change), NOW)


def test_page_jump_changed_total_and_duplicate_native_entries_fail_visibly():
    entries = [item(number) for number in range(1, 26)]
    with pytest.raises(ValueError, match="pagination_changed"):
        c._listing(listing(entries, total=3, next_index=2), c.CALENDAR)
    first = c.collect_chunk(SOURCE, lambda *_: listing(entries, total=2), now=NOW, max_fetches=1)["checkpoint"]
    with pytest.raises(ValueError, match="pagination_changed"):
        c.collect_chunk(SOURCE, lambda *_: listing(entries, index=1, total=3), now=NOW, checkpoint=first, max_fetches=1)
    with pytest.raises(ValueError, match="calendar_changed"):
        c.collect_chunk(SOURCE, lambda *_: listing(entries[:1], index=1, total=2), now=NOW, checkpoint=first, max_fetches=1)
    with pytest.raises(ValueError, match="pagination_changed"):
        c._listing(listing(entries, total=2).replace('rel="next"', 'rel="other"'), c.CALENDAR)


def test_empty_eligible_window_requires_a_complete_nonempty_native_calendar():
    future = item(day="2027-01-14")
    result = c.collect_chunk(SOURCE, lambda *_: listing([future]), now=NOW)
    assert result["complete"] and result["events"] == []
    assert result["checkpoint"]["outside_window_count"] == 1
    assert c.checkpoint_complete(result["checkpoint"])
    c._checkpoint(result["checkpoint"], NOW)
    with pytest.raises(ValueError, match="calendar_changed"):
        c._listing(listing([]), c.CALENDAR)


@patch.object(c, "record", side_effect=preview)
def test_corrupt_outcome_or_record_cannot_certify_completed_snapshot(_):
    entry = item()
    result = c.collect_chunk(SOURCE, lambda url, _: listing([entry]) if url == c.CALENDAR else detail(entry), now=NOW)
    checkpoint = result["checkpoint"]
    for field, value in (("next_page", c.CALENDAR), ("listed_pages", []), ("outcomes", []), ("listing_complete", False)):
        assert not c.checkpoint_complete(dict(checkpoint, **{field: value}))
    corrupt = deepcopy(checkpoint)
    corrupt["events"][0]["description"] = "Replacement text that was not present in the captured source."
    c._seal(corrupt)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        c._checkpoint(corrupt, NOW)
    corrupt = deepcopy(checkpoint)
    corrupt["outcomes"][0]["item_hash"] = "0" * 64
    c._seal(corrupt)
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        c._checkpoint(corrupt, NOW)


def test_unregistered_source_or_off_host_detail_is_rejected_before_fetch():
    bad = dict(SOURCE, feed_url="https://another.example/calendar")
    with pytest.raises(ValueError, match="source_unregistered"):
        c.collect_chunk(bad, lambda *_: pytest.fail("unregistered request"), now=NOW)
    assert not c.event_url(c.SOURCE, "https://page158books.com.evil.example/event/2026-11-16/book-event-1")
    assert not c.event_url(c.SOURCE, "https://page158books.com/event/2026-11-16/book-event-1?other=1")
    assert c.photo_url("https://external.example/picture.jpg") is None
