#!/usr/bin/env bash
# loop-test.sh: run agent-loop.sh against a throwaway repo with a fake agent and check the outcome.
# Covers: parallel tickets, a merge conflict an agent resolves, a dependent ticket waiting for its
# blockers, and a ticket that fails the gate once and passes on attempt 2 from its own branch.
set -euo pipefail
command -v bd >/dev/null 2>&1 || { echo "skip: bd is not installed"; exit 0; }
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYBIN=""; for c in python3 python; do $c -c 'import sys' >/dev/null 2>&1 && { PYBIN="$c"; break; }; done
[[ -n "$PYBIN" ]] || { echo "No working Python found" >&2; exit 1; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
unset BEADS_DIR
cd "$T"
git init -q -b factory; git config user.email test@example.com; git config user.name test; git config core.autocrlf false
printf '#!/usr/bin/env bash\n[[ ! -e BAD ]]\n' > ci.sh; chmod +x ci.sh
echo base > shared.txt; printf '.worktrees/\n.agent/\n' > .gitignore
git add -A; git commit -qm base
BD_NON_INTERACTIVE=1 bd init --stealth --prefix t >/dev/null 2>&1

mk() { bd create "$1" -t task -p 1 2>&1 | grep -o 't-[a-z0-9]*' | head -1 | tr -d '\r'; }
a=$(mk "Ticket A"); b=$(mk "Ticket B"); c=$(mk "Ticket C needs A and B"); e=$(mk "Ticket E gate fails once")
for i in "$a" "$b" "$c" "$e"; do bd label add "$i" agent-ok >/dev/null; done
bd dep add "$c" "$a" >/dev/null; bd dep add "$c" "$b" >/dev/null
echo "$a $b $c $e" > "$T/roles.txt"

export FAKE_ROLES="$T/roles.txt" CLAUDE_BIN="$KIT/tests/fake-claude.sh" MAIN_BRANCH=factory
export MAX_PARALLEL=2 MAX_TICKETS=10 MAX_COST_USD=5 ALLOW_REMOTE=1 BD_NO_REMOTE_ADOPT=1
"$KIT/bin/agent-loop.sh" > "$T/loop.out" 2>&1 || { cat "$T/loop.out"; echo "FAIL: loop exited non-zero"; exit 1; }

fail() { cat "$T/loop.out"; echo "FAIL: $*"; exit 1; }
closed="$(bd list --all --json 2>/dev/null | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(sum(1 for i in d if i.get("status")=="closed"))' | tr -d '\r')"
[[ "$closed" == 4 ]] || fail "expected 4 closed tickets, got $closed"
for i in "$a" "$b" "$c" "$e"; do
  git log factory --merges --format=%s | grep -q "^Merge $i: " || fail "no merge commit for $i on factory"
done
[[ "$(cat shared.txt)" == *"line from A"* && "$(cat shared.txt)" == *"line from B"* ]] || fail "shared.txt lost a side of the conflict"
[[ -f "file-$c.txt" ]] || fail "dependent ticket $c was not built"
[[ -z "$(git worktree list | grep '.worktrees')" ]] || fail "worktrees were left behind"
grep -q "attempt 2" "$T/loop.out" || fail "ticket $e never got a second attempt"
echo "loop-test: ok (4 closed, conflict resolved, retry from branch)"
