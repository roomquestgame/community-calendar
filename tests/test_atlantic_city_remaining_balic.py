from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import unittest
from unittest.mock import Mock, patch

from roomquest import atlantic_city_remaining_balic as ac


NOW = datetime(2026, 11, 15, 0, 25, tzinfo=timezone.utc)
IMAGE = b"\xff\xd8\xffreviewed-balic-program\xff\xd9"
BODY = "Inside the tasting room, join Beth Tinnon bring your own snacks or visit their website for more information"


def source():
    return dict(source_key=ac.KEY, feed_url=ac.FEED, kind="html", platform_adapter="html", timezone=ac.ZONE)


def winery():
    return (f'<meta property="og:url" content="{ac.FEED}">'
            '<div><h2>Save the Dates</h2>'
            f'<div><img src="{escape(ac.POSTER_URL, quote=True)}"></div>'
            '<div class="paragraph">Live Music November 21, 22, 27, 28, &amp; 29th</div>'
            '<div class="paragraph">For more information please call us at 609 625 2166</div>'
            f'<div><img src="{escape(ac.TERRACE_IMAGE, quote=True)}"></div></div>'
            '<footer>Route 40 (6623 Harding Hwy) Mays Landing, NJ 08330</footer>')


def bitter(line="11/27 Friday Balic Winery 1pm to 5pm", year=2026):
    return (f'<meta property="og:url" content="{ac.BITTER_URL}">'
            f'<link rel="canonical" href="{ac.BITTER_URL}">'
            f'<h1>BITTERSWEET DUO SCHEDULE {year}</h1><p>{escape(line)}</p>')


def beth(body=BODY, *, start="2026-11-28T13:00:00", end="2026-11-28T17:00:00",
         visible_start="1:00PM", visible_end="5:00PM", json_body=None):
    event = dict(**{"@type": "MusicEvent"}, name=ac.BETH_TITLE, url=ac.BETH_URL,
                 startDate=start, description=body if json_body is None else json_body,
                 location={"@type": "Place", "name": "Balic Winery",
                           "address": "6623 Harding Hwy, Mays Landing, NJ, US"})
    if end is not None:
        event["endDate"] = end
    end_markup = f'<time class="to"><span class="time">{visible_end}</span></time>' if visible_end else ""
    return (f'<meta property="og:url" content="{ac.BETH_URL}">'
            f'<script type="application/ld+json">{json.dumps(event)}</script>'
            f'<h2 class="event-title"><a href="{ac.BETH_URL}">{ac.BETH_TITLE}</a></h2>'
            '<span class="date-long"><time class="from"><span class="date">Saturday, November 28</span>'
            f'<span class="time">{visible_start}</span></time>{end_markup}</span>'
            f'<div class="event-notes"><p>{escape(body)}</p></div>')


def pages():
    return {ac.FEED: winery(), ac.POSTER_URL: IMAGE, ac.BITTER_URL: bitter(), ac.BETH_URL: beth()}


def raw_record(title, start, end, venue, street, city, url, identity, category="", **kwargs):
    return dict(id=identity, title=title, starts_at=start, ends_at=end,
                venue_name=venue, venue_address=street, venue_city=city,
                event_url=url, category=category, lat=kwargs.get("lat"), lng=kwargs.get("lng"))


