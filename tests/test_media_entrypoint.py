"""Only a DB ticket can reach the dedicated production media worker."""
import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from api import media_demand
from roomquest.preview_worker import PreviewError

ROOT = Path(__file__).parents[1]
TICKET = '00000000-0000-0000-0000-000000000001'


def request(value, *, path='/api/media-demand', length=None):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    instance = object.__new__(media_demand.handler)
    instance.path = path
    instance.headers = {'Content-Length': str(len(raw) if length is None else length)}
    instance.rfile = io.BytesIO(raw)
    instance.reply = Mock()
    return instance


class EntryTests(unittest.TestCase):
    def test_valid_ticket_is_the_only_argument(self):
        handler = request({'ticket': TICKET})
        with patch.object(media_demand, 'collect_media', return_value={'outcome': 'idle'}) as collect:
            handler.do_POST()
        collect.assert_called_once_with(TICKET)
        handler.reply.assert_called_once_with(200, {'outcome': 'idle'})

    def test_arbitrary_urls_sources_limits_and_bad_tickets_are_rejected(self):
        invalid = ({}, [], None, {'ticket': 1}, {'ticket': 'not-a-uuid'},
                   {'ticket': TICKET, 'source_id': 4992}, {'ticket': TICKET, 'limit': 10},
                   {'ticket': TICKET, 'url': 'https://x.org'}, b'{', b'\xff')
        for value in invalid:
            handler = request(value)
            with patch.object(media_demand, 'collect_media') as collect:
                handler.do_POST()
            collect.assert_not_called()
            handler.reply.assert_called_once_with(400, {'error': 'invalid_dispatch'})

    def test_invalid_lengths_are_rejected_before_collection(self):
        for length in (-1, 0, 97, 'invalid'):
            handler = request({'ticket': TICKET}, length=length)
            with patch.object(media_demand, 'collect_media') as collect:
                handler.do_POST()
            collect.assert_not_called()
            handler.reply.assert_called_once_with(400, {'error': 'invalid_dispatch'})

    def test_truncated_request_is_rejected(self):
        raw = json.dumps({'ticket': TICKET}).encode()
        handler = request(raw, length=len(raw) + 1)
        with patch.object(media_demand, 'collect_media') as collect:
            handler.do_POST()
        collect.assert_not_called()
        handler.reply.assert_called_once_with(400, {'error': 'invalid_dispatch'})

    def test_get_does_not_consume_ticket(self):
        handler = request({'ticket': TICKET})
        with patch.object(media_demand, 'collect_media') as collect:
            handler.do_GET()
        collect.assert_not_called()
        handler.reply.assert_called_once_with(405, {'error': 'method_not_allowed'})

    def test_wrong_route_does_not_consume_ticket(self):
        handler = request({'ticket': TICKET}, path='/api/other')
        with patch.object(media_demand, 'collect_media') as collect:
            handler.do_POST()
        collect.assert_not_called()
        handler.reply.assert_called_once_with(404, {'error': 'not_found'})

    def test_errors_do_not_return_secrets_or_exception_messages(self):
        for error, code in ((PreviewError('private database details'), 'collector_unavailable'),
                            (RuntimeError('private token ' + TICKET), 'collector_failed')):
            handler = request({'ticket': TICKET})
            with patch.object(media_demand, 'collect_media', side_effect=error):
                handler.do_POST()
            handler.reply.assert_called_once_with(503, {'error': code})

    def test_central_entrypoint_routes_media_and_does_not_fall_through(self):
        modules = {}
        for name in ('geocode', 'preview', 'chambermaster', 'provider_pilot',
                     'category_demand', 'html_demand', 'media_demand'):
            module = ModuleType('api.' + name)
            module.handler = type(name + 'Handler', (), {'do_GET': Mock(), 'do_POST': Mock()})
            modules[module.__name__] = module
        spec = importlib.util.spec_from_file_location('media_index_test', ROOT / 'api/index.py')
        entry = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', modules):
            spec.loader.exec_module(entry)
        handler = object.__new__(entry.handler)
        handler.path = '/api/media-demand'
        handler.do_GET()
        handler.do_POST()
        modules['api.media_demand'].handler.do_GET.assert_called_once_with(handler)
        modules['api.media_demand'].handler.do_POST.assert_called_once_with(handler)
        modules['api.preview'].handler.do_POST.assert_not_called()

    def test_manifest_gives_media_its_own_runtime_without_an_image_polling_cron(self):
        manifest = json.loads((ROOT / 'vercel.json').read_text())
        self.assertEqual(manifest['functions']['api/media_demand.py']['maxDuration'], 60)
        self.assertIn({'src': '/api/media-demand', 'dest': '/api/media_demand.py'}, manifest['routes'])
        self.assertNotIn('/api/media-demand', [entry['path'] for entry in manifest['crons']])


if __name__ == '__main__':
    unittest.main()
