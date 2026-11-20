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

    # ---- actions: how the Loop changes an issue's state --------------------------------------
    def _edit(self, n, *flags):
        self._gh("issue", "edit", str(n), "--repo", self.repo, *flags)

    def claim(self, n):
        self._edit(n, "--add-label", IN_PROGRESS)

    def status(self, n, status):
        """open: back to the Frontier. blocked: handed to a human. in_progress: claimed."""
        if status == "open":
            self._edit(n, "--remove-label", IN_PROGRESS)
        elif status == "in_progress":
            self.claim(n)
        elif status == "blocked":
            self._edit(n, "--remove-label", self.ready_label, "--remove-label", IN_PROGRESS,
                       "--add-label", HUMAN)
        else:
            raise TrackerError(f"unknown status {status!r} (use open, in_progress or blocked)")

    def note(self, n, text):
        self._gh("issue", "comment", str(n), "--repo", self.repo, "--body", text)

    def close(self, n, comment=None):
        self._edit(n, "--remove-label", IN_PROGRESS)
        extra = ["--comment", comment] if comment else []
        self._gh("issue", "close", str(n), "--repo", self.repo, "--reason", "completed", *extra)

    def title(self, n):
        return self._gh("issue", "view", str(n), "--repo", self.repo, "--json", "title", "--jq", ".title").strip()

    def ensure_labels(self):
        """Create the labels the Loop sets, if the repo lacks them (--force updates, never fails on exists)."""
        for name, color, desc in ((IN_PROGRESS, "fbca04", "An agent is working this ticket"),
                                  (HUMAN, "d93f0b", "Needs a human: the Loop gave up or it is not for agents")):
            self._gh("label", "create", name, "--repo", self.repo, "--color", color, "--description", desc, "--force")


def issue_number(ref):
    """12, '12', '#12' or a Loop id 'gh-12' -> 12."""
    m = re.fullmatch(r"(?:gh-|#)?(\d+)", str(ref).strip())
    if not m:
        raise TrackerError(f"not an issue reference: {ref!r} (use 12, #12 or gh-12)")
    return int(m.group(1))


def main(argv=None, run=default_run, out=print):
    ap = argparse.ArgumentParser(prog="gh_tracker", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["ready", "check", "claim", "note", "status", "close", "title", "setup"])
    ap.add_argument("ticket", nargs="?", help="issue number, #number or gh-number")
    ap.add_argument("value", nargs="?", help="status: open | in_progress | blocked")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--ready-label", default=READY)
    ap.add_argument("--body", default="", help="note text")
    ap.add_argument("--comment", default=None, help="close: comment to post")
    a = ap.parse_args(argv)
    t = GithubTracker(a.repo, run, a.ready_label)
    try:
        if a.command == "ready":
            for n in t.ready():
                out(str(n))
            return 0
        if a.command == "check":
            problems = t.check()
            for p in problems:
                out(p)
            return 1 if problems else 0
        if a.command == "setup":
            t.ensure_labels()
            return 0
        if a.ticket is None:
            raise TrackerError(f"{a.command} needs an issue number")
        n = issue_number(a.ticket)
        if a.command == "claim":
            t.claim(n)
        elif a.command == "status":
            t.status(n, a.value or "")
        elif a.command == "close":
            t.close(n, a.comment)
        elif a.command == "title":
            out(t.title(n))
        elif a.command == "note":
            try:
                t.note(n, a.body)
            except TrackerError as e:  # a missing note must never stop the Loop
                out(f"gh_tracker: warning: note not posted: {e}")
        return 0
    except TrackerError as e:
        out(f"gh_tracker: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
