# ADR-0007: Dual Deployment Profile

**Status:** Accepted (2026-07-18)

## Context

Sprint 4A built the target architecture but didn't formalize the two deployment environments into a code-enforced profile system. The 16-core local workstation with RTX 3050 Ti and 2-core cloud server with 2 GB RAM need different capability sets.

## Decision

Introduce `DeploymentProfile` enum (`LOCAL_IMPORT`, `CLOUD_API`) frozen at pipeline creation, with `RuntimeCapabilities` describing the environment. Profile determines OCR adapters, PageStream config, concurrency, and data sync capability.

- Profile is selected once per pipeline run and frozen in `PipelineExecutionContext`
- `LOCAL_IMPORT` enables resource-intensive operations (full PaddleOCR, batch processing, local storage sync)
- `CLOUD_API` restricts to lightweight operations (remote-only OCR calls, minimal concurrency, no local storage)

## Alternatives

- **Detection at each call site**: Rejected — inconsistent behavior across stages
- **Single binary with auto-detection**: Rejected — wrong resource assumptions lead to OOM on cloud

## Consequences

- Pipeline behavior is deterministic given the profile
- Profile is recorded in pipeline audit trail for debugging
- `CLOUD_API` pipelines cannot accidentally trigger local OCR or unbounded processing

## Compatibility

- No breaking changes. Existing pipelines that don't specify a profile default to `LOCAL_IMPORT`.
- `DEPLOYMENT_PROFILE` env var sets the global default; per-request override via API parameter.

## Rollout

`DEPLOYMENT_PROFILE=local_import` (default on both environments). Set to `cloud_api` on the production server.

## Rollback

Set `DEPLOYMENT_PROFILE=local_import` or remove the env var.

## Metrics

- Profile selection recorded in pipeline trace
- `test_deployment_profile_*` verifies capability restrictions per profile
- Cloud OOM incidents should drop to zero after rollout

## Failure modes

- Unknown profile value: default to `LOCAL_IMPORT` with a warning
- Missing `RuntimeCapabilities`: profile falls back to conservative assumptions (CLOUD_API-like)
- Profile mismatch between env var and actual hardware: log a warning, proceed with requested profile

## Removal criteria

When the deployment model is replaced by a different abstraction or the cloud server is upgraded to match local hardware.
