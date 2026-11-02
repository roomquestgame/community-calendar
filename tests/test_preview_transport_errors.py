"""Transport failures must survive normalization without staging partial data."""
import json
import unittest
from unittest.mock import patch

from roomquest.preview_worker import PreviewError, _process_claimed_source, preview_source


class TransportErrorTests(unittest.TestCase):
    source = {
        'source_key': 'nebraska_game_parks', 'kind': 'json',
        'platform_adapter': 'wordpress',
        'feed_url': 'https://calendar.outdoornebraska.gov/wp-json/tribe/events/v1/events',
    }

    def test_http_status_survives_all_family_error_handlers(self):
        for kind, adapter in [('ical', 'ical'), ('json', 'wordpress'),
                              ('json', 'jsonld'), ('json', 'squarespace')]:
            for code in ('publisher_http_403', 'publisher_http_429', 'publisher_http_503'):
                with self.subTest(adapter=adapter, code=code):
                    source = dict(self.source, source_key='municipal_mapsee_fixture',
                                  kind=kind, platform_adapter=adapter)
                    profile = {'url': source['feed_url'], 'type':
                               {'ical': 'ics', 'wordpress': 'tribe'}.get(adapter, adapter)}
                    failure = PreviewError(code)
                    with patch('roomquest.mapsee_adapter.profiles', return_value={source['source_key']: profile}), \
                         patch('roomquest.preview_worker.fetch_publisher', side_effect=failure):
                        with self.assertRaises(PreviewError) as caught:
                            preview_source(source)
                    self.assertIs(caught.exception, failure)

    def test_worker_records_failure_without_staging_or_marking_complete(self):
        with patch('roomquest.preview_worker.fetch_publisher', side_effect=PreviewError('publisher_http_403')), \
             patch('roomquest.preview_worker.supabase_rpc') as rpc:
            result = _process_claimed_source(self.source)
        self.assertEqual(result, {'complete': 0, 'failed': 1, 'staged': 0})
        rpc.assert_called_once()
        self.assertEqual(rpc.call_args.args[0], 'community_collector_record_preview')
        self.assertEqual(rpc.call_args.args[1]['p_error'], 'publisher_http_403')
        self.assertEqual(rpc.call_args.args[1]['p_future_count'], 0)

    def test_raw_parser_messages_remain_sanitized(self):
        with patch('roomquest.preview_worker.fetch_publisher', return_value='<html>private response text</html>'):
            with self.assertRaisesRegex(PreviewError, '^invalid_calendar_payload$'):
                preview_source(self.source)
