import http.client
import json
import os
import subprocess
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MainTest(unittest.TestCase):
    def test_py_m_dashboard_serves_state_for_a_repo_list(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "repos.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump([{"name": "ghost", "path": os.path.join(d, "missing"), "branch": "main"}], f)
            p = subprocess.Popen([sys.executable, "-m", "dashboard", "--config", cfg, "--port", "0", "--no-open"],
                                 cwd=KIT, stdout=subprocess.PIPE, text=True)
            try:
                line = p.stdout.readline().strip()
                self.assertTrue(line.startswith("http://127.0.0.1:"), line)
                port = int(line.rsplit(":", 1)[1].strip("/"))
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", "/api/state")
                st = json.loads(c.getresponse().read())
                self.assertEqual(st["repos"][0]["name"], "ghost")
            finally:
                p.kill()
                p.wait()
                p.stdout.close()

    def test_missing_repo_list_exits_with_a_clear_message(self):
        r = subprocess.run([sys.executable, "-m", "dashboard", "--config", "no-such.json"], cwd=KIT,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No repo list", r.stderr)


if __name__ == "__main__":
    unittest.main()
