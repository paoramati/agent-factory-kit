#!/usr/bin/env bash
# ci.sh: the gate for the kit itself. Exit non-zero on any failure.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
step() { printf '\n== %s ==\n' "$*"; }

step "Syntax"
for f in bin/*.sh hooks/*.sh tests/*.sh ci.sh; do bash -n "$f" || { echo "bash syntax error in $f"; exit 1; }; done
PYBIN=""; for c in python3 python; do $c -c 'import sys' >/dev/null 2>&1 && { PYBIN="$c"; break; }; done
[[ -n "$PYBIN" ]] || { echo "No working Python found"; exit 1; }
for f in bin/*.py tracker/*.py dashboard/*.py dashboard/tests/*.py; do $PYBIN -m py_compile "$f" || exit 1; done
echo ok

step "Windows pitfalls"
# The Windows Store python3 stub exists but fails; bare python3 invocations must go through py().
bad=$(grep -nE 'python3( -| "| <<|$)' bin/*.sh hooks/*.sh 2>/dev/null | grep -v 'for c in' || true)
[[ -z "$bad" ]] || { echo "bare python3 invocation (use the detected interpreter):"; echo "$bad"; exit 1; }
# Windows Python cannot launch an npm shim like bd by bare name.
bad=$(grep -nE 'subprocess\.[a-z]+\(\["(bd|npx|npm)"' bin/*.py tracker/*.py dashboard/*.py 2>/dev/null || true)
[[ -z "$bad" ]] || { echo "subprocess launches a shim by bare name (use shutil.which):"; echo "$bad"; exit 1; }
echo ok

step "Dashboard tests"
$PYBIN -m unittest discover -s dashboard/tests -t .

step "Loop test"
tests/loop-test.sh

printf '\nci.sh: all checks passed\n'
