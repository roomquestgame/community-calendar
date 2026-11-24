"""Actual shared RPC names and common stage function, with isolated fixtures."""
import ast
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from roomquest import spektrix_capture_transport as transport
from roomquest import incremental_snapshot as inc
from test_spektrix_capture_runner import Backend, SOURCE, PROFILE, STAMP, TICKET

def pacing():
    return {'crawl_delay_seconds': 0, 'retry_after_seconds': 0, 'wait_unbounded': False}


def load_worker_functions(names, namespace):
    path = Path(__file__).resolve().parents[1] / 'roomquest' / 'preview_worker.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(funcs) == len(names)
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class TransportTests(unittest.TestCase):
    def test_exact_claim_shared_checkpoint_and_no_event_rpc(self):
        db=Backend(25)
        calls=[]
        state=pacing()
        def rpc(name,payload,timeout):
            calls.append(name)
            self.assertEqual(timeout,8)
            self.assertEqual(payload['p_source_key'],SOURCE['source_key'])
            self.assertEqual(payload['p_category'],'jsonld')
            self.assertEqual(payload['p_ticket'],'test-lease')
            if name==transport.READ:
                return db.read()
            if name==transport.WRITE:
                self.assertEqual(payload['p_publisher_crawl_delay_seconds'],1 if db.requests else 0)
                self.assertFalse(payload['p_publisher_wait_unbounded'])
                return db.write(payload['p_expected_revision'],payload['p_checkpoint'])
            self.fail('Unexpected RPC '+name)
        def fetch(url,accept,**kw):
            self.assertEqual(kw,{'respect_robots':True,'allowed_hosts':('system.spektrix.com',),
                                  'follow_redirects':False,'deadline_at':28})
            state['crawl_delay_seconds']=1
            return db.fetch(url,accept)
        for _ in range(50):
            with inc.capture_snapshot(SOURCE,TICKET):
                result=transport.preview(SOURCE,PROFILE,collection_context=TICKET,rpc=rpc,
                    fetch_publisher=fetch,convert=lambda s,d:d['events'],pacing=state,
                    deadline_at=40,clock=lambda:STAMP,monotonic_clock=lambda:1,max_steps=1)
            if not result.get('fetch_pending'):
                break
        self.assertEqual(result['p_future_count'],25)
        self.assertEqual(set(calls),{'community_collector_read_fetch_checkpoint',
                                    'community_collector_write_fetch_checkpoint'})

    def test_no_negotiated_claim_never_calls_any_transport(self):
        def denied(*args,**kwargs):
            self.fail('Unauthorized callback')
        for source,scope in ((dict(SOURCE,fetch_checkpoint_version=1),TICKET),
                             (SOURCE,dict(TICKET,p_ticket='wrong'))):
            with inc.capture_snapshot(SOURCE,TICKET):
                with self.assertRaisesRegex(ValueError,'shared_claim_required'):
                    transport.preview(source,PROFILE,collection_context=scope,rpc=denied,
                        fetch_publisher=denied,convert=denied,pacing=pacing(),
                        deadline_at=40,monotonic_clock=lambda:1)
        with self.assertRaisesRegex(ValueError,'shared_claim_required'):
            transport.preview(SOURCE,PROFILE,collection_context=TICKET,rpc=denied,
                fetch_publisher=denied,convert=denied,pacing=pacing(),
                deadline_at=40,monotonic_clock=lambda:1)

    def test_interruption_never_mints_progress_or_stage_receipt(self):
        db=Backend(1)
        state=pacing()
        def rpc(name,payload,timeout):
            if name==transport.READ:return db.read()
            if name==transport.WRITE:return db.write(payload['p_expected_revision'],payload['p_checkpoint'])
            self.fail(name)
        def interrupted(*args,**kwargs):
            state['retry_after_seconds']=123
            raise OSError('publisher unavailable')
        with inc.capture_snapshot(SOURCE,TICKET):
            with self.assertRaises(OSError):
                transport.preview(SOURCE,PROFILE,collection_context=TICKET,rpc=rpc,
                    fetch_publisher=interrupted,convert=lambda s,d:d['events'],pacing=state,
                    deadline_at=40,clock=lambda:STAMP,monotonic_clock=lambda:1)
        self.assertEqual(db.revision,1)
        self.assertEqual(db.envelope['cursor'],0)
        # The shared outer worker retains this pacing context for its error receipt.
        self.assertEqual(state['retry_after_seconds'],123)

    def test_actual_common_stage_function_uses_only_changed_hash_bodies(self):
        db=Backend(25)
        output=db.finish()
        calls=[]
        class PreviewError(ValueError): pass
        def rpc(name,payload):
            calls.append((name,payload))
            self.assertEqual(name,'community_collector_stage_incremental')
            return {'accepted':True,'staged':len(payload['p_events'])}
        ns=load_worker_functions({'_event_batches','_stage_incremental_events'},
            dict(json=json,STAGING_BATCH_SIZE=20,monotonic=lambda:0,PreviewError=PreviewError,
                 supabase_rpc=rpc,_observe_collection_phase=lambda *a,**k:None))
        stage=ns['_stage_incremental_events']
        with inc.capture_snapshot(SOURCE,TICKET) as snapshot:
            plan=snapshot.plan(output['p_events'],output)
            self.assertEqual(stage(snapshot,plan,native_content=False,deadline=40,observe_phase=None),25)
            receipt=snapshot.receipt(plan)
        self.assertEqual([len(p['p_events']) for _,p in calls],[20,5])
        self.assertTrue(all(item['hash']==inc.fingerprint(item['event'])
                            for _,p in calls for item in p['p_events']))
        baseline=dict(SOURCE,incremental_snapshot=dict(receipt,baseline_id='f994cffb-1af2-4d86-a42e-02f39e15d19c'))
        next_ticket=dict(TICKET,p_ticket='next-lease')
        calls.clear()
        with inc.capture_snapshot(baseline,next_ticket) as snapshot:
            again=snapshot.plan(output['p_events'],output)
            self.assertEqual(stage(snapshot,again,native_content=False,deadline=40,observe_phase=None),0)
            self.assertEqual(calls,[])
            changed=deepcopy(output)
            changed['p_events'][0]['title']='Changed title'
            changed_plan=snapshot.plan(changed['p_events'],changed)
            self.assertEqual(stage(snapshot,changed_plan,native_content=False,deadline=40,observe_phase=None),1)
            self.assertEqual(len(snapshot.receipt(changed_plan)['events']),25)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['p_ticket'],'next-lease')


