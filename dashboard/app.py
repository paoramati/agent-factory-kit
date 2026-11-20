"""Compose the Dashboard's state: repo config plus each Source's snapshot."""
import datetime
import time

APP = "factory-dashboard"  # lets the launcher recognise a running Dashboard


def build_state(repos, cache, clock=time.time):
    snap = cache.snapshot()
    return {
        "app": APP,
        "generated": datetime.datetime.fromtimestamp(clock()).isoformat(timespec="seconds"),
        "repos": [{"name": r["name"], "path": r["path"], "github": r.get("github", ""),
                   "branch": r.get("branch", "main"), "beads": bool(r.get("beads")),
                   "sources": snap.get(r["name"], {})} for r in repos],
    }
