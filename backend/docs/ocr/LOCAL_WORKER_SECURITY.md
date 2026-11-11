# Local OCR Worker Security Guide

## Credential Management

### Key Principles
1. **Plaintext keys are never stored** — only SHA-256 hashes in the database
2. **Raw key is shown once** — at credential creation time
3. **Constant-time comparison** — prevents timing side-channel attacks
4. **Per-worker credentials** — each worker has a unique key
5. **Rotation support** — old keys are disabled, not deleted

### Credential Lifecycle
```
Create ──► Active ──► Rotated ──► Disabled (old)
                      │
                      └──► New Active credential
```

### File Permissions
| File | Permission | Owner |
|------|-----------|-------|
| `ocr-worker.env` | `0600` | `ocr-worker` |
| `ocr-worker.service` | `0644` | `root` |
| `worker_credentials` (DB) | N/A (DB access) | `app` user |

### Environment File Security
```bash
chmod 600 /opt/22408-ai/deploy/ocr-worker/ocr-worker.env
chown ocr-worker:ocr-worker /opt/22408-ai/deploy/ocr-worker/ocr-worker.env
```

## Network Security

### API Access
- All internal endpoints require `Worker-API-Key` header
- Worker has NO access to admin or public APIs
- Token is scoped: `worker-id/token` format
- Input download URLs are short-lived (signed)
- Job completion verifies lease ownership

### No Direct Database Access
The worker does NOT connect to the production database:
- All state is managed via the server API
- Leases are server-authoritative
- Workspace is local-only

## Audit Trail

### Logged Events
- Job claim (worker_id, job_id, timestamp)
- Heartbeat (job_id, timestamp)
- Job complete (job_id, output_hash)
- Job failure (job_id, error_code)
- Credential rotation (worker_id, old_cred_id, new_cred_id)

### Not Logged
- Plaintext API keys
- Signed URLs
- Document content (only hashes)
- Worker workspace paths

## Incident Response

### Compromised Key
1. Rotate credential immediately
2. Verify no unauthorized job claims
3. Check audit log for suspicious activity
4. Update `ocr-worker.env` on all affected workers
5. Restart workers

### Worker Offline (Suspicious)
1. Check `systemctl status ocr-worker`
2. Review last heartbeat timestamp
3. Check CircuitBreaker state
4. Verify network connectivity
5. Review auth logs for the worker
