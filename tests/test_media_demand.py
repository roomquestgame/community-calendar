"""The ticketed image lane drains safely beyond one three-item wave."""
import io
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from roomquest import event_media as images
from roomquest import media_worker as worker
from roomquest.preview_worker import PreviewError

TICKET = '00000000-0000-0000-0000-000000000001'
WORKER_LEASE = '00000000-0000-0000-0000-000000000002'
PHOTO = 'https://cdn.example.org/event-photo.jpg'


def claim(index):
    return {'media_key': 'vsp:' + str(index), 'lease_id': 'item-lease-' + str(index),
            'candidate_only': True, 'candidate_url': PHOTO,
            'event_url': 'https://www.dcr.virginia.gov/state-parks/event?id=' + str(index),
            'title': 'A publisher event'}


def result(item):
    return {'image_url': PHOTO, 'mime_type': 'image/jpeg', 'evidence_url': item['event_url']}


class Database:
    """Model only the observable ticket/lease protocol, not its SQL internals."""

    def __init__(self, count=1, **config):
        self.config = {'worker_lease_id': WORKER_LEASE, 'concurrency': 5,
                       'per_host_concurrency': 3, 'budget_seconds': 40,
                       'host_backoffs': {}, **config}
        self.pending = [claim(index) for index in range(count)]
        self.active = {}
        self.calls = []
        self.lock = threading.Lock()
        self.acknowledge = True
        self.finish_acknowledged = True
        self.raise_action = None
        self.after_claim = None
        self.capacity_violations = []

    def __call__(self, action, payload, *, timeout=4):
        with self.lock:
            self.calls.append((action, payload, timeout))
            if action == self.raise_action:
                raise PreviewError('database_unavailable')
            if action == 'start':
                return self.config
            assert payload['ticket'] == TICKET
            assert payload['worker_lease_id'] == WORKER_LEASE
            if action == 'claim':
                capacity = min(10, self.config['concurrency']) - len(self.active)
                if not 0 < payload['limit'] <= capacity:
                    self.capacity_violations.append((payload['limit'], capacity))
                items = self.pending[:payload['limit']]
                del self.pending[:payload['limit']]
                self.active.update((item['media_key'], item['lease_id']) for item in items)
                if self.after_claim:
                    self.after_claim()
                return items
            if action in ('submit', 'fail', 'defer'):
                assert self.active.pop(payload['media_key']) == payload['lease_id']
                return {'recorded': self.acknowledge}
            if action == 'finish':
                self.active.clear()
                return {'recorded': self.finish_acknowledged}
            raise AssertionError('Unexpected action')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'VERCEL_ENV': 'production',
                                                   'FORWARD_GEOCODER_ENABLED': 'false'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.output = patch('sys.stdout', new_callable=io.StringIO)
        self.captured = self.output.start()
        self.addCleanup(self.output.stop)

    def test_rolling_drain_processes_more_than_three_with_five_concurrent_slots(self):
        db = Database(count=13)
        barrier = threading.Barrier(5)
        lock = threading.Lock()
        state = {'started': 0, 'active': 0, 'peak': 0}

        def resolve(item, **kwargs):
            with lock:
                state['started'] += 1
                number = state['started']
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            if number <= 5:
                barrier.wait(timeout=3)
            with lock:
                state['active'] -= 1
            return result(item)

        stats = worker.collect_media(TICKET, database=db, resolver=resolve, clock=lambda: 0)
        self.assertEqual(stats['claimed'], 13)
        self.assertEqual(stats['ready'], 13)
        self.assertEqual(stats['outcome'], 'complete')
        self.assertEqual(stats['peak_inflight'], 5)
        self.assertEqual(state['peak'], 5)
        self.assertEqual(db.capacity_violations, [])
        self.assertGreater(len([c for c in db.calls if c[0] == 'claim']), 1)
        self.assertEqual(db.calls[0][1], {'ticket': TICKET, 'worker_version': 'media_demand_v1',
                                        'candidate_only_version': 'publisher_event_html_v2',
                                        'publisher_candidates_version': 'publisher_event_candidates_v1'})
        self.assertEqual(db.calls[-1][0], 'finish')

    def test_database_concurrency_is_clamped_at_ten(self):
        db = Database(count=11, concurrency=50)
        stats = worker.collect_media(TICKET, database=db, resolver=lambda item, **kw: result(item), clock=lambda: 0)
        self.assertEqual(stats['ready'], 11)
        self.assertEqual(db.calls[1][1]['limit'], 10)
        self.assertLessEqual(stats['peak_inflight'], 10)
        self.assertEqual(db.capacity_violations, [])

    def test_each_thread_reuses_its_own_session_and_closes_it(self):
        db = Database(count=6, concurrency=1)
        session = MagicMock()
        used = []
        def resolve(item, **kwargs):
            used.append((threading.get_ident(), kwargs['session']))
            return result(item)
        with patch.object(worker.requests, 'Session', return_value=session) as factory:
            stats = worker.collect_media(TICKET, database=db, resolver=resolve, clock=lambda: 0)
        self.assertEqual(stats['ready'], 6)
        factory.assert_called_once_with()
        self.assertEqual(len({thread for thread, _ in used}), 1)
        self.assertTrue(all(s is session for _, s in used))
        session.close.assert_called_once_with()

    def test_nonproduction_does_not_consume_ticket(self):
        db = MagicMock()
        with patch.dict(os.environ, {'VERCEL_ENV': 'preview'}):
            stats = worker.collect_media(TICKET, database=db)
        db.assert_not_called()
        self.assertEqual(stats['stop_reason'], 'disabled')

    def test_rejected_or_replayed_ticket_never_claims_or_probes(self):
        for denied in (None, {}):
            db = MagicMock(return_value=denied)
            resolve = MagicMock()
            stats = worker.collect_media(TICKET, database=db, resolver=resolve)
            self.assertEqual(stats['stop_reason'], 'not_admitted')
            self.assertEqual(db.call_count, 1)
            resolve.assert_not_called()

    def test_insufficient_budget_does_not_claim(self):
        db = Database(budget_seconds=10)
        stats = worker.collect_media(TICKET, database=db, clock=lambda: 0)
        self.assertEqual([call[0] for call in db.calls], ['start', 'finish'])
        self.assertEqual(stats['outcome'], 'budget')
        self.assertEqual(stats['claimed'], 0)

    def test_budget_consumed_by_claim_defers_without_starting_probe(self):
        now = [0]
        db = Database()
        db.after_claim = lambda: now.__setitem__(0, 29)
        resolve = MagicMock()
        stats = worker.collect_media(TICKET, database=db, resolver=resolve, clock=lambda: now[0])
        resolve.assert_not_called()
        deferred = next(payload for action, payload, _ in db.calls if action == 'defer')
        self.assertEqual(deferred['reason'], 'deadline')
        self.assertFalse(deferred['attempted'])
        self.assertEqual(stats['deferred'], 1)
        self.assertEqual(stats['outcome'], 'budget')
        self.assertFalse(any(action == 'fail' for action, _, _ in db.calls))

    def test_transient_result_is_deferred_not_recorded_as_no_image(self):
        db = Database()
        error = images.MediaDeferred('transient_http', host='www.CDN.example.org.',
                                     retry_after_seconds=120, attempted=True)
        stats = worker.collect_media(TICKET, database=db,
                                     resolver=MagicMock(side_effect=error), clock=lambda: 0)
        deferred = next(payload for action, payload, _ in db.calls if action == 'defer')
        self.assertEqual(deferred['host'], 'cdn.example.org')
        self.assertEqual(deferred['retry_after_seconds'], 120)
        self.assertTrue(deferred['attempted'])
        self.assertEqual(stats['deferred'], 1)
        self.assertEqual(stats['unavailable'], 0)
        self.assertFalse(any(action == 'fail' for action, _, _ in db.calls))

    def test_unavailable_requires_completed_negative_resolution(self):
        db = Database()
        stats = worker.collect_media(TICKET, database=db, resolver=lambda *a, **kw: None, clock=lambda: 0)
        failed = next(payload for action, payload, _ in db.calls if action == 'fail')
        self.assertEqual(failed['reason'], 'no_event_image')
        self.assertEqual(stats['unavailable'], 1)
        self.assertEqual(stats['deferred'], 0)

    def test_false_acknowledgement_is_not_counted_as_ready(self):
        db = Database()
        db.acknowledge = False
        stats = worker.collect_media(TICKET, database=db, resolver=lambda item, **kw: result(item), clock=lambda: 0)
        self.assertEqual(stats['ready'], 0)
        self.assertEqual(stats['unrecorded'], 1)
        self.assertEqual(stats['errors'], 1)
        self.assertFalse(any(action == 'fail' for action, _, _ in db.calls))

    def test_result_cannot_replace_the_claimed_identity(self):
        db = Database()
        def resolve(item, **kwargs):
            return {**result(item), 'media_key': 'unclaimed', 'lease_id': 'unclaimed'}
        stats = worker.collect_media(TICKET, database=db, resolver=resolve, clock=lambda: 0)
        self.assertEqual(stats['ready'], 1)
        submitted = next(payload for action, payload, _ in db.calls if action == 'submit')
        self.assertEqual(submitted['media_key'], 'vsp:0')
        self.assertEqual(submitted['lease_id'], 'item-lease-0')

    def test_lost_submit_acknowledgement_finishes_without_terminal_failure(self):
        db = Database(count=1, concurrency=1)
        db.raise_action = 'submit'
        stats = worker.collect_media(TICKET, database=db, resolver=lambda item, **kw: result(item), clock=lambda: 0)
        self.assertEqual(stats['outcome'], 'failed')
        self.assertEqual(stats['ready'], 0)
        self.assertEqual(stats['unrecorded'], 1)
        self.assertEqual(db.calls[-1][0], 'finish')
        self.assertEqual(db.active, {})
        self.assertFalse(any(action == 'fail' for action, _, _ in db.calls))

    def test_claim_failure_still_releases_the_worker_once(self):
        db = Database()
        db.raise_action = 'claim'
        with self.assertRaises(PreviewError):
            worker.collect_media(TICKET, database=db, clock=lambda: 0)
        finishes = [payload for action, payload, _ in db.calls if action == 'finish']
        self.assertEqual(len(finishes), 1)
        self.assertEqual(finishes[0]['outcome'], 'failed')

    def test_unconfirmed_finish_is_reported_as_a_worker_error(self):
        db = Database(count=0)
        db.finish_acknowledged = False
        with self.assertRaisesRegex(PreviewError, 'media_finish_unconfirmed'):
            worker.collect_media(TICKET, database=db, clock=lambda: 0)
        self.assertEqual(len([action for action, _, _ in db.calls if action == 'finish']), 1)
        self.assertIn('finish_error', self.captured.getvalue())

    def test_lane_does_not_probe_legacy_page_fallback_claims(self):
        db = Database()
        db.pending[0]['candidate_only'] = False
        resolve = MagicMock()
        stats = worker.collect_media(TICKET, database=db, resolver=resolve, clock=lambda: 0)
        resolve.assert_not_called()
        self.assertEqual(stats['outcome'], 'failed')
        self.assertEqual(stats['deferred'], 1)

    def test_backend_backoff_is_forwarded_to_claim_exclusion(self):
        db = Database(count=0, host_backoffs={'www.CDN.example.org.': 90})
        worker.collect_media(TICKET, database=db, clock=lambda: 0)
        self.assertEqual(db.calls[1][1]['exclude_hosts'], ['cdn.example.org'])

    def test_logs_contain_counters_without_tickets_or_publisher_data(self):
        db = Database()
        worker.collect_media(TICKET, database=db, resolver=lambda item, **kw: result(item), clock=lambda: 0)
        output = self.captured.getvalue()
        self.assertIn('collector_media_run', output)
        self.assertIn('elapsed_ms', output)
        for private in (TICKET, WORKER_LEASE, PHOTO, 'A publisher event', 'item-lease'):
            self.assertNotIn(private, output)


