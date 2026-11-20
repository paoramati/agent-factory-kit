#!/usr/bin/env python3
"""dashboard.py: one local page over every repo in the initiative, combining three sources:
  * beads (the local ticket store the loop reads),
  * GitHub issues and pull requests (through the gh CLI, when the repo has a GitHub remote),
  * local "PRs": agent/<id> branches, merged or still open against the integration branch.

Usage: py bin/dashboard.py [--config PATH] [--out PATH] [--open]
Config is a JSON list: [{"name","path","github","branch","beads"}]. Default: the Home Repo's
factory/repos.json. The page is a local file; nothing is uploaded.
"""
import argparse, datetime, html, json, os, shutil, subprocess, sys, webbrowser

ap = argparse.ArgumentParser()
ap.add_argument("--config", default=os.environ.get("FACTORY_REPOS", "repos.json"),
                help="JSON list of repos (default: $FACTORY_REPOS, else ./repos.json); see config/repos.example.json")
ap.add_argument("--out", default=None, help="output page (default: .dashboard/index.html beside the config)")
ap.add_argument("--open", action="store_true")
a = ap.parse_args()
cfg_path = os.path.abspath(a.config)
if not os.path.isfile(cfg_path):
    sys.exit(f"No repo list at {cfg_path}. Copy config/repos.example.json, edit it, and pass --config or set FACTORY_REPOS.")
repos = json.load(open(cfg_path, encoding="utf-8"))
out = a.out or os.path.join(os.path.dirname(cfg_path), ".dashboard", "index.html")

BD, GH, GIT = shutil.which("bd"), shutil.which("gh"), shutil.which("git")


def run(cmd, cwd=None, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env, timeout=60)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def jload(text):
    if not text:
        return None
    try:
        return json.loads(text[min(i for i in (text.find("["), text.find("{")) if i >= 0):])
    except Exception:
        return None


def esc(x):
    return html.escape(str(x if x is not None else ""))


def git(path, *args):
    return (run([GIT, "-C", path, *args]) or "").strip()


def beads(r):
    if not (r.get("beads") and BD):
        return None
    env = dict(os.environ, BEADS_DIR=os.path.join(r["path"], ".beads"))
    d = jload(run([BD, "list", "--all", "--limit", "0", "--json"], cwd=r["path"], env=env))
    return d.get("issues", []) if isinstance(d, dict) else d


def github(r):
    if not (r.get("github") and GH):
        return None, None
    issues = jload(run([GH, "issue", "list", "--repo", r["github"], "--state", "all", "--limit", "50",
                        "--json", "number,title,state,url,labels"]))
    prs = jload(run([GH, "pr", "list", "--repo", r["github"], "--state", "all", "--limit", "50",
                     "--json", "number,title,state,url,headRefName"]))
    return issues, prs


def local_prs(r):
    """agent/<id> branches: merged into the integration branch or still open."""
    base = r.get("branch", "main")
    names = git(r["path"], "for-each-ref", "--format=%(refname:short)", "refs/heads/agent/").splitlines()
    out_ = []
    for n in names:
        merged = run([GIT, "-C", r["path"], "merge-base", "--is-ancestor", n, base]) is not None
        ahead = git(r["path"], "rev-list", "--count", f"{base}..{n}")
        subject = git(r["path"], "log", "-1", "--format=%cs %s", n)
        out_.append({"branch": n, "merged": merged, "ahead": ahead, "last": subject})
    return out_


def repo_state(r):
    p = r["path"]
    if not os.path.isdir(os.path.join(p, ".git")):
        return {"missing": True}
    base = r.get("branch", "main")
    upstream = git(p, "rev-parse", "--abbrev-ref", f"{base}@{{upstream}}")
    if upstream:
        unpushed = git(p, "rev-list", "--count", f"{upstream}..{base}")
    elif git(p, "rev-parse", "--verify", "-q", "origin/main"):
        unpushed = git(p, "rev-list", "--count", f"origin/main..{base}") + " (branch not pushed)"
    else:
        unpushed = "no remote"
    merges = git(p, "log", base, "--merges", "--format=%cs|%s", "-n", "8").splitlines()
    return {"unpushed": unpushed, "dirty": bool(git(p, "status", "--porcelain")), "merges": merges,
            "head": git(p, "log", "-1", "--format=%h %s", base)}


data = []
for r in repos:
    gi, gp = github(r)
    data.append({"cfg": r, "state": repo_state(r), "beads": beads(r), "gh_issues": gi, "gh_prs": gp,
                 "lprs": local_prs(r) if os.path.isdir(os.path.join(r["path"], ".git")) else []})


def counts(items, key, vals):
    return {v: sum(1 for i in items if i.get(key) == v) for v in vals}


