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
from urllib.parse import parse_qs, urlparse

from roomquest import forward_geocoder as worker
from roomquest import geoapify_geocoder as geo

ADDRESS = "58 regent st,cambridge,CB2 1DP"
KEY = "credential-secret-sentinel"
ENV = {"VERCEL_ENV": "production", "FORWARD_GEOCODER_ENABLED": "true",
       "GEOCODIO_API_KEY": "us-fixture", "GEOAPIFY_API_KEY": KEY,
       "GB_GEOCODER_PROVIDER": "geoapify"}


def response(**changes):
    # Synthetic provider data; never a source of production coordinates.
    row = {"country": "United Kingdom", "country_code": "gb", "city": "Cambridge",
           "street": "Regent Street", "housenumber": "58", "postcode": "CB2 1DP",
           "lat": 52.2, "lon": 0.1, "result_type": "building",
           "formatted": "58 Regent Street, Cambridge, CB2 1DP, United Kingdom",
           "rank": {"confidence": 1, "confidence_city_level": 1,
                    "confidence_street_level": 1, "confidence_building_level": 1,
                    "match_type": "full_match"},
           "datasource": {"sourcename": "openstreetmap", "attribution": "© OpenStreetMap contributors",
                          "license": "Open Database License", "url": "https://www.openstreetmap.org/copyright"}}
    row.update(changes)
    return {"results": [row]}


