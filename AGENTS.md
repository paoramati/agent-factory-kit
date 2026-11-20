# Agent factory kit

Private tooling that runs AI coding agents unattended: one ticket per fresh agent, a gate script as the only judge, local merges. Read `CONTEXT.md` for the vocabulary and `README.md` for usage.

## Layout

- `bin/agent-loop.sh`: the loop. `bin/status.py` (one repo) and `bin/dashboard.py` (all repos, beads plus GitHub plus local PRs): local views of issues, branches and progress. `bin/time-rollup.py`: active time per ticket.
- `templates/PROMPT.md`: the per-ticket prompt every worker receives. `config/`: Claude Code and OpenCode settings.
- `tests/loop-test.sh`: runs the loop against a throwaway repo with a fake agent. `ci.sh`: the gate; run it before every commit.

## Rules

- Use the `bash-on-windows` skill before writing any shell script or Python that launches tools.
- Test loop changes through `tests/loop-test.sh`; extend it when the loop gains behaviour.
- Commit locally. The owner pushes.

## Agent skills

### Issue tracker

GitHub Issues on paoramati/agent-factory-kit (private), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.
