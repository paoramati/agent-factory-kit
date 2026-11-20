#!/usr/bin/env python3
"""Stand-in for the gh CLI used by loop-test-github.sh. State lives in the JSON file $FAKE_GH_STATE:
{"issues": [{"number", "title", "state", "labels": [names], "body", "comments": []}], "labels": []}
Supports only what the Loop's GitHub tracker calls."""
import json
import os
import sys

path = os.environ["FAKE_GH_STATE"]
with open(path, encoding="utf-8") as f:
    st = json.load(f)
a = sys.argv[1:]


def opt(name, many=False):
    vals = [a[i + 1] for i, x in enumerate(a) if x == name and i + 1 < len(a)]
    return vals if many else (vals[0] if vals else None)


def issue(n):
    return next(i for i in st["issues"] if i["number"] == int(n))


def save():
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, path)


cmd = a[:2]
if cmd == ["issue", "list"]:
    out = [{"number": i["number"], "title": i["title"], "state": i["state"], "body": i["body"],
            "labels": [{"name": l} for l in i["labels"]]} for i in st["issues"]]
    print(json.dumps(out))
elif cmd == ["issue", "edit"]:
    i = issue(a[2])
    for l in opt("--remove-label", True):
        if l in i["labels"]:
            i["labels"].remove(l)
    for l in opt("--add-label", True):
        if l not in i["labels"]:
            i["labels"].append(l)
    save()
elif cmd == ["issue", "comment"]:
    issue(a[2])["comments"].append(opt("--body"))
    save()
elif cmd == ["issue", "close"]:
    i = issue(a[2])
    i["state"] = "CLOSED"
    if opt("--comment"):
        i["comments"].append(opt("--comment"))
    save()
elif cmd == ["issue", "view"]:
    print(issue(a[2])["title"])
elif cmd == ["label", "create"]:
    if a[2] not in st["labels"]:
        st["labels"].append(a[2])
    save()
else:
    sys.stderr.write("fake gh: unsupported: " + " ".join(a) + "\n")
    sys.exit(1)
