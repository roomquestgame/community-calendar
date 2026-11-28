"""Definitive optional-probe misses differ from failures and denials."""
import json
import unittest

from roomquest.preview_worker import PreviewError
from roomquest.venue_calendar_locator import find_calendar
from roomquest.venue_discovery import discover


WEBSITE = "https://venue.example/"
LEAD = {"name": "Example Venue", "address": "123 Mainstreet, Boston, MA",
        "website": WEBSITE, "event_url": ""}
HOME = ('<h1>Example Venue</h1><p>123 Mainstreet, Boston, MA</p>'
        '<div class="tribe-events"></div>')
INDEX_PAGE = '<link rel="https://api.w.org/" href="https://venue.example/wp-json/">'
API_ROOT = "https://venue.example/wp-json/"
TEC_URL = API_ROOT + "tribe/events/v1/events"


class RoverProbeMissTests(unittest.TestCase):
    def test_missing_optional_tec_endpoint_allows_clean_miss_research(self):
        for reason in ("publisher_http_404", "publisher_http_410"):
            with self.subTest(reason=reason):
                requests, research_calls = [], []

                def fetch(url, accept, **options):
                    requests.append(url)
                    if url == WEBSITE:
                        return HOME
                    self.assertEqual(url, TEC_URL)
                    raise PreviewError(reason)

                def research(*args, **kwargs):
                    research_calls.append(args[0])
                    return {"status": "review", "reason": "rover_no_verified_selection"}

                result = discover(LEAD, fetch=fetch, research=research)
                self.assertEqual(result["p_reason"], "calendar_not_found")
                self.assertEqual(research_calls, [LEAD])
                self.assertEqual(requests, [WEBSITE, TEC_URL])

    def test_missing_advertised_api_index_is_a_definitive_miss(self):
        def missing(url, accept, **options):
            self.assertEqual(url, API_ROOT)
            raise PreviewError("publisher_http_404")

        self.assertEqual(find_calendar(
            INDEX_PAGE, WEBSITE + "events", "", missing, 999999999,
            strict_probe_errors=True), (None, "none"))

    def test_gone_advertised_tec_route_is_a_definitive_miss(self):
        requests = []

        def fetch(url, accept, **options):
            requests.append(url)
            if url == API_ROOT:
                return json.dumps({"namespaces": ["tribe/events/v1"], "routes": {
                    "/tribe/events/v1/events": {"methods": ["GET"]}}})
            self.assertEqual(url, TEC_URL)
            raise PreviewError("publisher_http_410")

        self.assertEqual(find_calendar(
            INDEX_PAGE, WEBSITE + "events", "", fetch, 999999999,
            strict_probe_errors=True), (None, "none"))
        self.assertEqual(requests, [API_ROOT, TEC_URL])

    def test_transient_optional_failure_does_not_trigger_research(self):
        for reason in ("publisher_http_503", "source_network_error",
                       "publisher_http_429"):
            with self.subTest(reason=reason):
                def fetch(url, accept, **options):
                    if url == WEBSITE:
                        return HOME
                    raise PreviewError(reason)

                def research(*args, **kwargs):
                    self.fail("a failed fetch is not a clean miss")

                with self.assertRaisesRegex(PreviewError, "^" + reason + "$"):
                    discover(LEAD, fetch=fetch, research=research)

    def test_optional_denial_does_not_trigger_research(self):
        def fetch(url, accept, **options):
            if url == WEBSITE:
                return HOME
            raise PreviewError("publisher_http_403")

        def research(*args, **kwargs):
            self.fail("publisher denial must not be retried with Rover")

        self.assertEqual(discover(LEAD, fetch=fetch, research=research)["p_reason"],
                         "calendar_access_denied")

    def test_missing_official_homepage_is_not_an_optional_probe_miss(self):
        def missing(*args, **kwargs):
            raise PreviewError("publisher_http_404")

        def research(*args, **kwargs):
            self.fail("missing official website cannot authorize Rover")

        with self.assertRaisesRegex(PreviewError, "^publisher_http_404$"):
            discover(LEAD, fetch=missing, research=research)
