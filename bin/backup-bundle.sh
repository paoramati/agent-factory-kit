#!/usr/bin/env bash
# backup-bundle.sh: write a full-history git bundle to a backup folder and prune old ones.
# Usage: backup-bundle.sh <repo-path> <backup-dir> [keep=14]
# Restore: git clone <file>.bundle restored-repo
# Schedule (cron, every 2 hours):
#   0 */2 * * * /path/to/backup-bundle.sh ~/code/myrepo "$HOME/OneDrive/backups/myrepo" 24
set -euo pipefail
repo="${1:?repo path}"; dest="${2:?backup dir}"; keep="${3:-14}"
cd "$repo"
name="$(basename "$(git rev-parse --show-toplevel)")"
mkdir -p "$dest"

# Include tracker data that lives outside git objects (beads stores issues in Dolt).
if command -v bd >/dev/null 2>&1 && [[ -d .beads ]]; then
  bd export -o .beads/backup-export.jsonl >/dev/null 2>&1 || true
  cp .beads/backup-export.jsonl "$dest/$name-issues-latest.jsonl" 2>/dev/null || true
fi

# Uncommitted work is not in a bundle; snapshot it as a patch alongside.
stamp="$(date +%Y%m%d-%H%M%S)"
if ! git diff --quiet HEAD 2>/dev/null; then
  git diff HEAD > "$dest/$name-$stamp-uncommitted.patch"
fi

tmp="$dest/.$name-$stamp.bundle.tmp"
git bundle create "$tmp" --all 2>/dev/null
git bundle verify "$tmp" >/dev/null 2>&1
mv "$tmp" "$dest/$name-$stamp.bundle"
echo "wrote $dest/$name-$stamp.bundle"

# Prune: keep the newest $keep bundles and patches.
ls -1t "$dest"/"$name"-*.bundle 2>/dev/null | tail -n +"$((keep+1))" | xargs -r rm -f
ls -1t "$dest"/"$name"-*-uncommitted.patch 2>/dev/null | tail -n +"$((keep+1))" | xargs -r rm -f
