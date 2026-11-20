#!/usr/bin/env python3
"""time-rollup.py: compute active time per ticket from agent hook event logs.

Rules (per session, events sorted by time):
  - The gap between two consecutive events counts in full if it is <= IDLE seconds.
  - A longer gap is idle and counts as zero.
  - Exception: a gap from tool_start to tool_end always counts in full (long commands
    fire no events while running).
  - A gap that starts at a 'stop', 'idle' or 'end' event never counts: the agent is
    waiting on a person.
  - Each gap is attributed to the ticket on the event that opens it.

Usage:
  time-rollup.py [--time-dir .agent/time] [--idle 300] [--ticket ID] [--json]
                 [--write-bd] [--write-md tracker/tickets]

--write-bd    add the result to the beads issue (metadata if supported, else a comment)
--write-md    update the 'time:' block in tracker/tickets/<ID>.md frontmatter
Processed sessions are recorded in <time-dir>/.rolled-up so nothing is counted twice.
"""
import argparse, collections, datetime as dt, json, os, re, shutil, subprocess, sys

WAITING = {"stop", "idle", "end"}


def parse_ts(s):
    s = s.replace("Z", "+00:00")
    return dt.datetime.fromisoformat(s)


def load(time_dir):
    sessions = collections.defaultdict(list)
    if not os.path.isdir(time_dir):
        return sessions
    for fn in os.listdir(time_dir):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(time_dir, fn)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    r["_t"] = parse_ts(r["ts"])
                    sessions[r.get("session", fn[:-6])].append(r)
                except Exception:
                    continue
    return sessions


def active_seconds(events, idle):
    """Return {ticket: seconds} for one session's events."""
    out = collections.Counter()
    ev = sorted(events, key=lambda r: r["_t"])
    for a, b in zip(ev, ev[1:]):
        gap = (b["_t"] - a["_t"]).total_seconds()
        if gap <= 0 or a.get("event") in WAITING:
            continue
        if a.get("event") == "tool_start" and b.get("event") == "tool_end":
            counted = gap
        elif gap <= idle:
            counted = gap
        else:
            counted = 0
        if counted:
            out[a.get("ticket") or "(none)"] += counted
    return out


BD = shutil.which("bd") or "bd"  # Windows Python cannot launch an npm shim by bare name


def write_bd(ticket, seconds, sessions_info):
    payload = {"time": {"active_seconds_added": int(seconds), "sessions": sessions_info}}
    help_txt = subprocess.run([BD, "update", "--help"], capture_output=True, text=True).stdout
    if "--metadata" in help_txt:
        r = subprocess.run([BD, "update", ticket, "--metadata", json.dumps(payload)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return "metadata"
    note = f"time: +{int(seconds)//60}m {int(seconds)%60}s active ({len(sessions_info)} session(s))"
    subprocess.run([BD, "comments", "add", ticket, note], capture_output=True, text=True)
    return "comment"


def write_md(ticket_dir, ticket, seconds, sessions_info):
    path = os.path.join(ticket_dir, f"{ticket}.md")
    if not os.path.exists(path):
        return False
    text = open(path).read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return False
    fm = m.group(1)
    cur = re.search(r"^  active_seconds:\s*(\d+)", fm, re.M)
    total = (int(cur.group(1)) if cur else 0) + int(seconds)
    new = [f"    - {{session: {s['session']}, start: \"{s['start']}\", active_seconds: {s['active_seconds']}}}"
           for s in sessions_info]
    rows = fm.split("\n")
    if not any(r.startswith("time:") for r in rows):
        rows += ["time:", f"  active_seconds: {total}", "  sessions:"] + new
    else:
        i = next(k for k, r in enumerate(rows) if r.startswith("time:"))
        j = i + 1
        while j < len(rows) and rows[j].startswith("  "):
            j += 1                      # j = end of the time block
        block = rows[i + 1:j]
        block = [f"  active_seconds: {total}" if b.strip().startswith("active_seconds:") else b for b in block]
        if not any(b.strip().startswith("active_seconds:") for b in block):
            block.insert(0, f"  active_seconds: {total}")
        block = ["  sessions:" if b.strip().startswith("sessions:") else b for b in block]
        if not any(b.strip() == "sessions:" for b in block):
            block.append("  sessions:")
        block += new
        rows = rows[:i + 1] + block + rows[j:]
    fm = "\n".join(rows)
    open(path, "w").write("---\n" + fm + "\n---\n" + text[m.end():])
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-dir", default=".agent/time")
    ap.add_argument("--idle", type=int, default=int(os.environ.get("IDLE_SECONDS", 300)))
    ap.add_argument("--ticket")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-bd", action="store_true")
    ap.add_argument("--write-md")
    ap.add_argument("--all", action="store_true", help="include sessions already rolled up")
    a = ap.parse_args()

    done_path = os.path.join(a.time_dir, ".rolled-up")
    done = set()
    if os.path.exists(done_path) and not a.all:
        done = set(open(done_path).read().split())

    per_ticket = collections.Counter()
    per_ticket_sessions = collections.defaultdict(list)
    newly = []
    for sid, events in load(a.time_dir).items():
        if sid in done:
            continue
        secs = active_seconds(events, a.idle)
        start = min(e["_t"] for e in events).isoformat(timespec="minutes")
        for t, s in secs.items():
            if a.ticket and t != a.ticket:
                continue
            per_ticket[t] += s
            per_ticket_sessions[t].append({"session": sid, "start": start, "active_seconds": int(s)})
        newly.append(sid)

    if a.json:
        print(json.dumps({t: {"active_seconds": int(s), "sessions": per_ticket_sessions[t]}
                          for t, s in per_ticket.items()}, indent=2))
    else:
        for t, s in sorted(per_ticket.items()):
            print(f"{t:20} {int(s)//3600:2d}h {int(s)%3600//60:2d}m {int(s)%60:2d}s")

    wrote = []
    for t, s in per_ticket.items():
        if t == "(none)" or s <= 0:
            continue
        if a.write_bd:
            wrote.append((t, write_bd(t, s, per_ticket_sessions[t])))
        if a.write_md:
            write_md(a.write_md, t, s, per_ticket_sessions[t])
            wrote.append((t, "markdown"))
    for t, how in wrote:
        print(f"wrote {t} -> {how}", file=sys.stderr)

    if (a.write_bd or a.write_md) and newly and not a.all:
        os.makedirs(a.time_dir, exist_ok=True)
        with open(done_path, "a") as f:
            f.write("\n".join(newly) + "\n")


if __name__ == "__main__":
    main()
