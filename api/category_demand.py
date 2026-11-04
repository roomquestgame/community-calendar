"""DB-issued, single-use dispatch tickets; no client URLs or source IDs accepted."""
from http.server import BaseHTTPRequestHandler
import json
import re
from roomquest.category_worker import CATEGORIES, collect_category, report_category_failure
from roomquest.preview_worker import PreviewError


class handler(BaseHTTPRequestHandler):
    def reply(self, code, value):
        raw = json.dumps(value, separators=(',', ':')).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path != '/api/category-demand':
            return self.reply(404, {'error': 'not_found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 160:
                return self.reply(400, {'error': 'invalid_dispatch'})
            body = json.loads(self.rfile.read(length))
            if (not isinstance(body, dict) or set(body) != {'category', 'ticket'}
                    or not isinstance(body['category'], str) or body['category'] not in CATEGORIES
                    or not isinstance(body['ticket'], str)
                    or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', body['ticket'])):
                return self.reply(400, {'error': 'invalid_dispatch'})
        except (ValueError, TypeError):
            return self.reply(400, {'error': 'invalid_dispatch'})
        try:
            return self.reply(200, collect_category(body['category'], body['ticket']))
        except PreviewError as error:
            report_category_failure(body['category'], error)
            return self.reply(503, {'error': 'collector_unavailable'})
        except Exception as error:
            report_category_failure(body['category'], error)
            return self.reply(503, {'error': 'collector_failed'})

    def do_GET(self):
        return self.reply(405, {'error': 'method_not_allowed'})
