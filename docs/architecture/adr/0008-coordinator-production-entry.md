# ADR-0008: Coordinator Pipeline as Production Entry

**Status:** Accepted (2026-07-18)

## Context

Sprint 4A created coordinator facades and Sprint 4B a `CoordinatorPipeline` integration layer, but the production import API still calls `pipeline_orchestrator` directly.

## Decision

Introduce `PIPELINE_COORDINATOR_MODE=legacy|shadow|coordinator`:

- **legacy**: `pipeline_orchestrator` is the primary entry point (existing behavior)
- **shadow**: runs old pipeline (real) + coordinator plan (dry-run, no real OCR/AI/persistence)
- **coordinator**: `CoordinatorPipeline` becomes the primary entry, legacy path is bypassed
- Legacy path retained for rollback in all modes

## Alternatives

- **Fork orchestrator**: Rejected — too risky, splits maintenance
- **Replace in one PR**: Rejected — no rollback path if issues are discovered post-deployment

## Consequences

- Shadow mode validates coordinator equivalence without production risk
- Migration can be done incrementally per deployment profile (`LOCAL_IMPORT` first, `CLOUD_API` later)
- Trace output from shadow runs is logged but not persisted as pipeline results
- Legacy orchestrator can be fully removed once both profiles pass coordinator mode for N days

## Compatibility

- No API contract changes. The import endpoint signature is identical across all modes.
- Shadow mode adds ~10% overhead per request (plan computation without execution).
- Legacy `pipeline_orchestrator` features remain accessible under `legacy` mode.

## Rollout

Default `legacy`. Set to `shadow` on the local machine for equivalence testing. Set to `coordinator` after validation.

## Rollback

Set `PIPELINE_COORDINATOR_MODE=legacy`. No data migration required since shadow mode writes nothing.

## Metrics

- `test_coordinator_shadow_equivalence.py`: every shadow run compares decisions and reports mismatches
- Latency delta between legacy and coordinator paths
- Mismatch rate trending to zero before coordinator mode is enabled

## Failure modes

- Shadow mode detects a mismatch: log error, continue with legacy result (shadow must not fail the request)
- Coordinator pipeline init failure: fall back to legacy automatically with a warning
- Shadow mode timeout: do not block the legacy pipeline response

## Removal criteria

When all production pipelines run in `coordinator` mode and `legacy` mode has zero callers for N consecutive days.
