"""Per-Source refresh with last-good data, age and error.

A Source is one origin of data for one repo (tracker, github, git). A collector is a
zero-argument function returning the Source's data; any exception means the refresh failed.
A failed refresh keeps the previous data and marks the Source stale. A Source that has never
succeeded is unavailable with the reason, never empty data.
"""
import threading
import time


class _Source:
    def __init__(self, fn, interval):
        self.fn = fn
        self.interval = interval
        self.next_due = 0.0
        self.has_data = False
        self.data = None
        self.last_ok = None
        self.error = None


class Cache:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._sources = {}  # (repo, source) -> _Source, in registration order
        self._stop = threading.Event()
        self._threads = []

    def register(self, repo, source, fn, interval):
        with self._lock:
            self._sources[(repo, source)] = _Source(fn, interval)

    def refresh(self, repo, source):
        """Run one collector now. The lock is not held while it runs."""
        with self._lock:
            s = self._sources[(repo, source)]
            s.next_due = self._clock() + s.interval  # a hung collector is not re-queued on top of itself
        try:
            data, err = s.fn(), None
        except Exception as e:
            data, err = None, str(e) or type(e).__name__
        with self._lock:
            now = self._clock()
            s.next_due = now + s.interval
            if err is None:
                s.has_data, s.data, s.last_ok, s.error = True, data, now, None
            else:
                s.error = err

    def tick(self):
        """Refresh every Source that is due, in registration order."""
        with self._lock:
            now = self._clock()
            due = [k for k, s in self._sources.items() if s.next_due <= now]
        for repo, source in due:
            self.refresh(repo, source)

    def snapshot(self):
        with self._lock:
            now = self._clock()
            out = {}
            for (repo, source), s in self._sources.items():
                if not s.has_data:
                    status = "unavailable"
                else:
                    status = "stale" if s.error else "fresh"
                out.setdefault(repo, {})[source] = {
                    "status": status,
                    "data": s.data,
                    "age": None if s.last_ok is None else now - s.last_ok,
                    "error": s.error,
                }
            return out

    def start(self):
        """One background thread per Source, so a slow Source never delays another."""
        for repo, source in list(self._sources):
            t = threading.Thread(target=self._loop, args=(repo, source), daemon=True)
            t.start()
            self._threads.append(t)

    def _loop(self, repo, source):
        interval = self._sources[(repo, source)].interval
        while not self._stop.is_set():
            self.refresh(repo, source)
            self._stop.wait(interval)

    def stop(self):
        self._stop.set()
