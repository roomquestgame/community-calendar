"""Protected, bounded curator preview endpoint for cron and manual checks."""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os

from roomquest.preview_worker import PreviewError, collect_previews


class handler(BaseHTTPRequestHandler):
    def reply(self, code: int, value: dict):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def batch(self):
        # Never accepts arbitrary URLs or source identifiers from the request.
        # At most four due preview candidates are claimed from the private DB.
        try:
            result = collect_previews(limit=4)
            return self.reply(200, result)
        except PreviewError:
            return self.reply(503, {"error": "collector_unavailable"})
        except Exception:
            return self.reply(503, {"error": "collector_failed"})

    def do_GET(self):
        if self.path != "/api/preview":
            return self.reply(404, {"error": "not_found"})
        authorization = self.headers.get("Authorization", "")
        if authorization:
            cron_secret = os.environ.get("CRON_SECRET", "")
            if not cron_secret or not hmac.compare_digest(
                authorization, "Bearer " + cron_secret
            ):
                return self.reply(401, {"error": "unauthorized"})
            return self.batch()
        return self.reply(200, {"service": "roomquest-community-calendar",
                                "mode": "admin_preview_only",
                                "scheduled": bool(os.environ.get("CRON_SECRET"))})

    def do_POST(self):
        if self.path != "/api/preview":
            return self.reply(404, {"error": "not_found"})
        secret = os.environ.get("ROOMQUEST_PREVIEW_SECRET", "")
        if not secret or not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + secret
        ):
            return self.reply(401, {"error": "unauthorized"})
        if self.headers.get("Content-Length", "0") not in ("", "0"):
            return self.reply(400, {"error": "unexpected_body"})
        return self.batch()
