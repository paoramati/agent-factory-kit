#!/usr/bin/env python3
"""gh_tracker.py: GitHub Issues as the Loop's Tracker.

Frontier: open issues labelled ready-for-agent (not in-progress) whose "## Blocked by" section
lists only closed issues. Blocked by lines are the format the to-issues skill writes:
    ## Blocked by
    - Blocked by #4        (or "- #4"; "None" or empty means no blockers)

Usage (run from anywhere; needs gh signed in):
    py tracker/gh_tracker.py ready --repo owner/name     one issue number per line
    py tracker/gh_tracker.py check --repo owner/name     exit 1 and list problems if a blocker is bad
Exit codes: 0 ok, 1 problems found (check), 2 error (gh failed, bad output).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys

READY = "ready-for-agent"
IN_PROGRESS = "in-progress"
HUMAN = "ready-for-human"
TIMEOUT = 60


class TrackerError(Exception):
    pass


def default_run(cmd):
    """Run a command; return (returncode, text): stdout on success, stderr on failure."""
    exe = shutil.which(cmd[0])  # Windows: find the real executable, not a bare name
    if not exe:
        raise TrackerError(f"{cmd[0]} not found")
    try:
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=TIMEOUT, encoding="utf-8")
    except subprocess.TimeoutExpired:
        raise TrackerError(f"{cmd[0]} timed out after {TIMEOUT}s")
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout))


_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")  # "#1" alone is a reference, not a heading
_NUM = re.compile(r"#(\d+)")


def _section(body, name):
    """Non-blank lines under the heading `name` (any level, any case) up to the next heading."""
    lines, inside = [], False
    for line in (body or "").splitlines():
        m = _HEADING.match(line.rstrip())
        if m:
            inside = m.group(1).lower() == name
        elif inside and line.strip():
            lines.append(line.rstrip())
    return lines


def parse_parents(body):
    """Issue numbers named under the body's Parent section."""
    return [int(n) for line in _section(body, "parent") for n in _NUM.findall(line)]


def parse_blockers(body):
    """Return (blocker numbers, malformed lines) from an issue body's Blocked by section."""
    nums, bad = [], []
    for line in _section(body, "blocked by"):
        if line.strip().lstrip("-* ").lower().startswith("none"):
            continue
        found = _NUM.findall(line)
        if found:
            nums += [int(n) for n in found]
        else:
            bad.append(line.strip())
    return nums, bad


class GithubTracker:
    def __init__(self, repo, run=default_run, ready_label=READY):
        self.repo, self._run, self.ready_label = repo, run, ready_label

    def _gh(self, *args):
        rc, out = self._run(["gh", *args])
        if rc != 0:
            raise TrackerError(f"gh {' '.join(args[:2])} failed: {out.strip() or 'exit ' + str(rc)}")
        return out

    def issues(self):
        out = self._gh("issue", "list", "--repo", self.repo, "--state", "all", "--limit", "1000",
                       "--json", "number,title,state,labels,body")
        try:
            data = json.loads(out)
        except ValueError as e:
            raise TrackerError(f"gh issue list: bad JSON ({e})")
        if not isinstance(data, list):
            raise TrackerError("gh issue list: expected a list")
        return data

    @staticmethod
    def _labels(i):
        return {l["name"] for l in i.get("labels", [])}

    def _analyse(self):
        """(by number, ready candidates with their blockers) from one listing."""
        by = {i["number"]: i for i in self.issues()}
        cands = {n: parse_blockers(i.get("body")) for n, i in by.items()
                 if i["state"] == "OPEN" and self.ready_label in self._labels(i)}
        return by, cands

    def ready(self):
        by, cands = self._analyse()
        epics = {p for i in by.values() for p in parse_parents(i.get("body"))}  # a parent is an epic, not a ticket
        out = []
        for n, (blockers, bad) in cands.items():
            if n in epics or IN_PROGRESS in self._labels(by[n]) or bad:
                continue
            if all(b != n and b in by and by[b]["state"] == "CLOSED" for b in blockers):
                out.append(n)
        return sorted(out)

    def check(self):
        by, cands = self._analyse()
        problems = []
        for n, (blockers, bad) in sorted(cands.items()):
            for b in blockers:
                if b == n:
                    problems.append(f"#{n} is blocked by itself")
                elif b not in by:
                    problems.append(f"#{n} is blocked by #{b}, which does not exist in {self.repo}")
            for line in bad:
                problems.append(f"#{n} has a Blocked by line with no issue number: {line}")
        return problems


def main(argv=None, run=default_run, out=print):
    ap = argparse.ArgumentParser(prog="gh_tracker", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ready", "check"])
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--ready-label", default=READY)
    a = ap.parse_args(argv)
    t = GithubTracker(a.repo, run, a.ready_label)
    try:
        if a.command == "ready":
            for n in t.ready():
                out(str(n))
            return 0
        problems = t.check()
        for p in problems:
            out(p)
        return 1 if problems else 0
    except TrackerError as e:
        out(f"gh_tracker: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
