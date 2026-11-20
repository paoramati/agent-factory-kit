import json
import os
import tempfile
import unittest

from tracker import beads_to_github as m
from tracker.gh_tracker import GithubTracker, parse_blockers, parse_parents

FRONT = "---\nid: P-1\ntitle: A\nlabels: [agent-ok]\nacceptance_criteria:\n  - works\n---\n\n## Problem\nthe body\n"


def ticket(id, title, status="open", labels=("agent-ok",), parent="e", blocks=(), description="", notes=None,
           issue_type="task"):
    deps = [{"issue_id": id, "depends_on_id": b, "type": "blocks"} for b in blocks]
    if parent:
        deps.append({"issue_id": id, "depends_on_id": parent, "type": "parent-child"})
    return {"id": id, "title": title, "status": status, "labels": list(labels), "parent": parent,
            "dependencies": deps or None, "description": description, "notes": notes, "issue_type": issue_type}


def graph():
    return [
        ticket("c", "Third", blocks=("a", "b")),
        ticket("b", "Second", blocks=("a",), description="plain description"),
        ticket("a", "First", status="closed", description=FRONT, notes="agent notes here", labels=("agent-ok", "risk:med", "src:P-1")),
        ticket("e", "Epic", labels=("human-only", "src:E-1"), parent=None, issue_type="epic", description="epic body"),
    ]


class FakeWorld:
    """Fake bd, git and gh in one runner. gh keeps issues in memory and numbers new ones from 101."""

    def __init__(self, tickets, existing=(), merges=None, visibility="PUBLIC"):
        self.tickets, self.merges, self.visibility = tickets, merges or {}, visibility
        self.issues = [dict(i) for i in existing]
        self.next = 101
        self.writes, self.labels = [], []

    def __call__(self, cmd, cwd=None, env=None):
        tool, a = cmd[0], cmd[1:]
        if tool == "bd":
            return 0, json.dumps({"issues": self.tickets})
        if tool == "git":
            tid = next((x[len("--grep=^Merge "):-1] for x in a if x.startswith("--grep=")), None)
            sha = self.merges.get(tid)
            return 0, (f"{sha} Merge {tid}: x\n" if sha else "")
        if tool == "gh":
            return self.gh(a)
        raise AssertionError(cmd)

    def opt(self, a, name):
        return [a[i + 1] for i, x in enumerate(a) if x == name]

    def gh(self, a):
        if a[:2] == ["issue", "list"]:
            return 0, json.dumps([{"number": i["number"], "title": i["title"], "state": i["state"], "body": i["body"],
                                   "labels": [{"name": l} for l in i["labels"]]} for i in self.issues])
        if a[:2] == ["repo", "view"]:
            return 0, self.visibility + "\n"
        self.writes.append(" ".join(a[:3]))
        if a[:2] == ["label", "create"]:
            self.labels.append(a[2])
            return 0, ""
        if a[:2] == ["issue", "create"]:
            with open(self.opt(a, "--body-file")[0], encoding="utf-8") as f:
                body = f.read()
            n = self.next
            self.next += 1
            self.issues.append({"number": n, "title": self.opt(a, "--title")[0], "state": "OPEN",
                                "labels": self.opt(a, "--label"), "body": body, "comments": []})
            return 0, f"https://github.com/o/r/issues/{n}\n"
        n = int(a[2])
        issue = next(i for i in self.issues if i["number"] == n)
        if a[:2] == ["issue", "comment"]:
            with open(self.opt(a, "--body-file")[0], encoding="utf-8") as f:
                issue.setdefault("comments", []).append(f.read())
        elif a[:2] == ["issue", "close"]:
            issue["state"] = "CLOSED"
            issue.setdefault("comments", []).extend(self.opt(a, "--comment"))
        return 0, ""

    def by_title(self, title):
        return next(i for i in self.issues if i["title"] == title)


