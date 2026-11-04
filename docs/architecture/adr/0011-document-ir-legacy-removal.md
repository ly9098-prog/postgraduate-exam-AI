# ADR-0011: DocumentIR Legacy Removal Criteria

**Status:** Accepted (2026-07-18)

## Context

DocumentIR is the canonical single source of truth, but `pipeline_orchestrator.py` still has 13 production write violations (`blocks_to_normalized`, `normalized_blocks` access). Legacy raw fields (`rec_texts`, `dt_polys`) are still accessed in production read paths.

## Decision

Two-phase migration:

**Phase 1 (this sprint):** Classify all legacy access sites into four categories:
- **Adapter-allowed**: raw field reads inside OcrAdapter implementations (legitimate, wrapped by Gateway)
- **Production write violations**: writes to legacy fields (`blocks_to_normalized`, `normalized_blocks`) — 13 sites in `pipeline_orchestrator.py`
- **Production read violations**: reads from legacy fields (`rec_texts`, `dt_polys`) — documented for migration
- **Test-only violations**: test code referencing legacy formats — migrated separately

**Phase 2 (future):** Migrate all production write violations to DocumentIR paths. Once migrated, switch `DOCUMENT_IR_SSOT_MODE=ir` to disable legacy compatibility views.

During migration, legacy blocks remain as a read-only compatibility view via `document_ir_to_blocks()`. Write access to legacy fields is tracked and logged.

## Alternatives

- **Big-bang rewrite**: Rejected — breaks all active pipelines, too risky mid-sprint
- **Keep forever**: Rejected — technical debt grows, new stages will continue using raw blocks
- **Runtime deprecation warnings only**: Rejected — no enforcement, violations accumulate

## Consequences

- Phase 1 produces an inventory with owners and migration effort estimates
- Phase 2 removes legacy writes without changing pipeline behavior
- After `DOCUMENT_IR_SSOT_MODE=ir`, legacy raw fields are removed from `ModuleResult`
- Migration can be parallelized across team members by site classification

## Compatibility

- No API contract changes during Phase 1. Read-only compat view preserves behavior for all external consumers.
- Phase 2 migration is backwards compatible until `DOCUMENT_IR_SSOT_MODE=ir`.
- Test fixtures that depend on legacy format get updated during Phase 1 test classification.

## Rollout

Phase 1 artifacts are documentation-only (no mode switch). Phase 2 moves through the existing `DOCUMENT_IR_SSOT_MODE` lifecycle: `dual` → `ir`.

## Rollback

Before `DOCUMENT_IR_SSOT_MODE=ir`: revert individual migration commits. After switching to `ir`: set `DOCUMENT_IR_SSOT_MODE=dual`.

## Metrics

- Violation count tracked per sprint (target: 0 for Phase 1 complete)
- `scripts/audit_document_ir_boundaries.py` runs in CI
- `test_document_ir_ssot_boundaries.py` regression suite passes before and after each migration
- Line count of legacy field access (target: 0 for Phase 2 complete)

## Failure modes

- Phase 2 migration breaks a legacy consumer: `DOCUMENT_IR_SSOT_MODE=dual` catches it before write paths diverge
- Forgotten write site: audit script flags it, migration continues with site documented as exception
- Oversized `ModuleResult.raw` (exceeds 100KB): redacted in trace, logged for cleanup

## Removal criteria

- All 13 production write violations migrated to DocumentIR paths
- `pipeline_orchestrator.py` no longer accesses `_ocr_scanned_pdf()` or `OCRFixResult`
- All coordinators and pipeline stages accept `DocumentIR` as their input
- `document_ir_to_blocks()` is removed
- `DOCUMENT_IR_SSOT_MODE=ir` is the default and only supported mode

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