def reservation(**changes):
    value = {"allowed": True, "provider": "geoapify", "country_code": "GB", "query_text": ADDRESS,
             "request_id": "00000000-0000-0000-0000-000000000001",
             "valid_until": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
    value.update(changes)
    return value


class VerificationTests(unittest.TestCase):
    def test_observed_reviewed_venue_responses_keep_native_coordinates_and_precision(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/geoapify/reviewed_gb_responses.json").read_text())
        for case in fixture["cases"]:
            rows = []
            for projected in case["results"]:
                row = copy.deepcopy(fixture["common_fields"])
                row.update(projected)
                row["rank"] = {**fixture["common_fields"]["rank"], **projected["rank"]}
                rows.append(row)
            with self.subTest(venue=case["venue"]):
                result = geo.verify({"results": rows}, case["query_text"])
                self.assertEqual(result is not None, case["accepted"])
                if result:
                    self.assertEqual(len(result["results"]), 1)
                    first = result["results"][0]
                    for field in ("lat", "lon", "result_type", "rank", "datasource"):
                        self.assertEqual(first[field], rows[0][field])

    def test_native_result_precision_confidence_and_attribution_are_retained(self):
        payload = response()
        payload["results"][0].update(secret=KEY, query={"apiKey": KEY}, place_id="unneeded")
        payload["results"][0]["rank"]["secret"] = KEY
        payload["results"][0]["datasource"]["raw"] = KEY
        result = geo.verify(payload, ADDRESS)
        self.assertEqual(result["provider"], "geoapify")
        first = result["results"][0]
        self.assertEqual(first["result_type"], "building")
        self.assertEqual(first["rank"]["confidence"], 1)
        self.assertEqual(first["datasource"]["attribution"], "© OpenStreetMap contributors")
        self.assertNotIn("geocodio", json.dumps(result))
        self.assertNotIn(KEY, json.dumps(result))
        self.assertNotIn("accuracy_type", first)

    def test_street_result_preserves_its_lower_precision(self):
        result = geo.verify(response(result_type="street", housenumber=None,
                                     rank={"confidence": .9, "match_type": "match_by_street"}), ADDRESS)
        self.assertEqual(result["results"][0]["result_type"], "street")
        self.assertNotIn("housenumber", result["results"][0])

    def test_full_postcode_can_identify_postal_town_alias(self):
        payload = response(city="Trumpington")
        self.assertIsNotNone(geo.verify(payload, ADDRESS))
        payload["results"][0]["postcode"] = "CB2 2AA"
        self.assertIsNone(geo.verify(payload, ADDRESS))

    def test_unambiguous_park_amenity_still_matches_its_reviewed_street(self):
        payload = response(result_type="amenity", housenumber=None, street="Grantchester Road",
                           city="Coton", postcode="CB23 7PY")
        self.assertIsNotNone(geo.verify(payload, "grantchester rd,cambridge,CB23 7PY"))
        payload["results"][0]["street"] = "High Street"
        self.assertIsNone(geo.verify(payload, "grantchester rd,cambridge,CB23 7PY"))

    def test_named_amenity_needs_exact_place_name_and_full_postcode(self):
        address = "wandlebury ring,cambridge,CB22 3AE"
        payload = response(result_type="amenity", name="Wandlebury Ring (Iron Age Hill Fort)",
                           street="Wandlebury", city="Stapleford", postcode="CB22 3AE", housenumber=None,
                           rank={"confidence": 1, "confidence_street_level": 1, "match_type": "inner_part"})
        self.assertIsNotNone(geo.verify(payload, address))
        payload["results"][0]["street"] = None
        self.assertIsNotNone(geo.verify(payload, address))
        for changes in ({"name": "Gog Magog Hills"}, {"name": "Wandlebury Hill"},
                        {"name": "Wandlebury Ring Road"}, {"name": "Wandlebury Ring (West) (Hill)"},
                        {"postcode": "CB22 3AA"}, {"postcode": None}, {"result_type": "street"}):
            changed = copy.deepcopy(payload)
            changed["results"][0].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(geo.verify(changed, address))
        numbered = response(result_type="amenity", name="58 Regent St", street=None, housenumber="58")
        self.assertIsNone(geo.verify(numbered, ADDRESS))

    def test_identity_fields_cannot_be_lost_while_bounding_the_result(self):
        for changes in ({"name": "x" * 201}, {"city": "x" * 181}, {"housenumber": 58},
                        {"postcode": "CB2" + " " * 20 + "1DP"}):
            with self.subTest(changes=changes):
                self.assertIsNone(geo.verify(response(**changes), ADDRESS))

    def test_country_street_house_and_precise_postcode_cannot_drift(self):
        for changes in ({"country_code": "us"}, {"country_code": "GB"}, {"country_code": "uk"},
                        {"street": "Regents Road"}, {"housenumber": "57"}, {"housenumber": None},
                        {"postcode": "CB2 2AA"}, {"postcode": "CB2"},
                        {"city": "Other", "postcode": None}):
            with self.subTest(changes=changes):
                self.assertIsNone(geo.verify(response(**changes), ADDRESS))

    def test_broad_and_malformed_precision_never_becomes_a_venue(self):
        for result_type in ("city", "postcode", "county", "state", "country", "suburb", "unknown", [], None):
            with self.subTest(result_type=result_type):
                self.assertIsNone(geo.verify(response(result_type=result_type), ADDRESS))

    def test_confidence_and_coordinates_are_finite_numeric_values(self):
        for score in (None, "1", True, float("nan"), float("inf"), 10 ** 1000, -.1, 1.1, .79):
            with self.subTest(score=score):
                self.assertIsNone(geo.verify(response(rank={"confidence": score, "match_type": "full_match"}), ADDRESS))
        for field, values in (("lat", (None, "52.2", True, float("nan"), float("inf"), 91, 10 ** 1000)),
                              ("lon", (None, "0.1", False, float("nan"), float("inf"), -181, -(10 ** 1000)))):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertIsNone(geo.verify(response(**{field: value}), ADDRESS))

    def test_all_supplied_confidence_fields_are_valid(self):
        payload = response()
        payload["results"][0]["rank"]["confidence_building_level"] = "unknown"
        self.assertIsNone(geo.verify(payload, ADDRESS))
        payload["results"][0]["rank"] = {"confidence": 1, "match_type": "match_by_postcode"}
        self.assertIsNone(geo.verify(payload, ADDRESS))

    def test_attribution_is_required_and_bounded(self):
        for changes in ({"attribution": ""}, {"license": None}, {"sourcename": ""},
                        {"url": "javascript:alert(1)"}, {"url": "https://user:pass@example.com/"},
                        {"url": "https://example.com/?apiKey=secret"},
                        {"attribution": "a" * 401}):
            payload = response()
            payload["results"][0]["datasource"].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(geo.verify(payload, ADDRESS))

    def test_bad_top_result_does_not_fall_through_to_lower_candidate(self):
        payload = response(country_code="us")
        payload["results"].append(response()["results"][0])
        self.assertIsNone(geo.verify(payload, ADDRESS))

    def test_changed_or_malformed_input_cannot_bind(self):
        for address in ("58 regent st,cambridge,CB2", "58 regent st,cambridge,CB2 1DP,UK",
                        "58 regent st,,CB2 1DP", "online,cambridge,CB2 1DP", ""):
            self.assertIsNone(geo.verify(response(), address))
        for payload in (None, [], {}, {"results": []}, {"results": [None]},
                        {"results": response()["results"] * 3}):
            self.assertIsNone(geo.verify(payload, ADDRESS))


class TransportTests(unittest.TestCase):
    def test_provider_aware_claim_uses_existing_authenticated_gateway(self):
        options = {"limit": 1, "gb_provider": "geoapify"}
        with patch.object(worker, "supabase_rpc", return_value=[]) as rpc, redirect_stdout(io.StringIO()):
            worker.rpc("claim", options)
        rpc.assert_called_once_with(worker.RPC, {"p_action": "claim_v2", "p_payload": options}, timeout=12)

    def test_one_country_filtered_request_requires_bound_fresh_reservation(self):
        opener = MagicMock(return_value=io.BytesIO(json.dumps(response()).encode()))
        result = geo.geocode(ADDRESS, KEY, reservation=reservation(), opener=opener)
        opener.assert_called_once()
        request = opener.call_args.args[0]
        url = urlparse(request.full_url)
        self.assertEqual(url.scheme + "://" + url.netloc + url.path, geo.ENDPOINT)
        self.assertEqual(parse_qs(url.query), {"text": [ADDRESS], "apiKey": [KEY],
                         "filter": ["countrycode:gb"], "bias": ["countrycode:none"],
                         "limit": ["2"], "format": ["json"], "lang": ["en"]})
        self.assertEqual(opener.call_args.kwargs, {"timeout": 8})
        self.assertEqual(result["provider"], "geoapify")

    def test_invalid_reservations_never_issue_request(self):
        cases = [{"provider": None}, {"provider": "geocodio"}, {"country_code": "US"},
                 {"query_text": ADDRESS + " "}, {"allowed": False}, {"request_id": None},
                 {"valid_until": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()}]
        for changes in cases:
            opener = MagicMock()
            with self.subTest(changes=changes), self.assertRaisesRegex(worker.GeocodeFailure, "invalid_reservation"):
                geo.geocode(ADDRESS, KEY, reservation=reservation(**changes), opener=opener)
            opener.assert_not_called()
        with self.assertRaisesRegex(worker.GeocodeFailure, "invalid_reservation"):
            geo.geocode(ADDRESS, KEY, reservation=reservation(), country_code="US", opener=MagicMock())

    def test_secret_bearing_http_errors_are_bounded_redacted_and_not_retried(self):
        for status, reason in ((400, "ambiguous"), (422, "ambiguous"), (401, "provider_auth"),
                               (403, "provider_auth"), (429, "rate_limited"), (503, "provider_error")):
            error = HTTPError(geo.ENDPOINT + "?apiKey=" + KEY, status, KEY, {},
                              io.BytesIO(json.dumps({"message": KEY, "query": ADDRESS}).encode()))
            opener = MagicMock(side_effect=error)
            output = io.StringIO()
            with self.subTest(status=status), redirect_stdout(output), self.assertRaises(worker.GeocodeFailure) as caught:
                geo.geocode(ADDRESS, KEY, reservation=reservation(), opener=opener)
            opener.assert_called_once()
            self.assertEqual(str(caught.exception), reason)
            self.assertEqual(caught.exception.diagnostic, {"version": 1, "cause": "http_rejected",
                                                         "http_status": status, "error_class": "unclassified"})
            self.assertNotIn(KEY, output.getvalue() + str(caught.exception) + json.dumps(caught.exception.diagnostic))

    def test_unusable_or_invalid_response_never_substitutes_coordinates(self):
        for raw, reason in ((b"not-json", "invalid_response"),
                            (b"x" * (geo.MAX_RESPONSE + 1), "invalid_response"),
                            (json.dumps({"results": []}).encode(), "ambiguous"),
                            (json.dumps(response(lat=10 ** 1000)).encode(), "ambiguous"),
                            (json.dumps(response(rank={"confidence": 10 ** 1000})).encode(), "ambiguous"),
                            (json.dumps(response(result_type="city")).encode(), "ambiguous")):
            opener = MagicMock(return_value=io.BytesIO(raw))
            with self.assertRaisesRegex(worker.GeocodeFailure, reason):
                geo.geocode(ADDRESS, KEY, reservation=reservation(), opener=opener)
            opener.assert_called_once()

    def test_network_failure_does_not_retry_or_disclose_exception(self):
        opener = MagicMock(side_effect=URLError(KEY))
        with self.assertRaisesRegex(worker.GeocodeFailure, "^provider_error$") as caught:
            geo.geocode(ADDRESS, KEY, reservation=reservation(), opener=opener)
        opener.assert_called_once()
        self.assertNotIn(KEY, json.dumps(caught.exception.diagnostic))


class WorkerRoutingTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.claim = {"venue_key": "a" * 32, "lease_id": "lease", "country_code": "GB", "query_text": ADDRESS}
        self.reserved = reservation()
        self.submitted = {"resolved": True, "events_updated": 30}

    def database(self, action, payload):
        self.calls.append((action, copy.deepcopy(payload)))
        if action == "claim":
            return [self.claim]
        if action == "reserve":
            return self.reserved
        if action == "submit":
            if isinstance(self.submitted, Exception):
                raise self.submitted
            return self.submitted
        return {"recorded": True}

    def test_uk_routes_only_to_geoapify_and_binds_provider_through_submit(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(geo, "geocode", return_value=geo.verify(response(), ADDRESS)) as uk, \
                patch.object(worker, "geocode") as us:
            stats = worker.run_batch(max_requests=1, database=self.database)
        uk.assert_called_once_with(ADDRESS, KEY, reservation=self.reserved, country_code="GB")
        us.assert_not_called()
        self.assertEqual((stats["resolved"], stats["events_updated"]), (1, 30))
        self.assertEqual(self.calls[0], ("claim", {"limit": 1, "gb_provider": "geoapify"}))
        for _, payload in self.calls[1:]:
            self.assertEqual(payload["provider"], "geoapify")
            self.assertEqual(payload["query_text"], ADDRESS)
            self.assertEqual(payload["country_code"], "GB")

    def test_us_keeps_its_existing_geocodio_provider_and_payload(self):
        self.claim.update(country_code="US", query_text="11 w jones st,raleigh,nc")
        self.reserved = {k: v for k, v in reservation().items() if k not in {"provider", "country_code", "query_text"}}
        with patch.dict(os.environ, ENV, clear=True), patch.object(geo, "geocode") as uk, \
                patch.object(worker, "geocode", return_value={"results": []}) as us:
            worker.run_batch(max_requests=1, database=self.database)
        uk.assert_not_called()
        us.assert_called_once_with(self.claim["query_text"], "us-fixture", reservation=self.reserved, country_code="US")
        self.assertNotIn("provider", self.calls[1][1])
        self.assertNotIn("query_text", self.calls[1][1])

    def test_missing_uk_key_cannot_fall_back_to_geocodio_or_consume_quota(self):
        with patch.dict(os.environ, {**ENV, "GEOAPIFY_API_KEY": ""}, clear=True), \
                patch.object(worker, "geocode") as us, patch.object(geo, "geocode") as uk:
            stats = worker.run_batch(database=self.database)
        self.assertEqual(stats["stop_reason"], "provider_not_configured")
        self.assertEqual([action for action, _ in self.calls], ["claim"])
        us.assert_not_called()
        uk.assert_not_called()

    def test_geoapify_cannot_use_legacy_or_wrong_provider_reservation(self):
        for provider in (None, "geocodio"):
            self.setUp()
            self.reserved["provider"] = provider
            injected = MagicMock()
            with patch.dict(os.environ, ENV, clear=True):
                stats = worker.run_batch(database=self.database, provider=injected)
            self.assertEqual(stats["stop_reason"], "invalid_reservation")
            self.assertEqual(stats["attempted"], 0)
            injected.assert_not_called()

    def test_quota_or_pacing_denial_never_calls_provider(self):
        for reason in ("quota_exhausted", "provider_rate_limit"):
            self.setUp()
            self.reserved = {"allowed": False, "reason": reason}
            injected = MagicMock()
            with patch.dict(os.environ, ENV, clear=True):
                stats = worker.run_batch(database=self.database, provider=injected)
            self.assertEqual(stats["stop_reason"], reason)
            injected.assert_not_called()

    def test_provider_failure_is_recorded_under_its_real_provider_without_retry(self):
        injected = MagicMock(side_effect=worker.GeocodeFailure("rate_limited"))
        with patch.dict(os.environ, ENV, clear=True), redirect_stdout(io.StringIO()):
            stats = worker.run_batch(max_requests=10, database=self.database, provider=injected)
        self.assertEqual(stats["stop_reason"], "rate_limited")
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "fail"])
        self.assertEqual(self.calls[-1][1]["provider"], "geoapify")
        injected.assert_called_once()

    def test_submit_timeout_keeps_reservation_without_retry_and_redacts_diagnostics(self):
        self.submitted = TimeoutError(KEY)
        injected = MagicMock(return_value=geo.verify(response(), ADDRESS))
        output = io.StringIO()
        with patch.dict(os.environ, ENV, clear=True), redirect_stdout(output):
            stats = worker.run_batch(max_requests=1, database=self.database, provider=injected)
        self.assertEqual(stats["errors"], 1)
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit"])
        logged = json.loads(output.getvalue())
        self.assertEqual(logged["provider"], "geoapify")
        self.assertTrue(logged["validation"]["country_valid"])
        self.assertTrue(logged["validation"]["address_match"])
        for secret in (KEY, ADDRESS, "Regent", "lease"):
            self.assertNotIn(secret, output.getvalue())
        injected.assert_called_once()

    def test_submit_requires_positive_database_acceptance_before_counting_resolution(self):
        for result in (None, {}, {"resolved": False}, {"resolved": "true"}, {"resolved": 1}):
            self.setUp()
            self.submitted = result
            injected = MagicMock(return_value=geo.verify(response(), ADDRESS))
            with self.subTest(result=result), patch.dict(os.environ, ENV, clear=True):
                stats = worker.run_batch(database=self.database, provider=injected)
            self.assertEqual(stats["resolved"], 0)
            self.assertEqual(stats["events_updated"], 0)
            self.assertEqual(stats["errors"], 1)
            self.assertEqual(stats["stop_reason"], "submit_not_resolved")
            self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit"])
            injected.assert_called_once()

    def test_invalid_routing_configuration_and_preview_issue_no_claim(self):
        for changes, reason in (({"GB_GEOCODER_PROVIDER": "typo"}, "invalid_provider_configuration"),
                                 ({"VERCEL_ENV": "preview"}, "disabled")):
            self.setUp()
            with patch.dict(os.environ, {**ENV, **changes}, clear=True):
                self.assertEqual(worker.run_batch(database=self.database)["stop_reason"], reason)
            self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
