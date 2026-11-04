# ADR-0004: OCR Gateway

**Status:** Accepted (2026-07-18)

## Context

OCR routing logic was embedded in `pipeline_orchestrator.py` and `ocr_service.py` as `if/elif` chains based on backend names. Adapter selection, circuit breaker checks, and fallback logic were scattered.

## Decision

Introduce `OCRGateway` as the single production entry point for page recognition:

- Routes by capability (not backend name)
- Reuses existing `OcrAdapter`, `AdapterRegistry`, `AdapterSelector`
- Unified timeout (120s), retry, and fallback chain
- Shadow mode: computes routing decision without calling backends
- `OCR_GATEWAY_MODE=legacy|shadow|gateway` (default: legacy)

## Alternatives

- **Keep if/elif routing**: Rejected — each new backend requires editing the orchestrator
- **Single backend only**: Rejected — need local + remote OCR

## Consequences

- No module calls `adapter.process()` directly — always through Gateway
- Shadow mode verifies routing correctness without double OCR cost
- Fallback chain is deterministic (paddleocr → paddleocr-vl → rule_fallback)

## Rollout

Default `legacy`. Set to `shadow` to verify routing. Set to `gateway` for production.

## Rollback

Set `OCR_GATEWAY_MODE=legacy`.

## Metrics

- Shadow tests: `test_ocr_gateway_shadow.py` verifies no double calls
- Gateway tests: `test_ocr_gateway.py` verifies routing

## Legacy Removal Criteria

When all pipeline calls go through OCRGateway and `OCR_GATEWAY_MODE=gateway`.

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
