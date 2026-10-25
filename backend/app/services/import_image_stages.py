"""Image-import checkpoint and OCR/pipeline stage orchestration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.services.import_image_ocr_stage import (
    ImageOcrStageRequest,
    ImageOcrStageResult,
    run_image_ocr_stage,
)


@dataclass(slots=True)
class ImageCompletionPersistence:
    pipeline_id: str
    source_file: str
    result: dict
    status: str
    async_session: Callable[[], Any]
    get_status: Callable[[str], Awaitable[dict | None]]
    set_status: Callable[..., Awaitable[dict]]
    update_record: Callable[..., Awaitable[None]]
    log_event: Callable[..., None]


@dataclass(slots=True)
class ImageStageCheckpointRequest:
    pipeline_id: str
    source_file: str | None
    created_by: str | None
    async_session: Callable[[], Any]
    ensure_record: Callable[..., Awaitable[None]]


@dataclass(slots=True)
class ImageOcrStage:
    image_path: str
    source_file: str
    pipeline_id: str
    read_bytes: Callable[[str], bytes]
    set_stage_tags: Callable[[str, str], None]
    build_runtime_diagnostics: Callable[[], dict]
    run_ocr: Callable[[bytes], Awaitable[dict]]
    clean_text: Callable[[str], str]
    build_diagnostics: Callable[[str, str], dict]
    build_blocks: Callable[..., list[dict]]
    set_status: Callable[..., Awaitable[dict]]


@dataclass(slots=True)
class PreparedImageOcr:
    image_bytes: bytes
    stage_result: ImageOcrStageResult


@dataclass(slots=True)
class ImagePipelineStage:
    pipeline_id: str
    source_file: str
    subject: str | None
    subject_id: int | None
    options: dict
    created_by: str | None
    image_bytes: bytes
    cleaned_text: str
    pre_extracted_blocks: list[dict]
    async_session: Callable[[], Any]
    ensure_record: Callable[..., Awaitable[None]]
    run_pipeline: Callable[..., Awaitable[dict]]


async def ensure_image_checkpoint(request: ImageStageCheckpointRequest) -> None:
    async with request.async_session() as db:
        await request.ensure_record(
            db,
            pipeline_id=request.pipeline_id,
            source_type="image",
            source_file=request.source_file or None,
            total_pages=1,
            chunk_size=1,
            created_by=request.created_by,
            status="processing",
        )


async def run_prepared_image_ocr(stage: ImageOcrStage) -> PreparedImageOcr:
    with open(stage.image_path, "rb") as file_handle:
        image_bytes = file_handle.read()
    stage.set_stage_tags("ocr", "PaddleOCR")
    stage_result = await run_image_ocr_stage(
        ImageOcrStageRequest(
            pipeline_id=stage.pipeline_id,
            source_file=stage.source_file,
            image_bytes=image_bytes,
            build_runtime_diagnostics=stage.build_runtime_diagnostics,
            run_ocr=stage.run_ocr,
            clean_text=stage.clean_text,
            build_diagnostics=stage.build_diagnostics,
            build_blocks=stage.build_blocks,
            set_status=stage.set_status,
        )
    )
    return PreparedImageOcr(image_bytes=image_bytes, stage_result=stage_result)


async def run_image_pipeline_stage(stage: ImagePipelineStage) -> dict:
    async with stage.async_session() as db:
        await stage.ensure_record(
            db,
            pipeline_id=stage.pipeline_id,
            source_type="image",
            source_file=stage.source_file or None,
            total_pages=1,
            chunk_size=1,
            created_by=stage.created_by,
            status="processing",
        )
        return await stage.run_pipeline(
            file_content=stage.cleaned_text.encode("utf-8"),
            source_type="txt",
            source_file=stage.source_file,
            subject=stage.subject,
            subject_id=stage.subject_id,
            options=stage.options,
            db=db,
            page_images={1: stage.image_bytes},
            pre_extracted_blocks=stage.pre_extracted_blocks,
        )


async def persist_image_completion(completion: ImageCompletionPersistence) -> None:
    current = await completion.get_status(completion.pipeline_id) or {}
    completion.result.setdefault(
        "started_at", current.get("started_at", _now_serialized())
    )
    await completion.set_status(completion.pipeline_id, **completion.result)
    async with completion.async_session() as db:
        await completion.update_record(
            db,
            completion.pipeline_id,
            status=completion.status,
            error_message=completion.result.get("diagnostics", {}).get("failure_reason")
            if completion.status == "failed"
            else None,
            finished=True,
        )
    completion.log_event(
        logging.getLogger("app.services.import_pipeline_service"),
        "import.background.finish",
        pipeline_id=completion.pipeline_id,
        source_type="image",
        source_file=completion.source_file,
        status=completion.status,
    )


def _now_serialized() -> str:
    from app.core.time_utils import serialize_utc_datetime, utcnow

    return serialize_utc_datetime(utcnow())
