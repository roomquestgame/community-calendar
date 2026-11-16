import unittest
from unittest.mock import Mock

from roomquest.things_to_do_search import (benchmark_queries, canonical_url,
                                          free_allowance, run_search)


def usage(**changes):
    account = dict(current_plan="Free", plan_usage=20, plan_limit=1000,
                   paygo_usage=0, paygo_limit=0)
    account.update(changes)
    return {"account": account}


class SearchTests(unittest.TestCase):
    def test_benchmark_is_exactly_twenty_distinct_queries(self):
        jobs = benchmark_queries()
        self.assertEqual(len(jobs), 20)
        self.assertEqual(len({j['identity'] for j in jobs}), 20)
        self.assertEqual({j['location'] for j in jobs}, {
            'Fairfax County, Virginia', 'Arlington, Virginia',
            'South Hill, Virginia', 'Chase City, Virginia'})

    def test_account_fence_fails_closed(self):
        self.assertEqual(free_allowance(usage()), 930)
        for change in ({'paygo_limit': 1}, {'paygo_usage': 1},
                       {'current_plan': 'Bootstrap'}, {'plan_usage': float('nan')},
                       {'plan_limit': 15000}, {'plan_usage': None}):
            self.assertIsNone(free_allowance(usage(**change)))
        self.assertIsNone(free_allowance({'key': {'limit': 950}}))

    def test_urls_are_untrusted_and_fragments_coalesce(self):
        self.assertEqual(canonical_url('https://PARKS.gov/trails#walk'), 'https://parks.gov/trails')
        for url in ('http://parks.gov', 'https://127.0.0.1/x', 'https://[::1]/',
                    'https://a.local/x', 'https://a:b@parks.gov/', 'https://parks.gov:444/',
                    'https://parks.gov\\@evil.test/'):
            self.assertIsNone(canonical_url(url), url)

    def run_search(self, response=None, allowance=None, admission=None):
        calls = []
        def request(key, endpoint, payload=None):
            calls.append(endpoint)
            if endpoint == 'usage':
                return allowance or usage()
            if isinstance(response, Exception):
                raise response
            self.assertEqual(payload['search_depth'], 'basic')
            self.assertFalse(payload['auto_parameters'])
            self.assertFalse(payload['include_answer'])
            self.assertFalse(payload['include_raw_content'])
            return response or {'usage': {'credits': 1}, 'request_id': 'provider-id', 'results': []}
        def database(action, payload):
            calls.append(action)
            if action == 'reserve_search':
                return admission or {'status': 'reserved', 'reservation_id': 'r', 'lease_token': 't'}
            return payload
        result = run_search(key='fixture', job={'id': 'q', 'query': 'dog parks South Hill, Virginia'},
                            database=database, request=request)
        return result, calls

    def test_reservation_precedes_spend_and_receipt_reconciles(self):
        result, calls = self.run_search()
        self.assertEqual(calls, ['usage', 'reserve_search', 'search', 'finish_search'])
        self.assertEqual(result['outcome'], 'success')
        self.assertEqual(result['credits'], 1)

    def test_no_network_when_credentials_missing(self):
        request = Mock()
        result = run_search(key='', job={}, database=Mock(), request=request)
        self.assertEqual(result['status'], 'search_credentials_missing')
        request.assert_not_called()

    def test_no_spend_without_account_fence_or_database_reservation(self):
        result, calls = self.run_search(allowance=usage(paygo_limit=100))
        self.assertEqual(result['status'], 'account_free_only_blocked')
        self.assertEqual(calls, ['usage'])
        result, calls = self.run_search(admission={'status': 'budget_exhausted'})
        self.assertEqual(calls, ['usage', 'reserve_search'])

    def test_ambiguous_failure_keeps_charge_and_never_retries(self):
        result, calls = self.run_search(response=TimeoutError('sensitive provider content'))
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertNotIn('credits', result)
        self.assertEqual(calls.count('search'), 1)

    def test_provider_content_does_not_enter_candidate_facts(self):
        result, _ = self.run_search(response={'usage': {'credits': 1}, 'results': [
            {'url': 'https://parks.gov/a#first', 'title': 'Park', 'score': .8,
             'content': 'unverified claim', 'raw_content': 'unverified page'},
            {'url': 'https://parks.gov/a#second', 'title': 'Duplicate'}]})
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(set(result['candidates'][0]), {'url', 'title', 'rank', 'score'})


if __name__ == '__main__':
    unittest.main()
