import unittest
from unittest.mock import Mock
from roomquest.things_to_do_coordinator import run_tick


class CoordinatorTests(unittest.TestCase):
    def test_foreground_pressure_does_not_plan_or_search(self):
        database, search = Mock(), Mock()
        result = run_tick(database=database, search=search,
                          page_worker=lambda: {'status': 'paused_load'})
        self.assertEqual(result['status'], 'paused_load')
        database.assert_not_called()
        search.assert_not_called()

    def test_admitted_page_waits_for_next_ordinary_tick(self):
        database = Mock(side_effect=[{'status': 'planned'}, {'status': 'admitted'}])
        search = Mock()
        result = run_tick(database=database, search=search,
                          page_worker=lambda: {'status': 'idle'})
        self.assertEqual(result['status'], 'planned_page')
        search.assert_not_called()

    def test_disabled_foundation_preserves_legacy_idle_result(self):
        database = Mock(return_value={'status': 'disabled'})
        self.assertEqual(run_tick(database=database, page_worker=lambda: {'status': 'idle'}), {'status': 'idle'})

    def test_known_page_work_precedes_search(self):
        database = Mock()
        self.assertEqual(run_tick(database=database, page_worker=lambda: {'status': 'finished'}), {'status': 'finished'})
        database.assert_not_called()

    def test_missing_key_never_spends(self):
        database = Mock(side_effect=[{'status': 'planned'}, {'status': 'no_verified_locality_candidate'},
                                     {'status': 'ready', 'id': 'fixture', 'query': 'parks South Hill, VA'}])
        result = run_tick(database=database, key='', page_worker=lambda: {'status': 'idle'})
        self.assertEqual(result['status'], 'search_credentials_missing')
        self.assertEqual(database.call_count, 3)

    def test_search_only_benchmark_does_not_admit_publishers(self):
        database = Mock(side_effect=[{'status': 'disabled'}, {'status': 'ready', 'planner': 'benchmark', 'id': 'q', 'query': 'parks Arlington'}])
        search = Mock(return_value={'status': 'finished'})
        result = run_tick(database=database, search=search, key='fixture', page_worker=lambda: {'status': 'idle'})
        self.assertEqual(result['status'], 'finished')
        self.assertEqual([c.args[0] for c in database.call_args_list], ['plan', 'next_search'])
        self.assertEqual(database.call_args_list[-1].args[1], {'planner': 'benchmark'})
        search.assert_called_once()
