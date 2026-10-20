"""Excel staging and queue admission."""

import uuid
from datetime import datetime

from app.core.time_utils import serialize_utc_datetime, utcnow
from app.features.pipeline_orchestrator import (
    _set_pipeline_store,
)
from app.schemas.import_review import PipelineUploadResponse
from app.services import import_pipeline_service as runtime
from app.services.import_upload_request import UploadRequest
from app.services.staging_storage import StagingObject, async_store_file


async def _stage_excel(request: UploadRequest, pipeline_id: str) -> StagingObject:
    staging_obj = await async_store_file(
        request.file_path,
        original_name=request.filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    await _set_pipeline_store(
        pipeline_id,
        {
            "pipeline_id": pipeline_id,
            "status": "parsing",
            "source_type": "excel",
            "source_file": request.filename,
            "stages": {"upload": {"status": "completed"}},
            "stats": {},
            "errors": [],
            "started_at": serialize_utc_datetime(utcnow()),
            "staging_object_id": staging_obj.object_id,
        },
    )
    return staging_obj


async def start_excel_upload(request: UploadRequest) -> PipelineUploadResponse:
    pipeline_id = (
        f"xl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    await runtime._acquire_pipeline_reservation(pipeline_id, "excel_pipeline")
    try:
        staging_obj = await _stage_excel(request, pipeline_id)
        from app.services.task_queue_worker import enqueue_excel_pipeline

        result = await enqueue_excel_pipeline(
            pipeline_id=pipeline_id,
            staging_object_id=staging_obj.object_id,
            source_file=request.filename,
        )
        if not result:
            await _set_pipeline_store(
                pipeline_id,
                {"status": "failed", "errors": [f"Queue rejected: {result.reason}"]},
            )
            raise ValueError(runtime._queue_rejection_message(result.reason))
        return PipelineUploadResponse(
            pipeline_id=pipeline_id, status="parsing", source_type="excel"
        )
    except Exception:
        await runtime._release_pipeline_reservation(pipeline_id)
        raise
