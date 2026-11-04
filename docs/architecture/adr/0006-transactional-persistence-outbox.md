# ADR-0006: Transactional Persistence with Asset Outbox

**Status:** Accepted (2026-07-18)

## Context

Pipeline persistence mixed DB writes with filesystem operations (asset deletion, storage cleanup). A failure midway could leave orphaned assets or partially-committed DB state. There was no reliable mechanism for deferred cleanup.

## Decision

Introduce a two-phase persistence model:

1. **Transactional Coordinator**: DB writes (questions, reviews, artifacts, pipeline status) in a single DB transaction
2. **Asset Outbox**: deferred, retryable asset operations (delete, confirm, cleanup)

Outbox guarantees:
- Idempotency key prevents duplicate execution
- Lease mechanism for exclusive processing
- Heartbeat for long-running operations
- Exponential backoff retry
- Dead letter after 5 retries
- `PERSISTENCE_MODE=legacy|transactional_shadow|transactional` (default: legacy)

## Alternatives

- **Message queue (Redis/Celery/Kafka)**: Rejected — Sprint 4A constraint
- **Synchronous cleanup**: Rejected — DB failure would delete files without commit

## Consequences

- DB commit always precedes irreversible file operations
- Outbox retry is idempotent — no duplicate side effects
- Dead letter visibility for operational debugging

## Rollout

Default `legacy`. Switch to `transactional_shadow` for plan + compare mode.

## Rollback

Set `PERSISTENCE_MODE=legacy`.

## Metrics

- `test_asset_outbox.py`: retry, dead letter, lease behavior
- Fault injection: DB failure must NOT delete assets

## Legacy Removal Criteria

When all pipelines use `PERSISTENCE_MODE=transactional` and outbox covers all asset operations.

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
