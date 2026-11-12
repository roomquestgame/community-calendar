import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from roomquest import webtrac


class WebTracTest(unittest.TestCase):
    def test_public_calendar_matches_date_time_and_meeting_address(self):
        calendar = """<table><caption>Event Calendar</caption><tr><td>
          <button aria-label="Date: 12/05/2026">5</button>
          <a class="calendar__block" data-state-item="912220674"
            aria-label="Holiday Hike at Hummel&#10;10:00 am - 12:00 pm"
            href="/webtrac/web/search.html?display=detail&amp;FMID=912220674&amp;Module=AR">Hike</a>
          </td></tr></table>"""
        meeting = """<section><h4 class="item-info__details-heading">Meeting Details</h4>
          <div><div>Date(s): 12/05/2026 - 12/05/2026</div><div>Time: 10:00 am - 12:00 pm</div>
          <div>Days: Sat</div><div>Hummel Nature Center</div><div>3033 Hummel Park Road</div>
          <div>Omaha,&nbsp;NE,&nbsp;68112</div></div></section>"""
        fetch = Mock(side_effect=[calendar, meeting])
        source = {"source_key": webtrac.KEY, "feed_url": webtrac.CALENDAR, "timezone": webtrac.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        with patch.object(webtrac, "record", return_value={"id": "912220674:2026-12-05",
                                                           "starts_at": "start"}) as record:
            rows = webtrac.collect(source, fetch, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(record.call_args.args[1:6], (
            "2026-12-05T10:00:00", "2026-12-05T12:00:00", "Hummel Nature Center",
            "3033 Hummel Park Road, Omaha, NE 68112", "Omaha",
        ))
        self.assertIn("/iteminfo.html?FMID=912220674&Module=AR", fetch.call_args.args[0])
