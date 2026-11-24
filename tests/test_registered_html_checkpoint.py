"""Lease/CAS-bound native HTML capture; transport and backend mocked only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from time import monotonic
import unittest
from unittest.mock import patch

from roomquest import registered_html_checkpoint as capture
from roomquest import national_feed_checkpoint as codec
from test_registered_html_continuation import FEED, fixture, source


def admitted(url=FEED):
    return dict(source(url), registered_html_checkpoint_version=1)


class CaptureTests(unittest.TestCase):
    def test_registration_transfer_and_complete_replay(self):
        pages, order = fixture()
        calls = []
        state = {'revision': 0, 'checkpoint': None}
        history = []

        def fetch(url, accept):
            calls.append(url)
            return pages[url]

        def rpc(method, args, **kwargs):
            history.append((method, args['p_category'], args['p_ticket']))
            if method == 'community_collector_read_fetch_checkpoint':
                return deepcopy(state)
            self.assertEqual(method, 'community_collector_write_fetch_checkpoint')
            self.assertEqual(args['p_expected_revision'], state['revision'])
            state.update(revision=state['revision']+1, checkpoint=args['p_checkpoint'])
            self.assertEqual(args['p_publisher_crawl_delay_seconds'], 1)
            return {'checkpoint_saved': True, 'revision': state['revision']}

        pacing = {'crawl_delay_seconds': 1, 'retry_after_seconds': 0, 'wait_unbounded': False}
        for i in range(7):
            chunk = capture.collect_and_save(admitted(), fetch, rpc, pacing,
                category='registration', ticket='ticket-'+str(i),
                deadline_at=monotonic()+30, listing=pages[FEED] if i==0 else None)
            self.assertEqual(chunk['complete'], i==6)
            if i!=6:
                self.assertIsNone(chunk['events'])
                self.assertEqual(chunk['checkpoint']['phase'], 'fetch')
            self.assertEqual(chunk['checkpoint']['record_count'], 0)
        self.assertEqual(len(chunk['events']), 45)
        self.assertEqual(calls, order[1:])
        self.assertEqual(len(set(calls)), 53)
        # Same exact checkpoint transfers to a fresh source claim, no new GET.
        state['revision']=1
        replay=capture.collect_and_save(admitted(), fetch, rpc, pacing,
            category='html', ticket='source-ticket', deadline_at=monotonic()+30)
        self.assertTrue(replay['complete'])
        self.assertEqual(replay['events'],chunk['events'])
        self.assertEqual(replay['checkpoint'],chunk['checkpoint'])
        self.assertEqual(calls, order[1:])
        self.assertEqual(history[-1],('community_collector_write_fetch_checkpoint','html','source-ticket'))

    def test_new_source_ordinary_collection(self):
        pages, order = fixture(2,2)
        calls=[]
        def fetch(url,accept):
            calls.append(url)
            return pages[url]
        chunk=capture.collect_chunk(admitted(),fetch)
        self.assertTrue(chunk['complete'])
        self.assertEqual(len(chunk['events']),4)
        self.assertEqual(calls,order)

    def test_wrong_context_rejected_before_network(self):
        pages, order=fixture(2,2)
        first=capture.collect_chunk(admitted(),lambda u,a:pages[u],max_requests=1)
        with patch.object(capture,'context_hash',return_value='a'*64):
            with self.assertRaisesRegex(ValueError,'html_calendar_capture_context_changed'):
                capture.collect_chunk(admitted(),lambda u,a:self.fail('network called'),checkpoint=first['checkpoint'])

    def test_source_collection_replays_completed_bytes_after_compatible_parser_change(self):
        pages, order=fixture(2,2)
        src=admitted()
        with patch.object(capture,'context_hash',return_value='1'*64):
            terminal=capture.collect_chunk(src,lambda u,a:pages[u])['checkpoint']
        state={'revision':7,'checkpoint':terminal}
        calls=[]

        def fetch(url,accept):
            calls.append(url)
            return pages[url]

        def rpc(method,args,**kwargs):
            if method.endswith('read_fetch_checkpoint'):
                return deepcopy(state)
            self.assertEqual(method,'community_collector_write_fetch_checkpoint')
            self.assertEqual(args['p_expected_revision'],7)
            self.assertEqual(args['p_checkpoint'],terminal)
            return {'checkpoint_saved':True,'revision':8}

        pacing={'crawl_delay_seconds':1,'retry_after_seconds':0,'wait_unbounded':False}
        with patch.object(capture,'context_hash',return_value='2'*64), \
                patch.object(capture,'_dispatch_predecessor_context',return_value=None):
            result=capture.collect_and_save(src,fetch,rpc,pacing,category='html',
                ticket='fresh-source-capture',deadline_at=monotonic()+30)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['events']),4)
        self.assertEqual(calls,[])

    def test_source_collection_rotates_terminal_capture_when_traversal_changed(self):
        pages,order=fixture(2,2)
        src=admitted()
        with patch.object(capture,'context_hash',return_value='5'*64):
            terminal=capture.collect_chunk(src,lambda u,a:pages[u])['checkpoint']
        calls=[]
        original_resume=capture.resume_capture

        def changed_traversal(source,prefix,**kwargs):
            if prefix:
                raise ValueError('html_calendar_capture_invalid')
            return original_resume(source,prefix,**kwargs)

        def fetch(url,accept):
            calls.append(url)
            return pages[url]

        def rpc(method,args,**kwargs):
            if method.endswith('read_fetch_checkpoint'):
                return {'revision':4,'checkpoint':terminal}
            self.assertEqual(method,'community_collector_rotate_fetch_checkpoint')
            self.assertEqual(args['p_expected_revision'],4)
            self.assertNotEqual(args['p_checkpoint'],terminal)
            return {'checkpoint_saved':True,'revision':5}

        pacing={'crawl_delay_seconds':1,'retry_after_seconds':0,'wait_unbounded':False}
        with patch.object(capture,'context_hash',return_value='6'*64), \
                patch.object(capture,'_dispatch_predecessor_context',return_value=None), \
                patch.object(capture,'resume_capture',side_effect=changed_traversal):
            result=capture.collect_and_save(src,fetch,rpc,pacing,category='html',
                ticket='rotated-source-capture',deadline_at=monotonic()+30)
        self.assertTrue(result['complete'])
        self.assertEqual(calls,order)

    def test_context_change_never_restarts_registration_or_partial_capture(self):
        pages,order=fixture(2,2)
        src=admitted()
        pacing={'crawl_delay_seconds':1,'retry_after_seconds':0,'wait_unbounded':False}
        for category,complete in [('registration',True),('html',False)]:
            with self.subTest(category=category,complete=complete):
                with patch.object(capture,'context_hash',return_value='3'*64):
                    prior=capture.collect_chunk(src,lambda u,a:pages[u],
                        max_requests=8 if complete else 1)['checkpoint']
                def rpc(method,args,**kwargs):
                    if method.endswith('read_fetch_checkpoint'):
                        return {'revision':1,'checkpoint':prior}
                    self.fail('stale capture must not be overwritten')
                with patch.object(capture,'context_hash',return_value='4'*64), \
                        patch.object(capture,'_dispatch_predecessor_context',return_value=None), \
                        self.assertRaisesRegex(ValueError,'html_calendar_capture_context_changed'):
                    capture.collect_and_save(src,lambda u,a:self.fail('network called'),rpc,pacing,
                        category=category,ticket='preserve-prior',deadline_at=monotonic()+30)

    def test_malformed_state_is_not_treated_as_context_rotation(self):
        pages,order=fixture(1,1)
        src=admitted()
        checkpoint=capture.collect_chunk(src,lambda u,a:pages[u])['checkpoint']
        state=codec.decode(src,checkpoint)
        state['events']=[{'forged':True}]
        invalid=codec.encode(src,state,phase='stage',cursor=1,count=1)
        with self.assertRaisesRegex(ValueError,'html_calendar_capture_invalid'):
            capture.collect_chunk(src,lambda u,a:self.fail('network called'),checkpoint=invalid)

    def test_expired_and_cross_source_rejected(self):
        pages, order=fixture(2,2)
        now=datetime.now(timezone.utc)
        first=capture.collect_chunk(admitted(),lambda u,a:pages[u],max_requests=1,at=now)
        for src, at in [(admitted('https://other.example.org/events'),now),
                         (admitted(),now+timedelta(hours=5))]:
            with self.assertRaises(ValueError):
                capture.collect_chunk(src,lambda u,a:self.fail('network called'),
                    checkpoint=first['checkpoint'],at=at)

    def test_receipt_tamper_rejected(self):
        pages,order=fixture(2,2)
        first=capture.collect_chunk(admitted(),lambda u,a:pages[u],max_requests=1)
        state=codec.decode(admitted(),first['checkpoint'])
        state['pages'][0]['body']+='tamper'
        bad=codec.encode(admitted(),state,phase='fetch',cursor=1,count=2)
        with self.assertRaisesRegex(ValueError,'html_calendar_capture_invalid'):
            capture.collect_chunk(admitted(),lambda u,a:self.fail('network called'),checkpoint=bad)

    def test_pacing_yield_keeps_prefix(self):
        pages,order=fixture(2,2)
        first=capture.collect_chunk(admitted(),lambda u,a:pages[u],max_requests=1)
        def blocked(url,accept):
            self.assertEqual(url,order[1])
            raise ValueError('publisher_pacing_deferred')
        out=capture.collect_chunk(admitted(),blocked,checkpoint=first['checkpoint'])
        self.assertFalse(out['complete'])
        self.assertIsNone(out['events'])
        self.assertEqual(out['checkpoint'],first['checkpoint'])

    def test_robots_denial_not_checkpoint_success(self):
        pages,order=fixture(2,2)
        first=capture.collect_chunk(admitted(),lambda u,a:pages[u],max_requests=1)
        def denied(url,accept):raise ValueError('robots_denied')
        with self.assertRaisesRegex(ValueError,'robots_denied'):
            capture.collect_chunk(admitted(),denied,checkpoint=first['checkpoint'])

    def test_no_capability_or_wrong_revision(self):
        with self.assertRaisesRegex(ValueError,'not_admitted'):
            capture.collect_chunk(source(),lambda u,a:self.fail('network called'))
        pages,order=fixture(1,1)
        def rpc(method,args,**kwargs):
            if method.endswith('read_fetch_checkpoint'):
                return {'revision':0,'checkpoint':None}
            return {'checkpoint_saved':True,'revision':2}
        pacing={'crawl_delay_seconds':1,'retry_after_seconds':0,'wait_unbounded':False}
        with self.assertRaisesRegex(ValueError,'fetch_checkpoint_invalid_response'):
            capture.collect_and_save(admitted(),lambda u,a:pages[u],rpc,pacing,
                category='registration',ticket='test',deadline_at=monotonic()+30)


    def test_reviewed_predecessor_terminal_capture_survives_dispatch_only_change(self):
        src = admitted()
        previous = '7'*64
        self.assertNotEqual(previous, capture.context_hash(src))
        pages, _ = fixture(1, 2)
        with patch.object(capture, 'context_hash', return_value=previous):
            original = capture.collect_chunk(src, lambda u, a: pages[u])
        self.assertTrue(original['complete'])
        with patch.object(capture,'_dispatch_predecessor_context',return_value=previous):
            replay = capture.collect_chunk(src,
                lambda u, a: self.fail('unexpected publisher request'),
                checkpoint=original['checkpoint'])
        self.assertEqual(replay['events'], original['events'])
        self.assertEqual(replay['checkpoint'], original['checkpoint'])

    def test_negotiated_category_claim_replays_transferred_capture_and_stages(self):
        from roomquest import category_worker, preview_worker
        from roomquest.registered_native_content import validate_record
        src = dict(admitted(), source_id=999, action='collect')
        pages, _ = fixture(1, 2)
        terminal = capture.collect_chunk(src, lambda u, a: pages[u])['checkpoint']
        calls, staged = [], []
        ticket = 'fixture-ticket'

        def rpc(method, args, **kwargs):
            calls.append(method)
            if method == 'community_collector_claim_category':
                self.assertEqual(args, {'p_category': 'html', 'p_ticket': ticket})
                return src
            if method == 'community_collector_read_fetch_checkpoint':
                self.assertEqual(args, {'p_category': 'html', 'p_ticket': ticket,
                                        'p_source_key': src['source_key']})
                return {'revision': 1, 'checkpoint': terminal}
            if method == 'community_collector_write_fetch_checkpoint':
                self.assertEqual(args['p_expected_revision'], 1)
                self.assertEqual(args['p_checkpoint'], terminal)
                self.assertEqual(args['p_ticket'], ticket)
                self.assertEqual(args['p_category'], 'html')
                return {'checkpoint_saved': True, 'revision': 2}
            if method == 'community_collector_record_staged_events':
                self.assertEqual(args['p_registered_native_content_version'], 1)
                for row in args['p_events']:
                    validate_record(row, src)
                staged.extend(args['p_events'])
                return len(args['p_events'])
            if method == 'community_collector_record_preview_v3':
                self.assertIsNone(args['p_error'])
                self.assertEqual(args['p_future_count'], len(staged))
                return None
            if method == 'community_collector_publish_category':
                return {'outcome': 'continued'}
            if method == 'community_collector_finish_category':
                self.assertEqual(args['p_outcome'], 'complete')
                return True
            self.fail(method)

        with patch.object(category_worker, 'supabase_rpc', side_effect=rpc), \
                patch.object(preview_worker, 'supabase_rpc', side_effect=rpc), \
                patch.object(preview_worker, 'fetch_publisher',
                             side_effect=AssertionError('unexpected publisher GET')):
            result = category_worker.collect_category('html', ticket)
        self.assertEqual(result['complete'], 1)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['staged'], 2)
        self.assertEqual(calls, ['community_collector_claim_category',
                                 'community_collector_read_fetch_checkpoint',
                                 'community_collector_write_fetch_checkpoint',
                                 'community_collector_record_staged_events',
                                 'community_collector_record_preview_v3',
                                 'community_collector_publish_category',
                                 'community_collector_finish_category'])


if __name__=='__main__':
    unittest.main()
