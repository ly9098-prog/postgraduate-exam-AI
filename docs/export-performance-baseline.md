# Export Performance Baseline

> Last updated: 2026-07-27
> Environment: WSL2 (Linux 6.6.114.1), Python 3.12.3
> CPU: Intel i7-14700K, RAM: 64 GB (WSL allocated ~16 GB)
> LibreOffice: Not installed in current environment

## Recommended Worker Configuration

| Parameter | Recommended | Notes |
|-----------|-------------|-------|
| `EXPORT_MAX_CONCURRENT` | 2 | 2 concurrent export tasks globally |
| `EXPORT_PDF_CONCURRENCY` | 1 | Serialize PDF generation (memory-bound) |
| `EXPORT_DOCX_CONCURRENCY` | 1 | Serialize DOCX generation |
| `EXPORT_IMAGE_DOWNLOAD_CONCURRENCY` | 4 | Parallel image downloads |
| `EXPORT_MAX_PER_USER` | 2 | Per-user active task limit |
| `EXPORT_TASK_TIMEOUT_SEC` | 600 | 10 min per task |
| `EXPORT_PROCESSING_TIMEOUT_SEC` | 900 | 15 min zombie threshold |
| `EXPORT_HEARTBEAT_INTERVAL_SEC` | 30 | Heartbeat every 30s |
| `GUNICORN_WORKERS` | 2 | For 2-core production server |

## Performance Estimates

### PDF Generation

| Questions | Est. Processing | Est. Output Size | Memory (RSS) |
|-----------|----------------|-----------------|--------------|
| 1 | < 1s | ~50 KB | ~80 MB |
| 10 | ~1-2s | ~100 KB | ~80 MB |
| 50 | ~3-5s | ~300 KB | ~80 MB |
| 100 (plain) | ~5-8s | ~500 KB | ~80 MB |
| 100 (image-heavy) | ~30-60s | ~10-50 MB | ~200 MB |
| 100 (formula-heavy) | ~10-20s | ~1-2 MB | ~100 MB |
| 100 (table-heavy) | ~8-15s | ~1 MB | ~100 MB |

### DOCX Generation

| Questions | Est. Processing | Est. Output Size | Memory (RSS) |
|-----------|----------------|-----------------|--------------|
| 1 | < 1s | ~60 KB | ~80 MB |
| 10 | ~1-2s | ~120 KB | ~80 MB |
| 50 | ~3-5s | ~350 KB | ~80 MB |
| 100 (plain) | ~5-10s | ~600 KB | ~80 MB |
| 100 (image-heavy) | ~30-60s | ~10-50 MB | ~200 MB |
| 100 (formula-heavy) | ~15-30s | ~2-5 MB | ~100 MB |
| 100 (table-heavy) | ~10-20s | ~1-2 MB | ~100 MB |

### Concurrency (5 simultaneous tasks)

| Scenario | Est. Throughput | Est. P95 Latency | Est. Peak RSS |
|----------|----------------|-----------------|---------------|
| 5x PDF 10q | ~2-3 tasks/min | ~30s | ~400 MB |
| 5x DOCX 10q | ~2-3 tasks/min | ~30s | ~400 MB |
| Mixed PDF+DOCX | ~2-3 tasks/min | ~45s | ~500 MB |
| Same user, 2 tasks | ~1 task/min | ~30s | ~200 MB |
| Multi-user (3 users) | ~3 tasks/min | ~30s | ~600 MB |

## Production 2-Core Server Constraints

**Critical limitations:**
- Maximum 2 concurrent processing tasks
- Each PDF/DOCX generation is single-threaded (fpdf2/python-docx)
- Image download is the primary IO bottleneck
- OMML conversion is lightweight (< 100ms per formula)
- Memory: expect peak RSS ~500 MB under concurrent load
- Disk: temp files ~50 MB per task

## P95/P99 Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Processing time (100q PDF) | > 30s | > 60s |
| Processing time (100q DOCX) | > 30s | > 60s |
| Queue wait time | > 120s | > 300s |
| Image download failure rate | > 5% | > 20% |
| OMML fallback rate | > 10% | > 50% |
| Export success rate | < 95% | < 90% |
| Zombie tasks | > 0 | > 3 |
| Pending queue depth | > 20 | > 50 |

## Production Deployment Notes

```bash
# Install LibreOffice for DOCX acceptance
apt-get install -y libreoffice-writer fonts-wqy-zenhei fonts-wqy-microhei

# Verify fonts installed
fc-list | grep -i wqy

# Performance test command
cd /opt/2240ai-v2/backend
.venv/bin/python -m pytest tests/test_export*.py -v --tb=short
```
