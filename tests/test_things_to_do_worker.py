"""Pilot admission, bounded transport and authenticated scheduler checks."""
from http.server import HTTPServer
from hashlib import sha256
import json
import os
from threading import Thread
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.index import handler as EntrypointHandler
from api.things_to_do import handler
from roomquest import things_to_do_worker as worker
from roomquest import preview_worker as transport
from roomquest.publisher_pacing import observe_retry_after


def claim():
    key = "potomac-overlook-regional-park"
    return {
        "status": "claimed", "job_id": "23453960-4229-4b89-a29b-835d895b7c18",
        "lease_token": "62d1e480-7c0f-43b8-bbca-c43b771f1f03",
        "source_key": key,
        "page_url": f"https://www.novaparks.com/parks/{key}/things-to-do",
        "park_context": {
            "park_slug": key, "park_name": "Potomac Overlook Regional Park",
            "city": "Arlington", "state": "VA",
            "location_text": "Potomac Overlook Regional Park, Arlington, VA",
            "location_source_url": f"https://www.novaparks.com/parks/{key}",
        },
    }


def activity():
    return {
        "external_id": "novaparks:node:319", "title": "Hiking Trails",
        "source_url": claim()["page_url"] + "#node-319",
        "extracted_from_url": claim()["page_url"],
        "location_text": claim()["park_context"]["location_text"],
    }


