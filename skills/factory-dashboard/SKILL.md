---
name: factory-dashboard
description: Open the factory dashboard, one live local page over every repo in the initiative: beads tickets, GitHub issues and PRs, and local PRs (agent branches). Use when the user asks to see, refresh or open the issues, PRs, progress or status of the factory or its repos.
---

# Factory dashboard

1. Find the repo list: `$FACTORY_REPOS` if set, else `repos.json` in the current directory, else the Home Repo's `factory/repos.json`. With no list, copy `config/repos.example.json` from the kit, edit it, and say where you saved it.
2. Start it from the kit directory, with an absolute path to the list, in the background (it runs until stopped): `cd <kit>; py -m dashboard --config <repo list>`. `<kit>` is the agent-factory-kit checkout (`C:\projects\agent-factory-kit` here). It opens the browser. If a Dashboard is already running on the port it just opens that one, so run it whenever asked; do not stop or restart it.
3. Report the URL it prints (default `http://127.0.0.1:8765/`), then summarise the top table in a few lines: tickets done, open and blocked per repo, open PRs, and any repo with commits not yet on GitHub (⚠) or a dirty tree. To read the same data as JSON, fetch `/api/state`.

For one repo only, run `py <kit>/bin/status.py --branch <integration branch> --open` from that repo's root.

## Reading the page

- It updates in place. Local sources refresh every few seconds, GitHub about once a minute. Each section shows how old its data is.
- **Stale**: a refresh failed, so the section is greyed and shows the last good data with its age and the reason. **Unavailable**: that source has never worked; the reason is shown. Neither means "no work".
- **Local tickets (beads)**: the loop's queue. Status counts, labels, priority.
- **GitHub issues and pull requests**: read through `gh`; `n/a` means the repo has no GitHub remote.
- **Local PRs**: each `agent/<id>` branch, merged into the integration branch or still open with its commit count. Open ones are unreviewed work.
- **Unpushed**: commits on the integration branch that GitHub does not have yet.

The server listens on 127.0.0.1 only, is read-only, and nothing is uploaded. `--port` changes the port; `--no-open` skips the browser.
