import base64
from datetime import datetime, timezone
from html import escape
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_social as ac


NOW = datetime(2026, 11, 14, 22, tzinfo=timezone.utc)


def source():
    return dict(source_key=ac.CLANCY, feed_url=ac.URL, kind="html", platform_adapter="html", timezone=ac.ZONE)


def fake_record(title, start, end, venue, address, city, url, identity, **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, lat=None, lng=None)


def item(day="2026-11-17", body="Join our weekly karaoke with Lori Kelley!", title="Karaoke with Lori Kelley"):
    start = datetime.fromisoformat(day + "T19:00:00-05:00")
    end = datetime.fromisoformat(day + "T22:00:00-05:00")
    native = "21sqovrn9d0n6lnssuo7foc6f5_" + start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    eid = base64.urlsafe_b64encode((native + " " + ac.CALENDAR).encode()).decode().rstrip("=")
    return (f'<li class="simcal-event"><span class="simcal-event-title" itemprop="name">{escape(title)}</span>'
            f'<span class="simcal-event-start-time" content="{start.isoformat()}" data-event-start="{int(start.timestamp())}">7:00 pm</span>'
            f'<span class="simcal-event-end-time" content="{end.isoformat()}" data-event-end="{int(end.timestamp())}">10:00 pm</span>'
            f'<meta itemprop="address" content="{escape(ac.NATIVE_ADDRESS, quote=True)}">'
            f'<div class="simcal-event-description"><p>{body}</p></div>'
            f'<a href="https://www.google.com/calendar/event?eid={eid}&amp;ctz=America/New_York">Details</a></li>')


def calendar(*items):
    return ('<div class="simcal-calendar" data-calendar-id="1642">'
            '<span class="simcal-current-month">November</span><span class="simcal-current-year">2026</span>'
            + "".join(items) + '</div>')


class AtlanticSocialTests(unittest.TestCase):
    def parse(self, payload):
        with patch.object(ac, "record", side_effect=fake_record):
            return ac.parse_calendar(payload, NOW)

    def test_preserves_full_long_narrative_and_escaped_literal_once(self):
        body = "Full program details. " * 150 + "Bring &lt;your ID&gt; &amp; friends."
        rows = self.parse(calendar(item(body=body)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Full program details. " * 150 + "Bring <your ID> & friends.")
        self.assertEqual(rows[0]["venue_address"], ac.VENUE[1])
        self.assertEqual(rows[0]["starts_at"], "2026-11-17T19:00:00-05:00")

    def test_accepts_only_listed_occurrences_no_weekly_projection(self):
        rows = self.parse(calendar(item("2026-11-10"), item("2026-11-17"), item("2026-11-24")))
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["id"] for r in rows], ["clancy:21sqovrn9d0n6lnssuo7foc6f5_20261118T000000Z", "clancy:21sqovrn9d0n6lnssuo7foc6f5_20261125T000000Z"])

    def test_deduplicates_identical_native_occurrence_and_rejects_conflict(self):
        self.assertEqual(len(self.parse(calendar(item(), item()))), 1)
        with self.assertRaisesRegex(ValueError, "duplicate_occurrence"):
            self.parse(calendar(item(), item(body="Changed program details")))

    def test_rejects_blank_and_over_limit_instead_of_clipping(self):
        for body, error in (("", "description_missing"), ("x" * 12001, "description_limit")):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.parse(calendar(item(body=body)))
        self.assertEqual(len(self.parse(calendar(item(body="x" * 12000)))[0]["description"]), 12000)

    def test_time_epoch_offset_and_visible_clock_must_agree(self):
        data = calendar(item())
        for before, after in (("7:00 pm", "8:00 pm"), ("T19:00:00-05:00", "T19:00:00-04:00"), ("November", "December")):
            with self.subTest(before=before), self.assertRaisesRegex(ValueError, "schedule_changed"):
                self.parse(data.replace(before, after))

    def test_foreign_event_calendar_or_venue_fails(self):
        data = calendar(item())
        for before, after, error in (("ctz=America/New_York", "ctz=America/Chicago", "identity_changed"),
                                     ("101 E Maryland Ave", "999 Unknown Ave", "venue_changed"),
                                     ('data-calendar-id="1642"', 'data-calendar-id="1234"', "calendar_changed")):
            with self.subTest(before=before), self.assertRaisesRegex(ValueError, error):
                self.parse(data.replace(before, after))

    def test_cancelled_listing_is_excluded(self):
        self.assertEqual(self.parse(calendar(item(title="Cancelled karaoke"))), [])

    def test_exact_source_contract_prevents_any_fetch_for_wrong_identity(self):
        for field, wrong in (("source_key", "unreviewed"), ("feed_url", "https://example.org"),
                             ("timezone", "America/Chicago"), ("kind", "ical")):
            value = source(); value[field] = wrong
            fetch = Mock()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unregistered"):
                ac.collect(value, fetch, now=NOW)
            fetch.assert_not_called()

    def test_native_html_requires_only_one_publisher_fetch(self):
        fetch = Mock(return_value=calendar(item()))
        with patch.object(ac, "record", side_effect=fake_record):
            rows = ac.collect(source(), fetch, now=NOW)
        self.assertEqual(len(rows), 1)
        fetch.assert_called_once_with(ac.URL, "text/html")


if __name__ == "__main__":
    unittest.main()
