"""Exercise the entrypoint Vercel actually instantiates, over local HTTP."""
import json
import os
from pathlib import Path
from http.server import HTTPServer
from threading import Thread
import tomllib
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.index import handler


class EntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.root = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, *, token=None, method="GET", body=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        req = Request(self.root + path, headers=headers, method=method, data=body)
        try:
            response = urlopen(req, timeout=2)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_config_selects_dispatcher_and_bounds_function(self):
        root = Path(__file__).parents[1]
        config = tomllib.loads((root / "pyproject.toml").read_text())
        self.assertEqual(config["tool"]["vercel"]["entrypoint"], "api.index:handler")
        self.assertEqual(json.loads((root / "vercel.json").read_text())["functions"]["api/index.py"]["maxDuration"], 60)

    def test_health_and_unknown_paths_never_execute_jobs(self):
        with patch("api.geocode.run_batch") as geocoder, patch("api.preview.collect_previews") as preview:
            code, health = self.request("/api/geocode")
            self.assertEqual(code, 200)
            self.assertEqual(health["service"], "roomquest-forward-geocoder")
            self.assertEqual(self.request("/api/preview")[0], 200)
            self.assertEqual(self.request("/api/unknown")[0], 404)
            self.assertEqual(self.request("/api/geocode?address=arbitrary")[0], 404)
            geocoder.assert_not_called()
            preview.assert_not_called()

    def test_both_geocoder_auth_methods_reach_real_handler(self):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-fixture", "ROOMQUEST_PREVIEW_SECRET": "manual-fixture"}), patch("api.geocode.run_batch", return_value={"attempted": 3}) as job:
            self.assertEqual(self.request("/api/geocode", token="wrong")[0], 401)
            self.assertEqual(self.request("/api/geocode", token="cron-fixture")[1], {"attempted": 3})
            self.assertEqual(self.request("/api/geocode", token="manual-fixture", method="POST")[0], 200)
            self.assertEqual(self.request("/api/geocode", token="manual-fixture", method="POST", body=b"{}")[0], 400)
            self.assertEqual(job.call_count, 2)

    def test_preview_cron_slots_keep_existing_behavior(self):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-fixture"}), patch("api.preview.collect_bulk_previews", return_value={"claimed": 2}) as bulk, patch("api.geocode.run_batch") as geocoder:
            for number in range(1, 6):
                self.assertEqual(self.request("/api/preview-" + str(number), token="cron-fixture")[1], {"claimed": 2})
            self.assertEqual(bulk.call_count, 5)
            geocoder.assert_not_called()
