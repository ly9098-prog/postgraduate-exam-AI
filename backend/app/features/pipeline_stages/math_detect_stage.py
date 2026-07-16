"""Math formula detection stage — rule engine + optional formula screenshot.

Extracted from ``pipeline_orchestrator.py:_run_math_detect`` (P5-2).

Key fix: math_image segments MUST have a valid bbox before cropping.
When bbox is None, the region is marked requires_review with risk flag
math_image_bbox_missing — no full-page upload is performed.
"""

from __future__ import annotations

import logging
from typing import Any

from app.features.math_import_profile import (
    apply_math_risk_flags,
    is_math_candidate,
)
from app.features.pipeline_stages._helpers import _count_risk_flags
from app.services.visual_region_cropper import crop_region
from app.services.visual_region_types import CoordinateSpace, contains_visual_reference

logger = logging.getLogger(__name__)


async def run_math_detect_stage(
    questions: list[dict],
    *,
    pipeline_id: str = "",
    page_image_refs: dict[int, str] | None = None,
) -> dict:
    """Detect math candidates and apply formula risk flags.

    Pure rule engine — no AI calls. When ``page_image_refs`` is available,
    performs real formula screenshots (with bbox validation) and uploads to
    storage backend.

    Important:
        - Never upload full-page images as formula screenshots.
        - When bbox is None, mark requires_review=True instead.
        - Uses crop_from_page_ref which validates bbox coordinates.

    Returns:
        dict with ``questions``, ``warnings``, ``risk_flag_counts`` keys.
    """
    if not questions:
        return {"questions": questions, "warnings": ["math_detect: empty questions"]}

    warnings: list[str] = []
    math_count = 0
    excluded_count = 0

    for q in questions:
        diagnosis = is_math_candidate(q)
        if diagnosis["excluded_by"]:
            excluded_count += 1
            continue
        if not diagnosis["is_math"]:
            continue

        math_count += 1
        flags = list(q.get("risk_flags") or [])
        new_flags = apply_math_risk_flags(q, diagnosis)
        for f in new_flags:
            if f not in flags:
                flags.append(f)

        stem = q.get("stem") or q.get("parsed_content", {}).get("text") or ""
        analysis = q.get("analysis") or ""
        full_text = f"{stem} {analysis}"

        segments: list[dict] = list(q.get("segments") or [])
        if diagnosis["has_complex_formula"] or diagnosis.get("low_confidence"):
            source_page = q.get("page_start") or 1
            has_visual_ref = contains_visual_reference(full_text)
            math_segment: dict = {
                "type": "math_image",
                "url": None,
                "alt": "公式截图（暂未生成）",
                "source_page": source_page,
                "bbox": None,
                "confidence": 0.5,
                "requires_review": True,
            }
            segments.append(math_segment)
            if diagnosis["has_complex_formula"] and "complex_formula_requires_review" not in flags:
                flags.append("complex_formula_requires_review")

        if segments:
            q["segments"] = segments
            q["parsed_content"] = {
                **(q.get("parsed_content") or {}),
                "render_mode": "segments",
                "segments": segments,
            }

        if flags:
            q["risk_flags"] = flags

    if math_count:
        warnings.append(f"math_detect: {math_count} math candidates flagged")
    if excluded_count:
        warnings.append(f"math_detect: {excluded_count} code/408 questions excluded")

    # P2-3: when page_image_refs available, perform real formula screenshots
    #        with strict bbox validation
    if page_image_refs and questions:
        crop_warnings: list[str] = []
        for q in questions:
            segments = list(q.get("segments") or [])
            updated = False
            risk_flags = list(q.get("risk_flags") or [])
            for seg in segments:
                if seg.get("type") != "math_image":
                    continue
                if seg.get("url") is not None:
                    continue

                source_page = seg.get("source_page")
                bbox = seg.get("bbox")
                if not source_page:
                    continue
                page_path = page_image_refs.get(source_page)
                if not page_path:
                    continue

                # CRITICAL FIX: Only crop when bbox is valid.
                # Never upload full-page image as formula screenshot.
                if bbox is None or not _is_valid_bbox(bbox):
                    seg["requires_review"] = True
                    seg["alt"] = "公式截图（bbox 缺失，无法自动裁剪）"
                    if "math_image_bbox_missing" not in risk_flags:
                        risk_flags.append("math_image_bbox_missing")
                    updated = True
                    crop_warnings.append(
                        f"math_image skipped (no bbox) for page {source_page}"
                    )
                    continue

                try:
                    # Crop using the valid bbox — produces a region, not full page
                    png_bytes = crop_region(
                        page_path,
                        tuple(bbox),
                        coordinate_space=CoordinateSpace.PDF_POINTS,
                    )

                    from app.services.storage_backend import get_storage
                    import hashlib
                    from datetime import datetime

                    content_hash = hashlib.md5(png_bytes).hexdigest()[:12]
                    month = datetime.now().strftime("%Y%m")
                    virtual_import_id = hashlib.md5(pipeline_id.encode()).hexdigest()[:8]
                    filename = f"{virtual_import_id}_p{source_page}_{content_hash}.png"

                    storage = get_storage()
                    url = await storage.upload(f"{month}/{filename}", png_bytes)

                    seg["url"] = url
                    seg["alt"] = "公式截图"
                    seg["requires_review"] = False  # clear since we have a real crop
                    updated = True
                    crop_warnings.append(
                        f"math_image cropped for page {source_page} bbox={bbox}"
                    )
                except Exception as e:
                    logger.warning(
                        "公式截图裁剪失败 import=%s page=%s: %s",
                        pipeline_id, source_page, e,
                    )
                    seg["crop_failed"] = True
                    seg["alt"] = "公式截图裁剪失败"
                    seg["requires_review"] = True
                    if "math_image_crop_failed" not in risk_flags:
                        risk_flags.append("math_image_crop_failed")
                    updated = True

            if risk_flags != q.get("risk_flags", []):
                q["risk_flags"] = risk_flags
            if updated:
                q["segments"] = segments
                q["parsed_content"] = {
                    **(q.get("parsed_content") or {}),
                    "render_mode": "segments",
                    "segments": segments,
                }

        if crop_warnings:
            warnings.append(f"math_image: {len(crop_warnings)} formula screenshots generated")

    return {
        "questions": questions,
        "warnings": warnings,
        "risk_flag_counts": _count_risk_flags(questions),
    }


def _is_valid_bbox(bbox: list | tuple | None) -> bool:
    """Check if bbox is a valid 4-element list with x1>x0 and y1>y0."""
    if not bbox or len(bbox) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (ValueError, TypeError):
        return False
    if x1 <= x0 or y1 <= y0:
        return False
    if any(v < 0 or v > 1_000_000 for v in (x0, y0, x1, y1)):
        return False
    return True
