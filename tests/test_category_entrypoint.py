"""Production uses the central Python entrypoint, not just file routes."""
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


def test_central_entrypoint_dispatches_category_get_and_post():
    modules = {}
    for name in ('geocode', 'preview', 'chambermaster', 'provider_pilot', 'category_demand'):
        module = ModuleType('api.'+name)
        module.handler = type(name+'Handler', (), {'do_GET': Mock(), 'do_POST': Mock()})
        modules[module.__name__] = module
    spec = importlib.util.spec_from_file_location('category_index_test', Path(__file__).parents[1]/'api/index.py')
    entry = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', modules):
        spec.loader.exec_module(entry)
    h=object.__new__(entry.handler);h.path='/api/category-demand'
    h.do_GET();h.do_POST()
    modules['api.category_demand'].handler.do_GET.assert_called_once_with(h)
    modules['api.category_demand'].handler.do_POST.assert_called_once_with(h)
    modules['api.preview'].handler.do_POST.assert_not_called()
    h.path='/api/demand-preview';h.do_POST()
    modules['api.preview'].handler.do_POST.assert_called_once_with(h)
