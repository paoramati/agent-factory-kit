# GitHub Issues is the default tracker; beads only for the stock project

Status: accepted

Each repository keeps its tickets in exactly one tracker. Beads is used only for the stock project; every other repository, git-vault included, uses GitHub Issues. The loop gained a GitHub backend (`TRACKER=github`) so the same unattended cycle runs on either, and git-vault's tickets were migrated from beads.

## Considered options

- **Leave git-vault on beads and mirror to GitHub** (the earlier decision). Rejected: two copies of a ticket drift, and a mirror needs replaying PRs and issues to look real.
- **Move git-vault to GitHub Issues and teach the loop to read them** (chosen). One tracker per repo, visible on GitHub, and no mirror to maintain.

## Consequences

- Blocked-by is a text convention (`## Blocked by` lines), not a native graph. The loop's preflight validates it, so a typo refuses to start rather than silently unblocking work.
- An issue named under `## Parent` is an epic and never built, so PRDs labelled `ready-for-agent` are safe.
- Time rollup writes to beads only.
- Switching a repo's tracker again means running the migration in the other direction, which does not exist yet.
