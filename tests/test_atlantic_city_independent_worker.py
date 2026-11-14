"""Exercise the shared production preview boundary for the independent batch."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from roomquest import preview_worker
from roomquest import atlantic_city_social, atlantic_city_independent_venues
from roomquest import atlantic_city_recreation, atlantic_city_markets_gaming
from tests.test_atlantic_city_worker import Harness, CLAIM, STAGE, RECORD, PUBLISH, FINISH


ADAPTERS = (atlantic_city_social, atlantic_city_independent_venues,
            atlantic_city_recreation, atlantic_city_markets_gaming)


def source(adapter, key):
    url, kind, platform = adapter.SOURCES[key]
    return dict(source_key=key, feed_url=url, kind=kind,
                platform_adapter=platform, timezone='America/New_York')


def event(n=0, body=None):
    start = datetime.now(timezone.utc) + timedelta(days=3, minutes=n)
    return dict(id='native-' + str(n), title='Reviewed public event', starts_at=start.isoformat(),
                ends_at=(start + timedelta(hours=2)).isoformat(), description=body or ('Full publisher prose. ' * 220),
                venue_name='Reviewed venue', venue_address='101 E Maryland Ave, Somers Point, NJ 08244',
                venue_city='Somers Point', lat=39.318957, lng=-74.5892325,
                event_url=atlantic_city_social.URL, timezone='America/New_York', reason=None)


class AtlanticIndependentWorkerTests(unittest.TestCase):
    def test_all_nine_profiles_keep_full_records_through_category_publication(self):
        for adapter in ADAPTERS:
            for key in adapter.SOURCES:
                with self.subTest(source=key):
                    profile = source(adapter, key)
                    row = event()
                    row['event_url'] = profile['feed_url']
                    state = Harness(self, profile, pages={profile['feed_url']: 'native publisher calendar'})

                    def collect(actual, fetch, *, deadline_at):
                        self.assertEqual(actual['source_key'], key)
                        fetch(actual['feed_url'], 'text/html')
                        return [deepcopy(row)]

                    with patch.object(adapter, 'collect', side_effect=collect):
                        result = state.run()
                    self.assertEqual((result['complete'], result['failed'], result['staged']), (1, 0, 1))
                    self.assertEqual(state.staged, [row])
                    self.assertGreater(len(state.staged[0]['description']), 2000)
                    self.assertEqual([operation for operation, _ in state.calls],
                                     [CLAIM, STAGE, RECORD, PUBLISH, FINISH])
                    receipt = next(payload for operation, payload in state.calls if operation == RECORD)
                    self.assertIsNone(receipt['p_error'])
                    self.assertEqual(receipt['p_future_count'], 1)

    def test_all_nine_exact_profiles_route_with_existing_transport_guards(self):
        keys = set()
        for adapter in ADAPTERS:
            for key in adapter.SOURCES:
                with self.subTest(source=key):
                    keys.add(key)
                    profile = source(adapter, key)
                    row = event()
                    def collect(profile, fetch, **kwargs):
                        self.assertIsNotNone(kwargs.get('deadline_at'))
                        fetch(profile['feed_url'], 'text/html')
                        return [deepcopy(row)]
                    with patch.object(adapter, 'collect', side_effect=collect), patch.object(preview_worker, 'fetch_publisher', return_value='publisher data') as fetch:
                        result = preview_worker.preview_source(profile)
                    self.assertEqual(result['p_future_count'], 1)
                    self.assertEqual(result['p_events'][0]['description'], row['description'])
                    self.assertGreater(len(result['p_events'][0]['description']), 2000)
                    self.assertEqual(fetch.call_args.args, (profile['feed_url'], 'text/html'))
                    self.assertIs(fetch.call_args.kwargs['respect_robots'], True)
                    self.assertEqual(fetch.call_args.kwargs['allowed_hosts'], adapter.ALLOWED_HOSTS[key])
                    self.assertIsNotNone(fetch.call_args.kwargs['deadline_at'])
        self.assertEqual(len(keys), 9)

    def test_preview_sample_budget_does_not_shorten_staged_descriptions(self):
        rows = [event(n, 'x' * 12000) for n in range(8)]
        with patch.object(atlantic_city_social, 'collect', return_value=deepcopy(rows)):
            result = preview_worker.preview_source(source(atlantic_city_social, atlantic_city_social.CLANCY))
        self.assertEqual(len(result['p_events']), 8)
        self.assertTrue(all(r['description'] == 'x' * 12000 for r in result['p_events']))
        self.assertLess(len(result['p_samples']), len(result['p_events']))

    def test_incomplete_or_over_limit_description_cannot_cross_preview_boundary(self):
        for text in ('', '   ', 'x' * 12001):
            row = event(); row['description'] = text
            with self.subTest(chars=len(text)), patch.object(atlantic_city_social, 'collect', return_value=[row]), self.assertRaisesRegex(preview_worker.PreviewError, 'atlantic_city_incomplete_event'):
                preview_worker.preview_source(source(atlantic_city_social, atlantic_city_social.CLANCY))

    def test_every_adapter_rejects_changed_profile_before_network(self):
        for adapter in ADAPTERS:
            for key in adapter.SOURCES:
                for field, wrong in (('feed_url', 'https://example.org/other'), ('timezone', 'UTC'), ('kind', 'ical')):
                    with self.subTest(source=key, field=field), patch.object(preview_worker, 'fetch_publisher') as fetch:
                        profile = source(adapter, key); profile[field] = wrong
                        with self.assertRaises(preview_worker.PreviewError):
                            preview_worker.preview_source(profile)
                        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
