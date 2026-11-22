"""No-network checks for private, unaccepted public-venue candidate diagnostics."""
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


def load_worker():
    preview = types.ModuleType("roomquest.preview_worker")
    preview.PreviewError = type("PreviewError", (Exception,), {})
    preview.supabase_rpc = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network disabled"))
    spec = importlib.util.spec_from_file_location(
        "private_candidate_worker", Path(__file__).parents[1] / "roomquest" / "forward_geocoder.py")
    worker = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"roomquest.preview_worker": preview}):
        spec.loader.exec_module(worker)
    return worker


worker = load_worker()


def candidate(**changes):
    # These deliberately synthetic coordinates are test data, never Echo evidence.
    value = {"latitude": 32.0, "longitude": -96.0, "accuracy": 0.7,
             "accuracy_type": "rooftop", "country_code": "US", "state_code": "TX"}
    return {**value, **changes}


def payload(**changes):
    item = {"location": {"lat": 32.0, "lng": -96.0}, "accuracy": 0.7,
            "accuracy_type": "rooftop", "formatted_address": "DO NOT RETAIN THIS ADDRESS",
            "address_components": {"number": "123", "street": "Wrong",
                                   "suffix": "St", "city": "Dallas",
                                   "state_province": "TX", "country": "US"},
            "secret": "DO NOT RETAIN PROVIDER DATA"}
    item.update(changes)
    return {"results": [item, {**item, "location": {"lat": 33.0, "lng": -97.0}}]}


class PrivateCandidateTests(unittest.TestCase):
    def test_only_first_ranked_point_and_fixed_fields_survive(self):
        value = worker._result_diagnostic(payload(), "123 Right St,Dallas,TX", "US", 200)
        self.assertEqual(value["candidate"], candidate())
        self.assertFalse(value["address_match"])
        self.assertNotIn("DO NOT RETAIN", json.dumps(value))
        self.assertEqual(worker.verify(payload(), "123 Right St,Dallas,TX"), None)

    def test_candidate_is_optional_and_does_not_change_acceptance(self):
        response = payload()
        response["results"][0]["address_components"]["street"] = "Right"
        match = worker.verify(response, "123 Right St,Dallas,TX")
        self.assertEqual(match["results"][0]["location"], {"lat": 32.0, "lng": -96.0})
        self.assertEqual(len(match["results"]), 1)

    def test_rejects_invalid_numbers_types_ranges_and_infinity(self):
        for name, value in [("latitude", True), ("latitude", "32"), ("latitude", float("nan")),
                            ("latitude", 91), ("longitude", -181), ("accuracy", -0.1),
                            ("accuracy", 1.1), ("longitude", float("inf")),
                            ("latitude", 10 ** 1000), ("accuracy", None)]:
            with self.subTest(name=name, value=str(value)[:30]):
                self.assertIsNone(worker.sanitize_us_candidate(candidate(**{name: value})))

    def test_rejects_other_countries_broad_centroids_and_arbitrary_codes(self):
        for fields in [{"country_code": "GB"}, {"country_code": "USA"},
                       {"accuracy_type": "county"}, {"accuracy_type": []},
                       {"state_code": "Texas"}, {"state_code": "TX\n"}]:
            with self.subTest(fields=fields):
                self.assertIsNone(worker.sanitize_us_candidate(candidate(**fields)))

    def test_gb_result_never_emits_us_candidate(self):
        response = payload()
        response["results"][0]["address_components"].update(country="GB", postal_code="CB2 8PX")
        self.assertNotIn("candidate", worker._result_diagnostic(response, "Long Road,Cambridge,CB2 8PX", "GB"))

    def test_unknown_or_non_result_diagnostic_cannot_attach_candidate(self):
        for cause in ["invalid_json", "http_rejected", "invalid_result", "empty_results", "arbitrary"]:
            with self.subTest(cause=cause):
                self.assertNotIn("candidate", worker.sanitize_diagnostic(
                    {"version": 1, "cause": cause, "candidate": candidate()}))

    def test_private_rpc_receives_candidate_console_does_not(self):
        calls = []
        diagnostic = {"version": 1, "cause": "result_mismatch", "candidate": candidate(),
                      "address_match": False, "unknown": "DO NOT RETAIN"}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            worker._record_failure(lambda action, body: calls.append((action, body)),
                {"venue_key": "a" * 32, "request_id": "11111111-1111-1111-1111-111111111111"},
                "ambiguous", diagnostic)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "fail")
        self.assertEqual(calls[0][1]["diagnostic"]["candidate"], candidate())
        record = json.loads(output.getvalue())
        self.assertNotIn("candidate", record["diagnostic"])
        self.assertNotIn("latitude", output.getvalue())
        self.assertNotIn("DO NOT RETAIN", output.getvalue())

    def test_geocode_failure_preserves_candidate_without_network_retry(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return json.dumps(payload()).encode()
        calls = []
        def open_response(request, timeout):
            calls.append(request)
            return Response()
        reservation = {"allowed": True, "request_id": "fixture", "country_code": "US",
                       "query_text": "123 Right St,Dallas,TX",
                       "valid_until": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
        with self.assertRaises(worker.GeocodeFailure) as captured:
            worker.geocode("123 Right St,Dallas,TX", "synthetic-test-key", reservation=reservation,
                           opener=open_response)
        self.assertEqual(str(captured.exception), "ambiguous")
        self.assertEqual(captured.exception.diagnostic["candidate"], candidate())
        self.assertEqual(len(calls), 1)

    def test_extra_candidate_fields_are_discarded(self):
        value = candidate(address="DO NOT RETAIN", raw={"token": "DO NOT RETAIN"})
        self.assertEqual(worker.sanitize_us_candidate(value), candidate())


if __name__ == "__main__":
    unittest.main()
