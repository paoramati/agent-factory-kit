---
name: factory-dashboard
description: Open the factory dashboard, one local page over every repo in the initiative: beads tickets, GitHub issues and PRs, and local PRs (agent branches). Use when the user asks to see, refresh or open the issues, PRs, progress or status of the factory or its repos.
---

# Factory dashboard

1. Find the repo list: `$FACTORY_REPOS` if set, else `repos.json` in the current directory, else the Home Repo's `factory/repos.json`. With no list, copy `config/repos.example.json` from the kit, edit it, and say where you saved it.
2. Run it from anywhere: `py <kit>/bin/dashboard.py --config <repo list> --open`. `<kit>` is the agent-factory-kit checkout (`C:\projects\agent-factory-kit` here).
3. Report the page path it prints, then summarise the top table in a few lines: tickets done, open and blocked per repo, open PRs, and any repo with commits not yet on GitHub (⚠) or a dirty tree.

For one repo only, run `py <kit>/bin/status.py --branch <integration branch> --open` from that repo's root.

## Reading the page

- **Local tickets (beads)**: the loop's queue. Status counts, labels, priority.
- **GitHub issues and pull requests**: read through `gh`; `n/a` means `gh` is missing, signed out, or the repo has no GitHub remote.
- **Local PRs**: each `agent/<id>` branch, merged into the integration branch or still open with its commit count. Open ones are unreviewed work.
- **Unpushed**: commits on the integration branch that GitHub does not have yet.

The page is a local file and nothing is uploaded. Each run overwrites it; run again to refresh.
