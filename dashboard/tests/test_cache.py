import unittest

from dashboard.cache import Cache


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Flaky:
    """A collector that returns queued values; an Exception in the queue is raised."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = Cache(clock=self.clock)

    def src(self, repo="r", source="tracker"):
        return self.cache.snapshot()[repo][source]

    def test_never_refreshed_is_unavailable_without_data(self):
        self.cache.register("r", "tracker", Flaky(), 3)
        s = self.src()
        self.assertEqual(s["status"], "unavailable")
        self.assertIsNone(s["data"])
        self.assertIsNone(s["age"])

    def test_success_is_fresh_with_data(self):
        self.cache.register("r", "tracker", Flaky([1, 2]), 3)
        self.cache.tick()
        s = self.src()
        self.assertEqual((s["status"], s["data"], s["age"], s["error"]), ("fresh", [1, 2], 0, None))

    def test_age_grows_since_last_success(self):
        self.cache.register("r", "tracker", Flaky("x"), 3)
        self.cache.tick()
        self.clock.advance(2)
        self.assertEqual(self.src()["age"], 2)

    def test_not_refreshed_before_interval(self):
        f = Flaky("a", "b")
        self.cache.register("r", "tracker", f, 3)
        self.cache.tick()
        self.clock.advance(2)
        self.cache.tick()
        self.assertEqual(f.calls, 1)
        self.clock.advance(1)
        self.cache.tick()
        self.assertEqual(f.calls, 2)
        self.assertEqual(self.src()["data"], "b")

    def test_failure_keeps_last_good_data_and_marks_stale(self):
        self.cache.register("r", "tracker", Flaky("good", RuntimeError("boom")), 3)
        self.cache.tick()
        self.clock.advance(3)
        self.cache.tick()
        s = self.src()
        self.assertEqual((s["status"], s["data"], s["age"]), ("stale", "good", 3))
        self.assertEqual(s["error"], "boom")

    def test_never_succeeded_failure_is_unavailable_with_reason(self):
        self.cache.register("r", "tracker", Flaky(RuntimeError("gh not found")), 3)
        self.cache.tick()
        s = self.src()
        self.assertEqual((s["status"], s["data"], s["error"]), ("unavailable", None, "gh not found"))

    def test_recovery_returns_to_fresh_and_clears_error(self):
        self.cache.register("r", "tracker", Flaky("a", RuntimeError("x"), "c"), 3)
        for _ in range(3):
            self.cache.tick()
            self.clock.advance(3)
        s = self.src()
        self.assertEqual((s["status"], s["data"], s["error"]), ("fresh", "c", None))

    def test_timeout_counts_as_failure(self):
        self.cache.register("r", "tracker", Flaky("ok", TimeoutError("timed out")), 3)
        self.cache.tick()
        self.clock.advance(3)
        self.cache.tick()
        s = self.src()
        self.assertEqual((s["status"], s["data"]), ("stale", "ok"))
        self.assertIn("timed out", s["error"])

    def test_error_with_empty_message_still_names_the_exception(self):
        self.cache.register("r", "tracker", Flaky(TimeoutError()), 3)
        self.cache.tick()
        self.assertEqual(self.src()["error"], "TimeoutError")

    def test_sources_have_independent_intervals_and_failures(self):
        local = Flaky("l1", "l2")
        remote = Flaky(RuntimeError("down"), "r2")
        self.cache.register("r", "git", local, 3)
        self.cache.register("r", "github", remote, 60)
        self.cache.tick()
        self.clock.advance(3)
        self.cache.tick()
        snap = self.cache.snapshot()["r"]
        self.assertEqual(snap["git"]["data"], "l2")
        self.assertEqual(snap["github"]["status"], "unavailable")
        self.assertEqual(remote.calls, 1)

    def test_snapshot_groups_by_repo(self):
        self.cache.register("a", "git", Flaky(1), 3)
        self.cache.register("b", "git", Flaky(2), 3)
        self.cache.tick()
        snap = self.cache.snapshot()
        self.assertEqual((snap["a"]["git"]["data"], snap["b"]["git"]["data"]), (1, 2))

    def test_snapshot_does_not_wait_for_a_running_refresh(self):
        import threading
        started, release = threading.Event(), threading.Event()

        def slow():
            started.set()
            release.wait(5)
            return "late"

        self.cache.register("r", "github", slow, 60)
        t = threading.Thread(target=self.cache.tick)
        t.start()
        self.assertTrue(started.wait(2))
        done = []
        reader = threading.Thread(target=lambda: done.append(self.cache.snapshot()))
        reader.start()
        reader.join(1)
        release.set()
        t.join(2)
        self.assertTrue(done, "snapshot blocked behind a slow collector")


if __name__ == "__main__":
    unittest.main()
