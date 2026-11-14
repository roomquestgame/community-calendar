"""All nine new sources retain full records at the existing worker boundaries."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from roomquest import atlantic_city_local_community as community
from roomquest import atlantic_city_local_markets as markets
from roomquest import atlantic_city_local_recreation as recreation
from roomquest import atlantic_city_local_venues as venues
from roomquest import preview_worker as worker, category_worker as category
from tests.test_atlantic_city_worker import Harness, WRITE, STAGE, RECORD, PUBLISH


def source(adapter,key):
    u,k,a=adapter.SOURCES[key]
    value=dict(source_key=key,feed_url=u,kind=k,platform_adapter=a,timezone='America/New_York')
    if key in adapter.CHECKPOINT_KEYS:value['fetch_checkpoint_version']=1
    return value


def event(key,n=0):
    start=datetime.now(timezone.utc)+timedelta(days=3,minutes=n)
    return dict(id=f'{key}-{n}',title='Native public program',
        description='Complete publisher participation detail. '*100+'Final native sentence.',
        starts_at=start.isoformat(),ends_at=(start+timedelta(hours=1)).isoformat(),
        venue_name='Reviewed public venue',venue_address='1735 Simpson Ave, Ocean City, NJ 08226',
        venue_city='Ocean City',lat=39.2714578,lng=-74.5900804,event_url='https://example.org/event',
        timezone='America/New_York',reason=None)


class LocalWorkerTests(unittest.TestCase):
    def test_all_six_bounded_sources_preserve_complete_prose_and_street(self):
        for adapter in (community,markets,recreation):
            for key in adapter.SOURCES:
                with self.subTest(source=key):
                    profile=source(adapter,key);row=event(key);state=Harness(self,profile)
                    with patch.object(adapter,'collect',return_value=[deepcopy(row)]):result=state.run()
                    self.assertEqual((result['complete'],result['failed'],result['staged']),(1,0,1))
                    self.assertEqual(state.staged,[row])
                    self.assertGreater(len(state.staged[0]['description']),2000)

    def test_all_three_durable_venues_stage_only_the_completed_snapshot(self):
        for key in venues.SOURCES:
            with self.subTest(source=key):
                profile=source(venues,key);rows=[event(key,n)for n in range(2)]
                state=Harness(self,profile,pages={profile['feed_url']:'native manifest'})
                def chunk(actual,fetch,*,checkpoint,deadline_at):
                    fetch(actual['feed_url'],'text/html')
                    cursor=1 if checkpoint is None else 2
                    return dict(complete=cursor==2,events=deepcopy(rows)if cursor==2 else[],
                        checkpoint=dict(cursor=cursor,manifest_count=2,events=deepcopy(rows[:cursor]),diagnostics=[]))
                with patch.object(venues,'collect_chunk',side_effect=chunk):
                    pending=state.run();self.assertTrue(pending['fetch_pending'])
                    self.assertEqual(state.staged,[])
                    self.assertNotIn(STAGE,[op for op,_ in state.calls]);self.assertNotIn(PUBLISH,[op for op,_ in state.calls])
                    before=len(state.calls);done=state.run()
                    self.assertEqual((done['complete'],done['failed'],done['staged']),(1,0,2))
                    self.assertEqual(state.staged,rows)
                    self.assertIsNone(state.checkpoint)
                    ops=[op for op,_ in state.calls[before:]]
                    self.assertLess(ops.index(WRITE),ops.index(STAGE))
                    self.assertLess(ops.index(RECORD),ops.index(PUBLISH))

    def test_durable_sources_require_checkpoint_path(self):
        for key in venues.SOURCES:
            with self.subTest(source=key),patch.object(worker,'fetch_publisher')as fetch:
                with self.assertRaisesRegex(worker.PreviewError,'publisher_checkpoint_required'):
                    worker.preview_source(source(venues,key))
                fetch.assert_not_called()

    def test_six_bounded_sources_cannot_stage_blank_or_truncated_to_fit_text(self):
        for adapter in (community,markets,recreation):
            for key in adapter.SOURCES:
                for body in ('','   ','x'*12001):
                    row=event(key);row['description']=body
                    with self.subTest(source=key,chars=len(body)),patch.object(adapter,'collect',return_value=[row]):
                        with self.assertRaisesRegex(worker.PreviewError,'atlantic_city_incomplete_event'):
                            worker.preview_source(source(adapter,key))

    def test_native_gateway_transport_remains_guarded_and_host_scoped(self):
        profile=source(community,community.LIBRARY)
        def collect(actual,fetch,*,deadline_at):
            fetch(community.LIBRARY_API+'?limit=100&page=1','application/json')
            return[event(community.LIBRARY)]
        with patch.object(community,'collect',side_effect=collect),patch.object(worker,'fetch_publisher',return_value='{}')as fetch:
            worker.preview_source(profile)
        self.assertTrue(fetch.call_args.kwargs['respect_robots'])
        self.assertEqual(fetch.call_args.kwargs['allowed_hosts'],('gateway.bibliocommons.com',))

    def test_controlled_new_diagnostics_are_visible_without_freeform_errors(self):
        for code in ('ocean_library_manifest_incomplete','newday_calendar_edition_unreviewed',
                     'brigantine_edition_unreviewed','local_markets_snapshot_changed','local_venue_checkpoint_invalid'):
            self.assertEqual(category._error_code(worker.PreviewError(code)),code)
        self.assertEqual(category._error_code(worker.PreviewError('publisher secret value')), 'unclassified_preview_error')


if __name__=='__main__':unittest.main()
