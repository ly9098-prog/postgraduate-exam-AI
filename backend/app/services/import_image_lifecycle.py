"""Image-import background lifecycle with injected persistence ports."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.services.import_image_completion import ImageCompletionRequest
from app.services.import_image_stages import (
    ImageCompletionPersistence,
    ImageFailurePersistence,
    ImagePipelineExecutionRequest,
    execute_image_pipeline_stages,
    persist_image_completion,
    persist_image_failure,
)
from app.utils.sentry_utils import capture_exception


@dataclass(slots=True)
class ImageLifecycleRequest:
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
    update_record: Callable[..., Awaitable[None]]
    run_pipeline: Callable[..., Awaitable[dict]]
    clean_text: Callable[[str], str]
    build_runtime_diagnostics: Callable[[], dict]
    run_ocr: Callable[[bytes], Awaitable[dict]]
    build_diagnostics: Callable[[str, str], dict]
    build_blocks: Callable[..., list[dict]]
    set_status: Callable[..., Awaitable[dict]]
    set_stage_tags: Callable[[str, str], None]
    apply_policy: Callable[[dict, bool], dict]
    finalize_result: Callable[..., tuple[dict, str]]
    get_status: Callable[[str], Awaitable[dict | None]]
    fail_pipeline: Callable[[str, str], Awaitable[None]]
    log_event: Callable[..., None]
    classify_result: Callable[[dict, str], str | None]
    capture_exception: Callable[..., None] = capture_exception


async def run_image_import_lifecycle(request: ImageLifecycleRequest) -> None:
    try:
        execution = await execute_image_pipeline_stages(
            ImagePipelineExecutionRequest(
                pipeline_id=request.pipeline_id,
                image_path=request.image_path,
                source_file=request.source_file,
                subject=request.subject,
                subject_id=request.subject_id,
                options=request.options,
                created_by=request.created_by,
                logger=request.logger,
                async_session=request.async_session,
                ensure_record=request.ensure_record,
                run_pipeline=request.run_pipeline,
                clean_text=request.clean_text,
                build_runtime_diagnostics=request.build_runtime_diagnostics,
                run_ocr=request.run_ocr,
                build_diagnostics=request.build_diagnostics,
                build_blocks=request.build_blocks,
                set_status=request.set_status,
                set_stage_tags=request.set_stage_tags,
                apply_policy=request.apply_policy,
            )
        )
        result, status = request.finalize_result(
            ImageCompletionRequest(
                pipeline_id=request.pipeline_id,
                result=execution.result,
                cleaned_text=execution.raw_text,
                raw_ocr_text=execution.raw_ocr_text,
                ocr_diagnostics=execution.ocr_diagnostics,
                runtime_diagnostics=execution.runtime_diagnostics,
                classify_result=request.classify_result,
            )
        )
        await persist_image_completion(
            ImageCompletionPersistence(
                pipeline_id=request.pipeline_id,
                source_file=request.source_file,
                result=result,
                status=status,
                async_session=request.async_session,
                get_status=request.get_status,
                set_status=request.set_status,
                update_record=request.update_record,
                log_event=request.log_event,
            )
        )
    except Exception as exc:
        _record_image_failure(request, exc)
        raise


def _record_image_failure(request: ImageLifecycleRequest, exc: Exception) -> None:
    request.logger.exception(
        "image pipeline failed: pipeline_id=%s file=%s",
        request.pipeline_id,
        request.source_file,
    )
    request.log_event(
        request.logger,
        "import.background.error",
        level="error",
        pipeline_id=request.pipeline_id,
        source_type="image",
        source_file=request.source_file,
        error_type=type(exc).__name__,
        error_message=str(exc)[:300],
    )
    request.capture_exception(
        exc,
        tags={
            "pipeline_id": request.pipeline_id,
            "source_file": request.source_file,
            "stage": "ocr",
        },
    )


async def persist_image_import_failure(
    request: ImageLifecycleRequest, exc: Exception
) -> None:
    await persist_image_failure(
        ImageFailurePersistence(
            pipeline_id=request.pipeline_id,
            source_file=request.source_file,
            exc=exc,
            async_session=request.async_session,
            fail_pipeline=request.fail_pipeline,
            update_record=request.update_record,
        )
    )
