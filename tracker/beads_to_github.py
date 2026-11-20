#!/usr/bin/env python3
"""beads_to_github.py: move a repo's beads tickets to GitHub Issues.

Dry run by default: prints the plan and changes nothing. With --apply it creates labels and issues
in dependency order (so "Blocked by #N" holds real numbers), closes done tickets with a comment
citing their merge commit, carries agent notes over as a comment, and writes an id map. Each issue
holds a hidden marker naming its beads id, so re-running skips what exists and resumes a partial run.

Usage:
    py tracker/beads_to_github.py --repo-path C:/projects/git-vault --github owner/name --branch factory
    py tracker/beads_to_github.py ... --apply

Mapping: parent -> "## Parent #N"; "blocks" dependencies -> "## Blocked by"; agent-ok -> ready-for-agent,
human-only -> ready-for-human, closed -> closed with no triage label; src:* labels are dropped; the
ticket's YAML spec is kept in a fenced block. Exit codes: 0 ok, 2 error.
"""
import argparse
import heapq
import json
import os
import re
import subprocess
import sys
import tempfile

if not __package__:  # run as a script: put the kit root on the path so `tracker` imports
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracker import gh_tracker  # noqa: E402
from tracker.gh_tracker import GithubTracker, TrackerError  # noqa: E402

MARK = "<!-- beads:{} -->"
MARK_RE = re.compile(r"<!-- beads:(\S+) -->")
_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.S)
LABEL_COLOR = "ededed"


class MigrateError(Exception):
    pass


def default_run(cmd, cwd=None, env=None):
    """(returncode, text). gh goes through the tracker's runner so GH_BIN works; bd and git run here."""
    if cmd[0] == "gh":
        try:
            return gh_tracker.default_run(cmd)
        except TrackerError as e:
            raise MigrateError(str(e))
    import shutil
    exe = shutil.which(cmd[0])
    if not exe:
        raise MigrateError(f"{cmd[0]} not found")
    r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, cwd=cwd, encoding="utf-8",
                       env=dict(os.environ, **env) if env else None, timeout=120)
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout))


def blockers(t):
    return [d["depends_on_id"] for d in (t.get("dependencies") or []) if d.get("type") == "blocks"]


def order(tickets):
    """Parents and blockers before the tickets that need them (Kahn, ties by priority then id)."""
    by = {t["id"]: t for t in tickets}
    need = {}
    for t in tickets:
        deps = set(blockers(t)) | ({t["parent"]} if t.get("parent") else set())
        missing = deps - set(by)
        if missing:
            raise MigrateError(f"{t['id']} depends on unknown ticket(s): {', '.join(sorted(missing))}")
        need[t["id"]] = deps
    key = lambda i: (by[i].get("priority", 9), i)
    heap = [(key(i), i) for i, d in need.items() if not d]
    heapq.heapify(heap)
    out, done = [], set()
    while heap:
        _, i = heapq.heappop(heap)
        out.append(by[i])
        done.add(i)
        for j, d in need.items():
            if j not in done and i in d and d <= done and all(j != x for _, x in heap):
                heapq.heappush(heap, (key(j), j))
    if len(out) != len(tickets):
        raise MigrateError("dependency cycle among: " + ", ".join(sorted(set(need) - done)))
    return out


def labels_for(t):
    own = t.get("labels") or []
    keep = [l for l in own if l not in ("agent-ok", "human-only") and not l.startswith("src:")]
    if t.get("status") == "closed":
        return keep
    triage = "ready-for-agent" if "agent-ok" in own else "ready-for-human" if "human-only" in own else "needs-triage"
    return [triage, *keep]


def render_body(t, numbers):
    parts = [MARK.format(t["id"]), f"Migrated from beads `{t['id']}`."]
    if t.get("parent"):
        parts.append(f"## Parent\n\n#{numbers[t['parent']]}")
    desc = (t.get("description") or "").replace("\r\n", "\n")
    fm = _FRONT.match(desc)
    if fm:
        parts.append(f"## Spec\n\n```yaml\n{fm.group(1)}\n```")
        desc = fm.group(2)
    if desc.strip():
        parts.append(desc.strip())
    bl = blockers(t)
    parts.append("## Blocked by\n\n" + ("\n".join(f"- Blocked by #{numbers[b]}" for b in bl) if bl
                                        else "None - can start immediately"))
    return "\n\n".join(parts) + "\n"


def load_tickets(run, repo_path):
    rc, out = run(["bd", "list", "--all", "--limit", "0", "--json"], cwd=repo_path,
                  env={"BEADS_DIR": os.path.join(repo_path, ".beads")})
    if rc != 0:
        raise MigrateError(f"bd list failed: {out.strip() or 'exit ' + str(rc)}")
    starts = [i for i in (out.find("["), out.find("{")) if i >= 0]
    if not starts:
        raise MigrateError("bd list: no JSON in its output")
    try:
        d = json.loads(out[min(starts):])
    except ValueError as e:
        raise MigrateError(f"bd list: could not read its JSON ({e})")
    return d.get("issues", []) if isinstance(d, dict) else d