class BalicTests(unittest.TestCase):
    def run_collect(self, data=None, now=NOW):
        data = pages() if data is None else data
        fetch = Mock(side_effect=lambda url, accept: data[url])
        with patch.object(ac, "POSTER_SHA256", sha256(IMAGE).hexdigest()), \
                patch.object(ac, "record", side_effect=raw_record) as recorded:
            rows = ac.collect(source(), fetch, now=now)
        return rows, fetch, recorded

    def test_two_verified_performances_keep_entire_flyer_and_native_bodies(self):
        rows, fetch, recorded = self.run_collect()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["starts_at"] for r in rows], ["2026-11-27T13:00:00-05:00", "2026-11-28T13:00:00-05:00"])
        self.assertEqual([r["ends_at"] for r in rows], ["2026-11-27T17:00:00-05:00", "2026-11-28T17:00:00-05:00"])
        self.assertTrue(rows[0]["description"].endswith("11/27 Friday Balic Winery 1pm to 5pm"))
        self.assertTrue(rows[1]["description"].endswith(BODY))
        for row in rows:
            self.assertTrue(row["description"].startswith(ac.POSTER_TEXT + "\n\n"))
            self.assertIn("For more information please call us at 609 625 2166", row["description"])
            self.assertEqual(row["venue_address"], "6623 Harding Hwy, Mays Landing, NJ 08330")
            self.assertEqual((row["lat"], row["lng"]), (39.460896000003, -74.791057500001))
            self.assertEqual(row["category"], "")
            self.assertRegex(row["id"], r"^[a-f0-9]{64}$")
            self.assertEqual(row["image_url"], ac.POSTER_URL)
        self.assertTrue(all(c.kwargs["retain_until_end"] for c in recorded.call_args_list))
        self.assertEqual(len(fetch.call_args_list), 4)
        self.assertEqual(fetch.call_args_list[1].args, (ac.POSTER_URL, "image/jpeg"))
        self.assertEqual(len({r["id"] for r in rows}), 2)
        self.assertEqual({h["date"] for h in ac.HELD_OCCURRENCES}, {"2026-11-21", "2026-11-22", "2026-11-29"})

    def test_changed_poster_bytes_fail_before_any_rows(self):
        data = pages()
        data[ac.POSTER_URL] += b"changed edition"
        with patch.object(ac, "POSTER_SHA256", sha256(IMAGE).hexdigest()), patch.object(ac, "record") as recorded:
            with self.assertRaisesRegex(ValueError, "poster_edition_changed"):
                ac.collect(source(), lambda u, a: data[u], now=NOW)
            recorded.assert_not_called()

    def test_changed_program_image_manifest_requires_review(self):
        for replacement in [ac.POSTER_URL.replace("2026", "2027"), "https://example.org/new-program.jpg"]:
            with self.subTest(replacement=replacement):
                data = pages()
                data[ac.FEED] = data[ac.FEED].replace(escape(ac.POSTER_URL, quote=True), replacement)
                with self.assertRaisesRegex(ValueError, "manifest_changed"):
                    self.run_collect(data)

    def test_missing_performer_time_cannot_fall_back_to_opening_hours(self):
        data = pages()
        data[ac.BITTER_URL] = bitter("11/27 Friday Balic Winery")
        data[ac.FEED] += "<p>Open Monday to Saturday 9AM to 8PM</p>"
        with self.assertRaisesRegex(ValueError, "performer_clock_changed"):
            self.run_collect(data)

    def test_current_year_and_venue_are_part_of_performer_identity(self):
        data = pages()
        data[ac.BITTER_URL] = bitter(year=2025)
        with self.assertRaisesRegex(ValueError, "performer_year_changed"):
            self.run_collect(data)
        data[ac.BITTER_URL] = bitter()
        data[ac.BETH_URL] = beth().replace("6623 Harding Hwy", "6625 Harding Hwy")
        with self.assertRaisesRegex(ValueError, "performer_identity_changed"):
            self.run_collect(data)

    def test_conflicting_visible_time_is_rejected(self):
        data = pages()
        data[ac.BETH_URL] = beth(visible_start="2:00PM")
        with self.assertRaisesRegex(ValueError, "performer_clock_conflict"):
            self.run_collect(data)

    def test_jsonld_excerpt_does_not_replace_long_native_description(self):
        body = "Complete native program details <not an HTML tag> & more. " * 100 + "Final publisher instruction."
        data = pages()
        data[ac.BETH_URL] = beth(body=body)
        rows, _, _ = self.run_collect(data)
        self.assertTrue(rows[1]["description"].endswith(body))
        self.assertGreater(len(rows[1]["description"]), 5_000)
        data[ac.BETH_URL] = beth(body=body, json_body=BODY)
        with self.assertRaisesRegex(ValueError, "description_conflict"):
            self.run_collect(data)

    def test_oversize_and_blank_native_descriptions_are_not_clipped_or_filled(self):
        for body in ["", "a" * 11_900]:
            with self.subTest(length=len(body)):
                data = pages()
                data[ac.BETH_URL] = beth(body=body)
                with self.assertRaises(ValueError):
                    self.run_collect(data)

    def test_unknown_end_remains_unknown_but_start_still_must_match(self):
        data = pages()
        data[ac.BETH_URL] = beth(end=None, visible_end=None)
        rows, _, _ = self.run_collect(data)
        self.assertIsNone(rows[1]["ends_at"])
        data[ac.BETH_URL] = beth(end=None, visible_end=None, visible_start="2:00PM")
        with self.assertRaisesRegex(ValueError, "clock_conflict"):
            self.run_collect(data)

    def test_last_fifteen_minutes_retained_without_future_projection(self):
        rows, _, _ = self.run_collect(now=datetime(2026, 11, 28, 21, 45, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], ac.BETH_TITLE)
        rows, _, _ = self.run_collect(now=datetime(2026, 11, 28, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(rows, [])
        rows, _, _ = self.run_collect(now=datetime(2026, 9, 28, 17, 59, tzinfo=timezone.utc))
        self.assertEqual(rows, [])

    def test_cancelled_or_private_edition_requires_review(self):
        data = pages()
        data[ac.BETH_URL] = beth(body=BODY + " This event is cancelled.")
        with self.assertRaisesRegex(ValueError, "eligibility_changed"):
            self.run_collect(data)
        data = pages()
        data[ac.FEED] = data[ac.FEED].replace("For more information", "All holiday galas are postponed. For more information")
        with self.assertRaisesRegex(ValueError, "program_eligibility_changed"):
            self.run_collect(data)

    def test_source_identity_and_point_are_exact(self):
        fetch = Mock()
        altered = source()
        altered["feed_url"] = "https://www.balicwinery.com/locations.html"
        with self.assertRaisesRegex(ValueError, "source_identity"):
            ac.collect(altered, fetch, now=NOW)
        fetch.assert_not_called()
        self.assertIsNone(ac.reviewed_venue_location(ac.KEY, ac.VENUE, "6625 Harding Hwy, Mays Landing, NJ 08330"))
        self.assertIsNone(ac.reviewed_venue_location(ac.KEY, "Another venue", ac.STREET))
        self.assertIsNone(ac.reviewed_venue_location("other_source", ac.VENUE, ac.STREET))
        self.assertFalse(ac.event_url(ac.KEY, ac.BITTER_URL))
        self.assertFalse(ac.event_url(ac.KEY, ac.FEED + "?old=1"))

    def test_deadline_prevents_additional_http(self):
        fetch = Mock()
        with patch.object(ac, "monotonic", return_value=10):
            with self.assertRaisesRegex(ValueError, "collection_deadline"):
                ac.collect(source(), fetch, now=NOW, deadline_at=11)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
