import json
import os
import tempfile
import unittest

from dashboard import collect
from dashboard.cache import Cache
from dashboard.collect import SourceError


class FakeRun:
    """Stands in for the command runner. Responses are keyed by the joined command."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, cmd, cwd=None, env=None):
        self.calls.append((list(cmd), cwd, env))
        r = self.responses.get(" ".join(cmd), (1, ""))
        if isinstance(r, Exception):
            raise r
        return r


BEADS = ["bd", "list", "--all", "--limit", "0", "--json"]


def beads_cmd():
    return " ".join(BEADS)


class TrackerTest(unittest.TestCase):
    repo = {"name": "r", "path": "/p", "beads": True}

    def test_parses_object_form(self):
        run = FakeRun({beads_cmd(): (0, json.dumps({"issues": [{"id": "a-1"}]}))})
        self.assertEqual(collect.tracker(self.repo, run), [{"id": "a-1"}])

    def test_parses_list_form_after_a_preamble(self):
        run = FakeRun({beads_cmd(): (0, "note: something\n" + json.dumps([{"id": "a-2"}]))})
        self.assertEqual(collect.tracker(self.repo, run), [{"id": "a-2"}])

    def test_points_bd_at_the_repo_store(self):
        run = FakeRun({beads_cmd(): (0, "[]")})
        collect.tracker(self.repo, run)
        _, cwd, env = run.calls[0]
        self.assertEqual(cwd, "/p")
        self.assertEqual(env["BEADS_DIR"], os.path.join("/p", ".beads"))

    def test_nonzero_exit_is_an_error_not_empty(self):
        with self.assertRaises(SourceError):
            collect.tracker(self.repo, FakeRun({beads_cmd(): (1, "")}))

    def test_bad_json_is_an_error_not_empty(self):
        with self.assertRaises(SourceError):
            collect.tracker(self.repo, FakeRun({beads_cmd(): (0, "not json")}))

    def test_timeout_propagates(self):
        with self.assertRaises(SourceError):
            collect.tracker(self.repo, FakeRun({beads_cmd(): SourceError("timed out")}))


ISSUES = "gh issue list --repo o/r --state all --limit 50 --json number,title,state,url,labels,body"
PRS = "gh pr list --repo o/r --state all --limit 50 --json number,title,state,url,headRefName"


class GithubTest(unittest.TestCase):
    repo = {"name": "r", "path": "/p", "github": "o/r"}

    def test_returns_issues_and_prs(self):
        run = FakeRun({ISSUES: (0, '[{"number": 1}]'), PRS: (0, '[{"number": 2}]')})
        self.assertEqual(collect.github(self.repo, run),
                         {"issues": [{"number": 1, "epic": False}], "prs": [{"number": 2}]})

    def test_an_issue_named_as_a_parent_is_flagged_as_an_epic_and_bodies_are_dropped(self):
        issues = [{"number": 1, "body": "the PRD"}, {"number": 2, "body": "## Parent\n\n#1\n"},
                  {"number": 3, "body": None}]
        got = collect.github(self.repo, FakeRun({ISSUES: (0, json.dumps(issues)), PRS: (0, "[]")}))["issues"]
        self.assertEqual([(i["number"], i["epic"]) for i in got], [(1, True), (2, False), (3, False)])
        self.assertTrue(all("body" not in i for i in got))

    def test_either_call_failing_is_an_error(self):
        with self.assertRaises(SourceError):
            collect.github(self.repo, FakeRun({ISSUES: (0, "[]"), PRS: (1, "")}))
        with self.assertRaises(SourceError):
            collect.github(self.repo, FakeRun({ISSUES: (1, ""), PRS: (0, "[]")}))

    def test_bad_json_is_an_error(self):
        with self.assertRaises(SourceError):
            collect.github(self.repo, FakeRun({ISSUES: (0, "oops"), PRS: (0, "[]")}))


class GitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.mkdir(os.path.join(self.tmp.name, ".git"))
        self.p = self.tmp.name
        self.repo = {"name": "r", "path": self.p, "branch": "factory"}

    def g(self, *args):
        return " ".join(["git", "-C", self.p, *args])

    def base(self, **over):
        r = {
            self.g("rev-parse", "--abbrev-ref", "factory@{upstream}"): (0, "origin/factory\n"),
            self.g("rev-list", "--count", "origin/factory..factory"): (0, "0\n"),
            self.g("log", "factory", "--merges", "--format=%cI|%s", "-n", "8"): (0, "2026-11-21T14:03:09+13:00|Merge gv-1: a\n"),
            self.g("status", "--porcelain"): (0, ""),
            self.g("log", "-1", "--format=%h %s", "factory"): (0, "abc1234 head subject\n"),
            self.g("for-each-ref", "--format=%(refname:short)", "refs/heads/agent/"): (0, ""),
        }
        r.update(over)
        return FakeRun(r)

    def test_missing_repo_is_reported_not_raised(self):
        out = collect.git({"name": "r", "path": os.path.join(self.p, "nope")}, FakeRun())
        self.assertEqual(out, {"missing": True})

    def test_state_with_upstream(self):
        s = collect.git(self.repo, self.base())["state"]
        self.assertEqual(s["unpushed"], "0")
        self.assertFalse(s["dirty"])
        self.assertEqual(s["merges"], ["2026-11-21T14:03:09+13:00|Merge gv-1: a"])
        self.assertEqual(s["head"], "abc1234 head subject")

    def test_unpushed_count_and_dirty(self):
        run = self.base(**{self.g("rev-list", "--count", "origin/factory..factory"): (0, "3\n"),
                           self.g("status", "--porcelain"): (0, " M file\n")})
        s = collect.git(self.repo, run)["state"]
        self.assertEqual(s["unpushed"], "3")
        self.assertTrue(s["dirty"])

    def test_branch_not_pushed_counts_against_origin_main(self):
        run = self.base(**{self.g("rev-parse", "--abbrev-ref", "factory@{upstream}"): (128, ""),
                           self.g("rev-parse", "--verify", "-q", "origin/main"): (0, "sha\n"),
                           self.g("rev-list", "--count", "origin/main..factory"): (0, "5\n")})
        self.assertEqual(collect.git(self.repo, run)["state"]["unpushed"], "5 (branch not pushed)")

    def test_no_remote(self):
        run = self.base(**{self.g("rev-parse", "--abbrev-ref", "factory@{upstream}"): (128, ""),
                           self.g("rev-parse", "--verify", "-q", "origin/main"): (1, "")})
        self.assertEqual(collect.git(self.repo, run)["state"]["unpushed"], "no remote")

    def test_local_prs_merged_and_open(self):
        run = self.base(**{
            self.g("for-each-ref", "--format=%(refname:short)", "refs/heads/agent/"): (0, "agent/gv-1\nagent/gv-2\n"),
            self.g("merge-base", "--is-ancestor", "agent/gv-1", "factory"): (0, ""),
            self.g("merge-base", "--is-ancestor", "agent/gv-2", "factory"): (1, ""),
            self.g("rev-list", "--count", "factory..agent/gv-1"): (0, "0\n"),
            self.g("rev-list", "--count", "factory..agent/gv-2"): (0, "2\n"),
            self.g("log", "-1", "--format=%cI|%s", "agent/gv-1"): (0, "2026-11-21T10:00:00+13:00|one\n"),
            self.g("log", "-1", "--format=%cI|%s", "agent/gv-2"): (0, "2026-11-21T11:30:45+13:00|two\n"),
        })
        lprs = collect.git(self.repo, run)["lprs"]
        self.assertEqual(lprs, [
            {"branch": "agent/gv-1", "merged": True, "ahead": "0", "last": "one", "when": "2026-11-21T10:00:00+13:00"},
            {"branch": "agent/gv-2", "merged": False, "ahead": "2", "last": "two", "when": "2026-11-21T11:30:45+13:00"},
        ])

    def test_failure_of_a_required_command_is_an_error(self):
        run = self.base(**{self.g("log", "-1", "--format=%h %s", "factory"): (128, "")})
        with self.assertRaises(SourceError):
            collect.git(self.repo, run)

    def test_timeout_propagates(self):
        run = self.base(**{self.g("status", "--porcelain"): SourceError("timed out")})
        with self.assertRaises(SourceError):
            collect.git(self.repo, run)


class RegisterTest(unittest.TestCase):
    def test_registers_only_the_sources_a_repo_has(self):
        cache = Cache()
        repos = [{"name": "a", "path": "/a", "beads": True, "github": "o/a"},
                 {"name": "b", "path": "/b", "beads": False, "github": ""}]
        collect.register(cache, repos, FakeRun())
        snap = cache.snapshot()
        self.assertEqual(sorted(snap["a"]), ["git", "github", "tracker"])
        self.assertEqual(sorted(snap["b"]), ["git"])


class RunnerTest(unittest.TestCase):
    def test_missing_tool_is_a_source_error_naming_it(self):
        with self.assertRaisesRegex(SourceError, "definitely-not-a-tool"):
            collect.subprocess_run(["definitely-not-a-tool", "x"])


if __name__ == "__main__":
    unittest.main()
