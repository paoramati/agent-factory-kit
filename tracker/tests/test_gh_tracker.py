import json
import unittest

from tracker import gh_tracker
from tracker.gh_tracker import GithubTracker, TrackerError, parse_blockers

LIST = "gh issue list --repo o/r --state all --limit 1000 --json number,title,state,labels,body"


def issue(n, state="OPEN", labels=("ready-for-agent",), blocked=None, title=None):
    if blocked is None:
        body = "## What to build\n\nx\n\n## Blocked by\n\nNone - can start immediately\n"
    else:
        body = "## Blocked by\n\n" + "\n".join(blocked) + "\n"
    return {"number": n, "title": title or f"Issue {n}", "state": state,
            "labels": [{"name": l} for l in labels], "body": body}


class FakeRun:
    def __init__(self, issues=None, listing=None):
        self.calls = []
        self.listing = listing if listing is not None else (0, json.dumps(issues or []))

    def __call__(self, cmd):
        self.calls.append(" ".join(cmd))
        if " ".join(cmd) == LIST:
            return self.listing
        return (0, "")


class ParseBlockersTest(unittest.TestCase):
    def test_none_and_empty_mean_no_blockers(self):
        self.assertEqual(parse_blockers("## Blocked by\n\nNone - can start immediately\n"), ([], []))
        self.assertEqual(parse_blockers("## Blocked by\n\n"), ([], []))

    def test_missing_section_means_no_blockers(self):
        self.assertEqual(parse_blockers("## What to build\n\nx"), ([], []))
        self.assertEqual(parse_blockers(""), ([], []))
        self.assertEqual(parse_blockers(None), ([], []))

    def test_both_bullet_forms(self):
        body = "## Blocked by\n\n- Blocked by #4\n- #5\n* Blocked by #6 (the cache)\n"
        self.assertEqual(parse_blockers(body), ([4, 5, 6], []))

    def test_section_ends_at_the_next_heading(self):
        body = "## Blocked by\n\n- #4\n\n## Notes\n\n- #99 unrelated\n"
        self.assertEqual(parse_blockers(body), ([4], []))

    def test_prose_blocker_is_malformed(self):
        nums, bad = parse_blockers("## Blocked by\n\n- Blocked by the cache slice\n")
        self.assertEqual(nums, [])
        self.assertEqual(bad, ["- Blocked by the cache slice"])

    def test_heading_level_and_case_are_flexible(self):
        self.assertEqual(parse_blockers("### blocked BY\n- #7\n"), ([7], []))

    def test_a_bare_issue_reference_line_does_not_end_the_section(self):
        self.assertEqual(parse_blockers("## Blocked by\n\n#4\n#5\n"), ([4, 5], []))

    def test_crlf_bodies(self):
        self.assertEqual(parse_blockers("## Blocked by\r\n\r\n- #4\r\n"), ([4], []))


class ReadyTest(unittest.TestCase):
    def ready(self, issues):
        return GithubTracker("o/r", FakeRun(issues)).ready()

    def test_labelled_open_unblocked_issue_is_ready(self):
        self.assertEqual(self.ready([issue(1)]), [1])

    def test_unlabelled_issue_is_not_ready(self):
        self.assertEqual(self.ready([issue(1, labels=())]), [])

    def test_human_labelled_issue_is_not_ready(self):
        self.assertEqual(self.ready([issue(1, labels=("ready-for-human",))]), [])

    def test_closed_issue_is_not_ready(self):
        self.assertEqual(self.ready([issue(1, state="CLOSED")]), [])

    def test_in_progress_issue_is_not_ready(self):
        self.assertEqual(self.ready([issue(1, labels=("ready-for-agent", "in-progress"))]), [])

    def test_open_blocker_holds_an_issue_back(self):
        self.assertEqual(self.ready([issue(1), issue(2, blocked=["- Blocked by #1"])]), [1])

    def test_closed_blocker_releases_an_issue(self):
        self.assertEqual(self.ready([issue(1, state="CLOSED"), issue(2, blocked=["- Blocked by #1"])]), [2])

    def test_all_blockers_must_be_closed(self):
        issues = [issue(1, state="CLOSED"), issue(2), issue(3, blocked=["- #1", "- #2"])]
        self.assertEqual(self.ready(issues), [2])

    def test_unknown_or_malformed_blocker_keeps_issue_out(self):
        self.assertEqual(self.ready([issue(1, blocked=["- #404"])]), [])
        self.assertEqual(self.ready([issue(1, blocked=["- Blocked by the cache"])]), [])

    def test_a_ready_label_can_be_chosen(self):
        t = GithubTracker("o/r", FakeRun([issue(1, labels=("agent-ok",))]), ready_label="agent-ok")
        self.assertEqual(t.ready(), [1])

    def test_a_parent_issue_is_an_epic_not_a_ticket(self):
        child = issue(2)
        child["body"] = "## Parent\n\n#1\n\n" + child["body"]
        self.assertEqual(self.ready([issue(1), child]), [2])

    def test_parent_exclusion_ignores_other_sections(self):
        other = issue(2)
        other["body"] = "## What to build\n\nsee #1\n\n" + other["body"]
        self.assertEqual(self.ready([issue(1), other]), [1, 2])

    def test_a_closed_child_still_makes_its_parent_an_epic(self):
        child = issue(2, state="CLOSED")
        child["body"] = "## Parent\n\n#1\n"
        self.assertEqual(self.ready([issue(1), child]), [])

    def test_sorted_by_number(self):
        self.assertEqual(self.ready([issue(5), issue(2), issue(9)]), [2, 5, 9])


