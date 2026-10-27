"""Mode-specific registry and warning projections, preserving local imports."""

from __future__ import annotations

from typing import Any

from app.features.freeze_source_binding import (
    bind_legacy_result,
    source_binding_fields,
)
from app.features.pipeline_freeze_state import FreezeState


def project_ir_freeze(state: FreezeState) -> dict:
    if not state.ir_registry_raw:
        return _project_empty_ir(state)
    from app.features.pipeline_stages.structure_freeze_stage import _freeze_deep_freeze
    from app.features.pipeline_stages.structure_freeze_stage import (
        freeze_registry_to_block_format as _ir_to_legacy,
    )

    legacy_compat = _freeze_deep_freeze(_ir_to_legacy(state.ir_registry_raw))
    return {
        "frozen_option_registry": legacy_compat,
        "frozen_option_registry_ir": state.ir_registry_raw,
        "frozen_structures": state.ir_result.get("frozen_structures", []),
        "freeze_checksum": state.ir_result.get("freeze_checksum", ""),
        "freeze_mode": "ir",
        "freeze_ir_warnings": state.ir_result.get("warnings", []),
        "warnings": state.port("list")(
            state.port("dict").fromkeys(
                state.legacy_result.get("warnings", []) + state.ir_result.get("warnings", [])
            )
        ),
        **source_binding_fields(state.doc_ir, legacy_compat),
    }


def _project_empty_ir(state: FreezeState) -> dict:
    state.port("logger").warning("[FREEZE] IR mode: registry empty, falling back to legacy")
    result = state.port("dict")(state.legacy_result)
    ir_warns = state.ir_result.get("warnings", [])
    result["warnings"] = state.port("list")(
        state.port("dict").fromkeys(
            result.get("warnings", []) + ir_warns + ["freeze_ir_empty_fallback_legacy"]
        )
    )
    result["freeze_mode"] = "ir"
    result["freeze_ir_warnings"] = ir_warns
    result["freeze_ir_empty"] = True
    return _bind_legacy_fallback(state, result)


def project_canary_fallback(state: FreezeState, failover_reasons: Any) -> dict:
    state.port("logger").warning(
        "[FREEZE] IR canary: fallback to legacy, reasons=%s", failover_reasons
    )
    result = {**state.legacy_result}
    result["freeze_mode"] = "ir_canary"
    result["freeze_canary_fallback"] = True
    result["freeze_canary_fallback_reasons"] = failover_reasons
    result["freeze_ir_warnings"] = state.ir_result.get("warnings", [])
    result["warnings"] = state.port("list")(
        state.port("dict").fromkeys(
            result.get("warnings", [])
            + state.ir_result.get("warnings", [])
            + ["freeze_ir_canary_fallback_legacy"]
        )
    )
    return _bind_legacy_fallback(state, result)


def _bind_legacy_fallback(state: FreezeState, result: dict) -> dict:
    return bind_legacy_result(state.doc_ir, result)


def project_canary_success(state: FreezeState, comparison: Any) -> dict:
    from app.features.pipeline_stages.structure_freeze_stage import _freeze_deep_freeze

    legacy_compat = state.converter()(state.ir_registry_raw)
    return {
        "frozen_option_registry": _freeze_deep_freeze(legacy_compat),
        "frozen_option_registry_ir": state.ir_registry_raw,
        "frozen_structures": state.ir_result.get("frozen_structures", []),
        "freeze_checksum": state.ir_result.get("freeze_checksum", ""),
        "freeze_mode": "ir_canary",
        "freeze_canary_fallback": False,
        "freeze_dual_diagnostics": comparison,
        "freeze_ir_warnings": state.ir_result.get("warnings", []),
        "warnings": state.port("list")(
            state.port("dict").fromkeys(
                state.legacy_result.get("warnings", []) + state.ir_result.get("warnings", [])
            )
        ),
        **source_binding_fields(state.doc_ir, legacy_compat),
    }
