#!/usr/bin/env bash
# agent-loop.sh: run one fresh agent per ready ticket, gated by ci.sh, until a limit is hit.
#
# Run from the root of the project repo.
#
# Environment (all optional):
#   MAX_TICKETS=5        stop after this many tickets attempted
#   MAX_HOURS=4          stop after this much wall-clock time
#   MAX_COST_USD=30      stop when cumulative reported cost reaches this
#   PER_RUN_TURNS=80     --max-turns for each agent run
#   MAX_FAILS=2          failures on one ticket before it is marked blocked
#   AGENT=claude         claude | opencode
#   MAIN_BRANCH=main      the long-running integration branch every ticket merges into (e.g. MAIN_BRANCH=factory)
#   CI_CMD=./ci.sh
#   PROMPT_FILE=PROMPT.md  (falls back to the kit's templates/PROMPT.md)
#   WORKTREE_DIR=.worktrees
#   ALLOWED_TOOLS="..."   tools the agent may use without prompting (see the default in this file)
#   READY_LABEL=agent-ok  only tickets with this label are picked up (human-only tickets are skipped)
#   ALLOW_REMOTE=1       run in a repo with a live push remote (agents still cannot push)
#   KIT_DIR              path to agent-factory-kit (auto-detected)
set -euo pipefail

# Find a working Python. The Windows Store "python3" stub exists but fails, so test each candidate.
PYCMD=()
for c in python3 python "py -3"; do
  # shellcheck disable=SC2086
  if $c -c 'import sys' >/dev/null 2>&1; then read -r -a PYCMD <<<"$c"; break; fi
