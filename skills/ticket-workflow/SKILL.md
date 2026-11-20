---
name: ticket-workflow
description: How to claim, work on, finish and hand off a tracker ticket in this repo. Use at the start of any coding task and before ending a session.
---

# Ticket workflow

## Start
1. If no ticket was given, pick one: `bd ready --json`, take the first.
2. Claim it: `bd update <id> --claim`.
3. Record it for time tracking: `mkdir -p .agent && echo <id> > .agent/current-ticket`.
4. Read the ticket, its parent and its dependencies. Read earlier notes on it.

## Work
- Stay inside the ticket's acceptance criteria. File anything else: `bd create "<title>" -t <type> --deps discovered-from:<id>`.
- Commit often, locally, with `<id>:` at the start of the message.

## Finish
1. Run `./ci.sh` until it passes.
2. Add a note: `bd comments add <id> "<what changed; decisions; what to review>"`.
3. In the automated loop, end the session; the loop closes the ticket. Working interactively, close it: `bd close <id>`.
4. Clear the current ticket: `rm -f .agent/current-ticket`.

## Context running out
Before the session ends for any reason, write the handoff into the ticket note: the current state, the next step, and any command that was failing. The next session reads it at step 4 of Start.

## Ticket types
| Type | Output |
|---|---|
| epic | Child tickets, not code |
| feature | User-visible behaviour with tests |
| mechanic | A core rule with its invariants tested at the edges |
| standard | A convention written into a skill or rules file, with one example applied |
| workflow | A script or process change, with how to run it |
| spike | A decision record in `docs/decisions/`, within the timebox |
