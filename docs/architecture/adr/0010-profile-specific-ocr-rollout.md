# ADR-0010: Profile-Specific OCR Rollout

**Status:** Accepted (2026-07-18)

## Context

`OCRGateway` mode switching previously applied globally — a single `OCR_GATEWAY_MODE` controlled both local and cloud profiles. This means enabling gateway mode for `CLOUD_API` would also affect `LOCAL_IMPORT`, creating cross-profile interference.

## Decision

Split `OCR_GATEWAY_MODE` into `LOCAL_OCR_GATEWAY_MODE` and `CLOUD_OCR_GATEWAY_MODE` for independent rollout:

- `OCRGateway` accepts a `DeploymentProfile` parameter and enforces profile-specific fallback policies
- `LOCAL_IMPORT` fallback chain: `[paddleocr → paddleocr-vl → rule_fallback]` (full local capability)
- `CLOUD_API` fallback chain: `[remote_api → review]` — never calls local PaddleOCR, even as fallback
- Each profile independently selects `legacy|shadow|gateway` mode
- Mode is evaluated at pipeline creation and frozen in the execution context

## Alternatives

- **Single global mode with conditional checks**: Rejected — cross-profile interference, complex branching
- **Separate Gateway instances per profile**: Rejected — code duplication, diverging behavior over time

## Consequences

- Both profiles can be rolled out independently — cloud can run `gateway` while local stays `legacy`
- Cloud production is safe from accidentally invoking local PaddleOCR (OOM risk eliminated)
- Two env vars instead of one, but each has a clear scope
- Fallback chains are explicit and auditable per profile

## Compatibility

- Existing `OCR_GATEWAY_MODE` env var is deprecated but honored as a fallback if profile-specific vars are unset
- No API contract changes. OCR results are identical across modes for the same input.
- Pipeline audit trail records which mode was active for each run.

## Rollout

Set `CLOUD_OCR_GATEWAY_MODE=gateway` on cloud server. Keep `LOCAL_OCR_GATEWAY_MODE=legacy` on local workstation. Shadow mode can be enabled per profile independently.

## Rollback

Set the profile-specific var to `legacy`, or remove it (falls back to deprecated `OCR_GATEWAY_MODE`, which falls back to `legacy`).

## Metrics

- `test_ocr_gateway_profile_isolation.py`: verifies one profile's mode does not affect the other
- `test_ocr_gateway_cloud_fallback.py`: verifies cloud fallback never calls local PaddleOCR
- Gateway decision agreement rate per profile (shadow mode)

## Failure modes

- Profile-specific var typo: fall back to deprecated `OCR_GATEWAY_MODE`, then to `legacy`
- Both profile vars and deprecated var are unset: default to `legacy`
- Cloud profile in `gateway` mode with a failing remote API: falls back to `review` per design, never crashes

## Removal criteria

When all profiles run in `gateway` mode and the deprecated `OCR_GATEWAY_MODE` env var is no longer referenced in code or config.

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
