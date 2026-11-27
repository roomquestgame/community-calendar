"""Full narratives and reviewed locations survive ordinary/checkpoint workers."""
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from roomquest import category_worker, new_york_arts as arts
from roomquest import new_york_nightlife as nightlife, new_york_outdoors as outdoors
from roomquest import new_york_arts_remaining as arts_remaining
from roomquest import new_york_social_remaining as social_remaining
from roomquest import new_york_outdoors_remaining as outdoors_remaining
from roomquest import new_york_arts_final as arts_final, new_york_social_final as social_final
from roomquest import new_york_outdoors_final as outdoors_final, new_york_family_final as family_final
from roomquest import new_york_local_expansion as local_expansion, new_york_other_half as other_half
from roomquest import new_york_food_expansion as food_expansion, new_york_culture_expansion as culture_expansion
from roomquest import new_york_community_expansion as community_expansion, new_york_performance_expansion as performance_expansion
from roomquest import new_york_sources as profiles, preview_worker as worker


def source(module, key):
    url,kind,adapter=module.SOURCES[key]
    return dict(source_key=key,feed_url=url,kind=kind,platform_adapter=adapter,
                timezone='America/New_York')


def event(**values):
    result=dict(id='native-occurrence',title='Public workshop',
      description='Complete publisher narrative. '*140,
      starts_at='2026-12-01T18:00:00-05:00',ends_at='2026-12-01T19:00:00-05:00',
      venue_name='Museum',venue_address='212 West 83rd Street, New York, NY 10024',
      venue_city='New York',lat=None,lng=None,event_url='https://cmom.org/event/workshop/')
    result.update(values)
    return result


def checkpoint(key, *, cursor=1, manifest_count=1, events=None):
    now = datetime.now(timezone.utc)
    return dict(version=1, source_key=key, manifest_hash='a'*64,
        started_at=now.isoformat(), window_start=now.astimezone(ZoneInfo(profiles.ZONE)).date().isoformat(),
        cursor=cursor, manifest_count=manifest_count, events=events or [], diagnostics=[])