class ScopedRpcLimitTests(unittest.TestCase):
    def test_only_shared_checkpoint_read_gets_larger_response_ceiling(self):
        class PreviewError(ValueError):pass
        root='https://example.invalid'
        ns=load_worker_functions({'supabase_rpc'},dict(os=os,json=json,HTTPError=HTTPError,
            URLError=URLError,ROOMQUEST_DB=root,PreviewError=PreviewError))
        rpc=ns['supabase_rpc']
        payload=json.dumps({'checkpoint':'x'*849000}).encode()
        env={'SUPABASE_URL':root,'SUPABASE_PUBLISHABLE_KEY':'test','ROOMQUEST_COLLECTOR_TOKEN':'a'*64}
        with patch.dict(os.environ,env,clear=True),patch('urllib.request.urlopen',side_effect=lambda *a,**k:BytesIO(payload)) as http:
            self.assertEqual(len(rpc(transport.READ,{})['checkpoint']),849000)
            for name in ('community_collector_claim_category',transport.WRITE,'community_collector_stage_incremental'):
                with self.assertRaisesRegex(PreviewError,'database_unavailable'):
                    rpc(name,{})
            for name in ('read','write','stage','seal','note_wait','yield','verify'):
                with self.assertRaisesRegex(PreviewError,'unsupported_collector_rpc'):
                    rpc('community_collector_feedzilla_capture_'+name,{})
            self.assertEqual(http.call_count,4)


if __name__=='__main__':unittest.main()
