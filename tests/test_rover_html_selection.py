"""Selected publisher pages retain ordinary registration scope guards."""
import unittest

from roomquest.rover import inspect_selection
from roomquest.venue_calendar_locator import find_calendar


LISTING = """<main><h1>Upcoming events</h1>
<a href="/events/alpha">Alpha</a><time datetime="2026-12-01">December 1</time>
<a href="/events/bravo">Bravo</a><time datetime="2026-12-02">December 2</time>
<a href="/events/charlie">Charlie</a><time datetime="2026-12-03">December 3</time>
</main>"""


class RoverHtmlSelectionTests(unittest.TestCase):
    def inspect(self, selected_url, html=LISTING, website="https://venue.example/"):
        calls = []

        def fetch(url, accept, **options):
            calls.append(url)
            self.assertEqual(url, selected_url)
            self.assertTrue(options["respect_robots"])
            self.assertEqual(options["allowed_hosts"], ("venue.example",))
            return html

        answer = inspect_selection(website, "", {
            "url": selected_url, "status": "needs_independent_validation"},
            fetch=fetch, deadline=999999999)
        return answer, calls

    def test_selected_unconventional_path_uses_real_collection_evidence(self):
        url = "https://venue.example/program"
        answer, calls = self.inspect(url)
        self.assertEqual(answer, {"status": "candidate", "url": url,
                                  "kind": "html_listing"})
        self.assertEqual(calls, [url])

    def test_ordinary_locator_keeps_its_existing_base_rules(self):
        def no_fetch(*args, **kwargs):
            self.fail("fixture needs no network")
        self.assertEqual(find_calendar(
            LISTING, "https://venue.example/program", "", no_fetch, 999999999),
            (None, "none"))

    def test_selected_homepage_is_not_promoted_from_event_highlights(self):
        answer, calls = self.inspect("https://venue.example/")
        self.assertEqual(answer, {"status": "review", "reason": "calendar_not_verified"})
        self.assertEqual(len(calls), 1)

    def test_selected_single_event_with_related_events_is_not_a_collection(self):
        answer, _ = self.inspect("https://venue.example/events/alpha")
        self.assertEqual(answer, {"status": "review", "reason": "calendar_not_verified"})

    def test_selected_page_preserves_query_scope(self):
        url = "https://venue.example/program?venue=west"
        answer, calls = self.inspect(url, website="https://venue.example/?venue=west")
        self.assertEqual(answer, {"status": "candidate", "url": url,
                                  "kind": "html_listing"})
        self.assertEqual(calls, [url])

    def test_selected_page_losing_query_scope_is_never_fetched(self):
        answer, calls = self.inspect("https://venue.example/program",
                                    website="https://venue.example/?venue=west")
        self.assertEqual(answer, {"status": "review", "reason": "invalid_selection"})
        self.assertEqual(calls, [])

    def test_multiple_subscriptions_remain_ambiguous(self):
        html = LISTING + ('<a href="/first.ics">Subscribe to calendar</a>'
                          '<a href="/second.ics">Subscribe to calendar</a>')
        answer, calls = self.inspect("https://venue.example/program", html)
        self.assertEqual(answer, {"status": "review", "reason": "calendar_not_verified"})
        self.assertEqual(len(calls), 1)

    def test_multiple_linked_calendars_remain_ambiguous(self):
        html = LISTING + ('<a href="/calendar">Calendar</a>'
                          '<a href="/shows">Shows</a>')
        answer, calls = self.inspect("https://venue.example/program", html)
        self.assertEqual(answer, {"status": "review", "reason": "calendar_not_verified"})
        self.assertEqual(len(calls), 1)
