#!/bin/bash
# Run 2C/2G Cloud Profile Validation — Requires production-equivalent container.
#
# Usage:
#   bash scripts/run_cloud_2c2g_validation.sh
#
# Output:
#   reports/sprint4c/cloud_2c2g_startup.json
#   reports/sprint4c/cloud_2c2g_memory.json
#   reports/sprint4c/cloud_2c2g_readiness.md
#
# Environment requirements:
#   - CPU limit: 2 cores
#   - Memory limit: 2 GB
#   - Swap: disabled
#   - GPU: none
#   - DEPLOYMENT_PROFILE=cloud_api

set -euo pipefail

REPORTS_DIR="reports/sprint4c"
mkdir -p "$REPORTS_DIR"

echo "=== 2C/2G Cloud Profile Validation ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "CPU: $(nproc) cores"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"
echo ""

# Check environment constraints
CPU_COUNT=$(nproc)
MEM_TOTAL_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
MEM_TOTAL_MB=$((MEM_TOTAL_KB / 1024))

if [ "$CPU_COUNT" -gt 4 ]; then
    echo "WARNING: CPU count ($CPU_COUNT) exceeds 2C constraint."
    echo "  Run this script in a 2C-limited container for accurate results."
fi

if [ "$MEM_TOTAL_MB" -gt 3000 ]; then
    echo "WARNING: Memory ($MEM_TOTAL_MB MB) exceeds 2 GB constraint."
    echo "  Run this script in a 2 GB-limited container for accurate results."
fi

# Startup memory measurement
echo ""
echo "=== Startup RSS ==="
export DEPLOYMENT_PROFILE=cloud_api

/usr/bin/time -v python -c "
import sys, os
os.environ['DEPLOYMENT_PROFILE'] = 'cloud_api'
import app.core.config
import app.core.deployment_profile
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile
profile = detect_deployment_profile()
caps_import = __import__('app.features.runtime_capabilities', fromlist=['build_runtime_capabilities'])
caps = caps_import.build_runtime_capabilities(profile)
print(f'Profile: {profile.value}')
print(f'GPU available: {caps.gpu_available}')
print(f'Local OCR allowed: {caps.local_ocr_allowed}')
print(f'Batch import allowed: {caps.batch_import_allowed}')
print(f'Database sync allowed: {caps.database_sync_allowed}')
print(f'PageStream window: {caps.page_stream_window_size}')
" 2>&1 | tee "$REPORTS_DIR/cloud_2c2g_startup_measurement.txt"

echo ""
echo "=== Startup Report ==="
python -c "
import json, os
report = {
    'environment': '2c2g_cloud',
    'cpu_count': $CPU_COUNT,
    'memory_total_mb': $MEM_TOTAL_MB,
    'deployment_profile': 'cloud_api',
    'startup_measurement_file': 'cloud_2c2g_startup_measurement.txt',
    'note': 'Full memory profiling requires real 2C/2G production container',
    'resource_guard_limits': {
        'max_concurrent_documents': 1,
        'max_concurrent_pages': 1,
        'page_stream_window_size': 1,
        'page_stream_overlap': 0,
        'max_rendered_page_cache': 1,
    },
    'test_status': 'environment_not_available' if $MEM_TOTAL_MB -gt 3000 else 'needs_production_container',
}
os.makedirs('$REPORTS_DIR', exist_ok=True)
with open('$REPORTS_DIR/cloud_2c2g_startup.json', 'w') as f:
    json.dump(report, f, indent=2)
print(f'Wrote $REPORTS_DIR/cloud_2c2g_startup.json')
"

echo ""
echo "=== Readiness ==="
cat > "$REPORTS_DIR/cloud_2c2g_readiness.md" << 'MDEOF'
# 2C/2G Cloud Profile Readiness

Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)

## Environment Status: ENVIRONMENT_NOT_AVAILABLE

This validation requires a production-equivalent container with:
- CPU: 2 cores
- Memory: 2 GB
- Swap: disabled
- GPU: none

## Required Tests (not executed)

1. Service cold start RSS
2. Service warm start RSS
3. Health check
4. Single page image request
5. 10-page PDF
6. 50-page PDF
7. 20 consecutive serial requests
8. 2 concurrent requests
9. Oversized file rejection
10. Oversized pixel rejection
11. Remote API timeout
12. Remote API 429
13. Task cancellation
14. Artifact Resume

## To Execute

Run in a container with:
```bash
docker run --cpus=2 --memory=2g --memory-swap=2g \\
  -e DEPLOYMENT_PROFILE=cloud_api \\
  -e REMOTE_OCR_API_KEY=... \\
  -v /path/to/test-data:/data \\
  your-image:latest
```

Then run:
```bash
bash scripts/run_cloud_2c2g_validation.sh
```
MDEOF

echo "Wrote $REPORTS_DIR/cloud_2c2g_readiness.md"
echo ""
echo "=== Validation Complete ==="
echo "Results in $REPORTS_DIR/"
echo "NOTE: Full 2C/2G validation requires production container."
