"""Focused claim/RPC adapter tests; no real publisher or DB requests."""
import ast
from copy import deepcopy
from hashlib import md5
from io import BytesIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from roomquest import spektrix_capture_transport as transport
from test_spektrix_capture_runner import Backend, SOURCE, PROFILE, STAMP


def pacing():
    return {'crawl_delay_seconds': 0, 'retry_after_seconds': 0, 'wait_unbounded': False}


class TransportTests(unittest.TestCase):
    def test_exact_claim_scoped_rpc_and_fetch_receipts(self):
        db = Backend(25)
        source = dict(SOURCE, action='collect', feedzilla_capture_version=2)
        source['source_key'] = 'municipal_' + md5(
            ('feed_registration:' + source['feed_url']).encode()).hexdigest()[:24]
        calls = []

        def rpc(name, payload, timeout):
            calls.append(name)
            self.assertEqual(timeout, 5 if name in (transport.YIELD, transport.NOTE_WAIT) else 8)
            self.assertEqual(payload['p_source_key'], source['source_key'])
            self.assertEqual(payload['p_category'], 'jsonld')
            self.assertEqual(payload['p_ticket'], 'test-lease')
            if name == transport.READ:
                return db.read()
            if name == transport.WRITE:
                self.assertEqual(payload['p_publisher_crawl_delay_seconds'], 1 if db.requests else 0)
                self.assertEqual(payload['p_publisher_retry_after_seconds'], 0)
                self.assertFalse(payload['p_publisher_wait_unbounded'])
                return db.write(payload['p_expected_revision'], payload['p_checkpoint'])
            if name == transport.SEAL:
                self.assertEqual(payload['p_previous_sha256'], db.envelope['sha256'])
                return db.seal(payload['p_expected_revision'], deepcopy(db.envelope),
                               payload['p_checkpoint'], payload['p_fetch_receipts'],
                               payload['p_members'])
            if name in (transport.YIELD, transport.VERIFY):
                self.assertEqual(payload['p_checkpoint_sha256'], db.envelope['sha256'])
                self.assertEqual(payload['p_expected_revision'], db.revision)
                if name == transport.YIELD:
                    return {'released': True, 'status': 'pending', 'revision': db.revision}
                return {'verified': True, 'revision': db.revision,
                        'expected_count': len(db.members), 'staged_count': len(db.rows),
                        'venue_count': 0}
            if name == transport.STAGE:
                self.assertEqual(payload['p_previous_sha256'], db.envelope['sha256'])
                return db.stage(payload['p_expected_revision'], deepcopy(db.envelope),
                                payload['p_checkpoint'], payload['p_events'])
            self.fail('Unexpected RPC ' + name)

        def fetch(url, accept, **kw):
            self.assertEqual(kw, {'respect_robots': True,
                                  'allowed_hosts': ('system.spektrix.com',),
                                  'follow_redirects': False, 'deadline_at': 30})
            state['crawl_delay_seconds'] = 1
            return db.fetch(url, accept)

        for _ in range(50):
            state = pacing()
            result = transport.run_claimed_capture(
                source, PROFILE, collection_context={'p_category': 'jsonld',
                                                     'p_ticket': 'test-lease'},
                rpc=rpc, fetch_publisher=fetch,
                convert=lambda source, snapshot: snapshot['events'],
                pacing=state, deadline_at=40, clock=lambda: STAMP,
                monotonic_clock=lambda: 1, max_steps=1)
            if result['status'] == 'verified':
                break
            self.assertTrue(result['lease_released'])
        self.assertEqual(result['status'], 'verified')
        self.assertFalse(result['lease_released'])
        self.assertEqual(result['record_count'], 25)
        self.assertEqual(calls.count(transport.STAGE), 2)
        self.assertEqual(calls.count(transport.SEAL), 1)
        self.assertEqual(calls.count(transport.VERIFY), 1)
        self.assertEqual(set(calls), {transport.READ, transport.WRITE, transport.SEAL, transport.STAGE,
                                      transport.YIELD, transport.VERIFY})

    def test_unnegotiated_claim_rejected_before_transport(self):
        def denied(*args, **kwargs):
            self.fail('Unauthorized callback')
        with self.assertRaisesRegex(ValueError, 'claim_required'):
            transport.run_claimed_capture(
                SOURCE, PROFILE, collection_context={'p_category': 'jsonld',
                                                     'p_ticket': 'test-lease'},
                rpc=denied, fetch_publisher=denied, convert=denied,
                pacing=pacing(), deadline_at=40, monotonic_clock=lambda: 1)

    def test_interrupted_fetch_persists_retry_after_without_progress(self):
        db = Backend(1)
        source = dict(SOURCE, action='collect', feedzilla_capture_version=2)
        source['source_key'] = 'municipal_' + md5(
            ('feed_registration:' + source['feed_url']).encode()).hexdigest()[:24]
        state = pacing()
        calls = []

        def rpc(name, payload, timeout):
            calls.append(name)
            if name == transport.READ:
                return db.read()
            if name == transport.WRITE:
                return db.write(payload['p_expected_revision'], payload['p_checkpoint'])
            if name == transport.NOTE_WAIT:
                self.assertEqual(payload['p_publisher_retry_after_seconds'], 123)
                return {'pacing_saved': True}
            self.fail('Unexpected RPC ' + name)

        def interrupted(*args, **kw):
            state['retry_after_seconds'] = 123
            raise OSError('publisher temporarily unavailable')

        with self.assertRaises(OSError):
            transport.run_claimed_capture(source, PROFILE,
                collection_context={'p_category': 'jsonld', 'p_ticket': 'test-lease'},
                rpc=rpc, fetch_publisher=interrupted,
                convert=lambda source, snapshot: snapshot['events'],
                pacing=state, deadline_at=40, clock=lambda: STAMP,
                monotonic_clock=lambda: 1)
        self.assertEqual(calls, [transport.READ, transport.WRITE, transport.NOTE_WAIT])
        self.assertEqual(db.revision, 1)

    def test_verification_receipt_cannot_be_replaced_by_a_count_guess(self):
        db = Backend(1)
        source = dict(SOURCE, action='collect', feedzilla_capture_version=2)
        source['source_key'] = 'municipal_' + md5(
            ('feed_registration:' + source['feed_url']).encode()).hexdigest()[:24]

        def rpc(name, payload, timeout):
            if name == transport.READ:
                return db.read()
            if name == transport.WRITE:
                return db.write(payload['p_expected_revision'], payload['p_checkpoint'])
            if name == transport.SEAL:
                return db.seal(payload['p_expected_revision'], deepcopy(db.envelope),
                               payload['p_checkpoint'], payload['p_fetch_receipts'], payload['p_members'])
            if name == transport.STAGE:
                return db.stage(payload['p_expected_revision'], deepcopy(db.envelope),
                                payload['p_checkpoint'], payload['p_events'])
            if name == transport.YIELD:
                return {'released': True, 'status': 'pending', 'revision': db.revision}
            if name == transport.VERIFY:
                return {'verified': True, 'revision': db.revision,
                        'expected_count': 1, 'staged_count': 0, 'venue_count': 0}
            self.fail('Unexpected RPC ' + name)

        with self.assertRaisesRegex(ValueError, 'verification_receipt_invalid'):
            for _ in range(50):
                transport.run_claimed_capture(source, PROFILE,
                    collection_context={'p_category': 'jsonld', 'p_ticket': 'test-lease'},
                    rpc=rpc, fetch_publisher=lambda url, accept, **kw: db.fetch(url, accept),
                    convert=lambda source, snapshot: snapshot['events'],
                    pacing=pacing(), deadline_at=40, clock=lambda: STAMP,
                    monotonic_clock=lambda: 1, max_steps=1)


