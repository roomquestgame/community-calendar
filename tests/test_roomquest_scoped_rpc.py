"""Contract regression: never expose a Supabase service key to the Python collector."""
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from api.preview import handler
from roomquest.preview_worker import PreviewError, ROOMQUEST_DB, supabase_rpc, collect_previews


class ScopedSupabaseTests(unittest.TestCase):
    def test_only_scoped_private_collection_rpcs_can_be_invoked(self):
        with self.assertRaisesRegex(PreviewError, "unsupported_collector_rpc"):
            supabase_rpc("store_approved_municipal_events", {})
        with self.assertRaisesRegex(PreviewError, "unsupported_collector_rpc"):
            supabase_rpc("community_source_review", {})

    def test_missing_credentials_fail_closed(self):
        with patch.dict(os.environ, {"SUPABASE_URL": ROOMQUEST_DB,
                                    "SUPABASE_PUBLISHABLE_KEY": "",
                                    "ROOMQUEST_COLLECTOR_TOKEN": ""}):
            with self.assertRaisesRegex(PreviewError, "collector_not_configured"):
                supabase_rpc("community_collector_claim_previews", {})

    def test_rpc_uses_project_publishable_key_plus_scoped_token(self):
        env = {
            "SUPABASE_URL": ROOMQUEST_DB,
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fixture",
            "ROOMQUEST_COLLECTOR_TOKEN": "a" * 64,
        }
        class Response(io.BytesIO):
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()
        with patch.dict(os.environ, env), patch(
            "urllib.request.urlopen", return_value=Response(b"[]")
        ) as mock_url:
            result = supabase_rpc("community_collector_claim_previews", {"p_limit": 2})
        self.assertEqual(result, [])
        request = mock_url.call_args.args[0]
        self.assertEqual(request.full_url, ROOMQUEST_DB + "/rest/v1/rpc/community_collector_claim_previews")
        self.assertEqual(request.headers.get("Apikey"), "sb_publishable_fixture")
        self.assertFalse(any(name.lower() == "authorization" for name in request.headers))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["p_token"], "a" * 64)
        self.assertEqual(body["p_limit"], 2)


    def test_successful_preview_also_stages_event_metadata(self):
        from unittest.mock import call
        from datetime import datetime, timedelta, timezone
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        rows = [{"id": "fixture1", "title": "Park Cleanup", "starts_at": tomorrow,
                 "venue_name": "Fixture Park", "lat": 35.7, "lng": -78.5}]
        source = {"source_key": "municipal_fixture"}
        preview = {"p_source_key": source["source_key"], "p_samples": rows,
                   "p_events": rows, "p_future_count": 1,
                   "p_venue_count": 1, "p_error": None}
        with patch("roomquest.preview_worker.preview_source", return_value=preview), patch(
                "roomquest.preview_worker.supabase_rpc", side_effect=[[source], 1, None]
        ) as mocked:
            result = collect_previews()
        self.assertEqual(result, {"claimed": 1, "complete": 1, "failed": 0, "staged": 1})
        self.assertEqual(mocked.call_args_list, [
            call("community_collector_claim_previews", {"p_limit": 4}),
            call("community_collector_record_staged_events", {
                "p_source_key": source["source_key"], "p_events": rows
            }),
            call("community_collector_record_preview", {
                "p_source_key": source["source_key"], "p_samples": rows,
                "p_future_count": 1, "p_venue_count": 1, "p_error": None
            }),
        ])

    def test_staging_error_marks_preview_failed_without_publication(self):
        source = {"source_key": "municipal_fixture"}
        preview = {"p_source_key": "municipal_fixture", "p_samples": [],
                   "p_events": [], "p_future_count": 0,
                   "p_venue_count": 0, "p_error": None}
        def fake_rpc(name, payload):
            if name == "community_collector_claim_previews":
                return [source]
            if name == "community_collector_record_staged_events":
                raise PreviewError("database_unavailable")
            self.assertEqual(name, "community_collector_record_preview")
            self.assertEqual(payload["p_error"], "database_unavailable")
            return None
        with patch("roomquest.preview_worker.preview_source", return_value=preview), patch(
                "roomquest.preview_worker.supabase_rpc", side_effect=fake_rpc
        ):
            result = collect_previews()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["complete"], 0)

    def test_hourly_cron_requires_secret_while_health_remains_safe(self):
        fake = handler.__new__(handler)
        fake.path = "/api/preview"
        fake.headers = {}
        fake.reply = MagicMock()
        fake.batch = MagicMock()
        with patch.dict(os.environ, {"CRON_SECRET": "c" * 64}):
            fake.do_GET()
            fake.batch.assert_not_called()
            fake.reply.assert_called_once()
            fake.reply.reset_mock()
            fake.headers = {"Authorization": "Bearer " + "c" * 64}
            fake.do_GET()
            fake.batch.assert_called_once()
            fake.batch.reset_mock()
            fake.headers = {"Authorization": "Bearer bad"}
            fake.do_GET()
            fake.batch.assert_not_called()
            self.assertEqual(fake.reply.call_args.args[0], 401)

    def test_five_workers_have_authenticated_fifteen_source_cap(self):
        from pathlib import Path
        from roomquest.preview_worker import collect_bulk_previews
        settings = json.loads((Path(__file__).parents[1] / "vercel.json").read_text())
        paths = [job["path"] for job in settings["crons"] if job["path"].startswith("/api/preview-")]
        self.assertEqual(paths, [f"/api/preview-{i}" for i in range(1, 6)])
        self.assertTrue(all(job["schedule"] == "*/15 * * * *"
                            for job in settings["crons"] if job["path"].startswith("/api/preview-")))
        self.assertEqual(len(paths) * 15, 75)
        for path in paths:
            fake = handler.__new__(handler)
            fake.path = path
            fake.headers = {"Authorization": "Bearer " + "c" * 64}
            fake.reply = MagicMock()
            with patch.dict(os.environ, {"CRON_SECRET": "c" * 64}), patch(
                "api.preview.collect_bulk_previews", return_value={"claimed": 0}
            ) as bulk:
                fake.do_GET()
                bulk.assert_called_once_with(max_sources=15)
                self.assertEqual(fake.reply.call_args.args[0], 200)
        with patch("roomquest.preview_worker.supabase_rpc", return_value=[]) as rpc:
            self.assertEqual(collect_bulk_previews(), {
                "claimed": 0, "complete": 0, "failed": 0, "staged": 0
            })
            rpc.assert_called_once_with("community_collector_claim_previews",
                                        {"p_limit": 3})

    def test_bulk_worker_handles_fifteen_sources_as_five_claims(self):
        from roomquest.preview_worker import collect_bulk_previews
        source_rows = [
            [{"source_key": f"test_{round_no}_{i}"} for i in range(3)]
            for round_no in range(5)
        ]
        with patch("roomquest.preview_worker.supabase_rpc", side_effect=source_rows) as rpc, patch(
            "roomquest.preview_worker._process_claimed_source",
            return_value={"complete": 1, "failed": 0, "staged": 2}
        ):
            result = collect_bulk_previews()
        self.assertEqual(result, {"claimed": 15, "complete": 15,
                                  "failed": 0, "staged": 30})
        self.assertEqual(rpc.call_count, 5)

    def test_manual_post_rejects_wrong_operator_token(self):
        fake = handler.__new__(handler)
        fake.path = "/api/preview"
        fake.headers = {"Authorization": "Bearer wrong", "Content-Length": "0"}
        fake.reply = MagicMock()
        fake.batch = MagicMock()
        with patch.dict(os.environ, {"ROOMQUEST_PREVIEW_SECRET": "p" * 64}):
            fake.do_POST()
        fake.batch.assert_not_called()
        self.assertEqual(fake.reply.call_args.args[0], 401)


if __name__ == "__main__":
    unittest.main()

