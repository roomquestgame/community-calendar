"""Focused RoomQuest preview tests: all fixtures synthetic, no live publisher calls."""
import importlib.util
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from roomquest.preview_worker import _preview, public_source_url, SUPPORTED
from scripts.roomquest_catalog import catalog


class PreviewSafetyTests(unittest.TestCase):

    def test_demand_worker_only_claims_requested_source(self):
        from roomquest.preview_worker import collect_demand_previews
        source = {"source_key": "fixture_ical", "feed_url": "https://example.org/a.ics"}
        with patch("roomquest.preview_worker.supabase_rpc", return_value=[source]) as rpc, patch(
                "roomquest.preview_worker._process_claimed_source",
                return_value={"complete": 1, "failed": 0, "staged": 2}) as process:
            self.assertEqual(collect_demand_previews(),
                             {"claimed": 1, "complete": 1, "failed": 0, "staged": 2})
            rpc.assert_called_once_with("community_collector_claim_demand_preview", {})
            process.assert_called_once_with(source)

    def test_large_official_ical_feed_is_bounded_but_accepted(self):
        from roomquest.preview_worker import fetch_publisher, MAX_BODY, PreviewError
        self.assertGreaterEqual(MAX_BODY, 1_240_000)
        self.assertLessEqual(MAX_BODY, 3_000_000)
        response = MagicMock(status_code=200, headers={"Content-Length": "1240000"}, encoding="utf-8")
        response.iter_content.return_value = [b"BEGIN:VCALENDAR", b"A" * 1_239_985]
        with patch("roomquest.preview_worker.validate_public_dns"), patch(
                "roomquest.preview_worker.requests.Session") as factory:
            factory.return_value.__enter__.return_value.get.return_value = response
            self.assertEqual(len(fetch_publisher("https://calendar.example.org/events.ics", "text/calendar")), 1_240_000)
        response.iter_content.return_value = [b"x" * (MAX_BODY + 1)]
        response.headers = {}
        with patch("roomquest.preview_worker.validate_public_dns"), patch(
                "roomquest.preview_worker.requests.Session") as factory:
            factory.return_value.__enter__.return_value.get.return_value = response
            with self.assertRaisesRegex(PreviewError,"source_too_large"):
                fetch_publisher("https://calendar.example.org/events.ics", "text/calendar")

    def test_unsafe_urls_fail_closed(self):
        blocked = [
            "http://calendar.example.org/events.ics",
            "https://localhost/events",
            "https://127.0.0.1/calendar.ics",
            "https://10.0.0.5/events",
            "https://192.168.1.1/",
            "https://evil.local/events",
            "https://person:password@events.example.org/",
            "https://events.example.org:8443/events",
            "https://events.example.org./events",
            "https://metadata.google.internal/",
        ]
        for url in blocked:
            with self.subTest(url=url):
                self.assertFalse(public_source_url(url))
        self.assertTrue(public_source_url("https://example.org/events/?ical=1"))

    def test_only_unambiguous_future_timed_events(self):
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        good = _preview("Public Event", tomorrow, tomorrow + timedelta(hours=2),
                        "Actual Park", 35.77, -78.63, "https://example.org/event/1")
        self.assertIsNotNone(good)
        self.assertEqual(good["lat"], 35.77)
        self.assertIsNone(_preview("Future floating date", tomorrow.replace(tzinfo=None),
                                   None, "Park", 35.77, -78.63, "https://example.org"))
        unlocated = _preview("Not located", tomorrow, None, "Unknown", None, None,
                             "https://example.org/event/2")
        self.assertEqual(unlocated["reason"], "missing_verified_venue_geo")
        self.assertIsNone(unlocated["lat"])

    def test_udell_redirects_revalidate_every_hop(self):
        from roomquest.preview_worker import fetch_publisher, PreviewError
        first = MagicMock(status_code=301, headers={"Location": "https://example.org/events.ics"})
        last = MagicMock(status_code=200, headers={"Content-Length": "15"}, encoding="utf-8")
        last.iter_content.return_value = [b"BEGIN:VCALENDAR"]
        with patch("roomquest.preview_worker.validate_public_dns"), patch(
            "roomquest.preview_worker.robots_allowed", return_value=True), patch(
            "roomquest.preview_worker.requests.Session") as factory:
            factory.return_value.__enter__.return_value.get.side_effect = [first, last]
            self.assertEqual(fetch_publisher("https://old.example.org/feed", "text/calendar"), "BEGIN:VCALENDAR")
            self.assertEqual(factory.return_value.__enter__.return_value.get.call_count, 2)
        with patch("roomquest.preview_worker.validate_public_dns"), patch(
            "roomquest.preview_worker.robots_allowed", return_value=True), patch(
            "roomquest.preview_worker.requests.Session") as factory:
            factory.return_value.__enter__.return_value.get.return_value = MagicMock(
                status_code=301, headers={"Location": "http://127.0.0.1/secrets"})
            with self.assertRaisesRegex(PreviewError, "invalid_redirect_url"):
                fetch_publisher("https://old.example.org/feed", "text/calendar")

    def test_udell_direct_transport_does_not_preflight_robots(self):
        from roomquest.preview_worker import fetch_publisher
        response = MagicMock(status_code=200,
                             headers={"Content-Length": "15"}, encoding="utf-8")
        response.iter_content.return_value = [b"BEGIN:VCALENDAR"]
        with patch("roomquest.preview_worker.validate_public_dns"), patch(
            "roomquest.preview_worker.robots_allowed") as robots, patch(
            "roomquest.preview_worker.requests.Session") as factory:
            factory.return_value.__enter__.return_value.get.return_value = response
            self.assertEqual(fetch_publisher("https://example.org/feed.ics", "text/calendar"),
                             "BEGIN:VCALENDAR")
            robots.assert_not_called()

    def test_supported_adapters_include_reviewed_json_calendars(self):
        self.assertEqual(SUPPORTED, {"ical", "jsonld", "growthzone", "wordpress", "squarespace"})

    def test_udell_raleigh_inventory_is_staged_only(self):
        rows, skipped = catalog("raleighdurham")
        self.assertGreaterEqual(len(rows), 70)
        self.assertGreaterEqual(len(skipped), 1)
        self.assertTrue(all(x["feed_url"].startswith("https://") for x in rows))
        self.assertTrue(all("unverified" in x["note"] for x in rows))
        self.assertTrue(all("approval" not in x for x in rows))

    @unittest.skipUnless(importlib.util.find_spec("icalendar"), "upstream icalendar dependency not installed")
    def test_ics_recurrence_and_precise_geo(self):
        from roomquest.preview_worker import parse_ics_preview
        start = datetime.now(timezone.utc) + timedelta(days=1)
        stamp = start.strftime("%Y%m%dT%H%M%SZ")
        raw = ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:rqunit@example.org\n"
               "SUMMARY:Fixture Recurring Festival\nDTSTART:" + stamp +
               "\nDURATION:PT2H\nRRULE:FREQ=DAILY;COUNT=2\nGEO:35.77;-78.63\n"
               "LOCATION:Actual Fixture Park\nURL:https://example.org/festival\n"
               "END:VEVENT\nEND:VCALENDAR")
        records = parse_ics_preview(raw)
        self.assertGreaterEqual(len(records), 2)
        self.assertEqual(records[0]["lat"], 35.77)

    @unittest.skipUnless(importlib.util.find_spec("icalendar"), "upstream Python dependencies not installed")
    def test_jsonld_venue_not_fabricated(self):
        from roomquest.preview_worker import parse_jsonld_preview
        stamp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        event = {"@context": "https://schema.org", "@type": "Event",
                 "name": "Fixture Town Lecture", "startDate": stamp,
                 "url": "https://example.org/lecture",
                 "location": {"@type": "Place", "name": "Fixture Library",
                              "geo": {"latitude": 36.7, "longitude": -78.1}}}
        html = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
        parsed = parse_jsonld_preview(html)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["lng"], -78.1)


