import http.client
import threading
import unittest

from dashboard.server import make_server


class PageSmokeTest(unittest.TestCase):
    """The page's rendering is checked in a real browser; here only that it is served and wired to poll."""

    def test_page_is_served_and_polls_the_state_endpoint(self):
        s = make_server(lambda: {}, port=0)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (s.shutdown(), s.server_close()))
        c = http.client.HTTPConnection(*s.server_address, timeout=5)
        c.request("GET", "/")
        body = c.getresponse().read().decode("utf-8")
        c.close()
        self.assertIn("/api/state", body)
        self.assertIn("setInterval(poll", body)
        for status in ("stale", "unavailable"):
            self.assertIn(status, body)


if __name__ == "__main__":
    unittest.main()
