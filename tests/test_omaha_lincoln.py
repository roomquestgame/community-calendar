from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event
import pytest

from roomquest import omaha_lincoln, preview_worker, riverfront


def test_intake_batches_keep_existing_identities():
    rows = omaha_lincoln.intake_rows()
    assert len({row["publisher"] for row in rows}) == len(rows) == 77
    assert sum(row["batch"] == 1 for row in rows) == 19
    assert sum(row["batch"] == 2 for row in rows) == 58
    assert {row["existing_id"] for row in rows if row["batch"] == 1 and "existing_id" in row} == {
        3177, 4301, 4901, 5131,
    }
    assert len(omaha_lincoln.new_ical_feeds()) == 8


def test_preview_preserves_explicit_venues_and_filters_private_records():
    row = next(row for row in omaha_lincoln.intake_rows() if row["publisher"] == "Telegraph District")
    source = dict(source_key=row["source_key"], feed_url=row["feed_url"], kind="ical",
                  platform_adapter="ical", timezone="America/Chicago")
    start = datetime.now(timezone.utc) + timedelta(days=4)
    end = start + timedelta(hours=1)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//EventQuest Test//EN"]
    for uid, title, location, visibility in (
        ("1", "Book club", r"Hub Cafe\, 250 N 21st St\, Lincoln\, NE\, United States", "PUBLIC"),
        ("2", "Karaoke", "The Post", "PUBLIC"),
        ("3", "Staff meeting", "Office", "PRIVATE"),
        ("4", "Private event", "Office", "PUBLIC"),
    ):
        lines.extend(("BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{title}", f"LOCATION:{location}",
                      f"CLASS:{visibility}", f"DTSTART:{start:%Y%m%dT%H%M%SZ}",
                      f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                      f"URL:https://telegraphdistrict.com/event/{uid}/", "END:VEVENT"))
    lines.append("END:VCALENDAR")
    with patch.object(preview_worker, "fetch_publisher", return_value="\r\n".join(lines)) as fetch:
        records = preview_worker.preview_source(source)["p_events"]
        assert fetch.call_args.kwargs["respect_robots"]
        assert fetch.call_args.kwargs["allowed_hosts"] == ("telegraphdistrict.com",)
    assert {record["title"] for record in records} == {"Book club", "Karaoke"}
    book = next(record for record in records if record["title"] == "Book club")
    assert (book["venue_name"], book["venue_address"], book["venue_city"]) == (
        "Hub Cafe", "250 N 21st St, Lincoln, NE", "Lincoln",
    )
    karaoke = next(record for record in records if record["title"] == "Karaoke")
    assert karaoke["venue_address"] == "The Post"
    assert all(record["lat"] is None and record["lng"] is None for record in records)
    with patch.object(preview_worker, "fetch_publisher") as fetch:
        with pytest.raises(preview_worker.PreviewError, match="unregistered_omaha_lincoln_ical"):
            preview_worker.preview_source({**source, "feed_url": "https://example.org/events.ics"})
        fetch.assert_not_called()


