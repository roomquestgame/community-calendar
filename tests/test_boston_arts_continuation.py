"""Source-specific throughput keeps the existing time and publisher boundaries."""
from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from roomquest import boston_arts as arts, boston_arts_remaining as museums
from roomquest import preview_worker as worker
from tests.test_boston_arts import bpl_payload, source as arts_source
from tests.test_boston_arts_remaining import NOW, mfa_detail, mfa_listing, source as museum_source
from tests.test_new_york_arts import fake_record


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ArtsContinuationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (arts, museums):
            self.stack.enter_context(patch.object(module, 'record', side_effect=fake_record))
        self.clock = Clock()
        for module in (arts, museums, worker):
            self.stack.enter_context(patch.object(module, 'monotonic', side_effect=self.clock.now))

    def test_mfa_bounded_listing_saves_complete_pages_before_detail_phase(self):
        calls = []

        def fetch(url, accept):
            page = int(parse_qs(urlsplit(url).query).get('page', ['0'])[0])
            calls.append(page)
            return mfa_listing(page + 1, page + 1 if page < 4 else None)

        first = museums.collect_chunk(museum_source(museums.MFA), fetch, now=NOW, deadline_at=36)
        self.assertEqual(calls, [0, 1, 2, 3])
        self.assertFalse(first['checkpoint']['listing_complete'])
        self.assertEqual(first['checkpoint']['manifest_count'], 4)
        self.assertEqual(first['checkpoint']['cursor'], 0)
        self.assertEqual(first['events'], [])
        self.assertFalse(first['complete'])
        museums._checkpoint(first['checkpoint'], museums.MFA, NOW)
        second = museums.collect_chunk(museum_source(museums.MFA), fetch,
            checkpoint=first['checkpoint'], now=NOW, deadline_at=36)
        self.assertEqual(calls, [0, 1, 2, 3, 4])
        self.assertTrue(second['checkpoint']['listing_complete'])
        self.assertEqual(second['checkpoint']['manifest_count'], 5)
        self.assertEqual(second['checkpoint']['started_at'], first['checkpoint']['started_at'])
        self.assertEqual(second['checkpoint']['cursor'], 0)
        self.assertEqual(second['events'], [])

    def test_mfa_listing_stops_at_twelve_second_reserve_and_resumes_same_page(self):
        calls = []

        def fetch(url, accept):
            page = int(parse_qs(urlsplit(url).query).get('page', ['0'])[0])
            calls.append(page)
            self.clock.advance(12)
            return mfa_listing(page + 1, page + 1)

        first = museums.collect_chunk(museum_source(museums.MFA), fetch, now=NOW, deadline_at=36)
        self.assertEqual(calls, [0, 1])
        self.assertEqual(first['checkpoint']['next_page'], museums.SOURCES[museums.MFA][0] + '?page=2')
        self.assertEqual(first['checkpoint']['cursor'], 0)
        self.assertEqual(first['events'], [])
        original = deepcopy(first['checkpoint'])
        fetch_blocked = Mock()
        with self.assertRaisesRegex(ValueError, '^collection_deadline$'):
            museums.collect_chunk(museum_source(museums.MFA), fetch_blocked,
                checkpoint=original, now=NOW, deadline_at=36)
        fetch_blocked.assert_not_called()
        self.assertEqual(original, first['checkpoint'])

    def test_mfa_twenty_detail_cap_uses_actual_publisher_pacing(self):
        listing = ''.join(mfa_listing(n) for n in range(1, 23)).replace('</main><main>', '')
        state = museums.collect_chunk(museum_source(museums.MFA), Mock(return_value=listing), now=NOW)['checkpoint']
        host = 'www.mfa.org'
        calls = []
        self.stack.enter_context(patch.dict(worker._publisher_next, {}, clear=True))
        self.stack.enter_context(patch.dict(worker._publisher_retry_after, {}, clear=True))
        self.stack.enter_context(patch.dict(worker._robots_delays, {host: 1}, clear=True))
        self.stack.enter_context(patch.object(worker, 'sleep', side_effect=self.clock.advance))

        def fetch(url, accept):
            self.assertLess(self.clock.now() + 12, 36)
            worker.pace_publisher(host, 36)
            calls.append((url, self.clock.now()))
            self.clock.advance(0.25)
            return mfa_detail(int(url.rsplit('=', 1)[1]))

        chunk = museums.collect_chunk(museum_source(museums.MFA), fetch,
            checkpoint=state, now=NOW, deadline_at=36)
        self.assertEqual(len(calls), 20)
        self.assertEqual(chunk['checkpoint']['cursor'], 20)
        self.assertTrue(all(b[1] - a[1] >= 1 for a, b in zip(calls, calls[1:])))
        self.assertLess(self.clock.now(), 24)
        self.assertFalse(chunk['complete'])
        self.assertEqual(chunk['events'], [])

    def test_bpl_six_page_cap_keeps_cardinality_and_deadline_guards(self):
        calls = []

        def fetch(url, accept):
            page = int(parse_qs(urlsplit(url).query)['page'][0])
            calls.append(page)
            self.clock.advance(1)
            return bpl_payload(page, pages=8)

        first = arts.collect_chunk(arts_source(arts.BPL), fetch, now=NOW, deadline_at=36)
        self.assertEqual(calls, [1, 2, 3, 4, 5, 6])
        self.assertEqual(first['checkpoint']['cursor'], 6)
        self.assertFalse(first['complete'])
        self.assertEqual(first['events'], [])
        arts._bpl_checkpoint(first['checkpoint'], NOW)
        final = arts.collect_chunk(arts_source(arts.BPL), fetch,
            checkpoint=first['checkpoint'], now=NOW, deadline_at=36)
        self.assertTrue(final['complete'])
        self.assertEqual(calls, list(range(1, 9)))
        self.assertEqual(len(final['checkpoint']['seen_ids']), final['checkpoint']['native_count'])
        self.assertEqual(final['checkpoint']['started_at'], first['checkpoint']['started_at'])

        self.clock.value = 23
        slow_calls = []

        def slow_fetch(url, accept):
            slow_calls.append(url)
            self.clock.advance(2)
            return bpl_payload(1, pages=8)

        slow = arts.collect_chunk(arts_source(arts.BPL), slow_fetch, now=NOW, deadline_at=36)
        self.assertEqual(len(slow_calls), 1)
        self.assertEqual(slow['checkpoint']['cursor'], 1)
        self.assertEqual(slow['events'], [])
        blocked = Mock()
        with self.assertRaisesRegex(ValueError, '^collection_deadline$'):
            arts.collect_chunk(arts_source(arts.BPL), blocked,
                checkpoint=slow['checkpoint'], now=NOW, deadline_at=36)
        blocked.assert_not_called()

    def test_transport_denial_or_deferred_pacing_never_becomes_a_skipped_page(self):
        for reason in ('robots_denied', 'publisher_http_403', 'publisher_pacing_deferred'):
            fetch = Mock(side_effect=[mfa_listing(1, 1), worker.PreviewError(reason)])
            with self.subTest(reason=reason), self.assertRaisesRegex(worker.PreviewError, '^' + reason + '$'):
                museums.collect_chunk(museum_source(museums.MFA), fetch, now=NOW, deadline_at=36)
            self.assertEqual(fetch.call_count, 2)


if __name__ == '__main__':
    unittest.main()
