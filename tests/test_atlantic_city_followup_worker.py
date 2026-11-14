"""New feeds use the existing full-record and durable-completion worker seams."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from roomquest import preview_worker as worker
from roomquest import atlantic_city_reviewed_posters as posters
from roomquest import atlantic_city_studio as studio
from roomquest import atlantic_city_cardboard_arena as cardboard
from tests.test_atlantic_city_worker import Harness, READ, WRITE, STAGE, RECORD, PUBLISH, FINISH


def source(adapter,key):
    url,kind,platform=adapter.SOURCES[key]
    row=dict(source_key=key,feed_url=url,kind=kind,platform_adapter=platform,timezone='America/New_York')
    if key in getattr(adapter,'CHECKPOINT_KEYS',()):row['fetch_checkpoint_version']=1
    return row


def event(key,n=0):
    start=datetime.now(timezone.utc)+timedelta(days=3,minutes=n)
    return dict(id=f'{key}-{n}',title='Native public program',description='Complete publisher paragraph. '*100+'Last native sentence.',
                starts_at=start.isoformat(),ends_at=(start+timedelta(hours=1)).isoformat(),
                venue_name='Exact venue',venue_address='1637 New Road Suite 2, Northfield, NJ 08225',
                venue_city='Northfield',lat=39.3706889,lng=-74.5584344,event_url='https://example.org/event',
                timezone='America/New_York',reason=None)


class FollowupWorkerTests(unittest.TestCase):
    def test_both_poster_sources_preserve_full_prose_and_address(self):
        for key in posters.SOURCES:
            with self.subTest(source=key):
                profile=source(posters,key);row=event(key);row['event_url']=profile['feed_url']
                state=Harness(self,profile)
                with patch.object(posters,'collect',return_value=[deepcopy(row)]):result=state.run()
                self.assertEqual((result['complete'],result['failed'],result['staged']),(1,0,1))
                self.assertEqual(state.staged,[row])
                self.assertGreater(len(state.staged[0]['description']),2000)

    def test_both_durable_collectors_publish_only_the_complete_snapshot(self):
        for adapter in (studio,cardboard):
            key=next(iter(adapter.CHECKPOINT_KEYS));profile=source(adapter,key)
            with self.subTest(source=key):
                rows=[event(key,n) for n in range(2)];state=Harness(self,profile,pages={profile['feed_url']:'native manifest'})
                def chunk(actual,fetch,*,checkpoint,deadline_at,**extra):
                    self.assertEqual(actual['source_key'],key)
                    self.assertIsNotNone(deadline_at)
                    fetch(actual['feed_url'],'text/html')
                    if adapter is cardboard:
                        self.assertEqual(set(extra),{'render_calendar'})
                        self.assertEqual(extra['render_calendar'](starts_at='2026-11-14T00:00:00Z',ends_at='2027-01-13T00:00:00Z'),'native manifest')
                    else:self.assertEqual(extra,{})
                    cursor=1 if checkpoint is None else 2
                    saved=dict(cursor=cursor,manifest_count=2,events=deepcopy(rows[:cursor]))
                    return dict(complete=cursor==2,events=deepcopy(rows) if cursor==2 else [],checkpoint=saved)
                with patch.object(adapter,'collect_chunk',side_effect=chunk),patch.object(worker,'render_cardboard_arena_calendar',return_value='native manifest') as render:
                    pending=state.run()
                    self.assertTrue(pending['fetch_pending']);self.assertEqual(state.staged,[])
                    self.assertNotIn(STAGE,[op for op,_ in state.calls]);self.assertNotIn(PUBLISH,[op for op,_ in state.calls])
                    first=len(state.calls)
                    complete=state.run()
                    self.assertEqual((complete['complete'],complete['failed'],complete['staged']),(1,0,2))
                    self.assertEqual(state.staged,rows)
                    self.assertIsNone(state.checkpoint)
                    operations=[op for op,_ in state.calls[first:]]
                    self.assertLess(operations.index(WRITE),operations.index(STAGE))
                    self.assertLess(operations.index(RECORD),operations.index(PUBLISH))
                    if adapter is cardboard:
                        self.assertEqual(render.call_count,2)
                        self.assertIsNotNone(render.call_args.kwargs['deadline_at'])

    def test_durable_sources_cannot_use_an_uncheckpointed_preview(self):
        for adapter in (studio,cardboard):
            profile=source(adapter,next(iter(adapter.CHECKPOINT_KEYS)))
            with self.subTest(source=profile['source_key']),patch.object(worker,'fetch_publisher') as fetch:
                with self.assertRaisesRegex(worker.PreviewError,'publisher_checkpoint_required'):worker.preview_source(profile)
                fetch.assert_not_called()

    def test_poster_boundary_rejects_blank_or_over_limit_text(self):
        for key in posters.SOURCES:
            for description in ('','   ','x'*12001):
                row=event(key);row['description']=description
                with self.subTest(source=key,length=len(description)),patch.object(posters,'collect',return_value=[row]):
                    with self.assertRaisesRegex(worker.PreviewError,'atlantic_city_incomplete_event'):
                        worker.preview_source(source(posters,key))


if __name__=='__main__':unittest.main()
