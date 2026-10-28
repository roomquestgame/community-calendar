"""Authenticated Vercel Cron/operator entry point. No addresses in public input."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os

from roomquest.venue_resolver import run_pipeline as run_batch


class handler(BaseHTTPRequestHandler):
    # BaseHTTPRequestHandler's default request log is unnecessary for this job.
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

    def invoke(self, name):
        secret = os.environ.get(name, "")
        if not secret or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + secret):
            return self.reply(401, {"error": "unauthorized"})
        if self.headers.get("Content-Length", "0") not in ("", "0"):
            return self.reply(400, {"error": "unexpected_body"})
        try:
            return self.reply(200, run_batch())
        except Exception:
            # Never serialize exceptions, HTTP request objects, or secrets.
            return self.reply(503, {"error": "geocoder_unavailable"})

    def do_GET(self):
        if self.path != "/api/geocode":
            return self.reply(404, {"error": "not_found"})
        if self.headers.get("Authorization"):
            return self.invoke("CRON_SECRET")
        return self.reply(200, {
            "service": "roomquest-forward-geocoder",
            "enabled": os.environ.get("FORWARD_GEOCODER_ENABLED") == "true",
            "configured": bool(os.environ.get("GEOCODIO_API_KEY")),
        })

    def do_POST(self):
        if self.path != "/api/geocode":
            return self.reply(404, {"error": "not_found"})
        return self.invoke("ROOMQUEST_PREVIEW_SECRET")

