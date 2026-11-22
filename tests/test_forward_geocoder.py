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

from api.geocode import handler
from roomquest import forward_geocoder as g
from roomquest import preview_worker

ADDRESS = "11 w jones st,raleigh,nc"
GB_ADDRESS = "Park Street,Cambridge,CB5 8AS"
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


def gb_response(**changes):
    # Synthetic provider fixture; these coordinates are never used in production.
    row = {"accuracy": .67, "accuracy_type": "street_center",
           "location": {"lat": 52.2, "lng": .1},
           "address_components": {"street": "Park", "suffix": "St", "city": "Cambridge",
                                  "nation": "England", "country": "GB", "postal_code": "CB5 8AS"}}
    row.update(changes)
    return {"results": [row]}


def gb_reservation(address=GB_ADDRESS):
    return {**reservation(), "country_code": "GB", "query_text": address}


class ValidationTests(unittest.TestCase):
    def test_real_v2_street_components(self):
        self.assertIsNotNone(g.verify(response(), ADDRESS))

    def test_exact_secondary_address_components_survive_provider_verification(self):
        cases = [
            ("10411 portal rd ste 104,la vista,ne", "10411", "Portal", "Rd", "104"),
            ("10411 portal rd ste 102,la vista,ne", "10411", "Portal", "Rd", "102"),
            ("12744 westport pkwy ste 1a,la vista,ne", "12744", "Westport", "Pkwy", "1A"),
        ]
        for address, number, street, suffix, unit in cases:
            with self.subTest(address=address):
                payload = response()
                payload["results"][0]["address_components"].update(
                    number=number, predirectional="", street=street, suffix=suffix,
                    city="La Vista", state_province="NE", postal_code="",
                    unit_type="Ste", unit_number=unit)
                opener = MagicMock(return_value=io.BytesIO(json.dumps(payload).encode()))
                accepted = g.geocode(address, "fixture-only", reservation=reservation(), opener=opener)
                self.assertIsNotNone(accepted)
                self.assertEqual(accepted["results"][0]["address_components"]["unit_number"], unit)
                opener.assert_called_once()

    def test_provider_building_point_can_share_coordinates_across_suites(self):
        # Publisher street+building is verified; a provider may omit a suite.
        for unit_type, unit_number in [("Ste", "102"), (None, None), ("", ""),
                                       ("Ste", None), (None, "104"), ("Unit", "104")]:
            with self.subTest(unit_type=unit_type, unit_number=unit_number):
                payload = response()
                payload["results"][0]["address_components"].update(
                    number="10411", predirectional="", street="Portal", suffix="Rd",
                    city="La Vista", state_province="NE", postal_code="",
                    unit_type=unit_type, unit_number=unit_number)
                self.assertIsNotNone(g.verify(
                    payload, "10411 portal rd ste 104,la vista,ne"))


    def test_optional_empty_secondary_components_preserve_existing_building_match(self):
        for empty in (None, "", "  "):
            with self.subTest(empty=empty):
                payload = response()
                payload["results"][0]["address_components"].update(
                    unit_type=empty, unit_number=empty)
                self.assertIsNotNone(g.verify(payload, ADDRESS))

    def test_matching_suite_accepts_lower_confidence_and_top_ranked_point(self):
        address = "10411 portal rd ste 104,la vista,ne"
        payload = response()
        payload["results"][0]["address_components"].update(
            number="10411", predirectional="", street="Portal", suffix="Rd",
            city="La Vista", state_province="NE", postal_code="",
            unit_type="Ste", unit_number="104")
        for changes in ({"accuracy": .56}, {"accuracy_type": "range_interpolation"},
                        {"accuracy_type": "street_center"}):
            with self.subTest(changes=changes):
                candidate = copy.deepcopy(payload)
                candidate["results"][0].update(changes)
                self.assertIsNotNone(g.verify(candidate, address))
        for field, value in (("country", "CA"), ("state_province", "KS"), ("number", "10412")):
            with self.subTest(field=field):
                rejected = copy.deepcopy(payload)
                rejected["results"][0]["address_components"][field] = value
                self.assertIsNone(g.verify(rejected, address))
        for wrong_suite in (False, True):
            ranked = copy.deepcopy(payload)
            alternate = copy.deepcopy(ranked["results"][0])
            if wrong_suite:
                alternate["address_components"]["unit_number"] = "102"
            else:
                alternate["location"]["lat"] += .02
            ranked["results"].append(alternate)
            chosen = g.verify(ranked, address)
            self.assertIsNotNone(chosen)
            self.assertEqual(len(chosen["results"]), 1)
            self.assertEqual(chosen["results"][0]["location"], payload["results"][0]["location"])


    def test_live_postal_locality_difference_preserves_street_and_state(self):
        r = response()
        r["results"][0]["address_components"]["city"] = "Durham"
        self.assertIsNotNone(g.verify(r, ADDRESS))

    def test_exact_zip_qualified_address_is_verified(self):
        address = "11 W. Jones Street, Raleigh, NC 27601"
        self.assertEqual(g.expected_address_parts(address),
                         ("11 w jones st", "raleigh", "nc", "27601"))
        self.assertIsNotNone(g.verify(response(), address))
        # Current South Hill queue inputs have no ZIP and keep their old parts.
        for number in ("111", "225"):
            self.assertEqual(g.expected_address_parts(f"{number} e danville st,s hill,va"),
                             (f"{number} e danville st", "s hill", "va", ""))

    def test_different_supplied_zip_is_rejected(self):
        self.assertIsNone(g.verify(response(), "11 W. Jones Street, Raleigh, NC 27602"))

    def test_zip_plus_four_matches_exactly(self):
        r = response()
        r["results"][0]["address_components"]["postal_code"] = "27601-1234"
        address = "11 W. Jones Street, Raleigh, NC 27601-1234"
        self.assertEqual(g.expected_address_parts(address),
                         ("11 w jones st", "raleigh", "nc", "27601-1234"))
        self.assertIsNotNone(g.verify(r, address))
        self.assertIsNone(g.verify(r, "11 W. Jones Street, Raleigh, NC 27601-1235"))

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

    def test_geocodio_accepts_street_and_city_level_coordinates(self):
        for values in [{"accuracy": .12}, {"accuracy_type": "range_interpolation"},
                       {"accuracy_type": "nearest_rooftop_match"},
                       {"accuracy_type": "street_center"}]:
            with self.subTest(values=values):
                self.assertIsNotNone(g.verify(response(**values), ADDRESS))
        city = response(accuracy=.17, accuracy_type="place")
        city["results"][0]["address_components"].update(number="", street="", suffix="")
        self.assertIsNotNone(g.verify(city, ADDRESS))
        city["results"][0]["address_components"]["city"] = "Orlando"
        self.assertIsNone(g.verify(city, ADDRESS))
        for values in [{"accuracy_type": "county"}, {"accuracy_type": "state"},
                       {"accuracy": float("nan")}, {"accuracy": -0.1},
                       {"location": {"lat": float("inf"), "lng": 0}},
                       {"location": {"lat": True, "lng": 0}}]:
            self.assertIsNone(g.verify(response(**values), ADDRESS))
        for payload in [None, {}, {"results": []}, {"results": [None]}, {"results": "bad"}]:
            self.assertIsNone(g.verify(payload, ADDRESS))

    def test_santa_cruz_addresses_accept_real_provider_precision_tiers(self):
        woodhouse = response(accuracy=.65, accuracy_type="range_interpolation")
        woodhouse["results"][0]["address_components"].update(
            number="119", predirectional="", street="Madrone", suffix="St",
            city="Santa Cruz", state_province="CA", unit_type="", unit_number="")
        self.assertIsNotNone(g.verify(woodhouse, "119 madrone st,santa cruz,ca"))

        discretion = response(accuracy=.58, accuracy_type="nearest_rooftop_match")
        discretion["results"][0]["address_components"].update(
            number="2703", predirectional="", street="41st", suffix="Ave",
            city="Soquel", state_province="CA", unit_type="", unit_number="")
        self.assertIsNotNone(g.verify(discretion, "2703 41st ave ste a,soquel,ca"))
        discretion["results"][0]["address_components"]["state_province"] = "NY"
        self.assertIsNone(g.verify(discretion, "2703 41st ave ste a,soquel,ca"))

    def test_top_geocodio_candidate_wins_over_lower_ranked_alternatives(self):
        payload = response()
        payload["results"].append(copy.deepcopy(payload["results"][0]))
        payload["results"][1]["location"]["lat"] += .02
        payload["results"][1]["address_components"]["state_province"] = "VA"
        chosen = g.verify(payload, ADDRESS)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["results"][0]["location"], payload["results"][0]["location"])
        self.assertEqual(len(chosen["results"]), 1)


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


