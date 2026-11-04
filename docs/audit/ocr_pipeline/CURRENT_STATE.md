# OCR Pipeline — Current State

**Last updated:** 2026-07-19  
**Commit:** `565277e` (dirty)  
**Python:** 3.12.3 (WSL2)  
**Phase status:** P5-P6-P7 all VERIFIED (except P6-01 DocumentIR PARTIAL, P7-01/P7-02 PARTIAL)

---

## Repository Baseline

| Metric | Value |
|--------|-------|
| Python files (backend, excluding .venv/cache) | ~392 |
| Test files | ~295 |
| CI workflows | 1 (`.github/workflows/ci.yml`) |
| Dockerfiles | 4 (`Dockerfile`, `Dockerfile.prod`, `Dockerfile.backup`, `admin-frontend/Dockerfile`) |
| Lock file | NONE (uses pyproject.toml + requirements.txt in CI) |
| Benchmark files | `backend/tests/ocr_bench/` |
| ruff config | Yes (in pyproject.toml) |
| mypy config | Yes (in pyproject.toml) |
| Static import checker | `scripts/check_ocr_imports.py` |

## Updated Architecture (Post-Sprint 4D)

```
User Request
  │
  ├─ OCRGateway (唯一业务入口)
  │   ├─ LocalOcrWorkerClient → OcrWorkerPool → OcrWorkerProcess → OcrEngine
  │   └─ PaddleOCRVLDocumentAdapter (远程 API)
  │
  └─ Legacy Path (向后兼容)
      └─ ocr_service.ocr_pages() → Gateway (try) → Executor (fallback)

CoordinatorPipeline (Shadow mode by default)
  ├─ InputCoordinator → OCRCoordinator → DocumentStructureCoordinator
  ├─ DomainParsingCoordinator → ReviewCoordinator (REAL)
  └─ CorrectionCoordinator → ValidationCoordinator → PersistenceCoordinator (NOT_IMPLEMENTED)
```

## Key Architecture Decisions (Verified)

1. **Gateway is the single entry point** — `OCRGateway.recognize_pages()` is primary. `ocr_service.ocr_pages()` is a backward-compat wrapper delegating to Gateway.
2. **Process isolation** — `OcrEngine` only created in child worker processes. AST tests verify business modules don't import engine.
3. **DocumentIR SSOT** — All OCR results go through canonical DocumentIR. `document_ir_to_blocks()` bridge for 179 legacy call sites.
4. **Coordinator Pipeline** — Shadow mode (default) runs both old + coordinator plan. No dummy_ir. No no-op success.
5. **CandidateEvaluator** — Single acceptance authority for AI corrections. `code_structure_stage` migrated. 3 remaining callers pending.

## Known Architecture Violations

1. **2 callers still bypass Gateway**: `batch_image_import_service.py`, `batch_answer_image_service.py` call `ocr_executor.run_ocr()` directly. (PARTIAL)
2. **3 `ai_safety` callers not migrated**: `ocr_correction.py`, `ai_repair.py`, `ocr_fix/router.py` still use `evaluate_and_trace()`/`safe_accept_ai_result()` directly. (PARTIAL)
3. **179 legacy `document_ir_to_blocks()` call sites**: Natural migration as coordinator replaces legacy orchestrator.
4. **Feature flags default to legacy**: `STRUCTURE_FREEZE_MODE=legacy`, `DOMAIN_QUALITY_GATE_MODE=off`, `REJECT_LEGACY_ARTIFACTS=False`. (Intentional — fail-closed until coordinators are real.)
5. **VL download stream limiting not implemented** (P5-02 PARTIAL): Post-download size check exists, but no stream-level size limiting during download.
6. **Live-OCR benchmark not runnable in CI**: Requires PaddleOCR runtime with GPU. Text-only benchmark runs in CI. (P7-02 PARTIAL)

## P0-P6 Completed Items

