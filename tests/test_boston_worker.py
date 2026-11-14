"""Full narratives and reviewed locations survive ordinary/checkpoint workers."""
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from roomquest import category_worker, boston_arts as arts
from roomquest import boston_nightlife as nightlife, boston_community as outdoors
from roomquest import boston_sources as profiles, preview_worker as worker


def source(module, key):
    url,kind,adapter=module.SOURCES[key]
    return dict(source_key=key,feed_url=url,kind=kind,platform_adapter=adapter,
                timezone='America/New_York')


def event(**values):
    result=dict(id='native-occurrence',title='Public workshop',
      description='Complete publisher narrative. '*140,
      starts_at='2026-12-01T18:00:00-05:00',ends_at='2026-12-01T19:00:00-05:00',
      venue_name='Museum',venue_address='700 Boylston Street, Boston, MA 02116',
      venue_city='Boston',lat=None,lng=None,event_url='https://www.sowaboston.com/event/workshop/')
    result.update(values)
    return result


def checkpoint(key, *, cursor=1, manifest_count=1, events=None):
    now = datetime.now(timezone.utc)
    return dict(version=1, source_key=key, manifest_hash='a'*64,
        started_at=now.isoformat(), window_start=now.astimezone(ZoneInfo(profiles.ZONE)).date().isoformat(),
        cursor=cursor, manifest_count=manifest_count, events=events or [], diagnostics=[])


