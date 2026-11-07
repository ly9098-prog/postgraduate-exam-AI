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

- Existing pipelines that don't specify a profile follow the environment default: `LOCAL_IMPORT` outside production and `CLOUD_API` when `APP_ENV=production`.
- `DEPLOYMENT_PROFILE` env var sets the global default; per-request override via API parameter.

## Rollout

`DEPLOYMENT_PROFILE=local_import` is used for local/import workloads. Production must use `APP_ENV=production` together with `DEPLOYMENT_PROFILE=cloud_api`; the application rejects conflicting combinations.

## Rollback

Set `DEPLOYMENT_PROFILE=local_import` or remove the env var.

## Metrics

- Profile selection recorded in pipeline trace
- `test_deployment_profile_*` verifies capability restrictions per profile
- Cloud OOM incidents should drop to zero after rollout

## Failure modes

- Unknown or conflicting profile value: startup fails closed with a configuration error
- Missing `RuntimeCapabilities`: profile falls back to conservative assumptions (CLOUD_API-like)
- Profile mismatch with the environment is treated as a deployment/configuration error, not silently downgraded

## Removal criteria

When the deployment model is replaced by a different abstraction or the cloud server is upgraded to match local hardware.

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]] — 生产发布与部署变更记录
- [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]] — 部署问题与修复记录