class NewYorkWorkerTests(unittest.TestCase):
    def test_remaining_profiles_use_the_same_full_description_boundary(self):
        for module in (arts_remaining,social_remaining,outdoors_remaining,
                       arts_final,social_final,outdoors_final,family_final,
                       local_expansion,other_half,food_expansion,culture_expansion,
                       community_expansion,performance_expansion):
            for key in module.SOURCES:
                with self.subTest(source_key=key):
                    self.assertIs(profiles.validate_source(source(module,key)),module)
                    self.assertEqual(key in profiles.checkpoint_keys(),key in module.CHECKPOINT_KEYS)
                    if key not in module.CHECKPOINT_KEYS:
                        row=event()
                        with patch.object(module,'collect',return_value=[row]):
                            self.assertEqual(worker.preview_source(source(module,key))['p_events'],[row])

    def test_expanded_checkpoint_bounds_are_specific_to_reviewed_pride_calendar(self):
        pride=checkpoint(social_remaining.PRIDE,cursor=329,manifest_count=329)
        profiles.validate_checkpoint(source(social_remaining,social_remaining.PRIDE),pride)
        ordinary={**pride,'source_key':social_remaining.IRISH}
        with self.assertRaisesRegex(ValueError,'new_york_checkpoint_invalid'):
            profiles.validate_checkpoint(source(social_remaining,social_remaining.IRISH),ordinary)

    def test_ordinary_worker_retains_complete_narrative_and_postal_address(self):
        row=event(collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','is_all_day':False,
                     'starts_at_utc':'2026-12-01T23:00:00+00:00'}})
        with patch.object(arts,'collect',return_value=[row]):
            result=worker.preview_source(source(arts,arts.CMOM))
        self.assertGreater(len(row['description']),2000)
        self.assertEqual(result['p_events'],[row])
        self.assertEqual(result['p_samples'][0]['venue_address'],row['venue_address'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_remaining_arts_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':'https://cmom.org/event/workshop/'}})
        with patch.object(arts_remaining,'collect',return_value=[row]):
            result=worker.preview_source(source(arts_remaining,arts_remaining.COMMONPOINT))
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_remaining_social_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':'https://www.newyorkirishcenter.org/events/workshop'}})
        responses=[{'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]
        chunk={'checkpoint':checkpoint(social_remaining.IRISH,events=[row]),
               'complete':True,'events':[row]}
        with patch.object(worker,'supabase_rpc',side_effect=responses), \
             patch.object(social_remaining,'collect_chunk',return_value=chunk):
            result=worker._preview_new_york_chunk(source(social_remaining,social_remaining.IRISH),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_remaining_outdoors_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':'https://cityparksfoundation.org/events/workshop/'}})
        with patch.object(outdoors_remaining,'collect',return_value=[row]):
            result=worker.preview_source(source(outdoors_remaining,outdoors_remaining.CITY))
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_final_arts_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':'https://www.brooklynkids.org/events/workshop/'}})
        with patch.object(arts_final,'collect',return_value=[row]):
            result=worker.preview_source(source(arts_final,arts_final.BCM))
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_final_social_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=social_final.SOURCES[social_final.WILD][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':social_final.SOURCES[social_final.WILD][0]}})
        with patch.object(social_final,'collect',return_value=[row]):
            result=worker.preview_source(source(social_final,social_final.WILD))
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_final_outdoors_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=outdoors_final.SOURCES[outdoors_final.PARKS][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':outdoors_final.SOURCES[outdoors_final.PARKS][0]}})
        with patch.object(outdoors_final,'collect',return_value=[row]):
            result=worker.preview_source(source(outdoors_final,outdoors_final.PARKS))
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_final_family_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=family_final.SOURCES[family_final.AQUARIUM][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':family_final.SOURCES[family_final.AQUARIUM][0]}})
        with patch.object(family_final,'collect',return_value=[row]):
            result=worker.preview_source(source(family_final,family_final.AQUARIUM))
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_local_expansion_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=local_expansion.SOURCES[local_expansion.FREDDYS][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':local_expansion.SOURCES[local_expansion.FREDDYS][0]}})
        with patch.object(local_expansion,'collect_chunk',return_value={
                'checkpoint':checkpoint(local_expansion.FREDDYS,events=[row]),
                'complete':True,'events':[row]}), \
             patch.object(worker,'supabase_rpc',side_effect=[
                {'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]):
            result=worker._preview_new_york_chunk(source(local_expansion,local_expansion.FREDDYS),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_community_expansion_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=community_expansion.SOURCES[community_expansion.PROSPECT][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':community_expansion.SOURCES[community_expansion.PROSPECT][0]}})
        with patch.object(community_expansion,'collect_chunk',return_value={
                'checkpoint':checkpoint(community_expansion.PROSPECT,events=[row]),
                'complete':True,'events':[row]}), \
             patch.object(worker,'supabase_rpc',side_effect=[
                {'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]):
            result=worker._preview_new_york_chunk(source(community_expansion,community_expansion.PROSPECT),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_other_half_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=other_half.SOURCES[other_half.OTHER][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':other_half.SOURCES[other_half.OTHER][0]}})
        with patch.object(other_half,'collect_chunk',return_value={
                'checkpoint':checkpoint(other_half.OTHER,events=[row]),
                'complete':True,'events':[row]}), \
             patch.object(worker,'supabase_rpc',side_effect=[
                {'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]):
            result=worker._preview_new_york_chunk(source(other_half,other_half.OTHER),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_food_expansion_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=food_expansion.SOURCES[food_expansion.EATALY][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':food_expansion.SOURCES[food_expansion.EATALY][0]}})
        with patch.object(food_expansion,'collect_chunk',return_value={
                'checkpoint':checkpoint(food_expansion.EATALY,events=[row]),
                'complete':True,'events':[row]}), \
             patch.object(worker,'supabase_rpc',side_effect=[
                {'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]):
            result=worker._preview_new_york_chunk(source(food_expansion,food_expansion.EATALY),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_culture_expansion_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=culture_expansion.SOURCES[culture_expansion.ASTOR][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':culture_expansion.SOURCES[culture_expansion.ASTOR][0]}})
        with patch.object(culture_expansion,'collect_chunk',return_value={
                'checkpoint':checkpoint(culture_expansion.ASTOR,events=[row]),
                'complete':True,'events':[row]}), \
             patch.object(worker,'supabase_rpc',side_effect=[
                {'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]):
            result=worker._preview_new_york_chunk(source(culture_expansion,culture_expansion.ASTOR),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_performance_expansion_normal_and_admin_payloads_share_private_content_boundary(self):
        row=event(event_url=performance_expansion.SOURCES[performance_expansion.JALOPY][0],collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':performance_expansion.SOURCES[performance_expansion.JALOPY][0]}})
        with patch.object(performance_expansion,'collect_chunk',return_value={
                'checkpoint':checkpoint(performance_expansion.JALOPY,events=[row]),
                'complete':True,'events':[row]}), \
             patch.object(worker,'supabase_rpc',side_effect=[
                {'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]):
            result=worker._preview_new_york_chunk(source(performance_expansion,performance_expansion.JALOPY),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},
                deadline_at=worker.monotonic()+50)
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],
                         row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_exact_source_contract_rejects_changed_endpoint_before_fetch(self):
        bad=source(arts,arts.CMOM);bad['feed_url']='https://cmom.org/other'
        with patch.object(arts,'collect') as collect:
            with self.assertRaisesRegex(worker.PreviewError,'unregistered_new_york_source'):
                worker.preview_source(bad)
            collect.assert_not_called()

    def test_missing_oversized_and_locationless_records_cannot_complete(self):
        for change in ({'description':''},{'description':'x'*12001},{'venue_address':'New York, NY 10024'}):
            with self.subTest(change=list(change)),patch.object(arts,'collect',return_value=[event(**change)]):
                with self.assertRaisesRegex(worker.PreviewError,'new_york_incomplete_event'):
                    worker.preview_source(source(arts,arts.CMOM))

    def test_only_exact_reviewed_intersection_point_is_accepted(self):
        point=outdoors.REVIEWED_INTERSECTIONS[0]
        src=source(outdoors,point['source_key'])
        row=event(**{k:point[k] for k in ('venue_name','venue_address','lat','lng')})
        profiles.validate_records([row],src)
        for change in ({'lat':row['lat']+0.001},{'lng':None},{'venue_name':'Another park'}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError,'new_york_incomplete_event'):
                    profiles.validate_records([{**row,**change}],src)
        with self.assertRaisesRegex(ValueError,'new_york_incomplete_event'):
            profiles.validate_records([row],source(arts,arts.CMOM))

    def test_checkpoint_persists_before_returning_full_rows(self):
        row=event(collector_event_content_v1={
            'version':1,'event_id':'native-occurrence',
            'facts':{'title':'Public workshop','description':'Complete publisher narrative. '*140,
                     'is_all_day':False,'starts_at_utc':'2026-12-01T23:00:00+00:00',
                     'ends_at_utc':'2026-12-02T00:00:00+00:00',
                     'event_url':'https://cmom.org/event/workshop/'}});calls=[]
        def rpc(operation,payload):
            calls.append(operation)
            if operation.endswith('read_fetch_checkpoint'):return {'revision':0,'checkpoint':None}
            if operation.endswith('write_fetch_checkpoint'):return {'checkpoint_saved':True,'revision':1}
            self.fail(operation)
        pacing=dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0)
        chunk={'checkpoint':checkpoint(nightlife.CHILOS, events=[row]),'complete':True,'events':[row]}
        with patch.object(worker,'supabase_rpc',side_effect=rpc),patch.object(nightlife,'collect_chunk',return_value=chunk):
            result=worker._preview_new_york_chunk(source(nightlife,nightlife.CHILOS),pacing,
                collection_context={'p_category':'html','p_ticket':'test-ticket'},deadline_at=worker.monotonic()+50)
        self.assertEqual(calls,['community_collector_read_fetch_checkpoint','community_collector_write_fetch_checkpoint'])
        self.assertEqual(result['p_events'][0]['description'],row['description'])
        self.assertEqual(result['p_events'][0]['collector_event_content_v1'],row['collector_event_content_v1'])
        self.assertNotIn('collector_event_content_v1',result['p_samples'][0])

    def test_partial_chunk_does_not_return_events_for_staging(self):
        chunk={'checkpoint':checkpoint(nightlife.CHILOS, manifest_count=2),'complete':False,'events':[event()]}
        responses=[{'revision':0,'checkpoint':None},{'checkpoint_saved':True,'revision':1}]
        with patch.object(worker,'supabase_rpc',side_effect=responses),patch.object(nightlife,'collect_chunk',return_value=chunk):
            result=worker._preview_new_york_chunk(source(nightlife,nightlife.CHILOS),
                dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                collection_context={'p_category':'html','p_ticket':'test-ticket'},deadline_at=worker.monotonic()+50)
        self.assertEqual(result,{'fetch_pending':True})

    def test_invalid_wire_checkpoint_is_rejected_before_database_write(self):
        valid = checkpoint(outdoors.DYCKMAN)
        for saved in (None, {**valid, 'window_start':valid['started_at']},
                      {**valid, 'cursor':0}, {**valid, 'started_at':'2020-01-01T00:00:00Z'}):
            with self.subTest(checkpoint=saved):
                chunk={'checkpoint':saved,'complete':True,'events':[event()]}
                with patch.object(worker,'supabase_rpc',return_value={'revision':0,'checkpoint':None}) as rpc, \
                     patch.object(outdoors,'collect_chunk',return_value=chunk):
                    with self.assertRaisesRegex(worker.PreviewError,'new_york_checkpoint_invalid'):
                        worker._preview_new_york_chunk(source(outdoors,outdoors.DYCKMAN),
                            dict(wait_unbounded=False,crawl_delay_seconds=0,retry_after_seconds=0),
                            collection_context={'p_category':'html','p_ticket':'test-ticket'},
                            deadline_at=worker.monotonic()+50)
                self.assertEqual(rpc.call_count,1)
                self.assertEqual(rpc.call_args.args[0],'community_collector_read_fetch_checkpoint')

    def test_unexpected_publisher_error_text_is_not_logged_as_diagnostic(self):
        with patch.object(arts,'collect',side_effect=ValueError('private_publisher_value')):
            with self.assertRaisesRegex(worker.PreviewError,'^invalid_new_york_payload$'):
                worker.preview_source(source(arts,arts.CMOM))
        self.assertEqual(category_worker._error_code(worker.PreviewError('new_york_incomplete_event')),
                         'new_york_incomplete_event')
        self.assertEqual(category_worker._error_code(worker.PreviewError('private_publisher_value')),
                         'unclassified_preview_error')


if __name__=='__main__':unittest.main()
