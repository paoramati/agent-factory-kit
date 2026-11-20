# Tracker scaffold

Beads holds the tickets. This folder holds the shape every ticket should have, so tickets stay consistent and can be exported to another tracker later with a mechanical mapping.

If you prefer plain Markdown tickets instead of beads, put them in `tracker/tickets/<ID>.md` using the templates here. `validate.py` checks their frontmatter against `schema.json`, and `time-rollup.py --write-md tracker/tickets` writes time into them.

## Statuses

`draft → ready → in_progress → in_review → done`, plus `blocked` and `cancelled`.
Only `ready` tickets are visible to agents.

## Definition of Ready
- Has a parent epic (except epics).
- Dependencies are linked.
- Acceptance criteria are testable by a script, not by opinion.
- Spikes have a timebox; mechanics list their invariants.
- Small enough for one agent session. If in doubt, split it.

## Definition of Done
- Acceptance criteria met and `ci.sh` green after merge.
- Note added: what changed, what to review.
- Time recorded.
- Follow-ups filed and linked.

## Labels
`layer:*`, `area:*`, `risk:low|med|high`, `agent-ok` or `human-only`, `parity-critical` (must match legacy behaviour exactly).

## Keeping it useful
- Review the schema at each retro. Drop fields nobody fills. Add a field only after it has been missed three times.
- Name custom fields so they map one-to-one onto your eventual tracker's custom fields.
