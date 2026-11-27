"""Authenticated Vercel Cron/operator entry point. No addresses in public input."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os
import re

from roomquest.venue_resolver import run_pipeline as run_batch, run_triggered


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
            return self.reply(200, run_batch(
                oidc_token=self.headers.get("x-vercel-oidc-token", "")))
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

    def invoke_venue_research(self):
        # The database issues one opaque single-use ticket after committing an
        # eligible queue row. No client may supply an address, URL or venue key.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 96:
                return self.reply(400, {"error": "invalid_dispatch"})
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.reply(400, {"error": "invalid_dispatch"})
            body = json.loads(raw)
            if (not isinstance(body, dict) or set(body) != {"ticket"}
                    or not isinstance(body["ticket"], str)
                    or not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", body["ticket"])):
                return self.reply(400, {"error": "invalid_dispatch"})
        except (ValueError, TypeError):
            return self.reply(400, {"error": "invalid_dispatch"})
        try:
            result = run_triggered(body["ticket"], oidc_token=self.headers.get("x-vercel-oidc-token", ""))
            return self.reply(503 if result.get("stop_reason") == "research_unconfigured" else 200, result)
        except Exception:
            return self.reply(503, {"error": "venue_research_unavailable"})

    def do_POST(self):
        if self.path == "/api/venue-research":
            return self.invoke_venue_research()
        if self.path != "/api/geocode":
            return self.reply(404, {"error": "not_found"})
        return self.invoke("ROOMQUEST_PREVIEW_SECRET")

