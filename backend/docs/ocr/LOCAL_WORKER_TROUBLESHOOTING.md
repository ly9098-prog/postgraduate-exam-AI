# Local OCR Worker Troubleshooting Guide

## Worker Won't Start

### 1. Environment not activated
```bash
# Error: ModuleNotFoundError: No module named 'app'
source .venv-ocr-gpu/bin/activate
PYTHONPATH=. python -m app.ocr_worker.daemon
```

### 2. GPU environment broken
```bash
source .venv-ocr-gpu/bin/activate
python scripts/preflight_local_ocr_gpu.py
```
If `preflight` fails:
- Rebuild env: `bash scripts/setup_local_ocr_gpu_env.sh`
- Check NVIDIA driver: `nvidia-smi`
- Check CUDA compatibility: `python -c "import paddle; print(paddle.is_compiled_with_cuda())"`

### 3. API key invalid
```bash
# Verify the key works
curl -s -H "Worker-API-Key: local-ocr-01/$(cat deploy/ocr-worker/ocr-worker.env | grep OCR_WORKER_API_KEY | cut -d= -f2)" \
  https://xzshub.top/api/internal/ocr-worker/jobs
# Should return {"ok":true,"data":null} or job list
```

### 4. Server unreachable
```bash
curl https://xzshub.top/health
# Should return 200 OK
ping -c 1 xzshub.top
```

## Job Claim Fails

### No Pending Jobs
```bash
# Check if there are any pending jobs
curl -s https://xzshub.top/api/admin/v1/ocr-jobs?status=pending
```

### All Jobs Leased
```bash
# Check for expired leases
curl -s https://xzshub.top/api/admin/v1/ocr-jobs?status=leased
# Old leases should auto-expire after 5 minutes
```

## OCR Processing Issues

### GPU OOM
```text
Error: CUDA out of memory
```
Solutions:
1. Reduce `OCR_WORKER_GPU_MEMORY_LIMIT_MB` to 3000
2. Check for other GPU processes: `nvidia-smi`
3. Restart worker: `sudo systemctl restart ocr-worker`
4. If persistent, enable CPU fallback: `OCR_WORKER_CPU_FALLBACK=true`

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
