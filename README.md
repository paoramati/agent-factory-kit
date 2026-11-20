# agent-factory-kit

A small, stack-agnostic kit for running AI coding agents (Claude Code, OpenCode) unattended on a local repository: one ticket per fresh agent process, a CI script as the only judge, hard stop conditions, active-time tracking per ticket, and layered protection against pushing to remotes.

It is deliberately small. The ideas come from multi-agent orchestrators like Gas Town and the Ralph Wiggum loop, cut down to what one developer can run over a weekend.

## What's in it

| Path | What it does |
|---|---|
| `bin/agent-loop.sh` | Claims a ready ticket, runs a fresh agent in its own worktree, gates on `ci.sh`, merges locally, repeats until a stop condition. |
| `bin/ci.sh.example` | Template for the single CI script both agents and the loop run. Copy to your repo as `ci.sh`. |
| `bin/lockdown-remote.sh` | Removes push paths from a repo: disables push URLs on every remote, adds a `pre-push` hook that refuses everything. |
| `bin/backup-bundle.sh` / `bin/backup-bundle.ps1` | Writes a timestamped `git bundle` of all history to a folder (e.g. a synced cloud drive) and prunes old ones. |
| `bin/status.py` / `bin/dashboard.py` | Local HTML views: one repo's tickets and progress, or every repo in a list (beads tickets, GitHub issues and PRs, local PRs). Nothing is uploaded. See `config/repos.example.json`. |
| `bin/time-rollup.py` | Turns hook event logs into active time per ticket and writes it back to the tracker. |
| `hooks/track.sh` | Claude Code hook: appends one timestamped event per hook call. |
| `opencode/plugins/time-tracker.js` | OpenCode plugin: same event log for OpenCode sessions. |
| `config/claude-settings.example.json` | Claude Code settings: hooks, deny `git push`, sandbox on. |
| `config/opencode.example.json` | OpenCode permissions: deny `git push`. |
| `templates/AGENTS.md` | Rules file for agents. Symlink or copy to `CLAUDE.md` too. |
| `templates/PROMPT.md` | The per-ticket prompt the loop feeds each agent. |
| `tracker/` | Ticket templates per type, a JSON Schema for frontmatter, Definition of Ready / Done. |
| `skills/ticket-workflow/` | Skill: how an agent claims, works, finishes and hands off a ticket. |
| `skills/time-tracking/` | Skill: how agents keep the time log accurate. |

## Requirements

