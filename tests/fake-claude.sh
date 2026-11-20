#!/usr/bin/env bash
# Stand-in for `claude -p` used by loop-test.sh. Reads the ticket id from the prompt and acts by role.
# FAKE_ROLES is a file holding four ticket ids: A B C E.
#   A and B both rewrite shared.txt (a guaranteed conflict); C builds on both; E fails the gate once.
prompt="$2"
[[ -z "${FAKE_ARGS_LOG:-}" ]] || printf '%s\n' "$*" >> "$FAKE_ARGS_LOG"   # lets a test inspect the flags and prompt
id=$(printf '%s' "$prompt" | grep -o 'Ticket: [a-z0-9-]*' | head -1 | cut -d' ' -f2)
read -r ia ib ic ie iff < "$FAKE_ROLES"   # optional 5th id: a ticket that never passes the gate
{
  if [[ "$prompt" == *"left conflicts"* ]]; then
    printf 'line from A\nline from B\n' > shared.txt
    git add -A && git commit -qm "$id: resolve merge"
  else
    echo "work for $id" > "file-$id.txt"
    [[ "$id" == "$ia" ]] && echo "line from A" > shared.txt
    [[ "$id" == "$ib" ]] && echo "line from B" > shared.txt
    if [[ "$id" == "$ie" ]]; then
      if [[ "$prompt" == *"This is a continuation"* ]]; then rm -f BAD; else touch BAD; fi
    fi
    [[ -n "$iff" && "$id" == "$iff" ]] && touch BAD
    git add -A && git commit -qm "$id: work"
  fi
} >/dev/null 2>&1
echo '{"total_cost_usd":0.01,"result":"fake agent done"}'