class BostonWorkerTests(unittest.TestCase):
    def test_remaining_profiles_use_the_same_full_description_boundary(self):
        for module in profiles.adapters():
            for key in module.SOURCES:
                with self.subTest(source_key=key):
                    self.assertIs(profiles.validate_source(source(module,key)),module)
                    self.assertEqual(key in profiles.checkpoint_keys(),key in module.CHECKPOINT_KEYS)
                    if key not in module.CHECKPOINT_KEYS:
                        row=event()
                        with patch.object(module,'collect',return_value=[row]):
                            self.assertEqual(worker.preview_source(source(module,key))['p_events'],[row])

    def test_ordinary_worker_retains_complete_narrative_and_postal_address(self):
        row=event()
        with patch.object(arts,'collect',return_value=[row]):
            result=worker.preview_source(source(arts,arts.SOWA))
        self.assertGreater(len(row['description']),2000)
        self.assertEqual(result['p_events'],[row])
        self.assertEqual(result['p_samples'][0]['venue_address'],row['venue_address'])

    def test_exact_source_contract_rejects_changed_endpoint_before_fetch(self):
        bad=source(arts,arts.SOWA);bad['feed_url']='https://www.sowaboston.com/other'
        with patch.object(arts,'collect') as collect:
            with self.assertRaisesRegex(worker.PreviewError,'unregistered_boston_source'):
                worker.preview_source(bad)
            collect.assert_not_called()

    def test_missing_oversized_and_locationless_records_cannot_complete(self):
        for change in ({'description':''},{'description':'x'*12001},{'venue_address':'Boston, MA 02116'}):
            with self.subTest(change=list(change)),patch.object(arts,'collect',return_value=[event(**change)]):
                with self.assertRaisesRegex(worker.PreviewError,'boston_incomplete_event'):
                    worker.preview_source(source(arts,arts.SOWA))

    def test_checkpoint_persists_before_returning_full_rows(self):
        row=event();calls=[]
        def rpc(operation,payload):
            calls.append(operation)
            if operation.endswith('read_fetch_checkpoint'):return {'revision':0,'checkpoint':None}
            if operation.endswith('write_fetch_checkpoint'):return {'checkpoint_saved':True,'revision':1}
            self.fail(operation)
        pacing=dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0)
        chunk={'checkpoint':checkpoint(nightlife.NOTCH, events=[row]),'complete':True,'events':[row]}
        with patch.object(worker,'supabase_rpc',side_effect=rpc),patch.object(nightlife,'collect_chunk',return_value=chunk):
            result=worker._preview_boston_chunk(source(nightlife,nightlife.NOTCH),pacing,
                collection_context={'p_category':'html','p_ticket':'test-ticket'},deadline_at=worker.monotonic()+50)
        self.assertEqual(calls,['community_collector_read_fetch_checkpoint','community_collector_write_fetch_checkpoint'])
        self.assertEqual(result['p_events'][0]['description'],row['description'])

    def test_partial_chunk_does_not_return_events_for_staging(self):
        chunk={'checkpoint':checkpoint(nightlife.NOTCH, manifest_count=2),'complete':False,'events':[event()]}
        responses=[{'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]
        with patch.object(worker,'supabase_rpc',side_effect=responses),patch.object(nightlife,'collect_chunk',return_value=chunk):
            result=worker._preview_boston_chunk(source(nightlife,nightlife.NOTCH),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},deadline_at=worker.monotonic()+50)
        self.assertEqual(result,{'fetch_pending':True})

    def test_invalid_wire_checkpoint_is_rejected_before_database_write(self):
        valid = checkpoint(outdoors.FOOD_FOREST)
        for saved in (None, {**valid, 'window_start':valid['started_at']},
                      {**valid, 'cursor':0}, {**valid, 'started_at':'2020-01-01T00:00:00Z'}):
            with self.subTest(checkpoint=saved):
                chunk={'checkpoint':saved,'complete':True,'events':[event()]}
                with patch.object(worker,'supabase_rpc',return_value={'revision':0,'checkpoint':None}) as rpc, \
                     patch.object(outdoors,'collect_chunk',return_value=chunk):
                    with self.assertRaisesRegex(worker.PreviewError,'boston_checkpoint_invalid'):
                        worker._preview_boston_chunk(source(outdoors,outdoors.FOOD_FOREST),
                            dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                            collection_context={'p_category':'html','p_ticket':'test-ticket'},
                            deadline_at=worker.monotonic()+50)
                self.assertEqual(rpc.call_count,1)
                self.assertEqual(rpc.call_args.args[0],'community_collector_read_fetch_checkpoint')

    def test_unexpected_publisher_error_text_is_not_logged_as_diagnostic(self):
        with patch.object(arts,'collect',side_effect=ValueError('private_publisher_value')):
            with self.assertRaisesRegex(worker.PreviewError,'^invalid_boston_payload$'):
                worker.preview_source(source(arts,arts.SOWA))
        self.assertEqual(category_worker._error_code(worker.PreviewError('boston_incomplete_event')),
                         'boston_incomplete_event')
        self.assertEqual(category_worker._error_code(worker.PreviewError('private_publisher_value')),
                         'unclassified_preview_error')

    def test_remaining_museum_wire_capacity_is_limited_to_its_exact_profile(self):
        from roomquest import boston_arts_remaining as remaining
        key=remaining.MFA
        large=checkpoint(key,cursor=500,manifest_count=500,events=[event() for _ in range(500)])
        self.assertIs(profiles.validate_checkpoint(source(remaining,key),large),large)
        for invalid in ({**large,'manifest_count':501},
                        {**large,'events':large['events']+[event()]},
                        {**large,'source_key':remaining.ICA}):
            src=source(remaining,invalid['source_key'])
            with self.subTest(source=invalid['source_key']),self.assertRaisesRegex(ValueError,'boston_checkpoint_invalid'):
                profiles.validate_checkpoint(src,invalid)

    def test_reviewed_intersection_requires_the_exact_source_venue_and_point(self):
        from roomquest import boston_community_remaining as remaining
        reviewed=remaining.REVIEWED_INTERSECTIONS[0]
        row=event(**{k:v for k,v in reviewed.items() if k!='source_key'})
        src=source(remaining,remaining.GREENWAY)
        self.assertEqual(profiles.validate_records([row],src),[row])
        for changed in ({**row,'lat':row['lat']+0.001},
                        {**row,'venue_name':'Unreviewed nearby venue'},
                        {**row,'lng':None}):
            with self.assertRaisesRegex(ValueError,'boston_incomplete_event'):
                profiles.validate_records([changed],src)
        with self.assertRaisesRegex(ValueError,'boston_incomplete_event'):
            profiles.validate_records([row],source(remaining,remaining.NATURE))


if __name__=='__main__':unittest.main()
