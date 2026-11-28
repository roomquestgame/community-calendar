"""Rover admission uses the real collector RPC boundary and authentication."""
import io
import json
import os
import unittest
from unittest.mock import patch
import urllib.request

from roomquest.preview_worker import PreviewError, ROOMQUEST_DB, supabase_rpc


class RoverRpcTests(unittest.TestCase):
    def test_admission_rpc_uses_collector_credentials(self):
        token = "a" * 64
        ticket = "398adf59-2255-4351-8972-8f507a10b305"
        permit = "8d0e4d60-e3ad-4556-96fd-91045b6cfbc7"
        env = {"SUPABASE_URL": ROOMQUEST_DB,
               "SUPABASE_PUBLISHABLE_KEY": "fixture-publishable-key",
               "ROOMQUEST_COLLECTOR_TOKEN": token}

        def open_rpc(request, *, timeout):
            self.assertEqual(request.full_url, ROOMQUEST_DB +
                             "/rest/v1/rpc/community_collector_admit_rover_calendar")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Apikey"), "fixture-publishable-key")
            self.assertEqual(json.loads(request.data), {
                "p_token": token, "p_ticket": ticket,
                "p_model": "anthropic/fixture"})
            self.assertEqual(timeout, 4)
            return io.BytesIO(json.dumps({"permit_id": permit}).encode())

        with patch.dict(os.environ, env, clear=True), patch.object(
                urllib.request, "urlopen", side_effect=open_rpc) as request:
            result = supabase_rpc("community_collector_admit_rover_calendar", {
                "p_ticket": ticket, "p_model": "anthropic/fixture"}, timeout=4)
        self.assertEqual(result, {"permit_id": permit})
        request.assert_called_once()

    def test_unknown_rpc_is_rejected_before_network(self):
        with patch.object(urllib.request, "urlopen") as request:
            with self.assertRaisesRegex(PreviewError, "^unsupported_collector_rpc$"):
                supabase_rpc("community_collector_admit_rover_calendar_extra", {})
        request.assert_not_called()

    def test_admission_still_requires_collector_configuration(self):
        env = {"SUPABASE_URL": ROOMQUEST_DB,
               "SUPABASE_PUBLISHABLE_KEY": "fixture-publishable-key"}
        with patch.dict(os.environ, env, clear=True), patch.object(
                urllib.request, "urlopen") as request:
            with self.assertRaisesRegex(PreviewError, "^collector_not_configured$"):
                supabase_rpc("community_collector_admit_rover_calendar", {})
        request.assert_not_called()