def merge_sha(run, repo_path, branch, tid):
    rc, out = run(["git", "-C", repo_path, "log", branch, "--merges", "-n", "1", "--format=%h",
                   f"--grep=^Merge {tid}:"])
    return out.split()[0] if rc == 0 and out.strip() else None


def done_comment(sha, branch):
    if sha:
        return f"Done. Built by the factory loop and merged into `{branch}` as {sha}."
    return f"Done in beads. No merge commit was found on `{branch}`."


def _write(run, what, cmd):
    rc, out = run(cmd)
    if rc != 0:
        raise MigrateError(f"{what} failed: {out.strip() or 'exit ' + str(rc)}")
    return out


def _with_file(text, fn):
    f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    try:
        f.write(text)
        f.close()
        return fn(f.name.replace("\\", "/"))
    finally:
        os.unlink(f.name)


def main(argv=None, run=default_run, out=print):
    ap = argparse.ArgumentParser(prog="beads_to_github", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-path", required=True, help="repo with the .beads store")
    ap.add_argument("--github", required=True, help="owner/name to create the issues in")
    ap.add_argument("--branch", default="main", help="integration branch, to find each ticket's merge commit")
    ap.add_argument("--apply", action="store_true", help="make the changes (default is a dry run)")
    ap.add_argument("--map-out", default=None, help="id map file (default: <repo>/tracker/github-issue-map.json)")
    a = ap.parse_args(argv)
    repo, gh = a.repo_path, a.github
    try:
        tickets = order(load_tickets(run, repo))
        gt = GithubTracker(gh, lambda c: run(c))
        existing = {}
        for i in gt.issues():
            mk = MARK_RE.search(i.get("body") or "")
            if mk:
                existing[mk.group(1)] = i
        todo = [t for t in tickets if t["id"] not in existing]
        if not a.apply:
            rc, vis = run(["gh", "repo", "view", gh, "--json", "visibility", "--jq", ".visibility"])
            out(f"Migration plan: beads in {repo} -> GitHub {gh} [{vis.strip() if rc == 0 else 'visibility unknown'}]")
            out(f"{len(todo)} issue(s) to create, {len(existing)} already migrated (skipped).")
            for t in todo:
                sha = merge_sha(run, repo, a.branch, t["id"]) if t.get("status") == "closed" else None
                state = "closed (" + (f"merged {sha}" if sha else "no merge commit found") + ")" if t.get("status") == "closed" else "open"
                bl = blockers(t)
                out(f"  {t['id']}  {t['title']}  [{', '.join(labels_for(t))}]  {state}"
                    + (f"  blocked by {', '.join(bl)}" if bl else ""))
            out("Dry run: nothing was changed. Re-run with --apply to create these issues.")
            return 0

        numbers = {bid: i["number"] for bid, i in existing.items()}
        used = sorted({l for t in todo for l in labels_for(t)})
        for l in used:
            _write(run, f"gh label create {l}", ["gh", "label", "create", l, "--repo", gh, "--color", LABEL_COLOR, "--force"])
        for t in tickets:
            tid, closed = t["id"], t.get("status") == "closed"
            if tid in existing:  # resume: make sure a done ticket is closed
                i = existing[tid]
                if closed and i["state"] == "OPEN":
                    sha = merge_sha(run, repo, a.branch, tid)
                    _write(run, f"gh issue close #{i['number']}", ["gh", "issue", "close", str(i["number"]), "--repo", gh,
                                                                    "--reason", "completed", "--comment", done_comment(sha, a.branch)])
                    out(f"closed  #{i['number']} {tid} (already migrated)")
                continue
            cmd = ["gh", "issue", "create", "--repo", gh, "--title", t["title"], "--body-file", "{body}"]
            for l in labels_for(t):
                cmd += ["--label", l]
            created = _with_file(render_body(t, numbers), lambda p: _write(
                run, f"gh issue create for {tid}", [p if c == "{body}" else c for c in cmd]))
            m = re.search(r"/issues/(\d+)", created)
            if not m:
                raise MigrateError(f"gh issue create for {tid}: no issue number in {created.strip()!r}")
            n = numbers[tid] = int(m.group(1))
            out(f"created #{n} {tid} {t['title']}")
            if (t.get("notes") or "").strip():
                _with_file("Agent notes carried over from beads:\n\n" + t["notes"].strip() + "\n", lambda p: _write(
                    run, f"gh issue comment #{n}", ["gh", "issue", "comment", str(n), "--repo", gh, "--body-file", p]))
            if closed:
                _write(run, f"gh issue close #{n}", ["gh", "issue", "close", str(n), "--repo", gh, "--reason", "completed",
                                                      "--comment", done_comment(merge_sha(run, repo, a.branch, tid), a.branch)])
        mp = a.map_out or os.path.join(repo, "tracker", "github-issue-map.json")
        if mp != os.devnull:
            os.makedirs(os.path.dirname(os.path.abspath(mp)), exist_ok=True)
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(numbers, f, indent=2, sort_keys=True)
        out(f"Done: {len(todo)} created, {len(existing)} already existed. Id map: {mp}")
        return 0
    except (MigrateError, TrackerError) as e:
        out(f"beads_to_github: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