class HostLimitTests(unittest.TestCase):
    def test_same_host_aliases_share_one_concurrency_limit(self):
        limiter = worker.HostLimiter(3, clock=lambda: 0)
        with limiter.request('www.CDN.example.org.'), limiter.request('cdn.example.org'), limiter.request('CDN.example.org'):
            self.assertEqual(limiter.excluded_hosts(), ['cdn.example.org'])
            with self.assertRaises(images.MediaDeferred) as error:
                with limiter.request('cdn.example.org'):
                    self.fail('Fourth request admitted')
            self.assertEqual(error.exception.reason, 'host_busy')
            with limiter.request('different.example.org'):
                pass
        self.assertEqual(limiter.excluded_hosts(), [])
        with limiter.request('cdn.example.org'):
            pass

    def test_backoff_persists_until_deadline_and_exclusion_is_bounded(self):
        now = [0]
        limiter = worker.HostLimiter(3, backoffs={'cdn.example.org': 60}, clock=lambda: now[0])
        with self.assertRaises(images.MediaDeferred):
            with limiter.request('www.cdn.example.org'):
                pass
        now[0] = 61
        with limiter.request('cdn.example.org'):
            pass
        for index in range(200):
            limiter.backoff(str(index) + '.example.org', 30)
        self.assertEqual(len(limiter.excluded_hosts()), 128)

    def test_redirect_target_obeys_persisted_backoff_before_http_request(self):
        first = MagicMock()
        first.status_code = 302
        first.headers = {'Location': 'https://other.example.org/event-photo.jpg'}
        first.__enter__.return_value = first
        session = MagicMock()
        session.get.return_value = first
        limiter = worker.HostLimiter(3, backoffs={'other.example.org': 60})
        with patch.object(images, 'validate_public_dns') as dns:
            with self.assertRaises(images.MediaDeferred) as error:
                images.probe_image(PHOTO, session=session, host_limiter=limiter)
        self.assertEqual(error.exception.reason, 'host_busy')
        self.assertTrue(error.exception.attempted)
        session.get.assert_called_once()
        self.assertEqual([call.args[0] for call in dns.call_args_list],
                         ['cdn.example.org', 'other.example.org'])

    def test_temporary_http_codes_preserve_retry_after(self):
        for status in (408, 429, 500, 502, 503):
            response = MagicMock()
            response.status_code = status
            response.headers = {'Retry-After': '120'}
            response.__enter__.return_value = response
            session = MagicMock()
            session.get.return_value = response
            limiter = worker.HostLimiter(3)
            with patch.object(images, 'validate_public_dns'):
                with self.assertRaises(images.MediaDeferred) as error:
                    images.probe_image(PHOTO, session=session, host_limiter=limiter)
            self.assertEqual(error.exception.reason, 'transient_http')
            self.assertEqual(error.exception.retry_after_seconds, 120)
            self.assertTrue(error.exception.attempted)
            self.assertEqual(limiter.excluded_hosts(), ['cdn.example.org'])
            response.iter_content.assert_not_called()

    def test_expired_probe_does_not_become_no_image(self):
        session = MagicMock()
        with self.assertRaises(images.MediaDeferred) as error:
            images.probe_image(PHOTO, session=session, deadline=0, clock=lambda: 0)
        self.assertEqual(error.exception.reason, 'deadline')
        self.assertFalse(error.exception.attempted)
        session.get.assert_not_called()

    def test_retry_after_is_bounded(self):
        self.assertEqual(images.retry_after_seconds('900000'), 3600)
        self.assertEqual(images.retry_after_seconds('0'), 1)
        self.assertEqual(images.retry_after_seconds('not a date'), 60)


