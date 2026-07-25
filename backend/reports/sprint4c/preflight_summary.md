# Sprint 4C — Preflight Summary

Generated: 2026-07-18

## Production Flow Audit

| Item | Status |
|------|--------|
| Public Import API entry | `app/api/v1/imports.py` → `import_pipeline_service` |
| Admin Import API entry | `app/api/v1/admin_imports.py` → `import_pipeline_service` |
| Import service target | `pipeline_orchestrator` (old) |
| CoordinatorPipeline in production | **NOT WIRED** — only test calls |
| Orchestrator is main entry | Yes |
| Direct orchestrator import | Yes |

## Orchestrator Responsibilities

| Responsibility | Call Sites |
|---------------|------------|
| document_ir_construction | 7 |
| persistence | 6 |
| storage_delete | 2 |
| page_rendering | 2 |
| ai_repair | 1 |
| question_splitting | 1 |
| review_artifact | 1 |

**Line count**: 6409 total, 5220 code lines

## Gateway Bypass Paths

| Category | Count |
|----------|-------|
| Violations (outside adapter boundary) | 18 |
| Allowed (adapter boundary) | 7 |

Main violation sources: `ocr_fix/deepseek_adapter.py`, `pipeline_orchestrator.py`, `ocr_correction.py`

## Profile Runtime Reachability

| Metric | Value |
|--------|-------|
| Files with unguarded local OCR reachability | 8 |
| Files with profile guard | 3 |

Key files with unguarded patterns: `ocr_service.py`, `ocr_adapter.py`, `batch_image_import_service.py`, `ocr_fix/router.py`

## DocumentIR Legacy Sites

| Category | Count |
|----------|-------|
| Total legacy sites | 49 |
| Production write violations | 13 |
| Production read sites | 10 |
| Adapter internal (legitimate) | 4 |
| Test compat | 22 |

**DOCUMENT_IR_SSOT_MODE=ir ready**: No (13 write violations remain)

## Database Sync

| Metric | Value |
|--------|-------|
| Existing sync implementations | 0 new |
| Sync entry points | `merge_sync_package`, `import_sync_package` |
| Sync protocol unchanged | Yes |

## Environment Requirements for This Sprint

### Can execute in current environment
- [x] Unit tests (all profiles)
- [x] Smoke test
- [x] Architecture audits
- [x] DocumentIR legacy classification
- [x] CI profile matrix script
- [x] ADR creation
- [x] DocumentIR migration (classification complete)

### Requires real hardware / API
- [ ] RTX 3050 Ti 4 GB GPU tests
- [ ] 2C/2G production-equivalent container
- [ ] External OCR API sandbox (real API key)

## Summary

CoordinatorPipeline must be wired into production as shadow mode.
Orchestrator responsibilities should be migrated incrementally.
DocumentIR has 13 production write violations preventing ir mode.
Real GPU, 2C/2G, and external API tests remain environment-dependent.
