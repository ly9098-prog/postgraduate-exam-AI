"""Synchronous mode selection and the original ordinary-IR-failure boundary."""

from __future__ import annotations

from app.features.pipeline_freeze_canary import project_canary_freeze
from app.features.pipeline_freeze_dual import project_dual_freeze
from app.features.pipeline_freeze_projection import project_ir_freeze
from app.features.pipeline_freeze_state import FreezeState


def run_structure_freeze_mode(normalized_blocks: list[dict], *, namespace: dict) -> dict:
    state = _load_freeze_inputs(normalized_blocks, namespace=namespace)
    if state.mode == "legacy":
        return state.legacy_result
    state.doc_ir = state.port("_get_blocks_document_ir")(normalized_blocks)
    _attempt_ir_freeze(state)
    if state.mode == "ir":
        return project_ir_freeze(state)
    if state.mode == "ir_canary":
        return project_canary_freeze(state)
    if state.mode == "dual":
        return project_dual_freeze(state)
    state.port("logger").warning(
        "[FREEZE] Unknown freeze_mode=%r, falling back to legacy", state.mode
    )
    return state.legacy_result


def _load_freeze_inputs(normalized_blocks: list[dict], *, namespace: dict) -> FreezeState:
    state = FreezeState(namespace, None, None, None, None)
    state.mode = state.port("_get_structure_freeze_mode")()
    state.legacy_result = state.port("run_structure_freeze_stage")(normalized_blocks)
    state.legacy_registry = state.legacy_result.get("frozen_option_registry", {})
    return state


def _attempt_ir_freeze(state: FreezeState) -> None:
    if state.doc_ir is not None:
        try:
            from app.features.pipeline_stages.structure_freeze_stage import (
                freeze_from_document_ir as _ir_freeze,
            )
            from app.features.pipeline_stages.structure_freeze_stage import (
                freeze_registry_to_block_format as _ir_to_legacy,
            )

            state.ir_to_legacy = _ir_to_legacy
            state.ir_result = _ir_freeze(state.doc_ir)
            state.ir_registry_raw = state.ir_result.get("frozen_option_registry", {})
        except state.port("Exception") as exc:
            state.port("logger").warning("[FREEZE] IR freeze failed, falling back: %s", exc)
            state.ir_result = {"warnings": [f"ir_freeze_error: {exc}"]}
