# ADR-0002: DocumentIR as Single Source of Truth

**Status:** Accepted (2026-07-18)

## Context

The pipeline historically used multiple intermediate formats: raw OCR blocks (`rec_texts`/`dt_polys`), normalized blocks, `PageStructure`, frozen option registries, and `DocumentIR`. New stages could use any of these, creating data inconsistency risks.

## Decision

DocumentIR is the canonical single source of truth (SSOT) for all pipeline stages. Legacy formats (`blocks`, `normalized_blocks`) become read-only compatibility views.

- `DocumentIR` → `document_ir_to_blocks()` for legacy consumers
- Raw OCR fields remain in `ModuleResult.raw` (100KB limit, redacted)
- `DOCUMENT_IR_SSOT_MODE=dual|ir` (default: dual)

## Alternatives

- **One format per stage**: Rejected — creates translation errors and maintenance burden
- **Raw blocks as SSOT**: Rejected — exposes backend-specific field names

## Consequences

- All new Coordinators receive `DocumentIR`, not raw blocks
- Audit: 11 direct raw-field access violations (all in `pipeline_orchestrator.py` legacy paths — documented for removal)
- 169 legacy blocks call sites documented for migration

## Rollout

`DOCUMENT_IR_SSOT_MODE=dual` runs both paths in parallel. Switch to `ir` when legacy call sites < 10.

## Rollback

Set `DOCUMENT_IR_SSOT_MODE=dual` or remove env var.

## Metrics

- SSOT boundary test: `test_document_ir_ssot_boundaries.py`
- Audit: `scripts/audit_document_ir_boundaries.py`

## Legacy Removal Criteria

- Pipeline Orchestrator no longer accesses `_ocr_scanned_pdf()` or `OCRFixResult`
- All coordinators use DocumentIR
- `document_ir_to_blocks()` removed
