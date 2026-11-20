# Agent rules

These rules apply to every agent working in this repository. Project-specific skills add to them; nothing overrides them.

## Scope
- Work on exactly one ticket: the one named in your prompt or in `.agent/current-ticket`.
- If you find other problems, file a new ticket (`bd create ...`) and leave them alone.
- Do not edit `ci.sh`, these rules, or tracker templates unless the ticket is about them.

## Git
- Commit locally with messages starting with the ticket ID: `F-012: add renewal rules`.
- Never push, add remotes, or change remote URLs. Pushing is a human step.
- Never rewrite history on the main branch.

## Done means
- Every acceptance criterion on the ticket is met.
- `./ci.sh` passes in your working tree. Run it; do not assume.
- New behaviour has tests.
- Follow-up work is filed as new tickets, linked to this one.
- A short note is added to the ticket: what changed, anything surprising, what to check in review.

## When stuck
- If the same failure repeats three times, stop. Add a note to the ticket explaining what you tried and what you think is wrong, and end the session.
- If a ticket is ambiguous, write down the interpretation you chose in the ticket note and continue.

## Never
- Weaken or skip a test to make CI pass.
- Commit secrets, credentials or real customer data.
- Change database schemas outside a migration.
