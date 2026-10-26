"""VL split rebuild publication and frozen option bindings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_state import SplitState


def remap_vl_registry(
    state: SplitState, old_registry: Any, rebuilt: Any, *, ports: Callable[[str], Any]
) -> None:
    """Remap old frozen bindings and report lost/preserved bindings."""
    remap_result = ports("_remap_frozen_registry_vl_rebuild")(old_registry, rebuilt)
    state.frozen_option_registry = remap_result.get("registry", {})
    binding_lost_qs = remap_result.get("binding_lost_questions", [])
    if binding_lost_qs:
        ports("logger").warning(
            "[FREEZE] VL rebuild: %d questions with binding_lost: %s",
            ports("len")(binding_lost_qs),
            binding_lost_qs,
        )
    if state.frozen_option_registry:
        preserved = ports("sum")(
            (
                1
                for q in state.frozen_option_registry.values()
                if not ports("isinstance")(q, ports("list"))
                or not ports("any")(
                    (
                        ports("getattr")(e, "binding_status", "") == "binding_lost"
                        for e in q
                    )
                )
            )
        )
        ports("logger").info(
            "[VL-REBUILD] preserved frozen registry: %d questions with bindings",
            preserved,
        )


def publish_vl_rebuild(
    state: SplitState, rebuilt: Any, *, ports: Callable[[str], Any]
) -> None:
    """Publish rebuilt blocks before remapping bindings and warning."""
    state.split_blocks = rebuilt
    old_registry = state.frozen_option_registry
    state.split_mode = "standard"
    state.layout_result = {}
    if old_registry:
        remap_vl_registry(state, old_registry, rebuilt, ports=ports)
    else:
        state.frozen_option_registry = None
    state.warnings.append(
        f"vl_rebuild: restructured {ports('len')(rebuilt)} blocks via PaddleOCR-VL"
    )


def rebuild_split_input(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Rebuild only with both inputs; preserve unavailable and missing fallbacks."""
    if state.split_mode == "vl_rebuild":
        file_path = state.keyword_arguments.get("file_path")
        vl_config = state.keyword_arguments.get("vision_config")
        if file_path and vl_config:
            ports("logger").info(
                "VL_REBUILD: restructuring blocks via PaddleOCR-VL (source=%s, confidence=%.2f, opt_failed=%s)",
                state.keyword_arguments.get("source_type", "unknown"),
                state.layout_result.get("layout_confidence", 1.0),
                state.layout_result.get("option_detection_failed", False),
            )
            rebuilt = state.pipeline._run_vl_rebuild_blocks(
                file_path,
                state.normalized_blocks,
                vl_config,
                original_raw_text=state.keyword_arguments.get("_original_raw_text", ""),
            )
            if rebuilt:
                publish_vl_rebuild(state, rebuilt, ports=ports)
            else:
                state.split_mode = "layout_enhanced"
                state.warnings.append(
                    "vl_rebuild: PaddleOCR-VL restructuring unavailable, falling back to layout_enhanced"
                )
        else:
            state.split_mode = "layout_enhanced"
            state.warnings.append(
                "vl_rebuild: file_path or vl_config missing, falling back to layout_enhanced"
            )
