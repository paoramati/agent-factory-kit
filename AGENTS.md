# Agent factory kit

Tooling that runs AI coding agents unattended: one ticket per fresh agent, a gate script as the only judge, local merges. Read `CONTEXT.md` for the vocabulary and `README.md` for usage.

## Layout

- `skills/`: `factory-dashboard` (open the UI), `ticket-workflow`, `time-tracking`.
- `bin/agent-loop.sh`: the loop. `bin/status.py` (one repo): local view of issues, branches and progress. `dashboard/` (all repos, beads plus GitHub plus local PRs): the live Dashboard, run `py -m dashboard --config <repo list>` from the kit directory; tests in `dashboard/tests`. `bin/time-rollup.py`: active time per ticket. `tracker/`: the GitHub Issues backend (`gh_tracker.py`) and the beads-to-GitHub migration (`beads_to_github.py`); tests in `tracker/tests`. `TRACKER=beads|github` picks the loop's tracker; `docs/adr/` records why.
- `templates/PROMPT.md`: the per-ticket prompt every worker receives. `config/`: Claude Code and OpenCode settings.
- `tests/loop-test.sh`: runs the loop against a throwaway repo with a fake agent. `ci.sh`: the gate; run it before every commit.

## Rules

- Use the `bash-on-windows` skill before writing any shell script or Python that launches tools.
- Test loop changes through `tests/loop-test.sh`; extend it when the loop gains behaviour.
- Use `git` and `gh` for GitHub operations the user requests, including pushing topic branches and creating or merging pull requests. Do not push directly to `main`; use pull requests. The unattended loop's push protections remain in force.

## Agent skills

### Issue tracker

GitHub Issues on paoramati/agent-factory-kit, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.
