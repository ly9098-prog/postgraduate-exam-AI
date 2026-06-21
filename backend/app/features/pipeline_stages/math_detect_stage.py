"""Math formula detection stage — rule engine + optional formula screenshot.

Extracted from ``pipeline_orchestrator.py:_run_math_detect`` (P5-2).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.features.math_import_profile import (
    apply_math_risk_flags,
    is_math_candidate,
)
from app.features.pipeline_stages._helpers import _count_risk_flags

logger = logging.getLogger(__name__)


async def run_math_detect_stage(
    questions: list[dict],
    *,
    pipeline_id: str = "",
    page_image_refs: dict[int, str] | None = None,
) -> dict:
    """Detect math candidates and apply formula risk flags.

    Pure rule engine — no AI calls. When ``page_image_refs`` is available,
    performs real formula screenshots and uploads to storage backend.

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
            math_segment: dict = {
                "type": "math_image",
                "url": None,
                "alt": "公式截图（暂未生成）",
                "source_page": q.get("page_start") or 1,
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
    if page_image_refs and questions:
        from app.services.storage_backend import get_storage

        virtual_import_id = hashlib.md5(pipeline_id.encode()).hexdigest()[:8]

        crop_warnings: list[str] = []
        for q in questions:
            segments = list(q.get("segments") or [])
            updated = False
            for seg in segments:
                if seg.get("type") != "math_image":
                    continue
                if seg.get("url") is not None:
                    continue
                source_page = seg.get("source_page")
                if not source_page:
                    continue
                page_path = page_image_refs.get(source_page)
                if not page_path:
                    continue

                try:
                    png_bytes = Path(page_path).read_bytes()

                    content_hash = hashlib.md5(png_bytes).hexdigest()[:8]
                    month = datetime.now().strftime("%Y%m")
                    filename = f"page_{source_page}_{content_hash}.png"

                    storage = get_storage()
                    url = await storage.upload(f"{month}/{virtual_import_id}_{filename}", png_bytes)

                    seg["url"] = url
                    seg["alt"] = "公式截图"
                    updated = True
                    crop_warnings.append(f"math_image generated for page {source_page}")
                except Exception as e:
                    logger.warning("公式截图失败 import=%s page=%s: %s",
                                   pipeline_id, source_page, e)
                    seg["crop_failed"] = True
                    seg["alt"] = "公式截图裁剪失败"
                    risk_flags = list(q.get("risk_flags") or [])
                    if "math_image_crop_failed" not in risk_flags:
                        risk_flags.append("math_image_crop_failed")
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
