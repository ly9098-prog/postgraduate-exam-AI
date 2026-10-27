"""Carry IR bindings to the splitter and prevent a second substring injection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_state import SplitState


def _uses_ir_binding(arguments: dict) -> bool:
    return arguments.get("freeze_mode") in ("ir", "ir_canary")


def initialize_split_binding(state: SplitState) -> None:
    if not _uses_ir_binding(state.keyword_arguments):
        return
    diagnostics = {"enabled": True, "accepted_questions": 0, "reasons": []}
    binding = {
        "plan": state.keyword_arguments.get("freeze_block_binding"),
        "diagnostics": diagnostics,
    }
    state.frozen_option_registry = {}
    state.extra_data["freeze_binding_diagnostics"] = diagnostics
    state.ir_freeze_binding = binding


def execute_split_questions(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    if state.ir_freeze_binding is not None:
        state.ir_freeze_binding["input_transformed"] = state.freeze_input_changed
    arguments = (
        {"freeze_block_binding": state.ir_freeze_binding}
        if state.ir_freeze_binding is not None
        else {}
    )
    state.raw_questions = ports("split_questions")(
        state.split_blocks,
        structure=state.structure,
        gap_tolerance=state.gap_tolerance,
        import_mode=state.import_mode_str,
        layout_result=state.layout_result if state.layout_result.get("option_groups") else None,
        split_mode=state.split_mode,
        frozen_option_registry=state.frozen_option_registry,
        **arguments,
    )


def finalize_split_binding(state: SplitState) -> None:
    if state.ir_freeze_binding is not None:
        diagnostics = state.ir_freeze_binding["diagnostics"]
        diagnostics["parsed_accepted_questions"] = diagnostics["accepted_questions"]
        diagnostics["accepted_questions"] = sum(
            1 for question in state.raw_questions if question.get("is_frozen")
        )
