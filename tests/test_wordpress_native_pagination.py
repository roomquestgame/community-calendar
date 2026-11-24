"""Provider inventory evidence on the existing registered WordPress path."""
from datetime import datetime, timedelta, timezone
from hashlib import md5
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from roomquest.wordpress_adapter import collect

FEED = 'https://venue.example.org/wp-json/tribe/events/v1/events'
SOURCE = {'source_key': 'municipal_' + md5(
    ('feed_registration:' + FEED).encode()).hexdigest()[:24], 'feed_url': FEED}


def event(identity, *, status='publish', start=None):
    start = start or datetime.now(timezone.utc) + timedelta(days=3)
    return {'id': identity, 'title': 'Local concert', 'status': status,
            'start_date': start.strftime('%Y-%m-%d %H:%M:%S'),
            'utc_start_date': start.strftime('%Y-%m-%d %H:%M:%S'),
            'utc_end_date': (start + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S'),
            'timezone': 'Europe/London',
            'url': 'https://venue.example.org/event/concert-' + str(identity),
            'venue': {'venue': 'Village Hall', 'address': '15 High Street',
                      'city': 'Cambridge', 'zip': 'CB1 1AA', 'country': 'United Kingdom'}}


def response(events, total, pages, *, more=False):
    result = {'events': events, 'total': total, 'total_pages': pages}
    if more:
        result['next_rest_url'] = 'https://venue.example.org/wp-json/tribe/events/v1/events?page=2'
    return result


class RegisteredTECInventoryTests(unittest.TestCase):
    def run_pages(self, pages, source=None):
        requests = []
        def fetch(url, accept):
            self.assertEqual(accept, 'application/json')
            parsed = urlsplit(url)
            self.assertEqual(parsed.hostname, 'venue.example.org')
            number = int(parse_qs(parsed.query)['page'][0])
            requests.append(number)
            return json.dumps(pages[number-1])
        result = collect(source or SOURCE, fetch)
        return result, requests

    def test_two_pages_with_declared_inventory_and_private_record(self):
        rows, calls = self.run_pages([
            response([event(1), event(2, status='draft')], 3, 2, more=True),
            response([event(3)], 3, 2)])
        self.assertEqual(calls, [1, 2])
        self.assertEqual({row['id'] for row in rows}, {'1','3'})

    def test_missing_member_at_terminal_is_not_a_complete_collection(self):
        with self.assertRaisesRegex(ValueError, 'wordpress_pagination_incomplete'):
            self.run_pages([response([event(1)], 3, 2, more=True),
                            response([event(2)], 3, 2)])

    def test_changed_or_missing_declared_totals(self):
        for last in [response([event(2)], 3, 2),
                     {'events': [event(2)], 'total_pages': 2},
                     response([event(2)], 2, 1)]:
            with self.subTest(last=last), self.assertRaisesRegex(ValueError, 'wordpress_pagination_changed'):
                self.run_pages([response([event(1)], 2, 2, more=True), last])

    def test_repeated_raw_member_across_pages(self):
        item = event(1)
        with self.assertRaisesRegex(ValueError, 'wordpress_pagination_duplicate'):
            self.run_pages([response([item], 2, 2, more=True),
                            response([item], 2, 2)])

    def test_recurring_post_id_with_distinct_start_is_not_duplicate(self):
        t = datetime.now(timezone.utc) + timedelta(days=2)
        rows, calls = self.run_pages([response([event(1, start=t)], 2, 2, more=True),
                            response([event(1, start=t + timedelta(days=1))], 2, 2)])
        self.assertEqual(len(rows), 2)

    def test_declared_terminal_page_cannot_also_have_next(self):
        with self.assertRaisesRegex(ValueError, 'wordpress_pagination_incomplete'):
            self.run_pages([response([event(1)], 1, 1, more=True)])

    def test_empty_intermediate_page_is_not_complete(self):
        with self.assertRaisesRegex(ValueError, 'wordpress_pagination_incomplete'):
            self.run_pages([response([], 2, 2, more=True)])

    def test_empty_inventory_accepts_existing_tec_conventions(self):
        for page_count in [0, 1]:
            rows, calls = self.run_pages([response([], 0, page_count)])
            self.assertEqual(rows, [])
            self.assertEqual(calls, [1])

    def test_over_existing_page_budget_is_held(self):
        with self.assertRaisesRegex(ValueError, 'pagination_limit'):
            self.run_pages([response([event(1)], 600, 6, more=True)])

    def test_older_body_without_counts_keeps_existing_compatibility(self):
        rows, calls = self.run_pages([{'events': [event(1)]}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(calls, [1])

    def test_legacy_source_outside_new_registered_guard_is_unchanged(self):
        rows, calls = self.run_pages([response([event(1)], 9, 1)],
                                     source={'feed_url': FEED})
        self.assertEqual(len(rows), 1)


if __name__ == '__main__':
    unittest.main()
