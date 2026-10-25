"""Image-import completion projection shared by the background executor."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImageCompletionRequest:
    pipeline_id: str
    result: dict
    cleaned_text: str
    raw_ocr_text: str
    ocr_diagnostics: dict
    runtime_diagnostics: dict
    classify_result: Callable[[dict, str], str | None]


def finalize_image_pipeline_result(request: ImageCompletionRequest) -> tuple[dict, str]:
    result = request.result
    status = "completed" if result.get("status") == "completed" else "failed"
    failure_reason = request.classify_result(result, request.cleaned_text)
    if status == "completed" and not result.get("batch_id"):
        status = "failed"
        failure_reason = failure_reason or "no_review_batch_created"
        result.setdefault("errors", []).append("OCR 文本未生成待审核批次")
    if result.get("batch_id"):
        logger.info(
            "image review created: pipeline_id=%s batch_id=%s count=%s",
            request.pipeline_id,
            result.get("batch_id"),
            result.get("stats", {}).get("to_review", 0),
        )
    logger.info(
        "image pipeline completed: pipeline_id=%s status=%s",
        request.pipeline_id,
        status,
    )
    return _project_result(request, status, failure_reason), status


def _project_result(
    request: ImageCompletionRequest, status: str, failure_reason: str | None
) -> dict[str, Any]:
    result = request.result
    result["pipeline_id"] = request.pipeline_id
    result["status"] = status
    result["raw_text_preview"] = request.cleaned_text[:500]
    result["finished_at"] = _finished_at()
    result.setdefault("stats", {})["ocr"] = request.ocr_diagnostics
    result["diagnostics"] = {
        **result.get("diagnostics", {}),
        "ocr_runtime": request.runtime_diagnostics,
        "ocr_raw_text": request.raw_ocr_text[:1000],
        "ocr_cleaned_text": request.cleaned_text[:1000],
        "failure_reason": failure_reason,
    }
    if status == "completed" and result.get("batch_id"):
        result["question_count"] = result.get("stats", {}).get("to_review", 0)
    return result


def _finished_at() -> str:
    from app.core.time_utils import serialize_utc_datetime, utcnow

    return serialize_utc_datetime(utcnow())
