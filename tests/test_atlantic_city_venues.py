from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_venues as venues


NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def source(key):
    return dict(source_key=key, feed_url=venues.SOURCES[key][0], timezone=venues.ZONE,
                kind="html", platform_adapter="html")


def row_record(title, start, end, venue, address, city, url, identity, category="", *args, **kwargs):
    return dict(id=str(identity), title=title, starts_at=start, ends_at=end, venue_name=venue,
                venue_address=address, venue_city=city, event_url=url, category=category,
                lat=kwargs.get("lat"), lng=kwargs.get("lng"))


class AtlanticCityVenueTests(unittest.TestCase):
    def collect(self, key, payload, now=NOW):
        fetch = Mock(return_value=payload)
        with patch.object(venues, "record", side_effect=row_record):
            result = venues.collect(source(key), fetch, now=now)
        return result, fetch

    def test_anchor_preserves_complete_prose_and_ignores_hidden_cancel_label(self):
        body = ("A detailed account of the artists, music and admission policies. " * 45) + "Bring <admission notes>. Final sentence."
        encoded_body = body.replace('<', '&lt;').replace('>', '&gt;')
        card = f"""<div class="w-dyn-item"><a id="event-location" href="/shows/community-concert"></a>
          <div id="event-start">November 18, 2026 8:00 PM</div><div id="event-title">Community Concert</div>
          <div class="canclled w-condition-invisible">Show Cancelled</div>
          <div id="event-desc"><p>{encoded_body}</p><script>untrusted script</script></div></div>"""
        payload = '<div class="collection-list">' + card + card.replace('w-condition-invisible', '').replace('community-concert', 'cancelled-concert') + '</div>'
        rows, fetch = self.collect(venues.ANCHOR, payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], body)
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertEqual(rows[0]["venue_address"], venues.VENUES[venues.ANCHOR][1])
        self.assertEqual(rows[0]["category"], "")
        self.assertEqual((rows[0]["lat"], rows[0]["lng"]), (39.3572301, -74.4262279))
        self.assertEqual(rows[0]["location_provenance"], "reviewed_venue_location")
        fetch.assert_called_once_with(venues.SOURCES[venues.ANCHOR][0], "text/html")

    def test_reviewed_points_require_exact_source_venue_and_street(self):
        expected = {
            venues.ANCHOR: (39.3572301, -74.4262279),
            venues.SEASIDE: (39.3845487, -74.4296631),
            venues.SMITHVILLE: (39.495354, -74.460754),
        }
        for key, point in expected.items():
            venue, street, _ = venues.VENUES[key]
            with self.subTest(source=key):
                self.assertEqual(venues.reviewed_venue_location(key, venue, street), point)
                self.assertIsNone(venues.reviewed_venue_location("unknown", venue, street))
                self.assertIsNone(venues.reviewed_venue_location(key, "Other room", street))
                self.assertIsNone(venues.reviewed_venue_location(key, venue, street.replace("NJ", "NY")))
                self.assertIsNone(venues.reviewed_venue_location(key, venue, ""))
                other = venues.SEASIDE if key != venues.SEASIDE else venues.ANCHOR
                self.assertIsNone(venues.reviewed_venue_location(other, venue, street))

    def test_reviewed_point_keeps_long_text_and_changed_street_unresolved(self):
        now = datetime.now(timezone.utc)
        body = "Complete artist biography and admission details. " * 118 + "Final paragraph."
        params = (venues.ANCHOR, "Live performance", now + timedelta(days=1), None,
                  "https://www.anchorrockclub.com/shows/live-performance", "live-performance", body)
        resolved = venues._row(*params)
        self.assertEqual((resolved["lat"], resolved["lng"]), (39.3572301, -74.4262279))
        self.assertEqual(resolved["description"], body)
        self.assertGreater(len(resolved["description"]), 5600)
        self.assertEqual(resolved["starts_at"], (now + timedelta(days=1)).isoformat())
        with patch.dict(venues.VENUES, {venues.ANCHOR: (
                "Anchor Rock Club", "999 S New York Ave, Atlantic City, NJ 08401", "Atlantic City")}):
            unresolved = venues._row(*params)
        self.assertIsNone(unresolved["lat"])
        self.assertIsNone(unresolved["lng"])
        self.assertEqual(unresolved["description"], body)
        self.assertEqual(unresolved["location_provenance"], "reviewed_venue_street_address_pending_geocode")

    def test_blank_or_oversized_narrative_is_not_silently_published(self):
        for body in ("<script>no event prose</script>", "a" * 12001):
            with self.assertRaises(ValueError):
                venues.narrative(body)
        for body in (" \n\t", "a" * 12001):
            with self.assertRaises(ValueError):
                venues._row(venues.SOMERS_BREW, "DJ Trivia", NOW + timedelta(days=2), None,
                            venues.SOURCES[venues.SOMERS_BREW][0], "bounded-prose", body,
                            already_normalized=True)

    def test_published_end_keeps_an_ongoing_event_during_its_last_hour(self):
        now = datetime.now(timezone.utc)
        row = venues._row(venues.CAROLINES, "DJ Trivia", now - timedelta(hours=1),
                          now + timedelta(minutes=15), venues.SOURCES[venues.CAROLINES][0],
                          "ongoing-trivia", "Official trivia hosted by the venue.")
        self.assertIsNotNone(row)
        self.assertEqual(row["ends_at"], (now + timedelta(minutes=15)).isoformat())

    def test_tennessee_ambiguous_season_does_not_invent_weekly_clocks(self):
        payload = """<div class="eventlist"><article class="eventlist-event--upcoming">
          <a class="eventlist-title-link" href="/new-events/college-football">College Football Saturdays</a>
          <div class="eventlist-meta-date">
          <time class="event-time-12hr" datetime="2026-09-19">11:00 AM</time>
          <time class="event-time-12hr" datetime="2026-12-05">10:00 PM</time></div>
          <a class="eventlist-meta-export-google" href="http://www.google.com/calendar/event?dates=20260919T150000Z/20261206T030000Z">Google</a>
          <a href="/new-events/college-football?format=ical">ICS</a>
          <div class="eventlist-description">College Football Every Saturday. All the games and game-day food specials.</div>
          </article></div>"""
        rows, fetch = self.collect(venues.TENNESSEE, payload)
        self.assertEqual(rows, [])
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("format=", fetch.call_args.args[0])
        with self.assertRaisesRegex(ValueError, "schedule_conflict"):
            self.collect(venues.TENNESSEE, payload.replace("20260919T150000Z", "20260919T160000Z"))

    def test_unknown_multiday_tennessee_pattern_is_not_projected(self):
        payload = """<div class="eventlist"><article class="eventlist-event--upcoming">
          <a class="eventlist-title-link" href="/new-events/season">Seasonal promotion</a>
          <div class="eventlist-meta-date"><time class="event-time-12hr" datetime="2026-11-01">10:00 AM</time>
          <time class="event-time-12hr" datetime="2026-12-31">5:00 PM</time></div>
          <div class="eventlist-description">Come enjoy seasonal activities.</div></article></div>"""
        rows, _ = self.collect(venues.TENNESSEE, payload)
        self.assertEqual(rows, [])

    def test_somers_month_scoping_and_unpublished_mahjong_time(self):
        payload = """<main><h1>November Hours – Open 7 days</h1><p>705 W New York Avenue</p>
          <p>MONDAYS – MAHJONG: Join the crew.</p>
          <p>WEDNESDAYS – DJ TRIVIA: Signups at 7pm. No cost to participate. Use &lt;team name&gt; on signup.</p>
          <p>THURSDAYS – LIVE MUSIC (6-8pm) – Weekly rotating local artists.</p></main>"""
        rows, _ = self.collect(venues.SOMERS_BREW, payload)
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["title"] for row in rows}, {"DJ Trivia", "Live Music"})
        self.assertTrue(all(row["starts_at"].startswith("2026-11-") for row in rows))
        self.assertTrue(all(row["description"].endswith("Use <team name> on signup.")
                            for row in rows if row["title"] == "DJ Trivia"))
        stale, _ = self.collect(venues.SOMERS_BREW, payload, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(stale, [])

    def test_seaside_stops_at_published_end_and_keeps_wildwood_out(self):
        payload = """<div class="pool-program" id="harrahs"><p>Atlantic City, NJ</p>
          <p class="pool-lead">Running Saturdays and Sundays, September 12 through December 27, 2026.</p>
          <div class="pool-day"><span class="pool-day-name">Saturday</span><div class="pool-class">
          <span class="pool-time">9:00 AM</span><h4>Yin + Restore Yoga</h4><p>Longer holds for a calm practice.</p>
          </div></div><p class="pool-cta">No booking needed. $25 for non-hotel guests. Read &lt;class instructions&gt;.</p></div>
          <div class="feature-event-body"><h2 class="fe-title">Sound Bowl Meditation</h2>
          <p>Crystal singing bowls, pillows and blankets. Read &lt;meditation instructions&gt;.</p>
          <div class="fe-session"><p class="fe-s-label">Saturday · November 14, 2026</p>
          <span class="fe-s-time">6:00 PM</span><p class="fe-s-doors">Wildwood Crest</p></div>
          <div class="fe-session"><p class="fe-s-label">Friday · December 4, 2026</p>
          <span class="fe-s-time">7:00 PM</span><p class="fe-s-doors">The Pool at Harrah's · Doors 6:30 · Ends 8:00</p></div></div>"""
        rows, _ = self.collect(venues.SEASIDE, payload)
        sound = [row for row in rows if row["title"] == "Sound Bowl Meditation"]
        self.assertEqual(len(sound), 1)
        self.assertTrue(sound[0]["starts_at"].startswith("2026-12-04T19:00"))
        self.assertTrue(sound[0]["ends_at"].startswith("2026-12-04T20:00"))
        self.assertIn("Read <meditation instructions>.", sound[0]["description"])
        yoga = [row for row in rows if "Yoga" in row["title"]]
        self.assertEqual(yoga[-1]["starts_at"][:10], "2026-12-26")
        self.assertTrue(all("777 Harrah's" in row["venue_address"] for row in rows))
        self.assertTrue(all("No booking needed" in row["description"] for row in yoga))
        self.assertTrue(all("Read <class instructions>." in row["description"] for row in yoga))

    def test_carolines_only_current_week_and_weekday_agreement(self):
        payload = """<div class="onespecial"><h2>Monday November 16th</h2><div class="row">
          <div class="col-sm-8">DJ Trivia | Hosted by Starshield Entertainment. Use &lt;team name&gt; on signup.</div>
          <div class="col-sm-4">07:00 PM - 09:00 PM</div></div></div>"""
        rows, _ = self.collect(venues.CAROLINES, payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "DJ Trivia | Hosted by Starshield Entertainment. Use <team name> on signup.")
        wrong_weekday, _ = self.collect(venues.CAROLINES, payload.replace("Monday", "Tuesday"))
        self.assertEqual(wrong_weekday, [])
        stale, _ = self.collect(venues.CAROLINES, payload, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(stale, [])

    def test_josie_reuses_wordpress_and_restores_full_description(self):
        full_text = "The musicians welcome everyone to this performance. " * 60
        event = dict(id=123, title="Traditional Irish Session", description="<p>" + full_text + "</p>",
                     status="publish", timezone=venues.ZONE,
                     url="https://josiekellys.com/event/traditional-irish-session/2026-11-22/",
                     start_date="2026-11-22 13:00:00", end_date="2026-11-22 13:00:00",
                     utc_start_date="2026-11-22 18:00:00", utc_end_date="2026-11-22 18:00:00", venue=[])
        payload = json.dumps(dict(events=[event, {**event, "id": 124, "title": "CLOSED MONDAYS"}], total_pages=1))
        with patch("roomquest.mapsee_adapter.record", side_effect=row_record):
            rows = venues.collect(source(venues.JOSIE), Mock(return_value=payload), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], full_text.strip())
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertIn("908 Shore Road", rows[0]["venue_address"])
        self.assertIsNone(rows[0]["ends_at"])
        self.assertIsNone(rows[0]["lat"])

    def test_source_and_event_hosts_are_bound(self):
        invalid = {**source(venues.ANCHOR), "feed_url": "https://example.com/events"}
        with self.assertRaisesRegex(ValueError, "unregistered"):
            venues.collect(invalid, Mock())
        for target in ("https://evil.example/shows/event", "https://www.anchorrockclub.com/shows/x?secret=1",
                       "https://www.anchorrockclub.com/shows/../outside", "https://www.anchorrockclub.com/shows/%2e%2e"):
            self.assertFalse(venues.event_url(venues.ANCHOR, target))

    def test_smithville_reuses_full_detail_across_exact_occurrences(self):
        def card(clock, encoded):
            return f'''<div class="ic-event"><div class="ic-event-title"><h2>
              <a href="/56-dicken-s-fest?date={encoded}">DICKENS FESTIVAL / RIDDLESBROOD</a></h2></div>
              <span class="ic-single-next">Saturday, November 28</span>
              <span class="ic-single-starttime">{clock}</span></div>'''
        listing = '<div class="ic-list-events">' + card("01:00 PM", "2026-11-28-13-00") + card("05:00 PM", "2026-11-28-17-00") + '</div>'
        body = ("Historic Smithville, 615 E. Moss Mill Rd, Smithville, NJ 08205. "
                + "Holiday family performances. " * 80 + "Bring <program notes>. Final participation condition.")
        encoded_body = body.replace('<', '&lt;').replace('>', '&gt;')
        detail = f'''<div class="ic-event-header"><h1>DICKENS FESTIVAL / RIDDLESBROOD</h1></div>
          <div class="ic-full-description">{encoded_body}</div><div id="detail-date-list">
          <li class="alldates">Saturday, November 28 <span>01:00 PM</span></li>
          <li class="alldates">Saturday, November 28 <span>05:00 PM</span></li></div>'''
        fetch = Mock(side_effect=lambda url, accept: listing if url == venues.SOURCES[venues.SMITHVILLE][0] else detail)
        with patch.object(venues, "record", side_effect=row_record):
            rows = venues.collect(source(venues.SMITHVILLE), fetch, now=NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(rows[0]["description"], body.strip())
        self.assertGreater(len(rows[0]["description"]), 2000)
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])
        self.assertTrue(venues.event_url(venues.SMITHVILLE, rows[1]["event_url"]))
        self.assertFalse(venues.event_url(venues.SMITHVILLE, rows[1]["event_url"] + "&admin=true"))

    def test_smithville_evening_event_is_not_expired_by_midnight_placeholder(self):
        listing = '''<div class="ic-list-events"><div class="ic-event">
          <div class="ic-event-title"><h2><a href="/24-hospitality-night?date=2026-12-04-00-00">Hospitality Night</a></h2></div>
          <span class="ic-single-next">Friday, December 4</span></div></div>'''
        detail = '''<div class="ic-event-header"><h1>Hospitality Night</h1></div>
          <div class="ic-full-description">Enjoy Hospitality Night at Historic Smithville from 6PM-8PM.</div>
          <div id="detail-date-list"><li class="alldates">Friday, December 4</li></div>'''
        fetch = Mock(side_effect=lambda url, accept: listing if url == venues.SOURCES[venues.SMITHVILLE][0] else detail)
        with patch.object(venues, "record", side_effect=row_record):
            rows = venues.collect(source(venues.SMITHVILLE), fetch,
                                  now=datetime(2026, 12, 4, 15, tzinfo=timezone.utc))
            expired = venues.collect(source(venues.SMITHVILLE), fetch,
                                     now=datetime(2026, 12, 5, 2, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["starts_at"].startswith("2026-12-04T18:00"))
        self.assertTrue(rows[0]["ends_at"].startswith("2026-12-04T20:00"))
        self.assertEqual(expired, [])


if __name__ == "__main__":
    unittest.main()
