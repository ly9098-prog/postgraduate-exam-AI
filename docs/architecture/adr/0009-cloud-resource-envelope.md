# ADR-0009: Cloud Resource Envelope

**Status:** Accepted (2026-07-18)

## Context

The 2C/2G cloud server must never OOM. Previous approach had no hard limits per request. PageStream, OCR responses, and concurrent pages could silently consume unbounded memory.

## Decision

`ResourceGuard` enforces per-pipeline budgets before work begins:

- `max_pages`: hard limit on total pages processed per pipeline (default: 50 for cloud, 500 for local)
- `max_input_bytes`: PDF/file size limit before any rendering (default: 50 MB for cloud, 500 MB for local)
- `max_pixel_budget`: total pixel area across all rendered pages (default: 50 MP for cloud, 500 MP for local)
- `concurrency`: maximum parallel page workers (default: 1 for cloud, 4 for local)
- `remote_ocr_calls`: maximum outbound OCR API calls per pipeline (default: 50 for cloud, unlimited for local)

PageStream defaults to `window=1`, `overlap=0` for `CLOUD_API` profile. Limits are checked before work begins, not retroactively — a pipeline that exceeds `max_pages` is rejected at creation time, not at page 51.

## Alternatives

- **Soft limits with warnings**: Rejected — still leads to OOM under memory pressure
- **mlock/resource.setrlimit**: Rejected — not portable across OS and container runtimes
- **Per-page garbage collection only**: Rejected — cannot prevent aggregate OOM from accumulated artifacts

## Consequences

- Cloud OOM risk is eliminated at the cost of rejecting oversized imports
- Oversized rejections surface clear error messages with actionable guidance
- Budgets are configurable per profile and per tenant if needed in the future
- ResourceGuard emits trace events for all budget checks, enabling operational dashboards

## Compatibility

- Existing pipelines with no explicit budget inherit conservative defaults per profile
- Pipeline API returns clear error codes for budget violations (413 Payload Too Large semantics)
- `CLOUD_API` profiles that previously processed >50 pages will need manual batching

## Rollout

Enabled by default for both profiles. Emergency override via `RESOURCE_GUARD_DISABLED=true` (not recommended).

## Rollback

Set `RESOURCE_GUARD_DISABLED=true`. Individual budgets can also be relaxed via config without full disable.

## Metrics

- `test_resource_guard_budget.py`: verifies each budget independently
- `test_resource_guard_cloud_defaults.py`: verifies cloud-safe defaults
- Grafana dashboard showing budget utilization and rejection counts
- OOM incident counter (target: zero after rollout)

## Failure modes

- Bug in budget calculation: budget 0 rejects all pipelines. Fail-open behavior: if guard raises an unexpected exception, log and allow the pipeline (safety valve).
- Budget mismatch with actual hardware: adjust config values, no code change needed.
- Race condition on shared counter: use atomic increments only (no lock needed for budget checks).

## Removal criteria

When the cloud server hardware is upgraded to match local capacity and unbounded processing is safe, or when a different resource management system replaces `ResourceGuard`.
