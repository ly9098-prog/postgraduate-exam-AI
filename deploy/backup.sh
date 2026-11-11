#!/usr/bin/env bash
# 22408AI — legacy backup entry
# Current backup entry: bash deploy/scripts/backup.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

cat >&2 <<'EOF'
[WARN] deploy/backup.sh is a legacy compatibility entry.
[WARN] Use deploy/scripts/backup.sh for current production backups.
EOF

exec bash deploy/scripts/backup.sh "$@"
