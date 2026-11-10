"""Recovery probes retain publisher guards, bounded scope and source holds."""
import contextlib
import hashlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

import roomquest
from scripts import capture_south_hill_recovery as audit


class PreviewError(ValueError):
    pass


class RecoveryAuditTest(unittest.TestCase):
    def setUp(self):
        self.worker = SimpleNamespace(
            PreviewError=PreviewError,
            preview_source=Mock(return_value={
                'p_error': None,
                'p_events': [{'image_url': 'https://publisher.example/public.jpg'}],
                'p_parser_capability': 'publisher_event_candidates_v1',
            }),
            fetch_publisher=Mock(return_value='PUBLIC_BODY_SENTINEL'),
        )
        self.worker_patch = patch.object(roomquest, 'preview_worker', self.worker, create=True)
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)
        self.halifax_patch = patch.object(audit, '_halifax_preview', return_value={
            'p_error': None, 'p_events': [{'image_url': 'https://publisher.example/public.jpg'}],
            'p_parser_capability': 'publisher_event_candidates_v1',
        })
        self.halifax_patch.start()
        self.addCleanup(self.halifax_patch.stop)
        self.stdout = io.StringIO()

    def run_audit(self, keys):
        with contextlib.redirect_stdout(self.stdout):
            return audit.audit(keys)

    def test_exact_cohort_endpoints_and_no_candidate_is_registered_by_probe(self):
        self.assertEqual(len(audit.SOURCES), 11)
        self.assertEqual({key for key, source in audit.SOURCES.items() if 'kind' in source}, {
            'south_hill_chamber_va', 'coopers_landing_clarksville_va',
            'mecklenburg_va_libraries', 'municipal_chambermaster_halifax_va',
            'discover_halifax_va', 'shady_shack_bracey_va',
        })
        result = self.run_audit(list(audit.SOURCES))
        self.assertTrue(result['complete'])
        self.assertFalse(result['collection_ready'])
        self.assertTrue(result['authoritative_state_unchanged'])
        self.assertEqual(result['counts']['parsed'], 6)
        self.assertEqual(result['counts']['fetched_unparsed'], 5)
        self.assertEqual(result['counts']['parsed_future_candidates'], 6)
        self.assertTrue(all(row['hold_cleared'] is False for row in result['sources']))
        pine = next(row for row in result['sources'] if row['source_key'] == 'pine_knot_farms')
        self.assertTrue(pine['candidate_only'])
        self.assertNotIn('candidate_count', pine)
        self.assertNotIn('source_id', pine)

    def test_candidate_fetches_keep_robots_and_exact_host_scope_without_body_output(self):
        keys = [key for key, source in audit.SOURCES.items() if 'kind' not in source]
        result = self.run_audit(keys)
        self.worker.preview_source.assert_not_called()
        self.assertEqual(self.worker.fetch_publisher.call_count, len(keys))
        for key, call in zip(keys, self.worker.fetch_publisher.call_args_list):
            self.assertEqual(call.args, (audit.SOURCES[key]['url'], 'text/html'))
            self.assertIs(call.kwargs['respect_robots'], True)
            self.assertEqual(call.kwargs['allowed_hosts'], (urlsplit(audit.SOURCES[key]['url']).hostname,))
            self.assertIn('deadline_at', call.kwargs)
        self.assertEqual(result['sources'][0]['body_sha256'], hashlib.sha256(b'PUBLIC_BODY_SENTINEL').hexdigest())
        self.assertNotIn('PUBLIC_BODY_SENTINEL', json.dumps(result) + self.stdout.getvalue())

    def test_existing_sources_use_preview_with_only_existing_source_contract(self):
        self.run_audit(['south_hill_chamber_va'])
        call = self.worker.preview_source.call_args
        self.assertEqual(call.args[0], {
            'source_key': 'south_hill_chamber_va',
            'feed_url': 'https://members.southhillchamber.com/calendar',
            'kind': 'html', 'platform_adapter': 'html',
            'timezone': 'America/New_York',
        })
        self.worker.fetch_publisher.assert_not_called()

    def test_local_dns_failure_is_distinct_from_publisher_denial(self):
        self.worker.fetch_publisher.side_effect = PreviewError('dns_unavailable')
        report = self.run_audit(['pine_knot_farms'])
        row = report['sources'][0]
        self.assertEqual(row['failure_category'], 'environment_dns')
        self.assertTrue(row['publisher_http_not_attempted'])
        self.assertNotIn('observed_http_status', row)
        self.assertEqual(report['counts']['environment_dns'], 1)
        self.assertFalse(report['complete'])

    def test_http_denial_keeps_status_without_error_text_or_any_retry(self):
        error = PreviewError('robots_denied')
        error.__cause__ = HTTPError('https://private.example/SECRET_URL', 403,
                                   'SECRET_MESSAGE', {'Authorization': 'SECRET_HEADER'}, None)
        self.worker.preview_source.side_effect = error
        report = self.run_audit(['coopers_landing_clarksville_va'])
        row = report['sources'][0]
        self.assertEqual(row['failure_category'], 'publisher_policy')
        self.assertEqual(row['observed_http_status'], 403)
        self.worker.preview_source.assert_called_once()
        self.assertNotIn('SECRET', json.dumps(report) + self.stdout.getvalue())

    def test_missing_runtime_dependency_does_not_become_a_publisher_failure(self):
        self.worker.preview_source.side_effect = ModuleNotFoundError('SECRET_MESSAGE', name='scrapers')
        report = self.run_audit(['south_hill_chamber_va'])
        row = report['sources'][0]
        self.assertEqual(row['failure_category'], 'environment_dependency')
        self.assertEqual(row['missing_module'], 'scrapers')
        self.assertEqual(report['counts']['environment_dependency'], 1)
        self.assertNotIn('observed_http_status', row)
        self.assertNotIn('SECRET', json.dumps(report) + self.stdout.getvalue())

    def test_retry_after_error_is_retained_without_an_audit_retry(self):
        self.worker.fetch_publisher.side_effect = PreviewError('publisher_rate_limited')
        report = self.run_audit(['shineforth_eventbrite'])
        self.assertEqual(report['sources'][0]['failure_category'], 'publisher_rate_limit')
        self.worker.fetch_publisher.assert_called_once()

    def test_incomplete_parser_outputs_never_report_a_successful_parse(self):
        for output in ({}, {'p_error': None, 'p_events': []},
                       {'p_error': None, 'p_events': [None]},
                       {'p_error': 'SECRET_URL /token', 'p_events': []}):
            with self.subTest(output=output):
                self.worker.preview_source.return_value = output
                report = self.run_audit(['south_hill_chamber_va'])
                self.assertFalse(report['complete'])
                self.assertEqual(report['sources'][0]['outcome'], 'blocked')
                self.assertNotIn('candidate_count', report['sources'][0])
                self.assertNotIn('SECRET_URL', json.dumps(report) + self.stdout.getvalue())

    def test_valid_empty_parser_output_remains_empty_without_clearing_hold(self):
        self.worker.preview_source.return_value['p_events'] = []
        report = self.run_audit(['south_hill_chamber_va'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['sources'][0]['candidate_count'], 0)
        self.assertFalse(report['sources'][0]['hold_cleared'])

    def test_overall_budget_prevents_later_probes_and_rejects_late_results(self):
        clock = [100.0]
        def preview(*args, **kwargs):
            clock[0] = 900.0
            return {'p_error': None, 'p_events': [],
                    'p_parser_capability': 'publisher_event_candidates_v1'}
        self.worker.preview_source.side_effect = preview
        with patch.object(audit, 'monotonic', side_effect=lambda: clock[0]):
            report = self.run_audit(['south_hill_chamber_va', 'pine_knot_farms'])
        self.worker.preview_source.assert_called_once()
        self.worker.fetch_publisher.assert_not_called()
        self.assertTrue(all(row['error'] == 'collection_deadline' for row in report['sources']))

    def test_shady_uses_real_parser_route_and_halifax_chamber_keeps_registered_contract(self):
        report = self.run_audit(['shady_shack_bracey_va', 'municipal_chambermaster_halifax_va'])
        self.assertEqual(report['counts']['parsed'], 2)
        shady, chamber = self.worker.preview_source.call_args_list
        self.assertEqual(shady.args[0]['source_key'], 'shady_shack_bracey_va')
        self.assertEqual(shady.args[0]['platform_adapter'], 'html')
        self.assertEqual(chamber.args[0], {
            'source_key': 'municipal_chambermaster_halifax_va',
            'feed_url': 'https://www.halifaxchamber.net/api/events',
            'kind': 'xml', 'platform_adapter': 'growthzone',
            'timezone': 'America/New_York',
        })
        self.worker.fetch_publisher.assert_not_called()

    def test_receipts_keep_public_candidates_but_no_transport_or_full_prose(self):
        self.worker.preview_source.return_value['p_events'] = [{
            'id': 'test:123', 'title': 'Public program', 'starts_at': '2026-11-12T23:00:00Z',
            'description': 'FULL_PROSE_SENTINEL', 'headers': {'Authorization': 'SECRET'},
            'publisher_details': {'age': '18+'},
        }]
        report = self.run_audit(['shady_shack_bracey_va'])
        self.assertEqual(report['sources'][0]['candidates'][0]['id'], 'test:123')
        self.assertNotIn('FULL_PROSE_SENTINEL', json.dumps(report) + self.stdout.getvalue())
        self.assertNotIn('SECRET', json.dumps(report) + self.stdout.getvalue())


class HalifaxReadOnlyChunksTest(unittest.TestCase):
    def setUp(self):
        from roomquest import discover_halifax
        self.tourism = discover_halifax
        self.worker = SimpleNamespace(PreviewError=PreviewError, fetch_publisher=Mock(return_value='BODY'))
        self.source = audit._source('discover_halifax_va', audit.SOURCES['discover_halifax_va'])
        self.stdout = io.StringIO()
        self.clock = patch.object(audit, 'monotonic', return_value=100.0)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def chunk(self, cursor, *, complete=False, events=None, count=8):
        return {'complete': complete, 'events': events or [], 'checkpoint': {
            'cursor': cursor, 'manifest_count': count, 'manifest_hash': 'a' * 64,
            'window_start': '2026-11-09', 'diagnostics': [], 'events': [],
        }}

    def test_all_chunks_use_same_guarded_transport_and_only_final_events_count(self):
        first, final = self.chunk(6), self.chunk(8, complete=True, events=[{'id': 'one'}])
        observed_checkpoints = []
        def collect(source, fetch, **kwargs):
            self.assertEqual(source, self.source)
            observed_checkpoints.append(kwargs['checkpoint'])
            fetch(self.tourism.URL, 'text/html')
            return first if len(observed_checkpoints) == 1 else final
        row = {}
        with patch.object(self.tourism, 'collect_chunk', side_effect=collect), contextlib.redirect_stdout(self.stdout):
            result = audit._halifax_preview(self.source, self.worker, 340.0, row)
        self.assertEqual(observed_checkpoints, [None, first['checkpoint']])
        self.assertEqual(result['p_events'], [{'id': 'one'}])
        self.assertTrue(row['snapshot_complete'])
        self.assertEqual(row['accounted_count'], 8)
        self.assertEqual(row['chunk_count'], 2)
        for call in self.worker.fetch_publisher.call_args_list:
            self.assertEqual(call.kwargs, {'respect_robots': True,
                                          'allowed_hosts': ('gohalifaxva.com',), 'deadline_at': 136.0})

    def test_failed_later_chunk_keeps_progress_but_never_reports_a_complete_snapshot(self):
        first, row = self.chunk(6), {}
        with patch.object(self.tourism, 'collect_chunk', side_effect=[first, PreviewError('robots_denied')]), \
                contextlib.redirect_stdout(self.stdout):
            with self.assertRaisesRegex(PreviewError, 'robots_denied'):
                audit._halifax_preview(self.source, self.worker, 340.0, row)
        self.assertFalse(row['snapshot_complete'])
        self.assertEqual(row['accounted_count'], 6)
        self.assertNotIn('candidate_count', row)

    def test_partial_event_leak_or_false_completion_are_not_parser_readiness(self):
        for result, code in ((self.chunk(6, events=[{'id': 'partial'}]), 'snapshot_partial_events_exposed'),
                             (self.chunk(6, complete=True), 'snapshot_completion_mismatch')):
            with self.subTest(code=code), patch.object(self.tourism, 'collect_chunk', return_value=result), \
                    contextlib.redirect_stdout(self.stdout):
                with self.assertRaisesRegex(PreviewError, code):
                    audit._halifax_preview(self.source, self.worker, 340.0, {})

    def test_no_progress_and_chunk_limit_stay_incomplete(self):
        first, row = self.chunk(6), {}
        with patch.object(self.tourism, 'collect_chunk', return_value=first), contextlib.redirect_stdout(self.stdout):
            with self.assertRaisesRegex(PreviewError, 'snapshot_no_progress'):
                audit._halifax_preview(self.source, self.worker, 340.0, row)
        self.assertFalse(row['snapshot_complete'])
        with patch.object(audit, 'MAX_HALIFAX_CHUNKS', 1), \
                patch.object(self.tourism, 'collect_chunk', return_value=first), \
                contextlib.redirect_stdout(self.stdout):
            with self.assertRaisesRegex(PreviewError, 'snapshot_chunk_limit'):
                audit._halifax_preview(self.source, self.worker, 340.0, {})


if __name__ == '__main__':
    unittest.main()
