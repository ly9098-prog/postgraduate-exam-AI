# ADR-0001: Logical Control Plane

**Status:** Accepted (2026-07-18)

## Context

Pipeline orchestration logic was scattered across `pipeline_orchestrator.py` (6409 lines), environment variables, global config, diagnostics dicts, and temporary data structures. There was no unified context object for pipeline execution, making it hard to trace, resume, or audit a specific run.

## Decision

Introduce a `PipelineExecutionContext` dataclass that carries all run-scoped state (fingerprints, quotas, feature flags, trace/metrics collectors) and an `OCRControlPlane` facade that manages job lifecycle. The control plane is purely logical — no new services or DB tables.

Key design choices:
- Feature flags are frozen at context creation, not read from env mid-run
- Context is serializable (no tokens, DB connections, or large byte blobs)
- Quota checks return typed error codes, not silent truncation
- `CONTROL_PLANE_MODE=legacy|facade` (default: facade)

## Alternatives

- **Distributed control plane** (separate service): Rejected — violates Sprint 4A constraint of no new microservices
- **Global state singleton**: Rejected — not testable, not resumable
- **Keep env-var-per-stage**: Rejected — resume would use wrong config

## Consequences

- Pipeline stages no longer read `os.environ` directly
- Resume restores the original context, not current env
- Trace and metrics share the same `pipeline_id` across all stages

## Rollout

`CONTROL_PLANE_MODE=facade` by default. Set to `legacy` for old behavior.

## Rollback

Unset `CONTROL_PLANE_MODE` or set to `legacy`.

## Metrics

- Stage latency recorded via `MetricsCollector`
- Trace events via `TraceCollector` → aggregated into final artifact

## Legacy Removal Criteria

When all pipelines use `facade` mode and no stage reads env vars directly.

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
