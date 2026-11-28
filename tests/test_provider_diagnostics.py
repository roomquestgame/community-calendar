"""Bounded provider diagnostics never expose response messages or credentials."""
from contextlib import redirect_stdout
import io
import json
from time import monotonic
import unittest
from unittest.mock import patch

from roomquest import venue_research
from roomquest.rover import research_clean_miss


class Response:
    def __init__(self, status, body, *, on_chunk=None, on_enter=None):
        self.status_code = status
        self.body = body
        self.on_chunk = on_chunk
        self.on_enter = on_enter
        self.bytes_yielded = 0
        self.body_iterations = 0

    def __enter__(self):
        if self.on_enter:
            self.on_enter()
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        self.body_iterations += 1
        for offset in range(0, len(self.body), chunk_size):
            chunk = self.body[offset:offset + chunk_size]
            self.bytes_yielded += len(chunk)
            if self.on_chunk:
                self.on_chunk()
            yield chunk


class ProviderDiagnosticsTests(unittest.TestCase):
    def request(self, response, *, max_body=16384, clock=lambda: 0):
        with patch.object(venue_research.requests, "post", return_value=response) as post:
            try:
                return venue_research.bounded_json(
                    "https://ai-gateway.vercel.sh/v1/messages",
                    {"Authorization": "Bearer fixture-token"}, {"fixture": True},
                    deadline_at=10, max_body=max_body, timeout=5, clock=clock)
            finally:
                post.assert_called_once()
                self.assertFalse(post.call_args.kwargs["allow_redirects"])
                self.assertTrue(post.call_args.kwargs["stream"])
                self.assertEqual(post.call_args.kwargs["timeout"], 5)

    def test_known_error_retains_only_status_and_allowlisted_code(self):
        response = Response(403, json.dumps({"error": {
            "type": "customer_verification_required",
            "message": "SECRET provider text",
            "action": "https://example.invalid/?credential=SECRET"}}).encode())
        with self.assertRaises(venue_research.ProviderError) as caught:
            self.request(response)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(str(caught.exception), "provider_unavailable")
        self.assertEqual(caught.exception.safe_details(), {
            "status": 403, "code": "customer_verification_required"})
        self.assertNotIn("SECRET", repr(caught.exception.__dict__))

    def test_documented_top_level_error_retains_only_allowlisted_code(self):
        response = Response(403, json.dumps({
            "error": "SECRET team or provider restriction details",
            "type": "no_providers_available", "statusCode": 403}).encode())
        with self.assertRaises(venue_research.ProviderError) as caught:
            self.request(response)
        self.assertEqual(caught.exception.safe_details(), {
            "status": 403, "code": "no_providers_available"})
        self.assertNotIn("SECRET", repr(caught.exception.__dict__))

    def test_unknown_malformed_or_nonobject_errors_are_unclassified(self):
        bodies = (b'{"error":{"type":"SECRET malicious"}}', b"not json",
                  b'{"error":{"code":["access_denied"]}}', b"[]",
                  b'{"error":"SECRET", "type":"SECRET unknown"}')
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(venue_research.ProviderError) as caught:
                    self.request(Response(403, body))
                self.assertEqual(caught.exception.safe_details(), {
                    "status": 403, "code": "unclassified"})

    def test_error_body_read_stays_below_existing_and_diagnostic_caps(self):
        for bound in (128, 16384):
            with self.subTest(bound=bound):
                response = Response(403, b"x" * 20000)
                with self.assertRaises(venue_research.ProviderError) as caught:
                    self.request(response, max_body=bound)
                self.assertLessEqual(response.bytes_yielded, min(4096, bound))
                self.assertEqual(caught.exception.code, "unclassified")

    def test_error_envelope_read_respects_deadline(self):
        expired = [False]
        response = Response(403, b'{"error":{"type":"access_denied"}}',
                            on_chunk=lambda: expired.__setitem__(0, True))
        with self.assertRaises(venue_research.ProviderError) as caught:
            self.request(response, clock=lambda: 10 if expired[0] else 0)
        self.assertEqual(caught.exception.safe_details(), {
            "status": 403, "code": "unclassified"})

    def test_expired_header_deadline_never_starts_error_body_read(self):
        expired = [False]
        response = Response(403, b'{"error":{"type":"access_denied"}}',
                            on_enter=lambda: expired.__setitem__(0, True))
        with self.assertRaises(venue_research.ProviderError) as caught:
            self.request(response, clock=lambda: 10 if expired[0] else 0)
        self.assertEqual(response.body_iterations, 0)
        self.assertEqual(response.bytes_yielded, 0)
        self.assertEqual(caught.exception.safe_details(), {
            "status": 403, "code": "unclassified"})

    def test_success_contract_and_response_bound_are_unchanged(self):
        self.assertEqual(self.request(Response(200, b'{"ok":true}')), {"ok": True})
        with self.assertRaisesRegex(ValueError, "^response_bound$"):
            self.request(Response(200, b"x" * 100), max_body=16)

    def test_address_transport_defaults_are_unchanged(self):
        response = Response(200, b'{"stop_reason":"end_turn","content":'
                                   b'[{"type":"text","text":"result"}]}')
        with patch.object(venue_research.requests, "post", return_value=response) as post:
            answer = venue_research.anthropic_extract(
                {"fixture": True}, api_key="fixture-key", model="fixture-model",
                deadline_at=10, clock=lambda: 0)
        self.assertEqual(answer, "result")
        self.assertEqual(post.call_args.args[0], "https://api.anthropic.com/v1/messages")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["max_tokens"], 512)
        self.assertEqual(body["system"], venue_research.SYSTEM)
        self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "fixture-key")
        self.assertNotIn("thinking", body)

    def test_rover_logs_only_safe_fields_without_retrying_model(self):
        calls = []
        def complete(*args):
            calls.append("model")
            raise venue_research.ProviderError(403, "customer_verification_required")
        def admit(*args):
            calls.append("admit")
            return {"permit_id": "398adf59-2255-4351-8972-8f507a10b305"}
        def fetch(*args, **kwargs):
            self.fail("failed model must not trigger publisher visits")
        log = io.StringIO()
        with redirect_stdout(log):
            result = research_clean_miss(
                {"name": "Example Venue"}, "https://venue.example/",
                '<a href="/program">Program</a>', ticket="fixture",
                admit=admit, complete=complete, fetch=fetch,
                deadline=monotonic() + 10)
        self.assertEqual(result, {"status": "retry", "reason": "rover_model_unavailable"})
        self.assertEqual(calls, ["admit", "model"])
        self.assertEqual(log.getvalue(), 'rover_model_failure '
                         '{"code":"customer_verification_required","status":403}\n')

    def test_ordinary_failure_does_not_log_freeform_exception(self):
        def complete(*args):
            raise OSError("SECRET arbitrary error")
        log = io.StringIO()
        with redirect_stdout(log):
            result = research_clean_miss(
                {"name": "Example Venue"}, "https://venue.example/",
                '<a href="/program">Program</a>', ticket="fixture",
                admit=lambda _: {"permit_id": "398adf59-2255-4351-8972-8f507a10b305"},
                complete=complete,
                fetch=lambda *args, **kwargs: self.fail("no fetch"),
                deadline=monotonic() + 10)
        self.assertEqual(result, {"status": "retry", "reason": "rover_model_unavailable"})
        self.assertEqual(log.getvalue(), "")
