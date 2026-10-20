"""Image upload validation, staging and queue admission."""

import logging
from datetime import datetime

from app.core.config import settings
from app.core.log_context import get_log_context, log_event
from app.schemas.import_review import PipelineUploadResponse
from app.services import import_pipeline_service as runtime
from app.services.import_upload_request import UploadRequest
from app.services.staging_storage import StagingObject, async_store_file

logger = logging.getLogger("app.services.import_pipeline_service")


def _prepare_image(request: UploadRequest) -> tuple[str, str, int, int, str]:
    if (
        request.content_type
        and request.content_type not in runtime._IMAGE_CONTENT_TYPES
    ):
        raise ValueError("图片 Content-Type 不支持")
    if not settings.OCR_ENABLED:
        raise ValueError("图片 OCR 功能未启用")
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
    from app.core.ocr_isolation import local_paddleocr_available

    if detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT and (
        not local_paddleocr_available()
    ):
        raise ValueError("OCR 依赖未安装：paddleocr")
    image_width, image_height, image_format = runtime._validate_image_path(
        request.file_path
    )
    image_hash = runtime._sha256_of_file(request.file_path)
    pipeline_id = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image_hash[:8]}"
    return (pipeline_id, image_hash, image_width, image_height, image_format)


async def _stage_image(
    request: UploadRequest,
    pipeline_id: str,
    image_hash: str,
    image_width: int,
    image_height: int,
    image_format: str,
    file_size: int,
) -> tuple[StagingObject, dict]:
    staging_obj = await async_store_file(
        request.file_path,
        original_name=request.filename,
        mime=request.content_type or "image/png",
    )
    options = {
        "enable_ai_repair": request.enable_ai_repair,
        "confidence_threshold": request.confidence_threshold,
        "image_hash": image_hash,
        "image_fast_mode": request.image_fast_mode,
    }
    _ctx = get_log_context()
    options["_trace_id"] = _ctx.get("trace_id")
    options["_request_id"] = _ctx.get("request_id")
    await runtime._set_image_pipeline_status(
        pipeline_id,
        status="queued",
        stats={
            "image_bytes": file_size,
            "image_width": image_width,
            "image_height": image_height,
            "image_format": image_format,
            "staging_object_id": staging_obj.object_id,
        },
        stages={"upload": {"status": "completed"}, "ocr": {"status": "pending"}},
    )
    return (staging_obj, options)


async def start_image_upload(
    request: UploadRequest, file_size: int,
) -> PipelineUploadResponse:
    pipeline_id, image_hash, image_width, image_height, image_format = _prepare_image(
        request
    )
    await runtime._acquire_pipeline_reservation(pipeline_id, "image_pipeline")
    try:
        staging_obj, options = await _stage_image(
            request,
            pipeline_id,
            image_hash,
            image_width,
            image_height,
            image_format,
            file_size,
        )
        from app.services.task_queue_worker import enqueue_image_pipeline

        result = await enqueue_image_pipeline(
            pipeline_id=pipeline_id,
            staging_object_id=staging_obj.object_id,
            source_file=request.filename,
            subject=request.subject,
            subject_id=request.subject_id,
            options=options,
        )
        if not result:
            await runtime._set_image_pipeline_status(
                pipeline_id,
                status="failed",
                errors=[f"Queue rejected: {result.reason}"],
            )
            raise ValueError(runtime._queue_rejection_message(result.reason))
        log_event(
            logger,
            "import.upload.accepted",
            pipeline_id=pipeline_id,
            source_type="image",
            source_file=request.filename,
            file_size=file_size,
            content_type=request.content_type or "-",
        )
        return PipelineUploadResponse(
            pipeline_id=pipeline_id, status="queued", source_type="image"
        )
    except Exception:
        await runtime._release_pipeline_reservation(pipeline_id)
        raise
