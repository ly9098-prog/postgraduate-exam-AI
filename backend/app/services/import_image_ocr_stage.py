"""Image import OCR stage with status and diagnostics preservation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImageOcrStageRequest:
    pipeline_id: str
    source_file: str
    image_bytes: bytes
    build_runtime_diagnostics: Callable[[], dict]
    run_ocr: Callable[[bytes], Awaitable[dict]]
    clean_text: Callable[[str], str]
    build_diagnostics: Callable[[str, str], dict]
    build_blocks: Callable[..., list[dict]]
    set_status: Callable[..., Awaitable[dict]]


@dataclass(slots=True)
class ImageOcrStageResult:
    raw_ocr_text: str
    cleaned_text: str
    pre_extracted_blocks: list[dict]
    runtime_diagnostics: dict
    diagnostics: dict


async def run_image_ocr_stage(request: ImageOcrStageRequest) -> ImageOcrStageResult:
    """Run one image OCR pass and publish the existing stage diagnostics."""
    logger.info(
        "image OCR started: pipeline_id=%s file=%s",
        request.pipeline_id,
        request.source_file,
    )
    runtime_diagnostics = request.build_runtime_diagnostics()
    await request.set_status(
        status="ocr_running",
        diagnostics={"ocr_runtime": runtime_diagnostics},
        stages={"upload": {"status": "completed"}, "ocr": {"status": "running"}},
    )
    ocr_result = await request.run_ocr(request.image_bytes)
    raw_ocr_text = str(ocr_result.get("text") or "")
    cleaned_text = request.clean_text(raw_ocr_text)
    blocks = request.build_blocks(
        image_bytes=request.image_bytes,
        cleaned_text=cleaned_text,
        ocr_result=ocr_result,
    )
    diagnostics = request.build_diagnostics(raw_ocr_text, cleaned_text)
    diagnostics.update(
        {
            "execution_backend": runtime_diagnostics.get("execution_backend"),
            "box_count": len(blocks[0].get("boxes") or []),
            "engine_fingerprint": ocr_result.get("engine_fingerprint", ""),
        }
    )
    if not cleaned_text:
        await _fail_empty_result(request, runtime_diagnostics, diagnostics)
        raise ValueError("图片 OCR 未识别到可导入文本")

    logger.info(_completion_log(request, diagnostics))
    await request.set_status(
        status="parsing",
        raw_text_preview=cleaned_text[:500],
        stats={"ocr": diagnostics},
        diagnostics={
            "ocr_runtime": runtime_diagnostics,
            "ocr_raw_text": raw_ocr_text[:1000],
            "ocr_cleaned_text": cleaned_text[:1000],
            "failure_reason": None,
        },
        stages={"upload": {"status": "completed"}, "ocr": {"status": "completed"}},
    )
    return ImageOcrStageResult(
        raw_ocr_text,
        cleaned_text,
        blocks,
        runtime_diagnostics,
        diagnostics,
    )


async def _fail_empty_result(
    request: ImageOcrStageRequest,
    runtime_diagnostics: dict,
    diagnostics: dict,
) -> None:
    await request.set_status(
        status="failed",
        stats={"ocr": diagnostics},
        diagnostics={
            "ocr_runtime": runtime_diagnostics,
            "failure_reason": "ocr_empty_text",
        },
        errors=["ocr_empty_text"],
        stages={
            "upload": {"status": "completed"},
            "ocr": {"status": "failed", "error": "ocr_empty_text"},
        },
    )


def _completion_log(request: ImageOcrStageRequest, diagnostics: dict) -> str:
    return (
        "image OCR completed: pipeline_id=%s raw_chars=%d cleaned_chars=%d "
        "raw_lines=%d cleaned_lines=%d"
    ) % (
        request.pipeline_id,
        diagnostics["raw_text_length"],
        diagnostics["cleaned_text_length"],
        diagnostics["raw_line_count"],
        diagnostics["cleaned_line_count"],
    )
