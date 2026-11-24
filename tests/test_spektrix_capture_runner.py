"""Exercise actual compressed captures across independent simulated leases."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from hashlib import md5
import unittest
from urllib.parse import parse_qs, urlsplit

from roomquest import feedzilla_capture_store as store
from roomquest import feedzilla_pagination_checkpoint as progress
from roomquest import spektrix_capture_plan as planner
from roomquest import spektrix_capture_runner as runner
from roomquest import incremental_snapshot as inc

STAMP = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
SOURCE = {'source_key': 'municipal_test_runner', 'kind': 'json',
          'feed_url': 'https://system.spektrix.com/testclient/api/v3/events',
          'platform_adapter': 'spektrix'}
PROFILE = {'client': 'testclient', 'ready_for_registration': True,
           'country': 'GB', 'timezone': 'Europe/London', 'home_city': 'London',
           'publisher_url': 'https://theatre.example/events', 'event_urls': {}}
SOURCE.update(source_key='municipal_' + md5(('feed_registration:' + SOURCE['feed_url']).encode()).hexdigest()[:24],
              action='collect', fetch_checkpoint_version=2,
              incremental_snapshot={'version': 1, 'policy_context': 'a'*64,
                                    'baseline_id': None, 'events': [], 'requests': []})
TICKET = {'p_category': 'jsonld', 'p_ticket': 'test-lease'}
EVENT = 'event-1234567890'
PLAN = 'plan-1234567890'
VENUE = 'venue-1234567890'


class Backend:
    """Test-only fetch CAS; no stage table, row receipts, or publisher writes."""
    def __init__(self, count=25):
        self.revision = 0
        self.envelope = None
        self.requests = []
        self.count = count

    def read(self):
        return {'revision': self.revision, 'checkpoint': deepcopy(self.envelope)}

    def write(self, revision, envelope):
        assert revision == self.revision
        self.revision += 1
        self.envelope = deepcopy(envelope)
        return {'checkpoint_saved': True, 'revision': self.revision}

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

    def run(self, source=SOURCE, profile=PROFILE, **overrides):
        with inc.capture_snapshot(source, TICKET) as snapshot:
            assert snapshot is not None
            args = dict(snapshot=snapshot, read=self.read, write=self.write,
                        fetch=self.fetch, convert=lambda source, data: data['events'],
                        can_continue=lambda: True, clock=lambda: STAMP, max_steps=1)
            args.update(overrides)
            return runner.run_slice(source, profile, **args)

    def finish(self, **overrides):
        for _ in range(50):
            result = self.run(**overrides)
            if not result.get('fetch_pending'):
                return result
        raise AssertionError('never finished')


class RunnerTests(unittest.TestCase):
    def context(self, source=SOURCE, profile=PROFILE):
        with inc.capture_snapshot(source,TICKET) as snapshot:
            return runner.capture_context(snapshot,profile)

    def test_60_day_fetch_then_ordinary_preview_without_repeat_gets(self):
        db = Backend()
        self.assertEqual(db.run(), {'fetch_pending': True})
        self.assertEqual(len(db.requests), 1)
        output = db.finish()
        self.assertEqual(output['p_future_count'], 25)
        self.assertEqual(len(output['p_events']), 25)
        self.assertEqual(len(set(db.requests)), 20)
        self.assertEqual(len(db.requests), 20)
        state = store.decode(SOURCE, db.envelope, context_hash=self.context(), at=STAMP)
        self.assertEqual(state['progress']['window_start'], '2026-11-24')
        self.assertEqual(state['progress']['window_end'], '2027-01-22')
        self.assertEqual(set(state), {'progress','pages','context_hash'})
        self.assertEqual(db.run(), output)
        self.assertEqual(len(db.requests), 20)

    def test_empty_complete_window_needs_no_fake_plan_request(self):
        db = Backend(0)
        output = db.finish()
        self.assertEqual(output['p_events'], [])
        self.assertEqual(len(db.requests), 19)
        self.assertTrue(store.ready_to_project(SOURCE, db.envelope, context_hash=self.context(), at=STAMP))

    def test_existing_incremental_plan_only_stages_changed_members(self):
        db = Backend()
        first = db.finish()
        rows = first['p_events']
        with inc.capture_snapshot(SOURCE,TICKET) as snapshot:
            plan = snapshot.plan(rows,first)
            self.assertEqual(len(plan['changed']),25)
            receipt = snapshot.receipt(plan)
        baseline = dict(SOURCE, incremental_snapshot=dict(receipt,baseline_id='f994cffb-1af2-4d86-a42e-02f39e15d19c'))
        again = db.run(source=baseline)
        with inc.capture_snapshot(baseline,TICKET) as snapshot:
            plan = snapshot.plan(again['p_events'],again)
            self.assertEqual(len(plan['events']),25)
            self.assertEqual(plan['changed'],[])
            self.assertEqual(snapshot.receipt(plan)['events'],receipt['events'])
            changed = deepcopy(again)
            changed['p_events'][0]['description']='Changed description'
            plan = snapshot.plan(changed['p_events'],changed)
            self.assertEqual(len(plan['events']),25)
            self.assertEqual(len(plan['changed']),1)
        self.assertEqual(len(db.requests),20)

    def test_lost_terminal_ack_reuses_verified_fetch_not_staging(self):
        db = Backend(1)
        while len(db.requests)<19:
            db.run()
        def lost(revision,envelope):
            db.write(revision,envelope)
            raise OSError('lost after CAS commit')
        with self.assertRaises(OSError):
            db.run(write=lost)
        self.assertEqual(db.run()['p_future_count'],1)
        self.assertEqual(len(db.requests),20)

    def test_foreign_same_host_task_rejected_before_get(self):
        db=Backend()
        db.run()
        context=self.context()
        state=store.decode(SOURCE,db.envelope,context_hash=context,at=STAMP)
        p=state['progress']
        p['tasks'][p['cursor']]=p['tasks'][p['cursor']].replace('/testclient/','/otherclient/')
        p['plan_sha256']=progress._digest(p['tasks'])
        db.envelope=store.encode(SOURCE,state,context_hash=context,at=STAMP)
        seen=list(db.requests)
        with self.assertRaisesRegex(ValueError,'manifest_invalid'):
            db.run()
        self.assertEqual(db.requests,seen)

    def test_forged_plan_id_rejected_before_get(self):
        db=Backend(1)
        while len(db.requests)<19:
            db.run()
        context=self.context()
        state=store.decode(SOURCE,db.envelope,context_hash=context,at=STAMP)
        p=state['progress']
        p['tasks'][-1]=p['tasks'][-1].replace(PLAN,'invented-12345678')
        p['plan_sha256']=progress._digest(p['tasks'])
        db.envelope=store.encode(SOURCE,state,context_hash=context,at=STAMP)
        with self.assertRaisesRegex(ValueError,'manifest_invalid'):
            db.run()
        self.assertEqual(len(db.requests),19)

    def test_invalid_page_never_commits_a_receipt(self):
        db=Backend()
        db.run()
        revision=db.revision
        with self.assertRaises(ValueError):
            db.run(fetch=lambda *args:'{"unexpected":"not an API list"}')
        self.assertEqual(db.revision,revision)

    def test_bad_cas_ack_stops_before_any_publisher_request(self):
        db=Backend()
        with self.assertRaisesRegex(ValueError,'write_receipt_invalid'):
            db.run(write=lambda *args:{'checkpoint_saved':True,'revision':2})
        self.assertFalse(db.requests)

    def test_expired_checkpoint_rejected_before_any_new_get(self):
        db=Backend()
        db.run()
        with self.assertRaises(ValueError):
            db.run(clock=lambda:STAMP+timedelta(hours=4,seconds=1))
        self.assertEqual(len(db.requests),1)

    def test_changed_profile_and_policy_reject_old_capture(self):
        db=Backend()
        db.run()
        with self.assertRaisesRegex(ValueError,'context_invalid'):
            db.run(profile=dict(PROFILE,home_city='Changed'))
        changed=deepcopy(SOURCE)
        changed['incremental_snapshot']['policy_context']='b'*64
        with self.assertRaisesRegex(ValueError,'context_invalid'):
            db.run(source=changed)
        self.assertEqual(len(db.requests),1)

    def test_deadline_yields_without_staging(self):
        db=Backend()
        self.assertEqual(db.run(can_continue=lambda:False),{'fetch_pending':True})
        self.assertEqual(db.revision,1)
        self.assertEqual(db.requests,[])
        self.assertEqual(db.run(),{'fetch_pending':True})

    def test_over_limit_cannot_return_partial_preview(self):
        db=Backend(1)
        with self.assertRaisesRegex(ValueError,'shared_incremental_limit'):
            db.finish(convert=lambda source,data:[dict(data['events'][0],id=str(i)) for i in range(501)])

    def test_legacy_checkpoint_claim_still_excluded(self):
        with inc.capture_snapshot(dict(SOURCE,fetch_checkpoint_version=1),TICKET) as snapshot:
            self.assertIsNone(snapshot)
        with inc.capture_snapshot(dict(SOURCE,platform_adapter='jsonld'),TICKET) as snapshot:
            self.assertIsNone(snapshot)
        with inc.capture_snapshot(SOURCE,dict(TICKET,p_category='html')) as snapshot:
            self.assertIsNone(snapshot)

if __name__=='__main__':
    unittest.main()