if __name__ == "__main__":
    unittest.main()


def test_public_shift_requires_posted_street_and_keeps_occurrence_identity():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import json
    import pytest
    from roomquest import richmond_public_calendars as calendars

    day_start = (datetime.now(ZoneInfo(calendars.ZONE)) + timedelta(days=1)).replace(hour=9, minute=0)
    shift = {
        "opportunityName": "Park Cleanup", "organizationServedName": "Friends of the Park",
        "locationType": "Address", "locationState": "VA", "locationCity": "Richmond",
        "locationZipCode": "23223", "timezone": calendars.ZONE, "opportunityType": "Project",
        "volunteersStillNeeded": "5", "description": "Meet at 50 Evergreen Road, Richmond.",
        "startDateTimeISO": day_start.isoformat(),
        "endDateTimeISO": (day_start + timedelta(hours=2)).isoformat(),
        "opportunityLink": "https://www.cfengage.org/opportunity/a0CNw0000JM6ICdMQN",
        "occurrenceId": "a0CNw0000JM6ICdMQN",
    }
    changes = [
        {"description": "Address shared with registered volunteers."},
        {"locationType": "Virtual"},
        {"opportunityLink": "https://another.example/opportunity/a0CNw0000JM6ICdMQN"},
        {"volunteersStillNeeded": "0"},
        {"description": "Volunteers must be 26 if a volunteer is court ordered."},
    ]
    day = {"overMaxToReturn": False, "occurrences": [shift, *(shift | change for change in changes)]}
    [row] = calendars.volunteer_shifts(json.dumps({"items": [day]}))
    assert row["id"] == shift["occurrenceId"]
    assert row["venue_address"] == "50 Evergreen Road, Richmond, VA 23223"
    day["overMaxToReturn"] = True
    with pytest.raises(ValueError, match="handson_calendar_truncated"):
        calendars.volunteer_shifts(json.dumps({"items": [day]}))


