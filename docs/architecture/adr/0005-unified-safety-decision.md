# ADR-0005: Unified Safety Decision

**Status:** Accepted (2026-07-18)

## Context

Safety evaluation was spread across `CandidateEvaluator`, `AI Safety`, `Code Integrity`, `Domain Quality Gate`, `Frozen Option Invariants`, and `Cross-page Validation`. Each produced its own result format, and there was no single aggregator producing a final accept/reject/review decision.

## Decision

Introduce `UnifiedSafetyEvaluator` that aggregates all gate evidence into a single `UnifiedSafetyDecision`:

- Each gate provides `SafetyEvidence` (provider, severity, reason_codes, metrics)
- Only `UnifiedSafetyEvaluator` generates the final decision
- Gate exceptions do NOT auto-accept high-risk candidates
- `CancelledError` propagates unmodified
- `UNIFIED_SAFETY_MODE=off|shadow` (default: off)

## Alternatives

- **Keep per-gate decisions**: Rejected — no single call site can answer "is this safe?"
- **Auto-accept on gate error**: Rejected — would accept high-risk candidates silently

## Consequences

- All reason codes use stable string enums
- Same candidate is evaluated once (not once per gate)
- Trace format and latency recording are unified

## Rollout

`UNIFIED_SAFETY_MODE=off` by default (shadow-ready). Switch to `shadow` for equivalence testing.

## Rollback

Set `UNIFIED_SAFETY_MODE=off`.

## Metrics

- Shadow equivalence: `test_unified_safety_shadow_equivalence.py`
- Gate test: `test_unified_safety_evaluator.py`

## Legacy Removal Criteria

When all pipeline decisions go through `UnifiedSafetyEvaluator` and `UNIFIED_SAFETY_MODE=enforce`.
