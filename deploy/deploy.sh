#!/usr/bin/env bash
# 22408AI — legacy deployment entry
# Current production entry: bash deploy/scripts/deploy.sh "$@"

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

cat >&2 <<'EOF'
[WARN] deploy/deploy.sh is a legacy compatibility entry.
[WARN] Use deploy/scripts/deploy.sh for current production deployment.
EOF

exec bash deploy/scripts/deploy.sh "$@"
