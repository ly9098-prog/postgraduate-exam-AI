"""Prepare fresh single-pass stages, vision configuration and live inputs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_single_pass_state import SinglePassState


def begin_single_pass(state: SinglePassState, *, ports: Callable[[str], Any]) -> None:
    """Build fresh stages and record start before applying page-range overrides."""
    state.pipeline._build_pipeline()
    state.pass_logger = ports("logging").getLogger("app.pipeline")
    state.started_clock = ports("time").monotonic()
    ports("log_event")(
        state.pass_logger,
        "pipeline.single_pass.start",
        pipeline_id=state.pipeline.pipeline_id,
        source_type=state.request.source_type,
        page_start=state.request.page_start,
        page_end=state.request.page_end,
    )
    if state.request.page_start is not None or state.request.page_end is not None:
        state.options = {
            **state.options,
            "page_start": state.request.page_start,
            "page_end": state.request.page_end,
        }


async def resolve_pass_vision(
    state: SinglePassState, *, ports: Callable[[str], Any]
) -> None:
    """Resolve optional vision configuration; warn on ordinary failures."""
    state.vision_config = None
    if state.request.db is not None:
        from app.services.model_config_resolver import resolve_active_model

        try:
            resolved = await resolve_active_model(state.request.db, feature="vision")
            if resolved and resolved.get("api_key"):
                state.vision_config = resolved
                ports("logger").info(
                    "Vision model configured: %s (provider=%s)",
                    state.vision_config.get("display_name")
                    or state.vision_config.get("model_name", "?"),
                    state.vision_config.get("provider", "?"),
                )
        except ports("Exception") as exc:
            ports("logger").warning("Failed to resolve vision model config: %s", exc)


def prepare_pass_data(state: SinglePassState, *, ports: Callable[[str], Any]) -> None:
    """Build one live stage payload with original shared object references."""
    state.data = {
        "file_content": state.request.file_content,
        "file_path": state.request.file_path,
        "source_type": state.request.source_type,
        "source_file": state.request.source_file,
        "subject": state.request.subject,
        "subject_id": state.request.subject_id,
        "options": state.options,
        "db": state.request.db,
        "vision_config": state.vision_config,
        "import_mode": state.request.shared["import_mode"],
        "strategy": state.request.shared["strategy"],
        "watermark_patterns": state.request.shared["watermark_patterns"],
        "page_images": state.request.page_images,
        "page_image_refs": state.request.page_image_refs,
        "pre_extracted_blocks": state.request.pre_extracted_blocks,
        "raw_blocks": [],
        "normalized_blocks": [],
        "layout_result": {},
        "split_mode": "standard",
        "frozen_option_registry": {},
        "frozen_structures": [],
        "freeze_checksum": "",
        "freeze_mode": "legacy",
        "freeze_ir_warnings": [],
        "freeze_dual_diagnostics": {},
        "frozen_option_registry_ir": {},
        "quality_gate_shadow_records": [],
        "cross_page_links": [],
        "raw_questions": [],
        "matched": [],
        "unmatched": [],
        "questions": [],
    }
    if state.request.shared.get("hash_index") is not None:
        state.data["hash_index"] = state.request.shared["hash_index"]
    if state.request.chunk_seen_hashes is not None:
        state.data["_chunk_seen_hashes"] = state.request.chunk_seen_hashes
    if state.request.chunk_logical_end is not None:
        state.data["_chunk_logical_end"] = state.request.chunk_logical_end
