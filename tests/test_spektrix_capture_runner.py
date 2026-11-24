"""Exercise actual compressed captures across independent simulated leases."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from roomquest import feedzilla_capture_store as store
from roomquest import feedzilla_pagination_checkpoint as progress
from roomquest import spektrix_capture_plan as planner
from roomquest import spektrix_capture_runner as runner

STAMP = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
SOURCE = {'source_key': 'municipal_test_runner', 'kind': 'json',
          'feed_url': 'https://system.spektrix.com/testclient/api/v3/events',
          'platform_adapter': 'spektrix'}
PROFILE = {'client': 'testclient', 'ready_for_registration': True,
           'country': 'GB', 'timezone': 'Europe/London', 'home_city': 'London',
           'publisher_url': 'https://theatre.example/events', 'event_urls': {}}
EVENT = 'event-1234567890'
PLAN = 'plan-1234567890'
VENUE = 'venue-1234567890'


class Backend:
    """A test-only atomic CAS/row receipt store, not a live Supabase mock test."""
    def __init__(self, count=25):
        self.revision = 0
        self.envelope = None
        self.requests = []
        self.rows = {}
        self.batches = []
        self.members = None
        self.fetch_receipts = None
        self.count = count

    def read(self):
        return {'revision': self.revision, 'checkpoint': deepcopy(self.envelope)}

    def write(self, revision, envelope):
        assert revision == self.revision
        self.revision += 1
        self.envelope = deepcopy(envelope)
        return {'checkpoint_saved': True, 'revision': self.revision}

    def seal(self, revision, previous, updated, receipts, members):
        assert previous == self.envelope and revision == self.revision
        assert self.members is None
        assert len(receipts) == len(self.requests)
        self.fetch_receipts = deepcopy(receipts)
        self.members = deepcopy(members)
        return dict(self.write(revision, updated), sealed_count=len(members))

    def stage(self, revision, previous, updated, rows):
        assert previous == self.envelope and revision == self.revision
        assert self.members is not None
        assert [{k: row[k] for k in ('id', 'starts_at', 'event_url')} for row in rows] == self.members[len(self.rows):len(self.rows)+len(rows)]
        for row in rows:
            self.rows[(row['id'], row['starts_at'])] = row
        self.batches.append(len(rows))
        return dict(self.write(revision, updated), staged_count=len(rows))

    def fetch(self, url, accept):
        assert accept == 'application/json'
        self.requests.append(url)
        path = urlsplit(url)
        if path.path.endswith('/venues'):
            return json.dumps([{'id': VENUE, 'name': 'Test Theatre',
                                'address': '12 Stage Lane, London'}])
        if path.path.endswith('/plans/' + PLAN):
            return json.dumps({'id': PLAN, 'venue': {'id': VENUE}})
        qs = parse_qs(path.query)
        dates = sorted(v[0] for v in qs.values())
        selected = []
        for idx in range(self.count):
            clock = STAMP + timedelta(days=idx+1, hours=7)
            if dates[0] <= clock.date().isoformat() <= dates[1]:
                selected.append({'id': 'instance-%012d' % idx,
                                 'event': {'id': EVENT}, 'planId': PLAN,
                                 'cancelled': False, 'isOnSale': True,
                                 'start': clock.replace(tzinfo=None).isoformat(),
                                 'startUtc': clock.isoformat()})
        if path.path.endswith('/instances'):
            return json.dumps(selected)
        if path.path.endswith('/events'):
            return json.dumps([{'id': EVENT, 'name': 'Fixture Concert',
                                'duration': 60, 'webUrl':
                                'https://theatre.example/events/concert'}] if selected else [])
        raise AssertionError(url)

    def run(self, **overrides):
        args = dict(read=self.read, write=self.write, fetch=self.fetch,
                    convert=lambda source, snapshot: snapshot['events'],
                    seal=self.seal, stage_and_save=self.stage, can_continue=lambda: True,
                    clock=lambda: STAMP, max_steps=1)
        args.update(overrides)
        return runner.run_slice(SOURCE, PROFILE, **args)

    def finish(self):
        for _ in range(50):
            result = self.run()
            if result['status'] == 'staged':
                return result
        raise AssertionError('never finished')


class RunnerTests(unittest.TestCase):
    def test_60_day_capture_resumes_and_stages_without_repeated_gets(self):
        db = Backend()
        first = db.run()
        self.assertEqual(first['status'], 'pending')
        self.assertEqual(len(db.requests), 1)
        result = db.finish()
        self.assertEqual(result['record_count'], 25)
        self.assertEqual(result['staged_count'], 25)
        self.assertEqual(db.batches, [20, 5])
        self.assertEqual(len(db.members), 25)
        self.assertEqual(len(db.fetch_receipts), 20)
        self.assertEqual(len(db.requests), 20)  # 9*2 dates + venues + real plan
        self.assertEqual(len(set(db.requests)), 20)
        self.assertEqual(len(db.rows), 25)
        state = store.decode(SOURCE, db.envelope, at=STAMP)
        self.assertEqual(state['progress']['window_start'], '2026-11-24')
        self.assertEqual(state['progress']['window_end'], '2027-01-22')
        self.assertEqual(db.run()['staged_this_slice'], 0)
        self.assertEqual(db.batches, [20, 5])

    def test_empty_complete_window_needs_no_fake_plan_request(self):
        db = Backend(0)
        result = db.finish()
        self.assertEqual(result['status'], 'staged')
        self.assertEqual(result['record_count'], 0)
        self.assertEqual(db.batches, [])
        self.assertEqual(db.members, [])
        self.assertEqual(len(db.fetch_receipts), 19)
        self.assertEqual(len(db.requests), 19)
        self.assertTrue(store.ready_to_publish(SOURCE, db.envelope, at=STAMP))

    def test_short_seal_ack_stops_before_stage(self):
        db = Backend(1)
        while db.run()['phase'] != 'project':
            pass
        revision = db.revision
        with self.assertRaisesRegex(ValueError, 'seal_receipt_invalid'):
            db.run(seal=lambda *args: {
                'checkpoint_saved': True, 'revision': revision + 1,
                'sealed_count': 0})
        self.assertIsNone(db.members)
        self.assertFalse(db.rows)

    def test_sealed_membership_cap_is_not_silent_truncation(self):
        db = Backend(1)
        while db.run()['phase'] != 'project':
            pass
        with self.assertRaisesRegex(ValueError, 'sealed_membership_limit'):
            db.run(convert=lambda source, snapshot: [
                dict(snapshot['events'][0], id='fixture-%04d' % i)
                for i in range(501)])
        self.assertIsNone(db.members)

    def test_bad_stage_receipt_does_not_advance_local_or_durable_cursor(self):
        db = Backend(1)
        while db.run()['phase'] != 'stage':
            pass
        revision = db.revision
        with self.assertRaisesRegex(ValueError, 'write_receipt_invalid'):
            db.run(stage_and_save=lambda *args: {
                'checkpoint_saved': True, 'revision': revision+1,
                'staged_count': 0})
        self.assertEqual(db.revision, revision)
        self.assertEqual(store.decode(SOURCE, db.envelope, at=STAMP)['stage_cursor'], 0)

    def test_lost_atomic_stage_reply_is_recovered_from_durable_cursor(self):
        db = Backend()
        while db.run()['phase'] != 'stage':
            pass

        def lost(*args):
            db.stage(*args)
            raise OSError('response lost after transaction committed')

        with self.assertRaises(OSError):
            db.run(stage_and_save=lost)
        self.assertEqual(db.finish()['record_count'], 25)
        self.assertEqual(db.batches, [20, 5])

    def test_foreign_same_host_task_rejected_before_get(self):
        db = Backend()
        db.run()
        state = store.decode(SOURCE, db.envelope, at=STAMP)
        p = state['progress']
        p['tasks'][p['cursor']] = p['tasks'][p['cursor']].replace(
            '/testclient/', '/otherclient/')
        p['plan_sha256'] = progress._digest(p['tasks'])
        db.envelope = store.encode(SOURCE, state, at=STAMP)
        seen = list(db.requests)
        with self.assertRaisesRegex(ValueError, 'manifest_invalid'):
            db.run()
        self.assertEqual(db.requests, seen)

    def test_forged_plan_id_rejected_before_get(self):
        db = Backend(1)
        while len(db.requests) < 19:
            db.run()
        state = store.decode(SOURCE, db.envelope, at=STAMP)
        p = state['progress']
        p['tasks'][-1] = p['tasks'][-1].replace(PLAN, 'invented-12345678')
        p['plan_sha256'] = progress._digest(p['tasks'])
        db.envelope = store.encode(SOURCE, state, at=STAMP)
        with self.assertRaisesRegex(ValueError, 'manifest_invalid'):
            db.run()
        self.assertEqual(len(db.requests), 19)

    def test_invalid_page_never_commits_a_receipt(self):
        db = Backend()
        db.run()
        revision = db.revision
        with self.assertRaises(ValueError):
            db.run(fetch=lambda *args: '{"unexpected": "not an API list"}')
        self.assertEqual(db.revision, revision)

    def test_bad_cas_ack_stops_before_any_publisher_request(self):
        db = Backend()
        with self.assertRaisesRegex(ValueError, 'write_receipt_invalid'):
            db.run(write=lambda *args: {'checkpoint_saved': True, 'revision': 2})
        self.assertFalse(db.requests)

    def test_expired_checkpoint_rejected_before_any_new_get(self):
        db = Backend()
        db.run()
        with self.assertRaises(ValueError):
            db.run(clock=lambda: STAMP + timedelta(hours=4, seconds=1))
        self.assertEqual(len(db.requests), 1)

    def test_deadline_yields_with_saved_initial_checkpoint(self):
        db = Backend()
        self.assertEqual(db.run(can_continue=lambda: False)['status'], 'pending')
        self.assertEqual(db.revision, 1)
        self.assertEqual(db.requests, [])
        self.assertEqual(db.run()['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
