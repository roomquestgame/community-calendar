"""Dedicated HTML / Beautiful Soup entrypoint, independent of category-demand URL.
Only a one-use database-issued ticket is accepted; no user-selected URLs or parks.
"""
from http.server import BaseHTTPRequestHandler
import json
import re
from roomquest.category_worker import collect_category
from roomquest.preview_worker import PreviewError

class handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        raw=json.dumps(data, separators=(",",":")).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        self.reply(405,{"error":"method_not_allowed"})
    def do_POST(self):
        if self.path!="/api/html-demand":
            return self.reply(404,{"error":"not_found"})
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length<1 or length>160: return self.reply(400,{"error":"invalid_dispatch"})
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict) or set(data)!={"category","ticket"} or data["category"]!="html" or not isinstance(data["ticket"],str) or not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}",data["ticket"]):
                return self.reply(400,{"error":"invalid_dispatch"})
        except (ValueError,TypeError):
            return self.reply(400,{"error":"invalid_dispatch"})
        try:
            return self.reply(200,collect_category("html",data["ticket"]))
        except PreviewError:
            return self.reply(503,{"error":"collector_unavailable"})
        except Exception:
            return self.reply(503,{"error":"collector_failed"})
