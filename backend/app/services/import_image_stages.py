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
class ImageFailurePersistence:
    pipeline_id: str
    source_file: str
    exc: Exception
    async_session: Callable[[], Any]
    fail_pipeline: Callable[[str, str], Awaitable[None]]
    update_record: Callable[..., Awaitable[None]]


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
class ImagePipelineExecutionResult:
    result: dict
    raw_text: str
    raw_ocr_text: str
    ocr_diagnostics: dict
    runtime_diagnostics: dict


@dataclass(slots=True)
class ImagePipelineExecutionRequest:
    pipeline_id: str
    image_path: str
    source_file: str
    subject: str | None
    subject_id: int | None
    options: dict
    created_by: str | None
    logger: logging.Logger
    async_session: Callable[[], Any]
    ensure_record: Callable[..., Awaitable[None]]
    run_pipeline: Callable[..., Awaitable[dict]]
    clean_text: Callable[[str], str]
    build_runtime_diagnostics: Callable[[], dict]
    run_ocr: Callable[[bytes], Awaitable[dict]]
    build_diagnostics: Callable[[str, str], dict]
    build_blocks: Callable[..., list[dict]]
    set_status: Callable[..., Awaitable[dict]]
    set_stage_tags: Callable[[str, str], None]
    apply_policy: Callable[[dict, bool], dict]


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


async def execute_image_pipeline_stages(
    request: ImagePipelineExecutionRequest,
) -> ImagePipelineExecutionResult:
    ocr_stage = await run_prepared_image_ocr(
        ImageOcrStage(
            pipeline_id=request.pipeline_id,
            image_path=request.image_path,
            source_file=request.source_file,
            read_bytes=lambda _path: b"",
            set_stage_tags=request.set_stage_tags,
            build_runtime_diagnostics=request.build_runtime_diagnostics,
            run_ocr=request.run_ocr,
            clean_text=request.clean_text,
            build_diagnostics=request.build_diagnostics,
            build_blocks=request.build_blocks,
            set_status=request.set_status,
        )
    )
    request.logger.info("image pipeline started: pipeline_id=%s", request.pipeline_id)
    pipeline_options = request.apply_policy(
        request.options,
        enabled=bool(request.options.get("image_fast_mode", True)),
    )
    result = await run_image_pipeline_stage(
        ImagePipelineStage(
            pipeline_id=request.pipeline_id,
            source_file=request.source_file,
            subject=request.subject,
            subject_id=request.subject_id,
            options=pipeline_options,
            created_by=request.created_by,
            image_bytes=ocr_stage.image_bytes,
            cleaned_text=ocr_stage.stage_result.cleaned_text,
            pre_extracted_blocks=ocr_stage.stage_result.pre_extracted_blocks,
            async_session=request.async_session,
            ensure_record=request.ensure_record,
            run_pipeline=request.run_pipeline,
        )
    )
    stage_result = ocr_stage.stage_result
    return ImagePipelineExecutionResult(
        result=result,
        raw_text=stage_result.cleaned_text,
        raw_ocr_text=stage_result.raw_ocr_text,
        ocr_diagnostics=stage_result.diagnostics,
        runtime_diagnostics=stage_result.runtime_diagnostics,
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


async def persist_image_failure(failure: ImageFailurePersistence) -> None:
    await failure.fail_pipeline(failure.pipeline_id, str(failure.exc))
    async with failure.async_session() as db:
        await failure.update_record(
            db,
            failure.pipeline_id,
            status="failed",
            error_message=str(failure.exc)[:4000],
            finished=True,
        )


def _now_serialized() -> str:
    from app.core.time_utils import serialize_utc_datetime, utcnow

    return serialize_utc_datetime(utcnow())
