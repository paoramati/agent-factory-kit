"""Collectors: gather one Source's data for one repo.

A collector takes (repo, run) and returns plain data, or raises SourceError. `run` is the
command runner: run(cmd, cwd=None, env=None) -> (returncode, stdout). It raises SourceError
only when the command cannot run or times out; a non-zero exit is the collector's call.
"""
import json
import os
import shutil
import subprocess

from tracker.gh_tracker import parse_parents

TIMEOUT = 60
LOCAL_INTERVAL = 3
GITHUB_INTERVAL = 60


class SourceError(Exception):
    pass


def subprocess_run(cmd, cwd=None, env=None):
    exe = shutil.which(cmd[0])  # Windows: npm shims like bd cannot be launched by bare name
    if not exe:
        raise SourceError(f"{cmd[0]} not found")
    try:
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, cwd=cwd,
                           env=dict(os.environ, **env) if env else None, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SourceError(f"{cmd[0]} timed out after {TIMEOUT}s")
    except OSError as e:
        raise SourceError(f"{cmd[0]} failed to start: {e}")
    return r.returncode, r.stdout


def _json(text, what):
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if not starts:
        raise SourceError(f"{what}: no JSON in output")
    try:
        return json.loads(text[min(starts):])
    except ValueError as e:
        raise SourceError(f"{what}: bad JSON ({e})")


def _ok(run, cmd, what, cwd=None, env=None):
    rc, out = run(cmd, cwd=cwd, env=env)
    if rc != 0:
        raise SourceError(f"{what} exited {rc}")
    return out


def tracker(repo, run):
    """The repo's beads tickets."""
    env = {"BEADS_DIR": os.path.join(repo["path"], ".beads")}
    out = _ok(run, ["bd", "list", "--all", "--limit", "0", "--json"], "bd list", cwd=repo["path"], env=env)
    d = _json(out, "bd list")
    return d.get("issues", []) if isinstance(d, dict) else d


def github(repo, run):
    """GitHub issues and pull requests."""
    g = repo["github"]
    issues = _json(_ok(run, ["gh", "issue", "list", "--repo", g, "--state", "all", "--limit", "50",
                             "--json", "number,title,state,url,labels,body"], "gh issue list"), "gh issue list")
    epics = {p for i in issues for p in parse_parents(i.get("body"))}  # an issue others name as parent
    for i in issues:
        i.pop("body", None)  # only needed to find parents; keep the state small
        i["epic"] = i["number"] in epics
    prs = _json(_ok(run, ["gh", "pr", "list", "--repo", g, "--state", "all", "--limit", "50",
                          "--json", "number,title,state,url,headRefName"], "gh pr list"), "gh pr list")
    return {"issues": issues, "prs": prs}


def git(repo, run):
    """Repo state plus the agent/<id> branches (local PRs)."""
    p = repo["path"]
    if not os.path.isdir(os.path.join(p, ".git")):
        return {"missing": True}
    base = repo.get("branch", "main")

    def g(*args):
        return ["git", "-C", p, *args]

    def req(*args):  # must succeed
        return _ok(run, g(*args), f"git {args[0]}").strip()

    def opt(*args):  # failure is a normal answer (no upstream, no origin/main)
        rc, out = run(g(*args))
        return out.strip() if rc == 0 else ""

    upstream = opt("rev-parse", "--abbrev-ref", f"{base}@{{upstream}}")
    if upstream:
        unpushed = req("rev-list", "--count", f"{upstream}..{base}")
    elif opt("rev-parse", "--verify", "-q", "origin/main"):
        unpushed = req("rev-list", "--count", f"origin/main..{base}") + " (branch not pushed)"
    else:
        unpushed = "no remote"
    state = {
        "unpushed": unpushed,
        "dirty": bool(req("status", "--porcelain")),
        "merges": req("log", base, "--merges", "--format=%cI|%s", "-n", "8").splitlines(),
        "head": req("log", "-1", "--format=%h %s", base),
    }
    lprs = []
    for n in req("for-each-ref", "--format=%(refname:short)", "refs/heads/agent/").splitlines():
        rc, _ = run(g("merge-base", "--is-ancestor", n, base))
        when, _, subject = req("log", "-1", "--format=%cI|%s", n).partition("|")  # ISO 8601 with time and zone
        lprs.append({"branch": n, "merged": rc == 0, "ahead": req("rev-list", "--count", f"{base}..{n}"),
                     "last": subject, "when": when})
    return {"state": state, "lprs": lprs}


def register(cache, repos, run=subprocess_run):
    """Register every Source each repo has: tracker if beads, github if a GitHub remote, git always."""
    for r in repos:
        name = r["name"]
        if r.get("beads"):
            cache.register(name, "tracker", lambda r=r: tracker(r, run), LOCAL_INTERVAL)
        if r.get("github"):
            cache.register(name, "github", lambda r=r: github(r, run), GITHUB_INTERVAL)
        cache.register(name, "git", lambda r=r: git(r, run), LOCAL_INTERVAL)
