#!/usr/bin/env bash
# agent-loop.sh: run fresh agents over the ready tickets, gated by ci.sh, until a limit is hit.
#
# Run from the root of the project repo.
#
# How it works
#   * The frontier (ready, unblocked, agent-ok tickets) is read from the tracker. Up to MAX_PARALLEL
#     tickets run at once, each in its own worktree on its own branch agent/<id>.
#   * Independence comes from the ticket graph: a ticket is only ready when its blockers are done.
#   * Each worker: agent builds the ticket -> merges the latest integration branch into its branch
#     (an agent resolves any conflicts) -> runs the gate. Only this process merges into the
#     integration branch, one ticket at a time, and runs the gate again on the result.
#   * A gate failure with commits keeps the ticket branch; the next attempt continues from it with the
#     gate output in its prompt. An attempt that commits nothing starts fresh.
#
# Environment (all optional):
#   MAX_TICKETS=5        stop after this many ticket attempts started
#   MAX_PARALLEL=2       tickets worked at once
#   MAX_HOURS=4          stop starting work after this much wall-clock time
#   MAX_COST_USD=30      stop starting work when cumulative reported cost reaches this
#                        (tickets already running finish, so the total can overshoot)
#   PER_RUN_TURNS=80     --max-turns for each agent session
#   MAX_FAILS=2          failures on one ticket before it is marked blocked
#   AGENT=claude         claude | opencode
#   MAIN_BRANCH=main     the long-running integration branch (e.g. MAIN_BRANCH=factory)
#   CI_CMD=./ci.sh       the gate
#   PROMPT_FILE=PROMPT.md  (falls back to the kit's templates/PROMPT.md)
#   WORKTREE_DIR=.worktrees
#   ALLOWED_TOOLS="..."  tools the agent may use without prompting (see the default below)
#   READY_LABEL=agent-ok only tickets with this label are picked up (human-only tickets are skipped)
#   ALLOW_REMOTE=1       run in a repo with a live push remote (agents still cannot push)
#   CLAUDE_BIN=claude    the agent command (override for testing)
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
MAX_PARALLEL="${MAX_PARALLEL:-2}"
MAX_HOURS="${MAX_HOURS:-4}"
MAX_COST_USD="${MAX_COST_USD:-30}"
PER_RUN_TURNS="${PER_RUN_TURNS:-80}"
MAX_FAILS="${MAX_FAILS:-2}"
AGENT="${AGENT:-claude}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
# Passed on the command line because Claude Code ignores a project's permissions.allow until the
# folder is trusted. Deliberately no "Bash(bash:*)": that would let the agent run anything.
ALLOWED_TOOLS="${ALLOWED_TOOLS:-Skill Bash(./ci.sh:*) Bash(git add:*) Bash(git commit:*) Bash(git merge:*) Bash(git status:*) Bash(git diff:*) Bash(git log:*) Bash(bd:*) Bash(ls:*) Bash(cat:*) Bash(mkdir:*)}"
CI_CMD="${CI_CMD:-./ci.sh}"
WORKTREE_DIR="${WORKTREE_DIR:-.worktrees}"
KIT_DIR="${KIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROMPT_FILE="${PROMPT_FILE:-PROMPT.md}"
[[ -f "$PROMPT_FILE" ]] || PROMPT_FILE="$KIT_DIR/templates/PROMPT.md"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
git rev-parse --verify -q "$MAIN_BRANCH" >/dev/null || { echo "Branch $MAIN_BRANCH does not exist. Create it first (git branch $MAIN_BRANCH)." >&2; exit 1; }
LOG_DIR=".agent/loop"
STATE_DIR="$LOG_DIR/state"
mkdir -p "$LOG_DIR" "$STATE_DIR" ".agent/time" "$WORKTREE_DIR"
rm -f "$STATE_DIR"/*.result "$STATE_DIR"/*.cost 2>/dev/null || true
# Worktrees do not contain the git-ignored .beads store, so point bd at the main repo's.
[[ -d "$REPO_ROOT/.beads" ]] && export BEADS_DIR="$REPO_ROOT/.beads"
RUN_LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$RUN_LOG"; }

# ---- tracker adapter (beads). Edit these to use another tracker. ----------
tracker_ready()   { bd ready --label "${READY_LABEL:-agent-ok}" --json 2>/dev/null | py -c 'import json,sys
d=json.load(sys.stdin)
items=d if isinstance(d,list) else d.get("issues",d.get("items",[]))
print("\n".join(i["id"] for i in items))' | tr -d '\r' || true; }
tracker_claim()   { bd update "$1" --claim >/dev/null; }
tracker_note()    { bd comments add "$1" "$2" >/dev/null 2>&1 || true; }
tracker_status()  { bd update "$1" --status "$2" >/dev/null; }
tracker_close()   { bd close "$1" >/dev/null; }
tracker_title()   { bd show "$1" --json 2>/dev/null | py -c 'import json,sys
d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d
print(d.get("title",""))' | tr -d '\r' || true; }
# ---------------------------------------------------------------------------

# Refuse to run if this repo can push anywhere.
if [[ "${ALLOW_REMOTE:-0}" != 1 ]] && git remote -v | grep '(push)' | grep -vq 'DISABLED'; then
  log "Refusing to run: a remote has a live push URL. Run $KIT_DIR/bin/lockdown-remote.sh first, or set ALLOW_REMOTE=1 for a repo you intend to push."
  exit 1
fi
[[ -x "${CI_CMD%% *}" ]] || { log "CI command not found or not executable: $CI_CMD"; exit 1; }
git diff --quiet && git diff --cached --quiet || { log "Working tree is dirty. Commit or stash first."; exit 1; }
git checkout -q "$MAIN_BRANCH"

declare -A PIDS=() FAILS=() REQUEUES=()

# Whether the next attempt on a ticket continues from its branch is kept in a file, so it survives
# a restart of the loop.
keep_get() { [[ -f "$STATE_DIR/$1.keep" ]]; }
keep_set() { if [[ "$2" == 1 ]]; then : > "$STATE_DIR/$1.keep"; else rm -f "$STATE_DIR/$1.keep"; fi; }

build_prompt() {  # $1 ticket, $2 work|resolve, $3 worktree
  local id="$1" kind="$2" wt="$3" out
  case "$kind" in
    work)
      out="$(cat "$PROMPT_FILE")"$'\n\n'"Ticket: $id"
      if keep_get "$id"; then
        out+=$'\n\n'"This is a continuation. Your previous attempt is already committed on this branch and failed the gate. Fix it; do not start over. The gate output (last 60 lines):"$'\n'"$(tail -n 60 "$STATE_DIR/$id.gate.log" 2>/dev/null || true)"
      fi ;;
    resolve)
      out="Ticket: $id. Merging the latest $MAIN_BRANCH into this branch left conflicts. Resolve every conflict keeping the intent of both sides, run $CI_CMD until it passes, then commit the merge. Do not push. Conflicted files:"$'\n'"$(git -C "$wt" diff --name-only --diff-filter=U)" ;;
  esac
  printf '%s' "$out"
}

run_agent() {  # $1 ticket, $2 worktree, $3 work|resolve; appends the run cost (USD) to the ticket's cost file
  local id="$1" wt="$2" kind="$3" out="$LOG_DIR/$1-$3-$(date +%H%M%S).json" prompt
  prompt="$(build_prompt "$id" "$kind" "$wt")"
  mkdir -p "$wt/.agent" && echo "$id" > "$wt/.agent/current-ticket"
  case "$AGENT" in
    claude)
      ( cd "$wt" && "$CLAUDE_BIN" -p "$prompt" \
          --output-format json \
          --max-turns "$PER_RUN_TURNS" \
          --permission-mode acceptEdits \
          --allowedTools "$ALLOWED_TOOLS" \
          --disallowedTools "Bash(git push:*)" < /dev/null ) > "$out" 2>>"$RUN_LOG" || true
      py -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("total_cost_usd",0) or 0)
except Exception: print(0)' "$out" >> "$STATE_DIR/$id.cost"
      ;;
    opencode)
      ( cd "$wt" && opencode run "$prompt" < /dev/null ) > "$out" 2>>"$RUN_LOG" || true
      echo 0 >> "$STATE_DIR/$id.cost"   # OpenCode cost is not parsed; rely on MAX_TICKETS / MAX_HOURS
      ;;
    *) log "Unknown AGENT=$AGENT"; exit 1 ;;
  esac
}

# Runs in a background subshell. Leaves its verdict in $STATE_DIR/<id>.result:
# ok | noop | unresolved | cifail | error
worker() {
  local id="$1" wt="$WORKTREE_DIR/$1" branch="agent/$1" res="$STATE_DIR/$1.result"
  set +e
  : > "$STATE_DIR/$id.cost"
  git worktree remove --force "$wt" 2>/dev/null
  if keep_get "$id" && git rev-parse --verify -q "$branch" >/dev/null; then
    git worktree add -q "$wt" "$branch" >>"$RUN_LOG" 2>&1 || { echo error > "$res"; return; }
  else
    git branch -D "$branch" 2>/dev/null
    git worktree add -q -b "$branch" "$wt" "$MAIN_BRANCH" >>"$RUN_LOG" 2>&1 || { echo error > "$res"; return; }
  fi

  run_agent "$id" "$wt" work

  # Commit anything the agent left uncommitted.
  ( cd "$wt" && git add -A && { git diff --cached --quiet || git commit -qm "$id: agent work (auto-commit)"; } ) >>"$RUN_LOG" 2>&1
  if [[ "$(git -C "$wt" rev-list --count "$MAIN_BRANCH..HEAD")" == 0 ]]; then echo noop > "$res"; return; fi

  # Bring the latest integration branch in; an agent resolves conflicts.
  if ! git -C "$wt" merge -q --no-edit "$MAIN_BRANCH" >>"$RUN_LOG" 2>&1; then
    run_agent "$id" "$wt" resolve
    if [[ -n "$(git -C "$wt" diff --name-only --diff-filter=U)" || -f "$(git -C "$wt" rev-parse --git-path MERGE_HEAD)" ]]; then
      git -C "$wt" merge --abort 2>/dev/null
      echo unresolved > "$res"; return
    fi
  fi

  if ( cd "$wt" && $CI_CMD ) > "$STATE_DIR/$id.gate.log" 2>&1; then echo ok > "$res"; else echo cifail > "$res"; fi
}

fail() {  # $1 ticket, $2 message, $3 keep branch for the next attempt (1) or start fresh (0)
  local id="$1" msg="$2" keep="${3:-0}"
  FAILS[$id]=$(( ${FAILS[$id]:-0} + 1 )); keep_set "$id" "$keep"
  tracker_note "$id" "agent-loop: $msg (failure ${FAILS[$id]}/$MAX_FAILS). Log: $RUN_LOG"$'\n'"$(tail -n 30 "$STATE_DIR/$id.gate.log" 2>/dev/null || true)"
  if (( FAILS[$id] >= MAX_FAILS )); then tracker_status "$id" blocked; log "[$id] blocked: $msg"
  else tracker_status "$id" open; log "[$id] reopened: $msg"; fi
}

integrate() {  # merge a ticket that passed the gate on its branch into the integration branch
  local id="$1" branch="agent/$1" pre title
  pre="$(git rev-parse HEAD)"; title="$(tracker_title "$id")"
  if ! git merge -q --no-ff "$branch" -m "Merge $id: ${title:-ticket}" -m "Ticket: $id"$'\n'"CI: ci.sh passed on branch and after merge" >>"$RUN_LOG" 2>&1; then
    git merge --abort 2>/dev/null || true
    REQUEUES[$id]=$(( ${REQUEUES[$id]:-0} + 1 )); keep_set "$id" 1
    if (( REQUEUES[$id] > 3 )); then fail "$id" "could not merge into $MAIN_BRANCH after 3 re-syncs" 1; return; fi
    attempted=$((attempted-1)); tracker_status "$id" open
    log "[$id] $MAIN_BRANCH moved while it was merging; re-queued to re-sync (not a failure)"
  elif ! $CI_CMD > "$STATE_DIR/$id.gate.log" 2>&1; then
    git reset -q --hard "$pre"
    fail "$id" "ci.sh failed after merge" 1
  else
    tracker_close "$id"; keep_set "$id" 0; done_count=$((done_count+1))
    log "[$id] merged and closed"
  fi
}

finish() {  # a worker has exited: read its verdict and act on it
  local id="$1" res cost
  res="$(cat "$STATE_DIR/$id.result" 2>/dev/null || echo error)"
  cost="$(py -c 'import sys
t=0.0
for l in open(sys.argv[1]):
    try: t+=float(l)
    except ValueError: pass
print(round(t,4))' "$STATE_DIR/$id.cost" 2>/dev/null || echo 0)"
  cost_total="$(py -c "print(round($cost_total + ${cost:-0}, 4))")"
  log "[$id] agent finished ($res), cost \$${cost:-0}, total \$$cost_total"
  case "$res" in
    ok)         integrate "$id" ;;
    noop)       fail "$id" "agent made no commits (see $LOG_DIR/)" 0 ;;
    unresolved) fail "$id" "merge conflicts with $MAIN_BRANCH were not resolved" 1 ;;
    cifail)     fail "$id" "ci.sh failed on branch" 1 ;;
    *)          fail "$id" "worker error: $res" 0 ;;
  esac
  py "$KIT_DIR/bin/time-rollup.py" --time-dir "$WORKTREE_DIR/$id/.agent/time" --ticket "$id" --write-bd >>"$RUN_LOG" 2>&1 || true
  git worktree remove --force "$WORKTREE_DIR/$id" 2>/dev/null || true
}

cleanup() { local p; for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null || true; done; }
trap cleanup INT TERM

start=$(date +%s); attempted=0; done_count=0; cost_total=0; stop=""
log "Loop start: integration branch $MAIN_BRANCH, up to $MAX_PARALLEL at once, limits $MAX_TICKETS tickets / ${MAX_HOURS}h / \$$MAX_COST_USD"

while :; do
  if [[ -z "$stop" ]]; then
    elapsed_h=$(py -c "print(($(date +%s)-$start)/3600)")
    if py -c "import sys; sys.exit(0 if $elapsed_h >= $MAX_HOURS else 1)"; then stop="time limit (${MAX_HOURS}h)"
    elif py -c "import sys; sys.exit(0 if $cost_total >= $MAX_COST_USD else 1)"; then stop="cost limit (\$$MAX_COST_USD)"
    fi
  fi

  # Start workers for the frontier, up to the parallel cap and the ticket limit.
  if [[ -z "$stop" ]]; then
    while (( ${#PIDS[@]} < MAX_PARALLEL && attempted < MAX_TICKETS )); do
      id=""
      while IFS= read -r cand; do
        [[ -n "$cand" && -z "${PIDS[$cand]:-}" ]] && { id="$cand"; break; }
      done < <(tracker_ready)
      [[ -z "$id" ]] && break
      attempted=$((attempted+1))
      tracker_claim "$id"
      log "[$id] claimed (attempt $(( ${FAILS[$id]:-0} + 1 )), $(( ${#PIDS[@]} + 1 )) running)"
      worker "$id" &
      PIDS[$id]=$!
    done
    if (( ${#PIDS[@]} == 0 )); then
      if (( attempted >= MAX_TICKETS )); then stop="ticket limit ($MAX_TICKETS)"; else stop="no ready tickets"; fi
    fi
  fi

  (( ${#PIDS[@]} == 0 )) && break
  wait -n 2>/dev/null || true
  for id in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[$id]}" 2>/dev/null; then
      unset "PIDS[$id]"
      finish "$id"
    fi
  done
done

log "Stop: ${stop:-done}."
log "Summary: $done_count closed, $attempted attempts started, \$$cost_total spent. Log: $RUN_LOG"
