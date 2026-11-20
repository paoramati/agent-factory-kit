#!/usr/bin/env bash
# lockdown-remote.sh: make a repo unable to push, in two independent ways.
#   1. Every remote's push URL is replaced with an invalid value (fetch still works).
#   2. A pre-push hook refuses every push, even to a newly added remote.
# Usage: lockdown-remote.sh [repo-path]
# Undo:  git remote set-url --push <remote> <url>; delete .git/hooks/pre-push
set -euo pipefail
repo="${1:-.}"
cd "$repo"
git rev-parse --git-dir >/dev/null

for r in $(git remote); do
  git remote set-url --push "$r" "DISABLED-by-lockdown-remote"
  echo "remote '$r': push URL disabled"
done

hooks_dir="$(git rev-parse --git-path hooks)"
mkdir -p "$hooks_dir"
cat > "$hooks_dir/pre-push" <<'HOOK'
#!/bin/sh
echo "pre-push: pushing is disabled in this repository (lockdown-remote.sh)." >&2
echo "Push manually from a reviewed clone if this change should be shared." >&2
exit 1
HOOK
chmod +x "$hooks_dir/pre-push"
echo "pre-push hook installed at $hooks_dir/pre-push"

# Worktrees share hooks with the main repo, so this covers agent worktrees too.
echo "Done. Verify with: git remote -v && git push --dry-run (should fail)"
