"""Gainesville Theatre Alliance actual official performance-clock evidence."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from roomquest.gainesville_theatre_ga import KEY, URL, DETAIL, ZONE, parse, collect, event_url

NOW = datetime(2026, 11, 19, 20, tzinfo=timezone.utc)
INDEX = """<link rel="canonical" href="https://www.gainesvilletheatrealliance.org/2026-2027-season"/>
<h1>2026-2027 Season</h1><a href="/pride-prejudice-2027">Pride &amp; Prejudice</a>
<h3>FEBRUARY 12 – 20, 2027</h3><p>Alice by Heart April 9-17, 2027</p>"""
DETAIL_HTML = """<link rel="canonical" href="https://www.gainesvilletheatrealliance.org/pride-prejudice-2027"/>
<meta property="og:title" content="Pride &amp; Prejudice — Gainesville Theatre Alliance"/>
<h1>Pride &amp; Prejudice</h1><p>February 12 – 20, 2027</p>
<p>Brenau University’s Hosch Theatre<br>429 Academy St NE<br>Gainesville, GA 30501</p>
<h2>ABOUT THE SHOW</h2>
<p>Elizabeth Bennet’s wit and independence collide with Darcy’s pride in this lively stage adaptation.</p>
<h2>SPECIAL EVENTS</h2><h3>Opening Night Reception</h3>
<p>following the Friday, Feb 12, 7:30 PM performance</p>"""
SRC = {"source_key":KEY, "feed_url":URL, "kind":"html", "platform_adapter":"html", "timezone":ZONE}


class GTAOfficialCalendarTests(unittest.TestCase):
    def test_original_publisher_clock_and_full_venue(self):
        rows = parse(INDEX, DETAIL_HTML, now=NOW)
        self.assertEqual(len(rows), 1)
        x = rows[0]
        self.assertEqual(x["event_url"], DETAIL)
        self.assertEqual(x["venue_address"], "429 Academy St NE, Gainesville, GA 30501")
        self.assertEqual(x["timezone"], ZONE)
        self.assertIn("2027-02-13T00:30:00+00:00", x["starts_at"])
        self.assertIsNone(x.get("ends_at"))
        self.assertIn("Elizabeth Bennet", x["description"])
        self.assertIsNone(x.get("lat"))
        self.assertIsNone(x.get("lng"))

    def test_run_dates_do_not_invent_daily_show_times(self):
        self.assertEqual(len(parse(INDEX, DETAIL_HTML, now=NOW)), 1)
        self.assertEqual(parse(INDEX, DETAIL_HTML.replace("7:30 PM performance", "reception follows"), now=NOW), [])
        self.assertEqual(parse(INDEX.replace("FEBRUARY 12 – 20, 2027", "APRIL 9 – 17, 2027"), DETAIL_HTML, now=NOW), [])
        self.assertEqual(parse(INDEX, DETAIL_HTML, now=datetime(2027, 2, 13, tzinfo=timezone.utc)), [])

    def test_changed_season_identity_and_venue_held(self):
        self.assertEqual(parse(INDEX.replace('href="/pride-prejudice-2027"', 'href="/alice-2027"'),
                               DETAIL_HTML, now=NOW), [])
        self.assertEqual(parse(INDEX, DETAIL_HTML.replace("429 Academy St NE", "Location TBD"), now=NOW), [])
        self.assertEqual(parse(INDEX, DETAIL_HTML.replace("Gainesville, GA 30501", "Dahlonega, GA 30533"), now=NOW), [])
        with self.assertRaisesRegex(ValueError, "canonical_changed"):
            parse(INDEX, DETAIL_HTML.replace('pride-prejudice-2027"/>', 'alice-2027"/>'), now=NOW)

    def test_event_link_and_registered_profile(self):
        self.assertTrue(event_url(DETAIL))
        for url in ("http://www.gainesvilletheatrealliance.org/pride-prejudice-2027",
                    DETAIL + "?redirect=1", "https://elsewhere.example/pride-prejudice-2027"):
            self.assertFalse(event_url(url))
        with self.assertRaisesRegex(ValueError,"unregistered_gta_source"):
            collect({**SRC, "timezone":"UTC"},lambda u,a: INDEX,now=NOW)

    def test_preview_dispatch_robots_safe_first_party_only(self):
        from roomquest.preview_worker import preview_source
        calls=[]
        def publisher(url, accept, **kwargs):
            calls.append((url,kwargs))
            if url==URL:return INDEX
            if url==DETAIL:return DETAIL_HTML
            raise AssertionError("unexpected network host or path")
        # This is a fixture-based dispatcher test; separate live robot-aware
        # publisher preview must pass before source DB enrollment.
        with patch("roomquest.preview_worker.fetch_publisher",side_effect=publisher):
            got=preview_source(SRC)
        self.assertEqual(got["p_future_count"],1)
        self.assertEqual([u for u,k in calls],[URL,DETAIL])
        self.assertTrue(all(k.get("respect_robots") is True for u,k in calls))
        self.assertTrue(all(k.get("allowed_hosts")==("www.gainesvilletheatrealliance.org",) for u,k in calls))


if __name__=="__main__":
    unittest.main()
