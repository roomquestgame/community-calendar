"""Contract regression: never expose a Supabase service key to the Python collector."""
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from api.preview import handler
from roomquest.preview_worker import PreviewError, ROOMQUEST_DB, supabase_rpc


class ScopedSupabaseTests(unittest.TestCase):
    def test_only_two_preview_rpcs_can_be_invoked(self):
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
