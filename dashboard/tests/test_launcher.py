import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from dashboard import __main__ as launcher
from dashboard.app import APP
from dashboard.launcher import probe
from dashboard.server import make_server


def serve_dashboard():
    s = make_server(lambda: {"app": APP, "repos": []}, port=0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def serve_foreign():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"hi")

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ProbeTest(unittest.TestCase):
    def test_free_port(self):
        self.assertEqual(probe(free_port()), "free")

    def test_running_dashboard_is_recognised(self):
        s = serve_dashboard()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        self.assertEqual(probe(s.server_address[1]), "dashboard")

    def test_other_http_service_is_foreign(self):
        s = serve_foreign()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        self.assertEqual(probe(s.server_address[1]), "foreign")

    def test_listener_that_never_answers_is_foreign(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            self.assertEqual(probe(srv.getsockname()[1], timeout=0.3), "foreign")


class LaunchTest(unittest.TestCase):
    def cfg(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = os.path.join(d.name, "repos.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump([], f)
        return p

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("webbrowser.open") as opened:
            code = 0
            try:
                launcher.main(list(args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), opened

    def test_second_launch_reuses_the_running_dashboard_and_opens_it(self):
        s = serve_dashboard()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        port = s.server_address[1]
        code, out, opened = self.run_main("--config", self.cfg(), "--port", str(port))
        self.assertIn(code, (0, None))
        self.assertIn(f"http://127.0.0.1:{port}/", out)
        opened.assert_called_once_with(f"http://127.0.0.1:{port}/")

    def test_reuse_respects_no_open(self):
        s = serve_dashboard()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        _, _, opened = self.run_main("--config", self.cfg(), "--port", str(s.server_address[1]), "--no-open")
        opened.assert_not_called()

    def test_foreign_listener_is_a_clear_error_pointing_at_port(self):
        s = serve_foreign()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        port = s.server_address[1]
        code, _, opened = self.run_main("--config", self.cfg(), "--port", str(port))
        self.assertIsInstance(code, str)
        self.assertIn("--port", code)
        self.assertIn(str(port), code)
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
