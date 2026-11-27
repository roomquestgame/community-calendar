"""One database-issued ticket invokes the existing shared venue resolver."""
from http.server import BaseHTTPRequestHandler
import json
import re

from roomquest.venue_resolver import run_triggered


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

    def do_POST(self):
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

    def do_GET(self):
        return self.reply(405, {"error": "method_not_allowed"})
