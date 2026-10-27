"""Private RoomQuest collector entrypoint. No public user URL or crawl parameters."""
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

    def do_GET(self):
        if self.path != "/api/preview":
            return self.reply(404, {"error": "not_found"})
        return self.reply(200, {"service": "roomquest-community-calendar",
                                "mode": "admin_preview_only", "scheduled": False})

    def do_POST(self):
        if self.path != "/api/preview":
            return self.reply(404, {"error": "not_found"})
        secret = os.environ.get("ROOMQUEST_PREVIEW_SECRET", "")
        if not secret or not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + secret
        ):
            return self.reply(401, {"error": "unauthorized"})
        # Requests do not contain URLs, source IDs or instructions. The service
        # claims bounded pre-approved work from the private Supabase queue.
        if self.headers.get("Content-Length", "0") not in ("", "0"):
            return self.reply(400, {"error": "unexpected_body"})
        try:
            result = collect_previews(limit=4)
            return self.reply(200, result)
        except PreviewError:
            return self.reply(503, {"error": "collector_unavailable"})
        except Exception:
            return self.reply(503, {"error": "collector_failed"})
