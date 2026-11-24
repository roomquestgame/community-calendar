"""Generic HTML continuation: no live transport, claims, staging or publication."""
from datetime import datetime, timedelta, timezone
import json
from time import monotonic
import unittest
from unittest.mock import patch

from roomquest import registered_html_calendar as calendar
from roomquest import feedzilla_pagination_checkpoint as progress
from roomquest.registration_formats import source_key
from roomquest.registered_native_content import validate_record

FEED = 'https://venue.example.org/events'


def source(url=FEED):
    return {'source_key': source_key(url), 'feed_url': url, 'kind': 'html',
            'platform_adapter': 'html', 'registered_html_calendar_version': 1,
            'registered_native_content_version': 1}


def listing(urls, nxt=None, prev=None):
    return ('<html><main><h1>Upcoming Events</h1>'
            + ''.join('<a href="' + url + '">Event</a>' for url in urls)
            + ('<link rel="next" href="' + nxt + '">' if nxt else '')
            + ('<link rel="prev" href="' + prev + '">' if prev else '')
            + '</main></html>')


def detail(url):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    event = {'@context': 'https://schema.org', '@type': 'MusicEvent',
             '@id': '#event', 'url': url, 'name': 'Publisher concert',
             'startDate': start.isoformat(),
             'endDate': (start + timedelta(hours=2)).isoformat(),
             'description': '<p>Live musical performance</p>',
             'image': '/images/poster.jpg',
             'location': {'@type': 'Place', 'name': 'Publisher Hall',
                          'address': {'@type': 'PostalAddress',
                                      'streetAddress': '12 Main St',
                                      'addressLocality': 'Richmond',
                                      'addressRegion': 'VA',
                                      'postalCode': '23220'}}}
    return ('<html><head><link rel="canonical" href="' + url
            + '"><script type="application/ld+json">' + json.dumps(event)
            + '</script></head></html>')


def fixture(n=9, d=5):
    pages, ordered, detail_order = {}, [], []
    for i in range(1, n + 1):
        url = FEED if i == 1 else FEED + '?page=' + str(i)
        nxt = FEED + '?page=' + str(i + 1) if i < n else None
        prev = None if i == 1 else FEED if i == 2 else FEED + '?page=' + str(i - 1)
        urls = ['https://venue.example.org/event/show-' + str(i) + '-' + str(k)
                for k in range(d)]
        pages[url] = listing(urls, nxt, prev)
        ordered.append(url)
        for event_url in urls:
            pages[event_url] = detail(event_url)
            detail_order.append(event_url)
    return pages, ordered + detail_order


def prefix(pages, order, n):
    return [{'url': url, 'body': pages[url]} for url in order[:n]]


