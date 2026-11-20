import http.client
import json
import threading
import time
import unittest

from dashboard.app import build_state
from dashboard.cache import Cache
from dashboard.server import make_server


def request(server, method, path):
    host, port = server.server_address
    c = http.client.HTTPConnection(host, port, timeout=5)
    c.request(method, path)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r.getheader("Content-Type"), body


class ServerTest(unittest.TestCase):
    def serve(self, state_fn):
        s = make_server(state_fn, port=0)
        t = threading.Thread(target=s.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        return s

    def test_binds_loopback_only(self):
        s = self.serve(lambda: {})
        self.assertEqual(s.server_address[0], "127.0.0.1")

    def test_api_state_is_json_from_the_state_function(self):
        s = self.serve(lambda: {"app": "factory-dashboard", "repos": []})
        status, ctype, body = request(s, "GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(body), {"app": "factory-dashboard", "repos": []})

    def test_serves_the_page_at_root(self):
        status, ctype, body = request(self.serve(lambda: {}), "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"<html", body.lower())

    def test_unknown_route_is_404(self):
        self.assertEqual(request(self.serve(lambda: {}), "GET", "/nope")[0], 404)

    def test_only_get_is_allowed(self):
        s = self.serve(lambda: {})
        for m in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(request(s, m, "/api/state")[0], 405, m)

    def test_a_failing_state_function_is_a_500_not_a_hang(self):
        def boom():
            raise RuntimeError("x")

        self.assertEqual(request(self.serve(boom), "GET", "/api/state")[0], 500)


class BuildStateTest(unittest.TestCase):
    def test_shape_includes_config_and_source_status(self):
        cache = Cache(clock=lambda: 50.0)
        cache.register("a", "git", lambda: {"x": 1}, 3)
        cache.tick()
        cache.register("a", "github", lambda: 1 / 0, 60)
        cache.tick()
        repos = [{"name": "a", "path": "/a", "github": "o/a", "branch": "factory", "beads": False}]
        st = build_state(repos, cache, clock=lambda: 50.0)
        self.assertEqual(st["app"], "factory-dashboard")
        r = st["repos"][0]
        self.assertEqual((r["name"], r["github"], r["branch"]), ("a", "o/a", "factory"))
        self.assertEqual(r["sources"]["git"]["status"], "fresh")
        self.assertEqual(r["sources"]["github"]["status"], "unavailable")
        self.assertIn("division by zero", r["sources"]["github"]["error"])
        json.dumps(st)  # must be serialisable

    def test_repo_with_no_sources_yet_still_listed(self):
        st = build_state([{"name": "z", "path": "/z"}], Cache(), clock=lambda: 0)
        self.assertEqual(st["repos"][0]["sources"], {})

    def test_slow_collector_never_delays_the_endpoint(self):
        release = threading.Event()
        cache = Cache()
        cache.register("a", "github", lambda: release.wait(5), 60)
        cache.register("a", "git", lambda: "quick", 3)
        threading.Thread(target=cache.tick, daemon=True).start()
        time.sleep(0.1)
        s = make_server(lambda: build_state([{"name": "a", "path": "/a"}], cache), port=0)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        t0 = time.time()
        status, _, body = request(s, "GET", "/api/state")
        elapsed = time.time() - t0
        release.set()
        s.shutdown()
        s.server_close()
        self.assertEqual(status, 200)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(json.loads(body)["repos"][0]["sources"]["github"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