class WorkerTests(unittest.TestCase):
    def setUp(self):
        def database(action, payload):
            if action == "claim":
                return claim()
            return {
            "status": "finished", "outcome": payload["status"], "accepted": 1, "inserted": 1,
            "updated": 0, "unchanged": 0, "skipped": 0, "enqueued": 0,
            }
        self.database = MagicMock(side_effect=database)
        self.fetch = MagicMock(return_value="<main>activity fixture</main>")
        self.parse = MagicMock(return_value=[activity()])
        self.discover = MagicMock(return_value=[])

    def run_worker(self, **kwargs):
        args = dict(database=self.database, fetch=self.fetch, parse=self.parse,
                    discover=self.discover)
        args.update(kwargs)
        return worker.run_batch(**args)

    def test_sparse_activity_stages_without_optional_fields_or_event_dates(self):
        result = self.run_worker()
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.database.call_args_list[0].args, ("claim", {}))
        payload = self.database.call_args.args[1]
        self.assertEqual(payload["activities"], [activity()])
        self.assertEqual(len(payload["content_hash"]), 64)
        self.assertNotIn("lease_token", result)

    def test_database_pressure_and_budget_outcomes_never_fetch(self):
        for status in worker.IDLE_STATUSES:
            with self.subTest(status=status):
                db = MagicMock(return_value={"status": status, "private": "not returned"})
                result = self.run_worker(database=db)
                self.assertEqual(result, {"status": status})
        self.fetch.assert_not_called()

    def test_unavailable_health_fails_closed(self):
        self.database.side_effect = RuntimeError("secret or response body")
        self.assertEqual(self.run_worker(), {"status": "paused_telemetry"})
        self.fetch.assert_not_called()

    def test_malformed_or_out_of_scope_claim_never_fetches(self):
        mutations = [
            {"page_url": "http://www.novaparks.com/parks/potomac-overlook-regional-park/things-to-do"},
            {"page_url": claim()["page_url"] + "?url=https://127.0.0.1"},
            {"page_url": claim()["page_url"] + "/../events"},
            {"page_url": claim()["page_url"] + "/%2e%2e"},
            {"page_url": claim()["page_url"].replace("www.", "user@www.")},
            {"page_url": claim()["page_url"] + "#node-319"},
            {"job_id": "not-a-uuid"}, {"lease_token": ""},
            {"source_key": "unapproved-park"},
            {"park_context": {"park_slug": "different-park"}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                candidate = {**claim(), **mutation}
                self.assertEqual(self.run_worker(database=MagicMock(return_value=candidate)),
                                 {"status": "invalid_claim"})
        self.fetch.assert_not_called()

    def test_slow_admission_releases_without_publisher_request(self):
        result = self.run_worker(clock=MagicMock(side_effect=[0, 1.6]))
        self.assertEqual(result["outcome"], "paused")
        self.assertEqual(result["error_code"], "slow_database_admission")
        self.fetch.assert_not_called()

    def test_publisher_rate_limit_preserves_wait_and_does_not_retry_in_process(self):
        def limited(url, **kwargs):
            observe_retry_after("90")
            raise transport.PreviewError("publisher_http_429")
        self.fetch.side_effect = limited
        result = self.run_worker()
        self.assertEqual(result["outcome"], "retry")
        self.assertEqual(self.database.call_args.args[1]["publisher_retry_after_seconds"], 90)
        self.assertEqual(self.fetch.call_count, 1)
        self.parse.assert_not_called()

    def test_access_denial_is_held_without_retry(self):
        self.fetch.side_effect = transport.PreviewError("robots_denied")
        self.assertEqual(self.run_worker()["outcome"], "held")
        self.assertEqual(self.fetch.call_count, 1)

    def test_expired_runtime_does_not_stage_partial_result(self):
        result = self.run_worker(clock=MagicMock(side_effect=[0, 0.1, 46]))
        self.assertEqual(result["outcome"], "retry")
        self.assertEqual(self.database.call_args.args[1]["activities"], [])

    def test_overflow_is_explicit_not_a_silent_partial_success(self):
        self.parse.return_value = [activity()] * 41
        result = self.run_worker()
        self.assertEqual(result["outcome"], "held")
        self.assertEqual(result["error_code"], "things_to_do_page_limit")

    def test_lost_finish_response_never_refetches_or_echoes_error(self):
        self.database.side_effect = [claim(), RuntimeError("private credentials")]
        result = self.run_worker()
        self.assertEqual(result["status"], "finish_unavailable")
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.database.call_count, 2)
        self.assertNotIn("private", str(result))

    def test_expired_or_recovered_lease_never_reports_requested_success(self):
        for receipt in ({"status": "lease_expired"},
                        {"status": "finished", "outcome": "lease_expired"}):
            with self.subTest(receipt=receipt):
                database = MagicMock(side_effect=[claim(), receipt])
                result = self.run_worker(database=database)
                self.assertNotEqual(result.get("outcome"), "success")
                self.assertIn("lease_expired", result.values())

    def test_missing_authoritative_outcome_is_not_success(self):
        result = self.run_worker(database=MagicMock(side_effect=[claim(), {"status": "finished"}]))
        self.assertEqual(result["status"], "finish_unavailable")

    def test_unexpected_parser_error_is_sanitized(self):
        self.parse.side_effect = RuntimeError("raw publisher HTML and secrets")
        result = self.run_worker()
        self.assertEqual(result["error_code"], "things_to_do_parser_unexpected")
        self.assertNotIn("raw publisher", str(self.database.call_args))

    def test_preview_and_local_process_cannot_start_real_work(self):
        with patch.dict(os.environ, {"VERCEL_ENV": "preview"}), patch.object(worker, "_rpc") as rpc:
            self.assertEqual(worker.run_batch(), {"status": "disabled_environment"})
            rpc.assert_not_called()

    def test_existing_transport_is_called_with_robots_and_no_redirects(self):
        with patch.object(worker, "fetch_publisher", return_value="ok") as fetch:
            self.assertEqual(worker._fetch(claim()["page_url"], deadline_at=45), "ok")
            self.assertEqual(fetch.call_args.kwargs, {
                "respect_robots": True, "allowed_hosts": ("www.novaparks.com",),
                "deadline_at": 45, "follow_redirects": False,
            })

    def test_only_the_reviewed_meadowlark_parent_url_is_admitted(self):
        parent = claim()
        parent["source_key"] = worker.PARENT_EVIDENCE_PARK
        parent["page_url"] = worker.PARENT_EVIDENCE_URL
        parent["park_context"] = {**parent["park_context"], "park_slug": worker.PARENT_EVIDENCE_PARK}
        self.assertTrue(worker._valid_claim(parent))
        for url in (worker.PARENT_EVIDENCE_URL + '/', worker.PARENT_EVIDENCE_URL + '?page=1',
                    worker.PARENT_EVIDENCE_URL + '#node-293', claim()["park_context"]["location_source_url"]):
            with self.subTest(url=url):
                self.assertFalse(worker._valid_claim({**parent, "page_url": url}))
        self.assertFalse(worker._valid_claim({**claim(), "page_url": worker.PARENT_EVIDENCE_URL}))

    def test_unchanged_html_is_reparsed_and_submits_newly_extracted_narrative(self):
        from tests.test_things_to_do_nova import detail
        admitted = claim()
        admitted["page_url"] += '/garden'
        raw = detail(body='An introductory description.',
                     extra='<div class="field--name-field-additional-content">Additional cultural exhibits.</div>')
        admitted["content_hash"] = sha256(raw.encode()).hexdigest()
        database = MagicMock(side_effect=[admitted, {"status": "finished", "outcome": "success"}])
        result = worker.run_batch(database=database, fetch=MagicMock(return_value=raw))
        self.assertEqual(result["outcome"], 'success')
        payload = database.call_args.args[1]
        self.assertEqual(payload['content_hash'], admitted['content_hash'])
        self.assertEqual(payload['activities'][0]['description'],
                         'An introductory description.\nAdditional cultural exhibits.')

    def test_parent_page_uses_the_real_parser_without_discovering_more_pages(self):
        from tests.test_things_to_do_nova import MEADOW, parent_page
        admitted = {**claim(), "source_key": MEADOW['park_slug'],
                    "page_url": MEADOW['location_source_url'], "park_context": MEADOW}
        database = MagicMock(side_effect=[admitted, {"status": "finished", "outcome": "success"}])
        fetch = MagicMock(return_value=parent_page('A rotating art display in the lobby.'))
        result = worker.run_batch(database=database, fetch=fetch)
        self.assertEqual(result['outcome'], 'success')
        self.assertEqual(fetch.call_count, 1)
        payload = database.call_args.args[1]
        self.assertEqual([row['external_id'] for row in payload['activities']], ['novaparks:node:293'])
        self.assertEqual(payload['discovered_urls'], [])


class EndpointTests(unittest.TestCase):
    def make_handler(self, headers=None, path="/api/things-to-do-pilot"):
        obj = object.__new__(handler)
        obj.path = path
        obj.headers = headers or {}
        obj.reply = MagicMock()
        return obj

    def test_only_authenticated_empty_get_can_run(self):
        for headers in ({}, {"Authorization": "Bearer wrong"},
                        {"Authorization": "Bearer fixture", "Content-Length": "3"}):
            with self.subTest(headers=headers), patch.dict(os.environ, {"CRON_SECRET": "fixture"}), \
                    patch("api.things_to_do.run_batch") as run:
                request = self.make_handler(headers)
                request.do_GET()
                run.assert_not_called()
                self.assertIn(request.reply.call_args.args[0], (400, 401))
        with patch.dict(os.environ, {"CRON_SECRET": "fixture"}), \
                patch("api.things_to_do.run_batch", return_value={"status": "idle"}) as run:
            request = self.make_handler({"Authorization": "Bearer fixture"})
            request.do_GET()
            run.assert_called_once_with()
            request.reply.assert_called_once_with(200, {"status": "idle"})

    def test_no_arbitrary_url_or_post_input(self):
        with patch("api.things_to_do.run_batch") as run:
            request = self.make_handler(path="/api/things-to-do-pilot?url=https://example.com")
            request.do_GET()
            self.assertEqual(request.reply.call_args.args[0], 404)
            request.do_POST()
            self.assertEqual(request.reply.call_args.args[0], 405)
            run.assert_not_called()


class EntrypointRouteTests(unittest.TestCase):
    """Exercise the configured api.index:handler over real local HTTP."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), EntrypointHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.root = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, *, path="/api/things-to-do-pilot", token=None, method="GET"):
        headers = {"Authorization": "Bearer " + token} if token else {}
        request = Request(self.root + path, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response), response.headers

    def test_missing_or_wrong_cron_auth_reaches_pilot_401_without_work(self):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-fixture"}), \
                patch("api.things_to_do.run_batch") as run:
            for token in (None, "wrong"):
                with self.subTest(token=token):
                    status, body, headers = self.request(token=token)
                    self.assertEqual((status, body), (401, {"error": "unauthorized"}))
                    self.assertEqual(headers["Cache-Control"], "no-store")
            run.assert_not_called()

    def test_authenticated_get_reaches_real_pilot_handler_once(self):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-fixture"}), \
                patch("api.things_to_do.run_batch", return_value={"status": "idle"}) as run:
            status, body, headers = self.request(token="cron-fixture")
            self.assertEqual((status, body), (200, {"status": "idle"}))
            self.assertEqual(headers["Cache-Control"], "no-store")
            run.assert_called_once_with()

    def test_post_is_405_without_starting_work(self):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-fixture"}), \
                patch("api.things_to_do.run_batch") as run:
            status, body, _ = self.request(token="cron-fixture", method="POST")
            self.assertEqual((status, body), (405, {"error": "method_not_allowed"}))
            run.assert_not_called()

    def test_query_path_is_404_without_falling_into_any_worker(self):
        with patch.dict(os.environ, {"CRON_SECRET": "cron-fixture"}), \
                patch("api.things_to_do.run_batch") as pilot, \
                patch("api.preview.collect_previews") as preview:
            for method in ("GET", "POST"):
                with self.subTest(method=method):
                    status, body, _ = self.request(
                        path="/api/things-to-do-pilot?url=https://example.com", token="cron-fixture", method=method)
                    self.assertEqual((status, body), (404, {"error": "not_found"}))
            pilot.assert_not_called()
            preview.assert_not_called()


class RedirectTests(unittest.TestCase):
    def response(self, status, location=None):
        response = MagicMock()
        response.status_code = status
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        if location:
            response.headers["Location"] = location
        response.encoding = "utf-8"
        response.iter_content.return_value = [b"<main>fixture</main>"]
        return response

    def test_pilot_does_not_follow_even_same_host_redirect(self):
        response = self.response(302, "https://www.novaparks.com/parks/other/things-to-do")
        with patch.object(transport, "validate_public_dns"), \
                patch.object(transport.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            session.get.return_value = response
            with self.assertRaisesRegex(transport.PreviewError, "redirect_blocked"):
                transport.fetch_publisher(claim()["page_url"], "text/html", follow_redirects=False)
            self.assertEqual(session.get.call_count, 1)
            response.close.assert_called()

    def test_existing_callers_keep_redirect_behavior(self):
        with patch.object(transport, "validate_public_dns"), \
                patch.object(transport.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = [self.response(302, "/destination"), self.response(200)]
            result = transport.fetch_publisher("https://example.com/first", "text/html")
            self.assertEqual(result, "<main>fixture</main>")
            self.assertEqual(session.get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
