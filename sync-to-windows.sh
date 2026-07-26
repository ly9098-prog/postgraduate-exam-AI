#!/usr/bin/env bash
# Sync WSL project to Windows filesystem (for Windows IDE / Git GUI access)
# Usage: ./sync-to-windows.sh
# Source: /home/lmh/projects/postgraduate-ai/
# Target: /mnt/d/workspace/postgraduate-ai/

set -euo pipefail

SRC="/home/lmh/projects/postgraduate-ai/"
DST="/mnt/d/workspace/postgraduate-ai/"

if [ ! -d "$DST" ]; then
    echo "Error: target directory $DST does not exist"
    exit 1
fi

rsync -av --delete \
    --exclude=.git \
    --exclude=.claude \
    \
    --exclude=.venv \
    --exclude=.venv-ocr-gpu \
    --exclude=.venv-ocr-gpu-330 \
    --exclude=.venv\* \
    --exclude=__pycache__ \
    --exclude=.pytest_cache \
    --exclude=.ruff_cache \
    --exclude=.mypy_cache \
    --exclude=.coverage \
    --exclude=coverage \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.egg-info' \
    \
    --exclude=node_modules \
    --exclude=.next \
    --exclude=dist \
    --exclude=build \
    \
    --exclude=.env \
    --exclude='.env.*' \
    --exclude='!env.example' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='*.crt' \
    \
    --exclude='*.db' \
    --exclude='*.sqlite' \
    --exclude='*.sqlite3' \
    --exclude='*.dump' \
    --exclude='*.backup' \
    --exclude='*.sql.gz' \
    \
    --exclude='*.log' \
    --exclude=logs \
    \
    --exclude=.staging \
    --exclude=.backend_cache \
    --exclude=tmp \
    --exclude=uploads \
    --exclude=static \
    --exclude=artifacts \
    --exclude=ocr_test \
    --exclude=backups \
    \
    --exclude=tests \
    --exclude=backend/tests \
    --exclude=prompts \
    \
    --exclude=.idea \
    --exclude=.vscode \
    --exclude='*.swp' \
    --exclude=.DS_Store \
    --exclude=Thumbs.db \
    \
    --exclude=pgdata \
    --exclude=redisdata \
    --exclude=deploy/logs \
    --exclude=deploy/nginx/ssl \
    \
    "$SRC" "$DST"

echo "Sync complete: $SRC -> $DST"