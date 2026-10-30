"""Protected ChamberMaster provider endpoint; existing collector credentials only."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os
from roomquest.chambermaster import collect_batch


class handler(BaseHTTPRequestHandler):
    def chambermaster_reply(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def chambermaster_run(self):
        if self.headers.get('Content-Length', '0') not in ('', '0') or self.headers.get('Transfer-Encoding'):
            return self.chambermaster_reply(400, {'error': 'unexpected_body'})
        try:
            return self.chambermaster_reply(200, collect_batch())
        except Exception:
            return self.chambermaster_reply(503, {'error': 'chambermaster_unavailable'})

    def do_GET(self):
        if self.path != '/api/chambermaster':
            return self.chambermaster_reply(404, {'error': 'not_found'})
        supplied = self.headers.get('Authorization', '')
        if not supplied:
            return self.chambermaster_reply(200, {'service': 'chambermaster', 'mode': 'registered_sources_only'})
        secret = os.environ.get('CRON_SECRET', '')
        if not secret or not hmac.compare_digest(supplied, 'Bearer ' + secret):
            return self.chambermaster_reply(401, {'error': 'unauthorized'})
        return self.chambermaster_run()

    def do_POST(self):
        if self.path != '/api/chambermaster':
            return self.chambermaster_reply(404, {'error': 'not_found'})
        secret = os.environ.get('ROOMQUEST_PREVIEW_SECRET', '')
        if not secret or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + secret):
            return self.chambermaster_reply(401, {'error': 'unauthorized'})
        return self.chambermaster_run()

    def log_message(self, *args):
        return