def test_riverfront_preview_corrects_omaha_times_and_resolves_reviewed_venues():
    source = dict(source_key=riverfront.SOURCE_KEY,
                  feed_url=omaha_lincoln.new_ical_feeds()[riverfront.SOURCE_KEY],
                  kind="ical", platform_adapter="ical", timezone="America/Chicago")
    start = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=4)).replace(
        hour=17, minute=0, second=0, microsecond=0)
    calendar = Calendar()
    calendar.add("version", "2.0")
    for uid, title, park, description, location in (
        ("1", "Story Walk", riverfront.GENE_LEAHY, "Visit Arches Playground.", ""),
        ("2", "Skating DJ Night", riverfront.HEARTLAND, "Visit the Skate Ribbon.", ""),
        ("3", "Veterans Day Storywalk", riverfront.HEARTLAND, "Meet at the American Flag.", ""),
        ("4", "The RiverFront Holly Days", riverfront.HEARTLAND, "Explore the park.", ""),
        ("5", "Holiday Lights Lighting Ceremony", riverfront.GENE_LEAHY, "Enjoy the lights.", ""),
        ("6", "Off-site Story Walk", riverfront.GENE_LEAHY, "Meet near Arches Playground.",
         "Library, 123 Main St, Omaha, NE 68102"),
        ("7", "Unresolved", "Seasonal Events", "Meet up to explore.", ""),
    ):
        event = Event()
        event.add("uid", uid)
        event.add("summary", title)
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=2))
        event.add("categories", [park])
        event.add("description", description)
        event.add("url", f"https://theriverfrontomaha.com/event/{uid}/")
        if location:
            event.add("location", location)
        calendar.add_component(event)

    with patch.object(preview_worker, "fetch_publisher", return_value=calendar.to_ical().decode()):
        result = preview_worker.preview_source(source)

    records = {record["id"]: record for record in result["p_events"]}
    assert result["p_future_count"] == 7
    assert result["p_venue_count"] == 5
    assert all(datetime.fromisoformat(row["starts_at"]).astimezone(ZoneInfo("America/Chicago")).hour == 17
               for row in records.values())
    assert all(row["reason"] is None for row in result["p_events"] if row["lat"] is not None)
    assert records["1"]["venue_name"] == "Arches Playground at Gene Leahy Mall"
    assert records["2"]["venue_name"] == "Skate Ribbon at Heartland of America Park"
    assert records["3"]["venue_name"] == "American Flag at Heartland of America Park (approximate pin)"
    assert "approximate" in records["3"]["description"]
    assert records["4"]["lat"] == records["2"]["lat"]
    assert records["4"]["venue_name"] == "Heartland of America Park (Skate Ribbon entrance)"
    assert "Skate Ribbon entrance" in records["4"]["description"]
    assert records["5"]["venue_address"] == "1001 Douglas St, Omaha, NE 68102"
    assert records["1"]["venue_address"] == records["5"]["venue_address"]
    assert records["2"]["venue_address"] == records["4"]["venue_address"] == "800 Douglas St, Omaha, NE"
    assert records["6"]["venue_name"] == "Library"
    assert records["7"]["lat"] is None


@pytest.mark.parametrize(("source_key", "events", "expected_pins"), [
    (omaha_lincoln.FRANCIE_AND_FINCH, (
        ("Visiting Author", "Francie & Finch Bookshop, 130 S. 13th Street, Lincoln, NE 68508"),
        ("Off-site Reading", "Francie & Finch Bookshop, 100 S 13th St, Lincoln, NE 68508"),
        ("Venue To Be Announced", ""),
    ), {"Visiting Author": (40.8129603, -96.7022956), "Off-site Reading": (None, None),
        "Venue To Be Announced": (None, None)}),
    (omaha_lincoln.CROOK_HOUSE, (
        ("History & Appreciation of Antiques Class", "General Crook House Museum, 5730 N 30th St., Omaha, NE 68111"),
        ("No Class This Week: History & Appreciation of Antiques", "General Crook House Museum, 5730 N 30th St., Omaha, NE 68111"),
    ), {"History & Appreciation of Antiques Class": (None, None)}),
])
def test_reviewed_venue_and_cancellation_rules(source_key, events, expected_pins):
    feed_url = omaha_lincoln.new_ical_feeds()[source_key]
    host = feed_url.split("/")[2]
    source = dict(source_key=source_key, feed_url=feed_url, kind="ical",
                  platform_adapter="ical", timezone="America/Chicago")
    calendar = Calendar()
    calendar.add("version", "2.0")
    start = datetime.now(timezone.utc) + timedelta(days=4)
    for index, (title, location) in enumerate(events):
        event = Event()
        event.add("uid", str(index))
        event.add("summary", title)
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=1))
        event.add("url", f"https://{host}/event/{index}/")
        if location:
            event.add("location", location)
        calendar.add_component(event)

    with patch.object(preview_worker, "fetch_publisher", return_value=calendar.to_ical().decode()):
        result = preview_worker.preview_source(source)

    assert {row["title"]: (row["lat"], row["lng"]) for row in result["p_events"]} == expected_pins
    assert result["p_venue_count"] == sum(lat is not None for lat, _ in expected_pins.values())


