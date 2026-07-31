# Local OCR Worker Operations Guide

## Daily Operations

### Check Worker Status
```bash
sudo systemctl status ocr-worker
journalctl -u ocr-worker -n 50 --no-pager
```

### View Current Job
```bash
# Check worker logs for current job_id
journalctl -u ocr-worker | grep "Claimed job\|Processing job"

# Query job status via API
curl -s -H "Worker-API-Key: $(sudo cat /opt/2240ai-v2/deploy/ocr-worker/ocr-worker.env | grep OCR_WORKER_API_KEY | cut -d= -f2)" \
  https://xzshub.top/api/internal/ocr-worker/jobs
```

### View Lease Status
```bash
# Check database for active leases
cd /opt/2240ai-v2/backend && source .venv/bin/activate
PYTHONPATH=. python -c "
import asyncio
from app.core.database import async_session
from app.models.ocr_job import OCRJob
from sqlalchemy import select

async def check():
    async with async_session() as db:
        result = await db.execute(select(OCRJob).where(OCRJob.status == 'leased'))
        for job in result.scalars():
            print(f'Job {job.id}: leased by {job.lease_owner}, expires {job.lease_expires_at}')
asyncio.run(check())
"
```

### View CircuitBreaker Status
```bash
cat /data/ocr-worker/.circuit_breaker.json 2>/dev/null || echo "No circuit breaker state"
```

### List Workers
```bash
# Via server API
curl -s https://xzshub.top/api/admin/v1/ocr-workers | python -m json.tool
```

## Maintenance

### Clean Workspace
```bash
# Remove completed job workspaces older than retention period
find /data/ocr-worker/jobs -name "manifest.json" -mtime +3 -exec dirname {} \; | xargs rm -rf
```

### Restart Worker
```bash
sudo systemctl restart ocr-worker
journalctl -u ocr-worker -n 20 -f
```

### Stop Worker (Graceful)
```bash
sudo systemctl stop ocr-worker
# Wait for current job to finish or lease to expire
```

### Upgrade Worker
```bash
# 1. Sync code
cd /opt/2240ai-v2 && git pull

# 2. Restart
sudo systemctl restart ocr-worker
```

### Rotate Credential
```bash
cd /opt/2240ai-v2/backend
source .venv/bin/activate
PYTHONPATH=. python -c "
import asyncio
from app.services.worker_credential_service import rotate_credential
from app.core.database import async_session

async def rotate(cred_id):
    async with async_session() as db:
        result = await rotate_credential(db, cred_id)
        if result:
            new_cred, new_key = result
            print(f'New credential: {new_cred.id}')
            print(f'New API Key: {new_key}')
            print('Update ocr-worker.env with this key!')
asyncio.run(rotate('<credential-id>'))
"

# Then update ocr-worker.env with new key
sudo systemctl restart ocr-worker
```

### Migrate Database
```bash
cd /opt/2240ai-v2/backend
source .venv/bin/activate
PYTHONPATH=. alembic upgrade head
```

## Monitoring

### Key Metrics
| Metric | Source | Warning | Critical |
|--------|--------|---------|----------|
| GPU memory | `nvidia-smi` | > 3.2 GB | > 3.6 GB |
| Worker RSS | `systemctl status` | > 1 GB | > 1.5 GB |
| Job latency | Worker logs | > 5 min/page | > 10 min/page |
| Heartbeat gap | `last_heartbeat_at` | > 120s | > 300s |
| Circuit state | `.circuit_breaker.json` | half_open | open |
| Workspace usage | `du -sh /data/ocr-worker` | > 10 GB | > 18 GB |

### Log Levels
- `--verbose`: DEBUG level logging (all requests)
- Default: INFO level (job lifecycle events)
- Errors are always logged at ERROR level
