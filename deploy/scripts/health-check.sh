#!/bin/bash
# === 2240AI 健康检查脚本 ===
# 用法: ./deploy/scripts/health-check.sh [domain]
set -euo pipefail

TARGET="${1:-localhost}"
SCHEME="https"

if [ "$TARGET" = "localhost" ] || [ "$TARGET" = "127.0.0.1" ]; then
    SCHEME="http"
fi

BASE_URL="${SCHEME}://${TARGET}"
PASS=0
FAIL=0

check() {
    local name="$1"
    local url="$2"
    local expected_code="${3:-200}"

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "$expected_code" ]; then
        echo "  ✓ $name ($HTTP_CODE)"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $name (expected $expected_code, got $HTTP_CODE)"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== 2240AI 健康检查 ==="
echo "目标: $BASE_URL"
echo ""

# 1. HTTPS 证书
if [ "$SCHEME" = "https" ]; then
    echo "--- 证书检查 ---"
    CERT_EXPIRY=$(echo | openssl s_client -servername "$TARGET" -connect "$TARGET:443" 2>/dev/null | \
        openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$CERT_EXPIRY" ]; then
        echo "  ✓ 证书有效至: $CERT_EXPIRY"
        PASS=$((PASS + 1))
    else
        echo "  ✗ 证书检查失败"
        FAIL=$((FAIL + 1))
    fi
fi

echo ""
echo "--- 端点检查 ---"
check "Health Check"   "$BASE_URL/api/v1/health"
check "Version"        "$BASE_URL/api/v1/version"
check "Simple Health"  "$BASE_URL/health"

echo ""
echo "--- 结果 ---"
echo "通过: $PASS, 失败: $FAIL"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
