"""Independent authenticated background job; no public event-view lookup."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os

from roomquest.coordinate_timezone import run_batch


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value):
        raw = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def invoke(self, secret_name):
        if self.path != "/api/timezones":
            return self.reply(404, {"error": "not_found"})
        secret = os.environ.get(secret_name, "")
        if not secret or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + secret):
            return self.reply(401, {"error": "unauthorized"})
        if self.headers.get("Content-Length", "0") not in ("", "0"):
            return self.reply(400, {"error": "unexpected_body"})
        try:
            return self.reply(200, run_batch())
        except Exception:
            return self.reply(503, {"error": "timezone_worker_unavailable"})

    def do_GET(self):
        self.invoke("CRON_SECRET")

    def do_POST(self):
        self.invoke("ROOMQUEST_PREVIEW_SECRET")