def summary_row(d):
    c, s = d["cfg"], d["state"]
    if s.get("missing"):
        return f'<tr><td>{esc(c["name"])}</td><td colspan="6">not found at {esc(c["path"])}</td></tr>'
    b = d["beads"]
    bt = "no beads" if b is None else (lambda k: f'{k["closed"]}/{len(b)} done, {k["in_progress"]} active, {k["blocked"]} blocked')(counts(b, "status", ["closed", "in_progress", "blocked"]))
    gi = d["gh_issues"]; gp = d["gh_prs"]
    gis = "n/a" if gi is None else f'{sum(1 for i in gi if i["state"] == "OPEN")} open / {len(gi)}'
    gps = "n/a" if gp is None else f'{sum(1 for i in gp if i["state"] == "OPEN")} open / {len(gp)}'
    lp = d["lprs"]; lps = f'{sum(1 for x in lp if not x["merged"])} open / {len(lp)}'
    flag = " ⚠" if s["unpushed"] not in ("0", "no remote") else ""  # something is not on GitHub yet
    dirty = " (dirty)" if s["dirty"] else ""
    return (f'<tr><td><a href="#{esc(c["name"])}">{esc(c["name"])}</a></td><td>{esc(bt)}</td><td>{gis}</td><td>{gps}</td>'
            f'<td>{lps}</td><td>{esc(s["unpushed"])}{flag}</td><td><code>{esc(c.get("branch","main"))}</code>{dirty}</td></tr>')


def table(headers, rows):
    if not rows:
        return "<p class=mute>None.</p>"
    return ('<div class=wrap><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")


def section(d):
    c, s = d["cfg"], d["state"]
    if s.get("missing"):
        return ""
    parts = [f'<h2 id="{esc(c["name"])}">{esc(c["name"])} <span class=mute>{esc(c.get("github",""))}</span></h2>',
             f'<p class=mute>Head of <code>{esc(c.get("branch","main"))}</code>: {esc(s["head"])} · unpushed commits: {esc(s["unpushed"])}</p>']
    b = d["beads"]
    if b is not None:
        order = {"in_progress": 0, "open": 1, "blocked": 2, "deferred": 3, "closed": 4}
        rows = [[f'<code>{esc(i.get("id"))}</code>', esc(i.get("title")), esc(i.get("status")), f'P{esc(i.get("priority"))}',
                 " ".join(f'<span class=tag>{esc(l)}</span>' for l in (i.get("labels") or []) if not l.startswith("src:"))]
                for i in sorted(b, key=lambda i: (order.get(i.get("status"), 9), i.get("priority", 9), i.get("id", "")))]
        parts += ["<h3>Local tickets (beads)</h3>", table(["ID", "Title", "Status", "Pri", "Labels"], rows)]
    lp = d["lprs"]
    if lp:
        parts += ["<h3>Local PRs (agent branches)</h3>", table(["Branch", "State", "Commits ahead", "Last commit"],
                  [[f'<code>{esc(x["branch"])}</code>', "merged" if x["merged"] else "open", esc(x["ahead"]), esc(x["last"])] for x in lp])]
    if s["merges"]:
        parts += ["<h3>Recent merges</h3><ul>" + "".join(f'<li><code>{esc(m.split("|",1)[0])}</code> {esc(m.split("|",1)[-1])}</li>' for m in s["merges"]) + "</ul>"]
    gi, gp = d["gh_issues"], d["gh_prs"]
    if gi is not None:
        parts += ["<h3>GitHub issues</h3>", table(["#", "Title", "State", "Labels"],
                  [[f'<a href="{esc(i["url"])}" target=_blank>#{i["number"]}</a>', esc(i["title"]), esc(i["state"]),
                    " ".join(f'<span class=tag>{esc(l["name"])}</span>' for l in i.get("labels", []))] for i in gi])]
    if gp is not None:
        parts += ["<h3>GitHub pull requests</h3>", table(["#", "Title", "State", "Branch"],
                  [[f'<a href="{esc(p["url"])}" target=_blank>#{p["number"]}</a>', esc(p["title"]), esc(p["state"]), f'<code>{esc(p["headRefName"])}</code>'] for p in gp])]
    return "".join(parts)


now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory dashboard</title>
<style>
:root{{--bg:#fff;--fg:#1c1c1e;--mute:#6b7280;--line:#e5e7eb;--accent:#2563eb;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111318;--fg:#e8e8ea;--mute:#9ca3af;--line:#2a2e37;--accent:#60a5fa;color-scheme:dark}}}}
body{{margin:0;padding:1.5rem 1rem;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
main{{max-width:72rem;margin:0 auto}} h1{{font-size:1.3rem;margin:0}} h2{{font-size:1.05rem;margin:2rem 0 .2rem}} h3{{font-size:.95rem;margin:1.1rem 0 .3rem}}
.mute{{color:var(--mute);font-weight:400}} a{{color:var(--accent)}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;padding:.3rem .55rem;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mute);font-weight:500}} code{{font-family:ui-monospace,monospace}}
.tag{{display:inline-block;border:1px solid var(--line);border-radius:.3rem;padding:0 .35rem;margin:0 .2rem .2rem 0;font-size:12px;color:var(--mute)}}
</style>
<main>
<h1>Factory dashboard</h1>
<p class=mute>{now} · beads = local tickets, GitHub = issues and PRs, local PRs = agent/&lt;id&gt; branches. Local file, nothing uploaded.</p>
{table(["Repo", "Local tickets", "GH issues", "GH PRs", "Local PRs", "Unpushed", "Branch"], [])[:0]}
<div class=wrap><table><thead><tr><th>Repo</th><th>Local tickets</th><th>GH issues</th><th>GH PRs</th><th>Local PRs</th><th>Unpushed</th><th>Branch</th></tr></thead>
<tbody>{"".join(summary_row(d) for d in data)}</tbody></table></div>
{"".join(section(d) for d in data)}
</main>"""

os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print(os.path.abspath(out))
if a.open:
    webbrowser.open("file:///" + os.path.abspath(out).replace("\\", "/"))
