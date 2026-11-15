"""The three remaining publishers keep full prose across the existing worker."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from roomquest import atlantic_city_remaining_fair as fair
from roomquest import atlantic_city_remaining_inland as inland
from roomquest import atlantic_city_remaining_balic as balic
from roomquest import preview_worker as worker, category_worker as category
from tests.test_atlantic_city_worker import Harness, READ, WRITE, STAGE, RECORD, PUBLISH


ADAPTERS = (fair, inland, balic)


def source(adapter):
    key = next(iter(adapter.SOURCES))
    url, kind, parser = adapter.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind,
                platform_adapter=parser, timezone='America/New_York')


def event(key, number=0):
    start = datetime.now(timezone.utc) + timedelta(days=3, minutes=number)
    return dict(id=f'{key}-{number}', title='Native community program',
                description='Complete publisher participation details. ' * 100 + 'The final native sentence.',
                starts_at=start.isoformat(), ends_at=(start + timedelta(hours=1)).isoformat(),
                venue_name='Reviewed public venue',
                venue_address='3050 Spruce Avenue, Egg Harbor Township, NJ 08234',
                venue_city='Egg Harbor Township', lat=39.411594, lng=-74.5859745,
                event_url='https://example.org/event', timezone='America/New_York', reason=None)


class RemainingWorkerTests(unittest.TestCase):
    def test_all_three_stage_full_description_and_street_without_checkpoint(self):
        for adapter in ADAPTERS:
            with self.subTest(adapter=adapter.__name__):
                profile = source(adapter)
                row = event(profile['source_key'])
                state = Harness(self, profile)
                with patch.object(adapter, 'collect', return_value=[deepcopy(row)]):
                    result = state.run()
                self.assertEqual((result['complete'], result['failed'], result['staged']), (1, 0, 1))
                self.assertEqual(state.staged, [row])
                self.assertGreater(len(state.staged[0]['description']), 2000)
                operations = [operation for operation, _ in state.calls]
                self.assertFalse({READ, WRITE} & set(operations))
                self.assertLess(operations.index(STAGE), operations.index(RECORD))
                self.assertLess(operations.index(RECORD), operations.index(PUBLISH))

    def test_preview_sample_budget_does_not_clip_staged_records(self):
        for adapter in ADAPTERS:
            profile = source(adapter)
            rows = [event(profile['source_key'], n) for n in range(6)]
            with self.subTest(adapter=adapter.__name__), patch.object(adapter, 'collect', return_value=rows):
                result = worker.preview_source(profile)
                self.assertEqual(result['p_events'], rows)
                self.assertEqual(result['p_future_count'], 6)
                self.assertLess(len(result['p_samples']), len(rows))

    def test_blank_missing_and_oversize_descriptions_never_stage(self):
        for adapter in ADAPTERS:
            profile = source(adapter)
            for body in (None, '', '  ', 'x' * 12001):
                row = event(profile['source_key'])
                row['description'] = body
                with self.subTest(adapter=adapter.__name__, body_length=len(body or '')):
                    with patch.object(adapter, 'collect', return_value=[row]):
                        with self.assertRaisesRegex(worker.PreviewError, 'atlantic_city_incomplete_event'):
                            worker.preview_source(profile)

    def test_missing_street_never_stages(self):
        for adapter in ADAPTERS:
            profile = source(adapter)
            row = event(profile['source_key'])
            row['venue_address'] = ' '
            with self.subTest(adapter=adapter.__name__), patch.object(adapter, 'collect', return_value=[row]):
                with self.assertRaisesRegex(worker.PreviewError, 'atlantic_city_incomplete_event'):
                    worker.preview_source(profile)

    def test_every_callback_retains_exact_hosts_robots_and_deadline(self):
        for adapter in ADAPTERS:
            profile = source(adapter)
            def collect(actual, fetch, *, deadline_at):
                self.assertEqual(actual, profile)
                fetch(actual['feed_url'], 'text/html')
                return [event(actual['source_key'])]
            with self.subTest(adapter=adapter.__name__):
                with patch.object(adapter, 'collect', side_effect=collect):
                    with patch.object(worker, 'fetch_publisher', return_value='native body') as fetch:
                        worker.preview_source(profile)
                self.assertTrue(fetch.call_args.kwargs['respect_robots'])
                self.assertEqual(fetch.call_args.kwargs['allowed_hosts'], adapter.ALLOWED_HOSTS[profile['source_key']])
                self.assertIsInstance(fetch.call_args.kwargs['deadline_at'], (int, float))

    def test_source_specific_diagnostics_survive_without_arbitrary_messages(self):
        for code in ('atlantic_fair_description_incomplete', 'balic_performer_clock_conflict',
                     'inland_calendar_edition_unreviewed'):
            self.assertEqual(category._error_code(worker.PreviewError(code)), code)
        self.assertEqual(category._error_code(worker.PreviewError('publisher_secret_value')), 'unclassified_preview_error')

    def test_failed_complete_snapshot_cannot_publish_partial_events(self):
        for adapter, code in ((fair, 'atlantic_fair_manifest_incomplete'),
                              (inland, 'inland_calendar_edition_unreviewed'),
                              (balic, 'balic_performer_clock_conflict')):
            with self.subTest(adapter=adapter.__name__):
                state = Harness(self, source(adapter))
                with patch.object(adapter, 'collect', side_effect=ValueError(code)):
                    result = state.run()
                self.assertEqual(result['failed'], 1)
                self.assertFalse({STAGE, PUBLISH} & {operation for operation, _ in state.calls})
                recorded = next(payload for operation, payload in state.calls if operation == RECORD)
                self.assertEqual(recorded['p_error'], code)


if __name__ == '__main__':
    unittest.main()
