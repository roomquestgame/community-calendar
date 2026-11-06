import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from api.geocode import handler
from roomquest import forward_geocoder as g

ADDRESS = "11 w jones st,raleigh,nc"
ENV = {"VERCEL_ENV": "production", "FORWARD_GEOCODER_ENABLED": "true",
       "GEOCODIO_API_KEY": "fixture-only"}


def response(**changes):
    row = {"accuracy": 1, "accuracy_type": "rooftop", "location": {"lat": 35.782, "lng": -78.639},
           "address_components": {"number": "11", "predirectional": "W", "street": "Jones",
                                  "suffix": "St", "city": "Raleigh", "state_province": "NC",
                                  "country": "US", "postal_code": "27601"}}
    row.update(changes)
    return {"results": [row]}


def reservation():
    return {"allowed": True, "request_id": "request-fixture",
            "valid_until": (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat()}


class ValidationTests(unittest.TestCase):
    def test_real_v2_street_components(self):
        self.assertIsNotNone(g.verify(response(), ADDRESS))

    def test_live_postal_locality_difference_preserves_street_and_state(self):
        r = response()
        r["results"][0]["address_components"]["city"] = "Durham"
        self.assertIsNotNone(g.verify(r, ADDRESS))

    def test_wrong_state_number_street_and_old_v1_state_fail(self):
        for field, value in [("state_province", "FL"),
                             ("number", "111"), ("street", "Jonesville")]:
            r = response()
            r["results"][0]["address_components"][field] = value
            self.assertIsNone(g.verify(r, ADDRESS))
        r = response()
        r["results"][0]["address_components"]["state"] = "NC"
        del r["results"][0]["address_components"]["state_province"]
        self.assertIsNone(g.verify(r, ADDRESS))

    def test_away_event_uses_actual_florida_address(self):
        r = response()
        r["results"][0]["address_components"].update(
            number="400", predirectional="W", street="Church", city="Orlando", state_province="FL")
        r["results"][0]["location"] = {"lat": 28.539, "lng": -81.383}
        self.assertIsNotNone(g.verify(r, "400 w church st,orlando,fl"))
        self.assertIsNone(g.verify(r, ADDRESS))

    def test_low_confidence_approximate_invalid_and_nonfinite_fail(self):
        for values in [{"accuracy": .89}, {"accuracy_type": "range_interpolation"},
                       {"accuracy_type": "place"}, {"accuracy": float("nan")},
                       {"location": {"lat": float("inf"), "lng": 0}},
                       {"location": {"lat": True, "lng": 0}}]:
            self.assertIsNone(g.verify(response(**values), ADDRESS))
        for r in [None, {}, {"results": []}, {"results": [None]}, {"results": "bad"}]:
            self.assertIsNone(g.verify(r, ADDRESS))

    def test_ambiguous_candidates_fail_but_same_parcel_duplicates_pass(self):
        r = response()
        r["results"].append(copy.deepcopy(r["results"][0]))
        self.assertIsNotNone(g.verify(r, ADDRESS))
        r["results"][1]["location"]["lat"] += .02
        self.assertIsNone(g.verify(r, ADDRESS))

    def test_endpoint_bearer_header_no_appends_no_automatic_retries(self):
        opener = MagicMock(return_value=io.BytesIO(json.dumps(response()).encode()))
        self.assertIsNotNone(g.geocode(ADDRESS, "fixture-only", reservation=reservation(), opener=opener))
        req = opener.call_args.args[0]
        self.assertTrue(req.full_url.startswith("https://api.geocod.io/v2/geocode?"))
        self.assertNotIn("fixture-only", req.full_url)
        self.assertNotIn("fields=", req.full_url)
        self.assertEqual(req.get_header("Authorization"), "Bearer fixture-only")
        self.assertEqual(opener.call_args.kwargs["timeout"], 8)
        opener.assert_called_once()

    def test_no_request_without_fresh_reservation(self):
        for r in [{}, {"allowed": False}, {**reservation(), "valid_until": "2000-01-01T00:00:00Z"}]:
            opener = MagicMock()
            with self.assertRaises(g.GeocodeFailure):
                g.geocode(ADDRESS, "fixture-only", reservation=r, opener=opener)
            opener.assert_not_called()

    def test_http_errors_are_redacted_and_never_retried(self):
        for error, reason in [(HTTPError("https://example", 429, "fixture-only", {}, None), "rate_limited"),
                              (HTTPError("https://example", 403, "fixture-only", {}, None), "provider_auth"),
                              (URLError("fixture-only"), "provider_error")]:
            opener = MagicMock(side_effect=error)
            with self.assertRaisesRegex(g.GeocodeFailure, "^" + reason + "$"):
                g.geocode(ADDRESS, "fixture-only", reservation=reservation(), opener=opener)
            opener.assert_called_once()


class WorkerTests(unittest.TestCase):
    def test_production_cron_route_and_execution_budget(self):
        config = json.loads((Path(__file__).parents[1] / "vercel.json").read_text())
        self.assertIn({"path": "/api/geocode", "schedule": "* * * * *"}, config["crons"])
        self.assertIn({"src": "/api/geocode", "dest": "/api/geocode.py"}, config["routes"])
        self.assertEqual(config["functions"]["api/geocode.py"]["maxDuration"], 60)

    def db(self, action, payload):
        self.calls.append((action, payload))
        if action == "claim":
            return [{"venue_key": "key", "lease_id": "lease", "query_text": ADDRESS}]
        if action == "reserve":
            return reservation()
        if action == "submit":
            return {"resolved": True, "events_updated": 4}
        return {"recorded": True}

    def setUp(self):
        self.calls = []

    def test_disabled_or_preview_makes_no_calls(self):
        for env in [{**ENV, "FORWARD_GEOCODER_ENABLED": "false"}, {**ENV, "VERCEL_ENV": "preview"}]:
            with patch.dict(os.environ, env):
                self.assertEqual(g.run_batch(database=self.db)["stop_reason"], "disabled")
            self.assertEqual(self.calls, [])

    def test_bound_reserve_precedes_every_request(self):
        def provider(*args, **kwargs):
            self.assertEqual(self.calls[-1][0], "reserve")
            return response()
        with patch.dict(os.environ, ENV):
            result = g.run_batch(max_requests=2, database=self.db, provider=provider)
        self.assertEqual(result["attempted"], 2)
        self.assertEqual(result["events_updated"], 8)
        self.assertEqual([x[0] for x in self.calls], ["claim", "reserve", "submit"] * 2)

    def test_quota_exhaustion_stops_without_outbound_request(self):
        def db(action, payload):
            return {"allowed": False, "reason": "quota_exhausted"} if action == "reserve" else self.db(action, payload)
        provider = MagicMock()
        with patch.dict(os.environ, ENV):
            result = g.run_batch(database=db, provider=provider)
        provider.assert_not_called()
        self.assertTrue(result["quota_exhausted"])

    def test_errors_record_failure_and_provider_pause_stops(self):
        with patch.dict(os.environ, ENV):
            result = g.run_batch(database=self.db, provider=MagicMock(side_effect=g.GeocodeFailure("rate_limited")))
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(self.calls[-1][1]["reason"], "rate_limited")

    def test_deadline_prevents_unfinishable_claim(self):
        times = iter([0, 30])
        with patch.dict(os.environ, ENV):
            self.assertEqual(g.run_batch(database=self.db, clock=lambda: next(times))["stop_reason"], "deadline")
        self.assertEqual(self.calls, [])

    def test_endpoint_unauthorized_cannot_start_worker(self):
        fake = handler.__new__(handler)
        fake.path = "/api/geocode"
        fake.headers = {"Authorization": "Bearer invalid"}
        fake.reply = MagicMock()
        with patch.dict(os.environ, {"CRON_SECRET": "fixture-only"}), patch("api.geocode.run_batch") as worker:
            fake.do_GET()
        self.assertEqual(fake.reply.call_args.args[0], 401)
        worker.assert_not_called()

    def test_cron_and_manual_auth_body_and_health(self):
        for method, name in [("do_GET", "CRON_SECRET"), ("do_POST", "ROOMQUEST_PREVIEW_SECRET")]:
            fake = handler.__new__(handler)
            fake.path = "/api/geocode"
            fake.headers = {"Authorization": "Bearer fixture-only"}
            fake.reply = MagicMock()
            with patch.dict(os.environ, {name: "fixture-only"}), patch("api.geocode.run_batch", return_value={}) as worker:
                getattr(fake, method)()
            self.assertEqual(fake.reply.call_args.args[0], 200)
            worker.assert_called_once()
        fake.headers = {}
        with patch("api.geocode.run_batch") as worker:
            fake.do_GET()
        worker.assert_not_called()


class SubmitFailureTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.claim_count = 0
        self.failure = g.PreviewError("sensitive-exception-sentinel")
        self.provider = MagicMock(side_effect=self.provide)

    def provide(self, address, key, *, reservation):
        self.assertEqual(self.calls[-1][0], "reserve")
        result = response()
        result["results"][0]["address_components"]["number"] = address.split()[0]
        return result

    def db(self, action, payload):
        self.calls.append((action, copy.deepcopy(payload)))
        if action == "claim":
            self.claim_count += 1
            return [{"venue_key": f"{self.claim_count:032x}",
                     "lease_id": f"lease-sensitive-sentinel-{self.claim_count}",
                     "query_text": f"{10 + self.claim_count} w jones st,raleigh,nc"}]
        if action == "reserve":
            return {**reservation(),
                    "request_id": f"00000000-0000-0000-0000-{int(payload['venue_key'], 16):012x}"}
        if action == "submit":
            if payload["venue_key"] == f"{1:032x}":
                raise self.failure
            return {"resolved": True, "events_updated": 2}
        self.fail(f"Unexpected database action: {action}")

    def test_submit_failure_continues_without_replay_or_lease_changes(self):
        output = io.StringIO()
        with patch.dict(os.environ, ENV), redirect_stdout(output):
            stats = g.run_batch(max_requests=2, database=self.db, provider=self.provider)
        self.assertEqual((stats["attempted"], stats["errors"], stats["resolved"]), (2, 1, 1))
        self.assertEqual(stats["events_updated"], 2)
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit"] * 2)
        self.assertEqual(self.provider.call_count, 2)
        self.assertNotEqual(self.provider.call_args_list[0].args[0], self.provider.call_args_list[1].args[0])
        for start in (0, 3):
            reserved, submitted = self.calls[start + 1][1], self.calls[start + 2][1]
            self.assertEqual(reserved, {name: submitted[name] for name in ("venue_key", "lease_id")})
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        diagnostic = json.loads(lines[0])
        self.assertEqual(diagnostic["request_id"], "00000000-0000-0000-0000-000000000001")
        self.assertEqual(diagnostic["venue_key"], f"{1:032x}")
        self.assertTrue(diagnostic["city_exact_match"])
        self.assertNotIn("sentinel", output.getvalue())

    def test_expected_network_failures_are_contained(self):
        failures = [HTTPError("https://sensitive.invalid", 504, "sensitive", {}, None),
                    URLError("sensitive"), TimeoutError("sensitive"), ConnectionError("sensitive")]
        for failure in failures:
            with self.subTest(error_type=type(failure).__name__):
                self.setUp()
                self.failure = failure
                with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()):
                    stats = g.run_batch(max_requests=2, database=self.db, provider=self.provider)
                self.assertEqual((stats["errors"], stats["resolved"]), (1, 1))
                self.assertEqual(self.provider.call_count, 2)

    def test_submit_failure_preserves_ten_request_limit(self):
        with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()):
            stats = g.run_batch(max_requests=100, database=self.db, provider=self.provider, clock=lambda: 0)
        self.assertEqual((stats["attempted"], stats["errors"], stats["resolved"]), (10, 1, 9))
        self.assertEqual(self.provider.call_count, 10)
        submitted = [payload["request_id"] for action, payload in self.calls if action == "submit"]
        self.assertEqual(len(set(submitted)), 10)

    def test_submit_failure_preserves_forty_five_second_budget(self):
        times = iter([0, 0, 26])
        with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()):
            stats = g.run_batch(deadline_seconds=999, database=self.db, provider=self.provider,
                                clock=lambda: next(times))
        self.assertEqual(stats["stop_reason"], "deadline")
        self.assertEqual(stats["errors"], 1)
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit"])
        self.provider.assert_called_once()

    def test_quota_exhaustion_after_submit_failure_prevents_another_provider_request(self):
        def db(action, payload):
            if action == "reserve" and self.claim_count == 2:
                self.calls.append((action, copy.deepcopy(payload)))
                return {"allowed": False, "reason": "quota_exhausted"}
            return self.db(action, payload)
        with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()):
            stats = g.run_batch(database=db, provider=self.provider)
        self.assertEqual((stats["attempted"], stats["errors"]), (1, 1))
        self.assertTrue(stats["quota_exhausted"])
        self.assertEqual(stats["stop_reason"], "quota_exhausted")
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit", "claim", "reserve"])
        self.provider.assert_called_once()

    def test_claim_failure_after_submit_failure_still_aborts(self):
        def db(action, payload):
            if action == "claim" and self.claim_count:
                self.calls.append((action, copy.deepcopy(payload)))
                raise g.PreviewError("database_unavailable")
            return self.db(action, payload)
        with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()):
            with self.assertRaises(g.PreviewError):
                g.run_batch(database=db, provider=self.provider)
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit", "claim"])
        self.provider.assert_called_once()

    def test_programming_errors_are_not_hidden(self):
        self.failure = RuntimeError("programming-error-sentinel")
        output = io.StringIO()
        with patch.dict(os.environ, ENV), redirect_stdout(output):
            with self.assertRaises(RuntimeError):
                g.run_batch(database=self.db, provider=self.provider)
        self.provider.assert_called_once()
        self.assertEqual(output.getvalue(), "")

    def test_rpc_submit_emits_one_redacted_diagnostic(self):
        match = response()
        match["results"][0].update(formatted_address="raw-address-sentinel",
                                   source="https://sensitive.invalid/provider-payload-sentinel",
                                   location={"lat": 12.3456789, "lng": 98.7654321})
        match["results"][0]["address_components"].update(
            street="street-sentinel", city="sensitive city sentinel", predirectional="", postdirectional="")
        claim = {"venue_key": f"{1:032x}", "lease_id": "lease-sensitive-sentinel",
                 "query_text": "11 street-sentinel st,sensitivecitysentinel,nc"}
        reserved = {**reservation(), "request_id": "00000000-0000-0000-0000-000000000001"}
        output = io.StringIO()
        with patch.dict(os.environ, {**ENV, "GEOCODIO_API_KEY": "key-sensitive-sentinel"}), redirect_stdout(output):
            with patch.object(g, "supabase_rpc", side_effect=[[claim], reserved, self.failure, []]) as database:
                stats = g.run_batch(provider=MagicMock(return_value=match))
        self.assertEqual((stats["attempted"], stats["errors"], stats["resolved"]), (1, 1, 0))
        self.assertEqual(database.call_count, 4)
        lines = [line for line in output.getvalue().splitlines() if line.startswith("{")]
        self.assertEqual(len(lines), 1)
        self.assertLess(len(lines[0]), 1000)
        diagnostic = json.loads(lines[0])
        self.assertFalse(diagnostic["city_exact_match"])
        self.assertTrue(diagnostic["city_space_insensitive_match"])
        self.assertTrue(diagnostic["street_match"])
        self.assertTrue(diagnostic["state_match"])
        self.assertTrue(diagnostic["empty_predirectional_component"])
        self.assertTrue(diagnostic["empty_postdirectional_component"])
        self.assertTrue(diagnostic["score_valid"])
        self.assertTrue(diagnostic["accuracy_type_valid"])
        self.assertTrue(diagnostic["country_valid"])
        for value in ("sentinel", "12.3456789", "98.7654321", "https://", "exception"):
            self.assertNotIn(value, output.getvalue())
        for name, value in diagnostic.items():
            if name not in {"event", "venue_key", "request_id", "error_type", "result_count"}:
                self.assertIs(type(value), bool)
        self.assertEqual(diagnostic["result_count"], 1)

    def test_diagnostic_rejects_malformed_identifiers_and_exposes_only_validity_flags(self):
        match = response(accuracy="score-sentinel", accuracy_type="type-sentinel")
        match["results"][0]["address_components"].update(city="", country="country-sentinel")
        diagnostic = g._submit_failure_diagnostic(
            {"request_id": "request-secret-sentinel", "venue_key": "venue-secret-sentinel"},
            ADDRESS, match, self.failure)
        self.assertIsNone(diagnostic["request_id"])
        self.assertIsNone(diagnostic["venue_key"])
        self.assertFalse(diagnostic["city_present"])
        self.assertFalse(diagnostic["city_exact_match"])
        self.assertFalse(diagnostic["city_space_insensitive_match"])
        self.assertFalse(diagnostic["score_valid"])
        self.assertFalse(diagnostic["accuracy_type_valid"])
        self.assertFalse(diagnostic["country_valid"])
        self.assertNotIn("sentinel", json.dumps(diagnostic))


if __name__ == "__main__":
    unittest.main()
