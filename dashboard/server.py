"""Local HTTP server: the page at / and the state snapshot at /api/state. Read-only."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8765
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html")


def make_server(state_fn, port=DEFAULT_PORT, host="127.0.0.1"):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, ctype, body):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                try:
                    body = json.dumps(state_fn()).encode("utf-8")
                except Exception as e:
                    return self._send(500, "text/plain; charset=utf-8", f"state failed: {e}".encode("utf-8"))
                return self._send(200, "application/json; charset=utf-8", body)
            if path == "/":
                with open(PAGE, "rb") as f:
                    return self._send(200, "text/html; charset=utf-8", f.read())
            self._send(404, "text/plain; charset=utf-8", b"not found")

        def _no(self):
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_POST = do_PUT = do_DELETE = do_PATCH = _no

        def log_message(self, *args):
            pass

    ThreadingHTTPServer.daemon_threads = True
    return ThreadingHTTPServer((host, port), Handler)
