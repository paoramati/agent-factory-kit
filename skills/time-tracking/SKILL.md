---
name: time-tracking
description: Keep per-ticket active time accurate. Use when starting or switching tickets, or when asked how long a ticket took.
---

# Time tracking

Active time is recorded automatically by session hooks. Your only job is to keep the current ticket correct, because every event is attributed to whatever `.agent/current-ticket` says at that moment.

- Starting a ticket: `echo <id> > .agent/current-ticket` before doing any work on it.
- Switching tickets mid-session: rewrite the file first, then switch.
- Finishing: `rm -f .agent/current-ticket`.
- Never edit files under `.agent/time/` by hand.

To report time: `python3 <kit>/bin/time-rollup.py --all` (add `--ticket <id>` for one ticket).

What counts as active: gaps between agent events of up to five minutes, and the full duration of any single tool call. Time spent waiting for a person after the agent stops does not count.
