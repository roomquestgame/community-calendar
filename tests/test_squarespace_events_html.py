import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from roomquest import squarespace_events_html as squarespace


class SquarespaceVenueCalendarTest(unittest.TestCase):
    def test_occurrence_uses_published_dates_and_ignores_archived_cards(self):
        key = "pageturners_lounge_omaha_ne"
        listing, *_ = squarespace.SOURCES[key]
        source = {"source_key": key, "feed_url": listing, "timezone": squarespace.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        card = """<article class="eventlist-event eventlist-event--upcoming">
          <a class="eventlist-title-link" href="/event-calendar/2026/10/21/pub-quiz">Literary Pub Quiz</a>
          <time class="event-date" datetime="2026-11-18">Wednesday, November 18, 2026</time>
          <time class="event-time-12hr-start" datetime="2026-11-18">7:00 PM</time>
          <time class="event-time-12hr-end" datetime="2026-11-18">9:30 PM</time>
          </article>"""
        fetch = Mock(return_value="<main>" + card + card.replace("--upcoming", "--past") + "</main>")
        with patch.object(squarespace, "record", return_value={"id": "quiz", "starts_at": "start"}) as record:
            rows = squarespace.collect(source, fetch, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(record.call_count, 1)
        self.assertEqual(record.call_args.args[1:3], ("2026-11-18T19:00:00", "2026-11-18T21:30:00"))
        fetch.assert_called_once_with(listing, "text/html")


    def test_saro_requires_the_lincoln_address_on_each_card(self):
        key = "saro_cider_lincoln_ne"
        listing, *_ = squarespace.SOURCES[key]
        source = {"source_key": key, "feed_url": listing, "timezone": squarespace.ZONE,
                  "kind": "html", "platform_adapter": "html"}
        card = """<article class="eventlist-event eventlist-event--upcoming">
          <a class="eventlist-title-link" href="/upcoming-events/music">Live Music</a>
          <time class="event-date" datetime="2026-11-18">November 18</time>
          <time class="event-time-12hr-start" datetime="2026-11-18">7:00 PM</time>
          <a href="https://maps.google.com/?q=1746+N+Street+Lincoln%2C+NE">Map</a>
          </article>"""
        fetch = Mock(return_value="<main>" + card + card.replace("1746+N+Street+Lincoln", "1012+S+10th+Omaha") + "</main>")
        with patch.object(squarespace, "record", return_value={"id": "music", "starts_at": "start"}) as record:
            rows = squarespace.collect(source, fetch, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        record.assert_called_once()
        self.assertEqual(record.call_args.args[4:6], ("1746 N St, Lincoln, NE 68508", "Lincoln"))
