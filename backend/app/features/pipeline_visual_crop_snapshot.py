"""Best-effort source snapshot publication after visual segment projection."""

from __future__ import annotations

from typing import Any

from app.features.pipeline_visual_crop_state import VisualCropState


async def publish_question_snapshot(state: VisualCropState, q: dict, stem: str) -> None:
    try:
        page = q.get("page_start") or 1
        page_path = state.page_image_refs.get(page) if state.page_image_refs else None
        if page_path:
            png_bytes, is_full_page = await read_snapshot(q, page_path)
            if png_bytes and len(png_bytes) > 0:
                content_hash = state.hashlib.md5(png_bytes).hexdigest()[:12]
                filename = f"{state.virtual_import_id}_snapshot_p{page}_{content_hash}.png"
                snapshot_url = await state.storage.upload(
                    f"{state.month}/snapshots/{filename}", png_bytes
                )
                if "parsed_content" not in q:
                    q["parsed_content"] = {"text": stem}
                if isinstance(q["parsed_content"], dict):
                    q["parsed_content"]["source_snapshot_url"] = snapshot_url
                    q["parsed_content"]["source_snapshot_full_page"] = is_full_page
    except Exception as e:
        state.logger.warning(
            "source_snapshot failed import=%s page=%s: %s",
            state.pipeline.pipeline_id,
            page,
            e,
        )
        flags = list(q.get("risk_flags") or [])
        if "source_snapshot_failed" not in flags:
            flags.append("source_snapshot_failed")
        q["risk_flags"] = flags


async def read_snapshot(q: dict, page_path: Any) -> tuple[Any, bool]:
    q_bbox = q.get("question_bbox")
    if q_bbox and len(q_bbox) == 4:
        from app.core.executor_registry import get_executor
        from app.services.visual_region_cropper import CoordinateSpace, crop_region

        png_bytes = await get_executor("image").run(
            crop_region,
            page_path,
            tuple(q_bbox),
            coordinate_space=CoordinateSpace.IMAGE_PIXELS,
        )
        is_full_page = False
    else:
        from pathlib import Path

        from app.core.executor_registry import get_executor

        png_bytes = await get_executor("file_io").run(Path(page_path).read_bytes)
        is_full_page = True
    return png_bytes, is_full_page
