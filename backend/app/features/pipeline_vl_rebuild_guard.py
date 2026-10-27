"""VL rebuild guard with historical live ports and outer try ownership."""

from __future__ import annotations

from app.features.pipeline_vl_rebuild_state import VlRebuildState


def rebuild_vl_input_guard(state: VlRebuildState) -> bool:
    """Reject absent configuration and unsupported files outside the fallback scope."""
    if not state.values["vl_config"]:
        state.port("logger").warning("VL_REBUILD: no vision config available")
        return False
    file_lower = state.values["file_path"].lower()
    state.is_pdf = file_lower.endswith(".pdf")
    state.is_image = state.port("any")(
        (file_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg"))
    )
    if not state.is_pdf and (not state.is_image):
        state.port("logger").warning(
            "VL_REBUILD: unsupported file type: %s", state.values["file_path"]
        )
        return False
    return True


def rebuild_vl_config_guard(state: VlRebuildState) -> bool:
    """Resolve configuration inside the original ordinary-error fallback scope."""
    state.api_token = (
        state.values["vl_config"].get("api_key")
        or state.values["vl_config"].get("paddleocr_vl_api_token")
        or ""
    )
    state.base_url = (
        state.values["vl_config"].get("api_base_url")
        or "https://paddleocr.aistudio-app.com"
    )
    state.model = state.values["vl_config"].get("model_name") or "PaddleOCR-VL-1.6"
    if not state.api_token:
        state.port("logger").warning("VL_REBUILD: PaddleOCR-VL not configured")
        return False
    return True
