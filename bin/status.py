#!/usr/bin/env python3
"""status.py: one local HTML page showing issues and progress for a repo run by the factory.

Run from the project repo root:  py bin/status.py [--open] [--branch factory] [--out .agent/status.html]
Reads `bd list --all --json`, `git log` on the integration branch and .agent/loop/run-*.log.
Writes a single self-contained file on this machine. Nothing is uploaded anywhere.
"""
import argparse, html, json, os, re, shutil, subprocess, sys, glob, webbrowser, datetime

ap = argparse.ArgumentParser()
ap.add_argument("--branch", default=os.environ.get("MAIN_BRANCH", "main"))
ap.add_argument("--out", default=".agent/status.html")
ap.add_argument("--open", action="store_true")
a = ap.parse_args()


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


bd = shutil.which("bd") or sys.exit("bd not found on PATH")
raw = run([bd, "list", "--all", "--limit", "0", "--json"])
try:
    issues = json.loads(raw[raw.index("["):]) if "[" in raw else []
except ValueError:
    issues = []
if isinstance(issues, dict):
    issues = issues.get("issues", [])

order = ["in_progress", "open", "blocked", "deferred", "closed"]
label = {"in_progress": "In progress", "open": "Ready / open", "blocked": "Blocked", "deferred": "Deferred", "closed": "Done"}
by = {s: [] for s in order}
for i in issues:
    by.setdefault(i.get("status", "open"), []).append(i)
total = len(issues) or 1
done = len(by.get("closed", []))

merges = run(["git", "log", a.branch, "--merges", "--format=%cs|%s", "-n", "15"]).strip().splitlines()
commits_ahead = run(["git", "rev-list", "--count", f"main..{a.branch}"]).strip() if a.branch != "main" else ""

runs = []
for f in sorted(glob.glob(".agent/loop/run-*.log"))[-5:]:
    for line in open(f, encoding="utf-8", errors="replace"):
        if "Summary:" in line:
            runs.append((os.path.basename(f), line.split("Summary:", 1)[1].strip()))


def esc(x):
    return html.escape(str(x if x is not None else ""))


def row(i):
    labels = " ".join(f'<span class="tag">{esc(l)}</span>' for l in (i.get("labels") or []) if not l.startswith("src:"))
    return (f'<tr><td class="id">{esc(i.get("id"))}</td><td>{esc(i.get("title"))}</td>'
            f'<td>P{esc(i.get("priority"))}</td><td>{esc(i.get("issue_type"))}</td><td>{labels}</td></tr>')


sections = []
for s in order:
    items = sorted(by.get(s, []), key=lambda i: (i.get("priority", 9), i.get("id", "")))
    if not items:
        continue
    sections.append(f'<h2>{label.get(s, s)} <span class="n">{len(items)}</span></h2>'
                    f'<div class="wrap"><table><thead><tr><th>ID</th><th>Title</th><th>Pri</th><th>Type</th><th>Labels</th></tr></thead>'
                    f'<tbody>{"".join(row(i) for i in items)}</tbody></table></div>')

pct = round(100 * done / total)
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory status</title>
<style>
:root{{--bg:#fff;--fg:#1c1c1e;--mute:#6b7280;--line:#e5e7eb;--accent:#2563eb;--ok:#16a34a;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111318;--fg:#e8e8ea;--mute:#9ca3af;--line:#2a2e37;--accent:#60a5fa;--ok:#4ade80;color-scheme:dark}}}}
body{{margin:0;padding:1.5rem 1rem;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
main{{max-width:60rem;margin:0 auto}} h1{{font-size:1.3rem;margin:0}} h2{{font-size:1rem;margin:1.6rem 0 .4rem}}
.n{{color:var(--mute);font-weight:400;margin-left:.3rem}} .sub{{color:var(--mute);margin:.2rem 0 1rem}}
.bar{{height:.6rem;background:var(--line);border-radius:1rem;overflow:hidden}} .bar i{{display:block;height:100%;width:{pct}%;background:var(--ok)}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;padding:.35rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mute);font-weight:500}} .id{{font-family:ui-monospace,monospace;white-space:nowrap}}
.tag{{display:inline-block;border:1px solid var(--line);border-radius:.3rem;padding:0 .35rem;margin:0 .2rem .2rem 0;font-size:12px;color:var(--mute)}}
li{{margin:.15rem 0}} code{{font-family:ui-monospace,monospace}}
</style>
<main>
<h1>Factory status</h1>
<p class="sub">{esc(os.path.basename(os.getcwd()))} · branch <code>{esc(a.branch)}</code>{f" · {commits_ahead} commits ahead of main" if commits_ahead else ""} · {now}</p>
<div class="bar" role="progressbar" aria-valuenow="{pct}" aria-valuemin="0" aria-valuemax="100"><i></i></div>
<p class="sub">{done} of {len(issues)} done ({pct}%)</p>
{"".join(sections) or "<p>No issues found.</p>"}
<h2>Recent merges <span class="n">{len(merges)}</span></h2>
<ul>{"".join(f"<li><code>{esc(m.split('|',1)[0])}</code> {esc(m.split('|',1)[-1])}</li>" for m in merges) or "<li>None yet.</li>"}</ul>
<h2>Recent loop runs</h2>
<ul>{"".join(f"<li><code>{esc(n)}</code> {esc(s)}</li>" for n, s in runs) or "<li>None yet.</li>"}</ul>
</main>"""

os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
with open(a.out, "w", encoding="utf-8") as f:
    f.write(page)
print(os.path.abspath(a.out))
if a.open:
    webbrowser.open("file:///" + os.path.abspath(a.out).replace("\\", "/"))
