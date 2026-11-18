"""Ensure the real bounded preview dispatcher uses exact source and safe transport."""
import unittest
from time import monotonic
from unittest.mock import patch

from roomquest import preview_worker, bibliocommons_rss
from test_bibliocommons_rss import PROFILE, make_item, document, sample_record


class BiblioRssPreviewIntegrationTests(unittest.TestCase):
    def test_source_scoped_preview_fetch_and_publication_stays_outside_collector(self):
        calls = []
        def fetched(url, accept, **kwargs):
            calls.append((url, accept, kwargs))
            return document([make_item()])
        with patch.object(preview_worker, "fetch_publisher", side_effect=fetched):
            with patch.object(bibliocommons_rss, "record", side_effect=sample_record):
                result = preview_worker.preview_source(PROFILE, deadline_at=monotonic()+25)
        self.assertEqual(result["p_future_count"], 1)
        self.assertEqual(result["p_venue_count"], 1)
        self.assertEqual(result["p_source_key"], PROFILE["source_key"])
        self.assertEqual(len(result["p_events"]), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], PROFILE["feed_url"]+"?page=1")
        self.assertEqual(calls[0][1], "application/rss+xml")
        self.assertIs(calls[0][2]["respect_robots"], True)
        self.assertEqual(calls[0][2]["allowed_hosts"], ("gateway.bibliocommons.com",))
        self.assertNotIn("image_url", result["p_events"][0])
        self.assertNotIn("image_candidate_url", result["p_events"][0])
        self.assertNotIn("p_publish", result)

    def test_mismatched_source_url_fails_before_publisher_request(self):
        with patch.object(preview_worker, "fetch_publisher", side_effect=AssertionError("network not permitted")):
            with self.assertRaisesRegex(preview_worker.PreviewError, "unregistered_bibliocommons_rss_source"):
                preview_worker.preview_source({**PROFILE,"feed_url":"https://example.org"}, deadline_at=monotonic()+25)


if __name__ == "__main__":
    unittest.main()
