"""Authenticated scheduled entry point for the finite NOVA activity pilot."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os

from roomquest.things_to_do_coordinator import run_tick as run_batch


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/api/things-to-do-pilot":
            return self.reply(404, {"error": "not_found"})
        secret = os.environ.get("CRON_SECRET", "")
        if not secret or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + secret):
            return self.reply(401, {"error": "unauthorized"})
        if self.headers.get("Content-Length", "0") not in ("", "0"):
            return self.reply(400, {"error": "unexpected_body"})
        try:
            return self.reply(200, run_batch())
        except Exception:
            return self.reply(503, {"error": "pilot_unavailable"})

    def do_POST(self):
        return self.reply(405, {"error": "method_not_allowed"})