def migrate(world, *extra, tmp=None):
    out = []
    mp = os.path.join(tmp, "map.json") if tmp else "map.json"
    code = m.main(["--repo-path", "/p", "--github", "o/r", "--branch", "factory", "--map-out", mp, *extra],
                  run=world, out=out.append)
    return code, "\n".join(out), mp


class PlanTest(unittest.TestCase):
    def test_parents_then_blockers_before_dependents(self):
        order = [t["id"] for t in m.order(graph())]
        self.assertEqual(order, ["e", "a", "b", "c"])

    def test_cycle_is_an_error(self):
        with self.assertRaisesRegex(m.MigrateError, "cycle"):
            m.order([ticket("a", "A", blocks=("b",), parent=None), ticket("b", "B", blocks=("a",), parent=None)])

    def test_labels(self):
        self.assertEqual(m.labels_for(graph()[2]), ["risk:med"])                                    # closed: no triage label
        self.assertEqual(m.labels_for(ticket("x", "X", labels=("agent-ok", "risk:high", "type:spike", "src:M-2"))),
                         ["ready-for-agent", "risk:high", "type:spike"])
        self.assertEqual(m.labels_for(ticket("x", "X", labels=("human-only",))), ["ready-for-human"])
        self.assertEqual(m.labels_for(ticket("x", "X", labels=())), ["needs-triage"])


class BodyTest(unittest.TestCase):
    def test_body_has_marker_parent_spec_and_blockers_the_tracker_can_read(self):
        t = graph()[2]
        body = m.render_body(t, {"e": 101, "a": 102})
        self.assertTrue(body.startswith("<!-- beads:a -->"))
        self.assertEqual(parse_parents(body), [101])
        self.assertIn("```yaml\nid: P-1", body)
        self.assertIn("the body", body)
        self.assertEqual(parse_blockers(body), ([], []))

    def test_blockers_become_real_numbers(self):
        body = m.render_body(graph()[0], {"e": 101, "a": 102, "b": 103})
        self.assertEqual(parse_blockers(body), ([102, 103], []))

    def test_description_without_frontmatter_is_kept(self):
        self.assertIn("plain description", m.render_body(graph()[1], {"e": 101, "a": 102}))


