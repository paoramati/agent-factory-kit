#!/usr/bin/env bash
# loop-test-github.sh: run agent-loop.sh with TRACKER=github against a throwaway repo, a fake agent and a
# fake gh. Same scenarios as loop-test.sh (parallel tickets, a conflict, a dependency, a retry), plus an
# epic that must be skipped, a ticket that keeps failing (handed to a human), and a bad blocker.
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYBIN=""; for c in python3 python; do $c -c 'import sys' >/dev/null 2>&1 && { PYBIN="$c"; break; }; done
[[ -n "$PYBIN" ]] || { echo "No working Python found" >&2; exit 1; }
win() { cygpath -m "$1" 2>/dev/null || echo "$1"; }   # forward-slash native path (identity off Windows)

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cd "$T"
git init -q -b factory; git config user.email test@example.com; git config user.name test; git config core.autocrlf false
printf '#!/usr/bin/env bash\n[[ ! -e BAD ]]\n' > ci.sh; chmod +x ci.sh
echo base > shared.txt; printf '.worktrees/\n.agent/\n' > .gitignore
git add -A; git commit -qm base

export FAKE_GH_STATE="$(win "$T")/gh-state.json"
export GH_BIN="$PYBIN $(win "$KIT")/tests/fake-gh.py"
export TRACKER=github TRACKER_REPO=o/r

mkstate() {  # $1 = python expression building the issue list
  $PYBIN - "$FAKE_GH_STATE" <<EOF
import json, sys
def iss(n, title, labels=("ready-for-agent",), parent=None, blocked=None):
    body = ("## Parent\n\n#%d\n\n" % parent if parent else "") + "## Blocked by\n\n" + (
        "\n".join("- Blocked by #%d" % b for b in blocked) if blocked else "None - can start immediately") + "\n"
    return {"number": n, "title": title, "state": "OPEN", "labels": list(labels), "body": body, "comments": []}
issues = $1
json.dump({"issues": issues, "labels": []}, open(sys.argv[1], "w"))
EOF
}
fail() { cat "${LOOPOUT:-/dev/null}" 2>/dev/null; echo "FAIL: $*"; exit 1; }
state() { $PYBIN -c "import json,sys; st=json.load(open(sys.argv[1])); i=next(i for i in st['issues'] if i['number']==int(sys.argv[2])); print($1)" "$FAKE_GH_STATE" "$2" | tr -d '\r'; }

export CLAUDE_BIN="$KIT/tests/fake-claude.sh" MAIN_BRANCH=factory FAKE_ARGS_LOG="$T/agent-args.txt"
export MAX_PARALLEL=2 MAX_TICKETS=10 MAX_COST_USD=5 ALLOW_REMOTE=1

# ---- 1. preflight refuses a ready issue with a blocker that does not exist ------------------------------
mkstate 'iss(1, "Bad blocker", blocked=[404]),'
echo "gh-1 gh-2 gh-3 gh-4 gh-6" > "$T/roles.txt"; export FAKE_ROLES="$T/roles.txt"
LOOPOUT="$T/bad.out"
if "$KIT/bin/agent-loop.sh" > "$LOOPOUT" 2>&1; then fail "loop ran despite a bad blocker"; fi
grep -q "404" "$LOOPOUT" || fail "preflight did not name the bad blocker"
[[ "$(state "i['state']" 1)" == OPEN && "$(git branch --list 'agent/*' | wc -l | tr -d ' ')" == 0 ]] || fail "work started despite the bad blocker"
rm -rf .agent

# ---- 2. the full loop ---------------------------------------------------------------------------------------
mkstate '[iss(5, "Epic PRD"), iss(1, "Ticket A", parent=5), iss(2, "Ticket B", parent=5),
          iss(3, "Ticket C needs A and B", parent=5, blocked=[1, 2]), iss(4, "Ticket E gate fails once", parent=5),
          iss(6, "Ticket F always fails", parent=5)]'
LOOPOUT="$T/loop.out"
"$KIT/bin/agent-loop.sh" > "$LOOPOUT" 2>&1 || fail "loop exited non-zero"

for n in 1 2 3 4; do
  [[ "$(state "i['state']" $n)" == CLOSED ]] || fail "issue #$n was not closed"
  [[ "$(state "'in-progress' in i['labels']" $n)" == False ]] || fail "issue #$n still in-progress"
  git log factory --merges --format=%s | grep -q "^Merge gh-$n: " || fail "no 'Merge gh-$n: <title>' commit on factory"
  [[ "$(state "any('Merged into factory' in c for c in i['comments'])" $n)" == True ]] || fail "issue #$n has no merge comment"
done
[[ "$(state "i['state']" 5)" == OPEN && ! -e file-gh-5.txt && -z "$(git branch --list agent/gh-5)" ]] || fail "the epic was treated as a ticket"
[[ "$(cat shared.txt)" == *"line from A"* && "$(cat shared.txt)" == *"line from B"* ]] || fail "shared.txt lost a side of the conflict"
[[ -f file-gh-3.txt ]] || fail "dependent ticket gh-3 was not built"
grep -q "attempt 2" "$LOOPOUT" || fail "ticket gh-4 never got a second attempt"
[[ "$(state "i['state']" 6)" == OPEN ]] || fail "failing ticket was closed"
[[ "$(state "'ready-for-human' in i['labels'] and 'ready-for-agent' not in i['labels'] and 'in-progress' not in i['labels']" 6)" == True ]] \
  || fail "ticket that failed twice was not handed to a human"
[[ "$(state "len(i['comments'])" 6)" -ge 2 ]] || fail "failure notes were not posted on issue #6"
[[ -z "$(git worktree list | grep '.worktrees')" ]] || fail "worktrees were left behind"

# agents may only view and comment on issues
tools="$(grep -o -- '--allowedTools.*' "$FAKE_ARGS_LOG" | head -1)"
[[ "$tools" == *"Bash(gh issue view:*)"* && "$tools" == *"Bash(gh issue comment:*)"* ]] || fail "allow-list lacks gh issue view/comment"
[[ "$tools" != *"Bash(gh:*)"* && "$tools" != *"Bash(bd:*)"* && "$tools" != *"gh issue close"* && "$tools" != *"gh issue edit"* ]] || fail "allow-list is too wide: $tools"
grep -q 'gh issue view 1 --comments' "$FAKE_ARGS_LOG" || fail "the prompt does not tell the agent how to read the issue"

echo "loop-test-github: ok (4 closed, epic skipped, conflict resolved, retry from branch, failing ticket handed to a human)"
