import unittest

from tracker import gh_tracker
from tracker.gh_tracker import GithubTracker, TrackerError, issue_number


class Recorder:
    def __init__(self, fail=None, out=""):
        self.calls, self.fail, self.out = [], fail, out

    def __call__(self, cmd):
        line = " ".join(cmd)
        self.calls.append(line)
        if self.fail and self.fail in line:
            return 1, "gh: boom"
        return 0, self.out


def tracker(**kw):
    r = Recorder(**kw)
    return GithubTracker("o/r", r), r


class NumberTest(unittest.TestCase):
    def test_accepts_loop_ids_and_hash_forms(self):
        self.assertEqual([issue_number(x) for x in ("12", "gh-12", "#12", 12)], [12] * 4)

    def test_rejects_anything_else(self):
        for bad in ("gv-12", "", "x", "gh-", "-1"):
            with self.assertRaises(TrackerError):
                issue_number(bad)


class ActionsTest(unittest.TestCase):
    def test_claim_adds_in_progress(self):
        t, r = tracker()
        t.claim(5)
        self.assertEqual(r.calls, ["gh issue edit 5 --repo o/r --add-label in-progress"])

    def test_reopen_removes_in_progress(self):
        t, r = tracker()
        t.status(5, "open")
        self.assertEqual(r.calls, ["gh issue edit 5 --repo o/r --remove-label in-progress"])

    def test_blocked_hands_the_issue_to_a_human(self):
        t, r = tracker()
        t.status(5, "blocked")
        self.assertEqual(r.calls, ["gh issue edit 5 --repo o/r --remove-label ready-for-agent "
                                   "--remove-label in-progress --add-label ready-for-human"])

    def test_blocked_uses_the_configured_ready_label(self):
        r = Recorder()
        GithubTracker("o/r", r, ready_label="agent-ok").status(5, "blocked")
        self.assertIn("--remove-label agent-ok", r.calls[0])

    def test_in_progress_status_is_a_claim(self):
        t, r = tracker()
        t.status(5, "in_progress")
        self.assertEqual(r.calls, ["gh issue edit 5 --repo o/r --add-label in-progress"])

    def test_unknown_status_is_an_error(self):
        t, r = tracker()
        with self.assertRaises(TrackerError):
            t.status(5, "weird")
        self.assertEqual(r.calls, [])

    def test_close_clears_the_label_then_closes_as_completed(self):
        t, r = tracker()
        t.close(5)
        self.assertEqual(r.calls, ["gh issue edit 5 --repo o/r --remove-label in-progress",
                                   "gh issue close 5 --repo o/r --reason completed"])

    def test_close_with_a_comment(self):
        t, r = tracker()
        t.close(5, comment="Merged in abc123")
        self.assertEqual(r.calls[1], "gh issue close 5 --repo o/r --reason completed --comment Merged in abc123")

    def test_note_is_an_issue_comment(self):
        t, r = tracker()
        t.note(5, "what changed")
        self.assertEqual(r.calls, ["gh issue comment 5 --repo o/r --body what changed"])

    def test_title(self):
        t, r = tracker(out="Lock and unlock pushing\n")
        self.assertEqual(t.title(5), "Lock and unlock pushing")
        self.assertEqual(r.calls, ["gh issue view 5 --repo o/r --json title --jq .title"])

    def test_ensure_labels_creates_the_loop_labels_idempotently(self):
        t, r = tracker()
        t.ensure_labels()
        self.assertEqual(len(r.calls), 2)
        self.assertTrue(all("gh label create" in c and "--force" in c for c in r.calls))
        self.assertTrue(any(" in-progress " in c + " " for c in r.calls))
        self.assertTrue(any(" ready-for-human " in c + " " for c in r.calls))

    def test_failed_gh_call_is_an_error_naming_the_reason(self):
        t, _ = tracker(fail="issue edit")
        for call in (lambda: t.claim(5), lambda: t.status(5, "open"), lambda: t.close(5)):
            with self.assertRaisesRegex(TrackerError, "boom"):
                call()

    def test_failed_close_does_not_leave_a_half_closed_issue_silently(self):
        t, r = tracker(fail="issue close")
        with self.assertRaises(TrackerError):
            t.close(5)


class CliActionsTest(unittest.TestCase):
    def run_cli(self, *argv, **kw):
        r = Recorder(**kw)
        out = []
        code = gh_tracker.main([*argv, "--repo", "o/r"], run=r, out=out.append)
        return code, out, r

    def test_claim_accepts_a_loop_id(self):
        code, _, r = self.run_cli("claim", "gh-7")
        self.assertEqual((code, r.calls), (0, ["gh issue edit 7 --repo o/r --add-label in-progress"]))

    def test_note_posts_a_comment(self):
        code, _, r = self.run_cli("note", "7", "--body", "hello")
        self.assertEqual((code, r.calls), (0, ["gh issue comment 7 --repo o/r --body hello"]))

    def test_note_never_aborts_the_loop(self):
        code, out, _ = self.run_cli("note", "7", "--body", "hello", fail="issue comment")
        self.assertEqual(code, 0)
        self.assertIn("boom", out[0])

    def test_status_and_close_and_title(self):
        self.assertEqual(self.run_cli("status", "7", "blocked")[0], 0)
        self.assertEqual(self.run_cli("close", "7", "--comment", "done")[0], 0)
        code, out, _ = self.run_cli("title", "7", out="Hello\n")
        self.assertEqual((code, out), (0, ["Hello"]))

    def test_failure_exits_2_with_the_reason(self):
        code, out, _ = self.run_cli("claim", "7", fail="issue edit")
        self.assertEqual(code, 2)
        self.assertIn("boom", out[0])

    def test_bad_id_exits_2(self):
        self.assertEqual(self.run_cli("claim", "gv-7")[0], 2)

    def test_setup_creates_labels(self):
        code, _, r = self.run_cli("setup")
        self.assertEqual((code, len(r.calls)), (0, 2))


if __name__ == "__main__":
    unittest.main()
