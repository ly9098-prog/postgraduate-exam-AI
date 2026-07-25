#!/usr/bin/env bash

set -euo pipefail

WINDOWS_HOST="$(ip route show default | awk '{print $3; exit}')"

if [[ -z "${WINDOWS_HOST}" ]]; then
    echo "无法获取 Windows WSL NAT 主机地址" >&2
    return 1 2>/dev/null || exit 1
fi

export OCR_EXECUTION_BACKEND="paddlex_http"
export OCR_REMOTE_URL="http://${WINDOWS_HOST}:8080/ocr"
export OCR_REMOTE_MAX_CONCURRENCY="1"
export OCR_USE_GPU="false"

echo "OCR_REMOTE_URL=${OCR_REMOTE_URL}"
