#!/usr/bin/env bash
set -euo pipefail

# 2240AI local development server
#
# Default: PROCESS_ROLE=all — runs API + scheduler (export processor, etc.)
# Override: PROCESS_ROLE=web for web-only (export tasks NOT processed)
# Override: PROCESS_ROLE=scheduler for scheduler-only (no HTTP)
#
# Multi-process deployment (production):
#   PROCESS_ROLE=web   ./run.sh     # API server + WebSocket
#   PROCESS_ROLE=scheduler python -m app.scheduler_main  # background tasks

export APP_ENV="${APP_ENV:-development}"
export PROCESS_ROLE="${PROCESS_ROLE:-all}"

echo "==> Starting 2240AI (APP_ENV=${APP_ENV}, PROCESS_ROLE=${PROCESS_ROLE})"

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --reload
