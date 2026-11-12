import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from roomquest import eventer


class EventerTest(unittest.TestCase):
    def test_dated_card_uses_publisher_times(self):
        card = """<a class="eventer-event-item-link" href="/eventer/bright-nights/edate/2026-11-27">
          <span class="eventer-event-day">27</span><span class="eventer-event-month">NOV</span>
          <span class="eventer-event-year">2026</span>
          <span class="eventer-event-title">Bright Nights</span>
          <span class="eventer-event-time">5:00 PM to 9:00 PM</span>
          <span class="eventer-status-badge">Upcoming</span></a>"""
        payload = '<div class="eventer-dynamic-listings-main">' + card + card + '</div>'
        fetch = Mock(return_value=payload)
        source = {"source_key": eventer.KEY, "feed_url": eventer.CALENDAR, "timezone": eventer.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        with patch.object(eventer, "record", return_value={"id": "bright-nights:2026-11-27",
                                                          "starts_at": "start"}) as record:
            rows = eventer.collect(source, fetch, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        fetch.assert_called_once_with(eventer.CALENDAR, "text/html")
        self.assertEqual(len(rows), 1)
        self.assertEqual(record.call_args.args[1:3], ("2026-11-27T17:00:00", "2026-11-27T21:00:00"))