class ScopedRpcLimitTests(unittest.TestCase):
    """Execute the exact existing RPC function, not unrelated parser imports."""
    def test_only_capture_read_gets_larger_response_ceiling(self):
        path = Path(__file__).resolve().parents[1] / 'roomquest' / 'preview_worker.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'supabase_rpc')

        class PreviewError(ValueError):
            pass

        root = 'https://example.invalid'
        namespace = dict(os=os, json=json, HTTPError=HTTPError, URLError=URLError,
                         ROOMQUEST_DB=root, PreviewError=PreviewError)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
        rpc = namespace['supabase_rpc']
        payload = json.dumps({'checkpoint': 'x' * 849000}).encode()

        def respond(request, timeout):
            self.assertEqual(timeout, 4)
            return BytesIO(payload)

        env = {'SUPABASE_URL': root, 'SUPABASE_PUBLISHABLE_KEY': 'test',
               'ROOMQUEST_COLLECTOR_TOKEN': 'a' * 64}
        with patch.dict(os.environ, env, clear=True), patch(
                'urllib.request.urlopen', side_effect=respond) as http:
            self.assertEqual(len(rpc(transport.READ, {})['checkpoint']), 849000)
            for operation in ('community_collector_claim_category',
                              transport.WRITE, transport.STAGE, transport.SEAL,
                              transport.NOTE_WAIT, transport.YIELD, transport.VERIFY):
                with self.assertRaisesRegex(PreviewError, 'database_unavailable'):
                    rpc(operation, {})
            with self.assertRaisesRegex(PreviewError, 'unsupported_collector_rpc'):
                rpc('community_collector_feedzilla_capture_other', {})
            self.assertEqual(http.call_count, 8)


if __name__ == '__main__':
    unittest.main()