class GreatBritainValidationTests(unittest.TestCase):
    def test_full_postcode_normalization_and_standard_shapes(self):
        cases = {" cb58as ": "CB5 8AS", "m11ae": "M1 1AE", "B33 8TH": "B33 8TH",
                 "cr2  6xh": "CR2 6XH", "DN551PT": "DN55 1PT", "w1a0ax": "W1A 0AX",
                 "ec1a1bb": "EC1A 1BB", "gir0aa": "GIR 0AA"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(g.normalize_gb_postcode(value), expected)
        for value in (None, "", "CB5", "CB5 8A", "27601", "CB5-8AS", "CB5 8AS, UK", "CB5 8AAS"):
            with self.subTest(value=value):
                self.assertEqual(g.normalize_gb_postcode(value), "")

    def test_uk_components_keep_postcode_letters_and_do_not_require_us_state(self):
        self.assertEqual(g.expected_address_parts(GB_ADDRESS, "GB"),
                         ("park st", "cambridge", "", "CB5 8AS"))
        self.assertEqual(g.result_address_parts(gb_response()["results"][0], "GB"),
                         ("park st", "cambridge", "england", "CB5 8AS"))
        self.assertIsNotNone(g.verify(gb_response(), GB_ADDRESS, "GB"))
        for address in ("Park Street,Cambridge,CB5", "Park Street,Cambridge,27601",
                        "Park Street,Cambridge,CB5 8AS,GB", "Park Street,,CB5 8AS"):
            with self.subTest(address=address):
                self.assertIsNone(g.verify(gb_response(), address, "GB"))

    def test_reviewed_gb_parts_match_database_normalization_and_reject_nonphysical_inputs(self):
        self.assertEqual(g.gb_address_part("  ST. IVES  "), "st. ives")
        self.assertEqual(g.gb_address_part("  West Orchard Close  ", street=True), "west orchard cl")
        for value in ("", "A", "12", "Online room", "PO Box 12", "https://example.test",
                      "12/14 Park Street", "Park\nStreet", "<Park>", "Park,Street"):
            with self.subTest(value=value):
                self.assertEqual(g.gb_address_part(value, street=True), "")
        payload = gb_response(accuracy_type="point")
        payload["results"][0]["address_components"].update(number="12A", street="Orchard", suffix="Cl")
        self.assertIsNotNone(g.verify(payload, "12a Orchard Close Unit 4,Cambridge,CB5 8AS", "GB"))

    def test_country_is_explicit_and_cannot_cross_us_gb_or_unknown_boundaries(self):
        self.assertIsNone(g.verify(gb_response(), GB_ADDRESS))
        for country in (None, "", "US", "USA", "UK", "CA", {"name": "GB"}):
            payload = gb_response()
            payload["results"][0]["address_components"]["country"] = country
            with self.subTest(country=country):
                self.assertIsNone(g.verify(payload, GB_ADDRESS, "GB"))
        for country in (None, "", "UK", "CA"):
            with self.subTest(expected_country=country):
                self.assertIsNone(g.verify(gb_response(), GB_ADDRESS, country))

    def test_precise_points_bind_provided_number_street_and_nonconflicting_postcode(self):
        address = "12 Park Street,Cambridge,CB5 8AS"
        for kind in ("rooftop", "point"):
            payload = gb_response(accuracy_type=kind)
            payload["results"][0]["address_components"]["number"] = "12"
            self.assertIsNotNone(g.verify(payload, address, "GB"))
            for field, value in (("number", "13"), ("number", ""), ("street", "Garden"),
                                 ("postal_code", "CB5 8AT"), ("postal_code", "27601")):
                rejected = copy.deepcopy(payload)
                rejected["results"][0]["address_components"][field] = value
                with self.subTest(kind=kind, field=field, value=value):
                    self.assertIsNone(g.verify(rejected, address, "GB"))
            payload["results"][0]["address_components"]["postal_code"] = ""
            self.assertIsNotNone(g.verify(payload, address, "GB"))

    def test_street_approximations_preserve_existing_provider_precision_policy(self):
        for kind in ("street_center", "range_interpolation", "nearest_rooftop_match"):
            for postal in ("", "CB5 8AT", "CB5 8AS"):
                payload = gb_response(accuracy=.12, accuracy_type=kind)
                payload["results"][0]["address_components"]["postal_code"] = postal
                with self.subTest(kind=kind, postal=postal):
                    self.assertIsNotNone(g.verify(payload, GB_ADDRESS, "GB"))
                    payload["results"][0]["address_components"]["street"] = "Pavilion"
                    self.assertIsNone(g.verify(payload, GB_ADDRESS, "GB"))

    def test_postcode_allows_postal_town_alias_but_never_a_different_street(self):
        payload = gb_response()
        components = payload["results"][0]["address_components"]
        components["city"] = "Postal Town Alias"
        components["postal_code"] = "cb58as"
        self.assertIsNotNone(g.verify(payload, GB_ADDRESS, "GB"))
        components["street"] = "Pavilion"
        self.assertIsNone(g.verify(payload, GB_ADDRESS, "GB"))
        components["street"] = "Park"
        for postal in ("", "CB5 8AT", "CB5"):
            components["postal_code"] = postal
            self.assertIsNone(g.verify(payload, GB_ADDRESS, "GB"))

    def test_place_and_intersection_require_town_even_with_exact_postcode(self):
        for kind in ("place", "intersection"):
            for postal in ("", "CB5 8AT", "CB5 8AS"):
                payload = gb_response(accuracy=.1, accuracy_type=kind)
                payload["results"][0]["address_components"].update(street="", suffix="", postal_code=postal)
                with self.subTest(kind=kind, postal=postal):
                    self.assertIsNotNone(g.verify(payload, GB_ADDRESS, "GB"))
                    payload["results"][0]["address_components"]["city"] = "Ely"
                    self.assertIsNone(g.verify(payload, GB_ADDRESS, "GB"))
        for kind in ("county", "state"):
            self.assertIsNone(g.verify(gb_response(accuracy_type=kind), GB_ADDRESS, "GB"))

    def test_uk_request_uses_reserved_identity_country_and_normalized_postcode(self):
        address = "Park Street, Cambridge, cb58as"
        opener = MagicMock(return_value=io.BytesIO(json.dumps(gb_response()).encode()))
        accepted = g.geocode(address, "fixture-only", reservation=gb_reservation(address),
                             country_code="GB", opener=opener)
        self.assertIsNotNone(accepted)
        request = opener.call_args.args[0]
        self.assertEqual(parse_qs(urlparse(request.full_url).query),
                         {"q": ["Park Street,Cambridge,CB5 8AS"], "country": ["GB"], "limit": ["2"]})
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-only")
        self.assertEqual(opener.call_args.kwargs["timeout"], 8)
        self.assertNotIn("fixture-only", request.full_url)
        opener.assert_called_once()

    def test_uk_reservation_must_echo_exact_country_and_query_before_request(self):
        for reserved in (reservation(), {**gb_reservation(), "country_code": "US"},
                         {**gb_reservation(), "query_text": "Pavilion Street,Cambridge,CB5 8AS"}):
            opener = MagicMock()
            with self.subTest(reserved=reserved), self.assertRaisesRegex(g.GeocodeFailure, "^invalid_reservation$"):
                g.geocode(GB_ADDRESS, "fixture-only", reservation=reserved, country_code="GB", opener=opener)
            opener.assert_not_called()
        opener = MagicMock()
        address = "Park Street,Cambridge,CB5"
        with self.assertRaisesRegex(g.GeocodeFailure, "^invalid_request$"):
            g.geocode(address, "fixture-only", reservation=gb_reservation(address),
                      country_code="GB", opener=opener)
        opener.assert_not_called()

    def test_uk_authentication_and_country_access_errors_are_distinct_and_not_retried(self):
        for status, reason in ((401, "provider_auth"), (403, "provider_country_access")):
            opener = MagicMock(side_effect=HTTPError("https://example", status, "secret-sentinel", {}, None))
            with self.subTest(status=status), self.assertRaisesRegex(g.GeocodeFailure, "^" + reason + "$"):
                g.geocode(GB_ADDRESS, "fixture-only", reservation=gb_reservation(),
                          country_code="GB", opener=opener)
            opener.assert_called_once()


class CountryBoundWorkerTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.claim = {"venue_key": "key", "lease_id": "lease", "query_text": GB_ADDRESS,
                      "country_code": "GB"}
        self.reserved = gb_reservation()

    def db(self, action, payload):
        self.calls.append((action, copy.deepcopy(payload)))
        if action == "claim":
            return [self.claim]
        if action == "reserve":
            return self.reserved
        if action == "submit":
            return {"resolved": True, "events_updated": 1}
        return {"recorded": True}

    def test_v2_claim_rpc_is_token_authenticated_and_allowlisted(self):
        env = {"SUPABASE_URL": preview_worker.ROOMQUEST_DB,
               "SUPABASE_PUBLISHABLE_KEY": "fixture-only", "ROOMQUEST_COLLECTOR_TOKEN": "t" * 64}
        with patch.dict(os.environ, env), redirect_stdout(io.StringIO()):
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"[]")) as transport:
                self.assertEqual(g.rpc("claim", {"limit": 1}), [])
        request = transport.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/rpc/community_collector_geocoder_claim_v2"))
        self.assertEqual(json.loads(request.data), {"p_limit": 1, "p_token": "t" * 64})
        self.assertEqual(transport.call_args.kwargs["timeout"], 12)

    def test_country_binds_claim_reservation_provider_and_submit(self):
        provider = MagicMock(return_value=gb_response())
        with patch.dict(os.environ, ENV):
            result = g.run_batch(max_requests=1, database=self.db, provider=provider)
        self.assertEqual((result["attempted"], result["resolved"], result["events_updated"]), (1, 1, 1))
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "submit"])
        for _, payload in self.calls[1:]:
            self.assertEqual(payload["country_code"], "GB")
            self.assertEqual(payload["query_text"], GB_ADDRESS)
            self.assertEqual(payload["venue_key"], self.claim["venue_key"])
            self.assertEqual(payload["lease_id"], self.claim["lease_id"])
        provider.assert_called_once_with(GB_ADDRESS, "fixture-only", reservation=self.reserved, country_code="GB")

    def test_missing_unknown_country_and_malformed_country_address_never_reserve(self):
        cases = [{"country_code": None}, {"country_code": "UK"}, {"country_code": []},
                 {"country_code": "US"}, {"query_text": "Park Street,Cambridge,CB5"},
                 {"query_text": "Park Street,Cambridge,CB5 8AS,UK"}]
        for changes in cases:
            self.setUp()
            self.claim.update(changes)
            provider = MagicMock()
            with self.subTest(changes=changes), patch.dict(os.environ, ENV):
                result = g.run_batch(database=self.db, provider=provider)
            self.assertEqual(result["stop_reason"], "invalid_claim")
            self.assertEqual(result["attempted"], 0)
            self.assertEqual([action for action, _ in self.calls], ["claim"])
            provider.assert_not_called()

    def test_unbound_reservation_never_reaches_provider_or_submit(self):
        for reserved in (reservation(), {**gb_reservation(), "country_code": "US"},
                         {**gb_reservation(), "query_text": "Garden,Cambridge,CB5 8AS"}):
            self.setUp()
            self.reserved = reserved
            provider = MagicMock()
            with self.subTest(reserved=reserved), patch.dict(os.environ, ENV):
                result = g.run_batch(database=self.db, provider=provider)
            self.assertEqual(result["stop_reason"], "invalid_reservation")
            self.assertEqual(result["attempted"], 0)
            self.assertEqual([action for action, _ in self.calls], ["claim", "reserve"])
            provider.assert_not_called()

    def test_uk_access_denial_records_country_bound_hold_and_stops_batch(self):
        provider = MagicMock(side_effect=g.GeocodeFailure("provider_country_access"))
        with patch.dict(os.environ, ENV):
            result = g.run_batch(max_requests=10, database=self.db, provider=provider)
        self.assertEqual(result["stop_reason"], "provider_country_access")
        self.assertEqual((result["attempted"], result["errors"]), (1, 1))
        self.assertEqual([action for action, _ in self.calls], ["claim", "reserve", "fail"])
        self.assertEqual(self.calls[-1][1]["country_code"], "GB")
        self.assertEqual(self.calls[-1][1]["query_text"], GB_ADDRESS)
        self.assertEqual(self.calls[-1][1]["reason"], "provider_country_access")
        provider.assert_called_once()

    def test_uk_submit_diagnostic_retains_only_country_aware_validity_flags(self):
        diagnostic = g._submit_failure_diagnostic(
            {**self.claim, "request_id": "request-secret-sentinel"}, GB_ADDRESS, gb_response(),
            g.PreviewError("secret-sentinel"))
        self.assertTrue(diagnostic["country_valid"])
        self.assertTrue(diagnostic["postal_match"])
        self.assertTrue(diagnostic["street_match"])
        self.assertNotIn("sentinel", json.dumps(diagnostic))
        self.assertNotIn("Cambridge", json.dumps(diagnostic))
        self.assertNotIn("CB5", json.dumps(diagnostic))


