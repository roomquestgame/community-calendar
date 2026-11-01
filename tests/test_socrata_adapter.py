"""Socrata transport and mapping tests using a retained NYC source record.

The fixture is a subset of the real publisher response retained in the main
repository's discover-events/fixtures/nyc-parks-2026-10-25.json, not fallback
event data. No live network, source activation, or geocoding occurs here.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from roomquest import mapsee_adapter, socrata_adapter

ROW = json.loads((Path(__file__).parent / "fixtures/socrata-nyc-source.json").read_text())
PROFILE = {"type": "opendata", "config": {
    "timezone": "America/New_York",
    "map": {"id": "guid", "title": "title", "start": "starttime", "end": "endtime",
            "venue": "location", "latlon": "coordinates", "url": "link"},
    "where": "endtime >= '{now}'", "order": "starttime, guid",
}}
BASE = "https://data.cityofnewyork.us/resource/w3wp-dpdi.json"


class SocrataTests(unittest.TestCase):
    def test_page_preserves_timezone_filters_and_pagination(self):
        url = socrata_adapter.page_url(BASE, PROFILE["config"], 2,
                                       datetime(2026, 10, 25, 12, tzinfo=timezone.utc))
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["$limit"], ["500"])
        self.assertEqual(query["$offset"], ["500"])
        self.assertEqual(query["$where"], ["endtime >= '2026-10-25T08:00:00'"])
        self.assertEqual(query["$order"], ["starttime, guid"])

    def test_mapping_keeps_publisher_fields_and_common_record_gate(self):
        calls = []
        def capture(*args):
            calls.append(args)
            return {"id": args[7], "title": args[0], "starts_at": args[1],
                    "venue_name": args[3], "venue_address": args[4], "lat": args[9], "lng": args[10]}
        with patch.object(mapsee_adapter, "record", capture):
            rows = mapsee_adapter.parse_open_data([ROW], {**PROFILE["config"], "publisher_url": BASE})
        self.assertEqual(rows[0]["id"], "2095183")
        self.assertEqual(calls[0][6], ROW["link"])
        self.assertEqual(calls[0][9:11], ("40.50260162353500000", "-74.25180053710900000"))
        self.assertEqual(calls[0][11], "America/New_York")

    def test_existing_mapsee_dispatch_calls_shared_socrata_mapping(self):
        def capture(*args):
            return {"id": args[7], "title": args[0], "starts_at": args[1],
                    "venue_name": args[3], "venue_address": args[4], "lat": args[9], "lng": args[10]}
        urls = []
        def fetch(url, accept):
            urls.append((url, accept))
            return json.dumps([ROW])
        with patch.object(mapsee_adapter, "record", capture):
            result = mapsee_adapter.collect({"feed_url": BASE}, PROFILE, fetch)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "2095183")
        self.assertEqual(len(urls), 1)
        self.assertEqual(parse_qs(urlsplit(urls[0][0]).query)["$limit"], ["500"])

    def test_invalid_shapes_remain_errors(self):
        with self.assertRaisesRegex(ValueError, "unsupported_open_data_payload"):
            socrata_adapter.parse_open_data({}, PROFILE["config"], lambda *args: None)
        with self.assertRaisesRegex(ValueError, "unsupported_open_data_mapping"):
            socrata_adapter.parse_open_data([], {"map": {}}, lambda *args: None)


if __name__ == "__main__":
    unittest.main()