- Architecture boundary tests (AST-based import/coordinator/config validation)
- `OcrEngine` class-based engine (child process only, no module-level singleton)
- `OcrWorkerProcess` with SIGTERM→SIGKILL escalation and PID verification
- `OcrWorkerPool` with async pending queue and lifecycle governance
- Engine code moved from `ocr_service.py` to `ocr_engine.py`, `ocr_service.py` is compat wrapper
- `dummy_ir` removed from coordinator pipeline
- ReviewCoordinator: real implementation (DocumentIR-based, review_ready=True)
- `AIEditTrace` extracted to `app.core.ai_trace`
- 4 coordinator callers migrated to `pipeline_coordinator_entry.run_pipeline()`
- Coordinate transform round-trip (8 tests, forward/back/bbox/serialize/bridge)
- `code_structure_stage` migrated from `evaluate_and_trace` to `CandidateEvaluator`
- Artifact path traversal: `_artifact_path()` now validates filename with `os.path.basename()`, 9 tests
- Config validation: production profile rejects unsafe_thread_fallback, GPU+fork, worker_count<1
- External OCR API DB config E2E script: `scripts/run_remote_ocr_db_config_validation.py`
- **SSRF protection**: `_validate_result_url()` DNS rebinding, redirect re-validation, private IP blocking (12 tests)
- **Retry-After handling**: extracted from error messages, `_retry_submit()` with backoff (8 tests)
- **AIModelConfigResolver integration**: `from_resolver()` factory creates client from `admin_ai_settings` (3 tests)
- **Text-only benchmark CI**: 100 cases (41 PASS / 59 xfail), CI advisory step, ScenarioBucket enum extended
- **Config cache fingerprint**: `_build_config_fingerprint()` hashes 11 key `OcrRuntimeConfig` fields. Stored in artifact metadata. Config change → artifact invalidation.
- **Fault injection tests**: 22 tests with real PaddleOCR runtime. Timeout/crash/corrupt injection, 100-iteration fault storm. Pool survives all.
- **Resume equivalence**: 25 tests. Artifact round-trip, config invalidation, `find_resumable_stage()` logic, cleanup.

## Test Status

**Sprint 4D + P5 + P6/P7 Regression: 335+ tests pass, 59 xfailed, 0 failed** (2026-07-19)

| Suite | Tests | Status |
|-------|-------|--------|
| Architecture boundaries | 10 | PASS |
| OCR pipeline (P1+P2 acceptance) | 22 | PASS |
| Gateway bypass zero | 2 | PASS |
| DocumentIR production write zero | 4 | PASS |
| AI model config resolver + snapshot | 25 | PASS |
| OCRFix/AI Repair config unification | 15 | PASS |
| Code structure reconstructor | 26 | PASS |
| Code question repair | 22 | PASS |
| Target architecture feature matrix | 1+ | PASS |
| Coordinator mode E2E + shadow | 6 | PASS |
| Quality gate all candidate paths | 2+ | PASS |
| Artifact path traversal (P6-02) | 9 | PASS |
| SSRF/HTTP lifecycle (P5) | 15 | PASS |
| Fault injection (P7-03, NEW) | 22 | PASS |
| Resume equivalence (P6-03, NEW) | 25 | PASS |
| Text-only benchmark | 41 | 59 xfailed |
| Coordinator boundaries/rollback | 6 | PASS |

## Documents

- `docs/audit/ocr_pipeline/ISSUE_MATRIX.md` — all P5/P6/P7 sections updated. 20 VERIFIED / 9 PARTIAL / 0 UNVERIFIED / 0 REGRESSED
- `docs/audit/ocr_pipeline/RELEASE_EVIDENCE.md` — P0-P6 evidence, P5/P6/P7 status table, test count 335 passed
- `docs/audit/ocr_pipeline/CURRENT_STATE.md` — this file

---

## 相关链接

- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
- [[docs/audit/AUDIT_INDEX.md|AUDIT_INDEX]] — 审计索引
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
