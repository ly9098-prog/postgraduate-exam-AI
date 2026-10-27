"""Compose region cropping and source snapshot publication for one stage."""

from __future__ import annotations

from typing import Any

from app.features.pipeline_visual_crop_regions import project_question_regions
from app.features.pipeline_visual_crop_snapshot import publish_question_snapshot
from app.features.pipeline_visual_crop_state import VisualCropState


async def run_visual_region_crop(
    pipeline: Any,
    questions: list[dict],
    page_image_refs: dict | None,
    *,
    namespace: dict,
) -> dict:
    import hashlib
    import logging
    from datetime import datetime

    logger = logging.getLogger(namespace["__name__"])
    if not page_image_refs:
        return mark_missing_page_images(questions)
    from app.services.storage_backend import get_storage
    from app.services.visual_region_cropper import crop_and_upload_region
    from app.services.visual_region_types import VisualRegion

    storage = get_storage()
    virtual_import_id = hashlib.md5(pipeline.pipeline_id.encode()).hexdigest()[:8]
    month = datetime.now().strftime("%Y%m")
    crop_warnings: list[str] = []
    state = VisualCropState(
        pipeline,
        page_image_refs,
        storage,
        virtual_import_id,
        month,
        hashlib,
        VisualRegion,
        crop_and_upload_region,
        logger,
        crop_warnings,
    )
    for q in questions:
        stem = await project_question_regions(state, q)
        await publish_question_snapshot(state, q, stem)
    return {"questions": questions, "warnings": crop_warnings}


def mark_missing_page_images(questions: list[dict]) -> dict:
    for q in questions:
        flags = list(q.get("risk_flags") or [])
        if "source_snapshot_failed" not in flags:
            flags.append("source_snapshot_failed")
        q["risk_flags"] = flags
    return {
        "questions": questions,
        "warnings": ["visual_region_crop: no page images"],
    }
