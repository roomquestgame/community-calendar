import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from roomquest import rockhouse


class RockhouseTest(unittest.TestCase):
    def setUp(self):
        self.listing, self.suffix, self.venue, self.address = rockhouse.SOURCES["omaha_admiral_events"]
        self.detail = "https://admiralomaha.com/event/a-show/" + self.suffix
        self.today, self.horizon = date(2026, 11, 12), date(2027, 1, 11)

    def test_only_same_venue_links_are_collected(self):
        payload = (f'<body><h1>Upcoming Events</h1><a href="{self.detail}">Show</a>'
                   '<a href="https://other.example/event/another/the-admiral/omaha-nebraska/">Offsite</a></body>')
        self.assertEqual(rockhouse.detail_links(payload, self.listing, self.suffix), [self.detail])

    def test_performance_uses_show_time_and_local_date(self):
        payload = '<body><h1>A Show</h1><div>Friday, November 20</div><div>Doors: 7 pm</div><div>Show: 8:30 pm</div></body>'
        with patch.object(rockhouse, "record", return_value={"id": self.detail}) as record:
            self.assertEqual(rockhouse.event_record(payload, self.detail, self.venue, self.address,
                                                   self.today, self.horizon), {"id": self.detail})
        self.assertEqual(record.call_args.args[1], "2026-11-20T20:30:00")
        self.assertEqual(record.call_args.kwargs["tz"], "America/Chicago")

    def test_door_time_alone_is_not_published(self):
        payload = '<body><h1>A Show</h1><div>Friday, November 20</div><div>Doors: 7 pm</div></body>'
        self.assertIsNone(rockhouse.event_record(payload, self.detail, self.venue, self.address,
                                                self.today, self.horizon))

    def test_reverb_uses_listing_show_time_and_month_heading(self):
        key = "omaha_reverb_lounge_events"
        listing, suffix, _, _ = rockhouse.SOURCES[key]
        detail = "https://reverblounge.com/event/a-show/" + suffix
        source = {"source_key": key, "feed_url": listing, "timezone": rockhouse.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        payload = f"""<body><h1>Upcoming Events</h1><div class="generalView">
            <!-- Calendar template marker -->
            <div class="rhp-events-list-separator-month">January 2027</div>
            <div class="rhpSingleEvent">
              <span class="singleEventDate">Sat, Jan 2</span>
              <a id="eventTitle" href="{detail}"><h2>A Show</h2></a>
              <span class="rhp-event__time-text--list">Doors: 7 pm // Show: 8:15 pm</span>
            </div></div></body>"""
        fetch = Mock(return_value=payload)
        with patch.object(rockhouse, "record", return_value={"id": detail, "starts_at": "start"}) as record:
            rows = rockhouse.collect(source, fetch, now=datetime(2026, 12, 30, tzinfo=timezone.utc))
        fetch.assert_called_once_with(listing, "text/html")
        self.assertEqual(len(rows), 1)
        self.assertEqual(record.call_args.args[1], "2027-01-02T20:15:00")
