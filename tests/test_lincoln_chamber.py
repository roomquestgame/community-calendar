import unittest
from unittest.mock import Mock, patch

from roomquest import lincoln_chamber as chamber


class LincolnChamberTest(unittest.TestCase):
    def test_only_public_same_host_exports_are_collected(self):
        listing = """<main><h1>Upcoming Events</h1>
          <a href="/event/13508485-business-toolbox">Business Toolbox</a>
          <a href="/ws/event.ics?id=13508485">Calendar</a>
          <a href="/ws/event.ics?id=13508485">Duplicate</a>
          <a href="https://other.example/ws/event.ics?id=13">Other</a>
          <a href="/ws/event.ics?id=12&amp;unexpected=true">Other parameters</a>
          </main>"""
        fetch = Mock(side_effect=[listing, "official iCalendar"])
        source = {"source_key": chamber.KEY, "feed_url": chamber.LISTING, "timezone": chamber.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        with patch.object(chamber, "event_record", return_value={"id": "13508485", "starts_at": "start"}) as parse:
            rows = chamber.collect(source, fetch)
        self.assertEqual(len(rows), 1)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args.args, ("https://www.lcoc.com/ws/event.ics?id=13508485", "text/calendar"))
        parse.assert_called_once_with("official iCalendar",
                                      "https://www.lcoc.com/event/13508485-business-toolbox", "13508485")
