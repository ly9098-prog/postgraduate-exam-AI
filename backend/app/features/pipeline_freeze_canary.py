"""Canary policy after the attempted IR freeze, with original short circuits."""

from __future__ import annotations

from app.features.pipeline_freeze_projection import (
    project_canary_fallback,
    project_canary_success,
)
from app.features.pipeline_freeze_state import FreezeState


def project_canary_freeze(state: FreezeState) -> dict:
    from app.features.ocr_canary import (
        check_ir_canary_failover,
        is_canary_globally_disabled,
        is_ir_canary_disabled,
    )

    if is_canary_globally_disabled() or is_ir_canary_disabled():
        state.port("logger").info(
            "[FREEZE] IR canary: disabled via kill-switch, falling back to legacy"
        )
        return state.legacy_result
    comparison = state.port("_compare_freeze_results")(
        state.legacy_result,
        state.ir_result,
        state.legacy_registry,
        state.ir_registry_raw,
    )
    should_fallback, failover_reasons = check_ir_canary_failover(
        doc_ir_available=state.doc_ir is not None,
        ir_registry_nonempty=state.port("bool")(state.ir_registry_raw),
        legacy_registry_nonempty=state.port("bool")(state.legacy_registry),
        option_key_match=comparison.get("option_key_match", False),
        binding_lost_count=comparison.get("binding_lost_count", 0),
        exception_occurred=state.port("bool")(
            state.port("any")(
                w.startswith("ir_freeze_error") for w in state.ir_result.get("warnings", [])
            )
        ),
    )
    if should_fallback or not state.ir_registry_raw:
        return project_canary_fallback(state, failover_reasons)
    return project_canary_success(state, comparison)
