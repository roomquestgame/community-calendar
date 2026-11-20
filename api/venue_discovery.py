"""Database-ticketed venue discovery endpoint (no caller-supplied URLs)."""
from http.server import BaseHTTPRequestHandler
import json
import re

from roomquest.venue_discovery import run
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
        if self.path != '/api/venue-discovery':
            return self.reply(404, {'error': 'not_found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 96:
                return self.reply(400, {'error': 'invalid_ticket'})
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.reply(400, {'error': 'invalid_ticket'})
            body = json.loads(raw)
            if (not isinstance(body, dict) or set(body) != {'ticket'}
                    or not isinstance(body['ticket'], str)
                    or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', body['ticket'])):
                return self.reply(400, {'error': 'invalid_ticket'})
        except (ValueError, TypeError):
            return self.reply(400, {'error': 'invalid_ticket'})
        try:
            return self.reply(200, run(body['ticket']))
        except PreviewError:
            return self.reply(503, {'error': 'collector_unavailable'})
        except Exception:
            return self.reply(503, {'error': 'collector_failed'})

    def do_GET(self):
        return self.reply(405, {'error': 'method_not_allowed'})

    def log_message(self, *args):
        # No venue URLs, exact locations or provider tokens in access logs.
        return
