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
    assert len(omaha_lincoln.new_ical_feeds()) == 7


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