class CheckTest(unittest.TestCase):
    def check(self, issues):
        return GithubTracker("o/r", FakeRun(issues)).check()

    def test_clean_graph_has_no_problems(self):
        self.assertEqual(self.check([issue(1), issue(2, blocked=["- #1"])]), [])

    def test_unknown_blocker_is_reported(self):
        (p,) = self.check([issue(1, blocked=["- #404"])])
        self.assertIn("#1", p)
        self.assertIn("#404", p)

    def test_self_blocker_is_reported(self):
        (p,) = self.check([issue(1, blocked=["- #1"])])
        self.assertIn("itself", p)

    def test_malformed_blocker_is_reported(self):
        (p,) = self.check([issue(1, blocked=["- Blocked by the cache slice"])])
        self.assertIn("cache slice", p)

    def test_only_ready_labelled_open_issues_are_checked(self):
        self.assertEqual(self.check([issue(1, labels=(), blocked=["- #404"]),
                                     issue(2, state="CLOSED", blocked=["- #404"])]), [])


class ErrorsTest(unittest.TestCase):
    def test_failed_listing_is_an_error_not_an_empty_frontier(self):
        with self.assertRaises(TrackerError):
            GithubTracker("o/r", FakeRun(listing=(1, "gh: not logged in"))).ready()

    def test_unparsable_listing_is_an_error(self):
        with self.assertRaises(TrackerError):
            GithubTracker("o/r", FakeRun(listing=(0, "<html>"))).ready()


class GhBinTest(unittest.TestCase):
    def test_gh_bin_replaces_the_gh_executable_and_may_carry_arguments(self):
        import os
        import sys
        from unittest import mock
        exe = sys.executable.replace("\\", "/")
        fake = f'{exe} -c "import sys; print(\'|\'.join(sys.argv[1:]))"'
        with mock.patch.dict(os.environ, {"GH_BIN": fake}):
            self.assertEqual(gh_tracker.default_run(["gh", "issue", "list"]), (0, "issue|list\n"))

    def test_missing_executable_is_a_tracker_error(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"GH_BIN": "definitely-not-a-tool"}):
            with self.assertRaisesRegex(TrackerError, "definitely-not-a-tool"):
                gh_tracker.default_run(["gh", "issue", "list"])


class CliTest(unittest.TestCase):
    def test_ready_prints_one_number_per_line(self):
        out = []
        code = gh_tracker.main(["ready", "--repo", "o/r"], run=FakeRun([issue(3), issue(1)]), out=out.append)
        self.assertEqual((code, out), (0, ["1", "3"]))

    def test_check_exits_1_and_prints_problems(self):
        out = []
        code = gh_tracker.main(["check", "--repo", "o/r"], run=FakeRun([issue(1, blocked=["- #404"])]), out=out.append)
        self.assertEqual(code, 1)
        self.assertIn("#404", out[0])

    def test_check_exits_0_when_clean(self):
        self.assertEqual(gh_tracker.main(["check", "--repo", "o/r"], run=FakeRun([issue(1)]), out=lambda s: None), 0)

    def test_error_exits_2_with_message(self):
        out = []
        code = gh_tracker.main(["ready", "--repo", "o/r"], run=FakeRun(listing=(1, "boom")), out=out.append)
        self.assertEqual(code, 2)
        self.assertIn("boom", out[0])


if __name__ == "__main__":
    unittest.main()
