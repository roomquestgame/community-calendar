"""Operator-only, fixed-source manual release check. Never scheduled."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os
from roomquest.provider_pilot import collect_pilot


class handler(BaseHTTPRequestHandler):
    def pilot_reply(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        return self.pilot_reply(404, {'error': 'not_found'})

    def do_POST(self):
        if self.path != '/api/provider-pilot':
            return self.pilot_reply(404, {'error': 'not_found'})
        secret = os.environ.get('ROOMQUEST_PREVIEW_SECRET', '')
        if not secret or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + secret):
            return self.pilot_reply(401, {'error': 'unauthorized'})
        if self.headers.get('Content-Length', '0') not in ('', '0') or self.headers.get('Transfer-Encoding'):
            return self.pilot_reply(400, {'error': 'unexpected_body'})
        try:
            return self.pilot_reply(200, collect_pilot())
        except Exception:
            return self.pilot_reply(503, {'error': 'pilot_unavailable'})

    def log_message(self, *args):
        pass