class RegisteredHTMLContinuationTests(unittest.TestCase):
    def test_small_normal_and_resumed_projection_agree(self):
        pages, order = fixture(4, 2)
        calls = []

        def fetch(url, accept):
            calls.append(url)
            return pages[url]

        got = calendar.collect(source(), fetch)
        _, request, resumed = calendar.resume_capture(source(), prefix(pages, order, len(order)))
        self.assertIsNone(request)
        self.assertEqual(got, resumed)
        self.assertEqual(len(got), 8)
        self.assertEqual(calls, order)
        for row in got:
            validate_record(row, source())

    def test_supplied_listing_reused(self):
        pages, order = fixture(1, 2)
        calls = []

        def fetch(url, accept):
            calls.append(url)
            return pages[url]

        self.assertEqual(len(calendar.collect(source(), fetch, listing=pages[FEED])), 2)
        self.assertEqual(calls, order[1:])

    def test_ordinary_cap_unchanged(self):
        pages, order = fixture()
        calls = []

        def fetch(url, accept):
            calls.append(url)
            return pages[url]

        with self.assertRaisesRegex(ValueError, 'html_calendar_(pagination|detail)_limit'):
            calendar.collect(source(), fetch)
        self.assertEqual(len(calls), calendar.MAX_LISTING_PAGES)

    def test_resume_54_requests_actual_normalization(self):
        pages, order = fixture()
        captured, gets = [], []
        while len(captured) < len(order):
            stream, request, records = calendar.resume_capture(source(), captured)
            self.assertIsNone(records)
            for _ in range(7):
                url, accept = request
                self.assertEqual(url, order[len(captured)])
                gets.append(url)
                body = pages[url]
                captured.append({'url': url, 'body': body})
                try:
                    request = stream.send(body)
                except StopIteration as finished:
                    self.assertEqual(len(finished.value), 45)
                    break
        _, request, rows = calendar.resume_capture(source(), captured)
        self.assertIsNone(request)
        self.assertEqual(len(rows), 45)
        self.assertEqual(gets, order)
        self.assertEqual(len(set(gets)), 54)
        for row in rows:
            validate_record(row, source())

    def test_incomplete_final_detail(self):
        pages, order = fixture(2, 2)
        _, request, rows = calendar.resume_capture(source(), prefix(pages, order, len(order)-1))
        self.assertEqual(request[0], order[-1])
        self.assertIsNone(rows)

    def test_wrong_order(self):
        pages, order = fixture(2, 2)
        with self.assertRaisesRegex(ValueError, 'html_calendar_capture_order_conflict'):
            calendar.resume_capture(source(), prefix(pages, [order[1]], 1))

    def test_extra_capture(self):
        pages, order = fixture(1, 1)
        captured = prefix(pages, order, len(order))
        with self.assertRaisesRegex(ValueError, 'html_calendar_capture_order_conflict'):
            calendar.resume_capture(source(), captured + [captured[-1]])

    def test_foreign_scope(self):
        with self.assertRaisesRegex(ValueError, 'html_calendar_pagination_scope_conflict'):
            calendar.resume_capture(source(), [{'url': FEED, 'body': listing(
                ['https://venue.example.org/event/a'], 'https://foreign.example.org/events?page=2')}])

    def test_same_inventory(self):
        url, p2 = 'https://venue.example.org/event/a', FEED + '?page=2'
        with self.assertRaisesRegex(ValueError, 'html_calendar_pagination_stalled'):
            calendar.resume_capture(source(), [{'url': FEED, 'body': listing([url], p2)},
                                               {'url': p2, 'body': listing([url])}])

    def test_wrong_source(self):
        wrong = dict(source(), source_key='municipal_wrong')
        with self.assertRaisesRegex(ValueError, 'unregistered_html_calendar'):
            calendar.resume_capture(wrong, [])

    def test_expired_deadline(self):
        with self.assertRaisesRegex(ValueError, 'collection_deadline'):
            calendar.resume_capture(source(), [], deadline_at=monotonic()-1)

    def test_invalid_last_detail(self):
        pages, order = fixture(1, 2)
        pages[order[-1]] = '<html></html>'
        with self.assertRaisesRegex(ValueError, 'html_calendar_event_jsonld_missing'):
            calendar.resume_capture(source(), prefix(pages, order, len(order)))

    def test_scope_selectors(self):
        url = FEED + '?venue=3'
        p2 = url + '&page=2'
        _, request, rows = calendar.resume_capture(source(url), [{'url': url, 'body': listing(
            ['https://venue.example.org/event/a'], p2)}])
        self.assertEqual(request[0], p2)
        self.assertIsNone(rows)

    def test_task_ceiling(self):
        with patch.object(progress, 'MAX_TASKS', 3):
            with self.assertRaisesRegex(ValueError, 'html_calendar_request_limit'):
                calendar.resume_capture(source(), [{'url': FEED, 'body': listing(
                    ['https://venue.example.org/event/a', 'https://venue.example.org/event/b'],
                    FEED + '?page=2')}])

    def test_body_ceiling(self):
        with self.assertRaisesRegex(ValueError, 'html_calendar_capture_limit'):
            calendar.resume_capture(source(), [{'url': FEED,
                                                'body': 'x' * (calendar.MAX_HTML_BYTES + 1)}])

    def test_forestry_stays_out_of_generic_resume(self):
        with patch('roomquest.forestry_england.owns_url', return_value=True):
            with self.assertRaisesRegex(ValueError, 'html_calendar_capture_unsupported'):
                calendar.resume_capture(source(), [])


if __name__ == '__main__':
    unittest.main()