class DeploymentCompatibilityTests(unittest.TestCase):
    def test_old_backend_capability_error_keeps_legacy_path(self):
        with patch.dict(os.environ, {'VERCEL_ENV': 'production', 'FORWARD_GEOCODER_ENABLED': 'true'}), \
                patch.object(images, 'rpc', side_effect=PreviewError('database_unavailable')):
            self.assertFalse(images.dedicated_media_ready())

    def test_only_exact_activated_capability_skips_legacy_path(self):
        with patch.dict(os.environ, {'VERCEL_ENV': 'production', 'FORWARD_GEOCODER_ENABLED': 'true'}):
            for answer in (None, [], {}, {'dedicated_ready': False}, {'dedicated_ready': 'true'}):
                with patch.object(images, 'rpc', return_value=answer):
                    self.assertFalse(images.dedicated_media_ready())
            with patch.object(images, 'rpc', return_value={'dedicated_ready': True}):
                self.assertTrue(images.dedicated_media_ready())

    def test_activation_skips_old_photo_runtime_but_preserves_geocoding(self):
        from roomquest import forward_geocoder, venue_resolver
        for ready in (False, True):
            with patch('datetime.datetime') as date, \
                    patch.object(forward_geocoder, 'run_batch', return_value={'claimed': 1}) as geocode, \
                    patch.object(images, 'dedicated_media_ready', return_value=ready), \
                    patch.object(images, 'run_batch', return_value={'claimed': 3}) as legacy:
                date.now.return_value.timestamp.return_value = 120  # Phase two.
                answer = venue_resolver.run_pipeline()
            geocode.assert_called_once()
            self.assertEqual(answer['geocoder'], {'claimed': 1})
            if ready:
                legacy.assert_not_called()
                self.assertEqual(answer['photos']['stop_reason'], 'dedicated_worker')
            else:
                legacy.assert_called_once_with()
                self.assertEqual(answer['photos'], {'claimed': 3})


if __name__ == '__main__':
    unittest.main()
