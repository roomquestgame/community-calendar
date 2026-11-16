import unittest
from unittest.mock import Mock
from roomquest.activity_request_admission import admitted_requests, before_request


class AdmissionTests(unittest.TestCase):
    def test_every_primary_auxiliary_and_redirect_is_reserved(self):
        reserve = Mock(return_value={'status': 'reserved'})
        with admitted_requests(reserve):
            before_request('https://example.gov/robots.txt', auxiliary=True)
            before_request('https://example.gov/park')
            before_request('https://example.gov/moved', redirect=True)
        self.assertEqual([c.args[0] for c in reserve.call_args_list], ['auxiliary','page','auxiliary'])

    def test_failure_does_not_fall_back_to_unbudgeted_transport(self):
        with admitted_requests(Mock(return_value={'status': 'budget_exhausted'})):
            with self.assertRaises(ValueError):
                before_request('https://example.gov/park')

    def test_three_redirect_limit_and_context_isolation(self):
        reserve = Mock(return_value={'status': 'reserved'})
        with admitted_requests(reserve):
            for i in range(3):
                before_request('https://example.gov/moved', redirect=True)
            with self.assertRaises(ValueError):
                before_request('https://example.gov/fourth', redirect=True)
        before_request('https://example.gov/legacy')
        self.assertEqual(reserve.call_count, 3)
