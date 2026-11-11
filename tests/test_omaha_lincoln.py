from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from roomquest import omaha_lincoln, preview_worker


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
