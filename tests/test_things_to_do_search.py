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
    def test_fixed_canary_billing_review_expires_without_relaxing_usage(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=48)).isoformat()
        self.assertEqual(free_allowance(usage(paygo_limit=None), reviewed_until=future), 930)
        for expiry in [(now-timedelta(seconds=1)).isoformat(), (now+timedelta(hours=73)).isoformat(),
                       'not-a-date', '2026-11-18', None]:
            self.assertIsNone(free_allowance(usage(paygo_limit=None), reviewed_until=expiry))
        self.assertIsNone(free_allowance(usage(paygo_limit=1), reviewed_until=future))
        self.assertIsNone(free_allowance(usage(paygo_limit=None, paygo_usage=1), reviewed_until=future))
        self.assertEqual(free_allowance(usage(paygo_limit=None, plan_usage=950), reviewed_until=future), 0)

    def test_benchmark_is_exactly_twenty_distinct_queries(self):
        jobs = benchmark_queries()
        self.assertEqual(len(jobs), 20)
        self.assertEqual(len({j['identity'] for j in jobs}), 20)
        self.assertEqual({j['location'] for j in jobs}, {
            'Fairfax County, Virginia', 'Arlington, Virginia',
            'South Hill, Virginia', 'Chase City, Virginia'})

    def test_account_fence_fails_closed(self):
        self.assertEqual(free_allowance(usage()), 930)
        self.assertEqual(free_allowance(usage(current_plan='Researcher')), 930)
        for change in ({'paygo_limit': 1}, {'paygo_usage': 1},
                       {'current_plan': 'Bootstrap'}, {'plan_usage': float('nan')},
                       {'plan_limit': 15000}, {'plan_usage': None}, {'paygo_limit': None}):
            self.assertIsNone(free_allowance(usage(**change)))
        self.assertIsNone(free_allowance({'key': {'limit': 950}}))

    def test_null_overage_is_not_assumed_to_be_zero(self):
        result, calls = self.run_search(allowance=usage(current_plan='Researcher', paygo_limit=None))
        self.assertEqual(result['reason'], 'account_limits_unconfirmed')
        self.assertEqual(calls, ['usage', 'record_search_preflight'])

    def test_reviewed_benchmark_retains_all_other_limits(self):
        from unittest.mock import patch
        from datetime import datetime, timezone
        with patch('datetime.datetime') as clock:
            clock.now.return_value = datetime(2026,11,16,9,tzinfo=timezone.utc)
            clock.side_effect = datetime
            self.assertEqual(free_allowance(usage(paygo_limit=None), reviewed_benchmark=True),930)
            self.assertIsNone(free_allowance(usage(paygo_limit=None, paygo_usage=1), reviewed_benchmark=True))
            self.assertIsNone(free_allowance(usage(paygo_limit=None, plan_usage=None), reviewed_benchmark=True))
            clock.now.return_value = datetime(2026,11,18,tzinfo=timezone.utc)
            self.assertIsNone(free_allowance(usage(paygo_limit=None), reviewed_benchmark=True))

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
        self.assertEqual(calls, ['usage', 'record_search_preflight', 'reserve_search', 'search', 'finish_search'])
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
        self.assertEqual(calls, ['usage', 'record_search_preflight'])
        result, calls = self.run_search(admission={'status': 'budget_exhausted'})
        self.assertEqual(calls, ['usage', 'record_search_preflight', 'reserve_search'])

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

class ContentProbeTests(unittest.TestCase):
    def test_only_reserved_probe_enables_content_and_preserves_bounded_text(self):
        received = {}
        def database(action, payload):
            if action == 'reserve_search':
                return {'status': 'reserved', 'reservation_id': 'r', 'lease_token': 't', 'content_probe': True}
            return payload
        def request(key, endpoint, payload=None):
            if endpoint == 'usage': return usage()
            received.update(payload)
            return {'usage': {'credits': 1}, 'results': [{'url': 'https://parks.gov/a', 'title': 'Park', 'raw_content': 'é' * 4000, 'content': 'Address and hours'}]}
        result = run_search(key='fixture', job={'id':'q','query':'parks'},database=database,request=request)
        self.assertTrue(received['include_raw_content'])
        self.assertEqual(received['max_results'], 5)
        self.assertEqual(received['search_depth'], 'basic')
        self.assertEqual(result['credits'], 1)
        row=result['candidates'][0]
        self.assertEqual(row['raw_content_bytes'],8000)
        self.assertEqual(len(row['raw_content'].encode()),6000)
        self.assertTrue(row['raw_content_truncated'])

class WiderContentTests(unittest.TestCase):
    def test_protocol_two_retains_full_bodies_and_marks_the_safety_limit(self):
        for size in (8000, 99000, 100002):
            def database(action, payload):
                if action == 'reserve_search':
                    return {'status':'reserved','reservation_id':'r','lease_token':'t',
                            'content_probe':True,'content_protocol':2}
                return payload
            def request(key, endpoint, payload=None):
                if endpoint == 'usage': return usage()
                self.assertEqual(payload['search_depth'], 'basic')
                self.assertEqual(payload['max_results'], 5)
                return {'usage':{'credits':1},'results':[{'url':'https://parks.gov/a',
                    'raw_content':'é' * (size // 2)}]}
            result=run_search(key='fixture',job={'id':'q','query':'parks'},database=database,request=request)
            row=result['candidates'][0]
            self.assertEqual(row['raw_content_bytes'], size)
            self.assertEqual(len(row['raw_content'].encode()), min(size,100000))
            self.assertEqual(row['raw_content_truncated'], size>100000)
