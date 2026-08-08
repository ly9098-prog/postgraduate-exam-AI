#!/usr/bin/env bash
# Sync WSL project to Windows filesystem (for Windows IDE access).
#
# Exclude strategy:
#   1. --exclude-from=.gitignore  — single source of truth for repo ignores
#      (auto-stays in sync when .gitignore changes; verified no tracked file
#       is gitignored, so source code is never dropped).
#   2. inline "extra" patterns — IDE-copy-specific dirs not covered by
#      .gitignore (prompts/tests/artifacts, venv variants, generated assets).
#
# NOTE: `.git` is intentionally NOT synced — git stays in WSL. The Windows copy
# is a plain file mirror for editing, not a git checkout.
#
# Usage:
#   ./sync-to-windows.sh          # sync
#   ./sync-to-windows.sh -n       # dry-run: preview what would change / delete

set -euo pipefail

# Location-independent: resolve repo root from this script's path, so it works
# when invoked from any directory (and the exclude-from path stays correct).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/"
DST="/mnt/d/workspace/postgraduate-ai/"

# Arg parsing: -n / --dry-run passthrough (rsync -n prints a plan, writes nothing).
DRYRUN=0
case "${1:-}" in
  -n|--dry-run) DRYRUN=1 ;;
  -h|--help) sed -n '1,12p' "$0"; exit 0 ;;
  "") ;;
  *) echo "usage: $0 [-n|--dry-run]" >&2; exit 1 ;;
esac

[ -d "$DST" ] || { echo "error: target directory $DST does not exist" >&2; exit 1; }

# -rtl instead of -a: destination is /mnt/d (drvfs/NTFS) with no real
# owner/group/perm bits. `-a` triggers chown/chmod errors on drvfs and can flip
# files read-only in Windows. Times (-t) are kept so re-runs stay incremental.
# --delete-after  : delete dest-only files only AFTER a successful transfer.
# --partial       : interrupted transfers keep partials and resume next run.
ARGS=(-rtlv --delete --delete-after --partial)
[ "$DRYRUN" -eq 1 ] && ARGS+=(-n)

# backend/static is gitignored wholesale, but question-assets holds generated
# preview images needed for local render checks. Include the dir BEFORE the
# .gitignore merge (first-match-wins; a re-include after it is pruned).
rsync "${ARGS[@]}" \
    --filter='+ backend/static/' \
    --filter='+ backend/static/question-assets/' \
    --filter='- backend/static/formulas/' \
    --filter='- backend/static/exports/' \
    --filter='- backend/static/*' \
    --exclude-from="${SCRIPT_DIR}/.gitignore" \
    \
    --exclude='.git' \
    --exclude='.venv*' \
    --exclude=prompts \
    --exclude=tests \
    --exclude=artifacts \
    --exclude=backups \
    --exclude=static/staging \
    --exclude=deploy/nginx/ssl \
    "$SRC" "$DST"

if [ "$DRYRUN" -eq 1 ]; then
    echo "Dry-run complete: $SRC -> $DST (no changes written)"
else
    echo "Sync complete: $SRC -> $DST"
fi
