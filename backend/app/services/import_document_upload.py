"""PDF/TXT page scope, staging and queue admission."""

import logging
import uuid
from datetime import datetime

from app.core.log_context import get_log_context, log_event
from app.core.time_utils import serialize_utc_datetime, utcnow
from app.features.pipeline_orchestrator import (
    _resolve_chunk_size,
    _set_pipeline_store,
    resolve_pdf_page_range,
)
from app.schemas.import_review import PdfPageRangeInfo, PipelineUploadResponse
from app.services import import_pipeline_service as runtime
from app.services.import_pipeline_admission import admit_pipeline_record
from app.services.import_upload_request import UploadRequest
from app.services.staging_storage import StagingObject, async_store_file
from app.services.upload_validator import UploadValidator

logger = logging.getLogger("app.services.import_pipeline_service")


def _resolve_document_range(
    request: UploadRequest, validator: UploadValidator, is_pdf: bool,
) -> PdfPageRangeInfo | None:
    page_range: PdfPageRangeInfo | None = None
    pdf_total_pages = 0
    if is_pdf:
        try:
            import fitz

            with fitz.open(request.file_path) as doc:
                pdf_total_pages = len(doc)
                validator.validate_pdf_pages(pdf_total_pages)
                page_range = resolve_pdf_page_range(
                    pdf_total_pages,
                    page_start=request.page_start,
                    page_end=request.page_end,
                )
        except ValueError:
            raise
        except Exception:
            logger.warning("PDF page count/range validation failed", exc_info=True)
        logger.info(
            "PDF upload accepted: filename=%s total_pages=%s page_start=%s page_end=%s selected=%s",
            request.filename,
            pdf_total_pages,
            request.page_start,
            request.page_end,
            page_range.selected_page_count if page_range else "N/A",
        )
    return page_range


def _document_options(
    request: UploadRequest, page_range: PdfPageRangeInfo | None,
) -> dict:
    options = {
        "enable_ai_repair": request.enable_ai_repair,
        "confidence_threshold": request.confidence_threshold,
        "import_mode": request.import_mode,
    }
    if page_range:
        options["page_start"] = page_range.effective_start
        options["page_end"] = page_range.effective_end
    ctx = get_log_context()
    options["_trace_id"] = ctx.get("trace_id")
    options["_request_id"] = ctx.get("request_id")
    return options


async def _stage_document(
    request: UploadRequest,
    pipeline_id: str,
    source_type: str,
    is_pdf: bool,
    page_range: PdfPageRangeInfo | None,
) -> StagingObject:
    mime = request.content_type or ("application/pdf" if is_pdf else "text/plain")
    staging_obj = await async_store_file(
        request.file_path, original_name=request.filename, mime=mime
    )
    store_data: dict = {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "source_type": source_type,
        "source_file": request.filename,
        "current_stage": "extract",
        "stages": {"upload": {"status": "completed"}},
        "stats": {},
        "errors": [],
        "started_at": serialize_utc_datetime(utcnow()),
        "staging_object_id": staging_obj.object_id,
    }
    if page_range:
        store_data["page_range"] = page_range.model_dump()
    await _set_pipeline_store(pipeline_id, store_data)
    return staging_obj


async def start_document_upload(
    request: UploadRequest, file_size: int, validator: UploadValidator, is_pdf: bool,
) -> PipelineUploadResponse:
    source_type = "pdf" if is_pdf else "txt"
    pipeline_id = (
        f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    page_range = _resolve_document_range(request, validator, is_pdf)
    source_sha256 = await admit_pipeline_record(
        request,
        pipeline_id=pipeline_id,
        source_type=source_type,
        chunk_size=_resolve_chunk_size(),
    )
    options = _document_options(request, page_range)
    await runtime._acquire_pipeline_reservation(pipeline_id, "import_pipeline")
    try:
        staging_obj = await _stage_document(
            request, pipeline_id, source_type, is_pdf, page_range
        )
        from app.services.task_queue_worker import enqueue_import_pipeline

        result = await enqueue_import_pipeline(
            pipeline_id=pipeline_id,
            staging_object_id=staging_obj.object_id,
            source_type=source_type,
            source_file=request.filename,
            subject=request.subject,
            subject_id=request.subject_id,
            options=options,
            created_by=request.created_by,
            source_sha256=source_sha256,
        )
        if not result:
            await _set_pipeline_store(
                pipeline_id,
                {"status": "failed", "errors": [f"Queue rejected: {result.reason}"]},
            )
            raise ValueError(runtime._queue_rejection_message(result.reason))
        _log_accepted(request, pipeline_id, source_type, file_size)
        return PipelineUploadResponse(
            pipeline_id=pipeline_id,
            status="parsing",
            source_type=source_type,
            page_range=page_range,
        )
    except Exception:
        await runtime._release_pipeline_reservation(pipeline_id)
        raise


def _log_accepted(
    request: UploadRequest, pipeline_id: str, source_type: str, file_size: int,
) -> None:
    log_event(
        logger, "import.upload.accepted", pipeline_id=pipeline_id,
        source_type=source_type, source_file=request.filename,
        file_size=file_size, content_type=request.content_type or "-",
    )