class DryRunTest(unittest.TestCase):
    def test_makes_no_write_call_and_says_what_it_would_do(self):
        w = FakeWorld(graph(), merges={"a": "abc1234"})
        code, out, mp = migrate(w)
        self.assertEqual(code, 0)
        self.assertEqual(w.writes, [])
        self.assertFalse(os.path.exists(mp))
        self.assertIn("o/r", out)
        self.assertIn("PUBLIC", out)
        self.assertIn("4 issue", out)
        self.assertIn("--apply", out)

    def test_dry_run_shows_what_exists_already(self):
        existing = [{"number": 7, "title": "Epic", "state": "OPEN", "labels": [], "body": "<!-- beads:e -->\nx"}]
        _, out, _ = migrate(FakeWorld(graph(), existing=existing))
        self.assertIn("3 issue", out)
        self.assertIn("1 already", out)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def apply(self, world):
        return migrate(world, "--apply", tmp=self.tmp.name)

    def test_creates_blockers_first_with_real_numbers(self):
        w = FakeWorld(graph(), merges={"a": "abc1234"})
        code, _, _ = self.apply(w)
        self.assertEqual(code, 0)
        nums = {i["title"]: i["number"] for i in w.issues}
        self.assertEqual(nums, {"Epic": 101, "First": 102, "Second": 103, "Third": 104})
        self.assertEqual(parse_blockers(w.by_title("Third")["body"]), ([102, 103], []))
        self.assertEqual(parse_parents(w.by_title("Third")["body"]), [101])

    def test_labels_are_created_then_applied(self):
        w = FakeWorld(graph())
        self.apply(w)
        for l in ("ready-for-agent", "ready-for-human", "risk:med"):
            self.assertIn(l, w.labels)
        self.assertEqual(w.by_title("Epic")["labels"], ["ready-for-human"])
        self.assertEqual(w.by_title("Second")["labels"], ["ready-for-agent"])

    def test_the_epic_stays_open_and_it_is_the_tracker_frontier_that_matters(self):
        w = FakeWorld(graph())
        self.apply(w)
        self.assertEqual(w.by_title("Epic")["state"], "OPEN")
        self.assertEqual(GithubTracker("o/r", lambda c: w(c)).ready(), [103])

    def test_done_ticket_is_closed_citing_its_merge_commit(self):
        w = FakeWorld(graph(), merges={"a": "abc1234"})
        self.apply(w)
        first = w.by_title("First")
        self.assertEqual(first["state"], "CLOSED")
        self.assertTrue(any("abc1234" in c for c in first["comments"]))

    def test_done_ticket_without_a_merge_commit_says_so(self):
        w = FakeWorld(graph())
        self.apply(w)
        self.assertTrue(any("no merge commit" in c.lower() for c in w.by_title("First")["comments"]))

    def test_agent_notes_are_carried_over_as_a_comment(self):
        w = FakeWorld(graph())
        self.apply(w)
        self.assertTrue(any("agent notes here" in c for c in w.by_title("First")["comments"]))

    def test_rerun_creates_no_duplicates(self):
        w = FakeWorld(graph())
        self.apply(w)
        before = len(w.issues)
        w.writes.clear()
        self.apply(w)
        self.assertEqual(len(w.issues), before)
        self.assertEqual([x for x in w.writes if x.startswith("issue create")], [])

    def test_resumes_a_partial_run_using_the_existing_numbers(self):
        w = FakeWorld(graph(), existing=[{"number": 50, "title": "Epic", "state": "OPEN", "labels": ["ready-for-human"],
                                           "body": "<!-- beads:e -->\nepic body"}])
        self.apply(w)
        self.assertEqual(len(w.issues), 4)
        self.assertEqual(parse_parents(w.by_title("Second")["body"]), [50])

    def test_resume_closes_a_done_ticket_whose_issue_is_still_open(self):
        existing = [{"number": 50, "title": "Epic", "state": "OPEN", "labels": [], "body": "<!-- beads:e -->"},
                    {"number": 51, "title": "First", "state": "OPEN", "labels": [], "body": "<!-- beads:a -->"}]
        w = FakeWorld(graph(), existing=existing, merges={"a": "abc1234"})
        self.apply(w)
        self.assertEqual(next(i for i in w.issues if i["number"] == 51)["state"], "CLOSED")

    def test_id_map_lists_every_ticket_with_its_issue_number(self):
        w = FakeWorld(graph())
        _, _, mp = self.apply(w)
        with open(mp, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"e": 101, "a": 102, "b": 103, "c": 104})


class ErrorsTest(unittest.TestCase):
    def test_bd_failure_is_an_error_and_writes_nothing(self):
        w = FakeWorld(graph())
        orig = w.__call__

        def run(cmd, cwd=None, env=None):
            return (1, "bd: no store") if cmd[0] == "bd" else orig(cmd, cwd, env)

        out = []
        code = m.main(["--repo-path", "/p", "--github", "o/r", "--apply"], run=run, out=out.append)
        self.assertEqual(code, 2)
        self.assertIn("no store", "\n".join(out))
        self.assertEqual(w.writes, [])

    def test_a_failed_issue_create_stops_with_the_reason(self):
        w = FakeWorld(graph())
        orig = w.__call__

        def run(cmd, cwd=None, env=None):
            if cmd[:3] == ["gh", "issue", "create"]:
                return 1, "gh: rate limited"
            return orig(cmd, cwd, env)

        out = []
        code = m.main(["--repo-path", "/p", "--github", "o/r", "--apply", "--map-out", os.devnull], run=run, out=out.append)
        self.assertEqual(code, 2)
        self.assertIn("rate limited", "\n".join(out))


if __name__ == "__main__":
    unittest.main()
