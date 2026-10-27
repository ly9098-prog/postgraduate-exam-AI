"""Dual-mode diagnostics and bounded logging with legacy output ownership."""

from __future__ import annotations

from app.features.pipeline_freeze_state import FreezeState


def project_dual_freeze(state: FreezeState) -> dict:
    comparison = state.port("_compare_freeze_results")(
        state.legacy_result,
        state.ir_result,
        state.legacy_registry,
        state.ir_registry_raw,
    )
    state.port("logger").info(
        "[FREEZE-DUAL] legacy=%d opt, ir=%d opt, "
        "key_match=%s, text_match=%s, binding_lost=%d, diffs=%d",
        comparison["legacy_option_count"],
        comparison["ir_option_count"],
        comparison["option_key_match"],
        comparison["option_text_match"],
        comparison["binding_lost_count"],
        comparison["differences_count"],
    )
    if comparison["differences_count"] > 0:
        for diff in comparison["differences"][:10]:
            state.port("logger").info(
                "[FREEZE-DUAL] diff: %s key=%s legacy=%.40s ir=%.40s",
                diff["type"],
                diff.get("option_key", "?"),
                diff.get("legacy_text", ""),
                diff.get("ir_text", ""),
            )
    result = state.port("dict")(state.legacy_result)
    result["freeze_mode"] = "dual"
    result["freeze_dual_diagnostics"] = comparison
    result["freeze_ir_warnings"] = state.ir_result.get("warnings", [])
    return result