- git 2.20+, bash, python3 (3.9+)
- [beads](https://github.com/steveyegge/beads) (`bd`) as the tracker. The loop only uses `bd ready`, `bd update --claim`, `bd update --status`, `bd close` and `bd comments add`, so swapping trackers means editing four functions at the top of `agent-loop.sh`.
- Claude Code and/or OpenCode

## Quick start

```bash
# in your project repo
cp -r agent-factory-kit/templates/AGENTS.md ./AGENTS.md && ln -s AGENTS.md CLAUDE.md
cp agent-factory-kit/bin/ci.sh.example ./ci.sh && chmod +x ci.sh   # then fill it in
mkdir -p .claude && cp agent-factory-kit/config/claude-settings.example.json .claude/settings.json
mkdir -p .agent && cp agent-factory-kit/hooks/track.sh .agent/track.sh && chmod +x .agent/track.sh
cp -r agent-factory-kit/skills/* .claude/skills/   # or your agent's skills folder
printf '.agent/*\n!.agent/track.sh\n.worktrees/\n' >> .gitignore
git add -A && git commit -m "Add agent factory scaffolding"   # worktrees branch from committed main

agent-factory-kit/bin/lockdown-remote.sh .       # no pushes from this repo
./ci.sh                                          # must be green before any agent runs

bd init
# write 10-30 small tickets with acceptance criteria, mark them ready

# watch a supervised run first
MAX_TICKETS=2 agent-factory-kit/bin/agent-loop.sh
```

Then leave it running with limits:

```bash
MAX_TICKETS=10 MAX_HOURS=8 MAX_COST_USD=60 agent-factory-kit/bin/agent-loop.sh
```

## How the loop decides

1. Stop starting work if a limit is hit: ticket count, wall-clock hours, or cumulative cost. Stop when the frontier is empty and nothing is running.
2. Read the **frontier**: ready, unblocked tickets carrying the `agent-ok` label (`READY_LABEL`). Independence comes from the ticket graph, so a ticket only appears once its blockers are done. Claim up to `MAX_PARALLEL` (default 2).
3. Each ticket gets its own worktree on a branch named `agent/<id>`, and one fresh agent process. The prompt (`templates/PROMPT.md`) tells it to build test-first with the `tdd` skill and review its own diff with the `code-review` skill.
4. The worker merges the latest integration branch into the ticket branch. If that conflicts, a second agent session resolves the conflicts. Then it runs `ci.sh` on the branch.
5. Only the loop merges into the integration branch (`MAIN_BRANCH`, default `main`), one ticket at a time, then runs `ci.sh` again on the merged result. The merge commit reads `Merge <id>: <ticket title>` with `Ticket:` and `CI:` trailers, and `agent/<id>` is kept, so the history reads like merged PRs. If the integration branch moved while a ticket waited to merge, the ticket is re-queued to re-sync. That is not counted as a failure.
6. A failure reopens the ticket with a note holding the gate output. A gate failure keeps the ticket branch, and the next attempt continues from it with the gate output in its prompt. An attempt that commits nothing starts fresh. Failing `MAX_FAILS` times (default 2) marks the ticket blocked.
7. Close the ticket, roll up time, remove the worktree.

For a long-running feature branch, create it (`git branch factory`) and run with `MAIN_BRANCH=factory`. Every ticket then merges there, and `main` stays untouched until you merge `factory` yourself.

Tickets that edit the same file will conflict when run in parallel. Structure the code so independent tickets touch different files (one file per command, for example), or run with `MAX_PARALLEL=1`.

Agents are given a fixed allow-list of tools on the command line (`ALLOWED_TOOLS`), because Claude Code ignores a project's `permissions.allow` until the folder is trusted. On Windows the sandbox is not active, so the allow-list and the `git push` deny rule are the protection, not a sandbox.

The agent's own claim that tests pass is never trusted.

## Active time

Every hook call appends one JSON line to `.agent/time/<session>.jsonl`. `time-rollup.py` sorts events per session and sums the gaps between them:

- a gap up to `IDLE_SECONDS` (default 300) counts in full;
- a longer gap counts as idle and adds nothing;
- a gap that ends a tool call counts in full, because nothing fires while a long command runs;
- time after a `stop` / `idle` event (the agent is waiting on a person) never counts.

The ticket being worked on comes from `.agent/current-ticket`, which the loop writes and the ticket-workflow skill tells interactive agents to write.

## No-push guardrails, in layers

1. `lockdown-remote.sh`: push URL set to an invalid value on every remote, plus a `pre-push` hook that exits non-zero.
2. Agent permissions deny `git push` (Claude Code `permissions.deny`, OpenCode `permission.bash`).
3. Keep forge credentials out of the environment the loop runs in.
4. Sandbox the agent's shell (Claude Code `sandbox.enabled`), or run everything in a container or VM.

Pushing is a human step, done through whatever review process your team uses.

## Backups without a remote

```bash
bin/backup-bundle.sh /path/to/repo "/path/to/synced/folder/repo-backups" 14
```

Writes `repo-YYYYmmdd-HHMMSS.bundle` and keeps the newest 14. Restore with `git clone repo-....bundle restored-repo`. Schedule it with cron, launchd or Windows Task Scheduler (`backup-bundle.ps1`). The tracker's own data is included if it lives in the repo; for beads, also run `bd export` into the repo before the bundle, which the script does when `bd` is present.

## Things to check against your installed versions

CLI flags move quickly. Before the first unattended run, confirm against `--help`:

- `claude -p` flags used in `agent-loop.sh`. Checked against Claude Code 2.1.329 on 2026-11-20: `--output-format json` (cost is in `total_cost_usd`), `--permission-mode acceptEdits` and `--disallowedTools` work. `--max-turns` is accepted but not listed in `--help`, so recheck it after upgrades.
- `bd update --help` for the metadata flag used by `time-rollup.py --write-bd`. Without it, time goes to a ticket comment instead.
- Claude Code hook input fields (`session_id`, `hook_event_name`, `tool_name`).
- OpenCode plugin event names in `time-tracker.js`.

## License

MIT. See `LICENSE`.