def test_runsignup_uses_registration_identity_and_ignores_mailing_lists():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from roomquest import richmond_public_calendars as calendars

    now = datetime(2026, 11, 12, tzinfo=ZoneInfo(calendars.ZONE))
    item = """<tr><td class="calendar-race-date">Sun, Nov 15 2026</td>
        <td class="race-title"><a href="https://runsignup.com/Race/VA/Henrico/Run">{title}</a></td>
        <td><a href="https://runsignup.com/Race/Register?raceId={id}">Register</a></td></tr>"""
    payload = '<table class="upcoming-races-table">' + item.format(title="Run", id=123)
    payload += item.format(title="Run Mailing List", id=456) + "</table>"
    assert calendars.race_listing(payload, now) == {
        "123": "https://runsignup.com/Race/VA/Henrico/Run",
    }


def test_runsignup_public_detail_publishes_named_timed_race_at_location():
    import json
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from roomquest import richmond_public_calendars as calendars

    now = datetime.now(ZoneInfo(calendars.ZONE))
    start = (now + timedelta(days=1)).isoformat()
    item = {
        "@type": "SportsEvent", "name": "Community 5K", "startDate": start,
        "location": {"@type": "Place", "address": {
            "streetAddress": "Dorey Park", "addressLocality": "Henrico",
            "addressRegion": "VA", "postalCode": "23231",
        }},
    }
    page = '<h2 class="rsuWebsiteSection__title">Race Location</h2>'
    page += '<p>Dorey Park<br>2999 Darbytown Rd<br>Henrico, VA 23231 US</p>'
    for data in (item, item | {"name": "Virtual 5K"}, item | {"additionalType": "Product"}):
        page += f'<script type="application/ld+json">{json.dumps(data)}</script>'
    [event] = calendars.race_events(
        page, "123", "https://runsignup.com/Race/VA/Henrico/Run", now,
    )
    assert event["venue_address"] == "2999 Darbytown Rd, Henrico, VA 23231"
    assert event["ends_at"] is None