class WorkerTests(unittest.TestCase):
    def test_production_cron_route_and_execution_budget(self):
        config = json.loads((Path(__file__).parents[1] / "vercel.json").read_text())
        self.assertIn({"path": "/api/geocode", "schedule": "* * * * *"}, config["crons"])
        self.assertIn({"src": "/api/geocode", "dest": "/api/geocode.py"}, config["routes"])
        self.assertEqual(config["functions"]["api/geocode.py"]["maxDuration"], 60)

    def db(self, action, payload):
        self.calls.append((action, payload))
        if action == "claim":
            return [{"venue_key": "key", "lease_id": "lease", "query_text": ADDRESS,
                     "country_code": "US"}]
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

    def provide(self, address, key, *, reservation, country_code):
        self.assertEqual(self.calls[-1][0], "reserve")
        self.assertEqual(country_code, "US")
        result = response()
        result["results"][0]["address_components"]["number"] = address.split()[0]
        return result

    def db(self, action, payload):
        self.calls.append((action, copy.deepcopy(payload)))
        if action == "claim":
            self.claim_count += 1
            return [{"venue_key": f"{self.claim_count:032x}",
                     "lease_id": f"lease-sensitive-sentinel-{self.claim_count}",
                     "country_code": "US",
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
            self.assertEqual(reserved, {name: submitted[name] for name in
                                       ("venue_key", "lease_id", "country_code")})
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
                 "country_code": "US",
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
