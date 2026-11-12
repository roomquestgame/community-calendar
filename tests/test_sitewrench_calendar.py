import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from roomquest import sitewrench_calendar as zoo


class SiteWrenchCalendarTest(unittest.TestCase):
    def test_public_pagination_preserves_dated_occurrences(self):
        def page(day, next_link=""):
            return f"""<div><div class="swCalEvents">
              <article class="CalendarListEvent">
                <a href="/special-events/event/42/date/2026-11-{day}">Details</a>
                <div class="CalendarListEvent__title">Zoolightful</div>
                <div class="CalendarListEvent__meta">November {day}, 2026 @ 6:00 PM - 9:30 PM</div>
              </article></div>{next_link}</div>"""

        link = '<nav class="CalendarListPagination"><a href="?cal-414412-page=2">Next</a></nav>'
        fetch = Mock(side_effect=[page(18, link), page(19)])
        source = {"source_key": zoo.KEY, "feed_url": zoo.CALENDAR, "timezone": zoo.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        with patch.object(zoo, "record", side_effect=lambda title, start, end, venue, address,
                          city, url, identity, **kwargs: {"id": identity, "starts_at": start,
                                                         "ends_at": end}):
            rows = zoo.collect(source, fetch, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual([row["id"] for row in rows], ["42:2026-11-18", "42:2026-11-19"])
        self.assertEqual(rows[0]["starts_at"], "2026-11-18T18:00:00")
        self.assertEqual(rows[0]["ends_at"], "2026-11-18T21:30:00")
        self.assertIn("cal-414412-page=2", fetch.call_args.args[0])

    def test_featured_fallback_uses_dated_official_link(self):
        featured = """<ul><li>
          <p class="upcoming-events-date"><span class="upcoming-events-month">Nov</span>
          <span class="upcoming-events-date">18</span>
          <span class="upcoming-events-time">6:00 PM - 9:30 PM</span></p>
          <p class="upcoming-events-name"><a href="/special-events/event/42/date/2026-11-18">Zoolightful</a></p>
          </li></ul>"""
        source = {"source_key": zoo.KEY, "feed_url": zoo.CALENDAR, "timezone": zoo.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        fetch = Mock(side_effect=["<main>Special Events</main>", featured])
        with patch.object(zoo, "record", return_value={"id": "42:2026-11-18", "starts_at": "start"}) as record:
            rows = zoo.collect(source, fetch, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(record.call_args.args[1:3], ("2026-11-18T18:00:00", "2026-11-18T21:30:00"))
        self.assertEqual(fetch.call_args.args, ("https://www.omahazoo.com/", "text/html"))
