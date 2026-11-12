# Local OCR Worker Troubleshooting Guide

## Worker Won't Start

### 1. Environment not activated
```bash
# Error: ModuleNotFoundError: No module named 'app'
source .venv-ocr-gpu-330/bin/activate
PYTHONPATH=. python -m app.ocr_worker.daemon
```

### 2. API key invalid
```bash
# Verify the key works
curl -s -H "Worker-API-Key: local-ocr-01/$(cat deploy/ocr-worker/ocr-worker.env | grep OCR_WORKER_API_KEY | cut -d= -f2)" \
  https://your-production-domain.example/api/internal/ocr-worker/jobs
# Should return {"ok":true,"data":null} or job list
```

### 3. Server unreachable
```bash
curl https://your-production-domain.example/health
# Should return 200 OK
ping -c 1 your-production-domain.example
```

## Job Claim Fails

### No Pending Jobs
```bash
# Check if there are any pending jobs
curl -s https://your-production-domain.example/api/admin/v1/ocr-jobs?status=pending
```

### All Jobs Leased
```bash
# Check for expired leases
curl -s https://your-production-domain.example/api/admin/v1/ocr-jobs?status=leased
# Old leases should auto-expire after 5 minutes
```

## OCR Processing Issues

### Slow Inference
```text
OCR takes a long time per image
```
Solutions:
1. Worker runs in the isolated `.venv-ocr-gpu-330` environment
2. Reduce concurrency / queue depth if memory constrained
3. Restart worker: `sudo systemctl restart ocr-worker`

### PaddleOCR Model Download Fails
```text
Error: Failed to download model
```
Solutions:
1. Check network: `curl -s -o /dev/null -w "%{http_code}" https://paddleocr.bj.bcebos.com`
2. Manual download: `python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=True)"`
3. Use pre-downloaded model cache from another machine

### Process Crash
```text
Executor subprocess died (pid=12345): Signal 11 (SIGSEGV)
```
Actions:
1. Check GPU memory at time of crash
2. Check for driver issues: `dmesg | grep -i nvidia`
3. Restart worker: `sudo systemctl restart ocr-worker`
4. If recurring, reduce `OCR_WORKER_MAX_TASKS_PER_CHILD`

## Upload Issues

### Upload Timeout
```text
Error: Upload timeout after 300s
```
Actions:
1. Check server disk space
2. Check network bandwidth
3. Reduce result size by adjusting DocumentIR settings

### Upload Rejected (Hash Mismatch)
```text
Error: 409 Conflict — output_sha256 mismatch
```
Actions:
1. The result artifact was corrupted during upload
2. Worker will retry with same output (no re-OCR)
3. If persistent, check disk integrity

## Workspace Issues

### Disk Full
```bash
# Check workspace usage
du -sh /data/ocr-worker/

# Clean old workspaces
find /data/ocr-worker/jobs -name "manifest.json" -mtime +1 -exec dirname {} \; | xargs rm -rf

# Check retention setting
grep OCR_WORKER_RESULT_RETENTION_HOURS deploy/ocr-worker/ocr-worker.env
```

### Permission Denied
```bash
sudo chown -R ocr-worker:ocr-worker /data/ocr-worker/
```

## Circuit Breaker Open

When the circuit breaker is open, the worker will not claim new jobs.

### Check Status
```bash
cat /data/ocr-worker/.circuit_breaker.json
```

### Reset
```bash
# Delete the circuit breaker state file
rm /data/ocr-worker/.circuit_breaker.json
sudo systemctl restart ocr-worker
```

### Prevent Recurrence
1. Review worker logs for root cause:
   ```bash
   journalctl -u ocr-worker | grep -i "error\|fail\|crash\|OOM"
   ```
2. Fix underlying issue before resetting
