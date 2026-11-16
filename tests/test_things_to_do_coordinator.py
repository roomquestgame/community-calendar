import unittest
from unittest.mock import Mock
from roomquest.things_to_do_coordinator import run_tick


class CoordinatorTests(unittest.TestCase):
    def test_foreground_pressure_does_not_plan_or_search(self):
        database, search = Mock(), Mock()
        result = run_tick(database=database, search=search,
                          page_worker=lambda: {'status': 'paused_load'})
        self.assertEqual(result['status'], 'paused_load')
        self.assertEqual([c.args[0] for c in database.call_args_list], ['next_content_probe'])
        search.assert_not_called()

    def test_admitted_page_fetches_in_same_tick(self):
        database = Mock(side_effect=[{'status': 'content_probe_complete'}, {'status': 'planned'}, {'status': 'admitted'}])
        search = Mock()
        result = run_tick(database=database, search=search,
                          page_worker=Mock(side_effect=[{'status': 'idle'}, {'status': 'finished'}]))
        self.assertEqual(result['status'], 'finished')
        search.assert_not_called()

    def test_disabled_foundation_preserves_legacy_idle_result(self):
        database = Mock(return_value={'status': 'disabled'})
        self.assertEqual(run_tick(database=database, page_worker=lambda: {'status': 'idle'}), {'status': 'idle'})

    def test_known_page_work_precedes_search(self):
        database = Mock()
        self.assertEqual(run_tick(database=database, page_worker=lambda: {'status': 'finished'}), {'status': 'finished'})
        self.assertEqual([c.args[0] for c in database.call_args_list], ['next_content_probe'])

    def test_missing_key_never_spends(self):
        database = Mock(side_effect=[{'status': 'content_probe_complete'}, {'status': 'planned'}, {'status': 'no_verified_locality_candidate'},
                                     {'status': 'ready', 'id': 'fixture', 'query': 'parks South Hill, VA'}])
        result = run_tick(database=database, key='', page_worker=lambda: {'status': 'idle'})
        self.assertEqual(result['status'], 'search_credentials_missing')
        self.assertEqual(database.call_count, 4)

    def test_search_only_benchmark_does_not_admit_publishers(self):
        database = Mock(side_effect=[{'status': 'content_probe_complete'}, {'status': 'disabled'}, {'status': 'ready', 'planner': 'benchmark', 'id': 'q', 'query': 'parks Arlington'}])
        search = Mock(return_value={'status': 'finished'})
        result = run_tick(database=database, search=search, key='fixture', page_worker=lambda: {'status': 'idle'})
        self.assertEqual(result['status'], 'finished')
        self.assertEqual([c.args[0] for c in database.call_args_list], ['next_content_probe', 'plan', 'next_search'])
        self.assertEqual(database.call_args_list[-1].args[1], {'planner': 'benchmark'})
        search.assert_called_once()

class ProbeTests(unittest.TestCase):
    def test_probe_preempts_only_when_durable_job_ready(self):
        database = Mock(return_value={'status': 'ready', 'id': 'q', 'query': 'parks'})
        worker = Mock()
        search = Mock(return_value={'status': 'finished'})
        self.assertEqual(run_tick(database=database, page_worker=worker, search=search, key='fixture')['status'], 'finished')
        worker.assert_not_called()
        search.assert_called_once()