done
[[ ${#PYCMD[@]} -gt 0 ]] || { echo "No working Python found (tried python3, python, py -3)." >&2; exit 1; }
py() { "${PYCMD[@]}" "$@"; }

MAX_TICKETS="${MAX_TICKETS:-5}"
MAX_HOURS="${MAX_HOURS:-4}"
MAX_COST_USD="${MAX_COST_USD:-30}"
PER_RUN_TURNS="${PER_RUN_TURNS:-80}"
MAX_FAILS="${MAX_FAILS:-2}"
AGENT="${AGENT:-claude}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
# Passed on the command line because Claude Code ignores a project's permissions.allow until the
# folder is trusted. Deliberately no "Bash(bash:*)": that would let the agent run anything.
ALLOWED_TOOLS="${ALLOWED_TOOLS:-Bash(./ci.sh:*) Bash(git add:*) Bash(git commit:*) Bash(git status:*) Bash(git diff:*) Bash(git log:*) Bash(bd:*) Bash(ls:*) Bash(cat:*) Bash(mkdir:*)}"
CI_CMD="${CI_CMD:-./ci.sh}"
WORKTREE_DIR="${WORKTREE_DIR:-.worktrees}"
KIT_DIR="${KIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROMPT_FILE="${PROMPT_FILE:-PROMPT.md}"
[[ -f "$PROMPT_FILE" ]] || PROMPT_FILE="$KIT_DIR/templates/PROMPT.md"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
git rev-parse --verify -q "$MAIN_BRANCH" >/dev/null || { echo "Branch $MAIN_BRANCH does not exist. Create it first (git branch $MAIN_BRANCH)." >&2; exit 1; }
LOG_DIR=".agent/loop"
mkdir -p "$LOG_DIR" ".agent/time" "$WORKTREE_DIR"
# Worktrees do not contain the git-ignored .beads store, so point bd at the main repo's.
[[ -d "$REPO_ROOT/.beads" ]] && export BEADS_DIR="$REPO_ROOT/.beads"
RUN_LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$RUN_LOG"; }

# ---- tracker adapter (beads). Edit these four to use another tracker. ----
tracker_next()    { bd ready --label "${READY_LABEL:-agent-ok}" --json 2>/dev/null | py -c 'import json,sys
d=json.load(sys.stdin)
items=d if isinstance(d,list) else d.get("issues",d.get("items",[]))
print(items[0]["id"] if items else "")'; }
tracker_claim()   { bd update "$1" --claim >/dev/null; }
tracker_note()    { bd comments add "$1" "$2" >/dev/null 2>&1 || true; }
tracker_status()  { bd update "$1" --status "$2" >/dev/null; }
tracker_close()   { bd close "$1" >/dev/null; }
tracker_title()   { bd show "$1" --json 2>/dev/null | py -c 'import json,sys
d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d
print(d.get("title",""))' || true; }
# --------------------------------------------------------------------------

# Refuse to run if this repo can push anywhere.
if [[ "${ALLOW_REMOTE:-0}" != 1 ]] && git remote -v | grep '(push)' | grep -vq 'DISABLED'; then
  log "Refusing to run: a remote has a live push URL. Run $KIT_DIR/bin/lockdown-remote.sh first, or set ALLOW_REMOTE=1 for a repo you intend to push."
  exit 1
fi
[[ -x "${CI_CMD%% *}" ]] || { log "CI command not found or not executable: $CI_CMD"; exit 1; }
git diff --quiet && git diff --cached --quiet || { log "Working tree is dirty. Commit or stash first."; exit 1; }

run_agent() {  # $1 ticket, $2 worktree path; prints cost in USD on stdout
  local id="$1" wt="$2" out="$LOG_DIR/$1-$(date +%H%M%S).json"
  local prompt; prompt="$(cat "$PROMPT_FILE")"$'\n\n'"Ticket: $id"
  mkdir -p "$wt/.agent" && echo "$id" > "$wt/.agent/current-ticket"
  case "$AGENT" in
    claude)
      ( cd "$wt" && claude -p "$prompt" \
          --output-format json \
          --max-turns "$PER_RUN_TURNS" \
          --permission-mode acceptEdits \
          --allowedTools "$ALLOWED_TOOLS" \
          --disallowedTools "Bash(git push:*)" ) > "$out" 2>>"$RUN_LOG" || true
      py -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("total_cost_usd",0) or 0)
except Exception: print(0)' "$out"
      ;;
    opencode)
      ( cd "$wt" && opencode run "$prompt" ) > "$out" 2>>"$RUN_LOG" || true
      echo 0   # OpenCode cost is not parsed; rely on MAX_TICKETS / MAX_HOURS
      ;;
    *) log "Unknown AGENT=$AGENT"; exit 1 ;;
  esac
}

declare -A FAILS=()
start=$(date +%s); attempted=0; done_count=0; cost_total=0

while :; do
  elapsed_h=$(py -c "print(($(date +%s)-$start)/3600)")
  if (( attempted >= MAX_TICKETS )); then log "Stop: ticket limit ($MAX_TICKETS)."; break; fi
  if py -c "import sys; sys.exit(0 if $elapsed_h >= $MAX_HOURS else 1)"; then log "Stop: time limit (${MAX_HOURS}h)."; break; fi
  if py -c "import sys; sys.exit(0 if $cost_total >= $MAX_COST_USD else 1)"; then log "Stop: cost limit (\$$MAX_COST_USD)."; break; fi

  id="$(tracker_next)"
  [[ -z "$id" ]] && { log "Stop: no ready tickets."; break; }
  attempted=$((attempted+1))
  tracker_claim "$id"
  log "[$id] claimed (attempt ${FAILS[$id]:-0}+1)"

  branch="agent/$id"
  wt="$WORKTREE_DIR/$id"
  git worktree remove --force "$wt" 2>/dev/null || true
  git branch -D "$branch" 2>/dev/null || true
  git worktree add -q -b "$branch" "$wt" "$MAIN_BRANCH"

  cost="$(run_agent "$id" "$wt")"
  cost_total=$(py -c "print(round($cost_total + ${cost:-0}, 4))")
  log "[$id] agent finished, run cost \$${cost:-0}, total \$$cost_total"

  # Commit anything the agent left uncommitted.
  ( cd "$wt" && git add -A && git diff --cached --quiet || git commit -qm "$id: agent work (auto-commit)" ) || true

  fail() {
    FAILS[$id]=$(( ${FAILS[$id]:-0} + 1 ))
    tracker_note "$id" "agent-loop: $1 (failure ${FAILS[$id]}/$MAX_FAILS). Log: $RUN_LOG"
    if (( FAILS[$id] >= MAX_FAILS )); then tracker_status "$id" blocked; log "[$id] blocked: $1"
    else tracker_status "$id" open; log "[$id] reopened: $1"; fi
  }

  if [[ "$(git -C "$wt" rev-list --count "$MAIN_BRANCH..HEAD")" == 0 ]]; then
    fail "agent made no commits (see $LOG_DIR/ for its output)"
  elif ! ( cd "$wt" && $CI_CMD ) >>"$RUN_LOG" 2>&1; then
    fail "ci.sh failed on branch"
  else
    git checkout -q "$MAIN_BRANCH"
    pre_merge=$(git rev-parse HEAD)
    title="$(tracker_title "$id")"
    if ! git merge -q --no-ff "$branch" -m "Merge $id: ${title:-ticket}" -m "Ticket: $id"$'
'"CI: ci.sh passed on branch and after merge" >>"$RUN_LOG" 2>&1; then
      git merge --abort 2>/dev/null || true
      fail "merge conflict with $MAIN_BRANCH"
    elif ! $CI_CMD >>"$RUN_LOG" 2>&1; then
      git reset -q --hard "$pre_merge"
      fail "ci.sh failed after merge"
    else
      tracker_close "$id"
      done_count=$((done_count+1))
      log "[$id] merged and closed"
    fi
  fi

  py "$KIT_DIR/bin/time-rollup.py" --time-dir "$wt/.agent/time" --ticket "$id" --write-bd >>"$RUN_LOG" 2>&1 || true
  git worktree remove --force "$wt" 2>/dev/null || true
done

log "Summary: $done_count closed, $attempted attempted, \$$cost_total spent. Log: $RUN_LOG"