def test_unl_public_preview_links_to_local_dated_event_and_skips_virtual_events():
    source = dict(source_key=omaha_lincoln.UNL_PUBLIC, feed_url=omaha_lincoln.UNL_FEED,
                  kind="ical", platform_adapter="ical", timezone="America/Chicago")
    start = (datetime.now(timezone.utc) + timedelta(days=4)).replace(hour=1, minute=30)
    local_start = start.astimezone(ZoneInfo("America/Chicago"))
    calendar = Calendar()
    calendar.add("version", "2.0")
    for uid, title, venue in (
        ("203744-981405@events.unl.edu", "Arcadia", "Temple Building Room Howell Theater"),
        ("204155@events.unl.edu", "Office Hours", "Zoom - Register Here"),
        ("unexpected@example.org", "Unknown publisher ID", "Temple Building"),
    ):
        event = Event()
        event.add("uid", uid)
        event.add("summary", title)
        event.add("location", venue)
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=1))
        calendar.add_component(event)

    with patch.object(preview_worker, "fetch_publisher", return_value=calendar.to_ical().decode()) as fetch:
        row, = preview_worker.preview_source(source)["p_events"]
        assert fetch.call_args.kwargs["respect_robots"]
        assert fetch.call_args.kwargs["allowed_hosts"] == ("events.unl.edu",)

    assert row["title"] == "Arcadia"
    assert row["event_url"] == f"https://events.unl.edu/{local_start:%Y/%m/%d}/203744/"
    with patch.object(preview_worker, "fetch_publisher") as fetch:
        with pytest.raises(preview_worker.PreviewError, match="unregistered_unl_public_calendar"):
            preview_worker.preview_source({**source, "feed_url": "https://events.unl.edu/upcoming/"})
        fetch.assert_not_called()


def test_bennington_preview_resolves_reviewed_onsite_and_offsite_series():
    source = dict(source_key=omaha_lincoln.BENNINGTON, feed_url=omaha_lincoln.BENNINGTON_FEED,
                  kind="ical", platform_adapter="ical", timezone="America/Chicago")
    start = datetime.now(timezone.utc) + timedelta(days=4)
    calendar = Calendar()
    calendar.add("version", "2.0")
    for slug, title, location in (
        ("thursday-storytime-2", "Storytime", ""),
        ("ridgewood-book-club-2", "Ridgewood Book Club", ""),
        ("another-program", "Another Program", ""),
        ("open-art-studio-4", "Special Art Studio", "Other Hall, 123 Main St, Bennington, NE"),
    ):
        event = Event()
        event.add("uid", slug)
        event.add("summary", title)
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(hours=1))
        event.add("url", f"https://benningtonlibrary.org/event/{slug}/")
        if location:
            event.add("location", location)
        calendar.add_component(event)

    with patch.object(preview_worker, "fetch_publisher", return_value=calendar.to_ical().decode()) as fetch:
        records = preview_worker.preview_source(source)["p_events"]
        assert fetch.call_args.kwargs["respect_robots"]
        assert fetch.call_args.kwargs["allowed_hosts"] == ("benningtonlibrary.org",)
    by_title = {row["title"]: row for row in records}
    assert by_title["Storytime"]["venue_address"] == "11401 North 156th Street, Bennington, NE 68007"
    assert by_title["Ridgewood Book Club"]["venue_address"] == "12301 North 149th Circle, Bennington, NE"
    assert not by_title["Another Program"]["venue_address"]
    assert by_title["Special Art Studio"]["venue_address"] == "123 Main St, Bennington, NE"
